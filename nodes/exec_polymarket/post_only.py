"""Durable post-only contract/lifecycle evidence. No network or signing.

The share bound is conditional on the CLOB honoring its documented maker-only promise.
An observed violation is permanent stop evidence, not permission to clamp a held position.
"""
from decimal import Decimal

from nodes.risk.flags import raise_flag

POST_ONLY_TERMINAL_GRACE_S = 2.0
REVIEWED_ADDRESSES = {
    "exchange_v2": "0xE111180000d2663C0091e4f400237545B87B996B",
    "neg_risk_exchange_v2": "0xe2222d279d744050d28e00520010520000310F59",
    "collateral": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
    "conditional_tokens": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
}


def reviewed_signing_domain(client):
    """Fail before signing if runtime configuration leaves the audited V2 domain."""
    import importlib.metadata
    from py_clob_client_v2 import config
    from py_clob_client_v2.order_builder import builder
    from py_clob_client_v2.order_utils.model import ctf_exchange_v2_typed_data as domain
    from py_clob_client_v2.order_utils import exchange_order_builder_v2 as exchange_builder
    if importlib.metadata.version("py-clob-client-v2") != "1.1.0" or client.chain_id != 137:
        raise ValueError("unreviewed SDK version or signing chain")
    for module in (domain, exchange_builder):
        if module.CTF_EXCHANGE_V2_DOMAIN_NAME != "Polymarket CTF Exchange" or module.CTF_EXCHANGE_V2_DOMAIN_VERSION != "2":
            raise ValueError("unreviewed EIP-712 domain")
    for runtime in (config.get_contract_config(137), builder.get_contract_config(137)):
        if any(str(getattr(runtime, key, "")).lower() != value.lower() for key, value in REVIEWED_ADDRESSES.items()):
            raise ValueError("unreviewed V2 exchange/collateral/CTF configuration")
    for signer in (getattr(client, "signer", None), getattr(client.builder, "signer", None)):
        if signer is None or signer.get_chain_id() != 137:
            raise ValueError("unreviewed signer chain")
    return config.get_contract_config(137)


POST_ONLY_DDL = """
CREATE TABLE IF NOT EXISTS pm_post_only_orders(
 client_order_id TEXT PRIMARY KEY, venue_order_id TEXT,
 maker_amount TEXT NOT NULL, taker_amount TEXT NOT NULL, wire_json TEXT NOT NULL,
 terminal_proved INTEGER NOT NULL DEFAULT 0, terminal_seen_utc REAL,
 terminal_fingerprint TEXT, violated INTEGER NOT NULL DEFAULT 0,
 cancel_deadline_utc REAL, cancel_attempt_utc REAL);
CREATE UNIQUE INDEX IF NOT EXISTS pm_post_only_venue_order ON pm_post_only_orders(venue_order_id);
CREATE TABLE IF NOT EXISTS pm_post_only_violations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL,
 code TEXT NOT NULL, detail TEXT NOT NULL, seen_utc REAL NOT NULL,
 UNIQUE(client_order_id,code,detail));
CREATE TABLE IF NOT EXISTS pm_post_only_admission(
 slot INTEGER PRIMARY KEY CHECK(slot=1), client_order_id TEXT, claimed_utc REAL);
INSERT OR IGNORE INTO pm_post_only_admission(slot) VALUES(1);
"""


def ensure_post_only_tables(journal):
    journal.store.ensure_ddl(POST_ONLY_DDL)
    # Existing unresolved orders without a stored deadline are immediately cancel-due.
    columns = {row[1] for row in journal.store.con.execute("PRAGMA table_info(pm_post_only_orders)")}
    for column in ("cancel_deadline_utc", "cancel_attempt_utc"):
        if column not in columns:
            journal.store.con.execute(f"ALTER TABLE pm_post_only_orders ADD COLUMN {column} REAL")
    journal.store.con.commit()


def claim_post_only(journal, cid, *, now):
    """Atomic across connections/processes; commit ownership before any signer work."""
    changed = journal.store.con.execute(
        "UPDATE pm_post_only_admission SET client_order_id=?,claimed_utc=? "
        "WHERE slot=1 AND client_order_id IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM pm_post_only_orders WHERE terminal_proved=0 OR violated=1) "
        "AND NOT EXISTS(SELECT 1 FROM orders WHERE venue='polymarket' AND (state='UNCONFIRMED' OR open=1))",
        (cid, now)).rowcount
    journal.store.con.commit()
    return bool(changed)


def release_post_only(journal, cid, *, now, reason):
    """Called only after durable terminal/no-send proof; preserve every prior marker."""
    if not journal.store.con.execute("SELECT 1 FROM pm_post_only_admission WHERE slot=1 AND client_order_id=?", (cid,)).fetchone():
        return
    journal._event(cid, "post_only_admission_release", None, {"reason": reason}, now)
    journal.store.con.execute(
        "UPDATE pm_post_only_admission SET client_order_id=NULL WHERE slot=1 AND client_order_id=?", (cid,))
    journal.store.con.commit()


def post_only_order(journal, venue_order_id):
    row = journal.store.con.execute(
        "SELECT client_order_id,venue_order_id,maker_amount,taker_amount,terminal_proved,violated "
        "FROM pm_post_only_orders WHERE venue_order_id=?", (venue_order_id,)).fetchone()
    return None if row is None else dict(zip(
        ("client_order_id", "venue_order_id", "maker_amount", "taker_amount", "terminal_proved", "violated"), row))


def record_post_only_violation(journal, cid, code, detail, *, now, kill=None):
    # Retry the live latch even when the evidence already exists or the DB write fails.
    if kill is not None:
        try:
            kill.latch("live", f"{code}: {cid} {detail}")
        except Exception as exc:
            detail += f"; kill latch failed: {type(exc).__name__}"
    journal.store.con.execute("UPDATE pm_post_only_orders SET violated=1 WHERE client_order_id=?", (cid,))
    changed = journal.store.con.execute(
        "INSERT OR IGNORE INTO pm_post_only_violations(client_order_id,code,detail,seen_utc) VALUES(?,?,?,?)",
        (cid, code, detail, now)).rowcount
    journal.store.con.commit()
    if changed:
        raise_flag(journal.store, code, f"{cid}: {detail}", now=now)


def check_post_only_quantity(journal, venue_order_id, quantity, *, now, kill=None):
    marker = post_only_order(journal, venue_order_id)
    if marker is None:
        return True
    q = Decimal(str(quantity))
    cap = Decimal(marker["taker_amount"]) / 1_000_000
    if marker["terminal_proved"] and q.is_finite():
        order = journal.get(marker["client_order_id"])
        if order and q > Decimal(str(order.get("filled_contracts") or 0)):
            journal.store.con.execute("UPDATE pm_post_only_orders SET terminal_proved=0 WHERE client_order_id=?",
                                      (marker["client_order_id"],))
            record_post_only_violation(journal, marker["client_order_id"], "POST_ONLY_ROLE_VIOLATION",
                                       "new fill contradicts an authoritatively closed maker lifecycle", now=now, kill=kill)
            return False
    if not q.is_finite() or q < 0 or q > cap:
        record_post_only_violation(journal, marker["client_order_id"], "ORDER_OVERFILL",
                                   f"post-only signed cap {cap}; authoritative quantity {quantity}", now=now, kill=kill)
        return False
    return not bool(marker["violated"])

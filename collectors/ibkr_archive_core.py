#!/usr/bin/env python3
"""Pure mechanics and SQLite storage for the Janus IBKR forward archive (Track B, spec L14).

Design rules (see research/exec/2026-08-18_ibkr-forward-archive/spec.yaml):
  * every network call goes through lib.ibkr_readonly.IBKRReadOnlyClient (the caller passes it in);
  * nothing here can express an order, and nothing here persists account/session/user/MAC data:
    rows are built ONLY from an explicit allowlist of quote/identity keys (`quote_row`);
  * a poll slot is the denominator: every second produces exactly one `polls` row, so a missing
    observation is always an explicit reason-coded row, never an absent one;
  * IBKR snapshot responses are DELTAS -- a conid whose response carries no quote field is
    "no message" (row_kind NO_CHANGE), which is distinct from "no change in price" and from
    "poll failed" (row_kind GAP with a reason);
  * prices here are futures/index/option prices, NOT probabilities, so lib.schema.Quote is not used.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

COLLECTOR_VERSION = "ibkr-archive/0.1.0"
SPEC_REF = "research/exec/2026-08-18_ibkr-forward-archive/spec.yaml"
DATA_ROOT = Path("/Volumes/Kilos/janus")

# Registered market-data fields (identical to L13): identity + top-of-book + availability.
FIELDS = ("31", "55", "84", "85", "86", "88", "6004", "6008", "6070", "6073", "6119", "6509")
QUOTE_FIELDS = frozenset({"31", "84", "85", "86", "88"})

ROW_KINDS = ("MSG", "NO_CHANGE", "GAP")
GAP_REASONS = frozenset({
    "NO_MESSAGE", "DISCONNECTED", "AUTH_INVALID", "AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED",
    "EXPIRED_CONTRACT", "DELAYED_OR_FROZEN", "MARKET_CLOSED", "UNKNOWN_RESPONSE", "DISK_FLOOR",
    "GATEWAY_ERROR", "GATEWAY_TIMEOUT", "SAFETY_REFUSED", "NOT_SELECTED",
})

# Substrings that must never appear in any persisted text (privacy invariant).
FORBIDDEN_TEXT = re.compile(
    r"acctId|accountId|\bU\d{6,}\b|session|cookie|\bMAC\b|hardware|userId|USERID|username",
    re.IGNORECASE,
)

_ET = ZoneInfo("America/New_York")
_CT = ZoneInfo("America/Chicago")


def as_num(value: Any) -> float | None:
    """IBKR quote strings may carry a status prefix letter ('C123.4' = closed, 'H' = halted)."""
    if value in (None, ""):
        return None
    text = str(value).replace(",", "").strip()
    text = re.sub(r"^[A-Za-z]", "", text)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def availability_status(code: Any) -> str:
    first = str(code or "")[:1]
    return {
        "R": "HFT_READY", "D": "BLOCKED_DELAYED", "Z": "BLOCKED_FROZEN",
        "Y": "BLOCKED_FROZEN_DELAYED", "N": "BLOCKED_NOT_SUBSCRIBED", "O": "BLOCKED_AGREEMENT",
    }.get(first, "BLOCKED_AVAILABILITY_UNKNOWN")


def conid_of(row: dict[str, Any]) -> int | None:
    for key in ("conid", "conId", "conidEx", "6008"):
        value = row.get(key)
        if value is None:
            continue
        match = re.match(r"^(\d+)", str(value))
        if match:
            return int(match.group(1))
    return None


def quote_row(raw: dict[str, Any], recv_ts: float) -> dict[str, Any]:
    """Project one snapshot element onto the persisted allowlist. Unknown keys are dropped."""
    updated = raw.get("_updated")
    updated_ms = int(updated) if isinstance(updated, (int, float)) else None
    present = sorted(f for f in QUOTE_FIELDS if f in raw)
    return {
        "recv_ts": recv_ts,
        "ibkr_updated_ms": updated_ms,
        "conid": conid_of(raw),
        "last": as_num(raw.get("31")),
        "bid": as_num(raw.get("84")),
        "ask": as_num(raw.get("86")),
        "bid_size": as_num(raw.get("88")),
        "ask_size": as_num(raw.get("85")),
        "availability_code": (str(raw["6509"])[:8] if raw.get("6509") is not None else None),
        "staleness_ms": (int(recv_ts * 1000) - updated_ms) if updated_ms else None,
        "fields_present": ",".join(present),
        "row_kind": "MSG" if present else "NO_CHANGE",
        "gap_reason": None,
    }


def session_label(ts: float, sec_type: str, root: str | None = None) -> str:
    """Pinned trading-hours label used only to reason-code missingness. Holidays are NOT pinned;
    observed availability is the truth, this is a hint. Times are exchange-local via zoneinfo."""
    t = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    if sec_type == "FUT":
        ct = t.astimezone(_CT)
        # CME Globex: Sun 17:00 CT -> Fri 16:00 CT, daily maintenance 16:00-17:00 CT.
        if ct.weekday() == 5:
            return "CLOSED"
        if ct.weekday() == 6 and ct.hour < 17:
            return "CLOSED"
        if ct.weekday() == 4 and ct.hour >= 16:
            return "CLOSED"
        if ct.hour == 16:
            return "MAINTENANCE"
        return "GLOBEX"
    et = t.astimezone(_ET)
    hm = et.hour * 60 + et.minute
    if et.weekday() >= 5:
        return "CLOSED"
    if 9 * 60 + 30 <= hm < 16 * 60 + 15:
        return "RTH"
    if sec_type in ("OPT", "IND"):
        # CBOE SPX/XSP global trading hours 20:15 -> 09:25 ET (index values are disseminated
        # only during RTH; overnight the index sits at its close).
        if hm >= 20 * 60 + 15 or hm < 9 * 60 + 25:
            return "GTH"
        return "CLOSED"
    return "CLOSED"


def next_slot(now: float, period_s: float = 1.0) -> float:
    return (int(now / period_s) + 1) * period_s


def select_front_future(raw: Any, root: str, today: dt.date) -> dict[str, Any] | None:
    """Earliest unexpired contract for `root` (the L13 rule)."""
    candidates = []
    for row in _dicts(raw):
        conid, expiry = conid_of(row), _expiry(row)
        symbol = str(row.get("symbol") or row.get("ticker") or row.get("underlyingSymbol") or "")
        if conid is None or expiry is None or expiry < today:
            continue
        if symbol and root.upper() != symbol.upper():
            continue
        candidates.append((expiry, conid, row))
    if not candidates:
        return None
    expiry, conid, row = min(candidates, key=lambda item: (item[0], item[1]))
    return {"root": root, "conid": conid, "sec_type": "FUT", "expiry": expiry.strftime("%Y%m%d"),
            "expiry_pinned": 1, "exchange": row.get("exchange") or row.get("listingExchange"),
            "strike": None, "right": None, "underlying_conid": None,
            "selection_rule": "earliest_unexpired_by_root"}


def select_option_expiry(info_raw: Any, now_ts: float) -> dict[str, Any] | None:
    """Among /iserver/secdef/info rows, pick the earliest maturityDate whose 16:15 ET has not
    passed at `now_ts`. Returns conid + pinned expiry, or None."""
    now_et = dt.datetime.fromtimestamp(now_ts, tz=dt.timezone.utc).astimezone(_ET)
    best = None
    for row in _dicts(info_raw):
        conid = conid_of(row)
        expiry = _expiry(row)
        if conid is None or expiry is None:
            continue
        close = dt.datetime.combine(expiry, dt.time(16, 15), tzinfo=_ET)
        if close <= now_et:
            continue
        key = (expiry, conid)
        if best is None or key < best[0]:
            best = (key, row)
    if best is None:
        return None
    (expiry, conid), row = best
    return {"conid": conid, "expiry": expiry.strftime("%Y%m%d"), "expiry_pinned": 1,
            "exchange": row.get("exchange") or row.get("listingExchange"),
            "symbol": row.get("symbol")}


def nearest_strike(strikes_raw: Any, spot: float) -> float | None:
    if not isinstance(strikes_raw, dict):
        return None
    values = []
    for key in ("call", "put"):
        for value in strikes_raw.get(key) or []:
            number = as_num(value)
            if number is not None:
                values.append(number)
    return min(set(values), key=lambda s: (abs(s - spot), s)) if values else None


def forward_from_parity(call_q: dict[str, Any] | None, put_q: dict[str, Any] | None,
                        strike: float) -> float | None:
    """Underlying FORWARD implied by put-call parity: F = K + (C - P), from mids.

    WHY THIS EXISTS. The index feed (CME S&P Indices) was deliberately not bought, so the SPX/XSP
    IND instruments return availability `Z` and a frozen `last`. On 2026-08-19 that frozen print
    read 7693.26 -- the same value as 26 hours earlier, and 1.50 points away from the official
    close L15 measured at 7691.76. Selecting a "near-ATM" strike from a stale, measurably wrong
    number is a silent defect. The option quotes ARE entitled (`RpBd`), so the level can be derived
    from data we actually pay for.

    C - P = e^(-rT)(F - K), so F = K + e^(rT)(C - P). The discount factor is dropped: over the
    near expiries this collector selects, e^(rT) - 1 is order 1e-3 and (C - P) is order a few
    points, so the omitted term is well under one strike increment. That approximation is the
    reason this returns a FORWARD and is labelled as one -- it is NOT spot, and it must never be
    recorded as an index level.

    Returns None unless both sides have a two-sided quote; a one-sided or crossed book gives no
    usable mid, and guessing one would reintroduce exactly the silent-defect problem.
    """
    def mid(q: dict[str, Any] | None) -> float | None:
        if not isinstance(q, dict):
            return None
        bid, ask = as_num(q.get("bid")), as_num(q.get("ask"))
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            return None
        return (bid + ask) / 2.0

    c, p = mid(call_q), mid(put_q)
    if c is None or p is None:
        return None
    return strike + (c - p)


def option_month(search_raw: Any, today: dt.date) -> str | None:
    months = {name: i for i, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
    found: set[str] = set()
    for row in _dicts(search_raw):
        if str(row.get("secType") or "").upper() != "OPT":
            continue
        found.update(re.findall(r"[A-Z]{3}\d{2}", str(row.get("months") or "").upper()))
    eligible = []
    for m in found:
        year, number = 2000 + int(m[3:]), months.get(m[:3])
        if number and (year, number) >= (today.year, today.month):
            eligible.append((year, number, m))
    return min(eligible)[2] if eligible else None


def underlying_conid(search_raw: Any, symbol: str) -> int | None:
    choices = []
    for row in _dicts(search_raw):
        conid = conid_of(row)
        if conid is None:
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "")
        # secType lives inside sections[] on /iserver/secdef/search rows (L13 run-1 lesson).
        section_types = {str(x.get("secType") or "").upper()
                         for x in (row.get("sections") or []) if isinstance(x, dict)}
        sec = str(row.get("secType") or row.get("assetClass") or "")
        is_index = sec.upper() == "IND" or "IND" in section_types
        choices.append(((sym.upper() == symbol.upper(), is_index), conid))
    if not choices:
        return None
    return max(choices, key=lambda item: (item[0], -item[1]))[1]


def alarm_decision(*, free_bytes: int, disk_floor_bytes: int, last_ok_poll_age_s: float,
                   max_poll_age_s: float, poll_success_rate: float, min_poll_success_rate: float,
                   authenticated: bool) -> list[str]:
    """Pure alarm comparator, fired both live and against fake targets in tests."""
    out = []
    if free_bytes < disk_floor_bytes:
        out.append("disk_floor")
    if last_ok_poll_age_s > max_poll_age_s:
        out.append("liveness")
    if poll_success_rate < min_poll_success_rate:
        out.append("capture_gap")
    if not authenticated:
        out.append("auth")
    return out


def _dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _expiry(row: dict[str, Any]) -> dt.date | None:
    for key in ("maturityDate", "expirationDate", "expiry", "lastTradingDay", "6073"):
        value = row.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip()
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(text[:10], fmt).date()
            except ValueError:
                pass
    return None


class ArchiveStorage:
    """Append-only archive. Never stores account, session, user, hardware, or MAC data."""

    def __init__(self, path: Path | str, *, enforce_data_root: bool = True):
        self.path = Path(path)
        resolved = self.path.resolve()
        if enforce_data_root:
            allowed = DATA_ROOT.resolve()
            if resolved != allowed and allowed not in resolved.parents:
                raise ValueError(f"archive DB must live under {allowed}, got {resolved}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self._schema()

    def _schema(self) -> None:
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS instruments (
          conid INTEGER NOT NULL, family TEXT NOT NULL, root TEXT NOT NULL, sec_type TEXT NOT NULL,
          exchange TEXT, expiry TEXT, expiry_pinned INTEGER NOT NULL DEFAULT 0, strike REAL,
          "right" TEXT, underlying_conid INTEGER, selection_rule TEXT NOT NULL,
          selected_ts REAL NOT NULL, retired_ts REAL, spec_ref TEXT NOT NULL,
          collector_version TEXT NOT NULL,
          PRIMARY KEY (conid, selected_ts));
        CREATE TABLE IF NOT EXISTS contract_roll (
          family TEXT NOT NULL, slot TEXT NOT NULL, old_conid INTEGER, new_conid INTEGER NOT NULL,
          roll_ts REAL NOT NULL, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS polls (
          slot_ts INTEGER PRIMARY KEY, sent_ts REAL, recv_ts REAL, ok INTEGER NOT NULL,
          n_conids INTEGER NOT NULL, latency_ms INTEGER, reason TEXT, authenticated INTEGER);
        CREATE TABLE IF NOT EXISTS quotes (
          recv_ts REAL NOT NULL, ibkr_updated_ms INTEGER, conid INTEGER NOT NULL, row_kind TEXT NOT NULL,
          gap_reason TEXT, session_label TEXT, last REAL, bid REAL, ask REAL, bid_size REAL,
          ask_size REAL, availability_code TEXT, staleness_ms INTEGER, fields_present TEXT,
          PRIMARY KEY (conid, recv_ts));
        CREATE INDEX IF NOT EXISTS quotes_recv ON quotes(recv_ts);
        CREATE TABLE IF NOT EXISTS health (
          timestamp REAL NOT NULL, component TEXT NOT NULL, status TEXT NOT NULL, detail TEXT);
        """)
        self.con.commit()

    # -- writes ------------------------------------------------------------------------------
    @staticmethod
    def _check_text(*values: Any) -> None:
        for value in values:
            if isinstance(value, str) and FORBIDDEN_TEXT.search(value):
                raise ValueError("refusing to persist text matching the privacy denylist")

    def add_instrument(self, family: str, spec: dict[str, Any], selected_ts: float) -> None:
        self._check_text(*[v for v in spec.values() if isinstance(v, str)])
        self.con.execute(
            "INSERT OR IGNORE INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (spec["conid"], family, spec["root"], spec["sec_type"], spec.get("exchange"),
             spec.get("expiry"), int(spec.get("expiry_pinned") or 0), spec.get("strike"),
             spec.get("right"), spec.get("underlying_conid"), spec["selection_rule"], selected_ts,
             None, SPEC_REF, COLLECTOR_VERSION))

    def retire_instrument(self, conid: int, retired_ts: float) -> None:
        self.con.execute("UPDATE instruments SET retired_ts=? WHERE conid=? AND retired_ts IS NULL",
                         (retired_ts, conid))

    def roll(self, family: str, slot: str, old_conid: int | None, new_conid: int, ts: float,
             reason: str) -> None:
        self.con.execute("INSERT INTO contract_roll VALUES (?,?,?,?,?,?)",
                         (family, slot, old_conid, new_conid, ts, reason))

    def poll(self, slot_ts: int, *, sent_ts: float | None, recv_ts: float | None, ok: bool,
             n_conids: int, latency_ms: int | None, reason: str | None, authenticated: bool) -> None:
        if reason is not None and reason not in GAP_REASONS:
            raise ValueError(f"unknown poll reason {reason}")
        self.con.execute("INSERT OR IGNORE INTO polls VALUES (?,?,?,?,?,?,?,?)",
                         (slot_ts, sent_ts, recv_ts, int(ok), n_conids, latency_ms, reason,
                          int(authenticated)))

    def quote(self, row: dict[str, Any], session: str) -> None:
        if row["row_kind"] not in ROW_KINDS:
            raise ValueError("bad row_kind")
        if row["row_kind"] == "GAP" and row.get("gap_reason") not in GAP_REASONS:
            raise ValueError("GAP rows need a registered gap_reason")
        self._check_text(row.get("fields_present"), row.get("availability_code"), row.get("gap_reason"))
        self.con.execute(
            "INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["recv_ts"], row.get("ibkr_updated_ms"), row["conid"], row["row_kind"],
             row.get("gap_reason"), session, row.get("last"), row.get("bid"), row.get("ask"),
             row.get("bid_size"), row.get("ask_size"), row.get("availability_code"),
             row.get("staleness_ms"), row.get("fields_present")))

    def gap(self, conid: int, recv_ts: float, reason: str, session: str) -> None:
        self.quote({"recv_ts": recv_ts, "conid": conid, "row_kind": "GAP", "gap_reason": reason},
                   session)

    def health(self, component: str, status: str, detail: str = "", ts: float | None = None) -> None:
        self._check_text(detail)
        self.con.execute("INSERT INTO health VALUES (?,?,?,?)",
                         (time.time() if ts is None else ts, component, status, detail[:1000]))

    # -- reads -------------------------------------------------------------------------------
    def active_instruments(self) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM instruments WHERE retired_ts IS NULL ORDER BY family, root, \"right\""
        ).fetchall()

    def last_ok_poll_ts(self) -> float | None:
        row = self.con.execute("SELECT MAX(recv_ts) FROM polls WHERE ok=1").fetchone()
        return row[0] if row else None

    def poll_success_rate(self, since_ts: float) -> float:
        row = self.con.execute("SELECT SUM(ok), COUNT(*) FROM polls WHERE slot_ts>=?",
                               (int(since_ts),)).fetchone()
        return 1.0 if not row or not row[1] else (row[0] or 0) / row[1]

    def flush(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.commit()
        self.con.close()

    def last_known_level(self, conid: int | None) -> float | None:
        """Most recent non-null `last` archived for a conid, or None."""
        if conid is None:
            return None
        row = self.con.execute(
            "SELECT last FROM quotes WHERE conid=? AND last IS NOT NULL "
            "ORDER BY recv_ts DESC LIMIT 1", (conid,)).fetchone()
        return float(row[0]) if row else None

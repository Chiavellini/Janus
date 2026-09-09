#!/usr/bin/env python3
"""Settle finished executions against each venue's own result, and release their capital.

The coordinator stops at HEDGED (or a failure state) with the reservation held: "capital is
released only by the reconcile node, after both venues reconcile". Until 2026-09-04 nothing in
the lane did that -- the first paper cover (F3) sat HEDGED with its reservation open and the
watchdog said UNRECONCILED_TOO_LONG. This is the pass:

  1. every execution not yet released: venue finality is polled directly, so a stale schedule
     phase cannot leave a paid/removed position looking missing to the guard;
  2. the venues' results: Kalshi `GET /markets/{ticker}` per ticker of the game, Polymarket the
     Gamma event's moneyline market(s) -- label -> YES token, the draw market for three-way;
  3. `reconcile.settle` over the execution's orders (venue, side, filled, average price, fee):
     realized PnL per leg, a `:NO` leg paying when its YES twin loses (either venue);
  4. when every leg is final: release the reservation, move the execution and the opportunity
     to SETTLED -> RECONCILED, write one `execution_settlements` row.

Network in `fetch_results` (a worker thread); state in `apply_settlements` (the loop). Paper
and real executions settle the same way -- the paper venue's fills are the priced books, and
the venue's result is the venue's result either way. Reads no price, claims no edge.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from kernel.schema import ExecutionState as X, OpportunityStatus as S
from nodes.reconcile.reconcile import releasable, settle
from nodes.reconcile.results import PM_GAMMA, fetch_kalshi_market, kalshi_result, polymarket_result

SETTLEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS execution_settlements(
  execution_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, event_id TEXT NOT NULL, league TEXT NOT NULL,
  mode TEXT NOT NULL, settled_ts REAL NOT NULL, kalshi_winner TEXT, polymarket_winner TEXT,
  realized_usd REAL NOT NULL, released INTEGER NOT NULL, legs_json TEXT NOT NULL,
  kind TEXT, hedged_contracts REAL, unhedged_contracts REAL, cover_usd REAL, directional_usd REAL);
"""
VENUE_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS execution_venue_results(
  execution_id TEXT NOT NULL, venue TEXT NOT NULL, winner TEXT NOT NULL, observed_ts REAL NOT NULL,
  PRIMARY KEY(execution_id, venue));
"""
SETTLEMENT_REVISIONS_DDL = """
CREATE TABLE IF NOT EXISTS execution_settlement_revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, revised_ts REAL NOT NULL, execution_id TEXT NOT NULL,
  old_realized_usd REAL NOT NULL, new_realized_usd REAL NOT NULL, reason TEXT NOT NULL,
  old_legs_json TEXT NOT NULL, new_legs_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS execution_settlement_revisions_execution
  ON execution_settlement_revisions(execution_id, revised_ts);
"""
#: Columns added after the table first existed (one production row on 2026-09-05); added in place.
_SETTLEMENT_COLUMNS = {"kind": "TEXT", "hedged_contracts": "REAL", "unhedged_contracts": "REAL",
                       "cover_usd": "REAL", "directional_usd": "REAL"}
#: Hedged, or settled without release (retry), or a HOLDING failure: leg A filled and the hedge did
#: not (fully). The last kind is F3's STOP condition (MIL @ CIN, 2026-09-05): it settles too -- the
#: hedged part as a cover, the remainder as a directional position at the venue's result -- or its
#: reservation is never released and the watchdog alarms forever.
OPEN_STATES = (X.HEDGED.value, X.SETTLED.value, *(x.value for x in X if x.holds_position))


def _ensure_columns(store) -> None:
    have = {r[1] for r in store.con.execute("PRAGMA table_info(execution_settlements)").fetchall()}
    for col, typ in _SETTLEMENT_COLUMNS.items():
        if col not in have:
            store.con.execute(f"ALTER TABLE execution_settlements ADD COLUMN {col} {typ}")


def pending(store, *, now: float | None = None, grace_s: float = 6 * 3600.0) -> list[dict]:
    """Executions still holding capital, with the event spec beside them.

    ``now`` and ``grace_s`` remain accepted for callers written against the old phase/time filter.
    They no longer gate the query: venue result endpoints are authoritative and return open until
    final. At the live cap there are at most six simultaneous events, so polling those held rows
    every settlement pass is both bounded and safer than waiting on a potentially stale schedule
    transition (MIN-DET finalized while its event row still said ``in:co_listed`` on 2026-09-09).
    """
    _ = now, grace_s
    marks = ",".join("?" * len(OPEN_STATES))
    rows = store.con.execute(
        "SELECT e.execution_id, e.opportunity_id, e.event_id, e.league, e.mode, e.state, e.reservation_id, "
        "ev.pm_slug, ev.spec_json, ev.phase, ev.start_utc, e.first_filled, e.hedge_filled, e.first_avg_price, e.hedge_avg_price "
        f"FROM executions e LEFT JOIN events ev ON ev.event_id = e.event_id WHERE e.released = 0 AND e.state IN ({marks})",
        OPEN_STATES).fetchall()
    out = []
    for r in rows:
        if X(r[5]).holds_position and not (r[11] or 0.0) > 0:
            continue            # a holding failure with nothing filled on leg A holds nothing
        spec = json.loads(r[8]) if r[8] else {}
        out.append({"execution_id": r[0], "opportunity_id": r[1], "event_id": r[2], "league": r[3], "mode": r[4],
                    "state": r[5], "reservation_id": r[6], "pm_slug": r[7], "outcomes": spec.get("outcomes") or {},
                    "first_filled": float(r[11] or 0.0), "hedge_filled": float(r[12] or 0.0),
                    "first_avg_price": r[13], "hedge_avg_price": r[14]})
    return out


def _pm_winner(event: dict | None, slug: str, outcomes: dict) -> str | None:
    """The winning YES token per the Gamma event, or None while open. Two shapes: one market
    carrying the event slug (label -> token by position), or per-side markets (`{slug}-x`), the
    one that closed Yes."""
    if not event:
        return None
    markets = [m for m in event.get("markets") or [] if m.get("sportsMarketType") == "moneyline" or m.get("slug") == slug]
    one = next((m for m in markets if m.get("slug") == slug), None)
    if one is not None:
        label = polymarket_result(one)
        if label is None:
            return None
        outs, toks = one.get("outcomes"), one.get("clobTokenIds")
        outs = json.loads(outs) if isinstance(outs, str) else outs
        toks = json.loads(toks) if isinstance(toks, str) else toks
        by = dict(zip(outs or [], toks or []))
        return str(by[label]) if label in by else None
    for m in markets:
        if not str(m.get("slug", "")).startswith(slug + "-"):
            continue
        label = polymarket_result(m)
        toks = m.get("clobTokenIds")
        toks = json.loads(toks) if isinstance(toks, str) else toks
        if label == "Yes" and toks:
            return str(toks[0])
    return None


def fetch_results(items: list[dict], cl, *, fetch_kalshi=fetch_kalshi_market, fetch_event=None) -> dict[str, dict]:
    """The network half: execution_id -> {"kalshi": winning ticker | None, "polymarket": winning token | None}."""
    def _event(slug):
        ev = cl.get_json(f"{PM_GAMMA}/events", params={"slug": slug}, use_cache=False)
        return ev[0] if isinstance(ev, list) and ev else None
    fetch_event = fetch_event or _event
    out: dict[str, dict] = {}
    for it in items:
        winners: dict[str, str | None] = {"kalshi": None, "polymarket": None}
        try:
            tickers = [v["kalshi"] for v in it["outcomes"].values() if v.get("kalshi")]
            results = {tk: kalshi_result(fetch_kalshi(tk, cl)) for tk in tickers}
            yes = [tk for tk, r in results.items() if r == "yes"]
            if len(yes) == 1 and all(r is not None for r in results.values()):
                winners["kalshi"] = yes[0]
        except Exception as exc:  # noqa: BLE001 -- one venue down must not hide the other's final result
            winners["kalshi_error"] = f"{type(exc).__name__}"
        try:
            if it.get("pm_slug"):
                winners["polymarket"] = _pm_winner(fetch_event(it["pm_slug"]), it["pm_slug"], it["outcomes"])
        except Exception as exc:  # noqa: BLE001 -- one venue down must not hide the other's final result
            winners["polymarket_error"] = f"{type(exc).__name__}"
        out[it["execution_id"]] = winners
    return out


def apply_settlements(store, ledger, records, opportunities, items: list[dict], winners: dict[str, dict],
                      *, now: float | None = None, log: Callable[[str], None] = print) -> dict:
    """The state half. Settles every execution both venues have resolved; the rest wait."""
    t = now or time.time()
    store.ensure_ddl(SETTLEMENTS_DDL)
    store.ensure_ddl(VENUE_RESULTS_DDL)
    _ensure_columns(store)
    out = {"settled": 0, "waiting": 0, "unreleasable": 0}
    for it in items:
        w = winners.get(it["execution_id"]) or {}
        execution = store.con.execute(
            "SELECT first_client_id,hedge_client_ids,unwind_client_ids FROM executions WHERE execution_id=?",
            (it["execution_id"],),
        ).fetchone()
        client_ids: list[str] = []
        if execution is not None:
            if execution[0]:
                client_ids.append(execution[0])
            for payload in execution[1:]:
                try:
                    client_ids.extend(str(x) for x in json.loads(payload or "[]"))
                except (TypeError, ValueError):
                    pass
        # Opportunity ids are stable candidate keys and are deliberately reused by retries.
        # Settlement must never include another retry's rejected order (or, worse, its fill).
        if not client_ids:
            log(f"[settle ] {it['event_id']} {it['mode']} execution {it['execution_id'][:8]} has no owned order ids; waiting")
            out["waiting"] += 1
            continue
        marks = ",".join("?" * len(client_ids))
        order_rows = store.con.execute(
            "SELECT venue, client_order_id, outcome_id, side, filled_contracts, avg_price, fee_usd, state "
            f"FROM orders WHERE client_order_id IN ({marks})", client_ids,
        ).fetchall()
        venues_needed = {r[0] for r in order_rows}
        if not venues_needed:
            out["waiting"] += 1
            continue
        # Venues do not necessarily finalize at the same time. Persist each authoritative result
        # immediately so the position guard knows why that venue no longer reports a position;
        # the reservation remains open until every venue is final and the cover is settled below.
        for venue in venues_needed:
            if w.get(venue) is not None:
                store.con.execute(
                    "INSERT OR REPLACE INTO execution_venue_results(execution_id,venue,winner,observed_ts) VALUES(?,?,?,?)",
                    (it["execution_id"], venue, str(w[venue]), t),
                )
        store.con.commit()
        if any(w.get(v) is None for v in venues_needed):
            out["waiting"] += 1
            continue
        legs = [{"venue": r[0], "client_order_id": r[1], "outcome_id": r[2], "side": r[3], "contracts": float(r[4] or 0.0),
                 "price": float(r[5] or 0.0), "fee_usd": float(r[6] or 0.0), "state": r[7], "final": True}
                for r in order_rows]
        realized = settle(legs=legs, winners={v: w[v] for v in venues_needed}, now=t)
        pnl = sum(x.realized_usd for x in realized)
        ok = releasable(realized)
        released = bool(ok and it.get("reservation_id") and ledger.release(it["reservation_id"], reason=f"settled: {w}", now=t))
        split = _split(it, legs, pnl)
        store.con.execute(
            "INSERT OR REPLACE INTO execution_settlements(execution_id, opportunity_id, event_id, league, mode, settled_ts, "
            "kalshi_winner, polymarket_winner, realized_usd, released, legs_json, kind, hedged_contracts, unhedged_contracts, "
            "cover_usd, directional_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (it["execution_id"], it["opportunity_id"], it["event_id"], it["league"], it["mode"], t,
             w.get("kalshi"), w.get("polymarket"), pnl, int(released), json.dumps(legs), split["kind"],
             split["hedged"], split["unhedged"], split["cover_usd"], split["directional_usd"]))
        store.con.execute("UPDATE executions SET state=?, released=?, last_utc=?, detail=? WHERE execution_id=?",
                          (X.RECONCILED.value if released else X.SETTLED.value, int(released), t,
                           f"settled {pnl:+.4f} USD ({split['kind']})" + ("" if released else "; not releasable"), it["execution_id"]))
        store.con.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) VALUES(?,?,?,?,?)",
                          (t, it["execution_id"], it["state"], X.RECONCILED.value if released else X.SETTLED.value, f"{pnl:+.4f}"))
        if opportunities is not None:
            load = getattr(opportunities, "load", None)
            opp = load(it["opportunity_id"]) if load is not None else opportunities.live.get(it["opportunity_id"])
            if opp is not None and opp.status in (S.HEDGED, S.FAILED_HEDGE):
                opportunities.move(opp, S.SETTLED, now=t, detail=f"{pnl:+.4f}")
                if released:
                    opportunities.move(opp, S.RECONCILED, now=t)
        out["settled" if released else "unreleasable"] += 1
        log(f"[settle ] {it['event_id']} {it['mode']} {split['kind']} realized {pnl:+.4f} USD"
            + (f" (cover {split['cover_usd']:+.4f}, directional {split['directional_usd']:+.4f} on {split['unhedged']} unhedged)"
               if split["kind"] == "PARTIAL" else "")
            + f"; kalshi={w.get('kalshi')} polymarket={str(w.get('polymarket'))[:12]}"
            + ("; reservation released" if released else "; NOT released"))
    store.con.commit()
    return out


def refresh_settlement_accounting(store, *, now: float | None = None,
                                  log: Callable[[str], None] = print) -> int:
    """Reprice settled rows from their owned orders after an authoritative fee correction.

    Polymarket's V2 trade record reports zero fee even when collateral was charged. Once the guard
    backfills the pinned per-market fee into ``orders``, an already-settled row must change too;
    otherwise the loss breaker and the operator ledger both overstate P&L. Revisions are append-only
    and idempotent. Winners and settlement time are never changed here.
    """
    t = now or time.time()
    store.ensure_ddl(SETTLEMENTS_DDL)
    store.ensure_ddl(SETTLEMENT_REVISIONS_DDL)
    _ensure_columns(store)
    rows = store.con.execute(
        "SELECT s.execution_id,s.settled_ts,s.kalshi_winner,s.polymarket_winner,s.realized_usd,s.legs_json,"
        "e.first_client_id,e.hedge_client_ids,e.unwind_client_ids,e.first_filled,e.hedge_filled,"
        "e.first_avg_price,e.hedge_avg_price FROM execution_settlements s "
        "JOIN executions e ON e.execution_id=s.execution_id"
    ).fetchall()
    changed = 0
    for row in rows:
        exid, settled_ts, kalshi_winner, pm_winner, old_pnl, old_legs = row[:6]
        client_ids = [row[6]] if row[6] else []
        for payload in row[7:9]:
            try:
                client_ids.extend(str(x) for x in json.loads(payload or "[]"))
            except (TypeError, ValueError):
                pass
        if not client_ids:
            continue
        marks = ",".join("?" * len(client_ids))
        order_rows = store.con.execute(
            "SELECT venue,client_order_id,outcome_id,side,filled_contracts,avg_price,fee_usd,state "
            f"FROM orders WHERE client_order_id IN ({marks})",
            client_ids,
        ).fetchall()
        if not order_rows:
            continue
        winners = {"kalshi": kalshi_winner, "polymarket": pm_winner}
        venues = {r[0] for r in order_rows if float(r[4] or 0.0) > 0}
        if any(winners.get(v) is None for v in venues):
            continue
        legs = [
            {"venue": r[0], "client_order_id": r[1], "outcome_id": r[2], "side": r[3],
             "contracts": float(r[4] or 0.0), "price": float(r[5] or 0.0),
             "fee_usd": float(r[6] or 0.0), "state": r[7], "final": True}
            for r in order_rows
        ]
        realized = settle(legs=legs, winners={v: winners[v] for v in venues}, now=float(settled_ts))
        if not releasable(realized):
            continue
        pnl = sum(x.realized_usd for x in realized)
        item = {"first_filled": float(row[9] or 0.0), "hedge_filled": float(row[10] or 0.0),
                "first_avg_price": row[11], "hedge_avg_price": row[12]}
        split = _split(item, legs, pnl)
        new_legs = json.dumps(legs)
        if abs(float(old_pnl or 0.0) - pnl) <= 1e-9 and json.loads(old_legs or "[]") == legs:
            continue
        store.con.execute(
            "INSERT INTO execution_settlement_revisions(revised_ts,execution_id,old_realized_usd,new_realized_usd,"
            "reason,old_legs_json,new_legs_json) VALUES(?,?,?,?,?,?,?)",
            (t, exid, float(old_pnl or 0.0), pnl, "authoritative order/fill accounting changed",
             old_legs or "[]", new_legs),
        )
        store.con.execute(
            "UPDATE execution_settlements SET realized_usd=?,legs_json=?,kind=?,hedged_contracts=?,"
            "unhedged_contracts=?,cover_usd=?,directional_usd=? WHERE execution_id=?",
            (pnl, new_legs, split["kind"], split["hedged"], split["unhedged"],
             split["cover_usd"], split["directional_usd"], exid),
        )
        store.con.execute(
            "UPDATE executions SET detail=? WHERE execution_id=? AND state IN (?,?)",
            (f"settled {pnl:+.4f} USD ({split['kind']}); accounting revised",
             exid, X.RECONCILED.value, X.SETTLED.value),
        )
        changed += 1
        log(f"[settle ] revised {exid[:8]} realized {float(old_pnl or 0.0):+.4f} -> {pnl:+.4f} USD")
    store.con.commit()
    return changed


def _split(it: dict, legs: list[dict], pnl: float) -> dict:
    """COVER when every first-leg contract was hedged; PARTIAL otherwise, with the realized PnL
    split into the hedged part (a cover: h x (1 - price_a - price_b) less its pro-rata fees) and
    the directional remainder (everything else, marked at the venue's result). The split is
    descriptive -- the venue paid one number -- and exists so a PARTIAL row is never read as a
    cover's return."""
    first, hedge = float(it.get("first_filled") or 0.0), float(it.get("hedge_filled") or 0.0)
    h, u = min(first, hedge), max(0.0, first - hedge)
    if first <= 0 or u <= 1e-9:
        return {"kind": "COVER", "hedged": round(h, 4), "unhedged": 0.0, "cover_usd": round(pnl, 4), "directional_usd": 0.0}
    pa, pb = float(it.get("first_avg_price") or 0.0), float(it.get("hedge_avg_price") or 0.0)
    fees = sum(float(l.get("fee_usd") or 0.0) for l in legs if float(l.get("contracts") or 0.0) > 0)
    filled = sum(float(l.get("contracts") or 0.0) for l in legs)
    cover = h * (1.0 - pa - pb) - (fees * (2 * h / filled) if filled else 0.0)
    return {"kind": "PARTIAL", "hedged": round(h, 4), "unhedged": round(u, 4),
            "cover_usd": round(cover, 4), "directional_usd": round(pnl - cover, 4)}

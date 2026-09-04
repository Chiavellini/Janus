#!/usr/bin/env python3
"""Settle finished executions against each venue's own result, and release their capital.

The coordinator stops at HEDGED (or a failure state) with the reservation held: "capital is
released only by the reconcile node, after both venues reconcile". Until 2026-09-04 nothing in
the lane did that -- the first paper cover (F3) sat HEDGED with its reservation open and the
watchdog said UNRECONCILED_TOO_LONG. This is the pass:

  1. every execution not yet released whose game has ended (phase `post`, or start + 6 h);
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
  realized_usd REAL NOT NULL, released INTEGER NOT NULL, legs_json TEXT NOT NULL);
"""
OPEN_STATES = (X.HEDGED.value, X.SETTLED.value)          # SETTLED without release: retry


def pending(store, *, now: float | None = None, grace_s: float = 6 * 3600.0) -> list[dict]:
    """Executions still holding capital whose game has ended, with the event spec beside them."""
    t = now or time.time()
    rows = store.con.execute(
        "SELECT e.execution_id, e.opportunity_id, e.event_id, e.league, e.mode, e.state, e.reservation_id, "
        "ev.pm_slug, ev.spec_json, ev.phase, ev.start_utc FROM executions e LEFT JOIN events ev ON ev.event_id = e.event_id "
        "WHERE e.released = 0 AND e.state IN (?, ?)", OPEN_STATES).fetchall()
    out = []
    for r in rows:
        phase, start = r[9] or "", r[10]
        ended = phase.startswith("post") or (start is not None and t - float(start) > grace_s)
        if not ended:
            continue
        spec = json.loads(r[8]) if r[8] else {}
        out.append({"execution_id": r[0], "opportunity_id": r[1], "event_id": r[2], "league": r[3], "mode": r[4],
                    "state": r[5], "reservation_id": r[6], "pm_slug": r[7], "outcomes": spec.get("outcomes") or {}})
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
            if it.get("pm_slug"):
                winners["polymarket"] = _pm_winner(fetch_event(it["pm_slug"]), it["pm_slug"], it["outcomes"])
        except Exception as exc:  # noqa: BLE001 -- one venue down must not stop the pass
            winners["error"] = f"{type(exc).__name__}"
        out[it["execution_id"]] = winners
    return out


def apply_settlements(store, ledger, records, opportunities, items: list[dict], winners: dict[str, dict],
                      *, now: float | None = None, log: Callable[[str], None] = print) -> dict:
    """The state half. Settles every execution both venues have resolved; the rest wait."""
    t = now or time.time()
    store.ensure_ddl(SETTLEMENTS_DDL)
    out = {"settled": 0, "waiting": 0, "unreleasable": 0}
    for it in items:
        w = winners.get(it["execution_id"]) or {}
        venues_needed = {r[0] for r in store.con.execute("SELECT DISTINCT venue FROM orders WHERE opportunity_id=?", (it["opportunity_id"],))}
        if any(w.get(v) is None for v in venues_needed):
            out["waiting"] += 1
            continue
        legs = [{"venue": r[0], "client_order_id": r[1], "outcome_id": r[2], "side": r[3], "contracts": float(r[4] or 0.0),
                 "price": float(r[5] or 0.0), "fee_usd": float(r[6] or 0.0), "state": r[7], "final": True}
                for r in store.con.execute(
                    "SELECT venue, client_order_id, outcome_id, side, filled_contracts, avg_price, fee_usd, state FROM orders "
                    "WHERE opportunity_id=?", (it["opportunity_id"],))]
        realized = settle(legs=legs, winners={v: w[v] for v in venues_needed}, now=t)
        pnl = sum(x.realized_usd for x in realized)
        ok = releasable(realized)
        released = bool(ok and it.get("reservation_id") and ledger.release(it["reservation_id"], reason=f"settled: {w}", now=t))
        store.con.execute(
            "INSERT OR REPLACE INTO execution_settlements VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (it["execution_id"], it["opportunity_id"], it["event_id"], it["league"], it["mode"], t,
             w.get("kalshi"), w.get("polymarket"), pnl, int(released), json.dumps(legs)))
        store.con.execute("UPDATE executions SET state=?, released=?, last_utc=?, detail=? WHERE execution_id=?",
                          (X.RECONCILED.value if released else X.SETTLED.value, int(released), t,
                           f"settled {pnl:+.4f} USD" + ("" if released else "; not releasable"), it["execution_id"]))
        store.con.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) VALUES(?,?,?,?,?)",
                          (t, it["execution_id"], it["state"], X.RECONCILED.value if released else X.SETTLED.value, f"{pnl:+.4f}"))
        opp = opportunities.live.get(it["opportunity_id"]) if opportunities is not None else None
        if opp is not None and opp.status is S.HEDGED:
            opp.transition(S.SETTLED, now=t, detail=f"{pnl:+.4f}")
            if released:
                opp.transition(S.RECONCILED, now=t)
            opportunities._upsert(opp)
        out["settled" if released else "unreleasable"] += 1
        log(f"[settle ] {it['event_id']} {it['mode']} realized {pnl:+.4f} USD; kalshi={w.get('kalshi')} polymarket={str(w.get('polymarket'))[:12]}"
            + ("; reservation released" if released else "; NOT released"))
    store.con.commit()
    return out

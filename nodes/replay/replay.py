#!/usr/bin/env python3
"""Captured frames -> the same handlers, the same pollers, the same record path -> a scratch DB.

WHY. GATE_TO_LIVE step 4: an offline parity check must rebuild EVERY logged decision by importing
the live runner's own constants, with zero mismatches. That is only possible if the offline path
IS the live path minus the socket. This node feeds `nodes/capture` frames into
`KalshiStream.handle` / `PolymarketStream.handle` with the captured receive time as `now`, lets
`nodes/game_poller` re-price on every event exactly as it did live, and writes through
`nodes/opportunity.record_evaluation` -- the function the supervisor writes through.

What is NOT shared: the supervisor's spawn/reap loop lives in `grids/live_stream` and this node
mirrors its spawn (a node may not import a grid). Consolidating that into a node is plan P7's
job; until then `Harness.spawn` must stay a line-for-line mirror.

    python3 -m nodes.replay.replay --start 2026-09-03T00:00Z --end 2026-09-03T01:00Z \
        --live-db /Volumes/Kilos/janus/tuples/tuples.sqlite --out /Volumes/Kilos/janus/replay/x.sqlite

`compare()` then diffs the scratch rows against the live table for the same window.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from kernel.redact import brief_error
from nodes.capture.capture import FRAMES_ROOT, Frame, iter_capture, merge
from nodes.discovery.discovery import load_specs
from nodes.game_poller.poller import GamePoller, PollerState
from nodes.settle_wedge.equivalence import SettlementEquivalence
from nodes.settle_wedge.pair import certify_from_spec
from kernel.schema import Mode, OpportunityStatus
from nodes.execute.coordinator import Coordinator
from nodes.execute.plan import plan_from_cover
from nodes.execute.records import ExecutionRecords
from nodes.execute.venues import build_venues
from nodes.execution.journal import Journal
from nodes.opportunity.opportunity import Opportunity, OpportunityStore, books_snapshot
from nodes.opportunity.thresholds import STRATEGY_VERSION
from nodes.risk.breaker import LossBreaker
from nodes.risk.clearance import Candidate, clear
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import ExposureLedger
from nodes.risk.limits import load_limits
from nodes.opportunity.record import record_evaluation
from nodes.store_tuples.store import TupleStore
from nodes.stream_kalshi.stream import KalshiStream
from nodes.stream_polymarket.stream import PolymarketStream

QUANTITIES = (5.0, 10.0, 25.0, 100.0)   # mirrors grids/live_stream/grid.py (parity, GATE step 4)
MIN_RETURN = 0.01


@dataclass
class Harness:
    """The supervisor's shape without its sockets or its clock."""
    store: TupleStore
    quantities: tuple[float, ...] = QUANTITIES
    #: mirrors grids/live_stream/grid.EVAL_INTERVAL_S; a capture replays only against rows the
    #: same interval produced.
    eval_interval_s: float = 0.2
    max_book_age_s: float = 5.0
    min_return: float = MIN_RETURN
    #: Settlement rates; None = the evidence registry, exactly as the supervisor uses it.
    rates: dict | None = None
    #: OFFLINE_REPLAY runs the paper coordinator over the replayed books; SHADOW_LIVE only records.
    mode: Mode = Mode.SHADOW_LIVE
    kill_root: object | None = None
    coordinator: Coordinator | None = field(init=False, default=None)
    venues: dict = field(init=False, default_factory=dict)
    executions: int = 0
    refusals: dict[str, int] = field(default_factory=dict)

    ks: KalshiStream = field(init=False)
    ps: PolymarketStream = field(init=False)
    pollers: dict[str, GamePoller] = field(default_factory=dict)
    fee_params: dict[str, dict] = field(default_factory=dict)
    leagues: dict[str, str] = field(default_factory=dict)
    blocked: dict[str, str] = field(default_factory=dict)
    frames: dict[str, int] = field(default_factory=lambda: {"kalshi": 0, "polymarket": 0})
    parse_errors: int = 0
    evaluations: int = 0
    written: int = 0

    opportunities: OpportunityStore = field(init=False)

    def __post_init__(self) -> None:
        self.ks = KalshiStream(api_key="replay", private_key=None)
        self.ps = PolymarketStream()
        self.opportunities = OpportunityStore(self.store)
        if self.mode.rank >= Mode.PAPER_EXECUTION.rank:
            self._clock_now = 0.0
            journal = Journal(self.store)
            self.venues = build_venues(Mode.OFFLINE_REPLAY, journal, clock=lambda: self._clock_now,
                                       mono=lambda: self._clock_now)
            self._limits = load_limits()
            self._kill = KillSwitches(self.kill_root or "/Volumes/Kilos/janus/kill", enforce_volume=self.kill_root is None)
            self._breaker = LossBreaker(__import__('pathlib').Path(self._kill.root) / 'breaker.json', kill=self._kill,
                                        enforce_volume=self.kill_root is None)
            self._ledger = ExposureLedger(self.store)
            self.coordinator = Coordinator(self.venues, ExecutionRecords(self.store), Mode.OFFLINE_REPLAY,
                                           hedge_deadline_s=self._limits.max_hedge_latency_ms / 1000.0,
                                           clock=lambda: self._clock_now, mono=lambda: self._clock_now,
                                           sleep=self._advance, opportunities=self.opportunities, kill=self._kill)

    # MIRROR of grids/live_stream Supervisor.reconcile's spawn branch. Keep them identical.
    def spawn(self, game_id: str, spec: dict) -> bool:
        if game_id in self.pollers:
            return True
        eq = certify_from_spec(spec, spec["league"], rates=self.rates)
        p = GamePoller(game_id, spec["league"], spec["outcomes"], quantities=self.quantities,
                       max_book_age_s=self.max_book_age_s, min_return=self.min_return,
                       min_eval_interval_s=self.eval_interval_s,      # mirrors grid.EVAL_INTERVAL_S
                       fee_params=spec["fee_params"],
                       equivalence=eq if isinstance(eq, SettlementEquivalence) else None,
                       order_limits={"polymarket": spec.get("pm_limits") or {}})
        if p.state is PollerState.BLOCKED:
            st = spec.get("settlement") or {}
            self.blocked[game_id] = f"SPAWN:{p.block_reason}" + (f" ({st.get('code')}: {str(st.get('detail', ''))[:120]})"
                                                                if st.get("result") == "BLOCKED" else "")
            return False
        cb = self._on_update(game_id)
        for venue, market_id, side, rep in p.registrations():
            if venue == "kalshi":
                self.ks.register(market_id, rep, side, on_update=cb)
            else:
                self.ps.register(market_id, rep, on_update=cb)
        self.pollers[game_id] = p
        self.fee_params[game_id] = dict(spec["fee_params"])
        self.leagues[game_id] = spec["league"]
        return True

    def _on_update(self, gid: str):
        def cb(market_id: str, now: float) -> None:
            p = self.pollers.get(gid)
            if p is None:
                return
            for ev in p.on_event("stream", market_id, now=now):
                self.evaluations += 1
                rec = record_evaluation(self.store, ev, league=self.leagues[gid],
                                        fee_params=self.fee_params[gid], hurdle=self.min_return,
                                        opportunities=self.opportunities)
                self.written += int(rec.wrote)
                if self.coordinator is not None and rec.status is OpportunityStatus.PROFITABLE_UNEXECUTED:
                    self._clock_now = ev.evaluated_utc
                    self._execute(gid, ev, rec)
        return cb

    def _advance(self, s: float) -> None:
        self._clock_now += s

    def _execute(self, gid: str, ev, rec) -> None:
        """MIRROR of grids/live_stream Supervisor._execute, on the replayed books and clock."""
        offers = {o: list(v) for o, v in ev.offers.items()}
        plan = plan_from_cover(opportunity_id=Opportunity.id_for(gid, ev.quantity), event_id=gid,
                               league=self.leagues[gid], cov=ev.cover, offers=offers, hurdle=self.min_return)
        if plan is None:
            return
        for legs in offers.values():
            for l in legs:
                v = self.venues.get(l.venue)
                if v is not None and hasattr(v, "books"):
                    side = "buy_no" if (l.venue == "kalshi" and l.outcome_id.endswith(":NO")) else "buy_yes"
                    v.books[(l.market_id, side)] = l.book
        max_age = max((ev.evaluated_utc - l.book.fetched_utc) for legs in offers.values() for l in legs)
        cand = Candidate(plan.opportunity_id, gid, self.leagues[gid],
                         ((plan.first.venue, plan.first.contracts, plan.first.limit_price),
                          (plan.hedge.venue, plan.hedge.contracts, plan.hedge.limit_price)),
                         rec.net_profit_usd or 0.0, rec.locked_return or 0.0, STRATEGY_VERSION, max_age)
        c = clear(cand, mode=Mode.OFFLINE_REPLAY, limits=self._limits, ledger=self._ledger, kill=self._kill,
                  breaker=self._breaker, fills_today=(), clock_healthy=True, fee_schedules_ok=True,
                  balances=None, venues_connected={"kalshi": True, "polymarket": True},
                  now_mono=self._clock_now, now=self._clock_now)
        if hasattr(c, "code"):
            self.refusals[c.code] = self.refusals.get(c.code, 0) + 1
            return
        ex = self.coordinator.execute(plan, c, offers_books=books_snapshot(offers))
        self.executions += 1
        if ex.released:
            self._ledger.release(ex.reservation_id, reason=f"nothing filled: {ex.state.value}")

    def feed(self, frame: Frame) -> None:
        """One captured frame, with its captured receive time as the clock."""
        self.frames[frame.venue] = self.frames.get(frame.venue, 0) + 1
        if frame.venue == "kalshi":
            try:
                msg = json.loads(frame.raw)
            except ValueError:
                self.parse_errors += 1
                return
            self.ks.handle(msg, now=frame.received_utc)
        elif frame.venue == "polymarket":
            self.ps.handle(frame.raw, now=frame.received_utc)
        else:
            raise ValueError(f"unknown venue in capture: {frame.venue!r}")

    def stats(self) -> dict:
        return {"pollers": len(self.pollers), "blocked": dict(self.blocked), "frames": dict(self.frames),
                "parse_errors": self.parse_errors, "evaluations": self.evaluations,
                "rows": self.written, "mode": self.mode.value, "executions": self.executions,
                "refusals": dict(self.refusals), "kalshi": self.ks.stats(), "polymarket": self.ps.stats()}


def replay(harness: Harness, frames: Iterable[Frame]) -> dict:
    for f in frames:
        harness.feed(f)
    harness.store.commit()
    return harness.stats()


# ── the parity check ─────────────────────────────────────────────────────────
_COLS = "game_id, quantity, seen_ts, status, cost, gross, fees, return_locked, blocked_by"


def _rows(store: TupleStore, start_utc: float, end_utc: float) -> list[tuple]:
    rows = store.con.execute(
        f"SELECT {_COLS} FROM stream_evaluations WHERE seen_ts BETWEEN ? AND ? "
        "ORDER BY game_id, quantity, seen_ts", (start_utc, end_utc)).fetchall()
    def norm(r):
        gid, q, ts, status, cost, gross, fees, ret, blocked = r
        rnd = lambda x: None if x is None else round(float(x), 6)   # noqa: E731
        return (gid, float(q), round(float(ts), 3), status, rnd(cost), rnd(gross), rnd(fees), rnd(ret), blocked)
    return [norm(r) for r in rows]


def compare(live: TupleStore, replayed: TupleStore, *, start_utc: float, end_utc: float) -> dict:
    """Zero mismatches is the bar. Anything else names the first differing rows."""
    a, b = _rows(live, start_utc, end_utc), _rows(replayed, start_utc, end_utc)
    sa, sb = set(a), set(b)
    only_live, only_replay = sorted(sa - sb)[:20], sorted(sb - sa)[:20]
    return {"live_rows": len(a), "replay_rows": len(b), "mismatches": len(sa ^ sb),
            "only_live": only_live, "only_replay": only_replay}


def _parse_ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-root", type=Path, default=FRAMES_ROOT)
    ap.add_argument("--start", required=True, help="ISO-8601 UTC, e.g. 2026-09-03T00:00Z")
    ap.add_argument("--end", required=True)
    ap.add_argument("--live-db", type=Path, default=Path("/Volumes/Kilos/janus/tuples/tuples.sqlite"))
    ap.add_argument("--out", type=Path, required=True, help="scratch DB for the replayed rows")
    ap.add_argument("--games", default="", help="comma-separated event ids; default: every spec on record")
    ap.add_argument("--max-book-age", type=float, default=5.0)
    ap.add_argument("--mode", default="SHADOW_LIVE", help="SHADOW_LIVE records; OFFLINE_REPLAY also runs the paper coordinator")
    a = ap.parse_args(argv)
    start, end = _parse_ts(a.start), _parse_ts(a.end)

    live = TupleStore(a.live_db)
    specs = load_specs(live, game_ids=[g for g in a.games.split(",") if g] or None)
    if not specs:
        print("no slate specs on record for that selection; nothing to rebuild", file=sys.stderr)
        return 2
    out = TupleStore(a.out)
    h = Harness(out, max_book_age_s=a.max_book_age, mode=Mode(a.mode) if a.mode != "OFFLINE_REPLAY" else Mode.PAPER_EXECUTION)
    for gid, spec in specs.items():
        h.spawn(gid, spec)
    frames = merge([iter_capture(a.frames_root, "kalshi", start, end),
                    iter_capture(a.frames_root, "polymarket", start, end)])
    try:
        st = replay(h, frames)
    except Exception as exc:  # noqa: BLE001
        print(f"replay failed: {brief_error(exc)}", file=sys.stderr)
        return 1
    print(json.dumps({"replay": st, "parity": compare(live, out, start_utc=start, end_utc=end)},
                     indent=2, default=str))
    out.close(); live.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
from nodes.opportunity.record import record_evaluation
from nodes.store_tuples.store import TupleStore
from nodes.stream_kalshi.stream import KalshiStream
from nodes.stream_polymarket.stream import PolymarketStream

QUANTITIES = (5.0, 25.0, 100.0)
MIN_RETURN = 0.01


@dataclass
class Harness:
    """The supervisor's shape without its sockets or its clock."""
    store: TupleStore
    quantities: tuple[float, ...] = QUANTITIES
    max_book_age_s: float = 5.0
    min_return: float = MIN_RETURN
    #: Settlement rates; None = the evidence registry, exactly as the supervisor uses it.
    rates: dict | None = None

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

    def __post_init__(self) -> None:
        self.ks = KalshiStream(api_key="replay", private_key=None)
        self.ps = PolymarketStream()

    # MIRROR of grids/live_stream Supervisor.reconcile's spawn branch. Keep them identical.
    def spawn(self, game_id: str, spec: dict) -> bool:
        if game_id in self.pollers:
            return True
        eq = certify_from_spec(spec, spec["league"], rates=self.rates)
        p = GamePoller(game_id, spec["league"], spec["outcomes"], quantities=self.quantities,
                       max_book_age_s=self.max_book_age_s, min_return=self.min_return,
                       fee_params=spec["fee_params"],
                       equivalence=eq if isinstance(eq, SettlementEquivalence) else None)
        if p.state is PollerState.BLOCKED:
            self.blocked[game_id] = f"SPAWN:{p.block_reason}"
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
                                        fee_params=self.fee_params[gid], hurdle=self.min_return)
                self.written += int(rec.wrote)
        return cb

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
                "rows": self.written, "kalshi": self.ks.stats(), "polymarket": self.ps.stats()}


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
    a = ap.parse_args(argv)
    start, end = _parse_ts(a.start), _parse_ts(a.end)

    live = TupleStore(a.live_db)
    specs = load_specs(live, game_ids=[g for g in a.games.split(",") if g] or None)
    if not specs:
        print("no slate specs on record for that selection; nothing to rebuild", file=sys.stderr)
        return 2
    out = TupleStore(a.out)
    h = Harness(out, max_book_age_s=a.max_book_age)
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

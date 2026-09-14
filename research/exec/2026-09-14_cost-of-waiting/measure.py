#!/usr/bin/env python3
"""L116: what does WAITING cost? The hedge book's move over a maker rest window.

Resting leg A as a Polymarket maker saves a certain 0.828 c/contract (`taker_only: True`, so a
maker pays nothing there). But a resting order fills when the market comes TO it, which is
disproportionately when the hedge has moved AWAY. If that adverse move exceeds 0.828c the maker
path is dead and the experiment is not worth running.

DESIGN, and why it is cheap. The "price now" side is already in the database: every
`stream_evaluations` row carries `legs_json` with the per-leg `vwap`, which is
`walk_ladder(book, q) / q` -- exactly `vwap_for_size(hedge_book, q)` at that instant, and exactly
what becomes `plan.hedge.vwap`, which is what the live `hedge_slippage_c` is measured against
(`protect.py`: `(avg - plan.hedge.vwap) * 100`). So only the "+N seconds" side needs frames, and
only KALSHI frames, because Kalshi is always the hedge (`plan.FIRST_VENUE/HEDGE_VENUE`).

Streaming, one forward pass, bounded memory: L41's shape, whose own note records that the
non-streaming first version was killed at 50 minutes on a paging Mac. Frames are parsed in receive
order; each actionable moment waits in a heap until the clock passes t+W, then the CURRENT
reconstructed book is priced with the same ladder walk the lane uses.

    python3 measure.py --day 2026-09-13 [--frames-root /srv/janus/frames] [--db ...] [--out ...]

Reads no outcome. Writes one results file. Changes nothing.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import heapq
import json
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

#: Importable both from the repo and when shipped standalone to the box (where it is run with
#: PYTHONPATH=/opt/janus and lives under /tmp, so `parents[3]` does not exist).
_parents = Path(__file__).resolve().parents
ROOT = next((p for p in _parents if (p / "kernel").is_dir()), None)
if ROOT is not None:
    sys.path.insert(0, str(ROOT))
from nodes.capture.capture import CORRUPT_FILES, read_frames  # noqa: E402
from nodes.entities.leagues import league_for_series  # noqa: E402
from nodes.stream_kalshi.protocol import TickerBook, parse  # noqa: E402

#: The rest windows a maker order might be given, PLUS the taker's own baseline.
#:
#: The comparison is not "0.828c saved against the whole move over the rest window". A TAKER
#: already suffers this drift: L108 measured decision -> hedge ack at 2,480 ms p50, and the hedge
#: is only priced when it acks. So the taker's exposure is the move over ~2.5 s, and the maker's
#: incremental cost is the move over (rest + 2.5 s) MINUS the move over 2.5 s. Both halves come
#: from this one instrument so they are directly comparable; 2.5 is the baseline and the paired
#: windows are rest + 2.5.
TAKER_BASELINE_S = 2.5
#: Windows BELOW the baseline matter just as much, and for the opposite reason. The 2,480 ms is
#: exactly what the speed work has been shortening (L103's metadata prefetch, L109's duplicated
#: orderbook read, L110/L111's loop blockers), so the sub-2.5 s points price what that work is
#: WORTH in cents per contract -- and they also say what it does to the maker case, which is
#: measured incrementally against this same baseline and therefore gets relatively worse as the
#: taker gets faster.
WINDOWS = (0.5, 1.0, 1.5, 2.0, 2.5, 5.0, 7.5, 10.0, 12.5, 20.0, 22.5)
#: What the Polymarket taker fee on leg A costs, measured from the venue's own recorded fees.
#: This is the number the answer is compared against.
FEE_SAVED_C = 0.828


def walk_vwap(asks, contracts: float) -> float | None:
    """Average price to buy `contracts` off an ask ladder, or None when depth is short.

    Deliberately identical arithmetic to `nodes/cover/cover.walk_ladder` + `plan.vwap_for_size`:
    the whole point is that this number is comparable to `plan.hedge.vwap`. `test_measure.py`
    asserts the two agree on random ladders.
    """
    need, gross = contracts, 0.0
    for p, s in asks:
        if need <= 0:
            break
        take = min(need, s)
        gross += take * p
        need -= take
    return round(gross / contracts, 6) if need <= 1e-9 and contracts > 0 else None


def actionable_moments(db: Path, day: str) -> list[tuple]:
    """(t, ticker, side, q, vwap0, league) for every actionable print whose hedge leg is Kalshi."""
    t0 = time.mktime(time.strptime(day + " 00:00:00", "%Y-%m-%d %H:%M:%S")) - time.timezone
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = []
    for seen, league, q, legs_json in con.execute(
            "SELECT seen_ts, league, quantity, legs_json FROM stream_evaluations "
            "WHERE seen_ts>=? AND seen_ts<? AND status='PROFITABLE_UNEXECUTED' AND legs_json IS NOT NULL",
            (t0, t0 + 86400)):
        try:
            legs = json.loads(legs_json)
        except ValueError:
            continue
        for leg in legs:
            if not isinstance(leg, dict) or leg.get("venue") != "kalshi":
                continue
            outcome = str(leg.get("outcome") or "")
            vwap = leg.get("vwap")
            if not outcome or vwap is None:
                continue
            # `_leg_side`: a Kalshi outcome ending ":NO" is a buy_no, which is the NO projection.
            side = "no" if outcome.endswith(":NO") else "yes"
            ticker = outcome[:-3] if side == "no" else outcome
            out.append((float(seen), ticker, side, float(q), float(vwap), league or "?"))
    con.close()
    out.sort()
    return out


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    def q(f):
        return round(s[min(len(s) - 1, int(len(s) * f))], 3)
    return {"n": len(s), "p10": q(0.10), "p50": round(statistics.median(s), 3), "p90": q(0.90),
            "mean": round(statistics.fmean(s), 3), "max": round(s[-1], 3),
            "adverse": sum(1 for x in s if x > 0)}


def run(frames_root: Path, db: Path, day: str) -> dict:
    moments = actionable_moments(db, day)
    if not moments:
        return {"day": day, "note": "no actionable prints with a Kalshi hedge leg on this day"}

    # (due_ts, seq, ticker, side, q, vwap0, league, window)
    heap: list[tuple] = []
    for i, (t, ticker, side, q, vwap0, lg) in enumerate(moments):
        for w in WINDOWS:
            heapq.heappush(heap, (t + w, i, ticker, side, q, vwap0, lg, w))

    books: dict[str, TickerBook] = {}
    moves: dict[tuple, list[float]] = defaultdict(list)
    no_depth: dict[tuple, int] = defaultdict(int)
    never_seen: dict[tuple, int] = defaultdict(int)
    frames = parse_errors = 0

    def settle(due, ticker, side, q, vwap0, lg, w, clock):
        book = books.get(ticker)
        if book is None:
            never_seen[(lg, w)] += 1
            return
        _bids, asks = book.project(side)
        now_vwap = walk_vwap(asks, q)
        if now_vwap is None:
            no_depth[(lg, w)] += 1          # cannot fill the size at all: worse than dear, not missing
            return
        moves[(lg, w)].append(round((now_vwap - vwap0) * 100.0, 4))

    files = sorted(glob.glob(str(frames_root / "kalshi" / day / "*.jsonl.gz")))
    for f in files:
        for fr in read_frames(f, "kalshi"):
            frames += 1
            t = fr.received_utc
            while heap and heap[0][0] <= t:
                due, _i, ticker, side, q, vwap0, lg, w = heapq.heappop(heap)
                settle(due, ticker, side, q, vwap0, lg, w, t)
            try:
                msg = json.loads(fr.raw)
            except ValueError:
                parse_errors += 1
                continue
            p = parse(msg, books)
            if p.kind not in ("snapshot", "delta"):
                continue
    # anything still pending never reached its window inside the day's frames
    while heap:
        _due, _i, _tk, _sd, _q, _v, lg, w = heapq.heappop(heap)
        never_seen[(lg, w)] += 1

    by_window, by_league = {}, {}
    pooled_by_w = {w: [v for (lg, ww), vs in moves.items() if ww == w for v in vs] for w in WINDOWS}
    base = pooled_by_w.get(TAKER_BASELINE_S) or []
    base_mean = statistics.fmean(base) if base else None
    base_p50 = statistics.median(base) if base else None
    for w in WINDOWS:
        pooled = [v for (lg, ww), vs in moves.items() if ww == w for v in vs]
        by_window[str(w)] = {**summarize(pooled),
                             "no_depth": sum(v for (lg, ww), v in no_depth.items() if ww == w),
                             "unresolved": sum(v for (lg, ww), v in never_seen.items() if ww == w),
                             "exceeds_fee_saved": (sum(1 for v in pooled if v > FEE_SAVED_C) / len(pooled)
                                                   if pooled else None),
                             # what the maker pays ON TOP of what the taker already pays
                             "incremental_mean": (None if (base_mean is None or not pooled)
                                                  else round(statistics.fmean(pooled) - base_mean, 3)),
                             "incremental_p50": (None if (base_p50 is None or not pooled)
                                                 else round(statistics.median(pooled) - base_p50, 3))}
    for (lg, w), vs in sorted(moves.items()):
        by_league.setdefault(lg, {})[str(w)] = summarize(vs)
    return {"day": day, "moments": len(moments), "samples": sum(len(v) for v in moves.values()),
            "frames": frames, "parse_errors": parse_errors, "files": len(files),
            "corrupt_files": dict(CORRUPT_FILES), "fee_saved_c": FEE_SAVED_C,
            "windows": by_window, "by_league": by_league}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-root", type=Path, default=Path("/srv/janus/frames"))
    ap.add_argument("--db", type=Path, default=Path("/srv/janus/tuples/tuples.sqlite"))
    ap.add_argument("--day", required=True, help="YYYY-MM-DD, UTC")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    r = run(a.frames_root, a.db, a.day)
    text = json.dumps(r, indent=1, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

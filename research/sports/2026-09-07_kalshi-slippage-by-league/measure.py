#!/usr/bin/env python3
"""L41: Kalshi hedge-window slippage per league, on clean windows, time-weighted, at q = 5 / 25 / 100.
L27's replay loop (nodes/capture -> nodes/stream_kalshi/protocol) with the row's stratification.
Appends a dated section to verdict.md; results_<run>.json beside it. Reads no outcome."""
from __future__ import annotations

import glob
import json
import sqlite3
import sys
from bisect import bisect_right
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.paths import DB  # noqa: E402
from nodes.capture.capture import CORRUPT_FILES, read_frames  # noqa: E402
from nodes.cover_cost.distribution import load_flap_windows  # noqa: E402
from nodes.entities.leagues import league_for_series  # noqa: E402
from nodes.stream_kalshi.protocol import TickerBook, parse  # noqa: E402

HERE = Path(__file__).resolve().parent
WINDOWS = (0.5, 1.0, 3.0)
QS = (5.0, 25.0, 100.0)
CAP_S = 60.0
MIN_N, MIN_TICKERS = 2000, 4


def asks_at_depth(book: TickerBook) -> dict[float, float | None]:
    _bids, asks = book.project("yes")
    out, cum = {}, 0.0
    for p, s in asks:
        cum += s
        for q in QS:
            if q not in out and cum >= q - 1e-9:
                out[q] = p
    return {q: out.get(q) for q in QS}


def in_windows(t: float, starts: list[float], ends: list[float]) -> bool:
    i = bisect_right(starts, t) - 1
    return i >= 0 and t < ends[i]


def wq(pairs: list[tuple[float, float]], p: float) -> float | None:
    """Time-weighted quantile of (value, weight)."""
    if not pairs:
        return None
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= p * total:
            return v
    return pairs[-1][0]


def main() -> int:
    """Streaming: one pass over the frames in receive order, a 3 s look-ahead per ticker, weighted
    histograms per cell. The first version held every instant of every ticker (32 M of them) and
    was killed at 50 min on the paging Mac (exit 137, 2026-09-07); the statistic is unchanged."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    flaps = load_flap_windows(con)
    con.close()
    starts, ends = [a for a, _ in flaps], [b for _, b in flaps]
    files = sorted(glob.glob("/Volumes/Kilos/janus/frames/kalshi/**/*.jsonl.gz", recursive=True))
    W_MAX = max(WINDOWS)
    # per ticker: pending instants [t, asks, {(q, w): worst}] not yet 3 s old, plus the last instant's t
    pending: dict[str, deque] = defaultdict(deque)
    # (league, q, w) -> {move: weight}: prices are ticks, so the moves take few distinct values
    hist: dict[tuple[str, float, float], dict[float, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, set] = defaultdict(set)
    n_inst: dict[str, int] = defaultdict(int)
    league_of: dict[str, str] = {}
    frames = dropped = 0

    def league(tk: str) -> str:
        lg = league_of.get(tk)
        if lg is None:
            lg = league_of[tk] = league_for_series(tk.split("-")[0]) or "other"
        return lg

    def finalise(tk: str, item: list, weight: float) -> None:
        if weight <= 0:
            return
        lg = league(tk)
        counts[lg].add(tk)
        n_inst[lg] += 1
        for (q, w), worst in item[2].items():
            hist[(lg, q, w)][round(worst, 4)] += weight

    for f in files:
        books: dict[str, TickerBook] = {}
        for fr in read_frames(f, "kalshi"):
            frames += 1
            try:
                msg = json.loads(fr.raw)
            except ValueError:
                continue
            p = parse(msg, books)
            if p.kind not in ("snapshot", "delta"):
                continue
            t = fr.received_utc
            if in_windows(t, starts, ends):
                dropped += 1
                continue
            asks = asks_at_depth(books[p.ticker])
            dq = pending[p.ticker]
            # fold this instant into every pending one still inside its window
            for item in dq:
                dt = t - item[0]
                if dt <= 0:
                    continue
                for q in QS:
                    a0, ak = item[1].get(q), asks.get(q)
                    if a0 is None or ak is None:
                        continue
                    for w in WINDOWS:
                        if dt <= w:
                            key = (q, w)
                            if ak - a0 > item[2][key]:
                                item[2][key] = ak - a0
            # instants older than the longest window are final; their weight is the dwell to the NEXT
            # instant, which is the one after them in the deque (or this one)
            while dq and t - dq[0][0] > W_MAX:
                item = dq.popleft()
                nxt = dq[0][0] if dq else t
                finalise(p.ticker, item, min(CAP_S, nxt - item[0]))
            dq.append([t, asks, {(q, w): 0.0 for q in QS for w in WINDOWS if asks.get(q) is not None}])
    # the tail: everything still pending has a successor except the last instant per ticker (weight 0)
    for tk, dq in pending.items():
        while dq:
            item = dq.popleft()
            finalise(tk, item, min(CAP_S, dq[0][0] - item[0]) if dq else 0.0)
    moves = {k: [(v, wt) for v, wt in h.items()] for k, h in hist.items()}
    stats: dict[str, dict] = {}
    for (league, q, w), pairs in moves.items():
        s = stats.setdefault(league, {"tickers": len(counts[league]), "instants": n_inst[league], "cells": {}})
        s["cells"][f"q{q:g}_w{w:g}"] = {"n": len(pairs), "p50": wq(pairs, .5), "p90": wq(pairs, .9), "p95": wq(pairs, .95), "p99": wq(pairs, .99),
                                        "share_nonzero_time": (sum(wt for v, wt in pairs if v > 0) / sum(wt for _, wt in pairs)) if pairs else None}
    registered = {}
    for league, s in stats.items():
        cell = s["cells"].get("q25_w3")
        ok = cell is not None and s["instants"] >= MIN_N and s["tickers"] >= MIN_TICKERS and league != "other"
        registered[league] = round(cell["p95"], 4) if ok else None
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    res = {"spec": "research/sports/2026-09-07_kalshi-slippage-by-league/spec.yaml", "run": run, "files": len(files), "frames": frames,
           "instants_dropped_in_flap_windows": dropped, "flap_windows": len(flaps), "corrupt_files": dict(CORRUPT_FILES),
           "leagues": stats, "registered_p95_3s_q25": registered}
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    fmt = lambda x: "—" if x is None else f"{x:.4f}"  # noqa: E731
    lines = [f"\n## Run {run}", "", f"{len(files)} capture files, {frames} frames; {dropped} instants dropped inside {len(flaps)} flap/stall windows; "
             f"corrupt files read up to the cut: {len(CORRUPT_FILES)}.", "",
             "| league | tickers | instants | q5 p95 @3s | q25 p50 / p90 / p95 / p99 @3s | q25 p95 @1s | q100 p95 @3s | q25 share>0 (time) | registered |",
             "|---|---|---|---|---|---|---|---|---|"]
    for league in sorted(stats, key=lambda l: -stats[l]["instants"]):
        s, c = stats[league], stats[league]["cells"]
        g = lambda k, f="p95": (c.get(k) or {}).get(f)  # noqa: E731
        lines.append(f"| {league} | {s['tickers']} | {s['instants']} | {fmt(g('q5_w3'))} | {fmt(g('q25_w3','p50'))} / {fmt(g('q25_w3','p90'))} / "
                     f"{fmt(g('q25_w3'))} / {fmt(g('q25_w3','p99'))} | {fmt(g('q25_w1'))} | {fmt(g('q100_w3'))} | "
                     f"{fmt(g('q25_w3','share_nonzero_time'))} | {registered[league] if registered[league] is not None else 'fallback (L27 pooled)'} |")
    lines += ["", "Registered value per league = time-weighted p95 at 3 s, q = 25, on clean windows, when n >= 2,000 instants over >= 4 tickers; "
              "else L27's pooled 0.0400 stays. Descriptive; reads no outcome; claims no edge."]
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# L41 — Kalshi hedge-window slippage per league (descriptive, re-runnable)\n\nDefinitions in `spec.yaml`, immutable after the first run.\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

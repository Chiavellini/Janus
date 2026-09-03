#!/usr/bin/env python3
"""L27: adverse movement of the Kalshi ask at 100 contracts inside the hedge window."""
from __future__ import annotations

import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.schema import Book, Quote  # noqa: E402
from nodes.capture.capture import read_frames  # noqa: E402
from nodes.stream_kalshi.protocol import TickerBook, parse  # noqa: E402

HERE = Path(__file__).resolve().parent
WINDOWS = (0.5, 1.0, 3.0)
Q = 100.0


def ask_at_depth(book: TickerBook) -> float | None:
    _bids, asks = book.project("yes")
    cum = 0.0
    for p, s in asks:
        cum += s
        if cum >= Q - 1e-9:
            return p
    return None


def main() -> int:
    files = sorted(glob.glob("/Volumes/Kilos/janus/frames*/kalshi/**/*.jsonl.gz", recursive=True))
    series: dict[str, list[tuple[float, float]]] = {}       # ticker -> [(t, ask_at_depth)]
    thin = frames = 0
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
            a = ask_at_depth(books[p.ticker])
            if a is None:
                thin += 1
                continue
            series.setdefault(p.ticker, []).append((fr.received_utc, a))
    moves = {w: [] for w in WINDOWS}
    for tk, pts in series.items():
        pts.sort()
        n = len(pts)
        j = {w: 0 for w in WINDOWS}
        for i, (t, a) in enumerate(pts):
            for w in WINDOWS:
                worst = 0.0
                k = i + 1
                while k < n and pts[k][0] - t <= w:
                    worst = max(worst, pts[k][1] - a)
                    k += 1
                if k > i + 1:
                    moves[w].append(worst)
    def q(xs, p):
        if not xs:
            return None
        xs = sorted(xs); return xs[min(len(xs) - 1, int(p * len(xs)))]
    stats = {str(w): {"n": len(xs), "p50": q(xs, .5), "p90": q(xs, .9), "p95": q(xs, .95), "p99": q(xs, .99),
                      "share_nonzero": (sum(1 for x in xs if x > 0) / len(xs)) if xs else None}
             for w, xs in moves.items()}
    n3 = stats["3.0"]["n"]
    preliminary = n3 < 2000 or len(series) < 4
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    res = {"spec": "research/sports/2026-09-03_kalshi-hedge-window-slippage/spec.yaml", "run": run,
           "files": len(files), "frames": frames, "tickers": sorted(series), "thin_excluded": thin,
           "reference_quantity": Q, "windows": stats, "preliminary": preliminary,
           "registered_value": None if preliminary else stats["3.0"]["p95"]}
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    v = HERE / "verdict.md"
    head = "" if v.exists() else "# L27 — Kalshi hedge-window slippage (descriptive)\n\n"
    lines = [f"## Run {run}", "",
             f"{len(files)} capture files, {frames} frames, {len(series)} tickers ({', '.join(sorted(series))}); "
             f"{thin} samples excluded for a ladder thinner than {Q:.0f} contracts.", "",
             "| window s | n | p50 | p90 | p95 | p99 | share > 0 |", "|---|---|---|---|---|---|---|"]
    for w in WINDOWS:
        s = stats[str(w)]
        fmt = lambda x: "—" if x is None else f"{x:.4f}"   # noqa: E731
        lines.append(f"| {w} | {s['n']} | {fmt(s['p50'])} | {fmt(s['p90'])} | {fmt(s['p95'])} | {fmt(s['p99'])} | "
                     f"{'—' if s['share_nonzero'] is None else f'{s['share_nonzero']:.3f}'} |")
    lines += ["", ("**PRELIMINARY** — under 2,000 samples at 3 s or under 4 tickers; slippage stays unmodelled."
                   if preliminary else f"Registered value: p95 at 3 s = {res['registered_value']:.4f} USD per contract."), ""]
    v.write_text(v.read_text() + "\n" + "\n".join(lines) if v.exists() else head + "\n".join(lines) + "\n")
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

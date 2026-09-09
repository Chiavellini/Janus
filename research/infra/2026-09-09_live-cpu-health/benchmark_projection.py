#!/usr/bin/env python3
"""L51 preserved uncached control versus the production projection implementation."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import itertools
import json
import statistics
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.schema import Quote, fold_complement_bids
from nodes.capture.capture import read_frames
from nodes.stream_kalshi.protocol import TickerBook


def uncached_project(self, outcome="yes"):
    """Verbatim pre-L51 implementation, independent of the candidate."""
    own, other = (self.yes, self.no) if outcome == "yes" else (self.no, self.yes)
    bids = tuple(Quote(p, s) for p, s in sorted(own.items(), reverse=True))
    other_bids = tuple(Quote(p, s) for p, s in sorted(other.items(), reverse=True))
    asks = fold_complement_bids(other_bids)
    return ([(q.price, q.size) for q in bids], [(q.price, q.size) for q in asks])


def trace_reader(measure, frames, project):
    stream = measure.stream_for(frames, "kalshi", 454)
    digest = hashlib.sha256()
    projections = 0
    def traced(book, outcome="yes"):
        nonlocal projections
        got = project(book, outcome)
        digest.update(repr((outcome, got)).encode())
        projections += 1
        return got
    with patch.object(TickerBook, "project", traced):
        for fr in frames:
            stream.handle(json.loads(fr.raw), now=fr.received_utc, mono=fr.received_mono)
    # Every replica's book, timestamps, state, fault and counters must also agree.
    state = {"replicas": {ticker: [dataclasses.asdict(reg.replica) for reg in regs]
                           for ticker, regs in stream.regs.items()},
             "books": {ticker: [book.yes, book.no, book.seq] for ticker, book in stream.books.items()},
             "last_seq": stream.last_seq, "snapshotted": stream.snapshotted,
             "counters": [stream.frames, stream.snapshots, stream.deltas, stream.gaps, stream.errors]}
    state_digest = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return {"projection_count": projections, "projection_sha256": digest.hexdigest(),
            "final_books_health_timestamps_sha256": state_digest}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True,
                    help="New result path; existing evidence is never overwritten")
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("l51_measure", Path(__file__).with_name("measure.py"))
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    frames = list(itertools.islice(read_frames(
        "/Volumes/Kilos/janus/frames/kalshi/2026-09-09/04.jsonl.gz", "kalshi"), 10000))
    optimized = TickerBook.project
    baseline_trace = trace_reader(measure, frames, uncached_project)
    candidate_trace = trace_reader(measure, frames, optimized)
    assert baseline_trace == candidate_trace
    result = {"frames": len(frames), "baseline": [], "optimized": [],
              "source_protocol_sha256": hashlib.sha256((ROOT / "nodes/stream_kalshi/protocol.py").read_bytes()).hexdigest(),
              "baseline_trace": baseline_trace, "optimized_trace": candidate_trace,
              "scope": "Reader/replica processing only; callbacks, network and store excluded."}
    for _ in range(3):
        with patch.object(TickerBook, "project", uncached_project):
            result["baseline"].append(measure.reader_run(frames, "kalshi", 454)["cpu_s"])
        result["optimized"].append(measure.reader_run(frames, "kalshi", 454)["cpu_s"])
    result["median_baseline_cpu_s"] = statistics.median(result["baseline"])
    result["median_optimized_cpu_s"] = statistics.median(result["optimized"])
    result["reader_cpu_reduction"] = 1 - result["median_optimized_cpu_s"] / result["median_baseline_cpu_s"]
    with args.output.open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

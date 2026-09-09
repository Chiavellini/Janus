#!/usr/bin/env python3
"""L51 bounded offline capture/reader profile. Never connects to a venue.

Uses raw public frames already copied to the data volume. Socket handlers run
without game callbacks, so this measures transport/book/capture overhead only,
not a complete live-lane attribution or a trading replay.
"""
from __future__ import annotations

import argparse
import cProfile
import gzip
import hashlib
import itertools
import json
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from nodes.book_replica.replica import BookReplica
from nodes.capture.capture import FrameWriter, capture_files, read_frames
from nodes.stream_kalshi.stream import KalshiStream
from nodes.stream_polymarket.stream import PolymarketStream


def ids_in(frames, venue):
    ids = set()
    for fr in frames:
        try:
            raw = json.loads(fr.raw)
        except ValueError:
            continue
        if venue == "kalshi":
            ticker = (raw.get("msg") or {}).get("market_ticker")
            if ticker:
                ids.add(ticker)
        else:
            for ev in raw if isinstance(raw, list) else [raw]:
                if ev.get("asset_id"):
                    ids.add(ev["asset_id"])
                ids.update(ch["asset_id"] for ch in ev.get("price_changes", []) if ch.get("asset_id"))
    return ids


def stream_for(frames, venue, count):
    stream = KalshiStream() if venue == "kalshi" else PolymarketStream()
    ids = ids_in(frames, venue)
    ids.update(f"L51-padding-{n}" for n in range(max(0, count - len(ids))))
    for mid in sorted(ids):
        rep = BookReplica(venue=venue, market_id=mid,
                          verification="stream" if venue == "kalshi" else "external")
        stream.register(mid, rep)
        if venue == "kalshi":
            stream.register(mid, BookReplica(venue=venue, market_id=mid, verification="stream"), "no")
    return stream


def capture_run(frames, venue, level, root):
    writer = FrameWriter(venue, root)
    original_open = gzip.open
    def open_level(*args, **kwargs):
        kwargs["compresslevel"] = level
        return original_open(*args, **kwargs)
    with patch("nodes.capture.capture.gzip.open", open_level):
        started = time.process_time()
        for fr in frames:
            writer.write(fr.raw, received_utc=fr.received_utc, received_mono=fr.received_mono)
        writer.close()
        cpu_s = time.process_time() - started
    files = capture_files(root, venue, frames[0].received_utc, frames[-1].received_utc)
    restored = list(itertools.chain.from_iterable(read_frames(p, venue) for p in files))
    assert restored == frames, "capture round trip changed frame content, order or timestamps"
    return {"cpu_s": cpu_s, "compressed_bytes": sum(p.stat().st_size for p in files),
            "uncompressed_bytes": writer.bytes, "round_trip_equal": True}


def reader_run(frames, venue, count, *, profile=False):
    stream = stream_for(frames, venue, count)
    profiler = cProfile.Profile() if profile else None
    started = time.process_time()
    if profiler:
        profiler.enable()
    for fr in frames:
        # Match the subscription-set work still done by each transport run loop.
        set(stream.tickers if venue == "kalshi" else stream.asset_ids)
        stream.handle(json.loads(fr.raw) if venue == "kalshi" else fr.raw,
                      now=fr.received_utc, mono=fr.received_mono)
    if profiler:
        profiler.disable()
    out = {"cpu_s": time.process_time() - started, "registrations": sum(map(len, stream.regs.values()))}
    if profiler:
        stats = pstats.Stats(profiler)
        top = sorted(stats.stats.items(), key=lambda item: item[1][2], reverse=True)[:15]
        out["profile_total_s"] = stats.total_tt
        out["profile_top_self_time"] = [
            {"function": f"{Path(k[0]).name}:{k[1]}:{k[2]}", "calls": v[1],
             "self_s": v[2], "cumulative_s": v[3]} for k, v in top]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=10000)
    ap.add_argument("--hour", default="2026-09-09/04")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    scratch = Path(tempfile.mkdtemp(prefix="l51-capture-", dir="/Volumes/Kilos/janus/research"))
    result = {"kind": "offline_component_profile", "data_root": str(scratch), "hour": args.hour,
              "limitation": "No game callbacks, store, network or warm-start parity. Cold capture prefix may omit prior snapshots.",
              "python": sys.version, "venues": {}}
    for venue, count in (("kalshi", 454), ("polymarket", 438)):
        source = Path("/Volumes/Kilos/janus/frames") / venue / (args.hour + ".jsonl.gz")
        frames = list(itertools.islice(read_frames(source, venue), args.frames))
        selected_digest = hashlib.sha256()
        for fr in frames:
            selected_digest.update(json.dumps([fr.received_utc, fr.received_mono, fr.raw], separators=(",", ":")).encode())
        got = {"source": str(source), "selected_sha256": selected_digest.hexdigest(),
               "frames": len(frames), "start_utc": frames[0].received_utc,
               "end_utc": frames[-1].received_utc, "capture": {}}
        for level in (9, 1, 3):
            runs = [capture_run(frames, venue, level, scratch / f"level-{level}-repeat-{n}") for n in range(3)]
            got["capture"][str(level)] = {"runs": runs, "median_cpu_s": statistics.median(r["cpu_s"] for r in runs)}
        got["reader"] = reader_run(frames, venue, count)
        got["reader_profile"] = reader_run(frames, venue, count, profile=True)
        result["venues"][venue] = got
        print(venue, json.dumps(got), flush=True)
    with args.output.open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(result, indent=2) + "\n")
    print("results", args.output, flush=True)


if __name__ == "__main__":
    main()

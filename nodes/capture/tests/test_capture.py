#!/usr/bin/env python3
"""A captured hour must come back exactly as it went in."""
from __future__ import annotations

from pathlib import Path

import pytest

from nodes.capture.capture import Frame, FrameWriter, capture_files, iter_capture, merge, read_frames

T0 = 1_800_000_000.0     # 2027-01-15 08:00:00Z


def test_round_trip_is_byte_for_byte_and_keeps_non_json(tmp_path: Path):
    w = FrameWriter("kalshi", tmp_path, enforce_volume=False)
    frames = ['{"type":"orderbook_snapshot","seq":1}', "PONG", "not json at all {", "ünïcödé"]
    for i, raw in enumerate(frames):
        w.write(raw, received_utc=T0 + i, received_mono=100.0 + i)
    w.write(b'{"bytes": true}', received_utc=T0 + 10, received_mono=110.0)
    w.close()
    files = capture_files(tmp_path, "kalshi", T0, T0 + 60)
    assert len(files) == 1 and files[0].name == "08.jsonl.gz"
    got = list(read_frames(files[0]))
    assert [f.raw for f in got] == frames + ['{"bytes": true}']
    assert got[0] == Frame("kalshi", T0, 100.0, frames[0])
    assert w.stats()["frames"] == 5


def test_files_rotate_on_the_hour(tmp_path: Path):
    w = FrameWriter("polymarket", tmp_path, enforce_volume=False)
    w.write("a", received_utc=T0 + 3599)
    w.write("b", received_utc=T0 + 3600)
    w.write("c", received_utc=T0 + 7200 + 5)
    w.close()
    names = [p.relative_to(tmp_path).as_posix() for p in capture_files(tmp_path, "polymarket", T0, T0 + 8000)]
    assert names == ["polymarket/2027-01-15/08.jsonl.gz", "polymarket/2027-01-15/09.jsonl.gz",
                     "polymarket/2027-01-15/10.jsonl.gz"]
    assert [f.raw for f in iter_capture(tmp_path, "polymarket", T0 + 3600, T0 + 7300)] == ["b", "c"]


def test_the_root_disk_is_refused():
    with pytest.raises(ValueError, match="Volumes/Kilos"):
        FrameWriter("kalshi", "/tmp/frames")


def test_merge_orders_by_receive_time_and_is_stable_within_a_venue():
    k = [Frame("kalshi", 1.0, None, "k1"), Frame("kalshi", 3.0, None, "k2"), Frame("kalshi", 3.0, None, "k3")]
    p = [Frame("polymarket", 2.0, None, "p1"), Frame("polymarket", 3.0, None, "p2")]
    assert [f.raw for f in merge([k, p])] == ["k1", "p1", "k2", "k3", "p2"]
    assert list(merge([[], []])) == []


def test_a_member_cut_mid_stream_yields_what_came_before_and_stops(tmp_path: Path):
    """2026-09-05: the lane died of a SIGBUS mid-hour; launchd appended a fresh gzip member to the
    same file. The first member is cut; zlib raises 'invalid block type' mid-stream, and every
    offline job over that hour died on it (L27's first re-run). The reader keeps the frames before
    the cut, records the file, and never raises into a research run."""
    import gzip as _gz
    import json as _js
    from nodes.capture.capture import CORRUPT_FILES, read_frames
    good = b"".join(_js.dumps({"t": 1000.0 + i, "raw": f"frame {i} " + "x" * 40}).encode() + b"\n" for i in range(20000))
    member = _gz.compress(good)
    cut = member[: (3 * len(member)) // 4] + b"\x00\xff\x13garbage-from-a-truncated-write\xff" * 8
    fresh = _gz.compress(b"".join(_js.dumps({"t": 50000.0 + i, "raw": f"after {i}"}).encode() + b"\n" for i in range(3)))
    p = tmp_path / "kalshi" / "2026-09-05" / "03.jsonl.gz"
    p.parent.mkdir(parents=True)
    p.write_bytes(cut + fresh)
    frames = list(read_frames(p))              # must not raise
    pre = {1000.0 + i for i in range(20000)}
    known = pre | {50000.0 + i for i in range(3)}
    assert frames and all(f.received_utc in known for f in frames), "nothing invented"
    assert any(f.received_utc in pre for f in frames), "what came before the cut is kept"
    # gzip may resync onto the fresh member (those frames are real) or give up at the garbage; either way
    # nothing is raised, and a stream that ends in garbage with no fresh member is recorded as cut
    p2 = tmp_path / "kalshi" / "2026-09-05" / "02.jsonl.gz"
    p2.write_bytes(cut)
    frames2 = list(read_frames(p2))
    assert frames2 and all(f.received_utc in pre for f in frames2)
    ok = tmp_path / "kalshi" / "2026-09-05" / "04.jsonl.gz"
    ok.write_bytes(fresh)
    assert len(list(read_frames(ok))) == 3 and str(ok) not in CORRUPT_FILES

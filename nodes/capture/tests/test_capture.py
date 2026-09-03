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

#!/usr/bin/env python3
"""The socket loop captures the raw text of every frame before parsing it."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nodes.book_replica.replica import BookReplica
from nodes.capture.capture import FrameWriter, capture_files, read_frames
from nodes.stream_kalshi.stream import KalshiStream
from nodes.stream_kalshi.tests.test_stream import SNAP, delta, key


def test_frames_are_written_verbatim_before_parse(tmp_path: Path):
    s = KalshiStream(api_key="k", private_key=key())
    s.register("K1", BookReplica("kalshi", "K1", verification="stream"), "yes")
    s.capture = FrameWriter("kalshi", tmp_path, enforce_volume=False)
    raws = [json.dumps(SNAP), json.dumps(delta(2)), "not json"]

    class FakeWS:
        def __init__(self): self.frames = list(raws)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send(self, m): pass
        async def recv(self):
            if self.frames: return self.frames.pop(0)
            raise asyncio.CancelledError

    async def go():
        stop = asyncio.Event()
        try:
            await asyncio.wait_for(s.run(stop, connect=lambda u, h: FakeWS()), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    asyncio.run(go())
    s.capture.close()
    import time
    files = capture_files(tmp_path, "kalshi", time.time() - 3600, time.time() + 1)
    got = [f.raw for p in files for f in read_frames(p)]
    assert got[:2] == raws[:2]
    assert got[2] == "not json", "captured BEFORE json.loads raised -- that is the point"

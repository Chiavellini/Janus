#!/usr/bin/env python3
"""The socket loop captures the raw text of every frame before parsing it."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from nodes.book_replica.replica import BookReplica
from nodes.capture.capture import FrameWriter, capture_files, read_frames
from nodes.stream_polymarket.stream import PolymarketStream
from nodes.stream_polymarket.tests.test_polymarket import A, BOOK, change


def test_frames_are_written_verbatim_including_pongs(tmp_path: Path):
    s = PolymarketStream()
    s.register(A, BookReplica("polymarket", A, verification="stream"))
    s.capture = FrameWriter("polymarket", tmp_path, enforce_volume=False)
    raws = [json.dumps(BOOK), "PONG", json.dumps(change(0.18, 4, bb=0.19, ba=0.20))]

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
            await asyncio.wait_for(s.run(stop, connect=lambda u: FakeWS()), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    asyncio.run(go())
    s.capture.close()
    files = capture_files(tmp_path, "polymarket", time.time() - 3600, time.time() + 1)
    got = [f.raw for p in files for f in read_frames(p)]
    assert got == raws
    assert s.frames == 3, "and every one of them was handled"

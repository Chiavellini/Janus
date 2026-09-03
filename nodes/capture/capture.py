#!/usr/bin/env python3
"""Raw WebSocket frames to disk, BEFORE they are parsed.

Every later phase needs this and nothing produced it: the reconnect/gap/partial-fill battery, the
faithfulness replay (GATE_TO_LIVE step 4 rebuilds every logged decision from captured input), the
slippage buffer (the distribution of Kalshi best-ask moves inside the hedge window), and any
question of the form "what did the venue actually send at 21:14:07". A parse bug is precisely the
thing you most want to replay, so capture happens on the raw text and never on the parsed dict.

Layout: `<root>/<venue>/<YYYY-MM-DD>/<HH>.jsonl.gz`, one line per frame:
    {"t": received_utc, "m": received_mono, "raw": "<the frame as received>"}
Files rotate on the hour. Disk goes to the Janus volume only; the root disk has ~10 GB free.

Reader and writer share one format so a captured hour round-trips byte-for-byte.
"""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from kernel.paths import FRAMES_ROOT, guard  # noqa: E402


@dataclass(frozen=True)
class Frame:
    venue: str
    received_utc: float
    received_mono: float | None
    raw: str


def _hour_key(ts: float) -> tuple[str, str]:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return d.strftime("%Y-%m-%d"), d.strftime("%H")


class FrameWriter:
    """Append-only, hour-rotated, gzip. One per venue socket."""

    def __init__(self, venue: str, root: Path | str = FRAMES_ROOT, *, enforce_volume: bool = True):
        self.venue = venue
        self.root = Path(root).resolve()
        if enforce_volume:
            guard(self.root, "frame capture")
        self._key: tuple[str, str] | None = None
        self._fh = None
        self.frames = 0
        self.bytes = 0

    def _open_for(self, ts: float) -> None:
        key = _hour_key(ts)
        if key == self._key and self._fh is not None:
            return
        self.close()
        day, hour = key
        path = self.root / self.venue / day / f"{hour}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = gzip.open(path, "at", encoding="utf-8")
        self._key = key

    def write(self, raw, *, received_utc: float | None = None,
              received_mono: float | None = None) -> None:
        """Persist one frame exactly as received. `raw` may be str, bytes or an already-parsed
        object (the last is serialised, but callers should pass the text)."""
        t = received_utc if received_utc is not None else time.time()
        m = received_mono if received_mono is not None else time.monotonic()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        elif not isinstance(raw, str):
            raw = json.dumps(raw, separators=(",", ":"), sort_keys=True)
        self._open_for(t)
        line = json.dumps({"t": t, "m": m, "raw": raw}, separators=(",", ":")) + "\n"
        self._fh.write(line)
        self.frames += 1
        self.bytes += len(line)

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._key = None

    def stats(self) -> dict:
        return {"venue": self.venue, "frames": self.frames, "bytes_uncompressed": self.bytes,
                "current": "/".join(self._key) if self._key else None}


def read_frames(path: Path | str, venue: str | None = None) -> Iterator[Frame]:
    """Frames from one capture file, in the order they were received."""
    p = Path(path)
    v = venue or p.parent.parent.name
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            yield Frame(v, float(d["t"]), d.get("m"), d["raw"])


def capture_files(root: Path | str, venue: str, start_utc: float, end_utc: float) -> list[Path]:
    """Every hour file for `venue` that could hold frames in [start_utc, end_utc]."""
    root = Path(root)
    out = []
    t = int(start_utc) - int(start_utc) % 3600
    while t <= end_utc:
        day, hour = _hour_key(t)
        p = root / venue / day / f"{hour}.jsonl.gz"
        if p.exists():
            out.append(p)
        t += 3600
    return out


def iter_capture(root: Path | str, venue: str, start_utc: float, end_utc: float) -> Iterator[Frame]:
    for p in capture_files(root, venue, start_utc, end_utc):
        for f in read_frames(p, venue):
            if start_utc <= f.received_utc <= end_utc:
                yield f


def merge(streams: Iterable[Iterable[Frame]]) -> Iterator[Frame]:
    """Merge per-venue frame streams by receive time, stable within a venue."""
    import heapq
    its = []
    for i, s in enumerate(streams):
        it = iter(s)
        try:
            first = next(it)
        except StopIteration:
            continue
        its.append((first.received_utc, i, 0, first, it))
    heapq.heapify(its)
    n = 0
    while its:
        _t, i, _n, f, it = heapq.heappop(its)
        yield f
        try:
            nxt = next(it)
        except StopIteration:
            continue
        n += 1
        heapq.heappush(its, (nxt.received_utc, i, n, nxt, it))

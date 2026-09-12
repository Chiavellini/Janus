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
import zlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from kernel.paths import FRAMES_ROOT, guard  # noqa: E402

# L51: retain every byte and timestamp while reducing synchronous compression work
# on the socket reader. Level 3 used ~59% less CPU than level 9 on the recorded
# sample, at 25-34% more compressed bytes. The gzip/JSONL format is unchanged.
CAPTURE_COMPRESSION_LEVEL = 3


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
    """Append-only, hour-rotated, gzip. One per venue socket.

    L81 (2026-09-12): the encode and the gzip write happen on a writer thread fed by a bounded
    queue, so a slow disk can never sit inside the socket's `recv()`; `write()` only enqueues.
    Order is the queue's order (one producer, one consumer); `flush()` drains the queue and flushes
    the file, `close()` drains and closes, so what a caller sees after either is what a reader
    sees. A full queue (`maxsize` frames, ~100 s at 1,000 frames/s) drops the frame and counts it
    in `dropped`: the lane's pricing must never block on its own evidence trail."""

    def __init__(self, venue: str, root: Path | str = FRAMES_ROOT, *, enforce_volume: bool = True,
                 maxsize: int = 100_000, threaded: bool = True):
        self.venue = venue
        self.root = Path(root).resolve()
        if enforce_volume:
            guard(self.root, "frame capture")
        self._key: tuple[str, str] | None = None
        self._fh = None
        self.frames = 0
        self.bytes = 0
        self.dropped = 0
        self._q = None
        self._thread = None
        self._error: BaseException | None = None
        if threaded:
            import queue
            import threading
            self._q = queue.Queue(maxsize=maxsize)
            self._thread = threading.Thread(target=self._drain, name=f"capture-{venue}", daemon=True)
            self._thread.start()

    def _drain(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is None:
                    return
                self._write_now(*item)
            except BaseException as exc:  # noqa: BLE001 -- the socket must not see a disk error
                self._error = exc
            finally:
                self._q.task_done()

    def _open_for(self, ts: float) -> None:
        key = _hour_key(ts)
        if key == self._key and self._fh is not None:
            return
        self._close_file()                      # never close(): that joins the queue this thread drains
        day, hour = key
        path = self.root / self.venue / day / f"{hour}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = gzip.open(path, "at", encoding="utf-8", compresslevel=CAPTURE_COMPRESSION_LEVEL)
        self._key = key

    def write(self, raw, *, received_utc: float | None = None,
              received_mono: float | None = None) -> None:
        """Persist one frame exactly as received. `raw` may be str, bytes or an already-parsed
        object (the last is serialised, but callers should pass the text)."""
        t = received_utc if received_utc is not None else time.time()
        m = received_mono if received_mono is not None else time.monotonic()
        if self._q is None:
            self._write_now(raw, t, m)
            return
        try:
            self._q.put_nowait((raw, t, m))
        except Exception:  # noqa: BLE001 -- queue.Full: the disk is behind; pricing goes on
            self.dropped += 1

    def _write_now(self, raw, t: float, m: float) -> None:
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
        if self._q is not None:
            self._q.join()
        if self._fh is not None:
            self._fh.flush()

    def _close_file(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._key = None

    def close(self) -> None:
        if self._q is not None:
            self._q.join()
            if self._thread is not None and self._thread.is_alive():
                self._q.put(None)
                self._thread.join(timeout=10.0)
            self._q = None
        self._close_file()

    def stats(self) -> dict:
        return {"venue": self.venue, "frames": self.frames, "bytes_uncompressed": self.bytes,
                "current": "/".join(self._key) if self._key else None}


#: Files whose stream was cut mid-member, by path: what was read before the cut is complete, the
#: rest of that hour is gone. Read by callers that want to say so (L27 reports it).
CORRUPT_FILES: dict[str, str] = {}


def prune_days(root: Path | str, venue: str, *, max_age_days: int, now: float | None = None) -> list[str]:
    """Delete this venue's frame DAY directories older than `max_age_days`, nothing else. Only a
    directory named YYYY-MM-DD directly under <root>/<venue> is a candidate, and it goes only when
    its date is before today minus `max_age_days` (UTC), so the newest `max_age_days` full days and
    today always stay. Returns the days removed, oldest first.

    L72 (2026-09-11): 21 GB of frames in four days on a 50 GB volume with no retention; the lane
    died in a commit and restart-looped 753 times. The cutoff is by the directory's capture date,
    never by mtime (an appended hour file has today's mtime whatever its day)."""
    import shutil
    if int(max_age_days) < 1:
        raise ValueError("max_age_days must be at least 1: today's frames are never pruned")
    t = now if now is not None else time.time()
    keep_from = datetime.fromtimestamp(t - int(max_age_days) * 86400, timezone.utc).strftime("%Y-%m-%d")
    base = Path(root) / venue
    removed: list[str] = []
    if not base.is_dir():
        return removed
    for d in sorted(base.iterdir()):
        if not d.is_dir() or len(d.name) != 10:
            continue
        try:
            datetime.strptime(d.name, "%Y-%m-%d")
        except ValueError:
            continue
        if d.name < keep_from:
            shutil.rmtree(d)
            removed.append(d.name)
    return removed


def read_frames(path: Path | str, venue: str | None = None) -> Iterator[Frame]:
    """Frames from one capture file, in the order they were received. A file cut mid-member (the
    lane died of a SIGBUS at 03:35:05Z 2026-09-05 and launchd appended a fresh member to the same
    hour) yields every frame before the cut and then stops; the cut is recorded in CORRUPT_FILES,
    never raised into a research run."""
    p = Path(path)
    v = venue or p.parent.parent.name
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        try:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    fr = Frame(v, float(d["t"]), d.get("m"), d["raw"])
                except (ValueError, KeyError, TypeError):
                    continue                    # a torn line at a cut: skip it, the stream error follows
                yield fr
        except EOFError:
            # The hour being written has no end-of-stream marker yet; what was flushed is complete
            # up to the last full line, and a replay over the live hour reads exactly that.
            return
        except (zlib.error, gzip.BadGzipFile, OSError) as exc:
            CORRUPT_FILES[str(p)] = f"{type(exc).__name__}: {exc}"
            return


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

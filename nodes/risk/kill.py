#!/usr/bin/env python3
"""Kill switches as files. Five scopes, one directory, no code path that can miss them.

    /Volumes/Kilos/janus/kill/all                 every mode that sends or simulates an order
    /Volumes/Kilos/janus/kill/live                LIMITED_LIVE and PRODUCTION
    /Volumes/Kilos/janus/kill/venue-<venue>       one venue
    /Volumes/Kilos/janus/kill/event-<event_id>    one game
    /Volumes/Kilos/janus/kill/strategy-<version>  one strategy version

A file's existence is the switch; its contents are the reason and the time, for the log. The
`live` switch is LATCHED automatically by the loss breaker and is reset only by a human deleting
the file (GATE_TO_LIVE standing requirements). `touch` and `rm` are the whole operator interface,
which is the point: a switch that needs a running process to honour a command is not a switch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

KILL_ROOT = Path("/Volumes/Kilos/janus/kill")


class KillSwitches:
    def __init__(self, root: Path | str = KILL_ROOT, *, enforce_volume: bool = True):
        self.root = Path(root)
        if enforce_volume and not str(self.root.resolve()).startswith("/Volumes/Kilos/"):
            raise ValueError("kill switches live on /Volumes/Kilos, never the root disk")

    def _present(self, name: str) -> bool:
        return (self.root / name).exists()

    def active(self, *, venue: str | None = None, event_id: str | None = None,
               strategy: str | None = None, live: bool = False, venues: tuple[str, ...] = ()) -> list[str]:
        """Every switch that applies to this action, by name. Empty means go."""
        out = []
        if self._present("all"):
            out.append("all")
        if live and self._present("live"):
            out.append("live")
        for v in (venue,) + tuple(venues):
            if v and self._present(f"venue-{v}"):
                out.append(f"venue-{v}")
        if event_id and self._present(f"event-{event_id}"):
            out.append(f"event-{event_id}")
        if strategy and self._present(f"strategy-{strategy}"):
            out.append(f"strategy-{strategy}")
        return sorted(set(out))

    def any_present(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_file())

    def latch(self, name: str, reason: str) -> Path:
        """Write a switch with its reason. Used by the breaker for `live`; a human may use it too."""
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / name
        p.write_text(json.dumps({"reason": reason, "latched_utc": time.time()}) + "\n")
        return p

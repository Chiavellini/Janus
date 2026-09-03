#!/usr/bin/env python3
"""Where Janus keeps its data. One root, read once, from JANUS_DATA_ROOT; the Mac's default is the
external volume. Every node that used to spell "/Volumes/Kilos/janus/..." reads it from here, so a
Linux box sets one variable and every guard, kill file, database and log follows.

THE GUARD STAYS. `under_data_root` is what `enforce_volume=True` checks: the data root exists and
the path is beneath it, compared both as written and resolved, so a symlinked root passes
consistently (before 2026-09-03 two guards resolved and two did not, and a symlink let the
database write while the kill switch refused to construct). The root disk is never the default.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_ROOT = "/Volumes/Kilos/janus"
DATA_ROOT = Path(os.environ.get("JANUS_DATA_ROOT") or DEFAULT_DATA_ROOT)

DB = DATA_ROOT / "tuples" / "tuples.sqlite"
PROOF_DB = DATA_ROOT / "tuples" / "proofs.sqlite"
KILL_ROOT = DATA_ROOT / "kill"
BREAKER_PATH = KILL_ROOT / "breaker.json"
OVERRIDE_PATH = KILL_ROOT / "arming_override.json"
FRAMES_ROOT = DATA_ROOT / "frames"
PROOFS = DATA_ROOT / "proofs"
RUN_INDEX = DATA_ROOT / "runs" / "index.jsonl"
LOGS = DATA_ROOT / "logs"
CREDENTIALS = DATA_ROOT / "credentials"
CATALOG = DATA_ROOT / "catalog"


def under_data_root(path: Path | str, root: Path | None = None) -> bool:
    """True when `path` is beneath the data root, as written or once resolved."""
    r = Path(root) if root is not None else DATA_ROOT
    p = Path(path)
    candidates = {str(p), str(p.resolve())}
    roots = {str(r), str(r.resolve())}
    return any(c == rr or c.startswith(rr.rstrip("/") + "/") for c in candidates for rr in roots)


def guard(path: Path | str, what: str) -> None:
    """Raise unless `path` is under the data root. `what` names the thing for the message."""
    if not under_data_root(path):
        raise ValueError(f"{what} must live under {DATA_ROOT} (JANUS_DATA_ROOT), never the root disk")

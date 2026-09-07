#!/usr/bin/env python3
"""The hash the arming override pins: the EXECUTABLE tree, not the whole checkout.

Until 2026-09-07 the override pinned `git rev-parse HEAD`, so a docs-only or research commit
deployed to the box invalidated the arm and cost the operator two pastes. The operator's answer
("Pin the code tree, one daily paste") is this file: one sha over the git tree ids of the paths
that decide what a running lane does. A change under any of them still invalidates the arm; a
change anywhere else does not.

    code_tree_sha(root)   -> 16 hex chars, "dirty" (uncommitted changes under a pinned path),
                             or "unknown" (git failed)
    runner_head_sha(root) -> the whole-checkout HEAD, for the record and the log

Both are read once at start by the lane and re-read on every report tick, so the values must be
cheap and must never raise.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

#: What the override pins, in this order. The order is part of the hash.
PINNED_PATHS: tuple[str, ...] = ("nodes", "grids", "kernel", "ops/run_node.sh", "ops/box/systemd")


def _git(root: Path | str, *args: str) -> str | None:
    """stdout of a git command run at `root`, or None on any failure (missing git, not a repo,
    a path absent from HEAD, a timeout). The caller decides what None means."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(root), timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def code_tree_sha(root: Path | str, paths: tuple[str, ...] = PINNED_PATHS) -> str:
    """sha256[:16] over the HEAD tree ids of `paths`; "dirty" when the working tree has
    uncommitted changes under any of them; "unknown" when git cannot answer."""
    status = _git(root, "status", "--porcelain", "--", *paths)
    if status is None:
        return "unknown"
    if status.strip():
        return "dirty"
    h = hashlib.sha256()
    for p in paths:
        tree_id = _git(root, "rev-parse", f"HEAD:{p}")
        if tree_id is None or not tree_id.strip():
            return "unknown"
        h.update(f"{p}={tree_id.strip()}\n".encode())
    return h.hexdigest()[:16]


def runner_head_sha(root: Path | str) -> str:
    """`git rev-parse HEAD` of the checkout, or "unknown". Informational since 2026-09-07."""
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out and out.strip() else "unknown"

#!/usr/bin/env python3
"""The override's pin covers the executable tree and nothing else: a commit under nodes/ moves it,
a commit to README.md does not, uncommitted code is "dirty", and no git at all is "unknown"."""
from __future__ import annotations

import subprocess
from pathlib import Path

from kernel.code_sha import PINNED_PATHS, code_tree_sha, runner_head_sha


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    for p in PINNED_PATHS:
        target = root / p
        if p.endswith(".sh"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("#!/bin/sh\n")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "a.py").write_text("x = 1\n")
    (root / "README.md").write_text("docs\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_the_pin_moves_with_code_and_not_with_docs(tmp_path: Path):
    root = _repo(tmp_path)
    base = code_tree_sha(root)
    assert len(base) == 16 and base not in ("dirty", "unknown")
    assert code_tree_sha(root) == base, "deterministic"
    head0 = runner_head_sha(root)
    assert len(head0) == 40

    (root / "README.md").write_text("docs, edited\n")
    _git(root, "commit", "-q", "-am", "docs only")
    assert code_tree_sha(root) == base, "a docs commit must not invalidate the arm"
    assert runner_head_sha(root) != head0, "the whole-checkout sha still moves (for the record)"

    (root / "nodes" / "a.py").write_text("x = 2\n")
    _git(root, "commit", "-q", "-am", "code")
    assert code_tree_sha(root) != base, "a code commit must invalidate the arm"


def test_uncommitted_code_is_dirty_and_no_git_is_unknown(tmp_path: Path):
    root = _repo(tmp_path)
    base = code_tree_sha(root)
    (root / "grids" / "a.py").write_text("x = 3\n")
    assert code_tree_sha(root) == "dirty"
    (root / "grids" / "a.py").write_text("x = 1\n")
    assert code_tree_sha(root) == base
    (root / "README.md").write_text("scratch\n")
    assert code_tree_sha(root) == base, "an uncommitted docs edit is not dirty code"

    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert code_tree_sha(plain) == "unknown"
    assert runner_head_sha(plain) == "unknown"
    assert code_tree_sha(tmp_path / "does-not-exist") == "unknown"

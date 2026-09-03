#!/usr/bin/env python3
"""One data root: the Mac default is unchanged, a box sets JANUS_DATA_ROOT, the guard treats a
symlinked root the same as written and resolved."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

from kernel import paths


def test_the_mac_defaults_are_unchanged():
    assert paths.DEFAULT_DATA_ROOT == "/Volumes/Kilos/janus"
    assert str(paths.DB).endswith("/tuples/tuples.sqlite") and str(paths.KILL_ROOT).endswith("/kill")
    assert str(paths.OVERRIDE_PATH).endswith("/kill/arming_override.json")


def test_the_guard_accepts_paths_under_the_root_as_written_or_resolved(tmp_path):
    real = tmp_path / "srv" / "janus"
    real.mkdir(parents=True)
    link = tmp_path / "Volumes" / "Kilos" / "janus"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    assert paths.under_data_root(link / "kill", root=link)             # as written
    assert paths.under_data_root(real / "kill", root=link)             # resolved form of the same root
    assert paths.under_data_root(link / "tuples" / "t.sqlite", root=real)
    assert not paths.under_data_root(tmp_path / "elsewhere", root=link)
    assert not paths.under_data_root("/tmp/x", root=link)


def test_a_box_sets_the_root_once_and_every_constant_follows(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUS_DATA_ROOT", str(tmp_path / "srv" / "janus"))
    mod = importlib.reload(paths)
    try:
        assert mod.DATA_ROOT == tmp_path / "srv" / "janus"
        assert mod.DB == tmp_path / "srv" / "janus" / "tuples" / "tuples.sqlite"
        assert mod.RUN_INDEX == tmp_path / "srv" / "janus" / "runs" / "index.jsonl"
        (tmp_path / "srv" / "janus" / "kill").mkdir(parents=True)
        mod.guard(tmp_path / "srv" / "janus" / "kill", "kill switches")
        try:
            mod.guard("/tmp/kill", "kill switches")
            raise AssertionError("the root disk must be refused")
        except ValueError as e:
            assert "JANUS_DATA_ROOT" in str(e)
    finally:
        monkeypatch.delenv("JANUS_DATA_ROOT")
        importlib.reload(paths)

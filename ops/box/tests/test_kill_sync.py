#!/usr/bin/env python3
"""The cross-host kill mirrors SSM into the box's kill files and never lifts a local latch."""
from __future__ import annotations

import json

from nodes.risk.kill import KillSwitches
from ops.box import kill_sync


class ParameterNotFound(Exception):
    pass


class FakeSSM:
    """The two calls kill_sync makes, over a dict. Raises the class boto3 would, by name."""

    def __init__(self, params: dict[str, str] | None = None):
        self.params = dict(params or {})
        self.calls = 0

    def get_parameter(self, *, Name: str):
        self.calls += 1
        if Name not in self.params:
            raise ParameterNotFound(Name)
        return {"Parameter": {"Name": Name, "Value": self.params[Name]}}


def test_a_parameter_latches_the_local_file_and_clearing_it_releases_only_an_ssm_latch(tmp_path):
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    ssm = FakeSSM()
    assert kill_sync.read_parameters(ssm) == {"all": None, "live": None}
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == [] and kill.any_present() == []

    ssm.params["/janus/kill/all"] = "2026-09-07T12:00:00Z bernardo@mac"
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == ["latched all (ssm)"]
    assert kill.active() == ["all"]
    assert json.loads((kill.root / "all").read_text())["reason"].startswith("ssm: 2026-09-07")
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == [], "idempotent"

    del ssm.params["/janus/kill/all"]
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == ["released all (ssm parameter cleared)"]
    assert kill.any_present() == []

    ssm.params["/janus/kill/live"] = "0"                        # "0" is clear, not set
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == [] and kill.any_present() == []


def test_a_breaker_or_human_latch_is_never_touched_from_ssm(tmp_path):
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    kill.latch("live", reason="breaker: realized loss 25.10 > 25.00")
    ssm = FakeSSM()
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == [], "no parameter: the breaker's file stays"
    assert kill.active(live=True) == ["live"]
    ssm.params["/janus/kill/live"] = "1"
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == [], "already latched: the reason is not rewritten"
    assert "breaker" in (kill.root / "live").read_text()
    del ssm.params["/janus/kill/live"]
    assert kill_sync.sync(kill_sync.read_parameters(ssm), kill) == [] and kill.active(live=True) == ["live"]
    (kill.root / "all").write_text("")                            # a human's `touch`: unreadable json
    assert kill_sync.sync({"all": None, "live": None}, kill) == [] and kill.active() == ["all"]


def test_main_runs_only_on_the_box_and_never_raises(tmp_path, capsys, monkeypatch):
    made = []

    def factory():
        made.append(1)
        return FakeSSM({"/janus/kill/all": "1"})

    assert kill_sync.main(client_factory=factory, env={}) == 0
    assert made == [] and "not the box" in capsys.readouterr().out
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    assert kill_sync.main(client_factory=factory, env={"JANUS_HOST": "box"}, kill=kill) == 0
    out = capsys.readouterr().out
    assert "all=set live=clear" in out and "latched all (ssm)" in out
    assert (tmp_path / "kill" / "all").exists()

    def boom():
        raise RuntimeError("no credentials")
    assert kill_sync.main(client_factory=boom, env={"JANUS_HOST": "box"}, kill=kill) == 1
    assert "kill_sync FAILED: RuntimeError" in capsys.readouterr().out

#!/usr/bin/env python3
"""A real clearance for tests, obtained the only way one can be: through nodes/risk.clear()."""
from __future__ import annotations

from kernel.schema import Mode
from nodes.risk.breaker import LossBreaker
from nodes.risk.clearance import Candidate, clear
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import ExposureLedger
from nodes.risk.limits import load_limits


def clearance_for(tmp_path, *, opportunity_id="o1", event_id="espn:mlb:1", mode=Mode.PAPER_EXECUTION,
                  legs=(("kalshi", 10.0, 0.44), ("polymarket", 10.0, 0.44)), now_mono=None):
    import time
    now_mono = time.monotonic() if now_mono is None else now_mono
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    breaker = LossBreaker(tmp_path / "kill" / "breaker.json", kill=kill, enforce_volume=False)
    cand = Candidate(opportunity_id, event_id, "mlb", tuple(legs), 8.0, 0.09, "v1", 0.5)
    c = clear(cand, mode=mode, limits=load_limits(), ledger=ExposureLedger(), kill=kill, breaker=breaker,
              fills_today=(), clock_healthy=True, fee_schedules_ok=True,
              balances={"kalshi": 500.0, "polymarket": 500.0},
              venues_connected={"kalshi": True, "polymarket": True}, now_mono=now_mono, now=1000.0)
    assert not hasattr(c, "code"), c
    return c

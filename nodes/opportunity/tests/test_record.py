#!/usr/bin/env python3
"""The one write path the supervisor and the replay share."""
from __future__ import annotations

from pathlib import Path

from kernel.schema import OpportunityStatus as S
from nodes.game_poller.tests.test_poller import FEES, mlb, sync_all
from nodes.opportunity.record import record_evaluation
from nodes.store_tuples.store import TupleStore

T = 1000.0


def test_a_priced_evaluation_lands_with_the_venues_own_hurdle(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    p = mlb()
    sync_all(p, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    ev = p.on_event("kalshi", "K_H", now=T)[-1]        # the 100-contract rung (the venues' smallest size, 3, is priced first since 2026-09-07)
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.status is S.PROFITABLE_UNEXECUTED and rec.wrote
    row = store.con.execute("SELECT status, gross, cost, required_ask_sum, cents_from_actionable, legs_json "
                            "FROM stream_evaluations").fetchone()
    assert row[0] == "PROFITABLE_UNEXECUTED" and abs(row[1] - 0.88) < 1e-9
    # the hurdle was priced through the SAME 0.5x / 0.05 schedules as the cover, so the distance
    # to actionable is consistent with the cover's own cost
    assert row[3] is not None and row[4] < 0, "already past actionable: negative distance"
    assert '"kalshi"' in row[5] and '"polymarket"' in row[5]
    assert not record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01).wrote, "gated"


def test_a_blocked_evaluation_lands_with_its_reason(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    p = mlb()
    ev = p.on_event("kalshi", "K_H", now=T)[0]
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.status is S.BLOCKED_STALE and rec.cost is None and rec.wrote
    assert store.con.execute("SELECT blocked_by FROM stream_evaluations").fetchone()[0]

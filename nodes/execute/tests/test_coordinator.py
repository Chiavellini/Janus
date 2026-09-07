#!/usr/bin/env python3
"""The machine, one rule per test. Paper venues on both sides; a fake venue for ambiguity."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from kernel.execution_protocol import Ack, OrderState
from kernel.schema import Book, ExecutionState as X, FillState, Mode, OpportunityStatus as S, Quote
from nodes.cover.cover import Leg, best_cover
from nodes.execute.coordinator import Coordinator
from nodes.execute.plan import marginal_price, plan_from_cover
from nodes.execute.records import ExecutionRecords
from nodes.execute.venues import build_venues
from nodes.execution.journal import Journal
from nodes.execution.testing import clearance_for
from nodes.opportunity.opportunity import Opportunity, OpportunityStore
from nodes.risk.kill import KillSwitches
from nodes.settle_wedge.fixtures import mlb_cover_proof
from nodes.store_tuples.store import TupleStore

T = 1000.0
PROOF = mlb_cover_proof(["away", "home"])
FEES_K = {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5}
FEES_P = {"fee_rate": 0.05}


def bk(levels):
    return Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=T)


def offers(pm_home=0.44, k_away=0.44, depth=5000):
    return {"home": [Leg("polymarket", "pm_clob", "P_H", "P_H", bk([(pm_home, depth)]), FEES_P)],
            "away": [Leg("kalshi", "kalshi_clob", "K_A", "K_A", bk([(k_away, depth)]), FEES_K)]}


class Clock:
    def __init__(self): self.t = T; self.m = 100.0
    def now(self): return self.t
    def mono(self): return self.m
    def sleep(self, s): self.t += s; self.m += s


def harness(tmp_path, mode=Mode.PAPER_EXECUTION, venues=None):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    journal = Journal(store)
    clk = Clock()
    vs = venues or build_venues(mode, journal, clock=clk.now, mono=clk.mono)
    opps = OpportunityStore(store)
    co = Coordinator(vs, ExecutionRecords(store), mode, hedge_deadline_s=3.0, poll_interval_s=0.1,
                     clock=clk.now, mono=clk.mono, sleep=clk.sleep, opportunities=opps)
    return co, vs, store, clk, opps


def plan_for(offs, q=100.0, oid="o1"):
    cov = best_cover(offs, q, now_utc=T, proof=PROOF)
    assert cov.ok
    p = plan_from_cover(opportunity_id=oid, event_id="espn:mlb:1", league="mlb", cov=cov, offers=offs)
    assert p is not None
    return p, cov


def test_the_plan_leads_with_polymarket_and_hedges_on_kalshi_at_the_walked_limit():
    p, cov = plan_for(offers())
    assert p.first.venue == "polymarket" and p.first.time_in_force == "fok" and p.first.side == "buy_yes"
    assert p.hedge.venue == "kalshi" and p.hedge.time_in_force == "ioc"
    assert p.first.limit_price == 0.44 and p.hedge.limit_price == 0.44
    assert p.max_cost_per_contract == pytest.approx(1 / 1.01)
    # the BUDGET is what the hedge may average if leg A paid 0.44: the cost ceiling minus fees minus 0.44
    assert p.hedge_budget(0.44) == pytest.approx(round(1 / 1.01 - cov.fee_per_contract - 0.44, 4))
    # the LIMIT is the level the pricer walked to (one level here), tightened only by leg-A overpay
    assert p.hedge_limit(0.44) == pytest.approx(0.44) and p.first.vwap == pytest.approx(0.44)
    assert p.hedge_limit(0.46) == pytest.approx(0.42), "two cents overpaid on leg A come off the hedge limit"
    assert marginal_price(bk([(0.40, 10), (0.45, 10)]), 15) == 0.45 and marginal_price(bk([(0.40, 10)]), 15) is None


def test_a_no_ladder_leg_becomes_buy_no_on_the_other_ticker():
    """Home via NO on the away market (0.44) beats YES on the home market (0.60): the hedge is a
    buy_no on K_A, which Kalshi expresses as an ask at 1 - price."""
    offs = {"home": [Leg("kalshi", "kalshi_clob", "K_H", "K_H", bk([(0.60, 5000)]), FEES_K),
                     Leg("kalshi", "kalshi_clob", "K_A:NO", "K_A", bk([(0.44, 5000)]), FEES_K)],
            "away": [Leg("polymarket", "pm_clob", "P_A", "P_A", bk([(0.44, 5000)]), FEES_P)]}
    p, _ = plan_for(offs)
    assert p.first.venue == "polymarket" and p.first.market_id == "P_A"
    assert p.hedge.venue == "kalshi" and p.hedge.market_id == "K_A" and p.hedge.side == "buy_no"


def test_happy_path_detected_to_hedged_with_every_transition_persisted(tmp_path):
    co, vs, store, clk, opps = harness(tmp_path)
    offs = offers()
    oid = Opportunity.id_for("espn:mlb:1", 100.0)
    p, cov = plan_for(offs, oid=oid)
    for v in vs.values():
        v.books = {"P_H": offs["home"][0].book, "K_A": offs["away"][0].book}
    opps.observe(event_id="espn:mlb:1", league="mlb", quantity=100.0, status=S.PROFITABLE_UNEXECUTED, now=T,
                 gross=0.88, fees=0.01, settlement_buffer=0.0, net_profit=10.0, locked_return=0.1, blocked_by=None, legs=[])
    ex = co.execute(p, clearance_for(tmp_path, opportunity_id=oid, now_mono=100.0), venues_connected={"kalshi": True, "polymarket": True})
    assert ex.state is X.HEDGED and ex.first_filled == 100.0 and ex.hedge_filled == 100.0 and ex.unhedged == 0.0
    states = [r[0] for r in store.con.execute("SELECT to_state FROM execution_transitions ORDER BY id").fetchall()]
    assert states == ["DETECTED", "VALIDATED", "CAPITAL_RESERVED", "LEG_A_SUBMITTED", "LEG_A_FILLED",
                      "LEG_B_SUBMITTED", "LEG_B_FILLED", "HEDGED"]
    assert opps.live[Opportunity.id_for("espn:mlb:1", 100.0)].status is S.HEDGED
    assert store.con.execute("SELECT COUNT(*) FROM orders WHERE state='FILLED'").fetchone()[0] == 2


def test_an_unfilled_first_leg_leaves_no_position_and_releases(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": bk([(0.44, 10)])}      # only 10 of 100: FOK fills nothing
    vs["kalshi"].books = {"K_A": offs["away"][0].book}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.ORDER_REJECTED and ex.released and ex.first_filled == 0.0
    assert not any(v.fills(since_utc=0) for v in vs.values())


@dataclass
class AmbiguousVenue:
    """Submit never answers; status says whatever the script says."""
    venue: str
    journal: Journal
    mode: Mode
    statuses: list
    def submit(self, req, clearance):
        assert clearance.consume(100.0, hedge=req.hedge), "the gate would have consumed it"
        self.journal.pending(req, mode=self.mode.value, now=T)
        return Ack(self.venue, req.client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "TRANSPORT", T)
    def status(self, cid):
        st = self.statuses.pop(0) if self.statuses else FillState.UNCONFIRMED
        filled = 100.0 if st is FillState.FILLED else 0.0
        return OrderState(self.venue, cid, "v1" if st is not FillState.UNCONFIRMED else None, st, filled,
                          0.44 if filled else None, None, st.value.lower(), T, final=st is not FillState.UNCONFIRMED)
    def cancel(self, cid): return self.status(cid)
    def fills(self, *, since_utc): return []
    def balance(self): return None
    def cancel_all(self): return 0


def test_an_unconfirmed_first_leg_is_polled_never_resubmitted_and_keeps_the_reservation(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    journal = Journal(store)
    clk = Clock()
    pm = AmbiguousVenue("polymarket", journal, Mode.PAPER_EXECUTION, statuses=[])
    from nodes.execution.paper import PaperVenue
    k = PaperVenue("kalshi", journal, clock=clk.now, mono=clk.mono)
    co = Coordinator({"polymarket": pm, "kalshi": k}, ExecutionRecords(store), Mode.PAPER_EXECUTION,
                     hedge_deadline_s=1.0, poll_interval_s=0.25, clock=clk.now, mono=clk.mono, sleep=clk.sleep)
    p, _ = plan_for(offers())
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and not ex.released
    assert store.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1, "one submit, ever"
    assert journal.get(ex.first_client_id)["state"] == "UNCONFIRMED"


def test_an_unconfirmed_first_leg_that_turns_out_filled_is_hedged(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    journal = Journal(store)
    clk = Clock()
    pm = AmbiguousVenue("polymarket", journal, Mode.PAPER_EXECUTION, statuses=[FillState.UNCONFIRMED, FillState.FILLED])
    from nodes.execution.paper import PaperVenue
    offs = offers()
    k = PaperVenue("kalshi", journal, clock=clk.now, mono=clk.mono, books={"K_A": offs["away"][0].book})
    co = Coordinator({"polymarket": pm, "kalshi": k}, ExecutionRecords(store), Mode.PAPER_EXECUTION,
                     hedge_deadline_s=3.0, poll_interval_s=0.1, clock=clk.now, mono=clk.mono, sleep=clk.sleep)
    p, _ = plan_for(offs)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_filled == 100.0


def test_the_hedge_is_for_exactly_what_leg_a_filled_and_stops_at_the_limit(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 60), (0.90, 5000)])}      # 60 at the limit, then far above
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.first_filled == 100.0 and ex.hedge_filled == 60.0 and ex.unhedged == 40.0
    assert ex.state is X.PARTIAL_FILL and not ex.released
    assert store.con.execute("SELECT unhedged FROM executions").fetchone()[0] == 40.0
    assert co.records.open_unhedged() == [(ex.execution_id, 40.0)]


def test_a_hedge_book_entirely_above_the_limit_is_slippage_exceeded_not_a_chase(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.70, 5000)])}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGE_SLIPPAGE_EXCEEDED and ex.unhedged == 100.0
    n = store.con.execute("SELECT COUNT(*) FROM orders WHERE venue='kalshi'").fetchone()[0]
    assert 1 <= n <= 3, "bounded attempts inside the deadline, never a chase"


def test_a_kill_switch_or_disconnect_before_leg_a_aborts_and_releases(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    p, _ = plan_for(offers())
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0), venues_connected={"kalshi": False, "polymarket": True})
    assert ex.state is X.VENUE_DISCONNECTED and ex.released
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    kill.latch("venue-kalshi", "t")
    co.kill = kill
    ex2 = co.execute(p, clearance_for(tmp_path / "b", now_mono=100.0))
    assert ex2.state is X.ORDER_REJECTED and "kill" in ex2.detail


def test_shadow_mode_sends_nothing_and_records_the_refusal(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path, mode=Mode.SHADOW_LIVE)
    p, _ = plan_for(offers())
    ex = co.execute(p, clearance_for(tmp_path, mode=Mode.PAPER_EXECUTION, now_mono=100.0))
    assert ex.state is X.ORDER_REJECTED and "SHADOW" in ex.detail
    assert vs["polymarket"].intents == 1 and vs["kalshi"].intents == 0


def test_the_factory_refuses_real_modes_without_real_adapters(tmp_path):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    with pytest.raises(ValueError):
        build_venues(Mode.LIMITED_LIVE, j)
    with pytest.raises(ValueError):
        build_venues(Mode.DEMO_EXECUTION, j)
    assert set(build_venues(Mode.OFFLINE_REPLAY, j)) == {"kalshi", "polymarket"}



def test_a_polymarket_no_leg_plans_as_buy_yes_of_the_no_token():
    """Three-way soccer as two legs: Kalshi YES home + Polymarket NO home (covering draw and away).
    Polymarket outcomes are separate tokens, so the NO leg is a buy_yes of the NO token id."""
    from nodes.settle_wedge.fixtures import epl_cover_proof
    from nodes.cover.cover import best_cover
    proof = epl_cover_proof(["home", "draw", "away"])
    offs = {"home": [Leg("kalshi", "kalshi_clob", "K_H", "K_H", bk([(0.40, 5000)]), FEES_K)],
            "draw": [Leg("polymarket", "pm_clob", "P_D", "P_D", bk([(0.30, 5000)]), FEES_P)],
            "away": [Leg("polymarket", "pm_clob", "P_A", "P_A", bk([(0.36, 5000)]), FEES_P)],
            "away|draw": [Leg("polymarket", "pm_clob", "P_H:NO", "P_H_NO", bk([(0.50, 5000)]), FEES_P, covers=frozenset({"away", "draw"}))]}
    cov = best_cover(offs, 100.0, now_utc=T, proof=proof)
    assert cov.ok and len(cov.legs) == 2
    p = plan_from_cover(opportunity_id="o", event_id="e", league="epl", cov=cov, offers=offs)
    assert p is not None
    assert p.first.venue == "polymarket" and p.first.market_id == "P_H_NO" and p.first.side == "buy_yes" and p.first.outcome_id == "P_H:NO"
    assert p.hedge.venue == "kalshi" and p.hedge.market_id == "K_H" and p.hedge.side == "buy_yes"


#: MIL @ CIN, 2026-09-05 00:49:35Z, execution 69852b86 -- the exact ladders from books_json. F3's
#: first unhedged paper leg: the pricer walked Kalshi to 0.85 for q=100 (64.18 @ 0.84 + 35.82 @
#: 0.85, VWAP 0.8436) while the coordinator sent the 0.8452 VWAP budget as the IOC limit.
MIL_CIN_2026_09_04 = {
    "cin": [Leg("polymarket", "pm_clob", "P_CIN", "P_CIN", bk([(0.13, 21604.45)]), FEES_P)],
    "mil": [Leg("kalshi", "kalshi_clob", "K_MIL", "K_MIL", bk([(0.84, 64.18), (0.85, 155.0), (0.86, 10.0)]), FEES_K)],
}


def test_the_hedge_limit_is_the_walked_level_not_the_vwap_budget_mil_cin(tmp_path):
    co, vs, store, clk, opps = harness(tmp_path)
    offs = MIL_CIN_2026_09_04
    oid = Opportunity.id_for("espn:mlb:401816802", 100.0)
    p, cov = plan_for(offs, oid=oid)
    assert p.hedge.limit_price == pytest.approx(0.85), "the pricer walked into the 0.85 level"
    assert p.hedge.vwap == pytest.approx((64.18 * 0.84 + 35.82 * 0.85) / 100)
    budget = p.hedge_budget(0.13)
    assert budget < 0.85 and budget > p.hedge.vwap, "the VWAP clears the budget; the marginal level does not"
    assert p.hedge_limit(0.13) == pytest.approx(0.85)
    for v in vs.values():
        v.books = {"P_CIN": offs["cin"][0].book, "K_MIL": offs["mil"][0].book}
    opps.observe(event_id="espn:mlb:401816802", league="mlb", quantity=100.0, status=S.PROFITABLE_UNEXECUTED, now=T,
                 gross=0.97, fees=0.01, settlement_buffer=0.0, net_profit=1.5, locked_return=0.015, blocked_by=None, legs=[])
    ex = co.execute(p, clearance_for(tmp_path, opportunity_id=oid, now_mono=100.0), venues_connected={"kalshi": True, "polymarket": True})
    assert ex.state is X.HEDGED and ex.unhedged == 0.0 and ex.hedge_filled == pytest.approx(100.0)
    assert ex.hedge_avg_price == pytest.approx(0.8436, abs=1e-4)
    details = [r[0] for r in store.con.execute("SELECT detail FROM execution_transitions WHERE to_state='LEG_B_SUBMITTED'").fetchall()]
    assert details == [f"attempt 1 limit 0.8500 budget {budget:.4f}"], details
    assert "ABOVE_BUDGET" not in ex.detail, "0.8436 averaged under the budget: a cover at the hurdle"
    # every execution-owned status change now lands in opportunity_transitions (F3's predicate)
    moves = [r[0] for r in store.con.execute("SELECT to_status FROM opportunity_transitions WHERE opportunity_id=? ORDER BY id", (oid,)).fetchall()]
    assert moves[-2:] == ["EXECUTION_PENDING", "HEDGED"], moves


def test_leg_a_overpay_tightens_the_limit_and_a_moved_book_is_slippage_not_a_chase(tmp_path):
    co, vs, store, clk, opps = harness(tmp_path)
    offs = MIL_CIN_2026_09_04
    p, _ = plan_for(offs)
    # pure arithmetic: leg A averaging 0.15 against a priced 0.13 takes two ticks off the hedge limit.
    # (A limit FOK never fills ABOVE its limit, so overpay is bounded by limit - vwap on a layered book.)
    assert p.hedge_limit(0.15) == pytest.approx(0.83) and p.hedge_limit(0.13) == pytest.approx(0.85)
    # the Kalshi book moved above the walked 0.85 between pricing and the hedge: HEDGE_SLIPPAGE_EXCEEDED,
    # leg A held, nothing chased, capital kept (a holding failure, not terminal)
    vs["polymarket"].books = {"P_CIN": offs["cin"][0].book}
    vs["kalshi"].books = {"K_MIL": bk([(0.86, 155.0), (0.87, 10.0)])}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0), venues_connected={"kalshi": True, "polymarket": True})
    assert ex.state is X.HEDGE_SLIPPAGE_EXCEEDED and ex.first_filled == 100.0 and ex.hedge_filled == 0.0 and not ex.released
    assert X.HEDGE_SLIPPAGE_EXCEEDED.holds_position and not X.HEDGE_SLIPPAGE_EXCEEDED.is_terminal


def test_a_hedge_that_averages_above_the_budget_is_still_a_cover_and_says_so(tmp_path):
    """The book moved between pricing and the hedge: the 0.84 level is gone, 0.85 remains. The IOC at
    the walked level fills the whole hedge at 0.85 -- above the VWAP budget, below the hurdle, and
    labelled. Hedging beats an unhedged leg (plan.py docstring)."""
    co, vs, store, clk, opps = harness(tmp_path)
    offs = MIL_CIN_2026_09_04
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_CIN": offs["cin"][0].book}
    vs["kalshi"].books = {"K_MIL": bk([(0.85, 155.0), (0.86, 10.0)])}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0), venues_connected={"kalshi": True, "polymarket": True})
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.85) and "ABOVE_BUDGET" in ex.detail


def test_paper_fills_carry_the_pinned_fee_when_the_venue_knows_its_params(tmp_path):
    co, vs, store, clk, opps = harness(tmp_path)
    offs = offers()
    p, cov = plan_for(offs)
    for v in vs.values():
        v.books = {"P_H": offs["home"][0].book, "K_A": offs["away"][0].book}
    vs["kalshi"].fee_params = dict(FEES_K); vs["polymarket"].fee_params = dict(FEES_P)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0), venues_connected={"kalshi": True, "polymarket": True})
    assert ex.state is X.HEDGED
    fees = {r[0]: r[1] for r in store.con.execute("SELECT venue, fee_usd FROM orders WHERE state='FILLED'").fetchall()}
    assert fees["kalshi"] > 0 and fees["polymarket"] > 0, fees
    assert fees["kalshi"] + fees["polymarket"] == pytest.approx(cov.fee_per_contract * 100, rel=0.05), "the cover priced these fees"


# ── 2026-09-07: the settle-ack rule, one hedge window, stage stamps ──────────
class ScriptedVenue(AmbiguousVenue):
    """Like AmbiguousVenue, but each scripted status carries its own `final` flag."""
    def __init__(self, venue, journal, mode, script):
        super().__init__(venue, journal, mode, statuses=[])
        self.script = list(script)          # [(FillState, final)]
        self.polls = 0
    def status(self, cid):
        self.polls += 1
        st, final = self.script.pop(0) if self.script else (FillState.UNFILLED, False)
        filled = 100.0 if st is FillState.FILLED else 0.0
        return OrderState(self.venue, cid, "v1", st, filled, 0.44 if filled else None, None, st.value.lower(), T, final=final)


def _scripted(tmp_path, script, *, deadline=1.0):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    journal = Journal(store)
    clk = Clock()
    pm = ScriptedVenue("polymarket", journal, Mode.PAPER_EXECUTION, script)
    from nodes.execution.paper import PaperVenue
    offs = offers()
    k = PaperVenue("kalshi", journal, clock=clk.now, mono=clk.mono, books={"K_A": offs["away"][0].book})
    co = Coordinator({"polymarket": pm, "kalshi": k}, ExecutionRecords(store), Mode.PAPER_EXECUTION,
                     hedge_deadline_s=deadline, poll_interval_s=0.1, clock=clk.now, mono=clk.mono, sleep=clk.sleep)
    p, _ = plan_for(offs)
    return co, pm, store, clk, p


def test_a_non_final_unfilled_status_is_not_an_answer_the_venue_may_still_fill(tmp_path):
    """Polymarket DELAYED reads as UNFILLED, final=False. Releasing on it double-spent the reservation."""
    co, pm, store, clk, p = _scripted(tmp_path, [(FillState.UNFILLED, False), (FillState.UNFILLED, False), (FillState.FILLED, True)])
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.first_filled == 100.0 and pm.polls == 3
    assert ex.stages["a_polls"] == 3


def test_a_status_that_never_turns_final_is_unknown_provider_state_and_keeps_the_reservation(tmp_path):
    co, pm, store, clk, p = _scripted(tmp_path, [(FillState.UNFILLED, False)] * 50, deadline=1.0)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and not ex.released
    assert store.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1, "never resubmitted"


def test_the_first_status_poll_is_immediate_and_the_interval_is_slept_between_polls(tmp_path):
    co, pm, store, clk, p = _scripted(tmp_path, [(FillState.FILLED, True)])
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and pm.polls == 1
    assert clk.m == 100.0, "one poll, zero sleeps: the blind 100 ms is gone"
    co, pm, store, clk, p = _scripted(tmp_path / "b", [(FillState.UNFILLED, False), (FillState.FILLED, True)])
    ex = co.execute(p, clearance_for(tmp_path / "b", now_mono=100.0))
    assert ex.state is X.HEDGED and pm.polls == 2 and clk.m == pytest.approx(100.1)


def test_the_hedge_window_is_the_clearance_s_and_starts_when_leg_a_is_known(tmp_path):
    """A slow leg A settle must not spend the hedge's window (CLEARANCE_SPENT with leg A filled)."""
    script = [(FillState.UNFILLED, False)] * 25 + [(FillState.FILLED, True)]      # 2.5 s of polling
    co, pm, store, clk, p = _scripted(tmp_path, script, deadline=3.0)
    c = clearance_for(tmp_path, now_mono=100.0)
    ex = co.execute(p, c)
    assert ex.state is X.HEDGED, ex.detail
    assert c.hedge_deadline_mono == pytest.approx(clk.m - 0.0, abs=3.0) and c.hedge_deadline_mono > 102.5 + 2.9


def test_hedge_unavailable_holds_a_position_and_is_not_terminal():
    assert X.HEDGE_UNAVAILABLE.holds_position and not X.HEDGE_UNAVAILABLE.is_terminal


def test_stage_stamps_are_recorded_monotone_and_persisted(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    for v in vs.values():
        v.books = {"P_H": offs["home"][0].book, "K_A": offs["away"][0].book}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0), pre_stages={"frame_to_eval_ms": 3.5, "clear_ms": 1.0})
    assert ex.state is X.HEDGED, ex.detail
    keys = ["a_submit_ms", "a_ack_ms", "a_settled_ms", "b_submit_ms", "b_ack_ms", "b_settled_ms", "done_ms"]
    vals = [ex.stages[k] for k in keys]
    assert vals == sorted(vals) and ex.stages["frame_to_eval_ms"] == 3.5 and "db_ms" in ex.stages
    row = json.loads(store.con.execute("SELECT stages_json FROM executions WHERE execution_id=?", (ex.execution_id,)).fetchone()[0])
    assert row == ex.stages

#!/usr/bin/env python3
"""The machine, one rule per test. Paper venues on both sides; a fake venue for ambiguity."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from kernel.execution_protocol import Ack, OrderState
from kernel.schema import Book, ExecutionState as X, FillState, Mode, OpportunityStatus as S, Quote
from nodes.cover.cover import Leg, best_cover
from nodes.execute.coordinator import Coordinator
from nodes.execute.plan import marginal_price, plan_from_cover, pm_wire_ok
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


#: These plans (MIL @ CIN 2026-09-05 among them) are exact replays priced at the 1 % hurdle of their
#: day; the hurdle moved to 0.5 % on 2026-09-12 and the mechanics under test do not depend on it.
HURDLE_2026_09_05 = 0.01


def plan_for(offs, q=100.0, oid="o1", hurdle=HURDLE_2026_09_05):
    cov = best_cover(offs, q, now_utc=T, proof=PROOF)
    assert cov.ok
    p = plan_from_cover(opportunity_id=oid, event_id="espn:mlb:1", league="mlb", cov=cov, offers=offs, hurdle=hurdle)
    assert p is not None
    return p, cov


def test_the_plan_s_default_hurdle_is_the_runner_s_constant():
    from nodes.opportunity.thresholds import EXECUTION_MIN_LOCKED_RETURN
    cov = best_cover(offers(), 100.0, now_utc=T, proof=PROOF)
    p = plan_from_cover(opportunity_id="o1", event_id="espn:mlb:1", league="mlb", cov=cov, offers=offers())
    assert p.max_cost_per_contract == pytest.approx(1 / (1 + EXECUTION_MIN_LOCKED_RETURN)) and EXECUTION_MIN_LOCKED_RETURN == 0.005


def test_the_plan_leads_with_polymarket_and_hedges_on_kalshi_at_the_walked_limit():
    p, cov = plan_for(offers())
    assert p.first.venue == "polymarket" and p.first.time_in_force == "ioc" and p.first.side == "buy_yes"   # FAK since 2026-09-07
    assert p.hedge.venue == "kalshi" and p.hedge.time_in_force == "ioc"
    assert p.first.limit_price == 0.45 and p.hedge.limit_price == 0.44   # the first leg one tick above the walked 0.44 (2026-09-07)
    assert p.max_cost_per_contract == pytest.approx(1 / 1.01)
    # the BUDGET is what the hedge may average if leg A paid 0.44: the cost ceiling minus fees minus 0.44
    assert p.hedge_budget(0.44) == pytest.approx(round(1 / 1.01 - cov.fee_per_contract
                                                      - (cov.settlement_buffer_per_contract or 0.0) - 0.44, 4))
    # the LIMIT is the level the pricer walked to (one level here), tightened only by leg-A overpay
    assert p.hedge_limit(0.44) == pytest.approx(0.44) and p.first.vwap == pytest.approx(0.44)
    assert p.hedge_limit(0.46) == pytest.approx(0.42), "two cents overpaid on leg A come off the hedge limit"
    assert marginal_price(bk([(0.40, 10), (0.45, 10)]), 15) == 0.45 and marginal_price(bk([(0.40, 10)]), 15) is None


def test_settlement_reserve_is_in_every_execution_budget_and_can_remove_the_entry_pad():
    """The opportunity cost already includes the bounded settlement wedge. The execution plan
    must not spend that reserve again as price room on leg A or the hedge chase."""
    offs = offers(pm_home=0.45, k_away=0.50)
    cov = best_cover(offs, 100.0, now_utc=T, proof=PROOF)
    assert cov.ok and cov.settlement_buffer_per_contract == 0.0
    reserved = replace(cov, cost_per_contract=cov.cost_per_contract + 0.01,
                       settlement_buffer_per_contract=0.01)
    p = plan_from_cover(opportunity_id="o", event_id="e", league="mlb", cov=reserved, offers=offs, hurdle=HURDLE_2026_09_05)
    assert p is not None and p.settlement_buffer_per_contract == 0.01
    assert p.first.limit_price == 0.45, "the one-tick pad would spend the settlement reserve"
    assert p.hedge_budget(0.45) == pytest.approx(round(1 / 1.01 - cov.fee_per_contract - 0.01 - 0.45, 4))
    assert p.hedge_break_even(0.45) == pytest.approx(round(1 - cov.fee_per_contract - 0.01 - 0.45, 4))


def off_grid_offers(pm_level, k_level, *, pm_tick=0.01, depth=5000.0):
    """A Polymarket ask quoted off the grid the leg itself declares (the L99 inputs)."""
    return {"home": [Leg("polymarket", "pm_clob", "P_H", "P_H", bk([(pm_level, depth)]), FEES_P, tick=pm_tick)],
            "away": [Leg("kalshi", "kalshi_clob", "K_A", "K_A", bk([(k_level, depth)]), FEES_K, tick=0.01)]}


def test_the_entry_limit_is_snapped_up_to_its_own_tick_and_refused_when_that_breaks_the_economics():
    """L99 (2026-09-13): leg A reached the venue off tick, and the wire silently re-priced it DOWN.

    17 of the 216 executions after the 08:03Z release were planned with a three-decimal Polymarket
    limit on a two-decimal grid: `marginal_price` hands back the book's level verbatim and the
    entry pad adds one tick to it, so both inherit whatever grid that level was quoted on. A
    0.814 ask under a declared 0.01 tick planned 0.814, padded to 0.824. The hedge has been
    tick-snapped since 2026-09-08; leg A never was.

    Downstream, the adapter's cent-exact search is the only thing that repairs an off-grid price
    and it searches DOWNWARD: 0.471 goes to the wire as 0.47, which cannot take the 0.471 ask the
    cover was walked against ("leg A unfilled (FAK): no position"). So the snap has to be UP, at
    the layer that owns the economics, and a raised BUY limit that no longer clears the plan's own
    ceiling must be refused rather than sent.
    """
    from nodes.exec_polymarket.client import PyClobTransport

    offs = off_grid_offers(0.814, 0.15)
    cov = best_cover(offs, 10.0, now_utc=T, proof=PROOF)
    assert cov.ok
    p = plan_from_cover(opportunity_id="o", event_id="e", league="mlb", cov=cov, offers=offs)
    assert p is not None
    # was 0.824 (0.814 + one tick), three decimals on a two-decimal grid
    assert p.first.limit_price == 0.82, "the entry limit must sit on the tick the leg declares"
    assert p.first.limit_price / p.first.tick == pytest.approx(round(p.first.limit_price / p.first.tick))
    assert p.first.limit_price >= 0.814, "a BUY limit floored lands under the level it was priced from"
    # The economics hold AT THE PRICE SENT, with that price's own fee -- not at the walked level.
    assert (p.first.limit_price + p.hedge.vwap + p.fee_per_contract
            + p.settlement_buffer_per_contract) <= p.max_cost_per_contract + 1e-9
    # ... and the wire no longer has to move it: the venue rejects on the AMOUNTS (a market BUY's
    # maker amount is collateral and must land on a whole cent), and the repair that enforces that
    # now finds the price already on the grid, so the order can still take the level.
    assert PyClobTransport._cent_exact_buy(size=10.0, price=p.first.limit_price,
                                           tick=p.first.tick) == (0.82, 10.0)

    # A cover that only clears while the limit is off tick is REFUSED, not sent off tick.
    thin = off_grid_offers(0.638, 0.33)
    cov_thin = best_cover(thin, 10.0, now_utc=T, proof=PROOF)
    assert cov_thin.ok, "the cover prices at the off-grid level; only the snapped entry breaks it"
    assert plan_from_cover(opportunity_id="o", event_id="e", league="mlb", cov=cov_thin, offers=thin) is None

    # An on-grid book is untouched: the one-tick pad still applies (0.44 -> 0.45).
    assert plan_for(offers())[0].first.limit_price == 0.45


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
    vs["polymarket"].books = {"P_H": bk([(0.60, 5000)])}    # the book moved past the limit: FAK fills nothing
    vs["kalshi"].books = {"K_A": offs["away"][0].book}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.ORDER_UNFILLED and ex.released and ex.first_filled == 0.0
    # and a book with only part of the size at the limit fills that part, hedged for exactly it (FAK, 2026-09-07)
    co2, vs2, store2, clk2, _ = harness(tmp_path / "p")
    vs2["polymarket"].books = {"P_H": bk([(0.44, 10)])}
    vs2["kalshi"].books = {"K_A": offs["away"][0].book}
    ex2 = co2.execute(p, clearance_for(tmp_path / "p", now_mono=100.0))
    assert ex2.state is X.HEDGED and ex2.first_filled == 10.0 and ex2.hedge_filled == 10.0 and ex2.unhedged == 0.0
    assert not any(v.fills(since_utc=0) for v in vs.values())


def test_a_zero_filled_leg_a_records_the_book_again_afterwards(tmp_path):
    """L102 (2026-09-14): a pre-send confirm cannot separate "the book advertised size the engine would
    not honour" from "we lost a race" -- in BOTH worlds it shows a level at our price with our size.
    Measured, it has no discriminating power at all: 15 of 16 confirmed zero-fills AND 6 of 6 confirmed
    fills had the full size at or below the limit. The SECOND read, after the venue's terminal answer,
    is what separates them -- size still resting there was taken by nobody.

    The fixture is the hypothesis in miniature: the confirm shows the whole size at the limit while the
    venue fills none of it."""
    co, vs, store, _, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": bk([(0.60, 5000)])}      # the engine honours nothing at our limit
    vs["kalshi"].books = {"K_A": offs["away"][0].book}
    confirmed = bk([(p.first.limit_price, 4000.0), (round(p.first.limit_price + 0.01, 4), 900.0)])
    co.fresh_book = lambda venue, market, side: (confirmed if venue == "polymarket"
                                                 else vs[venue].books.get(market))
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.ORDER_UNFILLED and ex.first_filled == 0.0

    before = ex.protect["first_leg_confirm"]
    assert before["ladder"][0] == [p.first.limit_price, 4000.0], "the ladder carries SIZES, not a price alone"
    assert before["at_mono"] is not None and before["at_utc"] is not None
    assert before["source"] == confirmed.source and before["fetched_utc"] == confirmed.fetched_utc
    # and it states what was actually SENT, which a downsize or a reprice can move away from the plan
    assert before["sent"]["contracts"] == p.first.contracts and before["sent"]["price"] == p.first.limit_price

    after = ex.protect["first_leg_post"]
    assert after["why"] == "unfilled", "recorded on the path that holds no position"
    assert after["at_mono"] >= before["at_mono"] and after["ladder"], "the book is read AGAIN, afterwards"
    assert "a_post_confirm_ms" in ex.stages


def test_a_partial_fill_is_not_delayed_by_the_post_mortem_read(tmp_path):
    """L102: the same read on a PARTIAL would sit between the fill and the hedge, and hedge latency is
    what costs the most money here (median 3.0c of slippage against 0.67c of margin). One partial in
    141 orders does not justify paying that, so the instrumentation stops where a position begins."""
    co, vs, store, _, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": bk([(0.44, 10)])}        # only part of the size fills
    vs["kalshi"].books = {"K_A": offs["away"][0].book}
    co.fresh_book = lambda venue, market, side: (bk([(p.first.limit_price, 4000.0)]) if venue == "polymarket"
                                                 else vs[venue].books.get(market))
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert 0 < ex.first_filled < p.first.contracts, "a genuine partial"
    assert "first_leg_post" not in ex.protect and "a_post_confirm_ms" not in ex.stages


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


def test_a_real_unconfirmed_first_leg_latches_live_before_any_retry(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    journal = Journal(store)
    clk = Clock()
    pm = AmbiguousVenue("polymarket", journal, Mode.LIMITED_LIVE, statuses=[])
    from nodes.execution.paper import PaperVenue
    k = PaperVenue("kalshi", journal, clock=clk.now, mono=clk.mono)
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    co = Coordinator({"polymarket": pm, "kalshi": k}, ExecutionRecords(store), Mode.LIMITED_LIVE,
                     hedge_deadline_s=1.0, poll_interval_s=0.25, clock=clk.now, mono=clk.mono,
                     sleep=clk.sleep, kill=kill)
    p, _ = plan_for(offers())
    ex = co.execute(p, clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=100.0))
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and not ex.released
    assert kill.active(live=True) == ["live"]


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


def test_the_hedge_is_for_exactly_what_leg_a_filled_and_the_rest_is_chased_only_inside_the_cap(tmp_path):
    """60 at the walked limit, the rest sits at 0.90: the chase goes to the budget and on to the loss
    cap (about 0.53 here) and stops; with the unwind off the 40 stay a held PARTIAL_FILL (2026-09-08)."""
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 60), (0.90, 5000)])}      # 60 at the limit, then far above
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.first_filled == 100.0 and ex.hedge_filled == 60.0 and ex.unhedged == 40.0
    assert ex.state is X.PARTIAL_FILL and not ex.released
    caps = [a["ceiling"] for a in ex.protect["attempts"] if a.get("phase") == "loss_cap"]
    assert caps and max(a["limit"] for a in ex.protect["attempts"]) == caps[-1] < 0.90, "chased to the cap, never to 0.90"
    assert store.con.execute("SELECT unhedged FROM executions").fetchone()[0] == 40.0
    assert co.records.open_unhedged() == [(ex.execution_id, 40.0)]


def test_a_hedge_book_entirely_above_the_cap_is_chased_to_the_cap_then_held_and_paged(tmp_path):
    """Until 2026-09-08 this was 'slippage exceeded, not a chase' after three IOCs at one price. Now
    the limit is raised tick by tick to the budget and on to the loss cap; a book at 0.70 is never
    reached, the position is a held failure, and on_unprotected fires (the lane latches the kill)."""
    co, vs, store, clk, _ = harness(tmp_path)
    paged = []
    co.on_unprotected = lambda ex, text: paged.append(text)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.70, 5000)])}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGE_SLIPPAGE_EXCEEDED and ex.unhedged == 100.0 and not ex.released
    n = store.con.execute("SELECT COUNT(*) FROM orders WHERE venue='kalshi'").fetchone()[0]
    assert 4 <= n <= 12, "phase 1's three, then the chase, all inside max_protect_submits"
    phases = [a["phase"] for a in ex.protect["attempts"]]
    assert phases[:3] == ["walked"] * 3 and "budget" in phases and "loss_cap" in phases
    last = ex.protect["attempts"][-1]
    paid = ex.first_avg_price
    assert last["limit"] == pytest.approx(round(p.hedge_break_even(paid) + 0.01, 2), abs=0.011), "the cap: break-even plus $0.01 a contract"
    assert paged and paged[0].startswith("UNPROTECTED: 100 unhedged") and "unwind disabled" in paged[0]
    assert "UNPROTECTED" in ex.detail


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


def test_leg_a_overpay_tightens_the_limit_and_a_moved_book_is_chased_inside_the_cap(tmp_path):
    co, vs, store, clk, opps = harness(tmp_path)
    offs = MIL_CIN_2026_09_04
    p, _ = plan_for(offs)
    # pure arithmetic: leg A averaging 0.15 against a priced 0.13 takes two ticks off the hedge limit.
    # (A limit FOK never fills ABOVE its limit, so overpay is bounded by limit - vwap on a layered book.)
    assert p.hedge_limit(0.15) == pytest.approx(0.83) and p.hedge_limit(0.13) == pytest.approx(0.85)
    # the Kalshi book moved above the walked 0.85 between pricing and the hedge: the chase (2026-09-08)
    # raises the limit past the budget into the loss cap and takes the 0.86 level -- a cover at a
    # locked loss inside the cap, labelled, instead of a naked leg
    vs["polymarket"].books = {"P_CIN": offs["cin"][0].book}
    vs["kalshi"].books = {"K_MIL": bk([(0.86, 155.0), (0.87, 10.0)])}
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0), venues_connected={"kalshi": True, "polymarket": True})
    assert ex.state is X.HEDGED and ex.first_filled == 100.0 and ex.hedge_filled == 100.0 and ex.hedge_avg_price == pytest.approx(0.86)
    assert "ABOVE_BUDGET" in ex.detail or "ABOVE_BREAK_EVEN" in ex.detail
    assert [a["phase"] for a in ex.protect["attempts"]][-1] in ("budget", "loss_cap")
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
    # the armed deadline is the PROTECT window from the instant leg A was known (2026-09-08), well
    # past the phase-1 3 s a slow settle used to spend
    assert c.hedge_deadline_mono == pytest.approx(102.5 + c.protect_window_s, abs=0.2) and c.hedge_deadline_mono > 102.5 + 2.9


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


def test_the_first_leg_is_fill_and_kill_one_tick_above_the_walked_level_when_the_hurdle_allows():
    """Ten fill-or-kill orders at the walked level were killed on 2026-09-07; the pad buys the step
    the CLOB's book has moved by, never a cover below the hurdle."""
    from nodes.execute.plan import plan_from_cover
    offs = offers(pm_home=0.40, k_away=0.40)             # cost 0.80 + fees: plenty of room under 1/(1.01)
    cov = best_cover(offs, 25.0, now_utc=T, proof=PROOF)
    p = plan_from_cover(opportunity_id="o", event_id="espn:mlb:1", league="mlb", cov=cov, offers=offs)
    assert p.first.time_in_force == "ioc" and p.hedge.time_in_force == "ioc"
    assert p.first.limit_price == pytest.approx(0.41), "one tick above the walked level"
    offs2 = offers(pm_home=0.50, k_away=0.485)           # 0.985 + fees: no room for a pad under the hurdle
    cov2 = best_cover(offs2, 25.0, now_utc=T, proof=PROOF)
    if cov2.ok:
        p2 = plan_from_cover(opportunity_id="o2", event_id="espn:mlb:1", league="mlb", cov=cov2, offers=offs2)
        assert p2 is None or p2.first.limit_price == pytest.approx(0.50), "no pad when it would breach the hurdle"


def test_the_first_leg_is_confirmed_against_the_venue_book_before_the_send(tmp_path):
    """L77 (2026-09-12): 28 of 30 taker first legs missed with the socket book showing size at the
    limit. One read of the venue's own book before the send: above the limit or without depth for
    the size, nothing is sent and the reservation goes back (BOOK_MOVED); at or under the limit the
    send goes out; no book (a failed read) sends as before."""
    # above the limit: nothing sent
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    moved = {"P_H": bk([(p.first.limit_price + 0.02, 5000)])}
    co.fresh_book = lambda venue, market, side: (moved if venue == "polymarket" else vs[venue].books).get(market)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.BOOK_MOVED and ex.released and ex.state.is_terminal and not ex.state.holds_position
    assert store.con.execute("SELECT count(*) FROM orders").fetchone()[0] == 0, "nothing was sent"
    assert "a_confirm_ms" in ex.stages and ex.protect["first_leg_confirm"]["marginal"] == pytest.approx(p.first.limit_price + 0.02)
    assert "nothing sent" in ex.detail
    # depth short of the size: L95 takes what the book HAS rather than refusing the whole entry
    co2, vs2, store2, _, _ = harness(tmp_path / "b")
    vs2["polymarket"].books = {"P_H": offs["home"][0].book}
    vs2["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    thin = {"P_H": bk([(p.first.limit_price, 7)])}
    co2.fresh_book = lambda venue, market, side: (thin if venue == "polymarket" else vs2[venue].books).get(market)
    ex2 = co2.execute(p, clearance_for(tmp_path / "b", now_mono=100.0))
    assert ex2.state is X.HEDGED and ex2.quantity == 7.0, "7 is what the venue had; 100 was not"
    assert ex2.stages["downsized_to"] == 7 and ex2.stages["planned_contracts"] == 100.0
    # L96: but a downsize below the CLOB's five-share floor is not a trade, it is a PRECISION
    # rejection waiting to happen. Refuse instead of sending something the wire cannot take.
    co2b, vs2b, store2b, _, _ = harness(tmp_path / "b2")
    vs2b["polymarket"].books = {"P_H": offs["home"][0].book}
    vs2b["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    tiny = {"P_H": bk([(p.first.limit_price, 3)])}
    co2b.fresh_book = lambda venue, market, side: (tiny if venue == "polymarket" else vs2b[venue].books).get(market)
    ex2b = co2b.execute(p, clearance_for(tmp_path / "b2", now_mono=100.0))
    assert ex2b.state is X.BOOK_MOVED, "three shares is under the venue's own floor"
    assert store2b.con.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
    # at the limit with depth: the send goes out and the cover completes as before
    co3, vs3, store3, _, _ = harness(tmp_path / "c")
    vs3["polymarket"].books = {"P_H": offs["home"][0].book}
    vs3["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    co3.fresh_book = lambda venue, market, side: vs3[venue].books.get(market)
    ex3 = co3.execute(p, clearance_for(tmp_path / "c", now_mono=100.0))
    assert ex3.state is X.HEDGED and ex3.stages["a_confirm_ms"] >= 0
    # no reader: the 2026-09-07 path, untouched
    co4, vs4, store4, _, _ = harness(tmp_path / "d")
    vs4["polymarket"].books = {"P_H": offs["home"][0].book}
    vs4["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    ex4 = co4.execute(p, clearance_for(tmp_path / "d", now_mono=100.0))
    assert ex4.state is X.HEDGED and "a_confirm_ms" not in ex4.stages


def test_the_first_leg_carries_a_collateral_ceiling_from_the_venue_s_ask(tmp_path):
    """L83: the L77 read's best ask, when under the plan limit, becomes the order's collateral
    ceiling (contracts x ask); at or above the limit there is none."""
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    cheaper = {"P_H": bk([(p.first.limit_price - 0.03, 5000)])}
    co.fresh_book = lambda venue, market, side: (cheaper if venue == "polymarket" else vs[venue].books).get(market)
    sent = []
    real = vs["polymarket"].submit
    vs["polymarket"].submit = lambda r, c: (sent.append(r), real(r, c))[1]
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED
    first = sent[0]
    assert first.max_collateral_usd == pytest.approx(round(p.first.contracts * (p.first.limit_price - 0.03), 2))
    assert ex.protect["first_leg_confirm"]["max_collateral_usd"] == first.max_collateral_usd
    assert all(r.max_collateral_usd is None for r in sent[1:]), "hedges carry no ceiling"
    co2, vs2, _, _, _ = harness(tmp_path / "b")
    vs2["polymarket"].books = {"P_H": bk([(p.first.limit_price, 5000)])}          # the ask AT the limit: no ceiling
    vs2["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    co2.fresh_book = lambda venue, market, side: vs2[venue].books.get(market)
    sent2 = []
    real2 = vs2["polymarket"].submit
    vs2["polymarket"].submit = lambda r, c: (sent2.append(r), real2(r, c))[1]
    assert co2.execute(p, clearance_for(tmp_path / "b", now_mono=100.0)).state is X.HEDGED
    assert sent2[0].max_collateral_usd is None


def test_the_hedge_leg_is_confirmed_against_its_own_book_before_leg_a_is_sent(tmp_path):
    """L85 (2026-09-12): L77 confirmed the price about to be PAID; nothing confirmed the price
    relied on to get out, so the lane could open a position against a hedge that had walked away.
    The read is a VWAP against break-even: above it nothing is sent and the reservation goes back;
    at or under it -- including above the hurdle budget, which still makes money -- the send goes
    out; depth short of the authorized size is a decline; no book sends as before."""
    offs = offers()
    p, _ = plan_for(offs)
    be = p.hedge_break_even(p.first.limit_price)
    budget = p.hedge_budget(p.first.limit_price)
    assert budget < be, "the budget is the hurdle, break-even is zero profit"

    # above break-even: nothing sent at all, not even leg A
    co, vs, store, _, _ = harness(tmp_path)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(be + 0.02, 5000)])}
    co.fresh_book = lambda venue, market, side: vs[venue].books.get(market)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.BOOK_MOVED and ex.released and ex.state.is_terminal and not ex.state.holds_position
    assert store.con.execute("SELECT count(*) FROM orders").fetchone()[0] == 0, "leg A was never sent"
    assert "b_confirm_ms" in ex.stages and "nothing sent" in ex.detail and "break-even" in ex.detail
    confirm = ex.protect["hedge_leg_confirm"]
    assert confirm["vwap"] == pytest.approx(be + 0.02) and confirm["break_even"] == pytest.approx(be)
    assert confirm["contracts"] == p.hedge.contracts

    # between the budget and break-even: a profit under the hurdle is still a profit -- it trades
    co2, vs2, _, _, _ = harness(tmp_path / "b")
    vs2["polymarket"].books = {"P_H": offs["home"][0].book}
    vs2["kalshi"].books = {"K_A": bk([(round((budget + be) / 2.0, 4), 5000)])}
    co2.fresh_book = lambda venue, market, side: vs2[venue].books.get(market)
    ex2 = co2.execute(p, clearance_for(tmp_path / "b", now_mono=100.0))
    assert ex2.state is X.HEDGED, "gating on the budget would have refused this"

    # hedge depth short of the authorized size: L95 hedges what the book can cover whole, rather
    # than refusing an entry the venue could have supported at a smaller size
    co3, vs3, store3, _, _ = harness(tmp_path / "c")
    vs3["polymarket"].books = {"P_H": offs["home"][0].book}
    vs3["kalshi"].books = {"K_A": bk([(0.44, p.hedge.contracts - 1)])}
    co3.fresh_book = lambda venue, market, side: vs3[venue].books.get(market)
    ex3 = co3.execute(p, clearance_for(tmp_path / "c", now_mono=100.0))
    assert ex3.state is X.HEDGED and ex3.quantity == p.hedge.contracts - 1
    assert ex3.unhedged == 0.0, "the whole downsized position is covered"

    # no reader: the pre-L85 path, untouched
    co4, vs4, _, _, _ = harness(tmp_path / "d")
    vs4["polymarket"].books = {"P_H": offs["home"][0].book}
    vs4["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    ex4 = co4.execute(p, clearance_for(tmp_path / "d", now_mono=100.0))
    assert ex4.state is X.HEDGED and "b_confirm_ms" not in ex4.stages


def test_a_downsize_never_lands_under_the_clobs_own_share_floor(tmp_path):
    """L96: the CLOB refuses a marketable BUY under 5.00 nominal shares, so a downsize that shrinks
    below it converts a BOOK_MOVED decline into a PRECISION rejection instead of into a fill."""
    from nodes.execute.plan import best_supported_size
    from nodes.cover.cover import PM_WIRE_MIN_SHARES
    offs = offers()
    p4, _ = plan_for(offs, q=4.0)
    deep = bk([(p4.first.limit_price, 5000)])
    hedge_ok = bk([(0.30, 5000)])
    assert best_supported_size(deep, hedge_ok, p4, min_net_profit_usd=0.0, max_size=4) is None, \
        "four contracts cannot reach the venue however good the price is"
    p10, _ = plan_for(offs, q=10.0)
    n10 = best_supported_size(bk([(p10.first.limit_price, 5000)]), hedge_ok, p10,
                              min_net_profit_usd=0.0, max_size=10)
    assert n10 is not None and n10 >= PM_WIRE_MIN_SHARES


def test_a_pad_that_would_shrink_the_wire_under_the_floor_sends_at_the_venues_own_ask(tmp_path):
    """L96 (2026-09-13): L83's ceiling is `contracts x top` and the adapter divides it by the price
    SENT, so a limit one tick above `top` shrinks the nominal size below `contracts` -- 4.948 at top
    0.95 -- and under five shares nothing reaches the venue at all. Seven of seven capped
    five-contract orders on 2026-09-13 died there, every one of them with the full size resting AT
    the top of book. Repricing to that top is the whole fix: the ceiling then shrinks nothing, and
    paying less than the limit cannot break economics that were cleared against paying more."""
    co, vs, store, _, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs, q=5.0)
    top = round(p.first.limit_price - 0.01, 4)                  # the one-tick pad, as the live plan pads
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    cheaper = {"P_H": bk([(top, 5000)])}
    co.fresh_book = lambda venue, market, side: (cheaper if venue == "polymarket" else vs[venue].books).get(market)
    sent = []
    real = vs["polymarket"].submit
    vs["polymarket"].submit = lambda r, c: (sent.append(r), real(r, c))[1]
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED
    assert sent[0].price == pytest.approx(top), "leg A goes out at the venue's own ask, not the pad"
    assert sent[0].max_collateral_usd == pytest.approx(round(5.0 * top, 2))
    assert sent[0].max_collateral_usd / sent[0].price + 1e-9 >= 5.0, "the wire sees the whole size"
    assert ex.stages["repriced_to_top"] == pytest.approx(top)
    assert ex.protect["first_leg_confirm"]["repriced_to_top"]["from"] == p.first.limit_price
    # A size the ceiling does not shrink below the floor is left exactly as the plan priced it.
    co2, vs2, _, _, _ = harness(tmp_path / "b")
    p25, _ = plan_for(offs, q=25.0)
    top25 = round(p25.first.limit_price - 0.01, 4)
    vs2["polymarket"].books = {"P_H": offs["home"][0].book}
    vs2["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    cheaper2 = {"P_H": bk([(top25, 5000)])}
    co2.fresh_book = lambda venue, market, side: (cheaper2 if venue == "polymarket" else vs2[venue].books).get(market)
    sent2 = []
    real2 = vs2["polymarket"].submit
    vs2["polymarket"].submit = lambda r, c: (sent2.append(r), real2(r, c))[1]
    ex2 = co2.execute(p25, clearance_for(tmp_path / "b", now_mono=100.0))
    assert ex2.state is X.HEDGED
    assert sent2[0].price == pytest.approx(p25.first.limit_price), "no reprice: 25 shrinks to 24.7"
    assert "repriced_to_top" not in ex2.stages


def test_the_wire_floor_reprice_never_puts_an_off_grid_level_back_on_the_entry(tmp_path):
    """L99 (2026-09-13): L96 reprices leg A to a LEVEL, and a level carries the book's grid.

    The plan snaps leg A onto the tick the leg declares precisely because an off-grid limit is
    re-priced DOWNWARD at the wire, under the only level that could have filled it. Repricing to an
    off-grid `top` hands that straight back, so the reprice is taken only when `top` is itself on
    the grid -- which every measured L96 case was."""
    co, vs, store, _, _ = harness(tmp_path)
    offs = offers(pm_home=0.81, k_away=0.15)
    p, _ = plan_for(offs, q=5.0)
    assert p.first.limit_price == 0.82                # 0.81 walked, one tick of pad, on the grid
    # An ask the declared 0.01 grid cannot express, chosen so L96's own sub-cent check passes it:
    # 5 x 0.812 = $4.06 exactly, so the cent-rounded ceiling still buys the whole size.
    off_grid_top = 0.812
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.15, 5000)])}
    cheaper = {"P_H": bk([(off_grid_top, 5000)])}
    co.fresh_book = lambda venue, market, side: (cheaper if venue == "polymarket" else vs[venue].books).get(market)
    sent = []
    real = vs["polymarket"].submit
    vs["polymarket"].submit = lambda r, c: (sent.append(r), real(r, c))[1]
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    # the wire WOULD shrink under the floor at 0.82, so L96's reprice is live for this shape
    assert not pm_wire_ok(5.0, top=off_grid_top, limit=p.first.limit_price)
    assert round(5.0 * off_grid_top, 2) / off_grid_top + 1e-9 >= 5.0, "L96's sub-cent check passes it"
    assert sent[0].price == pytest.approx(0.82), "an off-grid ask must not become the entry limit"
    assert sent[0].price / p.first.tick == pytest.approx(round(sent[0].price / p.first.tick))
    assert "repriced_to_top" not in ex.stages


def test_no_size_the_books_support_still_refuses_the_whole_entry(tmp_path):
    """L95 only ever SHRINKS. When the price is wrong at every level -- not merely thin -- there is
    no size to fall back to and the entry is refused exactly as before."""
    co, vs, store, _, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    dear = {"P_H": bk([(p.first.limit_price + 0.05, 5000)])}      # deep, but above the limit at q=1
    co.fresh_book = lambda venue, market, side: (dear if venue == "polymarket" else vs[venue].books).get(market)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.BOOK_MOVED and ex.released and "nothing sent" in ex.detail
    assert store.con.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
    assert "downsized_to" not in ex.stages


def test_a_downsize_must_still_earn_the_dollar_floor(tmp_path):
    """Profit is size-linear, so the floor is the test that bites on the way down. A book that can
    only support a size too small to earn `min_net_profit_usd` is a refusal, not a tiny trade."""
    co, vs, store, _, _ = harness(tmp_path)
    co.min_net_profit_usd = 5.00                       # far above anything 3 contracts could earn
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    thin = {"P_H": bk([(p.first.limit_price, 3)])}
    co.fresh_book = lambda venue, market, side: (thin if venue == "polymarket" else vs[venue].books).get(market)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.BOOK_MOVED, "3 contracts cannot earn $5.00; refuse rather than trade it"
    assert store.con.execute("SELECT count(*) FROM orders").fetchone()[0] == 0


def test_the_64d6925e_shape_is_declined_instead_of_locking_a_loss(tmp_path):
    """The first cover after the 2026-09-12 18:47Z kill clear: planned PM 0.54 / Kalshi 0.41, the
    Kalshi NO side at 0.51 when the hedge fired 0.2 s later, break-even 0.4233. The layer paid it
    because a capped loss beats a naked leg and the cover locked -$2.17 of a $2.50 allowance. With
    L85 the entry is declined and no position is opened."""
    co, vs, store, _, _ = harness(tmp_path)
    offs = offers()
    p0, _ = plan_for(offs, q=25.0)
    p = replace(p0, quantity=25.0,
                first=replace(p0.first, limit_price=0.54, vwap=0.54, contracts=25.0),
                hedge=replace(p0.hedge, limit_price=0.41, vwap=0.41, contracts=25.0, tick=0.01),
                max_cost_per_contract=0.9950248756218907,
                fee_per_contract=0.029356, settlement_buffer_per_contract=0.0073607)
    assert p.hedge_break_even(0.54) == pytest.approx(0.4233, abs=0.0001), "the live break-even"
    vs["polymarket"].books = {"P_H": bk([(0.54, 5000)])}
    vs["kalshi"].books = {"K_A": bk([(0.51, 5000)])}
    co.fresh_book = lambda venue, market, side: vs[venue].books.get(market)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.BOOK_MOVED and ex.released
    assert store.con.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
    assert ex.first_filled == 0.0 and ex.unhedged == 0.0, "no position, so nothing to protect"
    assert ex.protect["hedge_leg_confirm"]["vwap"] == pytest.approx(0.51)

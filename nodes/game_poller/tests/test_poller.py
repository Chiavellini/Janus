#!/usr/bin/env python3
"""One game, four books, priced on every event."""
from __future__ import annotations

import pytest

from nodes.game_poller.poller import Evaluation, GamePoller, PollerState
from nodes.settle_wedge.fixtures import mlb_equivalence

T = 1000.0
OUT = {"home": {"kalshi": "K_H", "polymarket": "P_H"},
       "away": {"kalshi": "K_A", "polymarket": "P_A"}}


#: What the venues actually reported on 2026-09-02. The poller refuses a leg without these.
FEES = {"kalshi": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5},
        "polymarket": {"fee_rate": 0.03}}


def mlb(**kw) -> GamePoller:
    kw.setdefault("fee_params", FEES)
    kw.setdefault("equivalence", mlb_equivalence())
    kw.setdefault("quantities", (100.0,))
    return GamePoller("g1", "mlb", OUT, **kw)


def sync_all(p: GamePoller, *, kh=0.50, ka=0.50, ph=0.50, pa=0.50, now=T, size=5000.0,
             no_h=None, no_a=None, no_size=5000.0):
    """Sync the four primary books. The complementary NO replicas ("kalshi_no") are synced
    only when a price is given; left alone they stay unsynced and are simply not offered."""
    prices = {("kalshi", "home"): kh, ("kalshi", "away"): ka,
              ("polymarket", "home"): ph, ("polymarket", "away"): pa,
              ("kalshi_no", "home"): no_h, ("kalshi_no", "away"): no_a}
    for key, rep in p.replicas.items():
        price = prices[key]
        if price is None:
            continue
        rep.subscribed(now)
        rep.snapshot_in([(0.01, size)], [(price, no_size if key[0] == "kalshi_no" else size)],
                        seq=1 if rep.verification != "external" else None, now=now)


def test_a_three_way_league_never_gets_a_two_outcome_poller():
    """No subscription should be spent on a game whose outcome set cannot be proven complete: two
    outcomes of a three-way soccer game are not a partition (OUTCOME_COUNT_MISMATCH since the rule
    was cited on 2026-09-03; RULE_UNCITED before)."""
    p = GamePoller("g", "epl", OUT)
    assert p.state is PollerState.BLOCKED
    assert p.block_reason == "OUTCOME_COUNT_MISMATCH"
    assert p.replicas == {}
    assert p.on_event("kalshi", "K_H", now=T) == []


def test_it_warms_before_it_watches():
    p = mlb()
    assert p.state is PollerState.WARMING
    evs = p.on_event("kalshi", "K_H", now=T)
    assert all(e.cover is None for e in evs)
    assert evs[0].blocked_by is not None


def test_a_blocked_evaluation_still_reports_why():
    """'We could not price this, and here is why' is what separates no-edge from no-data."""
    p = mlb()
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert "NOT_SYNCED" in e.blocked_by or "HEARTBEAT" in e.blocked_by


def test_all_four_synced_lets_it_price():
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert p.state is PollerState.WATCHING
    assert e.cover is not None and e.cover.ok
    assert e.blocked_by is None


def test_a_real_gap_is_flagged_actionable():
    """0.44 + 0.44 = 0.88 gross; fees at the money are ~3c, so this clears 1% comfortably."""
    p = mlb()
    sync_all(p, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    evs = p.on_event("polymarket", "P_A", now=T)
    # the venues' smallest size (3 shares: a dollar at $0.44) is priced beside the 100 rung (2026-09-07)
    assert [e.quantity for e in evs] == [3.0, 100.0]
    e = evs[-1]
    assert e.actionable_return is not None and e.actionable_return > 0.01
    assert p.opportunities == 2


def test_one_desynced_replica_blocks_the_whole_cover():
    """A drifted book invents gaps. Three good replicas do not make a fourth trustworthy."""
    p = mlb()
    sync_all(p, kh=0.44, pa=0.44)
    # Kalshi's seq is per subscription, so the STREAM detects the gap and tells the replica.
    from nodes.book_replica.replica import Fault
    p.replicas[("kalshi", "home")].invalidate(Fault.SEQ_GAP)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover is None
    assert "SEQ_GAP" in e.blocked_by
    assert p.opportunities == 0


def test_a_quiet_book_on_a_live_socket_prices_and_one_whose_last_frame_is_old_blocks():
    """Currency runs from the last proof (the last frame on a sequence-checked socket), not from
    the last mutation (2026-09-07). The bound still bites when the socket itself has gone quiet."""
    p = mlb(max_book_age_s=2.0)
    sync_all(p, kh=0.44, pa=0.44)
    for r in p.replicas.values():
        r.heartbeat(T + 10)
    e = p.on_event("kalshi", "K_H", now=T + 10)[0]
    assert e.cover is not None, "unchanged for 10 s on a socket alive at T+10: the venue's book"
    e = p.on_event("kalshi", "K_H", now=T + 13)[0]
    assert e.cover is None and "STALE" in e.blocked_by, "the last frame is 3 s old; the bound is 2 s"


def test_evaluation_happens_per_event_not_per_tick_of_a_clock():
    """Default (no window): every event prices."""
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48)
    before = p.evaluations
    per = len(p.on_event("kalshi", "K_H", now=T))       # the smallest executable size and the 100 rung
    assert per == 2
    for _ in range(24):
        p.on_event("kalshi", "K_H", now=T)
    assert p.evaluations == before + 25 * per
    assert p.events >= 25


def test_the_coalescing_window_prices_once_per_interval_but_never_hides_a_state_change():
    """2026-09-04: ~3,400 evaluations a second saturated the loop. Inside the window an event is
    folded, not priced; the 15 s heartbeat and any replica state/fault change still price on
    the frame they happen, so replay stays faithful and no BLOCKED transition is lost."""
    p = mlb(min_eval_interval_s=0.2, quantities=(3.0,))    # 3 = the venues' smallest size at $0.48: one quantity per event
    sync_all(p, kh=0.48, pa=0.48)
    assert len(p.on_event("kalshi", "K_H", now=T)) == 1
    for i in range(25):
        assert p.on_event("kalshi", "K_H", now=T + 0.001 * i) == [], "inside the window: folded, not priced"
    assert p.skipped == 25 and p.evaluations == 1
    assert len(p.on_event("kalshi", "K_H", now=T + 0.25)) == 1, "past the window: priced"
    for i in range(25):
        p.on_event("kalshi", "K_H", now=T + 0.25 + 0.3 * (i + 1))
    assert p.evaluations == 27, "spaced past the window: every one prices"
    # a replica fault inside the window prices immediately, with the fault on the row
    t2 = T + 0.25 + 0.3 * 26
    sync_all(p, kh=0.48, pa=0.48, now=t2)                    # fresh books, priced on this frame
    assert len(p.on_event("kalshi", "K_H", now=t2)) == 1
    p.replicas[("polymarket", "home")].invalidate(__import__("nodes.book_replica.replica", fromlist=["Fault"]).Fault.HASH_MISMATCH)
    ev = p.on_event("polymarket", "P_H", now=t2 + 0.01)
    assert ev and ev[0].blocked_by and "HASH_MISMATCH" in ev[0].blocked_by, "a fault inside the window prices at once"
    # the heartbeat prices even when nothing changed
    ev = p.on_event("kalshi", "K_H", now=t2 + 0.02)
    assert ev == []
    assert len(p.on_event("kalshi", "K_H", now=t2 + 15.5)) == 1, "the 15 s heartbeat is due"


def test_it_reports_its_subscriptions_per_venue():
    p = mlb()
    assert sorted(p.market_ids("kalshi")) == ["K_A", "K_H"]
    assert sorted(p.market_ids("polymarket")) == ["P_A", "P_H"]


def test_each_venue_declares_how_it_proves_it_is_in_sync():
    """Kalshi's seq is per SUBSCRIPTION, so the stream verifies. Polymarket has no seq at all."""
    p = mlb()
    assert p.replicas[("kalshi", "home")].verification == "stream"
    assert p.replicas[("polymarket", "home")].verification == "external"


def test_draining_stops_evaluation():
    p = mlb()
    sync_all(p)
    p.drain()
    assert p.on_event("kalshi", "K_H", now=T) == []


def test_a_single_venue_cover_is_not_counted_as_an_opportunity():
    """Both legs on one book is the intra-venue control, not an arbitrage."""
    p = mlb()
    sync_all(p, kh=0.44, ka=0.44, ph=0.99, pa=0.99)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover.ok and e.cover.single_venue
    assert p.opportunities == 0


def test_a_leg_without_a_fee_schedule_is_blocked_not_defaulted():
    """The lane hardcoded PM at 0.05 and let Kalshi default to 1.0x. The venues said 0.03 and
    0.5x. A missing schedule is a BLOCK with a name, never a constant."""
    p = mlb(fee_params={"kalshi": FEES["kalshi"]})          # PM schedule never fetched
    sync_all(p, kh=0.44, pa=0.44)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover is None
    assert e.blocked_by == "polymarket:home:FEE_SCHEDULE_MISSING"


def test_the_fee_schedule_reaches_the_cover_verbatim():
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48)
    e = p.on_event("kalshi", "K_H", now=T)[-1]                # the 100-contract rung
    assert e.quantity == 100.0
    assert {l.venue for l in e.cover.legs} == {"kalshi", "polymarket"}
    # Kalshi quadratic_with_maker_fees on a 0.48 fill: the venue charges the full 0.07 (production
    # fill 2026-09-04), kept to the hundredth of a cent: 0.07*100*0.48*0.52 = $1.7472 exactly.
    # PM at the market's 0.03: 100*0.03*0.48*0.52 = 74.88c (124.8c at the hardcoded 0.05).
    expected = 1.7472 + 100 * 0.03 * 0.48 * 0.52
    assert abs(e.cover.fee_per_contract * 100.0 - expected) < 1e-9


def test_a_supervisor_halt_blocks_with_its_name_but_still_records():
    p = mlb()
    sync_all(p, kh=0.44, pa=0.44)
    p.halt = "CLOCK_UNHEALTHY"
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover is None and e.blocked_by == "supervisor:halt:CLOCK_UNHEALTHY"
    p.halt = None
    assert p.on_event("kalshi", "K_H", now=T)[0].cover.ok


# ── the complementary NO ladder ─────────────────────────────────────────────
def test_the_no_ladder_registers_on_the_other_markets_ticker():
    p = mlb()
    regs = sorted((v, m, side) for v, m, side, _r in p.registrations())
    assert regs == [("kalshi", "K_A", "no"), ("kalshi", "K_A", "yes"), ("kalshi", "K_H", "no"),
                    ("kalshi", "K_H", "yes"), ("polymarket", "P_A", "yes"), ("polymarket", "P_H", "yes")]
    assert p.replicas[("kalshi_no", "home")].market_id == "K_A", "NO on the AWAY market backs HOME"


def test_the_no_ladder_is_extra_depth_and_a_cheaper_price_wins():
    """Home via NO-on-away at 0.40 beats home via YES-on-home at 0.48; the cover takes it and the
    liquidity_source guard still allows it (a different outcome_id on the same book family)."""
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48, no_h=0.40)
    e = p.on_event("kalshi", "K_A", now=T)[0]
    assert e.cover.ok
    ids = {l.outcome_id for l in e.cover.legs}
    assert "K_A:NO" in ids and "K_H" not in ids


def test_a_faulted_no_replica_never_blocks_the_primary_cover():
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48, no_h=0.40)
    from nodes.book_replica.replica import Fault
    p.replicas[("kalshi_no", "home")].invalidate(Fault.SEQ_GAP)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover.ok and e.blocked_by is None
    assert "K_A:NO" not in {l.outcome_id for l in e.cover.legs}


def test_a_rest_sourced_book_is_held_to_the_stricter_bound():
    p = mlb(max_book_age_s=5.0, max_rest_book_age_s=2.0)
    sync_all(p, kh=0.48, pa=0.48)
    r = p.replicas[("polymarket", "home")]
    r.reconcile([(0.01, 5000)], [(0.48, 5000)], now=T)          # adopted from REST at T
    for rep in p.replicas.values():
        rep.heartbeat(T + 0.5)                                    # the last frame on either socket
    e = p.on_event("kalshi", "K_H", now=T + 3)[0]
    assert e.cover is None and e.blocked_by == "polymarket:home:STALE", "2.5 s since the last proof: fine for ws, stale for rest"
    r.snapshot_in([(0.01, 5000)], [(0.48, 5000)], now=T + 3)     # a socket snapshot relabels it ws
    assert p.on_event("kalshi", "K_H", now=T + 3)[0].cover.ok


def test_no_settlement_proof_means_no_poller():
    """The second refusal at spawn: an unproven settlement basis spends no subscription."""
    p = GamePoller("g", "mlb", OUT, fee_params=FEES)
    assert p.state is PollerState.BLOCKED and p.block_reason == "SETTLEMENT_UNPROVEN"
    assert p.replicas == {} and p.registrations() == []


def test_the_settlement_reserve_is_inside_the_cost():
    from nodes.settle_wedge.fixtures import RATES_FOR_TESTS
    free = mlb(); reserved = mlb(equivalence=mlb_equivalence(RATES_FOR_TESTS))
    for p in (free, reserved):
        # cross-venue is the only fillable cover: Kalshi home 0.30 + Polymarket away 0.70 (the favourite)
        sync_all(p, kh=0.30, ka=0.99, ph=0.99, pa=0.70)
    a = free.on_event("kalshi", "K_H", now=T)[0].cover
    b = reserved.on_event("kalshi", "K_H", now=T)[0].cover
    assert a.cover_ok if hasattr(a, 'cover_ok') else a.ok
    assert not b.single_venue and a.settlement_buffer_per_contract == 0.0
    # cancellation 0.002*(0.70-0.5) + (postponed+suspended) 2*0.01*0.70, per contract
    assert abs(b.settlement_buffer_per_contract - (0.002 * 0.2 + 0.02 * 0.70)) < 1e-9
    assert abs((b.cost_per_contract - a.cost_per_contract) - b.settlement_buffer_per_contract) < 1e-9


def test_the_venues_order_limits_reach_the_legs_and_set_the_smallest_quantity():
    """The smallest priced quantity is the smallest size both venues execute (2026-09-07): the
    Polymarket share minimum, or one dollar of notional at its ask, whichever is larger."""
    from nodes.game_poller.poller import smallest_executable
    p = mlb(order_limits={"polymarket": {"min_order_contracts": 5.0, "tick": 0.01}}, quantities=(3.0, 100.0))
    sync_all(p, kh=0.44, pa=0.44)
    evs = p.on_event("kalshi", "K_H", now=T)
    # 3 would be below the Polymarket minimum: the smallest quantity priced is 5, and it is a cross-venue cover
    assert [e.quantity for e in evs] == [5.0, 100.0]
    assert evs[0].cover.ok and {l.venue for l in evs[0].cover.legs} == {"kalshi", "polymarket"}
    # a 12-cent token needs 9 shares for a dollar; a 50-cent one keeps the 5-share minimum
    p2 = mlb(order_limits={"polymarket": {"min_order_contracts": 5.0, "tick": 0.01}}, quantities=(5.0, 10.0, 25.0, 100.0))
    sync_all(p2, kh=0.85, ka=0.85, ph=0.12, pa=0.12)
    evs2 = p2.on_event("kalshi", "K_H", now=T)
    assert [e.quantity for e in evs2] == [9.0, 10.0, 25.0, 100.0]
    assert smallest_executable(evs2[0].offers) == 9.0
    p3 = mlb(order_limits={"polymarket": {"min_order_contracts": 5.0, "tick": 0.01}}, quantities=(5.0, 10.0))
    sync_all(p3, kh=0.50, ka=0.50, ph=0.50, pa=0.50)
    assert [e.quantity for e in p3.on_event("kalshi", "K_H", now=T)] == [5.0, 10.0]



OUT3 = {"home": {"kalshi": "K_H", "polymarket": "P_H", "polymarket_no": "P_H_NO"},
        "draw": {"kalshi": "K_D", "polymarket": "P_D"},
        "away": {"kalshi": "K_A", "polymarket": "P_A", "polymarket_no": "P_A_NO"}}


def epl(**kw) -> GamePoller:
    from nodes.settle_wedge.fixtures import epl_equivalence
    kw.setdefault("fee_params", FEES)
    kw.setdefault("equivalence", epl_equivalence())
    kw.setdefault("quantities", (100.0,))
    return GamePoller("g3", "epl", OUT3, **kw)


def _sync(rep, price, now=T, size=5000.0):
    rep.subscribed(now)
    rep.snapshot_in([(0.01, size)], [(price, size)], seq=1 if rep.verification != "external" else None, now=now)


def test_a_three_way_poller_carries_the_polymarket_no_replicas_and_subscribes_them():
    """2026-09-04: NO on a team market pays on the other two outcomes, so a soccer cover is two
    legs. The replica keys ("polymarket_no", outcome), registers as a Polymarket asset, and is
    in market_ids() so the reap unsubscribes it."""
    p = epl()
    assert p.state is PollerState.WARMING, p.block_reason
    assert ("polymarket_no", "home") in p.replicas and ("polymarket_no", "away") in p.replicas
    assert ("polymarket_no", "draw") not in p.replicas and ("kalshi_no", "home") not in p.replicas
    regs = {(v, m, side) for v, m, side, _ in p.registrations()}
    assert ("polymarket", "P_H_NO", "yes") in regs and ("polymarket", "P_A_NO", "yes") in regs
    assert set(p.market_ids("polymarket")) == {"P_H", "P_D", "P_A", "P_H_NO", "P_A_NO"}
    assert set(p.market_ids("kalshi")) == {"K_H", "K_D", "K_A"}


def test_a_three_way_cover_prices_as_two_legs_through_the_no_token():
    p = epl()
    for key, px in {("kalshi", "home"): 0.40, ("kalshi", "draw"): 0.30, ("kalshi", "away"): 0.35,
                    ("polymarket", "home"): 0.42, ("polymarket", "draw"): 0.30, ("polymarket", "away"): 0.36,
                    ("polymarket_no", "home"): 0.50, ("polymarket_no", "away"): 0.62}.items():
        _sync(p.replicas[key], px)
    e = p.on_event("polymarket", "P_H_NO", now=T)[0]
    assert p.state is PollerState.WATCHING and e.cover is not None and e.cover.ok, e.blocked_by
    assert "away|draw" in e.offers and e.offers["away|draw"][0].covers == frozenset({"away", "draw"})
    assert e.offers["away|draw"][0].outcome_id == "P_H:NO" and e.offers["away|draw"][0].market_id == "P_H_NO"
    # Kalshi YES home 0.40 + Polymarket NO home 0.50 = 0.90 gross beats any three-leg shape (0.40+0.30+0.35)
    assert len(e.cover.legs) == 2 and abs(e.cover.gross_per_contract - 0.90) < 1e-9
    assert {lc.outcome_id for lc in e.cover.legs} == {"K_H", "P_H:NO"}
    # the NO leg is extra depth, never a requirement: without it the three-leg cover still prices
    p2 = epl()
    for key, px in {("kalshi", "home"): 0.40, ("kalshi", "draw"): 0.30, ("kalshi", "away"): 0.35,
                    ("polymarket", "home"): 0.42, ("polymarket", "draw"): 0.30, ("polymarket", "away"): 0.36}.items():
        _sync(p2.replicas[key], px)
    e2 = p2.on_event("kalshi", "K_H", now=T)[0]
    assert e2.cover is not None and e2.cover.ok and len(e2.cover.legs) == 3

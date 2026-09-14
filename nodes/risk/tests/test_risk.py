#!/usr/bin/env python3
"""Every fail-closed condition, in order; a token that cannot be forged, reused or kept."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kernel.schema import FillState, Mode
from nodes.risk.breaker import LossBreaker, RealizedFill
from nodes.risk.clearance import Candidate, RiskClearance, clear, clear_proof
from nodes.risk.gate import Refused as GateRefused, resolve_mode
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import ExposureLedger, Refused
from nodes.risk.limits import load_limits
from nodes.store_tuples.store import TupleStore

LIMITS = load_limits()


@pytest.fixture
def kill(tmp_path):
    return KillSwitches(tmp_path / "kill", enforce_volume=False)


@pytest.fixture
def breaker(tmp_path, kill):
    return LossBreaker(tmp_path / "kill" / "breaker.json", kill=kill, enforce_volume=False)


def cand(**kw):
    base = dict(opportunity_id="o1", event_id="espn:mlb:1", league="mlb",
                legs=(("kalshi", 100.0, 0.44), ("polymarket", 100.0, 0.44)),
                net_profit_usd=8.0, locked_return=0.09, strategy_version="v1", max_book_age_s=0.5)
    base.update(kw)
    return Candidate(**base)


def ok_env(**kw):
    d = dict(mode=Mode.PAPER_EXECUTION, limits=LIMITS, kill=None, breaker=None, fills_today=(),
             clock_healthy=True, fee_schedules_ok=True, balances={"kalshi": 500.0, "polymarket": 500.0},
             venues_connected={"kalshi": True, "polymarket": True}, now_mono=100.0, now=1000.0)
    d.update(kw)
    return d


# ── limits ───────────────────────────────────────────────────────────────────
def test_limits_load_with_a_pin_and_absent_is_zero_not_unlimited():
    assert LIMITS.sha and len(LIMITS.sha) == 16
    assert LIMITS.venue_cap("kalshi") == 250.0 and LIMITS.venue_cap("sxbet") == 0.0
    assert LIMITS.league_cap("epl") == 200.0, "paper caps for the enabled leagues, 2026-09-05"
    assert LIMITS.league_cap("khl") == 0.0 and LIMITS.min_locked_return == 0.005, "absent is zero, not unlimited"


def test_the_risk_file_and_the_labelling_thresholds_agree():
    """thresholds.py decides what is PROFITABLE_UNEXECUTED; limits.toml refuses at clearance. When the
    two disagreed (2026-09-07/08) the stricter one silently bound. They move together, by GATE row."""
    from nodes.opportunity.thresholds import EXECUTION_MIN_LOCKED_RETURN, EXECUTION_MIN_NET_PROFIT_USD
    assert LIMITS.min_locked_return == EXECUTION_MIN_LOCKED_RETURN == 0.005
    assert LIMITS.min_net_profit_usd == EXECUTION_MIN_NET_PROFIT_USD == 0.05


# ── kill switches ────────────────────────────────────────────────────────────
def test_every_scope_is_a_file_and_nothing_else(kill):
    assert kill.active(venue="kalshi", event_id="e", strategy="v1", live=True) == []
    kill.latch("all", "test")
    assert kill.active() == ["all"]
    (kill.root / "venue-polymarket").write_text("")
    (kill.root / "event-e").write_text("")
    (kill.root / "strategy-v1").write_text("")
    (kill.root / "live").write_text("")
    assert kill.active(venues=("kalshi", "polymarket"), event_id="e", strategy="v1", live=False) == \
        ["all", "event-e", "strategy-v1", "venue-polymarket"]
    assert "live" in kill.active(live=True)
    assert kill.any_present() == ["all", "event-e", "live", "strategy-v1", "venue-polymarket"]


# ── breaker ──────────────────────────────────────────────────────────────────
def test_an_unconfirmed_fill_makes_pnl_unknown_and_unknown_is_closed(breaker):
    fills = [RealizedFill("f1", FillState.FILLED, -3.0, "2026-09-03"),
             RealizedFill("f2", FillState.UNCONFIRMED, 0.0, "2026-09-03")]
    assert breaker.day_pnl(fills, "2026-09-03") is None
    assert breaker.evaluate(fills, max_daily_loss_usd=25.0, day="2026-09-03").startswith("PNL_UNKNOWN")
    assert not breaker.latched


def test_a_breach_latches_persists_and_latches_the_live_switch(tmp_path, kill):
    b = LossBreaker(tmp_path / "kill" / "breaker.json", kill=kill, enforce_volume=False)
    fills = [RealizedFill("f1", FillState.FILLED, -20.0, "2026-09-03"),
             RealizedFill("f2", FillState.FILLED, -6.0, "2026-09-03"),
             RealizedFill("f3", FillState.FILLED, +50.0, "2026-09-02")]   # yesterday does not help today
    assert b.evaluate(fills, max_daily_loss_usd=25.0, day="2026-09-03").startswith("BREAKER_LATCHED")
    assert kill.active(live=True) == ["live"]
    again = LossBreaker(tmp_path / "kill" / "breaker.json", enforce_volume=False)
    assert again.latched and "26.00" in again.latch_reason, "latched across a restart"
    with pytest.raises(ValueError):
        again.reset(by="")
    again.reset(by="operator")
    assert not LossBreaker(tmp_path / "kill" / "breaker.json", enforce_volume=False).latched


# ── ledger ───────────────────────────────────────────────────────────────────
def test_every_cap_refuses_before_anything_is_reserved():
    L = ExposureLedger()
    r = L.reserve(event_id="e1", league="mlb", per_venue_usd={"kalshi": 44.0, "polymarket": 44.0}, limits=LIMITS)
    assert not isinstance(r, Refused) and L.total_usd() == 88.0
    assert L.reserve(event_id="e1", league="mlb", per_venue_usd={"kalshi": 1.0}, limits=LIMITS).code == "EVENT_IN_FLIGHT"
    assert L.reserve(event_id="e2", league="mlb", per_venue_usd={"kalshi": 150.0, "polymarket": 100.0}, limits=LIMITS).code == "EVENT_NOTIONAL"
    assert L.reserve(event_id="e2", league="khl", per_venue_usd={"kalshi": 10.0}, limits=LIMITS).code == "LEAGUE_EXPOSURE"
    assert L.reserve(event_id="e2", league="mlb", per_venue_usd={"sxbet": 10.0}, limits=LIMITS).code == "VENUE_CAPITAL"
    assert L.reserve(event_id="e2", league="mlb", per_venue_usd={"kalshi": 90.0, "polymarket": 90.0}, limits=LIMITS).code == "UNRESOLVED_EXPOSURE"
    assert not isinstance(L.reserve(event_id="e2", league="mlb", per_venue_usd={"kalshi": 60.0, "polymarket": 60.0}, limits=LIMITS), Refused)
    assert not isinstance(L.reserve(event_id="e3", league="mlb", per_venue_usd={"kalshi": 10.0}, limits=LIMITS), Refused)
    for e in ("e4", "e5", "e6"):        # max_simultaneous is 6 since 2026-09-05 (was 3)
        assert not isinstance(L.reserve(event_id=e, league="mlb", per_venue_usd={"kalshi": 1.0}, limits=LIMITS), Refused), e
    assert L.reserve(event_id="e7", league="mlb", per_venue_usd={"kalshi": 1.0}, limits=LIMITS).code == "MAX_EVENTS"
    assert L.total_usd() == 221.0 and L.venue_usd("kalshi") == 117.0 and L.league_usd("mlb") == 221.0


def test_reservations_survive_a_restart_and_release_records_why(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    L = ExposureLedger(store)
    r = L.reserve(event_id="e1", league="mlb", per_venue_usd={"kalshi": 10.0}, limits=LIMITS, now=1000.0)
    store.commit()
    # A restart is a NEW connection: it sees only what was committed, which is the whole point.
    L2 = ExposureLedger(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    assert L2.has_event("e1") and L2.oldest_open_age_s(now=1600.0) == 600.0
    assert L2.release(r.reservation_id, reason="both venues reconciled", now=1700.0)
    assert not L2.release(r.reservation_id, reason="twice")
    assert ExposureLedger(store).open == {}
    row = store.con.execute("SELECT released_utc, release_reason FROM capital_reservations").fetchone()
    assert row == (1700.0, "both venues reconciled")


# ── clearance ────────────────────────────────────────────────────────────────
def test_the_token_cannot_be_forged_and_is_single_use_and_short_lived(kill, breaker):
    with pytest.raises(TypeError):
        RiskClearance(opportunity_id="o", event_id="e", mode=Mode.PAPER_EXECUTION, reservation=None,
                      limits_sha="x", issued_mono=0, expires_mono=1, hedge_deadline_mono=3)
    L = ExposureLedger()
    c = clear(cand(), ledger=L, **ok_env(kill=kill, breaker=breaker))
    assert isinstance(c, RiskClearance) and c.limits_sha == LIMITS.sha
    assert c.reservation.per_venue_usd == {"kalshi": 44.0, "polymarket": 44.0}
    assert c.valid(100.2) and not c.valid(100.0 + LIMITS.clearance_ttl_ms / 1000 + 0.01)
    assert not c.consume(100.1, hedge=True), "no hedge before the first leg"
    assert c.consume(100.1) and not c.consume(100.1), "the first leg exactly once"
    assert c.used and not c.valid(100.1)
    # hedges: bounded in count and inside the hedge deadline (max_hedge_latency_ms from the limits)
    assert c.consume(100.5, hedge=True) and c.consume(101.0, hedge=True) and c.consume(102.0, hedge=True)
    # 2026-09-08: the token admits PROTECTIVE legs (the hedge, its chase, the unwind) up to the
    # protect section's bound, not the phase-1 three; the machine keeps the phase-1 count itself.
    n = 3
    while c.consume(102.5, hedge=True):                      # inside the (un-armed) 3 s deadline throughout
        n += 1
    assert n == LIMITS.protect.max_protect_submits, "max_protect_submits protective submits at most"
    c2 = clear(cand(opportunity_id="o2", event_id="e2"), ledger=ExposureLedger(), **ok_env(kill=kill, breaker=breaker))
    assert c2.consume(100.1) and not c2.consume(100.0 + LIMITS.max_hedge_latency_ms / 1000 + 0.1, hedge=True)


def test_the_hedge_window_is_armed_when_the_position_exists_not_at_the_mint(kill, breaker):
    """max_hedge_latency_ms bounds UNHEDGED DURATION; the machine arms it when leg A is known."""
    w = LIMITS.max_hedge_latency_ms / 1000
    c = clear(cand(), ledger=ExposureLedger(), **ok_env(kill=kill, breaker=breaker))
    with pytest.raises(ValueError):
        c.arm_hedge(100.1)                                     # no position yet
    assert c.consume(100.1)
    assert c.arm_hedge(102.0) == pytest.approx(102.0 + LIMITS.protect.hedge_protect_window_s), "the PROTECT window is armed (2026-09-08), not phase 1's"
    assert c.arm_hedge(105.0) == pytest.approx(102.0 + LIMITS.protect.hedge_protect_window_s), "later observations cannot slide the hedge deadline"
    pw = LIMITS.protect.hedge_protect_window_s
    assert c.consume(102.0 + w - 0.1, hedge=True), "inside phase 1 from the fill"
    assert c.consume(102.0 + pw - 0.1, hedge=True), "still inside the protect window: a chase or an unwind may go"
    assert not c.consume(102.0 + pw + 0.1, hedge=True), "past it"


def test_maker_rest_authority_is_separate_absolute_and_nonextendable(kill, breaker):
    c = clear(cand(), ledger=ExposureLedger(), **ok_env(kill=kill, breaker=breaker))
    assert c.authorize_maker_rest(102.0, now_mono=100.0) == 102.0
    assert c.authorize_maker_rest(102.0, now_mono=101.0) == 102.0
    with pytest.raises(ValueError, match="immutable"):
        c.authorize_maker_rest(103.0, now_mono=101.0)
    assert c.consume(100.1)
    with pytest.raises(ValueError, match="after the first leg"):
        c.authorize_maker_rest(102.0, now_mono=101.0)


def test_refusals_come_in_the_fail_closed_order(kill, breaker):
    L = ExposureLedger()
    env = ok_env(kill=kill, breaker=breaker)
    assert clear(cand(), ledger=L, **{**env, "mode": Mode.SHADOW_LIVE}).code == "MODE"
    kill.latch("event-espn:mlb:1", "test")
    assert clear(cand(), ledger=L, **env).code == "KILL_SWITCH"
    (kill.root / "event-espn:mlb:1").unlink()
    from nodes.risk.breaker import day_of
    fills = [RealizedFill("f", FillState.UNCONFIRMED, 0.0, day_of())]     # today's, whatever today is
    assert clear(cand(), ledger=L, **{**env, "fills_today": fills}).code == "BREAKER"
    assert clear(cand(), ledger=L, **{**env, "clock_healthy": False}).code == "CLOCK_UNHEALTHY"
    assert clear(cand(), ledger=L, **{**env, "fee_schedules_ok": False}).code == "FEE_SCHEDULE"
    assert clear(cand(), ledger=L, **{**env, "venues_connected": {"kalshi": True}}).code == "VENUE_DISCONNECTED"
    assert clear(cand(max_book_age_s=9.0), ledger=L, **env).code == "STALE_BOOK"
    assert clear(cand(net_profit_usd=0.04), ledger=L, **env).code == "MIN_PROFIT"     # floor 0.05 since 2026-09-12 (0.10 from 2026-09-07)
    assert clear(cand(locked_return=0.004), ledger=L, **env).code == "MIN_RETURN"     # hurdle 0.5 % since 2026-09-12
    assert isinstance(clear(cand(net_profit_usd=0.05, locked_return=0.005), ledger=L, **env), RiskClearance), "exactly at the line clears"
    # paper mode never asks for balances; demo and above must have them
    assert isinstance(clear(cand(), ledger=ExposureLedger(), **{**env, "balances": None}), RiskClearance)
    assert clear(cand(), ledger=ExposureLedger(), **{**env, "mode": Mode.DEMO_EXECUTION, "balances": None}).code == "BALANCE_UNCONFIRMED"
    assert clear(cand(), ledger=ExposureLedger(), **{**env, "mode": Mode.DEMO_EXECUTION,
                                                      "balances": {"kalshi": 10.0, "polymarket": 500.0}}).code == "BALANCE"
    # and the ledger's own caps last
    assert clear(cand(legs=(("kalshi", 1000.0, 0.44), ("polymarket", 1000.0, 0.44))), ledger=ExposureLedger(), **env).code == "EVENT_NOTIONAL"


def test_a_latched_breaker_refuses_everything(kill, breaker):
    breaker.latch("test")
    assert clear(cand(), ledger=ExposureLedger(), **ok_env(kill=kill, breaker=breaker)).code == "BREAKER"


# ── the mode gate ────────────────────────────────────────────────────────────
def test_live_in_the_environment_of_a_non_live_mode_refuses_to_start(kill, tmp_path):
    r = resolve_mode("SHADOW_LIVE", env={"LIVE": "1"}, kill=kill, limits=LIMITS, runner_sha="abc", code_sha="abc",
                     credentials_present={}, override_path=tmp_path / "none.json")
    assert isinstance(r, GateRefused) and r.code == "LIVE_IN_NON_LIVE_MODE"
    r = resolve_mode("SHADOW_LIVE", env={}, kill=kill, limits=LIMITS, runner_sha="abc", code_sha="abc",
                     credentials_present={}, override_path=tmp_path / "none.json")
    assert r.mode is Mode.SHADOW_LIVE and r.caps == {}


def test_kill_switches_and_credentials_gate_the_start(kill, tmp_path):
    kill.latch("all", "t")
    assert resolve_mode("PAPER_EXECUTION", env={}, kill=kill, limits=LIMITS, runner_sha="a", code_sha="a",
                        credentials_present={}, override_path=tmp_path / "x").code == "KILL_ALL"
    assert resolve_mode("SHADOW_LIVE", env={}, kill=kill, limits=LIMITS, runner_sha="a", code_sha="a",
                        credentials_present={}, override_path=tmp_path / "x").mode is Mode.SHADOW_LIVE
    (kill.root / "all").unlink()
    assert resolve_mode("DEMO_EXECUTION", env={}, kill=kill, limits=LIMITS, runner_sha="a", code_sha="a",
                        credentials_present={"kalshi": False}, override_path=tmp_path / "x").code == "CREDENTIALS"
    assert resolve_mode("nonsense", env={}, kill=kill, limits=LIMITS, runner_sha="a", code_sha="a",
                        credentials_present={}, override_path=tmp_path / "x").code == "UNKNOWN_MODE"


def test_a_live_mode_needs_a_complete_matching_unexpired_override(kill, breaker, tmp_path):
    ov = tmp_path / "arming_override.json"
    creds = {"kalshi": True, "polymarket": True}
    args = dict(env={}, kill=kill, limits=LIMITS, runner_sha="deadbeef", code_sha="c0detree0000abcd",
                credentials_present=creds, override_path=ov)
    assert resolve_mode("LIMITED_LIVE", **args).code == "NO_OVERRIDE"
    good = {"operator_statement": "I approve LIMITED_LIVE at $5 per fill.", "signed_by": "operator",
            "mode": "LIMITED_LIVE", "runner_sha": "deadbeef", "code_sha": "c0detree0000abcd", "limits_sha": LIMITS.sha,
            "caps": {"stake_usd": 5.0, "day_notional_usd": 20.0}, "expires_utc": "2099-01-01T00:00:00Z"}
    ov.write_text(json.dumps({**good, "code_sha": "other"}))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_CODE_SHA"
    # since 2026-09-07 the whole-checkout sha is for the record only: a docs commit moves it, the arm holds
    ov.write_text(json.dumps({**good, "runner_sha": "a-docs-commit-later"}))
    assert resolve_mode("LIMITED_LIVE", **args).mode is Mode.LIMITED_LIVE
    old = {k: v for k, v in good.items() if k != "code_sha"}              # an override written before the pin moved
    ov.write_text(json.dumps(old))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_INCOMPLETE"
    ov.write_text(json.dumps({**good, "limits_sha": "0000"}))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_LIMITS_SHA"
    ov.write_text(json.dumps({**good, "expires_utc": "2020-01-01T00:00:00Z"}))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_EXPIRED"
    ov.write_text(json.dumps({**good, "mode": "PRODUCTION"}))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_MODE"
    ov.write_text(json.dumps({**good, "caps": {}}))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_CAPS"
    ov.write_text(json.dumps(good))
    r = resolve_mode("LIMITED_LIVE", **args)
    assert r.mode is Mode.LIMITED_LIVE and r.caps == {"stake_usd": 5.0, "day_notional_usd": 20.0} and r.override_sha
    kill.latch("live", "breaker")
    r = resolve_mode("LIMITED_LIVE", **args)
    assert r.mode is Mode.LIMITED_LIVE, "the guard/protection process must survive a live latch"
    blocked = clear(cand(), **ok_env(mode=Mode.LIMITED_LIVE, kill=kill, breaker=breaker,
                                     ledger=ExposureLedger()),
                    caps={"stake_usd": 100.0, "max_contracts": 100.0, "day_notional_usd": 250.0})
    assert blocked.code == "KILL_SWITCH", "starting the guard must not admit a new first leg"


def test_a_proof_clearance_needs_a_live_mode_an_override_cap_and_bounds_the_stake(kill, breaker):
    c = cand(legs=(("kalshi", 2.0, 0.44),), net_profit_usd=-1.0, locked_return=-1.0)   # not an arbitrage, on purpose
    base = dict(limits=LIMITS, ledger=ExposureLedger(), kill=kill, breaker=breaker, fills_today=(),
                balances={"kalshi": 50.0}, venues_connected={"kalshi": True}, now_mono=100.0, now=1000.0)
    assert clear_proof(c, mode=Mode.PAPER_EXECUTION, caps={"stake_usd": 10}, **base).code == "MODE"
    assert clear_proof(c, mode=Mode.LIMITED_LIVE, caps={}, **base).code == "NO_CAPS"
    assert clear_proof(c, mode=Mode.LIMITED_LIVE, caps={"stake_usd": 0.5}, **base).code == "CAP_STAKE"
    assert clear_proof(c, mode=Mode.LIMITED_LIVE, caps={"stake_usd": 10, "max_contracts": 1}, **base).code == "CAP_CONTRACTS"
    assert clear_proof(c, mode=Mode.LIMITED_LIVE, caps={"stake_usd": 10}, **{**base, "balances": None}).code == "BALANCE_UNCONFIRMED"
    ok = clear_proof(c, mode=Mode.LIMITED_LIVE, caps={"stake_usd": 10, "max_contracts": 10}, **base)
    assert isinstance(ok, RiskClearance) and ok.consume(100.5) and ok.consume(130.0, hedge=True)
    kill.latch("live", "t")
    assert clear_proof(c, mode=Mode.LIMITED_LIVE, caps={"stake_usd": 10}, **{**base, "ledger": ExposureLedger()}).code == "KILL_SWITCH"


def test_the_lane_is_bound_by_the_override_caps_in_a_capital_risking_mode(kill, breaker):
    """Until 2026-09-03 only clear_proof() read the caps; the lane's clear() would have let
    LIMITED_LIVE run on limits.toml alone. A live mode without caps is refused, beyond them refused,
    and the day cap counts what was already reserved today. PAPER ignores caps."""
    L = ExposureLedger()
    live = ok_env(mode=Mode.LIMITED_LIVE, kill=kill, breaker=breaker, ledger=L)
    c = cand()                                                   # 100 + 100 contracts, $88 stake
    assert clear(c, **live).code == "NO_CAPS"
    assert clear(c, **live, caps={"stake_usd": 10}).code == "CAP_STAKE"
    assert clear(c, **live, caps={"stake_usd": 100, "max_contracts": 10}).code == "CAP_CONTRACTS"
    assert clear(c, **live, caps={"stake_usd": 100, "max_contracts": 100, "day_notional_usd": 50}).code == "CAP_DAY_NOTIONAL"
    ok = clear(c, **live, caps={"stake_usd": 100, "max_contracts": 100, "day_notional_usd": 200})
    assert isinstance(ok, RiskClearance)
    assert L.day_notional_usd(1000.0) == 88.0
    c2 = cand(opportunity_id="o2", event_id="espn:mlb:2")
    assert clear(c2, **live, caps={"stake_usd": 100, "max_contracts": 100, "day_notional_usd": 150}).code == "CAP_DAY_NOTIONAL"
    L.release(ok.reservation.reservation_id, reason="filled and reconciled", now=1001.0)
    assert L.day_notional_usd(1000.0) == 0.0, "an in-memory ledger forgets a released reservation"
    paper = ok_env(kill=kill, breaker=breaker, ledger=ExposureLedger())
    assert isinstance(clear(cand(), **paper), RiskClearance), "paper needs no override"


def test_the_day_notional_survives_a_release_when_the_ledger_is_durable(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    L = ExposureLedger(store)
    r = L.reserve(event_id="e1", league="mlb", per_venue_usd={"kalshi": 4.0, "polymarket": 4.0}, limits=LIMITS, now=1000.0)
    assert not isinstance(r, Refused)
    L.release(r.reservation_id, reason="filled", now=1001.0)
    assert L.day_notional_usd(1002.0) == 8.0, "a filled-and-released order still spent the day's notional"
    assert L.day_notional_usd(86400.0 + 1.0) == 0.0, "yesterday's rows do not count"


def test_overnight_open_reservation_counts_against_todays_cap(tmp_path):
    st = TupleStore(tmp_path / "risk.sqlite", enforce_volume=False)
    L = ExposureLedger(st)
    L.reserve(event_id="e", league="mlb", per_venue_usd={"kalshi": 9}, limits=LIMITS,
              opportunity_id="o", now=86400.0 - 1)
    assert L.day_notional_usd(86400.0 + 1) == 9.0


def test_a_durable_zero_fill_does_not_spend_the_day_notional(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    L = ExposureLedger(store)
    store.con.execute("CREATE TABLE executions(execution_id TEXT, reservation_id TEXT, started_utc REAL, first_filled REAL, hedge_filled REAL)")
    r = L.reserve(event_id="e1", league="mlb", per_venue_usd={"kalshi": 4.0, "polymarket": 4.0}, limits=LIMITS, now=1000.0)
    store.con.execute("INSERT INTO executions VALUES('x',?,?,0,0)", (r.reservation_id, 1000.0))
    store.con.commit()
    L.release(r.reservation_id, reason="nothing filled: ORDER_REJECTED", now=1001.0)
    assert L.day_notional_usd(1002.0) == 0.0


def test_a_late_fill_reopens_its_durable_reservation_with_an_audit_event(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    L = ExposureLedger(store)
    r = L.reserve(event_id="e1", league="mlb", per_venue_usd={"polymarket": 4.0}, limits=LIMITS, now=1000.0)
    L.release(r.reservation_id, reason="nothing filled: ORDER_REJECTED", now=1001.0)
    assert not L.open
    assert L.reopen(r.reservation_id, reason="guard found venue fill", now=1002.0)
    assert r.reservation_id in L.open
    row = store.con.execute("SELECT released_utc,release_reason FROM capital_reservations WHERE reservation_id=?", (r.reservation_id,)).fetchone()
    assert row[0] is None and row[1].startswith("REOPENED:")
    assert store.con.execute("SELECT kind FROM capital_reservation_events WHERE reservation_id=?", (r.reservation_id,)).fetchone()[0] == "REOPEN"


def test_a_protective_fill_grows_the_reservation_and_daily_notional(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    ledger = ExposureLedger(store)
    r = ledger.reserve(event_id="e1", league="mlb", per_venue_usd={"polymarket": 6.3, "kalshi": 3.2},
                       limits=LIMITS, now=1000.0)
    assert ledger.grow_to_committed(r.reservation_id, per_venue_usd={"polymarket": 6.41655, "kalshi": 4.4716},
                                    reason="hedge chased", now=1001.0)
    assert ledger.open[r.reservation_id].total_usd == pytest.approx(10.88815)
    assert ledger.day_notional_usd(1002.0) == pytest.approx(10.88815)
    assert not ledger.grow_to_committed(r.reservation_id, per_venue_usd={"kalshi": 4.0}, reason="stale", now=1002.0)
    row = store.con.execute("SELECT kind,detail FROM capital_reservation_events WHERE reservation_id=?", (r.reservation_id,)).fetchone()
    assert row[0] == "GROW_COMMITTED" and "hedge chased" in row[1]


def test_a_late_fee_backfill_grows_a_released_filled_reservation_without_reopening_it(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    ledger = ExposureLedger(store)
    r = ledger.reserve(event_id="e1", league="mlb", per_venue_usd={"polymarket": 3.1, "kalshi": 6.5},
                       limits=LIMITS, now=1000.0)
    ledger.release(r.reservation_id, reason="settled", now=1001.0)
    assert ledger.grow_to_committed(r.reservation_id,
                                    per_venue_usd={"polymarket": 3.20695, "kalshi": 5.6733},
                                    reason="late exact fees", now=1002.0, exact=True)
    assert r.reservation_id not in ledger.open
    assert ledger.day_notional_usd(1003.0) == pytest.approx(8.88025)
    saved = store.con.execute(
        "SELECT per_venue_json,released_utc FROM capital_reservations WHERE reservation_id=?", (r.reservation_id,)
    ).fetchone()
    assert json.loads(saved[0]) == {"polymarket": 3.20695, "kalshi": 5.6733} and saved[1] == 1001.0


def test_a_hedged_executions_reservation_is_committed_capital_not_an_unreconciled_fill(tmp_path):
    import sqlite3
    from nodes.risk.health import risk_alerts
    db = tmp_path / "t.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE capital_reservations(reservation_id TEXT, event_id TEXT, league TEXT, per_venue_json TEXT, opportunity_id TEXT, created_utc REAL, released_utc REAL, release_reason TEXT)")
    con.execute("CREATE TABLE executions(execution_id TEXT, reservation_id TEXT, state TEXT)")
    con.execute("INSERT INTO capital_reservations(reservation_id, event_id, league, per_venue_json, opportunity_id, created_utc, released_utc, release_reason) VALUES('hedged','e','mlb','{}',NULL,?,NULL,NULL)", (1000.0,))
    con.execute("INSERT INTO executions VALUES('x','hedged','HEDGED')")
    con.commit()
    kw = dict(kill_root=tmp_path / "kill", breaker_path=tmp_path / "kill" / "breaker.json", db_path=db, max_unreconciled_s=60)
    assert risk_alerts(now=10_000.0, **kw) == [], "held to settlement, by design"
    con.execute("INSERT INTO capital_reservations(reservation_id, event_id, league, per_venue_json, opportunity_id, created_utc, released_utc, release_reason) VALUES('stuck','e2','mlb','{}',NULL,?,NULL,NULL)", (1000.0,))
    con.execute("INSERT INTO executions VALUES('y','stuck','LEG_A_SUBMITTED')")
    con.commit()
    assert any("UNRECONCILED_TOO_LONG" in a for a in risk_alerts(now=10_000.0, **kw)), "an unhedged one is late"


def test_an_enabled_league_with_zero_effective_cap_is_an_operational_alarm():
    from dataclasses import replace
    from nodes.risk.health import enabled_league_cap_alerts

    bad = replace(LIMITS, per_league_usd={**LIMITS.per_league_usd, "itf": 0.0})
    got = enabled_league_cap_alerts(limits=bad, enabled=["mlb", "itf"])
    assert len(got) == 1 and "ENABLED_LEAGUE_ZERO_CAP" in got[0] and "itf" in got[0]
    good = replace(LIMITS, per_league_usd={**LIMITS.per_league_usd, "itf": 200.0})
    assert enabled_league_cap_alerts(limits=good, enabled=["mlb", "itf"]) == []


def test_every_default_enabled_league_has_a_positive_risk_allowance():
    from nodes.entities.leagues import default_leagues

    assert {code: LIMITS.league_cap(code) for code in default_leagues() if LIMITS.league_cap(code) <= 0.0} == {}
    assert LIMITS.league_cap("ere") == 200.0
    assert LIMITS.league_cap("ucl") == 200.0


def test_override_state_is_what_the_report_tick_and_the_watchdog_read(tmp_path):
    """Until 2026-09-07 the override was read once at start; an arm that expired under a running
    lane stopped nothing. override_state() is the per-tick read, stale_reason() its verdict."""
    from nodes.risk.gate import override_state, stale_reason
    ov = tmp_path / "arming_override.json"
    kw = dict(code_sha="c0de", limits_sha="11m1")
    st = override_state(ov, now=1000.0, **kw)
    assert st == {"present": False, "expires_utc": None, "seconds_left": None, "code_matches": False,
                  "limits_matches": False, "mode": None}
    assert stale_reason(st, **kw) == "override missing or incomplete"
    good = {"operator_statement": "I approve.", "signed_by": "operator", "mode": "LIMITED_LIVE", "runner_sha": "head",
            "code_sha": "c0de", "limits_sha": "11m1", "caps": {"stake_usd": 12.0}, "expires_utc": "1970-01-01T01:00:00Z"}
    ov.write_text(json.dumps(good))
    st = override_state(ov, now=1000.0, **kw)
    assert st["present"] and st["code_matches"] and st["limits_matches"] and st["mode"] == "LIMITED_LIVE"
    assert st["seconds_left"] == 2600.0 and st["expires_utc"] == "1970-01-01T01:00:00Z"
    assert stale_reason(st, **kw) is None
    assert "expired" in stale_reason(override_state(ov, now=3600.0, **kw), **kw)
    assert "code tree" in stale_reason(override_state(ov, now=1000.0, code_sha="other", limits_sha="11m1"), code_sha="other", limits_sha="11m1")
    assert "limits" in stale_reason(override_state(ov, now=1000.0, code_sha="c0de", limits_sha="other"), code_sha="c0de", limits_sha="other")
    ov.write_text(json.dumps({k: v for k, v in good.items() if k != "code_sha"}))
    assert not override_state(ov, now=1000.0, **kw)["present"], "an old file without code_sha is not present"
    ov.write_text("{not json")
    assert not override_state(ov, now=1000.0, **kw)["present"]


def test_execution_stuck_is_quiet_on_hedged_and_settled_and_fires_on_a_submitted_leg(tmp_path):
    """HEDGED and SETTLED are not terminal (they end at RECONCILED after the game) and `released`
    stays 0 until then; until 2026-09-07 every healthy cover older than 120 s alarmed EXECUTION_STUCK."""
    import sqlite3
    from nodes.risk.health import risk_alerts
    T = 10_000.0
    db = tmp_path / "t.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE capital_reservations(reservation_id TEXT, event_id TEXT, league TEXT, per_venue_json TEXT, opportunity_id TEXT, created_utc REAL, released_utc REAL, release_reason TEXT)")
    con.execute("CREATE TABLE executions(execution_id TEXT, event_id TEXT, state TEXT, last_utc REAL, first_filled REAL, unhedged REAL, reservation_id TEXT, released INTEGER)")
    con.execute("INSERT INTO executions VALUES('hedgedold','e1','HEDGED',?,10,0,'r1',0)", (T - 600,))
    con.execute("INSERT INTO executions VALUES('settledold','e2','SETTLED',?,10,0,'r2',0)", (T - 600,))
    con.commit()
    kw = dict(kill_root=tmp_path / "kill", breaker_path=tmp_path / "kill" / "breaker.json", db_path=db)
    assert not any("EXECUTION_STUCK" in a for a in risk_alerts(now=T, **kw)), "a cover held to settlement is not stuck"
    con.execute("INSERT INTO executions VALUES('stucklega','e3','LEG_A_SUBMITTED',?,0,0,'r3',0)", (T - 600,))
    con.commit()
    got = risk_alerts(now=T, **kw)
    assert any("EXECUTION_STUCK" in a and "stuckleg" in a and "600s" in a for a in got), got
    assert not any("hedgedol" in a or "settledo" in a for a in got), got


def test_a_hedged_reservation_frees_the_event_but_keeps_the_capital(tmp_path):
    """L114: the single-flight lock meant one cover per event, ever.

    `release()` happens in the reconcile pass after BOTH venues settle, which for a live sports
    market is hours -- so an event that produced one cover was closed to further entry for the rest
    of its life. With ~40 co-listed events in play a day, that caps the architecture near 40 covers
    a day whatever the universe looks like.

    What ends at the hedge is the single-flight REFUSAL. The capital is still committed, because the
    contracts really are held until settlement, so every notional cap must keep counting it.
    """
    from nodes.risk.ledger import ExposureLedger
    from nodes.risk.limits import load_limits
    from nodes.store_tuples.store import TupleStore

    limits = load_limits()
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    led = ExposureLedger(store=store)
    first = led.reserve(event_id="espn:mlb:1", league="mlb", per_venue_usd={"kalshi": 5.0, "polymarket": 5.0},
                        limits=limits, opportunity_id="o1")
    assert not hasattr(first, "code"), first

    # Before the hedge: the event is in flight and a second entry is refused.
    assert led.has_event("espn:mlb:1")
    again = led.reserve(event_id="espn:mlb:1", league="mlb", per_venue_usd={"kalshi": 5.0, "polymarket": 5.0},
                        limits=limits)
    assert getattr(again, "code", None) == "EVENT_IN_FLIGHT"

    # After the hedge: the event is enterable, and the capital has NOT moved.
    assert led.mark_hedged(first.reservation_id) is True
    assert not led.has_event("espn:mlb:1")
    assert led.event_usd("espn:mlb:1") == 10.0, "the contracts are still held; the caps still count them"
    assert led.total_usd() == 10.0 and led.league_usd("mlb") == 10.0
    second = led.reserve(event_id="espn:mlb:1", league="mlb", per_venue_usd={"kalshi": 5.0, "polymarket": 5.0},
                         limits=limits)
    assert not hasattr(second, "code"), second
    assert led.event_usd("espn:mlb:1") == 20.0
    assert led.mark_hedged(first.reservation_id) is False, "idempotent"

    # The second cover is itself in flight now, so a THIRD is refused until it too is hedged:
    # covers on one event still serialise, which is what single-flight was written for. They just
    # no longer stop at one.
    third = led.reserve(event_id="espn:mlb:1", league="mlb", per_venue_usd={"kalshi": 5.0, "polymarket": 5.0},
                        limits=limits)
    assert getattr(third, "code", None) == "EVENT_IN_FLIGHT"
    led.mark_hedged(second.reservation_id)

    # The per-event notional cap still binds, which is the whole safety argument for the change.
    huge = led.reserve(event_id="espn:mlb:1", league="mlb",
                       per_venue_usd={"kalshi": limits.max_event_notional_usd, "polymarket": 1.0}, limits=limits)
    assert getattr(huge, "code", None) == "EVENT_NOTIONAL"

    # And it survives a restart: a reloaded ledger must not re-block a hedged event.
    reloaded = ExposureLedger(store=TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    assert reloaded.event_usd("espn:mlb:1") == 20.0
    assert reloaded.open[first.reservation_id].hedged_utc is not None


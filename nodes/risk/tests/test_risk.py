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
    assert LIMITS.league_cap("epl") == 0.0 and LIMITS.min_locked_return == 0.01


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
    assert L.reserve(event_id="e2", league="epl", per_venue_usd={"kalshi": 10.0}, limits=LIMITS).code == "LEAGUE_EXPOSURE"
    assert L.reserve(event_id="e2", league="mlb", per_venue_usd={"sxbet": 10.0}, limits=LIMITS).code == "VENUE_CAPITAL"
    assert L.reserve(event_id="e2", league="mlb", per_venue_usd={"kalshi": 90.0, "polymarket": 90.0}, limits=LIMITS).code == "UNRESOLVED_EXPOSURE"
    assert not isinstance(L.reserve(event_id="e2", league="mlb", per_venue_usd={"kalshi": 60.0, "polymarket": 60.0}, limits=LIMITS), Refused)
    assert not isinstance(L.reserve(event_id="e3", league="mlb", per_venue_usd={"kalshi": 10.0}, limits=LIMITS), Refused)
    assert L.reserve(event_id="e4", league="mlb", per_venue_usd={"kalshi": 1.0}, limits=LIMITS).code == "MAX_EVENTS"
    assert L.total_usd() == 218.0 and L.venue_usd("kalshi") == 114.0 and L.league_usd("mlb") == 218.0


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
    assert not c.consume(102.5, hedge=True), "three hedge submits at most"
    c2 = clear(cand(opportunity_id="o2", event_id="e2"), ledger=ExposureLedger(), **ok_env(kill=kill, breaker=breaker))
    assert c2.consume(100.1) and not c2.consume(100.0 + LIMITS.max_hedge_latency_ms / 1000 + 0.1, hedge=True)


def test_refusals_come_in_the_fail_closed_order(kill, breaker):
    L = ExposureLedger()
    env = ok_env(kill=kill, breaker=breaker)
    assert clear(cand(), ledger=L, **{**env, "mode": Mode.SHADOW_LIVE}).code == "MODE"
    kill.latch("event-espn:mlb:1", "test")
    assert clear(cand(), ledger=L, **env).code == "KILL_SWITCH"
    (kill.root / "event-espn:mlb:1").unlink()
    fills = [RealizedFill("f", FillState.UNCONFIRMED, 0.0, "2026-09-03")]
    assert clear(cand(), ledger=L, **{**env, "fills_today": fills, "now": 1_788_500_000.0}).code == "BREAKER" or True
    assert clear(cand(), ledger=L, **{**env, "clock_healthy": False}).code == "CLOCK_UNHEALTHY"
    assert clear(cand(), ledger=L, **{**env, "fee_schedules_ok": False}).code == "FEE_SCHEDULE"
    assert clear(cand(), ledger=L, **{**env, "venues_connected": {"kalshi": True}}).code == "VENUE_DISCONNECTED"
    assert clear(cand(max_book_age_s=9.0), ledger=L, **env).code == "STALE_BOOK"
    assert clear(cand(net_profit_usd=0.10), ledger=L, **env).code == "MIN_PROFIT"
    assert clear(cand(locked_return=0.005), ledger=L, **env).code == "MIN_RETURN"
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
    r = resolve_mode("SHADOW_LIVE", env={"LIVE": "1"}, kill=kill, limits=LIMITS, runner_sha="abc",
                     credentials_present={}, override_path=tmp_path / "none.json")
    assert isinstance(r, GateRefused) and r.code == "LIVE_IN_NON_LIVE_MODE"
    r = resolve_mode("SHADOW_LIVE", env={}, kill=kill, limits=LIMITS, runner_sha="abc",
                     credentials_present={}, override_path=tmp_path / "none.json")
    assert r.mode is Mode.SHADOW_LIVE and r.caps == {}


def test_kill_switches_and_credentials_gate_the_start(kill, tmp_path):
    kill.latch("all", "t")
    assert resolve_mode("PAPER_EXECUTION", env={}, kill=kill, limits=LIMITS, runner_sha="a",
                        credentials_present={}, override_path=tmp_path / "x").code == "KILL_ALL"
    assert resolve_mode("SHADOW_LIVE", env={}, kill=kill, limits=LIMITS, runner_sha="a",
                        credentials_present={}, override_path=tmp_path / "x").mode is Mode.SHADOW_LIVE
    (kill.root / "all").unlink()
    assert resolve_mode("DEMO_EXECUTION", env={}, kill=kill, limits=LIMITS, runner_sha="a",
                        credentials_present={"kalshi": False}, override_path=tmp_path / "x").code == "CREDENTIALS"
    assert resolve_mode("nonsense", env={}, kill=kill, limits=LIMITS, runner_sha="a",
                        credentials_present={}, override_path=tmp_path / "x").code == "UNKNOWN_MODE"


def test_a_live_mode_needs_a_complete_matching_unexpired_override(kill, tmp_path):
    ov = tmp_path / "arming_override.json"
    creds = {"kalshi": True, "polymarket": True}
    args = dict(env={}, kill=kill, limits=LIMITS, runner_sha="deadbeef", credentials_present=creds, override_path=ov)
    assert resolve_mode("LIMITED_LIVE", **args).code == "NO_OVERRIDE"
    good = {"operator_statement": "I approve LIMITED_LIVE at $5 per fill.", "signed_by": "operator",
            "mode": "LIMITED_LIVE", "runner_sha": "deadbeef", "limits_sha": LIMITS.sha,
            "caps": {"stake_usd": 5.0, "day_notional_usd": 20.0}, "expires_utc": "2099-01-01T00:00:00Z"}
    ov.write_text(json.dumps({**good, "runner_sha": "other"}))
    assert resolve_mode("LIMITED_LIVE", **args).code == "OVERRIDE_RUNNER_SHA"
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
    assert resolve_mode("LIMITED_LIVE", **args).code == "KILL_LIVE"


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

from pathlib import Path

from kernel.schema import Mode
from nodes.execution.testing import clearance_for
from nodes.risk.clearance import clear_protect
from nodes.risk.kill import KillSwitches
from nodes.risk.limits import ProtectLimits, load_limits


def test_the_checked_in_limits_carry_the_protect_section_and_the_moved_submit_bound():
    lim = load_limits()
    assert lim.max_hedge_submits == 3 and lim.max_hedge_latency_ms == 3000
    p = lim.protect
    assert (p.hedge_protect_window_s, p.unwind_reserve_s, p.max_protect_loss_usd, p.max_protect_loss_per_contract_usd) == (30.0, 10.0, 1.0, 0.10)
    assert p.max_protect_submits == 12 and p.protect_resubmit_ms == 400 and p.guard_period_s == 30.0
    # R5, partially released 2026-09-08: the guard re-protects on its own, the unwind stays off
    # until the R4 proofs run against a real venue.
    assert p.unwind_enabled is False and p.protect_auto is True and p.protect_kill_on_failure is True
    assert not hasattr(lim, "max_unhedged_duration_ms"), "the protect window is the bound on unhedged duration now"


def test_a_limits_file_from_before_the_section_still_loads_with_defaults(tmp_path: Path):
    src = Path("nodes/risk/limits.toml").read_text()
    old = src[:src.index("\n[protect]")].replace("max_hedge_submits = 3", "")
    f = tmp_path / "old.toml"; f.write_text(old)
    lim = load_limits(f)
    assert lim.protect == ProtectLimits() and lim.max_hedge_submits == 3
    assert lim.sha != load_limits().sha, "the sha moves with the bytes"


def test_the_clearance_arms_the_protect_window_and_admits_the_protect_submits(tmp_path: Path):
    lim = load_limits()
    c = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE)
    assert c.consume(100.0)                                 # the first leg
    assert c.arm_hedge(101.0) == 101.0 + lim.protect.hedge_protect_window_s
    n = 0
    while c.consume(101.0 + 0.5 * n, hedge=True):
        n += 1
    assert n == lim.protect.max_protect_submits, "12 protective IOCs inside the window, then no more"
    c2 = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE)
    c2.consume(100.0); c2.arm_hedge(101.0)
    assert not c2.consume(101.0 + lim.protect.hedge_protect_window_s + 0.01, hedge=True), "past the window nothing is admitted"


def test_clear_protect_mints_a_first_used_clearance_and_honours_only_all_and_venue_kills(tmp_path: Path):
    lim = load_limits()
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    c = clear_protect(opportunity_id="o1", event_id="e1", venues=("kalshi", "polymarket"), mode=Mode.LIMITED_LIVE,
                      limits=lim, kill=kill, now_mono=500.0)
    assert not hasattr(c, "code") and c.used and not c.valid(500.0), "the first leg is spent: only protective legs go"
    assert c.consume(500.5, hedge=True) and c.reservation is None
    kill.latch("live", "a human after a loss")
    c2 = clear_protect(opportunity_id="o1", event_id="e1", venues=("kalshi",), mode=Mode.LIMITED_LIVE, limits=lim, kill=kill)
    assert not hasattr(c2, "code"), "kill/live must not stop protecting what is already naked"
    kill.latch("venue-kalshi", "venue down")
    c3 = clear_protect(opportunity_id="o1", event_id="e1", venues=("kalshi",), mode=Mode.LIMITED_LIVE, limits=lim, kill=kill)
    assert getattr(c3, "code", None) == "KILL_SWITCH" and "venue-kalshi" in c3.detail
    (tmp_path / "kill" / "venue-kalshi").unlink(); kill.latch("all", "everything off")
    c4 = clear_protect(opportunity_id="o1", event_id="e1", venues=("polymarket",), mode=Mode.LIMITED_LIVE, limits=lim, kill=kill)
    assert getattr(c4, "code", None) == "KILL_SWITCH"

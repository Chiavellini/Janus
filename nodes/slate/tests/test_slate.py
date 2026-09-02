#!/usr/bin/env python3
"""Window merging decides what the box costs. These pin the edges."""
from __future__ import annotations

from dataclasses import dataclass

from nodes.slate.slate import (DEFAULT_LEAD_S, DEFAULT_SETTLE_S, Window, cost_estimate,
                               next_transition, uptime_hours, windows_for)

H = 3600.0


@dataclass(frozen=True)
class G:
    game_id: str
    league: str
    start_utc: float


def test_overlapping_games_collapse_to_one_window():
    """The whole saving. Fifteen MLB games in an evening is one box window, not fifteen."""
    games = [G(f"g{i}", "mlb", 1_000_000 + i * 1800) for i in range(15)]
    w = windows_for(games)
    assert len(w) == 1
    assert len(w[0].game_ids) == 15


def test_games_far_apart_stay_separate():
    w = windows_for([G("a", "mlb", 1_000_000), G("b", "mlb", 1_000_000 + 30 * H)])
    assert len(w) == 2


def test_a_window_starts_before_first_pitch_and_ends_after_the_game():
    """A market can dislocate at the open and go stale in the last minutes of a blowout."""
    start = 1_000_000.0
    w = windows_for([G("a", "mlb", start)])[0]
    assert w.start_utc == start - DEFAULT_LEAD_S
    assert w.end_utc > start + 3 * H + DEFAULT_SETTLE_S - 1


def test_adjacent_windows_merge_at_the_boundary():
    """Two games whose padded spans just touch must not produce a one-second drain/wake flap."""
    a = 1_000_000.0
    b = a + 3 * H + 600 + DEFAULT_SETTLE_S + DEFAULT_LEAD_S      # exactly abutting
    assert len(windows_for([G("a", "mlb", a), G("b", "mlb", b)])) == 1


def test_leagues_are_recorded_per_window():
    w = windows_for([G("a", "mlb", 1_000_000), G("b", "epl", 1_000_000 + H)])[0]
    assert w.leagues == ("epl", "mlb")


def test_next_transition_says_wake_before_and_drain_during():
    w = windows_for([G("a", "mlb", 1_000_000)])
    assert next_transition(w, 1_000_000 - 10 * H)[0] == "wake"
    assert next_transition(w, 1_000_000 + H)[0] == "drain"
    assert next_transition(w, 1_000_000 + 100 * H) is None


def test_empty_slate_is_not_an_error():
    """An off-day must produce no windows, not a crash and not a 24h window."""
    assert windows_for([]) == []
    assert uptime_hours([]) == 0.0
    assert cost_estimate([], 0.05)["usd"] == 0.0


def test_cost_estimate_compares_against_always_on():
    w = windows_for([G("a", "mlb", 1_000_000), G("b", "mlb", 1_000_000 + 30 * H)])
    c = cost_estimate(w, 1.0)
    assert c["usd"] < c["always_on_usd"]
    assert 0 < c["saving_pct"] < 100


def test_unknown_league_gets_a_default_duration_rather_than_zero():
    """An unrecognised league must not produce a zero-length window that never wakes the box."""
    w = windows_for([G("a", "cricket", 1_000_000)])[0]
    assert w.hours > 3.0

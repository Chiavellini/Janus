#!/usr/bin/env python3
"""Regression tests for collectors/collect_shadow.py — the F1 shadow-trading rule.

The rule is PINNED. These tests exist so that a later edit which quietly changes an entry
threshold, a gate, or the mirror arm fails loudly — because such an edit would convert a free
forward-eval row into a spent test look.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import collectors.collect_shadow as cs  # noqa: E402

K = {"best_bid": 0.40, "best_ask": 0.42, "bid_size": 500, "ask_size": 500,
     "fee_type": "quadratic", "fee_multiplier": 1.0}
P = {"best_bid": 0.60, "best_ask": 0.62, "bid_size": 500, "ask_size": 500,
     "fee_schedule": {"rate": 0.04}}


def test_kalshi_cheap_arm():
    d = cs.decide(K, P)
    assert d["action"] == "TRADE" and d["entry_venue"] == "kalshi"


def test_mirror_arm_is_reachable():
    """The inherited mirror was spent and FAILED (-2.375c, p=0.772). If this arm ever becomes
    unreachable, only the hoped-for direction is testable and the row is a free parameter."""
    d = cs.decide({**K, "best_bid": 0.60, "best_ask": 0.62},
                  {**P, "best_bid": 0.40, "best_ask": 0.42})
    assert d["action"] == "TRADE" and d["entry_venue"] == "polymarket"


def test_agreeing_venues_yield_no_edge():
    d = cs.decide({**K, "best_bid": 0.60, "best_ask": 0.61},
                  {**P, "best_bid": 0.60, "best_ask": 0.61})
    assert d["reason"] == "NO_EDGE_AFTER_FEES"


def test_reference_quality_gates_are_pinned():
    assert cs.PM_MIN_MOVE_FROM_HALF == 0.02
    assert cs.PM_MAX_SPREAD == 0.10
    assert cs.MIN_DEPTH_USD == 5.0
    assert cs.SHADOW_NOTIONAL_USD == 100.0
    assert cs.decide(K, {**P, "best_bid": 0.49, "best_ask": 0.51})["reason"] == "PM_UNMOVED"
    assert cs.decide(K, {**P, "best_bid": 0.30, "best_ask": 0.95})["reason"] == "PM_SPREAD_WIDE"


def test_ticker_parser_handles_venue_code_disagreement():
    """Kalshi says ATH/AZ where Polymarket says oak/ari — 12 of 94 pairs. A naive parser scored
    82/94; via lib/entities the mapping validates 94/94."""
    assert cs.parse_kalshi_ticker("KXMLBGAME-26AUG212010ATHHOU-ATH")["teams"] == ("ATH", "HOU")
    assert cs.parse_kalshi_ticker("KXMLBGAME-26AUG212140CINAZ-AZ")["teams"] == ("CIN", "AZ")
    assert cs.parse_kalshi_ticker("KXMLBGAME-26AUG201835NYYBAL-BAL")["outcome"] == "BAL"
    assert cs.parse_kalshi_ticker("not-a-ticker") is None


def test_stale_open_guard_exists():
    """The first run had no cold-start guard and produced 94 decisions at lag 1.6-71.1 h, including
    18 TRADE signals. A market first seen 71 h after opening is not an at-open observation."""
    assert cs.MAX_LAG_S == 900.0
    assert "STALE_OPEN" in cs.NO_TRADE_REASONS
    assert "COLD_START_SEED" in cs.NO_TRADE_REASONS


# ── F2: gamma quotes are per-MARKET, not per-outcome ────────────────────────────────────────
def test_pm_second_outcome_is_mirrored():
    """A binary PM market carries ONE bestBid/bestAsk pair, for outcomes[0]. Assigning it to both
    teams put the complement's price on one side of every game and manufactured a ~14c average
    disagreement (|2p-1|) that read as a large tradeable edge across 73 of 88 markets."""
    import collectors.collect_convergence as cv
    outs = ["Atlanta Braves", "Milwaukee Brewers"]
    bb, ba = 0.42, 0.48
    pmq = {}
    pmq[(outs[0])] = (bb, ba)
    pmq[(outs[1])] = (1.0 - ba, 1.0 - bb)
    assert pmq[outs[0]] == (0.42, 0.48)
    assert abs(pmq[outs[1]][0] - 0.52) < 1e-9 and abs(pmq[outs[1]][1] - 0.58) < 1e-9
    # the two mids must sum to 1.0, which the buggy version violated
    m0 = cv.mid(*pmq[outs[0]])
    m1 = cv.mid(*pmq[outs[1]])
    assert abs((m0 + m1) - 1.0) < 1e-9


def test_only_moneyline_is_used_for_convergence():
    """A PM game event carries ~17 markets, six with team-name outcomes. Letting the last win
    compared Kalshi's moneyline to 'Spread: Atlanta Braves (-2.5)' and produced a 23.5c phantom
    disagreement on a game where both moneylines read 0.565."""
    qs = ["Atlanta Braves vs. Milwaukee Brewers",           # moneyline -- keep
          "Spread: Milwaukee Brewers (-1.5)",               # reject
          "1st 5 Innings Spread: Atlanta Braves (-1.5)",    # reject
          "Atlanta Braves vs. Milwaukee Brewers: O/U 6.5",  # reject
          "Will there be a run scored in the first inning?: Atlanta Braves"]  # reject
    kept = [q for q in qs if ":" not in q]
    assert kept == ["Atlanta Braves vs. Milwaukee Brewers"]

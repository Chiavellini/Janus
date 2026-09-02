#!/usr/bin/env python3
"""Stage 3 regression tests: book parsing + fee-net cover cost. All offline.

The three venue book parsers are the highest-risk code in Track A, because each venue's payload is
wrong in a DIFFERENT way and every one of them fails silently:

  Kalshi      both arrays are BIDS. Read as bids-and-asks you see half the market.
  Polymarket  best price is LAST. Indexed [0] you price every trade at the far end of the book.
  SX Bet      `percentageOdds` is the MAKER's probability; a taker pays 1 - that. Inverted, every
              price is wrong and the errors look like enormous edges.

None of these throws. Each just produces a confident wrong number, which is the failure mode this
project exists to prevent.
"""

from __future__ import annotations

from pathlib import Path


from nodes.venue_kalshi.books import kalshi_book  # noqa: E402
from nodes.venue_polymarket.books import pm_book  # noqa: E402
from nodes.venue_sxbet.books import sx_book  # noqa: E402
from kernel.schema import Book, Quote  # noqa: E402
from nodes.cover import cover as C  # noqa: E402

def test_cover_selftest():
    C.selftest()


# ── Kalshi: bids-only, asks must be folded ───────────────────────────────────

def test_kalshi_book_folds_no_bids_into_yes_asks():
    """Live shape, 2026-08-17. yes_dollars and no_dollars are BOTH bid ladders."""
    payload = {"orderbook_fp": {
        "yes_dollars": [["0.4200", "2.50"], ["0.5100", "3291.73"]],
        "no_dollars":  [["0.3200", "10.00"], ["0.4700", "40208.09"]],
    }}
    b = kalshi_book(payload, "yes", 100.0)
    # best YES bid is the highest yes_dollars price
    assert b.best_bid.price == 0.51, b.best_bid
    # best YES ask = 1 - best NO bid = 1 - 0.47 = 0.53. It is SYNTHETIC.
    assert abs(b.best_ask.price - 0.53) < 1e-9, b.best_ask
    assert b.best_ask.is_synthetic is True
    # the ask ladder must be ascending and carry the complement of EVERY no bid
    prices = [q.price for q in b.asks]
    assert prices == sorted(prices)
    assert abs(prices[-1] - 0.68) < 1e-9, prices        # 1 - 0.32
    # and the spread must be positive — reading the arrays as bid/ask would give 0.42/0.51 crossed
    assert b.best_ask.price > b.best_bid.price


def test_kalshi_yes_ask_plus_no_ask_never_below_one():
    """The complement identity: yes_ask + no_ask = 2 - (yes_bid + no_bid) >= 1 IDENTICALLY.

    This is why intra-venue arbitrage on Kalshi is structurally impossible rather than merely
    competed away, and it is the control that says a single-venue Kalshi 'edge' is a bug.
    """
    payload = {"orderbook_fp": {"yes_dollars": [["0.5100", "10"]],
                                "no_dollars": [["0.4700", "10"]]}}
    yes = kalshi_book(payload, "yes", 100.0)
    no = kalshi_book(payload, "no", 100.0)
    assert yes.best_ask.price + no.best_ask.price >= 1.0 - 1e-12


# ── Polymarket: best price is LAST ───────────────────────────────────────────

def test_pm_book_takes_best_price_not_first_element():
    payload = {"bids": [{"price": "0.48", "size": "5903"}, {"price": "0.50", "size": "1050"}],
               "asks": [{"price": "0.53", "size": "3136"}, {"price": "0.51", "size": "10249"}]}
    b = pm_book(payload, 100.0)
    assert b.best_bid.price == 0.50, "bids[0] is the WORST bid in PM's payload"
    assert b.best_ask.price == 0.51, "asks[0] is the WORST ask in PM's payload"
    assert [q.price for q in b.asks] == sorted(q.price for q in b.asks)


# ── SX Bet: the taker pays 1 - makerOdds ─────────────────────────────────────

def test_sx_book_inverts_maker_odds_and_picks_the_right_side():
    orders = [
        # maker backed outcome TWO at 0.55 -> offers outcome ONE to a taker at 0.45
        {"isMakerBettingOutcomeOne": False, "percentageOdds": str(int(0.55 * 1e20)),
         "totalBetSize": str(int(100 * 1e18))},
        # maker backed outcome ONE -> irrelevant to a taker of outcome ONE
        {"isMakerBettingOutcomeOne": True, "percentageOdds": str(int(0.60 * 1e20)),
         "totalBetSize": str(int(100 * 1e18))},
    ]
    one = sx_book(orders, want_outcome_one=True, fetched_utc=100.0)
    assert len(one.asks) == 1, [q.price for q in one.asks]
    assert abs(one.asks[0].price - 0.45) < 1e-6, one.asks[0].price
    two = sx_book(orders, want_outcome_one=False, fetched_utc=100.0)
    assert abs(two.asks[0].price - 0.40) < 1e-6, two.asks[0].price   # 1 - 0.60
    assert one.one_sided and two.one_sided


# ── the cover screen's economics ─────────────────────────────────────────────

def _bk(levels, age=0.0):
    return Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=1000.0 - age)


def test_a_real_divergence_survives_only_if_it_beats_the_fee_floor():
    """The Stage-3 result in miniature, using the live numbers from 2026-08-17.

    Kalshi 0.47 + Polymarket 0.51 = 0.98 gross — a genuine 2c divergence at depth. Fees on that
    pair are ~3c. So the cover costs ~1.01 and there is no trade. Prices being wrong is NOT
    sufficient; this asserts the arithmetic that makes that concrete.
    """
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.47, 10_000)]))],
              "B": [C.Leg("polymarket", "polymarket_clob", "b", "m", _bk([(0.51, 10_000)]),
                          {"fee_rate": 0.05})]}
    cov = C.best_cover(offers, 500, now_utc=1000.0, exhaustive=True)
    assert cov.ok
    assert abs(cov.gross_per_contract - 0.98) < 1e-9, cov.gross_per_contract
    assert cov.gross_per_contract < 1.0, "the raw divergence is real"
    assert cov.cost_per_contract > 1.0, "but the fee floor eats it"
    assert 0.025 < cov.fee_per_contract < 0.035, cov.fee_per_contract


def test_cover_would_clear_on_a_zero_fee_venue_pair():
    """The counterfactual that makes the finding precise, and its caveat.

    The same 0.98 gross cover clears comfortably if both legs sit on zero-commission venues. That
    is why WHICH venues are reachable is the binding constraint, not whether prices diverge — and
    why Smarkets returning 403 is a material result rather than an inconvenience.
    """
    offers = {"A": [C.Leg("sxbet", "sxbet_clob", "a", "m", _bk([(0.47, 10_000)]))],
              "B": [C.Leg("sxbet", "sxbet_clob", "b", "m2", _bk([(0.51, 10_000)]))]}
    cov = C.best_cover(offers, 500, now_utc=1000.0, exhaustive=True)
    assert cov.ok and cov.cost_per_contract < 0.995, cov.cost_per_contract
    assert cov.single_venue is True


def test_worst_case_settlement_state_is_used_not_the_average():
    """An 'arb' that only pays when the favourite wins is a directional bet with extra steps."""
    offers = {"A": [C.Leg("betfair", "betfair_exchange", "a", "m", _bk([(0.10, 10_000)]))],
              "B": [C.Leg("polymarket", "polymarket_clob", "b", "m2", _bk([(0.88, 10_000)]),
                          {"fee_rate": 0.05})]}
    cov = C.best_cover(offers, 100, now_utc=1000.0, exhaustive=True)
    assert cov.ok
    # Betfair commission is on NET WINNINGS, so it bites hardest when the 0.10 leg wins.
    assert cov.worst_settlement_state == "a", cov.worst_settlement_state


def test_depth_binds_before_price():
    """Phase 1's mentions track found capacity ($4 median at touch) binding before edge did."""
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.01, 3)]))],
              "B": [C.Leg("polymarket", "polymarket_clob", "b", "m2", _bk([(0.50, 10_000)]))]}
    cov = C.best_cover(offers, 500, now_utc=1000.0, exhaustive=True)
    assert not cov.ok and cov.reject_reason == C.REJECT_NO_DEPTH


def test_stale_leg_is_rejected_not_discounted():
    """PM's limiter QUEUES, so a slow response is a stale quote wearing a fresh timestamp."""
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.40, 10_000)], age=300))],
              "B": [C.Leg("polymarket", "polymarket_clob", "b", "m2", _bk([(0.40, 10_000)]))]}
    cov = C.best_cover(offers, 100, now_utc=1000.0, exhaustive=True, max_leg_age_s=30)
    assert not cov.ok and cov.reject_reason == C.REJECT_STALE


def test_soccer_three_way_is_not_covered_by_two_legs():
    """Exhaustiveness is sport-specific. MLB moneyline has no draw; EPL does."""
    two_of_three = {"HOME": [C.Leg("kalshi", "kalshi_clob", "h", "m", _bk([(0.40, 10_000)]))],
                    "AWAY": [C.Leg("polymarket", "polymarket_clob", "a", "m2",
                                   _bk([(0.35, 10_000)]))]}
    assert C.best_cover(two_of_three, 100, now_utc=1000.0,
                        exhaustive=False).reject_reason == C.REJECT_NOT_EXHAUSTIVE


def test_screen_is_deterministic_over_frozen_books():
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.47, 10_000)]))],
              "B": [C.Leg("polymarket", "polymarket_clob", "b", "m2", _bk([(0.51, 10_000)]))]}
    a = C.best_cover(offers, 200, now_utc=1000.0, exhaustive=True)
    b = C.best_cover(offers, 200, now_utc=1000.0, exhaustive=True)
    assert a == b

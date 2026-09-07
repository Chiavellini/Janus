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
from nodes.settle_wedge.fixtures import mlb_cover_proof  # noqa: E402

#: A genuine proof from the mlb_no_draw rule. `ExhaustiveOutcomeSet` cannot be forged, so a test
#: asserting exhaustiveness goes through the same gate production does.
MLB2 = mlb_cover_proof(["a", "b"])


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
              "B": [C.Leg("polymarket", "pm_clob", "b", "m", _bk([(0.51, 10_000)]),
                          {"fee_rate": 0.05})]}
    cov = C.best_cover(offers, 500, now_utc=1000.0, proof=MLB2)
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
    cov = C.best_cover(offers, 500, now_utc=1000.0, proof=MLB2)
    assert cov.ok and cov.cost_per_contract < 0.995, cov.cost_per_contract
    assert cov.single_venue is True


def test_worst_case_settlement_state_is_used_not_the_average():
    """An 'arb' that only pays when the favourite wins is a directional bet with extra steps."""
    offers = {"A": [C.Leg("betfair", "betfair_exchange", "a", "m", _bk([(0.10, 10_000)]))],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m2", _bk([(0.88, 10_000)]),
                          {"fee_rate": 0.05})]}
    cov = C.best_cover(offers, 100, now_utc=1000.0, proof=MLB2)
    assert cov.ok
    # Betfair commission is on NET WINNINGS, so it bites hardest when the 0.10 leg wins.
    assert cov.worst_settlement_state == "a", cov.worst_settlement_state


def test_depth_binds_before_price():
    """Phase 1's mentions track found capacity ($4 median at touch) binding before edge did."""
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.01, 3)]))],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m2", _bk([(0.50, 10_000)]))]}
    cov = C.best_cover(offers, 500, now_utc=1000.0, proof=MLB2)
    assert not cov.ok and cov.reject_reason == C.REJECT_NO_DEPTH


def test_stale_leg_is_rejected_not_discounted():
    """PM's limiter QUEUES, so a slow response is a stale quote wearing a fresh timestamp."""
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.40, 10_000)], age=300))],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m2", _bk([(0.40, 10_000)]))]}
    cov = C.best_cover(offers, 100, now_utc=1000.0, proof=MLB2, max_leg_age_s=30)
    assert not cov.ok and cov.reject_reason == C.REJECT_STALE


def test_soccer_three_way_is_not_covered_by_two_legs():
    """Exhaustiveness is sport-specific. MLB moneyline has no draw; EPL does."""
    two_of_three = {"HOME": [C.Leg("kalshi", "kalshi_clob", "h", "m", _bk([(0.40, 10_000)]))],
                    "AWAY": [C.Leg("polymarket", "pm_clob", "a", "m2",
                                   _bk([(0.35, 10_000)]))]}
    assert C.best_cover(two_of_three, 100, now_utc=1000.0,
                        proof=None).reject_reason == C.REJECT_NO_PROOF


def test_screen_is_deterministic_over_frozen_books():
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", _bk([(0.47, 10_000)]))],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m2", _bk([(0.51, 10_000)]))]}
    a = C.best_cover(offers, 200, now_utc=1000.0, proof=MLB2)
    b = C.best_cover(offers, 200, now_utc=1000.0, proof=MLB2)
    assert a == b


def test_fees_are_charged_per_level_and_a_vwap_fill_overstates_them():
    """Two levels on Kalshi at 0.40 and 0.60 for 50 each: the true fee is the sum over the levels,
    and the old single-VWAP fill at 0.50 charged strictly more (p(1-p) is concave)."""
    from nodes.fees.models import Fill, KalshiQuadratic
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m1", _bk([(0.40, 50), (0.60, 50)]), {"fee_multiplier": 1.0})],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m2", _bk([(0.30, 10_000)]), {"fee_rate": 0.0})]}
    cov = C.best_cover(offers, 100, now_utc=1000.0, proof=MLB2)
    assert cov.ok
    k = KalshiQuadratic()
    per_level = k.entry_cost([Fill("kalshi", "m1", "a", "yes", 0.40, 50.0), Fill("kalshi", "m1", "a", "yes", 0.60, 50.0)],
                             {"fee_multiplier": 1.0})
    vwap = k.entry_cost([Fill("kalshi", "m1", "a", "yes", 0.50, 100.0)], {"fee_multiplier": 1.0})
    assert abs(cov.fee_per_contract * 100 - per_level) < 1e-9 and per_level < vwap


def test_a_size_below_a_legs_minimum_order_is_not_a_cover():
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m1", _bk([(0.40, 1000)]))],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m2", _bk([(0.30, 1000)]), min_order_contracts=5.0)]}
    assert C.best_cover(offers, 3, now_utc=1000.0, proof=MLB2).reject_reason == C.REJECT_BELOW_MIN_ORDER
    assert C.best_cover(offers, 5, now_utc=1000.0, proof=MLB2).ok


def test_a_polymarket_leg_under_one_dollar_of_notional_is_not_a_cover_at_that_size():
    """The CLOB refuses a marketable BUY under $1 (5 x $0.12 = $0.60 on 2026-09-07)."""
    from nodes.cover.cover import Leg, best_cover, PM_MIN_NOTIONAL_USD, REJECT_BELOW_MIN_ORDER
    from kernel.schema import Book, Quote
    from nodes.settle_wedge.fixtures import mlb_cover_proof
    proof = mlb_cover_proof(["away", "home"])
    offs = {"home": [Leg("polymarket", "pm_clob", "P_H", "P_H", Book(asks=(Quote(0.12, 5000),), fetched_utc=1000.0), {"fee_rate": 0.0})],
            "away": [Leg("kalshi", "kalshi_clob", "K_A", "K_A", Book(asks=(Quote(0.80, 5000),), fetched_utc=1000.0), {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5})]}
    assert PM_MIN_NOTIONAL_USD == 1.0
    c5 = best_cover(offs, 5.0, now_utc=1000.0, proof=proof)
    assert not c5.ok and c5.reject_reason == REJECT_BELOW_MIN_ORDER
    c10 = best_cover(offs, 10.0, now_utc=1000.0, proof=proof)
    assert c10.ok or c10.reject_reason != REJECT_BELOW_MIN_ORDER

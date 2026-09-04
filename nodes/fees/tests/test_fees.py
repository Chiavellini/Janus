#!/usr/bin/env python3
"""Stage-0 tests: normalized schema, fee engine, venue registry.

Runs under pytest or standalone:  python3 tests/test_schema_fees.py

The load-bearing test here is `test_legacy_cost_anchors_reproduce`. `nodes/fees/venue_costs.py` carries
anchors traced back to real fills and to frozen Kilos results; the new fee engine is only
trustworthy if it reproduces every one of them digit-for-digit. If that test fails, the new engine
is wrong — not the old one.
"""

from __future__ import annotations

import sys
from pathlib import Path


from kernel import schema
from nodes.fees import venue_costs as vc  # noqa: E402
from nodes.fees import models as fm  # noqa: E402
from nodes.fees import registry as fr  # noqa: E402
from kernel.schema import (  # noqa: E402
    Book, CanonicalKey, NormMarket, Outcome, Quote, SettleRef, VoidPolicy,
)

#: Kalshi's 1x tier, passed explicitly. A missing or null multiplier is an ERROR (see
#: test_a_null_multiplier_is_an_error_not_a_default); tests say what they mean.
K1 = {"fee_multiplier": 1.0}


# ── schema ────────────────────────────────────────────────────────────────

def test_schema_selftest():
    schema.selftest()


def test_prices_are_probabilities_not_cents():
    """The guard that would have caught the Kilos 30c-read-as-0.3c incident."""
    schema.assert_price_range([0.0, 0.21, 1.0])
    for bad in (50.0, 100.0, -0.5):
        try:
            schema.assert_price_range(bad)
            raise AssertionError(f"guard missed {bad}")
        except ValueError:
            pass


def test_kalshi_bids_only_fold():
    """Kalshi returns bids only; a YES ask exists only as a NO bid at the complement."""
    no_bids = (Quote(0.22, 100.0), Quote(0.21, 50.0))
    yes_asks = schema.fold_complement_bids(no_bids)
    assert [round(q.price, 10) for q in yes_asks] == [0.78, 0.79]
    assert all(q.is_synthetic for q in yes_asks)
    # the structural identity that makes single-condition YES+NO arb impossible
    yes_bid, no_ask = 0.978, 0.022
    assert abs(yes_bid + no_ask - 1.0) < 1e-12


def test_sportsbook_becomes_an_ask_level():
    """A one-sided stake limit is structurally identical to depth at a price."""
    p = schema.american_odds_to_price(-110)
    contracts = schema.stake_to_contracts(1000.0, p)
    assert abs(contracts - 1000.0 / p) < 1e-9
    assert contracts > 1000.0            # you buy more than $1000 of payout at a sub-1 price


def test_no_proof_by_default_and_settleref_defaults_unknown():
    """Phase 1 burned four scans inferring exhaustiveness. Both defaults must be pessimistic."""
    m = NormMarket(venue="kalshi", liquidity_source="kalshi_clob", venue_market_id="X",
                   outcomes=(), fee_model_id="kalshi_quadratic", settle_ref=SettleRef(),
                   raw_title="t", fetched_utc=0.0)
    assert m.proof is None
    assert m.settle_ref.void_policy is VoidPolicy.UNKNOWN
    assert m.settle_ref.provenance == "assumed"


def test_same_book_venues_share_a_liquidity_source():
    for v in ("robinhood", "webull", "ibkr_kalshi"):
        assert schema.liquidity_source_for(v) == schema.liquidity_source_for("kalshi")
    assert schema.liquidity_source_for("polymarket") != schema.liquidity_source_for("kalshi")


# ── fee engine ────────────────────────────────────────────────────────────

def test_fee_models_selftest():
    fm.selftest()


def test_fee_registry_selftest():
    fr.selftest()


def test_legacy_cost_anchors_reproduce():
    """THE REGRESSION CONTRACT. Every legacy anchor, through the new API."""
    vc.selftest()                                     # the old suite still passes untouched
    k, pm = fm.KalshiQuadratic(), fm.PMQuadratic()

    for price_c in (1.0, 21.0, 25.0, 50.0, 70.0, 75.0, 99.0):
        p = price_c / 100.0
        new = k.entry_cost([fm.Fill("kalshi", "M", "y", "buy", p, 1.0)], K1) * 100.0
        assert abs(new - float(vc.kalshi_fee_cents(price_c))) < 1e-9, (price_c, new)

        new_mk = k.entry_cost([fm.Fill("kalshi", "M", "y", "buy", p, 1.0,
                                       liquidity="maker")], K1) * 100.0
        assert abs(new_mk - float(vc.kalshi_fee_cents(price_c, coeff=vc.KALSHI_MAKER_COEFF))) < 1e-9

        new_pm = pm.entry_cost([fm.Fill("pm", "M", "y", "buy", p, 1.0)], {}) * 100.0
        assert abs(new_pm - float(vc.pm_fee_cents(price_c))) < 1e-9, (price_c, new_pm)

    # per-order amortisation across sizes
    for n in (1, 2, 10, 100, 1000):
        new = k.entry_cost([fm.Fill("kalshi", "M", "y", "buy", 0.50, float(n))], K1) * 100.0 / n
        assert abs(new - vc.kalshi_fee_cents_per_contract(50.0, n_contracts=n)) < 1e-9, n

    # PM's on-chain-verified anchor
    assert abs(pm.entry_cost([fm.Fill("pm", "M", "y", "buy", 0.37, 13.51)], {})
               - vc.pm_fee_usd(13.51, 0.37)) < 1e-12


def test_kalshi_ceil_is_per_order_not_per_contract():
    """100 contracts in one order pay the ceil once; as 100 orders they pay it 100 times."""
    k = fm.KalshiQuadratic()
    one_order = k.entry_cost([fm.Fill("kalshi", "M", "y", "buy", 0.50, 100.0)], K1)
    many = k.entry_cost([fm.Fill("kalshi", "M", "y", "buy", 0.50, 1.0, order_seq=i)
                         for i in range(100)], K1)
    assert abs(one_order - 1.75) < 1e-12
    assert abs(many - 2.00) < 1e-12
    assert many > one_order


def test_pm_per_market_rate_overrides_the_pin():
    """The live bug: an earlier screen applied 0.07 to every market. Modal live rate is 0.04."""
    pm = fm.PMQuadratic()
    f = [fm.Fill("pm", "M", "y", "buy", 0.50, 1.0)]
    assert abs(pm.entry_cost(f, {"fee_rate": 0.07}) * 100 - 1.75) < 1e-9
    assert abs(pm.entry_cost(f, {"fee_rate": 0.05}) * 100 - 1.25) < 1e-9    # sports
    assert abs(pm.entry_cost(f, {"fee_rate": 0.04}) * 100 - 1.00) < 1e-9    # politics/mentions
    assert pm.entry_cost(f, {"fee_rate": 0.0}) == 0.0                        # geopolitics
    assert abs(fr.screening_coeff("polymarket", {"fee_rate": 0.05}) - 0.05) < 1e-12


def test_net_winnings_commission_collapses_to_the_parabola():
    """Family (b) reduces to k*p*(1-p) for a CROSS-VENUE hedge. The Stage-0 free result."""
    n = fm.NetWinningsCommission()
    for p in (0.10, 0.25, 0.50, 0.75, 0.90):
        for rate in (0.02, 0.05):
            leg = [fm.Fill("betfair", "M", "A", "buy", p, 1.0)]
            win = n.settlement_cost(leg, {"A": True}, {"commission_rate": rate})
            lose = n.settlement_cost(leg, {"A": False}, {"commission_rate": rate})
            assert lose == 0.0                        # charged only where you finish ahead
            expected = p * win + (1 - p) * lose
            assert abs(expected - rate * p * (1 - p)) < 1e-12, (p, rate, expected)


def test_same_venue_cover_commission_falls_on_the_edge_only():
    """Cover every outcome on ONE exchange and commission applies to the arb profit alone."""
    n = fm.NetWinningsCommission()
    cover = [fm.Fill("smarkets", "M", "A", "buy", 0.48, 1.0),
             fm.Fill("smarkets", "M", "B", "buy", 0.49, 1.0)]
    c = n.settlement_cost(cover, {"A": True, "B": False}, {"commission_rate": 0.02})
    assert abs(c - 0.02 * 0.03) < 1e-12               # 2% of a 3c edge
    cross = n.settlement_cost([fm.Fill("smarkets", "M", "A", "buy", 0.50, 1.0)],
                              {"A": True}, {"commission_rate": 0.02})
    assert c < cross / 10                             # ~50x cheaper than the cross-venue leg


def test_embedded_vig_charges_nothing_but_is_not_free():
    """A book charges no commission; its cost is the ask you cross. Adding a fee double-counts."""
    e = fm.EmbeddedPrice()
    assert e.entry_cost([fm.Fill("pinnacle", "M", "A", "buy", 0.524, 1000.0)], {}) == 0.0
    p = schema.american_odds_to_price(-110)
    m = NormMarket(
        venue="pinnacle", liquidity_source="pinnacle_book", venue_market_id="Y",
        outcomes=(Outcome("h", "BOS", Book(asks=(Quote(p, 1000.0),), one_sided=True)),
                  Outcome("a", "LAL", Book(asks=(Quote(p, 1000.0),), one_sided=True))),
        fee_model_id="embedded", settle_ref=SettleRef(), raw_title="t", fetched_utc=0.0)
    assert m.overround > 0.047                        # the vig is visible in the price, not the fee


def test_premium_charge_targets_the_arbitrageur_profile():
    """Betfair does not limit winners; it taxes them, and an arb book is exposed by definition."""
    pc = fm.PremiumChargeSchedule()
    assert pc.is_exposed(300_000, 30_000) is True     # low commission ratio = the arb profile
    assert pc.is_exposed(300_000, 90_000) is False
    assert pc.is_exposed(100_000, 5_000) is False     # under threshold
    assert abs(pc.stressed_charge(10_000) - 6_000) < 1e-9


def test_carry_is_signed_and_cannot_rescue_a_negative_edge():
    """4.05% APY over a week is ~0.04c on a 50c contract. Model it; never let it flip a sign."""
    k = fm.KalshiQuadratic()
    f = [fm.Fill("kalshi", "M", "y", "buy", 0.50, 1.0)]
    week = k.carry_credit(f, 7.0, {})
    assert week < 0                                   # a credit is negative cost
    assert abs(week) * 100 < 0.05                     # under 0.05c — smaller than one tick
    assert abs(k.carry_credit(f, 180.0, {})) > abs(week)


def test_unknown_venue_raises_rather_than_defaulting():
    """Silently defaulting a fee is how the PM 0.07 bug survived a whole phase."""
    for fn in (fr.model_for, fr.params_for, fr.screening_coeff):
        try:
            fn("venue_that_does_not_exist")
            raise AssertionError(f"{fn.__name__} silently defaulted")
        except KeyError:
            pass


def test_fee_floor_by_venue_pair():
    """The Stage-0 result: the two-leg fee floor is 7.5x lower on the right venue pair.

    Phase 1 concluded the fee floor exceeds the tick — true, but measured on Kalshi+Polymarket
    crypto, the most expensive pair available. All 59 coherence violations it found were 1-2c
    gross against a 3.75c floor. On an exchange+exchange pair the floor is 1.00c.
    """
    k, pm, n = fm.KalshiQuadratic(), fm.PMQuadratic(), fm.NetWinningsCommission()
    p = 0.50

    def kalshi_leg(c=1.0):
        return k.entry_cost([fm.Fill("kalshi", "M", "o", "buy", p, c)], K1) * 100 / c

    def pm_leg(rate, c=1.0):
        return pm.entry_cost([fm.Fill("pm", "M", "o", "buy", p, c)], {"fee_rate": rate}) * 100 / c

    def exch_leg(rate, c=1.0):
        f = [fm.Fill("x", "M", "o", "buy", p, c)]
        return p * n.settlement_cost(f, {"o": True}, {"commission_rate": rate}) * 100 / c

    kalshi_pm_crypto = kalshi_leg() + pm_leg(0.07)
    kalshi_smarkets = kalshi_leg() + exch_leg(0.02)
    exch_exch = exch_leg(0.02) + exch_leg(0.02)

    assert abs(kalshi_pm_crypto - 3.75) < 1e-9, kalshi_pm_crypto
    assert abs(kalshi_smarkets - 2.50) < 1e-9, kalshi_smarkets
    assert abs(exch_exch - 1.00) < 1e-9, exch_exch
    # the headline: changing venue pair cuts the floor by more than 3x, and 7.5x against a book
    assert kalshi_pm_crypto / exch_exch > 3.5


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)


def test_a_null_multiplier_is_an_error_not_a_default():
    """Found live 2026-09-02: KXMLBGAME reports fee_multiplier 0.5 with quadratic_with_maker_fees,
    and the lane had been charging 1.0x because a missing value silently became 1.0. The model
    now refuses; the registry pin (1.0) is a labelled screening fallback reached only through
    params_for, and the live path passes the series value."""
    import pytest
    k = fm.KalshiQuadratic()
    f = [fm.Fill("kalshi", "M", "y", "buy", 0.50, 100.0)]
    with pytest.raises(ValueError, match="fee_multiplier"):
        k.entry_cost(f, {})
    with pytest.raises(ValueError, match="fee_multiplier"):
        k.entry_cost(f, {"fee_multiplier": None})
    # quadratic_with_maker_fees: the multiplier is NOT applied to the taker fee (production fill,
    # 2026-09-04, below) and the fee is kept to the hundredth of a cent: 0.07*100*0.25 = $1.75 exactly.
    assert abs(k.entry_cost(f, {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5})
               - 1.75) < 1e-9
    # plain quadratic keeps the multiplier and the per-order ceil to the cent
    assert abs(k.entry_cost(f, {"fee_type": "quadratic", "fee_multiplier": 0.5}) - 0.88) < 1e-9


def test_the_pin_reproduces_the_2026_09_04_production_fill_to_the_hundredth_of_a_cent():
    """GATE step 8: the charged fee is the pin. KXMLBGAME (quadratic_with_maker_fees, multiplier 0.5,
    a scheduled series fee change since 2026-08-07) charged 2 taker contracts at 0.35 exactly
    0.031900 = 0.07 x 2 x 0.35 x 0.65. The old pin said ceil(0.035 x ...) = 2c and the proof
    STOPped on FEE_ABOVE_PIN. The fixture is the venue's own fill and order records."""
    import json
    from pathlib import Path
    fx = json.loads((Path(__file__).parent / "fixtures" / "kalshi_fill_20260904_KXMLBGAME.json").read_text())
    fill, series = fx["fill"], fx["series"]
    assert fill["is_taker"] and fill["outcome_side"] == "yes"
    k = fm.KalshiQuadratic()
    f = [fm.Fill("kalshi", fill["ticker"], "kc", "buy", float(fill["yes_price_dollars"]), float(fill["count_fp"]))]
    params = fr.params_for("kalshi", {"fee_type": series["fee_type"], "fee_multiplier": series["fee_multiplier"]})
    assert abs(k.entry_cost(f, params) - float(fill["fee_cost"])) < 1e-9
    assert abs(float(fx["order"]["taker_fees_dollars"]) - float(fill["fee_cost"])) < 1e-9
    assert abs(k.screening_coeff(params) - 0.07) < 1e-12, "the lane's screen must charge sports the full coefficient"
    # the proof's resting bid was hit at 00:13Z (is_taker false): the maker coefficient is unscaled too,
    # 0.0175 x 1 x 0.25 x 0.75 = 0.0032812 -> 0.0033 at the hundredth of a cent
    mk = fx["maker_fill"]
    assert not mk["is_taker"]
    fm_ = [fm.Fill("kalshi", mk["ticker"], "kc", "buy", float(mk["yes_price_dollars"]), float(mk["count_fp"]), liquidity="maker")]
    assert abs(k.entry_cost(fm_, params) - float(mk["fee_cost"])) < 1e-9
    assert abs(float(fx["maker_order"]["maker_fees_dollars"]) - float(mk["fee_cost"])) < 1e-9

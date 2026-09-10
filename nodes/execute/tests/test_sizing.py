from kernel.schema import Book, Quote, liquidity_source_for
from nodes.cover.cover import Leg
from nodes.execute.sizing import choose_live_size
from nodes.risk.ledger import ExposureLedger, Reservation
from nodes.risk.limits import load_limits
from nodes.settle_wedge.fixtures import mlb_cover_proof


T = 1_800_000_000.0


def book(levels):
    return Book(asks=tuple(Quote(p, q) for p, q in levels), fetched_utc=T)


def offers(pm=((0.40, 10),), kalshi=((0.50, 10),)):
    return {
        "a": [Leg("polymarket", liquidity_source_for("polymarket"), "pm-a", "a", book(pm),
                  {"fee_rate": 0.0}, tick=0.01)],
        "b": [Leg("kalshi", liquidity_source_for("kalshi"), "k-b", "b", book(kalshi),
                  {"fee_multiplier": 0.0}, tick=0.01)],
    }


def choose(os, **kw):
    return choose_live_size(os, now_utc=T, proof=mlb_cover_proof(["a", "b"]), event_id="g1",
                            league="mlb", caps={"stake_usd": 12, "max_contracts": 10,
                                                "day_notional_usd": 250}, limits=load_limits(),
                            ledger=ExposureLedger(), balances={"polymarket": 100, "kalshi": 100},
                            min_net_profit_usd=0.0, **kw)


def test_selects_profit_maximum_not_first_or_largest_profitable_quantity():
    # Profit rises through q=5, then the Kalshi tail costs enough that larger sizes remain positive
    # but lock fewer total dollars.  The live selector must choose 5 while N_max is 10.
    d = choose(offers(pm=((0.30, 10),), kalshi=((0.50, 5), (0.72, 5))))
    assert d.n_star_feasible == 5
    assert d.n_max_feasible == 10
    assert d.selected.quantity == 5
    assert d.selected.profit_usd > next(c.profit_usd for c in d.candidates if c.quantity == 10)
    assert d.fill_model == "BOUNDED_TAKER_V1"


def test_objective_uses_final_maker_plan_fee_not_pre_plan_cover_fee():
    os = {
        "a": [Leg("polymarket", liquidity_source_for("polymarket"), "pm-a", "a",
                  book(((0.20, 8), (0.35, 2))), {"fee_rate": 0.07}, tick=0.01)],
        "b": [Leg("kalshi", liquidity_source_for("kalshi"), "k-b", "b",
                  book(((0.20, 8), (0.60, 2))),
                  {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5}, tick=0.01)],
    }
    d = choose(os)
    q8, q10 = (next(c for c in d.candidates if c.quantity == q) for q in (8, 10))
    assert q10.cover is not None and q10.cover.fee_per_contract < q10.plan.fee_per_contract
    assert q8.profit_usd > q10.profit_usd and d.n_star_feasible == 8


def test_signed_contract_cap_binds_between_economic_n_star_and_n_max():
    d = choose_live_size(offers(pm=((0.30, 20),), kalshi=((0.50, 20),)), now_utc=T,
                         proof=mlb_cover_proof(["a", "b"]), event_id="g1", league="mlb",
                         caps={"stake_usd": 100, "max_contracts": 7, "day_notional_usd": 250},
                         limits=load_limits(), ledger=ExposureLedger(),
                         balances={"polymarket": 100, "kalshi": 100}, min_net_profit_usd=0.0)
    assert d.n_star_feasible == d.n_max_feasible == 7
    assert [c.quantity for c in d.candidates] == list(range(1, 8))
    assert [c.refusals for c in d.candidates[:3]] == [("below_min_order",)] * 3


def test_stake_day_balance_and_exposure_constraints_are_all_visible():
    limits = load_limits()
    ledger = ExposureLedger(open={"r": Reservation("r", "existing", "mlb",
                                                    {"kalshi": 249.0, "polymarket": 150.0}, None, T)})
    d = choose_live_size(offers(), now_utc=T, proof=mlb_cover_proof(["a", "b"]), event_id="g1",
                         league="mlb", caps={"stake_usd": 3.0, "max_contracts": 10,
                                             "day_notional_usd": 250}, limits=limits, ledger=ledger,
                         balances={"polymarket": 1.0, "kalshi": 100.0}, min_net_profit_usd=0.0)
    assert d.selected is None
    assert {"CAP_STAKE", "CAP_DAY_NOTIONAL", "BALANCE:polymarket", "LEAGUE_EXPOSURE",
            "VENUE_CAPITAL:kalshi", "UNRESOLVED_EXPOSURE"} <= set(d.binding_constraints)


def test_missing_outer_caps_fails_closed_before_pricing():
    d = choose_live_size(offers(), now_utc=T, proof=mlb_cover_proof(["a", "b"]), event_id="g1",
                         league="mlb", caps={}, limits=load_limits(), ledger=ExposureLedger(),
                         balances={"polymarket": 100, "kalshi": 100})
    assert d.selected is None and d.binding_constraints == ("NO_CAPS",)

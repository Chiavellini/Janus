#!/usr/bin/env python3
"""Two-venue execution-cost model for Janus (Kalshi + Polymarket binary contracts).

PROVENANCE — COPIED/MERGED, NOT IMPORTED.
  Kalshi curve      : ~/Code/Kilos/Phase1/costs.py                 (formula + conservatisms)
  Polymarket curve  : ~/Code/Kilos/PM/FEE_PIN.md                   (on-chain-verified pin)
  Scenario dict shape: ~/Code/Kilos/Equity/kernel/stats.py:FEE_SCENARIOS
  Scenario-menu idea : ~/Code/Kilos/PM/phase2/cost_menu.py

Both curves were RE-VERIFIED live against the venues' own APIs on 2026-07-24 (see PINS below).
Do not hardcode a fee anywhere else in Janus — import from here so a re-pin lands in one place.

────────────────────────────────────────────────────────────────────────────
THE TWO CURVES ARE THE SAME SHAPE BUT NOT THE SAME FUNCTION
────────────────────────────────────────────────────────────────────────────
Both are 0.07 * p * (1-p) per contract. The difference that matters:

  Kalshi     : ceil()-ed to whole cents, PER ORDER. Discrete. A 1-contract order at p=0.5
               pays ceil(1.75) = 2c; a 100-contract order pays ceil(175) = 175c = 1.75c each.
               So per-contract cost FALLS with order size. Maker tier is 4x cheaper (0.0175).
  Polymarket : continuous, no rounding, TAKER ONLY. Maker pays literally 0 (plus an
               unverified rebate — see PM_REBATE_RATE below). Per-contract cost is
               size-independent.

Modelling Kalshi with a per-contract ceil (as Kilos' Phase1/costs.py does) is CONSERVATIVE at
n=1 and materially overstated above it. `kalshi_fee_cents_per_contract(..., n_contracts=N)`
gives the honest per-order number; the n=1 default reproduces the Kilos lineage digit-for-digit.
"""

from __future__ import annotations

import math

import numpy as np

# ══════════════════════════════════════════════════════════════════════════
# PINS — every constant below carries its source and verification date.
# Re-verify against a REAL FILL before sizing anything. A charged fee above
# the pinned curve is a STOP-grade event, not a rounding note.
# ══════════════════════════════════════════════════════════════════════════

# --- Kalshi ---------------------------------------------------------------
# Source: kalshi.com/fee-schedule; confirmed 2026-06-10 (Kilos Phase1/costs.py header).
# RE-VERIFIED 2026-07-24 via GET /trade-api/v2/series: every KX*15M crypto series returns
#   {"fee_type": "quadratic", "fee_multiplier": 1}
# Crypto is the premium tier (peak 1.75% of contract value at 50c). S&P/NASDAQ are 0.035.
KALSHI_TAKER_COEFF = 0.07
KALSHI_MAKER_COEFF = 0.0175          # 4x cheaper; saves exactly +1c/contract in the 20-80c band
KALSHI_SETTLEMENT_FEE = 0.0          # settlement is free; only a pre-expiry SELL adds a 2nd fee

# --- Polymarket -----------------------------------------------------------
# Source: PM/FEE_PIN.md — on-chain verified against a real FeeCharged event
#   (Kilos ARMED_SMOKE.md: FeeCharged 0.185490 == shares * 0.07 * p * (1-p), exact).
# RE-VERIFIED 2026-07-24 via GET gamma-api/markets on btc-updown-15m:
#   feeSchedule = {"exponent": 1, "rate": 0.07, "takerOnly": true, "rebateRate": 0.2}
PM_TAKER_RATE = 0.07
PM_FEE_EXPONENT = 1                  # exponent 1 => linear in p*(1-p); assert on re-pin
PM_MAKER_RATE = 0.0                  # takerOnly: makers pay nothing

# UNVERIFIED. The live feeSchedule carries rebateRate=0.2 and NOTHING in Kilos models it.
# Two plausible semantics, not yet distinguished: (a) maker receives 20% of the taker fee on
# the matched size, (b) 20% of a protocol fee pool allocated by some other rule.
# Default 0.0 = conservative (credit no rebate). Do NOT flip this on without a real maker fill
# reconciled against a wallet delta. Tracked as an open item in GATE_TO_LIVE.md.
PM_REBATE_RATE = 0.2
PM_CREDIT_REBATE = False

# --- Venue microstructure limits (live-verified 2026-07-24) ---------------
PM_MIN_ORDER_SHARES = 5              # orderMinSize; blocks sub-$2 stakes at typical prices
PM_TICK = 0.01                       # orderPriceMinTickSize
KALSHI_TICK = 0.01

# ══════════════════════════════════════════════════════════════════════════
# THE ORACLE BASIS — the single most important number in this project
# ══════════════════════════════════════════════════════════════════════════
# Kalshi KX*15M and Polymarket *-updown-15m look like the same contract and are NOT:
#
#   Kalshi     : settles on BRTI (CF Benchmarks), close >= floor_strike (a fixed rounded level)
#   Polymarket : settles on the Chainlink data stream, close >= the window OPEN
#
# Measured 2026-07-24 by joining every settled window on both venues on exact close time
# (Kilos pm_data.db / pm_xa_data.db + market_data.db + the frozen 2026-07-17 shard):
#
#   asset  matched  disagree   rate     a "hedged" pair is worth
#   btc      2859      163     5.70%    94.30c   (not 100c)
#   eth      1063       65     6.11%    93.89c
#   sol      1064       79     7.42%    92.58c
#
# Disagreement is symmetric (btc: 86 one way, 77 the other), spans 39 distinct days, and holds
# across three independent assets -> STRUCTURAL, not a bad patch of days and not an artifact.
#
# CONSEQUENCE: a cross-venue two-leg position is NOT an arbitrage. It pays 100c only when the two
# oracles agree. Any code that treats a sub-par pair as riskless profit is wrong by ~5-7c/trade,
# which is larger than the entire nominal edge.
P_DISAGREE = {"btc": 0.05701, "eth": 0.06114, "sol": 0.07424}
P_DISAGREE_N = {"btc": 2859, "eth": 1063, "sol": 1064}
P_DISAGREE_DEFAULT = 0.07424         # SOL, the worst measured -> conservative for unmeasured assets
P_DISAGREE_MEASURED_UTC = "2026-07-24"

# Conditional structure (btc, n=2033 windows carrying a PM mid in the final 90s).
# Disagreement is a SMALL-MOVE phenomenon: it collapses when the window ends decisively.
#   |final_mid - 0.5| < 0.10  -> 27.66% disagree  (n=47)
#   0.10 .. 0.25              -> 31.67%           (n=60)
#   0.25 .. 0.40              -> 21.55%           (n=116)
#   >= 0.40 (89% of windows)  ->  2.98%           (n=1810)   <- the tradeable regime
# NOTE: final mid is only knowable at the close. Selecting this regime AT ENTRY is the open
# research question (the dual-reference moneyness gate). Do not use these as entry-time pins.
P_DISAGREE_BY_FINAL_CONFIDENCE = {"coinflip": 0.2766, "low": 0.3167,
                                  "mid": 0.2155, "confident": 0.0298}

# --- API endpoints (public, unauthenticated for market data) --------------
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA_URL = "https://gamma-api.polymarket.com"
PM_CLOB_URL = "https://clob.polymarket.com"

PINS_VERIFIED_UTC = "2026-07-24"


# ══════════════════════════════════════════════════════════════════════════
# Kalshi
# ══════════════════════════════════════════════════════════════════════════


# The ceil() is float-fragile: 0.07*100*100*0.25 evaluates to 175.00000000000003, so a naive
# ceil bills 176c for an order whose true fee is exactly 175c. Snap to 9dp before every ceil.
# On the 1-cent price grid the true product 7*p*(1-p) is never an integer except at p in {0,1},
# so this rounding cannot change any legitimate result — it only removes the artifact.
_CEIL_DP = 9


def _ceil_cents(x):
    return np.ceil(np.round(np.asarray(x, dtype=float), _CEIL_DP))


def kalshi_fee_cents(price_cents, *, coeff: float = KALSHI_TAKER_COEFF):
    """Kalshi per-contract fee (cents) at a 1-contract order size. Vectorised.

    fee = ceil(coeff * 100 * p * (1-p)), p = price_cents/100.
    This is the Kilos-lineage function — use it when reproducing a Kilos number exactly.
    """
    p = np.clip(np.asarray(price_cents, dtype=float) / 100.0, 0.0, 1.0)
    return _ceil_cents(coeff * 100.0 * p * (1.0 - p))


def kalshi_fee_cents_per_contract(price_cents: float, *, n_contracts: int = 1,
                                  coeff: float = KALSHI_TAKER_COEFF) -> float:
    """Honest per-contract fee accounting for Kalshi's PER-ORDER rounding.

    Kalshi computes ceil(coeff * C * P * (1-P)) once for the whole order. At C=1 this equals
    `kalshi_fee_cents`; above that the ceil is amortised and the per-contract cost falls.
    """
    if n_contracts < 1:
        raise ValueError("n_contracts must be >= 1")
    p = min(max(price_cents / 100.0, 0.0), 1.0)
    order_fee_cents = math.ceil(round(coeff * 100.0 * n_contracts * p * (1.0 - p), _CEIL_DP))
    return order_fee_cents / n_contracts


def kalshi_round_turn_fee_cents(entry_price_cents: float, exit_price_cents: float | None,
                                *, entry_coeff: float = KALSHI_TAKER_COEFF,
                                exit_coeff: float = KALSHI_TAKER_COEFF,
                                n_contracts: int = 1) -> float:
    """Total fee (cents/contract) for a position.

    Hold to settlement -> pass exit_price_cents=None -> ONE fee. Kalshi charges no settlement
    fee. Only a pre-expiry SELL adds a second fee.
    """
    fee = kalshi_fee_cents_per_contract(entry_price_cents, n_contracts=n_contracts,
                                        coeff=entry_coeff)
    if exit_price_cents is not None:
        fee += kalshi_fee_cents_per_contract(exit_price_cents, n_contracts=n_contracts,
                                             coeff=exit_coeff)
    return fee


# ══════════════════════════════════════════════════════════════════════════
# Polymarket
# ══════════════════════════════════════════════════════════════════════════


def pm_fee_cents(price_cents, *, rate: float = PM_TAKER_RATE):
    """Polymarket per-contract TAKER fee (cents). Continuous, no rounding. Vectorised.

    fee_usd = shares * rate * p * (1-p)  =>  cents/contract = rate * 100 * p * (1-p)
    """
    p = np.clip(np.asarray(price_cents, dtype=float) / 100.0, 0.0, 1.0)
    return rate * 100.0 * p * (1.0 - p)


def pm_fee_usd(shares: float, price: float, *, rate: float = PM_TAKER_RATE) -> float:
    """Polymarket taker fee in USD for `shares` at `price` in [0,1]. The on-chain-verified form."""
    p = min(max(price, 0.0), 1.0)
    return shares * rate * p * (1.0 - p)


def pm_maker_fee_cents(price_cents, *, credit_rebate: bool = PM_CREDIT_REBATE):
    """Polymarket per-contract MAKER fee (cents). Zero, optionally minus an UNVERIFIED rebate.

    With credit_rebate=False (default) this returns 0.0 — makers pay nothing and we credit
    nothing. Setting credit_rebate=True applies interpretation (a): maker receives
    PM_REBATE_RATE of the taker fee on the matched size, returned as a NEGATIVE cost.
    Do not use the rebate in a registered number until a real maker fill confirms it.
    """
    if not credit_rebate:
        return np.zeros_like(np.asarray(price_cents, dtype=float))
    return -PM_REBATE_RATE * pm_fee_cents(price_cents)


def pm_shares_for_spend(spend_usd: float, price: float, *, rate: float = PM_TAKER_RATE) -> float:
    """Shares purchasable for a fixed USD spend INCLUSIVE of the taker fee.

    Solves spend = shares*p + shares*rate*p*(1-p) for shares. This is the flat-DOLLAR sizing
    the live arms use; note the resulting share count varies ~12.5x across the price range,
    which is exactly why flat-share risk statistics do not carry over. See kernel/stats.py.
    """
    p = min(max(price, 1e-9), 1.0)
    return spend_usd / (p * (1.0 + rate * (1.0 - p)))


# ══════════════════════════════════════════════════════════════════════════
# Scenario menu — the axis every study must sweep, never a single hardcoded cost
# ══════════════════════════════════════════════════════════════════════════

FEE_SCENARIOS = {
    # bounds
    "zero":                 lambda c: 0.0,                                   # optimistic bound
    # Kalshi
    "kalshi_taker":         lambda c: float(kalshi_fee_cents(c, coeff=KALSHI_TAKER_COEFF)),
    "kalshi_maker":         lambda c: float(kalshi_fee_cents(c, coeff=KALSHI_MAKER_COEFF)),
    "kalshi_taker_2x":      lambda c: 2.0 * float(kalshi_fee_cents(c, coeff=KALSHI_TAKER_COEFF)),
    # Polymarket
    "pm_taker":             lambda c: float(pm_fee_cents(c)),
    "pm_maker":             lambda c: 0.0,
    "pm_maker_with_rebate": lambda c: float(-PM_REBATE_RATE * pm_fee_cents(c)),  # UNVERIFIED
    "pm_taker_2x":          lambda c: 2.0 * float(pm_fee_cents(c)),
}

#: Gate-4 stress pairs: (nominal, stressed) scenario names per venue.
STRESS_PAIRS = {
    "kalshi": ("kalshi_taker", "kalshi_taker_2x"),
    "pm": ("pm_taker", "pm_taker_2x"),
}


def fee_cents(price_cents: float, scenario: str) -> float:
    """Dispatch into FEE_SCENARIOS. Raises on an unknown name rather than defaulting."""
    if scenario not in FEE_SCENARIOS:
        raise KeyError(f"unknown fee scenario {scenario!r}; known: {sorted(FEE_SCENARIOS)}")
    return float(FEE_SCENARIOS[scenario](price_cents))


# ══════════════════════════════════════════════════════════════════════════
# Trade economics
# ══════════════════════════════════════════════════════════════════════════


def entry_contract_cents(entry_price: float, *, slip: float, scenario: str):
    """(entry_cents, pnl_win_cents, pnl_loss_cents) for a taker BUY at entry_price + slip.

    entry_price in [0,1]; slip in price points (e.g. 0.005 = half a cent).
    Win pays (100 - entry - fee); loss pays -(entry + fee).
    """
    p = min(entry_price + slip, 0.99)
    entry_c = p * 100.0
    fee = fee_cents(entry_c, scenario)
    return entry_c, (100.0 - entry_c - fee), -(entry_c + fee)


def breakeven_hit_rate(entry_price: float, *, slip: float, scenario: str) -> float:
    """Win probability at which a hold-to-settlement taker buy is EV-neutral.

    EV/trade in cents equals (hit_rate - breakeven) * 100 exactly, which is why hit-rate points
    above breakeven and EV-cents-per-trade are the same statement in this program.
    """
    _, pw, pl = entry_contract_cents(entry_price, slip=slip, scenario=scenario)
    return float(-pl / (pw - pl))


def two_leg_ev_cents(kalshi_yes_ask_cents: float, pm_down_ask_cents: float, *,
                     asset: str = "btc",
                     p_disagree: float | None = None,
                     kalshi_scenario: str = "kalshi_taker",
                     pm_scenario: str = "pm_taker",
                     slip_cents: float = 0.0) -> dict:
    """EV (cents) of the cross-venue two-leg position. THE core pricing function of this project.

    The structure — buy the SAME direction's complement on the two venues:
        leg 1: BUY Kalshi YES  ("BTC up this window")            at its ask
        leg 2: BUY Polymarket DOWN ("BTC down this window")      at its ask
    Exactly one leg pays 100c, so the pair pays 100c *whenever the two venues settle the same
    way*. Pass the mirrored trade (Kalshi NO + PM UP) by swapping the two price arguments.

    This is NOT an arbitrage, and modelling it as one is the central error this function exists
    to prevent. The two venues use different oracles and different reference levels, and settle
    OPPOSITELY 5.7-7.4% of the time (see P_DISAGREE). When they disagree, BOTH legs lose and the
    position returns 0c, not 100c.

        EV = (1 - p_disagree) * 100 - kalshi_cost - pm_cost

    Worked example — measured live on the 2026-07-24 20:45Z BTC window:
        Kalshi YES ask 21c, PM DOWN ask 70c -> outlay 91c, fees 2.00 + 1.47 = 3.47c
        nominal ("riskless") edge  = 100 - 94.47 = +5.53c
        true EV at p_disagree=5.70% = 94.30 - 94.47 = -0.17c
    The nominal edge IS the oracle risk premium, priced almost exactly. That is why the gap
    persists rather than being competed away.
    """
    if p_disagree is None:
        p_disagree = P_DISAGREE.get(asset, P_DISAGREE_DEFAULT)
    k_entry = kalshi_yes_ask_cents + slip_cents
    p_entry = pm_down_ask_cents + slip_cents
    k_fee = fee_cents(k_entry, kalshi_scenario)
    p_fee = fee_cents(p_entry, pm_scenario)
    outlay = k_entry + p_entry
    cost = outlay + k_fee + p_fee
    return {
        "kalshi_entry_cents": k_entry, "kalshi_fee_cents": k_fee,
        "pm_entry_cents": p_entry, "pm_fee_cents": p_fee,
        "outlay_cents": outlay,
        "total_cost_cents": cost,
        # what a naive "riskless arb" calculation would report — kept ONLY so studies can show
        # the gap between the illusion and the truth. Never promote this number.
        "nominal_edge_cents": 100.0 - cost,
        # the honest numbers
        "p_disagree": p_disagree,
        "hedge_value_cents": (1.0 - p_disagree) * 100.0,
        "ev_cents": (1.0 - p_disagree) * 100.0 - cost,
        # how much oracle risk this entry can absorb before EV goes negative
        "breakeven_p_disagree": max(0.0, 1.0 - cost / 100.0),
        "oracle_risk_modelled": True,
    }


def required_edge_cents(asset: str = "btc", p_disagree: float | None = None) -> float:
    """Gross nominal edge a two-leg entry must show before it is EV-neutral.

    Equals 100 * p_disagree. At the measured btc rate that is 5.70c of nominal 'free money'
    that is not free at all — it is the oracle risk premium.
    """
    if p_disagree is None:
        p_disagree = P_DISAGREE.get(asset, P_DISAGREE_DEFAULT)
    return 100.0 * p_disagree


def selftest() -> None:
    """Assert the pinned curves reproduce their published/verified anchors. Run in CI."""
    # Kalshi: 1-contract order at 50c pays ceil(1.75) = 2c
    assert float(kalshi_fee_cents(50.0)) == 2.0, kalshi_fee_cents(50.0)
    # ...and the per-order form amortises the ceil at size
    assert abs(kalshi_fee_cents_per_contract(50.0, n_contracts=100) - 1.75) < 1e-9
    # Kalshi maker saves ~1c in the mid band
    assert float(kalshi_fee_cents(50.0, coeff=KALSHI_MAKER_COEFF)) == 1.0
    # Kalshi fee vanishes in the wings
    assert float(kalshi_fee_cents(1.0)) == 1.0 or float(kalshi_fee_cents(1.0)) == 0.0
    # PM: continuous, peaks at 1.75c at p=0.5, no rounding
    assert abs(float(pm_fee_cents(50.0)) - 1.75) < 1e-9
    assert abs(float(pm_fee_cents(37.0)) - 0.07 * 100 * 0.37 * 0.63) < 1e-9
    # PM on-chain anchor from Kilos ARMED_SMOKE: 13.51 sh 15m UP @0.37 -> fee 0.2205
    assert abs(pm_fee_usd(13.51, 0.37) - 0.2205) < 5e-4, pm_fee_usd(13.51, 0.37)
    # spend inversion round-trips
    sh = pm_shares_for_spend(4.00, 0.37)
    assert abs(sh * 0.37 + pm_fee_usd(sh, 0.37) - 4.00) < 1e-9
    # Kilos' frozen pnl_pair anchor (PM/phase2/run_phase2.py): entry 50c + 1c slip, fee 2c
    # -> +47/-53 -> breakeven 53.0%. Reproduce it digit-exact.
    _, pw, pl = entry_contract_cents(0.50, slip=0.01, scenario="kalshi_taker")
    assert (pw, pl) == (47.0, -53.0), (pw, pl)
    be = breakeven_hit_rate(0.50, slip=0.01, scenario="kalshi_taker")
    assert abs(be - 0.530) < 1e-9, be
    # at half-cent slip the same curve gives 52.5% (the ceil still bills a full 2c)
    assert abs(breakeven_hit_rate(0.50, slip=0.005, scenario="kalshi_taker") - 0.525) < 1e-9
    # rebate is OFF by default
    assert float(np.asarray(pm_maker_fee_cents(50.0))) == 0.0

    # ── the two-leg anchor: the live 2026-07-24 20:45Z BTC window ──────────
    # Kalshi YES ask 21c + PM DOWN ask 70c. Reproduce both the illusion and the truth.
    r = two_leg_ev_cents(21.0, 70.0, asset="btc")
    assert r["outlay_cents"] == 91.0, r
    assert r["kalshi_fee_cents"] == 2.0, r                    # ceil(0.07*100*.21*.79) = ceil(1.16)
    assert abs(r["pm_fee_cents"] - 1.47) < 0.005, r           # 0.07*100*.70*.30
    assert abs(r["nominal_edge_cents"] - 5.53) < 0.01, r      # what a naive arb calc reports
    assert abs(r["hedge_value_cents"] - 94.30) < 0.01, r      # what the pair is actually worth
    assert abs(r["ev_cents"] - (-0.17)) < 0.01, r             # the truth: slightly negative
    assert r["oracle_risk_modelled"] is True

    # the nominal edge required just to break even IS the oracle risk premium
    assert abs(required_edge_cents("btc") - 5.701) < 1e-3
    assert required_edge_cents("sol") > required_edge_cents("btc")   # sol disagrees more

    # a genuinely wide divergence does clear the bar
    wide = two_leg_ev_cents(10.0, 70.0, asset="btc")
    assert wide["ev_cents"] > 10.0, wide

    # unmeasured assets fall back to the WORST measured rate, never to zero
    assert two_leg_ev_cents(21.0, 70.0, asset="hype")["p_disagree"] == P_DISAGREE_DEFAULT

    print(f"venue_costs selftest OK (pins verified {PINS_VERIFIED_UTC}; "
          f"oracle basis measured {P_DISAGREE_MEASURED_UTC})")


if __name__ == "__main__":
    selftest()

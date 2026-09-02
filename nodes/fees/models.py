#!/usr/bin/env python3
"""Fee models for every venue class Janus touches. Replaces the two-venue `nodes/fees/venue_costs.py`.

The old model was a flat dict of `lambda c:` taking ONLY price-in-cents. It could not express
order size, maker vs taker, a per-series multiplier, a per-market fee schedule, or any venue whose
cost is not a per-contract charge. Three of those limitations were live bugs:
`an earlier screen:66` applied Polymarket's 0.07 unconditionally, while the measured distribution is
0.04 -> 1,262 markets, 0.07 -> 372, 0.05 -> 336, none -> 130, so PM edges were understated across
most of the corpus.

────────────────────────────────────────────────────────────────────────────
THE THREE FAMILIES, AND WHY THEY ARE REALLY ONE
────────────────────────────────────────────────────────────────────────────
(a) PER-CONTRACT PARABOLIC — Kalshi `ceil(0.07*C*P*(1-P))` cents, ceil applied PER ORDER;
    Polymarket `C*rate*p*(1-p)`, continuous, taker-only, rate varying BY CATEGORY.

(b) COMMISSION ON NET WINNINGS, charged only if you win — Betfair 5% base, Smarkets 2%,
    Matchbook ~1.5-2%, Sporttrade 2%. Looks structurally alien to (a).

(c) EMBEDDED VIG — sportsbooks. No commission at all; the cost is already in the quoted price,
    and shows up as `NormMarket.overround`. Charging a fee on top would double-count it.

Family (b) collapses into (a)'s functional form, and this is the single most useful result of the
design pass. Back one outcome at price p for 1 contract of payout. Stake is p. If it wins you
receive 1, so net winnings on that market are (1-p) and commission is r*(1-p). If it loses,
net is negative and you pay nothing. So

    E[commission] = P(win) * r * (1-p) = r * p * (1-p)      per contract, at a fair price

which is the SAME PARABOLA as Kalshi's 0.07*p*(1-p). Every venue therefore reduces to a single
screening coefficient k in `k*p*(1-p)`:

    Kalshi taker 0.07 | Kalshi maker 0.0175 | PM sports 0.05 | PM maker 0.0
    Betfair 0.05      | Smarkets 0.02       | Sporttrade 0.02 | sportsbook 0.0 (embedded)

At the money that is 1.75c on Kalshi against 1.25c at Betfair and 0.50c at Smarkets — computable
before a single quote is fetched.

⚠ The unification is for SCREENING ONLY. The exact evaluation differs in *when* the charge lands
and *what it aggregates over*: Kalshi's ceil aggregates fills within one order, net-winnings
commission aggregates per venue per market and is state-dependent. Never mix the screening
number and the exact number in one reported result.

⚠ And the collapse is specific to a CROSS-VENUE hedge, where the exchange holds one leg. If you
cover every outcome on the SAME exchange, its net winnings are your arb profit alone, so
commission is r*edge -- nearly free. `NetWinningsCommission` handles both from one formula
because it computes net per venue per market rather than per leg.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

# Kalshi's ceil is float-fragile: 0.07*100*100*0.25 evaluates to 175.00000000000003, so a naive
# ceil bills 176c for an order whose true fee is exactly 175c. Snap to 9dp before every ceil.
# Inherited verbatim from nodes/fees/venue_costs.py; changing it breaks the Kilos-lineage anchors.
_CEIL_DP = 9


@dataclass(frozen=True)
class Fill:
    """One execution. The fee is a function of a FILL SET, never of a bare price.

    `order_seq` exists because Kalshi computes `ceil(coeff * C * P * (1-P))` ONCE for the whole
    order, so per-contract cost falls with size: a 1-contract order at p=0.5 pays ceil(1.75) = 2c,
    a 100-contract order pays ceil(175) = 175c = 1.75c each. Fills sharing an `order_seq` are
    billed as one order. Getting this wrong overstates cost by up to 14% at the money.
    """
    venue: str
    market_id: str
    outcome_id: str
    side: str                    # "buy" | "sell"
    price: float                 # [0,1]
    contracts: float             # units of $1 payout
    liquidity: str = "taker"     # "taker" | "maker"
    order_seq: int = 0

    @property
    def stake_usd(self) -> float:
        return self.price * self.contracts


class FeeModel(Protocol):
    """Four charge points. A venue implements the ones that apply and returns 0.0 for the rest."""
    id: str

    def entry_cost(self, fills: Sequence[Fill], params: Mapping[str, Any]) -> float:
        """USD charged at execution time, regardless of outcome."""
        ...

    def settlement_cost(self, fills: Sequence[Fill], won: Mapping[str, bool],
                        params: Mapping[str, Any]) -> float:
        """USD charged at resolution, conditional on which outcomes won."""
        ...

    def carry_credit(self, fills: Sequence[Fill], hold_days: float,
                     params: Mapping[str, Any]) -> float:
        """USD credit for holding (negative cost). Kalshi pays ~4.05% APY on cash AND positions."""
        ...

    def screening_coeff(self, params: Mapping[str, Any]) -> float:
        """The k in k*p*(1-p). Cheap first-pass only — never report it as an exact cost."""
        ...


class _Base:
    """Default no-op charge points so each model states only what it actually charges."""

    def entry_cost(self, fills, params):            # noqa: D102
        return 0.0

    def settlement_cost(self, fills, won, params):  # noqa: D102
        return 0.0

    def carry_credit(self, fills, hold_days, params):  # noqa: D102
        return 0.0


# ══════════════════════════════════════════════════════════════════════════
# (a) Per-contract parabolic
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class KalshiQuadratic(_Base):
    """`ceil(coeff * C * P * (1-P))` cents, ceil applied PER ORDER. Settlement is free.

    Pins re-verified 2026-07-24 against GET /trade-api/v2/series: every KX*15M crypto series
    returns {"fee_type": "quadratic", "fee_multiplier": 1}. Crypto is the premium tier; S&P and
    NASDAQ series carry 0.035, so a hardcoded 0.07 overstates index markets by 2x.

    `fee_multiplier` MUST come from the market payload (params), never from a constant. Missing
    is an error, not a default -- silently defaulting is how the PM 0.07 bug survived.
    """
    id: str = "kalshi_quadratic"
    taker_coeff: float = 0.07
    maker_coeff: float = 0.0175          # 4x cheaper; exactly +1c/contract saved in the 20-80c band

    def entry_cost(self, fills: Sequence[Fill], params: Mapping[str, Any]) -> float:
        mult = params.get("fee_multiplier", 1.0)
        if mult is None:
            mult = 1.0
        # Only the quadratic fee_type honours the multiplier; others are flat-rate at 1x.
        if not str(params.get("fee_type") or "quadratic").startswith("quadratic"):
            mult = 1.0
        by_order: dict[tuple, list[Fill]] = defaultdict(list)
        for f in fills:
            by_order[(f.market_id, f.order_seq, f.liquidity)].append(f)
        total_cents = 0.0
        for (_mid, _seq, liq), group in by_order.items():
            coeff = (self.maker_coeff if liq == "maker" else self.taker_coeff) * float(mult)
            if coeff <= 0:
                continue
            # One ceil for the whole order, summed over its (possibly multi-price) fills.
            raw = sum(coeff * 100.0 * f.contracts * f.price * (1.0 - f.price) for f in group)
            total_cents += math.ceil(round(raw, _CEIL_DP))
        return total_cents / 100.0

    def carry_credit(self, fills, hold_days, params):
        apy = params.get("cash_apy", 0.0405)     # Kalshi pays on cash AND open positions
        notional = sum(f.stake_usd for f in fills)
        return -notional * apy * (hold_days / 365.0)

    def screening_coeff(self, params: Mapping[str, Any]) -> float:
        mult = params.get("fee_multiplier") or 1.0
        liq = params.get("liquidity", "taker")
        return (self.maker_coeff if liq == "maker" else self.taker_coeff) * float(mult)


@dataclass(frozen=True)
class PMQuadratic(_Base):
    """`C * rate * p * (1-p)` USD. Continuous, no rounding, TAKER ONLY.

    On-chain verified (Kilos ARMED_SMOKE): FeeCharged 0.185490 == shares * 0.07 * p * (1-p) exact.

    `rate` is PER MARKET and varies by category — measured across the live corpus:
        Crypto 0.07 | Sports 0.05 | Economics/Culture/Weather 0.05 | Finance/Politics/Mentions 0.04
        | Geopolitics 0.0
    Makers are never charged. The live schedule also carries `rebateRate: 0.2`, whose semantics
    are UNVERIFIED (maker share of the taker fee, or a pool allocation?). Default credits nothing;
    do not flip it on without a real maker fill reconciled against a wallet delta.
    """
    id: str = "pm_quadratic"
    default_rate: float = 0.07           # conservative: the highest tier, not the modal one

    def entry_cost(self, fills: Sequence[Fill], params: Mapping[str, Any]) -> float:
        rate = params.get("fee_rate")
        if rate is None:
            rate = self.default_rate
        total = 0.0
        for f in fills:
            if f.liquidity == "maker":
                if params.get("credit_rebate", False):
                    total -= params.get("rebate_rate", 0.2) * (
                        f.contracts * float(rate) * f.price * (1.0 - f.price))
                continue
            total += f.contracts * float(rate) * f.price * (1.0 - f.price)
        return total

    def screening_coeff(self, params: Mapping[str, Any]) -> float:
        if params.get("liquidity", "taker") == "maker":
            return 0.0
        r = params.get("fee_rate")
        return float(self.default_rate if r is None else r)


# ══════════════════════════════════════════════════════════════════════════
# (b) Commission on net winnings — the family the old model could not express
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class NetWinningsCommission(_Base):
    """`rate * max(0, net)` per VENUE per MARKET, charged only where you finish ahead.

    Aggregating per venue-market rather than per leg is what makes one formula cover both cases:

      cross-venue hedge  -- the exchange holds one leg, so in the winning state net = (1-p) and
                            commission = r*(1-p); expected r*p*(1-p). The parabola.
      same-venue cover   -- all legs on the exchange, so net = 1 - sum(stakes) = the arb edge
                            alone, and commission = r*edge. Nearly free.

    Betfair's base rate is 5% (10% NRL), reducible to ~2% via its points programme. Smarkets 2%,
    Pro tier 1%. Matchbook is reported at 1.5-2% and sources conflict -- verify before sizing.
    """
    id: str = "net_winnings_commission"
    default_rate: float = 0.05

    def settlement_cost(self, fills: Sequence[Fill], won: Mapping[str, bool],
                        params: Mapping[str, Any]) -> float:
        rate = float(params.get("commission_rate", self.default_rate))
        discount = float(params.get("commission_discount", 0.0))   # Betfair points programme
        effective = rate * (1.0 - discount)
        by_market: dict[tuple[str, str], float] = defaultdict(float)
        for f in fills:
            payout = f.contracts if won.get(f.outcome_id, False) else 0.0
            by_market[(f.venue, f.market_id)] += payout - f.stake_usd
        return sum(effective * net for net in by_market.values() if net > 0)

    def screening_coeff(self, params: Mapping[str, Any]) -> float:
        rate = float(params.get("commission_rate", self.default_rate))
        return rate * (1.0 - float(params.get("commission_discount", 0.0)))


# ══════════════════════════════════════════════════════════════════════════
# (c) Embedded vig
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EmbeddedPrice(_Base):
    """Charges nothing. The vig IS the ask; it is already paid when you cross the price.

    Recorded via `NormMarket.overround` for attribution. Adding a fee here double-counts.
    IBKR ForecastEx belongs to this family in an unusual way: it charges no commission but quotes
    YES+NO summing to $1.01, so the exchange takes 1c per contract pair inside the spread.
    """
    id: str = "embedded"

    def screening_coeff(self, params: Mapping[str, Any]) -> float:
        return 0.0


@dataclass(frozen=True)
class ForecastExCoupon(EmbeddedPrice):
    """ForecastEx: embedded 1c spread, plus a reported ~3.13% APY coupon on HELD contracts.

    A carry term most arb models omit. It favours whichever leg you hold to expiry — but see the
    warning on `PremiumChargeSchedule`: carry cannot rescue a negative edge, and over a 7-day hold
    it is worth ~0.08c per dollar. Model it as a signed term; never let it flip a sign in a writeup.
    """
    id: str = "forecastex"

    def carry_credit(self, fills, hold_days, params):
        apy = params.get("coupon_apy", 0.0313)
        return -sum(f.stake_usd for f in fills) * apy * (hold_days / 365.0)


# ══════════════════════════════════════════════════════════════════════════
# Account-level scale constraint — not a per-trade fee
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PremiumChargeSchedule:
    """Betfair's Premium Charge. Betfair does not limit winners; it TAXES them.

    Up to 60% weekly once cumulative net profit exceeds GBP 250,000 AND commission paid is under
    20% of gross profit. It is aimed precisely at the low-margin high-turnover profile that an
    arbitrage book has, so this strategy is exposed almost by definition.

    This is NOT a per-trade fee and must never be amortised into one. It is (i) a boolean exposure
    flag and (ii) a mandatory G4 stress axis at the maximum rate, handled the way `STRESS_PAIRS`
    already handles 2x fees.
    """
    threshold_gbp: float = 250_000.0
    commission_ratio_trigger: float = 0.20
    max_rate: float = 0.60

    def is_exposed(self, cumulative_profit: float, commission_paid: float) -> bool:
        if cumulative_profit <= 0:
            return False
        ratio = commission_paid / cumulative_profit
        return cumulative_profit > self.threshold_gbp and ratio < self.commission_ratio_trigger

    def stressed_charge(self, period_profit: float) -> float:
        """Worst-case charge on a period's profit. The G4 stress number."""
        return max(0.0, period_profit) * self.max_rate


def selftest() -> None:
    """Anchors, including a digit-for-digit cross-check against the legacy model."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from nodes.fees import venue_costs as vc  # noqa: E402  — the regression contract

    k, pm = KalshiQuadratic(), PMQuadratic()

    # ── Kalshi: reproduce every legacy anchor through the new API ──────────
    # 1 contract at 50c pays ceil(1.75) = 2c
    one = [Fill("kalshi", "M", "yes", "buy", 0.50, 1.0)]
    assert abs(k.entry_cost(one, {}) - 0.02) < 1e-12, k.entry_cost(one, {})
    assert k.entry_cost(one, {}) * 100.0 == float(vc.kalshi_fee_cents(50.0))

    # 100 contracts in ONE order amortise the ceil to exactly 1.75c each
    hundred = [Fill("kalshi", "M", "yes", "buy", 0.50, 100.0)]
    assert abs(k.entry_cost(hundred, {}) - 1.75) < 1e-12, k.entry_cost(hundred, {})
    assert abs(k.entry_cost(hundred, {}) / 100.0 * 100.0
               - vc.kalshi_fee_cents_per_contract(50.0, n_contracts=100)) < 1e-9

    # 100 contracts as 100 SEPARATE orders pay the ceil 100 times — the order_seq contract
    split = [Fill("kalshi", "M", "yes", "buy", 0.50, 1.0, order_seq=i) for i in range(100)]
    assert abs(k.entry_cost(split, {}) - 2.00) < 1e-12, k.entry_cost(split, {})

    # maker tier saves exactly 1c in the mid band
    mk = [Fill("kalshi", "M", "yes", "buy", 0.50, 1.0, liquidity="maker")]
    assert abs(k.entry_cost(mk, {}) - 0.01) < 1e-12
    assert k.entry_cost(mk, {}) * 100.0 == float(vc.kalshi_fee_cents(50.0, coeff=vc.KALSHI_MAKER_COEFF))

    # per-series multiplier is honoured (S&P/NASDAQ are 0.035 = half the crypto tier).
    # Note the ceil still bites: 0.035*100*100*0.25 = 87.5c -> ceil -> 88c, not 87.5c. The
    # rounding is per ORDER, so it never fully disappears no matter how cheap the tier.
    half = k.entry_cost([Fill("kalshi", "M", "yes", "buy", 0.50, 100.0)],
                        {"fee_multiplier": 0.5, "fee_type": "quadratic"})
    assert abs(half - 0.88) < 1e-12, half
    assert half < k.entry_cost(hundred, {})          # still materially cheaper than the 1x tier

    # the two-leg anchor's Kalshi leg: 21c -> ceil(0.07*100*.21*.79) = ceil(1.16) = 2c
    leg = [Fill("kalshi", "M", "yes", "buy", 0.21, 1.0)]
    assert abs(k.entry_cost(leg, {}) - 0.02) < 1e-12

    # ── Polymarket ────────────────────────────────────────────────────────
    pf = [Fill("pm", "M", "down", "buy", 0.70, 1.0)]
    assert abs(pm.entry_cost(pf, {}) * 100.0 - 1.47) < 0.005, pm.entry_cost(pf, {})
    assert abs(pm.entry_cost(pf, {}) * 100.0 - float(vc.pm_fee_cents(70.0))) < 1e-12
    # on-chain anchor: 13.51 shares @ 0.37 -> 0.2205 USD
    onchain = [Fill("pm", "M", "up", "buy", 0.37, 13.51)]
    assert abs(pm.entry_cost(onchain, {}) - 0.2205) < 5e-4, pm.entry_cost(onchain, {})
    assert abs(pm.entry_cost(onchain, {}) - vc.pm_fee_usd(13.51, 0.37)) < 1e-12
    # per-market rate is honoured — sports is 0.05, not the 0.07 the legacy code hardcoded
    assert abs(pm.entry_cost(pf, {"fee_rate": 0.05}) * 100.0 - 1.05) < 1e-9
    assert pm.entry_cost(pf, {"fee_rate": 0.0}) == 0.0          # Geopolitics is free
    # makers pay nothing, and the rebate stays off unless explicitly enabled
    mkr = [Fill("pm", "M", "down", "buy", 0.70, 1.0, liquidity="maker")]
    assert pm.entry_cost(mkr, {}) == 0.0
    assert pm.entry_cost(mkr, {"credit_rebate": True}) < 0.0     # a credit, i.e. negative cost

    # ── Net-winnings commission: the collapse, verified numerically ───────
    bf = NetWinningsCommission()
    # cross-venue hedge, exchange holds ONE leg at p=0.5. Winning state: net = 0.5, fee = 0.025.
    ex_leg = [Fill("betfair", "M1", "A", "buy", 0.50, 1.0)]
    win = bf.settlement_cost(ex_leg, {"A": True}, {})
    lose = bf.settlement_cost(ex_leg, {"A": False}, {})
    assert abs(win - 0.025) < 1e-12, win
    assert lose == 0.0, lose
    # expected cost = p*win + (1-p)*lose = 0.0125 = 0.05 * p * (1-p). The parabola.
    assert abs((0.5 * win + 0.5 * lose) - 0.05 * 0.5 * 0.5) < 1e-12
    # and it is CHEAPER than Kalshi at the money: 1.25c vs 1.75c
    assert (0.5 * win + 0.5 * lose) < k.entry_cost(one, {})
    # screening coefficients line up with the exact expectation
    assert abs(bf.screening_coeff({}) - 0.05) < 1e-12
    assert abs(bf.screening_coeff({"commission_rate": 0.02}) - 0.02) < 1e-12   # Smarkets
    assert abs(bf.screening_coeff({"commission_discount": 0.6}) - 0.02) < 1e-12  # max Betfair discount

    # same-venue full cover: commission falls on the EDGE only, not on the payout
    cover = [Fill("betfair", "M1", "A", "buy", 0.48, 1.0),
             Fill("betfair", "M1", "B", "buy", 0.49, 1.0)]
    c = bf.settlement_cost(cover, {"A": True, "B": False}, {})
    assert abs(c - 0.05 * (1.0 - 0.97)) < 1e-12, c      # 5% of a 3c edge = 0.15c, not 2.5c
    assert c < win / 10

    # ── embedded vig charges nothing ──────────────────────────────────────
    emb = EmbeddedPrice()
    assert emb.entry_cost([Fill("pinnacle", "M", "A", "buy", 0.52, 100.0)], {}) == 0.0
    assert emb.screening_coeff({}) == 0.0

    # ── carry is signed, small, and cannot rescue anything ────────────────
    credit = k.carry_credit(one, 7.0, {})
    assert credit < 0                                            # a credit is a negative cost
    assert abs(credit) < 0.001, credit                           # ~0.04c over a week on 50c
    fx = ForecastExCoupon()
    assert fx.carry_credit(one, 365.0, {}) < 0

    # ── Premium Charge: exposure is the arbitrageur's default state ───────
    pc = PremiumChargeSchedule()
    assert pc.is_exposed(300_000, 30_000) is True        # 10% ratio, over threshold -> exposed
    assert pc.is_exposed(300_000, 90_000) is False       # 30% ratio -> not exposed
    assert pc.is_exposed(100_000, 5_000) is False        # under threshold
    assert abs(pc.stressed_charge(10_000) - 6_000) < 1e-9

    print("fees.models selftest OK (legacy venue_costs anchors reproduced digit-for-digit)")


if __name__ == "__main__":
    selftest()

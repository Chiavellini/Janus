#!/usr/bin/env python3
"""Venue -> fee model + pinned parameters. The single place a fee is defined.

Every pin carries its source and verification date. A charged fee ABOVE the pinned curve is a
STOP-grade event, not a rounding note. Re-verify against a real fill before sizing anything.

Per-market overrides always win over the pins here: Kalshi exposes `fee_type`/`fee_multiplier`
per series, Polymarket exposes `feeSchedule` per market. Those come from the venue payload via
`NormMarket.fee_params`. The pins are the fallback for discovery-time screening only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from lib.fees.models import (
    EmbeddedPrice,
    FeeModel,
    ForecastExCoupon,
    KalshiQuadratic,
    NetWinningsCommission,
    PMQuadratic,
)

MODELS: dict[str, FeeModel] = {
    m.id: m for m in (
        KalshiQuadratic(),
        PMQuadratic(),
        NetWinningsCommission(),
        EmbeddedPrice(),
        ForecastExCoupon(),
    )
}


@dataclass(frozen=True)
class VenueFeePin:
    model_id: str
    params: Mapping[str, Any] = field(default_factory=dict)
    verified_utc: str = "unverified"
    note: str = ""


#: Fee pins by venue. `verified_utc` is the honest field — several of these are RESEARCHED, not
#: measured, and are labelled so. Do not promote a number that rests on an "unverified" pin.
VENUE_FEES: dict[str, VenueFeePin] = {
    # ── Per-contract parabolic ────────────────────────────────────────────
    "kalshi": VenueFeePin(
        "kalshi_quadratic", {"fee_type": "quadratic", "fee_multiplier": 1.0, "cash_apy": 0.0405},
        "2026-07-24",
        "taker 0.07 / maker 0.0175, ceil PER ORDER, no settlement fee. Multiplier is per-series: "
        "crypto 1.0, S&P/NASDAQ 0.5. ALWAYS prefer the per-series value from the payload."),
    "polymarket": VenueFeePin(
        "pm_quadratic", {"fee_rate": 0.07, "credit_rebate": False, "rebate_rate": 0.2},
        "2026-07-24",
        "Measured rate distribution across the live corpus: 0.04 -> 1,262 markets, 0.07 -> 372, "
        "0.05 -> 336, none -> 130. The pinned 0.07 is the MINORITY case and is kept only as a "
        "conservative fallback. Sports is 0.05. rebateRate 0.2 semantics UNVERIFIED."),

    # ── Same-book venues: different fee layer, SAME liquidity ─────────────
    # Robinhood charges a FLAT $0.01/contract/side commission + $0.01 exchange fee against
    # Kalshi's parabolic. Consequence worth exploiting: flat is cheaper than 1.75c near P=0.50 and
    # dearer than the ~1c wings. That is a venue-SELECTION input, never an arbitrage — these route
    # to the same book (see schema.LIQUIDITY_SOURCES).
    "robinhood": VenueFeePin("embedded", {}, "unverified",
                             "RESEARCHED: ~$0.02/contract/side flat, routed to KalshiEX. "
                             "Not modelled as parabolic. No depth feed, so unusable as a quote "
                             "source; execution venue only."),

    # ── Commission on net winnings ────────────────────────────────────────
    "betfair": VenueFeePin(
        "net_winnings_commission", {"commission_rate": 0.05, "commission_discount": 0.0},
        "unverified",
        "RESEARCHED: Market Base Rate 5% (NRL 10%), reducible toward ~2% via the points "
        "programme. PLUS the Premium Charge - up to 60% weekly once cumulative profit exceeds "
        "GBP 250k with commission under 20% of gross. See models.PremiumChargeSchedule; it is a "
        "capacity constraint, not a per-trade fee. Live App Key also costs GBP 499 one-off and "
        "read-only use is not permitted."),
    "smarkets": VenueFeePin(
        "net_winnings_commission", {"commission_rate": 0.02}, "unverified",
        "RESEARCHED: flat 2% on net winnings per market; Pro tier 1%. Free API. Cheapest "
        "screening coefficient of any two-sided venue in the census."),
    "matchbook": VenueFeePin(
        "net_winnings_commission", {"commission_rate": 0.02}, "unverified",
        "RESEARCHED AND SOURCES CONFLICT: 2%, or 1.5%, or 0.75% if you posted the offer. Pinned "
        "at the WORST cited value. Verify directly before sizing."),
    "sporttrade": VenueFeePin(
        "net_winnings_commission", {"commission_rate": 0.02}, "unverified",
        "RESEARCHED: 2% on profitable trades. Prices 0-100 like Kalshi, so natively comparable. "
        "No public API - reachable only via an aggregator."),
    "sxbet": VenueFeePin(
        "net_winnings_commission", {"commission_rate": 0.0}, "unverified",
        "RESEARCHED: 0% on singles, 5% on PARLAY profit only. Singles run as a zero-rake CLOB. "
        "V2->V3 migration cutoff 2026-08-25; build against V3."),
    "cloudbet": VenueFeePin(
        "embedded", {}, "unverified",
        "RESEARCHED: sportsbook decimal odds; no separate commission model is applied here. "
        "Displayed max stake and in-play acceptance are not executable until Cloudbet accepts "
        "the specific bet. Settlement and void rules remain market/sport dependent."),

    # ── Embedded vig ──────────────────────────────────────────────────────
    "pinnacle": VenueFeePin("embedded", {}, "unverified",
                            "RESEARCHED: 1-3% vig on major markets, embedded in the price. Limits "
                            "are a property of the MARKET not the account: max(base, "
                            "base/(price-1)), public and computable, and LARGER on heavy "
                            "favourites. Public API closed Jul 2025."),
    "circa": VenueFeePin("embedded", {}, "unverified",
                         "RESEARCHED: no public API. Publicly commits to not limiting winners; "
                         "best executable size in US-legal land."),
    "forecastex": VenueFeePin("forecastex", {"coupon_apy": 0.0313}, "unverified",
                              "RESEARCHED: zero commission; YES+NO quote sums to $1.01 so the "
                              "exchange takes 1c per pair inside the spread. Pays ~3.13% APY on "
                              "held contracts. ~1000x thinner than Kalshi - see 1ST_INVESTIGATION."),
}


def model_for(venue: str) -> FeeModel:
    pin = VENUE_FEES.get(venue)
    if pin is None:
        raise KeyError(f"no fee pin for venue {venue!r}; known: {sorted(VENUE_FEES)}")
    return MODELS[pin.model_id]


def params_for(venue: str, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Pinned params, with per-market payload values taking precedence.

    The override path is not optional politeness — it is the fix for the live bug where
    `match/screen.py` applied PM's 0.07 to every market while the modal live rate is 0.04.
    """
    pin = VENUE_FEES.get(venue)
    if pin is None:
        raise KeyError(f"no fee pin for venue {venue!r}; known: {sorted(VENUE_FEES)}")
    out = dict(pin.params)
    if overrides:
        out.update({k: v for k, v in overrides.items() if v is not None})
    return out


def screening_coeff(venue: str, overrides: Mapping[str, Any] | None = None) -> float:
    """The k in k*p*(1-p) for a first-pass screen. Never report this as an exact cost."""
    return model_for(venue).screening_coeff(params_for(venue, overrides))


def screening_table(price: float = 0.50) -> list[tuple[str, float, float]]:
    """(venue, k, expected cost in cents per contract at `price`) sorted cheapest first."""
    rows = []
    for venue in VENUE_FEES:
        k = screening_coeff(venue)
        rows.append((venue, k, k * price * (1.0 - price) * 100.0))
    return sorted(rows, key=lambda r: r[2])


def selftest() -> None:
    assert abs(screening_coeff("kalshi") - 0.07) < 1e-12
    assert abs(screening_coeff("kalshi", {"liquidity": "maker"}) - 0.0175) < 1e-12
    assert abs(screening_coeff("kalshi", {"fee_multiplier": 0.5}) - 0.035) < 1e-12
    assert abs(screening_coeff("polymarket") - 0.07) < 1e-12
    # per-market override wins over the pin — the fix for the unconditional-0.07 bug
    assert abs(screening_coeff("polymarket", {"fee_rate": 0.05}) - 0.05) < 1e-12
    assert screening_coeff("polymarket", {"liquidity": "maker"}) == 0.0
    assert abs(screening_coeff("betfair") - 0.05) < 1e-12
    assert abs(screening_coeff("smarkets") - 0.02) < 1e-12
    assert screening_coeff("pinnacle") == 0.0          # embedded, not free
    # unknown venue raises rather than defaulting to zero
    try:
        screening_coeff("nonexistent")
        raise AssertionError("unknown venue silently defaulted")
    except KeyError:
        pass
    # params_for never mutates the pin
    p = params_for("kalshi", {"fee_multiplier": 0.5})
    assert p["fee_multiplier"] == 0.5
    assert VENUE_FEES["kalshi"].params["fee_multiplier"] == 1.0
    print("fees.registry selftest OK")


if __name__ == "__main__":
    selftest()

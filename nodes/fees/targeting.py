#!/usr/bin/env python3
"""Where a cover is CHEAP ENOUGH to be worth watching. Derived from the pinned fee curves.

THE HURDLE IS NOT A CONSTANT. Kalshi charges `0.07 * C * p * (1-p)` per contract and Polymarket
sports `~0.05 * C * p * (1-p)`. A cover buys one leg at p and the complementary leg at ~(1-p), and
`p(1-p)` is symmetric -- so BOTH legs sit at the same point on the curve and the combined fee is
approximately `(k_a + k_b) * p * (1-p)`:

    p = 0.50   ->  0.12 * 0.2500  =  3.00c per contract
    p = 0.75   ->  0.12 * 0.1875  =  2.25c
    p = 0.90   ->  0.12 * 0.0900  =  1.08c
    p = 0.95   ->  0.12 * 0.0475  =  0.57c
    p = 0.99   ->  0.12 * 0.0099  =  0.12c

A 25x swing across the price range. Measured on the 2026-09-02 lane: median fee 2.49c per
contract against a median gross gap of 0.70c -- the fee was three and a half times the entire
price discrepancy -- while the cheapest observation of the session paid 0.06c at p=0.995.

So a coin-flip game must show a ~4c cross-venue divergence to clear a 1% hurdle, and a lopsided
one only ~1.6c. Nothing in the scanner prioritised by this; it swept uniformly.

WHAT THIS NODE DOES AND DOES NOT CLAIM. The fee is the KNOWN, computable half of the hurdle. It
says how large a divergence a game needs, never how likely that divergence is -- whether lopsided
games actually diverge more is an empirical question the recorded distribution has to answer.
Ranking by fee is ranking by the part we can compute in advance, not a prediction of edge.
"""

from __future__ import annotations

from dataclasses import dataclass

from nodes.fees.models import Fill
from nodes.fees.registry import model_for, params_for


@dataclass(frozen=True)
class Hurdle:
    """What a specific game needs to show before it is worth anything."""
    price: float                 # the favourite-side ask that anchors the curve
    fee_per_contract: float      # both legs, at the tested size
    required_ask_sum: float      # the two asks must total at or below this
    gap_needed_cents: float      # how far below parity that is, in cents

    @property
    def is_cheap(self) -> bool:
        """Under a cent of fee. The wings, where a cover is nearly free to put on."""
        return self.fee_per_contract < 0.01


def combined_fee(price_a: float, venue_a: str, price_b: float, venue_b: str,
                 contracts: float = 100.0,
                 overrides_a: dict | None = None,
                 overrides_b: dict | None = None) -> float:
    """Entry fee per contract for both legs, priced through the SAME models the cover engine uses.

    Deliberately not a reimplementation of the curve. `nodes/fees/registry.py` is the single place
    a fee is defined, and a targeting heuristic that drifts from the pricer is worse than none --
    it would rank games by a cost the screen does not actually charge.
    """
    total = 0.0
    for price, venue, ov in ((price_a, venue_a, overrides_a), (price_b, venue_b, overrides_b)):
        fill = Fill(venue=venue, market_id="t", outcome_id="o", side="yes",
                    price=price, contracts=contracts, liquidity="taker", order_seq=0)
        total += model_for(venue).entry_cost([fill], params_for(venue, ov or {}))
    return total / contracts


def hurdle_for(price: float, *, venue_a: str = "kalshi", venue_b: str = "polymarket",
               hurdle: float = 0.01, contracts: float = 100.0,
               overrides_a: dict | None = None,
               overrides_b: dict | None = None) -> Hurdle:
    """Given a favourite-side price, what must the two asks total to clear `hurdle`?

    A cover costs `gross + fee` and returns `(1 - cost) / cost`. Requiring that return to be at
    least `h` gives `cost <= 1 / (1 + h)`, so the asks must satisfy
    `gross <= 1 / (1 + h) - fee`.
    """
    p = min(max(price, 1e-6), 1.0 - 1e-6)
    fee = combined_fee(p, venue_a, 1.0 - p, venue_b, contracts, overrides_a, overrides_b)
    required = 1.0 / (1.0 + hurdle) - fee
    return Hurdle(price=p, fee_per_contract=fee, required_ask_sum=required,
                  gap_needed_cents=(1.0 - required) * 100.0)


def rank(prices: dict[str, float], **kw) -> list[tuple[str, Hurdle]]:
    """Games ordered by how small a divergence they need. Cheapest hurdle first."""
    scored = [(gid, hurdle_for(p, **kw)) for gid, p in prices.items()]
    return sorted(scored, key=lambda x: x[1].gap_needed_cents)


def selftest() -> None:
    curve = [(p, hurdle_for(p, overrides_b={"fee_rate": 0.05})) for p in
             (0.50, 0.75, 0.90, 0.95, 0.99)]
    for p, h in curve:
        print(f"  p={p:.2f}  fee={h.fee_per_contract*100:5.2f}c  "
              f"asks must total <= {h.required_ask_sum:.4f}  "
              f"({h.gap_needed_cents:.2f}c below parity)")
    fees = [h.fee_per_contract for _p, h in curve]
    assert fees == sorted(fees, reverse=True), "fee must fall monotonically toward the wings"
    assert fees[0] / fees[-1] > 10, "the coin-flip/wing spread should be an order of magnitude"
    assert not curve[0][1].is_cheap and curve[-1][1].is_cheap
    # symmetry: a cover at p and at 1-p is the same cover, so the hurdle must agree
    assert abs(hurdle_for(0.20).fee_per_contract - hurdle_for(0.80).fee_per_contract) < 1e-9
    print("fees.targeting selftest OK")


if __name__ == "__main__":
    selftest()

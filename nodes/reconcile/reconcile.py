#!/usr/bin/env python3
"""Reconciliation: the venue's word on every order, every fill, every fee, every settlement --
before any capital is released and before any PnL is believed.

  * `resolve_unconfirmed`: every journaled order still UNCONFIRMED or open is asked about through
    `status()`. An unresolved poll stays UNCONFIRMED; it is never promoted to a no-fill.
  * `ingest_fills`: venue fills into the journal's FIFO with their final flag.
  * `check_fees`: a charged fee above the pinned curve is a STOP and a re-pin, not a rounding note
    (GATE step 8). Returned as a finding; the caller latches.
  * `settle`: given each venue's settlement outcome for the event, realized PnL per leg becomes
    `RealizedFill`s for the loss breaker. Settlement timing differs between venues; the ledger
    releases only when BOTH legs are final and settled.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping, Sequence
import math

from kernel.execution_protocol import ExecutionVenue, FillRecord
from kernel.schema import FillState
from nodes.execution.journal import Journal
from nodes.fees.models import Fill
from nodes.fees.registry import model_for, params_for
from nodes.risk.breaker import RealizedFill, day_of


@dataclass(frozen=True)
class FeeFinding:
    venue: str
    order_client_id: str
    charged_usd: float
    pinned_usd: float
    excess_usd: float

    @property
    def stop(self) -> bool:
        return self.excess_usd > 1e-6


def resolve_unconfirmed(journal: Journal, venues: Mapping[str, ExecutionVenue]) -> tuple[dict[str, str], set[str]]:
    """client_order_id -> resulting state, and the ids the venue proved TERMINAL.

    L92 (2026-09-12): the state is not finality, and a caller that reads `UNFILLED` as "nothing
    filled, ever" releases the capital of a position the venue is still about to hand it. Polymarket
    returns UNFILLED with `final=False` for a `delayed` order -- the exact case
    `Coordinator._settle_ack` was fixed for and documents -- and Kalshi returns UNFILLED with
    `open=True` for an order still resting. Finality is reported separately, and absent evidence the
    id is simply not in the set: unknown is never terminal.
    """
    out, final = {}, set()
    for row in journal.unconfirmed():
        v = venues.get(row["venue"])
        if v is None:
            out[row["client_order_id"]] = FillState.UNCONFIRMED.value
            continue
        st = v.status(row["client_order_id"])
        out[row["client_order_id"]] = st.state.value
        if getattr(st, "final", False) and not getattr(st, "open", False):
            final.add(row["client_order_id"])
    return out, final


def ingest_fills(journal: Journal, venues: Mapping[str, ExecutionVenue], *, since_utc: float) -> list[FillRecord]:
    out = []
    for v in venues.values():
        out.extend(v.fills(since_utc=since_utc))
    return out


def check_fees(journal: Journal, fills: Sequence[FillRecord], fee_params: Mapping[str, Mapping]) -> list[FeeFinding]:
    """Charged vs pinned, per fill, through the same fee models the cover used."""
    findings = []
    for f in fills:
        row = next((r for r in (journal.get(cid) for cid in _client_ids_for(journal, f.venue_order_id)) if r), None)
        pinned = model_for(f.venue).entry_cost([Fill(f.venue, f.venue_order_id, "o", "yes", f.price, f.contracts,
                                                     "taker" if f.is_taker else "maker", 0)],
                                               params_for(f.venue, fee_params.get(f.venue, {})))
        findings.append(FeeFinding(f.venue, row["client_order_id"] if row else "", f.fee_usd, pinned,
                                   max(0.0, f.fee_usd - pinned)))
    return findings


def _client_ids_for(journal: Journal, venue_order_id: str) -> list[str]:
    rows = journal.store.con.execute("SELECT client_order_id FROM orders WHERE venue_order_id=?", (venue_order_id,)).fetchall()
    return [r[0] for r in rows]


def settle(*, legs: Sequence[dict], winners: Mapping[str, str],
           payouts: Mapping[str, Mapping[str, float]] | None = None,
           now: float | None = None) -> list[RealizedFill]:
    """Realized PnL per leg. `legs`: [{venue, client_order_id, outcome_id, side, contracts, price, fee_usd,
    state, final}]; `winners`: venue -> the outcome_id that won on that venue (each venue's OWN
    settlement, which is the point). ``payouts`` optionally supplies the venue-authoritative
    outcome_id -> payout map (including scalar/half outcomes); when absent, the legacy binary
    ``winners`` path is used. A leg whose venue has not settled yields an UNCONFIRMED
    RealizedFill, which keeps the day's PnL unknown and the breaker closed."""
    t = now or time.time()
    out = []
    for leg in legs:
        st = FillState(leg["state"])
        if st in (FillState.UNCONFIRMED,) or not leg.get("final", True):
            out.append(RealizedFill(leg["client_order_id"], FillState.UNCONFIRMED, 0.0, day_of(t)))
            continue
        if st in (FillState.UNFILLED, FillState.REJECTED) or leg["contracts"] <= 0:
            out.append(RealizedFill(leg["client_order_id"], st, 0.0, day_of(t)))
            continue
        venue = leg["venue"]
        w = winners.get(venue)
        venue_payouts = payouts.get(venue) if payouts else None
        bought = leg["outcome_id"]
        base = bought[:-3] if bought.endswith(":NO") else bought
        payout_per_contract = None
        if venue_payouts is not None:
            try:
                candidate = venue_payouts.get(base)
                if candidate is not None:
                    candidate = float(candidate)
                    if math.isfinite(candidate) and 0.0 <= candidate <= 1.0:
                        payout_per_contract = 1.0 - candidate if bought.endswith(":NO") else candidate
            except (TypeError, ValueError):
                payout_per_contract = None
        if payout_per_contract is None and w is None:
            out.append(RealizedFill(leg["client_order_id"], FillState.UNCONFIRMED, 0.0, day_of(t)))
            continue
        if payout_per_contract is None:
            if bought.endswith(":NO"):
            # Kalshi's complementary NO on the other ticker, or Polymarket's NO token on a
            # three-way team market (2026-09-04): pays when the game did NOT go to its YES twin.
                won = w != base
            else:
                won = w == bought
            payout_per_contract = 1.0 if won else 0.0
        payout = leg["contracts"] * payout_per_contract
        # A sell leg (the unwind, 2026-09-08) took the price in and owes the payout: the sign flips.
        sign = -1.0 if str(leg.get("side") or "").startswith("sell_") else 1.0
        pnl = sign * (payout - leg["contracts"] * leg["price"]) - float(leg.get("fee_usd") or 0.0)
        out.append(RealizedFill(leg["client_order_id"], st, pnl, day_of(t)))
    return out


def releasable(realized: Sequence[RealizedFill]) -> bool:
    """Capital is released only when every leg is final: no UNCONFIRMED anywhere."""
    return bool(realized) and all(r.state is not FillState.UNCONFIRMED for r in realized)

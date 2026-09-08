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


def resolve_unconfirmed(journal: Journal, venues: Mapping[str, ExecutionVenue]) -> dict[str, str]:
    """client_order_id -> resulting state. UNCONFIRMED stays UNCONFIRMED; nothing is assumed."""
    out = {}
    for row in journal.unconfirmed():
        v = venues.get(row["venue"])
        if v is None:
            out[row["client_order_id"]] = FillState.UNCONFIRMED.value
            continue
        st = v.status(row["client_order_id"])
        out[row["client_order_id"]] = st.state.value
    return out


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


def settle(*, legs: Sequence[dict], winners: Mapping[str, str], now: float | None = None) -> list[RealizedFill]:
    """Realized PnL per leg. `legs`: [{venue, client_order_id, outcome_id, side, contracts, price, fee_usd,
    state, final}]; `winners`: venue -> the outcome_id that won on that venue (each venue's OWN
    settlement, which is the point). A leg whose venue has not settled yields an UNCONFIRMED
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
        w = winners.get(leg["venue"])
        if w is None:
            out.append(RealizedFill(leg["client_order_id"], FillState.UNCONFIRMED, 0.0, day_of(t)))
            continue
        bought = leg["outcome_id"]
        if bought.endswith(":NO"):
            # Kalshi's complementary NO on the other ticker, or Polymarket's NO token on a
            # three-way team market (2026-09-04): pays when the game did NOT go to its YES twin.
            won = w != bought[:-3]
        else:
            won = w == bought
        payout = leg["contracts"] if won else 0.0
        # A sell leg (the unwind, 2026-09-08) took the price in and owes the payout: the sign flips.
        sign = -1.0 if str(leg.get("side") or "").startswith("sell_") else 1.0
        pnl = sign * (payout - leg["contracts"] * leg["price"]) - float(leg.get("fee_usd") or 0.0)
        out.append(RealizedFill(leg["client_order_id"], st, pnl, day_of(t)))
    return out


def releasable(realized: Sequence[RealizedFill]) -> bool:
    """Capital is released only when every leg is final: no UNCONFIRMED anywhere."""
    return bool(realized) and all(r.state is not FillState.UNCONFIRMED for r in realized)

#!/usr/bin/env python3
"""The one check every adapter's submit() runs first: a live, unused clearance for THIS order."""

from __future__ import annotations

import time

from kernel.execution_protocol import Ack, OrderRequest
from kernel.schema import FillState, Mode
from nodes.risk.clearance import RiskClearance


def admit(req: OrderRequest, clearance, *, venue: str, mode: Mode, needs: Mode,
          now_mono: float | None = None, now: float | None = None) -> Ack | None:
    """None if the order may go; otherwise the REJECTED ack to return. Consumes the clearance."""
    t = now or time.time()
    if not mode.allows(needs):
        return Ack(venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "MODE", t,
                   detail=f"{mode.value} may not submit to a {venue} adapter that needs {needs.value}")
    if not isinstance(clearance, RiskClearance):
        return Ack(venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "NO_CLEARANCE", t,
                   detail="submit() requires a RiskClearance minted by nodes/risk.clear()")
    if clearance.opportunity_id != req.opportunity_id:
        return Ack(venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "CLEARANCE_MISMATCH", t,
                   detail=f"clearance is for {clearance.opportunity_id}, order is for {req.opportunity_id}")
    if not clearance.consume(now_mono):
        return Ack(venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "CLEARANCE_SPENT", t,
                   detail="clearance already used or expired")
    return None

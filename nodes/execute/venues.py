#!/usr/bin/env python3
"""The one place adapters are chosen by mode. The coordinator never branches on mode itself.

    OFFLINE_REPLAY   paper / paper
    SHADOW_LIVE      refusing / refusing
    PAPER_EXECUTION  paper / paper            (fed by the live replicas' books)
    DEMO_EXECUTION   Kalshi demo host / paper (Polymarket has no demo)
    LIMITED_LIVE     Kalshi prod / Polymarket real, under the signed override
    PRODUCTION       Kalshi prod / Polymarket real
"""

from __future__ import annotations

from typing import Callable

from kernel.schema import Mode
from nodes.execution.journal import Journal
from nodes.execution.paper import PaperVenue, RefusingVenue


def build_venues(mode: Mode, journal: Journal, *, kalshi_factory: Callable[[str], object] | None = None,
                 polymarket_factory: Callable[[], object] | None = None, clock=None, mono=None) -> dict[str, object]:
    kw = {k: v for k, v in (("clock", clock), ("mono", mono)) if v}
    if mode is Mode.SHADOW_LIVE:
        return {"kalshi": RefusingVenue("kalshi", journal, **kw), "polymarket": RefusingVenue("polymarket", journal, **kw)}
    if mode in (Mode.OFFLINE_REPLAY, Mode.PAPER_EXECUTION):
        return {"kalshi": PaperVenue("kalshi", journal, mode=mode, **kw),
                "polymarket": PaperVenue("polymarket", journal, mode=mode, **kw)}
    if mode is Mode.DEMO_EXECUTION:
        if kalshi_factory is None:
            raise ValueError("DEMO_EXECUTION needs a Kalshi demo adapter factory (demo credentials)")
        return {"kalshi": kalshi_factory("demo"), "polymarket": PaperVenue("polymarket", journal, mode=mode, **kw)}
    if kalshi_factory is None or polymarket_factory is None:
        raise ValueError(f"{mode.value} needs both real adapter factories")
    return {"kalshi": kalshi_factory("prod"), "polymarket": polymarket_factory()}

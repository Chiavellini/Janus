#!/usr/bin/env python3
"""From a slate spec's raw rules fields to records and a verdict. One code path for discovery
(which writes the records), the supervisor (which spawns) and the replay harness."""

from __future__ import annotations

from typing import Mapping

from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence, certify
from nodes.settle_wedge.harvest import RulesRecord, harvest_kalshi, harvest_polymarket


def records_from_spec(spec: Mapping) -> tuple[RulesRecord, RulesRecord] | None:
    rules = spec.get("rules") or {}
    k, p = rules.get("kalshi"), rules.get("polymarket")
    if not k or not p:
        return None
    t = float(rules.get("retrieved_at") or 0.0)
    return (harvest_kalshi(k["market"], participants=k.get("participants", ()), retrieved_at=t,
                           series=k.get("series")),
            harvest_polymarket(p["market"], participants=p.get("participants", ()), retrieved_at=t))


def certify_from_spec(spec: Mapping, league: str, *,
                      rates: Mapping[str, float] | None = None) -> SettlementEquivalence | NotEquivalent:
    recs = records_from_spec(spec)
    if recs is None:
        return NotEquivalent("RULES_MISSING", "the slate spec carries no rules text for one or both venues")
    return certify(recs[0], recs[1], league=league, rates=rates)


def summary(result: SettlementEquivalence | NotEquivalent) -> dict:
    if isinstance(result, SettlementEquivalence):
        return {"result": "EQUIVALENT", "template_a": result.template_a, "template_b": result.template_b,
                "rates": dict(result.rates)}
    return {"result": "BLOCKED", "code": result.code, "detail": result.detail, "dimension": result.dimension}

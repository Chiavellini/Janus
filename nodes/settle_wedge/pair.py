#!/usr/bin/env python3
"""From a slate spec's raw rules fields to records and a verdict. One code path for discovery
(which writes the records), the supervisor (which spawns) and the replay harness."""

from __future__ import annotations

from typing import Mapping

from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence, certify
from nodes.settle_wedge.harvest import RulesRecord, harvest_kalshi, harvest_polymarket


def population_from_schedule(game) -> dict:
    """Preserve the external schedule classification for every certification consumer."""
    return {"source": "espn" if game.game_id.startswith("espn:") else "venue_structured",
            "game_id": game.game_id, "league": game.league, "season_slug": game.season_slug}


def _scrub(league: str | None) -> tuple[str, ...]:
    from nodes.entities.leagues import LEAGUES
    return LEAGUES[league].template_scrub if league in LEAGUES else ()


def records_from_spec(spec: Mapping, league: str | None = None) -> tuple[RulesRecord, RulesRecord] | None:
    rules = spec.get("rules") or {}
    k, p = rules.get("kalshi"), rules.get("polymarket")
    if not k or not p:
        return None
    t = float(rules.get("retrieved_at") or 0.0)
    scrub = _scrub(league or spec.get("league"))
    return (harvest_kalshi(k["market"], participants=k.get("participants", ()), retrieved_at=t,
                           series=k.get("series"), scrub=scrub),
            harvest_polymarket(p["market"], participants=p.get("participants", ()), retrieved_at=t, scrub=scrub))


def certify_from_spec(spec: Mapping, league: str, *,
                      rates: Mapping[str, float] | None = None) -> SettlementEquivalence | NotEquivalent:
    recs = records_from_spec(spec, league)
    if recs is None:
        return NotEquivalent("RULES_MISSING", "the slate spec carries no rules text for one or both venues")
    if league == "mls":
        population = spec.get("schedule_population")
        if not isinstance(population, Mapping) or population.get("game_id") != spec.get("game_id"):
            return NotEquivalent("EVIDENCE_POPULATION_MISMATCH",
                                 "MLS schedule population must identify this exact slate game")
    return certify(recs[0], recs[1], league=league, population=spec.get("schedule_population"), rates=rates)


def summary(result: SettlementEquivalence | NotEquivalent) -> dict:
    if isinstance(result, SettlementEquivalence):
        return {"result": "EQUIVALENT", "template_a": result.template_a, "template_b": result.template_b,
                "rates": dict(result.rates)}
    return {"result": "BLOCKED", "code": result.code, "detail": result.detail, "dimension": result.dimension}

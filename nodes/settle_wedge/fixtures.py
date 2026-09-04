#!/usr/bin/env python3
"""Proofs for tests, built the only way proofs can be built: from the reviewed sample texts,
through harvest and certify, with injected rates. Nothing here mints anything itself."""

from __future__ import annotations

from nodes.rules_exhaustive.rules import prove
from nodes.settle_wedge.equivalence import CoverProof, SettlementEquivalence, certify, certify_cover
from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
from nodes.settle_wedge.policy import KALSHI_EPL_GAME_V1, KALSHI_MLB_GAME_V1, POLYMARKET_MLB_GAME_V1, POLYMARKET_SOCCER_GAME_V2

RATES_FOR_TESTS = {"mlb.cancelled_rate": 0.002, "mlb.postponed_gt2d_rate": 0.01}
NO_WEDGE = {"mlb.cancelled_rate": 0.0, "mlb.postponed_gt2d_rate": 0.0}


def mlb_records(retrieved_at: float = 1_800_000_000.0):
    k = harvest_kalshi({"ticker": "KXMLBGAME-TEST", "rules_primary": KALSHI_MLB_GAME_V1.sample_text.split("\n")[0],
                        "rules_secondary": "\n".join(KALSHI_MLB_GAME_V1.sample_text.split("\n")[1:])},
                       participants=KALSHI_MLB_GAME_V1.sample_participants, retrieved_at=retrieved_at)
    p = harvest_polymarket({"slug": "mlb-test", "description": POLYMARKET_MLB_GAME_V1.sample_text,
                            "resolutionSource": "https://www.mlb.com/"},
                           participants=POLYMARKET_MLB_GAME_V1.sample_participants, retrieved_at=retrieved_at)
    return k, p


def mlb_equivalence(rates=None) -> SettlementEquivalence:
    k, p = mlb_records()
    eq = certify(k, p, league="mlb", rates=NO_WEDGE if rates is None else rates)
    assert isinstance(eq, SettlementEquivalence), eq
    return eq


def mlb_cover_proof(outcome_ids, rates=None) -> CoverProof:
    """Zero-rate by default so a test's arithmetic is about prices and fees unless it opts in."""
    cp = certify_cover(prove("mlb", "moneyline", "game", list(outcome_ids)), mlb_equivalence(rates))
    assert isinstance(cp, CoverProof), cp
    return cp


#: Three-way soccer (2026-09-04): the EPL texts, injected L33-shaped rates.
EPL_RATES_FOR_TESTS = {"soccer.epl.postponed_gt48h_rate": 0.004, "soccer.epl.cancelled_rate": 0.0005}


def epl_records(retrieved_at: float = 1_800_000_000.0):
    k = harvest_kalshi({"ticker": "KXEPLGAME-TEST", "rules_primary": KALSHI_EPL_GAME_V1.sample_text.split("\n")[0],
                        "rules_secondary": KALSHI_EPL_GAME_V1.sample_text.split("\n", 1)[1]},
                       participants=KALSHI_EPL_GAME_V1.sample_participants, retrieved_at=retrieved_at)
    p = harvest_polymarket({"slug": "epl-test", "description": POLYMARKET_SOCCER_GAME_V2.sample_text},
                           participants=POLYMARKET_SOCCER_GAME_V2.sample_participants, retrieved_at=retrieved_at)
    return k, p


def epl_equivalence(rates=None) -> SettlementEquivalence:
    k, p = epl_records()
    eq = certify(k, p, league="epl", rates=EPL_RATES_FOR_TESTS if rates is None else rates)
    assert isinstance(eq, SettlementEquivalence), eq
    return eq


def epl_cover_proof(outcome_ids, rates=None) -> CoverProof:
    cp = certify_cover(prove("epl", "moneyline", "game", list(outcome_ids)), epl_equivalence(rates))
    assert isinstance(cp, CoverProof), cp
    return cp

#!/usr/bin/env python3
"""Three-way soccer: the verbatim texts hash to the reviewed templates, an unmeasured rate blocks,
injected rates certify, and the exhaustiveness proof needs all three outcomes."""
from __future__ import annotations

from kernel.schema import Book, Quote
from nodes.cover.cover import Leg, price_combination
from nodes.rules_exhaustive.rules import prove
from nodes.settle_wedge.equivalence import CoverProof, NotEquivalent, SettlementEquivalence, certify, certify_cover
from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
from nodes.settle_wedge.policy import (KALSHI_EPL_GAME_V1, KALSHI_LAL_GAME_V1, KALSHI_MLS_GAME_V1,
                                       POLYMARKET_SOCCER_DRAW_CLAUSE_2026_09_03, POLYMARKET_SOCCER_GAME_V1,
                                       POLYMARKET_SOCCER_GAME_V2)

T = 1_800_000_000.0
RATES = {"soccer.epl.postponed_gt48h_rate": 0.004, "soccer.epl.cancelled_rate": 0.0005}


def records(k_tmpl=KALSHI_EPL_GAME_V1):
    k = harvest_kalshi({"ticker": "t", "rules_primary": k_tmpl.sample_text.split("\n")[0],
                        "rules_secondary": k_tmpl.sample_text.split("\n", 1)[1]},
                       participants=k_tmpl.sample_participants, retrieved_at=T)
    p = harvest_polymarket({"slug": "s", "description": POLYMARKET_SOCCER_GAME_V2.sample_text},
                           participants=POLYMARKET_SOCCER_GAME_V2.sample_participants, retrieved_at=T)
    return k, p


def test_the_texts_hash_to_their_templates_and_polymarket_is_one_template_for_every_league():
    k, p = records()
    assert k.template_hash == KALSHI_EPL_GAME_V1.template_hash and p.template_hash == POLYMARKET_SOCCER_GAME_V2.template_hash
    # a La Liga game on Polymarket reads the same once the names and the date are stripped
    p2 = harvest_polymarket({"slug": "lal-x", "description": POLYMARKET_SOCCER_GAME_V2.sample_text
                             .replace("Leeds United FC", "Real Sociedad de Fútbol").replace("September 14, 2026", "September 3, 2026")},
                            participants=("Real Sociedad de Fútbol", "RC Celta de Vigo"), retrieved_at=T)
    assert p2.template_hash == POLYMARKET_SOCCER_GAME_V2.template_hash
    # the older live text (events created 2026-08-21) is its own template with the same verdicts
    p1 = harvest_polymarket({"slug": "lal-rso-cel-2026-09-03-rso", "description": POLYMARKET_SOCCER_GAME_V1.sample_text},
                            participants=POLYMARKET_SOCCER_GAME_V1.sample_participants, retrieved_at=T)
    assert p1.template_hash == POLYMARKET_SOCCER_GAME_V1.template_hash != POLYMARKET_SOCCER_GAME_V2.template_hash
    from nodes.settle_wedge.policy import verdicts_for
    assert verdicts_for(KALSHI_LAL_GAME_V1.template_id, "polymarket_soccer_game_v1") == verdicts_for(KALSHI_LAL_GAME_V1.template_id, "polymarket_soccer_game_v2")
    # Kalshi names the competition in the sentence, so La Liga and MLS are their own templates
    assert len({KALSHI_EPL_GAME_V1.template_hash, KALSHI_LAL_GAME_V1.template_hash, KALSHI_MLS_GAME_V1.template_hash}) == 3
    assert "resolve to \"Yes\"" in POLYMARKET_SOCCER_DRAW_CLAUSE_2026_09_03 and "canceled" in POLYMARKET_SOCCER_DRAW_CLAUSE_2026_09_03


def test_every_soccer_pair_blocks_on_its_unmeasured_rate_and_certifies_once_measured():
    k, p = records()
    got = certify(k, p, league="epl")
    assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED"
    assert got.context["evidence_key"].startswith("soccer.epl.")
    eq = certify(k, p, league="epl", rates=RATES)
    assert isinstance(eq, SettlementEquivalence)
    by = {v.dimension: v.outcome for v in eq.verdicts}
    assert by["overtime"] == "SAME" and by["tie"] == "SAME" and by["cancellation"] == "BOUNDED"
    # the buffer charges Polymarket legs only; three Polymarket legs at 0.4/0.3/0.3 -> postponement
    # (twice: suspended, abandoned share the key -> three times) plus cancellation, each p * price
    legs = [("kalshi", 0.40), ("polymarket", 0.30), ("polymarket", 0.30)]
    n_post = sum(1 for v in eq.verdicts if v.evidence_key == "soccer.epl.postponed_gt48h_rate")
    assert abs(eq.settlement_buffer(legs) - (n_post * 0.004 * 0.60 + 0.0005 * 0.60)) < 1e-9


def test_the_proof_needs_the_draw_and_a_three_leg_cover_prices():
    k, p = records()
    eq = certify(k, p, league="epl", rates=RATES)
    two = prove("epl", "moneyline", "game", ["home", "away"])
    assert two.code == "OUTCOME_COUNT_MISMATCH"
    three = prove("epl", "moneyline", "game", ["home", "draw", "away"])
    cp = certify_cover(three, eq)
    assert isinstance(cp, CoverProof)

    def bk(px):
        return Book(asks=(Quote(px, 1000.0),), fetched_utc=T)
    fees_k = {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}
    fees_p = {"fee_rate": 0.05}
    legs = [Leg("kalshi", "kalshi_clob", "home", "K-H", bk(0.40), fees_k),
            Leg("polymarket", "pm_clob", "draw", "tok-d", bk(0.26), fees_p),
            Leg("polymarket", "pm_clob", "away", "tok-a", bk(0.30), fees_p)]
    cov = price_combination(legs, 100.0, now_utc=T, max_leg_age_s=30.0, proof=cp)
    assert cov.ok and len(cov.legs) == 3
    assert cov.gross_per_contract == 0.96 and cov.cost_per_contract > 0.96
    # without the draw leg the same proof cannot price: a two-leg "cover" is not one
    two_legs = price_combination(legs[:1] + legs[2:], 100.0, now_utc=T, max_leg_age_s=30.0, proof=cp)
    assert two_legs.ok, "price_combination prices what it is given; the poller's prove() is the gate"


def test_college_football_texts_hash_to_their_templates_and_the_tie_cannot_fire():
    from nodes.settle_wedge.policy import KALSHI_CFB_GAME_V1, POLYMARKET_CFB_GAME_V1
    k = harvest_kalshi({"ticker": "t", "rules_primary": KALSHI_CFB_GAME_V1.sample_text.split("\n")[0],
                        "rules_secondary": KALSHI_CFB_GAME_V1.sample_text.split("\n", 1)[1]},
                       participants=KALSHI_CFB_GAME_V1.sample_participants, retrieved_at=T)
    p = harvest_polymarket({"slug": "s", "description": POLYMARKET_CFB_GAME_V1.sample_text},
                           participants=POLYMARKET_CFB_GAME_V1.sample_participants, retrieved_at=T)
    assert k.template_hash == KALSHI_CFB_GAME_V1.template_hash and p.template_hash == POLYMARKET_CFB_GAME_V1.template_hash
    got = certify(k, p, league="cfb")
    assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED" and got.context["evidence_key"].startswith("cfb.")
    eq = certify(k, p, league="cfb", rates={"cfb.postponed_gt48h_rate": 0.002, "cfb.cancelled_rate": 0.001})
    assert isinstance(eq, SettlementEquivalence)
    assert {v.dimension: v.outcome for v in eq.verdicts}["tie"] == "NA"
    assert isinstance(certify_cover(prove("cfb", "moneyline", "game", ["a", "b"]), eq), CoverProof)


def test_a_school_named_without_its_nickname_still_hashes_to_the_template():
    """Live 2026-09-03: Polymarket wrote 'Kentucky Christian' / 'Morehead State' while the participants
    known to discovery were the full ESPN names; the normaliser strips the head of a name too."""
    from nodes.settle_wedge.policy import POLYMARKET_CFB_GAME_V1
    text = POLYMARKET_CFB_GAME_V1.sample_text.replace("Louisiana Christian", "Kentucky Christian").replace("Northwestern State", "Morehead State")
    p = harvest_polymarket({"slug": "s", "description": text},
                           participants=("Kentucky Christian Knights", "Morehead State Eagles", "Knights", "Eagles"), retrieved_at=T)
    assert p.template_hash == POLYMARKET_CFB_GAME_V1.template_hash, p.template_text

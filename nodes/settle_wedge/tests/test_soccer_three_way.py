#!/usr/bin/env python3
"""Three-way soccer: the verbatim texts hash to the reviewed templates, an unmeasured rate blocks,
injected rates certify, and the exhaustiveness proof needs all three outcomes."""
from __future__ import annotations

import pytest

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
    # V3 (2026-09-05): V2 without its trailing 24-hour no-data sentence. The hash is DERIVED from the
    # text and pinned to the one the lane recorded for LIV @ IPS and KOE @ VFB (TEMPLATE_UNKNOWN all
    # evening on 2026-09-04); the pair verdicts are the same rulings as V1/V2.
    from nodes.settle_wedge.policy import POLYMARKET_SOCCER_GAME_V3, TEMPLATES
    assert POLYMARKET_SOCCER_GAME_V3.template_hash == "7580dcecfba14bc3" and POLYMARKET_SOCCER_GAME_V3.template_hash in TEMPLATES
    assert verdicts_for(KALSHI_LAL_GAME_V1.template_id, "polymarket_soccer_game_v3") == verdicts_for(KALSHI_LAL_GAME_V1.template_id, "polymarket_soccer_game_v1")
    # Kalshi names the competition in the sentence, so La Liga and MLS are their own templates
    assert len({KALSHI_EPL_GAME_V1.template_hash, KALSHI_LAL_GAME_V1.template_hash, KALSHI_MLS_GAME_V1.template_hash}) == 3
    assert "resolve to \"Yes\"" in POLYMARKET_SOCCER_DRAW_CLAUSE_2026_09_03 and "canceled" in POLYMARKET_SOCCER_DRAW_CLAUSE_2026_09_03


def test_every_soccer_pair_blocks_on_its_unmeasured_rate_and_certifies_once_measured():
    k, p = records()
    from nodes.settle_wedge import evidence
    saved = dict(evidence.EVIDENCE)
    try:
        evidence.EVIDENCE.clear()                  # before L33
        got = certify(k, p, league="epl")
        assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED"
        assert got.context["evidence_key"].startswith("soccer.epl.")
    finally:
        evidence.EVIDENCE.update(saved)
    # the registry (L33): 58 of 1,520 Premier League matches played >48 h after their round window, 0 cancelled;
    # postponement is charged once (suspended and abandoned are the same population, ruled SAME)
    live = certify(k, p, league="epl")
    assert isinstance(live, SettlementEquivalence)
    assert live.settlement_buffer([("kalshi", 0.40), ("polymarket", 0.30), ("polymarket", 0.30)]) == pytest.approx(
        (58 / 1520) * 0.60, abs=1e-6)
    assert sum(1 for v in live.verdicts if v.outcome == "BOUNDED") == 2
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
    # without the draw leg the same proof cannot price: two singleton legs on a three-outcome
    # proof are not a partition (the pricer checks it since 2026-09-04, not only the poller's prove())
    two_legs = price_combination(legs[:1] + legs[2:], 100.0, now_utc=T, max_leg_age_s=30.0, proof=cp)
    assert not two_legs.ok and two_legs.reject_reason == "outcome_set_not_proven_exhaustive"
    # but Kalshi YES home + Polymarket NO home (covering draw and away) IS a cover, in two legs
    no_home = Leg("polymarket", "pm_clob", "tok-h:NO", "tok-h-no", bk(0.55), fees_p, covers=frozenset({"draw", "away"}))
    two_way = price_combination([legs[0], no_home], 100.0, now_utc=T, max_leg_age_s=30.0, proof=cp)
    assert two_way.ok and len(two_way.legs) == 2 and two_way.gross_per_contract == 0.95
    assert two_way.worst_settlement_state in ("", "home", "draw", "away")   # '' when no venue charges at settlement
    # and best_cover finds the two-leg shape from a compound offers key
    offers = {"home": [legs[0]], "draw": [legs[1]], "away": [legs[2]], "away|draw": [no_home]}
    from nodes.cover.cover import best_cover
    best = best_cover(offers, 100.0, now_utc=T, max_leg_age_s=30.0, proof=cp)
    assert best.ok and len(best.legs) == 2 and best.cost_per_contract < cov.cost_per_contract


def test_college_football_texts_hash_to_their_templates_and_the_tie_cannot_fire():
    from nodes.settle_wedge.policy import KALSHI_CFB_GAME_V1, POLYMARKET_CFB_GAME_V1
    k = harvest_kalshi({"ticker": "t", "rules_primary": KALSHI_CFB_GAME_V1.sample_text.split("\n")[0],
                        "rules_secondary": KALSHI_CFB_GAME_V1.sample_text.split("\n", 1)[1]},
                       participants=KALSHI_CFB_GAME_V1.sample_participants, retrieved_at=T)
    p = harvest_polymarket({"slug": "s", "description": POLYMARKET_CFB_GAME_V1.sample_text},
                           participants=POLYMARKET_CFB_GAME_V1.sample_participants, retrieved_at=T)
    assert k.template_hash == KALSHI_CFB_GAME_V1.template_hash and p.template_hash == POLYMARKET_CFB_GAME_V1.template_hash
    from nodes.settle_wedge import evidence
    saved = dict(evidence.EVIDENCE)
    try:
        evidence.EVIDENCE.clear()                  # before L32
        got = certify(k, p, league="cfb")
        assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED" and got.context["evidence_key"].startswith("cfb.")
    finally:
        evidence.EVIDENCE.update(saved)
    live = certify(k, p, league="cfb")
    assert isinstance(live, SettlementEquivalence) and set(live.rates) == {"cfb.postponed_gt48h_rate", "cfb.cancelled_rate"}
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


def test_tennis_texts_hash_to_their_templates_across_tournaments_and_block_on_unmeasured_rates():
    from nodes.entities.leagues import LEAGUES
    from nodes.settle_wedge.policy import KALSHI_TENNIS_MATCH_V1, POLYMARKET_TENNIS_MATCH_V1
    scrub = LEAGUES["atp"].template_scrub
    # another tournament and round, other players: the scrub removes what varies
    k_text = (KALSHI_TENNIS_MATCH_V1.sample_text.replace("Yibing Wu", "Jannik Sinner").replace("Wu vs Alcaraz", "Sinner vs Zverev")
              .replace("2026 US Open Men Singles Round Of 32", "2026 Shanghai Masters Men Singles Quarterfinal"))
    k = harvest_kalshi({"ticker": "t", "rules_primary": k_text.split("\n")[0], "rules_secondary": k_text.split("\n", 1)[1]},
                       participants=("Jannik Sinner", "Alexander Zverev"), retrieved_at=T, scrub=scrub)
    assert k.template_hash == KALSHI_TENNIS_MATCH_V1.template_hash, k.template_text
    p_text = (POLYMARKET_TENNIS_MATCH_V1.sample_text.replace("Laura Siegemund", "Jannik Sinner").replace("Liudmila Samsonova", "Alexander Zverev")
              .replace("'Siegemund'", "'Sinner'").replace("'Samsonova'", "'Zverev'").replace("Australian Open WTA", "Shanghai Masters ATP")
              .replace("January 17 at 7:00PM ET", "October 10 at 8:00AM ET").replace("Australian Open", "Shanghai Masters"))
    p = harvest_polymarket({"slug": "s", "description": p_text}, participants=("Jannik Sinner", "Alexander Zverev"), retrieved_at=T, scrub=scrub)
    assert p.template_hash == POLYMARKET_TENNIS_MATCH_V1.template_hash, p.template_text
    # Since F4 (2026-09-05) both tennis rates are registered, so the pair CERTIFIES at the registry's
    # values: L39's walkover rate and the forward row's UPPER BOUND on the delay rate.
    from nodes.settle_wedge.evidence import EVIDENCE
    got = certify(k, p, league="atp")
    assert isinstance(got, SettlementEquivalence) and got.rates["tennis.delayed_gt7d_rate"] == EVIDENCE["tennis.delayed_gt7d_rate"].value
    rates = {"tennis.walkover_rate": 0.02, "tennis.delayed_gt7d_rate": 0.001}
    eq = certify(k, p, league="atp", rates=rates)
    assert isinstance(eq, SettlementEquivalence)
    by = {v.dimension: v.outcome for v in eq.verdicts}
    assert by["retirement"] == "SAME" and by["player_non_participation"] == "BOUNDED" and by["postponement"] == "BOUNDED"
    # the buffer: walkover charges max(0, p_pm - 0.5), the long delay charges half a contract
    assert eq.settlement_buffer([("kalshi", 0.30), ("polymarket", 0.70)]) == pytest.approx(0.02 * 0.20 + 0.001 * 0.5, abs=1e-9)
    assert isinstance(certify_cover(prove("atp", "moneyline", "game", ["a", "b"]), eq), CoverProof)
    # the WTA text ("Potapova vs Anisimova ... Women Singles Round Of 32") hashes to the same template
    w_text = (KALSHI_TENNIS_MATCH_V1.sample_text.replace("Yibing Wu", "Anastasia Potapova").replace("Wu vs Alcaraz", "Potapova vs Anisimova")
              .replace("Men Singles", "Women Singles"))
    w = harvest_kalshi({"ticker": "t", "rules_primary": w_text.split("\n")[0], "rules_secondary": w_text.split("\n", 1)[1]},
                       participants=("Anastasia Potapova", "Amanda Anisimova"), retrieved_at=T, scrub=LEAGUES["wta"].template_scrub)
    assert w.template_hash == KALSHI_TENNIS_MATCH_V1.template_hash
    assert isinstance(certify(w, p, league="wta", rates=rates), SettlementEquivalence)


def test_polymarket_has_two_tennis_texts_and_both_certify():
    from nodes.entities.leagues import LEAGUES
    from nodes.settle_wedge.policy import KALSHI_TENNIS_MATCH_V1, POLYMARKET_TENNIS_MATCH_V2, verdicts_for
    scrub = LEAGUES["wta"].template_scrub
    a, b = POLYMARKET_TENNIS_MATCH_V2.sample_participants
    text = POLYMARKET_TENNIS_MATCH_V2.sample_text.replace(a, "Iga Swiatek").replace(b, "Coco Gauff").replace("US Open", "Wimbledon")
    p = harvest_polymarket({"slug": "s", "description": text}, participants=("Iga Swiatek", "Coco Gauff"), retrieved_at=T, scrub=scrub)
    assert p.template_hash == POLYMARKET_TENNIS_MATCH_V2.template_hash, p.template_text
    assert verdicts_for(KALSHI_TENNIS_MATCH_V1.template_id, "polymarket_tennis_match_v2") == verdicts_for(KALSHI_TENNIS_MATCH_V1.template_id, "polymarket_tennis_match_v1")


def test_a_two_word_mascot_dropped_by_the_venue_still_hashes_to_the_cfb_template():
    """2026-09-05: Polymarket wrote "Kent State" for "Kent State Golden Flashes"; only one-word heads
    were stripped, the text (identical to V1) hashed elsewhere, and KENT @ SC blocked at
    TEMPLATE_UNKNOWN. Every multi-word head of a participant name is stripped."""
    from nodes.settle_wedge.policy import POLYMARKET_CFB_GAME_V1
    text = (POLYMARKET_CFB_GAME_V1.sample_text.replace("August 27 at 8:00PM ET", "September 5 at 12:45PM ET")
            .replace("Louisiana Christian", "Kent State").replace("Northwestern State", "South Carolina"))
    p = harvest_polymarket({"slug": "cfb-kentst-sc-2026-09-05", "description": text},
                           participants=("Golden Flashes", "Kent St.", "Kent State Golden Flashes", "South Carolina", "South Carolina Gamecocks"),
                           retrieved_at=T)
    assert p.template_hash == POLYMARKET_CFB_GAME_V1.template_hash, p.template_text

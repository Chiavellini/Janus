#!/usr/bin/env python3
"""Unknown is a block; bounded is priced; the templates are the ones we read."""
from __future__ import annotations

from pathlib import Path

import pytest

from nodes.rules_exhaustive.rules import prove
from nodes.settle_wedge.equivalence import (CoverProof, NotEquivalent, SettlementEquivalence, certify,
                                            certify_cover)
from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket, normalise_template
from nodes.settle_wedge.policy import KALSHI_MLB_GAME_V1, POLYMARKET_MLB_GAME_V1
from nodes.settle_wedge.records import record_equivalence, record_rules
from nodes.store_tuples.store import TupleStore

T = 1_800_000_000.0
#: Verbatim from the APIs on 2026-09-02 (KXMLBGAME-26SEP022210STLLAD-STL, mlb-stl-lad-2026-09-02).
K_MARKET = {
    "ticker": "KXMLBGAME-26SEP022210STLLAD-STL",
    "rules_primary": "If St. Louis wins the St. Louis vs Los Angeles D professional baseball game "
                     "originally scheduled for Sep 2, 2026 at 10:10 PM EDT, then the market resolves to Yes.",
    "rules_secondary": "The following market refers to the St. Louis vs Los Angeles D professional baseball "
                       "game originally scheduled for Sep 2, 2026 at 10:10 PM EDT. If this game is postponed "
                       "or delayed, the market will remain open and close after the rescheduled game has "
                       "finished (within two days). If the game is cancelled or rescheduled to over two days "
                       "away, the market will resolve to a fair price in accordance with the rules.\n\n"
                       "Kalshi is not affiliated, associated, authorized, endorsed by, or in any way officially "
                       "connected with the Governing League. All trademarks, logos, and brand names are the "
                       "property of their respective owners."}
K_SERIES = {"series": {"ticker": "KXMLBGAME", "settlement_sources": [{"name": "ESPN"}, {"name": "Fox Sports"},
                                                                     {"name": "the Governing League"}],
                       "contract_url": "https://kalshi.com/c/KXMLBGAME"}}
PM_MARKET = {
    "slug": "mlb-stl-lad-2026-09-02", "resolutionSource": "https://www.mlb.com/",
    "description": "In the upcoming MLB game between the St. Louis Cardinals and Los Angeles Dodgers, "
                   "scheduled for September 2 at 10:10PM ET:\n\nThis market will resolve to \"St. Louis "
                   "Cardinals\" if the St. Louis Cardinals win the game.\n\nThis market will resolve to \"Los "
                   "Angeles Dodgers\" if the Los Angeles Dodgers win the game.\n\nIf the game is postponed, "
                   "this market will remain open until the game has been completed. If the game is canceled "
                   "entirely, with no make-up game, or ends in a tie, this market will resolve 50-50.\n\nThe "
                   "primary resolution source for this market is the official final statistics of the event "
                   "as recognized by the governing body or event organizers. However, if the governing body "
                   "or event organizers have not published final match statistics within 24 hours after the "
                   "event's conclusion, a consensus of credible reporting may be used instead."}
NAMES = ["St. Louis", "Los Angeles D", "St. Louis Cardinals", "Los Angeles Dodgers"]
RATES = {"mlb.cancelled_rate": 0.002, "mlb.postponed_gt2d_rate": 0.01}


def records():
    return (harvest_kalshi(K_MARKET, participants=NAMES, retrieved_at=T, series=K_SERIES),
            harvest_polymarket(PM_MARKET, participants=NAMES, retrieved_at=T))


def test_the_verbatim_texts_hash_to_the_reviewed_templates():
    k, p = records()
    assert k.template_hash == KALSHI_MLB_GAME_V1.template_hash, k.template_text
    assert p.template_hash == POLYMARKET_MLB_GAME_V1.template_hash, p.template_text
    assert k.settlement_sources == ("ESPN", "Fox Sports", "the Governing League")
    assert p.source_url == "https://www.mlb.com/" and k.rules_hash != k.template_hash


def test_another_game_of_the_same_league_shares_the_template():
    other = {**K_MARKET, "ticker": "KXMLBGAME-26SEP031235SFPIT-SF",
             "rules_primary": K_MARKET["rules_primary"].replace("St. Louis", "San Francisco").replace(
                 "Los Angeles D", "Pittsburgh").replace("Sep 2, 2026 at 10:10 PM EDT", "Sep 3, 2026 at 12:35 PM EDT"),
             "rules_secondary": K_MARKET["rules_secondary"].replace("St. Louis", "San Francisco").replace(
                 "Los Angeles D", "Pittsburgh").replace("Sep 2, 2026 at 10:10 PM EDT", "Sep 3, 2026 at 12:35 PM EDT")}
    r = harvest_kalshi(other, participants=["San Francisco", "Pittsburgh"], retrieved_at=T)
    assert r.template_hash == KALSHI_MLB_GAME_V1.template_hash
    assert r.rules_hash != records()[0].rules_hash


def test_a_reworded_template_blocks_as_unknown():
    k, p = records()
    p2 = harvest_polymarket({**PM_MARKET, "description": PM_MARKET["description"].replace("50-50", "at the last traded price")},
                            participants=NAMES, retrieved_at=T)
    got = certify(k, p2, league="mlb", rates=RATES)
    assert isinstance(got, NotEquivalent) and got.code == "TEMPLATE_UNKNOWN" and got.context["venue"] == "polymarket"


def test_bounded_dimensions_block_until_their_rate_is_measured(monkeypatch):
    from nodes.settle_wedge import evidence
    monkeypatch.setattr(evidence, "EVIDENCE", {})              # before L26 measured anything
    k, p = records()
    got = certify(k, p, league="mlb")
    assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED"
    assert got.context["evidence_key"] in RATES


def test_a_wrong_league_for_a_known_template_blocks():
    k, p = records()
    got = certify(k, p, league="nfl", rates=RATES)
    assert isinstance(got, NotEquivalent) and got.code == "LEAGUE_MISMATCH"


def test_with_measured_rates_mlb_certifies_and_the_buffer_charges_the_pm_favourite():
    k, p = records()
    eq = certify(k, p, league="mlb", rates=RATES)
    assert isinstance(eq, SettlementEquivalence)
    assert {v.dimension for v in eq.verdicts} == {"official_source", "winner_determination", "overtime", "tie",
                                                    "postponement", "cancellation", "suspended", "abandoned",
                                                    "player_non_participation", "retirement", "dispute_revision",
                                                    "settlement_timing"}
    # PM leg at 0.70: cancellation 0.002*(0.70-0.50) + (postponed+suspended) 2*0.01*0.70
    assert eq.settlement_buffer([("kalshi", 0.28), ("polymarket", 0.70)]) == pytest.approx(0.002 * 0.2 + 0.02 * 0.70)
    # PM leg the longshot: only the late-makeup term bites
    assert eq.settlement_buffer([("kalshi", 0.72), ("polymarket", 0.26)]) == pytest.approx(0.02 * 0.26)
    assert eq.settlement_buffer([("kalshi", 0.5), ("kalshi", 0.5)]) == 0.0


def test_the_token_cannot_be_forged_and_the_cover_proof_checks_the_key():
    k, p = records()
    eq = certify(k, p, league="mlb", rates=RATES)
    with pytest.raises(TypeError):
        SettlementEquivalence("mlb", "moneyline", "game", "kalshi", "polymarket", "a", "b", "h", "h", (), {})
    with pytest.raises(TypeError):
        CoverProof(prove("mlb", "moneyline", "game", ["a", "b"]), eq)
    proof = certify_cover(prove("mlb", "moneyline", "game", ["a", "b"]), eq)
    assert isinstance(proof, CoverProof)
    bad = certify_cover(prove("nba", "moneyline", "game", ["a", "b"]), eq)
    assert isinstance(bad, NotEquivalent) and bad.code == "LEAGUE_MISMATCH"
    assert certify_cover(True, eq).code == "PROOF_MISSING"


def test_records_are_append_on_change_and_keep_the_text(tmp_path: Path, monkeypatch):
    from nodes.settle_wedge import evidence
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    k, p = records()
    record_rules(store, k); record_rules(store, p); record_rules(store, k)
    assert store.con.execute("SELECT COUNT(*) FROM settlement_records").fetchone()[0] == 2
    with monkeypatch.context() as m:
        m.setattr(evidence, "EVIDENCE", {})
        blocked = certify(k, p, league="mlb")
    record_equivalence(store, event_id="e", league="mlb", rec_a=k, rec_b=p, result=blocked, now=T)
    record_equivalence(store, event_id="e", league="mlb", rec_a=k, rec_b=p, result=blocked, now=T + 1)
    ok = certify(k, p, league="mlb", rates=RATES)
    record_equivalence(store, event_id="e", league="mlb", rec_a=k, rec_b=p, result=ok, now=T + 2)
    rows = store.con.execute("SELECT result, block_code, template_a FROM equivalence_records ORDER BY id").fetchall()
    assert rows == [("BLOCKED", "EVIDENCE_UNMEASURED", None), ("EQUIVALENT", None, "kalshi_mlb_game_v1")]
    store.close()


def test_normalisation_strips_what_varies_and_keeps_what_rules():
    s = normalise_template('If "St. Louis" wins on Sep 2, 2026 at 10:10 PM EDT (within two days).', ["St. Louis"])
    assert s == "if wins on at within two days"


def test_the_registry_carries_l26_and_mlb_certifies_from_it():
    """The measured rates: 10 of 2,100 games made up more than two days out, zero cancellations."""
    from nodes.settle_wedge.evidence import EVIDENCE
    assert EVIDENCE["mlb.postponed_gt2d_rate"].value == pytest.approx(10 / 2100, abs=1e-6)
    assert EVIDENCE["mlb.cancelled_rate"].value == 0.0
    assert all(e.research_ref.startswith("research/sports/2026-09-02_mlb-settlement-wedge-rates")
               for k, e in EVIDENCE.items() if k.startswith("mlb."))
    assert all(e.research_ref.startswith("research/sports/2026-09-03_nfl-settlement-wedge-rates-v2")
               for k, e in EVIDENCE.items() if k.startswith("nfl."))
    assert all(e.research_ref.startswith("research/sports/2026-09-03_soccer-settlement-wedge-rates")
               for k, e in EVIDENCE.items() if k.startswith("soccer."))
    assert EVIDENCE["tennis.walkover_rate"].research_ref.startswith("research/sports/2026-09-04_tennis-settlement-wedge-rates")
    assert {k.split(".")[0] for k in EVIDENCE} == {"mlb", "nfl", "soccer", "cfb", "tennis"}
    # F4 (2026-09-05): the delay rate is the forward row's UPPER BOUND, never a point estimate below n = 300
    d = EVIDENCE["tennis.delayed_gt7d_rate"]
    assert d.research_ref == "research/sports/2026-09-04_tennis-delay-forward/spec.yaml" and "UPPER BOUND" in d.note
    from nodes.watch_settle.settle import upper_bound_95
    assert upper_bound_95(0, 42) == pytest.approx(3 / 42) and upper_bound_95(0, 0) is None
    assert 0.0 < upper_bound_95(1, 100) < 0.05 and upper_bound_95(50, 100) > 0.5
    assert d.n >= 42 and d.value <= round(3 / 42, 6) + 1e-9 and d.value >= 0.0   # the bound shrinks as n grows
    assert all(e.research_ref.startswith("research/sports/2026-09-03_cfb-settlement-wedge-rates") for k, e in EVIDENCE.items() if k.startswith("cfb."))
    assert all("FLOOR" in e.note for k, e in EVIDENCE.items() if k.startswith("soccer.") and k.endswith("postponed_gt48h_rate"))
    k, p = records()
    eq = certify(k, p, league="mlb")
    assert isinstance(eq, SettlementEquivalence)
    # at the measured rates a 0.70 Polymarket favourite reserves ~0.67c/contract
    assert eq.settlement_buffer([("kalshi", 0.30), ("polymarket", 0.70)]) == pytest.approx(2 * (10 / 2100) * 0.70, abs=1e-6)


def test_the_nfl_templates_hash_from_their_samples_and_nicknames_are_stripped():
    from nodes.settle_wedge.policy import KALSHI_NFL_GAME_V1, POLYMARKET_NFL_GAME_V1
    other = harvest_polymarket({"slug": "nfl-sf-la-2026-09-11", "description":
                                "In the upcoming NFL game, scheduled for September 10 at 8:35PM ET:\nIf 49ers wins, the market "
                                "will resolve to \"49ers\".\nIf Rams wins, the market will resolve to \"Rams\".\nIf the game is "
                                "postponed, this market will remain open until the game has been completed.\nIf the game is "
                                "canceled entirely or ends in a tie, with no make-up game, this market will resolve 50-50."},
                               participants=["San Francisco 49ers", "Los Angeles Rams"], retrieved_at=T)
    assert other.template_hash == POLYMARKET_NFL_GAME_V1.template_hash, other.template_text
    k = harvest_kalshi({"ticker": "KXNFLGAME-26SEP10SFLAR-LAR",
                        "rules_primary": "If Los Angeles R wins the San Francisco vs Los Angeles R professional football game originally scheduled for Sep 10, 2026, then the market resolves to Yes.",
                        "rules_secondary": KALSHI_NFL_GAME_V1.sample_text.split("\n", 1)[1].replace("New England", "San Francisco").replace("Seattle", "Los Angeles R").replace("Sep 9", "Sep 10")},
                       participants=["San Francisco", "Los Angeles R"], retrieved_at=T)
    assert k.template_hash == KALSHI_NFL_GAME_V1.template_hash, k.template_text


def test_nfl_blocks_on_unmeasured_evidence_not_on_an_unknown_template():
    from nodes.settle_wedge.policy import KALSHI_NFL_GAME_V1, POLYMARKET_NFL_GAME_V1
    k = harvest_kalshi({"ticker": "t", "rules_primary": KALSHI_NFL_GAME_V1.sample_text.split("\n")[0],
                        "rules_secondary": KALSHI_NFL_GAME_V1.sample_text.split("\n", 1)[1]},
                       participants=KALSHI_NFL_GAME_V1.sample_participants, retrieved_at=T)
    p = harvest_polymarket({"slug": "s", "description": POLYMARKET_NFL_GAME_V1.sample_text},
                           participants=POLYMARKET_NFL_GAME_V1.sample_participants, retrieved_at=T)
    from nodes.settle_wedge import evidence
    saved = dict(evidence.EVIDENCE)
    try:
        evidence.EVIDENCE.clear()                  # the world before L30: the templates match, the rates do not exist
        got = certify(k, p, league="nfl")
        assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED" and got.context["evidence_key"].startswith("nfl.")
    finally:
        evidence.EVIDENCE.update(saved)
    # the registry (L30): 4 of 2,640 games moved more than 48 h, 1 cancelled
    live = certify(k, p, league="nfl")
    assert isinstance(live, SettlementEquivalence)
    assert live.settlement_buffer([("kalshi", 0.30), ("polymarket", 0.70)]) == pytest.approx(
        2 * (4 / 2640) * 0.70 + (1 / 2640) * 0.20, abs=1e-6)
    eq = certify(k, p, league="nfl", rates={"nfl.postponed_gt48h_rate": 0.001, "nfl.cancelled_rate": 0.0005})
    assert isinstance(eq, SettlementEquivalence)
    assert {v.dimension: v.outcome for v in eq.verdicts}["tie"] == "SAME", "both venues pay $0.50 a side: a full $1 cover"
    assert isinstance(certify_cover(prove("nfl", "moneyline", "game", ["a", "b"]), eq), CoverProof)


def test_a_generic_one_word_tail_of_a_school_name_is_not_stripped_from_the_rules_text():
    """"Boston College" stripped "college" out of "college football game" (2026-09-05, BC @ CIN
    blocked at TEMPLATE_UNKNOWN); the two-word tail "golden flashes" of "Kent State Golden Flashes"
    is still a name."""
    text = "If Boston College wins the Boston College vs Cincinnati college football game, then Yes."
    assert normalise_template(text, ("Boston College", "Cincinnati")) == "if wins the vs college football game then yes"
    text2 = "If the Golden Flashes win the Kent State Golden Flashes vs Cincinnati college football game, then Yes."
    assert normalise_template(text2, ("Kent State Golden Flashes", "Cincinnati")) == "if the win the vs college football game then yes"


def test_every_template_hash_is_unique_and_the_tennis_texts_land_where_reviewed():
    """2026-09-07: an ITF Polymarket template normalised to the tour's V2 string; the later entry
    displaced the earlier in TEMPLATES and every ATP/WTA match blocked LEAGUE_MISMATCH."""
    from nodes.settle_wedge import policy as P
    objs = [v for v in vars(P).values() if isinstance(v, P.Template)]
    assert len({t.template_hash for t in objs}) == len(objs) == len(P.TEMPLATES)
    assert {"atp", "wta", "itf"} <= P.POLYMARKET_TENNIS_MATCH_V2.leagues
    assert {"atp", "wta", "itf"} <= P.KALSHI_ITF_MATCH_V1.leagues
    text = ("If Denisa Zoldakova wins the Zoldakova vs Noha Akugue professional tennis match in the 2026 WTA 125K Montreux "
            "Round Of 32 after a ball has been played, then the market resolves to Yes.\nThe following market refers to the "
            "Zoldakova vs Noha Akugue professional tennis match in the 2026 WTA 125K Montreux Round Of 32 after a ball has been "
            "played. If the match does not occur (signaled by a ball being played) due to a player injury, walkover, forfeiture, "
            "or any other cancellation (all before the match starts), the market will resolve to a fair price in accordance with "
            "the rules. If this match is postponed or delayed, the market will remain open and close after the rescheduled match "
            "has finished (within two weeks).\n\nKalshi is not affiliated, associated, authorized, endorsed by, or in any way "
            "officially connected with the Governing League. All trademarks, logos, and brand names are the property of their "
            "respective owners.")
    assert normalise_template(text, ("Denisa Zoldakova", "Noha Akugue"), P.TENNIS_SCRUB) == P.KALSHI_TENNIS_MATCH_V1.template_text

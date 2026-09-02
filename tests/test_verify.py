#!/usr/bin/env python3
"""Regression tests for match/verify.py — the cross-venue equivalence stage.

Every case here is a REAL pair observed in the 2026-08-20 crawl or the 2026-07-25 mentions corpus,
not a synthetic example. Two of them are bugs this file caught during development and must never
come back: the trigger extractor firing on non-utterance markets, and `archetype == "other"` (a
no-match sentinel) being treated as evidence that two markets differ.
"""

from __future__ import annotations

from pathlib import Path


from match.verify import (  # noqa: E402
    classify, extract_triggers, no_shared_subject, qualifier_mismatch, strike_mismatch,
    subject_mismatch, superlative_mismatch, trigger_relation,
)


def cand(**kw):
    base = {"kalshi_ticker": "K", "pm_condition_id": "P", "kalshi_text": "", "pm_text": "",
            "kalshi_archetype": "other", "pm_archetype": "other", "archetype_match": True,
            "jaccard": 0.5, "channels": ["entity"], "days_apart": 0.0,
            # a distinctive shared token by default; no_shared_subject() is exercised explicitly
            # in its own tests rather than incidentally here
            "shared_tokens": ["subject"]}
    base.update(kw)
    return base


def krow(**kw):
    base = {"rules_primary": "Resolves per the official release.", "category": "Economics",
            "series": "KXISM", "title": "t", "event_title": "e"}
    base.update(kw)
    return base


def prow(**kw):
    base = {"description": "Resolves per the official release.", "question": "q"}
    base.update(kw)
    return base


# ── the AI superset case (2026-07-25 mentions corpus: 275 Kalshi vs 83 PM markets) ──────────
def test_trigger_superset_is_rejected():
    k = extract_triggers("AI / Artificial Intelligence")
    p = extract_triggers('Will Kamala say "Artificial Intelligence" at debate?')
    assert k == {"ai", "artificial intelligence"}
    assert p == {"artificial intelligence"}
    assert trigger_relation(k, p) == "K_SUPERSET"


def test_ai_superset_pair_rejected_end_to_end():
    v = classify(
        cand(kalshi_text="What will Bernie Sanders say during the rally?",
             pm_text='Will Bernie Sanders say "Artificial Intelligence" during the rally?'),
        krow(category="Mentions", series="KXMENTION", term="AI / Artificial Intelligence",
             rules_primary="Resolves YES if the speaker says AI or Artificial Intelligence."),
        prow(description="Resolves YES if he says artificial intelligence."))
    assert v["verdict"] == "NOT_EQUIVALENT"
    assert v["reason"] == "TRIGGER_SET_ASYMMETRY"


# ── BUG: the trigger extractor used to run on every market and invent disjoint sets ─────────
def test_trigger_check_does_not_fire_on_non_utterance_markets():
    """1,350 false rejects before this gate: an ISM PMI pair "differed" because one side yielded
    the trigger 'the manufacturing pmi registered 527 percent'."""
    v = classify(
        cand(kalshi_text="ISM Manufacturing PMI in Aug 2026? At least 59",
             pm_text="Will ISM Manufacturing PMI be at least 59.0?"),
        krow(floor_strike=59, strike_type="greater_or_equal",
             rules_primary="The manufacturing PMI registered 52.7 percent."),
        prow(description="Resolves to the ISM release."))
    assert v["reason"] != "TRIGGER_SETS_DISJOINT"
    assert v["verdict"] == "UNDECIDED"


# ── the ISM threshold ladder: eight Kalshi rungs blocked to one PM market ───────────────────
def test_strike_ladder_cross_rung_rejected():
    hit = strike_mismatch({"floor_strike": 52, "strike_type": "greater_or_equal"},
                          "Will ISM Manufacturing PMI be at least 59.0?")
    assert hit and hit[0] == "STRIKE_MISMATCH"


def test_strike_ladder_matching_rung_survives():
    assert strike_mismatch({"floor_strike": 59, "strike_type": "greater_or_equal"},
                           "Will ISM Manufacturing PMI be at least 59.0?") is None


def test_strike_direction_mismatch():
    hit = strike_mismatch({"floor_strike": 65, "strike_type": "greater"},
                          "Will WTI settle below 65 dollars?")
    assert hit and hit[0] == "STRIKE_DIRECTION_MISMATCH"


# ── the Insidious / Mutiny case: number matches, film does not ──────────────────────────────
def test_subject_mismatch_rejected():
    hit = subject_mismatch("Insidious: Out of the Further - Rotten Tomatoes score, at least 60",
                           '"Mutiny" Rotten Tomatoes Score? Will "Mutiny" score at least 60?')
    assert hit and hit[0] == "SUBJECT_MISMATCH"


def test_same_subject_survives():
    assert subject_mismatch(
        "Insidious: Out of the Further - Rotten Tomatoes score, at least 60",
        '"Insidious: Out of the Further" score at least 60 on the Tomatometer?') is None


def test_superlative_vs_threshold_rejected():
    hit = superlative_mismatch("Insidious vs Mutiny: Highest Rotten Tomatoes Score",
                               'Will "Mutiny" score at least 60 on the Tomatometer?')
    assert hit and hit[0] == "SUPERLATIVE_VS_THRESHOLD"


# ── the Netflix ranking case ────────────────────────────────────────────────────────────────
def test_rank_qualifier_mismatch():
    hit = qualifier_mismatch("#2 US Netflix Show this week?",
                             "What will be the top US Netflix show this week?")
    assert hit and hit[0] == "QUALIFIER_MISMATCH" and hit[1]["field"] == "rank"


def test_region_qualifier_mismatch():
    hit = qualifier_mismatch("#2 US Netflix Show this week?",
                             "What will be the #2 global Netflix show this week?")
    assert hit and hit[0] == "QUALIFIER_MISMATCH" and hit[1]["field"] == "region"


# ── BUG: "other" is a no-match sentinel, not evidence of difference ─────────────────────────
def test_archetype_other_sentinel_does_not_reject():
    """Kalshi's "How many launches will SpaceX have in August" reads `threshold_price`; PM's "Will
    SpaceX have 16+ launches in August" reads `other`. Same contract. Rejecting on the sentinel
    discarded real pairs, and nothing downstream can recover a pair the verifier throws away."""
    v = classify(
        cand(kalshi_text="How many launches will SpaceX have in August? 16 or more",
             pm_text="Will SpaceX have 16+ launches in August 2026?",
             kalshi_archetype="threshold_price", pm_archetype="other", archetype_match=False),
        krow(floor_strike=16, strike_type="greater_or_equal", category="Science and Technology"),
        prow())
    assert v["verdict"] == "UNDECIDED", v


def test_archetype_both_classified_and_differing_is_rejected():
    v = classify(
        cand(kalshi_archetype="winner", pm_archetype="over_under", archetype_match=False),
        krow(), prow())
    assert v["verdict"] == "NOT_EQUIVALENT" and v["reason"] == "ARCHETYPE_MISMATCH"


# ── structural guards ───────────────────────────────────────────────────────────────────────
def test_unrendered_placeholder_rejected():
    """L21 found "is above ||Price||" live on a market carrying 324,239 OI."""
    v = classify(cand(), krow(rules_primary="Resolves YES if the price is above ||Price||."), prow())
    assert v["verdict"] == "NOT_EQUIVALENT" and v["reason"] == "UNRENDERED_RULES_PLACEHOLDER"


def test_resolution_date_mismatch_rejected():
    v = classify(cand(days_apart=9.0), krow(), prow())
    assert v["verdict"] == "NOT_EQUIVALENT" and v["reason"] == "RESOLUTION_DATE_MISMATCH"


def test_missing_catalog_row_is_undecided_not_equivalent():
    """A pair we cannot look up is never silently dropped and never silently accepted."""
    v = classify(cand(), None, prow())
    assert v["verdict"] == "UNDECIDED" and v["reason"] == "CATALOG_ROW_MISSING"


# ── numeric-collision family: found by hand-adjudicating 22 survivors (18 were false) ───────
def test_no_shared_subject_rejects_numeric_collisions():
    """Real, observed pairs. Each shares a number and a date and nothing else."""
    for shared in (["$290", "above", "august"], ["2026"], ["2026", "21"]):
        hit = no_shared_subject({"shared_tokens": shared})
        assert hit and hit[0] == "NO_SHARED_SUBJECT", shared


def test_no_shared_subject_keeps_real_pairs():
    """The two pairs from that same sample that WERE equivalent."""
    for shared in (["boys", "global", "life", "netflix", "season", "walter"],
                   ["banks", "global", "netflix", "outer", "season", "show"]):
        assert no_shared_subject({"shared_tokens": shared}) is None, shared


def test_shared_surname_survives_for_adjudication():
    """Warren Buffett net worth vs "Trump praises Warren Buffett" shares the SUBJECT but differs in
    predicate. Necessary-not-sufficient: it must reach the adjudicator, not be dropped here."""
    assert no_shared_subject({"shared_tokens": ["august", "buffett", "warren"]}) is None

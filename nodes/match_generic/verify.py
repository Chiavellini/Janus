#!/usr/bin/env python3
"""Stage 3 — cross-venue EQUIVALENCE. Decides whether a blocked candidate is the same product.

    python3 -m nodes.match_generic.verify.py --catalog data/catalog_2026-08-20 --candidates data/match/candidates.json

WHY THIS FILE EXISTS. `nodes/match_generic/block.py:7` and `nodes/match_generic/screen.py (not ported: it read prices):10` both document the pipeline as
`block -> ECONOMIC SCREEN -> LLM equivalence verify -> trade`, and this stage was never written.
Blocking is deliberately recall-optimised ("expected, even, to emit garbage") and had no adjudicator,
so candidates could never be promoted to pairs. Phase 1's central negative rested on n=35 title-matched
pairs against a universe of 95,852 Kalshi / 179,863 Polymarket markets — AGENTS.md already concedes
that is "a matcher limit, not a venue fact". This file is that limit.

NO PRICES ARE READ HERE. Equivalence is a property of the two RULES TEXTS, not of the quotes. Reading
prices while deciding equivalence is how a matcher gets tuned toward whichever pairing shows an edge.
`screen.py` runs after this, on the survivors.

THE FAILURE MODE THIS IS BUILT TO CATCH
───────────────────────────────────────
The sacred rule in AGENTS.md is "never compare two prices without first measuring the basis between
their settlement references, regardless of venue." An unmeasured basis is a BLOCK, not zero. The
subtle version is not a different question — it is the SAME question with a different TRIGGER SET.
Measured on the 2026-07-25 mentions corpus:

    Kalshi  term "AI / Artificial Intelligence"  (EITHER utterance triggers)   275 markets
    PM      term "AI"                            (that string alone)            83 markets

Kalshi's condition is a strict SUPERSET of Polymarket's, so the Kalshi contract is worth strictly
more, forever, with no arbitrage in it. Person, event and topic all match, so every title-similarity
matcher pairs them happily and reports a large, persistent, one-directional "edge". That is the
`+97.94c golfer vs cyclist` failure mode (state.yaml:184) wearing a better disguise, and a
subset/superset relation is therefore a HARD REJECT, never a scored penalty.

DETERMINISTIC FIRST, MODEL ONLY FOR THE REMAINDER
─────────────────────────────────────────────────
Every rejection this file can make from structure is made deterministically and is auditable, per the
house rule that "a missing pair means an alias-table hole -- fix it deterministically and auditably"
(state.yaml:183). Only genuinely ambiguous pairs reach the model, and they are written to
`undecided.jsonl` rather than being silently dropped or silently accepted. UNDECIDED is a real
verdict here: it is never folded into either bucket.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

#: Two markets whose resolution instants differ by more than this are not the same contract.
#: Deliberately loose: the venues stamp close times differently (Kalshi `close_time` is the trading
#: halt, PM `endDate` is often the calendar day), so a tight bound would cut real pairs. The residual
#: date risk is handed to the model, not silently accepted.
MAX_DAYS_APART = 1.5

#: Splitters for a trigger set written as alternatives: "AI / Artificial Intelligence",
#: "Elon, Musk, or Elon Musk", "Zuckerberg or Zuck".
_ALT_SPLIT = re.compile(r"\s*(?:/|\bor\b|,)\s*", re.I)
_QUOTED = re.compile(r"[\"“”']([^\"“”']{2,60})[\"“”']")


def _norm_trigger(s: str) -> str:
    """Casefold and strip punctuation that venues disagree about. 'A.I.' and 'AI' are one trigger."""
    s = (s or "").strip().lower()
    s = re.sub(r"[.’']", "", s)
    return " ".join(s.split())


def extract_triggers(*texts: str) -> set[str]:
    """The set of utterances that would resolve this market YES, as far as the text states it.

    Prefers explicitly QUOTED strings, which is how Polymarket writes the trigger ("Will Trump say
    \"Elon Musk\"..."). Falls back to alternative-splitting, which is how Kalshi writes it in the
    structured `term` / `custom_strike.Word` field ("AI / Artificial Intelligence").
    """
    out: set[str] = set()
    for t in texts:
        if not t:
            continue
        quoted = _QUOTED.findall(t)
        if quoted:
            for q in quoted:
                for part in _ALT_SPLIT.split(q):
                    if (n := _norm_trigger(part)):
                        out.add(n)
            continue
        for part in _ALT_SPLIT.split(t):
            if (n := _norm_trigger(part)) and len(n) <= 60:
                out.add(n)
    return out


def trigger_relation(k: set[str], p: set[str]) -> str:
    """EQUAL / K_SUPERSET / P_SUPERSET / DISJOINT / OVERLAP / UNKNOWN."""
    if not k or not p:
        return "UNKNOWN"
    if k == p:
        return "EQUAL"
    if k > p:
        return "K_SUPERSET"
    if p > k:
        return "P_SUPERSET"
    if not (k & p):
        return "DISJOINT"
    return "OVERLAP"


def k_rules(row: dict) -> str:
    return " ".join(str(x) for x in (row.get("rules_primary"), row.get("rules_secondary")) if x)


def p_rules(row: dict) -> str:
    return " ".join(str(x) for x in (row.get("description"), row.get("resolution_source")) if x)


#: Tokens that carry no SUBJECT information. Two markets sharing only these share nothing.
#:
#: Derived from hand-adjudicating 22 survivors of the deterministic layer on 2026-08-20, of which 18
#: were false. The dominant residual failure mode was a pure NUMERIC COLLISION between unrelated
#: subjects, and it is unmistakable in the shared-token lists:
#:
#:   Larry Page net worth > $290B  vs  Amazon closes above $290   -> shared ['$290','above','august']
#:   Phoenix max temp > 115F       vs  Elon Musk 115-139 tweets   -> shared ['2026']
#:   Austin min temp > 79F         vs  Zelenskyy 60-79 posts      -> shared ['2026']
#:
#: against the two pairs that were genuinely equivalent:
#:
#:   My Life With the Walter Boys  -> shared ['boys','global','life','netflix','season','walter']
#:   Outer Banks: Season 5         -> shared ['banks','global','netflix','outer','season','show']
#:
#: A real pair shares its SUBJECT; a collision shares a date and a number. block.py's numeric channel
#: deliberately bypasses the jaccard floor to protect recall, which is correct there -- the filter
#: belongs here instead.
GENERIC_TOKENS = set("""
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
above below over under between reach hit exceed close closes closing price prices
week weekly month monthly day daily date year end ending final total number
billion billions million millions trillion thousand bn per hour hourly average
""".split())
_PURE_NUM = re.compile(r"^[\$€£]?[\d,.]+%?$")


def no_shared_subject(cand: dict) -> tuple[str, dict] | None:
    """Reject when the only tokens the two markets share are dates, numbers and prepositions."""
    shared = cand.get("shared_tokens") or []
    distinctive = [t for t in shared
                   if t not in GENERIC_TOKENS and not _PURE_NUM.match(t) and len(t) > 2]
    if distinctive:
        return None
    return "NO_SHARED_SUBJECT", {"shared_tokens": shared[:6]}


#: PRICE/DATA-FEED settlement authorities, canonicalised so the two venues become comparable.
#:
#: This is the sacred rule in AGENTS.md made machine-checkable: "never compare two prices without
#: first measuring the basis between their settlement references, regardless of venue. An unmeasured
#: basis is a BLOCK, not zero." Measured on the 2026-08-20 non-sports corpus, the venues genuinely
#: disagree on the reference for the SAME asset -- Polymarket resolves crypto off Chainlink (1,533
#: markets) and Pyth (425), while Kalshi's rules name Pyth (607), CF Benchmarks (324) and Coinbase
#: (248). A Kalshi contract on CF Benchmarks BRTI and a PM contract on a Chainlink TWAP are different
#: products however identically their titles read; L17 recorded the Kalshi-vs-BRTI basis as
#: "entirely unmeasured".
#:
#: Deliberately restricted to FEEDS. Kalshi's `settlement_sources` is usually a generic acceptable-
#: news list (Bloomberg / NYT / Reuters / AP) which carries no reference commitment, so comparing it
#: against Polymarket's specific source would reject good pairs on nothing.
FEED_AUTHORITIES = (
    ("chainlink", re.compile(r"chain\.link|chainlink", re.I)),
    ("pyth", re.compile(r"\bpyth\b|pythdata", re.I)),
    ("cf_benchmarks", re.compile(r"cf benchmarks|\bbrti\b|\bbrr\b", re.I)),
    ("coinbase", re.compile(r"\bcoinbase\b", re.I)),
    ("binance", re.compile(r"\bbinance\b", re.I)),
    ("cme", re.compile(r"\bcme\b|\bcomex\b|\bnymex\b", re.I)),
    ("nasdaq", re.compile(r"\bnasdaq\b", re.I)),
    ("sp_dji", re.compile(r"s&p dow jones|s&p 500|\bspx\b", re.I)),
)


def feed_authorities(*texts) -> set[str]:
    hay = " ".join(str(t) for t in texts if t)
    return {name for name, rx in FEED_AUTHORITIES if rx.search(hay)}


def settlement_source_mismatch(krow: dict, prow: dict) -> tuple[str, dict] | None:
    """Reject only when BOTH sides name a price feed and the feeds are disjoint."""
    k = feed_authorities(krow.get("rules_primary"), krow.get("rules_secondary"))
    p = feed_authorities(prow.get("resolution_source"), prow.get("description"))
    if not k or not p or (k & p):
        return None
    return "SETTLEMENT_SOURCE_MISMATCH", {"kalshi_feeds": sorted(k), "pm_feeds": sorted(p)}


#: An "utterance market" resolves on someone SAYING a specific string. Only there is a trigger set a
#: meaningful object; elsewhere the extractor just pulls prose fragments.
_SAY_RX = re.compile(r"\bsay\b|\bsays\b|\bsaid\b|\bmention\b|\bmentions\b|\butter", re.I)


def is_utterance_market(krow: dict) -> bool:
    if (krow.get("category") or "") == "Mentions":
        return True
    if "MENTION" in (krow.get("series") or "").upper():
        return True
    return bool(_SAY_RX.search(" ".join(str(x) for x in
                (krow.get("title"), krow.get("event_title"), krow.get("rules_primary")) if x)))


def is_utterance_market_pm(prow: dict, pm_text: str | None = None) -> bool:
    hay = " ".join(str(x) for x in (prow.get("question"), prow.get("event_title"),
                                    prow.get("description"), pm_text) if x)
    return bool(_SAY_RX.search(hay))


def k_trigger_text(row: dict) -> str:
    cs = row.get("custom_strike") or {}
    word = cs.get("Word") if isinstance(cs, dict) else None
    return " ".join(str(x) for x in (row.get("term"), word) if x)


#: An unrendered template placeholder in a live rules text. L21 found "is above ||Price||" on a market
#: carrying 324,239 OI. A market whose own rule did not render cannot be compared to anything.
_PLACEHOLDER = re.compile(r"\|\|[A-Za-z_]+\|\||\{\{[^}]+\}\}|\$\{[^}]+\}")

_NUM = re.compile(r"\d[\d,]*\.?\d*")
#: Strike equality tolerance. Venues round differently ("at least 59" vs "59.0"), but a genuine
#: threshold ladder steps by >= 1.0, so this separates rounding from a different rung.
STRIKE_TOL = 0.051

_ABOVE = re.compile(r"\bat least\b|\babove\b|\bover\b|\bmore than\b|\bgreater\b|\bexceed|\bhigher\b|\b\+\b", re.I)
_BELOW = re.compile(r"\bbelow\b|\bunder\b|\bless than\b|\bfewer\b|\blower\b|\bat most\b|\bbeneath\b", re.I)

#: Rank qualifiers. "#2 US Netflix Show" and "top US Netflix show" share nearly every token and are
#: different contracts; so do "#2 US" and "#2 global". Both were in the top-15 blocked candidates.
_RANK_HASH = re.compile(r"#\s*(\d{1,2})\b")
_RANK_TOP = re.compile(r"\btop\b|\bnumber one\b|\b#1\b", re.I)
_REGIONS = (("us", re.compile(r"\bus\b|\bu\.s\.|\bunited states\b|\bamerican\b", re.I)),
            ("global", re.compile(r"\bglobal\b|\bworldwide\b|\bworld\b", re.I)))


def all_numbers(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(text or ""):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def strike_mismatch(krow: dict, pm_text: str) -> tuple[str, dict] | None:
    """Kalshi states its threshold STRUCTURALLY; Polymarket states it in prose. Compare them.

    This is the dominant non-sports trap. Kalshi lists a full ladder on one event -- ISM PMI "At
    least 52" through "At least 59" are eight separate markets -- and blocking matched every rung to
    the single PM market at 59, because rung and target share every token but the number. Seven of
    those eight pairs are false and only the matching rung is real.
    """
    floor, cap = krow.get("floor_strike"), krow.get("cap_strike")
    st = (krow.get("strike_type") or "").lower()
    pnums = all_numbers(pm_text)
    if not pnums:
        return None

    def present(v):
        return any(abs(v - n) <= STRIKE_TOL for n in pnums)

    if st == "between" and floor is not None and cap is not None:
        if not (present(floor) and present(cap)):
            return "STRIKE_MISMATCH", {"kalshi_floor": floor, "kalshi_cap": cap,
                                       "pm_numbers": sorted(pnums)[:8], "strike_type": st}
        return None

    v = floor if floor is not None else cap
    if v is None:
        return None
    if not present(v):
        return "STRIKE_MISMATCH", {"kalshi_strike": v, "strike_type": st,
                                   "pm_numbers": sorted(pnums)[:8]}

    # Same number, opposite side of it, is a different contract -- and one that looks near-identical.
    if st.startswith("greater") and _BELOW.search(pm_text) and not _ABOVE.search(pm_text):
        return "STRIKE_DIRECTION_MISMATCH", {"kalshi_strike": v, "strike_type": st}
    if st == "less" and _ABOVE.search(pm_text) and not _BELOW.search(pm_text):
        return "STRIKE_DIRECTION_MISMATCH", {"kalshi_strike": v, "strike_type": st}
    return None


#: Polymarket names its subject in quotes -- `"Mutiny" Rotten Tomatoes Score?`. Kalshi puts it in the
#: title. If PM names a subject that appears nowhere in the Kalshi text, the two markets are about
#: different things however well their numbers line up.
def pm_quoted_subjects(pm_text: str) -> list[str]:
    return [_norm_trigger(q) for q in _QUOTED.findall(pm_text or "") if len(q.strip()) >= 3]


def subject_mismatch(k_text: str, p_text: str) -> tuple[str, dict] | None:
    subs = pm_quoted_subjects(p_text)
    if not subs:
        return None
    kn = _norm_trigger(k_text)
    if not kn:
        return None
    # A single shared subject is enough; PM quotes outcome labels too ("Yes"/"No"), which are short
    # and filtered above. Requiring ALL to match would reject legitimate multi-quote phrasings.
    if any(s and s in kn for s in subs):
        return None
    return "SUBJECT_MISMATCH", {"pm_subjects": subs[:4]}


#: "Which of these scores highest" is not "will this score at least 60", even about the same titles.
_SUPERLATIVE = re.compile(r"\bhighest\b|\blowest\b|\bmost\b|\bfewest\b|\bbest\b|\bworst\b|\bvs\.?\b", re.I)


def superlative_mismatch(k_text: str, p_text: str) -> tuple[str, dict] | None:
    k_sup, p_sup = bool(_SUPERLATIVE.search(k_text or "")), bool(_SUPERLATIVE.search(p_text or ""))
    if k_sup == p_sup:
        return None
    thresholded = _ABOVE.search(p_text if k_sup else k_text or "")
    if thresholded:
        return "SUPERLATIVE_VS_THRESHOLD", {"kalshi_superlative": k_sup, "pm_superlative": p_sup}
    return None


_PM_RANGE = re.compile(r"\bbetween\b\s*\$?[\d.,]+\s*(?:and|-|to)\s*\$?[\d.,]+", re.I)


def range_vs_threshold(krow: dict, p_text: str) -> tuple[str, dict] | None:
    """A bracket is not a one-sided threshold, even sharing an endpoint.

    Observed repeatedly in the GPU-price family: Kalshi "H100 compute above $2.75" against
    Polymarket "Ornn H100 Index between $2.75 and $3.00". They share the endpoint and diverge for
    every value above $3.00.
    """
    st = (krow.get("strike_type") or "").lower()
    if st in ("between", "") or not _PM_RANGE.search(p_text or ""):
        return None
    if st.startswith("greater") or st == "less":
        return "RANGE_VS_THRESHOLD", {"kalshi_strike_type": st}
    return None


def qualifiers(text: str) -> dict:
    """Rank and region, the two qualifiers that separate otherwise-identical ranking markets."""
    q = {}
    if (m := _RANK_HASH.search(text or "")):
        q["rank"] = int(m.group(1))
    elif _RANK_TOP.search(text or ""):
        q["rank"] = 1
    for name, rx in _REGIONS:
        if rx.search(text or ""):
            q["region"] = name
            break
    return q


def qualifier_mismatch(k_text: str, p_text: str) -> tuple[str, dict] | None:
    kq, pq = qualifiers(k_text), qualifiers(p_text)
    for field in ("rank", "region"):
        if field in kq and field in pq and kq[field] != pq[field]:
            return "QUALIFIER_MISMATCH", {"field": field, "kalshi": kq[field], "pm": pq[field]}
    return None


def classify(cand: dict, krow: dict | None, prow: dict | None) -> dict:
    """One verdict per candidate. Returns EQUIVALENT / NOT_EQUIVALENT / UNDECIDED plus a reason.

    EQUIVALENT is never returned by the deterministic layer alone — passing every structural check
    means "nothing here proves these differ", which is not the same as "these are the same product".
    That judgement needs both rules texts read in full, so it goes to the model.
    """
    v = {"kalshi_ticker": cand.get("kalshi_ticker"), "pm_condition_id": cand.get("pm_condition_id"),
         "kalshi_text": cand.get("kalshi_text"), "pm_text": cand.get("pm_text"),
         "jaccard": cand.get("jaccard"), "channels": cand.get("channels")}

    def out(verdict, reason, **extra):
        v.update({"verdict": verdict, "reason": reason, **extra})
        return v

    if krow is None or prow is None:
        return out("UNDECIDED", "CATALOG_ROW_MISSING")

    kr, pr = k_rules(krow), p_rules(prow)

    # An unrendered placeholder means the venue itself does not state the rule. Never comparable.
    if _PLACEHOLDER.search(kr) or _PLACEHOLDER.search(pr):
        return out("NOT_EQUIVALENT", "UNRENDERED_RULES_PLACEHOLDER")

    # A moneyline is not an over/under. But block.py's archetype is a regex over the TITLE, and
    # "other" is its no-match sentinel, not a claim about the product -- measured here, Kalshi's
    # "How many launches will SpaceX have in August" reads `threshold_price` while PM's "Will SpaceX
    # have 16+ launches in August" reads `other`, and those are the same contract. Rejecting on a
    # sentinel discards real pairs, which nothing downstream can recover. So this fires only when
    # BOTH sides were positively classified and disagree.
    ka, pa = cand.get("kalshi_archetype"), cand.get("pm_archetype")
    if ka != pa and "other" not in (ka, pa):
        return out("NOT_EQUIVALENT", "ARCHETYPE_MISMATCH", kalshi_archetype=ka, pm_archetype=pa)

    da = cand.get("days_apart")
    if da is not None and da > MAX_DAYS_APART:
        return out("NOT_EQUIVALENT", "RESOLUTION_DATE_MISMATCH", days_apart=round(da, 2))

    ptext = cand.get("pm_text") or ""
    ktext = cand.get("kalshi_text") or ""

    # On an utterance market the PM quoted string is the TRIGGER ("say \"Artificial Intelligence\""),
    # not the subject, and it will not appear verbatim in Kalshi's title -- which carries the speaker
    # and event instead. Running the subject check there rejects legitimate mention pairs and steals
    # the case from the trigger-set check below, which is the one that can tell superset from equal.
    utterance = is_utterance_market(krow) and is_utterance_market_pm(prow, ptext)

    # ── subject presence: kills the numeric-collision family ──────────────────────────────
    if (hit := no_shared_subject(cand)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── settlement reference: the sacred rule, machine-checked ────────────────────────────
    if (hit := settlement_source_mismatch(krow, prow)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── subject: the "Insidious" vs "Mutiny" case, where the NUMBER matches and the film does not ──
    if not utterance and (hit := subject_mismatch(ktext, ptext)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── "which scores highest" is not "will it score at least 60" ─────────────────────────
    if (hit := superlative_mismatch(ktext, ptext)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── the threshold-ladder check: the ISM PMI case ──────────────────────────────────────
    if (hit := strike_mismatch(krow, ptext)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── a bracket is not a one-sided threshold ────────────────────────────────────────────
    if (hit := range_vs_threshold(krow, ptext)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── rank / region: the Netflix "#2 US" vs "top global" case ───────────────────────────
    if (hit := qualifier_mismatch(ktext, ptext)):
        return out("NOT_EQUIVALENT", hit[0], **hit[1])

    # ── the trigger-set check: the AI / Artificial Intelligence case ──────────────────────
    # ONLY for utterance markets. A trigger set is meaningful when the contract resolves on someone
    # SAYING a specific string; run on anything else it extracts prose fragments and calls them
    # disjoint. Measured on this corpus before the gate was added: 1,350 false rejects, e.g. an ISM
    # PMI pair "rejected" because one side yielded 'the manufacturing pmi registered 527 percent'.
    rel = None
    if utterance:
        kt = extract_triggers(k_trigger_text(krow)) or extract_triggers(kr)
        pt = extract_triggers(cand.get("pm_text") or "") or extract_triggers(pr)
        rel = trigger_relation(kt, pt)
        if rel in ("K_SUPERSET", "P_SUPERSET"):
            return out("NOT_EQUIVALENT", "TRIGGER_SET_ASYMMETRY", relation=rel,
                       kalshi_triggers=sorted(kt), pm_triggers=sorted(pt))
        if rel == "DISJOINT":
            return out("NOT_EQUIVALENT", "TRIGGER_SETS_DISJOINT",
                       kalshi_triggers=sorted(kt), pm_triggers=sorted(pt))

    if not kr or not pr:
        return out("UNDECIDED", "RULES_TEXT_MISSING")

    return out("UNDECIDED", "NEEDS_RULES_ADJUDICATION", relation=rel,
               kalshi_rules=kr[:1200], pm_rules=pr[:1200],
               kalshi_settlement_sources=krow.get("settlement_sources"),
               pm_resolution_source=prow.get("resolution_source"))


def load_index(catalog: Path):
    K = json.loads((catalog / "kalshi_markets.json").read_text())
    P = json.loads((catalog / "pm_markets.json").read_text())
    return ({r["ticker"]: r for r in K if r.get("ticker")},
            {r["condition_id"]: r for r in P if r.get("condition_id")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog_2026-08-20")
    ap.add_argument("--candidates", default="data/match/candidates.json")
    ap.add_argument("--out-dir", default="data/match")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    cands = json.loads(Path(a.candidates).read_text())
    kidx, pidx = load_index(Path(a.catalog))
    print(f"candidates {len(cands)}   catalog: kalshi {len(kidx)}  pm {len(pidx)}")

    # ── reciprocal best-match ─────────────────────────────────────────────────────────────
    # A pair must be each other's TOP candidate. Free, and it removes the fan-out directly: the Fed
    # "Hike rates by 0bps" market alone was blocked against 8 different PM markets, of which at most
    # one can be the same contract. Ranked on jaccard, which blocking already computed; ties keep
    # both rather than picking arbitrarily.
    def best_of(key_fn, other_fn):
        top = {}
        for c, _v in passed:
            k, j = key_fn(c), c.get("jaccard") or 0.0
            if k not in top or j > top[k][0]:
                top[k] = (j, {other_fn(c)})
            elif abs(j - top[k][0]) < 1e-9:
                top[k][1].add(other_fn(c))
        return top

    # ORDER MATTERS: structural checks run FIRST, reciprocal-best chooses only among the pairs that
    # survived them. Ranking raw candidates on jaccard cannot separate ladder rungs -- "exactly 13"
    # and "exactly 14" share every token but the number -- so choosing first would sometimes discard
    # the correct rung in favour of a wrong one that happened to tie.
    verdicts, passed = [], []
    for c in cands:
        v = classify(c, kidx.get(c.get("kalshi_ticker")), pidx.get(c.get("pm_condition_id")))
        if v["verdict"] == "NOT_EQUIVALENT":
            verdicts.append(v)
        else:
            passed.append((c, v))

    k_best = best_of(lambda c: c.get("kalshi_ticker"), lambda c: c.get("pm_condition_id"))
    p_best = best_of(lambda c: c.get("pm_condition_id"), lambda c: c.get("kalshi_ticker"))

    survivors = []
    for c, v in passed:
        kt, pc = c.get("kalshi_ticker"), c.get("pm_condition_id")
        if pc not in k_best.get(kt, (0, set()))[1] or kt not in p_best.get(pc, (0, set()))[1]:
            verdicts.append(dict(v, verdict="NOT_EQUIVALENT", reason="NOT_RECIPROCAL_BEST"))
            continue
        verdicts.append(v)
        if v["verdict"] != "NOT_EQUIVALENT":
            # the ORIGINAL candidate record, quotes intact, so screen.py can price it unchanged
            survivors.append(dict(c, verify_reason=v["reason"]))

    by_v = Counter(v["verdict"] for v in verdicts)
    by_r = Counter(v["reason"] for v in verdicts)
    (out / "verdicts.json").write_text(json.dumps(verdicts, indent=1))
    (out / "verified_candidates.json").write_text(json.dumps(survivors, indent=1))
    undecided = [v for v in verdicts if v["verdict"] == "UNDECIDED"]
    with (out / "undecided.jsonl").open("w") as fh:
        for v in undecided:
            fh.write(json.dumps(v) + "\n")

    print("\nverdicts:", dict(by_v))
    print("\nreasons:")
    for r, n in by_r.most_common():
        print(f"  {n:7d}  {r}")
    print(f"\nwrote {out}/verdicts.json and {out}/undecided.jsonl ({len(undecided)} for adjudication)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

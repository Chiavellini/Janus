#!/usr/bin/env python3
"""Candidate generation: cheaply propose Kalshi<->Polymarket market pairs that MIGHT be the same.

    python3 -m nodes.match_generic.block.py --catalog data/catalog --out-dir data/match

This stage optimises RECALL, not precision. It is explicitly allowed — expected, even — to emit
garbage; the LLM verifier in nodes/match_generic/verify.py is what decides equivalence by reading both rules
texts. What blocking must never do is *miss* a real pair, because nothing downstream can recover it.

Two failures measured on 2026-07-24 define the design:

  * Token-jaccard over titles produced 1,602 candidates whose TOP hits were false — the same two
    teams matched across different questions (moneyline vs "O/U 183.5"). Title similarity cannot
    distinguish "who wins" from "how many goals". So blocking emits candidates but records
    STRUCTURAL features (question archetype, numbers, dates) for the verifier to adjudicate.
  * On politics/economics, token overlap found NOTHING — the venues phrase the same question far
    too differently ("Will the Federal Reserve Hike rates by 25bps at their July meeting?" vs a PM
    Fed market). So a second, orthogonal channel blocks on ENTITIES + DATES only, ignoring phrasing.

Channels (unioned, each tagged so a dead channel is visible):
  1. entity-overlap  — rare-token overlap, catches sports/teams/people
  2. entity+date     — shared proper nouns AND a shared resolution date, catches politics/econ
  3. numeric         — shared distinctive numbers (strikes, percentages, bps)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

STOP = set("""
will the be a an in on at to of for by and or is are was were do does did have has had
who what when which whether any before after more than less at least most next this that
market resolve resolves resolved yes no if it its their there then
""".split())

#: Question archetypes. Two markets in different archetypes are almost never the same product --
#: this is the feature that separates a moneyline from an over/under.
ARCHETYPES = [
    ("over_under", r"\bo/u\b|over/under|\bover\b.*\bunder\b|total .*(points|goals|runs)"),
    ("spread", r"\bspread\b|\bhandicap\b|\+\d+\.5|\-\d+\.5"),
    ("draw", r"\bdraw\b|\btie\b"),
    ("both_score", r"both teams to score|\bbtts\b"),
    ("exact_score", r"exact score"),
    ("threshold_price", r"\babove\b|\bbelow\b|\breach\b|\bhit\b|\$[\d,]+"),
    ("range", r"\bbetween\b|\brange\b"),
    ("timing", r"\bbefore\b|\bby\b \w+ \d|\bwhen will\b"),
    ("winner", r"\bwin\b|\bwins\b|\bwinner\b|\bbeat\b|\bvs\.?\b"),
]


def archetype(text: str) -> str:
    t = (text or "").lower()
    for name, pat in ARCHETYPES:
        if re.search(pat, t):
            return name
    return "other"


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9$%.\- ]", " ", s)
    return " ".join(s.split())


def tokens(s: str) -> set[str]:
    return {w for w in norm(s).split() if len(w) > 2 and w not in STOP}


def numbers(s: str) -> set[str]:
    """Distinctive numerals: strikes, percentages, bps. Bare small ints are too common to block on."""
    out = set()
    for m in re.findall(r"\$?\d[\d,]*\.?\d*%?", s or ""):
        v = m.replace(",", "").lstrip("$").rstrip("%")
        try:
            fv = float(v)
        except ValueError:
            continue
        if fv >= 10 or "." in v or "%" in m or "$" in m:
            out.add(v)
    return out


def day_key(ts) -> str | None:
    if not ts:
        return None
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d")


def k_text(r: dict) -> str:
    return " ".join(x for x in (r.get("event_title"), r.get("title"),
                                r.get("yes_sub_title"), r.get("sub_title")) if x)


def p_text(r: dict) -> str:
    return " ".join(x for x in (r.get("event_title"), r.get("question")) if x)


def load(catalog: Path, horizon_days: float):
    K = json.loads((catalog / "kalshi_markets.json").read_text())
    P = json.loads((catalog / "pm_markets.json").read_text())

    def short(rows, tradeable_key):
        return [r for r in rows
                if r.get("days_to_close") is not None
                and 0 <= r["days_to_close"] <= horizon_days
                and r.get(tradeable_key)]

    return short(K, "two_sided"), short(P, "two_sided")


def build(K, P):
    for r in K:
        t = k_text(r)
        r["_tok"], r["_num"], r["_arch"], r["_day"] = tokens(t), numbers(t), archetype(t), day_key(r.get("close_ts"))
    for r in P:
        t = p_text(r)
        r["_tok"], r["_num"], r["_arch"], r["_day"] = tokens(t), numbers(t), archetype(t), day_key(r.get("end_ts"))


def candidates(K, P, *, max_per_market: int = 12, min_jac: float = 0.25):
    tok_idx, day_idx, num_idx = defaultdict(list), defaultdict(list), defaultdict(list)
    for i, p in enumerate(P):
        for w in p["_tok"]:
            tok_idx[w].append(i)
        if p["_day"]:
            day_idx[p["_day"]].append(i)
        for n in p["_num"]:
            num_idx[n].append(i)
    df = {w: len(v) for w, v in tok_idx.items()}

    pairs = {}
    for ki, k in enumerate(K):
        score = Counter()
        chan = defaultdict(set)
        # ch1: rare-token overlap
        for w in k["_tok"]:
            if df.get(w, 0) > 300:
                continue
            for pi in tok_idx.get(w, ()):
                score[pi] += 1
                chan[pi].add("entity")
        # ch2: shared date x shared proper-noun-ish token (phrasing-independent)
        if k["_day"]:
            for pi in day_idx.get(k["_day"], ()):
                if k["_tok"] & P[pi]["_tok"]:
                    score[pi] += 1
                    chan[pi].add("entity_date")
        # ch3: distinctive numbers
        for n in k["_num"]:
            for pi in num_idx.get(n, ()):
                score[pi] += 1
                chan[pi].add("numeric")
        for pi, _ in score.most_common(max_per_market):
            p = P[pi]
            inter = k["_tok"] & p["_tok"]
            union = k["_tok"] | p["_tok"]
            jac = len(inter) / len(union) if union else 0.0
            if jac < min_jac and "entity_date" not in chan[pi] and "numeric" not in chan[pi]:
                continue
            key = (k["ticker"], p["condition_id"])
            if key in pairs and pairs[key]["jaccard"] >= jac:
                continue
            pairs[key] = {
                "kalshi_ticker": k["ticker"], "pm_condition_id": p["condition_id"],
                "kalshi_text": k_text(k), "pm_text": p_text(p),
                "kalshi_category": k.get("category"), "pm_tags": p.get("tags"),
                "kalshi_archetype": k["_arch"], "pm_archetype": p["_arch"],
                "archetype_match": k["_arch"] == p["_arch"],
                "jaccard": round(jac, 3),
                "shared_tokens": sorted(inter)[:12],
                "shared_numbers": sorted(k["_num"] & p["_num"])[:6],
                "kalshi_close": k.get("close_time"), "pm_close": p.get("end_date"),
                "same_day": k["_day"] == p["_day"] and k["_day"] is not None,
                "days_apart": (abs(k["close_ts"] - p["end_ts"]) / 86400.0
                               if k.get("close_ts") and p.get("end_ts") else None),
                "channels": sorted(chan[pi]),
                "kalshi_yes_bid": k.get("yes_bid"), "kalshi_yes_ask": k.get("yes_ask"),
                "pm_best_bid": p.get("best_bid"), "pm_best_ask": p.get("best_ask"),
                "pm_liquidity": p.get("liquidity"), "kalshi_volume": k.get("volume"),
                "kalshi_days_to_close": round(k["days_to_close"], 2),
                "pm_days_to_close": round(p["days_to_close"], 2),
            }
    return list(pairs.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog")
    ap.add_argument("--out-dir", default="data/match")
    ap.add_argument("--horizon-days", type=float, default=30.0)
    a = ap.parse_args()
    cat, out = Path(a.catalog), Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    K, P = load(cat, a.horizon_days)
    print(f"short-dated two-sided: kalshi {len(K)}  polymarket {len(P)}")
    build(K, P)
    pairs = candidates(K, P)
    pairs.sort(key=lambda x: (-x["archetype_match"], -x["jaccard"]))

    (out / "candidates.json").write_text(json.dumps(pairs, indent=1))
    print(f"\ncandidate pairs: {len(pairs)}")
    print(f"  archetype MATCH   : {sum(p['archetype_match'] for p in pairs)}")
    print(f"  archetype MISMATCH: {sum(not p['archetype_match'] for p in pairs)}  "
          f"(the moneyline-vs-O/U trap; verifier must reject these)")
    print(f"  same resolution day: {sum(p['same_day'] for p in pairs)}")
    print("\nby channel:", Counter(c for p in pairs for c in p["channels"]).most_common())
    print("by kalshi category:", Counter(p["kalshi_category"] for p in pairs).most_common(10))
    print("\n--- top 15 archetype-matched candidates ---")
    for p in [x for x in pairs if x["archetype_match"]][:15]:
        print(f"  jac={p['jaccard']:.2f} [{','.join(p['channels'])[:18]:18s}] "
              f"{p['kalshi_archetype']:14s}")
        print(f"     K: {p['kalshi_text'][:78]}")
        print(f"     P: {p['pm_text'][:78]}")
    print(f"\nwrote {out}/candidates.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

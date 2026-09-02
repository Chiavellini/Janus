#!/usr/bin/env python3
"""Emit a BLIND labelling sheet for the cross-venue equivalence gate.

    python3 match/make_gold.py --match-dir data/match_2026-08-20 --n 150

WHY THIS IS BLIND. `match/verify.py`'s deterministic layer was developed by INSPECTING the 2026-08-20
corpus -- rejection samples were read and the rules were changed in response (the trigger extractor
was gated, the archetype sentinel was demoted, subject and superlative checks were added). That is
legitimate development, but it means the verifier is fitted to this data and CANNOT be graded on it
by its author. A precision number produced that way measures memory, not accuracy.

So the sheet carries no verdict, no reason and no verifier-derived ordering. The labeller sees only
the two markets. Verdicts are written to a separate key file that scoring reads afterwards. Same
discipline as `match/gold/mlb_moneyline.csv`, which sports_match.py records as "frozen before the
first run", and as `research/mentions/HOLDOUT.md`.

LABEL VALUES
    SAME       -- one contract; identical resolution criteria, threshold, subject and date
    DIFFERENT  -- any material difference, including a threshold rung, a subject, or a trigger-set
                  subset/superset relation ("AI / Artificial Intelligence" is NOT "AI")
    UNSURE     -- rules texts are insufficient to decide. A real answer, not a cop-out; these are
                  the pairs that must never be traded on.

Sampling is stratified across the verifier's OWN outcome classes so the sheet contains both accepted
and rejected pairs -- grading only the survivors measures precision and is blind to recall, and a
verifier that rejects everything would score perfectly.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-dir", default="data/match_2026-08-20")
    ap.add_argument("--out", default="match/gold/nonsports.csv")
    ap.add_argument("--key", default=None, help="default: <out>.key.json, kept OUT of the sheet")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20260820)
    a = ap.parse_args()

    md = Path(a.match_dir)
    verdicts = json.loads((md / "verdicts.json").read_text())

    # stratify by reason so rejections are graded too, not just survivors
    buckets = defaultdict(list)
    for v in verdicts:
        buckets[v["reason"]].append(v)

    rng = random.Random(a.seed)
    per = max(1, a.n // max(1, len(buckets)))
    picked = []
    for reason in sorted(buckets):
        rows = buckets[reason]
        picked.extend(rng.sample(rows, min(per, len(rows))))
    rng.shuffle(picked)          # so the sheet's ORDER leaks nothing about the strata
    picked = picked[:a.n]

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_id", "label", "note", "kalshi_text", "pm_text"])
        for i, v in enumerate(picked):
            w.writerow([i, "", "", (v.get("kalshi_text") or "").strip(),
                        (v.get("pm_text") or "").strip()])

    key = Path(a.key) if a.key else out.with_suffix(".key.json")
    key.write_text(json.dumps(
        [{"pair_id": i, "kalshi_ticker": v.get("kalshi_ticker"),
          "pm_condition_id": v.get("pm_condition_id"),
          "verdict": v.get("verdict"), "reason": v.get("reason")}
         for i, v in enumerate(picked)], indent=1))

    print(f"wrote {out}  ({len(picked)} pairs, {len(buckets)} strata, seed {a.seed})")
    print(f"wrote {key}  -- do NOT open this until the sheet is labelled")
    print("\nfill the `label` column with SAME / DIFFERENT / UNSURE, then score with:")
    print(f"  python3 match/score_gold.py --gold {out} --key {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

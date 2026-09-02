#!/usr/bin/env python3
"""Score match/verify.py against a labelled blind sheet.

    python3 match/score_gold.py --gold match/gold/nonsports.csv --key match/gold/nonsports.key.json

THE GATE (frozen, per the registered plan): precision >= 0.98.

Precision here means: of the pairs the verifier let through, how many did the labeller call SAME.
That is the number that matters, because a false pair carries a fabricated edge into the screen --
this project has already paid for that lesson twice, at 47c (phase 1, mid-price scoring) and at
+97.94c (the golfer-vs-cyclist alias collision).

RECALL IS REPORTED TOO AND IS NOT OPTIONAL. `match/block.py:8` states the rule for the stage above:
"What blocking must never do is *miss* a real pair, because nothing downstream can recover it." The
same applies here. A verifier that rejects everything scores precision 1.00 and is worthless, so a
recall collapse must be visible in the same output rather than discoverable later.

UNSURE labels are excluded from both numerators and denominators and reported separately. Folding
them into either direction would manufacture certainty the labeller explicitly declined to supply.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

VALID = {"SAME", "DIFFERENT", "UNSURE"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="match/gold/nonsports.csv")
    ap.add_argument("--key", default="match/gold/nonsports.key.json")
    ap.add_argument("--min-precision", type=float, default=0.98)
    a = ap.parse_args()

    labels = {}
    with Path(a.gold).open() as fh:
        for row in csv.DictReader(fh):
            lab = (row.get("label") or "").strip().upper()
            if lab:
                labels[int(row["pair_id"])] = lab

    bad = {k: v for k, v in labels.items() if v not in VALID}
    if bad:
        print(f"!! {len(bad)} rows have an unrecognised label: {sorted(set(bad.values()))}")
        return 2

    key = {r["pair_id"]: r for r in json.loads(Path(a.key).read_text())}
    unlabelled = len(key) - len(labels)
    if unlabelled:
        print(f"note: {unlabelled} of {len(key)} rows are unlabelled and are excluded\n")

    tp = fp = fn = tn = unsure = 0
    fp_rows, fn_rows = [], []
    for pid, lab in labels.items():
        k = key.get(pid)
        if k is None:
            continue
        accepted = k["verdict"] != "NOT_EQUIVALENT"
        if lab == "UNSURE":
            unsure += 1
            continue
        same = lab == "SAME"
        if accepted and same:
            tp += 1
        elif accepted and not same:
            fp += 1
            fp_rows.append(k)
        elif not accepted and same:
            fn += 1
            fn_rows.append(k)
        else:
            tn += 1

    graded = tp + fp + fn + tn
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")

    print(f"graded {graded}   (UNSURE excluded: {unsure})")
    print(f"  accepted & SAME      (TP): {tp}")
    print(f"  accepted & DIFFERENT (FP): {fp}    <- fabricated edges")
    print(f"  rejected & SAME      (FN): {fn}    <- unrecoverable losses")
    print(f"  rejected & DIFFERENT (TN): {tn}")
    print(f"\nprecision {prec:.3f}   recall {rec:.3f}")

    if fn_rows:
        print(f"\nrecall losses by reason: {Counter(r['reason'] for r in fn_rows).most_common()}")
    if fp_rows:
        print(f"false accepts by reason: {Counter(r['reason'] for r in fp_rows).most_common()}")

    ok = (tp + fp) > 0 and prec >= a.min_precision
    print(f"\nGATE precision >= {a.min_precision}: {'PASS' if ok else 'FAIL'}")
    if fn:
        print("NOTE: recall losses are present. A pair rejected here cannot be recovered downstream.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

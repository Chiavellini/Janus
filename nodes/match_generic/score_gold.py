#!/usr/bin/env python3
"""Score nodes/match_generic/verify.py against the labelled blind sheet, per stratum (ledger L31).

    python3 -m nodes.match_generic.score_gold            # defaults to gold/nonsports.csv + gold/nonsports.key.json

THE BAR, as registered in snooping_ledger.md row L31 BEFORE ANY LABEL EXISTED (immutable):

    a stratum's rejections are trusted only if
        precision(labelled 0 | verdict NOT_EQUIVALENT) >= 0.95
    i.e. of the pairs the verifier REJECTED in that stratum, at least 95% were labelled "not the
    same contract" by the operator. The UNDECIDED stratum has no rejections; its share labelled 1 is
    reported as the recall the model stage would have to supply, and licenses nothing.

Labels are the operator's, written from both rules texts and blind to the key: 1 = the same
contract, 0 = not; a blank row is unlabelled and excluded; "UNSURE" (or "?") is excluded and
counted apart. SAME / DIFFERENT are accepted as aliases of 1 / 0 for the phase-1 sheets.

Until 2026-09-05 this file carried the phase-1 gate (pooled acceptance precision >= 0.98,
SAME/DIFFERENT labels, `match/gold/` paths). The ledger row is the registered one; this scorer
now computes what it declares. A label written after seeing the key is void.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALIASES = {"1": 1, "0": 0, "SAME": 1, "DIFFERENT": 0, "TRUE": 1, "FALSE": 0}
UNSURE = {"UNSURE", "?"}
BAR = 0.95


def load_labels(gold: Path) -> tuple[dict[int, int], int, dict[int, str]]:
    """pair_id -> 1/0; the count of UNSURE rows; and any unrecognised labels (pair_id -> raw)."""
    labels, unsure, bad = {}, 0, {}
    with gold.open() as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("label") or "").strip().upper()
            if not raw:
                continue
            if raw in UNSURE:
                unsure += 1
            elif raw in ALIASES:
                labels[int(row["pair_id"])] = ALIASES[raw]
            else:
                bad[int(row["pair_id"])] = raw
    return labels, unsure, bad


def score(labels: dict[int, int], key: list[dict], *, bar: float = BAR) -> dict:
    """Per-stratum rejection precision. A stratum is the key's `reason` (the verifier's rejection
    code, or UNDECIDED). Returns {stratum: {rejected, labelled_0, precision, trusted}} plus the
    UNDECIDED recall share and the pooled figures."""
    by: dict[str, dict] = defaultdict(lambda: {"rejected": 0, "labelled_0": 0, "labelled": 0, "accepted": 0, "accepted_labelled_1": 0})
    for k in key:
        pid = int(k["pair_id"])
        if pid not in labels:
            continue
        s = by[k.get("reason") or "UNDECIDED"]
        s["labelled"] += 1
        if k["verdict"] == "NOT_EQUIVALENT":
            s["rejected"] += 1
            s["labelled_0"] += int(labels[pid] == 0)
        else:
            s["accepted"] += 1
            s["accepted_labelled_1"] += int(labels[pid] == 1)
    out = {}
    for name, s in sorted(by.items()):
        prec = (s["labelled_0"] / s["rejected"]) if s["rejected"] else None
        out[name] = {**s, "precision": None if prec is None else round(prec, 4),
                     "trusted": (prec is not None and prec >= bar),
                     # UNDECIDED: the share the operator called the same contract = the recall a model stage would have to find
                     "undecided_share_labelled_1": (round(s["accepted_labelled_1"] / s["accepted"], 4) if name == "UNDECIDED" and s["accepted"] else None)}
    rejected = sum(s["rejected"] for s in by.values())
    l0 = sum(s["labelled_0"] for s in by.values())
    return {"strata": out, "pooled_rejection_precision": round(l0 / rejected, 4) if rejected else None,
            "labelled": sum(s["labelled"] for s in by.values()), "bar": bar}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--gold", type=Path, default=HERE / "gold" / "nonsports.csv")
    ap.add_argument("--key", type=Path, default=HERE / "gold" / "nonsports.key.json")
    ap.add_argument("--bar", type=float, default=BAR, help="the L31 bar; lowering it after labels exist is forbidden")
    a = ap.parse_args()
    labels, unsure, bad = load_labels(a.gold)
    if bad:
        print(f"!! {len(bad)} rows carry an unrecognised label: {sorted(set(bad.values()))} (use 1 / 0, or UNSURE)")
        return 2
    key = json.loads(a.key.read_text())
    if not labels:
        print(f"no labels yet: {len(key)} pairs in {a.gold} await the operator (1 = the same contract, 0 = not). Nothing scored.")
        return 3
    res = score(labels, key, bar=a.bar)
    print(f"labelled {res['labelled']} of {len(key)}; UNSURE excluded: {unsure}; bar: per-stratum rejection precision >= {a.bar}\n")
    print(f"{'stratum':<28} {'rejected':>8} {'labelled 0':>10} {'precision':>9}  verdict")
    for name, s in res["strata"].items():
        if name == "UNDECIDED":
            share = s["undecided_share_labelled_1"]
            print(f"{name:<28} {'-':>8} {'-':>10} {'-':>9}  {s['accepted']} accepted; share labelled 1 = {share} (the recall a model stage must supply; licenses nothing)")
        else:
            p = "-" if s["precision"] is None else f"{s['precision']:.3f}"
            print(f"{name:<28} {s['rejected']:>8} {s['labelled_0']:>10} {p:>9}  {'TRUSTED' if s['trusted'] else 'NOT TRUSTED'}")
    print(f"\npooled rejection precision {res['pooled_rejection_precision']} (reported, not the bar)")
    strata = [s for n, s in res["strata"].items() if n != "UNDECIDED"]
    ok = bool(strata) and all(s["trusted"] for s in strata)
    print(f"L31: {'every rejection stratum meets the bar' if ok else 'at least one rejection stratum is NOT trusted'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

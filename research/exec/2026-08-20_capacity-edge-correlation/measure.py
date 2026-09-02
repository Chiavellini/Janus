#!/usr/bin/env python3
"""L25 — does EDGE live where SIZE lives? Executes the registered spec, unedited.

    python3 research/exec/2026-08-20_capacity-edge-correlation/measure.py

Spec: research/exec/2026-08-20_capacity-edge-correlation/spec.yaml (IMMUTABLE) · Ledger L25.
THE PROJECT'S FIRST TEST LOOK. Reads no outcome and no settlement.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client                      # noqa: E402
from lib.stats import bh_fdr_threshold            # noqa: E402
from match.screen import screen_pair              # noqa: E402
import collectors.collect_newborn as nb           # noqa: E402

HERE = Path(__file__).parent
CAT = ROOT / "data/catalog_2026-08-20_nonsports"
MATCH = ROOT / "data/match_2026-08-20"
SEED, NPERM, LEDGER_ROWS = 0, 10_000, 25
ALPHA = bh_fdr_threshold(LEDGER_ROWS)


def spearman(x, y):
    def rank(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0.0] * len(a)
        i = 0
        while i < len(order):                     # average ties, or the coefficient is biased
            j = i
            while j + 1 < len(order) and a[order[j + 1]] == a[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def median(a):
    a = sorted(a)
    n = len(a)
    return None if not n else (a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2.0)


def perm_p(observed, values, labels, stat, n=NPERM, seed=SEED):
    """Two-sided permutation p on shuffled labels."""
    rng = random.Random(seed)
    lab = list(labels)
    hits = 0
    for _ in range(n):
        rng.shuffle(lab)
        if abs(stat(values, lab)) >= abs(observed) - 1e-12:
            hits += 1
    return (hits + 1) / (n + 1)


def main():
    cands = json.loads((MATCH / "verified_candidates.json").read_text())
    K = {r["ticker"]: r for r in json.loads((CAT / "kalshi_markets.json").read_text())}
    P = {r["condition_id"]: r for r in json.loads((CAT / "pm_markets.json").read_text())}
    client = Client("l25", rate=4.0, burst=8.0, cache_dir=None)

    # ── per-market edge: MAX across that market's pairs, executable prices, per-market fees ──
    best = {}
    for c in cands:
        k, p = K.get(c["kalshi_ticker"]), P.get(c["pm_condition_id"])
        if not k or not p:
            continue
        s = screen_pair(c, k, p)
        if s is None:
            continue
        t = c["kalshi_ticker"]
        if t not in best or s["nominal_edge_cents"] > best[t]["nominal_edge_cents"]:
            best[t] = {"nominal_edge_cents": s["nominal_edge_cents"],
                       "pm_condition_id": c["pm_condition_id"],
                       "category": k.get("category")}

    # ── capacity: live books, both legs, binding side ──
    rows, excl = [], {"no_kalshi_size": 0, "no_pm_token": 0, "pm_book_error": 0, "pm_one_sided": 0}
    for t, b in best.items():
        k = K[t]
        kb, ka = k.get("yes_bid_size"), k.get("yes_ask_size")
        if not kb or not ka:
            excl["no_kalshi_size"] += 1
            continue
        k_usd = min(kb, ka) * max(k.get("yes_ask") or 0.0, 0.01)
        tok = nb.pm_yes_token(P[b["pm_condition_id"]].get("clob_token_ids"))
        if not tok:
            excl["no_pm_token"] += 1
            continue
        try:
            pb = nb.norm_pm_book(nb.fetch_pm_book(client, tok))
        except Exception:                                          # noqa: BLE001
            excl["pm_book_error"] += 1
            continue
        if pb["best_bid"] is None or pb["best_ask"] is None:
            excl["pm_one_sided"] += 1
            continue
        p_usd = min(pb["bid_size"] or 0.0, pb["ask_size"] or 0.0) * pb["best_ask"]
        rows.append({"ticker": t, "category": b["category"],
                     "capacity_usd": min(k_usd, p_usd),
                     "edge_cents": b["nominal_edge_cents"]})

    def run(sample, tag):
        cap = [r["capacity_usd"] for r in sample]
        edge = [r["edge_cents"] for r in sample]
        n = len(sample)
        cut = sorted(cap)[int(0.90 * n)] if n else 0.0
        top = [1 if c >= cut else 0 for c in cap]
        e_top = [e for e, t in zip(edge, top) if t]
        e_rest = [e for e, t in zip(edge, top) if not t]

        def diff(vals, labels):
            a = [v for v, l in zip(vals, labels) if l]
            b = [v for v, l in zip(vals, labels) if not l]
            return (median(a) or 0.0) - (median(b) or 0.0)

        d_obs = diff(edge, top)
        d_p = perm_p(d_obs, edge, top, diff)
        rho = spearman(cap, edge)
        r_p = perm_p(rho, cap, edge, lambda v, l: spearman(v, l))
        return {"tag": tag, "n_markets": n, "decile_cut_usd": round(cut, 2),
                "n_top": len(e_top), "n_rest": len(e_rest),
                "median_edge_top_decile_c": round(median(e_top) or 0, 3),
                "median_edge_rest_c": round(median(e_rest) or 0, 3),
                "primary_diff_c": round(d_obs, 3), "primary_p": round(d_p, 5),
                "spearman_rho": round(rho, 4), "spearman_p": round(r_p, 5),
                "alpha": ALPHA,
                "primary_significant": d_p < ALPHA, "spearman_significant": r_p < ALPHA}

    out = {"spec": "research/exec/2026-08-20_capacity-edge-correlation/spec.yaml",
           "ledger_row": "L25", "test_looks_spent": 1,
           "n_unique_markets_scored": len(best), "excluded": excl,
           "primary": run(rows, "all"),
           "robustness_trimmed_20c": run([r for r in rows if abs(r["edge_cents"]) <= 20],
                                         "abs_edge_le_20c")}
    (HERE / "results.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

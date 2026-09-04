#!/usr/bin/env python3
"""L39: tennis walkover rate from frozen ATP (TML) and WTA (fork) main-draw match files."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEASONS = (2021, 2022, 2023, 2024, 2025)


def main() -> int:
    per = {}
    pooled = {"population": 0, "walkovers": 0, "retirements": 0, "defaults": 0, "team_ties_excluded": 0}
    gate = {}
    for tour in ("atp", "wta"):
        for y in SEASONS:
            f = HERE / "inputs" / f"{tour}_matches_{y}.csv"
            rows = list(csv.DictReader(open(f, encoding="utf-8", errors="replace")))
            scored = sum(1 for r in rows if (r.get("score") or "").strip())
            ok = len(rows) >= 2000 and scored >= 0.99 * len(rows)
            gate[f"{tour}_{y}"] = {"rows": len(rows), "scored": scored, "passed": ok}
            if not ok:
                continue
            pop = [r for r in rows if (r.get("tourney_level") or "") != "D"]
            d = {"population": len(pop), "team_ties_excluded": len(rows) - len(pop),
                 "walkovers": sum(1 for r in pop if "W/O" in (r.get("score") or "")),
                 "retirements": sum(1 for r in pop if "RET" in (r.get("score") or "")),
                 "defaults": sum(1 for r in pop if "DEF" in (r.get("score") or ""))}
            d["walkover_rate"] = round(d["walkovers"] / d["population"], 6) if d["population"] else None
            per[f"{tour}_{y}"] = d
            for k in pooled:
                pooled[k] += d[k]
    by_tour = {}
    for tour in ("atp", "wta"):
        p = sum(v["population"] for k, v in per.items() if k.startswith(tour))
        w = sum(v["walkovers"] for k, v in per.items() if k.startswith(tour))
        by_tour[tour] = {"population": p, "walkovers": w, "walkover_rate": round(w / p, 6) if p else None}
    pooled["walkover_rate"] = round(pooled["walkovers"] / pooled["population"], 6) if pooled["population"] else None
    res = {"run": datetime.now(timezone.utc).isoformat(), "gate": gate, "per_season": per, "by_tour": by_tour, "pooled": pooled,
           "delayed_gt7d_rate": "NOT MEASURABLE from results files (no match dates); forward row F4 to be registered"}
    (HERE / "results.json").write_text(json.dumps(res, indent=2) + "\n")
    lines = ["# L39 — tennis settlement-wedge rates (descriptive)", "",
             f"ATP from Tennismylife/TML-Database and WTA from VictorSquidWei/tennis_wta (both the Sackmann layout; commits in `inputs/PROVENANCE.md`), seasons 2021–2025, run {res['run']}.",
             "", "| rate | value | count / population |", "|---|---|---|",
             f"| walkover_rate (pooled, REGISTERED) | {pooled['walkover_rate']} | {pooled['walkovers']} / {pooled['population']} |",
             f"| walkover_rate atp | {by_tour['atp']['walkover_rate']} | {by_tour['atp']['walkovers']} / {by_tour['atp']['population']} |",
             f"| walkover_rate wta | {by_tour['wta']['walkover_rate']} | {by_tour['wta']['walkovers']} / {by_tour['wta']['population']} |",
             f"| retirements (context, ruled SAME) | — | {pooled['retirements']} |", f"| defaults (context, ruled SAME) | — | {pooled['defaults']} |",
             "| delayed_gt7d_rate | NOT MEASURABLE | see spec: no results archive keeps match dates; forward row F4 |",
             "", "| season file | rows | walkovers | population | rate | gate |", "|---|---|---|---|---|---|"]
    for k, v in per.items():
        lines.append(f"| {k} | {gate[k]['rows']} | {v['walkovers']} | {v['population']} | {v['walkover_rate']} | {'PASSED' if gate[k]['passed'] else 'FAILED'} |")
    failed = [k for k, g in gate.items() if not g["passed"]]
    lines += ["", f"Parse gate: {'PASSED on every file' if not failed else 'FAILED on ' + ', '.join(failed) + ' (excluded)'}; team ties (level D) excluded: {pooled['team_ties_excluded']}.",
              "", "Verdict: **REGISTERED** for `tennis.walkover_rate` in `nodes/settle_wedge/evidence.py` with this row as `research_ref`. "
              "`tennis.delayed_gt7d_rate` stays EVIDENCE_UNMEASURED; tennis keeps blocking by name until the forward row F4 accrues. Claims nothing about edge."]
    (HERE / "verdict.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

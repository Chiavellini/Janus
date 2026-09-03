#!/usr/bin/env python3
"""L32: college-football settlement-wedge rates. Denominator from ESPN (FBS + FCS, season type 2);
numerator from events.csv (cited schedule changes)."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402
from nodes.entities.resolve import normalize  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE = "https://site.web.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
CACHE = "/Volumes/Kilos/janus/catalog/espn_cfb"
SEASONS = (2019, 2021, 2022, 2023, 2024, 2025)
GROUPS = ("80", "81")
#: regular-season window per season (late August to the second week of December), in 3 ranges
RANGES = (("0820", "0930"), ("1001", "1105"), ("1106", "1215"))


def season_games(cl: Client, season: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for g in GROUPS:
        for a, b in RANGES:
            d = cl.get_json(BASE, params={"dates": f"{season}{a}-{season}{b}", "limit": 1000, "groups": g}, use_cache=True)
            for e in d.get("events") or []:
                if (e.get("season") or {}).get("type") != 2:
                    continue                  # bowls / postseason
                comps = (e.get("competitions") or [{}])[0]
                teams = [c["team"].get("displayName", "") for c in comps.get("competitors") or []]
                out.setdefault(e["id"], {"id": e["id"], "date": e.get("date"), "teams": teams, "group": g,
                                         "status": ((e.get("status") or {}).get("type") or {}).get("name")})
    return out


def team_key(name: str) -> str:
    return normalize(name)


def main() -> int:
    cl = Client("espn-cfb", rate=4, burst=8, cache_dir=CACHE)
    played: dict[int, dict[str, dict]] = {s: season_games(cl, s) for s in SEASONS}
    events = list(csv.DictReader((HERE / "events.csv").open())) if (HERE / "events.csv").exists() else []
    problems, per_season = [], {s: Counter() for s in SEASONS}
    n_post = Counter(); n_canc = Counter(); extra = 0
    for e in events:
        s = int(e["season"]); div = (e.get("division") or "FBS").upper()
        cancelled = e["actual_date_or_CANCELLED"].strip().upper() == "CANCELLED"
        if s not in per_season:
            continue
        if cancelled:
            n_canc[div] += 1; per_season[s]["cancelled"] += 1; extra += 1
            continue
        want = {team_key(e["away"]), team_key(e["home"])}
        hits = [g for g in played[s].values() if {team_key(t) for t in g["teams"]} == want]
        if len(hits) != 1:
            problems.append(f"{s} {e['away']} @ {e['home']}: {len(hits)} ESPN games match")
            continue
        if float(e["hours_moved"]) > 48.0:
            n_post[div] += 1; per_season[s]["postponed_gt48h"] += 1
        else:
            per_season[s]["moved_le48h"] += 1
    n_played = sum(len(v) for v in played.values())
    n_fbs = sum(1 for v in played.values() for g in v.values() if g["group"] == "80")
    denom = n_played + extra
    complete, sufficient = not problems, denom >= 3000
    post, canc = sum(n_post.values()), sum(n_canc.values())
    res = {"spec": "research/sports/2026-09-03_cfb-settlement-wedge-rates/spec.yaml", "retrieved_at": datetime.now(timezone.utc).isoformat(),
           "seasons": list(SEASONS), "played": n_played, "played_fbs": n_fbs, "cancelled_added": extra, "denominator": denom,
           "counts": {"postponed_gt48h": post, "cancelled": canc, "by_division": {"postponed_gt48h": dict(n_post), "cancelled": dict(n_canc)}},
           "rates": {"postponed_gt48h_rate": round(post / denom, 6) if denom else None, "cancelled_rate": round(canc / denom, 6) if denom else None,
                     "fbs_only": {"postponed_gt48h_rate": round(n_post.get("FBS", 0) / (n_fbs + n_canc.get("FBS", 0)), 6) if n_fbs else None,
                                  "cancelled_rate": round(n_canc.get("FBS", 0) / (n_fbs + n_canc.get("FBS", 0)), 6) if n_fbs else None}},
           "per_season": {str(s): {**dict(c), "played": len(played[s])} for s, c in per_season.items()},
           "completeness": {"problems": problems, "complete": complete}, "sufficient": sufficient,
           "verdict": "REGISTERED" if (complete and sufficient and events) else ("INCOMPLETE" if not complete else ("INSUFFICIENT" if not sufficient else "NO_TABLE"))}
    (HERE / "results.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    lines = ["# L32 — college-football settlement-wedge rates (descriptive)", "",
             f"ESPN season-type-2 games, groups 80+81, seasons {list(SEASONS)} (2020 excluded), retrieved {res['retrieved_at']}: "
             f"played {n_played} ({n_fbs} FBS) + {extra} cancelled = denominator **{denom}** ({'sufficient' if sufficient else 'INSUFFICIENT'}).", "",
             "| rate | pooled | FBS only | count |", "|---|---|---|---|",
             f"| postponed_gt48h_rate | {res['rates']['postponed_gt48h_rate']} | {res['rates']['fbs_only']['postponed_gt48h_rate']} | {post} ({dict(n_post)}) |",
             f"| cancelled_rate | {res['rates']['cancelled_rate']} | {res['rates']['fbs_only']['cancelled_rate']} | {canc} ({dict(n_canc)}) |", "",
             "| season | played | >48 h | ≤48 h moves | cancelled |", "|---|---|---|---|---|"]
    for s in SEASONS:
        c = per_season[s]
        lines.append(f"| {s} | {len(played[s])} | {c.get('postponed_gt48h', 0)} | {c.get('moved_le48h', 0)} | {c.get('cancelled', 0)} |")
    lines += ["", f"Table rows without exactly one ESPN game: {len(problems)}" + (f" {problems}" if problems else ""),
              "", f"Verdict: **{res['verdict']}**. FCS coverage of the numerator is press-limited: the registered value is a FLOOR for FCS."]
    (HERE / "verdict.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if res["verdict"] == "REGISTERED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

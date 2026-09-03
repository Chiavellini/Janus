#!/usr/bin/env python3
"""L35 (batch 2): the L33 proxy over the EFL Championship, EFL League One and Serie A season files (a FLOOR)."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPS = {"elc": ("EFL Championship", 24), "el1": ("EFL League One", 24), "ita": ("Serie A", 20)}
SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
#: "▪ Matchday 12" or "▪ Regular, Matchday 12"; any other stage header ("▪ Playoffs", "▪ Finals",
#: "▪ Championship, Matchday 1") ends the regular season for this parser: match_unit is a league match.
_ROUND = re.compile(r"^[▪»]?\s*(?:Regular,\s*)?(?:Matchday|Round|Week)\s+(\d+)")
_STAGE = re.compile(r"^[▪»]\s*\S")
_DATE = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?")
#: Two line shapes across seasons. Up to 2023-24: "  20:00  Brentford FC             2-0 (1-0)  Arsenal FC"
#: (the score sits BETWEEN the teams). From 2024-25: "    20:00  Manchester United FC    v Fulham FC   1-0 (0-0)"
#: (a " v " separator, the score last) and date lines indented by two spaces.
_MATCH = re.compile(r"^\s+(?:(\d{1,2}[.:]\d{2})\s+)?(.+?)\s{2,}(\d+-\d+(?:\s+\(\d+-\d+\))?|n/a|postponed|cancelled)\s+(.+?)\s*$")
_MATCH_V = re.compile(r"^\s+(?:(\d{1,2}[.:]\d{2})\s+)?(.+?)\s+v\s+(.+?)\s{2,}(\d+-\d+(?:\s+\(\d+-\d+\))?|n/a|postponed|cancelled)\s*$")


def parse(path: Path, season: str) -> list[dict]:
    """[{round, date, time, home, away}] from an openfootball text file. The year of a date line comes
    from the season string: months >= Jul belong to the first year."""
    y0 = int(season[:4]); y1 = y0 + 1
    out, rnd, date, last_time = [], None, None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROUND.match(line.strip())
        if m:
            rnd = int(m.group(1)); continue
        if _STAGE.match(line.strip()):
            rnd = None; continue                      # a playoff / final stage: not a league match
        m = _DATE.match(line.strip())
        if m and len(line) - len(line.lstrip()) <= 2:
            mon, day, year = MONTHS[m.group(1)], int(m.group(2)), m.group(3)
            yy = int(year) if year else (y0 if mon >= 7 else y1)
            date = datetime(yy, mon, day); last_time = None; continue
        mv = _MATCH_V.match(line)
        m = None if mv else _MATCH.match(line)
        if (mv or m) and rnd is not None and date is not None:
            t = (mv or m).group(1)
            if t:
                last_time = t.replace(".", ":")
            hh, mm = (last_time or "15:00").split(":")
            home, away = (mv.group(2), mv.group(3)) if mv else (m.group(2), m.group(4))
            out.append({"round": rnd, "kickoff": date.replace(hour=int(hh), minute=int(mm)),
                        "home": home.strip(), "away": away.strip()})
    return out


def core_window(kickoffs: list[datetime]) -> tuple[datetime, datetime]:
    days = sorted({k.date() for k in kickoffs})
    best, best_n = None, -1
    for d in days:
        span = {d + timedelta(days=i) for i in range(4)}
        n = sum(1 for k in kickoffs if k.date() in span)
        if n > best_n:
            best, best_n = d, n
    start = datetime(best.year, best.month, best.day)
    return start, start + timedelta(days=4) - timedelta(minutes=1)      # 23:59 of the fourth day


def flag(matches: list[dict]) -> list[dict]:
    by_round: dict[int, list[dict]] = defaultdict(list)
    for m in matches:
        by_round[m["round"]].append(m)
    flagged = []
    for r, ms in by_round.items():
        _s, end = core_window([m["kickoff"] for m in ms])
        for m in ms:
            hours = (m["kickoff"] - end).total_seconds() / 3600.0
            if hours > 48.0:
                flagged.append({**m, "hours_after_window": round(hours, 1), "window_end": end.isoformat()})
    return flagged


def main() -> int:
    res: dict = {"spec": "research/sports/2026-09-03_soccer-settlement-wedge-rates-batch2/spec.yaml",
                 "retrieved_at": datetime.now(timezone.utc).isoformat(), "competitions": {}, "validation": {}}
    # validation on the out-of-window 2020-21 England file
    vf = HERE / "inputs" / "validation_epl_2020-21.txt"
    if vf.exists():
        ms = parse(vf, "2020-21")
        fl = flag(ms)
        hit = [f for f in fl if "Manchester United" in f["home"] and "Liverpool" in f["away"] and f["round"] == 34]
        res["validation"] = {"matches": len(ms), "flagged": [(f["round"], f["home"], f["away"], f["kickoff"].isoformat(), f["hours_after_window"]) for f in fl],
                             "man_utd_liverpool_r34_flagged": bool(hit)}
    valid = res["validation"].get("man_utd_liverpool_r34_flagged", False)
    lines = ["# L35 — soccer settlement-wedge rates, batch 2 (descriptive; the L33 round-window proxy, a FLOOR)", "",
             f"Validation (2020-21 England, out of window): Man Utd v Liverpool R34 flagged = **{valid}**; "
             f"{len(res['validation'].get('flagged', []))} matches flagged in that season.", ""]
    for code, (name, n_teams) in COMPS.items():
        expected = n_teams * (n_teams - 1)
        c = {"seasons": {}, "played": 0, "scheduled": 0, "postponed_gt48h_proxy": 0, "cancelled": 0, "flagged": []}
        complete = True
        for season in SEASONS:
            ms = parse(HERE / "inputs" / f"{code}_{season}.txt", season)
            fl = flag(ms)
            ok = len(ms) == expected
            complete &= ok
            c["seasons"][season] = {"parsed": len(ms), "expected": expected, "complete": ok, "postponed_gt48h_proxy": len(fl)}
            c["played"] += len(ms); c["scheduled"] += expected; c["postponed_gt48h_proxy"] += len(fl)
            c["cancelled"] += max(0, expected - len(ms)) if ok else 0
            c["flagged"] += [(season, f["round"], f["home"], f["away"], f["kickoff"].date().isoformat(), f["hours_after_window"]) for f in fl]
        denom = c["scheduled"]
        c["rates"] = {"postponed_gt48h_rate": round(c["postponed_gt48h_proxy"] / denom, 6), "cancelled_rate": round(c["cancelled"] / denom, 6)}
        c["verdict"] = "REGISTERED" if (complete and valid and denom >= 1000) else ("INVALID" if not valid else ("INCOMPLETE" if not complete else "INSUFFICIENT"))
        res["competitions"][code] = c
        lines += [f"## {code} ({name})", "", "| season | parsed | expected | >48 h after round window |", "|---|---|---|---|"]
        for season, s in c["seasons"].items():
            lines.append(f"| {season} | {s['parsed']} | {s['expected']} | {s['postponed_gt48h_proxy']} |")
        lines += ["", f"postponed_gt48h_rate (FLOOR) **{c['rates']['postponed_gt48h_rate']:.6f}** ({c['postponed_gt48h_proxy']} of {denom}); "
                  f"cancelled_rate **{c['rates']['cancelled_rate']:.6f}** ({c['cancelled']}). Verdict: **{c['verdict']}**.", ""]
        if c["flagged"]:
            lines += ["Flagged: " + "; ".join(f"{s} R{r} {h} v {a} played {d} (+{x:.0f} h)" for s, r, h, a, d, x in c["flagged"]), ""]
    (HERE / "results.json").write_text(json.dumps(res, indent=2, sort_keys=True, default=str) + "\n")
    lines += ["Ligue 1, the Eredivisie, the Primeira Liga and the Scottish Premiership are not measured (no openfootball archive) and keep blocking; the Belgian Pro League waits on a file without playoff rounds.",
              "", "The registered value is a FLOOR: a move inside the round window or a same-week reschedule is invisible to this proxy."]
    (HERE / "verdict.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(c["verdict"] == "REGISTERED" for c in res["competitions"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

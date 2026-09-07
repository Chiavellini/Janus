#!/usr/bin/env python3
"""Build teams.csv / aliases.csv / xrefs.csv. Run explicitly; the outputs are VERSIONED DATA.

These files are checked in and human-reviewable on purpose. An entity table that is regenerated
silently on every run is a table nobody ever reads, and an unreviewed alias is how "3M Open golfer
== Tour de France cyclist" gets into a screen.

CROSS-REFERENCE STRATEGY
────────────────────────
The venues hand us stable team ids, so the xref rows are built by INTERSECTION, never by a single
string match:

  Kalshi     `custom_strike.{sport}_team` UUID, plus TWO independent labels — the market ticker
             suffix (an abbreviation, "-STL") and `yes_sub_title` (a location, "St. Louis"). We
             resolve both and keep the xref only if they agree on exactly one entity. Where they
             disagree or either is ambiguous, the row goes to unresolved.csv instead. This matters:
             `yes_sub_title` alone is ambiguous for New York, Los Angeles and Chicago, and the
             abbreviation alone assumes Kalshi and ESPN abbreviate identically — which is checked
             here rather than assumed.

  Polymarket `teams[].id` plus `teams[].name` ("St. Louis Cardinals") and `abbreviation` ("stl").
             Same intersection rule.

MEASURED, NOT ASSUMED: `no_sub_title` on Kalshi equals `yes_sub_title` on 82/82 MLB markets — it
is NOT the opposing team. Anything reading it as the opponent builds a team-against-itself pair.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from nodes.entities.resolve import (
    ALIASES_CSV, ALIASES_MANUAL_CSV, TEAMS_CSV, UNRESOLVED_CSV, XREFS_CSV,
    Resolver, Team, build_alias_index, load_alias_rows, normalize,
)

#: Labels that are a legitimate market OUTCOME but not a team. A three-way soccer market prices
#: home / draw / away, and the draw leg has no participant. These must be recognized, not filed as
#: unresolved entities — 20 of 25 first-pass Kalshi conflicts were EPL "Tie".
NON_TEAM_OUTCOMES = {"tie", "draw", "no winner"}
from kernel.fetch import Client
from nodes.schedule_espn import espn

from nodes.entities.leagues import LEAGUES, kalshi_series, pm_tags

#: Every registered league (nodes/entities/leagues.py is the one table; these names are views).
SEED_LEAGUES = list(LEAGUES)
#: Kalshi game-level series per league. Verified live 2026-08-16.
KALSHI_GAME_SERIES = kalshi_series()
#: Polymarket tag slug per league.
PM_TAG = pm_tags()

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA = "https://gamma-api.polymarket.com"


def _slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalize(s))).strip("-")


# ── teams + aliases from ESPN ────────────────────────────────────────────────

def _seed_players(lg: str, client) -> tuple[list[Team], list[dict]]:
    """A venue-structured league (tennis): the participants are the players Polymarket lists, keyed
    by Polymarket's stable id (carried in the `espn_id` column: the schedule source's id)."""
    from nodes.discovery.venue_schedule import pm_game_events, pm_players
    league = LEAGUES[lg]
    tag = league.pm_tag_id if league.pm_tag_id is not None else league.pm_tag
    cl = client or Client("polymarket", rate=4.0, burst=8.0)
    teams, aliases = [], []
    for pl in pm_players(lg, league.pm_prefix, pm_game_events(tag, cl)):
        name = pl["name"]
        surname = name.split()[-1] if " " in name else name
        eid = f"{lg}:{_slugify(name)}"
        teams.append(Team(entity_id=eid, league=lg, espn_id=pl["id"], abbrev=pl["abbreviation"].upper(),
                          location=" ".join(name.split()[:-1]), nickname=surname, display_name=name))
        for a in {name, pl["abbreviation"], f"{name[0]}. {surname}" if " " in name else name}:
            if a and normalize(a):
                aliases.append({"league": lg, "alias": a, "entity_id": eid, "source": "polymarket"})
    return teams, aliases


def seed_teams(leagues=SEED_LEAGUES, *, client=None) -> tuple[list[Team], list[dict]]:
    teams: list[Team] = []
    aliases: list[dict] = []
    for lg in leagues:
        if lg in LEAGUES and LEAGUES[lg].anchor == "venue_structured":
            t_, a_ = _seed_players(lg, client)
            teams += t_; aliases += a_
            continue
        raw = espn.fetch_teams(lg, client=client)
        for t in raw:
            if not t.get("isActive", True):
                continue
            # ESPN's field NAMES are unreliable: on MLB `name`="Diamondbacks" (nickname) and
            # `nickname`="Arizona" (location). We derive location/nickname from displayName and
            # the fields that actually behave, rather than trusting the labels.
            display = t.get("displayName", "") or ""
            location = t.get("location", "") or ""
            nickname = t.get("name", "") or t.get("shortDisplayName", "") or ""
            eid = f"{lg}:{t.get('slug') or _slugify(display)}"
            teams.append(Team(entity_id=eid, league=lg, espn_id=str(t["id"]),
                              abbrev=(t.get("abbreviation") or "").upper(),
                              location=location, nickname=nickname, display_name=display))
            cands = {display, location, nickname, t.get("shortDisplayName", ""),
                     t.get("abbreviation", ""), (t.get("slug") or "").replace("-", " ")}
            # location+nickname is how most books render a team; include it explicitly in case
            # displayName ever differs from the concatenation.
            if location and nickname:
                cands.add(f"{location} {nickname}")
            for a in cands:
                if a and normalize(a):
                    aliases.append({"league": lg, "alias": a, "entity_id": eid, "source": "espn"})
    return teams, aliases


# ── xrefs ────────────────────────────────────────────────────────────────────

def _kalshi_markets(series: str, client: Client) -> list[dict]:
    out = []
    for status in ("open", "unopened"):
        try:
            d = client.get_json(f"{KALSHI_BASE}/events",
                                params={"series_ticker": series, "status": status,
                                        "limit": 200, "with_nested_markets": "true"})
        except Exception:  # noqa: BLE001 — a league with no open events is not an error
            continue
        for e in d.get("events") or []:
            for m in e.get("markets") or []:
                out.append(m)
    return out


def seed_kalshi_xrefs(resolver: Resolver, leagues=SEED_LEAGUES, *,
                      client=None) -> tuple[list[dict], list[dict]]:
    """Kalshi UUID -> entity_id, accepted only when abbreviation and location AGREE."""
    cl = client or Client("kalshi", rate=4.0, burst=8.0)
    rows, conflicts = [], []
    for lg in leagues:
        series = KALSHI_GAME_SERIES.get(lg)
        if not series:
            continue
        seen: dict[str, set[str]] = defaultdict(set)
        labels: dict[str, tuple[str, str]] = {}
        for m in _kalshi_markets(series, cl):
            cs = m.get("custom_strike") or {}
            uuid = next((v for v in cs.values() if isinstance(v, str) and len(v) >= 32), None)
            if not uuid:
                continue
            suffix = (m.get("ticker") or "").rsplit("-", 1)[-1]
            sub = m.get("yes_sub_title") or ""
            # The draw leg of a 3-way market is an outcome, not a participant. Skip it here; the
            # adapter models it as market_type="1x2", outcome="draw".
            if normalize(sub) in NON_TEAM_OUTCOMES or normalize(suffix) in NON_TEAM_OUTCOMES:
                continue
            by_abbrev = resolver.by_text(lg, suffix)
            by_loc = resolver.by_text(lg, sub)
            hits = {r.entity_id for r in (by_abbrev, by_loc) if r.ok}
            if len(hits) == 1:
                seen[uuid].add(next(iter(hits)))
                labels[uuid] = (suffix, sub)
            else:
                conflicts.append({"venue": "kalshi", "league": lg, "uuid": uuid,
                                  "abbrev": suffix, "sub_title": sub,
                                  "abbrev_hit": by_abbrev.entity_id or "",
                                  "loc_hit": by_loc.entity_id or "",
                                  "reason": "no_agreement" if not hits else "disagree"})
        for uuid, ents in seen.items():
            if len(ents) == 1:
                rows.append({"venue": "kalshi", "league": lg, "venue_team_id": uuid,
                             "entity_id": next(iter(ents)), "source": "custom_strike",
                             "label": labels[uuid][0]})
            else:
                conflicts.append({"venue": "kalshi", "league": lg, "uuid": uuid, "abbrev": "",
                                  "sub_title": "", "abbrev_hit": "", "loc_hit": "",
                                  "reason": f"uuid_maps_to_{len(ents)}_entities"})
    return rows, conflicts


def _pm_events(tag: str, client: Client) -> list[dict]:
    out = []
    for off in range(0, 1500, 100):
        try:
            d = client.get_json(f"{PM_GAMMA}/events",
                                params={("tag_id" if isinstance(tag, int) else "tag_slug"): tag, "closed": "false",
                                        "limit": 100, "offset": off})
        except Exception:  # noqa: BLE001
            break
        if not d:
            break
        out += d
        if len(d) < 100:
            break
    return out


def seed_pm_xrefs(resolver: Resolver, leagues=SEED_LEAGUES, *,
                  client=None) -> tuple[list[dict], list[dict]]:
    cl = client or Client("polymarket", rate=4.0, burst=8.0)
    rows, conflicts = [], []
    for lg in leagues:
        tag = PM_TAG.get(lg)
        if not tag:
            continue
        seen: dict[str, set[str]] = defaultdict(set)
        labels: dict[str, str] = {}
        prefix = LEAGUES[lg].pm_prefix if lg in LEAGUES else None
        for e in _pm_events(tag, cl):
            # Both tours share Polymarket's `tennis` tag: keep to this league's own events, or an
            # ATP player's id lands on a WTA row through a shared surname (measured 2026-09-03).
            if lg in LEAGUES and LEAGUES[lg].anchor == "venue_structured" and prefix \
                    and not str(e.get("slug", "")).startswith(prefix + "-"):
                continue
            for t in e.get("teams") or []:
                tid = str(t.get("id") or "")
                if not tid:
                    continue
                name, ab = t.get("name") or "", t.get("abbreviation") or ""
                by_name, by_ab = resolver.by_text(lg, name), resolver.by_text(lg, ab)
                hits = {r.entity_id for r in (by_name, by_ab) if r.ok}
                if len(hits) == 1:
                    seen[tid].add(next(iter(hits)))
                    labels[tid] = name
                else:
                    conflicts.append({"venue": "polymarket", "league": lg, "uuid": tid,
                                      "abbrev": ab, "sub_title": name,
                                      "abbrev_hit": by_ab.entity_id or "",
                                      "loc_hit": by_name.entity_id or "",
                                      "reason": "no_agreement" if not hits else "disagree"})
        for tid, ents in seen.items():
            if len(ents) == 1:
                rows.append({"venue": "polymarket", "league": lg, "venue_team_id": tid,
                             "entity_id": next(iter(ents)), "source": "teams[].id",
                             "label": labels[tid]})
            else:
                conflicts.append({"venue": "polymarket", "league": lg, "uuid": tid, "abbrev": "",
                                  "sub_title": "", "abbrev_hit": "", "loc_hit": "",
                                  "reason": f"id_maps_to_{len(ents)}_entities"})
    return rows, conflicts


# ── writing ──────────────────────────────────────────────────────────────────

def _write(path: Path, fields: list[str], rows: list[dict], *, leagues=None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A run scoped to some leagues rewrites THOSE leagues' rows and keeps every other league's
    # as they are. Until 2026-09-07 `seed ita` replaced all 20 leagues' files with Serie A alone.
    if leagues is not None and path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            kept = [r for r in csv.DictReader(fh) if r.get("league") not in set(leagues)]
        rows = list(rows) + kept
    # Sorted output so a re-run is byte-identical — the phase-1 determinism gate.
    rows = sorted(rows, key=lambda r: tuple(str(r.get(f, "")) for f in fields))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main(leagues=SEED_LEAGUES) -> dict:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"seeding entities for {leagues} at {stamp}")

    teams, aliases = seed_teams(leagues)
    print(f"  ESPN: {len(teams)} teams, {len(aliases)} raw aliases")

    # Merge the hand-curated overlay BEFORE building the index, so xref seeding benefits from it
    # in the same run. Manual rows are never written back into the generated file.
    known = {t.entity_id for t in teams}
    manual = [r for r in load_alias_rows(ALIASES_MANUAL_CSV, None)
              if r.get("league") in leagues]
    orphan = [r for r in manual if r["entity_id"] not in known]
    if orphan:
        raise SystemExit(f"aliases_manual.csv references unknown entity_ids: "
                         f"{sorted({r['entity_id'] for r in orphan})}")
    print(f"  manual overlay: {len(manual)} aliases")
    aliases = aliases + manual

    # Dedupe aliases, and REPORT collisions rather than dropping them — a collision is a real
    # ambiguity in the world (mlb "New York"), and resolve() needs to see it to refuse.
    idx = build_alias_index(aliases)
    ambiguous = {k: v for k, v in idx.items() if len(v) > 1}
    print(f"  alias keys: {len(idx)}  ambiguous: {len(ambiguous)}")
    for k, v in sorted(ambiguous.items())[:15]:
        print(f"     AMBIGUOUS {k[0]}/{k[1]!r} -> {v}")

    n_t = _write(TEAMS_CSV, ["entity_id", "league", "espn_id", "abbrev", "location",
                             "nickname", "display_name"], [t.__dict__ for t in teams], leagues=leagues)
    # Only the GENERATED rows go back to aliases.csv. Writing the manual overlay in here too
    # would duplicate it on every run and, worse, make the hand-curated file look redundant.
    seen_alias = set()
    dedup = []
    for a in aliases:
        # Generated aliases from EITHER schedule source. Until 2026-09-07 only ESPN's were kept, so
        # the tennis names built above were never written and aliases.csv had no atp/wta row.
        if a.get("source") not in ("espn", "polymarket"):
            continue
        k = (a["league"], normalize(a["alias"]), a["entity_id"])
        if k not in seen_alias:
            seen_alias.add(k)
            dedup.append(a)
    n_a = _write(ALIASES_CSV, ["league", "alias", "entity_id", "source"], dedup, leagues=leagues)

    resolver = Resolver({t.entity_id: t for t in teams}, idx, {})
    k_rows, k_conf = seed_kalshi_xrefs(resolver, leagues)
    p_rows, p_conf = seed_pm_xrefs(resolver, leagues)
    print(f"  kalshi xrefs: {len(k_rows)} ({len(k_conf)} conflicts)")
    print(f"  pm xrefs:     {len(p_rows)} ({len(p_conf)} conflicts)")
    n_x = _write(XREFS_CSV, ["venue", "league", "venue_team_id", "entity_id", "source", "label"],
                 k_rows + p_rows, leagues=leagues)
    n_u = _write(UNRESOLVED_CSV.with_name("xref_conflicts.csv"),
                 ["venue", "league", "uuid", "abbrev", "sub_title", "abbrev_hit", "loc_hit",
                  "reason"], k_conf + p_conf, leagues=leagues)
    resolver.write_unresolved(leagues=leagues)

    summary = {"generated_utc": stamp, "leagues": leagues, "teams": n_t, "alias_rows": n_a,
               "alias_keys": len(idx), "ambiguous_alias_keys": len(ambiguous),
               "xrefs": n_x, "xref_conflicts": n_u,
               "kalshi_xrefs": len(k_rows), "pm_xrefs": len(p_rows)}
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    main(sys.argv[1:] or SEED_LEAGUES)

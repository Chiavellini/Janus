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
    Resolver, Team, build_alias_index, load_alias_rows, load_teams, normalize,
)

#: Labels that are a legitimate market OUTCOME but not a team. A three-way soccer market prices
#: home / draw / away, and the draw leg has no participant. These must be recognized, not filed as
#: unresolved entities — 20 of 25 first-pass Kalshi conflicts were EPL "Tie".
NON_TEAM_OUTCOMES = {"tie", "draw", "no winner"}
from kernel.fetch import Client
from nodes.schedule_espn import espn

from nodes.entities.leagues import LEAGUES, entity_scope, kalshi_series, pm_tags

#: Every registered league (nodes/entities/leagues.py is the one table; these names are views).
SEED_LEAGUES = list(LEAGUES)
#: Kalshi game-level series per league. Verified live 2026-08-16.
KALSHI_GAME_SERIES = kalshi_series()
#: Polymarket tag slug per league.
PM_TAG = pm_tags()

def _slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalize(s))).strip("-")


# ── teams + aliases from ESPN ────────────────────────────────────────────────

def _seed_players(lg: str, client, *, diagnostics: dict | None = None) -> tuple[list[Team], list[dict]]:
    """A venue-structured league (tennis): the participants are the players Polymarket lists, keyed
    by Polymarket's stable id (carried in the `espn_id` column: the schedule source's id)."""
    from nodes.discovery.venue_schedule import pm_players
    from nodes.match_sports.stage1_checkpoint import pull_pm
    league = LEAGUES[lg]
    cl = client or Client("polymarket", rate=4.0, burst=8.0)
    teams, aliases = [], []
    events = pull_pm(lg, cl)
    if diagnostics is not None:
        diagnostics[lg] = dict(events.diagnostics)
    for pl in pm_players(lg, league.pm_prefix, events):
        name = pl["name"]
        surname = name.split()[-1] if " " in name else name
        eid = f"{lg}:{_slugify(name)}"
        teams.append(Team(entity_id=eid, league=lg, espn_id=pl["id"], abbrev=pl["abbreviation"].upper(),
                          location=" ".join(name.split()[:-1]), nickname=surname, display_name=name))
        for a in {name, pl["abbreviation"], f"{name[0]}. {surname}" if " " in name else name}:
            if a and normalize(a):
                aliases.append({"league": lg, "alias": a, "entity_id": eid, "source": "polymarket"})
    return teams, aliases


def seed_teams(leagues=SEED_LEAGUES, *, client=None, existing_teams=None,
               pm_diagnostics: dict | None = None) -> tuple[list[Team], list[dict]]:
    """Seed competition aliases against stable identities, reusing exact ESPN soccer ids.

    Existing club ids are immutable even when their old prefix names a domestic competition.
    New clubs use a competition-independent id. Conflicting pre-existing identities stop the
    seed: neither venue labels nor iteration order may choose which entity owns an ESPN id.
    """
    teams: list[Team] = []
    aliases: list[dict] = []
    existing = load_teams() if existing_teams is None else dict(existing_teams)
    clubs: dict[str, Team] = {}
    for team in existing.values():
        if entity_scope(team.league) != "soccer":
            continue
        if not team.espn_id:
            raise ValueError(f"soccer entity lacks ESPN id: {team.entity_id}")
        previous = clubs.get(team.espn_id)
        if previous is not None and previous.entity_id != team.entity_id:
            raise ValueError(f"soccer ESPN id collision: {team.espn_id}: "
                             f"{previous.entity_id} / {team.entity_id}")
        clubs[team.espn_id] = team
    for lg in leagues:
        if lg in LEAGUES and LEAGUES[lg].anchor == "venue_structured":
            t_, a_ = _seed_players(lg, client, diagnostics=pm_diagnostics)
            # Venue-structured schedules expose only currently open events. Stable identities
            # are append-only: deleting yesterday's player would leave an audited manual xref
            # dangling merely because the event closed.
            kept = {team.entity_id: team for team in existing.values() if team.league == lg}
            by_stable_id: dict[str, Team] = {}
            for team in kept.values():
                prior = by_stable_id.get(team.espn_id)
                if prior is not None and prior.entity_id != team.entity_id:
                    raise ValueError(f"{lg} stable player id collision: {team.espn_id}: "
                                     f"{prior.entity_id} / {team.entity_id}")
                by_stable_id[team.espn_id] = team
            remap: dict[str, str] = {}
            for team in sorted(t_, key=lambda row: (row.espn_id, row.entity_id)):
                owner = kept.get(team.entity_id)
                if owner is not None and owner.espn_id != team.espn_id:
                    raise ValueError(f"{lg} player identity changed: {team.entity_id}: "
                                     f"{owner.espn_id} / {team.espn_id}")
                canonical = by_stable_id.get(team.espn_id)
                if canonical is None:
                    canonical = owner or team
                    by_stable_id[team.espn_id] = canonical
                    kept[canonical.entity_id] = canonical
                prior_target = remap.get(team.entity_id)
                if prior_target is not None and prior_target != canonical.entity_id:
                    raise ValueError(f"{lg} generated player identity collision: {team.entity_id}: "
                                     f"{prior_target} / {canonical.entity_id}")
                remap[team.entity_id] = canonical.entity_id
            a_ = [{**alias, "entity_id": remap.get(alias["entity_id"], alias["entity_id"])}
                  for alias in a_]
            t_ = list(kept.values())
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
            espn_id = str(t.get("id") or "")
            if not espn_id:
                raise ValueError(f"{lg} team lacks ESPN id: {display}")
            scope = entity_scope(lg)
            known = clubs.get(espn_id) if scope == "soccer" else None
            eid = (known.entity_id if known else f"soccer:espn-{espn_id}" if scope == "soccer"
                   else f"{lg}:{t.get('slug') or _slugify(display)}")
            team = known or Team(entity_id=eid, league=scope, espn_id=espn_id,
                                 abbrev=(t.get("abbreviation") or "").upper(),
                                 location=location, nickname=nickname, display_name=display)
            if scope == "soccer":
                clubs[espn_id] = team
            teams.append(team)
            cands = {display, location, nickname, t.get("shortDisplayName", ""),
                     t.get("abbreviation", ""), (t.get("slug") or "").replace("-", " ")}
            # location+nickname is how most books render a team; include it explicitly in case
            # displayName ever differs from the concatenation.
            if location and nickname:
                cands.add(f"{location} {nickname}")
            for a in cands:
                if a and normalize(a):
                    aliases.append({"league": lg, "alias": a, "entity_id": eid, "source": "espn"})
    return list({t.entity_id: t for t in teams}.values()), aliases


# ── xrefs ────────────────────────────────────────────────────────────────────

def _kalshi_markets(league: str, client: Client, *, diagnostics: dict | None = None) -> list[dict]:
    """Flatten the same complete, schema-validated enumeration used by live matching.

    An empty terminal page is a valid league/status with no events. A failed or malformed page is
    not equivalent to that state and must abort the reseed before any generated file is touched.
    """
    from nodes.match_sports.stage1_checkpoint import VenuePullError, pull_kalshi
    try:
        events = pull_kalshi(league, client)
    except VenuePullError as exc:
        if diagnostics is not None:
            diagnostics[league] = dict(exc.diagnostics)
        raise
    if diagnostics is not None:
        diagnostics[league] = dict(events.diagnostics)
    return [market for event in events for market in event["markets"]]


def seed_kalshi_xrefs(resolver: Resolver, leagues=SEED_LEAGUES, *,
                      client=None, diagnostics: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Kalshi UUID -> entity_id, accepted only when abbreviation and location AGREE."""
    cl = client or Client("kalshi", rate=4.0, burst=8.0)
    rows, conflicts = [], []
    for lg in leagues:
        if lg not in LEAGUES or not LEAGUES[lg].kalshi_series_all:
            continue
        seen: dict[str, set[str]] = defaultdict(set)
        labels: dict[str, tuple[str, str]] = {}
        for m in _kalshi_markets(lg, cl, diagnostics=diagnostics):
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


def _pm_events(league: str, client: Client, *, diagnostics: dict | None = None) -> list[dict]:
    """The same complete, dual-selector enumeration used by live matching."""
    from nodes.match_sports.stage1_checkpoint import pull_pm
    events = pull_pm(league, client)
    if diagnostics is not None:
        diagnostics[league] = dict(events.diagnostics)
    return events


def seed_pm_xrefs(resolver: Resolver, leagues=SEED_LEAGUES, *, client=None,
                  diagnostics: dict | None = None) -> tuple[list[dict], list[dict]]:
    cl = client or Client("polymarket", rate=4.0, burst=8.0)
    rows, conflicts = [], []
    for lg in leagues:
        if lg not in LEAGUES:
            continue
        seen: dict[str, set[str]] = defaultdict(set)
        labels: dict[str, str] = {}
        prefix = LEAGUES[lg].pm_prefix if lg in LEAGUES else None
        for e in _pm_events(lg, cl, diagnostics=diagnostics):
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


def _write_teams(teams: list[Team], path: Path = TEAMS_CSV) -> int:
    """Upsert stable identities: a roster refresh must not orphan another competition's aliases.

    Alias/xref membership is still refreshed only for the explicitly selected competitions.
    An absent club is not deleted from the identity directory merely because it was relegated
    or has no fixture in the current continental tournament.
    """
    merged = load_teams(path)
    for team in teams:
        prior = merged.get(team.entity_id)
        if prior is not None and (entity_scope(prior.league), prior.espn_id) != (
                entity_scope(team.league), team.espn_id):
            raise ValueError(f"entity identity changed: {team.entity_id}")
        merged[team.entity_id] = team
    return _write(path, ["entity_id", "league", "espn_id", "abbrev", "location", "nickname",
                         "display_name"], [t.__dict__ for t in merged.values()])


def main(leagues=SEED_LEAGUES) -> dict:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"seeding entities for {leagues} at {stamp}")

    pm_team_diagnostics: dict = {}
    teams, aliases = seed_teams(leagues, pm_diagnostics=pm_team_diagnostics)
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
    # Gather every remote-dependent result before the first generated table is touched. A venue
    # selector/page/schema conflict therefore aborts the scoped reseed with byte-identical files,
    # instead of refreshing teams/aliases and leaving xrefs from the previous generation.
    resolver = Resolver({t.entity_id: t for t in teams}, idx, {})
    kalshi_xref_diagnostics: dict = {}
    k_rows, k_conf = seed_kalshi_xrefs(resolver, leagues, diagnostics=kalshi_xref_diagnostics)
    pm_xref_diagnostics: dict = {}
    p_rows, p_conf = seed_pm_xrefs(resolver, leagues, diagnostics=pm_xref_diagnostics)
    print(f"  kalshi xrefs: {len(k_rows)} ({len(k_conf)} conflicts)")
    print(f"  pm xrefs:     {len(p_rows)} ({len(p_conf)} conflicts)")
    for phase, diagnostics in (("teams", pm_team_diagnostics), ("xrefs", pm_xref_diagnostics)):
        for league, detail in sorted(diagnostics.items()):
            print(f"  PM enumeration {phase}/{league}: {json.dumps(detail, sort_keys=True)}")
    for league, detail in sorted(kalshi_xref_diagnostics.items()):
        print(f"  Kalshi enumeration xrefs/{league}: {json.dumps(detail, sort_keys=True)}")

    n_t = _write_teams(teams)
    n_a = _write(ALIASES_CSV, ["league", "alias", "entity_id", "source"], dedup, leagues=leagues)
    n_x = _write(XREFS_CSV, ["venue", "league", "venue_team_id", "entity_id", "source", "label"],
                 k_rows + p_rows, leagues=leagues)
    n_u = _write(UNRESOLVED_CSV.with_name("xref_conflicts.csv"),
                 ["venue", "league", "uuid", "abbrev", "sub_title", "abbrev_hit", "loc_hit",
                  "reason"], k_conf + p_conf, leagues=leagues)
    resolver.write_unresolved(leagues=leagues)

    summary = {"generated_utc": stamp, "leagues": leagues, "teams": n_t, "alias_rows": n_a,
               "alias_keys": len(idx), "ambiguous_alias_keys": len(ambiguous),
               "xrefs": n_x, "xref_conflicts": n_u,
               "kalshi_xrefs": len(k_rows), "pm_xrefs": len(p_rows),
               "kalshi_enumeration": {"xrefs": kalshi_xref_diagnostics},
               "pm_enumeration": {"teams": pm_team_diagnostics, "xrefs": pm_xref_diagnostics}}
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    main(sys.argv[1:] or SEED_LEAGUES)

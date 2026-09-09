#!/usr/bin/env python3
"""A schedule from the venues themselves, for competitions ESPN does not anchor (tennis).

Polymarket's game events carry the two players (`teams`: name, abbreviation, a stable id) and
`gameStartTime`; that is the schedule. Kalshi is joined onto it by the players' names and the
ticker date (`nodes/match_sports`), so the pair's key is still league + sorted entity ids + start,
never a title similarity -- with the weaker `venue_structured` provenance the registry records.

The ScheduledGame's `home_espn` / `away_espn` fields carry the Polymarket team ids for these
leagues: the field names are ESPN's, the contract is "the schedule source's stable participant id".
"""

from __future__ import annotations

from datetime import datetime, timezone

from kernel.fetch import Client, HttpError, OffsetCap
from nodes.schedule_espn.espn import ScheduledGame
from nodes.venue_polymarket.books import PM_GAMMA


def _empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_sparse(left, right):
    """Merge two representations after their schedule-critical fields were checked."""
    if _empty(left):
        return right
    if _empty(right):
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        out = dict(left)
        for key, value in right.items():
            out[key] = _merge_sparse(out[key], value) if key in out else value
        return out
    if isinstance(left, list) and isinstance(right, list):
        out = list(left)
        for item in right:
            match = next((i for i, old in enumerate(out)
                          if isinstance(old, dict) and isinstance(item, dict)
                          and ((old.get("id") is not None and old.get("id") == item.get("id"))
                               or (old.get("slug") and old.get("slug") == item.get("slug")))), None)
            if match is not None:
                out[match] = _merge_sparse(out[match], item)
            elif item not in out:
                out.append(item)
        return out
    return left


def _schedule_conflict(left: dict, right: dict) -> str | None:
    """Name the first disagreement in fields that define a ScheduledGame."""
    for key in ("id", "slug"):
        if not _empty(left.get(key)) and not _empty(right.get(key)) and str(left[key]) != str(right[key]):
            return key
    left_teams, right_teams = left.get("teams") or [], right.get("teams") or []
    if left_teams and right_teams:
        left_ids = {str(team.get("id")) for team in left_teams if isinstance(team, dict) and team.get("id") is not None}
        right_ids = {str(team.get("id")) for team in right_teams if isinstance(team, dict) and team.get("id") is not None}
        if left_ids and right_ids and left_ids != right_ids:
            return "teams.ids"
    for collection, keys in (("teams", ("name", "abbreviation")),
                             ("markets", ("sportsMarketType", "gameStartTime"))):
        a = {str(x.get("id") if collection == "teams" else x.get("slug")): x
             for x in left.get(collection) or [] if isinstance(x, dict)
             and (x.get("id") is not None if collection == "teams" else x.get("slug"))}
        b = {str(x.get("id") if collection == "teams" else x.get("slug")): x
             for x in right.get(collection) or [] if isinstance(x, dict)
             and (x.get("id") is not None if collection == "teams" else x.get("slug"))}
        for ident in sorted(a.keys() & b.keys()):
            for key in keys:
                av, bv = a[ident].get(key), b[ident].get(key)
                if not _empty(av) and not _empty(bv) and str(av) != str(bv):
                    return f"{collection}[{ident}].{key}"
    return None


def _dedupe_schedule_events(events: list[dict]) -> list[dict]:
    """Collapse repeated Gamma representations by exact id, failing on identity conflicts.

    Offset pagination can repeat an event while listings move between pages.  Distinct ids with
    distinct slugs remain distinct even when the participants and clock coincide.
    """
    by_key: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    slug_ids: dict[str, set[str]] = {}
    for event in events:
        ident, slug = str(event.get("id") or ""), str(event.get("slug") or "")
        if slug and ident:
            slug_ids.setdefault(slug, set()).add(ident)
            if len(slug_ids[slug]) > 1:
                raise ValueError(f"PM schedule slug {slug!r} maps to multiple ids: {sorted(slug_ids[slug])}")
        key = ("id", ident) if ident else (("slug", slug) if slug else ("object", str(id(event))))
        if key not in by_key:
            by_key[key] = event
            order.append(key)
            continue
        conflict = _schedule_conflict(by_key[key], event)
        if conflict:
            raise ValueError(f"conflicting duplicate PM schedule event {key[1]!r}: {conflict}")
        by_key[key] = _merge_sparse(by_key[key], event)
    return [by_key[key] for key in order]


def pm_game_events(tag: str | int, cl: Client, *, pages: int = 60) -> list[dict]:
    """Every open event under the tag, page by page until a short page.

    The terminal short page is part of the completeness proof.  A malformed response, failed
    request or a run of full pages through the safety cap is therefore an error, never a partial
    schedule.  The old cap of six pages (600 events) sat 38 events above the tennis tag on
    2026-09-07.
    """
    if pages < 1:
        raise ValueError("PM schedule pages must be positive")
    out = []
    key = "tag_id" if isinstance(tag, int) else "tag_slug"
    for i in range(pages):
        try:
            d = cl.get_json(f"{PM_GAMMA}/events", params={key: tag, "closed": "false", "limit": 100, "offset": i * 100}, use_cache=False)
        except (HttpError, OffsetCap, OSError, RuntimeError, ValueError, KeyError) as exc:
            raise RuntimeError(f"incomplete PM schedule enumeration for {key}={tag!r}: page {i} failed") from exc
        if type(d) is not list:  # bool/dict/None are not valid empty pages
            raise ValueError(f"malformed PM schedule page {i} for {key}={tag!r}: expected list, got {type(d).__name__}")
        if any(type(event) is not dict
               or (_empty(event.get("id")) and _empty(event.get("slug"))) for event in d):
            raise ValueError(f"malformed PM schedule page {i} for {key}={tag!r}: "
                             "event is not an identified object")
        out.extend(d)
        if len(d) < 100:
            return out
    raise RuntimeError(f"incomplete PM schedule enumeration for {key}={tag!r}: "
                       f"{pages} full pages without terminal short page")


def _start(m: dict) -> int | None:
    gs = m.get("gameStartTime")
    if not gs:
        return None
    try:
        return int(datetime.fromisoformat(str(gs).replace(" ", "T").replace("+00", "+00:00")).timestamp())
    except ValueError:
        return None


def schedule_from_events(league: str, prefix: str, events: list[dict], now_ts: float, *, singles_only: bool = True) -> list[ScheduledGame]:
    """PURE. One ScheduledGame per full-match moneyline whose slug starts with the league's prefix.
    `state` is inferred from the start (pre / in for up to 5 h / post), since the venue states none."""
    out = []
    for ev in _dedupe_schedule_events(events):
        slug = str(ev.get("slug", ""))
        if not slug.startswith(prefix + "-") or (singles_only and "doubles" in slug):
            continue
        teams = ev.get("teams") or []
        if len(teams) != 2:
            continue
        m = next((x for x in ev.get("markets") or [] if x.get("sportsMarketType") == "moneyline" and x.get("gameStartTime")
                  and x.get("slug") == slug), None)
        if m is None:
            continue
        st = _start(m)
        if st is None:
            continue
        away, home = teams[0], teams[1]          # Polymarket's `ordering` is away-first
        age = now_ts - st
        state = "pre" if age < 0 else ("in" if age < 5 * 3600 else "post")
        out.append(ScheduledGame(f"pm:{league}:{ev.get('id') or slug}", league, st, str(home.get("id")), str(away.get("id")),
                                 str(home.get("name") or ""), str(away.get("name") or ""), state, state == "post", True, False,
                                 "tournament", f"{away.get('abbreviation', '')} v {home.get('abbreviation', '')}".upper(),
                                 str(ev.get("title") or slug)))
    return sorted(out, key=lambda g: (g.start_utc, g.game_id))


def pm_players(league: str, prefix: str, events: list[dict]) -> list[dict]:
    """PURE. Distinct players seen in the league's events: {id, name, abbreviation}, for the entity seed."""
    seen: dict[str, dict] = {}
    for ev in events:
        slug = str(ev.get("slug", ""))
        if not slug.startswith(prefix + "-") or "doubles" in slug:      # a pair is not a player
            continue
        for t in ev.get("teams") or []:
            if t.get("id") is not None and t.get("name"):
                seen.setdefault(str(t["id"]), {"id": str(t["id"]), "name": str(t["name"]), "abbreviation": str(t.get("abbreviation") or "")})
    return list(seen.values())


def fetch_schedule(league: str, now: datetime | None = None, *, client: Client | None = None) -> list[ScheduledGame]:
    from nodes.entities.leagues import LEAGUES
    lg = LEAGUES[league]
    cl = client or Client("polymarket-schedule", rate=4, burst=8, cache_dir=None)
    tag = lg.pm_tag_id if lg.pm_tag_id is not None else lg.pm_tag
    t = (now or datetime.now(timezone.utc)).timestamp()
    return schedule_from_events(league, lg.pm_prefix, pm_game_events(tag, cl), t)

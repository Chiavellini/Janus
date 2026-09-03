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

from kernel.fetch import Client
from nodes.schedule_espn.espn import ScheduledGame
from nodes.venue_polymarket.books import PM_GAMMA


def pm_game_events(tag: str | int, cl: Client, *, pages: int = 6) -> list[dict]:
    out = []
    key = "tag_id" if isinstance(tag, int) else "tag_slug"
    for i in range(pages):
        d = cl.get_json(f"{PM_GAMMA}/events", params={key: tag, "closed": "false", "limit": 100, "offset": i * 100}, use_cache=False)
        if not d:
            break
        out += d
        if len(d) < 100:
            break
    return out


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
    for ev in events:
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
        if not str(ev.get("slug", "")).startswith(prefix + "-"):
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

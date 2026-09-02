#!/usr/bin/env python3
"""The schedule spine: an EXTERNAL anchor both venues join to, instead of joining to each other.

WHY THIS EXISTS
───────────────
Phase 1 matched Kalshi to Polymarket by title similarity and got n=35 usable pairs out of ~100k
markets. Title-Jaccard is not merely weak here, it is *anti*-correlated with truth: "Lakers vs
Celtics Nov 3" and "Lakers vs Celtics Nov 17" share nearly every token and are different games,
while "Lakers beat Celtics" and "Will the Los Angeles Lakers win?" share almost none and are the
same one.

Anchoring both venues to a third source turns one O(n*m) fuzzy problem into two O(n) exact joins.
The schedule is that third source.

WHY ESPN SPECIFICALLY
─────────────────────
Not convenience. Kalshi's own `settlement_sources` on KXMLBGAME lists, in order:
    ESPN (espn.com) · Fox Sports · the Governing League (mlb.com)
So ESPN is *the venue's own primary settlement reference*, not a neutral third party we picked.
Per the phase-2 settlement-reference rule in AGENTS.md, that makes the Kalshi<->schedule basis
structurally zero for game identity and outcome, which is the strongest anchor available.
Polymarket's `resolutionSource` is mlb.com — the same league feed Kalshi lists third. Any residual
ESPN/MLB disagreement is a Stage-4 wedge input, and it is NOT assumed to be zero here.

THREE THINGS MEASURED, NOT ASSUMED (2026-08-16)
───────────────────────────────────────────────
1. `site.api.espn.com` — the host every tutorial cites — returns **403 Forbidden**. The working
   host is `site.web.api.espn.com`. Same paths, same payloads.
2. The `dates=` query parameter is resolved in the league's LOCAL/Eastern date space, but every
   `event.date` comes back in UTC with a `Z`. Query 20260815-20260822 and you get events dated
   2026-08-23 UTC. So we deliberately OVER-FETCH by a day on each side and filter on UTC. Failing
   to do this silently drops every late-evening game from the last day of any window.
3. A date-RANGE query works in one request (`dates=YYYYMMDD-YYYYMMDD`), so a league-week is one
   call, not seven.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from lib.fetch import Client

#: The working host. `site.api.espn.com` is 403 — see module docstring.
ESPN_BASE = "https://site.web.api.espn.com/apis/site/v2/sports"

#: Our league code -> ESPN's (sport, league) path pair.
LEAGUE_PATHS: dict[str, tuple[str, str]] = {
    "mlb":  ("baseball", "mlb"),
    "nfl":  ("football", "nfl"),
    "nba":  ("basketball", "nba"),
    "wnba": ("basketball", "wnba"),
    "nhl":  ("hockey", "nhl"),
    "epl":  ("soccer", "eng.1"),
}

#: How far a venue's stated start time may sit from the schedule's and still be the same game.
#: MLB doubleheaders are typically ~3.5h apart, so this must stay well under that or G1 and G2
#: become ambiguous. 90 minutes absorbs a venue rounding to the hour without reaching G2.
DEFAULT_START_TOLERANCE_S = 5400


@dataclass(frozen=True)
class ScheduledGame:
    """One scheduled contest. This is the spine record every venue market resolves onto."""
    game_id: str            # "espn:mlb:401816535" — globally unique, venue-independent
    league: str
    start_utc: int          # epoch seconds, from event.date (already UTC)
    home_espn: str          # ESPN team id
    away_espn: str
    home_name: str
    away_name: str
    state: str              # "pre" | "in" | "post"
    completed: bool
    neutral_site: bool
    was_suspended: bool
    season_slug: str        # "regular-season" | "preseason" | ...
    short_name: str         # "CHW @ DET"
    name: str

    @property
    def participants_espn(self) -> tuple[str, ...]:
        """SORTED team ids. Orientation-free on purpose.

        Home/away is NOT reliable across venues — Polymarket's `sport.ordering` is "away" (its
        slug is away-first) while Kalshi's event ticker is home-first for some series and not
        others. Trusting orientation silently halves the candidate set. Sort, then carry
        home/away separately for the leagues where it changes the market's meaning (spreads).
        """
        return tuple(sorted((self.home_espn, self.away_espn)))


def _to_epoch(iso: str) -> int:
    """ESPN emits '2026-08-15T17:10Z'. Note: minute precision, no seconds."""
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).timestamp())


def _client(cache_dir=None) -> Client:
    # ESPN is unauthenticated and tolerant, but this is someone else's free endpoint.
    return Client("espn", rate=4.0, burst=8.0, cache_dir=cache_dir)


def parse_scoreboard(payload: Mapping, league: str) -> list[ScheduledGame]:
    """Raw scoreboard JSON -> ScheduledGame list. PURE: no network, no clock.

    Purity is the point — it makes frozen-fixture golden tests possible and lets an archived
    payload be re-parsed after a schema change without re-fetching.
    """
    out: list[ScheduledGame] = []
    for e in payload.get("events") or []:
        comps = e.get("competitions") or []
        if not comps:
            continue
        c = comps[0]
        home = away = None
        for t in c.get("competitors") or []:
            if t.get("homeAway") == "home":
                home = t
            elif t.get("homeAway") == "away":
                away = t
        if not home or not away:
            continue  # non-head-to-head (golf, racing) — a different key shape entirely
        st = (e.get("status") or {}).get("type") or {}
        out.append(ScheduledGame(
            game_id=f"espn:{league}:{e['id']}",
            league=league,
            start_utc=_to_epoch(e["date"]),
            home_espn=str(home["team"]["id"]),
            away_espn=str(away["team"]["id"]),
            home_name=home["team"].get("displayName", ""),
            away_name=away["team"].get("displayName", ""),
            state=st.get("state", "unknown"),
            completed=bool(st.get("completed")),
            # Both feed Stage 4. A neutral-site or suspended game is exactly where venue rulesets
            # diverge, so they are captured at Stage 1 rather than reconstructed later.
            neutral_site=bool(c.get("neutralSite")),
            was_suspended=bool(c.get("wasSuspended")),
            season_slug=(e.get("season") or {}).get("slug", ""),
            short_name=e.get("shortName", ""),
            name=e.get("name", ""),
        ))
    return out


def fetch_range(league: str, start: datetime, end: datetime, *, client: Client | None = None,
                use_cache: bool = True) -> list[ScheduledGame]:
    """Every scheduled game with a UTC start inside [start, end).

    Over-fetches one day on each side because the `dates=` parameter is Eastern-date-scoped while
    `event.date` is UTC (see module docstring, finding 2), then filters on true UTC.
    """
    if league not in LEAGUE_PATHS:
        raise KeyError(f"unknown league {league!r}; known: {sorted(LEAGUE_PATHS)}")
    sport, lg = LEAGUE_PATHS[league]
    cl = client or _client()
    q_from = (start - timedelta(days=1)).strftime("%Y%m%d")
    q_to = (end + timedelta(days=1)).strftime("%Y%m%d")
    payload = cl.get_json(f"{ESPN_BASE}/{sport}/{lg}/scoreboard",
                          params={"dates": f"{q_from}-{q_to}", "limit": 1000},
                          use_cache=use_cache)
    lo, hi = int(start.timestamp()), int(end.timestamp())
    games = [g for g in parse_scoreboard(payload, league) if lo <= g.start_utc < hi]
    return sorted(games, key=lambda g: (g.start_utc, g.game_id))


def fetch_teams(league: str, *, client: Client | None = None,
                use_cache: bool = True) -> list[Mapping]:
    """Team directory for a league. Seeds lib/entities/teams.csv.

    ESPN's field names are counterintuitive and MUST NOT be trusted by name alone: on MLB,
    `name` = "Diamondbacks" (the nickname) while `nickname` = "Arizona" (the location). The seeder
    reads them positionally-by-meaning, not by what they are called.
    """
    sport, lg = LEAGUE_PATHS[league]
    cl = client or _client()
    d = cl.get_json(f"{ESPN_BASE}/{sport}/{lg}/teams", params={"limit": 500}, use_cache=use_cache)
    return [t["team"] for t in d["sports"][0]["leagues"][0]["teams"]]


def index_by_participants(games: Sequence[ScheduledGame]) -> dict[tuple[str, ...], list[ScheduledGame]]:
    """{sorted team-id pair} -> games, chronological. A doubleheader is a 2-element list."""
    out: dict[tuple[str, ...], list[ScheduledGame]] = {}
    for g in games:
        out.setdefault(g.participants_espn, []).append(g)
    for v in out.values():
        v.sort(key=lambda g: g.start_utc)
    return out


def nearest_game(candidates: Sequence[ScheduledGame], start_utc: int,
                 tolerance_s: int = DEFAULT_START_TOLERANCE_S) -> ScheduledGame | None:
    """The single game closest in time, or None if nothing is inside the tolerance.

    Returns None on a TIE rather than picking one. A tie means two games of the same matchup are
    equidistant from the quoted start, which is unresolvable from time alone — and quietly picking
    G1 would produce a confident wrong pair, the phase-1 failure mode.
    """
    if not candidates:
        return None
    scored = sorted(((abs(g.start_utc - start_utc), g) for g in candidates), key=lambda x: x[0])
    best_d, best = scored[0]
    if best_d > tolerance_s:
        return None
    if len(scored) > 1 and scored[1][0] == best_d:
        return None
    return best


def to_rows(games: Iterable[ScheduledGame]) -> list[dict]:
    return [asdict(g) for g in games]


def selftest() -> None:
    """Offline. Uses a frozen fixture shaped like a real ESPN payload."""
    fixture = {"events": [
        {"id": "401816535", "date": "2026-08-15T17:10Z", "name": "Chicago White Sox at Detroit Tigers",
         "shortName": "CHW @ DET", "season": {"slug": "regular-season"},
         "status": {"type": {"state": "post", "completed": True}},
         "competitions": [{"neutralSite": False, "wasSuspended": False, "competitors": [
             {"homeAway": "home", "team": {"id": "6", "displayName": "Detroit Tigers"}},
             {"homeAway": "away", "team": {"id": "4", "displayName": "Chicago White Sox"}}]}]},
        # doubleheader: same pair, same day, 3.5h apart
        {"id": "401816600", "date": "2026-08-15T20:40Z", "name": "Chicago White Sox at Detroit Tigers",
         "shortName": "CHW @ DET", "season": {"slug": "regular-season"},
         "status": {"type": {"state": "pre", "completed": False}},
         "competitions": [{"neutralSite": False, "wasSuspended": False, "competitors": [
             {"homeAway": "home", "team": {"id": "6", "displayName": "Detroit Tigers"}},
             {"homeAway": "away", "team": {"id": "4", "displayName": "Chicago White Sox"}}]}]},
        # a golf-shaped event with no home/away must be skipped, not crash
        {"id": "999", "date": "2026-08-15T12:00Z", "name": "Some Open", "shortName": "OPEN",
         "season": {"slug": "regular-season"}, "status": {"type": {"state": "pre"}},
         "competitions": [{"competitors": [{"homeAway": "", "team": {"id": "1"}}]}]},
    ]}
    gs = parse_scoreboard(fixture, "mlb")
    assert len(gs) == 2, f"expected 2 head-to-head games, got {len(gs)}"
    g = gs[0]
    assert g.game_id == "espn:mlb:401816535"
    assert g.start_utc == 1786813800, g.start_utc
    # orientation-free key, and it is genuinely sorted
    assert g.participants_espn == ("4", "6")
    assert gs[1].participants_espn == g.participants_espn

    idx = index_by_participants(gs)
    assert list(idx) == [("4", "6")] and len(idx[("4", "6")]) == 2

    dh = idx[("4", "6")]
    # a venue quoting 17:40Z resolves to G1, not G2
    assert nearest_game(dh, _to_epoch("2026-08-15T17:40Z")).game_id == "espn:mlb:401816535"
    # a venue quoting 20:40Z resolves to G2
    assert nearest_game(dh, _to_epoch("2026-08-15T20:40Z")).game_id == "espn:mlb:401816600"
    # far outside tolerance -> None, never a silent nearest
    assert nearest_game(dh, _to_epoch("2026-08-16T17:10Z")) is None
    # exact midpoint is a TIE -> None, never a coin flip
    mid = (dh[0].start_utc + dh[1].start_utc) // 2
    assert nearest_game(dh, mid, tolerance_s=10_000) is None

    assert _to_epoch("2026-08-15T17:10Z") == 1786813800
    print("schedule.espn selftest OK")


if __name__ == "__main__":
    selftest()

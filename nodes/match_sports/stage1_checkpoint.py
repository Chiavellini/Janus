#!/usr/bin/env python3
"""Stage 1 checkpoint: does the entity + schedule spine actually resolve venue markets to games?

WHAT IS AND IS NOT BEING MEASURED
─────────────────────────────────
MEASURED — the RESOLUTION rate: given a venue's own rendering of a market, can we land it on a
`game_id` from the external schedule? A failure here is our bug (an alias hole, a bad time field,
a broken key).

NOT MEASURED — the CO-LISTING rate: what fraction of scheduled games both venues quote. That is
Stage 2's pre-registered gate (coverage >= 0.80, precision >= 0.98 against hand-labelled pairs),
and its criteria are immutable once written. Co-listing counts are printed here as CONTEXT ONLY
and must not be quoted as a Stage-2 result — reading them is free, but tuning the matcher against
them would burn the gate before it is registered.

The denominator is the SCHEDULE, never the matcher's own output. A matcher that scores itself on
the pairs it managed to find always reports ~100%.

TIME FIELDS: WHICH ONE IS THE START
───────────────────────────────────
Both venues carry several timestamps and most of them are not the start.

  Kalshi   `close_time` / `expiration_time` / `latest_expiration_time` are start + ~3 DAYS — a
           postponement buffer, matching the rules text "will remain open and close after the
           rescheduled game has finished (within two days)". `expected_expiration_time` and
           `occurrence_datetime` are the expected END. The start is carried in the event ticker
           (`KXMLBGAME-26AUG171340STLCING1` -> Aug 17, 13:40 ET) and stated in English in
           `rules_primary`. Using close_time as the start puts every game three days late.

  Polymarket  the SLUG DATE IS NOT THE GAME DATE. `mlb-stl-cin-2026-05-24` was played
           2026-08-17: PM mints a slug once and keeps it when a game is postponed, while Kalshi
           re-mints on the new date with a doubleheader marker. `markets[].gameStartTime` and
           `startTime` carry the truth (2026-08-17T17:40:00Z), and they agree with Kalshi's
           ticker time exactly.

Consequence, and the reason this is worth the words: a slug/ticker-date join would drop precisely
the POSTPONED games — which are exactly the games where the settlement wedge is largest, because
postponement is the mode where venue rulesets diverge most (LFMP vs void-at-par). The bias would
be invisible and would point the wrong way.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from nodes.entities.resolve import Resolver, normalize
from nodes.entities.seed import KALSHI_GAME_SERIES, NON_TEAM_OUTCOMES, PM_TAG
from kernel.fetch import Client
from nodes.schedule_espn import espn

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA = "https://gamma-api.polymarket.com"

#: Kalshi event ticker: KXMLBGAME-26AUG171340STLCING1 / KXNFLGAME-26AUG20LVHOU
#: The time block (HHMM) is present on MLB (needed for doubleheaders) and absent elsewhere.
TICKER_RE = re.compile(r"^(?P<series>KX[A-Z0-9]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})"
                       r"(?P<hhmm>\d{4})?(?P<rest>.*)$")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

#: Kalshi's `rules_primary` states the start in English, e.g.
#: "originally scheduled for Aug 17, 2026 at 1:40 PM EDT". This is the AUTHORITATIVE start, and
#: unlike the ticker it carries an explicit timezone.
RULES_TIME_RE = re.compile(
    r"scheduled for\s+(?P<mon>[A-Z][a-z]{2})\w*\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+at\s+"
    r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>[AP]M)\s*(?P<tz>[A-Z]{3,4})")
TZ_OFFSETS = {"EDT": -4, "EST": -5, "CDT": -5, "CST": -6, "MDT": -6, "MST": -7,
              "PDT": -7, "PST": -8, "UTC": 0, "GMT": 0, "BST": 1}


#: Date-only form, which is what every league EXCEPT MLB uses:
#: "originally scheduled for Aug 20, 2026, then the market resolves to Yes."
#: Only MLB states a clock time, because only MLB needs one — doubleheaders put two games of the
#: same matchup on the same date. Everywhere else (team pair, local date) is already unique.
RULES_DATE_RE = re.compile(
    r"scheduled for\s+(?P<mon>[A-Z][a-z]{2})\w*\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})")

#: Kalshi states dates in US Eastern. Verified against MLB, whose rules carry an explicit EDT.
VENUE_TZ = ZoneInfo("America/New_York")


def kalshi_start_from_rules(rules: str) -> int | None:
    """Exact scheduled start from Kalshi's rules text, when it states a clock time.

    Returns None when the text is date-only — which is the NORMAL case outside MLB. None here
    means "use the date path", not "failed".
    """
    m = RULES_TIME_RE.search(rules or "")
    if not m:
        return None
    mon = MONTHS.get(m.group("mon").upper())
    off = TZ_OFFSETS.get(m.group("tz"))
    if mon is None or off is None:
        return None
    h = int(m.group("h")) % 12 + (12 if m.group("ampm") == "PM" else 0)
    dt = datetime(int(m.group("year")), mon, int(m.group("day")), h, int(m.group("m")),
                  tzinfo=timezone(timedelta(hours=off)))
    return int(dt.timestamp())


def kalshi_date_from_rules(rules: str) -> date | None:
    """Scheduled LOCAL date from the rules text. The authoritative date for non-MLB leagues."""
    m = RULES_DATE_RE.search(rules or "")
    if not m:
        return None
    mon = MONTHS.get(m.group("mon").upper())
    if mon is None:
        return None
    return date(int(m.group("year")), mon, int(m.group("day")))


def games_on_local_date(candidates: Sequence[espn.ScheduledGame], d: date):
    """Games from this matchup whose start falls on local date `d` in the venue's timezone.

    Returns the single match, or None if zero or MORE THAN ONE. More than one is a genuine
    doubleheader with no clock time to separate them, and picking either would be a coin flip.
    """
    hits = [g for g in candidates
            if datetime.fromtimestamp(g.start_utc, VENUE_TZ).date() == d]
    return hits[0] if len(hits) == 1 else None


def kalshi_date_from_ticker(ticker: str) -> tuple[int, int, int, int | None] | None:
    """(year, month, day, hhmm-as-int-or-None) in the venue's LOCAL date space."""
    m = TICKER_RE.match(ticker or "")
    if not m or m.group("mon") not in MONTHS:
        return None
    hhmm = int(m.group("hhmm")) if m.group("hhmm") else None
    return 2000 + int(m.group("yy")), MONTHS[m.group("mon")], int(m.group("dd")), hhmm


# ── venue pulls ──────────────────────────────────────────────────────────────

def pull_kalshi(league: str, client: Client) -> list[dict]:
    series = KALSHI_GAME_SERIES[league]
    out = []
    for status in ("open", "unopened"):
        try:
            d = client.get_json(f"{KALSHI_BASE}/events",
                                params={"series_ticker": series, "status": status,
                                        "limit": 200, "with_nested_markets": "true"},
                                use_cache=False)
        except Exception:  # noqa: BLE001
            continue
        for e in d.get("events") or []:
            out.append(e)
    return out


def pull_pm(league: str, client: Client) -> list[dict]:
    out = []
    for off in range(0, 1500, 100):
        try:
            d = client.get_json(f"{PM_GAMMA}/events",
                                params={"tag_slug": PM_TAG[league], "closed": "false",
                                        "limit": 100, "offset": off}, use_cache=False)
        except Exception:  # noqa: BLE001
            break
        if not d:
            break
        out += d
        if len(d) < 100:
            break
    return out


def _pm_start(ev: dict) -> int | None:
    """PM's authoritative start. Prefer the per-market gameStartTime, fall back to startTime."""
    for m in ev.get("markets") or []:
        gs = m.get("gameStartTime")
        if gs:
            try:
                return int(datetime.strptime(str(gs)[:19], "%Y-%m-%d %H:%M:%S")
                           .replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                pass
    st = ev.get("startTime")
    if st:
        try:
            return int(datetime.strptime(st, "%Y-%m-%dT%H:%M:%SZ")
                       .replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None
    return None


# ── the checkpoint ───────────────────────────────────────────────────────────

def run(league: str, days: int, out_dir: Path | None = None) -> dict:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)

    games = espn.fetch_range(league, start, end, use_cache=False)
    by_pair = espn.index_by_participants(games)
    print(f"schedule: {len(games)} {league} games in [{start:%Y-%m-%d}, {end:%Y-%m-%d})")

    r = Resolver.load()
    kc = Client("kalshi", rate=4.0, burst=8.0)
    pc = Client("polymarket", rate=4.0, burst=8.0)

    stats: Counter = Counter()
    matched_games: dict[str, set[str]] = defaultdict(set)
    failures: list[dict] = []

    # ── Kalshi ───────────────────────────────────────────────────────────
    for ev in pull_kalshi(league, kc):
        mkts = [m for m in (ev.get("markets") or [])
                if normalize(m.get("yes_sub_title") or "") not in NON_TEAM_OUTCOMES]
        if not mkts:
            continue
        ents = set()
        for m in mkts:
            cs = m.get("custom_strike") or {}
            uuid = next((v for v in cs.values() if isinstance(v, str) and len(v) >= 32), None)
            res = r.resolve(league, text=m.get("yes_sub_title"),
                            venue="kalshi", venue_team_id=uuid)
            if res.ok:
                ents.add(res.entity_id)
        stats["kalshi_events"] += 1
        if len(ents) != 2:
            stats["kalshi_entity_fail"] += 1
            failures.append({"venue": "kalshi", "id": ev.get("event_ticker"),
                             "reason": f"resolved_{len(ents)}_entities", "title": ev.get("title")})
            continue
        rules = (mkts[0].get("rules_primary") or "") + " " + (mkts[0].get("rules_secondary") or "")
        espn_ids = tuple(sorted(_espn_ids(r, ents)))
        cands = by_pair.get(espn_ids, [])

        # Path A — an exact clock time (MLB). Path B — a local date (everyone else).
        st = kalshi_start_from_rules(rules)
        if st is not None:
            method, g = "exact_time", espn.nearest_game(cands, st)
        else:
            d = kalshi_date_from_rules(rules)
            if d is None:
                stats["kalshi_no_start"] += 1
                failures.append({"venue": "kalshi", "id": ev.get("event_ticker"),
                                 "reason": "no_date_in_rules", "title": ev.get("title")})
                continue
            method, g = "local_date", games_on_local_date(cands, d)

        if g is None:
            # Distinguish "outside our window" (expected, not a failure) from a real miss: if the
            # matchup has no candidate games at all in the window, the event is simply for a game
            # we did not fetch.
            if not cands:
                stats["kalshi_out_of_window"] += 1
                continue
            stats["kalshi_in_window"] += 1
            stats["kalshi_no_game"] += 1
            failures.append({"venue": "kalshi", "id": ev.get("event_ticker"),
                             "reason": f"no_scheduled_game_via_{method}",
                             "title": ev.get("title")})
            continue
        if not (start.timestamp() <= g.start_utc < end.timestamp()):
            stats["kalshi_out_of_window"] += 1
            continue
        stats["kalshi_in_window"] += 1
        stats[f"kalshi_via_{method}"] += 1
        stats["kalshi_resolved"] += 1
        matched_games[g.game_id].add("kalshi")

    # ── Polymarket ───────────────────────────────────────────────────────
    for ev in pull_pm(league, pc):
        teams = ev.get("teams") or []
        if len(teams) != 2:
            continue
        stats["pm_events"] += 1
        ents = set()
        for t in teams:
            res = r.resolve(league, text=t.get("name"), venue="polymarket",
                            venue_team_id=str(t.get("id") or ""))
            if res.ok:
                ents.add(res.entity_id)
        if len(ents) != 2:
            stats["pm_entity_fail"] += 1
            failures.append({"venue": "polymarket", "id": ev.get("slug"),
                             "reason": f"resolved_{len(ents)}_entities", "title": ev.get("title")})
            continue
        st = _pm_start(ev)
        if st is None:
            stats["pm_no_start"] += 1
            failures.append({"venue": "polymarket", "id": ev.get("slug"),
                             "reason": "no_start_time", "title": ev.get("title")})
            continue
        if not (start.timestamp() <= st < end.timestamp()):
            stats["pm_out_of_window"] += 1
            continue
        stats["pm_in_window"] += 1
        espn_ids = tuple(sorted(_espn_ids(r, ents)))
        g = espn.nearest_game(by_pair.get(espn_ids, []), st)
        if g is None:
            stats["pm_no_game"] += 1
            failures.append({"venue": "polymarket", "id": ev.get("slug"),
                             "reason": "no_scheduled_game_at_that_time", "title": ev.get("title"),
                             "start_utc": datetime.fromtimestamp(st, timezone.utc).isoformat()})
            continue
        stats["pm_resolved"] += 1
        matched_games[g.game_id].add("polymarket")

    def rate(res: int, denom: int) -> float:
        return round(res / denom, 4) if denom else 0.0

    result = {
        "league": league,
        "window_utc": [start.isoformat(), end.isoformat()],
        "scheduled_games": len(games),
        "kalshi": {
            "events_seen": stats["kalshi_events"],
            "in_window": stats["kalshi_in_window"],
            "resolved_to_game": stats["kalshi_resolved"],
            "resolution_rate": rate(stats["kalshi_resolved"], stats["kalshi_in_window"]),
            "entity_fail": stats["kalshi_entity_fail"], "no_start": stats["kalshi_no_start"],
            "no_game": stats["kalshi_no_game"],
            "via_exact_time": stats["kalshi_via_exact_time"],
            "via_local_date": stats["kalshi_via_local_date"],
        },
        "polymarket": {
            "events_seen": stats["pm_events"],
            "in_window": stats["pm_in_window"],
            "resolved_to_game": stats["pm_resolved"],
            "resolution_rate": rate(stats["pm_resolved"], stats["pm_in_window"]),
            "entity_fail": stats["pm_entity_fail"], "no_start": stats["pm_no_start"],
            "no_game": stats["pm_no_game"],
        },
        # CONTEXT ONLY — not the Stage-2 gate. See module docstring.
        "context_colisting": {
            "games_with_kalshi": sum(1 for v in matched_games.values() if "kalshi" in v),
            "games_with_pm": sum(1 for v in matched_games.values() if "polymarket" in v),
            "games_with_both": sum(1 for v in matched_games.values() if len(v) == 2),
        },
        "failures": failures[:60],
        "failure_total": len(failures),
    }
    print(json.dumps({k: v for k, v in result.items() if k != "failures"}, indent=1))
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"stage1_{league}.json").write_text(json.dumps(result, indent=1))
    return result


def _espn_ids(r: Resolver, entity_ids: set[str]) -> list[str]:
    return [r.teams[e].espn_id for e in entity_ids if e in r.teams]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    run(a.league, a.days, a.out)

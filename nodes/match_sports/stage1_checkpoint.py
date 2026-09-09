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
from nodes.entities.leagues import kalshi_series
from kernel.fetch import Client, HttpError, OffsetCap
from nodes.schedule_espn import espn

KALSHI_GAME_SERIES = kalshi_series()
NON_TEAM_OUTCOMES = {"tie", "draw", "no winner"}

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

class VenuePullError(RuntimeError):
    """A venue enumeration was not complete enough to be called successful."""

    def __init__(self, message: str, *, diagnostics=None):
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class PulledEvents(list):
    """List-compatible venue result with machine-readable enumeration diagnostics."""

    def __init__(self, events=(), *, diagnostics=None):
        super().__init__(events)
        self.diagnostics = dict(diagnostics or {})


def _event_identity(event: dict) -> tuple[str, str]:
    return str(event.get("id") or ""), str(event.get("slug") or "")


def _merge_records(left: dict, right: dict) -> dict:
    """Merge sparse representations without replacing a non-empty field."""
    out = dict(left)
    for key, value in right.items():
        if key not in out or out[key] in (None, "", [], {}):
            out[key] = value
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge_records(out[key], value)
        elif isinstance(out[key], list) and isinstance(value, list):
            combined = list(out[key])
            for item in value:
                match = next((i for i, old in enumerate(combined)
                              if isinstance(old, dict) and isinstance(item, dict)
                              and ((old.get("id") and old.get("id") == item.get("id"))
                                   or (old.get("slug") and old.get("slug") == item.get("slug")))), None)
                if match is not None:
                    combined[match] = _merge_records(combined[match], item)
                elif item not in combined:
                    combined.append(item)
            out[key] = combined
    return out


def _normal_critical(value):
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            return _normal_critical(json.loads(value))
        except ValueError:
            pass
    if isinstance(value, dict):
        return tuple(sorted((str(k), _normal_critical(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_normal_critical(v) for v in value)
    return value


def _critical_fields(event: dict, venue: str) -> dict[str, object]:
    """Only fields that can change game identity, executable markets, fees, or settlement."""
    flat: dict[str, object] = {}

    def put(path: str, value) -> None:
        if value not in (None, "", [], {}):
            flat[path] = _normal_critical(value)

    if venue == "polymarket":
        for key in ("id", "slug", "startTime", "resolutionSource"):
            put(f"event.{key}", event.get(key))
        for i, team in enumerate(event.get("teams") or []):
            if not isinstance(team, dict):
                continue
            ident = str(team.get("id") or f"index:{i}")
            for key in ("id", "providerId", "name", "abbreviation"):
                put(f"team.{ident}.{key}", team.get(key))
        for i, market in enumerate(event.get("markets") or []):
            if not isinstance(market, dict):
                continue
            ident = str(market.get("id") or market.get("slug") or f"index:{i}")
            for key in ("id", "slug", "sportsMarketType", "gameStartTime", "outcomes", "clobTokenIds",
                        "description", "resolutionSource", "feeSchedule", "orderMinSize", "minimumTickSize"):
                put(f"market.{ident}.{key}", market.get(key))
    else:
        for key in ("event_ticker", "series_ticker"):
            put(f"event.{key}", event.get(key))
        for i, market in enumerate(event.get("markets") or []):
            if not isinstance(market, dict):
                continue
            ident = str(market.get("ticker") or f"index:{i}")
            for key in ("ticker", "market_type", "strike_type", "yes_sub_title", "no_sub_title",
                        "custom_strike", "rules_primary", "rules_secondary"):
                put(f"market.{ident}.{key}", market.get(key))
    return flat


def _critical_conflicts(left: dict, right: dict, venue: str) -> list[str]:
    a, b = _critical_fields(left, venue), _critical_fields(right, venue)
    out = [path for path in a.keys() & b.keys() if a[path] != b[path]]
    if venue == "polymarket":
        ids: dict[str, set[str]] = defaultdict(set)
        slugs: dict[str, set[str]] = defaultdict(set)
        for event in (left, right):
            for market in event.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                ident, slug = str(market.get("id") or ""), str(market.get("slug") or "")
                if ident and slug:
                    ids[ident].add(slug)
                    slugs[slug].add(ident)
        out += [f"market.id:{ident}" for ident, values in ids.items() if len(values) > 1]
        out += [f"market.slug:{slug}" for slug, values in slugs.items() if len(values) > 1]
    return sorted(out)


def _pm_representation_conflicts(events: list[dict]) -> list[str]:
    ids: dict[str, set[str]] = defaultdict(set)
    slugs: dict[str, set[str]] = defaultdict(set)
    for event in events:
        ident, slug = _event_identity(event)
        if ident and slug:
            ids[ident].add(slug)
            slugs[slug].add(ident)
    out = [f"id:{ident}->{','.join(sorted(values))}" for ident, values in ids.items() if len(values) > 1]
    out += [f"slug:{slug}->{','.join(sorted(values))}" for slug, values in slugs.items() if len(values) > 1]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        groups[_event_identity(event)].append(event)
    for (ident, slug), representations in groups.items():
        team_sets = {tuple(sorted(str(t.get("id")) for t in (event.get("teams") or [])
                                  if isinstance(t, dict) and t.get("id") is not None))
                     for event in representations if event.get("teams")}
        starts = {tuple(sorted({str(m.get("gameStartTime")) for m in (event.get("markets") or [])
                                if isinstance(m, dict) and m.get("sportsMarketType") == "moneyline"
                                and m.get("gameStartTime")}))
                  for event in representations if event.get("markets")}
        label = f"id:{ident}" if ident else f"slug:{slug}"
        if len(team_sets) > 1:
            out.append(f"{label}:team_ids_disagree")
        if len(starts) > 1:
            out.append(f"{label}:start_times_disagree")
    return sorted(out)


def _normalize_pm_event(event: dict) -> tuple[dict, list[str]]:
    """Merge complementary duplicate markets inside one event; reject identity contradictions.

    This must run even for the first event representation. Cross-selector comparison alone cannot
    see two contradictory records already present in that representation's own `markets` array.
    """
    markets = event.get("markets")
    if markets is None:
        return dict(event), []
    if not isinstance(markets, list) or any(not isinstance(market, dict) for market in markets):
        return {}, ["event.markets:malformed"]
    merged: list[dict] = []
    for market in markets:
        ident, slug = str(market.get("id") or ""), str(market.get("slug") or "")
        if not ident and not slug:
            return {}, ["market:missing_identity"]
        matches = [i for i, old in enumerate(merged)
                   if (ident and ident == str(old.get("id") or ""))
                   or (slug and slug == str(old.get("slug") or ""))]
        if not matches:
            merged.append(market)
            continue
        first = matches[0]
        combined = merged[first]
        for other in [market] + [merged[i] for i in matches[1:]]:
            # If one representation omits id (or slug), compare both records under the stable
            # identity supplied by its duplicate. Otherwise their critical-field paths differ
            # (`market.<id>` vs `market.<slug>`) and contradictory tokens evade intersection.
            left_cmp, right_cmp = dict(combined), dict(other)
            for key in ("id", "slug"):
                canonical = left_cmp.get(key) or right_cmp.get(key)
                if canonical:
                    if not left_cmp.get(key):
                        left_cmp[key] = canonical
                    if not right_cmp.get(key):
                        right_cmp[key] = canonical
            disagreement = _critical_conflicts({"markets": [left_cmp]},
                                               {"markets": [right_cmp]}, "polymarket")
            if disagreement:
                label = f"id:{ident}" if ident else f"slug:{slug}"
                return {}, [f"{label}:critical:{path}" for path in disagreement]
            combined = _merge_records(combined, other)
        merged[first] = combined
        for match in reversed(matches[1:]):
            del merged[match]
    normalized = dict(event)
    normalized["markets"] = merged
    return normalized, []


def _pm_cross_event_conflicts(left: dict, right: dict) -> list[str]:
    """Critical conflicts after aligning sparse overlapping nested-market identities.

    Missing id/slug values inherit only from a record that overlaps on the other stable key.
    Two present but different ids or slugs are never rewritten, so genuine identity
    contradictions remain visible to `_critical_conflicts`.
    """
    out = list(_critical_conflicts(left, right, "polymarket"))
    for a in left.get("markets") or []:
        for b in right.get("markets") or []:
            aid, bid = str(a.get("id") or ""), str(b.get("id") or "")
            aslug, bslug = str(a.get("slug") or ""), str(b.get("slug") or "")
            if not ((aid and aid == bid) or (aslug and aslug == bslug)):
                continue
            a_cmp, b_cmp = dict(a), dict(b)
            for key in ("id", "slug"):
                canonical = a_cmp.get(key) or b_cmp.get(key)
                if canonical:
                    if not a_cmp.get(key):
                        a_cmp[key] = canonical
                    if not b_cmp.get(key):
                        b_cmp[key] = canonical
            out.extend(_critical_conflicts({"markets": [a_cmp]},
                                           {"markets": [b_cmp]}, "polymarket"))
    return sorted(set(out))


def _merge_pm_events(events: list[dict]) -> tuple[list[dict], list[str]]:
    normalized_events: list[dict] = []
    for event in events:
        normalized, conflicts = _normalize_pm_event(event)
        if conflicts:
            ident, slug = _event_identity(event)
            label = f"id:{ident}" if ident else f"slug:{slug}"
            return [], [f"{label}:{conflict}" for conflict in conflicts]
        normalized_events.append(normalized)
    events = normalized_events
    conflicts = _pm_representation_conflicts(events)
    if conflicts:
        return [], conflicts
    merged: list[dict] = []
    for event in events:
        ident, slug = _event_identity(event)
        matches = [i for i, old in enumerate(merged)
                   if (ident and ident == _event_identity(old)[0])
                   or (slug and slug == _event_identity(old)[1])]
        if not matches:
            merged.append(event)
            continue
        first = matches[0]
        disagreement = _pm_cross_event_conflicts(merged[first], event)
        if disagreement:
            label = f"id:{ident}" if ident else f"slug:{slug}"
            return [], [f"{label}:critical:{path}" for path in disagreement]
        combined = _merge_records(merged[first], event)
        for match in matches[1:]:
            disagreement = _pm_cross_event_conflicts(combined, merged[match])
            if disagreement:
                label = f"id:{ident}" if ident else f"slug:{slug}"
                return [], [f"{label}:critical:{path}" for path in disagreement]
            combined = _merge_records(combined, merged[match])
        merged[first] = combined
        for match in reversed(matches[1:]):
            del merged[match]
    return merged, []


def _kalshi_pages(series: str, status: str, client: Client, *, max_pages: int) -> list[dict]:
    out: list[dict] = []
    cursor = None
    seen_cursors: set[str] = set()
    for _page in range(max_pages):
        params = {"series_ticker": series, "status": status, "limit": 200,
                  "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        d = client.get_json(f"{KALSHI_BASE}/events", params=params, use_cache=False)
        if not isinstance(d, dict) or not isinstance(d.get("events"), list):
            raise VenuePullError(f"kalshi {series}/{status} page is malformed")
        for event in d["events"]:
            if not isinstance(event, dict) or not event.get("event_ticker"):
                raise VenuePullError(f"kalshi {series}/{status} event is malformed")
            markets = event.get("markets")
            if not isinstance(markets, list):
                raise VenuePullError(f"kalshi {series}/{status} event markets are malformed")
            if any(not isinstance(market, dict) or not market.get("ticker") for market in markets):
                raise VenuePullError(f"kalshi {series}/{status} market is malformed")
        out.extend(d["events"])
        nxt = d.get("cursor")
        if not nxt:
            return out
        if not isinstance(nxt, str) or nxt in seen_cursors:
            raise VenuePullError(f"kalshi {series}/{status} cursor is malformed or repeated")
        seen_cursors.add(nxt)
        cursor = nxt
    raise VenuePullError(f"kalshi {series}/{status} exceeded {max_pages} pages")


def _pm_pages(selector: str, value: str | int, client: Client, *, max_pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(max_pages):
        d = client.get_json(f"{PM_GAMMA}/events",
                            params={selector: value, "closed": "false", "limit": 100,
                                    "offset": page * 100}, use_cache=False)
        if not isinstance(d, list):
            raise VenuePullError(f"polymarket {selector}={value} page is not a list")
        if any(not isinstance(event, dict) or not any(_event_identity(event)) for event in d):
            raise VenuePullError(f"polymarket {selector}={value} event is malformed")
        out.extend(d)
        if len(d) < 100:
            return out
    raise VenuePullError(f"polymarket {selector}={value} exceeded {max_pages} pages")


def pull_kalshi(league: str, client: Client, *, max_pages: int = 1000) -> PulledEvents:
    """Every open and unopened event of every Kalshi series the league owns, following the
    cursor: one page of 200 silently cut college football's tail until 2026-09-07."""
    from nodes.entities.leagues import LEAGUES
    series_all = LEAGUES[league].kalshi_series_all if league in LEAGUES else (KALSHI_GAME_SERIES[league],)
    out = []
    diagnostics = {"venue": "kalshi", "league": league, "selectors": {}, "errors": {}}
    for series in series_all:
        for status in ("open", "unopened"):
            key = f"{series}:{status}"
            try:
                got = _kalshi_pages(series, status, client, max_pages=max_pages)
            except (HttpError, OffsetCap, OSError, RuntimeError, ValueError, KeyError) as exc:
                diagnostics["errors"][key] = f"{type(exc).__name__}: {exc}"
                raise VenuePullError(f"incomplete Kalshi pull for {league}: {key}: {exc}",
                                     diagnostics=diagnostics) from exc
            diagnostics["selectors"][key] = {"events": len(got), "complete": True}
            out.extend(got)
    merged: dict[str, dict] = {}
    market_owners: dict[str, str] = {}
    for event in out:
        ticker = str(event.get("event_ticker") or "")
        # A nested market ticker is a stable venue identity. It may be repeated verbatim across
        # selector pages/statuses, but it may neither belong to two events nor carry two critical
        # representations within one event.
        normalized = dict(event)
        markets: dict[str, dict] = {}
        for market in event["markets"]:
            market_ticker = str(market["ticker"])
            owner = market_owners.setdefault(market_ticker, ticker)
            if owner != ticker:
                path = f"market:{market_ticker}:owners:{owner},{ticker}"
                diagnostics["errors"][f"market:{market_ticker}"] = path
                raise VenuePullError(f"conflicting Kalshi representations for {league}: {path}",
                                     diagnostics=diagnostics)
            if market_ticker in markets:
                disagreement = _critical_conflicts(
                    {"event_ticker": ticker, "markets": [markets[market_ticker]]},
                    {"event_ticker": ticker, "markets": [market]}, "kalshi")
                if disagreement:
                    paths = ", ".join(disagreement)
                    diagnostics["errors"][f"market:{market_ticker}"] = (
                        f"critical fields disagree: {paths}")
                    raise VenuePullError(
                        f"conflicting Kalshi representations for {league} {market_ticker}: {paths}",
                        diagnostics=diagnostics)
                markets[market_ticker] = _merge_records(markets[market_ticker], market)
            else:
                markets[market_ticker] = market
        normalized["markets"] = [markets[key] for key in sorted(markets)]
        if ticker in merged:
            disagreement = _critical_conflicts(merged[ticker], normalized, "kalshi")
            if disagreement:
                diagnostics["errors"][f"event:{ticker}"] = f"critical fields disagree: {', '.join(disagreement)}"
                raise VenuePullError(f"conflicting Kalshi representations for {league} {ticker}: "
                                     f"{', '.join(disagreement)}", diagnostics=diagnostics)
            merged[ticker] = _merge_records(merged[ticker], normalized)
        else:
            merged[ticker] = normalized
    result = [merged[k] for k in sorted(merged)]
    diagnostics.update({"events": len(result), "duplicates_merged": len(out) - len(result), "complete": True})
    return PulledEvents(result, diagnostics=diagnostics)


def pull_pm(league: str, client: Client, *, max_pages: int = 60) -> PulledEvents:
    """Complete, independently enumerated Gamma representations for one registered league."""
    from nodes.entities.leagues import LEAGUES
    lg = LEAGUES[league]
    selectors: list[tuple[str, str | int]] = []
    if lg.pm_tag_id is not None:
        selectors.append(("tag_id", lg.pm_tag_id))
    selectors.append(("tag_slug", lg.pm_tag))
    selectors = list(dict.fromkeys(selectors))
    diagnostics = {"venue": "polymarket", "league": league, "selectors": {}, "errors": {},
                   "representation_conflicts": [], "selector_disagreement": {}}
    complete: list[dict] = []
    complete_by_selector: dict[str, list[dict]] = {}
    for selector, value in selectors:
        key = f"{selector}:{value}"
        try:
            got = _pm_pages(selector, value, client, max_pages=max_pages)
        except (HttpError, OffsetCap, OSError, RuntimeError, ValueError, KeyError) as exc:
            diagnostics["errors"][key] = f"{type(exc).__name__}: {exc}"
            diagnostics["selectors"][key] = {"events": 0, "complete": False}
            continue
        diagnostics["selectors"][key] = {"events": len(got), "complete": True}
        complete_by_selector[key] = got
        complete.extend(got)
    if not any(v["complete"] for v in diagnostics["selectors"].values()):
        raise VenuePullError(f"no complete Polymarket selector for {league}: {diagnostics['errors']}",
                             diagnostics=diagnostics)
    merged, conflicts = _merge_pm_events(complete)
    diagnostics["representation_conflicts"] = conflicts
    if conflicts:
        raise VenuePullError(f"conflicting Polymarket representations for {league}: {'; '.join(conflicts)}",
                             diagnostics=diagnostics)
    if len(complete_by_selector) > 1:
        keys = list(complete_by_selector)
        def identities(events):
            return {f"id:{ident}" if ident else f"slug:{slug}" for ident, slug in map(_event_identity, events)}
        a, b = identities(complete_by_selector[keys[0]]), identities(complete_by_selector[keys[1]])
        diagnostics["selector_disagreement"] = {
            "selectors": keys, "only_first": sorted(a - b), "only_second": sorted(b - a)}
    diagnostics.update({"events": len(merged), "complete": not diagnostics["errors"],
                        "degraded": bool(diagnostics["errors"])})
    return PulledEvents(merged, diagnostics=diagnostics)


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

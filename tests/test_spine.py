#!/usr/bin/env python3
"""Stage 1 regression tests: schedule spine + entity resolution.

Every test here is OFFLINE. The pure-parse functions are tested against frozen fixtures shaped
like real payloads, and one test actively asserts that parsing performs no network I/O — the
`normalize() MUST BE PURE` rule in lib/venues/base.py applies to the spine too, and a rule nobody
checks is a comment.
"""

from __future__ import annotations


import pytest
from datetime import date, datetime, timezone
from pathlib import Path


from catalog.stage1_checkpoint import (  # noqa: E402
    games_on_local_date, kalshi_date_from_rules, kalshi_date_from_ticker,
    kalshi_start_from_rules,
)
from lib.entities.resolve import (  # noqa: E402
    Resolver, Team, build_alias_index, load_alias_rows, load_teams, load_xrefs, normalize,
)
from lib.schedule import espn  # noqa: E402

# ── module selftests ─────────────────────────────────────────────────────────

def test_schedule_espn_selftest():
    espn.selftest()


def test_entities_resolve_selftest():
    from lib.entities import resolve
    resolve.selftest()


# ── the shipped data tables ──────────────────────────────────────────────────

def test_seeded_tables_load_and_are_consistent():
    teams = load_teams()
    assert len(teams) >= 150, f"only {len(teams)} teams seeded"
    xrefs = load_xrefs()          # raises on any colliding venue id
    assert len(xrefs) >= 150, f"only {len(xrefs)} xrefs"
    # every xref points at a team that exists
    unknown = {e for e in xrefs.values() if e not in teams}
    assert not unknown, f"xrefs reference unknown entities: {sorted(unknown)[:5]}"
    # every alias points at a team that exists (this is what catches a typo'd manual row)
    rows = load_alias_rows()
    bad = {r["entity_id"] for r in rows if r["entity_id"] not in teams}
    assert not bad, f"aliases reference unknown entities: {sorted(bad)[:5]}"


def test_manual_alias_overlay_is_actually_loaded():
    """The overlay is a separate file precisely so the seeder cannot clobber it. If loading ever
    silently drops it, the three known abbreviation divergences come back."""
    idx = build_alias_index(load_alias_rows())
    r = Resolver(load_teams(), idx, load_xrefs())
    # Kalshi says CWS / JAC / WAS; ESPN says CHW / JAX / WSH
    assert r.by_text("mlb", "CWS").entity_id == "mlb:chicago-white-sox"
    assert r.by_text("nfl", "JAC").entity_id == "nfl:jacksonville-jaguars"
    assert r.by_text("nfl", "WAS").entity_id == "nfl:washington-commanders"
    # and the ESPN spellings still work
    assert r.by_text("mlb", "CHW").entity_id == "mlb:chicago-white-sox"
    assert r.by_text("nfl", "JAX").entity_id == "nfl:jacksonville-jaguars"


def test_real_ambiguities_refuse_to_resolve():
    """Six alias keys are genuinely ambiguous in the seeded corpus. Every one must refuse.

    Kalshi renders MLB teams by location only, so "New York" arrives as a real query — not a
    hypothetical. Guessing here manufactures a pair between two unrelated markets, which reads as
    an enormous edge and sorts to the top of any ranked list.
    """
    r = Resolver(load_teams(), build_alias_index(load_alias_rows()), load_xrefs())
    for lg, txt, n in [("mlb", "New York", 2), ("mlb", "Los Angeles", 2), ("mlb", "Chicago", 2),
                       ("nfl", "New York", 2), ("nfl", "Los Angeles", 2), ("nhl", "New York", 2)]:
        res = r.by_text(lg, txt)
        assert not res.ok, f"{lg}/{txt!r} resolved to {res.entity_id} — must refuse"
        assert res.reason == "ambiguous"
        assert len(res.ambiguous_among) == n, f"{lg}/{txt!r} -> {res.ambiguous_among}"


def test_no_short_alias_for_a_shared_location_city():
    """Guards the exact false alias this table nearly shipped.

    An alias was auto-derived from co-occurrence with an exact venue id: nfl "la" -> Rams, n=4.
    It looked unambiguous only because the Chargers had not yet appeared with that label. "LA"
    denotes either LA club, and a wrong entity does not make a slightly-wrong pair — it makes a
    pair of unrelated markets whose price gap reads as an enormous edge.

    RULE: a short code (<=3 chars) is trustworthy only when its team's location is unique within
    the league. Long forms ("LA Rams") are self-disambiguating and exempt, as are rows a human
    verified against observed venue output (source starting "manual_").
    """
    import collections
    import csv as _csv
    from lib.entities.resolve import ALIASES_MANUAL_CSV
    teams = load_teams()
    shared = collections.Counter((t.league, normalize(t.location)) for t in teams.values())
    offenders = []
    with ALIASES_MANUAL_CSV.open(newline="", encoding="utf-8") as fh:
        for row in _csv.DictReader(fh):
            if str(row.get("source", "")).startswith("manual_"):
                continue                       # human-verified, exempt by design
            t = teams.get(row["entity_id"])
            n = normalize(row["alias"])
            if t and len(n) <= 3 and shared[(row["league"], normalize(t.location))] > 1:
                offenders.append((row["league"], row["alias"], row["entity_id"], t.location))
    assert not offenders, f"ambiguous short aliases present: {offenders}"


def test_xref_beats_an_ambiguous_label():
    """The whole point of carrying venue team ids: an exact id rescues an ambiguous label."""
    r = Resolver(load_teams(), build_alias_index(load_alias_rows()), load_xrefs())
    kalshi_mlb = [(v, e) for (v, _), e in r.xrefs.items() if v == "kalshi"]
    assert kalshi_mlb, "no kalshi xrefs seeded"
    (venue, tid), want = next(((k, v) for k, v in r.xrefs.items()
                               if k[0] == "kalshi" and v.startswith("mlb:new-york")), ((None, None), None))
    if want:  # only if a NY club is currently listed
        got = r.resolve("mlb", text="New York", venue=venue, venue_team_id=tid)
        assert got.entity_id == want and got.method == "xref"


# ── Kalshi time parsing: the trap that puts every game 3 days late ───────────

def test_kalshi_exact_time_parsed_from_mlb_rules():
    rules = ("If St. Louis wins the St. Louis vs Cincinnati professional baseball game 1 of the "
             "double header originally scheduled for Aug 17, 2026 at 1:40 PM EDT, then the market "
             "resolves to Yes.")
    got = kalshi_start_from_rules(rules)
    assert got is not None
    assert datetime.fromtimestamp(got, timezone.utc).isoformat() == "2026-08-17T17:40:00+00:00", \
        datetime.fromtimestamp(got, timezone.utc).isoformat()


def test_kalshi_date_only_rules_are_not_a_failure():
    """Every league except MLB states a date and no clock. That is the normal case, not a miss."""
    rules = ("If HOU Texans wins the Las Vegas vs Houston Pro Football game originally scheduled "
             "for Aug 20, 2026, then the market resolves to Yes.")
    assert kalshi_start_from_rules(rules) is None       # no clock time present
    assert kalshi_date_from_rules(rules) == date(2026, 8, 20)


def test_close_time_is_start_plus_three_days_not_the_start():
    """THE TRAP. Kalshi's close_time/expiration_time are a postponement buffer, ~3 days past the
    start. A join keyed on close_time puts every game three days late and matches nothing."""
    rules = ("game originally scheduled for Aug 17, 2026 at 1:40 PM EDT")
    start = kalshi_start_from_rules(rules)
    close = int(datetime(2026, 8, 20, 17, 40, tzinfo=timezone.utc).timestamp())  # observed live
    assert close - start == 3 * 86400, (close - start)


def test_ticker_date_parses_with_and_without_a_time_block():
    assert kalshi_date_from_ticker("KXMLBGAME-26AUG171340STLCING1") == (2026, 8, 17, 1340)
    assert kalshi_date_from_ticker("KXNFLGAME-26AUG20LVHOU") == (2026, 8, 20, None)
    assert kalshi_date_from_ticker("garbage") is None


# ── doubleheaders and local-date matching ────────────────────────────────────

def _dh_fixture():
    payload = {"events": [
        {"id": "1", "date": "2026-08-17T17:40Z", "name": "a", "shortName": "a",
         "season": {"slug": "regular-season"}, "status": {"type": {"state": "pre"}},
         "competitions": [{"competitors": [
             {"homeAway": "home", "team": {"id": "CIN", "displayName": "Cincinnati Reds"}},
             {"homeAway": "away", "team": {"id": "STL", "displayName": "St. Louis Cardinals"}}]}]},
        {"id": "2", "date": "2026-08-17T21:10Z", "name": "b", "shortName": "b",
         "season": {"slug": "regular-season"}, "status": {"type": {"state": "pre"}},
         "competitions": [{"competitors": [
             {"homeAway": "home", "team": {"id": "CIN", "displayName": "Cincinnati Reds"}},
             {"homeAway": "away", "team": {"id": "STL", "displayName": "St. Louis Cardinals"}}]}]},
    ]}
    return espn.parse_scoreboard(payload, "mlb")


def test_exact_time_separates_a_doubleheader():
    gs = _dh_fixture()
    cands = espn.index_by_participants(gs)[("CIN", "STL")]
    t1 = kalshi_start_from_rules("scheduled for Aug 17, 2026 at 1:40 PM EDT")
    t2 = kalshi_start_from_rules("scheduled for Aug 17, 2026 at 5:10 PM EDT")
    assert espn.nearest_game(cands, t1).game_id == "espn:mlb:1"
    assert espn.nearest_game(cands, t2).game_id == "espn:mlb:2"


def test_local_date_REFUSES_a_doubleheader():
    """Date-only matching cannot separate two games on the same date, so it must return None.

    This is why MLB is the one league whose rules text carries a clock time — and why the
    date path is safe for the leagues that use it."""
    gs = _dh_fixture()
    cands = espn.index_by_participants(gs)[("CIN", "STL")]
    assert games_on_local_date(cands, date(2026, 8, 17)) is None, "must refuse an ambiguous date"
    # a single-game date resolves fine
    assert games_on_local_date(cands[:1], date(2026, 8, 17)).game_id == "espn:mlb:1"


def test_late_game_local_date_uses_eastern_not_utc():
    """A 10pm-Pacific game is the NEXT DAY in UTC but the same day in Eastern, which is how Kalshi
    dates it. Matching on the UTC date would miss every West Coast night game."""
    payload = {"events": [
        {"id": "9", "date": "2026-08-18T02:10Z", "name": "n", "shortName": "n",
         "season": {"slug": "regular-season"}, "status": {"type": {"state": "pre"}},
         "competitions": [{"competitors": [
             {"homeAway": "home", "team": {"id": "GS", "displayName": "Golden State"}},
             {"homeAway": "away", "team": {"id": "DAL", "displayName": "Dallas"}}]}]}]}
    gs = espn.parse_scoreboard(payload, "wnba")
    assert datetime.fromtimestamp(gs[0].start_utc, timezone.utc).date() == date(2026, 8, 18)
    assert games_on_local_date(gs, date(2026, 8, 17)).game_id == "espn:wnba:9"   # Eastern
    assert games_on_local_date(gs, date(2026, 8, 18)) is None


# ── purity ───────────────────────────────────────────────────────────────────

def test_parsing_performs_no_network_io():
    """The spine's parse path must not touch the network.

    This used to install its own socket guard for the duration of one test. That guard now lives
    in the repo-root conftest as an autouse fixture covering EVERY test, so this asserts two
    things: that the global guard is genuinely armed (a fixture nobody verifies is a fixture that
    can silently stop working -- the same class of bug as the swallowing @check harness these
    files used to use), and that the parse path runs clean underneath it.
    """
    import socket
    with pytest.raises(AssertionError, match="network access"):
        socket.socket()

    espn.parse_scoreboard({"events": []}, "mlb")
    _dh_fixture()
    normalize("St. Louis Cardinals")
    Resolver(load_teams(), build_alias_index(load_alias_rows()), load_xrefs()) \
        .by_text("mlb", "Cardinals")
    kalshi_start_from_rules("scheduled for Aug 17, 2026 at 1:40 PM EDT")


def test_parse_is_deterministic_across_repeat_calls():
    """The phase-1 determinism gate, applied to the spine."""
    a = [g.__dict__ for g in _dh_fixture()]
    b = [g.__dict__ for g in _dh_fixture()]
    assert a == b

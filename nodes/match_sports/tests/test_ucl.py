"""Shared clubs must still anchor independently onto the exact UCL competition."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nodes.entities.resolve import Resolver, Team, build_alias_index
from nodes.match_sports import sports_match as sm
from nodes.schedule_espn.espn import ScheduledGame, index_by_participants, parse_scoreboard


def inputs():
    start = int(datetime(2026, 9, 9, 19, tzinfo=timezone.utc).timestamp())
    game = ScheduledGame("espn:ucl:123", "ucl", start, "359", "86", "Arsenal", "Real Madrid",
                         "pre", False, False, False, "league-phase", "RMA @ ARS", "Real Madrid at Arsenal")
    entities = [Team("epl:eng.arsenal", "epl", "359", "ARS", "Arsenal", "Arsenal", "Arsenal"),
                Team("lal:esp.real_madrid", "lal", "86", "RMA", "Real Madrid", "Real Madrid", "Real Madrid")]
    aliases = [{"league": "ucl", "alias": t.display_name, "entity_id": t.entity_id} for t in entities]
    xrefs = {("kalshi", str(i) * 36): t.entity_id for i, t in enumerate(entities, 1)}
    xrefs.update({("polymarket", str(i)): t.entity_id for i, t in enumerate(entities, 1)})
    resolver = Resolver({t.entity_id: t for t in entities}, build_alias_index(aliases), xrefs)
    rules = "game originally scheduled for Sep 9, 2026 at 3:00 PM EDT"
    event = {"event_ticker": "KXUCLGAME-26SEP09ARSRMA", "markets": [
        {"ticker": "KXUCLGAME-26SEP09ARSRMA-ARS", "yes_sub_title": "Arsenal FC",
         "custom_strike": {"soccer_team": "1" * 36}, "rules_primary": rules},
        {"ticker": "KXUCLGAME-26SEP09ARSRMA-RMA", "yes_sub_title": "Real Madrid CF",
         "custom_strike": {"soccer_team": "2" * 36}, "rules_primary": rules},
        {"ticker": "KXUCLGAME-26SEP09ARSRMA-TIE", "yes_sub_title": "Tie", "rules_primary": rules}]}
    slug = "ucl-ars-rma-2026-09-09"
    pm = {"slug": slug, "teams": [
        {"id": "1", "name": "Arsenal", "abbreviation": "ars"},
        {"id": "2", "name": "Real Madrid", "abbreviation": "rea"}],
        "markets": [{"slug": slug, "gameStartTime": "2026-09-09 19:00:00+00"},
                    {"slug": slug + "-draw", "gameStartTime": "2026-09-09 19:00:00+00"}]}
    return resolver, game, event, pm


def matched(monkeypatch, games, *, event=None, pm=None, resolver=None):
    r, _, k, p = inputs()
    monkeypatch.setattr(sm, "pull_kalshi", lambda *args: [event or k])
    stats = Counter(k_reason=Counter(), p_reason=Counter())
    index = index_by_participants(games)
    near = []
    kms = sm.kalshi_markets("ucl", resolver or r, index, (0, 4_000_000_000), stats, near)
    pms = sm.pm_markets("ucl", resolver or r, index, (0, 4_000_000_000), stats, near, events=[pm or p])
    return kms, pms, sm.pair(kms, pms), stats


def test_ucl_three_way_joins_shared_domestic_clubs_only_to_ucl(monkeypatch):
    _, game, _, _ = inputs()
    domestic = replace(game, league="epl", game_id="espn:epl:other")
    k, p, pairs, _ = matched(monkeypatch, [domestic, game])
    assert len(k) == len(p) == len(pairs) == 3
    assert {row["entity_id"] for row in pairs} == {"epl:eng.arsenal", "lal:esp.real_madrid", sm.DRAW_ENTITY}
    assert all(row["game_id"] == game.game_id and row["canonical_key"]["league"] == "ucl" for row in pairs)
    assert all(row["canonical_key"]["participants"] == ["359", "86"] for row in pairs)


@pytest.mark.parametrize("negative", ["domestic", "missing", "outside_tolerance", "ambiguous_schedule"])
def test_ucl_schedule_hard_negatives_fail_closed(monkeypatch, negative):
    _, game, _, _ = inputs()
    games = {"domestic": [replace(game, league="epl", game_id="espn:epl:123")],
             "missing": [],
             "outside_tolerance": [replace(game, start_utc=game.start_utc + 86400)],
             "ambiguous_schedule": [game, replace(game, game_id="espn:ucl:duplicate")]}
    k, p, pairs, _ = matched(monkeypatch, games[negative])
    assert k == p == pairs == []


@pytest.mark.parametrize("venue", ["kalshi", "polymarket"])
def test_ucl_missing_draw_cannot_pair(monkeypatch, venue):
    _, game, k, p = inputs()
    if venue == "kalshi":
        k["markets"] = k["markets"][:-1]
    else:
        p["markets"] = p["markets"][:-1]
    _, _, pairs, stats = matched(monkeypatch, [game], event=k, pm=p)
    assert pairs == []
    assert stats["k_reason" if venue == "kalshi" else "p_reason"]["no_draw_market"] == 1


def test_ucl_derivative_event_is_not_full_game(monkeypatch):
    _, game, _, p = inputs()
    p["slug"] += "-total-2pt5"
    _, pm, pairs, stats = matched(monkeypatch, [game], pm=p)
    assert pm == pairs == []
    assert stats["p_reason"]["derivative_event_not_full_game_moneyline"] == 1


def test_ucl_ambiguous_participant_is_not_guessed(monkeypatch):
    r, game, k, p = inputs()
    r.xrefs.clear()
    r.alias_index[("ucl", "united")] = sorted(r.teams)
    for market in k["markets"][:2]:
        market["yes_sub_title"] = "United"
    for team in p["teams"]:
        team["name"] = "United"
    k, p, pairs, stats = matched(monkeypatch, [game], event=k, pm=p, resolver=r)
    assert k == p == pairs == []
    assert stats["k_reason"]["entity_resolution"] == stats["p_reason"]["entity_resolution"] == 1


FROZEN_UCL = json.loads((Path(__file__).parent / "fixtures" / "ucl_20260909_10.json").read_text())


def frozen_inputs():
    """Project frozen identity facts into parser-shaped payloads; rules here test time parsing only.

    The compact fixture preserves observed game/participant identities and starts. Its synthetic
    rule sentence and draw payload shape are matcher fixtures, not settlement-certification evidence.
    """
    schedule, kalshi, polymarket = [], [], []
    for row in FROZEN_UCL["games"]:
        e, k, p = row["espn"], row["kalshi"], row["polymarket"]
        start = datetime.fromisoformat(row["start"])
        schedule.append({"id": e["id"], "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                         "season": {"slug": "league-phase"},
                         "competitions": [{"competitors": [
                             {"homeAway": "home", "team": {"id": e["home_id"], "displayName": e["home"]}},
                             {"homeAway": "away", "team": {"id": e["away_id"], "displayName": e["away"]}}]}]})
        local = start.astimezone(ZoneInfo("America/New_York"))
        rule = f"game originally scheduled for {local.strftime('%b %d, %Y at %I:%M %p %Z')}"
        markets = []
        for i, label in enumerate(k["labels"]):
            uuid = (k.get("uuids") or [None, None])[i]
            markets.append({"ticker": f"{k['event']}-SIDE{i}", "yes_sub_title": label,
                            "custom_strike": {"soccer_team": uuid} if uuid else {}, "rules_primary": rule})
        markets.append({"ticker": k["event"] + "-TIE", "yes_sub_title": "Tie", "rules_primary": rule})
        kalshi.append({"event_ticker": k["event"], "markets": markets})
        polymarket.append({**p, "markets": [
            {"slug": p["slug"], "gameStartTime": row["start"]},
            {"slug": p["slug"] + "-draw", "gameStartTime": row["start"]}]})
    return parse_scoreboard({"events": schedule}, "ucl"), kalshi, polymarket


def test_frozen_all_twelve_ucl_games_resolve_both_venues_and_three_outcomes(monkeypatch):
    frozen = FROZEN_UCL["games"]
    assert Counter(row["date"] for row in frozen) == {"2026-09-09": 6, "2026-09-10": 6}
    games, kalshi, pm = frozen_inputs()
    assert len(games) == 12
    r = Resolver.load()
    for row in frozen:
        expected = [row["espn"]["home_id"], row["espn"]["away_id"]]
        for i, label in enumerate(row["kalshi"]["labels"]):
            uuid = (row["kalshi"].get("uuids") or [None, None])[i]
            found = r.resolve("ucl", text=label, venue="kalshi", venue_team_id=uuid)
            assert found.ok, (row["kalshi"]["event"], label)
            assert r.teams[found.entity_id].espn_id == expected[i]
        for i, team in enumerate(row["polymarket"]["teams"]):
            found = r.resolve("ucl", text=team["name"], venue="polymarket", venue_team_id=team["id"])
            assert found.ok, (row["polymarket"]["slug"], team)
            assert r.teams[found.entity_id].espn_id == expected[i]
    monkeypatch.setattr(sm, "pull_kalshi", lambda *args: kalshi)
    stats = Counter(k_reason=Counter(), p_reason=Counter())
    index, near = index_by_participants(games), []
    kms = sm.kalshi_markets("ucl", r, index, (0, 4_000_000_000), stats, near)
    pms = sm.pm_markets("ucl", r, index, (0, 4_000_000_000), stats, near, events=pm)
    pairs = sm.pair(kms, pms)
    assert len(kms) == len(pms) == len(pairs) == 36
    assert not near and not stats["k_reason"] and not stats["p_reason"]
    for row in frozen:
        gid = "espn:ucl:" + row["espn"]["id"]
        found = [p for p in pairs if p["game_id"] == gid]
        assert len(found) == 3
        assert sum(p["entity_id"] == sm.DRAW_ENTITY for p in found) == 1
        for pair in found:
            assert pair["kalshi_event"] == row["kalshi"]["event"]
            assert pair["pm_event"] == row["polymarket"]["slug"]
            key = pair["canonical_key"]
            assert key["league"] == "ucl" and key["period"] == "game" and key["market_type"] == "moneyline"
            assert key["participants"] == sorted([row["espn"]["home_id"], row["espn"]["away_id"]])
            assert key["start_utc"] == int(datetime.fromisoformat(row["start"]).timestamp())


def test_frozen_twelve_ucl_derivatives_and_absent_schedule_never_pair(monkeypatch):
    games, kalshi, pm = frozen_inputs()
    r = Resolver.load()
    stats = Counter(k_reason=Counter(), p_reason=Counter())
    derivatives = [{**event, "slug": event["slug"] + "-total-2pt5"} for event in pm]
    assert sm.pm_markets("ucl", r, index_by_participants(games), (0, 4_000_000_000), stats, [], events=derivatives) == []
    assert stats["p_reason"]["derivative_event_not_full_game_moneyline"] == 12
    monkeypatch.setattr(sm, "pull_kalshi", lambda *args: kalshi)
    assert sm.kalshi_markets("ucl", r, {}, (0, 4_000_000_000), stats, []) == []
    assert sm.pm_markets("ucl", r, {}, (0, 4_000_000_000), stats, [], events=pm) == []


def test_frozen_twelve_game_report_counts_three_way_coverage(monkeypatch, tmp_path):
    games, kalshi, pm = frozen_inputs()
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 9, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sm, "datetime", FrozenClock)
    monkeypatch.setattr(sm.espn, "fetch_range", lambda *args, **kwargs: games)
    monkeypatch.setattr(sm, "pull_kalshi", lambda *args: kalshi)
    monkeypatch.setattr(sm, "pull_pm", lambda *args: pm)
    result = sm.run("ucl", days=2, out_dir=tmp_path)
    assert result["scheduled_games"] == 12
    assert result["outcome_pairs_emitted"] == 36
    assert result["coverage"]["eligible_games_both_venues"] == 12
    assert result["coverage"]["completely_paired_games"] == 12
    assert result["coverage"]["coverage"] == 1.0


@pytest.mark.parametrize("league,outcome_count,complete", [("mlb", 2, 1), ("ucl", 2, 0), ("ucl", 3, 1), ("ucl", 4, 0)])
def test_report_requires_exact_registered_outcome_count(monkeypatch, tmp_path, league, outcome_count, complete):
    from kernel.schema import CanonicalKey
    key = CanonicalKey(league, ("a", "b"), 1_800_000_000, "moneyline", "game")
    sides = ["a", "b", sm.DRAW_ENTITY, "extra"][:outcome_count]
    def markets(venue):
        return [sm.VenueMarket(venue, "event", "event:" + side, "game", side, "moneyline", "game",
                               key.start_utc, side, key=key) for side in sides]
    monkeypatch.setattr(sm.espn, "fetch_range", lambda *args, **kwargs: [])
    monkeypatch.setattr(sm, "kalshi_markets", lambda *args: markets("kalshi"))
    monkeypatch.setattr(sm, "pm_markets", lambda *args: markets("polymarket"))
    result = sm.run(league, days=2, out_dir=tmp_path)
    assert result["coverage"]["eligible_games_both_venues"] == 1
    assert result["coverage"]["completely_paired_games"] == complete

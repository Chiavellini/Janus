from __future__ import annotations

import json
from pathlib import Path

from collectors.cloudbet_sports import (
    add_accepted_cloudbet_legs, add_cloudbet_legs, discover_joined,
    record_accepted_cloudbet_leg,
)
from collectors.tuple_store import TupleStore
from lib.entities.resolve import Resolver, Team, build_alias_index
from lib.schedule.espn import ScheduledGame
from lib.venues.cloudbet import event_start_utc, event_status, iter_event_markets
from lib.venues.cloudbet_trading import AcceptanceState, CloudbetAcceptance
from screen.cover import Leg


FIXTURES = Path(__file__).parent / "fixtures" / "cloudbet"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_documented_keyed_market_shape_preserves_line_identity():
    items = list(iter_event_markets(fixture("mlb_live.json"), fetched_utc=1000.0))
    assert {(i.market_key, i.submarket_key) for i in items} == {
        ("baseball.moneyline", "period=ot&period=ft"),
        ("baseball.totals", "period=ot&period=ft"),
    }
    moneyline = next(i for i in items if i.market_key == "baseball.moneyline")
    assert [s.market_url for s in moneyline.selections] == [
        "baseball.moneyline/home", "baseball.moneyline/away"
    ]
    assert all(s.selection_id.startswith("7001001:") for s in moneyline.selections)
    assert event_status(moneyline.event) == "TRADING_LIVE"
    assert event_start_utc(moneyline.event) == 1788390300


def test_all_league_fixture_shapes_parse_and_three_way_is_not_two_way():
    nfl = list(iter_event_markets(fixture("nfl_upcoming.json"), fetched_utc=1.0))
    nba = list(iter_event_markets(fixture("nba_newborn.json"), fetched_utc=1.0))
    epl = list(iter_event_markets(fixture("epl_three_way.json"), fetched_utc=1.0))
    assert len(nfl) == len(nba) == 1
    assert len(epl[0].selections) == 3
    assert {s.outcome for s in epl[0].selections} == {"home", "draw", "away"}


def test_unknown_or_suspended_fields_fail_closed():
    assert list(iter_event_markets(fixture("malformed_and_suspended.json"), fetched_utc=1.0)) == []


def _resolver() -> Resolver:
    teams = {
        "mlb:bos": Team("mlb:bos", "mlb", "2", "BOS", "Boston", "Red Sox", "Boston Red Sox"),
        "mlb:nyy": Team("mlb:nyy", "mlb", "10", "NYY", "New York", "Yankees", "New York Yankees"),
    }
    aliases = build_alias_index([
        {"league": "mlb", "alias": "Boston Red Sox", "entity_id": "mlb:bos"},
        {"league": "mlb", "alias": "New York Yankees", "entity_id": "mlb:nyy"},
    ])
    return Resolver(teams, aliases, {})


def _schedule_game() -> ScheduledGame:
    return ScheduledGame(
        game_id="espn:mlb:401", league="mlb", start_utc=1788390300,
        home_espn="2", away_espn="10", home_name="Boston Red Sox",
        away_name="New York Yankees", state="in", completed=False,
        neutral_site=False, was_suspended=False, season_slug="regular-season",
        short_name="NYY @ BOS", name="New York Yankees at Boston Red Sox",
    )


def test_discovery_joins_cloudbet_to_schedule_without_title_matching():
    result = discover_joined(
        [("baseball-usa-mlb", fixture("mlb_live.json"))], [_schedule_game()],
        league="mlb", resolver=_resolver(), market_keys=("baseball.moneyline",),
    )
    assert len(result.matches) == 1
    assert result.matches[0].game.game_id == "espn:mlb:401"
    assert result.matches[0].market.market_key == "baseball.moneyline"
    assert not result.blocked


def test_join_maps_home_away_to_canonical_entities_and_keeps_feed_nonexecutable():
    item = next(iter(iter_event_markets(fixture("mlb_live.json"), fetched_utc=1000.0)))
    offers = {"mlb:bos": (), "mlb:nyy": ()}
    joined = add_cloudbet_legs(offers, item, resolver=_resolver(), league="mlb")
    assert joined.ok
    assert {leg.outcome_id for legs in joined.offers.values() for leg in legs} == {"mlb:bos", "mlb:nyy"}
    assert all(not leg.executable for legs in joined.offers.values() for leg in legs)


def test_accepted_cloudbet_legs_are_the_only_ones_wired_to_cover_and_store(tmp_path):
    item = next(iter(iter_event_markets(fixture("mlb_live.json"), fetched_utc=1000.0)))
    resolver = _resolver()
    offers = {"mlb:bos": (), "mlb:nyy": ()}
    acceptances = {
        s.selection_id: CloudbetAcceptance(
            reference_id=f"00000000-0000-4000-8000-{i:012d}", state=AcceptanceState.ACCEPTED,
            event_id=s.event_id, market_url=s.market_url, requested_price=s.decimal_odds,
            requested_stake=10.0, currency="PLAY_EUR", accepted_price=s.decimal_odds,
            accepted_stake=10.0, provider_status="ACCEPTED", observed_utc=1000.0,
        )
        for i, s in enumerate(item.selections, 1)
    }
    joined = add_accepted_cloudbet_legs(offers, item, resolver=resolver, league="mlb",
                                        acceptances=acceptances)
    assert joined.ok
    assert all(leg.executable for legs in joined.offers.values() for leg in legs)
    assert {leg.outcome_id for legs in joined.offers.values() for leg in legs} == {"mlb:bos", "mlb:nyy"}

    store = TupleStore(tmp_path / "tuples.sqlite", enforce_volume=False)
    market_id, changed = record_accepted_cloudbet_leg(
        store, item.selections[0], next(iter(acceptances.values())),
        game_id="espn:mlb:401", league="mlb", seen_ts=1000.0,
    )
    assert changed
    assert store.con.execute("SELECT status FROM latest_markets WHERE market_id=?", (market_id,)).fetchone()[0] == "ACCEPTED"
    assert abs(store.con.execute("SELECT best_ask FROM latest_quotes WHERE market_id=?", (market_id,)).fetchone()[0] - 1 / 2.1) < 1e-12
    store.close()

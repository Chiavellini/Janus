from __future__ import annotations

from pathlib import Path


from nodes.venue_kalshi.books import kalshi_book  # noqa: E402
from nodes.venue_cloudbet.join import add_cloudbet_legs  # noqa: E402
from nodes.entities.resolve import Resolver  # noqa: E402
from kernel.schema import liquidity_source_for  # noqa: E402
from kernel.venue_registry import names  # noqa: E402
from nodes.venue_cloudbet.feed import (  # noqa: E402
    CloudbetAdapter,
    CloudbetFeedClient,
    cloudbet_book,
    cloudbet_leg,
    iter_event_markets,
    parse_selection,
)
from nodes.rules_exhaustive.rules import prove
from nodes.cover.cover import Leg, REJECT_NOT_EXECUTABLE, best_cover  # noqa: E402

#: A genuine proof from the mlb_no_draw rule. `ExhaustiveOutcomeSet` cannot be forged, so a test
#: asserting exhaustiveness goes through the same gate production does.
MLB2 = prove("mlb", "moneyline", "game", ["a", "b"])



EVENT = {
    "id": "cb-1",
    "name": "Away FC v Home FC",
    "status": "TRADING_LIVE",
    "cutoffTime": "2026-09-01T20:00:00Z",
    "markets": [{
        "marketKey": "baseball.moneyline",
        "submarkets": [{
            "submarketKey": "game",
            "selections": [
                {"id": "home", "outcome": "Home FC", "side": "BACK", "status": "SELECTION_ENABLED",
                 "price": "2.00", "minStake": "1", "maxStake": "100"},
                {"id": "away", "outcome": "Away FC", "side": "BACK", "status": "SELECTION_ENABLED",
                 "price": "2.10", "minStake": "1", "maxStake": "50"},
                {"id": "disabled", "outcome": "Draw", "side": "BACK", "status": "SUSPENDED",
                 "price": "4.00", "minStake": "1", "maxStake": "50"},
                {"id": "lay", "outcome": "Home FC", "side": "LAY", "status": "SELECTION_ENABLED",
                 "price": "1.01", "minStake": "1", "maxStake": "50"},
            ],
        }],
    }],
}


def test_cloudbet_back_selection_is_one_sided_payout_depth():
    item = next(iter(iter_event_markets(EVENT, fetched_utc=1000.0)))
    assert len(item.selections) == 2
    selection = item.selections[0]
    assert selection.price == 0.5
    assert selection.contracts == 200.0
    book = cloudbet_book(selection)
    assert book.bids == ()
    assert book.one_sided is True
    assert book.best_ask.price == 0.5
    assert book.best_ask.size == 200.0


def test_cloudbet_feed_quote_is_not_executable_until_acceptance():
    selection = next(iter(iter_event_markets(EVENT, fetched_utc=1000.0))).selections[0]
    leg = cloudbet_leg(selection)
    assert leg.executable is False
    offers = {
        "Home FC": [leg],
        "Away FC": [Leg("kalshi", "kalshi_clob", "away", "K", kalshi_book(
            {"orderbook_fp": {"yes_dollars": [[0.40, 500]], "no_dollars": [[0.40, 500]]}},
            "yes", 1000.0))],
    }
    assert best_cover(offers, 10, now_utc=1000.0, exhaustive=MLB2).reject_reason == REJECT_NOT_EXECUTABLE

    accepted = selection.accepted_offer(10.0, odds=2.0)
    cover = best_cover({
        "Home FC": [cloudbet_leg(accepted)],
        "Away FC": [offers["Away FC"][0]],
    }, 10, now_utc=1000.0, exhaustive=MLB2)
    assert cover.ok
    assert {leg.venue for leg in cover.legs} == {"cloudbet", "kalshi"}


def test_cloudbet_is_independent_and_registered():
    assert liquidity_source_for("cloudbet") == "cloudbet_sportsbook"
    assert "cloudbet" in names()


def test_cloudbet_normalizes_without_inventing_exhaustiveness_or_rules():
    normalized = CloudbetAdapter().normalize({**EVENT, "_janus_fetched_utc": 1000.0})
    assert normalized is not None
    assert normalized.venue_market_id == "cb-1:baseball.moneyline:game"
    assert normalized.proof is None
    assert normalized.key is None
    assert normalized.settle_ref.provenance == "assumed"
    assert all(outcome.book.one_sided for outcome in normalized.outcomes)


def test_cloudbet_client_keeps_key_in_header():
    class FakeClient:
        def __init__(self):
            self.args = None

        def get_json(self, *args, **kwargs):
            self.args = (args, kwargs)
            return {"sports": []}

    fake = FakeClient()
    CloudbetFeedClient("test-key", client=fake).sports()
    args, kwargs = fake.args
    assert args[0].endswith("/odds/sports")
    assert kwargs["headers"]["X-API-Key"] == "test-key"
    assert "test-key" not in args[0]


def test_cloudbet_feed_tier_controls_tradeable_quality():
    class FakeFeed:
        data_quality = "live"

        def event(self, event_id):
            assert event_id == "cb-1"
            return EVENT

    adapter = CloudbetAdapter(feed=FakeFeed())
    market = adapter.normalize({**EVENT, "_janus_fetched_utc": 1000.0})
    books = adapter.quote([market])
    assert adapter.tradeable() is True
    assert len(books) == 2
    assert all(book.one_sided for book in books.values())

    delayed = CloudbetFeedClient("test-key", feed_tier="affiliate")
    assert delayed.data_quality == "delayed"


def test_cloudbet_join_requires_exact_schedule_outcome_set():
    item = next(iter(iter_event_markets(EVENT, fetched_utc=1000.0)))
    resolver = Resolver(alias_index={
        ("mlb", "home"): ["mlb:home"],
        ("mlb", "away"): ["mlb:away"],
    })
    offers = {"mlb:home": (), "mlb:away": ()}
    joined = add_cloudbet_legs(offers, item, resolver=resolver, league="mlb")
    assert joined.ok
    assert all(joined.offers[e][0].venue == "cloudbet" for e in offers)
    assert all(joined.offers[e][0].executable is False for e in offers)

    mismatch = add_cloudbet_legs({"mlb:home": ()}, item, resolver=resolver, league="mlb")
    assert mismatch.ok is False
    assert "OUTCOME_SET_MISMATCH" in mismatch.blocked_reason

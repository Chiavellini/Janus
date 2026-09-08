from kernel.execution_protocol import OrderRequest
from kernel.schema import Book, FillState, Mode, Quote
from nodes.execution.journal import Journal
from nodes.execution.paper import PaperVenue, RefusingVenue
from nodes.execution.testing import clearance_for
from nodes.store_tuples.store import TupleStore

T = 1000.0


def _req(side, price, n, cid):
    return OrderRequest("polymarket", "tok", "tok", side, price, n, "ioc", cid, "o1", hedge=side.startswith("sell"))


def test_a_paper_sell_hits_the_bids_from_the_best_down_and_reduces_the_position(tmp_path):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    v = PaperVenue("polymarket", j, clock=lambda: T, balance_usd=100.0)
    v.books["tok"] = Book(bids=(Quote(0.55, 6.0), Quote(0.53, 20.0)), asks=(Quote(0.57, 50.0),), fetched_utc=T)
    c = clearance_for(tmp_path)                       # one clearance: the buy is its first leg, the sells its protective legs
    a = v.submit(_req("buy_yes", 0.57, 10.0, "b1"), c)
    assert a.state is FillState.FILLED and v.positions()[0].contracts == 10.0 and v.balance_usd == 100.0 - 5.7
    s = v.submit(_req("sell_yes", 0.53, 10.0, "s1"), c)
    assert s.state is FillState.FILLED and abs(s.avg_price - (6 * 0.55 + 4 * 0.53) / 10) < 1e-9
    assert v.positions() == [] and abs(v.balance_usd - (100.0 - 5.7 + 6 * 0.55 + 4 * 0.53)) < 1e-9
    assert [q.size for q in v.orderbook("tok", "sell_yes").bids] == [16.0], "the bids were consumed"
    # a sell below its floor takes nothing
    v.books["tok"] = Book(bids=(Quote(0.50, 6.0),), asks=(), fetched_utc=T)
    u = v.submit(_req("sell_yes", 0.53, 5.0, "s2"), c)
    assert u.state is FillState.UNFILLED and u.filled_contracts == 0.0
    assert [f.side for f in v.fills(since_utc=0)] == ["buy_yes", "sell_yes"] and v.fills(since_utc=0)[1].market_id == "tok"


def test_the_refusing_venue_reads_nothing():
    r = RefusingVenue("kalshi", None) if RefusingVenue.__dataclass_fields__.get("journal") else None
    if r is not None:
        assert r.orderbook("K") is None and list(r.positions()) == []

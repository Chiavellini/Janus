"""The unwind proof's steps on a paper venue: buy the minimum, sell it back, the venue agrees."""
from types import SimpleNamespace

from kernel.schema import Book, Mode, Quote
from nodes.execution.journal import Journal
from nodes.execution.paper import PaperVenue
from nodes.execution.testing import clearance_for
from nodes.store_tuples.store import TupleStore
from ops.unwind_proof import execute_steps

T = 1000.0


def _venue(tmp_path, bids, asks):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    v = PaperVenue("polymarket", j, mode=Mode.LIMITED_LIVE, clock=lambda: T, mono=lambda: 100.1, balance_usd=100.0)
    book = Book(bids=tuple(Quote(p, s) for p, s in bids), asks=tuple(Quote(p, s) for p, s in asks), fetched_utc=T)
    v.books["tok"] = book
    return v


def test_a_round_trip_at_the_touch_passes_every_check(tmp_path):
    v = _venue(tmp_path, bids=[(0.43, 50)], asks=[(0.45, 50)])
    c = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=100.0)
    cand = SimpleNamespace(opportunity_id=c.opportunity_id)
    proof = execute_steps(v, market_id="tok", outcome_id="tok", size=5.0, ask=0.45, bid=0.43, tick=0.01, cand=cand, clearance=c,
                          balance_before=v.balance(), runner_sha="t", override_sha=None, sleep=lambda s: None, poll_step=0.0,
                          confirm_wait_s=0.0, mono=lambda: 100.5)
    assert proof["ok"] and proof["stop"] is None, proof["checks"]
    assert proof["steps"][0]["bought"] == 5.0 and proof["steps"][1]["sold"] == 5.0
    assert proof["steps"][2]["held_after"] == 0 and abs(proof["realized_usd"] - (-5 * 0.02)) < 1e-9
    assert [r[0] for r in v.journal.store.con.execute("SELECT side FROM orders ORDER BY submitted_utc")] == ["buy_yes", "sell_yes"]


def test_a_sell_that_finds_no_bid_is_a_stop_with_the_position_named(tmp_path):
    v = _venue(tmp_path, bids=[(0.30, 50)], asks=[(0.45, 50)])     # the bid is far below the price we sell at
    c = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=100.0)
    cand = SimpleNamespace(opportunity_id=c.opportunity_id)
    proof = execute_steps(v, market_id="tok", outcome_id="tok", size=5.0, ask=0.45, bid=0.43, tick=0.01, cand=cand, clearance=c,
                          balance_before=v.balance(), runner_sha="t", override_sha=None, sleep=lambda s: None, poll_step=0.0,
                          confirm_wait_s=0.0, mono=lambda: 100.5)
    assert not proof["ok"] and proof["stop"].startswith("SELL_SHORT: bought 5, sold 0")
    assert v.positions()[0].contracts == 5.0, "the position is still held: the operator closes it by hand"

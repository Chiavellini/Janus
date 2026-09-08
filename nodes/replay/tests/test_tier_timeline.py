"""The replay harness mirrors the lane's per-tier evaluation window from the recorded timeline."""
from types import SimpleNamespace

from nodes.replay.replay import Harness
from nodes.store_tuples.store import TupleStore


def test_the_timeline_moves_the_window_as_the_clock_passes_each_change(tmp_path):
    h = Harness(TupleStore(tmp_path / "r.sqlite", enforce_volume=False),
                tier_timeline={"g1": [(1000.0, "newborn"), (1500.0, "starting_soon"), (2000.0, "live")]})
    p = SimpleNamespace(min_eval_interval_s=0.2)
    h._apply_tier("g1", p, 999.0)
    assert p.min_eval_interval_s == 0.2, "nothing recorded yet: the spawn window stands"
    h._apply_tier("g1", p, 1200.0)
    assert p.min_eval_interval_s == 5.0
    h._apply_tier("g1", p, 2100.0)
    assert p.min_eval_interval_s == 0.2, "two changes passed at once: the last one wins"
    h._apply_tier("g1", p, 9999.0)
    assert p.min_eval_interval_s == 0.2 and h._tier_cursor["g1"] == 3
    h._apply_tier("g2", p, 9999.0)                       # a game with no timeline is untouched
    assert p.min_eval_interval_s == 0.2

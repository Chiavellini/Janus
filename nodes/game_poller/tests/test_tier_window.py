from nodes.game_poller.poller import EVAL_INTERVAL_BY_TIER, eval_interval_for


def test_the_window_per_tier_and_the_default():
    assert eval_interval_for("live") == 0.2 and eval_interval_for("starting_soon") == 1.0
    assert eval_interval_for("newborn") == 5.0 and eval_interval_for("long_term") == 5.0
    assert eval_interval_for(None) == 0.2 and eval_interval_for("nonsense", default=0.7) == 0.7
    assert set(EVAL_INTERVAL_BY_TIER) == {"live", "starting_soon", "newborn", "recently_listed", "closing_soon", "long_term"}

"""L53: a share-cap breach alarms independently of the protection dust threshold."""
from nodes.risk.flags import raise_flag
from nodes.risk.health import risk_alerts
from nodes.store_tuples.store import TupleStore


def test_order_overfill_has_a_watchdog_alarm_even_without_an_open_position(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    opts = dict(db_path=tmp_path / "t.sqlite", kill_root=tmp_path / "kill",
                breaker_path=tmp_path / "breaker.json", mode_conf=tmp_path / "mode.conf", now=1001)
    assert not any("ORDER_OVERFILL" in a for a in risk_alerts(**opts))
    raise_flag(store, "ORDER_OVERFILL", "F15 requested 10; venue filled 10.166667", now=1000)
    alarms = [a for a in risk_alerts(**opts) if "ORDER_OVERFILL" in a]
    assert len(alarms) == 1 and "10.166667" in alarms[0]
    assert "live entry stopped" in alarms[0]

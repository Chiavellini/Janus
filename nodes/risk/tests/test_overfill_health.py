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


def test_post_only_role_violation_remains_a_watchdog_stop(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    raise_flag(store, "POST_ONLY_ROLE_VIOLATION", "post-only order appeared as TAKER", now=1000)
    alarms = risk_alerts(db_path=tmp_path / "t.sqlite", kill_root=tmp_path / "kill",
                         breaker_path=tmp_path / "breaker.json", mode_conf=tmp_path / "mode.conf", now=1001)
    assert any("POST_ONLY_ROLE_VIOLATION" in a and "live entry stopped" in a for a in alarms)


def test_post_only_persistence_failure_remains_a_watchdog_stop(tmp_path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    raise_flag(store, "POST_ONLY_PERSISTENCE_FAILED", "status record failed after observed fill6", now=1000)
    alarms = risk_alerts(db_path=tmp_path / "t.sqlite", kill_root=tmp_path / "kill",
                         breaker_path=tmp_path / "breaker.json", mode_conf=tmp_path / "mode.conf", now=1001)
    assert any("POST_ONLY_PERSISTENCE_FAILED" in a and "live entry stopped" in a for a in alarms)


def test_legacy_order_persistence_failure_is_a_distinct_watchdog_stop(tmp_path):
    store = TupleStore(tmp_path / 't.sqlite', enforce_volume=False)
    raise_flag(store, 'ORDER_PERSISTENCE_FAILED', 'legacy IOC fallback: database is locked', now=1000)
    alarms = risk_alerts(db_path=tmp_path / 't.sqlite', kill_root=tmp_path / 'kill',
                         breaker_path=tmp_path / 'breaker.json', mode_conf=tmp_path / 'mode.conf', now=1001)
    assert any('ORDER_PERSISTENCE_FAILED' in a and 'live entry stopped' in a for a in alarms)
    assert not any('POST_ONLY_PERSISTENCE_FAILED' in a for a in alarms)

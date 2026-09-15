import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from nodes.discovery.discovery import EVENTS_DDL
from nodes.exec_polymarket.post_only import POST_ONLY_DDL
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.opportunity.opportunity import OPPORTUNITY_DDL
from nodes.reconcile.settle_executions import SETTLEMENTS_DDL, VENUE_RESULTS_DDL
from nodes.risk.flags import FLAGS_DDL
from nodes.risk.ledger import LEDGER_DDL
from nodes.store_tuples.store import TupleStore
from ops.box import settle_held_cover as helper


def test_direct_path_invocation_imports_from_outside_repo(tmp_path):
    script = Path(helper.__file__).resolve()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        (sys.executable, str(script), "--help"),
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def _fixture(tmp_path: Path):
    db = tmp_path / "tuples.sqlite"
    st = TupleStore(db, enforce_volume=False)
    for ddl in (EVENTS_DDL, OPPORTUNITY_DDL, EXECUTION_DDL, JOURNAL_DDL, SETTLEMENTS_DDL,
                VENUE_RESULTS_DDL, POST_ONLY_DDL, FLAGS_DDL, LEDGER_DDL):
        st.ensure_ddl(ddl)
    spec = {"outcomes": helper.EXPECTED_OUTCOMES}
    st.con.execute("INSERT INTO events(event_id,league,start_utc,phase,pm_slug,spec_json,first_seen_ts,last_seen_ts) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (helper.EVENT_ID, "atp", 1789000000, "post:co_listed", helper.PM_SLUG,
                    json.dumps(spec), 1789000000, 1789000000))
    st.con.execute(
        "INSERT INTO opportunities(opportunity_id,event_id,league,strategy_version,status,first_seen_ts,last_seen_ts,"
        "quantity,gross,fees,settlement_buffer,slippage_buffer,fixed_cost,net_profit,locked_return,n_max,n_star,"
        "limit_reason,slippage_modelled,blocked_by,legs_json,books_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (helper.OPPORTUNITY_ID, helper.EVENT_ID, "atp", "v1-taker-taker-moneyline", "HEDGED",
         1789000000, 1789000000, helper.QUANTITY, 0.95, 0.029743, 0.00712205, 0.0, 0.0,
         0.32837375, 0.01330977, 4889.67, 3525.06, "below_hurdle", 0, None, "[]", "{}"),
    )
    st.con.execute("INSERT INTO capital_reservations(reservation_id,event_id,league,per_venue_json,opportunity_id,created_utc) "
                   "VALUES(?,?,?,?,?,?)",
                   (helper.RESERVATION_ID, helper.EVENT_ID, "atp", json.dumps(helper.RESERVED_USD),
                    helper.OPPORTUNITY_ID, 1789000000))
    st.con.execute("INSERT INTO executions(execution_id,opportunity_id,event_id,league,mode,state,started_utc,last_utc,quantity,"
                   "first_client_id,hedge_client_ids,first_filled,first_avg_price,hedge_filled,hedge_avg_price,unhedged,"
                   "reservation_id,released) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (helper.EXECUTION_ID, helper.OPPORTUNITY_ID, helper.EVENT_ID, "atp", helper.MODE, "HEDGED",
                    1789000000, 1789000000, helper.QUANTITY, helper.FIRST_CLIENT_ID, json.dumps([helper.HEDGE_CLIENT_ID]),
                    helper.QUANTITY, helper.FIRST_PRICE, helper.QUANTITY, helper.HEDGE_PRICE, 0,
                    helper.RESERVATION_ID, 0))
    ins = ("INSERT INTO orders(client_order_id,venue,mode,market_id,outcome_id,side,price,contracts,time_in_force,"
           "opportunity_id,state,venue_order_id,filled_contracts,avg_price,fee_usd,open,settlement_pending,"
           "submitted_utc,last_utc,execution_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    st.con.execute(ins, (helper.FIRST_CLIENT_ID, "polymarket", "LIMITED_LIVE", helper.FIRST_MARKET_ID,
                         helper.FIRST_MARKET_ID, "buy_yes",
                         helper.FIRST_PRICE, helper.QUANTITY, "ioc", helper.OPPORTUNITY_ID, "FILLED", "pm-order",
                         helper.QUANTITY, helper.FIRST_PRICE, helper.FIRST_FEE, 0, 0, 1789000000, 1789000000,
                         helper.EXECUTION_ID))
    st.con.execute(ins, (helper.HEDGE_CLIENT_ID, "kalshi", "LIMITED_LIVE", helper.HEDGE_MARKET_ID,
                         helper.HEDGE_MARKET_ID, "buy_yes",
                         helper.HEDGE_PRICE, helper.QUANTITY, "ioc", helper.OPPORTUNITY_ID, "FILLED", "k-order",
                         helper.QUANTITY, helper.HEDGE_PRICE, helper.HEDGE_FEE, 0, 0, 1789000000, 1789000000,
                         helper.EXECUTION_ID))
    st.con.execute("UPDATE pm_post_only_admission SET client_order_id=NULL,claimed_utc=1789000001 WHERE slot=1")
    st.con.commit(); st.con.close()
    kill = tmp_path / "kill" / "live"
    kill.parent.mkdir()
    kill.write_bytes(b'{"reason":"registered kill"}\n')
    digest = hashlib.sha256(kill.read_bytes()).hexdigest()
    return db, kill, digest, subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()


def _run(db, kill, digest, release, tmp_path, monkeypatch, **kwargs):
    monkeypatch.setattr(helper, "EXPECTED_KILL_SHA256", digest)
    fetcher = kwargs.pop("fetcher", lambda items, client: {
        helper.EXECUTION_ID: {
            "kalshi": None, "polymarket": None,
            "kalshi_payouts": dict(helper.EXPECTED_PAYOUTS["kalshi"]),
            "polymarket_payouts": dict(helper.EXPECTED_PAYOUTS["polymarket"]),
        }})
    return helper.settle_exact(db_path=db, kill_path=kill, expected_kill_sha=digest, release_sha=release,
                               repo=Path("."), fetcher=fetcher,
                               unit_reader=kwargs.pop("unit_reader", lambda: ("inactive", "0", "0")),
                               store_factory=lambda p: TupleStore(p, enforce_volume=False), **kwargs)


def test_exact_final_results_settle_one_cover_and_release(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)
    out = _run(db, kill, digest, release, tmp_path, monkeypatch)
    assert out["status"] == "SETTLED"
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT state,released FROM executions").fetchone() == ("RECONCILED", 1)
        assert con.execute("SELECT status FROM opportunities").fetchone() == ("RECONCILED",)
        assert con.execute("SELECT COUNT(*),kind,hedged_contracts,unhedged_contracts FROM execution_settlements").fetchone() == (1, "COVER", 25.0, 0.0)
        assert con.execute("SELECT realized_usd,cover_usd,directional_usd FROM execution_settlements").fetchone() == pytest.approx(
            (helper.EXPECTED_REALIZED_USD, helper.EXPECTED_COVER_USD, 0.0))
        assert [json.loads(row[0]) for row in con.execute(
            "SELECT payouts_json FROM execution_venue_payouts ORDER BY venue").fetchall()] == [
                helper.EXPECTED_PAYOUTS["kalshi"], helper.EXPECTED_PAYOUTS["polymarket"]]
        assert con.execute("SELECT released_utc IS NOT NULL FROM capital_reservations").fetchone() == (1,)
    assert kill.exists()


def test_open_result_writes_nothing(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)
    with pytest.raises(helper.SettlementWaiting):
        _run(db, kill, digest, release, tmp_path, monkeypatch,
             fetcher=lambda items, client: {helper.EXECUTION_ID: {"kalshi": None, "polymarket": None}})
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT released FROM executions").fetchone() == (0,)
        assert con.execute("SELECT COUNT(*) FROM execution_settlements").fetchone() == (0,)


@pytest.mark.parametrize("mutation", ["identity", "economics", "extra", "extra_held", "order_identity", "wrong_payout", "kill"])
def test_adversarial_state_never_releases(tmp_path, monkeypatch, mutation):
    db, kill, digest, release = _fixture(tmp_path)
    if mutation == "identity":
        with sqlite3.connect(db) as con:
            con.execute("UPDATE executions SET opportunity_id='other'")
    elif mutation == "economics":
        with sqlite3.connect(db) as con:
            con.execute("UPDATE orders SET fee_usd=0.0 WHERE client_order_id=?", (helper.FIRST_CLIENT_ID,))
    elif mutation == "extra":
        with sqlite3.connect(db) as con:
            con.execute("UPDATE orders SET execution_id='other' WHERE client_order_id=?", (helper.HEDGE_CLIENT_ID,))
    elif mutation == "extra_held":
        with sqlite3.connect(db) as con:
            con.execute(
                "INSERT INTO executions SELECT 'extra-execution',opportunity_id,event_id,league,mode,state,started_utc,"
                "last_utc,quantity,first_client_id,hedge_client_ids,first_filled,first_avg_price,hedge_filled,"
                "hedge_avg_price,unhedged,reservation_id,released,detail,plan_json,books_json,stages_json,first_unwound,"
                "first_unwind_avg,hedge_unwound,hedge_unwind_avg,unwind_client_ids,protect_json,corrected_utc "
                "FROM executions WHERE execution_id=?",
                (helper.EXECUTION_ID,),
            )
    elif mutation == "order_identity":
        with sqlite3.connect(db) as con:
            con.execute("UPDATE orders SET time_in_force='gtc' WHERE client_order_id=?", (helper.FIRST_CLIENT_ID,))
    elif mutation == "kill":
        kill.write_bytes(b'{"reason":"new kill"}\n')
    fetcher = lambda items, client: {helper.EXECUTION_ID: {
        "kalshi": None, "polymarket": None,
        "kalshi_payouts": dict(helper.EXPECTED_PAYOUTS["kalshi"]),
        "polymarket_payouts": dict(helper.EXPECTED_PAYOUTS["polymarket"]),
    }}
    if mutation == "wrong_payout":
        fetcher = lambda items, client: {helper.EXECUTION_ID: {
            "kalshi": None, "polymarket": None,
            "kalshi_payouts": {helper.HEDGE_MARKET_ID: 0.45, helper.OTHER_KALSHI_MARKET_ID: 0.55},
            "polymarket_payouts": dict(helper.EXPECTED_PAYOUTS["polymarket"]),
        }}
    with pytest.raises((helper.SettlementBlocked, RuntimeError)):
        _run(db, kill, digest, release, tmp_path, monkeypatch, fetcher=fetcher)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT released FROM executions").fetchone() == (0,)
    assert kill.exists()


def test_write_failure_rolls_back_reservation_and_all_state(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)

    def fail_after_release(store, ledger, records, opportunities, items, winners, **kwargs):
        assert ledger.release(helper.RESERVATION_ID, reason="injected failure", now=1789000010)
        store.con.execute("UPDATE executions SET released=1 WHERE execution_id=?", (helper.EXECUTION_ID,))
        raise sqlite3.OperationalError("injected after release")

    with pytest.raises(sqlite3.OperationalError, match="injected after release"):
        _run(db, kill, digest, release, tmp_path, monkeypatch, applier=fail_after_release)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT released,state FROM executions").fetchone() == (0, "HEDGED")
        assert con.execute("SELECT released_utc FROM capital_reservations").fetchone() == (None,)
        assert con.execute("SELECT COUNT(*) FROM execution_settlements").fetchone() == (0,)
    assert kill.exists()


def test_unit_restart_during_write_rolls_back_everything(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)
    states = iter([("inactive", "0", "0"), ("inactive", "0", "0"),
                   ("inactive", "0", "0"), ("active", "123", "0")])
    with pytest.raises(helper.SettlementBlocked, match="not stopped"):
        _run(db, kill, digest, release, tmp_path, monkeypatch, unit_reader=lambda: next(states))
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT released,state FROM executions").fetchone() == (0, "HEDGED")
        assert con.execute("SELECT released_utc FROM capital_reservations").fetchone() == (None,)
        assert con.execute("SELECT COUNT(*) FROM execution_settlements").fetchone() == (0,)


def test_kill_change_during_write_rolls_back_everything(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)

    def change_kill_after_apply(*args, **kwargs):
        result = helper.apply_settlements(*args, **kwargs)
        kill.write_bytes(b'{"reason":"changed during write"}\n')
        return result

    with pytest.raises(helper.SettlementBlocked, match="kill changed"):
        _run(db, kill, digest, release, tmp_path, monkeypatch, applier=change_kill_after_apply)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT released,state FROM executions").fetchone() == (0, "HEDGED")
        assert con.execute("SELECT released_utc FROM capital_reservations").fetchone() == (None,)
        assert con.execute("SELECT COUNT(*) FROM execution_settlements").fetchone() == (0,)


def test_changed_complementary_map_blocks_before_provider_fetch(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)
    with sqlite3.connect(db) as con:
        spec = json.loads(con.execute("SELECT spec_json FROM events").fetchone()[0])
        spec["outcomes"]["atp:ilya-ivashka"]["kalshi"] = helper.HEDGE_MARKET_ID
        con.execute("UPDATE events SET spec_json=?", (json.dumps(spec),))
    with pytest.raises(helper.SettlementBlocked, match="outcome map changed"):
        _run(db, kill, digest, release, tmp_path, monkeypatch,
             fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("must not fetch")))


def test_retry_after_exact_release_does_not_fetch_or_write_again(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)
    _run(db, kill, digest, release, tmp_path, monkeypatch)
    def fail_fetch(*_):
        raise AssertionError("provider must not be fetched on exact retry")
    out = _run(db, kill, digest, release, tmp_path, monkeypatch, fetcher=fail_fetch)
    assert out["retry"] is True


def test_canonical_admission_and_missing_lifecycle_marker_predicates(tmp_path, monkeypatch):
    db, kill, digest, release = _fixture(tmp_path)
    with sqlite3.connect(db) as con:
        assert helper.l133_predicates(con) == {
            "admission_empty": True, "unresolved_post_only_violations": 0}
        con.execute("UPDATE pm_post_only_admission SET client_order_id='claimed'")
        assert helper.l133_predicates(con)["admission_empty"] is False


def test_cli_wait_is_nonzero_and_never_claims_complete(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(helper, "settle_exact", lambda **_kwargs: (_ for _ in ()).throw(
        helper.SettlementWaiting("venue open")))
    rc = helper.main(["--db", str(tmp_path / "db"), "--kill", str(tmp_path / "kill"),
                      "--expected-kill-sha", "0" * 64, "--release-sha", "0" * 40,
                      "--repo", str(tmp_path)])
    assert rc == 3
    output = capsys.readouterr().out
    assert "L136_SETTLE_WAIT" in output and "COMPLETE" not in output


@pytest.mark.parametrize("state,main,control", [("active", "0", "0"), ("inactive", "1", "0"),
                                                  ("failed", "0", "7")])
def test_stopped_unit_proof_is_fail_closed(state, main, control):
    with pytest.raises(helper.SettlementBlocked):
        helper.assert_stopped_unit(state=state, main_pid=main, control_pid=control)

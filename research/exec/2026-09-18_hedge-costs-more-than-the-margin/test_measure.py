"""Pins for L151's measurement. Every fixture is a box-shaped sqlite built here; no box is touched."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

_spec = importlib.util.spec_from_file_location("l151_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _db(tmp_path, rows):
    """rows: (league, plan_hedge_vwap|None, requested, filled, avg_price, fee, venue, mode)"""
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE executions(execution_id TEXT, league TEXT, mode TEXT, plan_json TEXT)")
    con.execute("CREATE TABLE orders(execution_id TEXT, venue TEXT, mode TEXT, contracts REAL,"
                " filled_contracts REAL, avg_price REAL, fee_usd REAL, state TEXT)")
    for i, (lg, vwap, want, got, avg, fee, venue, mode) in enumerate(rows):
        xid = f"x{i}"
        plan = json.dumps({"hedge": {"vwap": vwap}} if vwap is not None else {"hedge": None})
        con.execute("INSERT INTO executions VALUES (?,?,?,?)", (xid, lg, mode, plan))
        con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
                    (xid, venue, mode, want, got, avg, fee, "FILLED" if got else "UNFILLED"))
    con.commit()
    con.close()
    return str(p)


K = ("kalshi", "LIMITED_LIVE")


def test_slippage_is_the_fill_against_the_plans_own_hedge_vwap(tmp_path):
    db = _db(tmp_path, [("atp", 0.30, 10, 10, 0.33, 0.1, *K)])
    out = m.run(db)
    assert out["by_league"]["atp"]["slippage_c_median"] == 3.0, "3 cents worse than planned"
    assert out["pooled"]["adverse"] == 1


def test_a_hedge_that_never_filled_is_counted_separately_from_one_that_filled_dearly(tmp_path):
    """A league that cannot fill and a league that fills expensively are different failures."""
    db = _db(tmp_path, [("atp", 0.30, 10, 0, None, None, *K),
                        ("atp", 0.30, 10, 10, 0.35, 0.1, *K)])
    atp = m.run(db)["by_league"]["atp"]
    assert atp["hedge_orders"] == 2 and atp["filled_orders"] == 1 and atp["zero_fill_orders"] == 1
    assert atp["slippage_sample"] == 1, "a zero fill has no slippage, it has no fill"


def test_only_real_money_kalshi_hedges_are_counted(tmp_path):
    db = _db(tmp_path, [("atp", 0.30, 10, 10, 0.40, 0.1, "polymarket", "LIMITED_LIVE"),
                        ("atp", 0.30, 10, 10, 0.40, 0.1, "kalshi", "PAPER_EXECUTION"),
                        ("mlb", 0.30, 10, 10, 0.31, 0.1, *K)])
    out = m.run(db)
    assert list(out["by_league"]) == ["mlb"], "the first leg and paper rows are not hedge evidence"


def test_a_row_without_a_usable_plan_vwap_is_named_not_silently_dropped(tmp_path):
    db = _db(tmp_path, [("atp", None, 10, 10, 0.33, 0.1, *K)])
    out = m.run(db)
    assert out["orders_without_a_usable_plan_vwap"] == 1
    assert out["by_league"]["atp"]["filled_orders"] == 1
    assert out["by_league"]["atp"]["slippage_sample"] == 0


def test_the_verdict_compares_slippage_with_the_margin_entry_requires(tmp_path):
    """The registered rule: a locked return of 0.5% on a $1 contract is half a cent."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    dear = _db(tmp_path / "a", [("atp", 0.30, 10, 10, 0.33, 0.1, *K)] * 12)
    out = m.run(dear)
    assert out["verdict"] == "SLIPPAGE_EXCEEDS_MARGIN"
    assert "6.0x" in out["verdict_reason"], out["verdict_reason"]
    assert out["thresholds"]["required_margin_c_per_contract"] == 0.5

    cheap = _db(tmp_path / "b", [("mlb", 0.30, 10, 10, 0.3001, 0.1, *K)] * 12)
    assert m.run(cheap)["verdict"] == "MARGIN_EXCEEDS_SLIPPAGE"


def test_ten_fills_is_the_floor_for_any_verdict_at_all(tmp_path):
    db = _db(tmp_path, [("atp", 0.30, 10, 10, 0.33, 0.1, *K)] * 9)
    out = m.run(db)
    assert out["verdict"] == "TOO_FEW_FILLS" and "9 filled" in out["verdict_reason"]


def test_every_per_league_figure_carries_its_sample_size(tmp_path):
    """The spec forbids reporting a per-league figure without it."""
    db = _db(tmp_path, [("atp", 0.30, 10, 10, 0.33, 0.1, *K), ("mlb", 0.30, 10, 10, 0.31, 0.1, *K)])
    for lg, d in m.run(db)["by_league"].items():
        assert "slippage_sample" in d and "hedge_orders" in d, lg


def test_the_reader_opens_the_database_read_only(tmp_path):
    db = _db(tmp_path, [("atp", 0.30, 10, 10, 0.33, 0.1, *K)])
    m.run(db)                                       # must not raise
    src = Path(__file__).with_name("measure.py").read_text()
    assert "mode=ro" in src and "INSERT" not in src and "UPDATE" not in src

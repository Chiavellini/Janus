import sqlite3

from nodes.execute.entry_experiment import F22_DECISIONS_DDL, F23_DECISIONS_DDL
from ops.f22_report import _clustered_interval, _minimum_counts
from ops.f23_report import report


def test_f23_report_never_pools_f22_rows(tmp_path):
    db = tmp_path / "cohorts.sqlite"
    con = sqlite3.connect(db)
    con.executescript(F22_DECISIONS_DDL + F23_DECISIONS_DDL)
    con.execute(
        "INSERT INTO f22_decisions(event_id,forward_row_id,assignment_algorithm,digest,arm,sizing_input_hash,"
        "sizing_occurrence,sizing_book_epoch,selected_quantity,decision_json,created_utc,updated_utc) "
        "VALUES('old','F22','janus:f22:entry-arm:v1','x','maker','h',1,'e',5,'{}',1,1)"
    )
    con.commit(); con.close()
    out = report(db)
    assert out["row_id"] == "F23"
    assert out["decisions"] == []


def test_f23_report_requires_its_own_table(tmp_path):
    db = tmp_path / "f23.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE f22_decisions(id INTEGER)")
    con.commit(); con.close()
    out = report(db)
    assert out["row_id"] == "F23" and "f23_decisions" in out["blocking_reason"]


def test_f23_report_keeps_terminal_completeness_separate_from_registered_minimum():
    facts = [{"arm": "maker" if i % 2 else "taker", "event_id": f"e-{i}", "league": f"l-{i % 3}",
              "created_utc": 1_757_900_000 + i * 86_400, "outcome": "accepted_full_fill",
              "settled_pnl_usd": .01 if i % 2 else .005} for i in range(4)]
    counts = _minimum_counts(facts)
    assert counts == {"decisions": 4, "maker": 2, "taker": 2, "events": 4, "days": None, "leagues": 3}
    # A terminal, balanced toy sample is still operationally insufficient and cannot get a scored
    # verdict. The CI helper is deterministic whenever the registered minimum is reached.
    assert _clustered_interval(facts)["seed"] == 230915


def test_f23_minimum_counts_only_complete_canonical_local_dates():
    facts = [{"arm": "maker" if i % 2 else "taker", "event_id": f"e-{i}",
              "league": f"l-{i % 3}", "league_local_date": f"2026-09-{11 + i:02d}"}
             for i in range(5)]
    assert _minimum_counts(facts)["days"] == 5
    facts[-1]["league_local_date"] = "not-a-date"
    assert _minimum_counts(facts)["days"] is None


def test_f23_clustered_primary_includes_terminal_zero_dollar_decisions():
    facts = [
        {"arm": "maker", "event_id": "e-zero", "outcome": "local_or_risk_refused_no_wire", "settled_pnl_usd": 0.0},
        {"arm": "taker", "event_id": "e-zero", "outcome": "provider_rejected_no_position", "settled_pnl_usd": 0.0},
        {"arm": "maker", "event_id": "e-fill", "outcome": "accepted_full_fill", "settled_pnl_usd": .1},
        {"arm": "taker", "event_id": "e-fill", "outcome": "accepted_full_fill", "settled_pnl_usd": .05},
    ]
    ci = _clustered_interval(facts)
    assert ci is not None and ci["maker_minus_taker_usd"] == .025

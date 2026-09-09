import json

import pytest

from nodes.account_ledger.ledger import Activity, Classification, cents, load_activities, summarize


def row(source_id, venue, amount, classification=Classification.REALIZED):
    return Activity(source_id, venue, source_id, classification, cents(amount))


def test_verified_control_totals_are_exact_integer_cents():
    rows = [row("pm", "polymarket", "11.26"), row("ks", "kalshi", "-0.87"),
            row("open", "polymarket", "-3.72", Classification.OPEN_POSITION),
            row("deposit", "polymarket", "205.35", Classification.FUNDING)]
    got = summarize(rows)
    assert got.realized_cents == 1039
    assert got.trading_cash_flow_cents == 667
    assert got.realized_by_venue == {"polymarket": 1126, "kalshi": -87}
    assert got.as_dict()["realized_pnl_usd"] == "10.39"


def test_subcents_floats_and_duplicate_sources_are_refused():
    with pytest.raises(ValueError, match="exact cent"):
        cents("1.001")
    with pytest.raises(ValueError, match="binary float"):
        cents(1.01)
    with pytest.raises(ValueError, match="duplicate"):
        summarize([row("same", "kalshi", "1.00"), row("same", "kalshi", "2.00")])


def test_json_boundary_requires_source_lines(tmp_path):
    path = tmp_path / "activity.json"
    path.write_text(json.dumps({"activities": [{"source_id": "a", "venue": "kalshi",
        "description": "venue line", "classification": "REALIZED", "amount_usd": "-0.87"}]}))
    rows, _ = load_activities(path)
    assert rows[0].amount_cents == -87

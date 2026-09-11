"""L53: actual received shares are not capped by nominal SDK size."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kernel.execution_protocol import Ack
from kernel.schema import FillState, Mode
from nodes.exec_polymarket.client import PolymarketUserStream, PyClobTransport
from nodes.exec_polymarket.quantity import BUY_CAP_UNPROVEN
from nodes.exec_polymarket.quantity import taker_trade_vwap
from nodes.exec_polymarket.tests.test_pm_exec import T, cl, req, venue

FIXTURE = json.loads((Path(__file__).parent / "fixtures/f15_overfill.json").read_text())


@pytest.mark.parametrize("tif,price,size", [("gtc", .36, 10), ("fok", .99, 26), ("ioc", .5, 25.01)])
def test_real_adapter_refuses_buys_outside_dedicated_taker_envelope(tmp_path, tif, price, size):
    # No client, signing key, or SDK is constructed. Any attempt to touch it fails.
    transport = PyClobTransport.__new__(PyClobTransport)
    v, journal = venue(tmp_path, transport)
    ack = v.submit(req(price=price, contracts=size, time_in_force=tif), cl(tmp_path))
    assert ack.state is FillState.REJECTED and ack.raw_status == "QUANTITY_CAP_UNPROVEN"
    assert ack.venue_order_id is None and v.submits == 0
    assert journal.get("c1")["contracts"] == size


def test_bounded_taker_authorization_is_durable_before_wire(tmp_path):
    class Transport:
        def buy_contract_cap_error(self): return BUY_CAP_UNPROVEN
        def post_bounded_taker_buy(self, **kwargs):
            row = journal.store.con.execute(
                "SELECT max_requested_contracts,max_collateral_usd,max_accepted_excess "
                "FROM pm_bounded_taker_orders WHERE client_order_id='c1'").fetchone()
            assert row == ("25", "30", "1")
            return {"success": False, "errorMsg": "no match"}
    v, journal = venue(tmp_path, Transport())
    ack = v.submit(req(price=.36, contracts=10, time_in_force="ioc"), cl(tmp_path))
    assert ack.state is FillState.REJECTED


def test_the_f21_envelope_admits_twenty_five_and_refuses_twenty_six(tmp_path):
    """F21 (2026-09-11): 25 contracts at any price is inside $30 collateral; 26 is refused before
    the wire, whatever the override says."""
    class Transport:
        def buy_contract_cap_error(self): return BUY_CAP_UNPROVEN
        def post_bounded_taker_buy(self, **kwargs):
            seen.append((kwargs["size"], kwargs["price"]))
            return {"success": False, "errorMsg": "no match"}
    seen = []
    v, journal = venue(tmp_path, Transport())
    assert v.submit(req(price=.99, contracts=25, time_in_force="ioc"), cl(tmp_path)).raw_status != "QUANTITY_CAP_UNPROVEN"
    assert seen == [(25.0, .99)]
    v2, _ = venue(tmp_path / "b", Transport())
    assert v2.submit(req(price=.36, contracts=26, time_in_force="ioc"), cl(tmp_path / "b")).raw_status == "QUANTITY_CAP_UNPROVEN"
    assert seen == [(25.0, .99)]


def test_unknown_transport_cannot_silently_bypass_share_cap(tmp_path):
    v, _ = venue(tmp_path, SimpleNamespace())
    assert v.submit(req(), cl(tmp_path)).raw_status == "QUANTITY_CAP_UNPROVEN"


def test_installed_sdk_nominal_shares_encode_only_a_collateral_budget():
    builder = pytest.importorskip("py_clob_client_v2.order_builder.builder")
    side, maker, taker = builder.OrderBuilder(None).get_order_amounts("BUY", 10, .36,
                                                                       builder.ROUNDING_CONFIG["0.01"])
    assert maker == 3_600_000 and taker == 10_000_000
    trade = FIXTURE["trade"]
    assert float(trade["size"]) > taker / 1_000_000
    assert taker_trade_vwap(trade) * float(trade["size"]) == pytest.approx(maker / 1_000_000)


def test_f15_mixed_makers_explain_extra_shares_and_correct_user_stream_vwap():
    trade = FIXTURE["trade"]
    price = taker_trade_vwap(trade)
    assert price == pytest.approx(3.60 / 10.166667)
    assert price != pytest.approx(float(trade["price"]))
    feed = PolymarketUserStream(SimpleNamespace(api_key="k", api_secret="s", api_passphrase="p"))
    feed.handle({"event_type": "trade", **trade})
    taking = feed.order(trade["taker_order_id"])
    assert taking["size_matched"] == 10.166667 and taking["price"] == price
    # The maker order's own quantity/side is not the taker aggregate.
    making = feed.order(trade["maker_orders"][0]["order_id"])
    assert making["size_matched"] == 6 and making["price"] == .65


@pytest.mark.parametrize("change", ["no_makers", "partial_makers", "unknown_asset", "same_side_same_asset"])
def test_unproven_stream_average_preserves_fill_without_inventing_price(change):
    trade = deepcopy(FIXTURE["trade"])
    if change == "no_makers":
        del trade["maker_orders"]
    elif change == "partial_makers":
        trade["maker_orders"].pop()
    elif change == "unknown_asset":
        del trade["maker_orders"][0]["asset_id"]
    else:
        trade["maker_orders"][1]["side"] = "BUY"
    assert taker_trade_vwap(trade) is None


def test_historical_authoritative_status_preserves_excess_shares(tmp_path):
    # Frozen pre-existing-order replay; no submit required to reconcile legacy orders.
    trade = FIXTURE["trade"]
    payload = FIXTURE["order"]
    v, journal = venue(tmp_path, SimpleNamespace(get_order=lambda oid: payload))
    journal.pending(req(), mode=Mode.LIMITED_LIVE.value, now=T)
    journal.record(Ack("polymarket", "c1", trade["taker_order_id"], FillState.UNCONFIRMED,
                       0, None, None, "delayed", T), kind="ack")
    state = v.status("c1")
    assert state.filled_contracts == 10.166667 and state.state is FillState.FILLED
    assert journal.get("c1")["contracts"] == 10
    assert journal.get("c1")["filled_contracts"] == 10.166667

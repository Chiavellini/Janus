"""L54 offline maker lifecycle: durable wire cap, no replace, late evidence."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from kernel.execution_protocol import FillRecord
from kernel.schema import FillState
from nodes.exec_polymarket.client import PolymarketExecution, PolymarketUserStream, PyClobTransport
from nodes.exec_polymarket.tests.test_pm_exec import cl, req, venue
from nodes.risk.kill import KillSwitches


class Transport:
    def __init__(self):
        self.posts = 0
        self.orders = 0
        self.payload = {"id": "signed-hash", "status": "LIVE", "size_matched": "0", "associate_trades": []}
        self.response = {"success": True, "orderID": "signed-hash", "status": "live"}
        self.cancel_error = None

    def prepare_post_only_buy(self, request):
        self.orders += 1
        return {"venue_order_id": "signed-hash", "maker_amount": str(int(Decimal(str(request.price)) * 10_000_000)),
                "taker_amount": "10000000", "wire": {"postOnly": True, "orderType": "GTC", "size": 10}}

    def post_prepared_post_only(self, prepared):
        # The exact cap and known hash must exist on durable storage before the POST.
        assert self.journal.store.con.execute("SELECT taker_amount FROM pm_post_only_orders").fetchone() == ("10000000",)
        assert self.journal.get("c1")["venue_order_id"] == "signed-hash"
        self.posts += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get_order(self, oid):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def trades(self, *, after_ts):
        return []

    def cancel(self, oid):
        assert self.journal.store.con.execute("SELECT 1 FROM order_events WHERE kind='post_only_cancel_intent'").fetchone()
        if self.cancel_error:
            raise self.cancel_error
        self.payload = {**self.payload, "status": "CANCELED"}
        return {"canceled": [oid], "not_canceled": {}}


def setup(tmp_path):
    tr = Transport()
    v, j = venue(tmp_path, tr)
    tr.journal = j
    v.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    return v, j, tr


def maker_request(**changes):
    return req(time_in_force="gtc", post_only=True, **changes)


def fill(journal, quantity, *, final=True, fill_id="t:maker:signed-hash"):
    journal.record_fill(FillRecord("polymarket", "signed-hash", fill_id, quantity, .44, 0, False, 1000, final))


def test_cap_and_intent_are_durable_before_post(tmp_path):
    v, j, tr = setup(tmp_path)
    ack = v.submit(maker_request(), cl(tmp_path))
    assert ack.open and ack.state is FillState.UNCONFIRMED and tr.posts == 1
    assert j.store.con.execute("SELECT maker_amount,taker_amount,terminal_proved FROM pm_post_only_orders").fetchone() == ("4400000", "10000000", 0)


@pytest.mark.parametrize("rest", [None, TimeoutError("REST unavailable")])
@pytest.mark.parametrize("conflicting_maker", [False, True])
def test_socket_taker_role_latches_within_cap_without_rest(tmp_path, rest, conflicting_maker):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    stream = PolymarketUserStream(SimpleNamespace(api_key="fake", api_secret="fake", api_passphrase="fake"))
    makers = ([{"order_id": "signed-hash", "matched_amount": "6", "price": ".44"}]
              if conflicting_maker else [])
    stream.handle({"event_type": "trade", "id": "socket-trade", "taker_order_id": "signed-hash",
                   "status": "MATCHED", "size": "6", "price": ".44", "maker_orders": makers})
    tr.user_order = stream.order
    tr.payload = rest
    state = v.status("c1")
    assert state.filled_contracts == 6 and not state.final and state.open
    assert v.kill.active(live=True)
    assert j.store.con.execute("SELECT code FROM pm_post_only_violations").fetchone() == ("POST_ONLY_ROLE_VIOLATION",)


def test_predeadline_status_has_no_blocking_venue_reads(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(entry_expires_utc=1000.1), cl(tmp_path))
    calls = []
    tr.get_order = lambda oid: calls.append("get")
    tr.trades = lambda **kw: calls.append("trades") or []
    state = v.status("c1")
    assert state.open and not state.final and calls == []


def test_observed_and_cancel_only_use_socket_high_water_without_rest(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(entry_expires_utc=1002.0), cl(tmp_path))
    stream = PolymarketUserStream(SimpleNamespace(api_key="fake", api_secret="fake", api_passphrase="fake"))
    stream.handle({"event_type": "trade", "id": "socket-fill", "taker_order_id": "other",
                   "status": "MATCHED", "size": "2", "price": ".44",
                   "maker_orders": [{"order_id": "signed-hash", "matched_amount": "2", "price": ".44"}]})
    tr.user_order = stream.order
    tr.get_order = lambda _oid: (_ for _ in ()).throw(AssertionError("no REST order read"))
    tr.trades = lambda **_kw: (_ for _ in ()).throw(AssertionError("no REST trade read"))
    assert v.observed("c1").filled_contracts == 2
    canceled = v.cancel_only("c1")
    assert canceled.filled_contracts == 2 and canceled.open and not canceled.final
    assert j.store.con.execute(
        "SELECT COUNT(*) FROM order_events WHERE kind='post_only_cancel_intent'"
    ).fetchone()[0] == 1


def test_socket_taker11_then_maker4_preserves_highest_quantity(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    stream = PolymarketUserStream(SimpleNamespace(api_key="fake", api_secret="fake", api_passphrase="fake"))
    stream.handle({"event_type": "trade", "id": "t", "taker_order_id": "signed-hash", "status": "MATCHED",
                   "size": "11", "price": ".44"})
    later = {"event_type": "trade", "id": "t", "taker_order_id": "elsewhere", "status": "CONFIRMED",
             "maker_orders": [{"order_id": "signed-hash", "matched_amount": "4", "price": ".44"}]}
    stream.handle(later)
    tr.user_order = stream.order
    state = v.status("c1")
    assert state.filled_contracts == j.get("c1")["filled_contracts"] == 11
    assert v.kill.active(live=True) and not state.final
    stream.handle({**later, "status": "FAILED"})
    assert stream.order("signed-hash")["size_matched"] == 11
    assert v.status("c1").filled_contracts == 11


@pytest.mark.parametrize("quantity", [6, 10])
def test_status_record_disk_failure_returns_high_water_and_latches(tmp_path, monkeypatch, quantity):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    tr.payload.update(size_matched=str(quantity), status="MATCHED")
    v.clock = lambda: 1001
    monkeypatch.setattr(j, "record", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    state = v.status("c1")
    assert state.filled_contracts == quantity and state.open and not state.final
    assert v.persistence_error and v.kill.active(live=True)
    v.last_error = "later unrelated balance error"
    assert v.stats()["persistence_error"].startswith("POST_ONLY_PERSISTENCE_FAILED")
    tr.payload.update(size_matched="0")
    assert v.status("c1").filled_contracts == quantity
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == ("c1",)


def test_post_ack_disk_failure_keeps_recovery_hash_and_admission(tmp_path, monkeypatch):
    v, j, tr = setup(tmp_path)
    post = tr.post_prepared_post_only
    def lose_disk(prepared):
        result = post(prepared)
        monkeypatch.setattr(j, "record", lambda *a, **kw: (_ for _ in ()).throw(OSError("post ack disk")))
        return result
    tr.post_prepared_post_only = lose_disk
    state = v.submit(maker_request(), cl(tmp_path))
    assert state.open and state.state is FillState.UNCONFIRMED and state.venue_order_id == "signed-hash"
    assert v.persistence_error and v.kill.active(live=True)
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == ("c1",)


def test_terminal_status_disk_failure_never_releases_claim(tmp_path, monkeypatch):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    v.cancel("c1")
    v.clock = lambda: 1002.1
    monkeypatch.setattr(j, "record", lambda *a, **kw: (_ for _ in ()).throw(OSError("terminal disk")))
    state = v.status("c1")
    assert state.open and not state.final and v.kill.active(live=True)
    assert j.store.con.execute("SELECT terminal_proved FROM pm_post_only_orders").fetchone() == (0,)
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == ("c1",)


@pytest.mark.parametrize("changed", ["chain", "package", "domain_name", "domain_version", "signer_chain", "builder_signer_chain", "builder_config", "exchange_v2", "neg_risk_exchange_v2", "collateral", "conditional_tokens"])
def test_unreviewed_runtime_domain_refused_before_signing(monkeypatch, changed):
    import importlib.metadata
    import py_clob_client_v2.config as config_module
    import py_clob_client_v2.order_builder.builder as builder_module
    import py_clob_client_v2.order_utils.model.ctf_exchange_v2_typed_data as domain
    types = pytest.importorskip("py_clob_client_v2.clob_types")
    config = config_module.get_contract_config(137)
    if changed in {"exchange_v2", "neg_risk_exchange_v2", "collateral", "conditional_tokens"}:
        config = replace(config, **{changed: "0x" + "11" * 20})
    monkeypatch.setattr(config_module, "get_contract_config", lambda _: config)
    if changed == "package": monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.0.0")
    if changed == "domain_name": monkeypatch.setattr(domain, "CTF_EXCHANGE_V2_DOMAIN_NAME", "Unreviewed Exchange")
    if changed == "domain_version": monkeypatch.setattr(domain, "CTF_EXCHANGE_V2_DOMAIN_VERSION", "9")
    if changed == "builder_config": monkeypatch.setattr(builder_module, "get_contract_config", lambda _: replace(config, exchange_v2="0x" + "11" * 20))
    calls = []
    tr = PyClobTransport.__new__(PyClobTransport)
    tr._T = types
    signer = SimpleNamespace(get_chain_id=lambda: 80002 if changed == "signer_chain" else 137)
    builder_signer = SimpleNamespace(get_chain_id=lambda: 80002 if changed == "builder_signer_chain" else 137)
    tr._c = SimpleNamespace(chain_id=80002 if changed == "chain" else 137, signer=signer, get_neg_risk=lambda _: False,
                            builder=SimpleNamespace(signer=builder_signer, build_order=lambda *a, **kw: calls.append("sign")))
    with pytest.raises(ValueError):
        tr.prepare_post_only_buy(maker_request(market_id="1", tick=.01))
    assert calls == []


def test_explicit_post_only_rejection_is_terminal_without_fill(tmp_path):
    v, j, tr = setup(tmp_path)
    tr.response = {"success": False, "errorMsg": "post-only would cross"}
    ack = v.submit(maker_request(), cl(tmp_path))
    assert ack.state is FillState.REJECTED and not ack.open
    assert j.store.con.execute("SELECT terminal_proved FROM pm_post_only_orders").fetchone() == (1,)
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == (None,)


@pytest.mark.parametrize("response", [{}, None, TimeoutError("lost response")])
def test_ambiguous_post_keeps_signed_hash_and_blocks_replacement(tmp_path, response):
    v, j, tr = setup(tmp_path)
    tr.response = response
    ack = v.submit(maker_request(), cl(tmp_path))
    assert ack.state is FillState.UNCONFIRMED and ack.venue_order_id == "signed-hash"
    second = v.submit(maker_request(client_order_id="c2"), cl(tmp_path))
    assert second.raw_status == "POST_ONLY_BLOCKED" and tr.posts == tr.orders == 1
    restarted = PolymarketExecution(tr, j, v.mode, clock=v.clock, kill=v.kill)
    assert restarted.submit(maker_request(client_order_id="c3"), cl(tmp_path)).state is FillState.REJECTED


def test_no_post_if_journal_write_fails(tmp_path, monkeypatch):
    v, j, tr = setup(tmp_path)
    monkeypatch.setattr(j, "record", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        v.submit(maker_request(), cl(tmp_path))
    assert tr.posts == 0


def test_terminal_zero_requires_stable_explicit_cancel_and_fresh_reads(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    assert not v.cancel("c1").final
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == ("c1",)
    v.clock = lambda: 1002.1
    assert v.status("c1").final
    assert j.store.con.execute("SELECT terminal_proved FROM pm_post_only_orders").fetchone() == (1,)
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == (None,)


def test_missing_lookup_never_becomes_a_post_only_no_fill(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    tr.payload = None
    v.clock = lambda: 999999
    state = v.status("c1")
    assert state.state is FillState.UNCONFIRMED and state.open and not state.final
    assert not j.store.con.execute("SELECT terminal_proved FROM pm_post_only_orders").fetchone()[0]
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == ("c1",)


def test_partial_then_cancel_race_full_keeps_cumulative_actual_and_restarts_window(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    tr.payload.update(status="CANCELED", size_matched="6", associate_trades=["t"])
    fill(j, 6)
    assert v.status("c1").filled_contracts == 6
    v.clock = lambda: 1002.1
    tr.payload.update(size_matched="10", associate_trades=["t", "late"])
    fill(j, 4, fill_id="late:maker:signed-hash")
    state = v.status("c1")
    assert state.filled_contracts == 10 and not state.final
    v.clock = lambda: 1004.2
    assert v.status("c1").final and not v.kill.active(live=True)


def test_partial_fifo_and_stale_order_never_reduce_authoritative_total(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    tr.payload.update(size_matched="10", status="CANCELED", associate_trades=["t", "late"])
    fill(j, 6)
    v.clock = lambda: 1001  # Reconciliation begins after deadline cancellation.
    assert v.status("c1").filled_contracts == 10
    tr.payload.update(size_matched="6")
    v.clock = lambda: 1005
    state = v.status("c1")
    assert state.filled_contracts == 10 and state.open and not state.final


@pytest.mark.parametrize("quantity", ["10.000001", "10.166667"])
def test_cap_violation_latches_without_clamping_even_below_dust(tmp_path, quantity):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    tr.payload.update(size_matched=quantity, status="MATCHED")
    v.clock = lambda: 1001  # No blocking order read before cancel dispatch.
    state = v.status("c1")
    assert state.filled_contracts == float(quantity) and v.kill.active(live=True)
    assert j.store.con.execute("SELECT violated FROM pm_post_only_orders").fetchone() == (1,)


def test_real_prepared_transport_sends_only_gtc_post_only_deferred():
    calls = []
    tr = PyClobTransport.__new__(PyClobTransport)
    tr._c = SimpleNamespace(post_order=lambda *a, **kw: calls.append((a, kw)) or {})
    tr._T = SimpleNamespace(OrderType=SimpleNamespace(GTC="GTC"))
    signed = object()
    tr.post_prepared_post_only({"signed": signed})
    assert calls == [((signed, "GTC"), {"post_only": True, "defer_exec": True})]


def test_preparation_cannot_spend_an_expired_quote(tmp_path):
    v, j, tr = setup(tmp_path)
    request = maker_request(entry_expires_utc=999)
    assert v.submit(request, cl(tmp_path)).raw_status == "POST_ONLY_EXPIRED"
    assert tr.posts == 0


def test_fill_after_proved_terminal_zero_reopens_lock_and_stops(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    v.cancel("c1")
    v.clock = lambda: 1002.1
    assert v.status("c1").final
    tr.payload.update(size_matched="6", associate_trades=["late"])
    fill(j, 6, fill_id="late:maker:signed-hash")
    assert v.status("c1").filled_contracts == 6
    assert v.kill.active(live=True)
    assert j.store.con.execute("SELECT terminal_proved,violated FROM pm_post_only_orders").fetchone() == (0, 1)


def test_real_preparation_uses_v2_hash_and_checks_actual_encoded_fields_without_post():
    types = pytest.importorskip("py_clob_client_v2.clob_types")
    from py_clob_client_v2.order_utils.model.order_data_v2 import SignedOrderV2
    signed = SignedOrderV2(salt="1", maker="0x" + "11" * 20, signer="0x" + "11" * 20,
                          tokenId="1", makerAmount="4400000", takerAmount="10000000", side=0,
                          signatureType=0, timestamp="1000000", metadata="0x" + "00" * 32,
                          builder="0x" + "00" * 32, signature="offline-not-a-signature")
    calls = []
    tr = PyClobTransport.__new__(PyClobTransport)
    tr._T = types
    signer = SimpleNamespace(get_chain_id=lambda: 137)
    tr._c = SimpleNamespace(chain_id=137, signer=signer, get_neg_risk=lambda _: False,
                            builder=SimpleNamespace(signer=signer, build_order=lambda *args, **kw: calls.append(kw) or signed))
    prepared = tr.prepare_post_only_buy(maker_request(market_id="1", tick=.01))
    assert calls[0]["version"] == 2 and prepared["venue_order_id"].startswith("0x")
    assert len(prepared["venue_order_id"]) == 66
    assert prepared["wire"]["postOnly"] is True and prepared["wire"]["orderType"] == "GTC"
    assert prepared["wire"]["order"]["signature"] == "redacted"
    signed.takerAmount = "10010000"
    with pytest.raises(ValueError):
        tr.prepare_post_only_buy(maker_request(market_id="1", tick=.01))


def test_expiry_during_durable_journal_cannot_reach_post(tmp_path, monkeypatch):
    v, j, tr = setup(tmp_path)
    clearance = cl(tmp_path)
    record = j.record
    def slow_record(ack, **kwargs):
        record(ack, **kwargs)
        if kwargs.get("kind") == "post_only_prepared":
            v.mono = lambda: clearance.expires_mono + 1
    monkeypatch.setattr(j, "record", slow_record)
    ack = v.submit(maker_request(), clearance)
    assert ack.state is FillState.REJECTED and ack.raw_status == "POST_ONLY_EXPIRED"
    assert tr.posts == 0


def test_restart_cancels_expired_resting_order_before_status_read(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(entry_expires_utc=1000.1), cl(tmp_path))
    calls = []
    get_order, cancel = tr.get_order, tr.cancel
    tr.get_order = lambda oid: calls.append("get") or get_order(oid)
    tr.cancel = lambda oid: calls.append("cancel") or cancel(oid)
    restarted = PolymarketExecution(tr, j, v.mode, clock=lambda: 1001, kill=v.kill)
    restarted.status("c1")
    assert calls[0] == "cancel"


def test_two_connections_cannot_enter_signer_while_first_preparation_is_in_flight(tmp_path):
    import threading
    from nodes.execution.journal import Journal
    from nodes.execution.testing import clearance_for
    from nodes.store_tuples.store import TupleStore
    v2, journal, tr2 = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    result = []
    def first_worker():
        other_journal = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
        first = Transport()
        first.journal = other_journal
        prepare = first.prepare_post_only_buy
        def blocked_prepare(request):
            entered.set()
            assert release.wait(3)
            return prepare(request)
        first.prepare_post_only_buy = blocked_prepare
        adapter = PolymarketExecution(first, other_journal, v2.mode, clock=lambda: 1000,
                                      mono=lambda: 100, kill=v2.kill)
        try:
            result.append(adapter.submit(maker_request(), clearance_for(tmp_path, mode=v2.mode, now_mono=100)))
        except Exception as exc:
            result.append(exc)
    worker = threading.Thread(target=first_worker)
    worker.start()
    assert entered.wait(3)
    v2.mono = lambda: 100
    second = None
    try:
        second = v2.submit(maker_request(client_order_id="c2"), clearance_for(tmp_path, mode=v2.mode, now_mono=100))
    except Exception as exc:
        second = exc
    finally:
        release.set()
        worker.join(3)
    assert tr2.orders == 0, "second connection must not reach preparation/signing"
    assert second.raw_status == "POST_ONLY_BLOCKED" and result[0].open


def test_singleton_survives_preparation_interruption_and_restart(tmp_path):
    v, j, tr = setup(tmp_path)
    tr.prepare_post_only_buy = lambda request: (_ for _ in ()).throw(KeyboardInterrupt("process interrupted"))
    with pytest.raises(KeyboardInterrupt):
        v.submit(maker_request(), cl(tmp_path))
    tr.prepare_post_only_buy = Transport.prepare_post_only_buy.__get__(tr)
    restarted = PolymarketExecution(tr, j, v.mode, clock=v.clock, kill=v.kill)
    assert restarted.submit(maker_request(client_order_id="c2"), cl(tmp_path)).raw_status == "POST_ONLY_BLOCKED"


def test_duplicate_client_id_cannot_replace_held_order_state(tmp_path):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    tr.payload.update(size_matched="6")
    v.clock = lambda: 1001
    v.status("c1")
    before = j.get("c1")
    assert v.submit(maker_request(), cl(tmp_path)).raw_status == "POST_ONLY_BLOCKED"
    assert j.get("c1") == before and tr.posts == 1


def test_late_old_fill_blocks_admission_without_stealing_new_claim(tmp_path):
    from nodes.exec_polymarket.post_only import claim_post_only
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    v.cancel("c1")
    v.clock = lambda: 1002.1
    assert v.status("c1").final
    assert claim_post_only(j, "c2", now=v.clock())
    tr.payload.update(size_matched="6", associate_trades=["late"])
    fill(j, 6, fill_id="late:maker:signed-hash")
    assert v.status("c1").filled_contracts == 6 and v.kill.active(live=True)
    assert j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone() == ("c2",)
    assert j.store.con.execute("SELECT client_order_id,violated FROM pm_post_only_orders").fetchone() == ("c1", 1)
    assert not claim_post_only(j, "c3", now=v.clock())


@pytest.mark.parametrize("stop", ["old_violation", "kill", "claim_lost"])
def test_new_preparation_cannot_post_after_admission_is_invalidated(tmp_path, stop):
    v, j, tr = setup(tmp_path)
    v.submit(maker_request(), cl(tmp_path))
    v.cancel("c1")
    v.clock = lambda: 1002.1
    assert v.status("c1").final
    prepare = tr.prepare_post_only_buy
    def invalidate(request):
        prepared = {**prepare(request), "venue_order_id": "second-hash"}
        if stop == "old_violation": v._post_only_violation("c1", "POST_ONLY_ROLE_VIOLATION", "late contradiction")
        elif stop == "kill": v.kill.latch("live", "new stop during preparation")
        else:
            j.store.con.execute("UPDATE pm_post_only_admission SET client_order_id='other' WHERE slot=1")
            j.store.con.commit()
        return prepared
    tr.prepare_post_only_buy = invalidate
    posted = []
    tr.post_prepared_post_only = lambda prepared: posted.append(prepared) or {}
    state = v.submit(maker_request(client_order_id="c2"), cl(tmp_path))
    assert not posted and state.state is FillState.REJECTED
    claim = j.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone()[0]
    assert claim == ("other" if stop == "claim_lost" else None)
    if stop == "old_violation":
        assert j.store.con.execute("SELECT violated FROM pm_post_only_orders WHERE client_order_id='c1'").fetchone() == (1,)

#!/usr/bin/env python3
"""The Polymarket proof, offline: rest/cancel/FOK/confirm against a scripted transport, the on-chain
reversal, the fee latch, the checklist over its file, and the read-only plan's refusals."""
from __future__ import annotations

import json
import types

import pytest

from kernel.schema import Mode
from nodes.exec_polymarket.client import PolymarketExecution
from nodes.execution.journal import Journal
from nodes.fees.models import Fill
from nodes.fees.registry import model_for, params_for
from nodes.risk.breaker import LossBreaker
from nodes.risk.clearance import Candidate, clear_proof
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import ExposureLedger
from nodes.risk.limits import load_limits
from nodes.store_tuples.store import TupleStore
from ops import polymarket_live_proof as pmp
from ops import proof_check

T = 1_800_000_000.0
TOKEN = "23587260317026359326884935753749480048028648271097330634178250204779064569512"
FEES = {"fee_rate": 0.05, "fee_exponent": 1.0, "taker_only": True, "rebate_rate": 0.15}
ASK = 0.54


def pinned(shares, price):
    return model_for("polymarket").entry_cost([Fill("polymarket", "o", TOKEN, "yes", price, shares, "taker", 0)],
                                              params_for("polymarket", FEES))


class FakeTransport:
    """A CLOB that rests the GTC, matches the FOK, and confirms (or fails) the trade on-chain."""
    def __init__(self, *, fee_bps: float, confirm=True, balance=25.0):
        self.fee_bps, self.confirm, self.bal = fee_bps, confirm, balance
        self.orders, self.calls, self.n = {}, [], 0

    def post_order(self, *, token_id, price, size, order_type, side="BUY"):
        self.n += 1
        oid = f"0x{self.n:03d}"
        self.calls.append(("post", order_type, price, size))
        if order_type == "GTC":
            self.orders[oid] = {"id": oid, "status": "LIVE", "size_matched": "0", "price": str(price), "size": size}
            return {"success": True, "orderID": oid, "status": "live"}
        self.orders[oid] = {"id": oid, "status": "MATCHED", "size_matched": str(size), "price": str(price), "size": size}
        self.bal -= size * price * (1 + self.fee_bps / 10_000.0 * (1 - price))
        return {"success": True, "orderID": oid, "status": "matched", "tradeIDs": ["t1"]}

    def get_order(self, order_id):
        return dict(self.orders[order_id])

    def cancel(self, order_id):
        self.calls.append(("cancel", order_id))
        self.orders[order_id]["status"] = "CANCELED"
        return {}

    def trades(self, *, after_ts):
        out = []
        for oid, o in self.orders.items():
            if o["status"] == "MATCHED":
                size, price = float(o["size"]), float(o["price"])
                out.append({"id": f"tr-{oid}", "taker_order_id": oid, "size": size, "price": price,
                            "fee_rate_bps": self.fee_bps * (1 - price) * 1.0, "trader_side": "TAKER", "match_time": T,
                            "status": "CONFIRMED" if self.confirm else "FAILED"})
        return out

    def balance_usd(self):
        return self.bal

    def cancel_all(self):
        return 0


def cleared(tmp_path, shares=5.0, store=None):
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    breaker = LossBreaker(tmp_path / "kill" / "breaker.json", kill=kill, enforce_volume=False)
    cand = Candidate("proof:pm1", f"proof:{TOKEN}", "mlb", (("polymarket", shares, ASK),), -shares * ASK, -1.0, "proof-v1", 0.0)
    c = clear_proof(cand, mode=Mode.LIMITED_LIVE, limits=load_limits(), ledger=ExposureLedger(store), kill=kill,
                    breaker=breaker, fills_today=(), balances={"polymarket": 25.0}, venues_connected={"polymarket": True},
                    caps={"stake_usd": 5.0, "max_contracts": 10.0, "day_notional_usd": 20.0}, now=T)
    assert not hasattr(c, "code"), c
    return cand, c, kill


def run(tmp_path, tr, store=None):
    cand, c, kill = cleared(tmp_path, store=store)
    st = store or TupleStore(tmp_path / "j.sqlite", enforce_volume=False)
    venue = PolymarketExecution(tr, Journal(st), Mode.LIMITED_LIVE, clock=lambda: T)
    proof = pmp.execute_steps(venue, slug="mlb-sf-pit-2026-09-03", outcome="San Francisco Giants", token=TOKEN, fees=FEES,
                              ask=ASK, resting_px=0.44, shares=5.0, min_size=5.0, cand=cand, clearance=c, kill=kill,
                              balance_before=venue.balance(), runner_sha="deadbeef", override_sha="0" * 16,
                              sleep=lambda s: None, poll_step=0.0, confirm_wait_s=1.0)
    return json.loads(json.dumps(proof, default=str)), kill


def fee_bps_at_pin():
    # the adapter computes fee = size * price * fee_rate_bps / 10_000; the pin is rate * p * (1-p) * size
    return 0.05 * 10_000.0


def test_the_flow_rests_cancels_matches_and_confirms_at_the_pinned_fee(tmp_path):
    tr = FakeTransport(fee_bps=fee_bps_at_pin())
    proof, kill = run(tmp_path, tr)
    assert [c[0] for c in tr.calls] == ["post", "cancel", "post"] and tr.calls[2][1] == "FOK"
    assert proof["venue"] == "polymarket" and proof["won_when"] == "San Francisco Giants" and "stop" not in proof
    ioc = proof["steps"][1]
    assert ioc["status"]["state"] == "FILLED" and ioc["status"]["final"] is True
    assert len(ioc["fills"]) == 1 and ioc["fills"][0]["confirmed"] is True and ioc["fills"][0]["excess"] == 0.0
    assert not kill.active(live=True)
    f = {x.name: x for x in proof_check.check_proof(proof, reservation_row=lambda r: {"released_utc": None, "release_reason": None},
                                                    open_rows_for_event=lambda e: 1)}
    assert all(x.ok for x in f.values()), [x for x in f.values() if not x.ok]


def test_a_failed_on_chain_trade_is_a_stop_not_a_fill(tmp_path):
    proof, kill = run(tmp_path, FakeTransport(fee_bps=fee_bps_at_pin(), confirm=False))
    assert proof["stop"] == "TRADE_FAILED" and proof["steps"][1]["fills"] == []
    assert proof["steps"][1]["status"]["state"] == "UNCONFIRMED"
    f = {x.name: x for x in proof_check.check_proof(proof, reservation_row=lambda r: {"released_utc": None, "release_reason": None},
                                                    open_rows_for_event=lambda e: 1)}
    assert not f["ioc_final"].ok and not f["fee_ok"].ok


def test_a_fee_above_the_pin_latches_kill_live(tmp_path):
    proof, kill = run(tmp_path, FakeTransport(fee_bps=fee_bps_at_pin() * 1.5))
    assert proof["stop"] == "FEE_ABOVE_PIN" and kill.active(live=True)


def test_settled_polymarket_proof_checks_the_arithmetic_on_the_outcome_label(tmp_path):
    proof, _ = run(tmp_path, FakeTransport(fee_bps=fee_bps_at_pin()))
    fee = proof["steps"][1]["fills"][0]["charged"]
    proof["settled"] = {"result": "San Francisco Giants", "realized_usd": 5 * (1 - ASK) - fee, "at": "x"}
    f = {x.name: x for x in proof_check.check_proof(proof, reservation_row=lambda r: {"released_utc": T, "release_reason": "r"},
                                                    open_rows_for_event=lambda e: 0)}
    assert f["settled_pnl"].ok and f["reservation"].ok
    proof["settled"] = {"result": "other", "realized_usd": -5 * ASK - fee, "at": "x"}
    assert {x.name: x for x in proof_check.check_proof(proof, reservation_row=lambda r: {"released_utc": T, "release_reason": "r"},
                                                       open_rows_for_event=lambda e: 0)}["settled_pnl"].ok


class FakeGamma:
    def __init__(self, *, fee=True, bid=0.53, ask=0.54):
        self.fee, self.bid, self.ask = fee, bid, ask

    def get_json(self, url, params=None, use_cache=True):
        if url.endswith("/events"):
            m = {"slug": "mlb-sf-pit-2026-09-03", "outcomes": '["San Francisco Giants", "Pittsburgh Pirates"]',
                 "clobTokenIds": json.dumps([TOKEN, "other"]), "orderMinSize": 5, "orderPriceMinTickSize": 0.01}
            if self.fee:
                m["feeSchedule"] = {"exponent": 1, "rate": 0.05, "takerOnly": True, "rebateRate": 0.15}
            return [{"slug": "mlb-sf-pit-2026-09-03", "markets": [m]}]
        if url.endswith("/book"):
            return {"bids": [{"price": str(self.bid), "size": "100"}] if self.bid else [],
                    "asks": [{"price": str(self.ask), "size": "200"}] if self.ask else []}
        raise AssertionError(url)


def args(**kw):
    base = dict(slug="mlb-sf-pit-2026-09-03", outcome="San Francisco Giants", token=None, shares=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_the_plan_reads_the_min_size_and_refuses_what_it_must(capsys):
    p = pmp.plan(args(), FakeGamma())
    assert p["token"] == TOKEN and p["shares"] == 5.0 and p["ask"] == 0.54 and p["league"] == "mlb"
    assert p["resting_px"] == 0.44 and p["fees"]["fee_rate"] == 0.05
    assert pmp.plan(args(shares=2), FakeGamma()) == 2                     # below orderMinSize
    assert pmp.plan(args(outcome="Giants"), FakeGamma()) == 2             # not a Gamma label
    assert pmp.plan(args(), FakeGamma(fee=False)) == 2                    # no feeSchedule: never defaulted
    assert pmp.plan(args(), FakeGamma(bid=None)) == 2                     # one-sided book
    assert pmp.plan(args(slug="xyz-a-b-2026-09-03"), FakeGamma()) == 2    # unregistered league prefix


def test_run_proof_stops_at_the_transport_without_a_key_file(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("JANUS_PM_WALLET_KEY_PATH", raising=False)
    monkeypatch.setattr(pmp, "Client", lambda *a, **k: FakeGamma())
    # the mode gate refuses on CREDENTIALS before any override is consulted; nothing is sent
    monkeypatch.setattr(pmp, "KillSwitches", lambda: KillSwitches(tmp_path / "kill", enforce_volume=False))
    rc = pmp.run_proof(args(arm=False, db=tmp_path / "t.sqlite"))
    out = capsys.readouterr().out
    assert rc == 2 and "CREDENTIALS" in out and "600-mode" in out

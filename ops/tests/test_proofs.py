#!/usr/bin/env python3
"""The execution proof, offline: the resting/cancel/IOC/fee/latch flow against a fake venue, the
post-proof checklist over proof files, and the arming-override writer.

Why these exist: the proof script is the one thing the operator runs with real money, and until
2026-09-03 nothing in the suite exercised it -- the first armed attempt was refused by risk for a
league-keying mistake that a fake venue would have caught (HANDOFF 2026-09-03, item 3).
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from kernel.execution_protocol import Ack, Balance, FillRecord, OrderState
from kernel.schema import FillState, Mode
from nodes.fees.models import Fill
from nodes.fees.registry import model_for, params_for
from nodes.risk.breaker import LossBreaker
from nodes.risk.clearance import Candidate, clear_proof
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import ExposureLedger
from nodes.risk.limits import load_limits
from nodes.store_tuples.store import TupleStore
from ops import proof_check
from ops.kalshi_live_proof import execute_steps

ROOT = Path(__file__).resolve().parents[2]
TICKER = "KXMLBGAME-26SEP031235SFPIT-SF"
FEES = {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5}
ASK, BID = 0.41, 0.40
T = 1_800_000_000.0


def pinned_fee(contracts: float, price: float) -> float:
    return model_for("kalshi").entry_cost([Fill("kalshi", "v2", TICKER, "yes", price, contracts, "taker", 0)],
                                          params_for("kalshi", FEES))


class FakeVenue:
    """Scripted Kalshi. `fee` is what the venue charges on the IOC fill; `resting_fill` simulates the
    book moving through the resting bid before the cancel."""
    venue = "kalshi"
    mode = Mode.LIMITED_LIVE

    def __init__(self, *, fee: float, balance0: float = 61.24, resting_fill: float = 0.0, ioc_unconfirmed=False):
        self.fee, self.bal, self.resting_fill, self.ioc_unconfirmed = fee, balance0, resting_fill, ioc_unconfirmed
        self.orders: dict[str, dict] = {}
        self.calls: list[str] = []

    def balance(self):
        return Balance("kalshi", self.bal, T)

    def submit(self, req, clearance):
        self.calls.append(f"submit:{req.time_in_force}")
        vid = f"v{len(self.orders) + 1}"
        if req.time_in_force == "gtc":
            self.orders[req.client_order_id] = {"vid": vid, "filled": 0.0, "price": req.price, "open": True}
            return Ack("kalshi", req.client_order_id, vid, FillState.UNFILLED, 0.0, None, None, "resting", T, open=True)
        if self.ioc_unconfirmed:
            self.orders[req.client_order_id] = {"vid": vid, "filled": 0.0, "price": req.price, "open": False}
            return Ack("kalshi", req.client_order_id, vid, FillState.UNCONFIRMED, 0.0, None, None, "TIMEOUT", T)
        self.orders[req.client_order_id] = {"vid": vid, "filled": req.contracts, "price": req.price, "open": False}
        self.bal -= req.contracts * req.price + self.fee
        return Ack("kalshi", req.client_order_id, vid, FillState.FILLED, req.contracts, req.price, self.fee, "executed", T)

    def status(self, cid):
        o = self.orders[cid]
        if self.ioc_unconfirmed and not o["open"]:
            return OrderState("kalshi", cid, o["vid"], FillState.UNCONFIRMED, 0.0, None, None, "TIMEOUT", T, final=False)
        st = FillState.FILLED if o["filled"] > 0 else FillState.UNFILLED
        return OrderState("kalshi", cid, o["vid"], st, o["filled"], o["price"] if o["filled"] else None,
                          self.fee if o["filled"] else None, "resting" if o["open"] else "executed", T,
                          open=o["open"], final=not o["open"])

    def cancel(self, cid):
        self.calls.append("cancel")
        o = self.orders[cid]
        if self.resting_fill:
            o["filled"] = self.resting_fill
            self.bal -= self.resting_fill * o["price"]
        o["open"] = False
        return Ack("kalshi", cid, o["vid"], FillState.FILLED if o["filled"] else FillState.UNFILLED, o["filled"],
                   None, None, "canceled", T)

    def fills(self, *, since_utc):
        out = []
        for cid, o in self.orders.items():
            if o["filled"] > 0:
                out.append(FillRecord("kalshi", o["vid"], f"f-{o['vid']}", o["filled"], o["price"],
                                      self.fee if o["vid"] == "v2" else 0.0, True, T, True))
        return out

    def cancel_all(self):
        return 0


def cleared(tmp_path, *, contracts=2.0, store=None):
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    breaker = LossBreaker(tmp_path / "kill" / "breaker.json", kill=kill, enforce_volume=False)
    ledger = ExposureLedger(store)
    cand = Candidate("proof:abcd1234", f"proof:{TICKER}", "mlb", (("kalshi", contracts, ASK),), -contracts * ASK, -1.0,
                     "proof-v1", 0.0)
    c = clear_proof(cand, mode=Mode.LIMITED_LIVE, limits=load_limits(), ledger=ledger, kill=kill, breaker=breaker,
                    fills_today=(), balances={"kalshi": 61.24}, venues_connected={"kalshi": True},
                    caps={"stake_usd": 5.0, "max_contracts": 10.0, "day_notional_usd": 20.0}, now=T)
    assert not hasattr(c, "code"), c
    return cand, c, kill, ledger


def run(tmp_path, venue, **kw):
    cand, c, kill, ledger = cleared(tmp_path, **{k: v for k, v in kw.items() if k in ("contracts", "store")})
    proof = execute_steps(venue, ticker=TICKER, series="KXMLBGAME", fees=FEES, ask=ASK, resting_px=0.31,
                          contracts=kw.get("contracts", 2.0), cand=cand, clearance=c, kill=kill,
                          balance_before=venue.balance(), runner_sha="deadbeef", override_sha="0" * 16,
                          sleep=lambda s: None, poll_step=0.0)
    return json.loads(json.dumps(proof, default=str)), kill, ledger


def by_name(findings):
    return {f.name: f for f in findings}


# ── the flow ──────────────────────────────────────────────────────────────

def test_the_flow_rests_cancels_fills_and_records_the_fee_at_the_pin(tmp_path):
    v = FakeVenue(fee=pinned_fee(2.0, ASK))
    proof, kill, _ = run(tmp_path, v)
    assert v.calls == ["submit:gtc", "cancel", "submit:ioc"]
    assert proof["contracts"] == 2.0 and proof["venue"] == "kalshi" and "stop" not in proof
    ioc = proof["steps"][1]
    assert ioc["status"]["state"] == "FILLED" and ioc["status"]["final"] is True
    assert len(ioc["fills"]) == 1 and ioc["fills"][0]["excess"] == 0.0
    assert ioc["balance_after"] == pytest.approx(61.24 - 2 * ASK - pinned_fee(2.0, ASK))
    assert not kill.active(live=True)
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert all(x.ok for x in f.values()), [x for x in f.values() if not x.ok]


def test_a_fee_above_the_pin_latches_kill_live_and_fails_the_check(tmp_path):
    v = FakeVenue(fee=pinned_fee(2.0, ASK) + 0.01)
    proof, kill, _ = run(tmp_path, v)
    assert proof["stop"] == "FEE_ABOVE_PIN"
    assert kill.active(live=True)
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert not f["fee_ok"].ok and "re-pinned" in f["fee_ok"].detail
    assert f["balance_delta"].ok           # the delta still reconciles against what was charged


def test_a_resting_bid_that_filled_is_reported_not_failed(tmp_path):
    v = FakeVenue(fee=pinned_fee(2.0, ASK), resting_fill=1.0)
    proof, _, _ = run(tmp_path, v)
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert f["resting_cancelled"].ok and "moved through" in f["resting_cancelled"].detail
    assert f["balance_delta"].ok           # the resting fill is in the fills and in the delta


def test_an_unconfirmed_ioc_is_never_final(tmp_path):
    v = FakeVenue(fee=0.0, ioc_unconfirmed=True)
    proof, _, _ = run(tmp_path, v)
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert not f["ioc_final"].ok and "UNCONFIRMED" in f["ioc_final"].detail


# ── the checklist over files ─────────────────────────────────────────────

def good_proof(tmp_path):
    proof, _, _ = run(tmp_path, FakeVenue(fee=pinned_fee(2.0, ASK)))
    return proof


def test_check_flags_a_balance_that_moved_by_more_than_the_fills(tmp_path):
    proof = good_proof(tmp_path)
    proof["steps"][1]["balance_after"] -= 0.05
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert not f["balance_delta"].ok


def test_check_flags_fills_that_disagree_with_the_status(tmp_path):
    proof = good_proof(tmp_path)
    proof["steps"][1]["fills"] = []
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert not f["fills_match_status"].ok


def test_settled_proof_needs_the_arithmetic_and_a_released_reservation(tmp_path):
    proof = good_proof(tmp_path)
    fee = pinned_fee(2.0, ASK)
    proof["settled"] = {"result": "yes", "realized_usd": 2 * (1 - ASK) - fee, "at": "x"}
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": T, "release_reason": "proof settled: yes"},
                                        open_rows_for_event=lambda e: 0))
    assert f["settled_pnl"].ok and f["reservation"].ok
    # the losing side
    proof["settled"] = {"result": "no", "realized_usd": -2 * ASK - fee, "at": "x"}
    assert by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": T, "release_reason": "r"},
                                           open_rows_for_event=lambda e: 0))["settled_pnl"].ok
    # wrong arithmetic, or a reservation still open after settlement, fails
    proof["settled"]["realized_usd"] = 0.0
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda rid: {"released_utc": None, "release_reason": None},
                                        open_rows_for_event=lambda e: 1))
    assert not f["settled_pnl"].ok and not f["reservation"].ok


def test_run_check_reads_the_real_ledger_read_only(tmp_path, capsys):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    proof, _, ledger = run(tmp_path, FakeVenue(fee=pinned_fee(2.0, ASK)), store=store)
    store.commit()
    path = tmp_path / "kalshi_test.json"
    path.write_text(json.dumps(proof))
    assert proof_check.run_check(path, tmp_path / "t.sqlite") == 0
    out = capsys.readouterr().out
    assert "unsettled" in out and "6/6" in out
    # after settlement the row must be released; a stale open row fails the check
    proof["settled"] = {"result": "no", "realized_usd": -2 * ASK - pinned_fee(2.0, ASK), "at": "x"}
    path.write_text(json.dumps(proof))
    assert proof_check.run_check(path, tmp_path / "t.sqlite") == 1
    ledger.release(proof["reservation_id"], reason="proof settled: no")
    assert proof_check.run_check(path, tmp_path / "t.sqlite") == 0
    # no ledger reachable -> the reservation check is SKIPPED and counts as a failure, never as a pass
    assert proof_check.run_check(path, tmp_path / "missing.sqlite") == 1
    assert "SKIPPED" in capsys.readouterr().out


def test_check_never_echoes_a_raw_ack(tmp_path, capsys):
    proof = good_proof(tmp_path)
    proof["steps"][0]["resting"]["detail"] = "SECRET-LOOKING-TOKEN-XYZ"
    path = tmp_path / "p.json"
    path.write_text(json.dumps(proof))
    proof_check.run_check(path, None)
    assert "SECRET-LOOKING-TOKEN-XYZ" not in capsys.readouterr().out


# ── the override writer ──────────────────────────────────────────────────

def write_override(tmp_path, *extra, root=None):
    path = tmp_path / "kill" / "arming_override.json"
    r = subprocess.run([sys.executable, str(ROOT / "ops" / "arming_override.py"), "--mode", "LIMITED_LIVE",
                        "--signed-by", "Test", "--stake-usd", "5", "--day-notional-usd", "20",
                        "--statement", "I approve a test.", "--path", str(path),
                        *(["--root", str(root)] if root else []), *extra],
                       capture_output=True, text=True, cwd=ROOT)
    return r, path


def test_arming_override_pins_the_code_tree_and_the_limits_and_refuses_to_overwrite(tmp_path):
    """Since 2026-09-07 the pin is the executable tree (kernel/code_sha), with the whole-checkout
    HEAD beside it for the record. A clean throwaway repo stands in for the box's checkout so the
    test does not depend on this working tree being clean."""
    from kernel.code_sha import code_tree_sha, runner_head_sha
    from kernel.tests.test_code_sha import _repo
    repo = _repo(tmp_path)
    r, path = write_override(tmp_path, root=repo)
    assert r.returncode == 0, r.stderr
    d = json.loads(path.read_text())
    assert d["code_sha"] == code_tree_sha(repo) and len(d["code_sha"]) == 16
    assert d["runner_sha"] == runner_head_sha(repo) and d["limits_sha"] == load_limits().sha
    assert d["mode"] == "LIMITED_LIVE" and d["caps"] == {"stake_usd": 5.0, "max_contracts": 10.0, "day_notional_usd": 20.0}
    assert d["operator_statement"] == "I approve a test." and d["signed_by"] == "Test"
    assert (path.stat().st_mode & 0o777) == 0o600
    assert f"code {d['code_sha']}" in r.stdout
    r2, _ = write_override(tmp_path, root=repo)
    assert r2.returncode == 2 and "--force" in r2.stderr
    r3, _ = write_override(tmp_path, "--force", root=repo)
    assert r3.returncode == 0


def test_arming_override_refuses_a_dirty_or_unknown_code_tree(tmp_path):
    from kernel.tests.test_code_sha import _repo
    repo = _repo(tmp_path)
    (repo / "nodes" / "a.py").write_text("x = 99\n")                      # uncommitted code
    r, path = write_override(tmp_path, root=repo)
    assert r.returncode == 2 and "dirty" in r.stderr and not path.exists()
    plain = tmp_path / "plain"
    plain.mkdir()
    r, path = write_override(tmp_path, root=plain)
    assert r.returncode == 2 and "unknown" in r.stderr and not path.exists()


def test_settle_takes_the_venues_fills_on_the_proofs_orders_not_the_files_memory():
    """2026-09-04: the resting bid the proof believed cancelled was hit nine minutes after the
    file was written. Settlement must cover every fill on the proof's own orders."""
    from ops.kalshi_live_proof import merge_venue_fills
    proof = {"steps": [{"resting": {"venue_order_id": "rest-1"}, "after_cancel": {"venue_order_id": "rest-1"}},
                       {"ioc": {"venue_order_id": "ioc-1"}, "status": {"venue_order_id": "ioc-1"},
                        "fills": [{"fill_id": "f-ioc", "contracts": 2.0, "price": 0.35, "charged": 0.0319, "pinned": 0.0319, "excess": 0.0, "taker": True}]}]}
    venue_fills = [FillRecord("kalshi", "ioc-1", "f-ioc", 2.0, 0.35, 0.0319, True, 1.0, True),
                   FillRecord("kalshi", "rest-1", "f-late", 1.0, 0.25, 0.0033, False, 2.0, True),
                   FillRecord("kalshi", "someone-elses", "f-other", 5.0, 0.5, 0.1, True, 3.0, True)]
    got = merge_venue_fills(proof, venue_fills)
    assert [f["fill_id"] for f in got] == ["f-ioc", "f-late"]
    late = got[1]
    assert late["late"] and late["contracts"] == 1.0 and late["price"] == 0.25 and late["charged"] == 0.0033 and late["taker"] is False
    assert got[0]["pinned"] == 0.0319, "the file's own record is kept as written"


def test_a_settled_proof_counts_the_late_fill_the_settle_step_found(tmp_path):
    """The resting bid hit after the file was written (2026-09-04): --settle recorded it under
    settled.fills, and the PnL arithmetic must be over those, not the file's original fills."""
    proof = {"ticker": "T", "won_when": "yes", "balance_before": 61.2445, "reservation_id": "r",
             "steps": [{"resting": {"venue_order_id": "a"}, "after_cancel": {"raw_status": "canceled", "filled_contracts": 0.0}},
                       {"ioc": {"state": "FILLED", "filled_contracts": 2.0}, "status": {"state": "FILLED", "final": True, "filled_contracts": 2.0},
                        "fills": [{"fill_id": "f1", "contracts": 2.0, "price": 0.35, "charged": 0.0319, "pinned": 0.0319, "excess": 0.0, "taker": True}],
                        "balance_after": 60.5126}],
             "settled": {"result": "yes", "realized_usd": 2.0148,
                         "fills": [{"fill_id": "f0", "contracts": 1.0, "price": 0.25, "charged": 0.0033, "pinned": None, "excess": 0.0, "taker": False, "late": True},
                                   {"fill_id": "f1", "contracts": 2.0, "price": 0.35, "charged": 0.0319, "pinned": 0.0319, "excess": 0.0, "taker": True}]}}
    f = by_name(proof_check.check_proof(proof, reservation_row=lambda r: {"released_utc": 1.0, "release_reason": "proof settled: yes"},
                                        open_rows_for_event=lambda e: 0))
    assert f["settled_pnl"].ok, f["settled_pnl"].detail
    assert "1 filled after the proof file was written" in f["settled_pnl"].detail

#!/usr/bin/env python3
"""GATE step 8 for Polymarket, on the real CLOB, tiny: rest -> cancel -> FOK fill -> confirm -> reconcile.

    python3 ops/polymarket_live_proof.py --slug mlb-sf-pit-2026-09-03 --outcome "San Francisco Giants"        # DRY RUN
    python3 ops/polymarket_live_proof.py --slug ... --outcome ... --arm                                       # sends
    python3 ops/polymarket_live_proof.py --settle /Volumes/Kilos/janus/proofs/polymarket_<ts>.json           # after the game
    python3 ops/polymarket_live_proof.py --check  /Volumes/Kilos/janus/proofs/polymarket_<ts>.json           # the checklist

THE OPERATOR RUNS THIS. Polymarket has no demo environment, so this is the first real order on the
venue (GATE_TO_LIVE step 8 pushback). It needs LIMITED_LIVE, which needs the arming override
(ops/arming_override.py) with a statement that names Polymarket, a funded wallet whose key sits in
a 600-mode file named by JANUS_PM_WALLET_KEY_PATH (never in track_b.env), and it refuses without
--arm. Everything goes through the same nodes a trade would: the mode gate, a proof clearance from
nodes/risk, the exec_polymarket adapter over py_clob_client (journal before the wire, no retry),
and nodes/reconcile for fills, fees and settlement.

What it does, in order:
  1. reads the Gamma market for the slug (fee schedule, min order size, tick, tokens) and the CLOB
     book for the chosen outcome's YES token; refuses a market with no two-sided touch;
  2. RESTING: a GTC bid for the minimum size well below the touch, polls it `live`, cancels it,
     confirms canceled with nothing matched -- the cancel path, proven without a fill;
  3. FILL: a FOK buy of --shares (default: the market's orderMinSize) at the best ask; `matched` is
     FILLED for hedging with settlement pending; polls fills() until the trade is CONFIRMED on-chain
     (MATCHED -> MINED -> CONFIRMED) or FAILED; compares the charged fee with the pinned curve at the
     market's own feeSchedule rate;
  4. balance before and after; writes a proof file. The position is held to settlement.
--settle later reads the Gamma market's result, computes realized PnL per nodes/reconcile.settle,
checks the balance delta, and releases the reservation. --check runs ops/proof_check.py.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.execution_protocol import OrderRequest  # noqa: E402
from kernel.fetch import Client  # noqa: E402
from kernel.schema import FillState, Mode  # noqa: E402
from nodes.entities.leagues import league_for_prefix  # noqa: E402
from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport, TransportUnavailable  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.fees.models import Fill  # noqa: E402
from nodes.fees.registry import model_for, params_for  # noqa: E402
from nodes.reconcile.reconcile import releasable, settle  # noqa: E402
from nodes.reconcile.results import fetch_pm_market, polymarket_result  # noqa: E402
from nodes.risk.breaker import LossBreaker  # noqa: E402
from nodes.risk.clearance import Candidate, clear_proof  # noqa: E402
from nodes.risk.gate import resolve_mode  # noqa: E402
from nodes.risk.kill import KillSwitches  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402
from nodes.store_tuples.store import DEFAULT_DB, TupleStore  # noqa: E402
from nodes.venue_polymarket.books import (PM_CLOB, PM_GAMMA, pm_book, pm_fee_params, pm_order_limits,  # noqa: E402
                                          pm_outcome_tokens, pm_primary_market)
from ops.proof_check import run_check  # noqa: E402

from kernel.paths import PROOFS, PROOF_DB  # noqa: E402,F401
CONFIRM_WAIT_S = 120.0


def _runner_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def _key_file_ok() -> tuple[bool, str]:
    path = os.environ.get("JANUS_PM_WALLET_KEY_PATH")
    if not path:
        return False, "JANUS_PM_WALLET_KEY_PATH is unset"
    if not os.path.exists(path):
        return False, f"{path} does not exist"
    if (os.stat(path).st_mode & 0o077) != 0:
        return False, f"{path} must be mode 600"
    return True, path


def _poll(venue, cid: str, *, seconds: float, step: float):
    t0 = time.time()
    st = venue.status(cid)
    while not st.final and time.time() - t0 < seconds:
        time.sleep(step)
        st = venue.status(cid)
    return st


def plan(a, cl: Client) -> dict | int:
    """Step 1: everything read-only. Returns the plan dict or an exit code."""
    ev = cl.get_json(f"{PM_GAMMA}/events", params={"slug": a.slug}, use_cache=False)
    ev = ev[0] if isinstance(ev, list) and ev else None
    if not ev:
        print(f"{a.slug}: no Gamma event", file=sys.stderr)
        return 2
    tokens = pm_outcome_tokens(ev, a.slug)
    if a.token:
        token = a.token
        outcome = next((n for n, t in tokens.items() if t == token), a.outcome or token)
    else:
        if a.outcome not in tokens:
            print(f"{a.slug}: outcome {a.outcome!r} is not one of {sorted(tokens)}", file=sys.stderr)
            return 2
        outcome, token = a.outcome, tokens[a.outcome]
    market = pm_primary_market(ev, a.slug) or {}
    fees = pm_fee_params(market)
    if fees is None:
        print(f"{a.slug}: the Gamma market carries no feeSchedule; refusing (never defaulted)", file=sys.stderr)
        return 2
    limits = pm_order_limits(market)
    min_size, tick = float(limits.get("min_order_contracts", 5.0)), float(limits.get("tick", 0.01))
    prefix = a.slug.split("-", 1)[0]
    league = league_for_prefix(prefix)
    if league is None:
        print(f"{a.slug}: prefix {prefix!r} is not a registered league (nodes/entities/leagues.py); refusing", file=sys.stderr)
        return 2
    book = pm_book(cl.get_json(f"{PM_CLOB}/book", params={"token_id": token}, use_cache=False), time.time())
    if not (book.best_bid and book.best_ask):
        print(f"{a.slug}/{outcome}: no two-sided touch ({book.best_bid}/{book.best_ask}); pick a live market", file=sys.stderr)
        return 2
    ask, bid = book.best_ask.price, book.best_bid.price
    shares = float(a.shares) if a.shares else min_size
    if shares < min_size:
        print(f"--shares {shares:g} is below the market's minimum {min_size:g}", file=sys.stderr)
        return 2
    resting_px = round(max(tick, min(bid - 0.05, ask - 0.10)), 2)
    print(f"[market] {a.slug} outcome {outcome!r} token …{token[-8:]} bid {bid:.2f} ask {ask:.2f} (ask size {book.best_ask.size:.0f}); "
          f"fees {fees}; min {min_size:g} tick {tick}")
    print(f"[plan] 1. RESTING bid {min_size:g} @ {resting_px:.2f} then cancel   2. FOK buy {shares:g} @ {ask:.2f} = ${shares * ask:.2f} stake")
    return {"event": ev, "market": market, "outcome": outcome, "token": token, "fees": fees, "league": league,
            "ask": ask, "bid": bid, "shares": shares, "min_size": min_size, "resting_px": resting_px, "tick": tick}


def run_proof(a, transport_factory=None) -> int:
    """`transport_factory()` builds the CLOB transport; the default is PyClobTransport (the wallet
    key). Tests inject a fake and drive `execute_steps` directly."""
    cl = Client("polymarket-proof", rate=4, burst=8, cache_dir=None)
    p = plan(a, cl)
    if isinstance(p, int):
        return p
    ok, why = _key_file_ok()
    limits, kill = load_limits(), KillSwitches()
    resolved = resolve_mode("LIMITED_LIVE", env=os.environ, kill=kill, limits=limits, runner_sha=_runner_sha(),
                            credentials_present={"polymarket": ok})
    if hasattr(resolved, "code"):
        print(f"[gate] LIMITED_LIVE refused: {resolved.code}: {resolved.detail}")
        if resolved.code == "CREDENTIALS":
            print(f"       {why}: the wallet key lives in its own 600-mode file, never in track_b.env")
        else:
            print("       write the override first: python3 ops/arming_override.py --mode LIMITED_LIVE ... (a statement naming Polymarket)")
        return 2
    print(f"[caps] override stake {resolved.caps.get('stake_usd')} max_contracts {resolved.caps.get('max_contracts')}")
    store = TupleStore(a.db)
    journal = Journal(store)
    try:
        transport = transport_factory() if transport_factory else PyClobTransport()
    except TransportUnavailable as exc:
        print(f"[transport] {exc}", file=sys.stderr)
        return 2
    venue = PolymarketExecution(transport, journal, resolved.mode)
    bal0 = venue.balance()
    if bal0 is None:
        print(f"balance could not be confirmed; refusing ({getattr(transport, 'last_error', None) or 'no error recorded'})", file=sys.stderr)
        return 2
    ledger, breaker = ExposureLedger(store), LossBreaker(kill=kill)
    event_id = f"proof:{p['token']}"
    stake = p["shares"] * p["ask"]
    cand = Candidate(f"proof:{uuid.uuid4().hex[:8]}", event_id, p["league"], (("polymarket", p["shares"], p["ask"]),),
                     -stake, -1.0, "proof-v1", 0.0)
    c = clear_proof(cand, mode=resolved.mode, limits=limits, ledger=ledger, kill=kill, breaker=breaker, fills_today=(),
                    balances={"polymarket": bal0.available_usd}, venues_connected={"polymarket": True}, caps=resolved.caps)
    if hasattr(c, "code"):
        print(f"risk refused the proof: {c.code}: {c.detail}", file=sys.stderr)
        return 2
    print(f"[risk] cleared: league {p['league']}, reservation {c.reservation.reservation_id[:8]}, balance {bal0.available_usd:.2f}")
    if not a.arm:
        ledger.release(c.reservation.reservation_id, reason="dry_run")
        print("dry run: nothing sent. Re-run with --arm to send.")
        return 0
    proof = execute_steps(venue, slug=a.slug, outcome=p["outcome"], token=p["token"], fees=p["fees"], ask=p["ask"],
                          resting_px=p["resting_px"], shares=p["shares"], min_size=p["min_size"], cand=cand, clearance=c,
                          kill=kill, balance_before=bal0, runner_sha=_runner_sha(), override_sha=resolved.override_sha)
    PROOFS.mkdir(parents=True, exist_ok=True)
    out = PROOFS / f"polymarket_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(proof, indent=2, default=str) + "\n")
    store.commit(); store.close()
    print(f"[proof  ] {out}  (run --settle {out} after the game settles)")
    return 0


def execute_steps(venue, *, slug: str, outcome: str, token: str, fees: dict, ask: float, resting_px: float,
                  shares: float, min_size: float, cand, clearance, kill, balance_before, runner_sha: str,
                  override_sha: str | None, sleep=time.sleep, poll_step: float = 1.0,
                  confirm_wait_s: float = CONFIRM_WAIT_S) -> dict:
    """Steps 2-4 against an already-cleared candidate. Returns the proof dict; the caller writes it."""
    bal0 = balance_before
    proof = {"venue": venue.venue, "slug": slug, "outcome": outcome, "token": token, "ticker": None, "fees": fees,
             "contracts": shares, "won_when": outcome, "started_utc": datetime.now(timezone.utc).isoformat(),
             "balance_before": bal0.available_usd, "reservation_id": clearance.reservation.reservation_id,
             "runner_sha": runner_sha, "override_sha": override_sha, "steps": []}

    # 2. RESTING -> cancel (GTC well below the touch; `live` is the venue's word for open)
    r1 = OrderRequest("polymarket", token, outcome, "buy_yes", resting_px, min_size, "gtc", uuid.uuid4().hex, cand.opportunity_id)
    ack1 = venue.submit(r1, clearance)
    print(f"[resting] {ack1.state.value} {ack1.raw_status} venue_id={ack1.venue_order_id} {ack1.detail}")
    st1 = _poll(venue, r1.client_order_id, seconds=3.0, step=poll_step)
    print(f"[resting] status {st1.state.value} open={st1.open} matched={st1.filled_contracts}")
    cx = venue.cancel(r1.client_order_id)
    print(f"[cancel ] {cx.state.value} {cx.raw_status} matched={cx.filled_contracts}")
    if cx.open:                    # a cancel is processed asynchronously; record the venue's final word (2026-09-07, Kalshi)
        cx = _poll(venue, r1.client_order_id, seconds=6.0, step=poll_step)
        print(f"[cancel ] confirmed {cx.state.value} {cx.raw_status} open={cx.open} matched={cx.filled_contracts}")
    proof["steps"].append({"resting": ack1.__dict__, "after_cancel": cx.__dict__})
    if cx.filled_contracts > 0:
        print("the resting bid matched (the book moved through it): counted as part of the fill proof")

    # 3. FILL: FOK at the best ask; matched -> FILLED with settlement pending, then CONFIRMED on-chain
    r2 = OrderRequest("polymarket", token, outcome, "buy_yes", ask, float(shares), "fok", uuid.uuid4().hex,
                      cand.opportunity_id, hedge=True)
    ack2 = venue.submit(r2, clearance)
    print(f"[fok    ] {ack2.state.value} {ack2.raw_status} matched={ack2.filled_contracts} @ {ack2.avg_price} pending={ack2.settlement_pending} {ack2.detail}")
    st2 = _poll(venue, r2.client_order_id, seconds=10.0, step=poll_step)
    print(f"[fok    ] status {st2.state.value} final={st2.final} matched={st2.filled_contracts}")
    # Matched is not settled: wait for the trade to be CONFIRMED (or FAILED) before believing the fill.
    t0 = time.time()
    mine, failed = [], False
    ids = {x for x in (ack1.venue_order_id, ack2.venue_order_id, st2.venue_order_id) if x}
    while time.time() - t0 < confirm_wait_s:
        recs = venue.fills(since_utc=time.time() - 900)
        mine = [f for f in recs if f.venue_order_id in ids]
        if mine and all(f.final for f in mine):
            break
        sleep(5.0)
    if ack2.state is FillState.FILLED and not mine:
        # the adapter drops FAILED trades from fills(); a matched order with no surviving trade is a reversal
        failed = True
    findings = []
    for f in mine:
        pinned = model_for("polymarket").entry_cost([Fill("polymarket", f.venue_order_id, token, "yes", f.price, f.contracts,
                                                          "taker" if f.is_taker else "maker", 0)], params_for("polymarket", fees))
        findings.append({"fill_id": f.fill_id, "contracts": f.contracts, "price": f.price, "charged": f.fee_usd,
                         "pinned": round(pinned, 4), "excess": round(max(0.0, f.fee_usd - pinned), 4), "taker": f.is_taker,
                         "confirmed": f.final})
        flag = "STOP: charged above the pinned curve" if f.fee_usd - pinned > 1e-6 else ("ok" if f.final else "NOT CONFIRMED")
        print(f"[fee    ] {f.contracts:.0f} @ {f.price:.2f} charged {f.fee_usd:.4f} pinned {pinned:.4f} -> {flag}")
    bal1 = venue.balance()
    status = st2.__dict__
    if failed:
        status = {**status, "state": "UNCONFIRMED", "final": False, "raw_status": "trade_failed"}
    proof["steps"].append({"ioc": ack2.__dict__, "status": status, "fills": findings,
                           "balance_after": bal1.available_usd if bal1 else None})
    if bal1 is not None:
        spent = sum(f["contracts"] * f["price"] + f["charged"] for f in findings)
        print(f"[balance] {bal0.available_usd:.4f} -> {bal1.available_usd:.4f} (delta {bal1.available_usd - bal0.available_usd:+.4f}; fills+fees {spent:.4f})")
    if failed:
        proof["stop"] = "TRADE_FAILED"
        print("the matched trade FAILED on-chain: a reversal. Reservation kept; reconcile by hand before anything else.")
    if any(x["excess"] > 1e-6 for x in findings):
        kill.latch("live", "proof: a charged fee exceeded the pinned curve; re-pin before anything else")
        proof["stop"] = "FEE_ABOVE_PIN"
    if mine and not all(f["confirmed"] for f in findings):
        proof["stop"] = proof.get("stop") or "NOT_CONFIRMED"
    return proof


def run_settle(a) -> int:
    proof = json.loads(Path(a.settle).read_text())
    cl = Client("polymarket-proof", rate=4, burst=8, cache_dir=None)
    m = fetch_pm_market(proof["slug"], cl)
    r = polymarket_result(m or {}) if m else None
    if r is None:
        print(f"{proof['slug']}: not resolved yet")
        return 1
    fills = [f for s in proof["steps"] for f in s.get("fills", [])]
    legs = [{"venue": "polymarket", "client_order_id": f["fill_id"], "outcome_id": proof["token"], "side": "buy_yes",
             "contracts": f["contracts"], "price": f["price"], "fee_usd": f["charged"], "state": "FILLED", "final": bool(f.get("confirmed", True))}
            for f in fills]
    won = r == proof["outcome"] or r == "Yes"
    realized = settle(legs=legs, winners={"polymarket": proof["token"] if won else "other"})
    pnl = sum(x.realized_usd for x in realized)
    print(f"[settle ] {proof['slug']} result={r!r}: realized {pnl:+.4f} USD over {len(fills)} fills; releasable={releasable(realized)}")
    store = TupleStore(a.db)
    ledger = ExposureLedger(store)
    if releasable(realized) and ledger.release(proof["reservation_id"], reason=f"proof settled: {r}"):
        print("[ledger ] reservation released")
    Path(a.settle).write_text(json.dumps({**proof, "settled": {"result": proof["outcome"] if won else "other", "venue_result": r,
                                                              "realized_usd": pnl, "at": datetime.now(timezone.utc).isoformat()}},
                                         indent=2, default=str) + "\n")
    store.commit(); store.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", help="the Gamma event slug of a live full-game moneyline, e.g. mlb-sf-pit-2026-09-03")
    ap.add_argument("--outcome", help="the outcome label to buy, as Gamma names it (or 'Draw')")
    ap.add_argument("--token", help="the outcome's YES token id, instead of --outcome")
    ap.add_argument("--shares", type=float, default=None, help="default: the market's orderMinSize")
    ap.add_argument("--arm", action="store_true", help="actually send; without it this is a dry run")
    ap.add_argument("--settle", help="a proof file to settle and reconcile")
    ap.add_argument("--check", help="a proof file to run the post-proof checklist over (no network)")
    ap.add_argument("--db", type=Path, default=PROOF_DB, help="the proofs' own database (journal, reservations); --check and --settle read the same file")
    a = ap.parse_args()
    if a.check:
        return run_check(a.check, a.db)
    if a.settle:
        return run_settle(a)
    if not a.slug or not (a.outcome or a.token):
        ap.error("--slug and --outcome (or --token) are required (or --settle / --check)")
    return run_proof(a)


if __name__ == "__main__":
    raise SystemExit(main())

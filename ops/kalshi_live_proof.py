#!/usr/bin/env python3
"""GATE step 8 for Kalshi, on the production account, tiny: place -> poll -> cancel -> fill -> reconcile.

    python3 ops/kalshi_live_proof.py --ticker KXMLBGAME-26SEP03...-STL            # DRY RUN: prints the plan
    python3 ops/kalshi_live_proof.py --ticker KXMLBGAME-26SEP03...-STL --arm      # sends the orders
    python3 ops/kalshi_live_proof.py --settle /Volumes/Kilos/janus/proofs/kalshi_<ts>.json   # after the game
    python3 ops/kalshi_live_proof.py --check  /Volumes/Kilos/janus/proofs/kalshi_<ts>.json   # the checklist, any time

THE OPERATOR RUNS THIS. It needs LIMITED_LIVE, which needs the arming override
(ops/arming_override.py) with your statement, and it refuses without --arm. Everything goes
through the same nodes a trade would: the mode gate, a proof clearance from nodes/risk (every
fail-closed check minus the profit thresholds, capped by the override), the exec_kalshi adapter
(journal before the wire, no retry), and nodes/reconcile for fills, fees and settlement.

What it does, in order:
  1. reads the book; refuses a market with no two-sided touch;
  2. RESTING: a GTC bid for 1 contract well below the touch, polls it open, cancels it, confirms
     canceled with nothing filled -- the cancel path, proven without a fill;
  3. FILL: an IOC buy of --contracts at the best ask; polls until the venue's word is final;
     pulls fills; compares the charged fee with the pinned curve at the series multiplier;
  4. balance before and after; writes a proof file. The position is held to settlement.
--settle later reads the market result, computes realized PnL per nodes/reconcile.settle, feeds
the loss breaker's FIFO, checks the balance delta, and releases the reservation. --check runs the
post-proof checklist (ops/proof_check.py) over the file: resting -> canceled, IOC final, fees at
the pin, balance delta, and after settlement the realized PnL and the released reservation.
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
from kernel.schema import FillState  # noqa: E402
from nodes.exec_kalshi.client import PROD_BASE, KalshiExecution  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.fees.registry import model_for, params_for  # noqa: E402
from nodes.fees.models import Fill  # noqa: E402
from nodes.reconcile.reconcile import releasable, settle  # noqa: E402
from nodes.reconcile.results import fetch_kalshi_market, kalshi_result  # noqa: E402
from nodes.risk.breaker import LossBreaker  # noqa: E402
from nodes.risk.clearance import Candidate, clear_proof  # noqa: E402
from nodes.risk.gate import resolve_mode  # noqa: E402
from nodes.risk.kill import KillSwitches  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402
from nodes.store_tuples.store import DEFAULT_DB, TupleStore  # noqa: E402
from nodes.entities.leagues import kalshi_series, league_for_series  # noqa: E402
from nodes.stream_kalshi.stream import load_private_key  # noqa: E402
from nodes.venue_kalshi.books import KALSHI_BASE, fetch_kalshi_series, kalshi_book, kalshi_fee_params  # noqa: E402
from ops.proof_check import run_check  # noqa: E402

PROOFS = Path("/Volumes/Kilos/janus/proofs")
#: The proofs' own journal, ledger and reservations. Not the lane's file: the lane holds write locks on
#: it for the length of a report period, and a proof must never wait on, or race, the observation lane.
PROOF_DB = Path("/Volumes/Kilos/janus/tuples/proofs.sqlite")


def _runner_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def _poll(venue, cid: str, *, seconds: float = 10.0, step: float = 0.5):
    t0 = time.time()
    st = venue.status(cid)
    while not st.final and time.time() - t0 < seconds:
        time.sleep(step)
        st = venue.status(cid)
    return st


def run_proof(a, venue_factory=None) -> int:
    """`venue_factory(api_key, private_key, journal, mode)` builds the execution venue; the default is
    the production Kalshi adapter. Tests inject a fake and drive `execute_steps` directly."""
    api_key, key_path = os.environ.get("JANUS_KALSHI_API_KEY"), os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH")
    if not (api_key and key_path):
        print("source the credentials env first (JANUS_KALSHI_API_KEY / JANUS_KALSHI_PRIVATE_KEY_PATH)", file=sys.stderr)
        return 2
    cl = Client("kalshi-proof", rate=4, burst=8, cache_dir=None)
    payload = cl.get_json(f"{KALSHI_BASE}/markets/{a.ticker}/orderbook", params={"depth": 10}, use_cache=False)
    book = kalshi_book(payload, "yes", time.time(), depth_requested=10)
    if not (book.best_bid and book.best_ask):
        print(f"{a.ticker}: no two-sided touch ({book.best_bid}/{book.best_ask}); pick a live game market", file=sys.stderr)
        return 2
    series_ticker = a.ticker.split("-")[0]
    # The risk ledger caps exposure PER LEAGUE (limits.toml [events.per_league_usd]); an unknown
    # league caps at zero, so the series must map back to one before anything else.
    league = league_for_series(series_ticker)
    if league is None:
        print(f"{series_ticker}: not a registered game series ({sorted(kalshi_series().values())}); refusing", file=sys.stderr)
        return 2
    fees = kalshi_fee_params(fetch_kalshi_series(series_ticker, cl))
    if fees is None:
        print(f"{series_ticker}: no fee schedule; refusing", file=sys.stderr)
        return 2
    ask, bid = book.best_ask.price, book.best_bid.price
    resting_px = round(max(0.01, min(bid - 0.05, ask - 0.10)), 2)
    stake = a.contracts * ask
    print(f"[book] {a.ticker} bid {bid:.2f} ask {ask:.2f} (ask size {book.best_ask.size:.0f}); series {series_ticker} {fees}")
    print(f"[plan] 1. RESTING bid 1 @ {resting_px:.2f} then cancel   2. IOC buy {a.contracts:.0f} @ {ask:.2f} = ${stake:.2f} stake")
    limits, kill = load_limits(), KillSwitches()
    resolved = resolve_mode("LIMITED_LIVE", env=os.environ, kill=kill, limits=limits, runner_sha=_runner_sha(),
                            credentials_present={"kalshi": True})
    if hasattr(resolved, "code"):
        print(f"[gate] LIMITED_LIVE refused: {resolved.code}: {resolved.detail}")
        print("       write the override first: python3 ops/arming_override.py --mode LIMITED_LIVE ...")
        return 2
    print(f"[caps] override stake {resolved.caps.get('stake_usd')} max_contracts {resolved.caps.get('max_contracts')}")

    store = TupleStore(a.db)
    journal = Journal(store)
    if venue_factory is None:
        venue = KalshiExecution(api_key, load_private_key(key_path), journal, resolved.mode, base_url=PROD_BASE)
    else:
        venue = venue_factory(api_key, load_private_key(key_path), journal, resolved.mode)
    bal0 = venue.balance()
    if bal0 is None:
        print("balance could not be confirmed; refusing", file=sys.stderr)
        return 2
    ledger, breaker = ExposureLedger(store), LossBreaker(kill=kill)
    event_id = f"proof:{a.ticker}"
    cand = Candidate(f"proof:{uuid.uuid4().hex[:8]}", event_id, league, (("kalshi", float(a.contracts), ask),),
                     -stake, -1.0, "proof-v1", 0.0)
    c = clear_proof(cand, mode=resolved.mode, limits=limits, ledger=ledger, kill=kill, breaker=breaker, fills_today=(),
                    balances={"kalshi": bal0.available_usd}, venues_connected={"kalshi": True}, caps=resolved.caps)
    if hasattr(c, "code"):
        print(f"risk refused the proof: {c.code}: {c.detail}", file=sys.stderr)
        return 2
    print(f"[risk] cleared: league {league}, reservation {c.reservation.reservation_id[:8]}, balance {bal0.available_usd:.2f}")
    if not a.arm:
        # The dry run goes through the same gate and clearance as the real thing, so a refusal
        # surfaces here and not after the operator has typed --arm. Its reservation is released.
        ledger.release(c.reservation.reservation_id, reason="dry_run")
        print("dry run: nothing sent. Re-run with --arm to send.")
        return 0
    proof = execute_steps(venue, ticker=a.ticker, series=series_ticker, fees=fees, ask=ask, resting_px=resting_px,
                          contracts=float(a.contracts), cand=cand, clearance=c, kill=kill, balance_before=bal0,
                          runner_sha=_runner_sha(), override_sha=resolved.override_sha)
    PROOFS.mkdir(parents=True, exist_ok=True)
    out = PROOFS / f"kalshi_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(proof, indent=2, default=str) + "\n")
    store.commit(); store.close()
    print(f"[proof  ] {out}  (run --settle {out} after the game settles)")
    return 0


def execute_steps(venue, *, ticker: str, series: str, fees: dict, ask: float, resting_px: float, contracts: float,
                  cand, clearance, kill, balance_before, runner_sha: str, override_sha: str | None,
                  sleep=time.sleep, poll_step: float = 0.5) -> dict:
    """Steps 2-4 against an already-cleared candidate: the resting bid and its cancel, the IOC fill,
    the fee comparison, the balance delta, the STOP latch. Returns the proof dict; the caller writes
    it. Everything on the wire goes through `venue` (an ExecutionVenue), so a fake drives it offline."""
    bal0 = balance_before
    proof = {"venue": venue.venue, "ticker": ticker, "series": series, "fees": fees, "contracts": contracts,
             "won_when": "yes", "started_utc": datetime.now(timezone.utc).isoformat(),
             "balance_before": bal0.available_usd, "reservation_id": clearance.reservation.reservation_id,
             "runner_sha": runner_sha, "override_sha": override_sha, "steps": []}

    # 2. RESTING -> cancel
    r1 = OrderRequest("kalshi", ticker, ticker, "buy_yes", resting_px, 1.0, "gtc", uuid.uuid4().hex, cand.opportunity_id)
    ack1 = venue.submit(r1, clearance)
    print(f"[resting] {ack1.state.value} {ack1.raw_status} venue_id={ack1.venue_order_id} {ack1.detail}")
    st1 = _poll(venue, r1.client_order_id, seconds=3.0, step=poll_step)
    print(f"[resting] status {st1.state.value} open={st1.open} filled={st1.filled_contracts}")
    cx = venue.cancel(r1.client_order_id)
    print(f"[cancel ] {cx.state.value} {cx.raw_status} filled={cx.filled_contracts}")
    proof["steps"].append({"resting": ack1.__dict__, "after_cancel": cx.__dict__})
    if cx.filled_contracts > 0:
        print("the resting bid filled (the book moved through it): counted as part of the fill proof")

    # 3. FILL
    r2 = OrderRequest("kalshi", ticker, ticker, "buy_yes", ask, float(contracts), "ioc", uuid.uuid4().hex,
                      cand.opportunity_id, hedge=True)
    ack2 = venue.submit(r2, clearance)
    print(f"[ioc    ] {ack2.state.value} {ack2.raw_status} filled={ack2.filled_contracts} @ {ack2.avg_price} fee={ack2.fee_usd} {ack2.detail}")
    st2 = _poll(venue, r2.client_order_id, seconds=10.0, step=poll_step)
    print(f"[ioc    ] status {st2.state.value} final={st2.final} filled={st2.filled_contracts} fee={st2.fee_usd}")
    sleep(2.0)
    fills = venue.fills(since_utc=time.time() - 600)
    mine = [f for f in fills if f.venue_order_id in {ack1.venue_order_id, ack2.venue_order_id, st2.venue_order_id}]
    findings = []
    for f in mine:
        pinned = model_for("kalshi").entry_cost([Fill("kalshi", f.venue_order_id, ticker, "yes", f.price, f.contracts,
                                                      "taker" if f.is_taker else "maker", 0)], params_for("kalshi", fees))
        findings.append({"fill_id": f.fill_id, "contracts": f.contracts, "price": f.price, "charged": f.fee_usd,
                         "pinned": round(pinned, 4), "excess": round(max(0.0, f.fee_usd - pinned), 4), "taker": f.is_taker})
        flag = "STOP: charged above the pinned curve" if f.fee_usd - pinned > 1e-6 else "ok"
        print(f"[fee    ] {f.contracts:.0f} @ {f.price:.2f} charged {f.fee_usd:.4f} pinned {pinned:.4f} -> {flag}")
    bal1 = venue.balance()
    proof["steps"].append({"ioc": ack2.__dict__, "status": st2.__dict__, "fills": findings,
                           "balance_after": bal1.available_usd if bal1 else None})
    if bal1 is not None:
        spent = sum(f["contracts"] * f["price"] + f["charged"] for f in findings)
        print(f"[balance] {bal0.available_usd:.4f} -> {bal1.available_usd:.4f} (delta {bal1.available_usd - bal0.available_usd:+.4f}; "
              f"fills+fees {spent:.4f})")
    if any(x["excess"] > 1e-6 for x in findings):
        kill.latch("live", "proof: a charged fee exceeded the pinned curve; re-pin before anything else")
        proof["stop"] = "FEE_ABOVE_PIN"
    return proof


def run_settle(a) -> int:
    proof = json.loads(Path(a.settle).read_text())
    api_key, key_path = os.environ.get("JANUS_KALSHI_API_KEY"), os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH")
    cl = Client("kalshi-proof", rate=4, burst=8, cache_dir=None)
    m = fetch_kalshi_market(proof["ticker"], cl)
    r = kalshi_result(m)
    if r is None:
        print(f"{proof['ticker']}: not settled yet ({m.get('market', m).get('status')})")
        return 1
    fills = [f for s in proof["steps"] for f in s.get("fills", [])]
    legs = [{"venue": "kalshi", "client_order_id": f["fill_id"], "outcome_id": proof["ticker"], "side": "buy_yes",
             "contracts": f["contracts"], "price": f["price"], "fee_usd": f["charged"], "state": "FILLED", "final": True}
            for f in fills]
    realized = settle(legs=legs, winners={"kalshi": proof["ticker"] if r == "yes" else "other"})
    pnl = sum(x.realized_usd for x in realized)
    print(f"[settle ] {proof['ticker']} result={r}: realized {pnl:+.4f} USD over {len(fills)} fills; releasable={releasable(realized)}")
    store = TupleStore(a.db)
    ledger = ExposureLedger(store)
    if releasable(realized) and ledger.release(proof["reservation_id"], reason=f"proof settled: {r}"):
        print("[ledger ] reservation released")
    if api_key and key_path:
        venue = KalshiExecution(api_key, load_private_key(key_path), Journal(store), __import__("kernel.schema", fromlist=["Mode"]).Mode.LIMITED_LIVE, base_url=PROD_BASE)
        b = venue.balance()
        if b is not None:
            print(f"[balance] before {proof['balance_before']:.4f} now {b.available_usd:.4f} (delta {b.available_usd - proof['balance_before']:+.4f})")
    Path(a.settle).write_text(json.dumps({**proof, "settled": {"result": r, "realized_usd": pnl,
                                                              "at": datetime.now(timezone.utc).isoformat()}}, indent=2, default=str) + "\n")
    store.commit(); store.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ticker", help="a live game market, e.g. KXMLBGAME-26SEP03...-STL")
    ap.add_argument("--contracts", type=float, default=2.0)
    ap.add_argument("--arm", action="store_true", help="actually send; without it this is a dry run")
    ap.add_argument("--settle", help="a proof file to settle and reconcile")
    ap.add_argument("--check", help="a proof file to run the post-proof checklist over (no network)")
    ap.add_argument("--db", type=Path, default=PROOF_DB, help="the proofs' own database (journal, reservations); --check and --settle read the same file")
    a = ap.parse_args()
    if a.check:
        return run_check(a.check, a.db)
    if a.settle:
        return run_settle(a)
    if not a.ticker:
        ap.error("--ticker is required (or --settle)")
    return run_proof(a)


if __name__ == "__main__":
    raise SystemExit(main())

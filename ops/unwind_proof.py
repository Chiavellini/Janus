#!/usr/bin/env python3
"""The unwind proof (hedge protection R4, 2026-09-08): buy the venue's minimum, sell it straight
back, and check the venue agrees. Real money, tiny, THE OPERATOR RUNS IT.

    python3 ops/unwind_proof.py --venue polymarket --slug <gamma slug> --outcome "<label>"     # dry run
    python3 ops/unwind_proof.py --venue polymarket --slug ... --outcome ... --arm               # sends
    python3 ops/unwind_proof.py --venue kalshi --ticker KXMLBGAME-...-XXX [--contracts 1]      # dry run
    python3 ops/unwind_proof.py --venue kalshi --ticker ... --arm                               # sends
    python3 ops/unwind_proof.py --check /Volumes/Kilos/janus/proofs/unwind_<venue>_<ts>.json   # the verdict, no network

Before the protection layer is trusted to sell a position back on its own (release R5), the sell
path is proven on each venue exactly as the layer will use it: a `sell_yes` IOC through the
same adapter, the same journal-before-the-wire rule, a proof clearance from nodes/risk (the buy
is its first leg, the sell a protective leg under `arm_hedge`). On Polymarket the sell needs the
conditional-token allowance, which the adapter sets on the first sell of a token; that is part
of what is proven. What the proof checks, from the venue's own record: the buy filled, the sell
filled for the same size, the venue holds nothing on the market afterwards (positions()), the
fills are final (Polymarket: CONFIRMED on-chain), and the balance moved by the spread plus the
fees and no more. The stake is the venue's minimum (Polymarket: orderMinSize and $1 of notional;
Kalshi: 1 contract) and the loss is the spread: cents.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.code_sha import code_tree_sha  # noqa: E402
from kernel.execution_protocol import OrderRequest  # noqa: E402
from kernel.fetch import Client  # noqa: E402
from kernel.paths import DATA_ROOT  # noqa: E402
from kernel.schema import FillState  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.risk.breaker import LossBreaker  # noqa: E402
from nodes.risk.clearance import Candidate, clear_proof  # noqa: E402
from nodes.risk.gate import resolve_mode  # noqa: E402
from nodes.risk.kill import KillSwitches  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402

PROOFS = Path(DATA_ROOT) / "proofs"
PROOF_DB = Path(DATA_ROOT) / "tuples" / "proofs.sqlite"
CONFIRM_WAIT_S = 120.0


def _runner_sha() -> str:
    try:
        import subprocess
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _poll(venue, cid: str, *, seconds: float, step: float, sleep=time.sleep):
    t0 = time.monotonic()
    st = venue.status(cid)
    while not (st.final or st.filled_contracts > 0 or st.state is FillState.REJECTED) and time.monotonic() - t0 < seconds:
        sleep(step)
        st = venue.status(cid)
    return st


def execute_steps(venue, *, market_id: str, outcome_id: str, size: float, ask: float, bid: float, tick: float,
                  cand, clearance, balance_before, runner_sha: str, override_sha: str | None,
                  sleep=time.sleep, poll_step: float = 1.0, confirm_wait_s: float = CONFIRM_WAIT_S,
                  mono=time.monotonic) -> dict:
    """Buy `size` IOC at `ask`, sell it IOC at `bid`, then ask the venue what it holds and what it
    charged. Everything on the wire goes through `venue`; a paper venue drives it offline."""
    proof = {"kind": "unwind", "venue": venue.venue, "market_id": market_id, "outcome_id": outcome_id, "size": size,
             "started_utc": datetime.now(timezone.utc).isoformat(), "balance_before": balance_before.available_usd,
             "reservation_id": clearance.reservation.reservation_id if clearance.reservation else None,
             "runner_sha": runner_sha, "override_sha": override_sha, "steps": [], "ok": False, "stop": None}
    # 1. BUY the minimum, IOC at the best ask
    buy = OrderRequest(venue.venue, market_id, outcome_id, "buy_yes", ask, size, "ioc", uuid.uuid4().hex, cand.opportunity_id)
    a1 = venue.submit(buy, clearance)
    s1 = _poll(venue, buy.client_order_id, seconds=30.0, step=poll_step, sleep=sleep) if a1.state is FillState.UNCONFIRMED else None
    bought = (s1.filled_contracts if s1 else a1.filled_contracts) or 0.0
    buy_avg = (s1.avg_price if s1 else a1.avg_price)
    proof["steps"].append({"buy": a1.__dict__, "status": s1.__dict__ if s1 else None, "bought": bought, "avg": buy_avg})
    if bought <= 0:
        proof["stop"] = f"BUY_UNFILLED: {a1.raw_status} {a1.detail}"
        return proof
    # 2. SELL it back, IOC at the best bid (the protective leg of the same clearance)
    clearance.arm_hedge(mono())
    sell = OrderRequest(venue.venue, market_id, outcome_id, "sell_yes", max(tick, bid), bought, "ioc", uuid.uuid4().hex,
                        cand.opportunity_id, hedge=True)
    a2 = venue.submit(sell, clearance)
    s2 = _poll(venue, sell.client_order_id, seconds=30.0, step=poll_step, sleep=sleep) if a2.state is FillState.UNCONFIRMED else None
    sold = (s2.filled_contracts if s2 else a2.filled_contracts) or 0.0
    sell_avg = (s2.avg_price if s2 else a2.avg_price)
    proof["steps"].append({"sell": a2.__dict__, "status": s2.__dict__ if s2 else None, "sold": sold, "avg": sell_avg})
    if sold < bought - 1e-6:
        proof["stop"] = f"SELL_SHORT: bought {bought:g}, sold {sold:g} ({a2.raw_status} {a2.detail}); a position is held: close it by hand"
        return proof
    # 3. the venue's record: fills final, nothing held, the balance moved by spread + fees
    t0 = time.monotonic()
    fills = []
    while True:                                                       # at least one read; then until final or the wait is up
        since = (getattr(venue, "clock", None) or time.time)() - 3600       # the venue's own clock (paper venues run on a test clock)
        fills = [f.__dict__ for f in venue.fills(since_utc=since)]
        ours = [f for f in fills if f.get("venue_order_id") in {a1.venue_order_id, a2.venue_order_id, s1.venue_order_id if s1 else None, s2.venue_order_id if s2 else None}]
        if (ours and all(f.get("final") for f in ours)) or time.monotonic() - t0 >= confirm_wait_s:
            break
        sleep(poll_step)
    pos = venue.positions() if hasattr(venue, "positions") else None
    held = None if pos is None else sum(p.contracts for p in pos if p.market_id == market_id)
    bal1 = venue.balance()
    fees = sum(float(f.get("fee_usd") or 0.0) for f in fills if f.get("venue_order_id") in {a1.venue_order_id, a2.venue_order_id})
    expected = -(bought * (buy_avg or ask)) + sold * (sell_avg or bid) - fees
    delta = (bal1.available_usd - balance_before.available_usd) if bal1 else None
    proof["steps"].append({"fills": fills, "held_after": held, "balance_after": bal1.available_usd if bal1 else None,
                           "fees_usd": fees, "expected_delta": round(expected, 4), "delta": None if delta is None else round(delta, 4)})
    checks = {"buy_filled": bought > 0, "sell_filled_all": sold >= bought - 1e-6,
              "nothing_held": held is not None and abs(held) <= 1e-6,
              "fills_final": bool(fills) and all(f.get("final") for f in fills if f.get("venue_order_id") in {a1.venue_order_id, a2.venue_order_id}),
              "balance_within_fees": delta is not None and abs(delta - expected) <= max(0.05, 0.02 * bought)}
    proof["checks"] = checks
    proof["ok"] = all(checks.values())
    proof["realized_usd"] = round(expected, 4)
    return proof


def run(a, *, venue_factory=None, sleep=time.sleep) -> int:
    limits, kill = load_limits(), KillSwitches()
    creds = {"polymarket": bool(os.environ.get("JANUS_PM_WALLET_KEY_PATH")), "kalshi": bool(os.environ.get("JANUS_KALSHI_API_KEY"))}
    resolved = resolve_mode("LIMITED_LIVE", env=os.environ, kill=kill, limits=limits, runner_sha=_runner_sha(),
                            code_sha=code_tree_sha(ROOT), credentials_present={a.venue: creds[a.venue]})
    if hasattr(resolved, "code"):
        print(f"[gate] LIMITED_LIVE refused: {resolved.code}: {resolved.detail}")
        return 2
    store = TupleStore(a.db)
    journal = Journal(store)
    cl = Client("unwind-proof", rate=4, burst=8, cache_dir=None)
    if a.venue == "polymarket":
        from ops.polymarket_live_proof import plan as pm_plan
        from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport
        p = pm_plan(a, cl)
        if isinstance(p, int):
            return p
        market_id, outcome_id, size, ask, tick, fees = p["token"], p["token"], p["shares"], p["ask"], 0.01, p["fees"]
        venue = venue_factory(journal, resolved.mode) if venue_factory else PolymarketExecution(PyClobTransport(), journal, resolved.mode, fee_params=fees)
        league = p["league"]
        bid = venue.orderbook(market_id, "sell_yes")
        bid = bid.bids[0].price if bid and bid.bids else None
    else:
        from nodes.entities.leagues import league_for_series
        from nodes.exec_kalshi.client import PROD_BASE, KalshiExecution
        from nodes.stream_kalshi.stream import load_private_key
        from nodes.venue_kalshi.books import KALSHI_BASE, kalshi_book
        payload = cl.get_json(f"{KALSHI_BASE}/markets/{a.ticker}/orderbook", params={"depth": 10}, use_cache=False)
        book = kalshi_book(payload, "yes", time.time(), depth_requested=10)
        if not (book.best_bid and book.best_ask):
            print(f"{a.ticker}: no two-sided touch; pick a live market", file=sys.stderr); return 2
        market_id = outcome_id = a.ticker
        size, ask, bid, tick = float(a.contracts), book.best_ask.price, book.best_bid.price, 0.01
        league = league_for_series(a.ticker.split("-")[0]) or "mlb"
        venue = (venue_factory(journal, resolved.mode) if venue_factory else
                 KalshiExecution(os.environ["JANUS_KALSHI_API_KEY"], load_private_key(os.environ["JANUS_KALSHI_PRIVATE_KEY_PATH"]),
                                 journal, resolved.mode, base_url=PROD_BASE))
    if bid is None:
        print("no bid to sell into; pick a market with a two-sided touch", file=sys.stderr); return 2
    bal0 = venue.balance()
    if bal0 is None:
        print("balance could not be confirmed; refusing", file=sys.stderr); return 2
    print(f"[plan] {a.venue} {market_id[-12:]}: buy {size:g} IOC @ {ask:.2f} then sell {size:g} IOC @ {bid:.2f}; "
          f"expected cost the spread {size * (ask - bid):.2f} + fees; balance {bal0.available_usd:.2f}")
    ledger, breaker = ExposureLedger(store), LossBreaker(kill=kill)
    cand = Candidate(f"unwind:{uuid.uuid4().hex[:8]}", f"proof:{market_id}", league, ((a.venue, size, ask),), -(size * ask), -1.0, "proof-v1", 0.0)
    c = clear_proof(cand, mode=resolved.mode, limits=limits, ledger=ledger, kill=kill, breaker=breaker, fills_today=(),
                    balances={a.venue: bal0.available_usd}, venues_connected={a.venue: True}, caps=resolved.caps)
    if hasattr(c, "code"):
        print(f"risk refused the proof: {c.code}: {c.detail}", file=sys.stderr); return 2
    if not a.arm:
        ledger.release(c.reservation.reservation_id, reason="dry_run")
        print("dry run: nothing sent. Re-run with --arm to send."); return 0
    proof = execute_steps(venue, market_id=market_id, outcome_id=outcome_id, size=size, ask=ask, bid=bid, tick=tick, cand=cand,
                          clearance=c, balance_before=bal0, runner_sha=_runner_sha(), override_sha=resolved.override_sha, sleep=sleep)
    ledger.release(c.reservation.reservation_id, reason="unwind proof: " + ("closed" if proof["ok"] else str(proof.get("stop"))))
    PROOFS.mkdir(parents=True, exist_ok=True)
    out = PROOFS / f"unwind_{a.venue}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(proof, indent=2, default=str) + "\n")
    store.commit(); store.close()
    print(f"[proof  ] {out}\n[verdict] {'OK' if proof['ok'] else 'NOT OK'} checks={proof.get('checks')} stop={proof.get('stop')}")
    return 0 if proof["ok"] else 1


def check(path: str) -> int:
    d = json.loads(Path(path).read_text())
    print(f"{d['venue']} {d['market_id'][-12:]} size {d['size']} ok={d['ok']} realized={d.get('realized_usd')} stop={d.get('stop')}")
    for k, v in (d.get("checks") or {}).items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    return 0 if d.get("ok") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--venue", choices=("polymarket", "kalshi"))
    ap.add_argument("--slug"); ap.add_argument("--outcome"); ap.add_argument("--token")
    ap.add_argument("--shares", type=float, default=None, help="Polymarket: default the market's orderMinSize")
    ap.add_argument("--ticker"); ap.add_argument("--contracts", type=float, default=1.0)
    ap.add_argument("--arm", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--db", type=Path, default=PROOF_DB)
    a = ap.parse_args()
    if a.check:
        return check(a.check)
    if not a.venue:
        ap.error("--venue is required (or --check)")
    if a.venue == "polymarket" and not (a.slug and (a.outcome or a.token)):
        ap.error("--slug and --outcome (or --token) are required for polymarket")
    if a.venue == "kalshi" and not a.ticker:
        ap.error("--ticker is required for kalshi")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())

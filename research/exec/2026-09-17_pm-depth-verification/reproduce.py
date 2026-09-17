#!/usr/bin/env python3
"""L146: reproduce the Polymarket depth-verification defect against the deployed classes.

Every object below is the real one from `nodes/`: `PolymarketStream`, `BookReplica`, `Reconciler`,
`due`, `AssetBook` and `KalshiStream`. Wire shapes are copied from their own test suites. The only
substitute is the Reconciler's REST `fetch` callable, which returns a fixed venue-truth ladder.

A lost websocket update is modelled by a local ladder holding a level the venue no longer has -- the
state a dropped removal or size cut leaves behind. Nothing under test is mocked or patched.

Each reproduction returns plain observations. `verdict()` applies the outcome rule registered in
spec.yaml. `python3 reproduce.py` prints the whole result as JSON.
"""
from __future__ import annotations

import json
import sys

from kernel.schema import Book, Quote
from nodes.book_replica.replica import BookReplica, Fault, ReplicaState
from nodes.execute.plan import vwap_for_size
from nodes.stream_kalshi.stream import KalshiStream
from nodes.stream_polymarket.protocol import AssetBook
from nodes.stream_polymarket.reconcile import Reconciler, due
from nodes.stream_polymarket.stream import PolymarketStream

SCHEMA = "janus.l146.pm_depth_verification.v1"
T = 1000.0
A = "asset-1"
SIZE = 25.0

#: The local book. Best price is LAST on the wire (protocol.py trap 2); the dict keys make order moot.
BOOK_DEEP = {
    "event_type": "book", "asset_id": A, "tick_size": "0.01",
    "bids": [{"price": "0.01", "size": "5"}, {"price": "0.19", "size": "10"}],
    "asks": [{"price": "0.23", "size": "10"}, {"price": "0.22", "size": "10"},
             {"price": "0.21", "size": "10"}, {"price": "0.20", "size": "8"}],
}
#: The venue's true book after a removal at 0.22 that never reached the local stream.
TRUTH_BIDS = [(0.19, 10.0), (0.01, 5.0)]
TRUTH_ASKS = [(0.20, 8.0), (0.21, 10.0), (0.23, 10.0)]
PHANTOM = 0.22


def change(price, size, side="BUY", bb=None, ba=None, aid=A) -> dict:
    """Same shape as nodes/stream_polymarket/tests/test_polymarket.py:change."""
    ch = {"asset_id": aid, "price": str(price), "size": str(size), "side": side}
    if bb is not None:
        ch["best_bid"] = str(bb)
    if ba is not None:
        ch["best_ask"] = str(ba)
    return {"event_type": "price_change", "price_changes": [ch]}


def _replica() -> BookReplica:
    # As the poller builds Polymarket replicas: external verification, 30 s budget.
    return BookReplica("polymarket", A, verification="external", max_unverified_s=30.0,
                       heartbeat_timeout_s=120.0)


def _vwap_c(asks: dict | list) -> float | None:
    items = sorted(asks.items()) if isinstance(asks, dict) else sorted(asks)
    v = vwap_for_size(Book(asks=tuple(Quote(p, s) for p, s in items)), SIZE)
    return None if v is None else round(v * 100.0, 6)


def _economics(stale_asks: dict) -> dict:
    stale, truth = _vwap_c(stale_asks), _vwap_c(TRUTH_ASKS)
    return {"contracts": SIZE, "stale_vwap_c": stale, "truth_vwap_c": truth,
            "truth_minus_stale_c": (None if stale is None or truth is None
                                    else round(truth - stale, 6)),
            "illustrative_only": True}


def r1_phantom_depth_survives_verification() -> dict:
    s, r = PolymarketStream(), _replica()
    s.register(A, r)
    s.handle(BOOK_DEEP, now=T)
    faults, due_hits = [], []
    for i in range(1, 61):
        # Agreeing traffic BELOW the touch: best bid stays 0.19, best ask stays 0.20.
        s.handle(change(0.18, 4 + (i % 3), "BUY", bb=0.19, ba=0.20), now=T + i)
        faults.append(r.check(T + i, max_age_s=5.0))
        due_hits.append(A in due(s.regs, T + i))
    return {
        "updates_sent": 60,
        "phantom_level_present": PHANTOM in r.asks,
        "phantom_size": r.asks.get(PHANTOM),
        "venue_truth_has_level": PHANTOM in dict(TRUTH_ASKS),
        "any_fault": any(f is not None for f in faults),
        "faults_seen": sorted({f.name for f in faults if f is not None}),
        "ever_due_for_rest": any(due_hits),
        "drift_counted": s.drift,
        "agreement_checks": s.checks,
        "verified_utc_advanced_to": r.verified_utc,
        "source": r.source,
        "economics": _economics(r.asks),
    }


def r2_touch_size_unchecked() -> dict:
    claim_bid, claim_ask = 0.19, 0.20
    stale, true = AssetBook(), AssetBook()
    stale.apply_book({"bids": [{"price": "0.19", "size": "10"}],
                      "asks": [{"price": "0.20", "size": "8"}]})
    true.apply_book({"bids": [{"price": "0.19", "size": "10"}],
                     "asks": [{"price": "0.20", "size": "1"}]})
    # Through the stream as well: the touch holds 8 locally while the venue holds 1.
    s, r = PolymarketStream(), _replica()
    s.register(A, r)
    s.handle({"event_type": "book", "asset_id": A,
              "bids": [{"price": "0.19", "size": "10"}],
              "asks": [{"price": "0.20", "size": "8"}]}, now=T)
    s.handle(change(0.18, 4, "BUY", bb=claim_bid, ba=claim_ask), now=T + 1)
    return {
        "touch_size_local": stale.asks[0.20], "touch_size_venue": true.asks[0.20],
        "stale_book_agrees": stale.agrees_with(claim_bid, claim_ask),
        "true_book_agrees": true.agrees_with(claim_bid, claim_ask),
        "stream_drift_counted": s.drift,
        "replica_touch_size_after": r.asks.get(0.20),
        "replica_fault": (lambda f: None if f is None else f.name)(r.check(T + 1, max_age_s=5.0)),
    }


def r3_rest_correction_overwritten() -> dict:
    s, r = PolymarketStream(), _replica()
    s.register(A, r)
    s.handle(BOOK_DEEP, now=T)
    for i in range(1, 21):
        s.handle("PONG", now=T + i)              # socket alive, no book traffic: a quiet market
    due_before = A in due(s.regs, T + 20)
    rc = Reconciler(s, lambda aid: (list(TRUTH_BIDS), list(TRUTH_ASKS)))
    reconciled = rc.once(now=T + 20, mono=5.0)
    after_reconcile = {
        "phantom_level_present": PHANTOM in r.asks,
        "asks_equal_truth": r.asks == dict(TRUTH_ASKS),
        "source": r.source,
        "rest_drift": rc.rest_drift,
        "last_fault": None if r.last_fault is None else r.last_fault.name,
        "stream_ladder_still_has_phantom": PHANTOM in s.books[A].asks,
    }
    # One ordinary agreeing update arrives.
    s.handle(change(0.18, 4, "BUY", bb=0.19, ba=0.20), now=T + 21)
    after_update = {
        "phantom_level_present": PHANTOM in r.asks,
        "asks_equal_truth": r.asks == dict(TRUTH_ASKS),
        "source": r.source,
        "fault": (lambda f: None if f is None else f.name)(r.check(T + 21, max_age_s=5.0)),
    }
    return {
        "due_before_reconcile": due_before,
        "reconciled_assets": reconciled,
        "after_reconcile": after_reconcile,
        "after_one_update": after_update,
        "correction_survived": after_update["asks_equal_truth"],
        "economics": _economics(r.asks),
    }


def c1_touch_level_is_caught() -> dict:
    """CONTROL. The same lost update, but AT the touch: the venue's best ask is now 0.21."""
    s, r = PolymarketStream(), _replica()
    s.register(A, r)
    s.handle(BOOK_DEEP, now=T)
    s.handle(change(0.18, 4, "BUY", bb=0.19, ba=0.21), now=T + 1)
    fault = r.check(T + 1, max_age_s=5.0)
    return {
        "drift_counted": s.drift,
        "replica_state": r.state.name,
        "last_fault": None if r.last_fault is None else r.last_fault.name,
        "check_fault": None if fault is None else fault.name,
        "resnapshot_requested": A in s.resnapshot,
        "caught": bool(s.drift == 1 and r.state is not ReplicaState.SYNCED
                       and r.last_fault is Fault.HASH_MISMATCH and fault is not None),
    }


def _kalshi_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def c2_kalshi_sequence_gap_is_caught() -> dict:
    """CONTROL. Shapes from nodes/stream_kalshi/tests/test_stream.py. Seq 2 is dropped."""
    s = KalshiStream(api_key="k", private_key=_kalshi_key())
    r = BookReplica("kalshi", "K1", verification="stream")
    s.register("K1", r, "yes")
    snap = {"type": "orderbook_snapshot", "seq": 1,
            "msg": {"market_ticker": "K1", "yes": [[0.40, 100]], "no": [[0.55, 200]]}}
    delta3 = {"type": "orderbook_delta", "seq": 3,
              "msg": {"market_ticker": "K1", "side": "yes", "price": 0.40, "delta": -30.0}}
    synced_after_snapshot = s.handle(snap, now=T) == "snapshot" and r.state is ReplicaState.SYNCED
    kind = s.handle(delta3, now=T + 1)
    fault = r.check(T + 1, max_age_s=5.0)
    return {
        "synced_after_snapshot": synced_after_snapshot,
        "handle_returned": kind,
        "replica_state": r.state.name,
        "last_fault": None if r.last_fault is None else r.last_fault.name,
        "gaps_counted": s.gaps,
        "caught": bool(synced_after_snapshot and kind == "gap"
                       and r.state is not ReplicaState.SYNCED and r.last_fault is Fault.SEQ_GAP
                       and fault is not None),
    }


def defective(r1: dict, r2: dict, r3: dict) -> dict[str, bool]:
    """Which reproductions exhibited the hypothesised defect, per spec.yaml."""
    return {
        "R1": bool(r1["phantom_level_present"] and not r1["venue_truth_has_level"]
                   and not r1["any_fault"] and not r1["ever_due_for_rest"]
                   and r1["drift_counted"] == 0),
        "R2": bool(r2["stale_book_agrees"] and r2["true_book_agrees"]
                   and r2["touch_size_local"] != r2["touch_size_venue"]
                   and r2["stream_drift_counted"] == 0 and r2["replica_touch_size_after"] == 8.0),
        "R3": bool(r3["due_before_reconcile"]
                   and r3["after_reconcile"]["asks_equal_truth"]
                   and r3["after_reconcile"]["source"] == "rest"
                   and r3["after_reconcile"]["rest_drift"] == 1
                   and r3["after_reconcile"]["stream_ladder_still_has_phantom"]
                   and r3["after_one_update"]["phantom_level_present"]
                   and r3["after_one_update"]["source"] == "ws"
                   and not r3["correction_survived"]),
    }


def verdict(r1, r2, r3, c1, c2) -> tuple[str, str]:
    """The registered outcome rule. Controls are evaluated first and override everything."""
    if not (c1["caught"] and c2["caught"]):
        return "HARNESS_INVALID", (f"control failed: C1 caught={c1['caught']}, "
                                   f"C2 caught={c2['caught']}; no conclusion about the defect")
    d = defective(r1, r2, r3)
    hit = [k for k, v in d.items() if v]
    if len(hit) == 3:
        return "DEFECT_REPRODUCED", "R1, R2 and R3 all exhibit the defect; both controls caught theirs"
    if not hit:
        return "DEFECT_REFUTED", "none of R1-R3 exhibits the defect; both controls caught theirs"
    return "PARTIAL", f"defect reproduced in {hit}, not in {[k for k, v in d.items() if not v]}"


def run() -> dict:
    r1 = r1_phantom_depth_survives_verification()
    r2 = r2_touch_size_unchecked()
    r3 = r3_rest_correction_overwritten()
    c1 = c1_touch_level_is_caught()
    c2 = c2_kalshi_sequence_gap_is_caught()
    v, reason = verdict(r1, r2, r3, c1, c2)
    return {"schema": SCHEMA, "R1": r1, "R2": r2, "R3": r3, "C1": c1, "C2": c2,
            "defective": defective(r1, r2, r3), "verdict": v, "verdict_reason": reason}


if __name__ == "__main__":
    json.dump(run(), sys.stdout, indent=1, sort_keys=True)
    print()

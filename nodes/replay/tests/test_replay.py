#!/usr/bin/env python3
"""The offline path is the live path minus the socket."""
from __future__ import annotations

import json
from pathlib import Path

from kernel.schema import OpportunityStatus as S
from nodes.capture.capture import Frame, merge
from nodes.replay.replay import Harness, compare, replay
from nodes.settle_wedge.fixtures import NO_WEDGE
from nodes.settle_wedge.policy import KALSHI_MLB_GAME_V1, POLYMARKET_MLB_GAME_V1
from nodes.store_tuples.store import TupleStore

T = 1_800_000_000.0
FEES = {"kalshi": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5},
        "polymarket": {"fee_rate": 0.05}}
SPEC = {"league": "mlb", "short_name": "AWY @ HOM", "state": "in", "start_utc": T,
        "outcomes": {"home": {"kalshi": "K_H", "polymarket": "P_H"},
                     "away": {"kalshi": "K_A", "polymarket": "P_A"}},
        "fee_params": FEES, "pm_slug": "s", "kalshi_event": "e", "pm_limits": {},
        "rules": {"kalshi": {"market": {"ticker": "K_H", "rules_primary": KALSHI_MLB_GAME_V1.sample_text.split("\n")[0],
                                        "rules_secondary": "\n".join(KALSHI_MLB_GAME_V1.sample_text.split("\n")[1:])},
                             "participants": list(KALSHI_MLB_GAME_V1.sample_participants)},
                  "polymarket": {"market": {"slug": "s", "description": POLYMARKET_MLB_GAME_V1.sample_text},
                                 "participants": list(POLYMARKET_MLB_GAME_V1.sample_participants)},
                  "retrieved_at": T}}


def k_snap(ticker, seq, yes, no):
    return json.dumps({"type": "orderbook_snapshot", "seq": seq,
                       "msg": {"market_ticker": ticker, "yes": [[yes, 5000]], "no": [[no, 5000]]}})


def k_delta(ticker, seq, side, price, d):
    return json.dumps({"type": "orderbook_delta", "seq": seq,
                       "msg": {"market_ticker": ticker, "side": side, "price": price, "delta": d}})


def p_book(asset, bid, ask):
    return json.dumps({"event_type": "book", "asset_id": asset, "tick_size": "0.01",
                       "bids": [{"price": str(bid), "size": "5000"}],
                       "asks": [{"price": str(ask), "size": "5000"}]})


def frames() -> list[Frame]:
    """Kalshi at 0.44/0.44 asks (via NO bids at 0.56), Polymarket at 0.99 asks: the cross-venue
    cover K_home + K_away... no -- each outcome's cheapest venue: kalshi for both is same-venue;
    make PM cheap on away instead so the cross-venue cover is 0.44 + 0.44 = 0.88 gross."""
    k = [Frame("kalshi", T + 0.0, 1.0, k_snap("K_H", 1, 0.40, 0.56)),      # YES ask 0.44
         Frame("kalshi", T + 0.1, 1.1, k_snap("K_A", 2, 0.01, 0.01)),      # YES ask 0.99
         Frame("kalshi", T + 0.5, 1.5, k_delta("K_H", 3, "no", 0.56, -100.0))]
    p = [Frame("polymarket", T + 0.2, 1.2, p_book("P_H", 0.01, 0.99)),
         Frame("polymarket", T + 0.3, 1.3, p_book("P_A", 0.40, 0.44))]
    return list(merge([k, p]))


def run(tmp_path: Path, name: str) -> tuple[TupleStore, dict]:
    store = TupleStore(tmp_path / f"{name}.sqlite", enforce_volume=False)
    h = Harness(store, quantities=(100.0,), rates=NO_WEDGE)
    assert h.spawn("espn:mlb:1", SPEC)
    st = replay(h, frames())
    return store, st


def test_captured_frames_replay_into_priced_rows(tmp_path: Path):
    store, st = run(tmp_path, "a")
    assert st["frames"] == {"kalshi": 3, "polymarket": 2} and st["parse_errors"] == 0
    rows = store.con.execute("SELECT status, cost, blocked_by FROM stream_evaluations ORDER BY seen_ts").fetchall()
    statuses = [r[0] for r in rows]
    # first event: the other three replicas have seen no frame yet -- blocked, with a name
    assert statuses[0] == S.BLOCKED_STALE.value and rows[0][2].startswith("polymarket:")
    assert S.PROFITABLE_UNEXECUTED.value in statuses, statuses                   # 0.88 gross clears 1%
    assert st["rows"] == len(rows) and st["evaluations"] >= len(rows)


def test_replay_is_deterministic_and_parity_with_itself_is_zero(tmp_path: Path):
    a, _ = run(tmp_path, "a")
    b, _ = run(tmp_path, "b")
    res = compare(a, b, start_utc=T - 1, end_utc=T + 10)
    assert res["mismatches"] == 0 and res["live_rows"] == res["replay_rows"] > 0, res


def test_parity_names_a_drift(tmp_path: Path):
    a, _ = run(tmp_path, "a")
    b, _ = run(tmp_path, "b")
    b.con.execute("UPDATE stream_evaluations SET status='NO_EDGE' WHERE rowid=(SELECT MAX(rowid) FROM stream_evaluations)")
    res = compare(a, b, start_utc=T - 1, end_utc=T + 10)
    assert res["mismatches"] == 2 and res["only_live"] and res["only_replay"]


def test_a_three_way_league_is_blocked_at_spawn_not_priced(tmp_path: Path):
    store = TupleStore(tmp_path / "c.sqlite", enforce_volume=False)
    h = Harness(store, rates=NO_WEDGE)
    assert not h.spawn("espn:epl:1", {**SPEC, "league": "epl"})
    assert h.blocked == {"espn:epl:1": "SPAWN:RULE_UNCITED"}
    assert h.ks.tickers == [] and h.ps.asset_ids == []


def test_a_non_json_kalshi_frame_is_counted_and_skipped(tmp_path: Path):
    store = TupleStore(tmp_path / "d.sqlite", enforce_volume=False)
    h = Harness(store, rates=NO_WEDGE)
    h.spawn("espn:mlb:1", SPEC)
    h.feed(Frame("kalshi", T, 1.0, "garbage{"))
    assert h.parse_errors == 1 and h.frames["kalshi"] == 1


def test_a_spec_without_rules_is_blocked_at_spawn_not_priced(tmp_path: Path):
    store = TupleStore(tmp_path / "e.sqlite", enforce_volume=False)
    h = Harness(store)
    spec = {k: v for k, v in SPEC.items() if k != "rules"}
    assert not h.spawn("espn:mlb:9", spec)
    assert h.blocked == {"espn:mlb:9": "SPAWN:SETTLEMENT_UNPROVEN"}

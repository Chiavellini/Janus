#!/usr/bin/env python3
"""The slate from a frozen Discovery: no network, every branch named."""
from __future__ import annotations

from pathlib import Path

from nodes.discovery.discovery import (Discovery, co_listed, load_specs, record_events, select_live)
from nodes.entities.resolve import Resolver
from nodes.schedule_espn.espn import ScheduledGame
from nodes.store_tuples.store import TupleStore

NOW = 1_800_000_000


def game(gid, start, state="in", league="mlb", home="10", away="12"):
    return ScheduledGame(f"espn:{league}:{gid}", league, start, home, away, "Home", "Away",
                         state, state == "post", False, False, "regular-season", "AWY @ HOM", "x")


def test_select_live_keeps_in_progress_and_near_pregame_only():
    sched = [game(1, NOW - 3600, "in"), game(2, NOW + 3600, "pre"), game(3, NOW + 8 * 3600, "pre"),
             game(4, NOW - 900, "pre"), game(5, NOW - 7200, "post")]
    live = select_live(sched, NOW, True, 6.0)
    assert [g.game_id for g in live] == ["espn:mlb:1", "espn:mlb:2", "espn:mlb:4"]
    assert [g.game_id for g in select_live(sched, NOW, False, 6.0)] == ["espn:mlb:1"]


def _discovery(*, pm_fee=True, k_fee=True, token_for_both=True) -> Discovery:
    r = Resolver.load()
    # Real entity ids from the seeded tables: the resolver must map PM's outcome labels back.
    nyy = r.resolve("mlb", text="New York Yankees").entity_id
    bos = r.resolve("mlb", text="Boston Red Sox").entity_id
    assert nyy and bos
    g = ScheduledGame("espn:mlb:7", "mlb", NOW, r.teams[nyy].espn_id, r.teams[bos].espn_id,
                      "Yankees", "Red Sox", "in", False, False, False, "regular-season",
                      "BOS @ NYY", "x")
    slug = "mlb-bos-nyy-2026-09-02"
    rows = [{"game_id": g.game_id, "entity_id": nyy, "market_type": "moneyline", "period": "game",
             "start_utc": NOW, "kalshi_event": "KXMLBGAME-26SEP02BOSNYY", "kalshi_outcome": "KXMLBGAME-26SEP02BOSNYY-NYY",
             "pm_event": slug, "pm_outcome": "New York Yankees", "kalshi_label": "Yankees", "pm_label": "New York Yankees"},
            {"game_id": g.game_id, "entity_id": bos, "market_type": "moneyline", "period": "game",
             "start_utc": NOW, "kalshi_event": "KXMLBGAME-26SEP02BOSNYY", "kalshi_outcome": "KXMLBGAME-26SEP02BOSNYY-BOS",
             "pm_event": slug, "pm_outcome": "Boston Red Sox", "kalshi_label": "Red Sox", "pm_label": "Boston Red Sox"}]
    names = {"New York Yankees": "tok-nyy"}
    if token_for_both:
        names["Boston Red Sox"] = "tok-bos"
    market = {"slug": slug, "orderMinSize": 5, "orderPriceMinTickSize": 0.01}
    return Discovery(NOW, [g], {}, {"mlb": (rows, {}, r)}, {slug: (names, {"markets": [market]})}, {},
                     fee_params={"kalshi": {"mlb": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5}} if k_fee else {},
                                 "polymarket": {slug: {"fee_rate": 0.03}} if pm_fee else {}})


def test_a_co_listed_game_carries_four_ids_and_both_fee_schedules():
    slate, blocked = co_listed(_discovery())
    assert blocked == {}
    spec = slate["espn:mlb:7"]
    assert {v["kalshi"] for v in spec["outcomes"].values()} == {"KXMLBGAME-26SEP02BOSNYY-NYY", "KXMLBGAME-26SEP02BOSNYY-BOS"}
    assert {v["polymarket"] for v in spec["outcomes"].values()} == {"tok-nyy", "tok-bos"}
    assert spec["fee_params"] == {"kalshi": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5},
                                  "polymarket": {"fee_rate": 0.03}}
    assert spec["pm_limits"] == {"min_order_contracts": 5.0, "tick": 0.01}
    assert spec["state"] == "in" and spec["league"] == "mlb"


def test_a_missing_fee_schedule_is_absent_from_the_spec_not_defaulted():
    slate, _ = co_listed(_discovery(pm_fee=False))
    assert "polymarket" not in slate["espn:mlb:7"]["fee_params"]
    slate, _ = co_listed(_discovery(k_fee=False))
    assert "kalshi" not in slate["espn:mlb:7"]["fee_params"]


def test_an_unresolved_pm_outcome_blocks_with_a_name():
    slate, blocked = co_listed(_discovery(token_for_both=False))
    assert slate == {} and blocked == {"espn:mlb:7": "PM_TOKEN_RESOLUTION"}


def test_events_table_is_change_gated(tmp_path: Path):
    d = _discovery()
    slate, blocked = co_listed(d)
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    assert record_events(store, d, slate, blocked, now=NOW) == 1
    assert record_events(store, d, slate, blocked, now=NOW + 60) == 0, "nothing changed"
    row = store.con.execute("SELECT phase, pm_slug, fee_params_json, first_seen_ts, last_seen_ts "
                            "FROM events WHERE event_id='espn:mlb:7'").fetchone()
    assert row[0] == "in:co_listed" and row[1] == "mlb-bos-nyy-2026-09-02"
    assert '"fee_multiplier": 0.5' in row[2]
    assert row[3] == NOW and row[4] == NOW + 60
    # the game drops off both venues: a transition, and the block reason is kept
    assert record_events(store, d, {}, {"espn:mlb:7": "PM_TOKEN_RESOLUTION"}, now=NOW + 120) == 1
    trans = store.con.execute("SELECT phase, block_reason FROM event_transitions ORDER BY id").fetchall()
    assert trans == [("in:co_listed", None), ("in", "PM_TOKEN_RESOLUTION")]
    store.close()


def test_the_spec_is_persisted_so_a_replay_can_rebuild_the_pollers(tmp_path: Path):
    d = _discovery()
    slate, blocked = co_listed(d)
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    record_events(store, d, slate, blocked, now=NOW)
    specs = load_specs(store)
    assert specs == slate
    assert load_specs(store, game_ids=["nope"]) == {}
    store.close()

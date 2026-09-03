#!/usr/bin/env python3
"""The slate from a frozen Discovery: no network, every branch named."""
from __future__ import annotations

from pathlib import Path

from nodes.discovery.discovery import (Discovery, co_listed, first_seen, load_specs, record_events,
                                       registry_health, select_live, tier_of, universe)
from nodes.entities.resolve import Resolver
from nodes.schedule_espn.espn import ScheduledGame
from nodes.settle_wedge.policy import KALSHI_MLB_GAME_V1, POLYMARKET_MLB_GAME_V1
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
    k_rules = {"ticker": "KXMLBGAME-26SEP02BOSNYY-NYY",
               "rules_primary": KALSHI_MLB_GAME_V1.sample_text.split("\n")[0].replace("St. Louis", "New York").replace("Los Angeles D", "Boston"),
               "rules_secondary": "\n".join(KALSHI_MLB_GAME_V1.sample_text.split("\n")[1:]).replace("St. Louis", "New York").replace("Los Angeles D", "Boston")}
    p_rules = {"slug": slug, "description": POLYMARKET_MLB_GAME_V1.sample_text.replace("St. Louis Cardinals", "New York Yankees").replace("Los Angeles Dodgers", "Boston Red Sox"),
               "resolutionSource": "https://www.mlb.com/"}
    rows = [{"game_id": g.game_id, "entity_id": nyy, "market_type": "moneyline", "period": "game",
             "start_utc": NOW, "kalshi_event": "KXMLBGAME-26SEP02BOSNYY", "kalshi_outcome": "KXMLBGAME-26SEP02BOSNYY-NYY",
             "pm_event": slug, "pm_outcome": "New York Yankees", "kalshi_label": "New York", "pm_label": "New York Yankees", "kalshi_rules": k_rules, "pm_rules": p_rules},
            {"game_id": g.game_id, "entity_id": bos, "market_type": "moneyline", "period": "game",
             "start_utc": NOW, "kalshi_event": "KXMLBGAME-26SEP02BOSNYY", "kalshi_outcome": "KXMLBGAME-26SEP02BOSNYY-BOS",
             "pm_event": slug, "pm_outcome": "Boston Red Sox", "kalshi_label": "Boston", "pm_label": "Boston Red Sox", "kalshi_rules": k_rules, "pm_rules": p_rules}]
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
    assert spec["settlement"]["result"] == "EQUIVALENT", spec["settlement"]
    assert spec["rules"]["kalshi"]["market"]["rules_secondary"].startswith("The following market")


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


def test_a_reworded_venue_template_blocks_the_game_and_is_recorded(tmp_path: Path):
    d = _discovery()
    rows = d.per_league["mlb"][0]
    for r in rows:
        r["pm_rules"] = {**r["pm_rules"], "description": r["pm_rules"]["description"].replace("50-50", "at the last price")}
    slate, blocked = co_listed(d)
    spec = slate["espn:mlb:7"]
    assert spec["settlement"]["result"] == "BLOCKED" and spec["settlement"]["code"] == "TEMPLATE_UNKNOWN"
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    record_events(store, d, slate, blocked, now=NOW)
    rows = store.con.execute("SELECT result, block_code FROM equivalence_records").fetchall()
    assert rows == [("BLOCKED", "TEMPLATE_UNKNOWN")]
    assert store.con.execute("SELECT COUNT(*) FROM settlement_records").fetchone()[0] == 2
    store.close()


def test_tiers_follow_the_specs_priority_order():
    live = game(1, NOW - 600, "in"); soon = game(2, NOW + 3600, "pre"); later = game(3, NOW + 30 * 3600, "pre")
    far = game(4, NOW + 80 * 3600, "pre")
    assert tier_of(live, NOW) == "live" and tier_of(soon, NOW) == "starting_soon"
    assert tier_of(later, NOW) == "closing_soon" and tier_of(far, NOW) == "long_term"
    assert tier_of(later, NOW, first_seen_ts=NOW - 3600) == "newborn"
    assert tier_of(later, NOW, first_seen_ts=NOW - 20 * 3600) == "recently_listed"
    assert tier_of(soon, NOW, first_seen_ts=NOW - 60) == "starting_soon", "start proximity outranks listing age"
    sched = [live, soon, later, far, game(5, NOW - 8000, "post")]
    assert [g.game_id for g in universe(sched, NOW)] == ["espn:mlb:1", "espn:mlb:2", "espn:mlb:3"]


def test_the_slate_carries_the_tier_and_the_registry_dates_newborns(tmp_path: Path):
    d = _discovery()
    slate, blocked = co_listed(d, now=NOW)
    assert slate["espn:mlb:7"]["tier"] == "live"
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    record_events(store, d, slate, blocked, now=NOW)
    assert first_seen(store) == {"espn:mlb:7": NOW}
    assert store.con.execute("SELECT tier FROM events").fetchone() == ("live",)
    assert registry_health(store, now=NOW + 60) == []
    assert registry_health(store, now=NOW + 2 * 86400)[0].startswith("registry: NO_CO_LISTED_GAMES")
    assert registry_health(store, now=NOW + 2 * 86400, in_season=False) == []
    store.close()


def test_a_fresh_registry_is_silent_and_a_day_of_uncolisted_writes_is_not(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    assert registry_health(store, now=NOW) == [], "first boot: nothing to judge yet"
    d = _discovery()
    record_events(store, d, {}, {"espn:mlb:7": "PM_TOKEN_RESOLUTION"}, now=NOW)   # discovered, never co-listed
    assert registry_health(store, now=NOW + 3600) == []
    assert registry_health(store, now=NOW + 2 * 86400)[0].startswith("registry: NO_CO_LISTED_GAMES")
    store.close()


def test_a_three_way_soccer_game_carries_six_ids_and_blocks_without_its_draw_token():
    """EPL: two teams and the draw on both venues; the slate spec has three outcomes, the draw keyed
    DRAW_ENTITY on both, and a missing draw token is an incomplete match, never a two-leg cover."""
    from nodes.match_sports.sports_match import DRAW_ENTITY
    from nodes.settle_wedge.policy import KALSHI_EPL_GAME_V1, POLYMARKET_SOCCER_GAME_V2
    r = Resolver.load()
    ars = r.resolve("epl", text="Arsenal").entity_id
    che = r.resolve("epl", text="Chelsea").entity_id
    assert ars and che
    g = ScheduledGame("espn:epl:9", "epl", NOW, r.teams[ars].espn_id, r.teams[che].espn_id, "Arsenal", "Chelsea",
                      "pre", False, False, False, "regular-season", "CHE @ ARS", "x")
    slug = "epl-che-ars-2026-09-14"
    k_rules = {"ticker": "KXEPLGAME-26SEP14CHEARS-ARS",
               "rules_primary": KALSHI_EPL_GAME_V1.sample_text.split("\n")[0].replace("Leeds United", "Arsenal").replace("Newcastle", "Chelsea"),
               "rules_secondary": KALSHI_EPL_GAME_V1.sample_text.split("\n", 1)[1].replace("Leeds United", "Arsenal").replace("Newcastle", "Chelsea")}
    p_rules = {"slug": slug + "-ars", "description": POLYMARKET_SOCCER_GAME_V2.sample_text.replace("Leeds United FC", "Arsenal FC").replace("Newcastle United FC", "Chelsea FC"),
               "resolutionSource": "https://www.premierleague.com/"}
    def row(ent, k_out, p_out, k_label, p_label):
        return {"game_id": g.game_id, "entity_id": ent, "market_type": "moneyline", "period": "game", "start_utc": NOW,
                "kalshi_event": "KXEPLGAME-26SEP14CHEARS", "kalshi_outcome": k_out, "pm_event": slug, "pm_outcome": p_out,
                "kalshi_label": k_label, "pm_label": p_label, "kalshi_rules": k_rules, "pm_rules": p_rules}
    rows = [row(DRAW_ENTITY, "KXEPLGAME-26SEP14CHEARS-TIE", slug + ":draw", "Tie", "Draw"),
            row(ars, "KXEPLGAME-26SEP14CHEARS-ARS", slug + ":ars", "Arsenal", "Arsenal FC"),
            row(che, "KXEPLGAME-26SEP14CHEARS-CHE", slug + ":che", "Chelsea", "Chelsea FC")]
    rows[0]["kalshi_rules"] = {**k_rules, "rules_primary": k_rules["rules_primary"].replace("Arsenal wins", "Tie is the result of")}
    names = {"Arsenal FC": "tok-ars", "Chelsea FC": "tok-che", "Draw": "tok-draw"}
    ev = {"slug": slug, "teams": [{"name": "Arsenal FC", "abbreviation": "ars"}, {"name": "Chelsea FC", "abbreviation": "che"}],
          "markets": [{"slug": slug + "-ars", "sportsMarketType": "moneyline", "orderMinSize": 5, "orderPriceMinTickSize": 0.01,
                       "feeSchedule": {"rate": 0.05}},
                      {"slug": slug + "-draw", "sportsMarketType": "moneyline"}, {"slug": slug + "-che", "sportsMarketType": "moneyline"}]}
    d = Discovery(NOW, [g], {}, {"epl": (rows, {}, r)}, {slug: (names, ev)}, {},
                  fee_params={"kalshi": {"epl": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}},
                              "polymarket": {slug: {"fee_rate": 0.05}}})
    slate, blocked = co_listed(d)
    assert blocked == {}, blocked
    spec = slate["espn:epl:9"]
    assert set(spec["outcomes"]) == {ars, che, DRAW_ENTITY}
    assert spec["outcomes"][DRAW_ENTITY] == {"kalshi": "KXEPLGAME-26SEP14CHEARS-TIE", "polymarket": "tok-draw"}
    assert spec["pm_limits"] == {"min_order_contracts": 5.0, "tick": 0.01}
    # the pair's settlement is reviewed and its rates registered (L33): EQUIVALENT, with the rates it used
    assert spec["settlement"]["result"] == "EQUIVALENT", spec["settlement"]
    assert set(spec["settlement"]["rates"]) == {"soccer.epl.postponed_gt48h_rate", "soccer.epl.cancelled_rate"}
    # without the draw token the game is not co-listed as a cover
    d2 = Discovery(NOW, [g], {}, {"epl": (rows, {}, r)}, {slug: ({k: v for k, v in names.items() if k != "Draw"}, ev)}, {})
    _, blocked2 = co_listed(d2)
    assert blocked2 == {"espn:epl:9": "PM_TOKEN_RESOLUTION"}
    d3 = Discovery(NOW, [g], {}, {"epl": (rows[1:], {}, r)}, {slug: (names, ev)}, {})
    _, blocked3 = co_listed(d3)
    assert blocked3 == {"espn:epl:9": "INCOMPLETE_EXACT_THREE_OUTCOME_MATCH"}

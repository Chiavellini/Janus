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
             "pm_event": slug, "pm_outcome": "New York Yankees", "kalshi_label": "New York", "pm_label": "New York Yankees", "pm_token_label": "New York Yankees", "kalshi_rules": k_rules, "pm_rules": p_rules},
            {"game_id": g.game_id, "entity_id": bos, "market_type": "moneyline", "period": "game",
             "start_utc": NOW, "kalshi_event": "KXMLBGAME-26SEP02BOSNYY", "kalshi_outcome": "KXMLBGAME-26SEP02BOSNYY-BOS",
             "pm_event": slug, "pm_outcome": "Boston Red Sox", "kalshi_label": "Boston", "pm_label": "Boston Red Sox", "pm_token_label": "Boston Red Sox", "kalshi_rules": k_rules, "pm_rules": p_rules}]
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
    assert spec["schedule_population"] == {"source": "espn", "game_id": "espn:mlb:7",
                                          "league": "mlb", "season_slug": "regular-season"}
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


def test_unknown_outcome_label_never_directly_owns_a_token():
    d = _discovery()
    slug = next(iter(d.tokens))
    row = d.per_league["mlb"][0][0]
    old_label = row["pm_token_label"]
    row["pm_label"] = "Schedule-qualified side (FL)"
    row["pm_token_label"] = ""
    names, event = d.tokens[slug]
    names[row["pm_label"]] = names.pop(old_label)
    assert not d.per_league["mlb"][2].resolve("mlb", text=row["pm_label"], venue="polymarket").ok

    slate, blocked = co_listed(d)
    assert slate == {}
    assert blocked == {"espn:mlb:7": "PM_TOKEN_RESOLUTION"}


def test_tennis_structured_full_name_keeps_exact_surname_token_fallback():
    from nodes.entities.resolve import Team, build_alias_index

    teams = {
        "wta:laura-siegemund": Team("wta:laura-siegemund", "wta", "p1", "LSI",
                                     "Laura", "Siegemund", "Laura Siegemund"),
        "wta:ludmila-samsonova": Team("wta:ludmila-samsonova", "wta", "p2", "LSA",
                                      "Ludmila", "Samsonova", "Ludmila Samsonova"),
    }
    aliases = build_alias_index([
        {"league": "wta", "alias": team.display_name, "entity_id": eid}
        for eid, team in teams.items()])
    resolver = Resolver(teams, aliases, {})
    game = ScheduledGame("pm:wta:one", "wta", NOW, "p1", "p2", "Laura Siegemund",
                         "Ludmila Samsonova", "in", False, True, False, "us-open",
                         "Siegemund v Samsonova", "x")
    slug = "wta-siegemu-samsono-2026-09-02"
    rows = []
    for entity, structured in (("wta:laura-siegemund", "Laura Siegemund"),
                               ("wta:ludmila-samsonova", "Ludmila Samsonova")):
        rows.append({"game_id": game.game_id, "entity_id": entity, "market_type": "moneyline",
                     "period": "game", "start_utc": NOW, "kalshi_event": "KXWTA",
                     "kalshi_outcome": "KXWTA-" + entity.rsplit("-", 1)[-1],
                     "pm_event": slug, "pm_outcome": slug + ":" + entity,
                     "kalshi_label": structured, "pm_label": structured,
                     "pm_token_label": "", "kalshi_rules": {}, "pm_rules": {}})
    tokens = {"Siegemund": "tok-siegemund", "Samsonova": "tok-samsonova"}
    d = Discovery(NOW, [game], {}, {"wta": (rows, {}, resolver)},
                  {slug: (tokens, {"markets": [{"slug": slug}]})}, {})
    slate, blocked = co_listed(d)
    assert blocked == {}
    assert {entity: outcome["polymarket"] for entity, outcome in
            slate[game.game_id]["outcomes"].items()} == {
                "wta:laura-siegemund": "tok-siegemund",
                "wta:ludmila-samsonova": "tok-samsonova"}


def test_token_binding_never_leaks_from_another_event_or_picks_a_conflict():
    d = _discovery(token_for_both=False)
    slug = next(iter(d.tokens))
    missing = d.per_league["mlb"][0][1]
    # An exact label on another event is not evidence for this event.
    d.tokens["mlb-other-game-2026-09-02"] = ({missing["pm_label"]: "wrong-game-token"}, {"markets": []})
    slate, blocked = co_listed(d)
    assert slate == {} and blocked == {"espn:mlb:7": "PM_TOKEN_RESOLUTION"}

    # Two different token ids for labels that normalise identically are ambiguous and fail closed.
    d = _discovery()
    slug = next(iter(d.tokens))
    names, _event = d.tokens[slug]
    names["New   York Yankees"] = "conflicting-token"
    slate, blocked = co_listed(d)
    assert slate == {} and blocked == {"espn:mlb:7": "PM_TOKEN_RESOLUTION"}


def test_duplicate_or_mixed_event_representations_fail_closed():
    d = _discovery()
    rows = d.per_league["mlb"][0]
    rows.append(dict(rows[0]))
    slate, blocked = co_listed(d)
    assert "espn:mlb:7" in slate and blocked == {}, "an identical repeated representation is harmless"

    d = _discovery()
    rows = d.per_league["mlb"][0]
    rows.append({**rows[0], "pm_event": "mlb-other-game-2026-09-02"})
    slate, blocked = co_listed(d)
    assert slate == {} and blocked == {"espn:mlb:7": "AMBIGUOUS_DUPLICATE_OUTCOME_MATCH"}

    d = _discovery()
    rows = d.per_league["mlb"][0]
    rows[1] = {**rows[1], "pm_event": "mlb-other-game-2026-09-02"}
    slate, blocked = co_listed(d)
    assert slate == {} and blocked == {"espn:mlb:7": "MIXED_EVENT_REPRESENTATION"}

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


def _three_way_fixture():
    """Arsenal v Chelsea on both venues with the draw: the shared three-way slate fixture."""
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
                "kalshi_label": k_label, "pm_label": p_label, "pm_token_label": p_label,
                "kalshi_rules": k_rules, "pm_rules": p_rules}
    rows = [row(DRAW_ENTITY, "KXEPLGAME-26SEP14CHEARS-TIE", slug + ":draw", "Tie", "Draw"),
            row(ars, "KXEPLGAME-26SEP14CHEARS-ARS", slug + ":ars", "Arsenal", "Arsenal FC"),
            row(che, "KXEPLGAME-26SEP14CHEARS-CHE", slug + ":che", "Chelsea", "Chelsea FC")]
    rows[0]["kalshi_rules"] = {**k_rules, "rules_primary": k_rules["rules_primary"].replace("Arsenal wins", "Tie is the result of")}
    names = {"Arsenal FC": "tok-ars", "Chelsea FC": "tok-che", "Draw": "tok-draw"}
    ev = {"slug": slug, "teams": [{"name": "Arsenal FC", "abbreviation": "ars"}, {"name": "Chelsea FC", "abbreviation": "che"}],
          "markets": [{"slug": slug + "-ars", "sportsMarketType": "moneyline", "orderMinSize": 5, "orderPriceMinTickSize": 0.01,
                       "feeSchedule": {"rate": 0.05}},
                      {"slug": slug + "-draw", "sportsMarketType": "moneyline"}, {"slug": slug + "-che", "sportsMarketType": "moneyline"}]}
    return g, r, rows, names, ev, ars, che, slug


def test_real_matcher_to_discovery_derives_three_way_team_tokens_without_array_order():
    """The real EPL shape has no market at the event slug: team YES tokens live at `slug-abbrev`.
    Reversing teams[] must not change which entity owns Arsenal/Chelsea's token."""
    import copy
    import json
    from collections import Counter
    from datetime import datetime, timezone
    from nodes.match_sports.sports_match import (VenueMarket, canonical_key, pair,
                                                  pm_markets)
    from nodes.venue_polymarket.books import pm_outcome_tokens

    g, r, legacy_rows, _names, ev, ars, che, slug = _three_way_fixture()
    ev = copy.deepcopy(ev)
    ev["teams"] = list(reversed(ev["teams"]))
    start = datetime.fromtimestamp(NOW, timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
    for market in ev["markets"]:
        suffix = market["slug"].rsplit("-", 1)[-1]
        market["gameStartTime"] = start
        market["clobTokenIds"] = json.dumps([f"tok-{suffix}", f"tok-{suffix}-no"])
    # The first team market supplies the settlement text for the event, exactly as production's
    # pm_primary_market fallback does for three-way soccer.
    ev["markets"][0].update(legacy_rows[1]["pm_rules"])

    stats = Counter(p_reason=Counter(), k_reason=Counter())
    by_pair = {(tuple(sorted(g.participants_espn))): [g]}
    pms = pm_markets("epl", r, by_pair, (NOW - 1, NOW + 1), stats, [], events=[ev])
    assert {market.entity_id: market.token_label for market in pms} == {
        ars: "Arsenal FC", che: "Chelsea FC", "draw": "Draw"}
    key = canonical_key(g, "epl")
    kms = [VenueMarket("kalshi", row["kalshi_event"], row["kalshi_outcome"], g.game_id,
                       row["entity_id"], "moneyline", "game", NOW, row["kalshi_label"],
                       rules=row["kalshi_rules"], key=key)
           for row in legacy_rows]
    matches = pair(kms, pms)
    names = pm_outcome_tokens(ev, slug)
    d = Discovery(NOW, [g], {}, {"epl": (matches, stats, r)}, {slug: (names, ev)}, {},
                  fee_params={"kalshi": {"epl": {"fee_type": "quadratic_with_maker_fees",
                                                   "fee_multiplier": 1.0}},
                              "polymarket": {slug: {"fee_rate": 0.05}}})
    slate, blocked = co_listed(d)
    assert blocked == {}
    assert {entity: outcome["polymarket"] for entity, outcome in
            slate[g.game_id]["outcomes"].items()} == {
                ars: "tok-ars", che: "tok-che", "draw": "tok-draw"}


def test_a_three_way_soccer_game_carries_six_ids_and_blocks_without_its_draw_token():
    """EPL: two teams and the draw on both venues; the slate spec has three outcomes, the draw keyed
    DRAW_ENTITY on both, and a missing draw token is an incomplete match, never a two-leg cover."""
    from nodes.match_sports.sports_match import DRAW_ENTITY
    from nodes.settle_wedge.policy import KALSHI_EPL_GAME_V1, POLYMARKET_SOCCER_GAME_V2
    g, r, rows, names, ev, ars, che, slug = _three_way_fixture()
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


def test_a_three_way_spec_carries_the_no_token_of_each_team_market():
    """2026-09-04: NO on a team market pays on the other two outcomes; the spec carries it as
    `polymarket_no`, taken from the team markets' second clobTokenId, never from the draw."""
    import json
    from nodes.discovery.discovery import Discovery, co_listed
    from nodes.match_sports.sports_match import DRAW_ENTITY
    g, r, rows, names, ev, ars, che, slug = _three_way_fixture()
    for m in ev["markets"]:
        suffix = m["slug"].rsplit("-", 1)[-1]
        m["clobTokenIds"] = json.dumps([f"tok-{suffix}", f"tok-{suffix}-no"])
    d = Discovery(NOW, [g], {}, {"epl": (rows, {}, r)}, {slug: (names, ev)}, {},
                  fee_params={"kalshi": {"epl": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}},
                              "polymarket": {slug: {"fee_rate": 0.05}}})
    slate, blocked = co_listed(d)
    assert blocked == {}, blocked
    spec = slate["espn:epl:9"]
    assert spec["outcomes"][ars] == {"kalshi": "KXEPLGAME-26SEP14CHEARS-ARS", "polymarket": "tok-ars", "polymarket_no": "tok-ars-no"}
    assert spec["outcomes"][che]["polymarket_no"] == "tok-che-no"
    assert "polymarket_no" not in spec["outcomes"][DRAW_ENTITY]
    assert spec["coverage_warnings"] == []


def test_missing_soccer_team_no_token_is_named_as_degraded_not_silently_lost():
    import json
    g, r, rows, names, ev, ars, che, slug = _three_way_fixture()
    for m in ev["markets"]:
        suffix = m["slug"].rsplit("-", 1)[-1]
        m["clobTokenIds"] = json.dumps([f"tok-{suffix}", f"tok-{suffix}-no"])
    # One team market loses its NO token. The three YES partition and the reverse Kalshi-NO /
    # PM-YES two-leg direction remain usable, but the missing direction is explicit in the spec.
    ev["markets"][-1]["clobTokenIds"] = json.dumps(["tok-che"])
    d = Discovery(NOW, [g], {}, {"epl": (rows, {}, r)}, {slug: (names, ev)}, {},
                  fee_params={"kalshi": {"epl": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}},
                              "polymarket": {slug: {"fee_rate": 0.05}}})
    slate, blocked = co_listed(d)
    assert blocked == {}
    assert slate[g.game_id]["coverage_warnings"] == [f"PM_NO_TOKEN_MISSING:{che}"]


def test_one_no_token_claimed_by_two_teams_binds_to_neither():
    """L94: the ambiguity guard refused ONE ENTITY holding TWO tokens and not the other direction.
    Two independent writers feed the NO candidates -- the entity resolver, and the exact
    token-label match -- so one token can end up claimed by two entities while each holds exactly
    one. That direction is worse: a leg bound to the wrong entity is a different INSTRUMENT, and
    Kalshi YES B + PM NO A pays $2 if B wins, $1 on the draw and $0 if A wins, which prices like a
    40-50 % edge. Neither team may keep it."""
    import json
    g, r, rows, names, ev, ars, che, slug = _three_way_fixture()
    for m in ev["markets"]:
        suffix = m["slug"].rsplit("-", 1)[-1]
        m["clobTokenIds"] = json.dumps([f"tok-{suffix}", f"tok-{suffix}-no"])
    # Both team markets hand back the SAME no token: one instrument, two claimants.
    for m in ev["markets"]:
        if m["slug"].rsplit("-", 1)[-1] in ("ars", "che"):
            m["clobTokenIds"] = json.dumps([f"tok-{m['slug'].rsplit('-', 1)[-1]}", "tok-shared-no"])
    d = Discovery(NOW, [g], {}, {"epl": (rows, {}, r)}, {slug: (names, ev)}, {},
                  fee_params={"kalshi": {"epl": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}},
                              "polymarket": {slug: {"fee_rate": 0.05}}})
    slate, blocked = co_listed(d)
    assert blocked == {}
    outs = slate[g.game_id]["outcomes"]
    assert "polymarket_no" not in outs[ars] and "polymarket_no" not in outs[che], "contested: neither"
    assert sorted(slate[g.game_id]["coverage_warnings"]) == [f"PM_NO_TOKEN_MISSING:{','.join(sorted([ars, che]))}"]


def test_soccer_no_token_binding_preserves_the_exact_matcher_label():
    import json
    g, r, rows, names, ev, ars, che, slug = _three_way_fixture()
    strange = "Schedule-qualified Club 1907"
    for row in rows:
        if row["entity_id"] == che:
            row["pm_label"] = strange
    assert not r.resolve("epl", text=strange, venue="polymarket").ok
    for m in ev["markets"]:
        suffix = m["slug"].rsplit("-", 1)[-1]
        m["clobTokenIds"] = json.dumps([f"tok-{suffix}", f"tok-{suffix}-no"])
    d = Discovery(NOW, [g], {}, {"epl": (rows, {}, r)}, {slug: (names, ev)}, {},
                  fee_params={"kalshi": {"epl": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}},
                              "polymarket": {slug: {"fee_rate": 0.05}}})
    slate, blocked = co_listed(d)
    assert blocked == {}
    assert slate[g.game_id]["outcomes"][che]["polymarket_no"] == "tok-che-no"
    assert slate[g.game_id]["coverage_warnings"] == []


def test_a_game_neither_venue_paired_is_named_unpaired_with_the_missing_side(tmp_path: Path):
    """Until 2026-09-07 an in-window game that did not pair left no trace: not on the slate, not in
    `blocked`, `events.block_reason` NULL. Now the reason says which venue side was missing."""
    d = _discovery()
    extra = game(8, NOW + 1800, "pre")                    # in the window, matched by nobody
    d.games.append(extra)
    d.per_league["mlb"][1]["kalshi_games"] = ["espn:mlb:8"]  # Kalshi found it, Polymarket did not
    slate, blocked = co_listed(d)
    assert "espn:mlb:7" in slate
    assert blocked == {"espn:mlb:8": "UNPAIRED:kalshi=found,polymarket=missing"}
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    record_events(store, d, slate, blocked, now=NOW)
    row = store.con.execute("SELECT phase, block_reason FROM events WHERE event_id='espn:mlb:8'").fetchone()
    assert row == ("pre", "UNPAIRED:kalshi=found,polymarket=missing")
    store.close()


def test_a_tier_change_is_a_transition_and_the_timeline_reads_back(tmp_path):
    from types import SimpleNamespace
    from nodes.discovery.discovery import load_tier_timeline, record_events
    from nodes.store_tuples.store import TupleStore
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    g = SimpleNamespace(game_id="g1", league="mlb", start_utc=5000, participants_espn=("A", "B"), short_name="A @ B", state="pre")
    d = SimpleNamespace(games=[g], made_utc=1000.0)
    spec = {"tier": "newborn", "kalshi_event": "K", "pm_slug": "s", "fee_params": {}, "league": "mlb", "outcomes": {}}
    assert record_events(st, d, {"g1": spec}, {}, now=1000.0) == 1
    assert record_events(st, d, {"g1": spec}, {}, now=1030.0) == 0, "nothing changed: no row"
    spec2 = {**spec, "tier": "starting_soon"}
    assert record_events(st, d, {"g1": spec2}, {}, now=1060.0) == 1, "the tier moved: a transition row"
    g.state = "in"
    spec3 = {**spec, "tier": "live"}
    assert record_events(st, d, {"g1": spec3}, {}, now=1090.0) == 1
    assert load_tier_timeline(st) == {"g1": [(1000.0, "newborn"), (1060.0, "starting_soon"), (1090.0, "live")]}
    assert load_tier_timeline(st, game_ids=["other"]) == {}

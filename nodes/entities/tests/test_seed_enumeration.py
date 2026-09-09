"""L59: entity reseeds consume complete venue enumeration before writing generated tables."""

import pytest

from nodes.entities.resolve import Resolver, Team, build_alias_index
from nodes.match_sports.stage1_checkpoint import VenuePullError


def test_venue_structured_reseed_preserves_and_reuses_existing_stable_players(monkeypatch):
    from nodes.entities import seed

    old = Team("atp:tai-sach", "atp", "3270406", "SACH", "Tai", "Sach", "Tai Sach")
    renamed = Team("atp:tai-leonard-sach", "atp", "3270406", "SACH", "Tai Leonard", "Sach",
                   "Tai Leonard Sach")
    fresh = Team("atp:fresh", "atp", "new-pm-id", "NEW", "New", "Player", "New Player")
    aliases = [{"league": "atp", "alias": "Tai Leonard Sach",
                "entity_id": renamed.entity_id, "source": "polymarket"}]
    monkeypatch.setattr(seed, "_seed_players", lambda *_a, **_k: ([renamed, fresh], aliases))

    teams, got_aliases = seed.seed_teams(["atp"], existing_teams={old.entity_id: old})

    assert {team.entity_id for team in teams} == {old.entity_id, fresh.entity_id}
    assert got_aliases[0]["entity_id"] == old.entity_id


def test_venue_structured_reseed_rejects_name_identity_reused_for_changed_stable_id(monkeypatch):
    from nodes.entities import seed

    old = Team("atp:same-name", "atp", "old-pm-id", "OLD", "Same", "Name", "Same Name")
    changed = Team("atp:same-name", "atp", "new-pm-id", "NEW", "Same", "Name", "Same Name")
    monkeypatch.setattr(seed, "_seed_players", lambda *_a, **_k: ([changed], []))

    with pytest.raises(ValueError, match="player identity changed"):
        seed.seed_teams(["atp"], existing_teams={old.entity_id: old})


def test_venue_structured_reseed_rejects_name_moved_onto_another_existing_stable_id(monkeypatch):
    from nodes.entities import seed

    alpha = Team("atp:alpha", "atp", "pm-alpha", "A", "", "Alpha", "Alpha")
    beta = Team("atp:beta", "atp", "pm-beta", "B", "", "Beta", "Beta")
    moved = Team("atp:alpha", "atp", "pm-beta", "A", "", "Alpha", "Alpha")
    monkeypatch.setattr(seed, "_seed_players", lambda *_a, **_k: ([moved], []))

    with pytest.raises(ValueError, match="player identity changed"):
        seed.seed_teams(["atp"], existing_teams={alpha.entity_id: alpha, beta.entity_id: beta})


def test_venue_structured_reseed_rejects_one_generated_name_for_two_existing_players(monkeypatch):
    from nodes.entities import seed

    alpha = Team("atp:alpha", "atp", "pm-alpha", "A", "", "Alpha", "Alpha")
    beta = Team("atp:beta", "atp", "pm-beta", "B", "", "Beta", "Beta")
    gamma_a = Team("atp:gamma", "atp", "pm-alpha", "G", "", "Gamma", "Gamma")
    gamma_b = Team("atp:gamma", "atp", "pm-beta", "G", "", "Gamma", "Gamma")
    aliases = [
        {"league": "atp", "alias": "Gamma", "entity_id": "atp:gamma", "source": "polymarket"},
    ]
    monkeypatch.setattr(seed, "_seed_players", lambda *_a, **_k: ([gamma_a, gamma_b], aliases))

    with pytest.raises(ValueError, match="generated player identity collision"):
        seed.seed_teams(["atp"], existing_teams={alpha.entity_id: alpha, beta.entity_id: beta})


def test_pm_xref_seed_uses_complete_fallback_and_exposes_primary_failure():
    from nodes.entities.seed import seed_pm_xrefs

    teams = {
        "ere:a": Team("ere:a", "ere", "1", "AAA", "Alpha", "A", "Alpha A"),
        "ere:b": Team("ere:b", "ere", "2", "BBB", "Beta", "B", "Beta B"),
    }
    aliases = build_alias_index([
        {"league": "ere", "alias": "Alpha A", "entity_id": "ere:a"},
        {"league": "ere", "alias": "AAA", "entity_id": "ere:a"},
        {"league": "ere", "alias": "Beta B", "entity_id": "ere:b"},
        {"league": "ere", "alias": "BBB", "entity_id": "ere:b"},
    ])

    class PrimaryFails:
        def get_json(self, _url, params=None, use_cache=False):
            if "tag_id" in params:
                raise OSError("numeric index unavailable")
            return [{"id": "event", "slug": "ere-aaa-bbb-2026-09-10", "teams": [
                {"id": "pm-a", "name": "Alpha A", "abbreviation": "AAA"},
                {"id": "pm-b", "name": "Beta B", "abbreviation": "BBB"}]}]

    diagnostics = {}
    rows, conflicts = seed_pm_xrefs(Resolver(teams, aliases, {}), leagues=["ere"],
                                    client=PrimaryFails(), diagnostics=diagnostics)
    assert conflicts == []
    assert {(row["venue_team_id"], row["entity_id"]) for row in rows} == {
        ("pm-a", "ere:a"), ("pm-b", "ere:b")}
    assert diagnostics["ere"]["degraded"] is True
    assert "tag_id:101735" in diagnostics["ere"]["errors"]


def test_reseed_gathers_all_remote_evidence_before_any_generated_write(monkeypatch):
    from nodes.entities import seed

    team = Team("nhl:a", "nhl", "1", "AAA", "Alpha", "A", "Alpha A")
    monkeypatch.setattr(seed, "seed_teams", lambda *a, **k: ([team], []))
    monkeypatch.setattr(seed, "seed_kalshi_xrefs", lambda *a, **k: ([], []))

    def incomplete(*_args, **_kwargs):
        raise VenuePullError("no complete PM selector", diagnostics={"errors": {"tag_slug:nhl": "broken"}})

    monkeypatch.setattr(seed, "seed_pm_xrefs", incomplete)
    monkeypatch.setattr(seed, "_write_teams", lambda *_a, **_k: pytest.fail("teams written before PM completed"))
    monkeypatch.setattr(seed, "_write", lambda *_a, **_k: pytest.fail("table written before PM completed"))
    with pytest.raises(VenuePullError, match="no complete PM selector"):
        seed.main(["nhl"])


def test_kalshi_xref_seed_uses_every_series_status_page_and_exposes_diagnostics():
    from nodes.entities.seed import seed_kalshi_xrefs

    uuid = "11111111-1111-1111-1111-111111111111"
    teams = {"atp:a": Team("atp:a", "atp", "1", "AAA", "Alpha", "A", "Alpha A")}
    aliases = build_alias_index([
        {"league": "atp", "alias": "AAA", "entity_id": "atp:a"},
        {"league": "atp", "alias": "Alpha", "entity_id": "atp:a"},
    ])

    class Complete:
        def __init__(self):
            self.calls = []

        def get_json(self, _url, params=None, use_cache=False):
            self.calls.append(dict(params))
            if params["series_ticker"] == "KXATPMATCH" and params["status"] == "open":
                if not params.get("cursor"):
                    return {"events": [{"event_ticker": "EV1", "markets": []}], "cursor": "two"}
                return {"events": [{"event_ticker": "EV2", "markets": [{
                    "ticker": "EV2-AAA", "yes_sub_title": "Alpha",
                    "custom_strike": {"tennis_player": uuid}}]}]}
            return {"events": []}

    client, diagnostics = Complete(), {}
    rows, conflicts = seed_kalshi_xrefs(Resolver(teams, aliases, {}), leagues=["atp"],
                                        client=client, diagnostics=diagnostics)
    assert conflicts == []
    assert [(row["venue_team_id"], row["entity_id"]) for row in rows] == [(uuid, "atp:a")]
    assert set(diagnostics["atp"]["selectors"]) == {
        "KXATPMATCH:open", "KXATPMATCH:unopened",
        "KXATPCHALLENGERMATCH:open", "KXATPCHALLENGERMATCH:unopened"}
    assert diagnostics["atp"]["complete"] is True
    assert any(call.get("cursor") == "two" for call in client.calls)


def test_kalshi_xref_seed_rejects_conflicting_duplicate_market_identity():
    from nodes.entities.seed import seed_kalshi_xrefs

    class ConflictingMarket:
        def get_json(self, _url, params=None, use_cache=False):
            if params["status"] == "unopened":
                return {"events": []}
            return {"events": [{"event_ticker": "EV", "markets": [
                {"ticker": "EV-A", "yes_sub_title": "Alpha"},
                {"ticker": "EV-A", "yes_sub_title": "Beta"}]}]}

    diagnostics = {}
    with pytest.raises(VenuePullError, match="conflicting Kalshi representations") as stopped:
        seed_kalshi_xrefs(Resolver({}, {}, {}), leagues=["atp"], client=ConflictingMarket(),
                          diagnostics=diagnostics)
    assert diagnostics["atp"] == stopped.value.diagnostics
    assert "market:EV-A" in diagnostics["atp"]["errors"]


def test_kalshi_reseed_failure_is_atomic_and_programmer_errors_propagate(monkeypatch):
    from nodes.entities import seed

    team = Team("nhl:a", "nhl", "1", "AAA", "Alpha", "A", "Alpha A")
    real_seed_kalshi_xrefs = seed.seed_kalshi_xrefs
    monkeypatch.setattr(seed, "seed_teams", lambda *a, **k: ([team], []))

    def incomplete(*_args, **_kwargs):
        raise VenuePullError("incomplete Kalshi pull", diagnostics={"errors": {"KXNHLGAME:open": "broken"}})

    monkeypatch.setattr(seed, "seed_kalshi_xrefs", incomplete)
    monkeypatch.setattr(seed, "seed_pm_xrefs", lambda *a, **k: pytest.fail("PM fetched after Kalshi failed"))
    monkeypatch.setattr(seed, "_write_teams", lambda *_a, **_k: pytest.fail("teams written before Kalshi completed"))
    monkeypatch.setattr(seed, "_write", lambda *_a, **_k: pytest.fail("table written before Kalshi completed"))
    with pytest.raises(VenuePullError, match="incomplete Kalshi pull"):
        seed.main(["nhl"])

    class ProgrammerBug:
        def get_json(self, _url, params=None, use_cache=False):
            raise AssertionError("seed implementation bug")

    with pytest.raises(AssertionError, match="seed implementation bug"):
        real_seed_kalshi_xrefs(Resolver({}, {}, {}), leagues=["nhl"], client=ProgrammerBug())

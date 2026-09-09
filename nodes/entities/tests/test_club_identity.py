"""Club identity is shared; competition aliases and game keys remain separate."""
import csv

import pytest

from nodes.entities.resolve import Resolver, Team, build_alias_index, load_teams, load_xrefs
from nodes.entities.seed import _write_teams, seed_teams


def club(eid="epl:eng.arsenal", league="epl", espn_id="359"):
    return Team(eid, league, espn_id, "ARS", "Arsenal", "Arsenal", "Arsenal")


def raw(espn_id="359", name="Arsenal", abbreviation="ARS"):
    return {"id": espn_id, "displayName": name, "name": name, "location": name,
            "abbreviation": abbreviation, "slug": name.lower().replace(" ", "-")}


def test_domestic_and_ucl_seed_reuse_one_existing_identity(monkeypatch):
    from nodes.entities import seed
    old = club()
    monkeypatch.setattr(seed.espn, "fetch_teams", lambda league, **kw: [raw()])
    teams, aliases = seed_teams(["ucl", "epl"], existing_teams={old.entity_id: old})
    assert teams == [old]
    r = Resolver({t.entity_id: t for t in teams}, build_alias_index(aliases), {})
    assert r.by_text("ucl", "Arsenal").entity_id == old.entity_id
    assert r.by_text("epl", "Arsenal").entity_id == old.entity_id
    assert not r.by_text("lal", "Arsenal").ok, "club identity does not globalize text aliases"


def test_new_club_identity_is_independent_of_competition_and_seed_order(monkeypatch):
    from nodes.entities import seed
    monkeypatch.setattr(seed.espn, "fetch_teams", lambda league, **kw: [raw()])
    first, a1 = seed_teams(["ucl", "epl"], existing_teams={})
    second, a2 = seed_teams(["epl", "ucl"], existing_teams={})
    assert first == second == [club("soccer:espn-359", "soccer")]
    assert build_alias_index(a1) == build_alias_index(a2)
    assert seed_teams(["epl"], existing_teams={first[0].entity_id: first[0]})[0] == first


def test_soccer_identity_never_collides_with_another_sports_espn_id(monkeypatch):
    from nodes.entities import seed
    baseball = club("mlb:other", "mlb")
    monkeypatch.setattr(seed.espn, "fetch_teams", lambda league, **kw: [raw()])
    teams, _ = seed_teams(["ucl"], existing_teams={baseball.entity_id: baseball})
    assert teams[0].entity_id == "soccer:espn-359"


def test_conflicting_existing_club_identities_fail_closed_before_fetch(monkeypatch):
    from nodes.entities import seed
    a, b = club(), club("ucl:arsenal", "ucl")
    def no_fetch(*args, **kwargs):
        pytest.fail("identity collision must stop before network")
    monkeypatch.setattr(seed.espn, "fetch_teams", no_fetch)
    with pytest.raises(ValueError, match="soccer ESPN id collision"):
        seed_teams(["ucl"], existing_teams={a.entity_id: a, b.entity_id: b})


def test_two_clubs_sharing_a_ucl_abbreviation_remain_ambiguous(monkeypatch):
    from nodes.entities import seed
    monkeypatch.setattr(seed.espn, "fetch_teams", lambda league, **kw: [
        raw("1", "Club One", "UNI"), raw("2", "Club Two", "UNI")])
    teams, aliases = seed_teams(["ucl"], existing_teams={})
    r = Resolver({t.entity_id: t for t in teams}, build_alias_index(aliases), {
        ("kalshi", "exact-id"): "soccer:espn-1"})
    assert r.by_text("ucl", "UNI").ambiguous_among == ("soccer:espn-1", "soccer:espn-2")
    assert r.resolve("ucl", text="UNI", venue="kalshi", venue_team_id="exact-id").entity_id == "soccer:espn-1"


def test_global_xrefs_allow_repeated_competition_rows_only_for_same_club(tmp_path):
    path = tmp_path / "xrefs.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows([
            ["venue", "league", "venue_team_id", "entity_id"],
            ["kalshi", "epl", "same-id", "epl:eng.arsenal"],
            ["kalshi", "ucl", "same-id", "epl:eng.arsenal"]])
    assert load_xrefs(path, manual=None) == {("kalshi", "same-id"): "epl:eng.arsenal"}
    with path.open("a", newline="") as stream:
        csv.writer(stream).writerow(["kalshi", "ucl", "same-id", "soccer:espn-999"])
    with pytest.raises(ValueError, match="xref collision"):
        load_xrefs(path, manual=None)


def test_partial_reseed_keeps_shared_club_directory_and_is_idempotent(tmp_path):
    path = tmp_path / "teams.csv"
    old = club()
    _write_teams([old], path)
    assert _write_teams([old, club("soccer:espn-2", "soccer", "2")], path) == 2
    before = path.read_bytes()
    _write_teams([], path)
    assert path.read_bytes() == before
    assert load_teams(path)[old.entity_id] == old
    with pytest.raises(ValueError, match="entity identity changed"):
        _write_teams([club(espn_id="other")], path)

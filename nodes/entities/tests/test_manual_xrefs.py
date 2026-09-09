"""Audited UUID exceptions are durable additions, never collision overrides."""
import csv

import pytest

from nodes.entities.resolve import Resolver, load_xrefs
from nodes.entities.seed import _write, seed_kalshi_xrefs


FIELDS = ["venue", "league", "venue_team_id", "entity_id", "source", "label"]


def row(entity="epl:eng.man_utd", league="ucl"):
    return {"venue": "kalshi", "league": league, "venue_team_id": "known-uuid",
            "entity_id": entity, "source": "fixture", "label": "Manchester United"}


def write_rows(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_manual_overlay_loads_when_generated_file_is_missing(tmp_path):
    manual = tmp_path / "manual.csv"
    write_rows(manual, [row()])
    assert load_xrefs(tmp_path / "absent.csv", manual) == {("kalshi", "known-uuid"): "epl:eng.man_utd"}


@pytest.mark.parametrize("where", ["generated", "manual", "between"])
def test_conflict_anywhere_in_global_xrefs_raises(tmp_path, where):
    generated, manual = tmp_path / "generated.csv", tmp_path / "manual.csv"
    correct, other = row(), row("bun:ger.bayern_munich", "bun")
    write_rows(generated, [correct, other] if where == "generated" else [correct])
    write_rows(manual, [correct, other] if where == "manual" else [other] if where == "between" else [])
    with pytest.raises(ValueError, match="xref collision"):
        load_xrefs(generated, manual)


def test_scoped_reseed_preserves_manual_file_and_identical_cross_competition_identity(tmp_path):
    generated, manual = tmp_path / "generated.csv", tmp_path / "manual.csv"
    write_rows(generated, [row(league="epl")])
    write_rows(manual, [row()])
    before = manual.read_bytes()
    _write(generated, FIELDS, [row()], leagues=["ucl"])
    assert manual.read_bytes() == before
    assert load_xrefs(generated, manual) == {("kalshi", "known-uuid"): "epl:eng.man_utd"}


def test_audited_ucl_uuid_does_not_relabel_mun_or_suppress_generated_disagreement():
    uuid = "7e273345-6669-4db7-8a38-7f3ccb608937"
    r = Resolver.load()
    assert r.resolve("ucl", venue="kalshi", venue_team_id=uuid).entity_id == "epl:eng.man_utd"
    assert r.by_text("ucl", "MUN").entity_id == "bun:ger.bayern_munich"
    class PublicFixture:
        def get_json(self, _url, params=None):
            if params["status"] == "unopened":
                return {"events": []}
            return {"events": [{"markets": [{"ticker": "KXUCLGAME-26SEP10-MUN",
                                              "yes_sub_title": "Manchester United",
                                              "custom_strike": {"soccer_team": uuid}}]}]}
    rows, conflicts = seed_kalshi_xrefs(r, leagues=["ucl"], client=PublicFixture())
    assert not rows
    assert [(c["uuid"], c["reason"]) for c in conflicts] == [(uuid, "disagree")]


def test_audited_ucl_name_variants_resolve_to_exact_soccer_clubs():
    r = Resolver.load()
    for name, espn_id in [("Sabah Masazir", "21922"), ("Bodoe/Glimt", "2980"),
                          ("FC Bayern München", "132"), ("FK Shakhtar Donetsk", "493"),
                          ("FK Bodø/Glimt", "2980"), ("Como 1907", "2572")]:
        resolved = r.by_text("ucl", name)
        assert resolved.ok, name
        assert r.teams[resolved.entity_id].espn_id == espn_id

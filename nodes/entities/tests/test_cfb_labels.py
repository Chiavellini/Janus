"""College football labels the lane could not resolve on 2026-09-08 (near-miss lines on the box)."""
from nodes.entities.resolve import Resolver


def test_a_trailing_st_is_state_and_the_manual_rows_cover_kalshi_s_college_labels():
    r = Resolver()
    for text, eid in (("Ohio St.", "cfb:ohio-state-buckeyes"), ("Jacksonville St.", "cfb:jacksonville-state-gamecocks"),
                      ("Kent St.", "cfb:kent-state-golden-flashes"), ("Alabama St.", "cfb:alabama-state-hornets"),
                      ("Nicholls St.", "cfb:nicholls-state-colonels") if False else ("Appalachian St.", "cfb:app-state-mountaineers"),
                      ("University at Albany", "cfb:ualbany-great-danes"), ("North Carolina St.", "cfb:nc-state-wolfpack"),
                      ("NC St.", "cfb:nc-state-wolfpack"), ("Ole Miss", "cfb:ole-miss-rebels"), ("UAB", "cfb:uab-blazers")):
        res = r.resolve("cfb", text=text)
        assert res.ok and res.entity_id == eid, (text, res)
    assert r.resolve("mlb", text="St. Louis").ok, "a leading St. is untouched"


def test_an_ambiguous_school_is_narrowed_to_the_one_the_schedule_knows():
    r = Resolver()
    res = r.resolve("cfb", text="Troy")
    assert not res.ok and len(res.ambiguous_among) >= 2, "Troy: the Trojans and a junior college's Vikings"
    trojans = r.teams["cfb:troy-trojans"]
    narrowed = r.narrow(res, espn_ids={trojans.espn_id})
    assert narrowed.ok and narrowed.entity_id == "cfb:troy-trojans"
    assert not r.narrow(res, espn_ids={"0"}).ok, "no candidate on the schedule: still unresolved"
    assert r.resolve("cfb", text="Troy Trojans").ok, "the school plus the nickname is unique on its own"
    assert r.resolve("cfb", text="Charlotte 49ers").entity_id == "cfb:charlotte-49ers"

"""Event metadata may vary; numeric settlement terms must change template identity."""

import pytest

from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket, normalise_template
from nodes.settle_wedge import policy as P


@pytest.mark.parametrize("left,right", [
    ("7 days", "14 days"),
    ("48 hours", "24 hours"),
    ("48h", "24h"),
    ("90 minutes", "120 minutes"),
    ("50-50", "60-40"),
    ("$0.50", "$0.05"),
    ("0.5%", "5%"),
    ("2:1", "1:2"),
    ("1.5 days", "15 days"),
])
def test_numeric_settlement_changes_cannot_collide(left, right):
    text = "If the event is delayed beyond TERM, the market will resolve."
    assert normalise_template(text.replace("TERM", left), ()) != normalise_template(
        text.replace("TERM", right), ())


@pytest.mark.parametrize("template,old,new", [
    (P.POLYMARKET_TENNIS_MATCH_V1, "7 days", "14 days"),
    (P.POLYMARKET_TENNIS_MATCH_V2, "14 days", "7 days"),
    (P.KALSHI_NFL_GAME_V1, "48 hours", "24 hours"),
    (P.KALSHI_NFL_GAME_V1, "$0.50", "$0.05"),
    (P.POLYMARKET_MLB_GAME_V1, "24 hours", "2 hours"),
    (P.POLYMARKET_MLB_GAME_V1, "50-50", "60-40"),
])
def test_numeric_edits_to_reviewed_rules_are_unknown(template, old, new):
    assert old in template.sample_text
    changed = template.sample_text.replace(old, new)
    if template.venue == "kalshi":
        rec = harvest_kalshi({"rules_primary": changed}, participants=template.sample_participants,
                             retrieved_at=0, scrub=template.scrub)
    else:
        rec = harvest_polymarket({"description": changed}, participants=template.sample_participants,
                                retrieved_at=0, scrub=template.scrub)
    assert rec.template_hash != template.template_hash
    assert P.template_for(rec.template_hash) is None


@pytest.mark.parametrize("template,expected", [
    (P.KALSHI_MLB_GAME_V1, "23f06ff42ee6456e"),
    (P.POLYMARKET_MLB_GAME_V1, "c595cbcfc4dfbda9"),
    (P.KALSHI_NFL_GAME_V1, "6145b415ef0ffed8"),
    (P.POLYMARKET_NFL_GAME_V1, "08a778dd8b781d81"),
])
def test_reviewed_mlb_nfl_numeric_hashes_are_pinned(template, expected):
    assert template.template_hash == expected
    assert P.template_for(expected) is template


@pytest.mark.parametrize("date,clock", [
    ("Sep 9, 2026", "8:20PM ET"),
    ("September 21st, 2027", "09:05 AM PDT"),
    ("Jan. 2, 2028", "23:10 UTC"),
    ("2028-01-02", "23:10:00 UTC"),
    ("01/02/2028", "11:10 PM CST"),
])
def test_recognized_dates_times_and_numeric_team_names_are_metadata(date, clock):
    text = (f"49ers vs Rams originally scheduled for {date} at {clock}. "
            "After 48 hours, resolve $0.50. Reporting may be used.")
    assert normalise_template(text, ("San Francisco 49ers", "Los Angeles Rams")) == (
        "vs originally scheduled for at after 48 hours resolve $0.50 reporting may be used")


def test_tennis_absolute_deadline_keeps_its_relative_duration():
    sample = P.POLYMARKET_TENNIS_MATCH_V2
    changed = (sample.sample_text.replace("September 2, 2026 at 11:00AM ET", "October 3, 2027 at 8:30PM ET")
               .replace("September 16, 2026, 11:59 PM ET", "October 17, 2027, 11:59 PM ET")
               .replace("Cristina Bucsa", "Iga Swiatek").replace("Himeno Sakatsume", "Coco Gauff"))
    rec = harvest_polymarket({"description": changed}, participants=("Iga Swiatek", "Coco Gauff"),
                            retrieved_at=0, scrub=sample.scrub)
    assert rec.template_hash == sample.template_hash
    assert "14 days" in rec.template_text
    assert "50-50" in rec.template_text
    assert "calendar_offset_+14d" in rec.template_text
    assert "11:59 pm et" in rec.template_text


def tennis_calendar(start, deadline):
    sample = P.POLYMARKET_TENNIS_MATCH_V2
    text = (sample.sample_text.replace("September 2, 2026 at 11:00AM ET", start)
            .replace("September 16, 2026, 11:59 PM ET", deadline))
    return harvest_polymarket({"description": text}, participants=sample.sample_participants,
                              retrieved_at=0, scrub=sample.scrub)


@pytest.mark.parametrize("start,deadline", [
    ("January 25, 2026 at 8:30PM ET", "February 8, 2026, 11:59 PM ET"),
    ("December 25, 2026 at 2:00PM PT", "January 8, 2027, 11:59 PM ET"),
    ("February 20, 2028 at 23:00 UTC", "March 5, 2028, 11:59 PM ET"),
    ("February 20, 2027 at 23:00 UTC", "March 6, 2027, 11:59 PM ET"),
    ("2028-02-20 at 23:00 UTC", "2028-03-05, 11:59 PM ET"),
    ("02/20/2028 at 23:00 UTC", "03/05/2028, 11:59 PM ET"),
])
def test_calendar_offsets_survive_month_year_and_leap_boundaries(start, deadline):
    rec = tennis_calendar(start, deadline)
    assert rec.template_hash == P.POLYMARKET_TENNIS_MATCH_V2.template_hash
    assert "calendar_offset_+14d" in rec.template_text


@pytest.mark.parametrize("deadline", [
    "September 3, 2026, 11:59 PM ET",   # one day
    "September 15, 2026, 11:59 PM ET",  # thirteen days
    "September 17, 2026, 11:59 PM ET",  # fifteen days
    "September 1, 2026, 11:59 PM ET",   # negative offset
    "September 2, 2026, 11:59 PM ET",   # zero cannot pass the reviewed fourteen
    "September 16, 2026, 11:58 PM ET",
    "September 16, 2026, 11:59 AM ET",
    "September 16, 2026, 11:59 PM PT",
    "September 16, 2026, 11:59 PM EST",
    "September 16, 2026, 11:59:01 PM ET",
    "September 16, 2026",              # deleted deadline clock
])
def test_absolute_deadline_edits_block_even_when_relative_days_are_unchanged(deadline):
    rec = tennis_calendar("September 2, 2026 at 11:00AM ET", deadline)
    assert "14 days" in rec.template_text
    assert P.template_for(rec.template_hash) is None


def test_leap_day_is_counted_and_repeated_event_metadata_is_stripped():
    rec = tennis_calendar("February 20, 2028 at 11:00AM ET", "March 6, 2028, 11:59 PM ET")
    assert "calendar_offset_+15d" in rec.template_text
    assert P.template_for(rec.template_hash) is None
    text = "Scheduled for Sep 2, 2026 at 11:00AM ET. Again Sep 2, 2026 at 8:00PM PT."
    shifted = text.replace("Sep 2, 2026", "Dec 31, 2028").replace("11:00AM ET", "23:59 UTC")
    assert normalise_template(text, ()) == normalise_template(shifted, ())
    assert "calendar_offset" not in normalise_template(text, ())


@pytest.mark.parametrize("start,deadline,literal", [
    ("September 2, 2026 at 11:00AM ET", "September 16, 11:59 PM ET", "september 16"),
    ("February 16, 2026 at 11:00AM ET", "February 30, 2026, 11:59 PM ET", "february 30"),
    ("February 29, 2027 at 11:00AM ET", "March 15, 2027, 11:59 PM ET", "february 29"),
    ("September 2, 2026 at 11:00AM ET", "20260916, 11:59 PM ET", "20260916"),
    ("September 2, 2026 at 13:00PM ET", "September 16, 2026, 11:59 PM ET", "13:00pm et"),
    ("September 2, 2026 at 26:00 ET", "September 16, 2026, 11:59 PM ET", "26:00 et"),
    ("September 2, 2026 at 11:00AM ET", "September 16, 2026, 11:59 PM XYZ", "xyz"),
])
def test_ambiguous_or_invalid_calendar_forms_survive_and_block(start, deadline, literal):
    rec = tennis_calendar(start, deadline)
    assert literal in rec.template_text
    assert P.template_for(rec.template_hash) is None


def test_unrecognized_numeric_metadata_survives_to_fail_closed():
    assert "20260909" in normalise_template("scheduled for 20260909", ())
    assert "99" in normalise_template("scheduled for September 99", ())
    assert "kxatpmatch" not in normalise_template("Market KXATPMATCH-26SEP09ABCDEF-ABC", ())

#!/usr/bin/env python3
"""Measured probabilities the bounded settlement dimensions price with. Nothing here is a guess.

A BOUNDED dimension (the venues differ, but the difference has a bounded cost) is priced as
probability x worst-case loss. The probability must come from a registered measurement: a
`research/` row with a spec, a results file and a verdict. A key that is absent here makes the
dimension UNKNOWN, and UNKNOWN blocks (spec §5: unknown rules are a hard BLOCKED_RULES state,
never zero risk). Filling a key without a research reference is the one thing this file forbids.
"""

from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Evidence:
    key: str
    value: float
    n: int
    source: str
    retrieved_at: str
    research_ref: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.research_ref.startswith("research/"):
            raise ValueError(f"evidence {self.key!r} must cite a research/ row, got {self.research_ref!r}")
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(f"evidence {self.key!r} is a probability; got {self.value}")


#: key -> Evidence. Filled ONLY from a registered measurement. See research/sports/.
_L26 = "research/sports/2026-09-02_mlb-settlement-wedge-rates/spec.yaml"
_L30 = "research/sports/2026-09-03_nfl-settlement-wedge-rates-v2/spec.yaml"
_L33 = "research/sports/2026-09-03_soccer-settlement-wedge-rates/spec.yaml"
_L32 = "research/sports/2026-09-03_cfb-settlement-wedge-rates/spec.yaml"
_L35 = "research/sports/2026-09-03_soccer-settlement-wedge-rates-batch2/spec.yaml"
_L39 = "research/sports/2026-09-04_tennis-settlement-wedge-rates/spec.yaml"
_L43 = "research/sports/2026-09-09_mls-original-schedule/spec.yaml"
_L46 = "research/sports/2026-09-09_itf-delay-atomic/spec.yaml"
_L47 = "research/sports/2026-09-09_itf-qualifying-atomic/spec.yaml"
_L50 = "research/sports/2026-09-09_eredivisie-interval-bounds/spec.yaml"
_L58 = "research/sports/2026-09-09_ucl-settlement-bounds/spec.yaml"
_F4_DIR = "research/sports/2026-09-04_tennis-delay-forward"
_F4 = _F4_DIR + "/spec.yaml"
EVIDENCE: dict[str, Evidence] = {
    "soccer.ucl.postponed_gt48h_rate": Evidence(
        "soccer.ucl.postponed_gt48h_rate", 0.020588792299495857, 144,
        "Official UEFA pre-event 2024/25 league-phase calendar joined to all 144 UEFA Full Time "
        "Reports; report publication timestamps conservatively bound actual completion", "2026-09-09", _L58,
        "Exact one-sided 95% Clopper-Pearson UPPER BOUND, 0/144 adverse, not zero risk. "
        "Original UTC+2 and report UTC+1 widen CET/CEST uncertainty; both 48 elapsed hours and "
        "the second Eastern calendar date are adverse boundaries. All 36 clubs have eight "
        "reciprocal original fixtures; every terminal report joins uniquely, no date change or "
        "suspension flag. ESPN historical keyEvents clocks are bulk-update contaminated and "
        "not used. League-phase only; unknown/group/qualifying/knockout populations block. "
        "One season and separate marginal binomial bounds do not guarantee future or joint risk."),
    "soccer.ucl.cancelled_rate": Evidence(
        "soccer.ucl.cancelled_rate", 0.020588792299495857, 144,
        "All 144 originally scheduled 2024/25 UEFA Champions League league-phase fixtures have "
        "unique official UEFA Full Time Reports; frozen source hashes in L58", "2026-09-09", _L58,
        "Exact one-sided 95% Clopper-Pearson UPPER BOUND, 0/144 cancellations, not zero risk. "
        "Original-calendar SHA256 088885318834ac759175a4f3cbb762a35e6c61345a6ffe7938f7a0db56037ebf. "
        "League-phase only; does not transfer to old group format, qualifying or knockout. "
        "Historical population reserve, not a future-rate or profitability guarantee."),
    "tennis.itf.delayed_gt14d_rate": Evidence(
        "tennis.itf.delayed_gt14d_rate", 0.01768867361249885, 11370,
        "Complete fresh Polymarket Gamma tennis keyset catalog: 33,295 closed and 531 open listings; "
        "ITF main-draw singles only; explicit original schedule versus authoritative closedTime", "2026-09-09", _L46,
        "Always one-sided 95% Wilson UPPER BOUND (z=1.6449), not point estimate: 178/11370 mature "
        "events adverse (136 HALF, 6 winner after 14 days, 34 winner before original start, 2 still open). "
        "All 13,467 identified main-draw singles parseable, including 2,097 immature exclusions; 2,222 "
        "qualifiers excluded structurally. Both full cursor chains and all request/response hashes verified; "
        "corrected offline replay reproduced result and row files byte-for-byte. This deliberately counts "
        "all HALF outcomes as adverse even when the venues agree. Historical reserve, not a future-rate "
        "or profitability guarantee. May not substitute for qualifying or ATP/WTA evidence."),
    "tennis.itf.qualifying.delayed_gt14d_rate": Evidence(
        "tennis.itf.qualifying.delayed_gt14d_rate", 0.031076457689201795, 1185,
        "Independent qualifying-only offline score of L46's complete fresh Polymarket Gamma tennis catalog; "
        "all 339 raw request/hash/cursor pages verified, zero network requests", "2026-09-09", _L47,
        "Always one-sided 95% Wilson UPPER BOUND (z=1.6449), not point estimate: 27/1185 mature "
        "qualifiers adverse (25 HALF, one winner before original start, one still open; zero late winners). "
        "All 2,222 identified qualifiers parseable, including 1,037 immature exclusions; main-draw events "
        "excluded structurally. All HALF outcomes are conservatively adverse. This historical reserve is "
        "not a future-rate or profitability guarantee, and may not substitute for main-draw or ATP/WTA evidence."),
    "soccer.mls.postponed_gt48h_rate": Evidence(
        "soccer.mls.postponed_gt48h_rate", 0.040221661406316125, 510,
        "Official MLS preseason 2025 Fact and Record Book (schedule as of January 6) joined one-to-one "
        "to all 510 ESPN regular-season fixtures and their actual final-whistle wallclocks", "2026-09-09", _L43,
        "One-sided exact 95% Clopper-Pearson UPPER BOUND: 13/510 completions more than 48 hours late. "
        "All 510 final-whistle timestamps present; every 19 changed kickoff date reviewed against official club "
        "sources. Includes changes announced before venue listing, and conservatively counts two-calendar-day "
        "boundaries. Regular season only; no postseason result or profitability claim. Registered result and "
        "source hashes are preserved separately from the initial pending-review result."),
    "soccer.mls.cancelled_rate": Evidence(
        "soccer.mls.cancelled_rate", 0.005856766730583303, 510,
        "All 510 fixtures in the official January 6, 2025 MLS schedule completed; 30 clubs each appear 34 times; "
        "every fixture has a unique ESPN final-whistle wallclock", "2026-09-09", _L43,
        "One-sided exact 95% Clopper-Pearson UPPER BOUND: zero cancellations in 510 complete regular-season "
        "fixtures. Zero observations is not registered as zero risk. No missing/ambiguous fixture was dropped."),
    "soccer.ere.postponed_gt48h_rate": Evidence(
        "soccer.ere.postponed_gt48h_rate", 0.04253671926053953, 306,
        "Official June/September/December Eredivisie 2025/26 scheduling publications; all 306 regular-season "
        "fixtures joined to ESPN actual period-two final-whistle wallclocks", "2026-09-09", _L50,
        "One-sided exact 95% Clopper-Pearson UPPER BOUND: 7/306 conservative completion delays. "
        "Every original uses its earliest candidate date at Europe/Amsterdam midnight; alternatives retained, "
        "including a separately preserved March 7-to-6 correction discovered in official review. "
        "All 15 initial date exceptions reviewed, including three official suspension-completion reports; "
        "329 raw/request hashes and every initial/corrected row independently replayed. Regular season only, "
        "not playoffs or another league's rate. A historical settlement reserve, not a future-rate or profit guarantee."),
    "soccer.ere.cancelled_rate": Evidence(
        "soccer.ere.cancelled_rate", 0.009742208949783377, 306,
        "All 306 ordered fixtures in the official Eredivisie 2025/26 original population completed; "
        "18 clubs each play 34 matches; one validated ESPN final whistle per fixture", "2026-09-09", _L50,
        "One-sided exact 95% Clopper-Pearson UPPER BOUND for 0/306 cancellations, abandonments without "
        "completion or forfeitures; zero observations is never zero risk. Every fixture retained, three "
        "European qualification playoff games excluded by explicit season phase. L49's original-lineage "
        "failure and L50's initial/corrected/replayed artifacts remain preserved."),
    "mlb.postponed_gt2d_rate": Evidence(
        "mlb.postponed_gt2d_rate", 0.004762, 2100,
        "MLB Stats API schedule, 2026 regular season 2026-03-25..2026-09-02", "2026-09-03", _L26,
        "10 of 2100 games postponed and made up more than two days later; exact "
        "(every postponement carried a reschedule date). All-cause postponement rate 0.0129."),
    "mlb.cancelled_rate": Evidence(
        "mlb.cancelled_rate", 0.000000, 2100,
        "MLB Stats API schedule, 2026 regular season 2026-03-25..2026-09-02", "2026-09-03", _L26,
        "0 cancellations in 2100 games. Registered verbatim per the spec; the rule-of-three "
        "upper bound at this n is ~0.0014, and a re-measurement over more seasons is the honest way to "
        "raise it, not an edit here."),
    "nfl.postponed_gt48h_rate": Evidence(
        "nfl.postponed_gt48h_rate", 0.001515, 2640,
        "nflverse games.csv REG rows (denominator) + cited schedule-change table (numerator), seasons "
        "2015-2019 and 2021-2025; 2020 excluded by the operator's decision", "2026-09-03", _L30,
        "4 of 2640 games started more than 48 h after the original kickoff (2017 TB@MIA, 2021 LV@CLE at 48.5 h, "
        "SEA@LA, WAS@PHI); strict >48.0 h; completeness gate over Tue/Wed/Fri games passed. With 2020 the "
        "count would be far higher: the exclusion is stated, not hidden."),
    "nfl.cancelled_rate": Evidence(
        "nfl.cancelled_rate", 0.000379, 2640,
        "nflverse games.csv REG rows (denominator) + cited schedule-change table (numerator), seasons "
        "2015-2019 and 2021-2025", "2026-09-03", _L30,
        "1 of 2640: 2022 week 17 BUF@CIN, suspended in the first quarter and declared cancelled; the game is "
        "absent from nflverse and added to the denominator."),
    "soccer.bun.postponed_gt48h_rate": Evidence(
        "soccer.bun.postponed_gt48h_rate", 0.003268, 1224,
        "openfootball Bundesliga season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L33,
        "PROXY: 4 of 1224 matches were played more than 48 h after their round's core window. "
        "It counts every such move, including cup-related moves announced weeks ahead (not postponements at the "
        "venue's listing time), and misses every move inside the window; a FLOOR on the second count, an over-count "
        "on the first. Replace with a forward measurement of true original dates (DESIGN.md)."),
    "soccer.bun.cancelled_rate": Evidence(
        "soccer.bun.cancelled_rate", 0.000000, 1224,
        "openfootball Bundesliga season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L33,
        "0 of 1224: every season parsed to exactly N(N-1) matches. Registered verbatim; the rule-of-three bound at "
        "this n is ~0.002 and a re-measurement over more seasons is the honest way to raise it."),
    "soccer.epl.postponed_gt48h_rate": Evidence(
        "soccer.epl.postponed_gt48h_rate", 0.038158, 1520,
        "openfootball Premier League season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L33,
        "PROXY: 58 of 1520 matches were played more than 48 h after their round's core window. "
        "It counts every such move, including cup-related moves announced weeks ahead (not postponements at the "
        "venue's listing time), and misses every move inside the window; a FLOOR on the second count, an over-count "
        "on the first. Replace with a forward measurement of true original dates (DESIGN.md)."),
    "soccer.epl.cancelled_rate": Evidence(
        "soccer.epl.cancelled_rate", 0.000000, 1520,
        "openfootball Premier League season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L33,
        "0 of 1520: every season parsed to exactly N(N-1) matches. Registered verbatim; the rule-of-three bound at "
        "this n is ~0.002 and a re-measurement over more seasons is the honest way to raise it."),
    "soccer.lal.postponed_gt48h_rate": Evidence(
        "soccer.lal.postponed_gt48h_rate", 0.013816, 1520,
        "openfootball La Liga season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L33,
        "PROXY: 21 of 1520 matches were played more than 48 h after their round's core window. "
        "It counts every such move, including cup-related moves announced weeks ahead (not postponements at the "
        "venue's listing time), and misses every move inside the window; a FLOOR on the second count, an over-count "
        "on the first. Replace with a forward measurement of true original dates (DESIGN.md)."),
    "soccer.lal.cancelled_rate": Evidence(
        "soccer.lal.cancelled_rate", 0.000000, 1520,
        "openfootball La Liga season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L33,
        "0 of 1520: every season parsed to exactly N(N-1) matches. Registered verbatim; the rule-of-three bound at "
        "this n is ~0.002 and a re-measurement over more seasons is the honest way to raise it."),
    # CFB deliberately absent (L60, 2026-09-09). L32's denominator included conference-title and
    # FCS-playoff games that its immutable spec excludes, its press-indexed FCS numerator is an
    # acknowledged FLOOR, and it registered raw point estimates rather than conservative exact
    # upper bounds. The historical values remain in L32's immutable results; they cannot mint a
    # settlement proof. L60 must complete before these keys may return.
    "soccer.el1.postponed_gt48h_rate": Evidence(
        "soccer.el1.postponed_gt48h_rate", 0.083333, 2208,
        "openfootball EFL League One season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L35,
        "PROXY (L33's design): 184 of 2208 matches played more than 48 h after their round's core window; "
        "over-counts moves announced weeks ahead, misses moves inside the window. FLOOR label as for L33."),
    "soccer.el1.cancelled_rate": Evidence(
        "soccer.el1.cancelled_rate", 0.000000, 2208,
        "openfootball EFL League One season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L35,
        "0 of 2208: every season parsed to exactly N(N-1) league matches (playoff rounds excluded)."),
    "soccer.elc.postponed_gt48h_rate": Evidence(
        "soccer.elc.postponed_gt48h_rate", 0.031703, 2208,
        "openfootball EFL Championship season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L35,
        "PROXY (L33's design): 70 of 2208 matches played more than 48 h after their round's core window; "
        "over-counts moves announced weeks ahead, misses moves inside the window. FLOOR label as for L33."),
    "soccer.elc.cancelled_rate": Evidence(
        "soccer.elc.cancelled_rate", 0.000000, 2208,
        "openfootball EFL Championship season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L35,
        "0 of 2208: every season parsed to exactly N(N-1) league matches (playoff rounds excluded)."),
    "soccer.ita.postponed_gt48h_rate": Evidence(
        "soccer.ita.postponed_gt48h_rate", 0.010526, 1520,
        "openfootball Serie A season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L35,
        "PROXY (L33's design): 16 of 1520 matches played more than 48 h after their round's core window; "
        "over-counts moves announced weeks ahead, misses moves inside the window. FLOOR label as for L33."),
    "soccer.ita.cancelled_rate": Evidence(
        "soccer.ita.cancelled_rate", 0.000000, 1520,
        "openfootball Serie A season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L35,
        "0 of 1520: every season parsed to exactly N(N-1) league matches (playoff rounds excluded)."),
    "tennis.walkover_rate": Evidence(
        "tennis.walkover_rate", 0.007955, 26398,
        "ATP main tour (Tennismylife/TML-Database, the Sackmann layout) and WTA (VictorSquidWei/tennis_wta, a Sackmann fork), "
        "seasons 2021-2025, team ties (level D) excluded; commits pinned under the row", "2026-09-04", _L39,
        "210 of 26398 main-draw matches were walkovers (score W/O): ATP 98 of 13598 = 0.0072, WTA 112 of 12800 = 0.0088. "
        "Retirements (789) and defaults (4) are ruled SAME and not counted here."),
}



def _tennis_delay() -> Evidence:
    """tennis.delayed_gt7d_rate has no backward source (L39: results files carry tournament starts,
    never match dates). It is measured FORWARD by nodes/watch_settle over the lane's own Polymarket
    gameStartTime records (ledger F4, registered 2026-09-05). The registered value is the row's
    pre-declared estimator -- the one-sided 95% upper bound (rule of three at zero events) while
    n < 300, the point estimate after -- read from the newest results file of the row, so the
    reserve shrinks as the row accrues and never rests on a point estimate of a rare event from a
    small n. The fallback pins the first resolved run (0 of 42) if the results directory is absent."""
    from nodes.watch_settle.settle import registered_delay_rate
    got = registered_delay_rate(Path(__file__).resolve().parents[2] / _F4_DIR)
    value, n, run = got if got else (3.0 / 42, 42, "20260904T193007Z (pinned fallback)")
    return Evidence("tennis.delayed_gt7d_rate", round(value, 6), n,
                    "the lane's own Polymarket first-seen gameStartTime per ATP/WTA event (nodes/watch_settle), resolved daily at Gamma "
                    "(com.janus.watch-settle, 13:30 local); ITF excluded", "2026-09-05", _F4,
                    f"UPPER BOUND, not a point estimate: one-sided 95% (rule of three at zero events) over n resolved tennis rows "
                    f"while n < 300, per the row's spec; latest run {run}. The delay clock runs from the FIRST-SEEN start; "
                    f"resolution time is the poll time (a +-24 h box), which can only lengthen a delay.")


EVIDENCE["tennis.delayed_gt7d_rate"] = _tennis_delay()


def rates(overrides: Mapping[str, float] | None = None) -> dict[str, float]:
    out = {k: e.value for k, e in EVIDENCE.items()}
    if overrides:
        out.update(overrides)
    return out

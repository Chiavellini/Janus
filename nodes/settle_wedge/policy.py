#!/usr/bin/env python3
"""The reviewed templates and, per pair of templates, the verdict on every settlement dimension.

This is a LOOKUP over text a human has read, not a classifier over prose. Each template below is
the venue's rules text with the per-game parts stripped (`harvest.normalise_template`), recorded
verbatim from the API on the date shown. A harvested record whose template hash matches none of
these is UNKNOWN, and UNKNOWN blocks. When a venue edits its wording the hash moves, the lookup
misses, and the league blocks until someone reads the new text and adds it here with a date.

The twelve dimensions are the spec's (§5). A verdict per dimension per PAIR:
  SAME       both venues produce the same terminal payout in this situation
  NA         the situation cannot arise for this league/market (with the citation that says so)
  BOUNDED    the payouts differ, the loss is bounded, and `evidence_key` names the measured
             probability that prices it (absent evidence -> UNKNOWN -> block)
  DIFFERENT  the payouts differ and the loss is not bounded -> block
  UNKNOWN    nobody has established it -> block
"""

from __future__ import annotations

from dataclasses import dataclass

from kernel.schema import SettleRef, TiePolicy, VoidPolicy
from nodes.settle_wedge.harvest import _sha, normalise_template

DIMENSIONS = ("official_source", "winner_determination", "overtime", "tie", "postponement",
              "cancellation", "suspended", "abandoned", "player_non_participation",
              "retirement", "dispute_revision", "settlement_timing")


@dataclass(frozen=True)
class Verdict:
    dimension: str
    outcome: str                       # SAME | NA | BOUNDED | DIFFERENT | UNKNOWN
    detail: str
    evidence_key: str | None = None    # BOUNDED only: the measured probability that prices it
    loss_model: str | None = None      # BOUNDED only: how the loss per contract is computed


@dataclass(frozen=True)
class Template:
    """A venue's rules text a human has read. `sample_text` is VERBATIM from the API on
    `reviewed_on`, with the participants named so the normaliser can strip them; the template is
    derived, never hand-typed, so it cannot drift from what `harvest` computes."""
    template_id: str
    venue: str
    leagues: frozenset
    reviewed_on: str
    sample_text: str
    sample_participants: tuple[str, ...]
    settle_ref: SettleRef              # this venue's own policies, for the record

    @property
    def template_text(self) -> str:
        return normalise_template(self.sample_text, self.sample_participants)

    @property
    def template_hash(self) -> str:
        return _sha(self.template_text)


# ── the templates, recorded verbatim from the API on 2026-09-02 ──────────────
KALSHI_MLB_GAME_V1 = Template(
    "kalshi_mlb_game_v1", "kalshi", frozenset({"mlb"}), "2026-09-02",
    # KXMLBGAME-26SEP022210STLLAD-STL, rules_primary + "\n" + rules_secondary
    "If St. Louis wins the St. Louis vs Los Angeles D professional baseball game originally scheduled "
    "for Sep 2, 2026 at 10:10 PM EDT, then the market resolves to Yes.\n"
    "The following market refers to the St. Louis vs Los Angeles D professional baseball game originally "
    "scheduled for Sep 2, 2026 at 10:10 PM EDT. If this game is postponed or delayed, the market will "
    "remain open and close after the rescheduled game has finished (within two days). If the game is "
    "cancelled or rescheduled to over two days away, the market will resolve to a fair price in "
    "accordance with the rules.\n\nKalshi is not affiliated, associated, authorized, endorsed by, or in "
    "any way officially connected with the Governing League. All trademarks, logos, and brand names are "
    "the property of their respective owners.",
    ("St. Louis", "Los Angeles D"),
    SettleRef(source_agency="ESPN / Fox Sports / MLB", oracle="kalshi",
              void_policy=VoidPolicy.LAST_FAIR_MARKET_PRICE, tie_policy=TiePolicy.UNKNOWN,
              ot_included=True, dnp_policy=VoidPolicy.UNKNOWN, retirement_policy=None,
              revision_policy="in accordance with the rules", dispute_mechanism="kalshi",
              settle_lag_h_p50=None, terms_url=None, provenance="api_field"))

POLYMARKET_MLB_GAME_V1 = Template(
    "polymarket_mlb_game_v1", "polymarket", frozenset({"mlb"}), "2026-09-02",
    # mlb-stl-lad-2026-09-02, market.description
    "In the upcoming MLB game between the St. Louis Cardinals and Los Angeles Dodgers, scheduled for "
    "September 2 at 10:10PM ET:\n\nThis market will resolve to \"St. Louis Cardinals\" if the St. Louis "
    "Cardinals win the game.\n\nThis market will resolve to \"Los Angeles Dodgers\" if the Los Angeles "
    "Dodgers win the game.\n\nIf the game is postponed, this market will remain open until the game has "
    "been completed. If the game is canceled entirely, with no make-up game, or ends in a tie, this "
    "market will resolve 50-50.\n\nThe primary resolution source for this market is the official final "
    "statistics of the event as recognized by the governing body or event organizers. However, if the "
    "governing body or event organizers have not published final match statistics within 24 hours after "
    "the event's conclusion, a consensus of credible reporting may be used instead.",
    ("St. Louis Cardinals", "Los Angeles Dodgers"),
    SettleRef(source_agency="MLB official final statistics", oracle="uma",
              void_policy=VoidPolicy.RESOLVE_FIFTY, tie_policy=TiePolicy.RESOLVE_FIFTY,
              ot_included=True, dnp_policy=VoidPolicy.UNKNOWN, retirement_policy=None,
              revision_policy="consensus of credible reporting after 24h", dispute_mechanism="uma",
              settle_lag_h_p50=None, terms_url="https://www.mlb.com/", provenance="api_field"))

KALSHI_NFL_GAME_V1 = Template(
    "kalshi_nfl_game_v1", "kalshi", frozenset({"nfl"}), "2026-09-03",
    # KXNFLGAME-26SEP09NESEA-SEA, rules_primary + "\n" + rules_secondary
    "If Seattle wins the New England vs Seattle professional football game originally scheduled for "
    "Sep 9, 2026, then the market resolves to Yes.\n"
    "The following market refers to the team who wins the New England vs Seattle professional football "
    "game originally scheduled for Sep 9, 2026. If the game ends in a tie, the market will resolve to "
    "$0.50 for each team. If the game is postponed but begins within 48 hours from its originally "
    "scheduled start time, the market will remain open and resolve based on the official final result. "
    "If the game is not started within 48 hours, the market will resolve to a fair market price.\n\n"
    "Kalshi is not affiliated, associated, authorized, endorsed by, or in any way officially connected "
    "with the Governing League. All trademarks, logos, and brand names are the property of their "
    "respective owners.",
    ("New England", "Seattle"),
    SettleRef(source_agency="NFL", oracle="kalshi", void_policy=VoidPolicy.LAST_FAIR_MARKET_PRICE,
              tie_policy=TiePolicy.RESOLVE_FIFTY, ot_included=True, dnp_policy=VoidPolicy.UNKNOWN,
              retirement_policy=None, revision_policy="official final result", dispute_mechanism="kalshi",
              settle_lag_h_p50=None, terms_url="https://assets.kalshi.com/regulatory/product-certifications/NFLGAME.pdf",
              provenance="api_field"))

POLYMARKET_NFL_GAME_V1 = Template(
    "polymarket_nfl_game_v1", "polymarket", frozenset({"nfl"}), "2026-09-03",
    # nfl-ne-sea-2026-09-10, market.description
    "In the upcoming NFL game, scheduled for September 9 at 8:20PM ET:\nIf Patriots wins, the market will "
    "resolve to \"Patriots\".\nIf Seahawks wins, the market will resolve to \"Seahawks\".\nIf the game is "
    "postponed, this market will remain open until the game has been completed.\nIf the game is canceled "
    "entirely or ends in a tie, with no make-up game, this market will resolve 50-50.",
    ("New England Patriots", "Seattle Seahawks"),
    SettleRef(source_agency="NFL official scores", oracle="uma", void_policy=VoidPolicy.RESOLVE_FIFTY,
              tie_policy=TiePolicy.RESOLVE_FIFTY, ot_included=True, dnp_policy=VoidPolicy.UNKNOWN,
              retirement_policy=None, revision_policy=None, dispute_mechanism="uma", settle_lag_h_p50=None,
              terms_url="https://www.nfl.com/scores", provenance="api_field"))

TEMPLATES: dict[str, Template] = {t.template_hash: t for t in (KALSHI_MLB_GAME_V1, POLYMARKET_MLB_GAME_V1,
                                                              KALSHI_NFL_GAME_V1, POLYMARKET_NFL_GAME_V1)}


def template_for(template_hash: str) -> Template | None:
    return TEMPLATES.get(template_hash)


# ── per pair of templates: the twelve verdicts ───────────────────────────────
_MLB_K_PM = (
    Verdict("official_source", "SAME",
            "both settle on the official final result (Kalshi: ESPN/Fox/MLB; Polymarket: MLB official "
            "final statistics). For a completed game the reference is the same fact."),
    Verdict("winner_determination", "SAME", "the team that wins the game, both venues."),
    Verdict("overtime", "SAME", "extra innings are part of a baseball game on both venues; there is no "
            "regulation-only market here."),
    Verdict("tie", "NA", "MLB Official Baseball Rules 7.01: no regulation tie exists (the exhaustiveness "
            "citation). Polymarket's 50-50 tie clause cannot fire."),
    Verdict("postponement", "BOUNDED",
            "Kalshi stays open only if the makeup finishes within two days, else resolves to a fair price; "
            "Polymarket stays open until the game is completed. A makeup more than two days out pays "
            "Kalshi ~its own price and Polymarket the eventual result: bounded loss on the Polymarket leg.",
            evidence_key="mlb.postponed_gt2d_rate", loss_model="kalshi_fair_vs_pm_result"),
    Verdict("cancellation", "BOUNDED",
            "Kalshi resolves to a fair price; Polymarket resolves 50-50. The cover loses when the "
            "Polymarket leg is the favourite: max(0, p_pm - 0.5) per contract.",
            evidence_key="mlb.cancelled_rate", loss_model="kalshi_fair_vs_pm_half"),
    Verdict("suspended", "BOUNDED",
            "A suspended game resumes later (MLB rule 7.02); both venues wait for completion, Kalshi "
            "only within two days. Same shape as postponement.",
            evidence_key="mlb.postponed_gt2d_rate", loss_model="kalshi_fair_vs_pm_result"),
    Verdict("abandoned", "SAME", "a game called after it is official (5 innings) settles on the official "
            "result on both venues; one called earlier is suspended or postponed (above)."),
    Verdict("player_non_participation", "NA", "team moneyline; no player condition on either venue."),
    Verdict("retirement", "NA", "not a tennis market."),
    Verdict("dispute_revision", "SAME",
            "terminal outcome is the official result on both; the mechanisms differ (Kalshi's rules vs "
            "UMA's proposal/dispute) and a misresolution is an operational risk monitored at "
            "reconciliation, not a payout difference by rule."),
    Verdict("settlement_timing", "SAME",
            "payouts agree; Kalshi settles ~2 min after expiry, Polymarket after UMA liveness (15 min) "
            "plus proposal. Capital-availability skew is the risk ledger's job (release after both)."),
)

_NFL_K_PM = (
    Verdict("official_source", "SAME", "both settle on the official NFL result (Kalshi: the Governing League; "
            "Polymarket: nfl.com scores)."),
    Verdict("winner_determination", "SAME", "the team that wins the game, both venues."),
    Verdict("overtime", "SAME", "the full game including overtime on both venues."),
    Verdict("tie", "SAME",
            "Kalshi resolves each team's market to $0.50; Polymarket resolves 50-50. A two-leg cover holds one "
            "contract of each side and receives 0.50 + 0.50 = $1.00 on a tie: the same terminal payout as a win."),
    Verdict("postponement", "BOUNDED",
            "Kalshi stays open only if the game starts within 48 hours, else resolves to a fair market price; "
            "Polymarket stays open until the game is completed. Bounded on the Polymarket leg.",
            evidence_key="nfl.postponed_gt48h_rate", loss_model="kalshi_fair_vs_pm_result"),
    Verdict("cancellation", "BOUNDED",
            "Kalshi's not-started-within-48-hours clause resolves to a fair market price; Polymarket resolves 50-50.",
            evidence_key="nfl.cancelled_rate", loss_model="kalshi_fair_vs_pm_half"),
    Verdict("suspended", "BOUNDED", "a suspended NFL game resumes; same shape as postponement.",
            evidence_key="nfl.postponed_gt48h_rate", loss_model="kalshi_fair_vs_pm_result"),
    Verdict("abandoned", "SAME", "an NFL game is not called official before completion; an abandoned game is "
            "rescheduled or cancelled (above)."),
    Verdict("player_non_participation", "NA", "team moneyline; no player condition on either venue."),
    Verdict("retirement", "NA", "not a tennis market."),
    Verdict("dispute_revision", "SAME", "terminal outcome is the official result on both; mechanisms differ."),
    Verdict("settlement_timing", "SAME", "payouts agree; timing differs and is the risk ledger's job."),
)

PAIR_POLICY: dict[tuple[str, str], tuple[Verdict, ...]] = {
    ("kalshi_mlb_game_v1", "polymarket_mlb_game_v1"): _MLB_K_PM,
    ("kalshi_nfl_game_v1", "polymarket_nfl_game_v1"): _NFL_K_PM,
}


def verdicts_for(template_a: str, template_b: str) -> tuple[Verdict, ...] | None:
    return PAIR_POLICY.get((template_a, template_b)) or PAIR_POLICY.get((template_b, template_a))

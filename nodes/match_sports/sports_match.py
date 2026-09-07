#!/usr/bin/env python3
"""Stage 2 — cross-venue matching on a canonical key. NO PRICES ARE READ.

Registered spec: research/sports/2026-08-17_stage2-matching/spec.yaml (ledger L9, PENDING).
The gate was written before this file existed and is NOT tunable:
    coverage  >= 0.80   (denominator from the schedule, not from this matcher's output)
    precision >= 0.98   (against match/gold/mlb_moneyline.csv, frozen before the first run)

WHAT REPLACED WHAT
──────────────────
Phase 1 blocked on title tokens and capped recall at 12 candidates per market, then scored the
survivors by Jaccard. On sports that is worse than useless: "Lakers vs Celtics Nov 3" and
"Lakers vs Celtics Nov 17" share nearly every token and are different games.

Here both venues are resolved INDEPENDENTLY onto an external schedule (`nodes/schedule_espn/espn.py`),
and two markets pair iff they land on the same `game_id` AND agree on every component of the
canonical key. There is no similarity score, no threshold, and no recall cap — an exact key needs
none.

THE THREE DISCRIMINATIONS THAT MATTER
─────────────────────────────────────
1. **period / market_type.** Polymarket lists `-first-five-winner`, `-player-props`, `-nrfi`,
   spreads and totals as SEPARATE events sharing the parent's teams and `gameStartTime`. They are
   not the same contract. Fifteen of them sit in the gold file as hard negatives precisely because
   participants-plus-time is NOT sufficient.
2. **start time, not date.** MLB doubleheaders put two games of one matchup on one date. G1 and G2
   are separated only by the clock, which Kalshi states in `rules_primary` and PM in
   `gameStartTime`.
3. **the slug lies.** PM keeps a game's ORIGINAL slug when it is postponed. In the current slate
   the STL/CIN doubleheader resolves to `mlb-stl-cin-2026-05-24` (G1, the May makeup) and
   `mlb-stl-cin-2026-08-17` (G2). Anything keyed on the slug date gets G1 wrong by three months.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nodes.match_sports.stage1_checkpoint import (
    KALSHI_BASE, PM_GAMMA, VENUE_TZ, games_on_local_date, kalshi_date_from_rules, kalshi_date_from_ticker,
    kalshi_start_from_rules, pull_kalshi, pull_pm, _pm_start,
)
from kernel.schema import CanonicalKey, KeyProvenance
from nodes.entities.resolve import Resolver, normalize
from nodes.entities.seed import NON_TEAM_OUTCOMES
from nodes.entities.leagues import LEAGUES
from nodes.venue_polymarket.books import pm_primary_market
from nodes.schedule_espn import espn

#: A PM FULL-GAME moneyline slug is exactly `{league}-{away}-{home}-{YYYY-MM-DD}`. Any further
#: suffix marks a derivative event — a different period (`-first-five-winner`, `-halftime-result`,
#: `-second-half-result`) or a different market type (`-player-props`, `-nrfi`, `-total-9pt5`,
#: `-spread-away-1pt5`, `-exact-score`, `-first-to-score`).
#:
#: This was hardcoded to `^mlb-` and applied to EVERY league, so NFL/NBA/WNBA/NHL/EPL rejected
#: every event as `derivative_event_not_full_game_moneyline` and emitted zero pairs — a coverage
#: failure that read as a benign reason code. Sampled 2026-09-02 against live Gamma data, the
#: convention is identical across leagues (mlb-tb-nyy-…, nfl-ne-sea-…, nhl-tor-mon-…, epl-ips-liv-…),
#: so the league prefix is a parameter, never a constant.
#: The draw of a three-way game is an outcome with no participant. One id on both venues, so the
#: exact join pairs Kalshi's "Tie" market with Polymarket's draw market like any other side.
DRAW_ENTITY = "draw"


def _fullgame_slug(league: str) -> re.Pattern[str]:
    prefix = LEAGUES[league].pm_prefix if league in LEAGUES else league
    # team abbreviations run 2-4 characters; a player's slug piece runs up to 8 ("siegemu", "samsono")
    return re.compile(rf"^{re.escape(prefix)}-[a-z0-9]{{2,8}}-[a-z0-9]{{2,8}}-\d{{4}}-\d{{2}}-\d{{2}}$")


@dataclass(frozen=True)
class VenueMarket:
    """One venue's rendering of one tradeable side. Deliberately price-free at this stage."""
    venue: str
    venue_id: str            # ticker (Kalshi) / slug (Polymarket)
    outcome_id: str          # the specific contract
    game_id: str
    entity_id: str           # which participant this side backs
    market_type: str         # "moneyline"
    period: str              # "game" -- kernel/schema.PERIODS vocabulary, as rules_exhaustive keys it
    start_utc: int
    label: str               # the venue's own text, kept for auditing
    #: The venue's settlement text, raw, for nodes/settle_wedge. Price-free, like everything here.
    rules: dict = field(default_factory=dict)
    #: The kernel's canonical identity: league + SORTED ESPN participant ids + external start +
    #: market type + period. Orientation is `entity_id`, never in the key. Built from the
    #: schedule game both venues resolved onto, so two markets pair iff their keys are equal.
    key: CanonicalKey | None = None
    #: How this venue's start time was obtained. Kalshi parses it from rules text
    #: (TICKER_PARSE grade); Polymarket exposes gameStartTime (API_STRUCTURED).
    key_provenance: KeyProvenance = KeyProvenance.TITLE_REGEX


def _reason(bucket: Counter, key: str) -> None:
    bucket[key] += 1


def canonical_key(g, league: str) -> CanonicalKey:
    """The kernel key for a scheduled game. Participants are ESPN team ids, sorted."""
    return CanonicalKey(league=league, participants=g.participants_espn, start_utc=int(g.start_utc),
                        market_type="moneyline", period="game")


# ── venue normalization (no prices) ──────────────────────────────────────────

def venue_structured_game(cands, ymd) -> tuple:
    """The schedule game a venue-structured (tennis) ticker names: the unique candidate on the
    ticker's date, else the unique candidate ONE day away. A ticker keeps the day the match was
    first scheduled; a match moved by a day (rain, order of play) keeps its ticker, and two
    players meet once per tournament, so a lone candidate a day away is the same match. Swiatek v
    Zheng, 2026-09-07: ticker `26SEP06`, played Sep 7, in play on both venues, unpaired for hours.
    Returns (game or None, shifted)."""
    if not ymd:
        return None, False
    d = date(ymd[0], ymd[1], ymd[2])
    g = games_on_local_date(cands, d)
    if g is not None:
        return g, False
    near = [c for c in cands if abs((datetime.fromtimestamp(c.start_utc, VENUE_TZ).date() - d).days) == 1]
    if len(cands) == 1 and len(near) == 1:
        return near[0], True
    return None, False


def kalshi_markets(league: str, r: Resolver, by_pair, window, stats, near_miss) -> list[VenueMarket]:
    lo, hi = window
    out: list[VenueMarket] = []
    for ev in pull_kalshi(league, _client("kalshi")):
        tick = ev.get("event_ticker", "")
        three_way = LEAGUES[league].outcomes == 3 if league in LEAGUES else False
        mkts = [m for m in (ev.get("markets") or [])
                if normalize(m.get("yes_sub_title") or "") not in NON_TEAM_OUTCOMES]
        draws = [m for m in (ev.get("markets") or [])
                 if normalize(m.get("yes_sub_title") or "") in NON_TEAM_OUTCOMES]
        if not mkts:
            _reason(stats["k_reason"], "no_participant_market")
            continue
        stats["kalshi_events"] += 1
        sides = []
        for m in mkts:
            cs = m.get("custom_strike") or {}
            uuid = next((v for v in cs.values() if isinstance(v, str) and len(v) >= 32), None)
            res = r.resolve(league, text=m.get("yes_sub_title"), venue="kalshi", venue_team_id=uuid)
            if res.ok:
                sides.append((m, res.entity_id))
                if uuid and res.method != "xref":
                    # The full name resolved (a player Polymarket lists today, `add_player`); the
                    # venue's id is learned on first sight so the next pass is exact.
                    r.xrefs.setdefault(("kalshi", uuid), res.entity_id)
        if len({e for _, e in sides}) != 2:
            _reason(stats["k_reason"], "entity_resolution")
            near_miss.append({"venue": "kalshi", "id": tick, "reason": "entity_resolution",
                              "labels": [m.get("yes_sub_title") or "" for m in mkts],
                              "resolved": [e for _, e in sides]})
            continue
        rules = (mkts[0].get("rules_primary") or "") + " " + (mkts[0].get("rules_secondary") or "")
        espn_ids = tuple(sorted(r.teams[e].espn_id for _, e in sides if e in r.teams))
        cands = by_pair.get(espn_ids, [])
        st = kalshi_start_from_rules(rules)
        if league in LEAGUES and LEAGUES[league].anchor == "venue_structured":
            # No date in the rules text (tennis names the tournament and round instead): the
            # ticker date is the venue's own statement of the day.
            ymd = kalshi_date_from_ticker(tick)
            g, shifted = venue_structured_game(cands, ymd)
            if shifted:
                _reason(stats["k_reason"], "date_shifted_1d")
        else:
            g = (espn.nearest_game(cands, st) if st is not None
                 else games_on_local_date(cands, kalshi_date_from_rules(rules) or datetime.now().date()))
        if g is None:
            if cands:
                _reason(stats["k_reason"], "no_schedule_match")
                near_miss.append({"venue": "kalshi", "id": tick, "reason": "no_schedule_match",
                                  "labels": [m.get("yes_sub_title") or "" for m in mkts],
                                  "candidates": [c.game_id for c in cands]})
            else:
                _reason(stats["k_reason"], "outside_window")
            continue
        if not (lo <= g.start_utc < hi):
            _reason(stats["k_reason"], "outside_window")
            continue
        # A three-way game's draw is a third OUTCOME with no participant: the Kalshi "Tie" market,
        # entity DRAW_ENTITY, same key. Without it a soccer cover has two legs and pays nothing on
        # a draw, which is the +31% ghost the exhaustiveness proof exists to refuse.
        if three_way:
            if len(draws) != 1:
                _reason(stats["k_reason"], "no_draw_market")
                near_miss.append({"venue": "kalshi", "id": tick, "reason": "no_draw_market", "game_id": g.game_id})
                continue
            sides.append((draws[0], DRAW_ENTITY))
        stats.setdefault("k_games", set()).add(g.game_id)
        for m, eid in sides:
            out.append(VenueMarket("kalshi", tick, m["ticker"], g.game_id, eid,
                                   "moneyline", "game", g.start_utc,
                                   m.get("yes_sub_title") or "",
                                   rules={"ticker": m["ticker"], "rules_primary": m.get("rules_primary") or "",
                                          "rules_secondary": m.get("rules_secondary") or ""},
                                   key=canonical_key(g, league),
                                   key_provenance=(KeyProvenance.TICKER_PARSE if st is not None
                                                   else KeyProvenance.TITLE_REGEX)))
    return out


def seed_live_players(league: str, r: Resolver, events: list[dict]) -> int:
    """A venue-structured league's participants are whoever Polymarket lists today: each becomes
    an entity for this pass (`Resolver.add_player`), so the Kalshi side resolves by the same full
    name and both venues' ids are learned. Doubles pairs are not players. Returns players added."""
    prefix = LEAGUES[league].pm_prefix if league in LEAGUES else league
    seeded: set[str] = set()
    for ev in events:
        slug = str(ev.get("slug", ""))
        if not slug.startswith(prefix + "-") or "doubles" in slug:
            continue
        for t in ev.get("teams") or []:
            if t.get("name"):
                eid = r.add_player(league, name=str(t["name"]), venue="polymarket",
                                   venue_id=str(t.get("id") or "") or None,
                                   abbreviation=str(t.get("abbreviation") or ""))
                if eid:
                    seeded.add(eid)
    return len(seeded)


_LOOSE_SLUG: dict[str, re.Pattern] = {}


def pm_markets(league: str, r: Resolver, by_pair, window, stats, near_miss, *, events=None) -> list[VenueMarket]:
    lo, hi = window
    out: list[VenueMarket] = []
    prefix = LEAGUES[league].pm_prefix if league in LEAGUES else league
    loose = _LOOSE_SLUG.setdefault(league, re.compile(rf"^{re.escape(prefix)}-[a-z0-9]+-[a-z0-9]+-\d{{4}}-\d{{2}}-\d{{2}}$"))
    for ev in (events if events is not None else pull_pm(league, _client("polymarket"))):
        slug = ev.get("slug", "")
        teams = ev.get("teams") or []
        if len(teams) != 2:
            _reason(stats["p_reason"], "teams_not_two")          # counted since 2026-09-07; was silent
            continue
        stats["pm_events"] += 1
        # DISCRIMINATION 1: derivative events share teams and start time but are not the same
        # contract. Rejecting them here is what the 15 hard negatives in the gold file test.
        # Named apart (2026-09-07): another league under a shared tag, a doubles slug, a slug piece
        # longer than the pattern allows, and the genuine derivative.
        if not _fullgame_slug(league).match(slug):
            if not slug.startswith(prefix + "-"):
                _reason(stats["p_reason"], "other_league_under_shared_tag")
            elif "doubles" in slug:
                _reason(stats["p_reason"], "doubles")
            elif loose.match(slug):
                _reason(stats["p_reason"], "slug_piece_too_long")
                near_miss.append({"venue": "polymarket", "id": slug, "reason": "slug_piece_too_long",
                                  "labels": [t.get("name") or "" for t in teams]})
            else:
                _reason(stats["p_reason"], "derivative_event_not_full_game_moneyline")
            continue
        # College football on Polymarket names `teams` by nickname alone ("Wildcats", "Demons") while
        # the moneyline's `outcomes` carry the schools; the outcome label is the fallback, in order.
        labels = _pm_outcome_labels(ev, slug)
        ents = []
        for i, t in enumerate(teams):
            res = r.resolve(league, text=t.get("name"), venue="polymarket",
                            venue_team_id=str(t.get("id") or ""))
            if not res.ok and i < len(labels):
                res = r.resolve(league, text=labels[i], venue="polymarket")
                if res.ok:
                    t = {**t, "name": labels[i]}
            if res.ok:
                ents.append((t, res.entity_id))
        if len({e for _, e in ents}) != 2:
            _reason(stats["p_reason"], "entity_resolution")
            near_miss.append({"venue": "polymarket", "id": slug, "reason": "entity_resolution",
                              "labels": [t.get("name") or "" for t in teams], "resolved": [e for _, e in ents]})
            continue
        st = _pm_start(ev)
        if st is None:
            _reason(stats["p_reason"], "no_start_time")
            continue
        espn_ids = tuple(sorted(r.teams[e].espn_id for _, e in ents if e in r.teams))
        cands = by_pair.get(espn_ids, [])
        g = espn.nearest_game(cands, st)
        if g is None:
            # The same split as the Kalshi side: a pair with no game in the universe at all is
            # outside the window, not a schedule miss (2026-09-07: every tennis "no_schedule_match"
            # was a match already past the 5 h post rule or beyond --pre-hours).
            if cands:
                _reason(stats["p_reason"], "no_schedule_match")
                near_miss.append({"venue": "polymarket", "id": slug, "reason": "no_schedule_match",
                                  "labels": [t.get("name") or "" for t in teams], "candidates": [c.game_id for c in cands]})
            else:
                _reason(stats["p_reason"], "outside_window")
            continue
        if not (lo <= g.start_utc < hi):
            _reason(stats["p_reason"], "outside_window")
            continue
        stats.setdefault("p_games", set()).add(g.game_id)
        mk = pm_primary_market(ev, slug) or {}
        pm_rules = {"slug": mk.get("slug") or slug, "description": mk.get("description") or "",
                    "resolutionSource": mk.get("resolutionSource") or ev.get("resolutionSource") or ""}
        for t, eid in ents:
            out.append(VenueMarket("polymarket", slug, f"{slug}:{t.get('abbreviation')}",
                                   g.game_id, eid, "moneyline", "game", g.start_utc,
                                   t.get("name") or "", rules=pm_rules,
                                   key=canonical_key(g, league), key_provenance=KeyProvenance.API_STRUCTURED))
        if league in LEAGUES and LEAGUES[league].outcomes == 3:
            if not any(str(x.get("slug", "")) == f"{slug}-draw" for x in ev.get("markets") or []):
                _reason(stats["p_reason"], "no_draw_market")
                near_miss.append({"venue": "polymarket", "id": slug, "reason": "no_draw_market", "game_id": g.game_id})
                out = [m for m in out if m.venue_id != slug]
                stats["p_games"].discard(g.game_id)
                continue
            out.append(VenueMarket("polymarket", slug, f"{slug}:draw", g.game_id, DRAW_ENTITY, "moneyline", "game",
                                   g.start_utc, "Draw", rules=pm_rules, key=canonical_key(g, league),
                                   key_provenance=KeyProvenance.API_STRUCTURED))
    return out


def _pm_outcome_labels(ev: dict, slug: str) -> list[str]:
    import json as _json
    mk = next((x for x in ev.get("markets") or [] if x.get("slug") == slug), None)
    outs = (mk or {}).get("outcomes")
    if isinstance(outs, str):
        try:
            outs = _json.loads(outs)
        except ValueError:
            outs = None
    return [str(o) for o in outs] if isinstance(outs, list) and len(outs) == 2 else []


def _client(name: str):
    from kernel.fetch import Client
    return Client(name, rate=4.0, burst=8.0)


# ── the join ─────────────────────────────────────────────────────────────────

def pair(kalshi: list[VenueMarket], pm: list[VenueMarket]) -> list[dict]:
    """Exact join on the canonical key. No score, no threshold, no recall cap."""
    # The join is on the kernel's CanonicalKey plus the side. `key` already carries league,
    # sorted participants, the external start time, market type and period; a market that
    # resolved onto no schedule game has no key and can pair with nothing.
    idx: dict[tuple, list[VenueMarket]] = defaultdict(list)
    for m in pm:
        if m.key is not None:
            idx[(m.key, m.entity_id)].append(m)
    pairs = []
    for k in kalshi:
        if k.key is None:
            continue
        for p in idx.get((k.key, k.entity_id), []):
            pairs.append({"game_id": k.game_id, "entity_id": k.entity_id,
                          "market_type": k.market_type, "period": k.period,
                          "start_utc": k.start_utc,
                          "kalshi_event": k.venue_id, "kalshi_outcome": k.outcome_id,
                          "pm_event": p.venue_id, "pm_outcome": p.outcome_id,
                          "kalshi_label": k.label, "pm_label": p.label,
                          "kalshi_rules": dict(k.rules), "pm_rules": dict(p.rules),
                          "canonical_key": {**asdict(k.key), "participants": list(k.key.participants)},
                          "key_provenance": {"kalshi": k.key_provenance.value,
                                             "polymarket": p.key_provenance.value}})
    return sorted(pairs, key=lambda r: (r["game_id"], r["entity_id"], r["kalshi_outcome"]))


def score_precision(pairs: list[dict], gold_path: Path) -> dict:
    """Score EVENT-level pairings against the frozen gold file.

    The gold file pairs a Kalshi event to a PM event. This matcher emits OUTCOME-level rows, so
    they are collapsed to the distinct (kalshi_event, pm_event) set before scoring — otherwise a
    single correct game would be double-counted and precision would be flattered.
    """
    if not gold_path.exists():
        return {"error": "gold file missing"}
    with gold_path.open(newline="", encoding="utf-8") as fh:
        gold = list(csv.DictReader(fh))
    # LAST ROW WINS: a correction row carries `supersedes` and is appended after the row it
    # replaces, per the spec's append-never-edit rule. Iterating in file order therefore lets the
    # correction take effect while the original label stays visible and auditable in the file.
    truth = {}
    corrections = 0
    for g in gold:
        key = (g["kalshi_ticker"], g["pm_slug"])
        if g.get("supersedes"):
            corrections += 1
        truth[key] = int(g["label"])
    emitted = {(p["kalshi_event"], p["pm_event"]) for p in pairs}
    judged = [(k, truth[k]) for k in emitted if k in truth]
    tp = sum(1 for _, lab in judged if lab == 1)
    fp = sum(1 for _, lab in judged if lab == 0)
    gold_pos = {k for k, lab in truth.items() if lab == 1}
    return {
        "gold_rows": len(gold),
        "gold_correction_rows_applied": corrections,
        "emitted_event_pairs": len(emitted),
        "judged_against_gold": len(judged),
        "not_in_gold": len(emitted) - len(judged),
        "true_positives": tp,
        "false_positives": fp,
        "false_positive_pairs": sorted(k for k, lab in judged if lab == 0)[:20],
        "precision": round(tp / len(judged), 4) if judged else None,
        "gold_positives": len(gold_pos),
        "gold_positives_recovered": len(gold_pos & emitted),
        "gold_recall": round(len(gold_pos & emitted) / len(gold_pos), 4) if gold_pos else None,
        "gold_positives_missed": sorted(gold_pos - emitted),
    }


def run(league: str, days: int, out_dir: Path) -> dict:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    window = (int(start.timestamp()), int(end.timestamp()))

    games = espn.fetch_range(league, start, end, use_cache=False)
    by_pair = espn.index_by_participants(games)

    r = Resolver.load()
    stats = Counter()
    stats["k_reason"] = Counter()
    stats["p_reason"] = Counter()
    near_miss: list[dict] = []

    kms = kalshi_markets(league, r, by_pair, window, stats, near_miss)
    pms = pm_markets(league, r, by_pair, window, stats, near_miss)
    pairs = pair(kms, pms)

    # ── coverage, with the denominator taken from the SCHEDULE ───────────────
    k_games = {m.game_id for m in kms}
    p_games = {m.game_id for m in pms}
    eligible = k_games & p_games                     # both venues independently list it
    matched = defaultdict(set)
    for p in pairs:
        matched[p["game_id"]].add(p["entity_id"])
    complete = {g for g, ents in matched.items() if len(ents) == 2}   # BOTH sides paired
    coverage = round(len(complete) / len(eligible), 4) if eligible else None

    for g in sorted(eligible - complete):
        near_miss.append({"venue": "both", "id": g, "reason": "eligible_but_not_completely_paired"})

    prec = score_precision(pairs, Path("match/gold/mlb_moneyline.csv"))

    result = {
        "spec": "research/sports/2026-08-17_stage2-matching/spec.yaml",
        "ledger_row": "L9",
        "prices_read": False,
        "league": league,
        "window_utc": [start.isoformat(), end.isoformat()],
        "scheduled_games": len(games),
        "kalshi": {"events": stats["kalshi_events"], "markets": len(kms),
                   "games": len(k_games), "reasons": dict(stats["k_reason"])},
        "polymarket": {"events": stats["pm_events"], "markets": len(pms),
                       "games": len(p_games), "reasons": dict(stats["p_reason"])},
        "coverage": {
            "eligible_games_both_venues": len(eligible),
            "completely_paired_games": len(complete),
            "coverage": coverage,
            "threshold": 0.80,
            "pass": (coverage is not None and coverage >= 0.80),
        },
        "precision": {**prec, "threshold": 0.98,
                      "pass": (prec.get("precision") is not None and prec["precision"] >= 0.98)},
        "outcome_pairs_emitted": len(pairs),
    }
    result["gate_pass"] = bool(result["coverage"]["pass"] and result["precision"]["pass"])

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=1))
    with (out_dir / "pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        if pairs:
            w = csv.DictWriter(fh, fieldnames=list(pairs[0])); w.writeheader(); w.writerows(pairs)
    with (out_dir / "near_miss.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["venue", "id", "reason"])
        for n in near_miss:
            w.writerow([n["venue"], n["id"], n["reason"]])
    print(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--out", type=Path,
                    default=Path("research/sports/2026-08-17_stage2-matching"))
    a = ap.parse_args()
    run(a.league, a.days, a.out)

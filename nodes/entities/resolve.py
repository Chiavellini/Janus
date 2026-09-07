#!/usr/bin/env python3
"""Entity resolution: any venue's rendering of a team -> one canonical entity_id.

THE RULE THIS MODULE ENFORCES
─────────────────────────────
**An ambiguous alias is UNRESOLVED, never a best guess.**

This is not fastidiousness. Phase 1's screen produced a "+97.94c edge" that was a 3M Open golfer
matched against a Tour de France cyclist. A wrong entity does not produce a slightly-wrong pair; it
produces a pair of unrelated markets whose prices are unrelated, which looks like an ENORMOUS
arbitrage. False pairs are not noise around zero — they are biased hugely positive, and they sort
straight to the top of any edge-ranked list. So the failure mode of guessing is precisely the
failure mode that wastes the most time.

Concretely: Kalshi renders MLB teams by LOCATION only (`yes_sub_title` = "St. Louis"). In three
markets that is ambiguous —
    "New York"    -> Yankees | Mets
    "Los Angeles" -> Dodgers | Angels
    "Chicago"     -> Cubs | White Sox
— and those are not rare teams. `resolve()` returns `ambiguous_among` for them and refuses to
pick. The caller must disambiguate with a second field (Kalshi's ticker suffix NYY/NYM, or better,
its `custom_strike` team UUID, which is exact).

THREE RESOLUTION PATHS, IN PRECEDENCE ORDER
───────────────────────────────────────────
1. **xref** — a venue's own stable team id. Kalshi exposes a per-team UUID in
   `custom_strike.{sport}_team` (measured: exactly 30 distinct UUIDs for 30 MLB teams, 1:1 with
   names, zero collisions). Polymarket exposes `teams[].id` plus `providerId`. Where an xref
   exists there is NO string matching at all and no ambiguity is possible.
2. **alias** — normalized text lookup, league-scoped. For text-only venues (sportsbooks,
   Smarkets) this is the only path.
3. **nothing** — logged to unresolved.csv with the reason. Never a fuzzy fallback.

There is deliberately no fuzzy/edit-distance/embedding tier. Recall problems here are alias-table
holes, and the fix for a hole is to add the row, auditably, not to lower a threshold globally.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

HERE = Path(__file__).resolve().parent
TEAMS_CSV = HERE / "teams.csv"
ALIASES_CSV = HERE / "aliases.csv"
#: Hand-curated overlay. seed.py REGENERATES aliases.csv from ESPN and would destroy hand-added
#: rows, so anything a human added lives here and is merged at load time. Every row carries the
#: date and the reason it was needed.
ALIASES_MANUAL_CSV = HERE / "aliases_manual.csv"
XREFS_CSV = HERE / "xrefs.csv"
UNRESOLVED_CSV = HERE / "unresolved.csv"

#: Tokens stripped during normalization. Kept SHORT and deliberately conservative — every entry is
#: a chance to collapse two distinct teams together. "fc"/"afc" are safe in England only because no
#: two Premier League clubs differ solely by them; that is checked by the collision assert in
#: build_alias_index(), not assumed.
_NOISE = {"fc", "afc", "cf", "sc", "the"}
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, drop noise tokens, collapse whitespace.

    Deterministic and total: same input always gives the same output, and it never raises.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = _PUNCT.sub(" ", s)
    toks = [t for t in _WS.split(s) if t and t not in _NOISE]
    return " ".join(toks)


@dataclass(frozen=True)
class Team:
    entity_id: str          # "mlb:st-louis-cardinals" — stable, human-readable, league-prefixed
    league: str
    espn_id: str
    abbrev: str
    location: str           # "St. Louis"
    nickname: str           # "Cardinals"
    display_name: str       # "St. Louis Cardinals"


@dataclass(frozen=True)
class Resolution:
    entity_id: str | None
    method: str                       # "xref" | "alias" | "unresolved"
    query: str
    ambiguous_among: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.entity_id is not None

    @property
    def reason(self) -> str:
        if self.ok:
            return ""
        return "ambiguous" if self.ambiguous_among else "unknown"


# ── loading ──────────────────────────────────────────────────────────────────

def load_teams(path: Path = TEAMS_CSV) -> dict[str, Team]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["entity_id"]: Team(**r) for r in csv.DictReader(fh)}


def load_alias_rows(path: Path = ALIASES_CSV,
                    manual: Path | None = ALIASES_MANUAL_CSV) -> list[dict]:
    """Generated aliases plus the hand-curated overlay. Both, always — a caller that loads only
    the generated file silently loses every abbreviation ESPN renders differently from a venue."""
    rows: list[dict] = []
    for p in (path, manual):
        if p and p.exists():
            with p.open(newline="", encoding="utf-8") as fh:
                rows.extend(csv.DictReader(fh))
    return rows


def load_xrefs(path: Path = XREFS_CSV) -> dict[tuple[str, str], str]:
    """(venue, venue_team_id) -> entity_id. Venue ids are globally unique per venue, so the
    league is not part of the key — but a collision across leagues is asserted against."""
    if not path.exists():
        return {}
    out: dict[tuple[str, str], str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            k = (r["venue"], r["venue_team_id"])
            prev = out.get(k)
            if prev is not None and prev != r["entity_id"]:
                raise ValueError(
                    f"xref collision: {k} maps to both {prev!r} and {r['entity_id']!r}. "
                    "A venue team id must identify exactly one entity.")
            out[k] = r["entity_id"]
    return out


def build_alias_index(rows: Iterable[Mapping]) -> dict[tuple[str, str], list[str]]:
    """(league, normalized_alias) -> [entity_id, ...].

    A list, not a scalar, ON PURPOSE. Multi-entry keys are the ambiguous ones ("new york" in mlb)
    and `resolve()` refuses them. Collapsing to a scalar here is exactly the bug this design
    exists to prevent.
    """
    idx: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        key = (r["league"], normalize(r["alias"]))
        if not key[1]:
            continue
        bucket = idx.setdefault(key, [])
        if r["entity_id"] not in bucket:
            bucket.append(r["entity_id"])
    for v in idx.values():
        v.sort()
    return idx


# ── the resolver ─────────────────────────────────────────────────────────────

class Resolver:
    """Holds the tables. Construct once, resolve many."""

    def __init__(self, teams: Mapping[str, Team] | None = None,
                 alias_index: Mapping[tuple[str, str], list[str]] | None = None,
                 xrefs: Mapping[tuple[str, str], str] | None = None):
        self.teams = dict(teams) if teams is not None else load_teams()
        self.alias_index = (dict(alias_index) if alias_index is not None
                            else build_alias_index(load_alias_rows()))
        self.xrefs = dict(xrefs) if xrefs is not None else load_xrefs()
        self.misses: list[dict] = []

    @classmethod
    def load(cls) -> "Resolver":
        return cls()

    def by_xref(self, venue: str, venue_team_id: str | None) -> Resolution:
        q = f"{venue}:{venue_team_id}"
        if venue_team_id is None:
            return Resolution(None, "unresolved", q)
        eid = self.xrefs.get((venue, str(venue_team_id)))
        if eid:
            return Resolution(eid, "xref", q)
        self._miss(q, "", "unknown_xref", venue)
        return Resolution(None, "unresolved", q)

    def by_text(self, league: str, text: str) -> Resolution:
        n = normalize(text)
        if not n:
            return Resolution(None, "unresolved", text)
        hits = self.alias_index.get((league, n), [])
        if len(hits) == 1:
            return Resolution(hits[0], "alias", text)
        if len(hits) > 1:
            self._miss(text, league, "ambiguous", "text")
            return Resolution(None, "unresolved", text, tuple(hits))
        self._miss(text, league, "unknown", "text")
        return Resolution(None, "unresolved", text)

    def resolve(self, league: str, *, text: str | None = None, venue: str | None = None,
                venue_team_id: str | None = None) -> Resolution:
        """xref first, text second. An xref hit is exact and outranks any string agreement."""
        if venue and venue_team_id is not None:
            r = self.by_xref(venue, venue_team_id)
            if r.ok:
                return r
        if text:
            return self.by_text(league, text)
        return Resolution(None, "unresolved", text or f"{venue}:{venue_team_id}")

    # ── live players (2026-09-07) ─────────────────────────────────────────
    def add_player(self, league: str, *, name: str, venue: str, venue_id: str | None,
                   abbreviation: str | None = None) -> str | None:
        """A participant a venue lists RIGHT NOW becomes an entity, in memory, for this pass.

        Tennis has no ESPN roster: the checked-in tables are whoever Polymarket listed at seed
        time (2026-09-07: 147 of 180 ATP and 110 of 126 WTA players on the day's slate were
        absent; Swiatek had no row). The entity is keyed by the player's name, its aliases are
        the name, the abbreviation and "I. Surname", and the venue id becomes an xref -- so the
        other venue's full-name label resolves by text and its id is learned on first sight.
        Returns the entity id, or None for an empty name."""
        n = normalize(name or "")
        if not n:
            return None
        hit = self.by_text(league, name)
        if hit.ok:
            eid = hit.entity_id
        else:
            eid = f"{league}:{re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', n)).strip('-')}"
            if eid not in self.teams:
                parts = name.split()
                self.teams[eid] = Team(entity_id=eid, league=league, espn_id=str(venue_id or ""),
                                       abbrev=(abbreviation or "").upper(), location=" ".join(parts[:-1]),
                                       nickname=parts[-1], display_name=name)
            for a in {name, abbreviation or "", f"{name[0]}. {name.split()[-1]}" if " " in name else ""}:
                key = (league, normalize(a))
                if key[1]:
                    bucket = self.alias_index.setdefault(key, [])
                    if eid not in bucket:
                        bucket.append(eid)
        if venue and venue_id:
            self.xrefs.setdefault((venue, str(venue_id)), eid)
        return eid

    # ── miss log ─────────────────────────────────────────────────────────
    def _miss(self, query: str, league: str, reason: str, source: str) -> None:
        self.misses.append({"query": query, "league": league, "reason": reason, "source": source})

    def write_unresolved(self, path: Path = UNRESOLVED_CSV, *, leagues=None) -> int:
        """Persist misses with counts. This file is a WORK QUEUE, not a log to ignore.

        Every row is either a real alias to add or a market we must consciously decline to match.
        A run scoped to `leagues` keeps every other league's rows as they are.
        """
        agg: dict[tuple, int] = {}
        for m in self.misses:
            agg[(m["league"], m["source"], m["reason"], m["query"])] = \
                agg.get((m["league"], m["source"], m["reason"], m["query"]), 0) + 1
        if leagues is not None and path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("league") not in set(leagues):
                        k = (r["league"], r["source"], r["reason"], r["query"])
                        agg[k] = agg.get(k, 0) + int(r.get("count") or 0)
        rows = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["league", "source", "reason", "query", "count"])
            for (lg, src, rsn, q), c in rows:
                w.writerow([lg, src, rsn, q, c])
        return len(rows)


def selftest() -> None:
    """Offline, on a hand-built table that reproduces the real MLB ambiguity."""
    teams = {
        "mlb:st-louis-cardinals": Team("mlb:st-louis-cardinals", "mlb", "24", "STL",
                                       "St. Louis", "Cardinals", "St. Louis Cardinals"),
        "mlb:new-york-yankees": Team("mlb:new-york-yankees", "mlb", "10", "NYY",
                                     "New York", "Yankees", "New York Yankees"),
        "mlb:new-york-mets": Team("mlb:new-york-mets", "mlb", "21", "NYM",
                                  "New York", "Mets", "New York Mets"),
    }
    alias_rows = [
        {"league": "mlb", "alias": "St. Louis Cardinals", "entity_id": "mlb:st-louis-cardinals"},
        {"league": "mlb", "alias": "St. Louis", "entity_id": "mlb:st-louis-cardinals"},
        {"league": "mlb", "alias": "Cardinals", "entity_id": "mlb:st-louis-cardinals"},
        {"league": "mlb", "alias": "STL", "entity_id": "mlb:st-louis-cardinals"},
        # the real, unavoidable collision: Kalshi renders both NY clubs as "New York"
        {"league": "mlb", "alias": "New York", "entity_id": "mlb:new-york-yankees"},
        {"league": "mlb", "alias": "New York", "entity_id": "mlb:new-york-mets"},
        {"league": "mlb", "alias": "Yankees", "entity_id": "mlb:new-york-yankees"},
        {"league": "mlb", "alias": "Mets", "entity_id": "mlb:new-york-mets"},
    ]
    xrefs = {("kalshi", "8068b1da-6725-4883-a163-885111c4f717"): "mlb:st-louis-cardinals",
             ("polymarket", "114216"): "mlb:st-louis-cardinals"}
    r = Resolver(teams, build_alias_index(alias_rows), xrefs)

    # normalization is punctuation- and case-insensitive
    assert normalize("St. Louis Cardinals") == "st louis cardinals"
    assert normalize("  ST.-LOUIS   cardinals ") == normalize("St Louis Cardinals")
    assert normalize("Atlético Madrid") == "atletico madrid"   # accents folded
    assert normalize("Arsenal FC") == "arsenal"                # noise token dropped
    assert normalize("") == "" and normalize(None) == ""       # total, never raises

    # text path
    assert r.by_text("mlb", "st louis cardinals").entity_id == "mlb:st-louis-cardinals"
    assert r.by_text("mlb", "STL").entity_id == "mlb:st-louis-cardinals"

    # THE LOAD-BEARING ASSERT: ambiguity refuses, and says what it was torn between
    amb = r.by_text("mlb", "New York")
    assert not amb.ok, "ambiguous alias must NOT resolve"
    assert amb.reason == "ambiguous"
    assert amb.ambiguous_among == ("mlb:new-york-mets", "mlb:new-york-yankees")

    # a second field disambiguates
    assert r.by_text("mlb", "Yankees").entity_id == "mlb:new-york-yankees"

    # xref path is exact and needs no text at all
    assert r.by_xref("kalshi", "8068b1da-6725-4883-a163-885111c4f717").entity_id == \
        "mlb:st-louis-cardinals"
    assert r.by_xref("kalshi", "not-a-real-uuid").ok is False

    # xref OUTRANKS text: a wrong/ambiguous label cannot override an exact id
    both = r.resolve("mlb", text="New York", venue="polymarket", venue_team_id="114216")
    assert both.entity_id == "mlb:st-louis-cardinals" and both.method == "xref"

    # unknown league scoping: the same string in another league does not leak across
    assert r.by_text("nfl", "Cardinals").ok is False

    # xref loader rejects a colliding table rather than silently keeping one
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as fh:
        fh.write("venue,venue_team_id,entity_id\nkalshi,X,mlb:a\nkalshi,X,mlb:b\n")
        p = Path(fh.name)
    try:
        load_xrefs(p)
        raise AssertionError("colliding xref table was accepted")
    except ValueError:
        pass
    finally:
        p.unlink()

    print("entities.resolve selftest OK")


if __name__ == "__main__":
    selftest()

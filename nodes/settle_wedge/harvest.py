#!/usr/bin/env python3
"""A venue's rules text -> a versioned, auditable RulesRecord. PURE.

Two hashes, deliberately:
  rules_hash     -- of the text exactly as the venue served it. Changes for every game (the teams
                    and the date are in the sentence). The audit trail: what did we read, when.
    template_hash  -- of the text with participant/event metadata stripped and later calendar
                    deadlines preserved as day offsets plus their clock/timezone. Kalshi
                    and Polymarket both generate game rules from a per-league template, so one
                    template covers a league-season; this is what the reviewed policy table is
                    keyed on. A venue editing its template changes the hash, the lookup misses,
                    and every cover in that league blocks until a human reads the new text.

Measured 2026-09-02: Kalshi KXMLBGAME rules_secondary is identical across games once the teams
and the date are removed; Polymarket's MLB description likewise. NFL and NHL differ from MLB and
from each other (Kalshi NFL names the tie and a 48-hour clause; Polymarket NHL names the shootout).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Sequence

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
           "sep", "sept", "oct", "nov", "dec")
_TZ = ("edt", "est", "et", "pdt", "pst", "pt", "cdt", "cst", "ct", "mdt", "mst", "mt", "utc", "gmt")
# Remove calendar/clock literals before punctuation, never arbitrary digit-bearing tokens.
# Dropping every number made e.g. 7-day and 14-day settlement windows the same template.
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"
_DATE = re.compile(
    rf"\b{_MONTH}\.?\s+(?:3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?"
    r"(?:,?\s+(?:19|20)\d{2})?\b"
    r"|\b(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])\b"
    r"|\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b")
_ZONE = "(?:" + "|".join(sorted(_TZ, key=len, reverse=True)) + ")"
_TIME = re.compile(
    rf"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?"
    rf"(?:\s*[ap]m(?:\s+{_ZONE})?|\s+{_ZONE})\b")
_TICKER = re.compile(r"\bkx[a-z0-9]+(?:-[a-z0-9]+)+\b")
# Keep decimal points and numeric ratios: $0.50, 0.05 and 2:1 are substantive.
_STRIP = re.compile(r"[\"'“”‘’,;()\[\]]|(?<!\d)[.:]|[.:](?!\d)")
_MONTH_NUMBER = {name: i for i, name in enumerate(_MONTHS[:12], 1)}
_MONTH_NUMBER.update({name[:3]: i for i, name in enumerate(_MONTHS[:12], 1)})
_MONTH_NUMBER["sept"] = 9


def _calendar_date(value: str) -> tuple[date | None, bool]:
    """Return a validated date and whether its year was explicit. Never guess a year."""
    named = re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", value)
    try:
        if named:
            month, day, year = named.groups()
            # A leap-year placeholder validates the month/day only; it is never used for offsets.
            return date(int(year or 2000), _MONTH_NUMBER[month], int(day)), year is not None
        parts = [int(p) for p in re.split("[-/]", value)]
        year, month, day = parts if len(value.split("-")[0].split("/")[0]) == 4 else (parts[2], parts[0], parts[1])
        return date(year, month, day), True
    except (ValueError, KeyError, IndexError):
        return None, False


def _normalise_calendar(text: str) -> str:
    """Keep later dates as offsets from the first date, with their deadline clocks intact.

    Only a validated first date (and exact repetitions of it) is event metadata. A lone
    yearless date is also metadata, but multiple dates require explicit years to compare.
    Ambiguous/invalid dates and clocks stay literal so they cannot acquire a reviewed hash.
    """
    matches = list(_DATE.finditer(text))
    if not matches:
        return text
    anchor, anchor_has_year = _calendar_date(matches[0].group())
    replacements = []
    for match in matches:
        parsed, has_year = _calendar_date(match.group())
        if parsed is None or anchor is None:
            continue
        if anchor_has_year and has_year:
            offset = (parsed - anchor).days
            if offset:
                replacements.append((match.start(), match.end(), f" calendar_offset_{offset:+d}d "))
                continue  # This date's clock/timezone is settlement content, not event metadata.
        elif not (len(matches) == 1 and not has_year):
            continue
        replacements.append((match.start(), match.end(), " "))
        # Strip a clock only when attached to the first event date or a same-date repetition.
        gap = re.match(r"[\s,]*(?:at\s+)?", text[match.end():])
        clock = _TIME.match(text, match.end() + gap.end())
        if clock and not (re.search(r"[ap]m", clock.group()) and
                          not 1 <= int(clock.group().split(":", 1)[0]) <= 12):
            replacements.append((clock.start(), clock.end(), " "))
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text


@dataclass(frozen=True)
class RulesRecord:
    venue: str
    market_id: str
    source_type: str           # "api_field" | "harvested_pdf" | "venue_default"
    source_url: str | None
    provenance: str            # what kind of thing we read: "api_field" today
    retrieved_at: float
    text: str
    rules_hash: str
    template_text: str
    template_hash: str
    settlement_sources: tuple[str, ...] = ()


#: Trailing words of a participant's name that are also ordinary words of a rules text.
_GENERIC_TAILS = frozenset({"college", "state", "university", "city", "united", "town", "county", "football",
                            "tennis", "fc", "athletic", "club", "team"})


def normalise_template(text: str, participants: Sequence[str], scrub: Sequence[str] = ()) -> str:
    """Strip recognized event metadata, retaining numbers in settlement rules.
    Unrecognized formatting survives and fails closed at the reviewed-template lookup.
    Longest participant names first, so
    'Los Angeles D' goes before 'Los Angeles'. `scrub` are a league's own regexes for what else
    varies (a tennis text names the tournament and the round), applied before anything else."""
    for pat in scrub:
        text = re.sub(pat, " ", text)
    s = text.lower()
    names = {p.lower() for p in participants if p}
    for n in list(names):
        words = n.split()
        # A venue may name a participant by a trailing part of the name alone (Polymarket NFL
        # "Patriots"; a tennis text "Wu vs Alcaraz", "Van De Zandschulp", "Bouzas Maneiro"): every
        # suffix of the name of two or more characters. One-letter tails ("D" in "Los Angeles D")
        # are left alone.
        for i in range(1, len(words)):
            tail = " ".join(words[i:])
            # A one-word tail that is a generic word of the rules text itself is not a name:
            # "Boston College" stripped "college" out of "college football game" and the text hashed
            # to nothing the policy held (2026-09-05, BC @ CIN blocked at TEMPLATE_UNKNOWN).
            if len(tail) >= 2 and not (i == len(words) - 1 and tail in _GENERIC_TAILS):
                names.add(tail)
        # ... and by the name without its nickname (Polymarket college football: "Morehead State"
        # for "Morehead State Eagles"; "Kent State" for "Kent State Golden Flashes", a two-word
        # mascot -- 2026-09-05, one cfb game blocked at TEMPLATE_UNKNOWN for a text identical to
        # V1): every head of two or more words. Short heads ("St.") are left alone.
        for i in range(len(words) - 1, 1, -1):
            head = " ".join(words[:i])
            if len(head) > 3:
                names.add(head)
        head = n.rsplit(" ", 1)[0] if " " in n else ""
        if len(head) > 3:
            names.add(head)
    # Whole words only: "Bu" must not turn "but" into "t" (measured 2026-09-03, Yunchaokete Bu).
    for name in sorted(names, key=len, reverse=True):
        s = re.sub(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", " ", s)
    s = _normalise_calendar(s)
    s = _TICKER.sub(" ", s)
    return " ".join(_STRIP.sub(" ", s).split())


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def harvest_kalshi(market: dict, *, participants: Sequence[str], retrieved_at: float,
                   series: dict | None = None, scrub: Sequence[str] = ()) -> RulesRecord:
    text = "\n".join(x for x in (market.get("rules_primary"), market.get("rules_secondary")) if x)
    s = (series or {}).get("series", series) or {}
    sources = tuple(str(x.get("name")) for x in (s.get("settlement_sources") or []) if x.get("name"))
    tmpl = normalise_template(text, participants, scrub)
    return RulesRecord("kalshi", str(market.get("ticker") or ""), "api_field",
                       s.get("contract_url") or None, "api_field", retrieved_at, text, _sha(text),
                       tmpl, _sha(tmpl), sources)


def harvest_polymarket(market: dict, *, participants: Sequence[str], retrieved_at: float,
                       scrub: Sequence[str] = ()) -> RulesRecord:
    text = str(market.get("description") or "")
    src = market.get("resolutionSource") or None
    tmpl = normalise_template(text, participants, scrub)
    return RulesRecord("polymarket", str(market.get("slug") or market.get("id") or ""), "api_field",
                       src, "api_field", retrieved_at, text, _sha(text), tmpl, _sha(tmpl),
                       (src,) if src else ())

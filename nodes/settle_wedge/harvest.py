#!/usr/bin/env python3
"""A venue's rules text -> a versioned, auditable RulesRecord. PURE.

Two hashes, deliberately:
  rules_hash     -- of the text exactly as the venue served it. Changes for every game (the teams
                    and the date are in the sentence). The audit trail: what did we read, when.
  template_hash  -- of the text with the participants, dates, times and tickers stripped. Kalshi
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
from typing import Sequence

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
           "sep", "sept", "oct", "nov", "dec")
_TZ = ("edt", "est", "et", "pdt", "pst", "pt", "cdt", "cst", "ct", "mdt", "mst", "mt", "utc", "gmt")
_STRIP = re.compile(r"[\"'“”‘’.,:;()\[\]]")


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


def normalise_template(text: str, participants: Sequence[str]) -> str:
    """Strip everything that varies per game. Longest participant names first, so
    'Los Angeles D' goes before 'Los Angeles'."""
    s = text.lower()
    names = {p.lower() for p in participants if p}
    # A venue may name a team by its nickname alone (Polymarket NFL: "Patriots"); strip the last
    # word of every multi-word name too. Short tails ("D" in "Los Angeles D") are left alone.
    for n in list(names):
        tail = n.split()[-1] if " " in n else ""
        if len(tail) > 3:
            names.add(tail)
    for name in sorted(names, key=len, reverse=True):
        s = s.replace(name, " ")
    s = _STRIP.sub(" ", s)
    toks = []
    for tok in s.split():
        if tok in _MONTHS or tok in _TZ or tok in ("am", "pm"):
            continue
        if any(ch.isdigit() for ch in tok):
            continue
        toks.append(tok)
    return " ".join(toks)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def harvest_kalshi(market: dict, *, participants: Sequence[str], retrieved_at: float,
                   series: dict | None = None) -> RulesRecord:
    text = "\n".join(x for x in (market.get("rules_primary"), market.get("rules_secondary")) if x)
    s = (series or {}).get("series", series) or {}
    sources = tuple(str(x.get("name")) for x in (s.get("settlement_sources") or []) if x.get("name"))
    tmpl = normalise_template(text, participants)
    return RulesRecord("kalshi", str(market.get("ticker") or ""), "api_field",
                       s.get("contract_url") or None, "api_field", retrieved_at, text, _sha(text),
                       tmpl, _sha(tmpl), sources)


def harvest_polymarket(market: dict, *, participants: Sequence[str], retrieved_at: float) -> RulesRecord:
    text = str(market.get("description") or "")
    src = market.get("resolutionSource") or None
    tmpl = normalise_template(text, participants)
    return RulesRecord("polymarket", str(market.get("slug") or market.get("id") or ""), "api_field",
                       src, "api_field", retrieved_at, text, _sha(text), tmpl, _sha(tmpl),
                       (src,) if src else ())

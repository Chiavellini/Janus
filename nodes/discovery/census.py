#!/usr/bin/env python3
"""The co-listing census: which competitions BOTH venues list as game markets right now, how much
executable money sits at the touch, and how long the contracts live. Descriptive, re-runnable
(ledger L28). It reads no outcome and claims no edge; it ranks where to look next.

Why a census and not a preference: sports were chosen because contract life is short and
arbitrage may appear -- a property of the market, not of the sport. The order in which
competitions get their citation, harvested templates and measured rates should follow measured
co-listed capacity, and this is the measurement.

Both venues enumerate themselves. Kalshi: GET /series?category=Sports, then the open markets of
every game-class series (ticker ending GAME / FIGHT / MATCH). Polymarket: GET /sports is the
venue's own league table (sport code = the slug prefix, `resolution` = the settlement source,
`primaryTagId`), then the open events under each league's tag; a game is an event with a
`moneyline` market carrying `gameStartTime`. The two are joined per event on the calendar date
(+-1 day, the ticker date is venue-local) and on the participants -- an abbreviation equal on
both venues, or a name token shared -- both participants, distinct. That is loose enough to count
and tight enough to rank; the unmatched remainder is reported per competition, never hidden.

Node kind: `source` (fetch) + `pure` (parse, join, rank).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from kernel.fetch import Client
from kernel.redact import brief_error
from nodes.venue_kalshi.books import kalshi_book
from nodes.venue_polymarket.books import PM_CLOB, PM_GAMMA, pm_book

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
GAME_SUFFIXES = ("GAME", "FIGHT", "MATCH")
NOT_GAME_SUFFIXES = ("GAMES", "GAMEDAY", "GAMEDAYGUEST")
NON_TEAM = {"tie", "draw", "no winner"}
#: Tokens too common to identify a club on their own.
STOP = {"united", "city", "real", "club", "athletic", "atletico", "sporting", "state", "university", "the",
        "team", "fc", "sc", "cf", "de", "town", "county", "national", "york", "angeles", "san", "los", "new"}
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_EVENT_TAIL = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})(\d{4})?([A-Z0-9]+)$")


# ── fetch ────────────────────────────────────────────────────────────────────
def kalshi_sports_series(cl: Client) -> list[dict]:
    out, cursor = [], None
    while True:
        p = {"category": "Sports", "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        d = cl.get_json(f"{KALSHI_BASE}/series", params=p, use_cache=False)
        out += d.get("series") or []
        cursor = d.get("cursor")
        if not cursor:
            return out


def kalshi_open_markets(series_ticker: str, cl: Client) -> list[dict]:
    out, cursor = [], None
    while True:
        p = {"series_ticker": series_ticker, "status": "open", "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        d = cl.get_json(f"{KALSHI_BASE}/markets", params=p, use_cache=False)
        out += d.get("markets") or []
        cursor = d.get("cursor")
        if not cursor:
            return out


def pm_sports(cl: Client) -> list[dict]:
    """Polymarket's own league table: sport code, name, settlement source, primary tag."""
    d = cl.get_json(f"{PM_GAMMA}/sports", use_cache=False)
    return list(d) if isinstance(d, list) else []


def pm_events_for_tag(tag_id: int | str, cl: Client, *, page: int = 100, max_pages: int = 30) -> list[dict]:
    out = []
    for i in range(max_pages):
        d = cl.get_json(f"{PM_GAMMA}/events", params={"tag_id": tag_id, "closed": "false", "limit": page,
                                                     "offset": i * page}, use_cache=False)
        if not d:
            break
        out += d
        if len(d) < page:
            break
    return out


def pm_touch(token_id: str, cl: Client, now: float) -> tuple[float | None, float | None]:
    """(bid notional, ask notional) at the touch from the CLOB book, USD."""
    b = pm_book(cl.get_json(f"{PM_CLOB}/book", params={"token_id": token_id}, use_cache=False), now)
    bid = b.best_bid.price * b.best_bid.size if b.best_bid else None
    ask = b.best_ask.price * b.best_ask.size if b.best_ask else None
    return bid, ask


# ── pure: parse ──────────────────────────────────────────────────────────────
def is_game_series(ticker: str) -> bool:
    t = ticker.upper()
    return t.endswith(GAME_SUFFIXES) and not t.endswith(NOT_GAME_SUFFIXES)


def norm_tokens(name: str) -> set[str]:
    toks = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    return {t for t in toks if len(t) >= 4 and t not in STOP}


def parse_kalshi_event(event_ticker: str) -> dict | None:
    """`KXLALIGAGAME-26SEP17MCFVIL` -> {series, date, time, abbrevs_concat}. None if unparseable."""
    if "-" not in event_ticker:
        return None
    series, tail = event_ticker.split("-", 1)
    m = _EVENT_TAIL.match(tail)
    if not m:
        return None
    yy, mon, dd, hhmm, rest = m.groups()
    if mon not in MONTHS:
        return None
    return {"series": series, "date": f"20{yy}-{MONTHS[mon]:02d}-{int(dd):02d}", "time": hhmm, "abbrevs": rest}


@dataclass
class GameEvent:
    venue: str
    competition: str            # Kalshi series ticker / Polymarket sport code
    event_id: str               # event_ticker / event slug
    date: str                   # YYYY-MM-DD as the venue states it
    start_utc: float | None
    participants: list[str]     # names as the venue states them (draw excluded)
    abbrevs: list[str]          # lowercase
    n_markets: int
    two_sided: bool
    touch_bid_usd: float | None
    touch_ask_usd: float | None
    life_h: float | None        # listing -> expected settlement (Kalshi) / game start (Polymarket)
    tokens: list[str] = field(default_factory=list)   # Polymarket YES token per moneyline market


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    s = str(s).replace(" ", "T").replace("+00", "+00:00")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def kalshi_events(series_ticker: str, markets: Iterable[dict]) -> list[GameEvent]:
    by_ev: dict[str, list[dict]] = defaultdict(list)
    for m in markets:
        by_ev[m.get("event_ticker") or ""].append(m)
    out = []
    for ev, ms in by_ev.items():
        p = parse_kalshi_event(ev)
        if p is None:
            continue
        names, abbrevs, bids, asks, lives = [], [], [], [], []
        for m in ms:
            sub = (m.get("yes_sub_title") or "").strip()
            suf = (m.get("ticker") or "").rsplit("-", 1)[-1].lower()
            if sub.lower() in NON_TEAM or suf in NON_TEAM:
                continue
            names.append(sub); abbrevs.append(suf)
            b, bs = _f(m.get("yes_bid_dollars")), _f(m.get("yes_bid_size_fp"))
            a, as_ = _f(m.get("yes_ask_dollars")), _f(m.get("yes_ask_size_fp"))
            bids.append(b * bs if b is not None and bs is not None else None)
            asks.append(a * as_ if a is not None and as_ is not None else None)
            o, x = _ts(m.get("open_time")), _ts(m.get("expected_expiration_time"))
            if o and x:
                lives.append((x - o) / 3600.0)
        two_sided = bool(bids) and all(b is not None and b > 0 for b in bids) and all(a is not None and a > 0 for a in asks)
        exp = [_ts(m.get("expected_expiration_time")) for m in ms]
        out.append(GameEvent("kalshi", series_ticker, ev, p["date"], min((e for e in exp if e), default=None),
                             names, abbrevs, len(ms), two_sided,
                             min((b for b in bids if b is not None), default=None),
                             min((a for a in asks if a is not None), default=None),
                             median(lives) if lives else None))
    return out


def _split_title(title: str) -> list[str]:
    t = re.sub(r"\(.*?\)", "", title or "")
    if ":" in t:
        t = t.split(":", 1)[1]
    parts = re.split(r"\s+vs\.?\s+|\s+v\s+|\s+@\s+", t, flags=re.I)
    return [p.strip() for p in parts if p.strip()][:2]


def pm_events(sport_code: str, events: Iterable[dict]) -> list[GameEvent]:
    out = []
    for ev in events:
        ms = [m for m in ev.get("markets") or [] if m.get("sportsMarketType") == "moneyline" and m.get("gameStartTime")]
        if not ms:
            continue
        slug = ev.get("slug") or ""
        m0 = ms[0]
        import json as _json
        outs = m0.get("outcomes")
        if isinstance(outs, str):
            outs = _json.loads(outs)
        names = [o for o in (outs or []) if str(o).lower() not in ("yes", "no")] or _split_title(ev.get("title") or "")
        parts = slug.split("-")
        abbrevs = [x for x in parts[1:] if not x.isdigit()][:2] if len(parts) >= 4 else []
        tokens = []
        for m in ms:
            toks = m.get("clobTokenIds")
            if isinstance(toks, str):
                toks = _json.loads(toks)
            if toks:
                tokens.append(str(toks[0]))
        start = _ts(m0.get("gameStartTime"))
        created = _ts(m0.get("createdAt") or ev.get("createdAt"))
        two_sided = all(_f(m.get("bestBid")) and _f(m.get("bestAsk")) for m in ms)
        out.append(GameEvent("polymarket", sport_code, slug, datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d") if start else "",
                             start, names, [a.lower() for a in abbrevs], len(ms), two_sided, None, None,
                             (start - created) / 3600.0 if start and created else None, tokens))
    return out


# ── pure: join ───────────────────────────────────────────────────────────────
def _day(d: str) -> datetime | None:
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        return None


def participant_match(k_name: str, k_abbr: str, p_name: str, p_abbr: str) -> bool:
    if k_abbr and p_abbr and k_abbr == p_abbr:
        return True
    return bool(norm_tokens(k_name) & norm_tokens(p_name))


def events_match(k: GameEvent, p: GameEvent) -> bool:
    dk, dp = _day(k.date), _day(p.date)
    if dk is None or dp is None or abs((dk - dp).days) > 1:
        return False
    if len(k.participants) < 2 or len(p.participants) < 2:
        return False
    kn, ka = k.participants[:2], (k.abbrevs + ["", ""])[:2]
    pn, pa = p.participants[:2], (p.abbrevs + ["", ""])[:2]
    straight = participant_match(kn[0], ka[0], pn[0], pa[0]) and participant_match(kn[1], ka[1], pn[1], pa[1])
    crossed = participant_match(kn[0], ka[0], pn[1], pa[1]) and participant_match(kn[1], ka[1], pn[0], pa[0])
    return straight or crossed


def join(kalshi: list[GameEvent], pm: list[GameEvent]) -> list[tuple[GameEvent, GameEvent]]:
    """Every Kalshi event paired with at most one Polymarket event, and vice versa; first match wins
    in date order. Returns the pairs."""
    used: set[str] = set()
    pairs = []
    by_date: dict[str, list[GameEvent]] = defaultdict(list)
    for p in pm:
        by_date[p.date].append(p)
    for k in sorted(kalshi, key=lambda e: (e.date, e.event_id)):
        dk = _day(k.date)
        if dk is None:
            continue
        cands = [p for off in (-1, 0, 1) for p in by_date.get((dk + timedelta(days=off)).strftime("%Y-%m-%d"), [])]
        for p in cands:
            if p.event_id in used:
                continue
            if events_match(k, p):
                used.add(p.event_id)
                pairs.append((k, p))
                break
    return pairs


# ── pure: rank ───────────────────────────────────────────────────────────────
def in_window(e: GameEvent, now: float, *, back_h: float = 3.0, ahead_h: float = 48.0) -> bool:
    if e.start_utc is None:
        return False
    return -back_h * 3600 <= e.start_utc - now <= ahead_h * 3600


def summarize(kalshi: list[GameEvent], pm: list[GameEvent], pairs: list[tuple[GameEvent, GameEvent]],
              pm_touch_usd: dict[str, tuple[float | None, float | None]], now: float) -> dict:
    """Per (Kalshi series, PM sport) competition: counts, co-listing, touch money, contract life,
    and the score = co-listed capacity / median contract life."""
    kw = [e for e in kalshi if in_window(e, now)]
    pw = [e for e in pm if in_window(e, now)]
    kw_ids, pw_ids = {e.event_id for e in kw}, {e.event_id for e in pw}
    comp: dict[tuple[str, str], dict] = {}
    mapping = Counter((k.competition, p.competition) for k, p in pairs)
    for k, p in pairs:
        if k.event_id not in kw_ids and p.event_id not in pw_ids:
            continue
        c = comp.setdefault((k.competition, p.competition), {
            "kalshi_series": k.competition, "pm_sport": p.competition, "co_listed_48h": 0, "two_sided_both": 0,
            "kalshi_touch_usd": [], "pm_touch_usd": [], "life_h_kalshi": [], "life_h_pm": [], "capacity_usd": 0.0,
            "examples": []})
        c["co_listed_48h"] += 1
        pb, pa = pm_touch_usd.get(p.event_id, (None, None))
        pm_two = pb is not None and pa is not None and pb > 0 and pa > 0
        if k.two_sided and (pm_two or (not pm_touch_usd and p.two_sided)):
            c["two_sided_both"] += 1
        k_t = min(x for x in (k.touch_bid_usd, k.touch_ask_usd) if x is not None) if (k.touch_bid_usd is not None and k.touch_ask_usd is not None) else None
        p_t = min(pb, pa) if pm_two else None
        if k_t is not None:
            c["kalshi_touch_usd"].append(k_t)
        if p_t is not None:
            c["pm_touch_usd"].append(p_t)
        if k.life_h is not None:
            c["life_h_kalshi"].append(k.life_h)
        if p.life_h is not None:
            c["life_h_pm"].append(p.life_h)
        if len(c["examples"]) < 3:
            c["examples"].append([k.event_id, p.event_id])
    rows = []
    for c in comp.values():
        k_med = median(c["kalshi_touch_usd"]) if c["kalshi_touch_usd"] else None
        p_med = median(c["pm_touch_usd"]) if c["pm_touch_usd"] else None
        # capacity: per co-listed event the binding touch, using the competition medians where a
        # side was not sampled; None when neither side has a number.
        per_event = min(x for x in (k_med, p_med) if x is not None) if (k_med is not None or p_med is not None) else None
        cap = per_event * c["co_listed_48h"] if per_event is not None else None
        life = median(c["life_h_kalshi"] + c["life_h_pm"]) if (c["life_h_kalshi"] or c["life_h_pm"]) else None
        rows.append({**{k: v for k, v in c.items() if not k.endswith("_usd") and not k.startswith("life_h")},
                     "kalshi_touch_usd_median": k_med, "kalshi_touch_n": len(c["kalshi_touch_usd"]),
                     "pm_touch_usd_median": p_med, "pm_touch_n": len(c["pm_touch_usd"]),
                     "life_h_median": life, "capacity_usd": cap,
                     "score": (cap / life) if (cap is not None and life) else None})
    rows.sort(key=lambda r: (-(r["score"] or 0.0), -r["co_listed_48h"]))
    k_by_series = Counter(e.competition for e in kw)
    p_by_sport = Counter(e.competition for e in pw)
    matched_k = {k.event_id for k, _ in pairs}
    matched_p = {p.event_id for _, p in pairs}
    unmatched_k = Counter(e.competition for e in kw if e.event_id not in matched_k)
    unmatched_p = Counter(e.competition for e in pw if e.event_id not in matched_p)

    def brief(e: GameEvent) -> dict:
        return {"event_id": e.event_id, "competition": e.competition, "date": e.date,
                "start_utc": e.start_utc, "participants": list(e.participants)}
    # The events behind the counts (2026-09-07): ops/coverage_report.py joins the co-listed pairs
    # against the lane's events table, which is how "both venues list it, the lane did not pair
    # it" becomes a row and an alarm instead of a number.
    co_listed_pairs = [{"kalshi_event": k.event_id, "pm_event": p.event_id, "kalshi_series": k.competition,
                        "pm_sport": p.competition, "date": k.date, "start_utc": k.start_utc if k.start_utc is not None else p.start_utc,
                        "participants": list(k.participants)}
                       for k, p in pairs if k.event_id in kw_ids or p.event_id in pw_ids]
    return {"competitions": rows, "mapping": [[k, p, n] for (k, p), n in mapping.most_common()],
            "kalshi_events_48h": dict(k_by_series), "pm_events_48h": dict(p_by_sport),
            "unmatched_kalshi_48h": dict(unmatched_k), "unmatched_pm_48h": dict(unmatched_p),
            "co_listed_pairs_48h": co_listed_pairs,
            "unmatched_kalshi_events_48h": [brief(e) for e in kw if e.event_id not in matched_k],
            "unmatched_pm_events_48h": [brief(e) for e in pw if e.event_id not in matched_p]}


# ── the run ──────────────────────────────────────────────────────────────────
def run_census(cl_k: Client, cl_p: Client, *, now: float | None = None, pm_book_budget: int = 150,
               log=print) -> dict:
    """One census: enumerate both venues, join, sample Polymarket books for co-listed events within
    the window (bounded by `pm_book_budget`, spread across competitions), summarize."""
    t = now or datetime.now(timezone.utc).timestamp()
    errors: dict[str, str] = {}
    series = kalshi_sports_series(cl_k)
    game_series = [s for s in series if is_game_series(s.get("ticker", ""))]
    kalshi: list[GameEvent] = []
    series_meta = {}
    for s in game_series:
        tk = s["ticker"]
        try:
            ms = kalshi_open_markets(tk, cl_k)
        except Exception as exc:  # noqa: BLE001 -- one series must not stop the census
            errors[f"kalshi:{tk}"] = brief_error(exc)
            continue
        if ms:
            series_meta[tk] = {"title": s.get("title"), "fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier"),
                               "settlement_sources": [x.get("name") for x in (s.get("settlement_sources") or []) if isinstance(x, dict)],
                               "open_markets": len(ms)}
            kalshi += kalshi_events(tk, ms)
    log(f"[kalshi] {len(series)} sports series, {len(game_series)} game-class, {len(series_meta)} with open markets, {len(kalshi)} events")
    sports = pm_sports(cl_p)
    pm: list[GameEvent] = []
    sport_meta = {}
    for sp in sports:
        code, tag = sp.get("sport"), sp.get("primaryTagId")
        if not code or not tag:
            continue
        try:
            evs = pm_events_for_tag(tag, cl_p)
        except Exception as exc:  # noqa: BLE001
            errors[f"polymarket:{code}"] = brief_error(exc)
            continue
        got = pm_events(str(code), evs)
        if got:
            sport_meta[str(code)] = {"name": sp.get("name"), "resolution": sp.get("resolution"), "tag_id": tag,
                                     "open_events": len(evs), "game_events": len(got)}
            pm += got
    log(f"[polymarket] {len(sports)} leagues in /sports, {len(sport_meta)} with game events, {len(pm)} game events")
    pairs = join(kalshi, pm)
    log(f"[join] {len(pairs)} co-listed events")
    # Polymarket books for co-listed events in the window, round-robin over competitions.
    touch: dict[str, tuple[float | None, float | None]] = {}
    queues: dict[str, list[GameEvent]] = defaultdict(list)
    for k, p in pairs:
        if in_window(k, t) or in_window(p, t):
            queues[p.competition].append(p)
    budget = pm_book_budget
    while budget > 0 and any(queues.values()):
        for comp_key in list(queues):
            if not queues[comp_key]:
                continue
            p = queues[comp_key].pop(0)
            if not p.tokens:
                continue
            try:
                bids, asks = [], []
                for tok in p.tokens:
                    b, a = pm_touch(tok, cl_p, t)
                    bids.append(b); asks.append(a)
                    budget -= 1
                touch[p.event_id] = (min((b for b in bids if b is not None), default=None) if all(b is not None for b in bids) else None,
                                     min((a for a in asks if a is not None), default=None) if all(a is not None for a in asks) else None)
            except Exception as exc:  # noqa: BLE001
                errors[f"pm_book:{p.event_id}"] = brief_error(exc)
            if budget <= 0:
                break
    summary = summarize(kalshi, pm, pairs, touch, t)
    return {"run_utc": datetime.fromtimestamp(t, timezone.utc).isoformat(), "window_h": [3.0, 48.0],
            "kalshi": {"sports_series": len(series), "game_class_series": len(game_series), "series": series_meta,
                       "events_total": len(kalshi)},
            "polymarket": {"leagues": len(sports), "sports": sport_meta, "game_events_total": len(pm),
                           "books_sampled": len(touch)},
            "pairs_total": len(pairs), **summary, "errors": errors}

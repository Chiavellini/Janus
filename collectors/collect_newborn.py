#!/usr/bin/env python3
"""L24 — forward capture of NEWBORN Kalshi/Polymarket markets and their books.

    python3 collectors/collect_newborn.py --self-test
    python3 collectors/collect_newborn.py --once
    python3 collectors/collect_newborn.py                   # loop at the registered cadences

Spec: research/exec/2026-08-20_newborn-capture/spec.yaml (immutable) · Ledger L24.

CAPTURE ONLY. This writes rows; it draws no conclusion about whether a tradeable gap exists. The
analysis is deliberately a SEPARATE ledger row: the question "does an executable, fee-surviving gap
appear at birth" is close in kind to L12 and to R3, it costs the project's first numbered test look,
and that decision belongs to the operator rather than arriving as a side effect of a collector. R3's
at-open mechanism is additionally unsettled with Kilos (its registered row 20, forward clock from
2026-07-21), which is a second reason nothing here reads an outcome.

WHY NEWBORNS. Every previous cross-venue screen sampled MATURE markets, and measured on the
12,684-market `kalshi_tape.jsonl`, the median Kalshi market goes 2.0 h before its first trade
(p75 7.2 h; 63.6% still unpriced at t+1h). A snapshot screen is structurally incapable of seeing a
dislocation that lives in a market's first hours, which is a cleaner explanation of phase 1's null
than venue efficiency.

BOOKS, NOT TAPES. The tape measurement above shows the absence of TRADES. Absence of a print is not
absence of an executable quote -- a maker may be quoting into silence. That distinction is the whole
question, so this collector records the ORDER BOOK on both venues and never infers a price from a
trade.

TWO LANES, because the window's width differs by four orders of magnitude:
  * discovery (slow) -- find markets born since the last pass
  * follow (fast)    -- poll the books of markets still inside their newborn window
AGENTS.md records the fast end measured on KXBTC15M: the spread collapses 24c -> 2c by +5 s. This
row deliberately does NOT chase that; it is R3's mechanism. Here the target is the hours-wide window
in illiquid non-sports markets, which nothing has ever examined.

Every scheduled slot writes exactly one cycle row -- ok or reason-coded. A missing observation is
always an explicit row, never an absence.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import sqlite3
import sys
import urllib.parse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402

SPEC_REF = "research/exec/2026-08-20_newborn-capture/spec.yaml"
VERSION = "newborn-capture/0.1.0"

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

DB_PATH = Path("/Volumes/Kilos/janus/newborn/forward.sqlite")
DISCOVERY_PERIOD_S = 900.0     # 15 min -- ample against a window measured in hours
FOLLOW_PERIOD_S = 60.0         # the tick; which markets are polled depends on their age
SWEEP_PERIOD_S = 300.0         # markets past the young tier are polled on this coarser grid
YOUNG_S = 1800.0               # first 30 min: polled every tick
FOLLOW_WINDOW_S = 6 * 3600.0   # a market is "newborn" for its first 6 h
DISK_FLOOR_BYTES = 2 * 1024**3
BOOK_DEPTH = 10
CLIENT_RATE = 4.0

#: TWO-TIER SAMPLING. The measurement this row exists to produce is the PROBABILITY SWEEP -- how the
#: price moves as capital arrives -- so the sampling grid has to resolve the sweep, not merely bracket
#: it. Measured in the 2026-08-20 dry run, one PM market's ask went 0.99 -> 0.99 -> 0.99 -> 0.20 ->
#: 0.05 between age 148 s and 681 s: the whole adjustment happened inside ~4.5 minutes, which a flat
#: 5-minute grid samples about three times. Markets under YOUNG_S are therefore polled every tick.
#: The cap is derived from the slot it must fit inside, at the client's sustained rate and a 0.4 duty
#: cycle, so it can never queue more requests than the slot has room for.
def slot_cap(period_s: float) -> int:
    return max(1, int(period_s * CLIENT_RATE * 0.4))


#: Batch sizes for the money-axis lookups. Both venues accept a multi-id query, so the money axis
#: costs ~n/BATCH requests per slot rather than n.
KALSHI_MONEY_BATCH = 50
PM_MONEY_BATCH = 50

#: Every non-ok cycle carries one of these. An unregistered reason raises rather than being stored,
#: so the missingness characterisation this row exists to produce cannot quietly rot.
GAP_REASONS = {"KALSHI_ERROR", "KALSHI_EMPTY", "PM_ERROR", "PM_EMPTY", "NO_COUNTERPART",
               "VERIFY_REJECTED", "BOOK_ERROR", "DISK_FLOOR", "MARKET_CLOSED", "UNKNOWN"}

#: Prices and identifiers of PUBLIC markets only. Nothing account-scoped is ever written; asserted at
#: write time rather than trusted to review.
#:
#: This deliberately matches identifier SHAPES rather than the bare English words used by
#: collect_wti_ladder.py, whose denylist never sees free text. Measured on the live Kalshi book:
#: a bare `secret` rejected 83 legitimate markets -- every "next Secretary General of NATO" contract
#: -- and `session` would reject any market about a legislative session. A denylist that fires on
#: ordinary market titles gets loosened in a hurry by whoever hits it, so it is written to be
#: precise now rather than permissive later.
FORBIDDEN_TEXT = re.compile(
    r"acctId|accountId|userId|\bU\d{6,}\b"                    # account handles (incl. IBKR UXXXXXXX)
    r"|api[_-]?key|client[_-]?secret|secret[_-]?key|private[_-]?key|passphrase"
    r"|session[_-]?(id|token|key)|set-cookie|cookie\s*:"
    r"|bearer\s+[A-Za-z0-9._-]{12,}|eyJ[A-Za-z0-9._-]{20,}",  # bearer tokens / JWTs
    re.IGNORECASE)

DDL = """
CREATE TABLE IF NOT EXISTS cycles(slot_ts REAL, lane TEXT, recv_ts REAL, ok INTEGER, reason TEXT,
  n_seen INTEGER, n_new INTEGER, n_followed INTEGER, spec_ref TEXT, version TEXT,
  PRIMARY KEY (slot_ts, lane));
CREATE TABLE IF NOT EXISTS births(venue TEXT, market_id TEXT, event_id TEXT, title TEXT,
  created_ts REAL, detected_ts REAL, detection_lag_s REAL, close_ts REAL, category TEXT,
  first_seen_slot REAL, seeded INTEGER DEFAULT 0, book_key TEXT,
  PRIMARY KEY (venue, market_id));
CREATE INDEX IF NOT EXISTS births_detected ON births(detected_ts);
CREATE TABLE IF NOT EXISTS books(slot_ts REAL, venue TEXT, market_id TEXT, recv_ts REAL,
  age_s REAL, best_bid REAL, best_ask REAL, bid_size REAL, ask_size REAL, spread REAL,
  n_bid_levels INTEGER, n_ask_levels INTEGER, two_sided INTEGER, raw_levels TEXT, reason TEXT,
  -- THE MONEY AXIS. The sweep is price-versus-capital-arrived, not price-versus-clock, so every
  -- book observation carries how much money had shown up by then. Stored CUMULATIVE and raw;
  -- deltas are derived in analysis, never trusted from the collector's memory.
  bid_depth REAL, ask_depth REAL, volume REAL, volume_24h REAL, open_interest REAL, liquidity REAL,
  -- event proximity, so an age effect can be separated from a time-to-resolution effect
  days_to_close REAL);
CREATE INDEX IF NOT EXISTS books_slot ON books(slot_ts);
CREATE INDEX IF NOT EXISTS books_market ON books(venue, market_id);
CREATE TABLE IF NOT EXISTS pairs(kalshi_ticker TEXT, pm_condition_id TEXT, linked_ts REAL,
  verify_reason TEXT, jaccard REAL, PRIMARY KEY (kalshi_ticker, pm_condition_id));
CREATE TABLE IF NOT EXISTS health(ts REAL, component TEXT, status TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path: Path, enforce_volume: bool = True):
        p = Path(path)
        if enforce_volume and not str(p.resolve()).startswith("/Volumes/"):
            raise ValueError("L24 data must live on the data volume, never the root disk")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(p))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(DDL)

    @staticmethod
    def _check(*vals):
        for v in vals:
            if isinstance(v, str) and FORBIDDEN_TEXT.search(v):
                raise ValueError("refusing to persist text matching the privacy denylist")

    def cycle_row(self, **kw):
        if kw.get("reason") and kw["reason"] not in GAP_REASONS:
            raise ValueError(f"unregistered gap reason {kw['reason']}")
        self._check(kw.get("reason"))
        self.con.execute("INSERT OR REPLACE INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (kw["slot_ts"], kw["lane"], kw.get("recv_ts"), int(kw["ok"]),
                          kw.get("reason"), kw.get("n_seen", 0), kw.get("n_new", 0),
                          kw.get("n_followed", 0), SPEC_REF, VERSION))

    def birth(self, **kw):
        self._check(kw.get("title"), kw.get("market_id"))
        self.con.execute(
            "INSERT OR IGNORE INTO births VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (kw["venue"], kw["market_id"], kw.get("event_id"), (kw.get("title") or "")[:300],
             kw.get("created_ts"), kw["detected_ts"], kw.get("detection_lag_s"),
             kw.get("close_ts"), kw.get("category"), kw.get("first_seen_slot"),
             int(bool(kw.get("seeded"))), kw.get("book_key")))

    def book(self, **kw):
        self._check(kw.get("market_id"), kw.get("reason"))
        if kw.get("reason") and kw["reason"] not in GAP_REASONS:
            raise ValueError(f"unregistered gap reason {kw['reason']}")
        self.con.execute("INSERT INTO books VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (kw["slot_ts"], kw["venue"], kw["market_id"], kw.get("recv_ts"),
                          kw.get("age_s"), kw.get("best_bid"), kw.get("best_ask"),
                          kw.get("bid_size"), kw.get("ask_size"), kw.get("spread"),
                          kw.get("n_bid_levels"), kw.get("n_ask_levels"),
                          int(bool(kw.get("two_sided"))), kw.get("raw_levels"), kw.get("reason"),
                          kw.get("bid_depth"), kw.get("ask_depth"), kw.get("volume"),
                          kw.get("volume_24h"), kw.get("open_interest"), kw.get("liquidity"),
                          kw.get("days_to_close")))

    def pair(self, k, p, reason, jac, ts=None):
        self.con.execute("INSERT OR IGNORE INTO pairs VALUES (?,?,?,?,?)",
                         (k, p, ts or time.time(), reason, jac))

    def health(self, component, status, detail="", ts=None):
        self._check(detail)
        self.con.execute("INSERT INTO health VALUES (?,?,?,?)",
                         (ts or time.time(), component, status, str(detail)[:500]))

    def known_ids(self, venue: str) -> set[str]:
        return {r[0] for r in self.con.execute(
            "SELECT market_id FROM births WHERE venue=?", (venue,))}

    def follow_cohort(self, now: float, window: float = FOLLOW_WINDOW_S,
                      cap: int = None, young_only: bool = True):
        """Markets we WATCHED being born, still inside the newborn window and not yet closed.

        TWO TIERS. `young_only` (the every-tick default) returns markets under YOUNG_S, where the
        probability sweep actually happens. `young_only=False` returns the full newborn window and
        runs on the coarser SWEEP_PERIOD_S grid. The young tier is small by construction, so the
        fine grid costs little; the wide tier is the one that needs the cap.

        `seeded` rows are excluded. On a cold start the first discovery pass sees the entire open
        book -- measured here, 95,811 Kalshi + 4,474 PM markets -- and none of those is an observed
        birth; they are simply the markets that already existed. Treating them as newborns queues a
        100k-request follow cycle and, worse, pollutes the cohort with markets of unknown age.

        Returns (rows, n_truncated). The cap is never silent: a bounded cohort that reported itself
        as complete would read as "we watched everything" when it did not.
        """
        max_age = window if young_only is False else YOUNG_S
        cap = slot_cap(SWEEP_PERIOD_S if young_only is False else FOLLOW_PERIOD_S) \
            if cap is None else cap
        rows = self.con.execute(
            "SELECT venue, market_id, COALESCE(created_ts, detected_ts) AS born, close_ts, "
            "COALESCE(book_key, market_id) FROM births "
            "WHERE seeded=0 AND COALESCE(created_ts, detected_ts) > ? "
            "ORDER BY born DESC", (now - max_age,)).fetchall()
        live = [(v, m, born, close, bk) for v, m, born, close, bk in rows
                if close is None or close > now]
        return live[:cap], max(0, len(live) - cap)

    def flush(self):
        self.con.commit()


def iso_ts(s):
    if not s:
        return None
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def disk_ok(path="/") -> bool:
    return shutil.disk_usage(path).free >= DISK_FLOOR_BYTES


def pm_yes_token(clob_token_ids) -> str | None:
    """The first outcome's CLOB token id. gamma serves this as a JSON-encoded string."""
    v = clob_token_ids
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (TypeError, ValueError):
            return None
    if isinstance(v, (list, tuple)) and v:
        return str(v[0]) or None
    return None


def _depth(levels, size_key):
    """Total resting size across the captured levels -- capital actually committed to the book.

    This is the cheapest reading on the money axis: it comes from the book we already fetched, so
    it costs nothing extra and it is available even on a market with zero traded volume, which is
    precisely the newborn state.
    """
    tot = 0.0
    for lv in levels or []:
        try:
            tot += float(lv[size_key] if isinstance(lv, dict) else lv[size_key])
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    return tot or None


# ── book normalisation ──────────────────────────────────────────────────────────────────────
def norm_kalshi_book(payload: dict) -> dict:
    """Kalshi returns resting interest as `yes_dollars` / `no_dollars` [[price, size], ...].

    A NO bid at price q is economically a YES ask at (1 - q); the book has no explicit ask side.
    Both sides are recorded raw so this derivation can be re-checked later rather than trusted.
    """
    ob = (payload or {}).get("orderbook_fp") or (payload or {}).get("orderbook") or {}
    yes = [lv for lv in (ob.get("yes_dollars") or ob.get("yes") or []) if lv]
    no = [lv for lv in (ob.get("no_dollars") or ob.get("no") or []) if lv]

    def top(levels):
        best = None
        for lv in levels:
            try:
                px, sz = float(lv[0]), float(lv[1])
            except (TypeError, ValueError, IndexError):
                continue
            if best is None or px > best[0]:
                best = (px, sz)
        return best

    yb, nb = top(yes), top(no)
    best_bid = yb[0] if yb else None
    best_ask = (1.0 - nb[0]) if nb else None
    return {"best_bid": best_bid, "best_ask": best_ask,
            "bid_depth": _depth(yes, 1), "ask_depth": _depth(no, 1),
            "bid_size": yb[1] if yb else None, "ask_size": nb[1] if nb else None,
            "spread": (best_ask - best_bid) if (yb and nb) else None,
            "n_bid_levels": len(yes), "n_ask_levels": len(no),
            "two_sided": bool(yb and nb),
            "raw_levels": json.dumps({"yes": yes[:BOOK_DEPTH], "no": no[:BOOK_DEPTH]})}


def norm_pm_book(payload: dict) -> dict:
    bids = (payload or {}).get("bids") or []
    asks = (payload or {}).get("asks") or []

    def top(levels, best_high: bool):
        out = None
        for lv in levels:
            try:
                px, sz = float(lv["price"]), float(lv["size"])
            except (TypeError, ValueError, KeyError):
                continue
            if out is None or (px > out[0] if best_high else px < out[0]):
                out = (px, sz)
        return out

    b, a = top(bids, True), top(asks, False)
    return {"best_bid": b[0] if b else None, "best_ask": a[0] if a else None,
            "bid_depth": _depth(bids, "size"), "ask_depth": _depth(asks, "size"),
            "bid_size": b[1] if b else None, "ask_size": a[1] if a else None,
            "spread": (a[0] - b[0]) if (a and b) else None,
            "n_bid_levels": len(bids), "n_ask_levels": len(asks),
            "two_sided": bool(a and b),
            "raw_levels": json.dumps({"bids": bids[:BOOK_DEPTH], "asks": asks[:BOOK_DEPTH]})}


# ── discovery ───────────────────────────────────────────────────────────────────────────────
def discover_pm(client: Client, known: set[str], *, max_pages: int = 12, limit: int = 100):
    """Newest-first walk, stopping once a page yields nothing unseen.

    gamma 422s past offset ~2100 (see catalog/enumerate_pm.py), but newest-first never needs depth:
    a 15-minute pass only has to reach back 15 minutes.
    """
    found, seen_total = [], 0
    for page in range(max_pages):
        evs = client.get_json(f"{GAMMA}/events", params={
            "order": "createdAt", "ascending": "false", "closed": "false",
            "limit": limit, "offset": page * limit}, use_cache=False)
        if not evs:
            break
        fresh_this_page = 0
        for e in evs:
            created = iso_ts(e.get("createdAt"))
            for m in (e.get("markets") or []):
                cid = m.get("conditionId")
                if not cid:
                    continue
                seen_total += 1
                if cid in known:
                    continue
                fresh_this_page += 1
                found.append({
                    "venue": "polymarket", "market_id": cid, "event_id": e.get("slug"),
                    "title": m.get("question") or e.get("title"),
                    "created_ts": iso_ts(m.get("createdAt")) or created,
                    "close_ts": iso_ts(m.get("endDateIso") or m.get("endDate")),
                    "category": ",".join(sorted(
                        t.get("slug") for t in (e.get("tags") or []) if isinstance(t, dict)
                    ))[:120] or None,
                    # CLOB /book is keyed by TOKEN id, not conditionId. Measured: sending the
                    # conditionId returns HttpError on every request -- 92/92 on the first live
                    # follow cycle. clobTokenIds arrives as a JSON-encoded string; [0] is the
                    # first outcome's (YES) token.
                    "book_key": pm_yes_token(m.get("clobTokenIds")),
                })
        if fresh_this_page == 0:
            break
    return found, seen_total


def discover_kalshi(client: Client, known: set[str], *, max_pages: int = 200):
    """Kalshi has no newest-first ordering, so discovery walks open events.

    `/markets?status=open` cannot be used: catalog/enumerate_kalshi.py:6 measured it returning 40,000
    rows of which only 1,357 had volume, because multivariate parlays swamp cursor pagination. The
    nested-events endpoint is the only one that enumerates the tradeable book.
    """
    found, seen_total = [], 0
    for page in client.paginate_cursor(
            f"{KALSHI}/events", {"status": "open", "limit": 200, "with_nested_markets": "true"},
            "events", max_pages=max_pages, use_cache=False):
        for e in page:
            for m in (e.get("markets") or []):
                t = m.get("ticker")
                if not t:
                    continue
                seen_total += 1
                if t in known:
                    continue
                found.append({
                    "venue": "kalshi", "market_id": t, "event_id": e.get("event_ticker"),
                    "title": m.get("title") or e.get("title"),
                    "created_ts": iso_ts(m.get("created_time") or m.get("open_time")),
                    "close_ts": iso_ts(m.get("close_time")),
                    "category": e.get("category"),
                })
    return found, seen_total


def discovery_cycle(store: Store, client: Client, slot_ts: float, *, now=time.time,
                    pm_fn=discover_pm, kalshi_fn=discover_kalshi, do_kalshi=True) -> dict:
    t0 = now()
    if not disk_ok():
        store.cycle_row(slot_ts=slot_ts, lane="discovery", ok=False, reason="DISK_FLOOR", recv_ts=t0)
        store.health("monitor", "DISK_FLOOR", f"free={shutil.disk_usage('/').free}")
        store.flush()
        return {"ok": False, "reason": "DISK_FLOOR"}

    n_new = n_seen = n_seeded = 0
    reason = None
    for venue, fn in (("polymarket", pm_fn), ("kalshi", kalshi_fn)):
        if venue == "kalshi" and not do_kalshi:
            continue
        known = store.known_ids(venue)
        # COLD START: an empty known-set means we have never looked at this venue, so everything we
        # find already existed. Those are seeds, not observed births, and must not enter the cohort.
        seeding = not known
        try:
            rows, seen = fn(client, known)
        except Exception as e:  # noqa: BLE001
            reason = "PM_ERROR" if venue == "polymarket" else "KALSHI_ERROR"
            store.health(venue, "discovery_error", type(e).__name__)
            continue
        n_seen += seen
        for r in rows:
            det = now()
            created = r.get("created_ts")
            store.birth(detected_ts=det, first_seen_slot=slot_ts, seeded=seeding,
                        detection_lag_s=None if seeding or not created else (det - created),
                        book_key=r.get("book_key") or r.get("market_id"), **{
                            k: v for k, v in r.items() if k not in ("clob_token_ids", "book_key")})
            if seeding:
                n_seeded += 1
            else:
                n_new += 1
        if seeding:
            store.health(venue, "cold_start_seed",
                         f"{len(rows)} pre-existing markets recorded as seeds, not births")

    store.cycle_row(slot_ts=slot_ts, lane="discovery", ok=reason is None, reason=reason,
                    recv_ts=now(), n_seen=n_seen, n_new=n_new)
    store.flush()
    return {"ok": reason is None, "reason": reason, "n_new": n_new, "n_seen": n_seen,
            "n_seeded": n_seeded}


# ── follow ──────────────────────────────────────────────────────────────────────────────────
def fetch_kalshi_book(client: Client, ticker: str) -> dict:
    return client.get_json(f"{KALSHI}/markets/{ticker}/orderbook",
                           params={"depth": BOOK_DEPTH}, use_cache=False)


def fetch_pm_book(client: Client, token_id: str) -> dict:
    return client.get_json(f"{CLOB}/book", params={"token_id": token_id}, use_cache=False)


# ── the money axis ──────────────────────────────────────────────────────────────────────────
def fetch_kalshi_money(client: Client, tickers: list[str], store: "Store" = None) -> dict:
    """{ticker: money fields}. Kalshi accepts a comma-joined `tickers=` list, so this is ~n/50
    requests rather than n. Field names are the `_fp` forms; the bare `volume`/`open_interest`
    keys exist on the payload but come back null."""
    out = {}
    for i in range(0, len(tickers), KALSHI_MONEY_BATCH):
        chunk = tickers[i:i + KALSHI_MONEY_BATCH]
        try:
            d = client.get_json(f"{KALSHI}/markets",
                                params={"tickers": ",".join(chunk), "limit": len(chunk)},
                                use_cache=False)
        except Exception as e:  # noqa: BLE001
            if store is not None:
                store.health("kalshi", "money_error", type(e).__name__)
            continue
        for m in (d or {}).get("markets", []):
            if m.get("ticker"):
                out[m["ticker"]] = {
                    "volume": m.get("volume_fp"), "volume_24h": m.get("volume_24h_fp"),
                    "open_interest": m.get("open_interest_fp"),
                    "liquidity": m.get("liquidity_dollars")}
    return out


def fetch_pm_money(client: Client, condition_ids: list[str], store: "Store" = None) -> dict:
    """gamma wants condition_ids REPEATED, not comma-joined.

    The repeated-key form cannot go through `params=`: `Client.cache_key` calls `.items()` on it and
    an AttributeError is raised before the request is made. So the query string is built here and
    the URL passed whole.
    """
    out = {}
    for i in range(0, len(condition_ids), PM_MONEY_BATCH):
        chunk = condition_ids[i:i + PM_MONEY_BATCH]
        qs = urllib.parse.urlencode([("condition_ids", c) for c in chunk])
        try:
            d = client.get_json(f"{GAMMA}/markets?{qs}", use_cache=False)
        except Exception as e:  # noqa: BLE001
            # never silent: a money-axis outage must be visible, not inferred from null columns
            if store is not None:
                store.health("polymarket", "money_error", type(e).__name__)
            continue
        for m in (d or []):
            if m.get("conditionId"):
                out[m["conditionId"]] = {
                    "volume": m.get("volumeNum"), "volume_24h": m.get("volume24hr"),
                    "open_interest": m.get("openInterest"), "liquidity": m.get("liquidityNum")}
    return out


def follow_cycle(store: Store, client: Client, slot_ts: float, *, now=time.time,
                 k_book=fetch_kalshi_book, p_book=fetch_pm_book,
                 k_money=fetch_kalshi_money, p_money=fetch_pm_money,
                 young_only: bool = True) -> dict:
    t0 = now()
    lane = "follow_young" if young_only else "follow_sweep"
    if not disk_ok():
        store.cycle_row(slot_ts=slot_ts, lane=lane, ok=False, reason="DISK_FLOOR", recv_ts=t0)
        store.health("monitor", "DISK_FLOOR", f"free={shutil.disk_usage('/').free}")
        store.flush()
        return {"ok": False, "reason": "DISK_FLOOR"}

    cohort, truncated = store.follow_cohort(t0, young_only=young_only)
    if truncated:
        store.health(lane, "COHORT_TRUNCATED",
                     f"{truncated} newborn markets not polled this slot")

    # THE MONEY AXIS, fetched once per venue per slot rather than once per market. Failure here is
    # not a gap: the book row is still written, with the money columns null. Losing the price
    # observation because a volume lookup failed would be the worse trade.
    k_ids = [bk for v, _m, _b, _c, bk in cohort if v == "kalshi"]
    p_ids = [m for v, m, _b, _c, _bk in cohort if v == "polymarket"]
    money = {}
    if k_ids:
        money.update(k_money(client, k_ids, store))
    if p_ids:
        money.update(p_money(client, p_ids, store))

    n_ok = n_money = 0
    for venue, mid, born, close, book_key in cohort:
        age = (t0 - born) if born else None
        dtc = ((close - t0) / 86400.0) if close else None
        mon = money.get(book_key if venue == "kalshi" else mid) or {}
        if mon:
            n_money += 1
        # every followed market writes exactly one book row per slot: quoted or reason-coded
        try:
            payload = k_book(client, book_key) if venue == "kalshi" else p_book(client, book_key)
            b = norm_kalshi_book(payload) if venue == "kalshi" else norm_pm_book(payload)
            store.book(slot_ts=slot_ts, venue=venue, market_id=mid, recv_ts=now(),
                       age_s=age, days_to_close=dtc, **b, **mon)
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            store.book(slot_ts=slot_ts, venue=venue, market_id=mid, recv_ts=now(),
                       age_s=age, days_to_close=dtc, reason="BOOK_ERROR", **mon)
            store.health(venue, "book_error", f"{type(e).__name__}")

    store.cycle_row(slot_ts=slot_ts, lane=lane, ok=True, recv_ts=now(),
                    n_followed=len(cohort), n_seen=n_ok)
    store.flush()
    return {"ok": True, "lane": lane, "n_followed": len(cohort), "n_quoted": n_ok,
            "n_with_money": n_money, "n_truncated": truncated}


def next_slot(now_ts: float, period: float) -> float:
    return (int(now_ts // period) + 1) * period


# ── selftest ────────────────────────────────────────────────────────────────────────────────
def selftest() -> None:
    import tempfile

    kb = norm_kalshi_book({"orderbook_fp": {"yes_dollars": [[0.41, 100], [0.40, 50]],
                                            "no_dollars": [[0.55, 70]]}})
    assert kb["best_bid"] == 0.41 and abs(kb["best_ask"] - 0.45) < 1e-9, kb
    assert kb["two_sided"] and kb["n_bid_levels"] == 2 and kb["n_ask_levels"] == 1

    one = norm_kalshi_book({"orderbook_fp": {"yes_dollars": [[0.41, 100]], "no_dollars": []}})
    assert one["best_bid"] == 0.41 and one["best_ask"] is None and not one["two_sided"]

    empty = norm_kalshi_book({"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
    assert empty["best_bid"] is None and not empty["two_sided"]

    assert pm_yes_token('["111","222"]') == "111"
    assert pm_yes_token(["333", "444"]) == "333"
    assert pm_yes_token(None) is None and pm_yes_token("not json") is None

    pb = norm_pm_book({"bids": [{"price": "0.30", "size": "10"}, {"price": "0.29", "size": "5"}],
                       "asks": [{"price": "0.34", "size": "8"}, {"price": "0.36", "size": "9"}]})
    assert pb["best_bid"] == 0.30 and pb["best_ask"] == 0.34 and pb["two_sided"]
    assert abs(pb["spread"] - 0.04) < 1e-9

    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / "t.sqlite", enforce_volume=False)
        try:
            st.cycle_row(slot_ts=1.0, lane="follow", ok=False, reason="NOT_A_REAL_REASON")
            raise AssertionError("unregistered gap reason must raise")
        except ValueError:
            pass
        try:
            st.birth(venue="kalshi", market_id="X", title="acctId=U1234567",
                     detected_ts=1.0)
            raise AssertionError("privacy denylist must raise")
        except ValueError:
            pass

        # ...and must NOT fire on ordinary market prose. These are live Kalshi titles.
        for ok_title in ("Will Kaja Kallas be the next Secretary General of NATO?",
                         "Will Congress hold a session before Oct 1?",
                         "Will the Fed cut rates at its next meeting?"):
            st.birth(venue="kalshi", market_id="ok-" + ok_title[:12], title=ok_title,
                     detected_ts=1.0)

        # a market born 1 h ago is followed; one born well outside the 6 h window is not
        NOW = 100_000.0
        st.birth(venue="kalshi", market_id="NEW", title="t",
                 created_ts=NOW - 3600.0, detected_ts=NOW - 3600.0)
        st.birth(venue="kalshi", market_id="OLD", title="t",
                 created_ts=NOW - 9 * 3600.0, detected_ts=NOW - 9 * 3600.0)
        st.flush()
        coh = {m for _, m, _, _, _ in st.follow_cohort(now=NOW, young_only=False)[0]}
        assert coh == {"NEW"}, coh

        # a market already past its close is dropped even inside the age window
        st.birth(venue="kalshi", market_id="CLOSED", title="t",
                 created_ts=NOW - 600.0, detected_ts=NOW - 600.0, close_ts=NOW - 60.0)
        st.flush()
        assert "CLOSED" not in {m for _, m, _, _, _ in st.follow_cohort(now=NOW, young_only=False)[0]}

        # cold-start seeds are recorded but never followed
        st.birth(venue="kalshi", market_id="SEED", title="t",
                 created_ts=NOW - 60.0, detected_ts=NOW - 60.0, seeded=True)
        st.flush()
        assert "SEED" not in {m for _, m, _, _, _ in st.follow_cohort(now=NOW, young_only=False)[0]}

        # the cohort cap truncates and REPORTS the truncation
        rows, trunc = st.follow_cohort(now=NOW, cap=0, young_only=False)
        assert rows == [] and trunc == 1, (rows, trunc)

        # every followed market writes exactly one row per slot, even when the fetch fails
        def boom(_c, _m):
            raise RuntimeError("network down")
        r = follow_cycle(st, None, 5000.0, now=lambda: NOW, k_book=boom, p_book=boom,
                         k_money=lambda *a: {}, p_money=lambda *a: {}, young_only=False)
        rows = st.con.execute("SELECT reason FROM books WHERE slot_ts=5000.0").fetchall()
        assert r["ok"] and len(rows) == 1 and rows[0][0] == "BOOK_ERROR", (r, rows)
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-kalshi-discovery", action="store_true",
                    help="PM-only discovery; Kalshi's crawl is the expensive lane")
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    if a.self_test:
        selftest()
        return 0

    store = Store(Path(a.db))
    client = Client("newborn", rate=4.0, burst=8.0, cache_dir=None)
    store.health("collector", "startup",
                 f"version={VERSION} spec={SPEC_REF} discovery={DISCOVERY_PERIOD_S} "
                 f"follow={FOLLOW_PERIOD_S} window={FOLLOW_WINDOW_S}")
    store.flush()

    if a.once:
        d = discovery_cycle(store, client, next_slot(time.time(), DISCOVERY_PERIOD_S),
                            do_kalshi=not a.no_kalshi_discovery)
        fy = follow_cycle(store, client, next_slot(time.time(), FOLLOW_PERIOD_S),
                          young_only=True)
        fs = follow_cycle(store, client, next_slot(time.time(), SWEEP_PERIOD_S),
                          young_only=False)
        print(json.dumps({"discovery": d, "follow_young": fy, "follow_sweep": fs}, indent=2))
        return 0

    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(v=True))
    # Three lanes on independent grids. Keyed by name rather than compared by timestamp: with two
    # lanes whose periods divide each other, `target == next_disc` is true whenever the grids
    # coincide, which silently skipped the other lane's slot.
    now0 = time.time()
    lanes = {"discovery": [next_slot(now0, DISCOVERY_PERIOD_S), DISCOVERY_PERIOD_S],
             "follow_young": [next_slot(now0, FOLLOW_PERIOD_S), FOLLOW_PERIOD_S],
             "follow_sweep": [next_slot(now0, SWEEP_PERIOD_S), SWEEP_PERIOD_S]}
    while not stop["v"]:
        name = min(lanes, key=lambda k: lanes[k][0])
        target, period = lanes[name]
        while time.time() < target and not stop["v"]:
            time.sleep(min(1.0, max(0.0, target - time.time())))
        if stop["v"]:
            break
        try:
            if name == "discovery":
                discovery_cycle(store, client, target, do_kalshi=not a.no_kalshi_discovery)
            else:
                follow_cycle(store, client, target, young_only=(name == "follow_young"))
        except Exception as e:  # noqa: BLE001
            store.cycle_row(slot_ts=target, lane=name, ok=False, reason="UNKNOWN",
                            recv_ts=time.time())
            store.health("collector", "cycle_error", f"{name}: {type(e).__name__}")
            store.flush()
        finally:
            # advance on every path, so a raising lane can never spin on a stale slot
            lanes[name][0] = next_slot(time.time(), period)
    store.health("collector", "shutdown")
    store.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

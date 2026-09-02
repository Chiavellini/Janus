#!/usr/bin/env python3
"""F1 — shadow trading Kalshi's OPEN against Polymarket's established price.

    python3 collectors/collect_shadow.py --self-test
    python3 collectors/collect_shadow.py --refresh-schedule   # rebuild upcoming Kalshi opens
    python3 collectors/collect_shadow.py                      # run the scheduler

Spec: research/exec/2026-08-21_shadow-kalshi-open/spec.yaml (IMMUTABLE) · Ledger F1 (forward eval).

FORWARD EVAL — COSTS NO TEST LOOK, on one condition. AGENTS.md: "Forward eval rows do not count."
That holds only while the rule stays pinned. Looking at results and then adjusting a threshold, a
gate, or a size makes this dev selection and it costs a look. Nothing in this file reads a result
before deciding, and the thresholds are constants, not parameters.

WHY THE DECISION INSTANT IS DISCOVERED, NOT SCHEDULED. Kalshi publishes `open_time` weeks ahead for
some series (KXECONSTATU3 is created three weeks before it opens) but NOT for sports: measured
2026-08-20, KXMLBGAME had zero markets with a future open_time and zero in any pre-open status. So
the collector polls for tickers it has never seen and treats their first appearance as t0. Detection
latency equals the poll interval, and `lag_s` is recorded on every decision so that cost is
measurable rather than assumed. The REFERENCE side IS indexed ahead -- possible because Polymarket
lists ~82 h earlier -- so only the newborn leg has to be caught live.

WHAT IS BEING SHADOWED. Polymarket lists an MLB game ~82 h before Kalshi opens it, so at t0 PM
carries an established price (median 0.085 off its 0.500 listing default) and Kalshi does not. Both
directions are pinned and both are reported: the inherited mirror was spent and FAILED (-2.375c,
p=0.772), so testing only the hoped-for direction would be a free parameter.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import signal
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client                      # noqa: E402
from match.screen import kalshi_fee_c, pm_fee_c   # noqa: E402
import collectors.collect_newborn as nb           # noqa: E402

SPEC_REF = "research/exec/2026-08-21_shadow-kalshi-open/spec.yaml"
VERSION = "shadow-kalshi-open/1.0.0"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
DB_PATH = Path("/Volumes/Kilos/janus/shadow/kalshi_open.sqlite")
DISK_FLOOR_BYTES = 2 * 1024**3

# ── PINNED RULE CONSTANTS. Changing any of these after the first decision costs a test look. ──
SHADOW_NOTIONAL_USD = 100.0
PM_MIN_MOVE_FROM_HALF = 0.02     # an unmoved market carries no information
PM_MAX_SPREAD = 0.10             # a 0.01/0.99 placeholder is not a reference
MIN_DEPTH_USD = 5.0
POLL_LEAD_S = 30.0               # start polling this far before t0
POLL_WINDOW_S = 300.0            # keep trying this long after t0 before calling MISSED_OPEN
POLL_TICK_S = 60.0   # detection latency == this interval; Kalshi has no pre-open surface

#: A decision is only an AT-OPEN observation if we actually saw the market near its open. The spec
#: defines t0 as "first observation of the Kalshi market after it opens"; a market first seen 71 h
#: after opening was not observed at open and must not be scored as though it were.
#:
#: MEASURED THE HARD WAY 2026-08-20: the first run had no cold-start guard, so its opening poll
#: treated all 94 already-open markets as newly discovered and produced 94 decisions with lag_s of
#: 1.6 to 71.1 hours -- including 18 TRADE signals at 43-71 h. Every one of those is an artifact.
#: That DB is preserved as CONTAMINATED_coldstart_*.sqlite and none of it counts.
MAX_LAG_S = 900.0

NO_TRADE_REASONS = {"REFERENCE_UNPRICED", "PM_ONE_SIDED", "PM_SPREAD_WIDE", "PM_UNMOVED",
                    "KALSHI_NO_BOOK", "KALSHI_ONE_SIDED", "NO_EDGE_AFTER_FEES", "BELOW_MIN_DEPTH",
                    "BOOK_ERROR", "DISK_FLOOR", "MISSED_OPEN", "STALE_OPEN", "COLD_START_SEED",
                    "UNKNOWN"}

FORBIDDEN_TEXT = nb.FORBIDDEN_TEXT

DDL = """
CREATE TABLE IF NOT EXISTS schedule(kalshi_ticker TEXT PRIMARY KEY, pm_event TEXT, pm_label TEXT,
  pm_token TEXT, game_id TEXT, open_ts REAL, close_ts REAL, added_ts REAL, decided INTEGER DEFAULT 0);
-- Polymarket lists ~82 h before Kalshi opens, so the REFERENCE side can be indexed ahead of time.
-- Keyed on canonical entity ids from lib/entities so ATH/OAK and AZ/ARI resolve to one game.
CREATE TABLE IF NOT EXISTS pm_index(game_key TEXT, entity_id TEXT, pm_event TEXT, pm_label TEXT,
  pm_token TEXT, start_ts REAL, indexed_ts REAL, PRIMARY KEY (game_key, entity_id));
CREATE TABLE IF NOT EXISTS seen_kalshi(kalshi_ticker TEXT PRIMARY KEY, first_seen_ts REAL);
CREATE TABLE IF NOT EXISTS decisions(kalshi_ticker TEXT PRIMARY KEY, game_id TEXT, t0 REAL,
  decided_ts REAL, lag_s REAL, action TEXT, reason TEXT,
  k_bid REAL, k_ask REAL, k_depth_usd REAL, pm_bid REAL, pm_ask REAL, pm_depth_usd REAL,
  pm_mid REAL, gap_cents REAL, fees_cents REAL, net_edge_cents REAL,
  size_usd REAL, entry_price REAL, entry_venue TEXT, spec_ref TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS settlements(kalshi_ticker TEXT PRIMARY KEY, settled_ts REAL,
  result TEXT, pnl_cents REAL);
CREATE TABLE IF NOT EXISTS health(ts REAL, component TEXT, status TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path: Path, enforce_volume: bool = True):
        p = Path(path)
        if enforce_volume and not str(p.resolve()).startswith("/Volumes/"):
            raise ValueError("F1 data must live on the data volume, never the root disk")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(p))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(DDL)

    @staticmethod
    def _check(*vals):
        for v in vals:
            if isinstance(v, str) and FORBIDDEN_TEXT.search(v):
                raise ValueError("refusing to persist text matching the privacy denylist")

    def add_scheduled(self, **kw):
        self._check(kw.get("kalshi_ticker"), kw.get("pm_event"))
        self.con.execute("INSERT OR IGNORE INTO schedule VALUES (?,?,?,?,?,?,?,?,0)",
                         (kw["kalshi_ticker"], kw.get("pm_event"), kw.get("pm_label"),
                          kw.get("pm_token"), kw.get("game_id"), kw.get("open_ts"),
                          kw.get("close_ts"), time.time()))

    def due(self, now: float):
        """Rows whose open is within the polling window and that have not been decided."""
        return self.con.execute(
            "SELECT kalshi_ticker, pm_event, pm_label, pm_token, game_id, open_ts FROM schedule "
            "WHERE decided=0 AND open_ts IS NOT NULL AND open_ts - ? <= ? AND ? - open_ts <= ? "
            "ORDER BY open_ts", (now, POLL_LEAD_S, now, POLL_WINDOW_S)).fetchall()

    def stale(self, now: float):
        return self.con.execute(
            "SELECT kalshi_ticker, game_id, open_ts FROM schedule "
            "WHERE decided=0 AND open_ts IS NOT NULL AND ? - open_ts > ?",
            (now, POLL_WINDOW_S)).fetchall()

    def record(self, **kw):
        if kw.get("reason") and kw["reason"] not in NO_TRADE_REASONS:
            raise ValueError(f"unregistered no-trade reason {kw['reason']}")
        self._check(kw.get("kalshi_ticker"), kw.get("reason"))
        cols = ("kalshi_ticker", "game_id", "t0", "decided_ts", "lag_s", "action", "reason",
                "k_bid", "k_ask", "k_depth_usd", "pm_bid", "pm_ask", "pm_depth_usd", "pm_mid",
                "gap_cents", "fees_cents", "net_edge_cents", "size_usd", "entry_price",
                "entry_venue")
        self.con.execute(
            f"INSERT OR REPLACE INTO decisions VALUES ({','.join('?' * (len(cols) + 2))})",
            tuple(kw.get(c) for c in cols) + (SPEC_REF, VERSION))
        self.con.execute("UPDATE schedule SET decided=1 WHERE kalshi_ticker=?",
                         (kw["kalshi_ticker"],))

    def health(self, component, status, detail=""):
        self._check(detail)
        self.con.execute("INSERT INTO health VALUES (?,?,?,?)",
                         (time.time(), component, status, str(detail)[:500]))

    def flush(self):
        self.con.commit()


#: MLB tickers look like KXMLBGAME-26AUG201835NYYBAL-BAL: date, start time, the two team codes
#: concatenated, then the outcome team. Kalshi is NOT expected to agree with Polymarket on those
#: codes -- measured, it uses ATH where PM uses OAK and AZ where PM uses ARI, which is 12 of 94 pairs
#: -- so both sides are pushed through lib/entities' Resolver and compared as canonical ids.
KTICK = re.compile(r"^KXMLBGAME-(\d{2})([A-Z]{3})(\d{2})(\d{4})([A-Z0-9]+)-([A-Z0-9]+)$")
_MON = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def split_ticker_teams(concat: str, outcome: str) -> tuple[str, str] | None:
    """The outcome code is one of the two teams; strip it from whichever end it sits on."""
    if concat.endswith(outcome) and len(concat) > len(outcome):
        return concat[: -len(outcome)], outcome
    if concat.startswith(outcome) and len(concat) > len(outcome):
        return outcome, concat[len(outcome):]
    return None


def parse_kalshi_ticker(ticker: str):
    m = KTICK.match(ticker or "")
    if not m:
        return None
    yy, mon, dd, _hhmm, concat, outcome = m.groups()
    pair = split_ticker_teams(concat, outcome)
    if not pair:
        return None
    return {"date": "20%s-%02d-%s" % (yy, _MON[mon], dd), "teams": pair, "outcome": outcome}


def game_key(date: str, entity_ids) -> str:
    return date + "|" + "|".join(sorted(entity_ids))


def disk_ok(path="/") -> bool:
    return shutil.disk_usage(path).free >= DISK_FLOOR_BYTES


def depth_usd(bid, ask, bid_sz, ask_sz):
    if not (bid and ask and bid_sz and ask_sz):
        return None
    return min(float(bid_sz), float(ask_sz)) * float(ask)


# ── THE PINNED DECISION. No result is read; the thresholds are constants. ────────────────────
def decide(k: dict, p: dict) -> dict:
    """Both directions are evaluated and the better one is taken. Prices are EXECUTABLE ONLY."""
    if k.get("best_bid") is None or k.get("best_ask") is None:
        return {"action": "NO_TRADE", "reason": "KALSHI_ONE_SIDED" if k.get("best_bid") or
                k.get("best_ask") else "KALSHI_NO_BOOK"}
    if p.get("best_bid") is None or p.get("best_ask") is None:
        return {"action": "NO_TRADE", "reason": "PM_ONE_SIDED"}

    pm_mid = (p["best_bid"] + p["best_ask"]) / 2.0
    if (p["best_ask"] - p["best_bid"]) > PM_MAX_SPREAD:
        return {"action": "NO_TRADE", "reason": "PM_SPREAD_WIDE", "pm_mid": pm_mid}
    if abs(pm_mid - 0.5) < PM_MIN_MOVE_FROM_HALF:
        return {"action": "NO_TRADE", "reason": "PM_UNMOVED", "pm_mid": pm_mid}

    kd = depth_usd(k["best_bid"], k["best_ask"], k.get("bid_size"), k.get("ask_size"))
    pd = depth_usd(p["best_bid"], p["best_ask"], p.get("bid_size"), p.get("ask_size"))
    if not kd or not pd or min(kd, pd) < MIN_DEPTH_USD:
        return {"action": "NO_TRADE", "reason": "BELOW_MIN_DEPTH", "pm_mid": pm_mid,
                "k_depth_usd": kd, "pm_depth_usd": pd}

    kf, km = k.get("fee_type"), k.get("fee_multiplier")
    pfs = p.get("fee_schedule")

    # arm A: Kalshi is cheap -> buy Kalshi YES, reference is PM's bid
    a_cost = k["best_ask"] * 100 + kalshi_fee_c(k["best_ask"] * 100, km, kf)
    a_ref = p["best_bid"] * 100 - pm_fee_c(p["best_bid"] * 100, pfs)
    a_edge = a_ref - a_cost
    # arm B (the MIRROR, mandatory): PM is cheap -> buy PM YES, reference is Kalshi's bid
    b_cost = p["best_ask"] * 100 + pm_fee_c(p["best_ask"] * 100, pfs)
    b_ref = k["best_bid"] * 100 - kalshi_fee_c(k["best_bid"] * 100, km, kf)
    b_edge = b_ref - b_cost

    best, venue, price = ((a_edge, "kalshi", k["best_ask"]) if a_edge >= b_edge
                          else (b_edge, "polymarket", p["best_ask"]))
    common = {"pm_mid": pm_mid, "k_depth_usd": kd, "pm_depth_usd": pd,
              "gap_cents": round((pm_mid - (k["best_bid"] + k["best_ask"]) / 2.0) * 100, 3),
              "net_edge_cents": round(best, 3)}
    if best <= 0:
        return {"action": "NO_TRADE", "reason": "NO_EDGE_AFTER_FEES", **common}
    return {"action": "TRADE", "reason": None, "entry_venue": venue, "entry_price": price,
            "size_usd": min(SHADOW_NOTIONAL_USD, kd, pd), **common}


def fetch_legs(client: Client, ticker: str, token: str):
    kb = nb.norm_kalshi_book(client.get_json(f"{KALSHI}/markets/{ticker}/orderbook",
                                             params={"depth": 10}, use_cache=False))
    m = (client.get_json(f"{KALSHI}/markets", params={"tickers": ticker, "limit": 1},
                         use_cache=False) or {}).get("markets", [{}])[0]
    kb["fee_type"], kb["fee_multiplier"] = m.get("fee_type"), m.get("fee_multiplier")
    pb = nb.norm_pm_book(nb.fetch_pm_book(client, token))
    return kb, pb


def selftest() -> None:
    import tempfile
    K = {"best_bid": 0.40, "best_ask": 0.42, "bid_size": 500, "ask_size": 500,
         "fee_type": "quadratic", "fee_multiplier": 1.0}
    P = {"best_bid": 0.60, "best_ask": 0.62, "bid_size": 500, "ask_size": 500,
         "fee_schedule": {"rate": 0.04}}
    d = decide(K, P)
    assert d["action"] == "TRADE" and d["entry_venue"] == "kalshi", d

    # the MIRROR must be reachable, or only one direction is ever testable
    d2 = decide({**K, "best_bid": 0.60, "best_ask": 0.62},
                {**P, "best_bid": 0.40, "best_ask": 0.42})
    assert d2["action"] == "TRADE" and d2["entry_venue"] == "polymarket", d2

    # reference-quality gates
    assert decide(K, {**P, "best_bid": 0.49, "best_ask": 0.51})["reason"] == "PM_UNMOVED"
    assert decide(K, {**P, "best_bid": 0.30, "best_ask": 0.95})["reason"] == "PM_SPREAD_WIDE"
    assert decide(K, {**P, "best_bid": None})["reason"] == "PM_ONE_SIDED"
    assert decide({**K, "best_bid": None, "best_ask": None}, P)["reason"] == "KALSHI_NO_BOOK"
    assert decide({**K, "bid_size": 1, "ask_size": 1}, P)["reason"] == "BELOW_MIN_DEPTH"

    # venues agreeing must yield NO edge after fees
    tight = decide({**K, "best_bid": 0.60, "best_ask": 0.61},
                   {**P, "best_bid": 0.60, "best_ask": 0.61})
    assert tight["reason"] == "NO_EDGE_AFTER_FEES", tight

    with tempfile.TemporaryDirectory() as t:
        st = Store(Path(t) / "s.sqlite", enforce_volume=False)
        try:
            st.record(kalshi_ticker="X", reason="NOT_A_REASON")
            raise AssertionError("unregistered reason must raise")
        except ValueError:
            pass
        st.add_scheduled(kalshi_ticker="T", pm_event="e", pm_label="l", pm_token="tok",
                         game_id="g", open_ts=1000.0)
        st.flush()
        assert len(st.due(1000.0)) == 1
        assert len(st.due(1000.0 + POLL_WINDOW_S + 1)) == 0      # outside the window
        assert len(st.stale(1000.0 + POLL_WINDOW_S + 1)) == 1
        st.record(kalshi_ticker="T", game_id="g", t0=1000.0, action="NO_TRADE",
                  reason="MISSED_OPEN")
        st.flush()
        assert len(st.stale(1e9)) == 0                            # decided rows leave the queue
    print("selftest OK")


def refresh_pm_index(store: Store, client: Client, resolver, days: int = 6) -> int:
    """Index Polymarket's upcoming MLB games. PM lists ~82 h before Kalshi opens, so the reference
    side is always available before the newborn side exists."""
    added = 0
    for page in range(6):
        evs = client.get_json(f"{GAMMA}/events", params={
            "closed": "false", "limit": 100, "offset": page * 100,
            "tag_slug": "mlb"}, use_cache=False)
        if not evs:
            break
        for e in evs:
            slug = e.get("slug") or ""
            parts = slug.split("-")
            if len(parts) < 5 or parts[0] != "mlb":
                continue
            date = "-".join(parts[3:6])
            ids = []
            for code in (parts[1], parts[2]):
                try:
                    ids.append(resolver.resolve("mlb", text=code).entity_id)
                except Exception:                                  # noqa: BLE001
                    ids.append(None)
            if not all(ids):
                continue
            gk = game_key(date, ids)
            for mm in (e.get("markets") or []):
                try:
                    outs = json.loads(mm.get("outcomes") or "[]")
                    toks = json.loads(mm.get("clobTokenIds") or "[]")
                except Exception:                                  # noqa: BLE001
                    continue
                if len(outs) != len(toks):
                    continue
                for lbl, tok in zip(outs, toks):
                    try:
                        eid = resolver.resolve("mlb", text=lbl).entity_id
                    except Exception:                              # noqa: BLE001
                        continue
                    store.con.execute(
                        "INSERT OR REPLACE INTO pm_index VALUES (?,?,?,?,?,?,?)",
                        (gk, eid, slug, lbl, str(tok), nb.iso_ts(e.get("startDate")), time.time()))
                    added += 1
    store.flush()
    return added


def poll_new_kalshi(store: Store, client: Client, resolver) -> list[tuple]:
    """Kalshi does NOT expose MLB markets before they open -- measured 2026-08-20, zero markets with
    a future open_time and zero in any pre-open status. So the decision instant is DISCOVERED, and
    detection latency is the poll interval. Anything we have not seen before is newly open."""
    d = client.get_json(f"{KALSHI}/markets",
                        params={"series_ticker": "KXMLBGAME", "status": "open", "limit": 500},
                        use_cache=False)
    # COLD START: an empty seen-table means we have never looked. Everything currently open opened
    # BEFORE we existed, so none of it is an at-open observation -- seed it and decide on nothing.
    seeding = not store.con.execute("SELECT 1 FROM seen_kalshi LIMIT 1").fetchone()
    fresh = []
    for m in (d or {}).get("markets", []):
        t = m.get("ticker")
        if not t:
            continue
        if store.con.execute("SELECT 1 FROM seen_kalshi WHERE kalshi_ticker=?", (t,)).fetchone():
            continue
        store.con.execute("INSERT OR IGNORE INTO seen_kalshi VALUES (?,?)", (t, time.time()))
        if seeding:
            continue
        parsed = parse_kalshi_ticker(t)
        if not parsed:
            continue
        try:
            ids = [resolver.resolve("mlb", text=c).entity_id for c in parsed["teams"]]
            out_id = resolver.resolve("mlb", text=parsed["outcome"]).entity_id
        except Exception:                                          # noqa: BLE001
            continue
        row = store.con.execute(
            "SELECT pm_event, pm_label, pm_token FROM pm_index WHERE game_key=? AND entity_id=?",
            (game_key(parsed["date"], ids), out_id)).fetchone()
        if row:
            fresh.append((t, row[0], row[1], row[2], nb.iso_ts(m.get("open_time")),
                          m.get("fee_type"), m.get("fee_multiplier")))
    if seeding:
        store.health("collector", "COLD_START_SEED",
                     f"{len(d.get('markets') or [])} already-open markets seeded, none decided")
    store.flush()
    return fresh


def refresh_schedule(store: Store, client: Client, pairs_csv: Path) -> int:
    rows = list(csv.DictReader(pairs_csv.open()))
    added = 0
    for r in rows:
        try:
            m = (client.get_json(f"{KALSHI}/markets", params={"tickers": r["kalshi_outcome"],
                                                              "limit": 1},
                                 use_cache=False) or {}).get("markets", [{}])[0]
            open_ts = nb.iso_ts(m.get("open_time"))
            evs = client.get_json(f"{GAMMA}/events", params={"slug": r["pm_event"]},
                                  use_cache=False)
            tok = None
            for e in (evs or []):
                for mm in (e.get("markets") or []):
                    outs = json.loads(mm.get("outcomes") or "[]")
                    toks = json.loads(mm.get("clobTokenIds") or "[]")
                    if r["pm_label"] in outs and len(toks) == len(outs):
                        tok = str(toks[outs.index(r["pm_label"])])
                        break
            if not (open_ts and tok):
                continue
            store.add_scheduled(kalshi_ticker=r["kalshi_outcome"], pm_event=r["pm_event"],
                                pm_label=r["pm_label"], pm_token=tok, game_id=r["game_id"],
                                open_ts=open_ts, close_ts=nb.iso_ts(m.get("close_time")))
            added += 1
        except Exception as e:                                    # noqa: BLE001
            store.health("schedule", "error", type(e).__name__)
    store.flush()
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--refresh-schedule", action="store_true")
    ap.add_argument("--refresh-pm-index", action="store_true")
    ap.add_argument("--validate-mapping", action="store_true")
    ap.add_argument("--pairs", default="research/sports/2026-08-20_stage2-rerun/pairs.csv")
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    if a.self_test:
        selftest()
        return 0

    store = Store(Path(a.db))
    client = Client("shadow", rate=4.0, burst=8.0, cache_dir=None)
    store.health("collector", "startup", f"version={VERSION} spec={SPEC_REF}")

    from lib.entities.resolve import Resolver
    resolver = Resolver()

    if a.refresh_pm_index:
        n = refresh_pm_index(store, client, resolver)
        tot = store.con.execute("SELECT count(DISTINCT game_key) FROM pm_index").fetchone()[0]
        print(json.dumps({"pm_index_rows_added": n, "distinct_games_indexed": tot}))
        return 0

    if a.validate_mapping:
        rows = list(csv.DictReader(Path(a.pairs).open()))
        ok = miss = 0
        for r in rows:
            parsed = parse_kalshi_ticker(r["kalshi_outcome"])
            if not parsed:
                miss += 1
                continue
            try:
                ids = [resolver.resolve("mlb", text=c).entity_id for c in parsed["teams"]]
                oid = resolver.resolve("mlb", text=parsed["outcome"]).entity_id
            except Exception:                                      # noqa: BLE001
                miss += 1
                continue
            got = store.con.execute(
                "SELECT pm_event FROM pm_index WHERE game_key=? AND entity_id=?",
                (game_key(parsed["date"], ids), oid)).fetchone()
            if got and got[0] == r["pm_event"]:
                ok += 1
            else:
                miss += 1
        print(json.dumps({"validated_against_known_pairs": len(rows), "matched": ok,
                          "unmatched": miss}))
        return 0

    if a.refresh_schedule:
        n = refresh_schedule(store, client, Path(a.pairs))
        pend = store.con.execute("SELECT count(*) FROM schedule WHERE decided=0").fetchone()[0]
        print(json.dumps({"scheduled_added": n, "pending": pend}))
        return 0

    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(v=True))
    while not stop["v"]:
        now = time.time()
        if not disk_ok():
            store.health("monitor", "DISK_FLOOR", f"free={shutil.disk_usage('/').free}")
            store.flush()
            time.sleep(30)
            continue
        try:
            fresh = poll_new_kalshi(store, client, resolver)
        except Exception as e:                                    # noqa: BLE001
            store.health("poll", "error", type(e).__name__)
            fresh = []
        for ticker, _ev, _lbl, token, t0, kft, kfm in fresh:
            game_id = ticker
            if t0 and (time.time() - t0) > MAX_LAG_S:
                store.record(kalshi_ticker=ticker, game_id=game_id, t0=t0,
                             decided_ts=time.time(), lag_s=time.time() - t0,
                             action="NO_TRADE", reason="STALE_OPEN")
                continue
            try:
                k, p = fetch_legs(client, ticker, token)
            except Exception as e:                                # noqa: BLE001
                store.health("legs", "error", f"{ticker[:24]}: {type(e).__name__}")
                continue
            d = decide(k, p)
            store.record(kalshi_ticker=ticker, game_id=game_id, t0=t0, decided_ts=time.time(),
                         lag_s=(time.time() - t0) if t0 else None,
                         k_bid=k.get("best_bid"), k_ask=k.get("best_ask"),
                         pm_bid=p.get("best_bid"), pm_ask=p.get("best_ask"), **d)
            store.health("decision", d["action"], f"{ticker[:28]} {d.get('reason') or ''}")
            store.flush()          # per-decision, so a mid-batch crash cannot lose observations
        store.flush()
        time.sleep(POLL_TICK_S)
    store.health("collector", "shutdown")
    store.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

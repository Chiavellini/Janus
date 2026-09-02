#!/usr/bin/env python3
"""F2 — does KALSHI converge to POLYMARKET, or the reverse?

    python3 collectors/collect_convergence.py --self-test
    python3 collectors/collect_convergence.py --once
    python3 collectors/collect_convergence.py

Spec: research/exec/2026-08-21_convergence/spec.yaml (IMMUTABLE) · Ledger F2 (forward eval).

WHY THIS EXISTS, AND WHY IT IS NOT F1. F1 asks "is there an executable gap at Kalshi's open" and
answered on its first observation: Kalshi opened ATL@MIL at 0.25/0.95, a SEVENTY cent spread, so the
two-leg round trip cost 143.9c for a 100c payoff. No arbitrage. But a one-legged CONVERGENCE bet
pays only one spread, and its condition is exact:

        edge  =  mid_error  -  half_spread          i.e. you need   spread < 2 x mid_error

At that open the mid error was 6.5c and the half spread 35c. Five hours later the same market quoted
0.50/0.58 -- the spread had collapsed from 70c to 8c. So the whole question is a RACE: does Kalshi's
spread fall below 2x the error before the error itself decays?

WHAT MAKES THIS MEASURABLE FAST. Convergence needs NO SETTLEMENT. Whether Kalshi's mid moves toward
Polymarket's is visible from the two books alone, so an observation is one poll rather than one
settled game, and the ~50c binary variance that makes n=10 useless for PnL never enters. Both venues
expose BATCH top-of-book -- Kalshi returns all 90 open MLB markets in a single call -- so a full
sweep costs a handful of requests.

THE STATISTIC IS ATTRIBUTION, NOT CORRELATION. Over an interval the error closes by some amount; the
question is WHO closed it. If Kalshi does most of the moving, Kalshi is the follower and the operator's
thesis holds. If Polymarket does, PM follows Kalshi -- which is what AGENTS.md's inherited "truth sits
at Kalshi" would predict, though that was measured on crypto where Kalshi LEADS and here Kalshi is
the late lister by 82 h. Both outcomes are recorded; neither is assumed.

NO OUTCOME IS EVER READ. This file records quotes and nothing else.
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client                      # noqa: E402
import collectors.collect_newborn as nb           # noqa: E402

SPEC_REF = "research/exec/2026-08-21_convergence/spec.yaml"
VERSION = "convergence/1.0.0"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
DB_PATH = Path("/Volumes/Kilos/janus/convergence/track.sqlite")
SHADOW_DB = Path("/Volumes/Kilos/janus/shadow/kalshi_open.sqlite")   # reuse F1's pm_index
DISK_FLOOR_BYTES = 2 * 1024**3

SAMPLE_PERIOD_S = 60.0
NEWBORN_S = 6 * 3600.0        # cohort boundary, for reporting only -- both cohorts are sampled

GAP_REASONS = {"KALSHI_ERROR", "PM_ERROR", "KALSHI_ONE_SIDED", "PM_ONE_SIDED", "NO_PAIR",
               "DISK_FLOOR", "UNKNOWN"}
FORBIDDEN_TEXT = nb.FORBIDDEN_TEXT

DDL = """
CREATE TABLE IF NOT EXISTS samples(sample_ts REAL, kalshi_ticker TEXT, pm_event TEXT, pm_label TEXT,
  k_bid REAL, k_ask REAL, k_mid REAL, pm_bid REAL, pm_ask REAL, pm_mid REAL,
  error_c REAL, k_spread_c REAL, pm_spread_c REAL, open_ts REAL, age_s REAL, cohort TEXT,
  tradeable INTEGER, reason TEXT, PRIMARY KEY (sample_ts, kalshi_ticker));
CREATE INDEX IF NOT EXISTS samples_mkt ON samples(kalshi_ticker, sample_ts);
CREATE TABLE IF NOT EXISTS cycles(sample_ts REAL PRIMARY KEY, recv_ts REAL, ok INTEGER, reason TEXT,
  n_markets INTEGER, n_paired INTEGER, spec_ref TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS health(ts REAL, component TEXT, status TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path: Path, enforce_volume: bool = True):
        p = Path(path)
        if enforce_volume and not str(p.resolve()).startswith("/Volumes/"):
            raise ValueError("F2 data must live on the data volume, never the root disk")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(p))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(DDL)

    @staticmethod
    def _check(*vals):
        for v in vals:
            if isinstance(v, str) and FORBIDDEN_TEXT.search(v):
                raise ValueError("refusing to persist text matching the privacy denylist")

    def sample(self, **kw):
        if kw.get("reason") and kw["reason"] not in GAP_REASONS:
            raise ValueError(f"unregistered gap reason {kw['reason']}")
        self._check(kw.get("kalshi_ticker"), kw.get("reason"))
        cols = ("sample_ts", "kalshi_ticker", "pm_event", "pm_label", "k_bid", "k_ask", "k_mid",
                "pm_bid", "pm_ask", "pm_mid", "error_c", "k_spread_c", "pm_spread_c", "open_ts",
                "age_s", "cohort", "tradeable", "reason")
        self.con.execute(f"INSERT OR REPLACE INTO samples VALUES ({','.join('?' * len(cols))})",
                         tuple(kw.get(c) for c in cols))

    def cycle(self, **kw):
        self.con.execute("INSERT OR REPLACE INTO cycles VALUES (?,?,?,?,?,?,?,?)",
                         (kw["sample_ts"], kw.get("recv_ts"), int(kw["ok"]), kw.get("reason"),
                          kw.get("n_markets", 0), kw.get("n_paired", 0), SPEC_REF, VERSION))

    def health(self, component, status, detail=""):
        self._check(detail)
        self.con.execute("INSERT INTO health VALUES (?,?,?,?)",
                         (time.time(), component, status, str(detail)[:500]))

    def flush(self):
        self.con.commit()


def mid(b, a):
    return (b + a) / 2.0 if (b is not None and a is not None) else None


def tradeable(error_c, k_spread_c) -> int:
    """The finish line, stated once: a one-legged bet pays ONE spread, so it clears when
    edge = |error| - half_spread > 0, i.e. spread < 2 x |error|."""
    if error_c is None or k_spread_c is None:
        return 0
    return int(abs(error_c) - k_spread_c / 2.0 > 0)


def load_pairs(shadow_db: Path) -> dict:
    """Reuse F1's pm_index: kalshi_ticker -> (pm_event, pm_label). Built from lib/entities, and
    validated 94/94 against the sports matcher's known-good pairs."""
    con = sqlite3.connect(f"file:{shadow_db}?mode=ro", uri=True)
    import collectors.collect_shadow as cs
    from lib.entities.resolve import Resolver
    r = Resolver()
    out = {}
    for (t,) in con.execute("SELECT kalshi_ticker FROM seen_kalshi"):
        parsed = cs.parse_kalshi_ticker(t)
        if not parsed:
            continue
        try:
            ids = [r.resolve("mlb", text=c).entity_id for c in parsed["teams"]]
            oid = r.resolve("mlb", text=parsed["outcome"]).entity_id
        except Exception:                                          # noqa: BLE001
            continue
        row = con.execute("SELECT pm_event, pm_label FROM pm_index WHERE game_key=? AND entity_id=?",
                          (cs.game_key(parsed["date"], ids), oid)).fetchone()
        if row:
            out[t] = row
    return out


def sweep(store: Store, client: Client, pairs: dict, *, now=time.time) -> dict:
    t0 = now()
    if not disk_ok():
        store.cycle(sample_ts=t0, ok=False, reason="DISK_FLOOR", recv_ts=t0)
        store.health("monitor", "DISK_FLOOR", f"free={shutil.disk_usage('/').free}")
        store.flush()
        return {"ok": False, "reason": "DISK_FLOOR"}

    # Kalshi: every open MLB market in ONE call
    try:
        d = client.get_json(f"{KALSHI}/markets", params={
            "series_ticker": "KXMLBGAME", "status": "open", "limit": 500}, use_cache=False)
    except Exception as e:                                         # noqa: BLE001
        store.cycle(sample_ts=t0, ok=False, reason="KALSHI_ERROR", recv_ts=now())
        store.health("kalshi", "error", type(e).__name__)
        store.flush()
        return {"ok": False, "reason": "KALSHI_ERROR"}
    kmk = {m["ticker"]: m for m in (d or {}).get("markets", []) if m.get("ticker")}

    # Polymarket: one call per distinct event, top-of-book comes back on the market objects
    slugs = {pairs[t][0] for t in kmk if t in pairs}
    pmq = {}
    for slug in slugs:
        try:
            evs = client.get_json(f"{GAMMA}/events", params={"slug": slug}, use_cache=False)
        except Exception:                                          # noqa: BLE001
            continue
        for e in (evs or []):
            for m in (e.get("markets") or []):
                try:
                    outs = json.loads(m.get("outcomes") or "[]")
                except Exception:                                  # noqa: BLE001
                    continue
                # MONEYLINE ONLY. A Polymarket game event carries ~17 markets and SIX of them use
                # the team names as outcomes -- "Spread: Milwaukee Brewers (-1.5)", "1st 5 Innings
                # Spread: Atlanta Braves (-1.5)", and so on. Mapping by team label alone let the
                # LAST one win, so Kalshi's moneyline was being compared against a run-line spread:
                # ATL@MIL read as a 23.5c "disagreement" when the two moneylines agreed to the cent.
                # This is the trap block.py:12 and sports_match.py:20 both document; the moneyline is
                # the only market whose question carries no ":" qualifier.
                if ":" in (m.get("question") or ""):
                    continue
                # gamma's bestBid/bestAsk are PER MARKET and refer to outcomes[0]. A binary
                # market has ONE quote pair, not one per outcome, so the second outcome is the
                # MIRROR: bid = 1 - ask, ask = 1 - bid. Assigning the same pair to both teams put
                # the complement's price on one side of every game and manufactured a ~14c average
                # "disagreement" -- |2p-1| -- that looked exactly like a large tradeable edge.
                bb, ba = m.get("bestBid"), m.get("bestAsk")
                if bb is None or ba is None or len(outs) != 2:
                    continue
                bb, ba = float(bb), float(ba)
                pmq[(slug, outs[0])] = (bb, ba)
                pmq[(slug, outs[1])] = (1.0 - ba, 1.0 - bb)

    n_paired = 0
    for t, m in kmk.items():
        pair = pairs.get(t)
        if not pair:
            store.sample(sample_ts=t0, kalshi_ticker=t, reason="NO_PAIR")
            continue
        slug, lbl = pair
        kb, ka = m.get("yes_bid_dollars"), m.get("yes_ask_dollars")
        kb = float(kb) if kb is not None else None
        ka = float(ka) if ka is not None else None
        pb, pa = pmq.get((slug, lbl), (None, None))
        pb = float(pb) if pb is not None else None
        pa = float(pa) if pa is not None else None
        km, pm = mid(kb, ka), mid(pb, pa)
        if km is None:
            store.sample(sample_ts=t0, kalshi_ticker=t, pm_event=slug, pm_label=lbl,
                         reason="KALSHI_ONE_SIDED")
            continue
        if pm is None:
            store.sample(sample_ts=t0, kalshi_ticker=t, pm_event=slug, pm_label=lbl,
                         k_bid=kb, k_ask=ka, k_mid=km, reason="PM_ONE_SIDED")
            continue
        ots = nb.iso_ts(m.get("open_time"))
        age = (t0 - ots) if ots else None
        err = (km - pm) * 100
        ksp = (ka - kb) * 100
        store.sample(sample_ts=t0, kalshi_ticker=t, pm_event=slug, pm_label=lbl,
                     k_bid=kb, k_ask=ka, k_mid=km, pm_bid=pb, pm_ask=pa, pm_mid=pm,
                     error_c=err, k_spread_c=ksp, pm_spread_c=(pa - pb) * 100,
                     open_ts=ots, age_s=age,
                     cohort=("newborn" if (age is not None and age < NEWBORN_S) else "mature"),
                     tradeable=tradeable(err, ksp))
        n_paired += 1

    store.cycle(sample_ts=t0, ok=True, recv_ts=now(), n_markets=len(kmk), n_paired=n_paired)
    store.flush()
    return {"ok": True, "n_markets": len(kmk), "n_paired": n_paired}


def disk_ok(path="/") -> bool:
    return shutil.disk_usage(path).free >= DISK_FLOOR_BYTES


def selftest() -> None:
    import tempfile
    assert mid(0.4, 0.6) == 0.5 and mid(None, 0.6) is None
    # the finish line: spread must be under 2x the error
    assert tradeable(6.5, 70.0) == 0          # the observed open: 6.5c error, 70c spread
    assert tradeable(6.5, 8.0) == 1           # same error, spread collapsed to 8c
    assert tradeable(6.5, 13.0) == 0          # exactly 2x -> not strictly positive
    assert tradeable(6.5, 12.9) == 1
    assert tradeable(-6.5, 8.0) == 1          # sign of the error must not matter
    assert tradeable(None, 8.0) == 0
    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / "c.sqlite", enforce_volume=False)
        try:
            st.sample(sample_ts=1.0, kalshi_ticker="T", reason="NOPE")
            raise AssertionError("unregistered reason must raise")
        except ValueError:
            pass
        st.sample(sample_ts=1.0, kalshi_ticker="T", reason="NO_PAIR")
        st.sample(sample_ts=1.0, kalshi_ticker="U", k_mid=0.6, pm_mid=0.535, error_c=6.5,
                  k_spread_c=8.0, tradeable=1)
        st.flush()
        assert st.con.execute("SELECT count(*) FROM samples").fetchone()[0] == 2
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    if a.self_test:
        selftest()
        return 0

    store = Store(Path(a.db))
    client = Client("convergence", rate=4.0, burst=8.0, cache_dir=None)
    store.health("collector", "startup", f"version={VERSION} spec={SPEC_REF}")
    pairs = load_pairs(SHADOW_DB)
    store.health("collector", "pairs_loaded", f"{len(pairs)} kalshi tickers mapped to PM")
    store.flush()

    if a.once:
        print(json.dumps(sweep(store, client, pairs), indent=1))
        return 0

    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(v=True))
    last_reload = time.time()
    while not stop["v"]:
        t = time.time()
        try:
            sweep(store, client, pairs)
        except Exception as e:                                     # noqa: BLE001
            store.cycle(sample_ts=t, ok=False, reason="UNKNOWN", recv_ts=time.time())
            store.health("collector", "cycle_error", type(e).__name__)
            store.flush()
        if time.time() - last_reload > 1800:      # pick up newly opened markets
            try:
                pairs = load_pairs(SHADOW_DB)
                last_reload = time.time()
            except Exception:                                      # noqa: BLE001
                pass
        slept = 0.0
        while slept < SAMPLE_PERIOD_S and not stop["v"]:
            time.sleep(1.0)
            slept += 1.0
    store.health("collector", "shutdown")
    store.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

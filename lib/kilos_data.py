#!/usr/bin/env python3
"""Read-only access to Kilos' collected data.

Janus never writes to ~/Code/Kilos and imports no Kilos Python. This module is the ONLY place
that opens a Kilos database, so the invariants in Janus/SHARED_SERVICES.md are enforced once:

  * every connection is `mode=ro` + `PRAGMA query_only`
  * queries are bounded; nothing bulk-scans a live collector's DB
  * the 2026-07-17 shard boundary is handled explicitly, because the schemas are IDENTICAL and a
    pre-rotation query against the live DB silently returns ~0 rows instead of erroring
  * Kalshi price columns are normalised on read -- `kalshi_snapshots` stores PROBABILITIES in
    [0,1], not cents. A Kilos engine once priced a 30c ask as 0.3c and produced a fake
    +37.5c/trade before anyone noticed.

If you need a Kilos table not exposed here, add a function -- do not open a connection elsewhere.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

KILOS = Path.home() / "Code" / "Kilos"
PM_DB = KILOS / "DaC" / "data" / "pm_data.db"          # PM btc (5m/15m/1h/4h)
PM_XA_DB = KILOS / "DaC" / "data" / "pm_xa_data.db"    # PM eth/sol (5m/15m)
KALSHI_DB = KILOS / "DaC" / "data" / "market_data.db"  # Kalshi, POST-rotation only
KALSHI_SHARD = Path("/Volumes/Kilos/shards/market_data_20260717T043030Z.db")

# Kilos registered its KXBTC15M maker-at-open episode population as row 20 with a forward clock
# beginning 2026-07-21. Track B may use the published headline as a prior, but the underlying
# episode rows are unreadable for a Janus question. Enforce this at SQLite's authorizer boundary,
# not by convention in a future query function.
JANUS_FORBIDDEN_KILOS_TABLES = frozenset({"kalshi_open_episode_samples"})

#: Everything before this instant lives in the frozen shard, not the live DB.
ROTATION_UTC = "2026-07-17T04:30:30Z"

#: Kalshi 15m series ticker -> asset. Kalshi lists 15 fifteen-minute series as of 2026-07-24;
#: these are the 7 that have a Polymarket counterpart.
KALSHI_15M = {
    "KXBTC15M": "btc", "KXETH15M": "eth", "KXSOL15M": "sol", "KXXRP15M": "xrp",
    "KXDOGE15M": "doge", "KXBNB15M": "bnb", "KXHYPE15M": "hype",
}
PAIRED_ASSETS = tuple(KALSHI_15M.values())


def connect_ro(path: Path | str) -> sqlite3.Connection:
    """Open a Kilos DB read-only. Raises if the file is missing rather than creating one."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Kilos database not found: {p}")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")

    def _deny_spent_episode_reads(action, arg1, arg2, db_name, trigger):
        if action == sqlite3.SQLITE_READ and str(arg1).lower() in JANUS_FORBIDDEN_KILOS_TABLES:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    con.set_authorizer(_deny_spent_episode_reads)
    return con


def iso_to_unix(s: str) -> int | None:
    """Kalshi stores close_time as an ISO-8601 UTC string; PM stores unix floats."""
    if not s:
        return None
    try:
        return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def norm_price(x) -> float | None:
    """Normalise a Kalshi price to CENTS.

    `kalshi_snapshots` stores probabilities in [0,1]; other paths store cents. Kalshi's REST API
    now also returns `*_dollars` string fields. Values <= 1.0 are treated as probabilities.
    """
    if x is None or x == "":
        return None
    v = float(x)
    return v * 100.0 if v <= 1.0 else v


# ══════════════════════════════════════════════════════════════════════════
# Settled outcomes
# ══════════════════════════════════════════════════════════════════════════


def pm_settlements(assets=PAIRED_ASSETS, timeframe: str = "15m") -> dict:
    """{(asset, window_end_unix): {'resolution','window_start'}} for resolved PM windows.

    btc comes from pm_data.db; eth/sol from the isolated pm_xa_data.db. The other four paired
    assets (xrp, doge, bnb, hype) are NOT collected by Kilos at all -- absence here is a
    coverage fact, not an error.
    """
    want = set(assets)
    out = {}
    for db in (PM_DB, PM_XA_DB):
        if not db.exists():
            continue
        con = connect_ro(db)
        try:
            q = ("SELECT asset, window_start_ts, window_end_ts, resolution FROM pm_markets "
                 "WHERE timeframe=? AND resolution IN ('up','down')")
            for asset, ws, we, res in con.execute(q, (timeframe,)):
                if asset in want:
                    out[(asset, int(round(we)))] = {
                        "resolution": res, "window_start": int(round(ws))}
        finally:
            con.close()
    return out


def kalshi_settlements(assets=PAIRED_ASSETS) -> dict:
    """{(asset, close_unix): {...}} for settled 15m markets.

    Unions the frozen shard (pre-2026-07-17 history) with the live DB. Reading only the live DB
    would silently lose ~4 months of history with no error, because the schemas are identical.

    Two recoveries from `raw_json`, both load-bearing:

    * `floor_strike` -- the COLUMN is NULL for ~94% of KXETH15M/KXSOL15M markets (a Kilos ingest
      gap; the BTC series is fine). The value is present in raw_json regardless, so the column is
      only a fast path. Without this fallback the ETH/SOL mechanism analysis collapses to n=34.
    * `expiration_value` -- Kalshi's ACTUAL settlement print (its BRTI reading at close). This is
      the other venue's oracle observed directly, so the Kalshi-vs-Chainlink index difference can
      be measured rather than inferred.
    """
    import json as _json
    want = {t: a for t, a in KALSHI_15M.items() if a in set(assets)}
    if not want:
        return {}
    like = " OR ".join(f"ticker LIKE '{t}-%'" for t in want)
    out = {}
    for db, tag in ((KALSHI_SHARD, "shard"), (KALSHI_DB, "live")):
        if not db.exists():
            continue
        con = connect_ro(db)
        try:
            q = ("SELECT ticker, close_time, result, floor_strike, raw_json FROM kalshi_markets "
                 f"WHERE result IN ('yes','no') AND ({like})")
            for ticker, ct, res, fs, raw in con.execute(q):
                series = ticker.split("-")[0]
                asset = want.get(series)
                t = iso_to_unix(ct)
                if asset is None or t is None:
                    continue
                settle = None
                fs_src = "column"
                if raw:
                    try:
                        j = _json.loads(raw)
                    except (ValueError, TypeError):
                        j = {}
                    if not fs:
                        v = j.get("floor_strike")
                        if v not in (None, "", 0):
                            fs, fs_src = float(v), "raw_json"
                    ev = j.get("expiration_value")
                    if ev not in (None, ""):
                        try:
                            settle = float(ev)
                        except ValueError:
                            settle = None
                # live DB wins on collision (it is the fresher write of the same market)
                out[(asset, t)] = {"result": res, "floor_strike": fs,
                                   "floor_strike_source": fs_src if fs else None,
                                   "settle_value": settle,
                                   "ticker": ticker, "source": tag}
        finally:
            con.close()
    return out


def matched_settlements(assets=PAIRED_ASSETS, timeframe: str = "15m") -> list[dict]:
    """Inner-join both venues on EXACT close time. One row per jointly-settled window.

    `agree` is the field the whole project turns on: True when a cross-venue two-leg position
    pays 100c, False when both legs lose.
    """
    pm = pm_settlements(assets, timeframe)
    kal = kalshi_settlements(assets)
    rows = []
    for key in sorted(set(pm) & set(kal)):
        asset, close_ts = key
        p, k = pm[key], kal[key]
        pm_up = p["resolution"] == "up"
        k_yes = k["result"] == "yes"
        rows.append({
            "asset": asset, "close_ts": close_ts,
            "window_start": p["window_start"],
            "open_date": dt.datetime.fromtimestamp(close_ts, dt.UTC).strftime("%Y-%m-%d"),
            "pm_resolution": p["resolution"], "kalshi_result": k["result"],
            "pm_up": pm_up, "kalshi_yes": k_yes,
            "agree": pm_up == k_yes,
            "floor_strike": k["floor_strike"],
            "floor_strike_source": k["floor_strike_source"],
            "kalshi_settle_value": k["settle_value"],
            "kalshi_ticker": k["ticker"],
            "kalshi_source": k["source"],
        })
    return rows


# ══════════════════════════════════════════════════════════════════════════
# Quotes
# ══════════════════════════════════════════════════════════════════════════


def pm_quote_at(con: sqlite3.Connection, condition_id: str, ts: float,
                lookback_s: float = 90.0) -> dict | None:
    """Most recent PM quote at or before `ts`, within `lookback_s`. Bounded by design."""
    r = con.execute(
        "SELECT timestamp, up_bid, up_ask, up_mid, dn_bid, dn_ask, dn_mid, book_age_sec "
        "FROM pm_quotes WHERE condition_id=? AND timestamp<=? AND timestamp>=? "
        "ORDER BY timestamp DESC LIMIT 1",
        (condition_id, ts, ts - lookback_s)).fetchone()
    if not r:
        return None
    cols = ("timestamp", "up_bid", "up_ask", "up_mid", "dn_bid", "dn_ask", "dn_mid", "book_age_sec")
    return dict(zip(cols, r))


def pm_final_mid_map(assets=PAIRED_ASSETS, timeframe: str = "15m",
                     lookback_s: float = 90.0) -> dict:
    """{(asset, close_unix): up_mid} -- PM's own mid in the final `lookback_s` of each window.

    This is the market's closing opinion. Only knowable AT the close, so it is a diagnostic for
    characterising disagreement, NOT an entry-time signal. Do not build a rule on it.
    """
    want = set(assets)
    out = {}
    for db in (PM_DB, PM_XA_DB):
        if not db.exists():
            continue
        con = connect_ro(db)
        try:
            q = """SELECT m.asset, m.window_end_ts,
                     (SELECT q.up_mid FROM pm_quotes q
                      WHERE q.condition_id=m.condition_id
                        AND q.timestamp < m.window_end_ts
                        AND q.timestamp >= m.window_end_ts - ?
                        AND q.up_mid IS NOT NULL
                      ORDER BY q.timestamp DESC LIMIT 1)
                   FROM pm_markets m
                   WHERE m.timeframe=? AND m.resolution IN ('up','down')"""
            for asset, we, mid in con.execute(q, (lookback_s, timeframe)):
                if asset in want and mid is not None:
                    out[(asset, int(round(we)))] = float(mid)
        finally:
            con.close()
    return out


def coverage_report() -> dict:
    """What Kilos actually holds, per venue and asset. Run this before trusting any join."""
    rep = {"rotation_boundary_utc": ROTATION_UTC, "pm": {}, "kalshi": {}}
    pm = pm_settlements()
    kal = kalshi_settlements()
    for a in PAIRED_ASSETS:
        pk = [t for (x, t) in pm if x == a]
        kk = [t for (x, t) in kal if x == a]
        rep["pm"][a] = _span(pk)
        rep["kalshi"][a] = _span(kk)
    return rep


def _span(ts: list[int]) -> dict:
    if not ts:
        return {"n": 0, "first": None, "last": None}
    return {"n": len(ts),
            "first": dt.datetime.fromtimestamp(min(ts), dt.UTC).strftime("%Y-%m-%d"),
            "last": dt.datetime.fromtimestamp(max(ts), dt.UTC).strftime("%Y-%m-%d")}


if __name__ == "__main__":
    import json
    print(json.dumps(coverage_report(), indent=1))

#!/usr/bin/env python3
"""Compact storage for targeted tuple sweeps.

The collector deliberately does not write a snapshot of the whole venue universe.  It keeps one
current row per watched market, appends a quote row only when a best price/depth/state changes
materially, appends tuple rows only when actionability changes, and writes one aggregate row per
sweep.  Normalized ladders are retained only on those material quote changes; venue response
payloads are never persisted.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


from kernel.paths import DB as DEFAULT_DB, guard  # noqa: E402

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS latest_markets(
  venue TEXT NOT NULL, market_id TEXT NOT NULL, family TEXT NOT NULL, event_key TEXT,
  outcome TEXT, category TEXT, created_ts REAL, close_ts REAL, status TEXT,
  settlement_ref TEXT, watch_tier TEXT, last_seen_ts REAL NOT NULL, metadata_json TEXT,
  PRIMARY KEY(venue, market_id));
CREATE TABLE IF NOT EXISTS latest_quotes(
  venue TEXT NOT NULL, market_id TEXT NOT NULL, seen_ts REAL NOT NULL,
  best_bid REAL, best_ask REAL, bid_depth REAL, ask_depth REAL,
  n_bid_levels INTEGER, n_ask_levels INTEGER, two_sided INTEGER, levels_json TEXT,
  PRIMARY KEY(venue, market_id));
CREATE TABLE IF NOT EXISTS quote_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL,
  venue TEXT NOT NULL, market_id TEXT NOT NULL, best_bid REAL, best_ask REAL,
  bid_depth REAL, ask_depth REAL, n_bid_levels INTEGER, n_ask_levels INTEGER,
  two_sided INTEGER, levels_json TEXT, material_reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS quote_history_market ON quote_history(venue, market_id, seen_ts);
CREATE TABLE IF NOT EXISTS latest_opportunities(
  tuple_id TEXT PRIMARY KEY, seen_ts REAL NOT NULL, relation_type TEXT NOT NULL,
  status TEXT NOT NULL, gross_cost REAL, fees REAL, net_profit REAL,
  return_locked REAL, capacity REAL, fingerprint TEXT NOT NULL, details_json TEXT);
CREATE TABLE IF NOT EXISTS opportunity_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, tuple_id TEXT NOT NULL,
  relation_type TEXT NOT NULL, status TEXT NOT NULL, gross_cost REAL, fees REAL,
  net_profit REAL, return_locked REAL, capacity REAL, fingerprint TEXT NOT NULL,
  details_json TEXT);
CREATE INDEX IF NOT EXISTS opportunity_history_tuple ON opportunity_history(tuple_id, seen_ts);
CREATE TABLE IF NOT EXISTS sweep_runs(
  sweep_id TEXT PRIMARY KEY, started_ts REAL NOT NULL, finished_ts REAL,
  universe TEXT NOT NULL, n_discovered INTEGER DEFAULT 0, n_watched INTEGER DEFAULT 0,
  n_changed INTEGER DEFAULT 0, n_opportunities INTEGER DEFAULT 0,
  status TEXT NOT NULL, error TEXT);
-- Streaming cover evaluations. The lane re-prices on every book event, ~200/s across a few
-- games, so writing all of them is neither affordable nor useful: most are identical. Rows land
-- on a MATERIAL move in cover cost (default 0.1c, a tenth of a Kalshi tick) or on a heartbeat, so
-- the series can be carried forward and the distribution reconstructed without storing noise.
CREATE TABLE IF NOT EXISTS stream_evaluations(
  seen_ts REAL NOT NULL, game_id TEXT NOT NULL, league TEXT NOT NULL, quantity REAL NOT NULL,
  status TEXT NOT NULL, cost REAL, gross REAL, fees REAL, return_locked REAL,
  required_ask_sum REAL, cents_from_actionable REAL,
  blocked_by TEXT, triggered_by TEXT, latency_ms REAL, legs_json TEXT);
CREATE INDEX IF NOT EXISTS stream_evaluations_game ON stream_evaluations(game_id, quantity, seen_ts);
CREATE INDEX IF NOT EXISTS stream_evaluations_ts ON stream_evaluations(seen_ts);
CREATE TABLE IF NOT EXISTS cloudbet_acceptances(
  reference_id TEXT PRIMARY KEY, state TEXT NOT NULL, event_id TEXT NOT NULL,
  market_url TEXT NOT NULL, requested_price REAL NOT NULL, requested_stake REAL NOT NULL,
  currency TEXT NOT NULL, accept_price_change TEXT NOT NULL, accept_partial_stake INTEGER NOT NULL,
  accepted_price REAL,
  accepted_stake REAL, provider_status TEXT NOT NULL, error TEXT NOT NULL,
  observed_ts REAL NOT NULL);
"""


def _rel_change(new: float | None, old: float | None) -> float:
    if new is None or old is None:
        return 1.0 if new != old else 0.0
    if old == 0:
        return 1.0 if new != 0 else 0.0
    return abs(new - old) / abs(old)


class TupleStore:
    def __init__(self, path: Path | str = DEFAULT_DB, *, enforce_volume: bool = True, check_same_thread: bool = True,
                 isolation_level: str | None = ""):
        p = Path(path).resolve()
        if enforce_volume:
            guard(p, "tuple data")
        p.parent.mkdir(parents=True, exist_ok=True)
        # The live lane holds write transactions on the shared file; a second writer (a proof, a
        # settle) must wait for it, not die with "database is locked" (seen 2026-09-03 on the
        # first armed proof attempt). 30 s is far longer than any lane transaction.
        # `check_same_thread=False` is for a SECOND store on the same file that one other thread
        # uses alone (the execution worker's journal and records, grids/live_stream/grid.py,
        # 2026-09-08): a connection is never used by two threads at once (Python's sqlite3 raises
        # "API misuse" when it is), WAL lets the two connections write in turn, and the 30 s busy
        # timeout covers the wait. That second store opens with isolation_level="IMMEDIATE": its
        # writes begin with BEGIN IMMEDIATE, so a wait for the loop's lock goes through the busy
        # handler instead of failing at once as a read-snapshot upgrade ("database is locked",
        # the first flight through it, 01:17Z).
        self.con = sqlite3.connect(str(p), timeout=30.0, check_same_thread=check_same_thread, isolation_level=isolation_level)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(DDL)
        #: (game_id, quantity) -> (status, cost, ts) for the material-change gate on evaluations.
        self._eval_last: dict[tuple, tuple] = {}
        self._ddl_applied: set[str] = set()

    def ensure_ddl(self, ddl: str) -> None:
        """A node owns its own tables. Idempotent (CREATE IF NOT EXISTS); call before the first
        write. This is how new nodes add storage without everyone editing one DDL string."""
        if ddl in self._ddl_applied:
            return
        self.con.executescript(ddl)
        self._ddl_applied.add(ddl)

    def market(self, *, venue: str, market_id: str, family: str, event_key: str,
               outcome: str, category: str, created_ts: float | None,
               close_ts: float | None, status: str, settlement_ref: str,
               watch_tier: str, metadata: dict[str, Any] | None = None,
               seen_ts: float | None = None) -> None:
        ts = seen_ts or time.time()
        compact = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
        self.con.execute("""
          INSERT INTO latest_markets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(venue, market_id) DO UPDATE SET
            family=excluded.family, event_key=excluded.event_key, outcome=excluded.outcome,
            category=excluded.category, created_ts=excluded.created_ts, close_ts=excluded.close_ts,
            status=excluded.status, settlement_ref=excluded.settlement_ref,
            watch_tier=excluded.watch_tier, last_seen_ts=excluded.last_seen_ts,
            metadata_json=excluded.metadata_json
        """, (venue, market_id, family, event_key, outcome, category, created_ts, close_ts,
               status, settlement_ref, watch_tier, ts, compact))

    def quote(self, *, venue: str, market_id: str, best_bid: float | None,
              best_ask: float | None, bid_depth: float | None, ask_depth: float | None,
              n_bid_levels: int, n_ask_levels: int, two_sided: bool,
              levels: list[dict[str, Any]] | None = None, tick: float = 0.01,
              seen_ts: float | None = None) -> bool:
        ts = seen_ts or time.time()
        old = self.con.execute("""
          SELECT best_bid,best_ask,bid_depth,ask_depth,n_bid_levels,n_ask_levels,two_sided
          FROM latest_quotes WHERE venue=? AND market_id=?
        """, (venue, market_id)).fetchone()
        reasons: list[str] = []
        if old is None:
            reasons.append("FIRST_SEEN")
        else:
            if (best_bid is None) != (old[0] is None) or (best_ask is None) != (old[1] is None):
                reasons.append("ONE_SIDED_CHANGE")
            if best_bid is not None and old[0] is not None and abs(best_bid - old[0]) >= tick:
                reasons.append("BID_TICK")
            if best_ask is not None and old[1] is not None and abs(best_ask - old[1]) >= tick:
                reasons.append("ASK_TICK")
            if _rel_change(bid_depth, old[2]) >= 0.10 or _rel_change(ask_depth, old[3]) >= 0.10:
                reasons.append("DEPTH_10PCT")
            if n_bid_levels != old[4] or n_ask_levels != old[5]:
                reasons.append("LEVEL_COUNT")
            if bool(two_sided) != bool(old[6]):
                reasons.append("STATE_CHANGE")
        reason = ",".join(dict.fromkeys(reasons))
        compact_levels = json.dumps(levels or [], sort_keys=True, separators=(",", ":"))
        if reason:
            self.con.execute("""
              INSERT INTO quote_history(seen_ts,venue,market_id,best_bid,best_ask,bid_depth,ask_depth,
                n_bid_levels,n_ask_levels,two_sided,levels_json,material_reason)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (ts, venue, market_id, best_bid, best_ask, bid_depth, ask_depth,
                   n_bid_levels, n_ask_levels, int(two_sided), compact_levels, reason))
        self.con.execute("""
          INSERT INTO latest_quotes VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(venue, market_id) DO UPDATE SET
            seen_ts=excluded.seen_ts,best_bid=excluded.best_bid,best_ask=excluded.best_ask,
            bid_depth=excluded.bid_depth,ask_depth=excluded.ask_depth,
            n_bid_levels=excluded.n_bid_levels,n_ask_levels=excluded.n_ask_levels,
            two_sided=excluded.two_sided,levels_json=excluded.levels_json
        """, (venue, market_id, ts, best_bid, best_ask, bid_depth, ask_depth,
               n_bid_levels, n_ask_levels, int(two_sided), compact_levels))
        return bool(reason)

    def opportunity(self, *, tuple_id: str, relation_type: str, status: str,
                    gross_cost: float | None, fees: float | None, net_profit: float | None,
                    return_locked: float | None, capacity: float | None,
                    details: dict[str, Any] | None = None, seen_ts: float | None = None) -> bool:
        ts = seen_ts or time.time()
        # A price move smaller than a cent and an unchanged capacity band do not deserve a row.
        fingerprint = json.dumps({
            "status": status,
            "gross_cost": None if gross_cost is None else round(gross_cost, 2),
            "fees": None if fees is None else round(fees, 2),
            "net_profit": None if net_profit is None else round(net_profit, 2),
            "capacity": None if capacity is None else round(capacity, 2),
        }, sort_keys=True, separators=(",", ":"))
        old = self.con.execute(
            "SELECT fingerprint FROM latest_opportunities WHERE tuple_id=?", (tuple_id,)
        ).fetchone()
        changed = old is None or old[0] != fingerprint
        compact = json.dumps(details or {}, sort_keys=True, separators=(",", ":"))
        if changed:
            self.con.execute("""
              INSERT INTO opportunity_history(seen_ts,tuple_id,relation_type,status,gross_cost,fees,
                net_profit,return_locked,capacity,fingerprint,details_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (ts, tuple_id, relation_type, status, gross_cost, fees, net_profit,
                   return_locked, capacity, fingerprint, compact))
        self.con.execute("""
          INSERT INTO latest_opportunities VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(tuple_id) DO UPDATE SET
            seen_ts=excluded.seen_ts,relation_type=excluded.relation_type,status=excluded.status,
            gross_cost=excluded.gross_cost,fees=excluded.fees,net_profit=excluded.net_profit,
            return_locked=excluded.return_locked,capacity=excluded.capacity,
            fingerprint=excluded.fingerprint,details_json=excluded.details_json
        """, (tuple_id, ts, relation_type, status, gross_cost, fees, net_profit,
               return_locked, capacity, fingerprint, compact))
        return changed

    def sweep(self, *, sweep_id: str, started_ts: float, finished_ts: float | None,
              universe: str, n_discovered: int, n_watched: int, n_changed: int,
              n_opportunities: int, status: str, error: str | None = None) -> None:
        self.con.execute("""
          INSERT OR REPLACE INTO sweep_runs VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (sweep_id, started_ts, finished_ts, universe, n_discovered, n_watched,
               n_changed, n_opportunities, status, error))

    def put_cloudbet_acceptance(self, result) -> None:
        """Persist acceptance economics and state, never the provider response payload.

        This commits immediately because the caller writes PENDING immediately before a
        non-retried POST. A process crash after the POST must still leave a reference that can be
        reconciled instead of being mistaken for a no-op.
        """
        self.con.execute("""
          INSERT INTO cloudbet_acceptances(
            reference_id,state,event_id,market_url,requested_price,requested_stake,currency,
            accept_price_change,accept_partial_stake,accepted_price,accepted_stake,provider_status,error,observed_ts)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(reference_id) DO UPDATE SET
            state=excluded.state,event_id=excluded.event_id,market_url=excluded.market_url,
            requested_price=excluded.requested_price,requested_stake=excluded.requested_stake,
            currency=excluded.currency,accept_price_change=excluded.accept_price_change,
            accept_partial_stake=excluded.accept_partial_stake,
            accepted_price=excluded.accepted_price,accepted_stake=excluded.accepted_stake,
            provider_status=excluded.provider_status,error=excluded.error,
            observed_ts=excluded.observed_ts
        """, (result.reference_id, result.state.value, result.event_id, result.market_url,
               result.requested_price, result.requested_stake, result.currency,
               result.accept_price_change, int(result.accept_partial_stake),
               result.accepted_price, result.accepted_stake,
               result.provider_status, result.error, result.observed_utc))
        self.con.commit()

    def get_cloudbet_acceptance(self, reference_id: str):
        row = self.con.execute("""
          SELECT reference_id,state,event_id,market_url,requested_price,requested_stake,currency,
                 accept_price_change,accept_partial_stake,accepted_price,accepted_stake,provider_status,error,observed_ts
          FROM cloudbet_acceptances WHERE reference_id=?
        """, (reference_id,)).fetchone()
        if row is None:
            return None
        from nodes.venue_cloudbet.trading import AcceptanceState, CloudbetAcceptance
        return CloudbetAcceptance(
            reference_id=row[0], state=AcceptanceState(row[1]), event_id=row[2], market_url=row[3],
            requested_price=row[4], requested_stake=row[5], currency=row[6],
            accept_price_change=row[7], accept_partial_stake=bool(row[8]), accepted_price=row[9],
            accepted_stake=row[10], provider_status=row[11], error=row[12], observed_utc=row[13],
        )

    def evaluation(self, *, game_id: str, league: str, quantity: float, status: str,
                   cost: float | None, gross: float | None, fees: float | None,
                   return_locked: float | None, required_ask_sum: float | None,
                   cents_from_actionable: float | None, blocked_by: str | None,
                   triggered_by: str, latency_ms: float, legs: list | None = None,
                   seen_ts: float | None = None, epsilon: float = 0.001,
                   heartbeat_s: float = 15.0) -> bool:
        """Record one streaming evaluation, gated on a MATERIAL move.

        The lane prices on every book event -- roughly 200/s across a handful of games -- and most
        of those are byte-identical to the last one. Writing all of them buys nothing and costs a
        gigabyte a day. A row lands when the cover cost moves by `epsilon` (default 0.1c, a tenth
        of a Kalshi tick), when the status changes, or on a heartbeat, which is enough to carry the
        series forward and reconstruct the distribution.

        Blocked evaluations are recorded too. "Could not price, and here is why" is what separates
        no-edge from no-data, and it is the channel that was a header-only CSV all August.
        """
        ts = seen_ts if seen_ts is not None else time.time()
        key = (game_id, quantity)
        prev = self._eval_last.get(key)
        material = (
            prev is None
            or prev[0] != status
            or (cost is None) != (prev[1] is None)
            or (cost is not None and prev[1] is not None and abs(cost - prev[1]) >= epsilon)
            or (ts - prev[2]) >= heartbeat_s)
        if not material:
            return False
        self.con.execute(
            """INSERT INTO stream_evaluations(seen_ts,game_id,league,quantity,status,cost,gross,
                 fees,return_locked,required_ask_sum,cents_from_actionable,blocked_by,triggered_by,
                 latency_ms,legs_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts, game_id, league, quantity, status, cost, gross, fees, return_locked,
             required_ask_sum, cents_from_actionable, blocked_by, triggered_by, latency_ms,
             json.dumps(legs or [], separators=(",", ":"))))
        self._eval_last[key] = (status, cost, ts)
        return True

    SOCKET_HEALTH_DDL = """
CREATE TABLE IF NOT EXISTS socket_health(
  seen_ts REAL NOT NULL, venue TEXT NOT NULL, connected INTEGER, subscriptions INTEGER,
  frames INTEGER, snapshots INTEGER, updates INTEGER, seq_gaps INTEGER, drift INTEGER,
  agreement REAL, errors INTEGER, clock_offset_s REAL, clock_healthy INTEGER, age_s REAL,
  last_error TEXT, loop_lag_s REAL);
CREATE INDEX IF NOT EXISTS socket_health_ts ON socket_health(venue, seen_ts);
"""

    def _add_column_if_missing(self, table: str, column: str, decl: str) -> None:
        """A column added after the table shipped. CREATE IF NOT EXISTS leaves an old table as it
        was, so a new column is an ALTER, once, guarded."""
        cols = {r[1] for r in self.con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            self.con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def socket_health(self, *, venue: str, stats: dict[str, Any], seen_ts: float | None = None) -> None:
        """One row per report tick per socket. This used to live only in stdout, which is not
        rotated; a run's frame counts, gaps, drift rate and agreement survived nowhere.
        `loop_lag_s` (2026-09-04) is the supervisor's event-loop stall since the last tick: the
        receive timestamps behind every freshness bound are only as good as the loop is prompt."""
        if self.SOCKET_HEALTH_DDL not in self._ddl_applied:
            self.ensure_ddl(self.SOCKET_HEALTH_DDL)
            self._add_column_if_missing("socket_health", "loop_lag_s", "REAL")
        clock = stats.get("clock") or {}
        self.con.execute(
            "INSERT INTO socket_health(seen_ts, venue, connected, subscriptions, frames, snapshots, updates, seq_gaps, "
            "drift, agreement, errors, clock_offset_s, clock_healthy, age_s, last_error, loop_lag_s) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (seen_ts or time.time(), venue, int(bool(stats.get("connected"))),
             stats.get("tickers", stats.get("assets")), stats.get("frames"), stats.get("snapshots"),
             stats.get("deltas", stats.get("changes")), stats.get("seq_gaps"), stats.get("drift"),
             stats.get("agreement"), stats.get("errors"), clock.get("offset_s"),
             None if clock.get("healthy") is None else int(bool(clock["healthy"])),
             stats.get("age_s"), stats.get("last_error") or None, stats.get("loop_lag_s")))

    def commit(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.commit()
        self.con.close()


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        s = TupleStore(Path(d) / "selftest.sqlite", enforce_volume=False)
        s.market(venue="x", market_id="m", family="f", event_key="e", outcome="o",
                 category="c", created_ts=1, close_ts=2, status="active", settlement_ref="r",
                 watch_tier="newborn")
        assert s.quote(venue="x", market_id="m", best_bid=.4, best_ask=.5, bid_depth=10,
                       ask_depth=10, n_bid_levels=1, n_ask_levels=1, two_sided=True)
        assert not s.quote(venue="x", market_id="m", best_bid=.4, best_ask=.5, bid_depth=10,
                           ask_depth=10, n_bid_levels=1, n_ask_levels=1, two_sided=True)
        assert s.opportunity(tuple_id="t", relation_type="pair", status="ACTIONABLE",
                             gross_cost=.8, fees=.01, net_profit=.19, return_locked=.23, capacity=5)
        assert not s.opportunity(tuple_id="t", relation_type="pair", status="ACTIONABLE",
                                 gross_cost=.8, fees=.01, net_profit=.19, return_locked=.23, capacity=5)
        s.commit(); s.close()
    print("tuple_store selftest OK")

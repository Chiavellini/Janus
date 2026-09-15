#!/usr/bin/env python3
"""The supervisor: one poller per live co-listed game, fed by two shared sockets.

    python3 -m grids.live_stream.grid --leagues mlb --pre-hours 2
    python3 -m grids.live_stream.grid --leagues mlb --once      # one discovery pass, then exit

WHAT IT OWNS. The lifecycle. It rebuilds the slate on its own slow clock, spawns a
`nodes/game_poller` for every game that is live and co-listed on both venues, registers that
poller's replicas with the two shared sockets, and reaps the poller when the game settles. The
sockets and the pricing are owned elsewhere; this is the thing that decides what exists.

WHY THE SOCKETS ARE SHARED AND THE POLLERS ARE NOT. Kalshi authenticates one connection and
multiplexes by market_ticker; Polymarket takes an assets_ids list on one socket and supports
mid-connection subscribe/unsubscribe. A socket per game would mean an RSA handshake per game and N
connections against each venue's limit for no gain. So connections are infrastructure, pollers are
actors, and a game starting or ending costs a subscription frame rather than a reconnect.

WHAT IT WRITES. Every evaluation is offered to the store, which gates on a material move in cover
cost (0.1c, a tenth of a Kalshi tick) or a heartbeat. At ~200 evaluations a second across a handful
of games, writing all of them would cost a gigabyte a day of near-identical rows and answer nothing
that carrying the series forward does not. Blocked evaluations are written too: "could not price,
and here is why" is what separates no-edge from no-data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]


class DiskPressure(RuntimeError):
    """The data volume is under the running floor (L72, 2026-09-11: the lane died inside a
    commit at 0 bytes free, then restart-looped 753 times). Raised on the report tick so the
    process stops between records, and main() exits 75 -- the runner's own df-guard code, which
    then holds the restart until space exists."""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kernel.fetch import Client  # noqa: E402
from kernel.redact import brief_error  # noqa: E402
from nodes.capture.capture import FRAMES_ROOT, FrameWriter, prune_days  # noqa: E402
from nodes.cover.capacity import frontier, slippage_for  # noqa: E402
from nodes.cover.cover import walk_ladder  # noqa: E402
from nodes.risk.flags import raise_flag  # noqa: E402
from nodes.discovery.watchlist import Watchlist, kalshi_watch, pm_watch_events  # noqa: E402
from nodes.watch_settle.settle import record_watch  # noqa: E402
from nodes.entities.leagues import LEAGUES, default_leagues  # noqa: E402
from nodes.discovery.discovery import co_listed, discover, first_seen, record_events, record_spawn_block  # noqa: E402
from nodes.slate.slate import next_transition, windows_for  # noqa: E402
from nodes.execute.coordinator import Coordinator  # noqa: E402
from nodes.execute.maker import (HedgeLevel, MakerFillSession, MakerRestAuthorization,
                                 MakerRestInputs, book_fingerprint)  # noqa: E402
from nodes.execute.sizing import SizingDecision, choose_live_size  # noqa: E402
from nodes.execute.guard import PositionGuard  # noqa: E402
from nodes.execute.on_loop import OnLoop  # noqa: E402
from nodes.execute.plan import maker_plan_from_cover, plan_from_cover, marginal_price  # noqa: E402
from nodes.execute.entry_experiment import (F22_ROW_ID, F23_ROW_ID, EntryArmAssignment, assign_entry_arm,
                                             assign_f23_entry_arm, assignment_from_record, f22_activation,
                                             f23_activation, first_three_fills_reconciled, record_f22_decision,
                                             record_f23_decision, update_f22_decision, update_f23_decision)  # noqa: E402
from nodes.execute.records import ExecutionRecords  # noqa: E402
from nodes.execute.venues import build_venues  # noqa: E402
from nodes.exec_kalshi.client import DEMO_BASE, PROD_BASE, KalshiExecution  # noqa: E402
from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport, TransportUnavailable  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.opportunity.opportunity import books_snapshot  # noqa: E402
from nodes.opportunity.thresholds import STRATEGY_VERSION  # noqa: E402
from nodes.reconcile.settle_executions import apply_settlements, fetch_results, pending  # noqa: E402
from nodes.risk.breaker import LossBreaker  # noqa: E402
from nodes.risk.clearance import Candidate, clear, clear_protect  # noqa: E402
from nodes.risk.gate import OVERRIDE_PATH, override_state, resolve_mode, stale_reason  # noqa: E402
from kernel.code_sha import code_tree_sha, runner_head_sha  # noqa: E402
from nodes.risk.kill import KillSwitches  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.risk.limits import RiskLimits, load_limits  # noqa: E402
from nodes.game_poller.poller import GamePoller, PollerState, eval_interval_for  # noqa: E402
from nodes.settle_wedge.equivalence import SettlementEquivalence  # noqa: E402
from nodes.settle_wedge.pair import certify_from_spec  # noqa: E402
from nodes.opportunity.opportunity import Opportunity, OpportunityStore  # noqa: E402
from nodes.opportunity.record import record_evaluation  # noqa: E402
from kernel.schema import Mode, OpportunityStatus  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.stream_kalshi.stream import KalshiStream, load_private_key  # noqa: E402
from nodes.stream_polymarket.reconcile import Reconciler  # noqa: E402
from nodes.stream_polymarket.stream import PolymarketStream  # noqa: E402
from nodes.venue_polymarket.books import PM_CLOB, pm_book  # noqa: E402
from ops import run_index  # noqa: E402
from nodes.opportunity.thresholds import EXECUTION_MIN_LOCKED_RETURN  # noqa: E402

from kernel.paths import DATA_ROOT, DB  # noqa: E402,F401
#: The size ladder. 25 and 100 were dropped for the 2026-09-14 measurement run: the operator's
#: standing rule is the smallest size that still executes, and 10 is where the evidence puts it.
#: Measured over 24 h of the box's own evaluations, a 10-contract ceiling keeps **516 of 590**
#: actionable prints (87 %) and loses **none at all** to the $0.05 dollar floor, while 5 loses 87 of
#: 375 (23 %) to it. And of the eleven real overfills to date, five exceed the one-contract accepted
#: excess at 25 but only two do at 10 -- going on down to 5 removes none of the remaining two, so 10
#: is where the overfill benefit stops and the surface starts costing. The venues' own computed
#: smallest size is a separate rung and is unaffected. Signed cap (25) unchanged and still enforced:
#: this is a tightening under it, not a new authority.
QUANTITIES = (5.0, 10.0)
#: L79: the frontier report is solved at most once per game per period (every rung of an epoch
#: shares it); sizing itself is gated in Supervisor._worth_sizing.
FRONTIER_PERIOD_S = 5.0   # 10 added 2026-09-07: under a $12 per-order cap only 5 fit, and 5 nets under the floor
MIN_RETURN = EXECUTION_MIN_LOCKED_RETURN   # one source: nodes/opportunity/thresholds.py
#: A game is priced at most this often on quiet books (nodes/game_poller coalescing); a replica
#: state change or the 15 s heartbeat still prices immediately. 2026-09-04: from ~3,400 to a few
#: hundred evaluations a second. Captures before the sha that introduced it replay to different rows.
EVAL_INTERVAL_S = 0.2
#: How often finished games' executions are settled against the venues' results (PAPER and above).
SETTLE_PERIOD_S = 300.0
VENUE_DATE_ZONE = ZoneInfo("America/New_York")


def _f23_audit_context(sup: Supervised, evaluated_utc: float) -> dict[str, object]:
    """Return immutable event/date fields for the F23 decision audit.

    The venue-date basis is the event start in America/New_York, not the process wall clock. A
    missing supervised start is only a discovery-data gap, so retain an explicit evaluated-time
    fallback rather than silently omitting the field.
    """
    event_start_utc = float(sup.start_utc if sup.start_utc is not None else evaluated_utc)
    return {
        "league": str(sup.league or sup.poller.league),
        "event_start_utc": event_start_utc,
        "league_local_date": datetime.fromtimestamp(event_start_utc, VENUE_DATE_ZONE).date().isoformat(),
    }


@dataclass
class Supervised:
    poller: GamePoller
    short_name: str
    started_utc: float
    kalshi_tickers: tuple[str, ...] = ()
    pm_assets: tuple[str, ...] = ()
    fee_params: dict = field(default_factory=dict)
    execution_spec: str = ""
    discovery_block: str | None = None
    evaluations: int = 0
    written: int = 0
    #: L79 (L78 profile: the sizing sweep was 55 % of the loop, on epochs that could select
    #: nothing). Whether the event's last recorded sizing decision selected something (the
    #: L74 exit is still recorded), when the frontier was last solved, and epochs not sized.
    last_sizing_executable: bool | None = None
    last_frontier_utc: float = 0.0
    sizing_skipped: int = 0
    #: The board (ops/box/board_server.py): slate tier, start time, the last evaluation's all-in
    #: cost and status, refreshed by _on_update; written every second by write_board().
    tier: str = ""
    start_utc: float | None = None
    league: str = ""
    last_status: str = ""
    last_cost: float | None = None
    last_eval_utc: float = 0.0


@dataclass
class Supervisor:
    leagues: list[str]
    pre_hours: float = 2.0
    db: Path = DB
    max_book_age_s: float = 5.0

    live: dict[str, Supervised] = field(default_factory=dict)
    ks: KalshiStream | None = None
    ps: PolymarketStream | None = None
    store: TupleStore | None = None
    #: A second connection to the same file for the execution worker's journal and records: one
    #: thread per connection, never marshalled (2026-09-08). Paper modes use it on the loop.
    worker_store: TupleStore | None = None
    opportunities: OpportunityStore | None = None
    #: The execution side. None below PAPER_EXECUTION: detection only.
    mode: Mode = Mode.SHADOW_LIVE
    coordinator: Coordinator | None = None
    venues: dict = field(default_factory=dict)
    limits: object | None = None
    #: The arming override's caps (stake_usd, max_contracts, day_notional_usd), as the risk gate
    #: resolved them. Empty below LIMITED_LIVE. clear() refuses a capital-risking order without them.
    caps: dict = field(default_factory=dict)
    #: The code tree this process runs (kernel/code_sha), fixed at start; what the override must pin.
    code_sha: str = "unknown"
    override_path: Path = OVERRIDE_PATH
    #: Set by check_arm() on the report tick when a capital-risking mode's override has expired
    #: or stopped matching: _execute refuses every real order (ARM_STALE) until it clears.
    #: Pricing continues. Until 2026-09-07 an expired override stopped nothing already running.
    arm_stale: str | None = None
    #: F22 is a separate signed authority layered on LIMITED_LIVE. A normal live override keeps
    #: the historical taker path. Persistence failure is an in-memory entry stop until restart.
    f22_enabled: bool = False
    f22_authority_detail: str = "not checked"
    f22_failed: bool = False
    #: F23 is a fresh cohort with its own table, assignment digest and signed authority. It never
    #: reads or pools F22 decisions (including F22's first-three checkpoint).
    f23_enabled: bool = False
    f23_authority_detail: str = "not checked"
    f23_failed: bool = False
    ledger: ExposureLedger | None = None
    kill: KillSwitches | None = None
    breaker: LossBreaker | None = None
    executions: int = 0
    spawned: int = 0
    reaped: int = 0
    blocked: dict[str, str] = field(default_factory=dict)
    #: Last fully built executable specs. A transient schedule failure keeps socket actors warm
    #: but suspends evaluation; it never trades stale state or pays a five-minute cold start.
    last_specs: dict[str, dict] = field(default_factory=dict)
    #: (game_id, exception class) -> count of evaluations whose record raised; see _on_update.
    record_errors: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Event-loop stall since the last report tick: the worst overshoot of a 250 ms sleep, and the
    #: readings, from the probe in run(). A stalled loop stamps every received frame late, so
    #: every freshness bound is off by this much (2026-09-04: 10-100 s on a starved host).
    loop_lag_max_s: float = 0.0
    loop_lag_readings: list = field(default_factory=list)
    #: The bound past which the loop's own lag halts pricing, same figure as the clock's.
    max_loop_lag_s: float = 5.0
    #: L72: the running floor, the same figure the runner enforces at start (ops/run_node.sh
    #: MINFREE_KB). Under it the report tick raises DiskPressure and main() exits 75, between
    #: records rather than half-way through one. `disk_usage` is injectable for tests.
    disk_floor_bytes: int = _env_int("JANUS_MINFREE_KB", 2097152) * 1024
    disk_usage: object = shutil.disk_usage
    #: L72: age-based retention of the observation series (store.RETENTION_TABLES, nothing else
    #: is reachable) and of raw frame days, from a worker thread on its own connection. 0 disables.
    retain_days: int = 7
    retain_period_s: float = 900.0
    retain_budget_s: float = 10.0
    last_retain: float = 0.0
    #: The data-volume guard on the retention connection; tests on a tmp path turn it off.
    enforce_volume: bool = True
    #: The last tick's verdict on the loop; what the risk gate sees between ticks.
    stalled: bool = False
    #: Report ticks since the loop last overshot. The clock's window is 60 s and the tick is 30 s,
    #: so the aftermath of a stall outlives one tick of grace (L111).
    ticks_since_stall: int = 99
    stall_aftermath_ticks: int = 2
    #: The last halt REASON said, so a transition between two reasons sharing a halt value prints.
    halt_reason: str = ""
    #: L113: refusals by (channel, code, league), flushed to `refusal_counts` on the report tick.
    #: Counted rather than rowed -- see TupleStore.refusal_counts for why that is not a preference.
    refusals: dict = field(default_factory=dict)
    tiers: dict[str, int] = field(default_factory=dict)
    wake_state: tuple = ("WAKE", None, None)
    #: Capture-only subscriptions for what the slate cannot co-list yet (tennis has no ESPN anchor):
    #: frames from both venues, no pricing. nodes/discovery/watchlist.
    watch: Watchlist | None = None
    #: What has been said once: game_id -> UNPAIRED reason, "venue:id" -> near-miss reason.
    said: dict[str, str] = field(default_factory=dict)
    #: game_id -> monotonic instant before which no new cover is sent on it: after a first leg
    #: the venue rejected or killed (2026-09-07: ten kills on one game in two minutes, each a
    #: round trip on the event loop; the books had moved and the lane kept re-sending).
    backoff: dict[str, float] = field(default_factory=dict)
    backoff_s: float = 20.0
    #: The game whose real cover is executing in the worker thread, or None. One at a time: a
    #: second cover during a flight is refused IN_FLIGHT before any round trip (2026-09-07).
    in_flight: str | None = None
    #: The position guard (nodes/execute/guard.py, 2026-09-08): real-order modes only; runs every
    #: `[protect] guard_period_s` when nothing is in flight, and its `fills_today` is what the loss
    #: breaker is fed (it was `()` until 2026-09-08, so the breaker could never latch from trading).
    guard: PositionGuard | None = None
    fills_today: tuple = ()
    guard_passes: int = 0
    #: L123: a guard fetch/apply failure is an entry stop even if an operator later clears an
    #: unrelated kill.  A complete later pass may clear this in-memory gate; durable evidence is
    #: append-only and the live kill remains a human decision.
    guard_unhealthy: bool = True
    guard_failure_detail: str = "no complete guard pass since process start"
    reprotect_queue: list = field(default_factory=list)
    #: L76 (2026-09-12): execution_id -> (next_due_mono, until_mono) for a position the layer left
    #: naked: re-run every [protect] protect_retry_s for protect_fast_window_s, from the run loop,
    #: instead of once per 30 s guard pass (VARILLA V WILD: hedged at +39 s, rounds two and three
    #: having waited for the guard while 25 sat one tick above the cap).
    reprotect_fast: dict = field(default_factory=dict)
    #: The guard confirms both venue balances every 30 s. Reuse that authoritative snapshot on
    #: the entry path instead of spending 300-400 ms on two balance round trips after an edge is
    #: seen. A missing/stale snapshot falls back to synchronous reads and remains fail-closed.
    balance_snapshot: dict[str, float] = field(default_factory=dict)
    balance_snapshot_mono: float = 0.0
    balance_snapshot_ttl_s: float = 35.0
    #: The store-touching collaborators of the machine and the venues (records, opportunities,
    #: the order journal), wrapped so a call from the worker runs on the loop thread.
    on_loop: list = field(default_factory=list)
    exec_tasks: set = field(default_factory=set)
    capture_series: tuple[str, ...] = ()
    capture_pm_tags: tuple = ()
    watch_rows: int = 0
    #: L102: Polymarket token ids whose SDK metadata is already cached, so a warm pass costs nothing.
    _pm_warmed: set = field(default_factory=set)

    # ── discovery ───────────────────────────────────────────────────────
    def discover(self) -> dict[str, dict]:
        """Games that are live (or nearly) AND co-listed on both venues, with their outcome map
        and the fee params each venue reported. `nodes/discovery` owns all of it; this grid only
        composes. Blocks are REPLACED each pass so a cleared block does not linger.

        Two halves, because the run loop must not block on the network: `fetch_discovery()` is
        the HTTP (ESPN, Kalshi, Polymarket; 43-107 s on 2026-09-04) and runs in a worker thread;
        `apply_discovery()` is the store and the supervisor's state and runs on the loop. Run
        synchronously, this method is their composition."""
        return self.apply_discovery(*self.fetch_discovery())

    def fetch_discovery(self):
        """The network half. Touches no store, no socket, no supervisor state. Ledger L37
        (2026-09-04): run inline, this starved both sockets for 13% of every hour."""
        now = datetime.now(timezone.utc)
        pc = Client("polymarket", rate=5, burst=8, cache_dir=None)
        kc = Client("kalshi", rate=4, burst=8, cache_dir=None)
        return now, discover(self.leagues, now, True, self.pre_hours, pc, kc)

    def apply_discovery(self, now: datetime, d) -> dict[str, dict]:
        """The state half. MUST run on the event-loop thread (sqlite, replicas)."""
        seen = first_seen(self.store) if self.store is not None else {}
        slate, blocked = co_listed(d, first_seen=seen, now=now.timestamp())
        self.tiers = {}
        for spec in slate.values():
            self.tiers[spec["tier"]] = self.tiers.get(spec["tier"], 0) + 1
        # Wake/drain: what the slate says the box should be doing right now (nodes/slate).
        wins = windows_for(d.games, lead_s=1800, settle_s=2700)
        nxt = next_transition(wins, now.timestamp())
        self.wake_state = ("WAKE" if any(w.covers(now.timestamp()) for w in wins) else "DRAIN",
                           nxt[0] if nxt else None, nxt[1] if nxt else None)
        # A spawn block (below) survives the discovery pass that would otherwise null it: the
        # 5-minute upsert writes `blocked` into events.block_reason, so a game still on the slate
        # keeps its SPAWN reason until it certifies (2026-09-05: two co-listed European games were
        # blocked at TEMPLATE_UNKNOWN for a whole evening and nothing said so).
        kept = {g: r for g, r in self.blocked.items() if str(r).startswith("SPAWN:") and g in slate and g not in blocked}
        self.blocked = {**dict(blocked), **kept}
        for venue, errs in d.fee_errors.items():
            for key, err in errs.items():
                self.blocked[f"fees:{venue}:{key}"] = f"FEE_SCHEDULE: {err}"
        if self.store is not None:
            record_events(self.store, d, slate, {**dict(blocked), **kept})
        for gid, spec in slate.items():
            self.last_specs[gid] = dict(spec)
        failed_leagues = set(getattr(d, "schedule_failures", {}) or {})
        for gid in self.live:
            old = self.last_specs.get(gid)
            if gid in slate or old is None or old.get("league") not in failed_leagues:
                continue
            held = dict(old)
            held["_discovery_block"] = f"SCHEDULE_FETCH: {d.schedule_failures[old['league']]}"
            slate[gid] = held
        # Every game in the window that did not pair is said ONCE per reason, by name, with the
        # venue side that was missing; every venue market that failed to pair is said once with
        # the venue's own labels and the matcher's reason. A league with games and no pair keeps
        # its summary line. Until 2026-09-07 the per-event reasons were computed and discarded,
        # and the operator learned about Swiatek v Zheng from the venues.
        games_by_league: dict[str, int] = {}
        for g in getattr(d, "games", ()) or ():
            games_by_league[g.league] = games_by_league.get(g.league, 0) + 1
            reason = self.blocked.get(g.game_id)
            if reason and str(reason).startswith("UNPAIRED:") and self.said.get(g.game_id) != reason:
                self.said[g.game_id] = reason
                when = datetime.fromtimestamp(g.start_utc, timezone.utc).strftime("%H:%M")
                print(f"[unpaired] {g.short_name} ({g.league}) {when}Z {reason[len('UNPAIRED:'):]}", flush=True)
        shown = 0
        for league, (matches, stats, _r) in sorted((getattr(d, "per_league", None) or {}).items()):
            for nm in stats.get("near_miss") or ():
                key = f"{nm.get('venue')}:{nm.get('id')}"
                if self.said.get(key) == nm.get("reason") or shown >= 40:
                    continue
                self.said[key] = nm.get("reason")
                shown += 1
                labels = " | ".join(str(x) for x in nm.get("labels") or ())
                extra = (f" candidates={nm['candidates']}" if nm.get("candidates") else "") + (f" game={nm['game_id']}" if nm.get("game_id") else "")
                print(f"[near-miss] {league} {nm.get('venue')} {nm.get('id')}: {nm.get('reason')} ({labels}){extra}", flush=True)
            if matches or not games_by_league.get(league):
                continue
            reasons = stats.get("matcher_reasons") or {}
            print(f"[discovery] {league}: {games_by_league[league]} games, 0 pairs; "
                  f"kalshi markets={stats.get('kalshi_markets', 0)} reasons={reasons.get('kalshi') or {}}; "
                  f"polymarket markets={stats.get('polymarket_markets', 0)} reasons={reasons.get('polymarket') or {}}",
                  flush=True)
        if self.store is not None and self.store.con.in_transaction:
            self.store.commit()
        return slate

    def sync_watch(self) -> tuple[int, int]:
        """Capture-only markets: subscribe what the venues list now, drop what is gone.
        Same split as discovery: `fetch_watch()` off the loop, `apply_watch()` on it."""
        return self.apply_watch(self.fetch_watch())

    def fetch_watch(self):
        if self.watch is None or not (self.capture_series or self.capture_pm_tags):
            return None
        now = time.time()
        kc = Client("kalshi-watch", rate=4, burst=8, cache_dir=None)
        pc = Client("polymarket-watch", rate=4, burst=8, cache_dir=None)
        k_now = kalshi_watch(list(self.capture_series), kc, now=now, ahead_h=self.pre_hours) if self.capture_series else []
        p_events = pm_watch_events(list(self.capture_pm_tags), pc, now=now, ahead_h=self.pre_hours) if self.capture_pm_tags else []
        p_now = [(tok, e.event_id) for e in p_events for tok in e.tokens]
        return k_now, p_now, p_events

    def apply_watch(self, fetched) -> tuple[int, int]:
        if fetched is None:
            return (0, 0)
        k_now, p_now, p_events = fetched
        added, removed = self.watch.sync(self.ks, self.ps, k_now, p_now)
        if self.store is not None and p_events:
            # First-seen starts for the settlement-timing collector (nodes/watch_settle, ledger F4).
            self.watch_rows = record_watch(self.store, p_events, now=time.time())
            if self.store.con.in_transaction:
                self.store.commit()
        return added, removed

    # ── lifecycle ───────────────────────────────────────────────────────
    def reconcile(self, slate: dict[str, dict]) -> None:
        """Spawn what is newly live, reap what has settled. Subscriptions follow."""
        for gid, spec in slate.items():
            if gid in self.live:
                # The evaluation window follows the slate tier (2026-09-08): a game that moved from
                # newborn to live prices on every frame from this pass on; the replay harness reads
                # the same change from the tier timeline the discovery pass recorded.
                current = self.live[gid]
                current.discovery_block = spec.get("_discovery_block")
                fingerprint = _execution_spec(spec)
                if current.execution_spec == fingerprint:
                    current.poller.min_eval_interval_s = eval_interval_for(spec.get("tier"), default=EVAL_INTERVAL_S)
                    current.tier = str(spec.get("tier") or "")
                    continue
                # Fees, token ids, order minima and settlement proof are executable state, not
                # display metadata.  A discovery refresh that changes any of them replaces the
                # actor before another frame can be priced from the obsolete specification.
                current.poller.drain()
                for ticker in current.kalshi_tickers:
                    self.ks.unregister(ticker)
                for asset in current.pm_assets:
                    self.ps.unregister(asset)
                self.live.pop(gid, None)
                print(f"[refresh] {current.short_name}: executable slate specification changed", flush=True)
            eq = certify_from_spec(spec, spec["league"])
            # The window per tier is nodes/game_poller/poller.EVAL_INTERVAL_BY_TIER, mirrored in
            # nodes/replay/replay.py: replay must coalesce exactly as the lane did or the rows differ.
            p = GamePoller(gid, spec["league"], spec["outcomes"],
                           quantities=QUANTITIES, max_book_age_s=self.max_book_age_s,
                           min_eval_interval_s=eval_interval_for(spec.get("tier"), default=EVAL_INTERVAL_S),
                           min_return=MIN_RETURN, fee_params=spec["fee_params"],
                           equivalence=eq if isinstance(eq, SettlementEquivalence) else None,
                           order_limits={"polymarket": spec.get("pm_limits") or {}})
            if p.state is PollerState.BLOCKED:
                # An unproven outcome set or settlement basis never gets a subscription spent on it.
                # Said once per game per reason and written to the event's row: the poller only
                # knows SETTLEMENT_UNPROVEN, the certify code and detail are in the spec.
                st = spec.get("settlement") or {}
                reason = f"SPAWN:{p.block_reason}" + (f" ({st.get('code')}: {str(st.get('detail', ''))[:120]})"
                                                      if st.get("result") == "BLOCKED" else "")
                if self.blocked.get(gid) != reason:
                    print(f"[spawn-blocked] {spec['short_name']} ({spec['league']}) {reason}", flush=True)
                    if self.store is not None:
                        record_spawn_block(self.store, gid, reason, now=time.time())
                self.blocked[gid] = reason
                continue
            sup = Supervised(p, spec["short_name"], time.time(),
                             tuple(p.market_ids("kalshi")), tuple(p.market_ids("polymarket")),
                             fee_params=dict(spec["fee_params"]), execution_spec=_execution_spec(spec),
                             tier=str(spec.get("tier") or ""), start_utc=spec.get("start_utc"), league=spec["league"])
            cb = self._on_update(gid)
            for venue, market_id, side, rep in p.registrations():
                if venue == "kalshi":
                    self.ks.register(market_id, rep, side, on_update=cb)
                else:
                    self.ps.register(market_id, rep, on_update=cb)
            self.live[gid] = sup
            self.spawned += 1
            print(f"[spawn] {spec['short_name']} ({spec['league']}, {spec['state']}) "
                  f"{len(sup.kalshi_tickers)}k+{len(sup.pm_assets)}pm", flush=True)

        for gid in [g for g in self.live if g not in slate]:
            sup = self.live.pop(gid)
            sup.poller.drain()
            for t in sup.kalshi_tickers:
                self.ks.unregister(t)
            for a in sup.pm_assets:
                self.ps.unregister(a)
            self.reaped += 1
            self.last_specs.pop(gid, None)
            st = sup.poller.stats()
            print(f"[reap ] {sup.short_name} after {(time.time()-sup.started_utc)/60:.0f}m — "
                  f"{st['evaluations']} evals, {sup.written} rows, {st['opportunities']} opps",
                  flush=True)

    def _on_update(self, gid: str):
        def cb(_market_id: str, now: float) -> None:
            sup = self.live.get(gid)
            if sup is None:
                return
            if sup.discovery_block:
                return
            failed = False
            written_before = sup.written
            evaluated = []
            sized_live = self._live_sizing_enabled()
            for ev in sup.poller.on_event("stream", _market_id, now=now):
                sup.evaluations += 1
                try:
                    rec = self._record(sup, ev, dispatch=not sized_live)
                    evaluated.append((ev, rec))
                    if not evaluated[:-1] or (rec.cost is not None and (sup.last_cost is None or rec.cost < sup.last_cost)):
                        sup.last_status, sup.last_cost, sup.last_eval_utc = rec.status.value, rec.cost, ev.evaluated_utc
                except Exception as exc:  # noqa: BLE001 -- a record bug must never reach the socket loop
                    failed = True
                    # The callback runs inside the venue socket's receive loop. An exception here
                    # was caught by the transport's blanket handler, which tore the socket down,
                    # resubscribed, and raised again on the first frame: 5-20 reconnects a minute
                    # on 2026-09-03, invisible to the watchdog. Count it, say it once per cause,
                    # keep pumping.
                    key = (gid, type(exc).__name__)
                    self.record_errors[key] = self.record_errors.get(key, 0) + 1
                    if self.record_errors[key] == 1:
                        print(f"  [record] {sup.short_name} {brief_error(exc)}", flush=True)
            if not failed and evaluated and sized_live and self.coordinator is not None:
                if not self._worth_sizing(sup, evaluated):
                    sup.sizing_skipped += 1
                    sized_live = False
            if not failed and evaluated and sized_live and self.coordinator is not None:
                try:
                    self._execute_sized(sup, evaluated)
                except Exception as exc:  # noqa: BLE001 -- selection must not tear down a socket
                    failed = True
                    key = (gid, "size:" + type(exc).__name__)
                    self.record_errors[key] = self.record_errors.get(key, 0) + 1
                    if self.record_errors[key] == 1:
                        print(f"  [size] {sup.short_name} {brief_error(exc)}", flush=True)
            if self.store is not None and self.store.con.in_transaction:
                # Commit per frame, not per report tick (30 s): the loop's implicit transaction held
                # the file's write lock for up to 30 s, and the execution worker's journal write
                # behind it hit the 30 s busy timeout with leg A already out (GEA V ZANDSCH,
                # 2026-09-08 01:40Z: filled on Polymarket, hedge never sent). A WAL commit here is
                # an append, not an fsync (synchronous=NORMAL).
                try:
                    if failed:
                        self.store.con.rollback()
                        sup.written = written_before
                    else:
                        self.store.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.store.con.rollback()
                    except Exception:  # noqa: BLE001 -- preserve the original commit failure
                        pass
                    sup.written = written_before
                    key = (gid, "commit:" + type(exc).__name__)
                    self.record_errors[key] = self.record_errors.get(key, 0) + 1
                    if self.record_errors[key] == 1:
                        print(f"  [record] {sup.short_name} commit {brief_error(exc)}", flush=True)
        return cb

    def _live_sizing_enabled(self) -> bool:
        return (self.mode.risks_capital and isinstance(self.limits, RiskLimits) and self.ledger is not None
                and all(name in self.caps for name in ("stake_usd", "max_contracts", "day_notional_usd")))

    # ── persistence ─────────────────────────────────────────────────────
    def _record(self, sup: Supervised, ev, *, dispatch: bool = True):
        rec = record_evaluation(self.store, ev, league=sup.poller.league,
                                fee_params=sup.fee_params, hurdle=MIN_RETURN,
                                opportunities=self.opportunities)
        sup.written += int(rec.wrote)
        if rec.status is OpportunityStatus.PROFITABLE_UNEXECUTED:
            # Solve the size frontier on the SAME books that produced the edge. Doing it from the
            # replicas afterwards would price a different instant -- the books move in milliseconds.
            cap = ""
            try:
                # L79: the frontier (up to 80 covers, ~40 ms) is a report, solved at most once per
                # FRONTIER_PERIOD_S per game; the sizing sweep, not this, picks the quantity.
                # (every rung of one epoch shares the instant; the period is between epochs)
                if ev.offers and sup.poller.proof is not None and (
                        ev.evaluated_utc == sup.last_frontier_utc or ev.evaluated_utc - sup.last_frontier_utc >= FRONTIER_PERIOD_S):
                    sup.last_frontier_utc = ev.evaluated_utc
                    fr = frontier({o: list(v) for o, v in ev.offers.items()},
                                  now_utc=ev.evaluated_utc, proof=sup.poller.proof,
                                  max_leg_age_s=self.max_book_age_s, hurdle=MIN_RETURN,
                                  slippage_per_contract=slippage_for(sup.poller.league))
                    if fr.actionable:
                        cap = (f"  N_max={fr.n_max:.0f} N*={fr.n_star:.0f} "
                               f"profit=${fr.best.profit:.2f} on ${fr.best.capital:.0f}")
                    if self.opportunities is not None:
                        opp = self.opportunities.live.get(Opportunity.id_for(ev.game_id, ev.quantity))
                        if opp is not None:
                            self.opportunities.record_frontier(opp, fr, now=ev.evaluated_utc)
            except Exception as exc:  # noqa: BLE001 -- reporting must never break the loop
                cap = f"  (capacity failed: {type(exc).__name__})"
            print(f"  *** {rec.status.value} {sup.short_name} q={ev.quantity} cost={rec.cost:.4f} "
                  f"return={rec.locked_return:+.3%}{cap}", flush=True)
            if dispatch and self.coordinator is not None:
                self._execute(sup, ev, rec)
        return rec

    def _worth_sizing(self, sup: Supervised, evaluated) -> bool:
        """L79: size only an epoch that can select something. The exhaustive sweep (q = 1..cap, a
        full cover each) ran on every epoch and was 55 % of the loop's CPU (L78, 2026-09-12) while
        ~97 % of epochs selected nothing. The one exact exclusion: gross at or above 1.0 on the
        smallest priced quantity. Gross is the ladders' VWAP sum and never falls with size, so no
        whole quantity can lock a profit; the sweep would enumerate the cap for nothing. Fee-bound
        or below-hurdle rungs still size (a neighbouring whole quantity can clear what the fixed
        rungs missed: fee rounding and the $0.10 floor move with q), and an event whose last
        recorded decision was executable sizes once more so L74 records the exit."""
        if sup.last_sizing_executable:
            return True
        covers = [ev.cover for ev, _ in evaluated if ev.cover is not None and ev.cover.ok]
        if not covers:
            return False           # nothing priced at any rung: the sweep prices the same offers, stricter
        # best_cover takes the cheapest combination, single-venue included, so its gross is the floor
        # for the cross-venue pair the sweep requires.
        g = min((c.gross_per_contract for c in covers if c.gross_per_contract is not None), default=None)
        return not (g is not None and g >= 1.0 - 1e-12)

    def _execute_sized(self, sup: Supervised, evaluated) -> None:
        """One cap-aware live quantity decision for one frozen book epoch."""
        base = evaluated[0][0]
        # Forward assignment is event-level and must precede the common sizing sweep: the sweep builds
        # the current taker-shaped economic candidates, while the selected arm's wire plan is built
        # only afterwards.  It is deliberately inactive outside LIMITED_LIVE, so paper/history are
        # never backfilled or relabelled.
        active_row = F23_ROW_ID if self.f23_enabled else F22_ROW_ID if self.f22_enabled else None
        if self.mode is Mode.LIMITED_LIVE and ((self.f23_enabled and self.f23_failed) or (self.f22_enabled and self.f22_failed)):
            code = f"{active_row}_PERSISTENCE_FAILED"
            self.refuse("execution", code, sup.poller.league)
            return
        assignment = ((assign_f23_entry_arm(base.game_id) if active_row == F23_ROW_ID else assign_entry_arm(base.game_id))
                      if self.mode is Mode.LIMITED_LIVE and active_row else None)
        if assignment is not None and (self.store is None or self.opportunities is None):
            # F22's unit cannot exist without both sides of its durable pre-wire join. This is an
            # instrumentation STOP, not permission to run an unscored order.
            self.refuse("execution", "F22_INSTRUMENTATION_MISSING", sup.poller.league)
            return
        # L123: do this before consuming even the cached balance snapshot.  The callback may have
        # priced the event already, but no new capital entry is allowed while guard health is unknown.
        if self._guard_entry_refused(sup):
            return
        if not base.offers or sup.poller.proof is None or self.limits is None or self.ledger is None:
            return
        balances = self._cached_balances({})
        balances = balances or {}
        offers = {o: list(v) for o, v in base.offers.items()}
        decision = choose_live_size(
            offers, now_utc=base.evaluated_utc, proof=sup.poller.proof,
            event_id=base.game_id, league=sup.poller.league, caps=self.caps,
            limits=self.limits, ledger=self.ledger, balances=balances,
            max_leg_age_s=self.max_book_age_s, hurdle=MIN_RETURN,
            min_net_profit_usd=float(getattr(self.limits, "min_net_profit_usd", 0.0) or 0.0),
            max_quote_age_s=min(sup.poller.max_book_age_s, sup.poller.max_rest_book_age_s),
        )
        identity = None
        if assignment is not None:
            # The audit is the exact object subsequently embedded in plan_json by Coordinator.
            # Caps are copied at assignment/sizing time and never inferred from later order shape.
            identity = assignment.as_record(self.caps)
        # L79: the fingerprints, the sha and the audit ladder exist for the recorded row; an epoch
        # that selects nothing after an epoch that selected nothing records nothing (L74).
        executable = decision.selected is not None
        if not executable and not sup.last_sizing_executable:
            sup.last_sizing_executable = False
            key = f"{sup.short_name}:SIZE:" + ",".join(decision.binding_constraints)
            if self.said.get(key) != "said":
                self.said[key] = "said"
                print(f"  [size] refused {sup.short_name}: {','.join(decision.binding_constraints) or 'NO_FEASIBLE_SIZE'}", flush=True)
            self._count_size_refusal(sup, decision)
            return
        epoch_payload = []
        for outcome, legs in sorted(offers.items()):
            for leg in sorted(legs, key=lambda x: (x.venue, x.market_id, x.outcome_id)):
                epoch_payload.append([outcome, leg.venue, leg.market_id, leg.outcome_id,
                                      book_fingerprint(((level.price, level.size) for level in leg.book.asks),
                                                       venue=leg.venue, market_id=leg.market_id),
                                      leg.book.source, leg.min_order_contracts,
                                      leg.tick, dict(leg.fee_overrides), sorted(leg.covers)])
        epoch_payload.append(["proof", sup.poller.proof.as_record()])
        if assignment is not None:
            # Include the arm (and its versioned digest) in the idempotency input.  A changed arm
            # cannot silently look like the same frozen-book epoch.
            epoch_payload.append([active_row.lower(), assignment.as_record(self.caps)])
        input_hash = hashlib.sha256(json.dumps(epoch_payload, separators=(",", ":")).encode()).hexdigest()
        if identity is not None:
            # `input_hash` alone is not unique: a real A -> B -> A book path records the second A
            # with a new occurrence. Predict the append-only row identity under the same loop-owned
            # connection used by OpportunityStore, then persist it on BOTH sides of the join.
            # The store recomputes these values when it inserts; a duplicate input returns false
            # below and therefore never dispatches a plan carrying a nonexistent occurrence.
            previous = (self.store.con.execute(
                "SELECT occurrence FROM sizing_decisions WHERE event_id=? ORDER BY id DESC LIMIT 1",
                (base.game_id,),
            ).fetchone() if self.store is not None and self.opportunities is not None else None)
            occurrence = int(previous[0] or 0) + 1 if previous is not None else 1
            identity["sizing_input_hash"] = input_hash
            identity["sizing_occurrence"] = occurrence
            identity["sizing_book_epoch"] = hashlib.sha256(f"{input_hash}:{occurrence}".encode()).hexdigest()
            if isinstance(decision, SizingDecision):
                decision = replace(decision, entry_experiment=identity)
        selected_oid = (Opportunity.id_for(base.game_id, decision.selected.quantity)
                        if decision.selected is not None else None)
        # L74: an epoch that selects nothing is recorded only as the transition out of an
        # executable state; its evaluation row already says why. An executable epoch whose input
        # is the last recorded one is the single-flight guard firing: nothing is minted twice.
        decision_audit = decision.audit()
        if assignment is not None:
            # Do not mutate a frozen/duck-typed test decision. Production decisions are the
            # SizingDecision above; this merge keeps lightweight replay stubs safe as well.
            decision_audit = dict(decision_audit)
            decision_audit["entry_experiment"] = dict(identity or assignment.as_record(self.caps))
            if active_row == F23_ROW_ID:
                # These are part of the immutable decision payload, alongside entry_experiment;
                # report code can therefore enforce the registered league-local-day minimum
                # without reconstructing dates from a later execution or wall-clock timestamp.
                decision_audit.update(_f23_audit_context(sup, base.evaluated_utc))
        recorded = self.opportunities is None or self.opportunities.record_sizing_decision(
            event_id=base.game_id, input_hash=input_hash, executable=executable,
            selected_opportunity_id=selected_oid, decision=decision_audit, now=base.evaluated_utc)
        sup.last_sizing_executable = executable
        if not recorded and executable:
            return
        if identity is not None and recorded and self.store is not None:
            # This additive analysis row is committed with the already durable sizing decision,
            # before _execute can construct a provider request.  A no-selection transition is kept
            # for lineage but is excluded by the report's eligible-decision filter.
            try:
                recorder = record_f23_decision if active_row == F23_ROW_ID else record_f22_decision
                inserted = recorder(
                    self.store, assignment=identity, decision=decision_audit,
                    selected_quantity=(float(decision.selected.quantity)
                                       if decision.selected is not None else None),
                    now=base.evaluated_utc)
                if not inserted:
                    raise RuntimeError("F22 decision row was not inserted for a newly recorded sizing epoch")
            except Exception as exc:
                if self.store.con.in_transaction:
                    self.store.con.rollback()
                self._f22_stop(f"pre-wire decision persistence failed: {brief_error(exc)}")
                return
        # The decision/outbox must be durable before any worker can reach a venue wire. If this
        # commit fails, the callback catches it and no task is created.
        if self.store is not None:
            try:
                self.store.commit()
            except Exception as exc:
                if self.store.con.in_transaction:
                    self.store.con.rollback()
                if identity is not None:
                    self._f22_stop(f"pre-wire decision commit failed: {brief_error(exc)}")
                    return
                raise
        if decision.selected is None:
            key = f"{sup.short_name}:SIZE:" + ",".join(decision.binding_constraints)
            if self.said.get(key) != "said":
                self.said[key] = "said"
                print(f"  [size] refused {sup.short_name}: {','.join(decision.binding_constraints) or 'NO_FEASIBLE_SIZE'}", flush=True)
            self._count_size_refusal(sup, decision)
            return
        selected = decision.selected
        ev = replace(base, quantity=float(selected.quantity), cover=selected.cover)
        rec = next((r for old, r in evaluated if abs(old.quantity - selected.quantity) < 1e-9), None)
        if rec is None:
            rec = self._record(sup, ev, dispatch=False)
        print(f"  [size] {sup.short_name} N*={decision.n_star_feasible} N_max={decision.n_max_feasible} "
              f"profit=${selected.profit_usd:.4f} bindings={','.join(decision.binding_constraints) or 'none'} "
              f"fill_model={decision.fill_model}", flush=True)
        self._execute(sup, ev, rec, sizing=decision)

    def _experiment_stop(self, row: str, detail: str) -> None:
        """Make one cohort's instrumentation failure a real entry stop."""
        if row not in {F22_ROW_ID, F23_ROW_ID}:
            row = F23_ROW_ID
        already = self.f23_failed if row == F23_ROW_ID else self.f22_failed
        if row == F23_ROW_ID:
            self.f23_failed = True
        else:
            self.f22_failed = True
        if not already:
            print(f"  [{row.lower()} STOP] {detail}", flush=True)
            self.flag(f"{row}_PERSISTENCE_FAILED", detail)
        if self.kill is not None and self.mode.risks_capital:
            self.kill.latch("live", f"{row} instrumentation failed: {detail}")

    def _f22_stop(self, detail: str) -> None:
        """Compatibility name for the active forward-cohort stop path."""
        self._experiment_stop(F23_ROW_ID if self.f23_enabled else F22_ROW_ID, detail)

    def _f22_update(self, sizing, *, outcome: str | None = None, detail: str | None = None,
                    execution_id: str | None = None) -> bool:
        """Persist an explicit forward-cohort disposition/link without making it an execution input."""
        identity = getattr(sizing, "entry_experiment", None)
        if identity is None and isinstance(sizing, dict):
            identity = sizing.get("entry_experiment")
        if not identity or self.store is None:
            return True
        row = str(identity.get("forward_row_id") or identity.get("row_id") or "")
        active = (F23_ROW_ID if self.f23_enabled else F22_ROW_ID if self.f22_enabled else None)
        # Non-capital replay/paper fixtures may carry a historical experiment identity without a
        # live authority. Capital mode remains strict: only the signed active cohort is accepted.
        if active is None and not self.mode.risks_capital:
            active = row
        if active is None and self.mode.risks_capital:
            self._experiment_stop(F23_ROW_ID, "cohort identity received without an active signed authority")
            return False
        if row not in {F22_ROW_ID, F23_ROW_ID}:
            self._experiment_stop(active or F23_ROW_ID, f"unknown cohort row id: {row or '<missing>'}")
            return False
        if active is not None and row != active:
            self._experiment_stop(active, f"cohort identity {row} does not match active {active}")
            return False
        try:
            updater = update_f23_decision if row == F23_ROW_ID else update_f22_decision
            updater(self.store, event_id=str(identity.get("event_id") or identity.get("canonical_event_id")),
                    sizing_book_epoch=str(identity["sizing_book_epoch"]), outcome=outcome,
                    detail=detail, execution_id=execution_id, now=time.time())
            self.store.commit()
            return True
        except Exception as exc:  # noqa: BLE001 -- reporting must never break the execution door
            key = (str(identity.get("event_id", "")), row.lower() + ":" + type(exc).__name__)
            self.record_errors[key] = self.record_errors.get(key, 0) + 1
            if self.record_errors[key] == 1:
                print(f"  [f22] disposition persistence failed: {brief_error(exc)}", flush=True)
            self._experiment_stop(row, f"disposition persistence failed: {brief_error(exc)}")
            return False

    def _f22_link_execution(self, sizing, ex) -> None:
        """Link the machine row and explicitly preserve a proved pre-wire no-order outcome."""
        exid = getattr(ex, "execution_id", None)
        state = str(getattr(getattr(ex, "state", None), "value", getattr(ex, "state", "")))
        no_wire = (not getattr(ex, "first_client_id", None)
                   and float(getattr(ex, "first_filled", 0.0) or 0.0) <= 1e-9
                   and float(getattr(ex, "hedge_filled", 0.0) or 0.0) <= 1e-9
                   and bool(getattr(ex, "released", False)))
        self._f22_update(sizing, execution_id=exid,
                         outcome="local_or_risk_refused_no_wire" if no_wire else None,
                         detail=state if no_wire else None)

    def loop_probe_reading(self, overshoot_s: float) -> None:
        self.loop_lag_readings.append(overshoot_s)
        if overshoot_s > self.loop_lag_max_s:
            self.loop_lag_max_s = overshoot_s

    def loop_stalled(self) -> bool:
        """Stalled at the last tick, or stalled since it."""
        return self.stalled or self.loop_lag_max_s > self.max_loop_lag_s

    def clock_ok(self) -> bool:
        """What the risk gate is told: both venues' stamps inside the bound AND the loop prompt."""
        return all(st_.clock.healthy for st_ in (self.ks, self.ps) if st_ is not None) and not self.loop_stalled()

    def check_arm(self, now: float | None = None) -> str | None:
        """Re-read the arming override on the report tick. In a capital-risking mode, an override
        that has expired or no longer pins THIS process's code tree and limits sets `arm_stale`,
        and _execute refuses real orders until a matching one is written (or the lane restarts
        under it). Said once per change. Below LIMITED_LIVE there is nothing to check."""
        if not self.mode.risks_capital:
            self.arm_stale = None
            self.f22_enabled = False
            self.f23_enabled = False
            self.f22_authority_detail = "mode does not risk capital"
            self.f23_authority_detail = "mode does not risk capital"
            return None
        limits_sha = str(getattr(self.limits, "sha", "") or "")
        st = override_state(self.override_path, code_sha=self.code_sha, limits_sha=limits_sha, now=now)
        reason = stale_reason(st, code_sha=self.code_sha, limits_sha=limits_sha)
        f23_enabled, f23_authority = f23_activation(root=ROOT, state=st) if reason is None else (False, str(reason))
        # F22 is permanently closed after its instrumentation STOP. Its report remains available
        # for historical/read-only evidence, but no signed override may reactivate its live path.
        f22_enabled, f22_authority = False, "F22 closed after instrumentation STOP; read-only reporting only"
        if f23_enabled != self.f23_enabled or f23_authority != self.f23_authority_detail:
            print(f"[f23] {'ENABLED' if f23_enabled else 'disabled'}: {f23_authority}", flush=True)
        if f22_enabled != self.f22_enabled or f22_authority != self.f22_authority_detail:
            print(f"[f22] {'ENABLED' if f22_enabled else 'disabled'}: {f22_authority}", flush=True)
        self.f23_enabled, self.f23_authority_detail = f23_enabled, f23_authority
        self.f22_enabled, self.f22_authority_detail = f22_enabled, f22_authority
        if reason != self.arm_stale:
            print(f"[arm] STALE {reason}" if reason else "[arm] override matches again; real orders resume", flush=True)
        self.arm_stale = reason
        return reason

    board_path: Path | None = None
    board_written: int = 0

    def board(self, now: float | None = None) -> dict:
        """What the box is watching, this second: every poller's books (best bid/ask per outcome
        per venue, age, replica state), the last evaluation's all-in cost and status, tier, start,
        plus the sockets and the loop. Read by ops/box/board_server.py for the terminal page."""
        t = time.time() if now is None else now
        games = []
        for gid, sup in self.live.items():
            p = sup.poller
            outcomes = {}
            for (key, outcome), rep in p.replicas.items():
                venue = {"kalshi_no": "kalshi_no", "polymarket_no": "polymarket_no"}.get(key, key)
                bid = max(rep.bids) if rep.bids else None
                ask = min(rep.asks) if rep.asks else None
                outcomes.setdefault(outcome, {})[venue] = {
                    "bid": bid, "ask": ask, "bid_size": rep.bids.get(bid) if bid is not None else None,
                    "ask_size": rep.asks.get(ask) if ask is not None else None,
                    "state": rep.state.value, "age_s": round(t - rep.as_of(), 1) if rep.as_of() else None, "market": rep.market_id}
            games.append({"game_id": gid, "name": sup.short_name, "league": sup.league or p.league, "tier": sup.tier,
                          "start_utc": sup.start_utc, "poller": p.state.value, "halt": p.halt,
                          "status": sup.last_status, "cost": sup.last_cost, "eval_age_s": round(t - sup.last_eval_utc, 1) if sup.last_eval_utc else None,
                          "evaluations": sup.evaluations, "outcomes": outcomes})
        socks = {}
        for name, st_ in (("kalshi", self.ks), ("polymarket", self.ps)):
            if st_ is not None:
                st = st_.stats()
                socks[name] = {"connected": st.get("connected"), "frames": st.get("frames"), "age_s": st.get("age_s"), "errors": st.get("errors")}
        return {"as_of": t, "mode": self.mode.value, "caps": dict(self.caps), "arm_stale": self.arm_stale,
                "f22_enabled": self.f22_enabled, "f22_failed": self.f22_failed,
                "f22_authority": self.f22_authority_detail,
                "f23_enabled": self.f23_enabled, "f23_failed": self.f23_failed,
                "f23_authority": self.f23_authority_detail,
                "loop_lag_s": round(self.loop_lag_max_s, 3), "stalled": self.stalled, "blocked": len(self.blocked),
                "sockets": socks, "games": games}

    def write_board(self, now: float | None = None) -> None:
        """Atomic: the reader never sees a partial file."""
        if self.board_path is None:
            return
        try:
            self.board_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.board_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.board(now), separators=(",", ":"), default=str))
            os.replace(tmp, self.board_path)
            self.board_written += 1
        except Exception as exc:  # noqa: BLE001 -- the board is a display, never a reason to stop
            if self.board_written == 0:
                print(f"  [board] write failed: {type(exc).__name__}: {exc}", flush=True)

    def data_free_bytes(self) -> int | None:
        """Free bytes on the volume holding the database (the data root), None when unreadable."""
        try:
            return int(self.disk_usage(self.db.parent).free)
        except OSError:
            return None

    def retain_once(self, now: float | None = None) -> dict:
        """One retention pass (L72): age out observation rows older than retain_days from the
        store's RETENTION_TABLES, on a connection of this thread's own, then the frame day
        directories older than retain_days under each socket's capture root. Evidence tables are
        structurally out of reach (store.retain refuses any other table); today's frames and the
        newest retain_days full days always stay."""
        t = now if now is not None else time.time()
        out: dict = {}
        st = TupleStore(self.db, check_same_thread=False, isolation_level="IMMEDIATE", enforce_volume=self.enforce_volume)
        try:
            out.update(st.retain(max_age_s=self.retain_days * 86400.0, now=t, budget_s=self.retain_budget_s))
        finally:
            st.close()
        days: list[str] = []
        for st_ in (self.ks, self.ps):
            cap = getattr(st_, "capture", None)
            if cap is not None:
                days += [f"{cap.venue}:{d}" for d in prune_days(cap.root, cap.venue, max_age_days=self.retain_days, now=t)]
        if days:
            out["frames"] = days
        return out

    def on_report_tick(self, now: float | None = None) -> None:
        """Persist socket health, and fail closed on an unhealthy clock: every freshness bound
        in the system is `now - updated_utc`, so a stepped clock makes every book fiction.

        Two causes, named apart (2026-09-04). STALL: the loop probe overshot the bound, so every
        frame on BOTH sockets was stamped late -- the lane is behind real time, not the clocks.
        CLOCK: a venue's stamps sit outside the bound while the loop was prompt -- a clock step
        or the venue stamping late. Both halt pricing; only the second is a clock finding."""
        t = now or time.time()
        free = self.data_free_bytes()
        if free is not None and free < self.disk_floor_bytes:
            raise DiskPressure(f"DISK_PRESSURE {free / 2 ** 30:.2f} GiB free under {self.db.parent}, floor "
                               f"{self.disk_floor_bytes / 2 ** 30:.2f} GiB (JANUS_MINFREE_KB): stopping before a commit fails")
        lag = self.loop_lag_max_s
        self.stalled = lag > self.max_loop_lag_s
        if self.stalled:
            # L111: the frames read during a stall carry OUR delay as the venue's skew, and the
            # backlog burst takes the 60 s median with it. They are contaminated, not merely old.
            for venue, st_ in (("kalshi", self.ks), ("polymarket", self.ps)):
                if st_ is not None:
                    print(f"  [clock] {venue} window dropped after a {lag:.1f}s stall: {st_.clock.reset()}", flush=True)
            self.ticks_since_stall = 0
        else:
            self.ticks_since_stall += 1
        for venue, st_ in (("kalshi", self.ks), ("polymarket", self.ps)):
            if st_ is not None:
                self.store.socket_health(venue=venue, stats={**st_.stats(), "loop_lag_s": round(lag, 3)}, seen_ts=t)
        if self.refusals and self.store is not None:
            try:
                self.store.refusal_counts(self.refusals, seen_ts=t)
            except Exception as exc:  # noqa: BLE001 -- telemetry must never break the tick
                print(f"  [risk] refusal counts not written: {brief_error(exc)}", flush=True)
            self.refusals = {}
        pm_exec = self.venues.get("polymarket")
        user_stream = getattr(getattr(pm_exec, "transport", None), "user_stream", None)
        if user_stream is not None:
            us = user_stream.stats()
            self.store.socket_health(venue="polymarket_user", stats={**us, "loop_lag_s": round(lag, 3)}, seen_ts=t)
            # L112: say the split out loud as well as store it. `frames` alone cannot distinguish a
            # working account feed from keepalive, and the entry gate trusts `connected`, which is
            # set on the subscribe SEND and proves only a handshake.
            if us.get("kinds"):
                print(f"  [pm-user] {us['kinds']} connected={us['connected']}", flush=True)
        bad = [v for v, st_ in (("kalshi", self.ks), ("polymarket", self.ps))
               if st_ is not None and not st_.clock.healthy]
        if self.loop_stalled():
            halt, why = "LOOP_STALLED", f"HALT STALL {lag:.1f}s" + (f" (stamps off on {','.join(bad)})" if bad else "")
        elif bad and self.ticks_since_stall <= self.stall_aftermath_ticks:
            # The clock window is 60 s and the report tick is 30 s, so ONE tick of grace covered
            # half of what it was written to cover; two ticks later the same contaminated samples
            # were still the median and the verdict fell through to HALT CLOCK. The window is now
            # dropped outright on a stall, so this is belt and braces while it refills.
            halt, why = "LOOP_STALLED", f"HALT STALL aftermath (stamps off on {','.join(bad)})"
        elif bad:
            halt, why = "CLOCK_UNHEALTHY", f"HALT CLOCK {','.join(bad)}"
        else:
            halt, why = None, "healthy again"
        changed = 0
        for sup in self.live.values():
            changed += int(sup.poller.halt != halt)
            sup.poller.halt = halt
        # L111: this used to print only when the halt VALUE changed. Branches 1 and 2 both assign
        # "LOOP_STALLED", and branch 2 can only run when branch 1 ran last tick -- so the aftermath
        # line was structurally unprintable, and its four appearances in six days were pollers
        # spawned mid-window, not four aftermath events. Every transition prints on its REASON now,
        # which is also what makes the STALL/CLOCK split countable at all.
        if changed or why != self.halt_reason:
            print(f"[clock] {why} ({changed} pollers)", flush=True)
        self.halt_reason = why
        self.loop_lag_max_s, self.loop_lag_readings = 0.0, []

    def _execute(self, sup: Supervised, ev, rec, *, sizing: SizingDecision | None = None) -> None:
        """PAPER and above: plan from the priced cover, clear it through nodes/risk, run the machine.
        Every refusal is recorded on the opportunity; nothing here raises into the socket loop."""
        # L123: this is deliberately before planning, balances, clearance, or any venue helper.
        if self._guard_entry_refused(sup):
            self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="GUARD_FAILED")
            return
        if self.arm_stale:
            # The override stopped authorising this process between ticks (check_arm). Refused
            # before any plan, balance call or clearance: nothing is minted for a stale arm.
            print(f"  [risk] refused {sup.short_name}: ARM_STALE {self.arm_stale}", flush=True)
            self.refuse("risk", "ARM_STALE", sup.poller.league)
            self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="ARM_STALE")
            return
        cov = ev.cover
        m_entry = time.monotonic()
        # The path's first two stages, for ops/latency_report.py: the poller's own event->decision
        # time and the gap from the decision to here (records, the frontier).
        # L97 (2026-09-13): `eval_to_exec_ms` used to be measured from `ev.evaluated_utc`, which IS
        # the frame's receive time (nodes/game_poller sets it to `t`) -- the same origin as
        # `frame_to_eval_ms`. So the two overlapped completely and summing them double-counted the
        # whole pricing phase. Subtract the first to make the name true: this is decision -> here.
        _frame_to_eval = round(float(getattr(ev, "latency_ms", 0.0) or 0.0), 2)
        pre = {"frame_to_eval_ms": _frame_to_eval,
               "eval_to_exec_ms": round(max(0.0, (time.time() - ev.evaluated_utc) * 1000.0 - _frame_to_eval), 2)}
        offers = {o: list(v) for o, v in ev.offers.items()}
        experiment = getattr(sizing, "entry_experiment", None) if sizing is not None else None
        assignment: EntryArmAssignment | None = None
        if experiment is not None:
            try:
                assignment = assignment_from_record(experiment)
            except (TypeError, ValueError) as exc:
                # The sizing decision is durable before this point. A contradictory identity is a
                # fail-closed instrumentation stop, never permission to guess or fall back.
                row = str(experiment.get("forward_row_id") or F22_ROW_ID)
                print(f"  [{row.lower()}] refused {sup.short_name}: assignment contradiction {exc}", flush=True)
                self.refuse("execution", f"{row}_ASSIGNMENT_CONTRADICTION", sup.poller.league)
                self._f22_update(sizing, outcome="persistence_or_reconciliation_failure", detail="assignment contradiction")
                return
            if assignment.forward_row_id not in {F22_ROW_ID, F23_ROW_ID} or assignment.event_id != ev.game_id:
                row = assignment.forward_row_id
                print(f"  [{row.lower()}] refused {sup.short_name}: assignment identity mismatch", flush=True)
                self.refuse("execution", f"{row}_ASSIGNMENT_CONTRADICTION", sup.poller.league)
                self._f22_update(sizing, outcome="persistence_or_reconciliation_failure", detail="assignment identity mismatch")
                return
            active = (F23_ROW_ID if self.f23_enabled else F22_ROW_ID if self.f22_enabled else None)
            if active is None and not self.mode.risks_capital:
                active = assignment.forward_row_id
            if assignment.forward_row_id != active:
                row = assignment.forward_row_id
                print(f"  [{row.lower()}] refused {sup.short_name}: cohort is not active", flush=True)
                self.refuse("execution", f"{row}_ASSIGNMENT_CONTRADICTION", sup.poller.league)
                self._f22_update(sizing, outcome="persistence_or_reconciliation_failure", detail="cohort is not active")
                return
            checkpoint_ok, checkpoint_detail = first_three_fills_reconciled(
                self.store, row_id=assignment.forward_row_id,
                exclude_event_id=assignment.event_id,
                exclude_book_epoch=str(experiment.get("sizing_book_epoch")) if experiment else None)
            if not checkpoint_ok:
                row = assignment.forward_row_id
                print(f"  [{row.lower()}] refused {sup.short_name}: {row}_RECONCILIATION_CHECKPOINT {checkpoint_detail}", flush=True)
                self.refuse("execution", f"{row}_RECONCILIATION_CHECKPOINT", sup.poller.league)
                self._f22_update(sizing, outcome="local_or_risk_refused_no_wire",
                                 detail=f"{row}_RECONCILIATION_CHECKPOINT")
                return
        plan_kwargs = dict(opportunity_id=Opportunity.id_for(ev.game_id, ev.quantity), event_id=ev.game_id,
                           league=sup.poller.league, cov=cov, offers=offers, hurdle=MIN_RETURN,
                           min_net_profit_usd=float(getattr(self.limits, "min_net_profit_usd", 0.0) or 0.0))
        if assignment is not None and assignment.arm == "maker":
            # The reviewed maker adapter owns its exact-share cap and the coordinator owns the
            # existing <=2s continuous hedge/safety-gated lifecycle. A maker refusal ends this
            # F22 decision; it must never be retried through the taker arm.
            plan = maker_plan_from_cover(
                **plan_kwargs,
                max_quote_age_s=min(sup.poller.max_book_age_s, sup.poller.max_rest_book_age_s),
            )
            if plan is None:
                print(f"  [f22] refused {sup.short_name}: MAKER_PLAN_REFUSED (no taker fallback)", flush=True)
                self.refuse("execution", "MAKER_PLAN_REFUSED", sup.poller.league)
                self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="MAKER_PLAN_REFUSED")
                return
            if not plan.first.post_only or plan.first.time_in_force != "gtc":
                print(f"  [f22] refused {sup.short_name}: F22_ROLE_VIOLATION (maker proof absent)", flush=True)
                self.refuse("execution", "F22_ROLE_VIOLATION", sup.poller.league)
                self._f22_update(sizing, outcome="role_violation", detail="maker plan role proof absent")
                return
        else:
            plan = plan_from_cover(**plan_kwargs)
        if plan is None:
            self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="NO_PLAN")
            return
        if sizing is not None:
            plan = replace(plan, sizing=sizing.audit())
        # Paper venues fill against the books the cover was priced from -- the same instant.
        for outcome, legs in offers.items():
            for l in legs:
                v = self.venues.get(l.venue)
                if v is not None:
                    params = dict(sup.fee_params.get(l.venue) or {})
                    if hasattr(v, "fee_params_by_market"):
                        v.fee_params_by_market[l.market_id] = params
                    elif hasattr(v, "fee_params"):
                        v.fee_params = params
                    if hasattr(v, "books"):
                        side = "buy_no" if (l.venue == "kalshi" and l.outcome_id.endswith(":NO")) else "buy_yes"
                        v.books[(l.market_id, side)] = l.book
        max_age = max((ev.evaluated_utc - l.book.fetched_utc) for legs in offers.values() for l in legs)
        # Passive quoting is not an executable-price EV claim. Keep the original walked
        # first-leg price and conservative fees in the eligibility/risk economics.
        first_cost = plan.first.vwap if plan.first.post_only else plan.first.limit_price
        planned_cost = first_cost + plan.hedge.vwap + plan.fee_per_contract + plan.settlement_buffer_per_contract
        planned_profit = plan.quantity * (1.0 - planned_cost)
        planned_capital = plan.quantity * planned_cost
        cand = Candidate(plan.opportunity_id, ev.game_id, sup.poller.league,
                         ((plan.first.venue, plan.first.contracts, plan.first.limit_price),
                          (plan.hedge.venue, plan.hedge.contracts, plan.hedge.limit_price)),
                         planned_profit, (planned_profit / planned_capital if planned_capital > 0 else 0.0),
                         STRATEGY_VERSION, max_age)
        # The cheap refusals BEFORE any round trip (2026-09-07, LAA @ BOS in play on the box): every
        # profitable print at q=25 and q=100 fetched both venues' balances -- two round trips on
        # the event loop -- only to be refused CAP_STAKE by the override. Dozens a minute stalled
        # the loop 5.6 s with 17 pollers live. The caps and the profit floor are known here.
        until = self.backoff.get(ev.game_id)
        if until is not None and time.monotonic() < until:
            self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="BACKOFF")
            return                                       # said when it was set; one line per backoff
        blocked_venue = getattr(self.venues.get("polymarket"), "geoblocked", None)
        if blocked_venue:
            if self.said.get("polymarket:geoblocked") != "said":
                self.said["polymarket:geoblocked"] = "said"
                print(f"  [risk] refused every cover: VENUE_GEOBLOCKED polymarket -- {blocked_venue[:120]} "
                      f"(this host cannot place Polymarket orders; restart from a permitted host)", flush=True)
            self.refuse("risk", "VENUE_GEOBLOCKED", sup.poller.league)
            self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="VENUE_GEOBLOCKED")
            return
        if self.caps and self.mode.risks_capital:
            stake = sum(c * p for _v, c, p in cand.legs)
            most = max(c for _v, c, _p in cand.legs)
            early = None
            if stake > float(self.caps.get("stake_usd", 0.0)):
                early = ("CAP_STAKE", f"{stake:.2f} > override stake cap {float(self.caps.get('stake_usd', 0.0)):.2f}")
            elif most > float(self.caps.get("max_contracts", 0.0)):
                early = ("CAP_CONTRACTS", f"{most:.0f} > override contract cap {float(self.caps.get('max_contracts', 0.0)):.0f}")
            elif cand.net_profit_usd < float(getattr(self.limits, "min_net_profit_usd", 0.0) or 0.0):
                early = ("MIN_PROFIT", f"{cand.net_profit_usd:.2f} < {float(getattr(self.limits, 'min_net_profit_usd', 0.0) or 0.0):.2f}")
            if early:
                key = f"{sup.short_name}:{early[0]}:{ev.quantity:g}"
                if self.said.get(key) != early[1][:12]:          # once per game, code and size, not per print
                    self.said[key] = early[1][:12]
                    print(f"  [risk] refused {sup.short_name}: {early[0]} {early[1]} (q={ev.quantity:g}, before any round trip)", flush=True)
                    self.refuse("risk", str(early[0]), sup.poller.league)
                    if early[0] in ("CAP_STAKE", "CAP_CONTRACTS") and ev.quantity <= min(QUANTITIES):
                        # The operator's rule (GATE row 2026-09-07): a cap that refuses the SMALLEST
                        # size the lane prices is a defect, not a limit. Said, stored, alarmed.
                        print(f"  [risk] CAP_BINDS_SMALLEST {sup.short_name}: {early[0]} {early[1]} at q={ev.quantity:g}", flush=True)
                        self.flag("CAP_BINDS_SMALLEST", f"{sup.short_name} {early[0]} {early[1]} q={ev.quantity:g}")
                self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail=str(early[0]))
                return
        if self.mode.sends_real_orders:
            # The round trips (balances, POSTs, settle polling: 0.2-10 s) leave the socket loop.
            # Until 2026-09-07 the whole machine ran here, inside the venue's receive callback:
            # no frame was read while a cover executed, the probe then declared a STALL and the
            # gate refused the next cover CLOCK_UNHEALTHY (four stalls of 6-11 s on the box, one
            # across a 13 % print). One flight at a time; the store is written from the loop only.
            if self.in_flight is not None:
                key = f"{sup.short_name}:IN_FLIGHT"
                if self.said.get(key) != self.in_flight:
                    self.said[key] = self.in_flight
                    print(f"  [risk] refused {sup.short_name}: IN_FLIGHT {self.in_flight} is executing", flush=True)
                self.refuse("risk", "IN_FLIGHT", sup.poller.league)
                self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="IN_FLIGHT")
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None                            # no loop (tests, a harness): the machine runs here
            if loop is not None:
                self.in_flight = ev.game_id
                for px in self.on_loop:
                    px.loop = loop
                # The record is the machine's from this instant, ON the loop, before any frame can
                # move it elsewhere (the first flight off the loop, STL @ SF 2026-09-08 00:40Z:
                # a later frame's NO_EDGE landed first and every move of the execution was refused).
                if not self._own_opportunity(plan.opportunity_id, sup):
                    self.in_flight = None
                    self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="OPPORTUNITY_NOT_OWNED")
                    return
                task = loop.create_task(self._execute_off_loop(sup, ev, plan, cand, offers, pre, m_entry))
                self.exec_tasks.add(task)
                task.add_done_callback(self.exec_tasks.discard)
                return
        balances = self._balances(pre) if self.mode.sends_real_orders else None
        aged = (replace(cand, max_book_age_s=cand.max_book_age_s + max(0.0, time.monotonic() - m_entry))
                if isinstance(cand, Candidate) else cand)
        clearance = self._clear(sup, aged, balances, pre)
        if clearance is None:
            self._f22_update(sizing, outcome="local_or_risk_refused_no_wire", detail="RISK_REFUSED")
            return
        pre["pre_machine_ms"] = round((time.monotonic() - m_entry) * 1000.0, 2)
        ex = self.coordinator.execute(plan, clearance, offers_books=books_snapshot(offers),
                                      venues_connected=self._connected(), pre_stages=pre,
                                      maker_guard=(lambda remaining: self._maker_rest_refusal(sup, plan, clearance, remaining))
                                      if plan.first.post_only and self.mode.risks_capital else None)
        # A test/replay stand-in may return no id; production report then leaves this decision
        # unresolved instead of manufacturing a link.
        self._f22_link_execution(sizing, ex)
        self._after_execution(sup, ev, ex)

    def _own_opportunity(self, opportunity_id: str, sup: Supervised) -> bool:
        if self.opportunities is None:
            return False
        try:
            opp = self.opportunities.load(opportunity_id)
            if opp is None:
                return False
            self.opportunities.move(opp, OpportunityStatus.EXECUTION_PENDING, now=time.time(), detail="dispatched")
            if self.store is not None:
                self.store.commit()
            return True
        except Exception as exc:  # noqa: BLE001 -- the record must not stop the flight; said once per cause
            key = f"{sup.short_name}:own:{type(exc).__name__}"
            if self.said.get(key) != "said":
                self.said[key] = "said"
                print(f"  [exec] opportunity record not owned before dispatch: {brief_error(exc)}", flush=True)
            return False

    def _cached_balances(self, pre: dict) -> dict | None:
        """Return a fresh guard snapshot without yielding to the worker pool.

        Even a zero-work `_balances` call queued with `asyncio.to_thread` can wait behind a burst
        of socket callbacks before its completion is delivered to the loop. The first F9 flight
        measured that queue hop at about 760 ms despite `balances_ms=0`. Read the immutable copy
        on the loop; only a real venue refresh belongs in the worker.
        """
        m = time.monotonic()
        age = m - self.balance_snapshot_mono if self.balance_snapshot_mono else float("inf")
        if self.balance_snapshot and age <= self.balance_snapshot_ttl_s:
            pre["balances_ms"] = round((time.monotonic() - m) * 1000.0, 2)
            pre["balance_cache_age_ms"] = round(age * 1000.0, 2)
            return dict(self.balance_snapshot)
        return None

    def _balances(self, pre: dict) -> dict | None:
        cached = self._cached_balances(pre)
        if cached is not None:
            return cached
        m = time.monotonic()
        got = {}
        for v, venue in self.venues.items():        # ONE round trip per venue (it was two, 2026-09-07)
            b = venue.balance()
            got[v] = b.available_usd if b else None
        pre["balances_ms"] = round((time.monotonic() - m) * 1000.0, 2)
        if any(b is None for b in got.values()):
            return None
        self.balance_snapshot = {v: float(b) for v, b in got.items()}
        self.balance_snapshot_mono = time.monotonic()
        pre["balance_cache_age_ms"] = 0.0
        return dict(self.balance_snapshot)

    def _connected(self) -> dict[str, bool]:
        pm_exec = self.venues.get("polymarket")
        user_stream = getattr(getattr(pm_exec, "transport", None), "user_stream", None)
        user_ok = (not self.mode.risks_capital
                   or (user_stream is not None and bool(user_stream.connected)))
        return {"kalshi": bool(self.ks and self.ks.connected),
                "polymarket": bool(self.ps and self.ps.connected and user_ok)}

    def _clear(self, sup: Supervised, cand: Candidate, balances: dict | None, pre: dict):
        """The risk gate, on the loop (it mints the reservation in the ledger). None when refused."""
        m = time.monotonic()
        clearance = clear(cand, mode=self.mode, limits=self.limits, ledger=self.ledger, kill=self.kill,
                          breaker=self.breaker, fills_today=self.fills_today, clock_healthy=self.clock_ok(),
                          fee_schedules_ok=bool(sup.fee_params.get("kalshi") and sup.fee_params.get("polymarket")),
                          balances=balances, venues_connected=self._connected(), caps=self.caps or None)
        pre["clear_ms"] = round((time.monotonic() - m) * 1000.0, 2)
        if hasattr(clearance, "code"):
            print(f"  [risk] refused {sup.short_name}: {clearance.code} {clearance.detail}", flush=True)
            self.refuse("risk", str(clearance.code), sup.poller.league)
            return None
        return clearance

    async def _execute_off_loop(self, sup: Supervised, ev, plan, cand: Candidate, offers: dict, pre: dict, m_entry: float) -> None:
        """Balances in a worker, the gate on the loop, the machine in a worker (its records,
        opportunity moves and journal rows come back to the loop through OnLoop), the
        bookkeeping on the loop. Nothing here raises into the loop; the flight always clears."""
        sizing_lineage = getattr(plan, "sizing", None) if plan is not None else None
        try:
            # A guard may fail after _execute dispatches this task but before the worker starts.
            # Recheck on the loop before the first balance read; protection has its own path.
            if self._guard_entry_refused(sup):
                self._f22_update(sizing_lineage, outcome="local_or_risk_refused_no_wire", detail="GUARD_FAILED")
                return
            # A guard snapshot is already authoritative and copying it cannot block. Do that on
            # the loop so a completed zero-work worker future does not sit behind socket traffic.
            balances = self._cached_balances(pre)
            if balances is None:
                balances = await asyncio.to_thread(self._balances, pre)
            if (plan is not None and getattr(plan, "sizing", None) and plan.first.post_only
                    and not self._hedge_capacity_ok(sup, plan, plan.quantity)):
                print(f"  [risk] refused {sup.short_name}: HEDGE_DEPTH_CHANGED before entry", flush=True)
                self.refuse("risk", "HEDGE_DEPTH_CHANGED", sup.poller.league)
                self._f22_update(sizing_lineage, outcome="local_or_risk_refused_no_wire", detail="HEDGE_DEPTH_CHANGED")
                return
            aged = (replace(cand, max_book_age_s=cand.max_book_age_s + max(0.0, time.monotonic() - m_entry))
                    if isinstance(cand, Candidate) else cand)
            clearance = self._clear(sup, aged, balances, pre)
            if clearance is None:
                self._f22_update(sizing_lineage, outcome="local_or_risk_refused_no_wire", detail="RISK_REFUSED")
                return
            pre["pre_machine_ms"] = round((time.monotonic() - m_entry) * 1000.0, 2)
            # L97: the `asyncio.to_thread` hop below had no stage at all, and it is the largest
            # structurally-unmeasured interval on the path -- the executor is shared with discovery,
            # the guard, retention and settlement, and a comparable hop was once measured at ~760 ms
            # despite `balances_ms=0`. The coordinator converts this into `worker_hop_ms`.
            pre["_dispatch_mono"] = time.monotonic()
            books = books_snapshot(offers)
            connected = self._connected()
            loop_proxy = OnLoop(self, asyncio.get_running_loop())
            maker_guard = (lambda remaining, timeout_s=None: loop_proxy._maker_rest_refusal(
                sup, plan, clearance, remaining, _timeout_s=timeout_s)) \
                if plan.first.post_only and self.mode.risks_capital else None
            ex = await asyncio.to_thread(self.coordinator.execute, plan, clearance, offers_books=books,
                                         venues_connected=connected, pre_stages=pre,
                                         maker_guard=maker_guard)
            self._f22_link_execution(sizing_lineage, ex)
            self._after_execution(sup, ev, ex)
        except Exception as exc:  # noqa: BLE001 -- an execution bug must never kill the loop; it is said, counted, flagged
            # The machine itself records a machine error as an execution failure (UNKNOWN_PROVIDER_STATE
            # once leg A is out); reaching here means even that failed. Traceback to the log, a
            # lane flag for the watchdog, and no new cover on this game for the backoff.
            key = (ev.game_id, "exec:" + type(exc).__name__)
            self.record_errors[key] = self.record_errors.get(key, 0) + 1
            tb = traceback.format_exc().strip().splitlines()
            print(f"  [exec FAILED] {sup.short_name} {brief_error(exc)}\n    " + "\n    ".join(tb[-4:]), flush=True)
            self._f22_update(sizing_lineage, outcome="persistence_or_reconciliation_failure", detail="execution dispatch failure")
            self.backoff[ev.game_id] = time.monotonic() + self.backoff_s
            self.flag("EXEC_CRASHED", f"{sup.short_name} q={ev.quantity:g} {brief_error(exc)}")
        finally:
            self.in_flight = None

    def warm_pm_metadata(self, *, budget: int = 12, spacing_s: float = 0.12) -> dict:
        """L102 (2026-09-14): warm the Polymarket SDK's per-token metadata before an order needs it.

        `create_market_order` calls `__ensure_market_info_cached(token_id)` before it signs anything,
        and on an unseen token that is two blocking GETs -- `/markets-by-token/{token}` and then
        `/clob-markets/{condition_id}`. Sports tokens are new every game, so nearly every first leg
        paid it: measured on this box, leg A submit-to-ack is **559.6 ms p50 on the FIRST order for a
        token (n=71) against 205.7 ms on a REPEAT (n=56)**, and 56 % of orders were firsts. Signing
        itself is under 7 ms, so this gap is the whole of it.

        `get_fee_exponent` is the cheapest public call on exactly that path -- its body is the same
        `__fee_infos` check followed by the same `__ensure_market_info_cached`. One call warms every
        token in the market, because the response carries them all, so this loop is self-deduping:
        an already-warm token costs a dict lookup and no HTTP at all.

        Runs in a worker thread, paced, and fail-soft by construction: a warm-up that fails leaves
        the cache exactly as cold as it is today. It can slow a trade down to the status quo; it can
        never block or fail one.
        """
        venue = (self.venues or {}).get("polymarket")
        client = getattr(getattr(venue, "transport", None), "_c", None)
        if client is None or not callable(getattr(client, "get_fee_exponent", None)):
            return {}                       # paper/shadow modes hold no transport to warm
        want = {t for s in self.live.values() for t in s.pm_assets}
        self._pm_warmed &= want              # a token that rotated off the slate is not worth keeping
        warmed = errors = 0
        for token in sorted(want - self._pm_warmed):
            if warmed >= budget:
                break                       # the backlog drains over the next discovery passes
            try:
                client.get_fee_exponent(token)
                self._pm_warmed.add(token)
                warmed += 1
            except Exception:  # noqa: BLE001 -- a cold cache is the status quo, never a failure
                errors += 1
            # The SDK bypasses kernel/fetch's rate limiter entirely (its own module-level httpx
            # client), so the pacing has to be ours. This sleep is in the worker; the loop is free.
            time.sleep(spacing_s)
        return {"warmed": warmed, "errors": errors, "known": len(self._pm_warmed),
                "pending": len(want - self._pm_warmed)}

    def _hedge_capacity_ok(self, sup: Supervised, plan, quantity: float) -> bool:
        """Fresh loop-owned Kalshi depth for the full prospective maker fill."""
        now = time.time()
        for venue, market_id, side, rep in sup.poller.registrations():
            plan_side = plan.hedge.side.removeprefix("buy_").removeprefix("sell_")
            if venue == plan.hedge.venue and market_id == plan.hedge.market_id and side == plan_side:
                book = rep.snapshot(now, max_age_s=sup.poller.max_book_age_s)
                price = marginal_price(book, quantity) if book is not None else None
                gross, full = walk_ladder(book, quantity) if book is not None else (0.0, False)
                budget = quantity * plan.hedge_budget(plan.first.limit_price)
                return (full and price is not None and price <= plan.hedge.limit_price + 1e-9
                        and gross <= budget + 1e-9)
        return False

    def _maker_rest_refusal(self, sup: Supervised, plan, clearance, remaining: float) -> str | None:
        """Continuous loop-owned proof for the unfilled maker remainder.

        The worker calls this through ``OnLoop``. It reads the same replicas, kill/breaker,
        signed caps, balance snapshot and durable reservation that admitted entry; any missing
        component cancels the maker order immediately.
        """
        if remaining <= 1e-9:
            return "MAKER_COMPLETE"
        if self.arm_stale:
            return "ARM_STALE"
        connected = self._connected()
        if self.ledger is None or not self.ledger.has_event(plan.event_id):
            return "HEDGE_RESERVATION_MISSING"
        reservation = next((r for r in self.ledger.open.values() if r.event_id == plan.event_id), None)
        full_hedge_usd = plan.hedge.contracts * plan.hedge.limit_price
        if reservation is None or float(reservation.per_venue_usd.get(plan.hedge.venue, 0.0)) + 1e-9 < full_hedge_usd:
            return "HEDGE_RESERVATION_SHORT"
        age = time.monotonic() - self.balance_snapshot_mono if self.balance_snapshot_mono else float("inf")
        if age > self.balance_snapshot_ttl_s:
            return "BALANCE_SNAPSHOT_STALE"
        need = {plan.first.venue: plan.first.contracts * plan.first.limit_price,
                plan.hedge.venue: full_hedge_usd}
        if any(float(self.balance_snapshot.get(v, 0.0)) + 1e-9 < usd for v, usd in need.items()):
            return "BALANCE_CHANGED"
        for venue, market_id, side, rep in sup.poller.registrations():
            plan_side = plan.hedge.side.removeprefix("buy_").removeprefix("sell_")
            if venue == plan.hedge.venue and market_id == plan.hedge.market_id and side == plan_side:
                book = rep.snapshot(time.time(), max_age_s=sup.poller.max_rest_book_age_s)
                if book is None:
                    return "HEDGE_BOOK_STALE"
                fee_reserve = plan.quantity * (plan.fee_per_contract + plan.settlement_buffer_per_contract)
                auth = MakerRestAuthorization(
                    authorization_id=str(getattr(reservation, "reservation_id", "session")),
                    maker_client_order_id=str(getattr(clearance, "opportunity_id", plan.opportunity_id)),
                    authorized_contracts=str(plan.quantity),
                    deadline_mono=float(getattr(clearance, "maker_rest_deadline_mono", None) or time.monotonic()),
                    hard_hedge_limit=str(plan.hedge.limit_price),
                    max_hedge_book_age_s=float(sup.poller.max_rest_book_age_s),
                )
                decision = MakerFillSession(
                    auth, confirmed_fill_high_water=str(max(0.0, plan.quantity - remaining))
                ).validate_rest(MakerRestInputs(
                    now_mono=time.monotonic(),
                    # ``fetched_utc`` is BookReplica.as_of(): mutation, verification, or heartbeat.
                    # Project that currentness proof onto monotonic time. ``received_mono`` is
                    # mutation-only and would cancel a quiet but continuously verified ladder.
                    hedge_book_received_mono=float(
                        time.monotonic() - max(0.0, time.time() - book.fetched_utc)),
                    hedge_asks=tuple(HedgeLevel(str(q.price), str(q.size)) for q in book.asks),
                    maker_connected=bool(connected.get(plan.first.venue, False)),
                    hedge_connected=bool(connected.get(plan.hedge.venue, False)),
                    clock_healthy=self.clock_ok(),
                    kill_active=bool(self.kill is None or self.kill.active(
                        event_id=plan.event_id, strategy=plan.strategy_version, live=True,
                        venues=(plan.first.venue, plan.hedge.venue))),
                    breaker_active=bool(self.breaker is None or self.breaker.evaluate(
                        self.fills_today, max_daily_loss_usd=self.limits.max_daily_realized_loss_usd)),
                    hedge_budget_usd=str(remaining * plan.hedge_budget(plan.first.limit_price)),
                    session_budget_usd=str(plan.first.contracts * plan.first.limit_price
                                           + remaining * plan.hedge_budget(plan.first.limit_price) + fee_reserve),
                    stake_cap_usd=str(float(self.caps.get("stake_usd", 0.0)) + fee_reserve),
                    contract_cap=str(float(self.caps.get("max_contracts", 0.0))),
                    day_cost_used_usd=str(max(0.0, self.ledger.day_notional_usd() - reservation.total_usd)),
                    day_cost_cap_usd=str(float(self.caps.get("day_notional_usd", 0.0)) + fee_reserve),
                    fixed_session_cost_usd=str(plan.first.contracts * plan.first.limit_price),
                    committed_hedge_cost_usd="0",
                    hedge_fee_reserve_usd=str(fee_reserve),
                ))
                return None if decision.allowed else decision.block.value
        return "HEDGE_BOOK_MISSING"

    def fresh_book(self, venue: str, market_id: str, side: str = "buy_yes"):
        """The protection layer's live book for a chase or an unwind: the venue's REST book (it runs
        in the worker thread, off the loop). None when the venue cannot say; the layer then goes
        to the phase's ceiling in one order."""
        v = self.venues.get(venue)
        try:
            return v.orderbook(market_id, side) if v is not None and hasattr(v, "orderbook") else None
        except Exception:  # noqa: BLE001
            return None

    def refuse(self, channel: str, code: str, league: str = "") -> None:
        """Count one refusal. The two channels are not the same question (L113).

        `size` is `nodes/execute/sizing`'s read-only mirror saying no whole quantity in 1..cap could
        have worked, so nothing was proposed; `risk` is `nodes/risk.clear` -- the authoritative gate
        that owns the reservation -- rejecting a quantity that WAS proposed. An epoch emits one or
        the other, never both, because `_execute_sized` returns before `_execute` is reached.
        """
        key = (channel, code or "UNKNOWN", league or "")
        self.refusals[key] = self.refusals.get(key, 0) + 1

    def _guard_entry_refused(self, sup) -> bool:
        """Refuse a new capital entry while the guard's health proof is invalid.

        The guard's kill is durable and is normally the first refusal seen by ``clear()``.  This
        separate in-memory gate is required when either alarm write failed, and remains in force
        until a complete pass restores health even if a human clears an unrelated live switch.
        It is intentionally not consulted by the protection path, which must remain able to hedge
        or unwind an already-open position.
        """
        if not self.guard_unhealthy or not getattr(self.mode, "risks_capital", False):
            return False
        league = getattr(getattr(sup, "poller", None), "league", "")
        key = f"{getattr(sup, 'short_name', league)}:GUARD_FAILED"
        if self.said.get(key) != self.guard_failure_detail:
            self.said[key] = self.guard_failure_detail
            print(f"  [risk] refused {getattr(sup, 'short_name', league)}: GUARD_FAILED "
                  f"{self.guard_failure_detail or 'guard health unavailable'}", flush=True)
        self.refuse("risk", "GUARD_FAILED", league)
        return True

    def _guard_pass_complete(self, snap) -> bool:
        """Require the full reconciliation proof before reopening capital entry.

        ``PositionGuard.fetch`` intentionally returns a structured snapshot even when one of its
        reads fails. Capital mode may only recover from that state when fills were read completely,
        every configured venue returned position evidence, and no errors remain. Balances are not
        required here: adapters may legitimately omit a balance while still providing complete
        position reconciliation (the entry gate will independently require balances).
        """
        if not getattr(self.mode, "risks_capital", False):
            return True
        if getattr(snap, "fills_read_complete", False) is not True:
            return False
        if getattr(snap, "errors", None):
            return False
        positions = getattr(snap, "positions", None)
        if not isinstance(positions, dict):
            return False
        return all(venue in positions and positions[venue] is not None for venue in self.venues)

    def _count_size_refusal(self, sup, decision) -> None:
        """Every binding constraint, counted separately: the sizer reports a SET, and which members
        co-occur is the finding. `CAP_CONTRACTS` is unioned in unconditionally by both return paths
        in `sizing.py`, so it is noise and is dropped here rather than swamping the table."""
        codes = [c for c in (decision.binding_constraints or ()) if c != "CAP_CONTRACTS"]
        for code in codes or ["NO_FEASIBLE_SIZE"]:
            self.refuse("size", str(code).split(":")[0], sup.poller.league)

    def flag(self, name: str, detail: str, *, on=None) -> bool:
        """Raise a lane flag on the connection THIS thread owns -- the only way the grid flags.

        `self.store` is the loop's connection (check_same_thread=True); `self.worker_store` is the
        worker's. Callbacks that run in the worker (`on_unprotected`, and anything reached from
        `asyncio.to_thread`) cannot use the former, and the failure is a swallowed ProgrammingError
        that costs the alarm silently -- 3,373 of 3,373 protect latches wrote no flag that way.
        Choosing per call site is what went wrong, so no call site chooses: `worker_store` works
        from either thread, and is preferred whenever it exists.

        `on` is an optional Execution whose `protect` dict records a failure, so a lost audit write
        leaves a trace on the row as well as in the log.
        """
        store = self.worker_store if self.worker_store is not None else self.store
        if store is None:
            return False
        try:
            raise_flag(store, name, detail)
            return True
        except Exception as exc:  # noqa: BLE001 -- a flag must never break the caller
            detail_map = getattr(on, "protect", None)
            if isinstance(detail_map, dict):
                detail_map[f"{name.lower()}_flag_error"] = brief_error(exc)
            print(f"  [risk] flag write failed ({name}): {brief_error(exc)}", flush=True)
            return False

    def on_unprotected(self, ex, text: str) -> None:
        """A position the layer could neither hedge nor unwind inside the cap (2026-09-08): the
        operator's decision is fail closed. The live kill is latched (real orders stop; pricing
        continues; protective re-runs still go through clear_protect), the flag is written for the
        watchdog, and the line is said. Runs in the worker thread: files and the main-store flag only."""
        print(f"  [PROTECT FAILED] {ex.event_id} {ex.execution_id[:8]} {text}", flush=True)
        # L76: the next re-run is seconds away, not a guard pass away. The loop's tick picks it up.
        pr = getattr(self.limits, "protect", None)
        retry = float(getattr(pr, "protect_retry_s", 0.0) or 0.0)
        if retry > 0 and getattr(pr, "protect_auto", False):
            now_m = time.monotonic()
            # L100 (2026-09-13): this re-armed the window on EVERY failure, so `until` moved forward
            # `protect_fast_window_s` each time and the window never expired. Execution 77013052 held
            # a 1.5625-share residual that `protect.py`'s quantity cap can never hedge without new
            # authority; it re-ran 2,840 times over two hours and wrote 2,836 of the 5,322 rows in
            # `execution_transitions` -- 53 % of the table -- for a verdict that could not change.
            # The window belongs to the naked POSITION, not to the latest failed attempt: arm it once
            # and let it expire into the guard's own 30 s cadence.
            prior = self.reprotect_fast.get(ex.execution_id)
            until = prior[1] if prior is not None else now_m + float(getattr(pr, "protect_fast_window_s", 60.0) or 0.0)
            self.reprotect_fast[ex.execution_id] = (now_m + retry, until)
        # The flag goes on the connection THIS thread owns.  `on_unprotected` only ever runs in the
        # worker (`asyncio.to_thread`, _execute_off_loop / _protect_off_loop) and `self.store` is the
        # loop's connection, opened check_same_thread=True -- so every write here raised
        # ProgrammingError and was swallowed below.  3,373 of 3,373 protect latches between
        # 2026-09-08 and 2026-09-14 wrote no flag at all: the watchdog's PROTECT_FAILED alarm could
        # never fire beside the kill it belongs to.  `worker_store` is check_same_thread=False.
        self.flag("PROTECT_FAILED", f"{ex.execution_id[:8]} {ex.event_id} {text}", on=ex)
        kill_it = bool(getattr(getattr(self.limits, "protect", None), "protect_kill_on_failure", True))
        if kill_it and self.kill is not None and self.mode.risks_capital:
            try:
                self.kill.latch("live", f"protect: {ex.execution_id[:8]} {ex.event_id} {text[:120]}")
                print("  [risk] kill/live latched by the protection layer; real orders stop until a human clears it", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  [risk] kill latch failed: {type(exc).__name__}", flush=True)

    def _guard_failed(self, exc: BaseException) -> None:
        """Record a failed guard pass and close the capital-entry gate.

        This handler runs on the loop after ``fetch`` returns from ``asyncio.to_thread`` (or after
        ``apply`` raises), so the flag write must use the connection selected by ``flag`` rather
        than reaching into the worker-owned guard journal. Kill/lane-flag writes are independent:
        a failure of either leaves ``guard_unhealthy`` set and therefore cannot become logging-only.
        ``KillSwitches.latch`` itself is exclusive, preserving the first writer's provenance.
        """
        try:
            diag = brief_error(exc)
        except Exception:  # noqa: BLE001 -- even diagnostic formatting cannot reopen entry
            diag = repr(exc)
        detail = f"{type(exc).__name__}: {diag}"[:180]
        self.guard_unhealthy = True
        self.guard_failure_detail = detail
        # Any snapshots from before the failed pass are not authoritative.  In particular, do not
        # let a stale balance or breaker fill view survive a failed fetch/apply.
        self.balance_snapshot = {}
        self.balance_snapshot_mono = 0.0
        self.fills_today = ()

        if getattr(self.mode, "risks_capital", False):
            if self.kill is None:
                print("  [guard kill latch failed] no kill switch configured", flush=True)
            else:
                try:
                    self.kill.latch("live", f"guard failed: {detail}"[:220])
                except Exception as kill_exc:  # noqa: BLE001 -- preserve the guard failure visibly
                    print(f"  [guard kill latch failed] {brief_error(kill_exc)}", flush=True)
        # Keep the alarm observable below LIMITED_LIVE, but acquire no live kill/order authority
        # there. A failed write is itself an unhealthy state, retained in memory above.
        try:
            alarm_ok = self.flag("GUARD_FAILED", detail)
        except Exception as flag_exc:  # noqa: BLE001 -- alarm failure must not reopen entry
            alarm_ok = False
            print(f"  [guard alarm write failed] {brief_error(flag_exc)}", flush=True)
        if not alarm_ok:
            print("  [guard alarm] GUARD_FAILED durable write unavailable; entry remains refused", flush=True)

    async def guard_pass(self) -> None:
        """One pass of the position guard: the network half in a worker, the state half here.
        Serialised with executions through `in_flight` (one connection, one thread at a time).
        Alarm-only until [protect] protect_auto: a naked execution is said and flagged; the
        re-protection is R5's."""
        if self.guard is None or self.in_flight is not None:
            return
        self.in_flight = "guard"
        try:
            snap = await asyncio.to_thread(self.guard.fetch)
            rep = self.guard.apply(snap)
            # A partial snapshot may still prove an already-open execution is naked. Preserve the
            # protection hand-off before deciding whether this pass is complete enough to admit
            # NEW capital. Protection re-loads the durable row and receives its own clearance.
            for line in rep.findings:
                print(f"  [guard] {line}", flush=True)
            if rep.to_protect:
                auto = bool(getattr(getattr(self.limits, "protect", None), "protect_auto", False))
                key = "guard:naked:" + ",".join(rep.to_protect)
                if self.said.get(key) != "said":
                    self.said[key] = "said"
                    print(f"  [guard] naked and idle: {', '.join(x[:8] for x in rep.to_protect)}"
                          + (" (protect_auto on: re-protection follows)" if auto else " (protect_auto off: by hand, ops/reconcile_stuck_execution.py)"), flush=True)
                if auto:
                    self.reprotect_queue = list(rep.to_protect)
            # PositionGuard.fetch reports venue/read failures in ``snap.errors`` so the loop can
            # still inspect the rest of the evidence. Such a snapshot is not a complete pass and
            # takes the same fail-closed path as an exception; only a complete pass restores health.
            if not self._guard_pass_complete(snap):
                errors = getattr(snap, "errors", None) or {}
                detail = "; ".join(f"{k}: {v}" for k, v in sorted(errors.items()))
                if not detail:
                    detail = "missing complete fills/positions proof"
                raise RuntimeError(f"incomplete guard snapshot: {detail[:140]}")
            if getattr(snap, "balances", None) and set(snap.balances) >= set(self.venues):
                self.balance_snapshot = dict(snap.balances)
                self.balance_snapshot_mono = time.monotonic()
            self.fills_today = rep.fills_today
            self.guard_passes += 1
            # Recovery is intentionally in-memory only. Do not resolve GUARD_FAILED or clear the
            # live kill here; both are durable operator evidence and require an explicit human act.
            self.guard_unhealthy = False
            self.guard_failure_detail = ""
        except Exception as exc:  # noqa: BLE001 -- the guard must never kill the loop
            print(f"  [guard FAILED] {brief_error(exc)}", flush=True)
            self._guard_failed(exc)
        finally:
            self.in_flight = None
        # One re-protection per pass, after the guard's slot is released: the layer runs in the
        # worker under its own flight, exactly like a fresh execution.
        if self.reprotect_queue:
            await self._protect_off_loop(self.reprotect_queue.pop(0))

    def fast_reprotect_due(self, now_mono: float | None = None) -> list[str]:
        """L76: the naked executions whose fast retry is due, oldest first; entries past their
        window are dropped here (the guard's 30 s cadence takes over)."""
        t = time.monotonic() if now_mono is None else now_mono
        due = []
        for exid, (next_due, until) in list(self.reprotect_fast.items()):
            if t > until:
                del self.reprotect_fast[exid]
            elif t >= next_due:
                due.append((next_due, exid))
        return [e for _, e in sorted(due)]

    async def fast_reprotect_tick(self) -> None:
        """One due fast re-run per loop iteration (the loop sleeps 1 s; the cadence is 3 s). A run
        that leaves the position hedged, released or terminal drops the entry; one that leaves it
        naked reschedules it `protect_retry_s` later inside the window."""
        if self.in_flight is not None:
            return
        for exid in self.fast_reprotect_due():
            pr = getattr(self.limits, "protect", None)
            retry = float(getattr(pr, "protect_retry_s", 0.0) or 0.0)
            out = await self._protect_off_loop(exid)
            still = out is not None and out.state.holds_position and not out.released \
                and out.unhedged > float(getattr(pr, "protect_dust_contracts", 1.0) or 1.0)
            if still and retry > 0 and exid in self.reprotect_fast:
                self.reprotect_fast[exid] = (time.monotonic() + retry, self.reprotect_fast[exid][1])
            else:
                self.reprotect_fast.pop(exid, None)
            break

    async def _protect_off_loop(self, execution_id: str):
        """The guard's hand-over (R5, 2026-09-08): the execution the venue says is naked, loaded from
        its row with its plan, given a `clear_protect` clearance on the loop, and run through the
        protection layer in the worker thread. The row's own reservation is what it holds; a
        released end state (UNWOUND) releases it here like any other."""
        if self.in_flight is not None or self.coordinator is None:
            return
        records = getattr(self.coordinator, "records", None)
        ex = records.load(execution_id) if records is not None else None
        plan = records.plan_of(execution_id) if records is not None else None
        if ex is None or plan is None:
            print(f"  [protect] {execution_id[:8]}: no row or no plan to re-run from", flush=True)
            return
        if ex.state.is_terminal or ex.released:
            return
        c = clear_protect(opportunity_id=ex.opportunity_id, event_id=ex.event_id, venues=(plan.first.venue, plan.hedge.venue),
                          mode=self.mode, limits=self.limits, kill=self.kill, now_mono=time.monotonic())
        if hasattr(c, "code"):
            print(f"  [protect] {execution_id[:8]} refused: {c.code} {c.detail}", flush=True)
            return
        self.in_flight = ex.event_id
        for px in self.on_loop:
            px.loop = asyncio.get_running_loop()
        sup = next((s for s in self.live.values() if s.poller.game_id == ex.event_id), None)
        short = sup.short_name if sup is not None else ex.event_id
        try:
            print(f"  [protect] re-run {execution_id[:8]} {short}: unhedged {ex.unhedged:g} overhedged {ex.overhedged:g}", flush=True)
            out = await asyncio.to_thread(self.coordinator.protect_existing, ex, plan, c)
            self.executions += 1
            print(f"  [exec] {short} {out.state.value} first={out.first_filled}@{out.first_avg_price} "
                  f"hedge={out.hedge_filled}@{out.hedge_avg_price} unhedged={out.unhedged} unwound={out.first_unwound} {out.detail}", flush=True)
            if out.released and self.ledger is not None and out.reservation_id:
                self.ledger.release(out.reservation_id, reason=f"protection re-run: {out.state.value}")
            return out
        except Exception as exc:  # noqa: BLE001
            print(f"  [protect FAILED] {short} {brief_error(exc)}", flush=True)
        finally:
            self.in_flight = None
        return None

    def _after_execution(self, sup: Supervised, ev, ex) -> None:
        self.executions += 1
        if ex.first_filled > 0 or ex.hedge_filled > 0:
            # A real fill moved collateral. Force the next flight to confirm balances unless a
            # newer guard pass has already replaced this snapshot.
            self.balance_snapshot_mono = 0.0
        print(f"  [exec] {sup.short_name} {ex.state.value} first={ex.first_filled}@{ex.first_avg_price} "
              f"hedge={ex.hedge_filled}@{ex.hedge_avg_price} unhedged={ex.unhedged} {ex.detail}", flush=True)
        try:
            print(f"  [latency] {sup.short_name} " + " ".join(f"{k}={v}" for k, v in sorted(ex.stages.items())), flush=True)
        except Exception:  # noqa: BLE001 -- reporting must never break the loop
            pass
        if ex.released and self.ledger is not None:
            self.ledger.release(ex.reservation_id, reason=f"nothing filled: {ex.state.value}")
        elif ex.state.value == "HEDGED" and self.ledger is not None and ex.reservation_id:
            # L114: both legs are filled, so this attempt is no longer IN FLIGHT and the event may
            # be entered again. The capital stays committed until settlement -- the contracts really
            # are held -- so every notional cap keeps counting it. Only the single-flight refusal
            # ends. Holding it until the reconcile pass hours later meant one cover per event, ever,
            # which caps the architecture near 40 covers a day whatever the universe looks like.
            if self.ledger.mark_hedged(ex.reservation_id):
                print(f"  [risk] {sup.short_name} hedged: event free to enter again "
                      f"(capital still committed)", flush=True)
        if ex.state.value == "UNKNOWN_PROVIDER_STATE" and self.mode.risks_capital:
            self.flag("UNKNOWN_PROVIDER_STATE", f"{ex.execution_id[:8]} {ex.event_id} {ex.detail[:180]}", on=ex)
            print("  [risk] kill/live latched: a submitted order has no authoritative outcome", flush=True)
        if ex.first_filled <= 0 and ex.state.value in ("ORDER_REJECTED", "UNKNOWN_PROVIDER_STATE"):
            self.backoff[ev.game_id] = time.monotonic() + self.backoff_s
            print(f"  [risk] backoff {sup.short_name} {self.backoff_s:g}s after {ex.state.value} on leg A", flush=True)

    def stats(self) -> dict:
        return {"live": len(self.live), "mode": self.mode.value, "executions": self.executions, "spawned": self.spawned, "reaped": self.reaped,
                "evaluations": sum(s.evaluations for s in self.live.values()),
                "record_errors": sum(self.record_errors.values()),
                "loop_lag_max_s": round(self.loop_lag_max_s, 3),
                "rows": sum(s.written for s in self.live.values()),
                "kalshi": self.ks.stats() if self.ks else None,
                "polymarket": self.ps.stats() if self.ps else None}


_STOP = False


def _on_signal(signum, _frame):
    global _STOP
    _STOP = True
    print(f"\n[signal {signum}] draining", flush=True)


async def run(sup: Supervisor, *, discovery_period: float, report_period: float,
              once: bool) -> None:
    stop = asyncio.Event()
    tasks = [asyncio.create_task(sup.ks.run(stop, on_state=lambda k, d: print(f"  [kalshi {k}] {d}", flush=True))),
             asyncio.create_task(sup.ps.run(stop, on_state=lambda k, d: print(f"  [pm {k}] {d}", flush=True)))]
    if sup.ps.reconciler is not None:
        tasks.append(asyncio.create_task(sup.ps.reconciler.run(stop)))
    pm_exec = sup.venues.get("polymarket")
    user_stream = getattr(getattr(pm_exec, "transport", None), "user_stream", None)
    if user_stream is not None:
        tasks.append(asyncio.create_task(user_stream.run(
            stop, on_state=lambda k, d: print(f"  [pm-user {k}] {d}", flush=True))))

    async def loop_probe(period: float = 0.25) -> None:
        # The one honest measure of the loop: how late a sleep wakes. Everything the sockets
        # stamp is late by at least this much when it is large.
        while not stop.is_set():
            t0 = time.monotonic()
            await asyncio.sleep(period)
            sup.loop_probe_reading(max(0.0, time.monotonic() - t0 - period))
    tasks.append(asyncio.create_task(loop_probe()))
    last_disc = 0.0
    last_report = time.time()
    last_settle = time.time()
    last_guard = 0.0
    guard_period = float(getattr(getattr(sup.limits, "protect", None), "guard_period_s", 30.0) or 30.0)
    try:
        while not _STOP:
            sup.write_board()                     # the board: one small JSON a second for the terminal page
            if sup.reprotect_fast:
                await sup.fast_reprotect_tick()       # L76: a naked position is retried in seconds
            if sup.guard is not None and time.time() - last_guard > guard_period:
                last_guard = time.time()
                await sup.guard_pass()
            if sup.ledger is not None and time.time() - last_settle > SETTLE_PERIOD_S:
                # Finished games: settle every execution still holding capital against each venue's
                # own result (nodes/reconcile/settle_executions). Network in a worker, state here.
                last_settle = time.time()
                try:
                    items = pending(sup.store)
                    if items:
                        winners = await asyncio.to_thread(fetch_results, items, Client("settle", rate=4, burst=8, cache_dir=None))
                        got = apply_settlements(sup.store, sup.ledger, None, sup.opportunities, items, winners)
                        if got["settled"] or got["unreleasable"]:
                            print(f"[settle ] {got}", flush=True)
                except Exception as exc:  # noqa: BLE001 -- settlement must never kill the loop
                    print(f"[settle FAILED] {brief_error(exc)}", flush=True)
            if sup.retain_days > 0 and time.time() - sup.last_retain > sup.retain_period_s:
                # L72: retention in a worker on its own connection; the loop never waits on a DELETE.
                sup.last_retain = time.time()
                try:
                    got = await asyncio.to_thread(sup.retain_once)
                    if got.get("frames") or any(v for k, v in got.items() if k not in ("_more", "frames")):
                        print(f"[retain] {got}", flush=True)
                except Exception as exc:  # noqa: BLE001 -- retention must never kill the loop
                    print(f"[retain FAILED] {brief_error(exc)}", flush=True)
            if time.time() - last_disc > discovery_period:
                try:
                    # The network halves run in a worker so the sockets keep being read (L37);
                    # the state halves run here, on the loop, where the store and replicas live.
                    now_d, d = await asyncio.to_thread(sup.fetch_discovery)
                    slate = sup.apply_discovery(now_d, d)
                    sup.reconcile(slate)
                    try:
                        warm = await asyncio.to_thread(sup.warm_pm_metadata)
                        if warm.get("warmed") or warm.get("errors"):
                            print(f"[warm] polymarket metadata {warm}", flush=True)
                    except Exception as exc:  # noqa: BLE001 -- warming must never break discovery
                        print(f"[warm FAILED] {type(exc).__name__}: {exc}", flush=True)
                    try:
                        added, removed = sup.apply_watch(await asyncio.to_thread(sup.fetch_watch))
                        if added or removed:
                            print(f"[watch] capture-only +{added} -{removed}: {sup.watch.stats()} rows={sup.watch_rows}", flush=True)
                    except Exception as exc:  # noqa: BLE001 -- capture-only must never break discovery
                        print(f"[watch FAILED] {type(exc).__name__}: {exc}", flush=True)
                    print(f"[slate] {len(slate)} co-listed games {sup.tiers}, {len(sup.live)} pollers, "
                          f"box {sup.wake_state[0]}" + (f" -> {sup.wake_state[1]} in "
                          f"{int(sup.wake_state[2] - time.time())}s" if sup.wake_state[1] else "")
                          + ((f", blocked: {len(sup.blocked)}" + (f" (spawn {n_spawn})" if (n_spawn := sum(1 for r in sup.blocked.values() if str(r).startswith('SPAWN:'))) else ""))
                             if sup.blocked else ""), flush=True)
                except Exception as exc:  # noqa: BLE001 -- discovery must never kill the loop
                    print(f"[slate FAILED] {type(exc).__name__}: {exc}", flush=True)
                    traceback.print_exc()
                last_disc = time.time()
                if once:
                    await asyncio.sleep(15)
                    break
            if time.time() - last_report > report_period:
                lag_for_print = sup.loop_lag_max_s        # the tick resets it
                sup.on_report_tick()
                sup.check_arm()                           # the override, re-read every tick
                sup.store.commit()
                for st_ in (sup.ks, sup.ps):
                    if st_.capture is not None:
                        st_.capture.flush()
                st = sup.stats()
                k, p = st["kalshi"] or {}, st["polymarket"] or {}
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}Z] pollers={st['live']} "
                      f"evals={st['evaluations']} rows={st['rows']} | "
                      f"kalshi {k.get('frames',0)}f/{k.get('seq_gaps',0)}gap | "
                      f"pm {p.get('frames',0)}f/{p.get('drift',0)}drift/"
                      f"{p.get('agreement')} | loop {lag_for_print:.1f}s", flush=True)
                last_report = time.time()
            await asyncio.sleep(1)
    finally:
        stop.set()
        for v in sup.venues.values():
            try:
                v.cancel_all()          # cancel_all() on SIGTERM: nothing may rest
            except Exception as exc:  # noqa: BLE001
                print(f"  [cancel_all {getattr(v, 'venue', '?')}] {brief_error(exc)}", flush=True)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        sup.on_report_tick()          # a --once run must still leave a health row
        sup.store.commit()


def _runner_sha() -> tuple[str, str]:
    """(code tree sha, whole-checkout HEAD) of the tree this process runs from. The first is the
    arming override's pin (kernel/code_sha); the second is logged, for the record."""
    return code_tree_sha(ROOT), runner_head_sha(ROOT)


def _execution_spec(spec: dict) -> str:
    """Stable fingerprint of every discovery field that can alter execution semantics."""
    keys = (
        "league", "outcomes", "fee_params", "rules", "settlement", "settlement_proof",
        "pm_slug", "kalshi_event", "polymarket", "kalshi", "pm_limits", "order_limits",
        "tokens", "market_ids",
    )

    def normal(value):
        if isinstance(value, dict):
            return {str(k): normal(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))
                    if str(k) not in {"retrieved_at", "retrieved_utc", "fetched_utc"}}
        if isinstance(value, (set, frozenset)):
            return sorted(normal(v) for v in value)
        if isinstance(value, (list, tuple)):
            return [normal(v) for v in value]
        return value

    return json.dumps({k: normal(spec.get(k)) for k in keys}, sort_keys=True, separators=(",", ":"), default=str)


def _leagues_arg(text: str) -> list[str]:
    """'enabled' -> every registered league that lacks nothing today; otherwise the list as given."""
    if text.strip() == "enabled":
        return default_leagues()
    return [x.strip() for x in text.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default=",".join(LEAGUES),
                    help="registered leagues (nodes/entities/leagues.py), or the word 'enabled' for the ones that "
                         "lack nothing (default_leagues()); a named league lacking a cited rule or reviewed "
                         "templates blocks downstream, it is not filtered here")
    ap.add_argument("--pre-hours", type=float, default=2.0)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--discovery-period", type=float, default=300.0)
    ap.add_argument("--report-period", type=float, default=30.0)
    ap.add_argument("--max-book-age", type=float, default=5.0)
    ap.add_argument("--once", action="store_true", help="one discovery pass, ~15s of capture, exit")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--frames-root", type=Path, default=FRAMES_ROOT,
                    help="raw frame capture root (hour-rotated gzip JSONL per venue)")
    ap.add_argument("--no-capture", action="store_true", help="do not write raw frames")
    ap.add_argument("--retain-days", type=int, default=7,
                    help="L72: age out stream_evaluations/quote_history/socket_health/opportunity_history rows and raw "
                         "frame days older than this many days, from a worker thread; evidence tables are never touched; "
                         "0 disables")
    ap.add_argument("--retain-period", type=float, default=900.0, help="seconds between retention passes")
    ap.add_argument("--board", type=Path, default=DATA_ROOT / "board" / "board.json",
                    help="the one-second board snapshot for ops/box/board_server.py; '' disables")
    ap.add_argument("--mode", default="SHADOW_LIVE",
                    help="OFFLINE_REPLAY | SHADOW_LIVE | PAPER_EXECUTION | DEMO_EXECUTION | LIMITED_LIVE | PRODUCTION; "
                         "resolved once by nodes/risk.gate and never escalated")
    ap.add_argument("--capture-series", default="KXATPMATCH,KXWTAMATCH,KXATPCHALLENGERMATCH,KXWTACHALLENGERMATCH",
                    help="Kalshi series to subscribe for CAPTURE ONLY (no pricing): what the slate cannot co-list yet; '' to disable")
    ap.add_argument("--capture-pm-tags", default="tennis",
                    help="Polymarket tag slugs or ids whose game markets are subscribed for capture only; '' to disable")
    ap.add_argument("--reconcile-period", type=float, default=5.0,
                    help="seconds between Polymarket REST reconcile passes over quiet replicas")
    a = ap.parse_args()

    if a.self_test:
        s = Supervisor(_leagues_arg(a.leagues),
                       pre_hours=a.pre_hours)
        slate = s.discover()
        print(f"live_stream selftest OK — {len(slate)} co-listed live games, "
              f"{len(s.blocked)} blocked")
        return 0

    key_path = os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH")
    api_key = os.environ.get("JANUS_KALSHI_API_KEY")
    if not (api_key and key_path):
        print("missing JANUS_KALSHI_API_KEY / JANUS_KALSHI_PRIVATE_KEY_PATH; "
              "Kalshi authenticates every socket, even for public market data", file=sys.stderr)
        return 2

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    ambient = os.environ.get("JANUS_RUN_ID")
    run_id = ambient or run_index.start("live_stream", argv=sys.argv[1:])
    owns_row = ambient is None

    sup = Supervisor(_leagues_arg(a.leagues),
                     pre_hours=a.pre_hours, db=a.db, max_book_age_s=a.max_book_age)
    sup.store = TupleStore(a.db)
    sup.opportunities = OpportunityStore(sup.store)
    # The mode is decided ONCE, here, by the risk gate. Nothing below may escalate it.
    limits = load_limits()
    kill = KillSwitches()
    code_sha, head_sha = _runner_sha()
    resolved = resolve_mode(a.mode, env=os.environ, kill=kill, limits=limits, runner_sha=head_sha,
                            code_sha=code_sha, credentials_present={"kalshi": bool(api_key)})
    if hasattr(resolved, "code"):
        print(f"mode refused: {resolved.code}: {resolved.detail}", file=sys.stderr)
        return 2
    sup.mode = resolved.mode
    sup.caps = dict(getattr(resolved, "caps", None) or {})
    sup.code_sha = code_sha
    print(f"[code] tree {code_sha} runner {head_sha[:12]} limits {limits.sha}", flush=True)
    if sup.mode.rank >= Mode.PAPER_EXECUTION.rank:
        sup.worker_store = TupleStore(sup.db, check_same_thread=False, isolation_level="IMMEDIATE")
        journal = Journal(sup.worker_store)       # the worker thread's own connection (_execute_off_loop)
        # Real venues, built only for the modes that need them, from credentials that are named
        # by environment variable and never appear on the command line or in a log.
        def kalshi_factory(host: str):
            if host == "demo":
                key, path = os.environ.get("JANUS_KALSHI_DEMO_API_KEY"), os.environ.get("JANUS_KALSHI_DEMO_PRIVATE_KEY_PATH")
                if not (key and path):
                    raise ValueError("DEMO_EXECUTION needs JANUS_KALSHI_DEMO_API_KEY and JANUS_KALSHI_DEMO_PRIVATE_KEY_PATH "
                                     "(a demo account is separate from production)")
                return KalshiExecution(key, load_private_key(path), journal, sup.mode, base_url=DEMO_BASE)
            return KalshiExecution(api_key, load_private_key(key_path), journal, sup.mode, base_url=PROD_BASE)

        def polymarket_factory():
            return PolymarketExecution(PyClobTransport(), journal, sup.mode, kill=kill)

        try:
            sup.venues = build_venues(sup.mode, journal, kalshi_factory=kalshi_factory,
                                      polymarket_factory=polymarket_factory)
        except (ValueError, TransportUnavailable) as exc:
            print(f"mode {sup.mode.value} cannot be built: {exc}", file=sys.stderr)
            return 2
        sup.limits, sup.kill = limits, kill
        # Resolve the experiment authority before the event loop can admit its first entry. The
        # periodic report tick revalidates the same spec digest and statement thereafter.
        sup.check_arm()
        sup.breaker = LossBreaker(kill=kill)
        sup.ledger = ExposureLedger(sup.store)
        # The opportunity record's in-memory state belongs to the loop (record_evaluation mutates it
        # on every frame): the machine's status moves are queued to the loop, never waited for.
        # Records and the journal write through the worker's own connection (2026-09-08).
        def finish_opportunity_write(exc: Exception | None) -> None:
            """Close the main-store transaction opened by every queued status move."""
            if sup.store is None or not sup.store.con.in_transaction:
                return
            if exc is None:
                sup.store.commit()
            else:
                sup.store.con.rollback()

        opps = OnLoop(sup.opportunities, nowait={"move"}, after_call=finish_opportunity_write)
        sup.on_loop.append(opps)
        records = ExecutionRecords(sup.worker_store)
        sup.coordinator = Coordinator(sup.venues, records, sup.mode,
                                      hedge_deadline_s=limits.max_hedge_latency_ms / 1000.0,
                                      opportunities=opps, kill=kill, limits=limits.protect,
                                      fresh_book=sup.fresh_book, on_unprotected=sup.on_unprotected,
                                      min_net_profit_usd=float(getattr(limits, "min_net_profit_usd", 0.0) or 0.0))
        if sup.mode.sends_real_orders:
            sup.guard = PositionGuard(venues=sup.venues, journal=journal, records=records, store=sup.store,
                                      limits=limits.protect, started_utc=time.time(), ledger=sup.ledger, kill=kill,
                                      opportunities=sup.opportunities)
    print(f"[mode] {sup.mode.value}", flush=True)
    sup.ks = KalshiStream(api_key=api_key, private_key=load_private_key(key_path))
    sup.ps = PolymarketStream()
    sup.capture_series = tuple(x.strip() for x in a.capture_series.split(",") if x.strip())
    sup.capture_pm_tags = tuple(int(x) if x.strip().isdigit() else x.strip() for x in a.capture_pm_tags.split(",") if x.strip())
    sup.watch = Watchlist() if (sup.capture_series or sup.capture_pm_tags) else None
    rest = Client("polymarket-rest", rate=4, burst=8, cache_dir=None)

    def _fetch_pm(asset_id: str):
        b = pm_book(rest.get_json(f"{PM_CLOB}/book", params={"token_id": asset_id}, use_cache=False), time.time())
        return [(q.price, q.size) for q in b.bids], [(q.price, q.size) for q in b.asks]

    sup.ps.reconciler = Reconciler(sup.ps, _fetch_pm, period_s=a.reconcile_period)
    if not a.no_capture:
        sup.ks.capture = FrameWriter("kalshi", a.frames_root)
        sup.ps.capture = FrameWriter("polymarket", a.frames_root)
    sup.retain_days = max(0, int(a.retain_days))
    sup.retain_period_s = float(a.retain_period)
    sup.board_path = Path(a.board) if str(a.board) else None

    status, code = "OK", 0
    try:
        asyncio.run(run(sup, discovery_period=a.discovery_period,
                        report_period=a.report_period, once=a.once))
    except DiskPressure as exc:
        # 75 is TEMPFAIL, the runner's own df-guard code: systemd retries a minute later and the
        # guard keeps the lane down until the volume has room (L72).
        status, code = "FAILED", 75
        print(f"[fatal] {exc}", flush=True)
        print(f"[fatal] {type(exc).__name__}: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        status, code = "FAILED", 1
        print(f"[fatal] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
    finally:
        st = sup.stats()
        sup.store.close()
        for st_ in (sup.ks, sup.ps):
            if st_.capture is not None:
                st_.capture.close()
        if owns_row:
            run_index.finish("live_stream", run_id, exit_code=code, status=status,
                             spawned=sup.spawned, reaped=sup.reaped, rows=st["rows"])
        print(f"[stopped] spawned={sup.spawned} reaped={sup.reaped} rows={st['rows']} "
              f"({status})", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

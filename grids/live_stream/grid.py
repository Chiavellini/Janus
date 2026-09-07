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
import json
import os
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kernel.fetch import Client  # noqa: E402
from kernel.redact import brief_error  # noqa: E402
from nodes.capture.capture import FRAMES_ROOT, FrameWriter  # noqa: E402
from nodes.cover.capacity import frontier, slippage_for  # noqa: E402
from nodes.discovery.watchlist import Watchlist, kalshi_watch, pm_watch_events  # noqa: E402
from nodes.watch_settle.settle import record_watch  # noqa: E402
from nodes.entities.leagues import LEAGUES, default_leagues  # noqa: E402
from nodes.discovery.discovery import co_listed, discover, first_seen, record_events, record_spawn_block  # noqa: E402
from nodes.slate.slate import next_transition, windows_for  # noqa: E402
from nodes.execute.coordinator import Coordinator  # noqa: E402
from nodes.execute.plan import plan_from_cover  # noqa: E402
from nodes.execute.records import ExecutionRecords  # noqa: E402
from nodes.execute.venues import build_venues  # noqa: E402
from nodes.exec_kalshi.client import DEMO_BASE, PROD_BASE, KalshiExecution  # noqa: E402
from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport, TransportUnavailable  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.opportunity.opportunity import books_snapshot  # noqa: E402
from nodes.opportunity.thresholds import STRATEGY_VERSION  # noqa: E402
from nodes.reconcile.settle_executions import apply_settlements, fetch_results, pending  # noqa: E402
from nodes.risk.breaker import LossBreaker  # noqa: E402
from nodes.risk.clearance import Candidate, clear  # noqa: E402
from nodes.risk.gate import resolve_mode  # noqa: E402
from nodes.risk.kill import KillSwitches  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402
from nodes.game_poller.poller import GamePoller, PollerState  # noqa: E402
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

from kernel.paths import DB  # noqa: E402,F401
QUANTITIES = (5.0, 25.0, 100.0)
MIN_RETURN = 0.01
#: A game is priced at most this often on quiet books (nodes/game_poller coalescing); a replica
#: state change or the 15 s heartbeat still prices immediately. 2026-09-04: from ~3,400 to a few
#: hundred evaluations a second. Captures before the sha that introduced it replay to different rows.
EVAL_INTERVAL_S = 0.2
#: How often finished games' executions are settled against the venues' results (PAPER and above).
SETTLE_PERIOD_S = 300.0


@dataclass
class Supervised:
    poller: GamePoller
    short_name: str
    started_utc: float
    kalshi_tickers: tuple[str, ...] = ()
    pm_assets: tuple[str, ...] = ()
    fee_params: dict = field(default_factory=dict)
    evaluations: int = 0
    written: int = 0


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
    opportunities: OpportunityStore | None = None
    #: The execution side. None below PAPER_EXECUTION: detection only.
    mode: Mode = Mode.SHADOW_LIVE
    coordinator: Coordinator | None = None
    venues: dict = field(default_factory=dict)
    limits: object | None = None
    #: The arming override's caps (stake_usd, max_contracts, day_notional_usd), as the risk gate
    #: resolved them. Empty below LIMITED_LIVE. clear() refuses a capital-risking order without them.
    caps: dict = field(default_factory=dict)
    ledger: ExposureLedger | None = None
    kill: KillSwitches | None = None
    breaker: LossBreaker | None = None
    executions: int = 0
    spawned: int = 0
    reaped: int = 0
    blocked: dict[str, str] = field(default_factory=dict)
    #: (game_id, exception class) -> count of evaluations whose record raised; see _on_update.
    record_errors: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Event-loop stall since the last report tick: the worst overshoot of a 250 ms sleep, and the
    #: readings, from the probe in run(). A stalled loop stamps every received frame late, so
    #: every freshness bound is off by this much (2026-09-04: 10-100 s on a starved host).
    loop_lag_max_s: float = 0.0
    loop_lag_readings: list = field(default_factory=list)
    #: The bound past which the loop's own lag halts pricing, same figure as the clock's.
    max_loop_lag_s: float = 5.0
    #: The last tick's verdict on the loop; what the risk gate sees between ticks.
    stalled: bool = False
    tiers: dict[str, int] = field(default_factory=dict)
    wake_state: tuple = ("WAKE", None, None)
    #: Capture-only subscriptions for what the slate cannot co-list yet (tennis has no ESPN anchor):
    #: frames from both venues, no pricing. nodes/discovery/watchlist.
    watch: Watchlist | None = None
    #: What has been said once: game_id -> UNPAIRED reason, "venue:id" -> near-miss reason.
    said: dict[str, str] = field(default_factory=dict)
    capture_series: tuple[str, ...] = ()
    capture_pm_tags: tuple = ()
    watch_rows: int = 0

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
        return added, removed

    # ── lifecycle ───────────────────────────────────────────────────────
    def reconcile(self, slate: dict[str, dict]) -> None:
        """Spawn what is newly live, reap what has settled. Subscriptions follow."""
        for gid, spec in slate.items():
            if gid in self.live:
                continue
            eq = certify_from_spec(spec, spec["league"])
            # EVAL_INTERVAL_S is mirrored in nodes/replay/replay.py (Harness.spawn): replay must
            # coalesce exactly as the lane did or the rows differ.
            p = GamePoller(gid, spec["league"], spec["outcomes"],
                           quantities=QUANTITIES, max_book_age_s=self.max_book_age_s, min_eval_interval_s=EVAL_INTERVAL_S,
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
                             fee_params=dict(spec["fee_params"]))
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
            st = sup.poller.stats()
            print(f"[reap ] {sup.short_name} after {(time.time()-sup.started_utc)/60:.0f}m — "
                  f"{st['evaluations']} evals, {sup.written} rows, {st['opportunities']} opps",
                  flush=True)

    def _on_update(self, gid: str):
        def cb(_market_id: str, now: float) -> None:
            sup = self.live.get(gid)
            if sup is None:
                return
            for ev in sup.poller.on_event("stream", _market_id, now=now):
                sup.evaluations += 1
                try:
                    self._record(sup, ev)
                except Exception as exc:  # noqa: BLE001 -- a record bug must never reach the socket loop
                    # The callback runs inside the venue socket's receive loop. An exception here
                    # was caught by the transport's blanket handler, which tore the socket down,
                    # resubscribed, and raised again on the first frame: 5-20 reconnects a minute
                    # on 2026-09-03, invisible to the watchdog. Count it, say it once per cause,
                    # keep pumping.
                    key = (gid, type(exc).__name__)
                    self.record_errors[key] = self.record_errors.get(key, 0) + 1
                    if self.record_errors[key] == 1:
                        print(f"  [record] {sup.short_name} {brief_error(exc)}", flush=True)
        return cb

    # ── persistence ─────────────────────────────────────────────────────
    def _record(self, sup: Supervised, ev) -> None:
        rec = record_evaluation(self.store, ev, league=sup.poller.league,
                                fee_params=sup.fee_params, hurdle=MIN_RETURN,
                                opportunities=self.opportunities)
        sup.written += int(rec.wrote)
        if rec.status is OpportunityStatus.PROFITABLE_UNEXECUTED:
            # Solve the size frontier on the SAME books that produced the edge. Doing it from the
            # replicas afterwards would price a different instant -- the books move in milliseconds.
            cap = ""
            try:
                if ev.offers and sup.poller.proof is not None:
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
            if self.coordinator is not None:
                self._execute(sup, ev, rec)

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

    def on_report_tick(self, now: float | None = None) -> None:
        """Persist socket health, and fail closed on an unhealthy clock: every freshness bound
        in the system is `now - updated_utc`, so a stepped clock makes every book fiction.

        Two causes, named apart (2026-09-04). STALL: the loop probe overshot the bound, so every
        frame on BOTH sockets was stamped late -- the lane is behind real time, not the clocks.
        CLOCK: a venue's stamps sit outside the bound while the loop was prompt -- a clock step
        or the venue stamping late. Both halt pricing; only the second is a clock finding."""
        t = now or time.time()
        lag = self.loop_lag_max_s
        stalled_prev, self.stalled = self.stalled, lag > self.max_loop_lag_s
        for venue, st_ in (("kalshi", self.ks), ("polymarket", self.ps)):
            if st_ is not None:
                self.store.socket_health(venue=venue, stats={**st_.stats(), "loop_lag_s": round(lag, 3)}, seen_ts=t)
        bad = [v for v, st_ in (("kalshi", self.ks), ("polymarket", self.ps))
               if st_ is not None and not st_.clock.healthy]
        if self.loop_stalled():
            halt, why = "LOOP_STALLED", f"HALT STALL {lag:.1f}s" + (f" (stamps off on {','.join(bad)})" if bad else "")
        elif bad and stalled_prev:
            # The clock window is 60 s; the tick after a stall still holds the late stamps.
            halt, why = "LOOP_STALLED", f"HALT STALL aftermath (stamps off on {','.join(bad)})"
        elif bad:
            halt, why = "CLOCK_UNHEALTHY", f"HALT CLOCK {','.join(bad)}"
        else:
            halt, why = None, "healthy again"
        changed = 0
        for sup in self.live.values():
            changed += int(sup.poller.halt != halt)
            sup.poller.halt = halt
        if changed:
            print(f"[clock] {why} ({changed} pollers)", flush=True)
        self.loop_lag_max_s, self.loop_lag_readings = 0.0, []

    def _execute(self, sup: Supervised, ev, rec) -> None:
        """PAPER and above: plan from the priced cover, clear it through nodes/risk, run the machine.
        Every refusal is recorded on the opportunity; nothing here raises into the socket loop."""
        cov = ev.cover
        m_entry = time.monotonic()
        # The path's first two stages, for ops/latency_report.py: the poller's own event->decision
        # time and the gap from the decision to here (records, the frontier).
        pre = {"frame_to_eval_ms": round(float(getattr(ev, "latency_ms", 0.0) or 0.0), 2),
               "eval_to_exec_ms": round(max(0.0, time.time() - ev.evaluated_utc) * 1000.0, 2)}
        offers = {o: list(v) for o, v in ev.offers.items()}
        plan = plan_from_cover(opportunity_id=Opportunity.id_for(ev.game_id, ev.quantity), event_id=ev.game_id,
                               league=sup.poller.league, cov=cov, offers=offers, hurdle=MIN_RETURN)
        if plan is None:
            return
        # Paper venues fill against the books the cover was priced from -- the same instant.
        for outcome, legs in offers.items():
            for l in legs:
                v = self.venues.get(l.venue)
                if v is not None and hasattr(v, "books"):
                    side = "buy_no" if (l.venue == "kalshi" and l.outcome_id.endswith(":NO")) else "buy_yes"
                    v.books[(l.market_id, side)] = l.book
                    if hasattr(v, "fee_params"):
                        v.fee_params = dict(sup.fee_params.get(l.venue) or {})    # paper fills carry the pinned fee
        max_age = max((ev.evaluated_utc - l.book.fetched_utc) for legs in offers.values() for l in legs)
        cand = Candidate(plan.opportunity_id, ev.game_id, sup.poller.league,
                         ((plan.first.venue, plan.first.contracts, plan.first.limit_price),
                          (plan.hedge.venue, plan.hedge.contracts, plan.hedge.limit_price)),
                         rec.net_profit_usd or 0.0, rec.locked_return or 0.0, STRATEGY_VERSION, max_age)
        balances = None
        if self.mode.sends_real_orders:
            m = time.monotonic()
            got = {}
            for v, venue in self.venues.items():        # ONE round trip per venue (it was two, 2026-09-07)
                b = venue.balance()
                got[v] = b.available_usd if b else None
            balances = None if any(b is None for b in got.values()) else got
            pre["balances_ms"] = round((time.monotonic() - m) * 1000.0, 2)
        connected = {"kalshi": bool(self.ks and self.ks.connected), "polymarket": bool(self.ps and self.ps.connected)}
        m = time.monotonic()
        clearance = clear(cand, mode=self.mode, limits=self.limits, ledger=self.ledger, kill=self.kill,
                          breaker=self.breaker, fills_today=(), clock_healthy=self.clock_ok(),
                          fee_schedules_ok=bool(sup.fee_params.get("kalshi") and sup.fee_params.get("polymarket")),
                          balances=balances, venues_connected=connected, caps=self.caps or None)
        pre["clear_ms"] = round((time.monotonic() - m) * 1000.0, 2)
        if hasattr(clearance, "code"):
            print(f"  [risk] refused {sup.short_name}: {clearance.code} {clearance.detail}", flush=True)
            return
        pre["pre_machine_ms"] = round((time.monotonic() - m_entry) * 1000.0, 2)
        ex = self.coordinator.execute(plan, clearance, offers_books=books_snapshot(offers), venues_connected=connected,
                                      pre_stages=pre)
        self.executions += 1
        print(f"  [exec] {sup.short_name} {ex.state.value} first={ex.first_filled}@{ex.first_avg_price} "
              f"hedge={ex.hedge_filled}@{ex.hedge_avg_price} unhedged={ex.unhedged} {ex.detail}", flush=True)
        try:
            print(f"  [latency] {sup.short_name} " + " ".join(f"{k}={v}" for k, v in sorted(ex.stages.items())), flush=True)
        except Exception:  # noqa: BLE001 -- reporting must never break the loop
            pass
        if ex.released and self.ledger is not None:
            self.ledger.release(ex.reservation_id, reason=f"nothing filled: {ex.state.value}")

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
    try:
        while not _STOP:
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
            if time.time() - last_disc > discovery_period:
                try:
                    # The network halves run in a worker so the sockets keep being read (L37);
                    # the state halves run here, on the loop, where the store and replicas live.
                    now_d, d = await asyncio.to_thread(sup.fetch_discovery)
                    slate = sup.apply_discovery(now_d, d)
                    sup.reconcile(slate)
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


def _runner_sha() -> str:
    """The tree this process runs from, for the arming override's pin."""
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=ROOT, timeout=5).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


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
    ap.add_argument("--mode", default="SHADOW_LIVE",
                    help="OFFLINE_REPLAY | SHADOW_LIVE | PAPER_EXECUTION | DEMO_EXECUTION | LIMITED_LIVE | PRODUCTION; "
                         "resolved once by nodes/risk.gate and never escalated")
    ap.add_argument("--capture-series", default="KXATPMATCH,KXWTAMATCH,KXATPCHALLENGERMATCH",
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
    resolved = resolve_mode(a.mode, env=os.environ, kill=kill, limits=limits,
                            runner_sha=_runner_sha(), credentials_present={"kalshi": bool(api_key)})
    if hasattr(resolved, "code"):
        print(f"mode refused: {resolved.code}: {resolved.detail}", file=sys.stderr)
        return 2
    sup.mode = resolved.mode
    sup.caps = dict(getattr(resolved, "caps", None) or {})
    if sup.mode.rank >= Mode.PAPER_EXECUTION.rank:
        journal = Journal(sup.store)
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
            return PolymarketExecution(PyClobTransport(), journal, sup.mode)

        try:
            sup.venues = build_venues(sup.mode, journal, kalshi_factory=kalshi_factory,
                                      polymarket_factory=polymarket_factory)
        except (ValueError, TransportUnavailable) as exc:
            print(f"mode {sup.mode.value} cannot be built: {exc}", file=sys.stderr)
            return 2
        sup.limits, sup.kill = limits, kill
        sup.breaker = LossBreaker(kill=kill)
        sup.ledger = ExposureLedger(sup.store)
        sup.coordinator = Coordinator(sup.venues, ExecutionRecords(sup.store), sup.mode,
                                      hedge_deadline_s=limits.max_hedge_latency_ms / 1000.0,
                                      opportunities=sup.opportunities, kill=kill)
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

    status, code = "OK", 0
    try:
        asyncio.run(run(sup, discovery_period=a.discovery_period,
                        report_period=a.report_period, once=a.once))
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

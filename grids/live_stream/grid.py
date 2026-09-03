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
from nodes.capture.capture import FRAMES_ROOT, FrameWriter  # noqa: E402
from nodes.cover.capacity import frontier  # noqa: E402
from nodes.discovery.discovery import co_listed, discover, record_events  # noqa: E402
from nodes.game_poller.poller import GamePoller, PollerState  # noqa: E402
from nodes.settle_wedge.equivalence import SettlementEquivalence  # noqa: E402
from nodes.settle_wedge.pair import certify_from_spec  # noqa: E402
from nodes.opportunity.opportunity import Opportunity, OpportunityStore  # noqa: E402
from nodes.opportunity.record import record_evaluation  # noqa: E402
from kernel.schema import OpportunityStatus  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.stream_kalshi.stream import KalshiStream, load_private_key  # noqa: E402
from nodes.stream_polymarket.reconcile import Reconciler  # noqa: E402
from nodes.stream_polymarket.stream import PolymarketStream  # noqa: E402
from nodes.venue_polymarket.books import PM_CLOB, pm_book  # noqa: E402
from ops import run_index  # noqa: E402

DB = Path("/Volumes/Kilos/janus/tuples/tuples.sqlite")
QUANTITIES = (5.0, 25.0, 100.0)
MIN_RETURN = 0.01


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
    spawned: int = 0
    reaped: int = 0
    blocked: dict[str, str] = field(default_factory=dict)

    # ── discovery ───────────────────────────────────────────────────────
    def discover(self) -> dict[str, dict]:
        """Games that are live (or nearly) AND co-listed on both venues, with their outcome map
        and the fee params each venue reported. `nodes/discovery` owns all of it; this grid only
        composes. Blocks are REPLACED each pass so a cleared block does not linger."""
        now = datetime.now(timezone.utc)
        pc = Client("polymarket", rate=5, burst=8, cache_dir=None)
        kc = Client("kalshi", rate=4, burst=8, cache_dir=None)
        d = discover(self.leagues, now, True, self.pre_hours, pc, kc)
        slate, blocked = co_listed(d)
        self.blocked = dict(blocked)
        for venue, errs in d.fee_errors.items():
            for key, err in errs.items():
                self.blocked[f"fees:{venue}:{key}"] = f"FEE_SCHEDULE: {err}"
        if self.store is not None:
            record_events(self.store, d, slate, blocked)
        return slate

    # ── lifecycle ───────────────────────────────────────────────────────
    def reconcile(self, slate: dict[str, dict]) -> None:
        """Spawn what is newly live, reap what has settled. Subscriptions follow."""
        for gid, spec in slate.items():
            if gid in self.live:
                continue
            eq = certify_from_spec(spec, spec["league"])
            p = GamePoller(gid, spec["league"], spec["outcomes"],
                           quantities=QUANTITIES, max_book_age_s=self.max_book_age_s,
                           min_return=MIN_RETURN, fee_params=spec["fee_params"],
                           equivalence=eq if isinstance(eq, SettlementEquivalence) else None,
                           order_limits={"polymarket": spec.get("pm_limits") or {}})
            if p.state is PollerState.BLOCKED:
                # An unproven outcome set or settlement basis never gets a subscription spent on it.
                self.blocked[gid] = f"SPAWN:{p.block_reason}"
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
                self._record(sup, ev)
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
                                  now_utc=ev.evaluated_utc, exhaustive=sup.poller.proof,
                                  max_leg_age_s=self.max_book_age_s, hurdle=MIN_RETURN)
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

    def on_report_tick(self, now: float | None = None) -> None:
        """Persist socket health, and fail closed on an unhealthy clock: every freshness bound
        in the system is `now - updated_utc`, so a stepped clock makes every book fiction."""
        t = now or time.time()
        for venue, st_ in (("kalshi", self.ks), ("polymarket", self.ps)):
            if st_ is not None:
                self.store.socket_health(venue=venue, stats=st_.stats(), seen_ts=t)
        bad = [v for v, st_ in (("kalshi", self.ks), ("polymarket", self.ps))
               if st_ is not None and not st_.clock.healthy]
        halt = "CLOCK_UNHEALTHY" if bad else None
        for sup in self.live.values():
            if sup.poller.halt != halt:
                print(f"[clock] {'HALT ' + ','.join(bad) if bad else 'healthy again'}", flush=True)
            sup.poller.halt = halt

    def stats(self) -> dict:
        return {"live": len(self.live), "spawned": self.spawned, "reaped": self.reaped,
                "evaluations": sum(s.evaluations for s in self.live.values()),
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
    last_disc = 0.0
    last_report = time.time()
    try:
        while not _STOP:
            if time.time() - last_disc > discovery_period:
                try:
                    slate = sup.discover()
                    sup.reconcile(slate)
                    print(f"[slate] {len(slate)} co-listed live games, {len(sup.live)} pollers"
                          + (f", blocked: {len(sup.blocked)}" if sup.blocked else ""), flush=True)
                except Exception as exc:  # noqa: BLE001 -- discovery must never kill the loop
                    print(f"[slate FAILED] {type(exc).__name__}: {exc}", flush=True)
                    traceback.print_exc()
                last_disc = time.time()
                if once:
                    await asyncio.sleep(15)
                    break
            if time.time() - last_report > report_period:
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
                      f"{p.get('agreement')}", flush=True)
                last_report = time.time()
            await asyncio.sleep(1)
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        sup.on_report_tick()          # a --once run must still leave a health row
        sup.store.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="mlb,nfl,nba,wnba,nhl,epl")
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
    ap.add_argument("--reconcile-period", type=float, default=5.0,
                    help="seconds between Polymarket REST reconcile passes over quiet replicas")
    a = ap.parse_args()

    if a.self_test:
        s = Supervisor([x.strip() for x in a.leagues.split(",") if x.strip()],
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

    sup = Supervisor([x.strip() for x in a.leagues.split(",") if x.strip()],
                     pre_hours=a.pre_hours, db=a.db, max_book_age_s=a.max_book_age)
    sup.store = TupleStore(a.db)
    sup.opportunities = OpportunityStore(sup.store)
    sup.ks = KalshiStream(api_key=api_key, private_key=load_private_key(key_path))
    sup.ps = PolymarketStream()
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

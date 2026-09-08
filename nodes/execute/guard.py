#!/usr/bin/env python3
"""The position guard: the venues' fills and positions are the truth, the execution rows are the
claim, and the claim is corrected (2026-09-08).

Why it exists: at 01:39Z the first real fill (10.175 shares @ $0.57) was hidden from the machine
by a store failure after the POST; the row said nothing filled, the hedge never went out, and
nothing in the lane would ever have asked the venue. This module asks, every `guard_period_s`,
in real-order modes:

  1. every journaled order still UNCONFIRMED is re-polled through `status()`
     (`nodes/reconcile.resolve_unconfirmed`, wired to a running process for the first time); a
     Polymarket order with no venue id, which `status()` cannot look up, is resolved through the
     venue's trades since its submit and ADOPTED (the trade's order id becomes the row's);
  2. every venue fill since the lane started is attributed to its order row, then to its
     execution; sums per leg that differ from the row rewrite the row (`ExecutionRecords.
     correct_fills`), a released rejection the venue contradicts is reopened as holding
     (`reopen`); a fill no row can explain is an ORPHAN (nothing planned it, nothing can protect
     it: flagged, and the live kill is latched when the limits say so);
  3. a corrected execution that is naked (or over-hedged) and not being worked by the machine is
     handed back for protection (`to_protect`; acted on when `protect_auto` is on);
  4. the venues' positions are compared with the net of the fills seen on each market: a
     mismatch is flagged (alarm-only in this version);
  5. `fills_today` for the loss breaker: today's settlement rows plus every young UNCONFIRMED
     order as UNCONFIRMED (PNL_UNKNOWN refuses covers until the guard resolves it).

Two halves, like discovery: `fetch()` does the network in a worker thread and touches only the
venue clients (whose journal lives on the worker's own store connection); `apply()` runs on the
event loop and touches the stores. The lane serialises the guard with executions through
`in_flight`, so a connection is never used by two threads at once.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from kernel.execution_protocol import Ack, FillRecord, Position
from kernel.schema import ExecutionState as X, FillState, Mode
from nodes.reconcile.reconcile import ingest_fills, resolve_unconfirmed
from nodes.risk.breaker import RealizedFill, day_of
from nodes.risk.flags import raise_flag

#: A trade this close in time to an UNCONFIRMED order on the same asset, with no other claimant,
#: is that order's fill (a FAK/IOC never rests; its fill is within seconds of its submit).
ADOPT_WINDOW_S = 120.0
#: An UNCONFIRMED order counts against the day's PnL as unknown for this long; older ones are the
#: reconcile script's business, not a reason to freeze the lane for good.
UNCONFIRMED_PNL_UNKNOWN_S = 30 * 60.0
#: A machine that moved this recently is still working the execution: not the guard's to protect.
IN_FLIGHT_GRACE_S = 60.0
#: The states in which nothing more is owed on the position.
_QUIET = {X.HEDGED, X.SETTLED, X.RECONCILED, X.UNWOUND}
#: Settlement rows that are money: the breaker never counts paper.
_REAL_MODES = {m.value for m in Mode if m.sends_real_orders}


@dataclass
class GuardSnapshot:
    now: float
    unconfirmed: dict[str, str] = field(default_factory=dict)         # client_order_id -> state after the poll
    fills: list[FillRecord] = field(default_factory=list)
    positions: dict[str, Sequence[Position] | None] = field(default_factory=dict)
    adopted: list[tuple[str, str]] = field(default_factory=list)      # (client_order_id, venue_order_id)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class GuardReport:
    findings: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)                # execution ids rewritten
    to_protect: list[str] = field(default_factory=list)               # execution ids that are naked and idle
    orphans: list[FillRecord] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    fills_today: tuple[RealizedFill, ...] = ()


class PositionGuard:
    def __init__(self, *, venues: Mapping[str, object], journal, records, store, limits, started_utc: float,
                 kill=None, log: Callable[[str], None] = print, clock: Callable[[], float] = time.time):
        self.venues, self.journal, self.records, self.store = venues, journal, records, store
        self.limits, self.kill, self.log, self.clock = limits, kill, log, clock
        self.cursor_utc = started_utc - ADOPT_WINDOW_S
        self.said: set[str] = set()
        self.passes = 0

    # ── the network half (a worker thread) ─────────────────────────────
    def fetch(self) -> GuardSnapshot:
        snap = GuardSnapshot(now=self.clock())
        try:
            snap.unconfirmed = resolve_unconfirmed(self.journal, self.venues)
        except Exception as exc:  # noqa: BLE001
            snap.errors["unconfirmed"] = f"{type(exc).__name__}: {exc}"
        try:
            snap.fills = list(ingest_fills(self.journal, self.venues, since_utc=self.cursor_utc))
        except Exception as exc:  # noqa: BLE001
            snap.errors["fills"] = f"{type(exc).__name__}: {exc}"
        for v, venue in self.venues.items():
            try:
                snap.positions[v] = venue.positions() if hasattr(venue, "positions") else None
            except Exception as exc:  # noqa: BLE001
                snap.positions[v] = None
                snap.errors[f"positions:{v}"] = f"{type(exc).__name__}: {exc}"
        # A Polymarket order without a venue id: status() cannot look it up; its trade can.
        for cid, state in list(snap.unconfirmed.items()):
            if state != FillState.UNCONFIRMED.value:
                continue
            row = self.journal.get(cid)
            if not row or row.get("venue_order_id") or row["venue"] != "polymarket":
                continue
            match = self._trade_for(row, snap.fills)
            if match is not None:
                self._adopt(row, match, snap)
        return snap

    def _trade_for(self, row: dict, fills: Sequence[FillRecord]) -> FillRecord | None:
        cands = [f for f in fills if f.venue == row["venue"] and f.market_id and f.market_id == row["market_id"]
                 and abs(f.ts - float(row["submitted_utc"])) <= ADOPT_WINDOW_S
                 and (f.side or "buy_yes") == row["side"] and not self._claimed(f.venue_order_id)]
        if len(cands) != 1:
            return None
        return cands[0]

    def _claimed(self, venue_order_id: str) -> bool:
        if not venue_order_id:
            return True
        r = self.journal.store.con.execute("SELECT 1 FROM orders WHERE venue_order_id=? LIMIT 1", (venue_order_id,)).fetchone()
        return r is not None

    def _adopt(self, row: dict, f: FillRecord, snap: GuardSnapshot) -> None:
        state = FillState.FILLED if f.contracts >= float(row["contracts"]) - 1e-6 else FillState.PARTIAL
        ack = Ack(row["venue"], row["client_order_id"], f.venue_order_id, state, f.contracts, f.price, f.fee_usd,
                  "guard_adopted", snap.now, detail=f"adopted from trade {f.fill_id} at {f.ts:.0f}")
        self.journal.record(ack, kind="guard", raw={"fill_id": f.fill_id, "ts": f.ts})
        snap.unconfirmed[row["client_order_id"]] = state.value
        snap.adopted.append((row["client_order_id"], f.venue_order_id))

    # ── the state half (the event loop) ────────────────────────────────
    def apply(self, snap: GuardSnapshot) -> GuardReport:
        rep = GuardReport()
        self.passes += 1
        for k, e in snap.errors.items():
            rep.findings.append(f"{k}: {e}")
        for cid, vid in snap.adopted:
            rep.findings.append(f"adopted {cid[:8]} <- venue order {vid[:12]}")
        by_exec: dict[str, list[tuple[dict, FillRecord]]] = {}
        seen_net: dict[tuple[str, str], float] = {}
        for f in snap.fills:
            key = (f.venue, f.market_id)
            if f.market_id:
                sign = -1.0 if f.side.startswith("sell") else 1.0
                seen_net[key] = seen_net.get(key, 0.0) + sign * f.contracts
            row = self._row_for(f)
            if row is None:
                rep.orphans.append(f)
                continue
            exid = self._execution_for(row)
            if exid is None:
                rep.orphans.append(f)
                continue
            by_exec.setdefault(exid, []).append((row, f))
        for f in rep.orphans:
            key = f"orphan:{f.fill_id}"
            if key not in self.said:
                self.said.add(key)
                detail = f"{f.venue} {f.market_id[:16]} {f.side} {f.contracts:g} @ {f.price} order {f.venue_order_id[:12]}"
                rep.findings.append(f"ORPHAN_FILL {detail}")
                self._flag("ORPHAN_FILL", detail, snap.now)
                if self.kill is not None and getattr(self.limits, "protect_kill_on_failure", True):
                    try:
                        self.kill.latch("live", f"guard: orphan fill {detail}")
                    except Exception as exc:  # noqa: BLE001
                        rep.findings.append(f"kill latch failed: {type(exc).__name__}")
        for exid, pairs in by_exec.items():
            self._reconcile_execution(exid, pairs, snap, rep)
        self._scan_naked(snap, rep, skip=set(by_exec))
        self._compare_positions(snap, seen_net, rep)
        rep.fills_today = self.fills_today(snap.now)
        self.cursor_utc = snap.now - ADOPT_WINDOW_S
        return rep

    def _row_for(self, f: FillRecord) -> dict | None:
        con = self.journal.store.con
        r = con.execute("SELECT client_order_id FROM orders WHERE venue_order_id=?", (f.venue_order_id,)).fetchone()
        if r is not None:
            return self.journal.get(r[0])
        if not f.market_id:
            return None
        # an order the venue answered late (no venue id yet) on the same asset, near in time
        rows = con.execute("SELECT client_order_id FROM orders WHERE venue=? AND market_id=? AND (venue_order_id IS NULL OR venue_order_id='') "
                           "AND ABS(submitted_utc - ?) <= ? AND side=?", (f.venue, f.market_id, f.ts, ADOPT_WINDOW_S, f.side or "buy_yes")).fetchall()
        if len(rows) != 1:
            return None
        row = self.journal.get(rows[0][0])
        if row is not None:
            snap_now = self.clock()
            state = FillState.FILLED if f.contracts >= float(row["contracts"]) - 1e-6 else FillState.PARTIAL
            self.journal.record(Ack(row["venue"], row["client_order_id"], f.venue_order_id, state, f.contracts, f.price, f.fee_usd,
                                    "guard_adopted", snap_now, detail=f"adopted from fill {f.fill_id}"), kind="guard",
                                raw={"fill_id": f.fill_id})
        return row

    def _execution_for(self, row: dict) -> str | None:
        r = self.records.store.con.execute(
            "SELECT execution_id FROM executions WHERE opportunity_id=? AND started_utc <= ? ORDER BY started_utc DESC LIMIT 1",
            (row["opportunity_id"], float(row["submitted_utc"]) + 1.0)).fetchone()
        return r[0] if r else None

    def _reconcile_execution(self, exid: str, pairs: list[tuple[dict, FillRecord]], snap: GuardSnapshot, rep: GuardReport) -> None:
        ex = self.records.load(exid)
        plan = self.records.plan_of(exid)
        if ex is None:
            return
        first_venue = plan.first.venue if plan else "polymarket"
        sums = {"first_buy": 0.0, "first_sell": 0.0, "hedge_buy": 0.0, "hedge_sell": 0.0}
        cost = {"first_buy": 0.0, "first_sell": 0.0, "hedge_buy": 0.0, "hedge_sell": 0.0}
        for row, f in pairs:
            leg = "first" if row["venue"] == first_venue else "hedge"
            kind = "sell" if str(row.get("side") or "").startswith("sell") else "buy"
            sums[f"{leg}_{kind}"] += f.contracts
            cost[f"{leg}_{kind}"] += f.contracts * f.price

        def avg(k):
            return (cost[k] / sums[k]) if sums[k] > 1e-9 else None
        changed = []
        if abs(sums["first_buy"] - ex.first_filled) > 1e-6:
            changed.append(f"first_filled {ex.first_filled:g}->{sums['first_buy']:g}")
        if abs(sums["hedge_buy"] - ex.hedge_filled) > 1e-6:
            changed.append(f"hedge_filled {ex.hedge_filled:g}->{sums['hedge_buy']:g}")
        if abs(sums["first_sell"] - ex.first_unwound) > 1e-6:
            changed.append(f"first_unwound {ex.first_unwound:g}->{sums['first_sell']:g}")
        if abs(sums["hedge_sell"] - ex.hedge_unwound) > 1e-6:
            changed.append(f"hedge_unwound {ex.hedge_unwound:g}->{sums['hedge_sell']:g}")
        if changed:
            note = "venue fills: " + ", ".join(changed)
            if ex.state.is_terminal and ex.released and (sums["first_buy"] > 1e-9 or sums["hedge_buy"] > 1e-9):
                self.records.reopen(ex, note=note, now=snap.now)
            ex.first_unwound, ex.first_unwind_avg = sums["first_sell"], avg("first_sell")
            ex.hedge_unwound, ex.hedge_unwind_avg = sums["hedge_sell"], avg("hedge_sell")
            self.records.correct_fills(ex, first_filled=sums["first_buy"], first_avg=avg("first_buy"),
                                       hedge_filled=sums["hedge_buy"], hedge_avg=avg("hedge_buy"), note=note, now=snap.now)
            rep.corrected.append(exid)
            rep.findings.append(f"CORRECTED {exid[:8]} {ex.event_id} {note}")
            self._flag("GUARD_CORRECTED", f"{exid[:8]} {ex.event_id} {note}", snap.now)
        naked = ex.unhedged > self.limits.protect_dust_contracts or ex.overhedged > self.limits.protect_dust_contracts
        if naked and ex.state not in _QUIET and not ex.released:
            key = f"naked:{exid}:{ex.unhedged:g}:{ex.overhedged:g}"
            if key not in self.said:
                self.said.add(key)
                detail = f"{exid[:8]} {ex.event_id} {ex.state.value} unhedged {ex.unhedged:g} overhedged {ex.overhedged:g}"
                rep.findings.append(f"UNHEDGED_POSITION {detail}")
                self._flag("UNHEDGED_POSITION", detail, snap.now)
            working = (snap.now - float(self._last_utc(exid) or 0.0)) < IN_FLIGHT_GRACE_S and not ex.state.holds_position
            if not working:
                rep.to_protect.append(exid)

    def _scan_naked(self, snap: GuardSnapshot, rep: GuardReport, *, skip: set[str]) -> None:
        """Every open execution that holds a naked (or over-hedged) position is handed over on EVERY
        pass, whether or not a new fill arrived: the fills cursor moves on, the position does not."""
        quiet = "', '".join(sorted(s.value for s in _QUIET))
        rows = self.records.store.con.execute(
            f"SELECT execution_id, event_id, state, first_filled, hedge_filled, first_unwound, hedge_unwound, last_utc "
            f"FROM executions WHERE released = 0 AND state NOT IN ('{quiet}')").fetchall()
        dust = self.limits.protect_dust_contracts
        for exid, event_id, state, ff, hf, fu, hu, last in rows:
            if exid in skip:
                continue
            net_first, net_hedge = max(0.0, (ff or 0.0) - (fu or 0.0)), max(0.0, (hf or 0.0) - (hu or 0.0))
            unhedged, over = max(0.0, net_first - net_hedge), max(0.0, net_hedge - net_first)
            if unhedged <= dust and over <= dust:
                continue
            st = X(state)
            key = f"naked:{exid}:{unhedged:g}:{over:g}"
            if key not in self.said:
                self.said.add(key)
                detail = f"{exid[:8]} {event_id} {st.value} unhedged {unhedged:g} overhedged {over:g}"
                rep.findings.append(f"UNHEDGED_POSITION {detail}")
                self._flag("UNHEDGED_POSITION", detail, snap.now)
            working = (snap.now - float(last or 0.0)) < IN_FLIGHT_GRACE_S and not st.holds_position
            if not working:
                rep.to_protect.append(exid)

    def _last_utc(self, exid: str) -> float | None:
        r = self.records.store.con.execute("SELECT last_utc FROM executions WHERE execution_id=?", (exid,)).fetchone()
        return r[0] if r else None

    def _compare_positions(self, snap: GuardSnapshot, seen_net: dict[tuple[str, str], float], rep: GuardReport) -> None:
        for v, pos in snap.positions.items():
            if pos is None:
                continue
            held = {(p.venue, p.market_id): (p.contracts if p.side == "yes" else -p.contracts) for p in pos}
            for key, net in seen_net.items():
                if key[0] != v:
                    continue
                have = held.get(key, 0.0)
                if abs(have - net) > max(self.limits.protect_dust_contracts, 1e-6):
                    msg = f"{key[0]} {key[1][:16]}: venue holds {have:g}, fills since start net {net:g}"
                    sk = f"mismatch:{key}:{have:g}:{net:g}"
                    if sk not in self.said:
                        self.said.add(sk)
                        rep.mismatches.append(msg)
                        rep.findings.append(f"POSITION_MISMATCH {msg}")
                        self._flag("POSITION_MISMATCH", msg, snap.now)

    # ── the breaker's feed ─────────────────────────────────────────────
    def fills_today(self, now: float | None = None) -> tuple[RealizedFill, ...]:
        t = now if now is not None else self.clock()
        day = day_of(t)
        out: list[RealizedFill] = []
        con = self.store.con
        try:
            has = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_settlements'").fetchone()
            if has:
                # Real money only: the box's paper bring-up rows settle in the same table (2026-09-08).
                for exid, usd, ts, mode in con.execute(
                        "SELECT execution_id, realized_usd, settled_ts, mode FROM execution_settlements WHERE settled_ts >= ?",
                        (t - 36 * 3600,)):
                    if day_of(ts) == day and str(mode) in _REAL_MODES:
                        out.append(RealizedFill(exid, FillState.FILLED, float(usd or 0.0), day))
        except Exception:  # noqa: BLE001 -- an unreadable table is PNL_UNKNOWN below, not a crash
            out.append(RealizedFill("settlements-unreadable", FillState.UNCONFIRMED, 0.0, day))
        jcon = self.journal.store.con
        for cid, sub in jcon.execute("SELECT client_order_id, submitted_utc FROM orders WHERE state=? AND submitted_utc >= ?",
                                     (FillState.UNCONFIRMED.value, t - UNCONFIRMED_PNL_UNKNOWN_S)):
            if day_of(sub) == day:
                out.append(RealizedFill(cid, FillState.UNCONFIRMED, 0.0, day))
        return tuple(out)

    def _flag(self, flag: str, detail: str, now: float) -> None:
        try:
            raise_flag(self.store, flag, detail, now=now)
        except Exception as exc:  # noqa: BLE001
            self.log(f"  [guard] flag {flag} not written: {type(exc).__name__}")

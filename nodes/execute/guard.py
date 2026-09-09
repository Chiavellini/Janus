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
  5. `fills_today` for the loss breaker: today's settlement rows plus every UNCONFIRMED order
     submitted today (PNL_UNKNOWN refuses covers until the guard resolves it).

Two halves, like discovery: `fetch()` does the network in a worker thread and touches only the
venue clients (whose journal lives on the worker's own store connection); `apply()` runs on the
event loop and touches the stores. The lane serialises the guard with executions through
`in_flight`, so a connection is never used by two threads at once.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from kernel.execution_protocol import Ack, FillRecord, Position
from kernel.schema import ExecutionState as X, FillState, Mode
from nodes.reconcile.reconcile import check_fees, ingest_fills, resolve_unconfirmed
from nodes.reconcile.settle_executions import refresh_settlement_accounting
from nodes.risk.breaker import RealizedFill, day_of
from nodes.risk.flags import raise_flag, resolve_flag

#: A trade this close in time to an UNCONFIRMED order on the same asset, with no other claimant,
#: is that order's fill (a FAK/IOC never rests; its fill is within seconds of its submit).
ADOPT_WINDOW_S = 120.0
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
    balances: dict[str, float] = field(default_factory=dict)
    adopted: list[tuple[str, str]] = field(default_factory=list)      # (client_order_id, venue_order_id)
    fee_findings: list = field(default_factory=list)
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
                 ledger=None, kill=None, log: Callable[[str], None] = print, clock: Callable[[], float] = time.time):
        self.venues, self.journal, self.records, self.store = venues, journal, records, store
        self.limits, self.ledger, self.kill, self.log, self.clock = limits, ledger, kill, log, clock
        self.cursor_utc = started_utc - ADOPT_WINDOW_S
        self.said: set[str] = set()
        self.passes = 0

    # ── the network half (a worker thread) ─────────────────────────────
    def fetch(self) -> GuardSnapshot:
        snap = GuardSnapshot(now=self.clock())
        # Never advance the trade cursor past an unresolved order. A process can be down longer
        # than ADOPT_WINDOW_S after POST-before-ack; on restart the only recoverable venue order
        # id may be in that older trade row.
        unresolved = self.journal.store.con.execute(
            "SELECT MIN(submitted_utc) FROM orders WHERE state=? OR open=1",
            (FillState.UNCONFIRMED.value,),
        ).fetchone()
        fill_since = self.cursor_utc
        if unresolved and unresolved[0] is not None:
            fill_since = min(fill_since, max(0.0, float(unresolved[0]) - 1.0))
        try:
            snap.unconfirmed = resolve_unconfirmed(self.journal, self.venues)
        except Exception as exc:  # noqa: BLE001
            snap.errors["unconfirmed"] = f"{type(exc).__name__}: {exc}"
        try:
            snap.fills = list(ingest_fills(self.journal, self.venues, since_utc=fill_since))
        except Exception as exc:  # noqa: BLE001
            snap.errors["fills"] = f"{type(exc).__name__}: {exc}"
        for venue_name, adapter in self.venues.items():
            if getattr(adapter, "projection_batch_error", ""):
                snap.errors[f"fills:{venue_name}"] = adapter.projection_batch_error
            if getattr(adapter, "persistence_error", ""):
                snap.errors[f"persistence:{venue_name}"] = adapter.persistence_error
        for fill in snap.fills:
            venue = self.venues.get(fill.venue)
            per_market = getattr(venue, "fee_params_by_market", {}) or {}
            params = per_market.get(fill.market_id) or getattr(venue, "fee_params", None)
            if not params:
                continue
            try:
                snap.fee_findings.extend(check_fees(self.journal, [fill], {fill.venue: params}))
            except Exception as exc:  # noqa: BLE001 -- missing proof is visible, never a free fee
                snap.errors[f"fee:{fill.fill_id}"] = f"{type(exc).__name__}: {exc}"
        for v, venue in self.venues.items():
            try:
                snap.positions[v] = venue.positions() if hasattr(venue, "positions") else None
            except Exception as exc:  # noqa: BLE001
                snap.positions[v] = None
                snap.errors[f"positions:{v}"] = f"{type(exc).__name__}: {exc}"
            if hasattr(venue, "balance"):
                try:
                    bal = venue.balance()
                    if bal is not None:
                        snap.balances[v] = float(bal.available_usd)
                    else:
                        snap.errors[f"balance:{v}"] = "venue did not return a balance"
                except Exception as exc:  # noqa: BLE001
                    snap.errors[f"balance:{v}"] = f"{type(exc).__name__}: {exc}"
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
        # Preserve/alarm the venue's order-level fact before a partial trade FIFO is
        # considered. The second pass below also catches newly adopted late fills.
        self._detect_order_overfills(snap, rep)
        self._preserve_unpersisted_fills(snap, rep)
        for k, e in snap.errors.items():
            rep.findings.append(f"{k}: {e}")
        for cid, vid in snap.adopted:
            rep.findings.append(f"adopted {cid[:8]} <- venue order {vid[:12]}")
        for finding in snap.fee_findings:
            if not finding.stop:
                continue
            key = f"fee:{finding.venue}:{finding.order_client_id}:{finding.charged_usd:.8f}"
            if key in self.said:
                continue
            self.said.add(key)
            detail = (f"{finding.venue} order {finding.order_client_id[:12] or 'unattributed'} charged "
                      f"${finding.charged_usd:.6f}; pinned ${finding.pinned_usd:.6f}; "
                      f"excess ${finding.excess_usd:.6f}")
            rep.findings.append(f"FEE_ABOVE_PIN {detail}")
            self._flag("FEE_ABOVE_PIN", detail, snap.now)
            if self.kill is not None:
                try:
                    self.kill.latch("live", f"guard: fee above pin {detail[:180]}")
                except Exception as exc:  # noqa: BLE001
                    rep.findings.append(f"kill latch failed: {type(exc).__name__}")
        by_exec: dict[str, list[tuple[dict, FillRecord]]] = {}
        for f in snap.fills:
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
        self._close_final_zero_fills(snap, rep)
        self._repair_reservations(snap, rep)
        self._held = self._holdings(snap)
        for exid, pairs in by_exec.items():
            self._reconcile_execution(exid, pairs, snap, rep)
        self._detect_order_overfills(snap, rep)
        self._scan_naked(snap, rep, skip=set(by_exec))
        self._compare_positions(snap, rep)
        revised = refresh_settlement_accounting(self.store, now=snap.now, log=self.log)
        if revised:
            rep.findings.append(f"SETTLEMENT_ACCOUNTING_REVISED {revised}")
        if not rep.mismatches:
            resolve_flag(self.store, "POSITION_MISMATCH", "the venue positions match every unreleased execution", now=snap.now)
        material = self.records.store.con.execute(
            "SELECT COUNT(*) FROM executions WHERE released=0 AND ABS(unhedged)>?",
            (self.limits.protect_dust_contracts,),
        ).fetchone()[0]
        if not material:
            resolve_flag(self.store, "UNHEDGED_POSITION", "no unreleased execution exceeds protection dust", now=snap.now)
        rep.fills_today = self.fills_today(snap.now)
        self.cursor_utc = snap.now - ADOPT_WINDOW_S
        return rep

    def _preserve_unpersisted_fills(self, snap, rep):
        """Returned validated quantity is evidence even if its FIFO write failed.

        Persist a cash-pending order total before ordinary FIFO sync/reconciliation.
        This fallback never invents complete cash and never bypasses failed execution
        persistence to send an unjournaled protective order.
        """
        by_order = {}
        for fill in snap.fills:
            by_order.setdefault(fill.venue_order_id, {})[fill.fill_id] = max(
                fill.contracts, by_order.get(fill.venue_order_id, {}).get(fill.fill_id, 0.0))
        con = self.journal.store.con
        for vid, observed in by_order.items():
            cid = None
            try:
                found = con.execute("SELECT client_order_id FROM orders WHERE venue_order_id=?", (vid,)).fetchone()
                if found is None:
                    continue  # The existing orphan/adoption path owns unknown order identity.
                cid = found[0]
                row = self.journal.get(cid)
                stored = {fid: float(q) for fid, q in con.execute(
                    "SELECT fill_id,contracts FROM venue_fills WHERE venue_order_id=?", (vid,))}
                if all(stored.get(fid, 0.0) >= quantity for fid, quantity in observed.items()):
                    continue
                for fid, quantity in observed.items():
                    stored[fid] = max(quantity, stored.get(fid, 0.0))
                quantity = max(sum(stored.values()), float(row.get("filled_contracts") or 0.0))
                if quantity <= float(row.get("filled_contracts") or 0.0):
                    continue
                price = float(row.get("price") or 0.0)
                prior_price = row.get("avg_price")
                if prior_price is not None:
                    price = min(price, float(prior_price)) if row["side"].startswith("sell") else max(price, float(prior_price))
                state = FillState.FILLED if quantity >= float(row["contracts"]) else FillState.PARTIAL
                open_order = bool(row.get("open"))
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='pm_post_only_orders'").fetchone():
                    marker = con.execute("SELECT terminal_proved FROM pm_post_only_orders WHERE client_order_id=?", (cid,)).fetchone()
                    open_order = open_order or bool(marker is not None and not marker[0])
                detail = f"validated unpersisted fill evidence retained: {quantity:g}; cash/FIFO coverage pending"
                self.journal.record(Ack(row["venue"], cid, vid, state, quantity, price, row.get("fee_usd"),
                                        "guard_unpersisted_fill", snap.now, open=open_order,
                                        settlement_pending=True, detail=detail), kind="guard_unpersisted_fill",
                                    raw={"observed_fill_quantities": observed, "union_quantity": quantity})
                rep.findings.append(f"UNPERSISTED_FILL_RETAINED {cid}: {quantity:g} recorded pending for reconciliation")
            except Exception as exc:
                detail = f"PERSISTENCE_FAILED {cid or vid}: returned quantity {sum(observed.values()):g}; order fallback failed: {type(exc).__name__}: {exc}"
                rep.findings.append(detail)
                for fill in snap.fills:
                    if fill.venue_order_id == vid:
                        adapter = self.venues.get(fill.venue)
                        if callable(getattr(adapter, "_persistence_failure", None)):
                            adapter._persistence_failure(cid or vid, exc)
                        elif self.kill is not None:
                            self.kill.latch("live", detail)
                        break

    def _detect_order_overfills(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        """Catch authoritative late fills even when the coordinator's poll saw zero/partial.

        Dust is a protection threshold, never permission to exceed a requested order.
        Read the durable totals after sync/adoption, without changing the reported fill.
        """
        rows = self.journal.store.con.execute(
            "SELECT client_order_id,venue,contracts,filled_contracts,mode FROM orders "
            "WHERE filled_contracts > contracts + 0.000000001"
        ).fetchall()
        for cid, venue, requested, filled, mode in rows:
            if mode not in _REAL_MODES:
                continue
            key = f"overfill:{cid}:{filled}"
            if key in self.said:
                continue
            detail = f"{venue} {cid}: requested {requested:g}, venue filled {filled:g}"
            rep.findings.append(f"ORDER_OVERFILL {detail}")
            # Latch first: failure to write an audit flag must not permit another entry.
            if self.kill is not None:
                try:
                    self.kill.latch("live", f"guard: ORDER_OVERFILL {detail}")
                except Exception as exc:  # noqa: BLE001
                    rep.findings.append(f"kill latch failed: {type(exc).__name__}")
                else:
                    self.said.add(key)
            else:
                self.said.add(key)
            self._flag("ORDER_OVERFILL", detail, snap.now)

    def _close_final_zero_fills(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        """Release an ambiguous execution once the venue finally proves zero fill.

        The coordinator gives `not_found` time to reconcile with the trade feed and therefore
        exits UNKNOWN_PROVIDER_STATE after its six-second synchronous window. When the later
        guard poll reaches terminal UNFILLED/REJECTED, no position exists and the reservation can
        be closed. Without this handoff every genuine zero-fill would block its event forever.
        """
        for cid, state in snap.unconfirmed.items():
            if state not in (FillState.UNFILLED.value, FillState.REJECTED.value):
                continue
            row = self.journal.get(cid)
            exid = self._execution_for(row) if row is not None else None
            ex = self.records.load(exid) if exid else None
            if ex is None or ex.released or ex.holds_anything:
                continue
            if ex.state not in (X.UNKNOWN_PROVIDER_STATE, X.LEG_A_SUBMITTED):
                continue
            ex.released = True
            self.records.move(ex, X.ORDER_REJECTED, now=snap.now,
                              detail=f"guard: leg A final {state.lower()}, no position")
            if self.ledger is not None and ex.reservation_id:
                self.ledger.release(ex.reservation_id, reason=f"nothing filled: guard final {state}", now=snap.now)
            rep.findings.append(f"ZERO_FILL_FINAL {exid[:8]} {state}; reservation released")

    def _repair_reservations(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        """A late fill reopens both the execution and its capital reservation.

        The old guard reopened only `executions.released`, leaving the durable reservation
        released and absent from the in-memory exposure picture while protection bought another
        leg. Also repair rows produced by that old path on startup.
        """
        if self.ledger is None:
            return
        rows = self.records.store.con.execute(
            "SELECT execution_id,reservation_id,released FROM executions WHERE reservation_id IS NOT NULL "
            "AND (first_filled>0 OR hedge_filled>0)"
        ).fetchall()
        for exid, rid, released in rows:
            if not released and rid not in self.ledger.open and self.ledger.reopen(
                    rid, reason=f"guard restored exposure for {exid[:8]}", now=snap.now):
                rep.findings.append(f"RESERVATION_REOPENED {rid[:8]} for {exid[:8]}")
            if not released and rid not in self.ledger.open:
                detail = f"{exid[:8]} holds venue quantity but reservation {str(rid)[:8]} is missing"
                rep.findings.append(f"RESERVATION_MISSING {detail}")
                self._flag("RESERVATION_MISSING", detail, snap.now)
                if self.kill is not None:
                    try:
                        self.kill.latch("live", f"guard: {detail}")
                    except Exception as exc:  # noqa: BLE001
                        rep.findings.append(f"kill latch failed: {type(exc).__name__}")
                continue
            execution = self.records.store.con.execute(
                "SELECT first_client_id,hedge_client_ids,unwind_client_ids FROM executions WHERE execution_id=?",
                (exid,),
            ).fetchone()
            if execution is None:
                continue
            client_ids = [execution[0]] if execution[0] else []
            for payload in execution[1:]:
                try:
                    client_ids.extend(str(x) for x in json.loads(payload or "[]"))
                except (TypeError, ValueError):
                    pass
            if not client_ids:
                continue
            marks = ",".join("?" * len(client_ids))
            committed = {
                venue: float(usd or 0.0)
                for venue, usd in self.records.store.con.execute(
                    "SELECT venue,SUM(COALESCE(filled_contracts,0)*COALESCE(avg_price,0)+COALESCE(fee_usd,0)) "
                    f"FROM orders WHERE client_order_id IN ({marks}) AND side LIKE 'buy_%' GROUP BY venue",
                    client_ids,
                ).fetchall()
            }
            if self.ledger.grow_to_committed(
                    rid, per_venue_usd=committed, reason=f"guard authoritative fills for {exid[:8]}",
                    now=snap.now, exact=bool(released)):
                rep.findings.append(
                    f"RESERVATION_GROWN {rid[:8]} for {exid[:8]} to "
                    + ", ".join(f"{v}={usd:.4f}" for v, usd in sorted(committed.items()))
                )

    def _row_for(self, f: FillRecord) -> dict | None:
        con = self.journal.store.con
        r = con.execute("SELECT client_order_id FROM orders WHERE venue_order_id=?", (f.venue_order_id,)).fetchone()
        if r is not None:
            row = self.journal.get(r[0])
            if row is not None:
                self._sync_order_from_fills(row)
                row = self.journal.get(r[0])
            return row
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

    def _sync_order_from_fills(self, row: dict) -> None:
        """Make the order row carry every durable fill for its venue order id.

        A later `get_order -> not_found` used to overwrite a real Polymarket fill with zero. The
        FIFO can lag an authoritative order total. Missing fills never imply a reversal;
        only an explicit venue reversal already journaled may lower the order's quantity.
        """
        vid = row.get("venue_order_id")
        if not vid:
            return
        agg = self.journal.store.con.execute(
            "SELECT COALESCE(SUM(contracts),0),COALESCE(SUM(contracts*price),0),"
            "COALESCE(SUM(fee_usd),0),MIN(final) FROM venue_fills WHERE venue_order_id=?", (vid,)
        ).fetchone()
        qty = float(agg[0] or 0.0)
        known_qty = float(row.get("filled_contracts") or 0.0)
        if qty < known_qty - 1e-9:
            # Every available fill may be cash-final while part of the order is still
            # absent. Its partial average/fee cannot price the full known position.
            detail = (f"incomplete venue fill coverage: {qty:g}/{known_qty:g}; authoritative "
                      "order quantity and cost retained; explicit reversal required to reduce")
            if (row.get("raw_status") != "guard_fill_coverage_pending" or row.get("detail") != detail
                    or not bool(row.get("settlement_pending"))):
                self.journal.record(
                    Ack(row["venue"], row["client_order_id"], vid, FillState(row["state"]),
                        known_qty, row.get("avg_price"), row.get("fee_usd"),
                        "guard_fill_coverage_pending", self.clock(), open=bool(row.get("open")),
                        settlement_pending=True, detail=detail),
                    kind="guard_fill_coverage", raw={"fifo_contracts": qty, "authoritative_contracts": known_qty},
                )
            return
        if qty <= 1e-9:
            return
        avg = float(agg[1]) / qty
        fee = float(agg[2] or 0.0)
        settlement_pending = not bool(agg[3])
        maker_pending = False
        if self.journal.store.con.execute("SELECT 1 FROM sqlite_master WHERE name='pm_post_only_orders'").fetchone():
            marker = self.journal.store.con.execute(
                "SELECT terminal_proved FROM pm_post_only_orders WHERE client_order_id=?", (row["client_order_id"],)).fetchone()
            maker_pending = marker is not None and not bool(marker[0])
        settlement_pending = settlement_pending or maker_pending
        state = FillState.FILLED if qty >= float(row["contracts"]) - 1e-6 else FillState.PARTIAL
        if (row["state"] == state.value
                and abs(float(row.get("filled_contracts") or 0.0) - qty) <= 1e-6
                and abs(float(row.get("avg_price") or 0.0) - avg) <= 1e-9
                and abs(float(row.get("fee_usd") or 0.0) - fee) <= 1e-9
                and bool(row.get("open")) == maker_pending
                and bool(row.get("settlement_pending")) == settlement_pending):
            return
        self.journal.record(
            Ack(row["venue"], row["client_order_id"], vid, state, qty, avg, fee,
                "guard_fills", self.clock(), open=maker_pending, settlement_pending=settlement_pending,
                detail="venue fill FIFO overrides order lookup"),
            kind="guard_fill",
        )

    def _execution_for(self, row: dict) -> str | None:
        """Map an order to the execution that names its exact client id.

        Opportunity ids are intentionally reused on retries. Choosing the latest execution for
        an opportunity attributed a real fill to a later zero-fill and made the guard buy a lone
        Kalshi leg. Exact persisted client ids are the only valid join.
        """
        cid = row["client_order_id"]
        rows = self.records.store.con.execute(
            "SELECT execution_id,first_client_id,hedge_client_ids,unwind_client_ids FROM executions "
            "WHERE opportunity_id=?", (row["opportunity_id"],)
        ).fetchall()
        for exid, first, hedges, unwinds in rows:
            try:
                other = list(json.loads(hedges or "[]")) + list(json.loads(unwinds or "[]"))
            except (TypeError, ValueError):
                other = []
            if cid == first or cid in other:
                return exid
        return None

    def _reconcile_execution(self, exid: str, pairs: list[tuple[dict, FillRecord]], snap: GuardSnapshot, rep: GuardReport) -> None:
        ex = self.records.load(exid)
        plan = self.records.plan_of(exid)
        if ex is None:
            return
        if plan is None:
            return
        sums = {"first_buy": 0.0, "first_sell": 0.0, "hedge_buy": 0.0, "hedge_sell": 0.0}
        cost = {"first_buy": 0.0, "first_sell": 0.0, "hedge_buy": 0.0, "hedge_sell": 0.0}
        cash_final = True
        first_ids = {ex.first_client_id} if ex.first_client_id else set()
        hedge_ids = set(ex.hedge_client_ids)
        unwind_ids = set(ex.unwind_client_ids)
        # Rebuild from every order this execution owns, not only this guard pass's rolling fill
        # slice. Otherwise the next pass zeros a fill as soon as it leaves the cursor.
        for cid in first_ids | hedge_ids | unwind_ids:
            row = self.journal.get(cid)
            if row is None:
                continue
            qty = float(row.get("filled_contracts") or 0.0)
            if qty <= 1e-9:
                continue
            cash_final = cash_final and not bool(row.get("settlement_pending"))
            if cid in first_ids:
                leg, kind = "first", "buy"
            elif cid in hedge_ids:
                leg, kind = "hedge", "buy"
            else:
                leg = "first" if row["market_id"] == plan.first.market_id else "hedge"
                kind = "sell"
            sums[f"{leg}_{kind}"] += qty
            cost[f"{leg}_{kind}"] += qty * float(row.get("avg_price") or 0.0)

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
        quantity_changed = bool(changed)
        if cash_final:
            for key, old in (("first_buy", ex.first_avg_price), ("hedge_buy", ex.hedge_avg_price),
                             ("first_sell", ex.first_unwind_avg), ("hedge_sell", ex.hedge_unwind_avg)):
                price = avg(key)
                if price is not None and (old is None or abs(price - old) > 1e-9):
                    changed.append(f"{key}_avg {old}->{price:.12g} (authoritative cash)")
        if changed:
            note = "venue fills: " + ", ".join(changed)
            if quantity_changed and ex.state.is_terminal and ex.released and (sums["first_buy"] > 1e-9 or sums["hedge_buy"] > 1e-9):
                if self.ledger is not None and ex.reservation_id:
                    self.ledger.reopen(ex.reservation_id, reason=f"guard found a fill on {exid[:8]}", now=snap.now)
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
            gone = self._gone(ex, plan)
            if gone:
                gk = f"gone:{exid}"
                if gk not in self.said:
                    self.said.add(gk)
                    rep.findings.append(f"POSITION_GONE {exid[:8]} {gone}")
            elif not working:
                rep.to_protect.append(exid)

    def _holdings(self, snap: GuardSnapshot) -> dict[str, dict[str, float]]:
        """venue -> market -> signed contracts held, for the venues that answered this pass."""
        out: dict[str, dict[str, float]] = {}
        for v, pos in snap.positions.items():
            if pos is None:
                continue
            out[v] = {}
            for p in pos:
                out[v][p.market_id] = out[v].get(p.market_id, 0.0) + (p.contracts if p.side == "yes" else -p.contracts)
        return out

    def _gone(self, ex, plan) -> str | None:
        """The naked side's position is no longer at the venue (the market resolved and paid, or the
        operator closed it by hand): nothing to protect, the settlement pass closes the row. Only
        when the venue answered this pass; an unreadable venue never counts as empty."""
        held = getattr(self, "_held", {})
        if plan is None:
            return None
        if ex.unhedged > 1e-9:
            leg = plan.first
        elif ex.overhedged > 1e-9:
            leg = plan.hedge
        else:
            return None
        if leg.venue not in held:
            return None
        if abs(held[leg.venue].get(leg.market_id, 0.0)) <= 1e-9:
            return f"{leg.venue} holds nothing on {leg.market_id[:14]}: settled or closed by hand; left to the settlement pass"
        return None

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
            ex = self.records.load(exid)
            gone = self._gone(ex, self.records.plan_of(exid)) if ex is not None else None
            if gone:
                gk = f"gone:{exid}"
                if gk not in self.said:
                    self.said.add(gk)
                    rep.findings.append(f"POSITION_GONE {exid[:8]} {gone}")
            elif not working:
                rep.to_protect.append(exid)

    def _last_utc(self, exid: str) -> float | None:
        r = self.records.store.con.execute("SELECT last_utc FROM executions WHERE execution_id=?", (exid,)).fetchone()
        return r[0] if r else None

    def _expected_positions(self) -> dict[tuple[str, str], float]:
        """Net holdings implied by every unreleased execution, over its full lifetime.

        Venue positions are cumulative. Comparing them with only the guard's rolling 120-second
        fill cursor made a settled fill look mismatched on every restart. The execution journal
        is the durable lifetime-sized claim and is therefore the like-for-like comparator.
        """
        out: dict[tuple[str, str], float] = {}
        rows = self.records.store.con.execute(
            "SELECT execution_id FROM executions WHERE released=0"
        ).fetchall()
        for (exid,) in rows:
            ex = self.records.load(exid)
            plan = self.records.plan_of(exid)
            if ex is None or plan is None:
                continue
            for leg, qty in ((plan.first, ex.net_first), (plan.hedge, ex.net_hedge)):
                if qty <= 1e-9:
                    continue
                # A venue can pay and remove its position hours before the other venue finalizes.
                # The settlement pass records that venue-authoritative result while retaining the
                # cover's capital reservation. It is no longer an expected open position there.
                has_results = self.records.store.con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_venue_results'"
                ).fetchone()
                if has_results and self.records.store.con.execute(
                    "SELECT 1 FROM execution_venue_results WHERE execution_id=? AND venue=?",
                    (exid, leg.venue),
                ).fetchone():
                    continue
                sign = -1.0 if leg.side.endswith("_no") else 1.0
                key = (leg.venue, leg.market_id)
                out[key] = out.get(key, 0.0) + sign * qty
        return out

    def _compare_positions(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        expected = self._expected_positions()
        for v, pos in snap.positions.items():
            if pos is None:
                continue
            held = {(p.venue, p.market_id): (p.contracts if p.side == "yes" else -p.contracts) for p in pos}
            # This may be a shared account. Existing positions outside Janus are not orphans;
            # fills no Janus order claims are detected above. Compare only Janus's open claims.
            keys = {k for k in expected if k[0] == v}
            for key in keys:
                net = expected.get(key, 0.0)
                have = held.get(key, 0.0)
                if abs(have - net) > max(self.limits.protect_dust_contracts, 1e-6):
                    msg = f"{key[0]} {key[1][:16]}: venue holds {have:g}, unreleased executions imply {net:g}"
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
        day_start = t - (t % 86400.0)
        for cid, sub in jcon.execute("SELECT client_order_id, submitted_utc FROM orders WHERE state=? AND submitted_utc >= ?",
                                     (FillState.UNCONFIRMED.value, day_start)):
            if day_of(sub) == day:
                out.append(RealizedFill(cid, FillState.UNCONFIRMED, 0.0, day))
        return tuple(out)

    def _flag(self, flag: str, detail: str, now: float) -> None:
        try:
            raise_flag(self.store, flag, detail, now=now)
        except Exception as exc:  # noqa: BLE001
            self.log(f"  [guard] flag {flag} not written: {type(exc).__name__}")

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
from kernel.schema import ExecutionState as X, FillState, Mode, OpportunityStatus as S
from nodes.reconcile.reconcile import check_fees, ingest_fills, resolve_unconfirmed
from nodes.reconcile.settle_executions import refresh_settlement_accounting
from nodes.execution.dispositions import latest as latest_disposition, match_disposition
from nodes.execution.overfill_ack import match_overfill_ack
from nodes.execution.legacy_incident_ack import resolve_idle_incidents, resolve_migration_false_alarms
from nodes.execution.legacy_incident_ack import match_incident
from nodes.execution.persistence_recovery import resolve_recovered_persistence
from nodes.exec_polymarket.position_evidence import terminal_zero_positions
from nodes.risk.breaker import RealizedFill, day_of
from nodes.risk.flags import flag_snapshot, raise_flag, resolve_flag, resolve_exact_flags, unresolved_flag_rows

#: A trade this close in time to an UNCONFIRMED order on the same asset, with no other claimant,
#: is that order's fill (a FAK/IOC never rests; its fill is within seconds of its submit).
ADOPT_WINDOW_S = 120.0
#: A machine that moved this recently is still working the execution: not the guard's to protect.
IN_FLIGHT_GRACE_S = 60.0
#: The states in which nothing more is owed on the position.
_QUIET = {X.SETTLED, X.RECONCILED, X.UNWOUND}
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
    fills_read_complete: bool = False
    position_evidence: dict[str, dict] = field(default_factory=dict)


@dataclass
class GuardReport:
    findings: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)                # execution ids rewritten
    to_protect: list[str] = field(default_factory=list)               # execution ids that are naked and idle
    orphans: list[FillRecord] = field(default_factory=list)
    dispositions: list[tuple[FillRecord, int]] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    fills_today: tuple[RealizedFill, ...] = ()


class PositionGuard:
    def __init__(self, *, venues: Mapping[str, object], journal, records, store, limits, started_utc: float,
                 ledger=None, kill=None, opportunities=None,
                 log: Callable[[str], None] = print, clock: Callable[[], float] = time.time):
        self.venues, self.journal, self.records, self.store = venues, journal, records, store
        self.limits, self.ledger, self.kill, self.log, self.clock = limits, ledger, kill, log, clock
        self.opportunities = opportunities
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
            snap.fills_read_complete = True
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
                if snap.positions[v] is not None and getattr(venue, 'position_evidence', None) is not None:
                    # Freeze the evidence from this exact reader call. Never consult
                    # mutable adapter metadata during the application/writer pass.
                    snap.position_evidence[v] = json.loads(json.dumps(venue.position_evidence))
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
            exid = self._execution_for(row) if row is not None else None
            if row is None or exid is None:
                try:
                    # A disposition lifecycle must never inherit a stale reporting
                    # cache from the earlier unknown fill in this same process.
                    if latest_disposition(self.journal.store.con, f.venue, f.fill_id) is not None:
                        self.said.discard(f"orphan:{f.fill_id}")
                    disposition = match_disposition(self.journal.store.con, f)
                except Exception as exc:
                    self.said.discard(f"orphan:{f.fill_id}")
                    disposition = None
                    rep.findings.append(f'DISPOSITION_INVALID {f.venue}:{f.fill_id}: {type(exc).__name__}: {exc}')
                if disposition is not None:
                    self.said.discard(f"orphan:{f.fill_id}")
                    rep.dispositions.append((f, disposition['id']))
                    rep.findings.append(f"EXTERNAL_FILL_DISPOSITION {f.venue}:{f.fill_id} row={disposition['id']} "
                                        f"fill_sha256={disposition['fill_sha256']} {disposition['reason']}")
                    continue
                rep.orphans.append(f)
                continue
            by_exec.setdefault(exid, []).append((row, f))
        for f in rep.orphans:
            key = f"orphan:{f.fill_id}"
            detail = f"{f.venue} {f.market_id[:16]} {f.side} {f.contracts:g} @ {f.price} order {f.venue_order_id[:12]}"
            latched = True
            # Reporting may be deduplicated; a current unknown holding must
            # still stop after an operator reset, and failed latches must retry.
            if self.kill is not None and getattr(self.limits, "protect_kill_on_failure", True):
                try:
                    self.kill.latch("live", f"guard: orphan fill {detail}")
                except Exception as exc:  # noqa: BLE001
                    latched = False
                    rep.findings.append(f"kill latch failed: {type(exc).__name__}")
            if key not in self.said:
                rep.findings.append(f"ORPHAN_FILL {detail}")
                self._flag("ORPHAN_FILL", detail, snap.now)
                if latched:
                    self.said.add(key)
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
        self._resolve_disposed_orphan_flags(snap, rep)
        self._resolve_acknowledged_overfills(snap, rep)
        self._resolve_legacy_incidents(snap, rep)
        self._resolve_recovered_persistence(snap, rep)
        self.cursor_utc = snap.now - ADOPT_WINDOW_S
        return rep

    def _resolve_recovered_persistence(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        def complete_safe_pass():
            if (not snap.fills_read_complete or snap.errors or rep.orphans or rep.mismatches
                    or rep.to_protect or any(snap.positions.get(venue) is None
                                             for venue in ("kalshi", "polymarket"))):
                return False
            material = ("INVALID", "FAILED", "BLOCKED", "ORPHAN_FILL ", "POSITION_MISMATCH ",
                        "UNHEDGED_POSITION ", "PROTECT_FAILED", "ORDER_OVERFILL ", "FEE_ABOVE_PIN ")
            return not any(any(token in finding for token in material) for finding in rep.findings)

        try:
            if resolve_recovered_persistence(self.store, now=snap.now, verify_pass=complete_safe_pass):
                rep.findings.append(
                    "ORDER_PERSISTENCE_FAILED_RESOLVED_EXACT: complete terminal economic record; kill unchanged")
        except Exception as exc:  # SQLite errors remain visible and unresolved.
            rep.findings.append(f"PERSISTENCE_RESOLUTION_BLOCKED: {type(exc).__name__}: {exc}")

    def _resolve_disposed_orphan_flags(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        if (not snap.fills_read_complete or snap.errors or rep.orphans or not rep.dispositions
                or any(finding.startswith('DISPOSITION_INVALID') for finding in rep.findings)):
            return
        relevant = {fill.venue for fill, _ in rep.dispositions}
        if any(venue not in self.venues or snap.positions.get(venue) is None for venue in relevant):
            return
        acknowledged = []
        def verify():
            acknowledged.clear()
            for fill, row_id in rep.dispositions:
                current = match_disposition(self.store.con, fill)
                if current is None or current['id'] != row_id:
                    return False
                acknowledged.extend(current['orphan_flags'])
            return True
        # Populate once for the API argument, then revalidate under its writer lock.
        try:
            if verify() and resolve_exact_flags(self.store, 'ORPHAN_FILL', acknowledged,
                    'Complete guard pass; exact confirmed external-proof dispositions ' + ','.join(str(row_id) for _, row_id in rep.dispositions),
                    now=snap.now, verify=verify):
                rep.findings.append('ORPHAN_FILL_RESOLVED_EXACT: every unresolved incident matched confirmed proof ownership; kill unchanged')
        except Exception as exc:
            rep.findings.append(f'DISPOSITION_RESOLUTION_BLOCKED: {type(exc).__name__}: {exc}')

    def _resolve_legacy_incidents(self, snap, rep):
        if not self.store.con.execute("SELECT 1 FROM sqlite_master WHERE name='historical_legacy_incident_acknowledgements'").fetchone():
            return
        invalid = False
        for (flag_id,) in self.store.con.execute('SELECT DISTINCT flag_id FROM historical_legacy_incident_acknowledgements').fetchall():
            try:
                match_incident(self.store.con, flag_id, require_idle=False)
            except Exception as exc:
                invalid = True
                detail = f'LEGACY_INCIDENT_ACK_INVALID flag={flag_id}: {type(exc).__name__}: {exc}'
                rep.findings.append(detail)
                if self.kill is not None:
                    try:
                        self.kill.latch('live', detail)
                    except Exception as kill_exc:
                        rep.findings.append(f'kill latch failed: {type(kill_exc).__name__}')
                self._flag('POST_ONLY_PERSISTENCE_FAILED', detail, snap.now)
        if invalid:
            return
        position_proof = {}
        position_error = []
        def base_safe_pass():
            return (snap.fills_read_complete and not snap.errors and not rep.orphans and not rep.mismatches
                    and all(venue in self.venues for venue in ('kalshi', 'polymarket'))
                    and all(snap.positions.get(venue) is not None for venue in ('kalshi', 'polymarket'))
                    and not any(any(word in finding for word in ('INVALID', 'FAILED', 'BLOCKED', 'ORDER_OVERFILL ', 'FEE_ABOVE_PIN '))
                                for finding in rep.findings))

        # These rows are not a new historical incident: they are the exact error emitted when an
        # additive nullable journal column changed SELECT-* v1 bytes. The original incident already
        # has a valid acknowledgement and exact resolution. Resolve the derived rows after a fresh
        # complete guard and terminal database check; do not require the original one-time
        # terminal-zero position proof again.
        try:
            if resolve_migration_false_alarms(self.store, now=snap.now, verify_pass=base_safe_pass):
                rep.findings.append('POST_ONLY_PERSISTENCE_FAILED_RESOLVED_EXACT: additive journal migration false alarms; kill unchanged')
                return
        except Exception as exc:
            rep.findings.append(f'LEGACY_MIGRATION_RESOLUTION_BLOCKED: {type(exc).__name__}: {exc}')
            return

        def complete_safe_pass():
            if not base_safe_pass() or snap.positions.get('kalshi') != []:
                return False
            try:
                current = terminal_zero_positions(snap.positions.get('polymarket'), snap.position_evidence.get('polymarket'),
                                                  pass_started_utc=snap.now, now=self.clock())
                if position_proof and current != position_proof:
                    return False
                position_proof.update(current)
                return True
            except (ValueError, TypeError, ArithmeticError, AttributeError):
                if not position_error:
                    position_error.append('fresh complete Polymarket terminal-zero position evidence unavailable or contradictory')
                return False
        if not complete_safe_pass():
            if position_error:
                rep.findings.append('LEGACY_POSITION_EVIDENCE_BLOCKED: ' + position_error[0])
            return
        try:
            if resolve_idle_incidents(self.store, now=snap.now, verify_pass=complete_safe_pass, position_evidence=position_proof):
                rep.findings.append('POST_ONLY_PERSISTENCE_FAILED_RESOLVED_EXACT: confirmed historical legacy label; kill unchanged')
        except Exception as exc:
            rep.findings.append(f'LEGACY_INCIDENT_RESOLUTION_BLOCKED: {type(exc).__name__}: {exc}')

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
            marker = None
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
                snap.errors[f"persistence:guard:{cid or vid}"] = detail
                try:
                    con.rollback()
                except Exception as rollback_error:
                    rep.findings.append(f"persistence rollback failed: {type(rollback_error).__name__}: {rollback_error}")
                for fill in snap.fills:
                    if fill.venue_order_id == vid:
                        adapter = self.venues.get(fill.venue)
                        if marker is not None and callable(getattr(adapter, "_persistence_failure", None)):
                            adapter._persistence_failure(cid or vid, exc)
                        else:
                            # A legacy immediate-order lock remains a STOP, never a
                            # fabricated post-only lifecycle violation.
                            if self.kill is not None:
                                self.kill.latch("live", detail)
                            self._flag("ORDER_PERSISTENCE_FAILED", detail, snap.now)
                        break

    def _overfill_candidates(self):
        con = self.journal.store.con
        rows = {r[0]: r for r in con.execute(
            "SELECT client_order_id,venue,contracts,filled_contracts,mode FROM orders "
            "WHERE filled_contracts > contracts + 0.000000001") if r[4] in _REAL_MODES}
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='historical_order_overfill_acknowledgements'").fetchone():
            for (cid,) in con.execute("SELECT DISTINCT client_order_id FROM historical_order_overfill_acknowledgements"):
                row = con.execute("SELECT client_order_id,venue,contracts,filled_contracts,mode FROM orders WHERE client_order_id=?", (cid,)).fetchone()
                rows[cid] = row or (cid, 'missing', 0., 0., 'missing')
        return list(rows.values())

    def _detect_order_overfills(self, snap: GuardSnapshot, rep: GuardReport) -> None:
        """Catch authoritative late fills even when the coordinator's poll saw zero/partial.

        Dust is a protection threshold, never permission to exceed a requested order.
        Read the durable totals after sync/adoption, without changing the reported fill.
        """
        for cid, venue, requested, filled, mode in self._overfill_candidates():
            key = f"overfill:{cid}:{filled}"
            bounded = None
            con = self.journal.store.con
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pm_bounded_taker_orders'").fetchone():
                bounded = con.execute(
                    "SELECT max_accepted_excess FROM pm_bounded_taker_orders WHERE client_order_id=?",
                    (cid,)).fetchone()
            if bounded is not None and venue == "polymarket" and filled - requested < float(bounded[0]) - 1e-9:
                if key not in self.said:
                    rep.findings.append(
                        f"BOUNDED_TAKER_RESIDUAL_ACCEPTED {venue} {cid}: requested {requested:g}, venue filled {filled:g}")
                    self.said.add(key)
                continue
            try:
                acknowledgement = match_overfill_ack(self.journal.store.con, cid)
            except Exception as exc:
                acknowledgement = None
                rep.findings.append(f"OVERFILL_ACK_INVALID {cid}: {type(exc).__name__}: {exc}")
                self.said.discard(key)
            if acknowledgement is not None:
                self.said.discard(key)
                finding = f"HISTORICAL_OVERFILL_ACKNOWLEDGED {cid}: row={acknowledgement['id']} snapshot={acknowledgement['snapshot_sha256']}"
                if finding not in rep.findings:
                    rep.findings.append(finding)
                continue
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

    def _resolve_acknowledged_overfills(self, snap, rep):
        """A complete pass closes only confirmed exact historical flag identities."""
        if (not snap.fills_read_complete or snap.errors or rep.orphans or rep.mismatches or rep.to_protect
                or any(f.stop for f in snap.fee_findings)
                or any('INVALID' in f or 'PERSISTENCE_FAILED' in f for f in rep.findings)
                or not {'polymarket', 'kalshi'} <= set(self.venues)
                or any(snap.positions.get(v) is None for v in self.venues)):
            return
        evidence = []
        def current_evidence():
            allowed = set()
            for cid, *_ in self._overfill_candidates():
                ack = match_overfill_ack(self.journal.store.con, cid)
                if ack is None:
                    return None
                allowed.update((flag['flag'], flag['detail']) for flag in ack['flag_evidence'])
            current = [flag_snapshot(row) for row in unresolved_flag_rows(
                self.journal.store.con, 'ORDER_OVERFILL')]
            # A valid immutable acknowledgement may close a later duplicate emitted for the same
            # terminal order and exact quantity. It may never close a new/different finding.
            if any((flag['flag'], flag['detail']) not in allowed for flag in current):
                return None
            return current

        def verify():
            current = current_evidence()
            return current is not None and current == evidence
        try:
            current = current_evidence()
            if current is None:
                self._detect_order_overfills(snap, rep)
                return
            evidence.extend(current)
            if evidence and resolve_exact_flags(self.journal.store, 'ORDER_OVERFILL', evidence,
                    'complete guard pass: exact source-confirmed settled historical overfills and identical duplicate findings; kill unchanged',
                    now=snap.now, verify=verify):
                rep.findings.append('ORDER_OVERFILL_RESOLVED exact acknowledged historical incident IDs; kill unchanged')
        except Exception as exc:
            rep.findings.append(f"OVERFILL_RESOLUTION_BLOCKED {type(exc).__name__}: {exc}")
        finally:
            # Revalidation may discover changed quantity/state after the earlier
            # detector pass. Once the writer transaction is over, surface/latch it.
            self._detect_order_overfills(snap, rep)

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
            self.records.move(ex, X.ORDER_UNFILLED, now=snap.now,
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
        owner = row.get("execution_id")
        if owner and self.records.load(str(owner)) is not None:
            return str(owner)
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
        self._recover_order_ownership(ex, plan)
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
            working = ((snap.now - float(self._last_utc(exid) or 0.0)) < IN_FLIGHT_GRACE_S
                       and not ex.state.holds_position and ex.state is not X.HEDGED)
            gone = self._gone(ex, plan)
            if gone:
                gk = f"gone:{exid}"
                if gk not in self.said:
                    self.said.add(gk)
                    rep.findings.append(f"POSITION_GONE {exid[:8]} {gone}")
            elif self._protection_order_unresolved(ex):
                self._report_unresolved_protection(ex, rep)
            elif not working:
                rep.to_protect.append(exid)
        elif (not naked and not ex.released and ex.net_first > self.limits.protect_dust_contracts
              and ex.state not in _QUIET and ex.state is not X.HEDGED and cash_final):
            # A crash after a durable delta-hedge fill but before the coordinator's final state
            # transition can leave a balanced execution at LEG_A_SUBMITTED. Venue truth is enough
            # to resume it as HEDGED so settlement and reservation release can proceed.
            self.records.move(ex, X.HEDGED, now=snap.now,
                              detail="guard recovered balanced first/hedge fills after interrupted maker session")
            if self.opportunities is not None:
                opp = self.opportunities.load(ex.opportunity_id)
                if opp is not None:
                    self.opportunities.move(
                        opp, S.HEDGED, now=snap.now,
                        detail="guard recovered balanced first/hedge fills after interrupted maker session",
                    )
                    self.store.commit()
            rep.corrected.append(exid)
            rep.findings.append(f"RECOVERED_HEDGED {exid[:8]} {ex.event_id}")

    def _recover_order_ownership(self, ex, plan) -> None:
        """Repair execution client-id lists from journal rows that carry exact execution ownership."""
        rows = self.journal.store.con.execute(
            "SELECT client_order_id,market_id,side FROM orders WHERE execution_id=? ORDER BY submitted_utc",
            (ex.execution_id,),
        ).fetchall()
        changed = False
        for cid, market_id, side in rows:
            if cid == ex.first_client_id:
                continue
            target = ex.unwind_client_ids if str(side).startswith("sell_") else ex.hedge_client_ids
            if cid not in target:
                target.append(cid)
                changed = True
        if changed:
            self.records.sync(ex, now=self.clock())

    def _protection_order_unresolved(self, ex) -> bool:
        ids = set(ex.hedge_client_ids) | set(ex.unwind_client_ids)
        rows = self.journal.store.con.execute(
            "SELECT client_order_id,state,open FROM orders WHERE execution_id=?",
            (ex.execution_id,),
        ).fetchall()
        ids.update(str(row[0]) for row in rows if row[0] != ex.first_client_id)
        if ex.protect.get("maker_delta_unconfirmed") and not ids:
            return True
        for cid in ids:
            row = self.journal.get(cid)
            if row is None or row["state"] == FillState.UNCONFIRMED.value or bool(row.get("open")):
                return True
        return False

    def _report_unresolved_protection(self, ex, rep: GuardReport) -> None:
        key = f"protect-unresolved:{ex.execution_id}"
        if key not in self.said:
            self.said.add(key)
            rep.findings.append(
                f"PROTECTION_ORDER_UNRESOLVED {ex.execution_id[:8]} {ex.event_id}; exact order reconciliation required"
            )

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
            working = ((snap.now - float(last or 0.0)) < IN_FLIGHT_GRACE_S
                       and not st.holds_position and st is not X.HEDGED)
            ex = self.records.load(exid)
            plan = self.records.plan_of(exid) if ex is not None else None
            if ex is not None and plan is not None:
                self._recover_order_ownership(ex, plan)
            gone = self._gone(ex, plan) if ex is not None else None
            if gone:
                gk = f"gone:{exid}"
                if gk not in self.said:
                    self.said.add(gk)
                    rep.findings.append(f"POSITION_GONE {exid[:8]} {gone}")
            elif self._protection_order_unresolved(ex):
                self._report_unresolved_protection(ex, rep)
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

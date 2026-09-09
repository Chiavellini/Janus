#!/usr/bin/env python3
"""The post-proof checklist as code (HANDOFF 2026-09-03, "what the agent does after the armed run").

A proof file is what `ops/kalshi_live_proof.py` (and its Polymarket twin) wrote: the venue's own
acks, the fills with the charged fee beside the pinned one, the balance before and after, and --
after `--settle` -- the result and the realized PnL. This module reads that file and says, one
line per check, whether the proof did what GATE step 8 requires. It never prints a raw ack: the
acks may carry identifiers, and a checker that echoes them into a terminal log is a leak.

Pure over the proof dict plus one callback for the ledger row, so the same checks run on a
fixture in a test and on the real file from the operator's terminal.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

CENT = 0.01
FINAL_STATES = {"FILLED", "UNFILLED", "PARTIAL"}


@dataclass(frozen=True)
class Finding:
    name: str
    ok: bool
    detail: str


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _step(proof: dict, key: str) -> dict | None:
    for s in proof.get("steps", []):
        if key in s:
            return s
    return None


def check_proof(proof: dict, *, reservation_row: Callable[[str], dict | None] | None = None,
                open_rows_for_event: Callable[[str], int] | None = None) -> list[Finding]:
    """Every check the handoff lists, in its order. `reservation_row(reservation_id)` returns
    {released_utc, release_reason} or None when the ledger is reachable; `open_rows_for_event`
    counts open rows for `proof:<ticker>`. Both None = ledger checks reported as SKIPPED, not ok."""
    out: list[Finding] = []
    venue = proof.get("venue", "kalshi")
    settled = proof.get("settled")

    # 1. RESTING -> canceled, nothing filled (the cancel path proven without a fill)
    s1 = _step(proof, "resting")
    if s1 is None:
        out.append(Finding("resting_cancelled", False, "no resting step in the proof"))
    else:
        ack, cx = s1.get("resting", {}), s1.get("after_cancel", {})
        st = str(cx.get("state", ""))
        filled = _f(cx.get("filled_contracts"))
        # A venue saying the just-submitted order is LIVE is unresolved until the cancel. The
        # proof is complete when the post-cancel state is terminal; the initial ack must not be
        # treated as an authoritative zero-fill merely to make this check pass.
        if st == "UNCONFIRMED":
            out.append(Finding("resting_cancelled", False,
                               f"resting order state is UNCONFIRMED (ack {ack.get('raw_status')!r}, "
                               f"after cancel {cx.get('raw_status')!r}); reconcile before anything else"))
        elif str(ack.get("state", "")) == "REJECTED":
            out.append(Finding("resting_cancelled", False, f"resting bid was rejected: {ack.get('raw_status')!r}"))
        elif filled > 0:
            out.append(Finding("resting_cancelled", True,
                               f"resting bid filled {filled:.0f} before the cancel (the book moved through it); "
                               "counted with the fill proof, not a failure"))
        elif cx.get("open"):
            out.append(Finding("resting_cancelled", False, f"resting order still open after cancel ({cx.get('raw_status')!r})"))
        else:
            out.append(Finding("resting_cancelled", True,
                               f"resting {ack.get('raw_status')!r} -> {cx.get('raw_status')!r}, filled 0"))

    # 2. IOC final, filled <= requested
    s2 = _step(proof, "ioc")
    fills: Sequence[dict] = s2.get("fills", []) if s2 else []
    if s2 is None:
        out.append(Finding("ioc_final", False, "no IOC step in the proof"))
    else:
        st = s2.get("status", {})
        state, final = str(st.get("state", "")), bool(st.get("final"))
        filled = _f(st.get("filled_contracts"))
        requested = proof.get("contracts")
        if state not in FINAL_STATES or not final:
            out.append(Finding("ioc_final", False, f"IOC is {state or '?'} final={final}; the venue's word is not final"))
        elif requested is not None and filled > _f(requested) + 1e-9:
            # CLOB V2 fills a BUY by NOTIONAL: 5 @ 0.39 came back as 5.131577 @ 0.38 (2026-09-07). More
            # shares for the same dollars at a better price is a fill within the request; more dollars is not.
            ioc = s2.get("ioc") or {}
            limit = _f(ioc.get("limit_price")) or _f(ioc.get("avg_price")) or _f(st.get("avg_price"))
            notional = sum(_f(f.get("contracts")) * _f(f.get("price")) for f in fills) or filled * _f(st.get("avg_price"))
            if limit > 0 and notional <= _f(requested) * limit + CENT:
                out.append(Finding("ioc_final", True, f"IOC {state} final, filled {filled:.6g} for ${notional:.4f} "
                                                      f"(requested {_f(requested):.0f} @ {limit:.2f} = ${_f(requested) * limit:.4f}; "
                                                      "the venue fills by notional at a better price)"))
            else:
                out.append(Finding("ioc_final", False, f"IOC filled {filled:.6g} > requested {_f(requested):.0f} and the notional "
                                                       f"${notional:.4f} exceeds the request's ${_f(requested) * limit:.4f}"))
        else:
            out.append(Finding("ioc_final", True, f"IOC {state} final, filled {filled:.0f}"
                                                  + (f" of {_f(requested):.0f}" if requested is not None else "")))
        fill_sum = sum(_f(f.get("contracts")) for f in fills)
        if filled > 0 and abs(fill_sum - filled) > 1e-6:
            out.append(Finding("fills_match_status", False,
                               f"status says {filled:.0f} filled but the fills pulled sum to {fill_sum:.0f}"))
        elif filled > 0:
            out.append(Finding("fills_match_status", True, f"{len(fills)} fill(s) sum to {fill_sum:.0f}"))
        else:
            out.append(Finding("fills_match_status", True, "nothing filled, no fills expected"))

    # 3. Fees at the pinned curve; the STOP latch
    excess = [f for f in fills if _f(f.get("excess")) > 1e-6]
    stop = proof.get("stop")
    if stop == "FEE_ABOVE_PIN" or excess:
        out.append(Finding("fee_ok", False,
                           f"{len(excess)} fill(s) charged above the pinned curve; kill/live is latched and stays "
                           "latched until nodes/fees is re-pinned with this fill payload as a frozen fixture"))
    elif stop:
        out.append(Finding("fee_ok", False, f"proof stopped: {stop}"))
    else:
        charged = sum(_f(f.get("charged")) for f in fills)
        pinned = sum(_f(f.get("pinned")) for f in fills)
        out.append(Finding("fee_ok", True, f"charged {charged:.4f} vs pinned {pinned:.4f} over {len(fills)} fill(s)"))

    # 4. Balance delta = -(stake + fees)
    b0, b1 = proof.get("balance_before"), (s2 or {}).get("balance_after")
    if b0 is None or b1 is None:
        out.append(Finding("balance_delta", False, "balance before/after not both recorded"))
    else:
        spent = sum(_f(f.get("contracts")) * _f(f.get("price")) + _f(f.get("charged")) for f in fills)
        delta = _f(b1) - _f(b0)
        ok = abs(delta + spent) <= CENT
        if ok:
            out.append(Finding("balance_delta", True, f"{_f(b0):.4f} -> {_f(b1):.4f} (delta {delta:+.4f}; fills+fees {spent:.4f})"))
        else:
            # A venue that charges the fee against collateral but reports none on the trade (CLOB V2,
            # 2026-09-07): the delta must then equal fills + the PINNED fee to the cent -- which is the
            # fee reconciliation the proof exists for, only read from the balance instead of the trade.
            pinned_only = sum(_f(f.get("contracts")) * _f(f.get("price")) + _f(f.get("pinned")) for f in fills)
            charged = sum(_f(f.get("charged")) for f in fills)
            if charged <= 1e-9 and abs(delta + pinned_only) <= CENT:
                out.append(Finding("balance_delta", True, f"{_f(b0):.4f} -> {_f(b1):.4f} (delta {delta:+.4f} = fills {spent:.4f} + the "
                                                          f"PINNED fee {pinned_only - spent:.4f}; the venue charged it against collateral "
                                                          "and reported none on the trade)"))
            else:
                out.append(Finding("balance_delta", False, f"{_f(b0):.4f} -> {_f(b1):.4f} (delta {delta:+.4f}; fills+fees {spent:.4f})"))

    # 5. Settlement: realized PnL is the arithmetic of the result, and the reservation is released
    event_id = f"proof:{proof.get('ticker') or proof.get('token') or proof.get('slug')}"
    if settled:
        result = str(settled.get("result", "")).lower()
        won = result == str(proof.get("won_when", "yes")).lower()
        # --settle records the venue's fills on the proof's orders, late ones included (a resting bid
        # hit after the file was written, 2026-09-04); the arithmetic is over those when present.
        settled_fills = settled.get("fills") or fills
        expected = sum(_f(f.get("contracts")) * ((1.0 if won else 0.0) - _f(f.get("price"))) - _f(f.get("charged"))
                       for f in settled_fills)
        realized = _f(settled.get("realized_usd"))
        late = sum(1 for f in settled_fills if f.get("late"))
        out.append(Finding("settled_pnl", abs(realized - expected) <= CENT,
                           f"result {result!r}: realized {realized:+.4f}, expected {expected:+.4f} over {len(settled_fills)} fill(s)"
                           + (f", {late} filled after the proof file was written" if late else "")))
    if reservation_row is None or open_rows_for_event is None:
        out.append(Finding("reservation", False, "SKIPPED: ledger not reachable (pass --db)"))
    else:
        row = reservation_row(str(proof.get("reservation_id", "")))
        n_open = open_rows_for_event(event_id)
        if row is None:
            out.append(Finding("reservation", False, f"no capital_reservations row for reservation {str(proof.get('reservation_id',''))[:8]}"))
        elif settled:
            released = row.get("released_utc") is not None and bool(row.get("release_reason"))
            out.append(Finding("reservation", released and n_open == 0,
                               f"released={row.get('released_utc') is not None} reason={row.get('release_reason')!r}; "
                               f"open rows for {event_id}: {n_open}"))
        else:
            out.append(Finding("reservation", row.get("released_utc") is None and n_open == 1,
                               f"unsettled: reservation open={row.get('released_utc') is None}, open rows for {event_id}: {n_open} "
                               "(expected exactly one until --settle)"))
    return out


def ledger_callbacks(db: Path | str):
    """Read-only sqlite access to `capital_reservations`; returns (reservation_row, open_rows_for_event)
    or (None, None) when the database or the table is absent."""
    p = Path(db)
    if not p.exists():
        return None, None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        con.execute("SELECT 1 FROM capital_reservations LIMIT 1")
    except sqlite3.OperationalError:
        con.close()
        return None, None

    def reservation_row(rid: str) -> dict | None:
        r = con.execute("SELECT released_utc, release_reason FROM capital_reservations WHERE reservation_id=?",
                        (rid,)).fetchone()
        return None if r is None else {"released_utc": r[0], "release_reason": r[1]}

    def open_rows_for_event(event_id: str) -> int:
        return int(con.execute("SELECT COUNT(*) FROM capital_reservations WHERE event_id=? AND released_utc IS NULL",
                               (event_id,)).fetchone()[0])
    return reservation_row, open_rows_for_event


def run_check(path: Path | str, db: Path | str | None) -> int:
    proof = json.loads(Path(path).read_text())
    rr, oe = ledger_callbacks(db) if db is not None else (None, None)
    findings = check_proof(proof, reservation_row=rr, open_rows_for_event=oe)
    for f in findings:
        print(f"[{'ok  ' if f.ok else 'FAIL'}] {f.name}: {f.detail}")
    bad = [f for f in findings if not f.ok]
    print(f"{Path(path).name}: {len(findings) - len(bad)}/{len(findings)} checks passed"
          + ("" if proof.get("settled") else " (unsettled; run --settle after the game, then --check again)"))
    return 0 if not bad else 1

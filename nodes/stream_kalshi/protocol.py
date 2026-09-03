#!/usr/bin/env python3
"""Kalshi's orderbook_delta wire format, with no network in it.

Split from the transport on purpose. The wire format is where the venue-specific traps live, and
they are all testable offline against captured frames; the socket is just plumbing around it.

THREE TRAPS, ALL OF WHICH PRODUCE A CONFIDENT WRONG NUMBER RATHER THAN AN ERROR:

1. BOTH LADDERS ARE BIDS. Kalshi ships `yes` and `no` bid ladders and no asks at all. A YES ask at
   p exists only as a NO bid at 1-p. Read the two arrays as bid/ask and you see half the market and
   compute a spread that does not exist.

2. DELTAS ARE SIGNED CHANGES, NOT SIZES. `delta` is added to the level's current size; it is not
   the new size. Treating it as absolute silently rewrites the book to whatever the last change
   happened to be.

3. ONE MESSAGE MOVES BOTH SIDES. Because YES asks are folded from NO bids, a delta on the `no`
   ladder changes the YES book's ASKS. So a Kalshi update cannot be expressed as a list of
   (side, price, size) edits -- the projected book is recomputed and applied whole, which is what
   `BookReplica.project_in` exists for.

Field names vary by API version: `yes_dollars_fp` / `yes_dollars` / `yes`, and `delta_fp` /
`delta`. All spellings are accepted; an unrecognised message is returned as a fault rather than
ignored, because a silently dropped orderbook message is a divergence with no symptom.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kernel.schema import Quote, fold_complement_bids

SIZE_EPS = 1e-9


def _levels(raw) -> dict[float, float]:
    out: dict[float, float] = {}
    for level in raw or ():
        if not level or len(level) < 2:
            continue
        price, size = float(level[0]), float(level[1])
        if not 0.0 <= price <= 1.0:
            raise ValueError(f"Kalshi price outside [0,1]: {price!r} -- prices are probabilities, "
                             "not cents")
        if size > SIZE_EPS:
            out[price] = size
    return out


def _first(body: dict, *names):
    for n in names:
        if body.get(n) is not None:
            return body[n]
    return None


@dataclass
class TickerBook:
    """Kalshi's native state for one market: two BID ladders, never asks."""
    yes: dict[float, float] = field(default_factory=dict)
    no: dict[float, float] = field(default_factory=dict)
    seq: int | None = None

    def apply_snapshot(self, body: dict, seq: int | None) -> None:
        self.yes = _levels(_first(body, "yes_dollars_fp", "yes_dollars", "yes"))
        self.no = _levels(_first(body, "no_dollars_fp", "no_dollars", "no"))
        self.seq = seq

    def apply_delta(self, body: dict, seq: int | None) -> None:
        side = body.get("side")
        if side not in ("yes", "no"):
            raise ValueError(f"unknown Kalshi side {side!r}")
        price = _first(body, "price_dollars", "price")
        change = _first(body, "delta_fp", "delta")
        if price is None or change is None:
            raise ValueError("Kalshi delta missing price or delta")
        price, change = float(price), float(change)
        if not 0.0 <= price <= 1.0:
            raise ValueError(f"Kalshi delta price outside [0,1]: {price!r}")
        book = self.yes if side == "yes" else self.no
        # SIGNED CHANGE, not a new size.
        size = book.get(price, 0.0) + change
        if size <= SIZE_EPS:
            book.pop(price, None)
        else:
            book[price] = size
        self.seq = seq

    def project(self, outcome: str = "yes") -> tuple[list, list]:
        """(bids, asks) for one side, with asks folded from the complementary bid ladder."""
        own, other = (self.yes, self.no) if outcome == "yes" else (self.no, self.yes)
        bids = tuple(Quote(p, s) for p, s in sorted(own.items(), reverse=True))
        other_bids = tuple(Quote(p, s) for p, s in sorted(other.items(), reverse=True))
        asks = fold_complement_bids(other_bids)
        return ([(q.price, q.size) for q in bids], [(q.price, q.size) for q in asks])


@dataclass(frozen=True)
class Parsed:
    """One decoded frame."""
    kind: str                # "snapshot" | "delta" | "heartbeat" | "error" | "ignored"
    ticker: str = ""
    seq: int | None = None
    detail: str = ""
    #: The subscription this frame belongs to. `seq` is contiguous PER SID (measured 2026-09-02:
    #: every snapshot and delta carries `sid`), so a gap check must be keyed on it.
    sid: int | None = None
    #: The venue's own stamp, seconds. Deltas carry `ts`/`ts_ms`; snapshots carry none.
    server_utc: float | None = None


def server_utc_of(body: dict) -> float | None:
    """`ts_ms` (epoch ms) preferred, else ISO `ts`; None when the frame carries neither."""
    ms = body.get("ts_ms")
    if ms is not None:
        try:
            return float(ms) / 1000.0
        except (TypeError, ValueError):
            return None
    iso = body.get("ts")
    if isinstance(iso, str) and iso:
        from datetime import datetime, timezone
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
        except ValueError:
            return None
    return None


def _int_or_none(v) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def ticker_of(msg: dict) -> str:
    body = msg.get("msg") or {}
    return body.get("market_ticker") or body.get("ticker") or ""


def parse(msg: dict, books: dict[str, TickerBook]) -> Parsed:
    """Decode one frame and fold it into `books`. Never raises; faults come back as Parsed."""
    typ = msg.get("type")
    body = msg.get("msg") or {}
    seq = _int_or_none(msg.get("seq"))          # the wire sends strings on some frames
    sid = _int_or_none(msg.get("sid") if msg.get("sid") is not None else body.get("sid"))
    ticker = ticker_of(msg)
    sutc = server_utc_of(body)

    if typ in ("subscribed", "ok", "pong"):
        return Parsed("heartbeat", ticker, seq, sid=sid)
    if typ == "error":
        return Parsed("error", ticker, seq, str(body or msg), sid=sid)
    if typ not in ("orderbook_snapshot", "orderbook_delta"):
        # Not silently dropped: an unhandled orderbook message is a divergence with no symptom.
        return Parsed("ignored", ticker, seq, f"unhandled type {typ!r}", sid=sid)
    if not ticker:
        return Parsed("error", "", seq, "orderbook message with no market_ticker", sid=sid)

    book = books.setdefault(ticker, TickerBook())
    try:
        if typ == "orderbook_snapshot":
            book.apply_snapshot(body, seq)
            return Parsed("snapshot", ticker, seq, sid=sid, server_utc=sutc)
        book.apply_delta(body, seq)
        return Parsed("delta", ticker, seq, sid=sid, server_utc=sutc)
    except (ValueError, TypeError) as exc:
        return Parsed("error", ticker, seq, f"{type(exc).__name__}: {exc}", sid=sid)


def subscribe_frame(tickers, msg_id: int = 1) -> dict:
    return {"id": msg_id, "cmd": "subscribe",
            "params": {"channels": ["orderbook_delta"], "market_tickers": sorted(tickers)}}


def unsubscribe_frame(sids, msg_id: int = 2) -> dict:
    return {"id": msg_id, "cmd": "unsubscribe", "params": {"sids": list(sids)}}

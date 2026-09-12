#!/usr/bin/env python3
"""Polymarket's market channel wire format, with no network in it.

Polymarket is the harder venue and not for the reason the docs suggest. It has NO SEQUENCE NUMBER
of any kind, no documented resynchronisation protocol, and a `hash` field whose verification
mechanism is undocumented. Taken at face value a replica here cannot prove it is in sync, which is
why `BookReplica` has an "external" mode at all.

BUT THE DOCS UNDERSELL IT. Every `price_change` entry carries `best_bid` and `best_ask` for its own
asset. That is a per-message integrity check the documentation never mentions: recompute the top of
the local book after applying the change and compare. Measured live on 2026-09-02 over 7,460
checks, agreement ran 97.5-99.9%, and EVERY disagreement was a genuinely incomplete local book --
one-sided ladders on settled markets (72 bids / 0 asks at 0.999/1.00) where the venue's stated best
referenced a level we had never been sent. The check was not producing false alarms; it was
correctly reporting that our replica was missing depth.

So Polymarket is verified per message after all, and the check is real rather than cosmetic. Its
limit is honest and worth stating: it verifies the TOP of the book only. A level that drifts deeper
in the ladder is invisible to it, and the cover engine walks the ladder -- so an outside REST
reconciliation is still the backstop for depth, just not the primary defence.

THREE MORE TRAPS:

1. `size` IS ABSOLUTE, NOT A DELTA. The opposite of Kalshi, where `delta` is a signed change.
   Adding it to the level instead of replacing it silently doubles resting size.
2. BEST PRICE IS LAST in both ladders of a `book` event -- bids ran 0.01 -> 0.19 and asks
   0.99 -> 0.20. Indexing [0] for "best" prices every trade at the far end of the book.
3. `side` IS "BUY"/"SELL", not bid/ask, and a subscribe returns a LIST of `book` events rather
   than one object.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SIZE_EPS = 1e-9
PING = "PING"          # the venue requires a text PING every 10s; it answers PONG
PONG = "PONG"


@dataclass
class AssetBook:
    """One asset's ladders. Keyed by price, so ladder ORDER on the wire cannot matter."""
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    tick_size: float | None = None
    #: L81: the sorted ladders, rebuilt only when a fold changed a side (L78: `ladders()` sorted both
    #: dicts on every price_change entry, ~100/s, with no memo). Keyed by the unsorted items in
    #: identity, like the Kalshi book, so a direct edit is observed too.
    _ladder_cache: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def apply_book(self, ev: dict) -> None:
        self.bids = self._levels(ev.get("bids"))
        self.asks = self._levels(ev.get("asks"))
        ts = ev.get("tick_size")
        self.tick_size = float(ts) if ts is not None else self.tick_size

    def apply_change(self, ch: dict) -> None:
        side = ch.get("side")
        if side not in ("BUY", "SELL"):
            raise ValueError(f"unknown Polymarket side {side!r}")
        price, size = float(ch["price"]), float(ch["size"])
        if not 0.0 <= price <= 1.0:
            raise ValueError(f"Polymarket price outside [0,1]: {price!r}")
        book = self.bids if side == "BUY" else self.asks
        # ABSOLUTE size. Not a delta.
        if size <= SIZE_EPS:
            book.pop(price, None)
        else:
            book[price] = size

    @staticmethod
    def _levels(raw) -> dict[float, float]:
        out: dict[float, float] = {}
        for lvl in raw or ():
            price, size = float(lvl["price"]), float(lvl["size"])
            if not 0.0 <= price <= 1.0:
                raise ValueError(f"Polymarket price outside [0,1]: {price!r}")
            if size > SIZE_EPS:
                out[price] = size
        return out

    @property
    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    def _sorted(self, side: str, reverse: bool) -> tuple:
        d = getattr(self, side)
        items = tuple(d.items())
        cached = self._ladder_cache.get(side)
        if (cached is None or len(cached[0]) != len(items)
                or any(p is not cp or s is not cs for (p, s), (cp, cs) in zip(items, cached[0]))):
            cached = (items, tuple((p, d[p]) for p in sorted(d, reverse=reverse)))
            self._ladder_cache[side] = cached
        return cached[1]

    def ladders(self) -> tuple[list, list]:
        """(bids desc, asks asc) as fresh lists (a consumer may mutate them); sorted only when the
        side changed since the last call."""
        return (list(self._sorted("bids", True)), list(self._sorted("asks", False)))

    def agrees_with(self, best_bid, best_ask) -> bool:
        """Does the local top of book match what the venue just claimed it is?

        The only integrity check Polymarket offers. A mismatch means the local ladder is missing or
        holding a level the venue does not agree about, which is drift, not a price move.
        """
        if best_bid is not None:
            mine = self.best_bid
            if mine is None or abs(mine - float(best_bid)) > 1e-9:
                return False
        if best_ask is not None:
            mine = self.best_ask
            if mine is None or abs(mine - float(best_ask)) > 1e-9:
                return False
        return True


@dataclass(frozen=True)
class Parsed:
    kind: str                  # "book" | "change" | "pong" | "trade" | "tick_size" | "error" | "ignored"
    asset_id: str = ""
    detail: str = ""
    claimed_bid: float | None = None
    claimed_ask: float | None = None
    #: The venue's own stamp, seconds, from the event-level `timestamp` (epoch ms). Measured
    #: 2026-09-02: present on book, price_change and last_trade_price.
    server_utc: float | None = None


def events_in(raw) -> list[dict]:
    """A subscribe answers with a LIST of book events; later frames are single objects."""
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    return [raw] if isinstance(raw, dict) else []


def server_utc_of(ev: dict) -> float | None:
    ts = ev.get("timestamp")
    try:
        return None if ts is None else float(ts) / 1000.0
    except (TypeError, ValueError):
        return None


def parse_event(ev: dict, books: dict[str, AssetBook]) -> list[Parsed]:
    """Fold one event into `books`. Never raises; faults come back as Parsed."""
    et = ev.get("event_type")
    sutc = server_utc_of(ev)

    if et == "book":
        aid = ev.get("asset_id") or ""
        if not aid:
            return [Parsed("error", "", "book event with no asset_id")]
        try:
            books.setdefault(aid, AssetBook()).apply_book(ev)
        except (ValueError, TypeError, KeyError) as exc:
            return [Parsed("error", aid, f"{type(exc).__name__}: {exc}")]
        return [Parsed("book", aid, server_utc=sutc)]

    if et == "price_change":
        out: list[Parsed] = []
        for ch in ev.get("price_changes") or []:
            aid = ch.get("asset_id") or ""
            if not aid:
                out.append(Parsed("error", "", "price_change with no asset_id"))
                continue
            book = books.get(aid)
            if book is None:
                # A change for an asset we hold no snapshot for cannot be applied to anything.
                out.append(Parsed("ignored", aid, "no snapshot yet"))
                continue
            try:
                book.apply_change(ch)
            except (ValueError, TypeError, KeyError) as exc:
                out.append(Parsed("error", aid, f"{type(exc).__name__}: {exc}"))
                continue
            bb, ba = ch.get("best_bid"), ch.get("best_ask")
            out.append(Parsed("change", aid,
                              claimed_bid=None if bb is None else float(bb),
                              claimed_ask=None if ba is None else float(ba),
                              server_utc=sutc))
        return out

    if et in ("last_trade_price",):
        return [Parsed("trade", ev.get("asset_id") or "")]
    if et in ("tick_size_change",):
        return [Parsed("tick_size", ev.get("asset_id") or "")]
    return [Parsed("ignored", ev.get("asset_id") or "", f"unhandled event_type {et!r}")]


def subscribe_frame(asset_ids) -> dict:
    return {"assets_ids": sorted(asset_ids), "type": "market"}


def operation_frame(asset_ids, operation: str) -> dict:
    """Mid-connection subscribe/unsubscribe, so a slate change costs no reconnect."""
    return {"assets_ids": sorted(asset_ids), "operation": operation}

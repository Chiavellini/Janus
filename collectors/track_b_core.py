#!/usr/bin/env python3
"""Pure mechanics and compact SQLite storage for Janus Track B.

Lineage: the book fold, episode-depth fields, RSA-PSS signing shape, and PM stream event handling
were independently copied from Kilos/DaC/src/data/{kalshi_ws.py,polymarket/*.py} on 2026-08-17.
No Kilos module is imported. Janus writes only to its own data root.

This module contains no order-placement path. It normalizes every price to a YES probability in
[0,1] and every size to $1-payout contracts. Kalshi's bids-only book is folded exactly once here.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from lib.schema import Book, Quote, assert_price_range, fold_complement_bids

OFFSETS_S = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0, 60.0,
             120.0, 300.0, 600.0)
REQUIRED_OFFSETS_S = OFFSETS_S[:11]
BOOK_SIZE_EPS = 1e-9


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_ts(value: Any) -> float | None:
    """Parse epoch seconds/ms or ISO-8601 to epoch seconds."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out / 1000.0 if out > 10_000_000_000 else out
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def assert_probability(value: float | None, name: str) -> None:
    assert_price_range(value, label=name)


def kalshi_ws_headers(api_key: str, private_key: Any, now_ms: int | None = None) -> dict[str, str]:
    """RSA-PSS SHA-256 headers for GET /trade-api/ws/v2.

    The private key object is injected, making the signing input fixture-testable without reading
    credentials. Salt length is SHA-256 digest length, matching Kalshi's official example.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp = str(int(time.time() * 1000) if now_ms is None else int(now_ms))
    message = (timestamp + "GET" + "/trade-api/ws/v2").encode()
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }


@dataclass
class BidBook:
    """Kalshi's native representation: YES bids and NO bids, never asks."""

    yes: dict[float, float] = field(default_factory=dict)
    no: dict[float, float] = field(default_factory=dict)
    receive_ts: float | None = None
    exchange_ts: float | None = None
    seq: int | None = None

    @staticmethod
    def _load(levels: Iterable) -> dict[float, float]:
        out: dict[float, float] = {}
        for level in levels or ():
            if not level or len(level) < 2:
                continue
            price, size = as_float(level[0]), as_float(level[1])
            assert_probability(price, "Kalshi bid")
            if price is not None and size is not None and size > BOOK_SIZE_EPS:
                out[price] = size
        return out

    def snapshot(self, msg: dict, receive_ts: float) -> None:
        body = msg.get("msg") or msg
        self.yes = self._load(body.get("yes_dollars_fp") or body.get("yes_dollars")
                              or body.get("yes") or ())
        self.no = self._load(body.get("no_dollars_fp") or body.get("no_dollars")
                             or body.get("no") or ())
        self.receive_ts = receive_ts
        self.exchange_ts = parse_ts(body.get("ts_ms") or body.get("ts"))
        self.seq = msg.get("seq")

    def delta(self, msg: dict, receive_ts: float) -> None:
        body = msg.get("msg") or msg
        side = body.get("side")
        if side not in ("yes", "no"):
            raise ValueError(f"unknown Kalshi side: {side!r}")
        price = as_float(body.get("price_dollars") or body.get("price"))
        change = as_float(body.get("delta_fp") if body.get("delta_fp") is not None
                          else body.get("delta"))
        assert_probability(price, "Kalshi delta price")
        if price is None or change is None:
            raise ValueError("Kalshi delta missing price or size")
        book = self.yes if side == "yes" else self.no
        new_size = book.get(price, 0.0) + change
        if new_size <= BOOK_SIZE_EPS:
            book.pop(price, None)
        else:
            book[price] = new_size
        self.receive_ts = receive_ts
        self.exchange_ts = parse_ts(body.get("ts_ms") or body.get("ts")) or self.exchange_ts
        self.seq = msg.get("seq")

    @staticmethod
    def _depth(side: dict[float, float], best: float | None, cents: float) -> float | None:
        if best is None:
            return None
        return sum(size for price, size in side.items() if price >= best - cents - 1e-12)

    def quote(self) -> dict[str, float | int | None]:
        yes_bids = tuple(Quote(p, s) for p, s in sorted(self.yes.items(), reverse=True))
        no_bids = tuple(Quote(p, s) for p, s in sorted(self.no.items(), reverse=True))
        yes_book = Book(bids=yes_bids, asks=fold_complement_bids(no_bids),
                        fetched_utc=self.receive_ts or 0.0)
        no_book = Book(bids=no_bids, asks=fold_complement_bids(yes_bids),
                       fetched_utc=self.receive_ts or 0.0)
        yes_bid = yes_book.best_bid.price if yes_book.best_bid else None
        no_bid = no_book.best_bid.price if no_book.best_bid else None
        yes_ask = yes_book.best_ask.price if yes_book.best_ask else None
        no_ask = no_book.best_ask.price if no_book.best_ask else None
        yes_bid_size = yes_book.best_bid.size if yes_book.best_bid else None
        no_bid_size = no_book.best_bid.size if no_book.best_bid else None
        crossed = ((yes_bid is not None and yes_ask is not None
                    and round(yes_bid * 100) > round(yes_ask * 100))
                   or (no_bid is not None and no_ask is not None
                       and round(no_bid * 100) > round(no_ask * 100)))
        out: dict[str, float | int | None] = {
            "yes_bid": yes_bid, "yes_bid_size": yes_bid_size,
            "yes_ask": yes_ask, "yes_ask_size": no_bid_size,
            "no_bid": no_bid, "no_bid_size": no_bid_size,
            "no_ask": no_ask, "no_ask_size": yes_bid_size,
            "spread": yes_ask - yes_bid if yes_bid is not None and yes_ask is not None else None,
            "quote_crossed": int(crossed), "book_receive_ts": self.receive_ts,
            "exchange_ts": self.exchange_ts, "seq": self.seq,
        }
        for cents, suffix in ((0.01, "1c"), (0.02, "2c"), (0.05, "5c")):
            out[f"yes_bid_depth_{suffix}"] = self._depth(self.yes, yes_bid, cents)
            out[f"no_bid_depth_{suffix}"] = self._depth(self.no, no_bid, cents)
            out[f"yes_ask_depth_{suffix}"] = self._depth(self.no, no_bid, cents)
            out[f"no_ask_depth_{suffix}"] = self._depth(self.yes, yes_bid, cents)
        return out


@dataclass
class TwoSidedBook:
    """One Polymarket outcome token's ordinary bid/ask book."""

    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    receive_ts: float | None = None
    exchange_ts: float | None = None

    def snapshot(self, event: dict, receive_ts: float) -> None:
        self.bids = {float(x["price"]): float(x["size"]) for x in event.get("bids", [])
                     if float(x["size"]) > BOOK_SIZE_EPS}
        self.asks = {float(x["price"]): float(x["size"]) for x in event.get("asks", [])
                     if float(x["size"]) > BOOK_SIZE_EPS}
        self.receive_ts = receive_ts
        self.exchange_ts = parse_ts(event.get("timestamp"))
        for p in (*self.bids, *self.asks):
            assert_probability(p, "Polymarket price")

    def price_change(self, change: dict, exchange_ts: Any, receive_ts: float) -> None:
        price, size = float(change["price"]), float(change["size"])
        assert_probability(price, "Polymarket price")
        side = self.bids if change.get("side") == "BUY" else self.asks
        if size <= BOOK_SIZE_EPS:
            side.pop(price, None)
        else:
            side[price] = size
        self.receive_ts = receive_ts
        self.exchange_ts = parse_ts(exchange_ts)

    def bbo(self) -> tuple[float | None, float | None, float | None, float | None]:
        book = self.schema_book()
        return (book.best_bid.price if book.best_bid else None,
                book.best_ask.price if book.best_ask else None,
                book.best_bid.size if book.best_bid else None,
                book.best_ask.size if book.best_ask else None)

    def schema_book(self) -> Book:
        return Book(
            bids=tuple(Quote(p, s) for p, s in sorted(self.bids.items(), reverse=True)),
            asks=tuple(Quote(p, s) for p, s in sorted(self.asks.items())),
            fetched_utc=self.receive_ts or 0.0,
        )


@dataclass(frozen=True)
class WindowMarket:
    venue: str
    market_id: str
    ticker: str
    series: str
    open_ts: float
    close_ts: float
    yes_token: str | None = None
    no_token: str | None = None
    asset: str | None = None
    settle_ref: str | None = None
    raw_json: str = "{}"


def combine_pm_books(yes: TwoSidedBook | None, no: TwoSidedBook | None) -> dict[str, Any]:
    y = yes.bbo() if yes else (None, None, None, None)
    n = no.bbo() if no else (None, None, None, None)
    times = [x for x in (yes.receive_ts if yes else None, no.receive_ts if no else None) if x]
    exchange = [x for x in (yes.exchange_ts if yes else None, no.exchange_ts if no else None) if x]
    return {
        "yes_bid": y[0], "yes_ask": y[1], "yes_bid_size": y[2], "yes_ask_size": y[3],
        "no_bid": n[0], "no_ask": n[1], "no_bid_size": n[2], "no_ask_size": n[3],
        "spread": y[1] - y[0] if y[0] is not None and y[1] is not None else None,
        "quote_crossed": int(y[0] is not None and y[1] is not None and y[0] > y[1] + 1e-12),
        "book_receive_ts": min(times) if times else None,
        "exchange_ts": min(exchange) if exchange else None,
        "seq": None,
        "yes_bid_depth_1c": _pm_depth(yes.bids if yes else {}, y[0], 0.01, True),
        "yes_bid_depth_2c": _pm_depth(yes.bids if yes else {}, y[0], 0.02, True),
        "yes_bid_depth_5c": _pm_depth(yes.bids if yes else {}, y[0], 0.05, True),
        "yes_ask_depth_1c": _pm_depth(yes.asks if yes else {}, y[1], 0.01, False),
        "yes_ask_depth_2c": _pm_depth(yes.asks if yes else {}, y[1], 0.02, False),
        "yes_ask_depth_5c": _pm_depth(yes.asks if yes else {}, y[1], 0.05, False),
        "no_bid_depth_1c": _pm_depth(no.bids if no else {}, n[0], 0.01, True),
        "no_bid_depth_2c": _pm_depth(no.bids if no else {}, n[0], 0.02, True),
        "no_bid_depth_5c": _pm_depth(no.bids if no else {}, n[0], 0.05, True),
        "no_ask_depth_1c": _pm_depth(no.asks if no else {}, n[1], 0.01, False),
        "no_ask_depth_2c": _pm_depth(no.asks if no else {}, n[1], 0.02, False),
        "no_ask_depth_5c": _pm_depth(no.asks if no else {}, n[1], 0.05, False),
    }


def _pm_depth(levels: dict[float, float], best: float | None, width: float,
              descending: bool) -> float | None:
    if best is None:
        return None
    if descending:
        return sum(s for p, s in levels.items() if p >= best - width - 1e-12)
    return sum(s for p, s in levels.items() if p <= best + width + 1e-12)


def parse_pm_market(raw: dict, asset: str, open_ts: float) -> WindowMarket | None:
    """Pure Gamma payload normalization for one 15m up/down market."""
    try:
        tokens = json.loads(raw.get("clobTokenIds") or "[]") if isinstance(
            raw.get("clobTokenIds"), str) else raw.get("clobTokenIds") or []
        outcomes = json.loads(raw.get("outcomes") or "[]") if isinstance(
            raw.get("outcomes"), str) else raw.get("outcomes") or []
    except (TypeError, ValueError):
        return None
    labels = [str(x).strip().lower() for x in outcomes]
    if len(tokens) != 2 or set(labels) != {"up", "down"}:
        return None
    up = labels.index("up")
    cid = str(raw.get("conditionId") or "")
    if not cid:
        return None
    slug = str(raw.get("slug") or f"{asset}-updown-15m-{int(open_ts)}")
    return WindowMarket(
        venue="polymarket", market_id=cid, ticker=slug, series=f"PM-{asset.upper()}-15M",
        open_ts=float(open_ts), close_ts=float(open_ts + 900), yes_token=str(tokens[up]),
        no_token=str(tokens[1 - up]), asset=asset, settle_ref="chainlink",
        raw_json=json.dumps(raw, sort_keys=True, separators=(",", ":")),
    )


class Storage:
    """Small append-only database; writes are approximately tens of MB/day, not full L2."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self._schema()

    def _schema(self) -> None:
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS markets (
          venue TEXT NOT NULL, market_id TEXT NOT NULL, ticker TEXT NOT NULL, series TEXT NOT NULL,
          asset TEXT, open_ts REAL NOT NULL, close_ts REAL NOT NULL, yes_token TEXT, no_token TEXT,
          settle_ref TEXT, discovered_ts REAL NOT NULL, raw_json TEXT NOT NULL,
          PRIMARY KEY (venue, market_id)
        );
        CREATE INDEX IF NOT EXISTS idx_markets_open ON markets(open_ts, venue, series);
        CREATE TABLE IF NOT EXISTS expectations (
          venue TEXT NOT NULL, series TEXT NOT NULL, open_ts REAL NOT NULL,
          target_offset_s REAL NOT NULL, market_id TEXT, status TEXT NOT NULL,
          reason TEXT, updated_ts REAL NOT NULL,
          PRIMARY KEY (venue, series, open_ts, target_offset_s)
        );
        CREATE INDEX IF NOT EXISTS idx_expectations_open
          ON expectations(open_ts, venue, series);
        CREATE TABLE IF NOT EXISTS episodes (
          venue TEXT NOT NULL, market_id TEXT NOT NULL, ticker TEXT NOT NULL, series TEXT NOT NULL,
          asset TEXT, open_ts REAL NOT NULL, target_offset_s REAL NOT NULL, scheduled_ts REAL NOT NULL,
          sample_ts REAL NOT NULL, receive_ts REAL, exchange_ts REAL, late_by_s REAL NOT NULL,
          book_age_s REAL, source TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
          yes_bid REAL, yes_ask REAL, yes_bid_size REAL, yes_ask_size REAL,
          no_bid REAL, no_ask REAL, no_bid_size REAL, no_ask_size REAL, spread REAL,
          yes_bid_depth_1c REAL, yes_bid_depth_2c REAL, yes_bid_depth_5c REAL,
          yes_ask_depth_1c REAL, yes_ask_depth_2c REAL, yes_ask_depth_5c REAL,
          no_bid_depth_1c REAL, no_bid_depth_2c REAL, no_bid_depth_5c REAL,
          no_ask_depth_1c REAL, no_ask_depth_2c REAL, no_ask_depth_5c REAL,
          reference_source TEXT, reference_symbol TEXT, reference_value REAL,
          reference_exchange_ts REAL, reference_age_s REAL, seq INTEGER,
          PRIMARY KEY (venue, market_id, target_offset_s)
        );
        CREATE INDEX IF NOT EXISTS idx_episodes_series_open ON episodes(series, open_ts);
        CREATE TABLE IF NOT EXISTS trades (
          venue TEXT NOT NULL, market_id TEXT NOT NULL, ticker TEXT NOT NULL, receive_ts REAL NOT NULL,
          exchange_ts REAL, side TEXT, price REAL, size REAL, trade_id TEXT,
          UNIQUE (venue, market_id, exchange_ts, side, price, size, trade_id)
        );
        CREATE TABLE IF NOT EXISTS reference_prices (
          source TEXT NOT NULL, symbol TEXT NOT NULL, receive_ts REAL NOT NULL,
          exchange_ts REAL, value REAL NOT NULL,
          UNIQUE (source, symbol, exchange_ts, value)
        );
        CREATE INDEX IF NOT EXISTS idx_reference_symbol_ts
          ON reference_prices(source, symbol, exchange_ts);
        CREATE TABLE IF NOT EXISTS health (
          timestamp REAL NOT NULL, component TEXT NOT NULL, status TEXT NOT NULL, detail TEXT
        );
        """)
        self.con.commit()

    def upsert_market(self, m: WindowMarket) -> None:
        self.con.execute("""INSERT INTO markets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(venue,market_id) DO UPDATE SET
            ticker=excluded.ticker, series=excluded.series, asset=excluded.asset,
            open_ts=excluded.open_ts, close_ts=excluded.close_ts, yes_token=excluded.yes_token,
            no_token=excluded.no_token, settle_ref=excluded.settle_ref, raw_json=excluded.raw_json""",
          (m.venue, m.market_id, m.ticker, m.series, m.asset, m.open_ts, m.close_ts,
           m.yes_token, m.no_token, m.settle_ref, time.time(), m.raw_json))

    def insert_episode(self, m: WindowMarket, offset: float, quote: dict[str, Any] | None,
                       *, status: str, reason: str | None, source: str,
                       sample_ts: float | None = None, reference: tuple | None = None) -> None:
        sample_ts = time.time() if sample_ts is None else sample_ts
        scheduled = m.open_ts + offset
        q = quote or {}
        receive_ts = q.get("book_receive_ts")
        book_age = sample_ts - receive_ts if receive_ts is not None else None
        ref_source, ref_symbol, ref_value, ref_exchange_ts, ref_receive_ts = (
            reference or (None, None, None, None, None))
        params = {
            "venue": m.venue, "market_id": m.market_id, "ticker": m.ticker, "series": m.series,
            "asset": m.asset, "open_ts": m.open_ts, "target_offset_s": offset,
            "scheduled_ts": scheduled, "sample_ts": sample_ts, "receive_ts": receive_ts,
            "exchange_ts": q.get("exchange_ts"), "late_by_s": sample_ts - scheduled,
            "book_age_s": book_age, "source": source, "status": status, "reason": reason,
            "reference_source": ref_source, "reference_symbol": ref_symbol,
            "reference_value": ref_value, "reference_exchange_ts": ref_exchange_ts,
            "reference_age_s": (sample_ts - ref_receive_ts) if ref_receive_ts else None,
            "seq": q.get("seq"),
        }
        for key in (
            "yes_bid", "yes_ask", "yes_bid_size", "yes_ask_size", "no_bid", "no_ask",
            "no_bid_size", "no_ask_size", "spread", "yes_bid_depth_1c", "yes_bid_depth_2c",
            "yes_bid_depth_5c", "yes_ask_depth_1c", "yes_ask_depth_2c", "yes_ask_depth_5c",
            "no_bid_depth_1c", "no_bid_depth_2c", "no_bid_depth_5c", "no_ask_depth_1c",
            "no_ask_depth_2c", "no_ask_depth_5c"):
            params[key] = q.get(key)
        cols = list(params)
        self.con.execute(
            f"INSERT OR IGNORE INTO episodes ({','.join(cols)}) VALUES ({','.join(':'+x for x in cols)})",
            params)
        self.mark_expectation(m.venue, m.series, m.open_ts, offset, status, reason, m.market_id,
                              commit=False)

    def ensure_expectations(self, venue: str, series: str, open_ts: float) -> None:
        now = time.time()
        self.con.executemany("""INSERT OR IGNORE INTO expectations
          (venue,series,open_ts,target_offset_s,market_id,status,reason,updated_ts)
          VALUES (?,?,?,?,NULL,'pending',NULL,?)""",
          [(venue, series, open_ts, off, now) for off in OFFSETS_S])

    def mark_expectation(self, venue: str, series: str, open_ts: float, offset: float,
                         status: str, reason: str | None, market_id: str | None,
                         *, commit: bool = False) -> None:
        self.con.execute("""INSERT OR IGNORE INTO expectations
          (venue,series,open_ts,target_offset_s,market_id,status,reason,updated_ts)
          VALUES (?,?,?,?,NULL,'pending',NULL,?)""",
          (venue, series, open_ts, offset, time.time()))
        self.con.execute("""UPDATE expectations SET market_id=?,status=?,reason=?,updated_ts=?
          WHERE venue=? AND series=? AND open_ts=? AND target_offset_s=?""",
          (market_id, status, reason, time.time(), venue, series, open_ts, offset))
        if commit:
            self.con.commit()

    def insert_trade(self, venue: str, market_id: str, ticker: str, receive_ts: float,
                     exchange_ts: float | None, side: str | None, price: float | None,
                     size: float | None, trade_id: str | None) -> None:
        assert_probability(price, "trade price")
        self.con.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                         (venue, market_id, ticker, receive_ts, exchange_ts, side, price, size, trade_id))

    def insert_reference(self, source: str, symbol: str, receive_ts: float,
                         exchange_ts: float | None, value: float) -> None:
        self.con.execute("INSERT OR IGNORE INTO reference_prices VALUES (?,?,?,?,?)",
                         (source, symbol, receive_ts, exchange_ts, value))

    def health(self, component: str, status: str, detail: str = "") -> None:
        self.con.execute("INSERT INTO health VALUES (?,?,?,?)",
                         (time.time(), component, status, detail[:1000]))

    def flush(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.commit()
        self.con.close()


def imbalance(yes_bid_depth: float, yes_ask_depth: float) -> float:
    """Orientation-safe imbalance. Relabelling YES<->NO flips the sign exactly."""
    denom = yes_bid_depth + yes_ask_depth
    return 0.0 if denom <= 0 else (yes_bid_depth - yes_ask_depth) / denom


def alarm_decision(*, free_bytes: int, disk_floor_bytes: int, last_message_age_s: float,
                   max_message_age_s: float, capture_rate: float, min_capture_rate: float) -> list[str]:
    """Pure alarm comparator used both live and against fake targets."""
    out = []
    if free_bytes < disk_floor_bytes:
        out.append("disk_floor")
    if last_message_age_s > max_message_age_s:
        out.append("liveness")
    if capture_rate < min_capture_rate:
        out.append("capture_gap")
    return out

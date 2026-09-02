#!/usr/bin/env python3
"""Janus Track B episode collector: Kalshi + Polymarket, research-only.

There is deliberately no order endpoint, signing method for POST/DELETE, or LIVE flag. The only
authenticated operation is the Kalshi market-data WebSocket handshake.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from collectors.track_b_core import (  # noqa: E402
    OFFSETS_S, BidBook, Storage, TwoSidedBook, WindowMarket, alarm_decision,
    as_float, combine_pm_books, kalshi_ws_headers, parse_pm_market, parse_ts,
)
from lib.fetch import Client  # noqa: E402

KALSHI_REST = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS = "wss://api.elections.kalshi.com/trade-api/ws/v2"
PM_GAMMA = "https://gamma-api.polymarket.com"
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PM_RTDS = "wss://ws-live-data.polymarket.com"
PM_ASSETS = ("btc", "eth", "sol", "xrp", "doge", "bnb", "hype")
KALSHI_ASSETS = {
    "KXBTC15M": "btc", "KXETH15M": "eth", "KXSOL15M": "sol", "KXXRP15M": "xrp",
    "KXDOGE15M": "doge", "KXBNB15M": "bnb", "KXHYPE15M": "hype",
    "KXGOLD15M": "gold", "KXSILVER15M": "silver", "KXWTI15M": "wti",
}
CHAINLINK_SYMBOLS = {"btc": "btc/usd", "eth": "eth/usd", "sol": "sol/usd", "xrp": "xrp/usd"}
BINANCE_SYMBOLS = {"btc": "btcusdt", "eth": "ethusdt", "sol": "solusdt", "xrp": "xrpusdt"}
PYTH_SERIES_SYMBOLS = {"KXGOLD15M": "xauusd", "KXSILVER15M": "xagusd", "KXWTI15M": "wti"}


def _series(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def parse_rtds_ticks(event: object, receive_ts: float) -> list[tuple[str, str, float, float | None, float]]:
    """Normalize an RTDS update or subscription backfill into reference-price ticks."""
    if not isinstance(event, dict):
        return []
    source = {"crypto_prices": "binance",
              "crypto_prices_chainlink": "chainlink",
              "equity_prices": "pyth"}.get(event.get("topic"))
    payload = event.get("payload") or {}
    if source is None or not isinstance(payload, dict):
        return []
    symbol = str(payload.get("symbol") or "").lower()
    if not symbol:
        return []
    allowed = {
        "binance": set(BINANCE_SYMBOLS.values())
        | {f"{asset}/usd" for asset in BINANCE_SYMBOLS},
        "chainlink": set(CHAINLINK_SYMBOLS.values()),
        "pyth": set(PYTH_SERIES_SYMBOLS.values()),
    }
    if symbol not in allowed[source]:
        return []
    points = payload.get("data") if isinstance(payload.get("data"), list) else [payload]
    ticks = []
    for point in points:
        if not isinstance(point, dict) or "value" not in point:
            continue
        raw_value = (point.get("full_accuracy_value", point.get("value"))
                     if source == "pyth" else point.get("value"))
        value = as_float(raw_value)
        if value is None:
            continue
        ticks.append((source, symbol, value, parse_ts(point.get("timestamp")), receive_ts))
    return ticks


class Collector:
    def __init__(self, db_path: Path, api_key: str, private_key_path: Path,
                 *, max_late_s: float = 0.75):
        resolved = db_path.resolve()
        allowed = Path("/Volumes/Kilos/janus").resolve()
        if resolved != allowed and allowed not in resolved.parents:
            raise ValueError(f"data DB must live under {allowed}, got {resolved}")
        free = shutil.disk_usage(allowed).free
        if free < 2 * 1024 ** 3:
            raise RuntimeError(f"disk floor: {free} bytes free under {allowed}; refusing to create DB")
        self.storage = Storage(db_path)
        self.api_key = api_key
        self.private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), None)
        self.max_late_s = max_late_s
        self.kalshi_books: dict[str, BidBook] = {}
        self.pm_books: dict[str, TwoSidedBook] = {}
        self.markets: dict[tuple[str, str], WindowMarket] = {}
        self.window_markets: dict[tuple[str, str, float], WindowMarket] = {}
        self.kalshi_series: set[str] = set()
        self.pm_token_market: dict[str, WindowMarket] = {}
        self.reference: dict[tuple[str, str], tuple] = {}
        self.scheduled: set[tuple[str, str, float]] = set()
        self.rtds_shapes: set[tuple[str, str, str]] = set()
        self.last_message_ts = {
            "kalshi_ws": 0.0,
            "pm_ws": 0.0,
            "pm_rtds_crypto": 0.0,
            "pm_rtds_xauusd": 0.0,
            "pm_rtds_xagusd": 0.0,
            "pm_rtds_wti": 0.0,
        }
        has_prior = bool(self.storage.con.execute("SELECT 1 FROM expectations LIMIT 1").fetchone())
        now = time.time()
        self.first_boundary = ((int(now) - int(now) % 900) if has_prior
                               else math.ceil(now / 900) * 900)
        self.stop = asyncio.Event()
        self.http = Client("track-b", rate=3.0, burst=6.0, cache_dir=None, timeout=15)

    def add_market(self, market: WindowMarket) -> None:
        key = (market.venue, market.market_id)
        self.markets[key] = market
        self.window_markets[(market.venue, market.series, market.open_ts)] = market
        self.storage.upsert_market(market)
        for token in (market.yes_token, market.no_token):
            if token:
                self.pm_token_market[token] = market

    def latest_reference(self, market: WindowMarket) -> tuple | None:
        if market.series in PYTH_SERIES_SYMBOLS:
            return self.reference.get(("pyth", PYTH_SERIES_SYMBOLS[market.series]))
        if market.asset in CHAINLINK_SYMBOLS:
            return self.reference.get(("chainlink", CHAINLINK_SYMBOLS[market.asset]))
        return None

    async def discover_kalshi(self) -> None:
        while not self.stop.is_set():
            try:
                payload = await asyncio.to_thread(
                    self.http.get_json, f"{KALSHI_REST}/series",
                    params={"limit": 1000}, use_cache=False)
                series_meta = {s["ticker"]: s for s in payload.get("series", [])
                               if s.get("frequency") == "fifteen_min"}
                self.kalshi_series.update(series_meta)
                self.storage.health("kalshi_discovery", "series",
                                    f"fifteen_min={len(series_meta)}")
                now = time.time()
                for series, meta in sorted(series_meta.items()):
                    seen: dict[str, dict] = {}
                    for status in ("open", "unopened"):
                        data = await asyncio.to_thread(
                            self.http.get_json, f"{KALSHI_REST}/markets",
                            params={"series_ticker": series, "status": status, "limit": 100},
                            use_cache=False)
                        for raw in data.get("markets", []):
                            seen[raw.get("ticker", "")] = raw
                    for raw in seen.values():
                        ticker = str(raw.get("ticker") or "")
                        open_ts = parse_ts(raw.get("open_time"))
                        close_ts = parse_ts(raw.get("close_time"))
                        if not ticker or open_ts is None or close_ts is None:
                            continue
                        if close_ts < now - 60 or open_ts > now + 1800:
                            continue
                        settle = ",".join(x.get("name", "") for x in meta.get("settlement_sources", []))
                        self.add_market(WindowMarket(
                            venue="kalshi", market_id=ticker, ticker=ticker, series=series,
                            open_ts=open_ts, close_ts=close_ts, asset=KALSHI_ASSETS.get(series),
                            settle_ref=settle or None,
                            raw_json=json.dumps(raw, sort_keys=True, separators=(",", ":"))))
            except Exception as exc:  # noqa: BLE001
                self.storage.health("kalshi_discovery", "error", repr(exc))
            await asyncio.sleep(30)

    async def discover_pm(self) -> None:
        while not self.stop.is_set():
            now = int(time.time())
            base = now - now % 900
            try:
                for asset in PM_ASSETS:
                    for open_ts in (base, base + 900, base + 1800):
                        slug = f"{asset}-updown-15m-{open_ts}"
                        data = await asyncio.to_thread(
                            self.http.get_json, f"{PM_GAMMA}/markets", params={"slug": slug},
                            use_cache=False)
                        raw = data[0] if isinstance(data, list) and data else None
                        market = parse_pm_market(raw, asset, open_ts) if raw else None
                        if market:
                            self.add_market(market)
            except Exception as exc:  # noqa: BLE001
                self.storage.health("pm_discovery", "error", repr(exc))
            await asyncio.sleep(20)

    async def kalshi_ws(self) -> None:
        subscribed: set[str] = set()
        while not self.stop.is_set():
            desired = {m.ticker for m in self.markets.values() if m.venue == "kalshi"
                       and m.close_ts > time.time() - 30 and m.open_ts < time.time() + 1800}
            if not desired:
                await asyncio.sleep(1)
                continue
            try:
                headers = kalshi_ws_headers(self.api_key, self.private_key)
                async with websockets.connect(KALSHI_WS, additional_headers=headers,
                                              ping_interval=20, max_size=2 ** 23) as ws:
                    subscribed = set(desired)
                    await ws.send(json.dumps({"id": 1, "cmd": "subscribe", "params": {
                        "channels": ["orderbook_delta", "trade"],
                        "market_tickers": sorted(subscribed)}}))
                    self.storage.health("kalshi_ws", "connected", f"tickers={len(subscribed)}")
                    while not self.stop.is_set():
                        current = {m.ticker for m in self.markets.values() if m.venue == "kalshi"
                                   and m.close_ts > time.time() - 30 and m.open_ts < time.time() + 1800}
                        if current != subscribed:
                            break
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        receive_ts = time.time()
                        self.last_message_ts["kalshi_ws"] = receive_ts
                        msg = json.loads(raw)
                        typ, body = msg.get("type"), msg.get("msg") or {}
                        ticker = body.get("market_ticker") or body.get("ticker") or ""
                        if typ == "orderbook_snapshot" and ticker:
                            self.kalshi_books.setdefault(ticker, BidBook()).snapshot(msg, receive_ts)
                        elif typ == "orderbook_delta" and ticker:
                            self.kalshi_books.setdefault(ticker, BidBook()).delta(msg, receive_ts)
                        elif typ == "trade" and ticker:
                            price = as_float(body.get("yes_price_dollars") or body.get("yes_price"))
                            if price is not None and price > 1:
                                price /= 100.0
                            self.storage.insert_trade("kalshi", ticker, ticker, receive_ts,
                                parse_ts(body.get("ts") or body.get("created_time")),
                                body.get("taker_side"), price, as_float(body.get("count_fp")
                                or body.get("count")), str(body.get("trade_id") or ""))
            except Exception as exc:  # noqa: BLE001
                self.storage.health("kalshi_ws", "reconnect", repr(exc))
                await asyncio.sleep(2)

    async def pm_ws(self) -> None:
        subscribed: set[str] = set()
        while not self.stop.is_set():
            desired = {t for m in self.markets.values() if m.venue == "polymarket"
                       and m.close_ts > time.time() - 30 and m.open_ts < time.time() + 1800
                       for t in (m.yes_token, m.no_token) if t}
            if not desired:
                await asyncio.sleep(1)
                continue
            try:
                async with websockets.connect(PM_WS, ping_interval=None, max_size=2 ** 23) as ws:
                    subscribed = set(desired)
                    await ws.send(json.dumps({"assets_ids": sorted(subscribed), "type": "market",
                                              "custom_feature_enabled": True}))
                    self.storage.health("pm_ws", "connected", f"tokens={len(subscribed)}")

                    async def ping() -> None:
                        while True:
                            await asyncio.sleep(10)
                            await ws.send("PING")
                    pinger = asyncio.create_task(ping())
                    try:
                        while not self.stop.is_set():
                            current = {t for m in self.markets.values() if m.venue == "polymarket"
                                       and m.close_ts > time.time() - 30
                                       and m.open_ts < time.time() + 1800
                                       for t in (m.yes_token, m.no_token) if t}
                            if current != subscribed:
                                break
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                            if raw == "PONG":
                                continue
                            receive_ts = time.time()
                            self.last_message_ts["pm_ws"] = receive_ts
                            parsed = json.loads(raw)
                            for event in parsed if isinstance(parsed, list) else [parsed]:
                                self.handle_pm_event(event, receive_ts)
                    finally:
                        pinger.cancel()
            except Exception as exc:  # noqa: BLE001
                self.storage.health("pm_ws", "reconnect", repr(exc))
                await asyncio.sleep(2)

    def handle_pm_event(self, event: dict, receive_ts: float) -> None:
        typ = event.get("event_type")
        if typ == "book":
            token = str(event.get("asset_id") or "")
            if token:
                self.pm_books.setdefault(token, TwoSidedBook()).snapshot(event, receive_ts)
        elif typ == "price_change":
            for change in event.get("price_changes", []):
                token = str(change.get("asset_id") or "")
                if token:
                    self.pm_books.setdefault(token, TwoSidedBook()).price_change(
                        change, event.get("timestamp"), receive_ts)
        elif typ == "last_trade_price":
            token = str(event.get("asset_id") or "")
            market = self.pm_token_market.get(token)
            if market:
                self.storage.insert_trade("polymarket", market.market_id, market.ticker,
                    receive_ts, parse_ts(event.get("timestamp")), event.get("side"),
                    as_float(event.get("price")), as_float(event.get("size")),
                    str(event.get("transaction_hash") or ""))

    async def rtds_connection(self, component: str, subscriptions: list[dict]) -> None:
        while not self.stop.is_set():
            try:
                async with websockets.connect(PM_RTDS, ping_interval=None) as ws:
                    # RTDS accepts incremental subscriptions. Sending repeated same-topic filters
                    # separately avoids a live server behavior where only the first filter in a
                    # batched topic is honored.
                    for subscription in subscriptions:
                        await ws.send(json.dumps({
                            "action": "subscribe", "subscriptions": [subscription]}))
                        await asyncio.sleep(0.02)

                    async def ping() -> None:
                        while True:
                            await asyncio.sleep(5)
                            await ws.send("PING")
                    pinger = asyncio.create_task(ping())
                    try:
                        while not self.stop.is_set():
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                            frame = raw.decode() if isinstance(raw, bytes) else raw
                            frame = frame.strip()
                            if frame.upper() == "PONG":
                                continue
                            if frame.upper() == "PING":
                                await ws.send("PONG")
                                continue
                            if not frame:
                                self.storage.health("pm_rtds", "non_json_frame", "empty")
                                continue
                            receive_ts = time.time()
                            try:
                                event = json.loads(frame)
                            except json.JSONDecodeError:
                                self.storage.health("pm_rtds", "non_json_frame", repr(frame[:80]))
                                continue
                            if isinstance(event, dict):
                                payload = event.get("payload") or {}
                                symbol = (str(payload.get("symbol") or "").lower()
                                          if isinstance(payload, dict) else "")
                                shape = (str(event.get("topic") or ""),
                                         str(event.get("type") or ""), symbol)
                                if shape not in self.rtds_shapes:
                                    self.rtds_shapes.add(shape)
                                    data = payload.get("data") if isinstance(payload, dict) else None
                                    self.storage.health("pm_rtds", "event_shape", json.dumps({
                                        "topic": shape[0], "type": shape[1], "symbol": shape[2],
                                        "payload_keys": sorted(payload) if isinstance(payload, dict) else [],
                                        "data_len": len(data) if isinstance(data, list) else None,
                                        "value": payload.get("value") if isinstance(payload, dict) else None,
                                        "full_accuracy_value": payload.get("full_accuracy_value")
                                        if isinstance(payload, dict) else None,
                                    }, sort_keys=True, separators=(",", ":")))
                            ticks = parse_rtds_ticks(event, receive_ts)
                            if ticks:
                                self.last_message_ts[component] = receive_ts
                            for tick in ticks:
                                source, symbol, value, exchange_ts, _ = tick
                                prior = self.reference.get((source, symbol))
                                if prior is None or (exchange_ts or 0) >= (prior[3] or 0):
                                    self.reference[(source, symbol)] = tick
                                self.storage.insert_reference(
                                    source, symbol, receive_ts, exchange_ts, value)
                    finally:
                        pinger.cancel()
            except Exception as exc:  # noqa: BLE001
                self.storage.health(component, "reconnect", repr(exc))
                await asyncio.sleep(2)

    async def rtds(self) -> None:
        streams = [
            ("pm_rtds_crypto", [
                {"topic": "crypto_prices", "type": "update",
                 "filters": ",".join(BINANCE_SYMBOLS.values())},
                {"topic": "crypto_prices_chainlink", "type": "*"},
            ]),
            *((f"pm_rtds_{symbol}", [{
                "topic": "equity_prices", "type": "*",
                "filters": json.dumps({"symbol": symbol.upper()}, separators=(",", ":")),
            }]) for symbol in PYTH_SERIES_SYMBOLS.values()),
        ]
        await asyncio.gather(*(
            self.rtds_connection(component, subscriptions)
            for component, subscriptions in streams
        ))

    def market_for_window(self, venue: str, series: str, open_ts: float) -> WindowMarket | None:
        return self.window_markets.get((venue, series, open_ts))

    async def capture_expected_window(self, venue: str, series: str, open_ts: float) -> None:
        self.storage.ensure_expectations(venue, series, open_ts)
        for offset in OFFSETS_S:
            target = open_ts + offset
            delay = target - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            sample_ts = time.time()
            late = sample_ts - target
            market = self.market_for_window(venue, series, open_ts)
            if market is None:
                self.storage.mark_expectation(venue, series, open_ts, offset, "gap",
                                              "market_not_discovered", None)
                continue
            if late > self.max_late_s:
                self.storage.insert_episode(market, offset, None, status="gap",
                    reason="scheduler_late", source="none", sample_ts=sample_ts,
                    reference=self.latest_reference(market))
                continue
            if market.venue == "kalshi":
                state = self.kalshi_books.get(market.ticker)
                quote = state.quote() if state else None
            else:
                quote = combine_pm_books(self.pm_books.get(market.yes_token or ""),
                                         self.pm_books.get(market.no_token or ""))
            if not quote or quote.get("yes_bid") is None or quote.get("yes_ask") is None:
                status, reason = "gap", "book_unavailable"
            elif quote.get("quote_crossed"):
                status, reason = "invalid", "crossed_quote"
            else:
                status, reason = "captured", None
            ref = self.latest_reference(market)
            supported_ref = (market.series in PYTH_SERIES_SYMBOLS
                             or market.asset in CHAINLINK_SYMBOLS)
            if ref is None and market.asset:
                ref_reason = "reference_missing" if supported_ref else "reference_unavailable"
                reason = (reason + ";" if reason else "") + ref_reason
            self.storage.insert_episode(market, offset, quote, status=status, reason=reason,
                source="ws_book", sample_ts=sample_ts, reference=ref)

    async def scheduler(self) -> None:
        while not self.stop.is_set():
            now = time.time()
            current = int(now) - int(now) % 900
            expected = [("kalshi", s) for s in sorted(self.kalshi_series)]
            expected += [("polymarket", f"PM-{a.upper()}-15M") for a in PM_ASSETS]
            for boundary in (current, current + 900):
                if boundary < self.first_boundary:
                    continue
                for venue, series in expected:
                    key = (venue, series, float(boundary))
                    if key in self.scheduled:
                        continue
                    self.scheduled.add(key)
                    asyncio.create_task(self.capture_expected_window(
                        venue, series, float(boundary)))
            await asyncio.sleep(0.2)

    async def monitor(self) -> None:
        root = Path("/Volumes/Kilos/janus")
        while not self.stop.is_set():
            free = shutil.disk_usage(root).free
            now = time.time()
            capture_rows = self.storage.con.execute("""SELECT series,
                SUM(CASE WHEN status='captured' THEN 1 ELSE 0 END),COUNT(*)
              FROM expectations WHERE venue='kalshi' AND target_offset_s<=60 AND open_ts=(
                SELECT MAX(open_ts) FROM expectations WHERE open_ts<=?) GROUP BY series""",
                (now - 75,)).fetchall()
            passing_series = sum((row[1] or 0) / row[2] >= .98 for row in capture_rows if row[2])
            capture_rate = min(1.0, passing_series / 12) if capture_rows else 1.0
            disk_alarms = alarm_decision(free_bytes=free, disk_floor_bytes=2 * 1024 ** 3,
                last_message_age_s=0, max_message_age_s=90, capture_rate=capture_rate,
                min_capture_rate=0.98)
            for alarm in disk_alarms:
                self.storage.health("monitor", alarm,
                    f"free={free} latest_window_series_passing={passing_series}/12")
            for component, last in self.last_message_ts.items():
                age = now - last if last else 1e9
                if age > 90:
                    self.storage.health("monitor", "liveness",
                                        f"component={component} age_s={age:.1f}")
            if "disk_floor" in disk_alarms:
                self.stop.set()
                raise RuntimeError("disk floor breached; collector stopped fail-closed")
            await asyncio.sleep(30)

    async def flusher(self) -> None:
        """Commit buffered event writes away from the latency-critical open window."""
        while not self.stop.is_set():
            phase = time.time() % 900
            if 62.0 < phase < 899.5:
                self.storage.flush()
            await asyncio.sleep(1)

    async def run(self, duration_s: float | None) -> None:
        tasks = [asyncio.create_task(fn()) for fn in (
            self.discover_kalshi, self.discover_pm, self.kalshi_ws, self.pm_ws,
            self.rtds, self.scheduler, self.monitor, self.flusher)]
        try:
            if duration_s:
                await asyncio.wait_for(self.stop.wait(), timeout=duration_s)
            else:
                await self.stop.wait()
        except asyncio.TimeoutError:
            self.stop.set()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.storage.close()


def selftest() -> None:
    fake = alarm_decision(free_bytes=1, disk_floor_bytes=2, last_message_age_s=91,
                          max_message_age_s=90, capture_rate=.97, min_capture_rate=.98)
    assert fake == ["disk_floor", "liveness", "capture_gap"]
    print("PASS fake-target alarms: disk_floor,liveness,capture_gap")
    print("PASS research-only surface: no order-placement method exists")


def public_probe() -> dict:
    """Small current-payload check. Reads public REST only and writes nothing."""
    client = Client("track-b-probe", rate=3.0, burst=6.0, cache_dir=None, timeout=15)
    series_payload = client.get_json(f"{KALSHI_REST}/series", params={"limit": 1000},
                                     use_cache=False)
    series = [s for s in series_payload.get("series", []) if s.get("frequency") == "fifteen_min"]
    markets = []
    now = time.time()
    for meta in sorted(series, key=lambda x: x.get("ticker", "")):
        ticker = meta.get("ticker")
        payload = client.get_json(f"{KALSHI_REST}/markets",
                                  params={"series_ticker": ticker, "status": "open", "limit": 5},
                                  use_cache=False)
        raw = (payload.get("markets") or [None])[0]
        if raw:
            markets.append({
                "series": ticker,
                "ticker": raw.get("ticker"),
                "open_time": raw.get("open_time"),
                "close_time": raw.get("close_time"),
                "open_lag_s": now - parse_ts(raw.get("open_time"))
                              if parse_ts(raw.get("open_time")) else None,
                "close_ahead_s": parse_ts(raw.get("close_time")) - now
                                 if parse_ts(raw.get("close_time")) else None,
                "settlement_sources": [x.get("name") for x in meta.get("settlement_sources", [])],
                "has_decimal_dollar_fields": any(k.endswith("_dollars") for k in raw),
            })
    base = int(now) - int(now) % 900
    pm = []
    for asset in PM_ASSETS:
        slug = f"{asset}-updown-15m-{base}"
        payload = client.get_json(f"{PM_GAMMA}/markets", params={"slug": slug}, use_cache=False)
        raw = payload[0] if isinstance(payload, list) and payload else None
        pm.append({"asset": asset, "slug": slug, "found": bool(raw),
                   "condition_id": raw.get("conditionId") if raw else None,
                   "has_tokens": bool(raw and raw.get("clobTokenIds")),
                   "fee_schedule": raw.get("feeSchedule") if raw else None})
    return {"measured_ts": now, "evidence_tier": "M1", "kalshi_fifteen_min_count": len(series),
            "kalshi_series": [s.get("ticker") for s in series], "kalshi_open_markets": markets,
            "polymarket_current": pm, "http_stats": client.stats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/track_b/episodes.sqlite")
    ap.add_argument("--duration-s", type=float)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--public-probe", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        selftest()
        return 0
    if args.public_probe:
        print(json.dumps(public_probe(), indent=2, sort_keys=True))
        return 0
    api_key = os.environ.get("JANUS_KALSHI_API_KEY", "")
    key_path = os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH", "")
    if not api_key or not key_path:
        raise SystemExit("missing JANUS_KALSHI_API_KEY/JANUS_KALSHI_PRIVATE_KEY_PATH")
    collector = Collector(Path(args.db), api_key, Path(key_path))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, collector.stop.set)
    loop.run_until_complete(collector.run(args.duration_s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

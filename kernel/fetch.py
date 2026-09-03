#!/usr/bin/env python3
"""Polite, rate-limited HTTP for bulk venue crawling (module named `fetch`, NOT `http`).

Kilos has NO rate limiter anywhere — no token bucket, no semaphore, no per-host budget; politeness
is a bare `time.sleep(0.1)` between sequential pages, and fan-out is unbounded `asyncio.gather` over
small fixed lists. That is fine for 5 hardcoded series. Janus crawls thousands of markets across two
venues, so the limiter is built here once and every crawler goes through it.

What this provides that the Kilos clients do not:
  * a real per-host token bucket (steady rate + burst)
  * `Retry-After` honoured on 429, exponential backoff on 5xx/network, jitter on every retry
  * an OffsetCap signal, because Polymarket's gamma API returns HTTP 422 past offset ~2100 rather
    than an empty page — a crawler that treats 422 as a hard error silently truncates the catalog
  * on-disk response caching, so re-running a crawl during development costs nothing and the
    "byte-identical on re-run" verification gate is actually reachable

Lineage: retry/backoff shape follows Kilos DaC/src/data/kalshi_fetcher.py; the offset-cap concept
and date-bisection workaround come from Kilos PM/phase1/build_gap_windows.py:99-145.

NAMING: this module is `fetch`, deliberately not `http` — a `lib/http.py` shadows the stdlib `http`
package for anything run from inside `lib/`, and `urllib.request` fails to import at all.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
DEFAULT_TIMEOUT = 40.0
MAX_RETRIES = 4
BASE_BACKOFF = 1.5


class OffsetCap(Exception):
    """The API refused a deep offset (gamma 422s past ~2100).

    This is NOT a failure — it means "you have paged as far as this channel allows". Callers must
    catch it and narrow the query (date slice, tag, ordering) rather than treating the catalog as
    complete. Silently swallowing it truncates the corpus, which is exactly how a first crawl of
    Polymarket showed 15 political events when the real book holds $200M+ of them.
    """


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status, self.url, self.body = status, url, body


class TokenBucket:
    """Thread-safe token bucket: `rate` requests/sec sustained, `burst` allowed instantaneously."""

    def __init__(self, rate: float, burst: float | None = None):
        self.rate = float(rate)
        self.capacity = float(burst if burst is not None else max(1.0, rate))
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, n: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = (n - self._tokens) / self.rate
            time.sleep(min(deficit, 1.0))


class Client:
    """One instance per host. Owns that host's budget and (optionally) its response cache."""

    def __init__(self, name: str, rate: float = 4.0, burst: float = 8.0,
                 cache_dir: Path | str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.name = name
        self.bucket = TokenBucket(rate, burst)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "429s": 0, "offset_caps": 0}

    # ── cache ────────────────────────────────────────────────────────────
    @staticmethod
    def cache_key(url: str, params: dict | None = None) -> str:
        """Order-independent cache key.

        BUG THIS FIXES: the key used to be the request URL, and the request URL is built with
        `urlencode(params)`, which preserves dict INSERTION order. So `{"limit":100,"cursor":"x"}`
        and `{"cursor":"x","limit":100}` are the same request but two different cache entries —
        a silent extra fetch, and worse, two entries that can drift apart. Sorting the pairs makes
        the key canonical. The REQUEST url is deliberately left untouched, so this changes nothing
        a server sees.
        """
        if not params:
            return url
        flat = sorted((str(k), str(v)) for k, v in params.items())
        return url + "?" + urllib.parse.urlencode(flat)

    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"

    # ── core ─────────────────────────────────────────────────────────────
    def get_json(self, url: str, *, params: dict | None = None, use_cache: bool = True,
                 headers: dict | None = None):
        ck = self.cache_key(url, params)
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        cp = self._cache_path(ck) if use_cache else None
        if cp and cp.exists():
            self.stats["cache_hits"] += 1
            return json.loads(cp.read_text())

        last = None
        for attempt in range(MAX_RETRIES):
            self.bucket.take()
            self.stats["requests"] += 1
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json",
                                                       **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode())
                if cp:
                    cp.write_text(json.dumps(data))
                return data
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:500]
                except Exception:  # noqa: BLE001
                    pass
                # 422 on a paginated endpoint == the offset cap. Signal, do not retry.
                if e.code == 422:
                    self.stats["offset_caps"] += 1
                    raise OffsetCap(url) from e
                if e.code == 429:
                    self.stats["429s"] += 1
                    wait = float(e.headers.get("Retry-After") or BASE_BACKOFF * (2 ** attempt))
                    last = e
                elif 500 <= e.code < 600:
                    wait = BASE_BACKOFF * (2 ** attempt)
                    last = e
                else:
                    raise HttpError(e.code, url, body) from e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                wait = BASE_BACKOFF * (2 ** attempt)
                last = e
            self.stats["retries"] += 1
            time.sleep(wait + random.uniform(0, 0.4))
        raise RuntimeError(f"{self.name}: giving up on {url} after {MAX_RETRIES} attempts: {last}")

    def post_json(self, url: str, payload, *, headers: dict | None = None):
        """POST (Polymarket's /books takes a batch of token ids). Never cached."""
        for attempt in range(MAX_RETRIES):
            self.bucket.take()
            self.stats["requests"] += 1
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                         **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                if attempt == MAX_RETRIES - 1:
                    raise
                self.stats["retries"] += 1
                time.sleep(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.4))

    def post_json_once(self, url: str, payload, *, headers: dict | None = None):
        """One non-retried JSON POST for non-idempotent endpoints.

        Trading endpoints may be idempotent at the provider, but a client-side retry after a
        timeout creates an ambiguous acceptance window and can amplify rate-limit/rejection
        problems. Callers that need a retry must reconcile the provider's reference first.
        """
        self.bucket.take()
        self.stats["requests"] += 1
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                     **(headers or {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def delete_json(self, url: str, *, headers: dict | None = None):
        """One non-retried DELETE (order cancellation). A cancel is idempotent at the venue, but a
        retry here would hide whether the FIRST attempt reached it; the caller reconciles."""
        self.bucket.take()
        self.stats["requests"] += 1
        req = urllib.request.Request(url, method="DELETE",
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                              **(headers or {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}

    def paginate_cursor(self, url: str, params: dict, key: str, *, max_pages: int = 500,
                        use_cache: bool = True):
        """Kalshi-style cursor walk. Yields each page's list; stops on empty page or no cursor."""
        cur, pages = None, 0
        while pages < max_pages:
            p = dict(params)
            if cur:
                p["cursor"] = cur
            d = self.get_json(url, params=p, use_cache=use_cache)
            page = d.get(key) or []
            if not page:
                return
            yield page
            pages += 1
            cur = d.get("cursor") or None
            if not cur:
                return

    def paginate_offset(self, url: str, params: dict, *, limit: int = 100,
                        max_offset: int = 100_000, use_cache: bool = True):
        """Gamma-style offset walk. Raises OffsetCap when the API refuses a deep offset.

        Callers MUST handle OffsetCap by narrowing the query — see catalog/enumerate_pm.py.
        """
        off = 0
        while off < max_offset:
            p = dict(params, limit=limit, offset=off)
            page = self.get_json(url, params=p, use_cache=use_cache)
            if not isinstance(page, list) or not page:
                return
            yield page
            if len(page) < limit:
                return
            off += limit


def selftest() -> None:
    b = TokenBucket(rate=50.0, burst=2.0)
    t0 = time.monotonic()
    for _ in range(6):
        b.take()
    el = time.monotonic() - t0
    # 6 tokens from a 2-burst bucket at 50/s: 4 must be refilled => >= ~80ms
    assert el >= 0.05, f"bucket did not throttle: {el:.3f}s"
    assert el < 2.0, f"bucket over-throttled: {el:.3f}s"
    assert issubclass(OffsetCap, Exception)
    print(f"http selftest OK (bucket throttled 6 takes to {el * 1000:.0f}ms)")


if __name__ == "__main__":
    selftest()

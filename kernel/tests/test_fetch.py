#!/usr/bin/env python3
"""The HTTP client every source node depends on. Until 2026-09-02 it had zero tests."""
from __future__ import annotations

import email.message
import io
import json
import time
import urllib.error
from contextlib import contextmanager

import pytest

from kernel import fetch
from kernel.fetch import Client, HttpError, OffsetCap, TokenBucket


class Responder:
    """Scripted urlopen: each call pops the next outcome (a dict payload or an exception)."""
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    @contextmanager
    def __call__(self, req, timeout=None):
        self.calls.append(req.full_url)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        yield io.BytesIO(json.dumps(out).encode())


def http_error(code, retry_after=None):
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://x", code, "err", hdrs, io.BytesIO(b"body"))


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(fetch.time, "sleep", lambda s: slept.append(s))
    return slept


def test_token_bucket_throttles_beyond_its_burst():
    b = TokenBucket(rate=50.0, burst=2.0)
    t0 = time.monotonic()
    for _ in range(6):
        b.take()
    assert 0.05 <= time.monotonic() - t0 < 2.0


def test_cache_key_is_independent_of_param_insertion_order():
    a = Client.cache_key("http://x", {"limit": 100, "cursor": "c"})
    b = Client.cache_key("http://x", {"cursor": "c", "limit": 100})
    assert a == b and Client.cache_key("http://x") == "http://x"


def test_a_5xx_is_retried_with_backoff_and_then_succeeds(monkeypatch, no_sleep):
    r = Responder([http_error(502), http_error(503), {"ok": 1}])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    c = Client("t", rate=1000, burst=1000)
    assert c.get_json("http://x/a", use_cache=False) == {"ok": 1}
    assert len(r.calls) == 3 and c.stats["retries"] == 2
    assert no_sleep[1] > no_sleep[0], "exponential, not constant"


def test_429_honours_retry_after(monkeypatch, no_sleep):
    r = Responder([http_error(429, retry_after=7), {"ok": 1}])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    Client("t", rate=1000, burst=1000).get_json("http://x/a", use_cache=False)
    assert 7.0 <= no_sleep[0] < 7.5, "Retry-After plus jitter, not our own backoff"


def test_422_is_the_offset_cap_signal_not_a_retry(monkeypatch, no_sleep):
    r = Responder([http_error(422)])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    with pytest.raises(OffsetCap):
        Client("t", rate=1000, burst=1000).get_json("http://x/a", use_cache=False)
    assert len(r.calls) == 1 and not no_sleep


def test_other_4xx_raise_immediately(monkeypatch, no_sleep):
    r = Responder([http_error(404)])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    with pytest.raises(HttpError):
        Client("t", rate=1000, burst=1000).get_json("http://x/a", use_cache=False)
    assert len(r.calls) == 1


def test_giving_up_names_the_url_and_attempt_count(monkeypatch, no_sleep):
    r = Responder([http_error(500)] * fetch.MAX_RETRIES)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    with pytest.raises(RuntimeError, match="giving up"):
        Client("t", rate=1000, burst=1000).get_json("http://x/a", use_cache=False)
    assert len(r.calls) == fetch.MAX_RETRIES


def test_post_json_once_never_retries(monkeypatch, no_sleep):
    """A retry after a timeout on a trading endpoint creates an ambiguous acceptance window."""
    r = Responder([TimeoutError("slow")])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    with pytest.raises(TimeoutError):
        Client("t", rate=1000, burst=1000).post_json_once("http://x/order", {"q": 1})
    assert len(r.calls) == 1 and not no_sleep


def test_cache_hit_costs_no_request(monkeypatch, tmp_path):
    r = Responder([{"v": 1}])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    c = Client("t", rate=1000, burst=1000, cache_dir=tmp_path)
    assert c.get_json("http://x/a", params={"k": 1}) == {"v": 1}
    assert c.get_json("http://x/a", params={"k": 1}) == {"v": 1}
    assert len(r.calls) == 1 and c.stats["cache_hits"] == 1


def test_cursor_pagination_stops_on_an_empty_page_or_no_cursor(monkeypatch):
    r = Responder([{"markets": [1, 2], "cursor": "c2"}, {"markets": [3], "cursor": None}])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", r)
    pages = list(Client("t", rate=1000, burst=1000).paginate_cursor(
        "http://x/m", {"limit": 2}, "markets", use_cache=False))
    assert pages == [[1, 2], [3]]
    assert "cursor=c2" in r.calls[1]

"""Repo-root pytest configuration.

WHY THIS IS AT THE ROOT, not in tests/
──────────────────────────────────────
Janus is not an installed package; modules are imported by path. Every test file used to carry its
own `sys.path.insert(0, ...parents[1])` prologue, which meant a file that forgot it -- as
tests/test_cloudbet_fixtures.py and tests/test_cloudbet_trading.py did on 2026-09-02 -- silently
collection-errored under a bare `pytest`, breaking the exact command
ops/ASHBURN_SPORTS_RUNBOOK.md prescribes on a fresh host. A root conftest puts the repo root on
sys.path for every test, once, so no file can forget.

No tests/__init__.py: that would force package semantics for no benefit.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Purity, enforced rather than asserted.

    kernel/venue_protocol.py declares normalize() PURE and nodes/fees/registry.py is a pure lookup, but
    nothing checked. A test that quietly reaches a venue is both slow and non-deterministic, and
    it turns a regression suite into an outage detector. Mark a test `@pytest.mark.network` to opt
    out; it is deselected by default via addopts in pyproject.toml.
    """
    if request.node.get_closest_marker("network"):
        return

    def _blocked(*a, **k):
        raise AssertionError(
            "network access from a test without @pytest.mark.network — "
            "use a fixture or a cassette instead")

    # Block CONNECTING OUT, not socket creation. Patching socket.socket itself was too blunt: an
    # asyncio event loop builds an internal self-pipe before it runs anything, so every async test
    # failed as if it had touched the network. `connect` and `create_connection` are the calls that
    # actually leave the machine; socketpair, which asyncio uses, does not.
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _guard(fn):
        def inner(self, address, *a, **k):
            host = address[0] if isinstance(address, tuple) else address
            if isinstance(host, str) and host in ("127.0.0.1", "::1", "localhost", ""):
                return fn(self, address, *a, **k)          # loopback is not the outside world
            return _blocked()
        return inner

    monkeypatch.setattr(socket.socket, "connect", _guard(real_connect), raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", _guard(real_connect_ex), raising=False)
    monkeypatch.setattr(socket, "create_connection", _blocked)

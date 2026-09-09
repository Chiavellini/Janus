"""L56 terminal-zero evidence: complete pages, exact projection, fail closed."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from kernel.execution_protocol import Position
from nodes.exec_polymarket.client import PyClobTransport
from nodes.exec_polymarket.position_evidence import (
    PAGE_LIMIT,
    capture,
    sha,
    terminal_zero_positions,
)


FUNDER = "0x" + "1" * 40
T0 = 1_800_000_000.0


def row(asset="101", **changes):
    value = dict(
        asset=asset,
        proxyWallet=FUNDER,
        conditionId="0x" + "2" * 64,
        size="10.166600",
        avgPrice="0.354098",
        currentValue="0",
        curPrice="0",
        redeemable=True,
        mergeable=False,
    )
    value.update(changes)
    return value


def evidence(rows, *, observed=T0):
    paging = dict(
        user=FUNDER,
        sizeThreshold=0,
        limit=PAGE_LIMIT,
        complete=True,
        pages=[dict(offset=0, count=len(rows), sha256=sha(rows))],
    )
    return capture(rows, paging, observed_utc=observed)


def projected(rows, *, observed=T0):
    return [
        Position("polymarket", r["asset"], "yes", float(r["size"]), float(r["avgPrice"]), observed)
        for r in rows
        if float(r["size"]) > 0
    ]


def test_terminal_zero_preserves_exact_physical_quantity_and_source():
    rows = [row()]
    positions = projected(rows)
    result = terminal_zero_positions(positions, evidence(rows), pass_started_utc=T0, now=T0 + 1)
    assert positions[0].contracts == 10.1666
    assert result["positions"][0]["contracts"] == 10.1666
    assert result["remnants"] == [{
        "asset": "101", "conditionId": "0x" + "2" * 64,
        "size": "10.166600", "row_sha256": sha(rows[0]),
    }]


@pytest.mark.parametrize("change", [
    {"redeemable": False},
    {"currentValue": "0.01"},
    {"curPrice": "0.01"},
    {"mergeable": True},
    {"active": True},
    {"resolved": False},
    {"umaResolutionStatus": "proposed"},
    {"proxyWallet": "0x" + "3" * 40},
    {"conditionId": "bad"},
    {"size": "NaN"},
])
def test_terminal_zero_rejects_every_ambiguous_or_valuable_holding(change):
    rows = [row(**change)]
    with pytest.raises((ValueError, ArithmeticError)):
        terminal_zero_positions(projected([row()]), evidence(rows), pass_started_utc=T0, now=T0 + 1)


def test_terminal_zero_rejects_stale_duplicate_missing_and_quantity_mismatch():
    rows = [row()]
    for raw, positions, start, now in (
        (rows, projected(rows), T0, T0 + 61),
        (rows + [deepcopy(rows[0])], projected(rows), T0, T0 + 1),
        (rows, [], T0, T0 + 1),
        (rows, [Position("polymarket", "101", "yes", 10.0, .35, T0)], T0, T0 + 1),
    ):
        with pytest.raises(ValueError):
            terminal_zero_positions(positions, evidence(raw), pass_started_utc=start, now=now)


class Pages:
    payloads = []
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def get_json(self, endpoint, *, params, use_cache):
        type(self).calls.append((endpoint, dict(params), use_cache))
        return type(self).payloads.pop(0)


def transport(monkeypatch, payloads):
    import kernel.fetch
    Pages.payloads, Pages.calls = list(payloads), []
    monkeypatch.setattr(kernel.fetch, "Client", Pages)
    monkeypatch.setenv("JANUS_PM_FUNDER", FUNDER)
    value = object.__new__(PyClobTransport)
    value.last_error = None
    return value


def test_real_transport_requires_and_records_terminal_short_page(monkeypatch):
    first = [{"asset": str(i)} for i in range(PAGE_LIMIT)]
    second = [{"asset": "last"}]
    value = transport(monkeypatch, [first, second])
    assert value.positions() == first + second
    assert [call[1]["offset"] for call in Pages.calls] == [0, PAGE_LIMIT]
    assert value.position_read_evidence == {
        "user": FUNDER,
        "sizeThreshold": 0,
        "limit": PAGE_LIMIT,
        "pages": [
            {"offset": 0, "count": PAGE_LIMIT, "sha256": sha(first)},
            {"offset": PAGE_LIMIT, "count": 1, "sha256": sha(second)},
        ],
        "complete": True,
    }


def test_real_transport_discards_malformed_or_unterminated_batches(monkeypatch):
    import nodes.exec_polymarket.position_evidence as pe
    value = transport(monkeypatch, [[{}] * (PAGE_LIMIT + 1)])
    assert value.positions() is None and value.position_read_evidence is None
    assert "malformed positions page" in value.last_error

    monkeypatch.setattr(pe, "MAX_OFFSET", PAGE_LIMIT)
    value = transport(monkeypatch, [[{}] * PAGE_LIMIT, [{}] * PAGE_LIMIT])
    assert value.positions() is None and value.position_read_evidence is None
    assert "pagination cap reached" in value.last_error

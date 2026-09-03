#!/usr/bin/env python3
"""The shard tool: the plan is printed, the transfer is sent only with --confirm, in centicents."""
from __future__ import annotations

from ops import kalshi_shards as ks


class FakeVenue:
    base_url = "https://api.elections.kalshi.com"

    def __init__(self, by_shard):
        self.by = by_shard
        self.client = self
        self.posts = []

    def balances_by_shard(self):
        return dict(self.by)

    def _headers(self, method, path):
        return {"KALSHI-ACCESS-KEY": "k"}

    def post_json_once(self, url, body, headers=None):
        self.posts.append((url, body))
        return {"transfer_id": "t-1"}


def test_move_plans_without_confirm_and_sends_centicents_with_it(capsys):
    v = FakeVenue({0: 61.24, 3: 0.0})
    assert ks.move(v, to=3, usd=20.0, source=0, confirm=False) == 0
    assert v.posts == [] and "plan only" in capsys.readouterr().out
    assert ks.move(v, to=3, usd=20.0, source=0, confirm=True) == 0
    url, body = v.posts[0]
    assert url.endswith("/trade-api/v2/portfolio/intra_exchange_instance_transfer")
    assert body == {"source": "event_contract", "destination": "event_contract", "amount": 200_000,
                    "source_exchange_shard": 0, "destination_exchange_shard": 3}
    assert "transfer_id t-1" in capsys.readouterr().out


def test_move_refuses_more_than_the_source_holds_or_a_non_positive_amount(capsys):
    v = FakeVenue({0: 10.0})
    assert ks.move(v, to=3, usd=20.0, source=0, confirm=True) == 2 and v.posts == []
    assert ks.move(v, to=3, usd=0.0, source=0, confirm=True) == 2 and v.posts == []

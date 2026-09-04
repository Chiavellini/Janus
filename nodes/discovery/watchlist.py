#!/usr/bin/env python3
"""Capture-only subscriptions: markets both venues list that the lane cannot yet co-list.

Tennis (KXATPMATCH / KXWTAMATCH on Kalshi; the `tennis` tag on Polymarket) has no ESPN anchor, so
the slate cannot pair its matches and no poller prices them. The frames are still the evidence
the anchor will be built and replayed against, so the lane subscribes to them anyway: a replica
per market on the shared sockets, captured with everything else, no pricing, no evaluation rows.

PURE selection over what the venues list, plus one register/unregister bookkeeping step the
supervisor calls each discovery period. Nothing here reads a price or writes a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from kernel.fetch import Client
from nodes.book_replica.replica import BookReplica
from nodes.discovery.census import GameEvent, in_window, kalshi_open_markets, pm_events
from nodes.venue_polymarket.books import PM_GAMMA


def kalshi_watch(series: list[str], cl: Client, *, now: float, ahead_h: float) -> list[tuple[str, str]]:
    """(ticker, series) for every open market of the series whose expected expiry is within the window."""
    out = []
    for s in series:
        for m in kalshi_open_markets(s, cl):
            exp = m.get("expected_expiration_time")
            try:
                t = datetime.fromisoformat(str(exp).replace("Z", "+00:00")).timestamp() if exp else None
            except ValueError:
                t = None
            if t is None or -3 * 3600 <= t - now <= (ahead_h + 6) * 3600:     # a match expires a few hours after it starts
                out.append((m["ticker"], s))
    return out


def pm_watch(tags: list[str | int], cl: Client, *, now: float, ahead_h: float) -> list[tuple[str, str]]:
    """(yes token, event slug) for every game market under the tags starting within the window."""
    return [(tok, e.event_id) for e in pm_watch_events(tags, cl, now=now, ahead_h=ahead_h) for tok in e.tokens]


def pm_watch_events(tags: list[str | int], cl: Client, *, now: float, ahead_h: float,
                    prefixes: tuple[str, ...] = ("atp-", "wta-")) -> list[GameEvent]:
    """The GameEvents behind pm_watch: slug, gameStartTime, participants, tokens. Kept (2026-09-04)
    so the supervisor can record each event's FIRST-SEEN start -- Polymarket rewrites
    gameStartTime in place on the same slug when a match moves, which is exactly the delay the
    tennis settlement wedge needs measured (nodes/watch_settle)."""
    out = []
    for tag in tags:
        evs = []
        for off in range(0, 600, 100):
            key = "tag_id" if isinstance(tag, int) or str(tag).isdigit() else "tag_slug"
            d = cl.get_json(f"{PM_GAMMA}/events", params={key: tag, "closed": "false", "limit": 100, "offset": off}, use_cache=False)
            if not d:
                break
            evs += d
            if len(d) < 100:
                break
        for e in pm_events(str(tag), evs):
            # The `tennis` tag carries ITF, challengers and doubles; the capture is for the tours the
            # registry knows. 2026-09-04: one ITF market's token got the whole socket dropped by
            # the venue every ~30 s (probed token by token), and ITF was 73 of 86 events that night.
            if prefixes and not e.event_id.startswith(prefixes):
                continue
            if in_window(e, now, back_h=3.0, ahead_h=ahead_h):
                out.append(e)
    return out


@dataclass
class Watchlist:
    """What is subscribed for capture only. `sync` registers what is new and unregisters what is gone."""
    kalshi: dict[str, str] = field(default_factory=dict)     # ticker -> series
    pm: dict[str, str] = field(default_factory=dict)         # token -> slug
    registered: int = 0
    unregistered: int = 0

    def sync(self, ks, ps, k_now: list[tuple[str, str]], p_now: list[tuple[str, str]]) -> tuple[int, int]:
        added = removed = 0
        nop = lambda _market_id, _now: None  # noqa: E731 -- capture only: no pricing on update
        for ticker, series in k_now:
            if ticker not in self.kalshi:
                ks.register(ticker, BookReplica(venue="kalshi", market_id=ticker, verification="stream"), "yes", on_update=nop)
                self.kalshi[ticker] = series; added += 1
        for ticker in [t for t in self.kalshi if t not in {x for x, _ in k_now}]:
            ks.unregister(ticker); del self.kalshi[ticker]; removed += 1
        for token, slug in p_now:
            if token not in self.pm:
                ps.register(token, BookReplica(venue="polymarket", market_id=token, verification="external"), on_update=nop)
                self.pm[token] = slug; added += 1
        for token in [t for t in self.pm if t not in {x for x, _ in p_now}]:
            ps.unregister(token); del self.pm[token]; removed += 1
        self.registered += added; self.unregistered += removed
        return added, removed

    def stats(self) -> dict:
        return {"kalshi": len(self.kalshi), "polymarket": len(self.pm), "registered": self.registered, "unregistered": self.unregistered}

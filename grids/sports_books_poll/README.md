# grids/sports_books_poll — multi-day, three-venue poller

`python3 -m grids.sports_books_poll.grid`

Composes `venue_kalshi` + `venue_polymarket` + **`venue_sxbet`** over a multi-day window — the
horizon `live_sports` does not cover (it sees live plus ±30 minutes only).

This is the closest thing in the repo to the intended three-venue system, and it already uses the
zero-rake CLOB. Fetches books **per game, back to back**, because an earlier version fetched all
Kalshi books then all PM books then priced, by which point 93 of 192 observations were stale.

Registered spec: `research/sports/2026-08-17_stage3-divergence/spec.yaml` (ledger L12).
Reads prices. Places nothing.

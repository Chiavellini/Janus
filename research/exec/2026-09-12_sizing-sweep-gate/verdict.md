# L79 verdict — the sizing sweep is gated on edge

## Paired offline benchmark (L78 instrument 2)

`research/infra/2026-09-12_loop-waste/measure.py`: the L51 capture prefix (10,000 Kalshi +
10,000 Polymarket frames, 2026-09-09 04Z) through a real `Supervisor` with LIMITED_LIVE sizing
(caps 30 / 25 / 500), the 234-event slate exported from the box for that hour, a stub executor.

| tree | median CPU s (3 runs) | evaluations | evaluation rows | sizing skipped | selections | rows digest | selections digest |
|---|---|---|---|---|---|---|---|
| before (`27c4549`) | 23.079 | 11,884 | 2,234 | 0 | 0 | 9f41923b8cf055a1 | 4f53cda18c2baa0c |
| after (L79) | 10.109 | 11,884 | 2,234 | 2,957 | 0 | 9f41923b8cf055a1 | 4f53cda18c2baa0c |

CPU −56 % with the recorded evaluation rows byte-identical and the selection set identical (none
in this prefix on either tree: the skip rule is exact by construction, and the grid tests cover an
edge epoch dispatching, the exit from an executable epoch being sized once for L74, and the
fixed-rung-miss case at gross 0.99 still sizing).

## What changed

- `Supervisor._worth_sizing`: an epoch whose cheapest priced cover has gross ≥ 1.0, or no priced
  cover, is not swept (counted in `Supervised.sizing_skipped`); an event whose last recorded
  decision selected something is swept once more.
- `choose_live_size`/`_risk_refusals`: one `day_notional_usd` read per decision.
- `_execute_sized`: fingerprints, sha and the audit ladder only when a row will be recorded.
- `_record`: the frontier report at most once per game per 5 s (every rung of an epoch shares it).
- `BookReplica.snapshot(checked=True)`: the poller's second gate per book is gone.

## Live confirmation

Pending the operator's paste; L82 repeats the py-spy sample on the same slate hour.

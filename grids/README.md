# grids — compositions of nodes

A grid wires nodes into a runnable pipeline. **Grids import nodes. Nodes never import grids, and a
grid never imports another grid** — that layering is what keeps failure attributable to one node.
(`live_stream` used to import discovery from `live_sports`; that code is `nodes/discovery` now.)

| Grid | Entry point | Status |
|---|---|---|
| `live_stream` | `python3 -m grids.live_stream.grid` | **The product.** Two shared sockets, one poller per live co-listed game, ~200–300 evaluations/s, change-gated rows. Runs under `com.janus.live-stream`. |
| `live_sports` | `python3 -m grids.live_sports.grid` | The REST lane it replaced (one sweep per ~17 s). `DISABLED` in the watchdog; kept for the complementary NO-ladder reference and offline comparison. |

Removed 2026-09-02 (recoverable from `2695129`): `scan_pure_arb` bypassed `nodes/cover` and wrote
into an immutable research directory; `sports_books_poll` passed `exhaustive=True` and so rejected
every cover since the proof token landed.

## What a grid may not do

Define a fee, a liquidity source, a status string, or a rule. Those live in `nodes/fees`,
`kernel/schema`, and `nodes/rules_exhaustive`. A grid that hardcodes one drifts from the pricer —
which is exactly how the Polymarket rate and the Kalshi multiplier were wrong for a month.

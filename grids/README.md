# grids — compositions of nodes

A grid wires nodes into a runnable pipeline. **Grids import nodes. Nodes never import grids, and a
grid never imports another grid** — that layering is what keeps failure attributable to one node.

| Grid | Entry point | Status |
|---|---|---|
| `live_sports` | `python3 -m grids.live_sports.grid` | The product. Kalshi + Polymarket, live and ±30 min pre-game. |
| `scan_pure_arb` | `python3 -m grids.scan_pure_arb.grid` | Bounded family scanner. A parallel implementation that bypasses `nodes/cover` — reconcile or retire. |
| `sports_books_poll` | `python3 -m grids.sports_books_poll.grid` | Multi-day, three-venue (Kalshi + PM + **SX Bet**) poller. Covers the horizon `live_sports` does not. |

## What is missing

There is no grid **runtime** yet. Each grid is currently a hand-written loop with its own error
handling, which is why one ESPN 500 kills all six leagues and why a failed sweep records
`error=None`. The runtime — typed `Fault` values that cross node boundaries instead of exceptions,
per-cell fan-out, and a run manifest — is the next build step. See the root `README.md`.

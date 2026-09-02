# Janus ↔ Kilos — the boundary contract

> Janus is a **read-only consumer** of Kilos. This file is the complete list of what it touches
> and the invariants that make that safe to leave in place. If Janus ever needs something not
> listed here, add a row — do not widen the surface silently.

## The rule

`~/Code/Kilos` runs **live launchd collectors writing multi-GB SQLite databases 24/7** and holds
**sacred forward eras** whose integrity is the basis of every registered result in that project.
Janus must not be able to damage either. Three mechanisms enforce that:

1. **No writes.** Janus opens every Kilos database with `mode=ro` in a URI connection string.
   There is no code path in Janus that opens a Kilos file for writing.
2. **No imports.** Janus imports no Kilos Python. Shared lineage is copied with a provenance
   header (`lib/stats.py`, `lib/venue_costs.py`), per `Kilos/DaC/SHARED_SERVICES.md` rule 1.
3. **No shared namespace.** Janus launchd jobs are `com.janus.*`. Janus credentials are `JANUS_*`.
   Nothing Janus runs can be mistaken for, or collide with, a Kilos job.

## Read surface

| Kilos artifact | Why Janus reads it | Access |
|---|---|---|
| `DaC/data/pm_data.db` | PM BTC quote/book history for the R1 anchor era | `mode=ro`, bounded queries |
| `DaC/data/pm_xa_data.db` | PM ETH/SOL quote/book history | `mode=ro`, bounded queries |
| `DaC/data/market_data.db` | Kalshi quotes, **post-2026-07-17 rotation only** | `mode=ro`, bounded queries |
| `/Volumes/Kilos/shards/market_data_20260717T043030Z.db` | Kalshi history **before** the rotation | `mode=ro`, frozen shard |
| `DaC/data/pm_exec/basis_divergence_ab.csv` | the existing forward divergence population | read |
| Kilos source tree | reference / copy-source only | read |

Janus writes **only** to `data -> /Volumes/Kilos/janus/` and to its own repo.

## Invariants — violating any of these is a stop-the-work event

1. **Never bulk-read a live Kilos DB while its collector is running.** A full-table scan stalls
   both processes; Kilos has a recorded incident from 2026-07-01. Always bound queries by
   timestamp range and `LIMIT`, and prefer the frozen shard for historical sweeps.
2. **The shard boundary is real and silent.** `market_data.db` was reset on 2026-07-17T04:30:30Z
   and prior history frozen to the shard. The schemas are **identical**, so a query for a
   pre-rotation era against the live DB returns ~0 rows with no error. Any Janus code reading
   pre-rotation Kalshi data must target the shard explicitly and assert non-empty.
3. **Never read a Kilos holdout era to answer a Janus question.** Kilos' sealed eras belong to
   Kilos' snooping budget. Janus keeps its **own** `snooping_ledger.md`, starting at zero spent
   looks, and does not inherit Kilos' row counts. Reusing spent Kilos evidence for a Janus
   *characterization* is fine and free; using it as a Janus *test look* is not.
4. **`kalshi_snapshots.yes_bid`/`yes_ask` are probabilities in [0,1], not cents.** A Kilos engine
   once priced a 30¢ ask as 0.3¢ and produced a fake +37.5¢/trade. Normalise on read.
5. **`kalshi_snapshots` spreads are exactly zero** (`bid == ask`) — entries from that table are
   effectively at mid. Any execution claim must come from `kalshi_orderbook_snapshots` instead.
6. **Do not disable, restart, or reconfigure a `com.kilos.*` job.** If a Kilos collector appears
   unhealthy, report it — do not intervene.
7. **`nice -n 19` any heavy Janus engine** while a Kilos live loop is trading. Compute contention
   starved the Kilos live runner's poll loop on 2026-07-21.

## Disk

Both projects share `/Volumes/Kilos` (931 GB, 863 GB free at Janus Phase 0). Kilos holds 31 GB of
frozen shards there. Janus' collector budget must leave headroom for Kilos' shard rotations —
measured Kalshi per-delta L1 runs **~4.8 GB/day/series**, so a 7-series hot tier without a cold
tier would consume the volume in ~25 days. Janus carries its own disk floor and alarm; see
`JANUS_CHECKLIST.md` Phase 2.

The **root disk is not an option**: ~18 GB free, 91% full.

## Coordination items

- **Kalshi MM-at-open** is registered in Kilos as its snooping row 20 with a forward clock started
  2026-07-21. Janus' R3 covers the same mechanism across 7 series. Settle who spends that
  evidence before either project reads it.
- If Janus' venue enumeration finds facts that correct Kilos' config (it already has: Kilos'
  `KALSHI_15M_SERIES` lists 5 series and no XRP/HYPE, but 15 exist), report them to Kilos rather
  than editing Kilos directly.

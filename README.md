# Janus — cross-venue Kalshi ↔ Polymarket engine

> Two faces, one event. Janus trades the **shared market corpus** between Kalshi and
> Polymarket: the same real-world question, listed on both venues, priced differently.

**Status: Phase 0 (scaffold). No data collected. No capital at risk. Nothing armed.**

---

## What this is

Kalshi and Polymarket both list continuously-recurring binary markets on the same underlyings.
Where they list the *same question over the same window*, the two prices form a **basis**. Janus
collects both venues' books, maps the pairs, and trades that basis — either directionally on
convergence, or as a two-legged position held to resolution.

The project exists because Kilos (`~/Code/Kilos`) already proved this works on **one instrument**
(BTC 15-minute) and the limiting factor turned out to be **capture, not signal**. Janus is the
venue-wide, multi-asset, properly-instrumented version.

## The corpus

Phase 1 targets the **exact-match intersection: 7 assets × 15-minute up/down**.

| Asset | Kalshi | Polymarket |
|---|---|---|
| BTC, ETH, SOL, XRP, DOGE, BNB, HYPE | `KX{ASSET}15M` — *"{ASSET} price up in next 15 mins?"* | `{asset}-updown-15m-{unix_ts}` — *"{Asset} Up or Down — H:MM-H:MM ET"* |

~672 paired windows/day. Windows on both venues align to the UTC 15-minute grid
(:00/:15/:30/:45), so pairs match on **implied close time**, not on ticker parsing.

**These are not the same contract.** Same question, two different oracles:

| | Kalshi | Polymarket |
|---|---|---|
| Settlement source | **BRTI** (CF Benchmarks) | **Chainlink** data stream |
| Reference level | `floor_strike`, set from the *prior window's close* | the *window open* |
| Fee | `ceil(0.07·p·(1−p))` per order, maker tier 0.0175 | `shares·0.07·p·(1−p)`, taker only |
| Tick / min size | 1¢ / 1 contract | 1¢ / 5 shares |

Kilos measured the construct mismatch at **10 bps mean strike-vs-spot offset** on BTC — small
against a 5 pp signal, but it is precisely why a "hedged" two-leg position is not actually flat.
Both legs can lose when the oracles disagree on direction.

Kalshi has **no 5-minute series** (its shortest cadence is `fifteen_min`), so Polymarket's 5m
markets are unpaired. They remain useful as a finer-grained instrument on the same asset — three
PM 5m windows nest inside one Kalshi 15m window — but they are not Phase-1 pairs.

## Relationship to Kilos

Janus is a **strictly read-only consumer** of Kilos. It never writes to `~/Code/Kilos`, never
imports Kilos Python, and runs under its own launchd namespace (`com.janus.*`). Shared lineage is
carried by **copying with a provenance header**, per `~/Code/Kilos/DaC/SHARED_SERVICES.md` rule 1.
See `SHARED_SERVICES.md` here for the exact read surface and the invariants.

## Layout

```
catalog/     venue-wide market enumeration + the pair map
collectors/  the dual-venue 7-asset collector (own DB, own launchd jobs)
lib/         stats.py, venue_costs.py — copied lineage, provenance-headed
exec/        signal runners, executors, risk shell  (Phase 4; disarmed)
research/    <track>/YYYY-MM-DD_<slug>/{spec.yaml,results.json,verdict.md}
specs/       immutable study specs
tests/       execution-safety battery
data ->      /Volumes/Kilos/janus/   (external volume; 863 GB free)
```

**Never write project data to the root disk** — it has ~18 GB free and is 91% full. All Janus data
lives on `/Volumes/Kilos` via the `data` symlink.

## Read order for a new session

1. `AGENTS.md` — the cold start
2. `state.yaml` — machine-readable current state
3. `VALIDATION_STATUS.md` — gate-by-gate distance to live
4. `JANUS_CHECKLIST.md` — phase history, pre-registered
5. `GATE_TO_LIVE.md` — the promotion sequence to real capital
6. `SHARED_SERVICES.md` — what Janus reads from Kilos, and the invariants

## Running things

```bash
# verify the cost pins still reproduce their anchors
python3 lib/venue_costs.py

# (Phase 1, not yet built)
python3 catalog/enumerate_kalshi.py --out data/catalog/
python3 catalog/enumerate_pm.py     --out data/catalog/
python3 catalog/build_pair_map.py   --out data/catalog/pairs.parquet
```

Every study writes to `research/<track>/YYYY-MM-DD_<slug>/` with a `spec.yaml` written **before**
the run. See `JANUS_CHECKLIST.md`.

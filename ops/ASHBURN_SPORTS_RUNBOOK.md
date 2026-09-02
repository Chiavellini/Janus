# Ashburn sports lane runbook

This is a deployment contract, not an instruction to start the EC2 instance. The current Ashburn
instance is stopped; starting it is billable and requires operator approval.

## Runtime shape

The coordinator should wake the worker before scheduled events, keep it hot through live play, and
drain it after the event and settlement checks complete. Overlapping events share one worker. The
worker must run the live sports collector in shadow mode; no order endpoint is enabled.

The first live lane is the existing schedule-first Kalshi/Polymarket collector. The Cloudbet
adapter is already integrated into the common payout/cover model, but Cloudbet acceptance and
trading-API reconciliation must be completed and validated before the three-venue lane is called
actionable.

## Host prerequisites

1. Attach and mount the durable data volume at `/Volumes/Kilos` (or provide the equivalent mount
   used by the Janus data symlink). Do not use the root volume for quote history.
2. Run `df -h / /Volumes/Kilos`; abort if either available space is below 2 GB.
3. Install the repository and Python runtime, then run the full test suite.
4. Provide credentials through the instance secret store or systemd environment injection. Never
   put a Cloudbet key in a checked-in `.env`, command line, cache, SQLite row, or research JSON.

## Cloudbet environment

```text
JANUS_CLOUDBET_API_KEY=<injected at runtime>
JANUS_CLOUDBET_FEED_TIER=trading
```

`trading` is required for a real-time feed. An affiliate key is explicitly treated as delayed and
cannot support a live-arbitrage claim. The Feed API is for discovery; an exact stake still needs a
successful Trading API acceptance response before the Cloudbet leg is executable.

## Shadow launch

```bash
cd /opt/janus
df -h / /Volumes/Kilos
python3 -m pytest -q
python3 collectors/live_sports_arb.py \
  --leagues mlb,nfl,nba,wnba,nhl,epl \
  --include-near \
  --db /Volumes/Kilos/janus/tuples/tuples.sqlite \
  --loop --period 10
```

The current collector writes only compact latest-state, material-change history, and aggregate
sweep rows. It does not retain unchanged full-universe snapshots and submits no orders.

## Promotion blockers

- exact Cloudbet Trading API acceptance request/response fixture and reconciliation;
- schedule-anchored Cloudbet event discovery for each configured competition;
- venue-pair settlement matrix for moneyline, spread, total, overtime, postponement, and voids;
- live latency/acceptance measurements from Ashburn;
- shadow evidence and the remaining Janus gates in `GATE_TO_LIVE.md`.


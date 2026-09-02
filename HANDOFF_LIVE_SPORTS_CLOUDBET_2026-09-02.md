# Janus live-sports low-latency build handoff

Date: 2026-09-02  
Repository: `/Users/bernardodelrio/Code/Janus`  
Mandate: research/shadow only; no live orders or capital are authorized.

## Initial project state

Janus began as a Kalshi ↔ Polymarket crypto/basis project. The repository still contains that
legacy scope, and `README.md`/the early portion of `state.yaml` still describe Phase 0 crypto
scaffolding. The sports track had already built a schedule spine, entity resolver, exact sports
matcher, fee model, cover enumerator, and a two-venue live scanner. The AWS Ashburn instance was
found stopped; it was not started.

The desired system is now narrower and different in emphasis: detect short-lived/live sports
mispricing across independent venues, prioritize live/newborn events, require at least 1% locked
return after all fees and executable depth, use Cloudbet as a sportsbook BACK leg when useful, and
use Ashburn for low-latency shadow monitoring before any promotion decision.

## Work completed

The current session added the Cloudbet normalization and safety boundary:

- Cloudbet decimal odds convert to a probability ask (`1 / decimal_odds`) and displayed stake limit
  converts to `$1-payout` contracts.
- Cloudbet contributes only BACK selections. No Cloudbet NO side is synthesized.
- Feed quotes are indicative. The shared cover screen refuses a Cloudbet leg until the exact stake
  is accepted by Cloudbet's Trading API.
- Cloudbet is registered as its own liquidity source and uses the embedded-vig fee model.
- A Cloudbet event/submarket can be joined only to an already schedule-anchored canonical outcome
  map. Unknown labels, extra outcomes (including an unexpected draw), and duplicate labels block.
- Cloudbet feed tier is explicit: affiliate feed is delayed; only a trading feed can be marked live.
- A three-venue sports study was preregistered before any Cloudbet API call.
- An Ashburn runbook documents storage, secret injection, shadow launch, and promotion blockers.
- The tuple store remains sparse/change-only: latest state plus material quote/opportunity changes and
  aggregate sweep rows, not repeated full 2,000-market snapshots.

Verification at handoff: `156 passed` via the full pytest suite.

## Files changed

- `lib/schema.py` — added Cloudbet's independent `liquidity_source`.
- `lib/fees/registry.py` — added the Cloudbet embedded-vig fee pin with unverified/acceptance caveats.
- `screen/cover.py` — added `Leg.executable` and a fail-closed rejection for unaccepted quotes.
- `lib/venues/__init__.py` — exposes the Cloudbet adapter/client.
- `snooping_ledger.md` — records row 2's completed bounded sports scan by appended note and registers
  row 3 for the three-venue study. Criteria remain immutable.

## Files created

- `lib/venues/cloudbet.py` — Feed API client, event/submarket parser, one-sided payout conversion,
  normalized `NormMarket`, registered adapter, and feed-tier handling.
- `collectors/cloudbet_sports.py` — pure exact-outcome join helper for schedule-anchored scanner data.
- `tests/test_cloudbet.py` — seven tests for conversion, acceptance gating, registry, normalization,
  headers, feed quality, and exact outcome joining.
- `research/sports/2026-09-01_three-venue-pure-arb/spec.yaml` — preregistered three-venue study.
- `ops/ASHBURN_SPORTS_RUNBOOK.md` — host and shadow-launch contract.
- `HANDOFF_LIVE_SPORTS_CLOUDBET_2026-09-02.md` — this handoff.

## Important files intentionally left untouched

- `collectors/live_sports_arb.py` — existing schedule-first live scanner remains Kalshi/Polymarket
  only. It was not falsely presented as Cloudbet end-to-end ready because Cloudbet acceptance and
  event discovery still need implementation.
- `collectors/tuple_store.py` — existing sparse storage is sufficient for the next integration pass.
- `match/sports_match.py`, `lib/entities/`, `lib/schedule/espn.py` — existing exact schedule/entity
  spine remains the source of truth; Cloudbet must plug into it rather than create a second matcher.
- `README.md` and the legacy sections of `state.yaml` — stale and should be rewritten only as a
  deliberate project-scope cleanup after the live-sports architecture is settled.
- AWS configuration and the Ashburn instance — no external state was changed; starting compute
  requires explicit operator approval.
- Any Cloudbet key — no credential was read, stored, or requested in chat.

## Source-of-truth documents

- `AGENTS.md` — read-only Kilos boundary, external-volume storage, preregistration, immutable
  criteria, unknown-rules BLOCK, liquidity-source deduplication, and no arming.
- `research/sports/2026-09-01_pure-arb-event-scan/spec.yaml` — current two-venue sports scan
  definition and 1% hurdle.
- `research/sports/2026-09-01_three-venue-pure-arb/spec.yaml` — Cloudbet study definition.
- `lib/schema.py`, `screen/cover.py`, `lib/fees/registry.py` — normalized contract, cover algebra,
  and fee source of truth.
- `match/sports_match.py`, `lib/entities/`, `lib/schedule/espn.py` — schedule-anchored exact match.
- Official Cloudbet API/rules documentation — Feed API authentication and tier behavior, Trading API
  acceptance, and settlement/cancellation caveats.

## Current state versus target

| Area | Current state | Target state |
|---|---|---|
| Exact event identity | Kalshi/PM schedule matcher works; Cloudbet join helper exists | Cloudbet discovery joins every configured competition to the same external schedule without title fuzzy matching |
| Quote conversion | Cloudbet feed parses to one-sided payout asks | Live feed polling plus accepted-odds/stake reconciliation |
| Pure-ARB economics | Shared `best_cover` supports 3 venues and 1% hurdle | End-to-end three-venue candidate generation, capacity, latency, and rejection metrics |
| Cloudbet execution | Not implemented; feed-only quote is non-executable | Trading API acceptance adapter, idempotency, timeout/pending/reject states, and reconciliation |
| Live collector | Kalshi + Polymarket only | Kalshi + Polymarket + Cloudbet in the same event loop |
| Settlement safety | Cloudbet defaults to unknown and blocks claims | Audited per-sport/market settlement matrix, including live baseball, soccer 3-way, OT, voids, suspension, and retirement |
| Storage | Sparse tuple DB works | Add Cloudbet quote/acceptance/reconciliation transitions without raw payload accumulation |
| Ashburn | Stopped instance; runbook only | Approved instance, durable data mount, secret injection, measured latency, supervised shadow process |
| Capital | Nothing armed | Still disarmed until all gates in `GATE_TO_LIVE.md` are met and operator explicitly promotes |

## Immediate next steps for the implementation agent

1. Read `AGENTS.md`, this handoff, both sports specs, `screen/cover.py`, `collectors/live_sports_arb.py`,
   `lib/venues/cloudbet.py`, and `collectors/tuple_store.py`.
2. Add frozen Cloudbet Feed API fixtures for MLB/NFL/NBA/EPL, including live status, a 3-way soccer
   market, suspended selections, and missing/unknown fields. Do not call the API without credentials
   or a newly registered research row if the work reads live data.
3. Implement Cloudbet event discovery keyed by configured competition keys and join it to ESPN's
   external schedule before appending legs to the existing live scanner.
4. Implement the Trading API acceptance client as a separate, fail-closed module. It must preserve
   `PENDING`, `REJECTED`, `PARTIAL/REDUCED`, `ACCEPTED`, and timeout/unknown states; never retry an
   unresolved acceptance automatically; and record accepted odds/stake for reconciliation.
5. Wire accepted Cloudbet legs into the existing `best_cover` path and `TupleStore`, with no raw API
   payload persistence and no order submission in the study lane.
6. Add latency instrumentation (request start/finish, quote skew, acceptance RTT, accepted-vs-displayed
   odds, and capacity) and run offline tests plus a credentialed shadow capture only after row 3 is
   properly registered.
7. Only after local verification, prepare the Ashburn service/timer. Do not start EC2, place bets, or
   alter Kilos without explicit authorization.

## Useful checks

```bash
cd /Users/bernardodelrio/Code/Janus
df -h / /Volumes/Kilos
python3 -m pytest -q
python3 collectors/live_sports_arb.py --self-test
```

## Implementation-owner update — 2026-09-02

The critical path listed above is now implemented offline and verified with **168 passing tests**.

Files added or materially changed in this pass:

- `lib/venues/cloudbet.py` — corrected parser for Cloudbet's documented proto-json map shape;
  preserves market/submarket keys, constructs stable Trading API line URLs because Feed selections
  have no selection ID, rejects unknown selection statuses, and uses structured `startTime` only.
- `tests/fixtures/cloudbet/` — frozen MLB, NFL, NBA, EPL three-way, and malformed/suspended feed
  payloads.
- `tests/test_cloudbet_fixtures.py` — parser golden tests, live/newborn/three-way coverage, exact
  ESPN schedule join, canonical home/away resolution, and accepted-leg store wiring.
- `collectors/cloudbet_sports.py` — pure competition-payload discovery joined to `ScheduledGame`
  by structured participants plus start time; accepted-only leg merge and sparse-store recording.
- `lib/venues/cloudbet_trading.py` — separate v4 Trading API boundary. Uses nested `selection` and
  `priceChange`, writes PENDING before a single non-retried POST, supports explicit reconciliation
  via `GET /pub/v4/bets?referenceIds=...`, maps ACCEPTED/lower accepted stake/rejected/pending to
  ACCEPTED/REDUCED/REJECTED/PENDING, and fail-closes transport ambiguity as TIMEOUT/UNKNOWN.
- `collectors/tuple_store.py` — durable `cloudbet_acceptances` journal with accepted odds/stake,
  request identity, state transitions, and no raw provider payloads.
- `lib/fetch.py` — added `post_json_once` so the non-idempotent Trading API boundary cannot inherit
  the generic retrying POST behavior.
- `lib/venues/__init__.py` — exposes the Cloudbet trading types.

The prior handoff statement that Trading API work was “not implemented” is superseded by this
section. The repository still intentionally has no end-to-end Cloudbet-enabled live loop, no
credentialed shadow capture, no settlement matrix, no AWS start/deployment, and no order
submission. Those remain blockers before any actionability or capital claim.

Cloudbet's current official Trading API is v4: v3 placement is superseded; v4 uses
`/pub/v4/bets/place/straight` and `GET /pub/v4/bets` reference-ID reconciliation. See the
official [v4 guide](https://www.cloudbet.com/en/blog/sports/how-to-place-bets-with-the-cloudbet-trading-api-straight-bets-and-accumulators).

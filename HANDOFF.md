# HANDOFF — 2026-09-03 ~07:00 UTC

For the next agent. Read this, then `BATTERY.md`, `NEXT.md`, `GATE_TO_LIVE.md` (last amendment) and the
plan at `/Users/bernardodelrio/.claude/plans/we-are-building-a-misty-stardust.md`. Do not re-derive
what is below; it was verified live tonight.

## Where the system is

- Main (`/Users/bernardodelrio/Code/Janus`) carries the v1 build; this branch
  (`claude/janus-arbitrage-trader-4e6d4d`, worktree under `.claude/worktrees/`) is merged into it
  fast-forward after every commit. `git -C /Users/bernardodelrio/Code/Janus log -1` says what the lane runs.
- `com.janus.live-stream` (launchd) runs main in SHADOW_LIVE with frame capture; `python3 ops/watchdog.py`
  should be quiet. Restart after a merge with `launchctl kickstart -k gui/$(id -u)/com.janus.live-stream`.
- All plan phases deliverable by code are done (P0a–P9, P8 partial: paper venue exists, adverse-move model
  is the measured one-tick slippage). Suite: `python3 -m pytest -q` from the tree root, green, no network.
- What only the operator can do is listed in `BATTERY.md`. The agent MUST NOT place orders, move funds,
  create accounts or enter credentials. Building and dry-running the tooling is fine; `--arm` is theirs.

## The Kalshi execution proof — exactly where we stopped

The operator (Bernardo) waived the Kalshi demo step (GATE amendment, verbatim quote) and agreed to tiny
fills on the production account. Tonight, in order:

1. `ops/arming_override.py` wrote `/Volumes/Kilos/janus/kill/arming_override.json`
   (LIMITED_LIVE, stake 5, max 10 contracts, day notional 20, expires 2026-09-04T06:33Z).
   **It pins runner sha `d8b680e`. Main has moved since, so the gate will refuse with
   OVERRIDE_RUNNER_SHA until the override is rewritten with `--force` at the current sha.**
2. Dry run of `ops/kalshi_live_proof.py --ticker KXMLBGAME-26SEP031235SFPIT-SF` passed
   (bid 0.40 / ask 0.41, KXMLBGAME multiplier 0.5, plan: resting 1 @ 0.31 then cancel, IOC 2 @ 0.41 = $0.82).
3. `--arm` was refused by risk at `LEAGUE_EXPOSURE: kxmlbgame: 0.00 + 0.82 > 0.00`: the script passed
   the series ticker where the ledger expects a league. **Nothing was sent** (refusal precedes any order;
   the account was only read for balance). Fixed: league derived from `KALSHI_GAME_SERIES`; the clearance
   now runs in the dry run too and releases its reservation as `dry_run`. Re-verified live: `mlb` clears,
   balance confirmed ($61.24 available), nothing sent.
4. Found while verifying: `ExposureLedger.reserve/release` never committed, so a reservation lived only
   in an uncommitted transaction (the journal's own commits masked it in the armed path). Fixed with
   commits and a restart test that uses a fresh connection.

### The operator's next commands (from the main checkout, credentials sourced)

```bash
set -a; . /Volumes/Kilos/janus/credentials/track_b.env; set +a
```
```bash
python3 ops/arming_override.py --force --mode LIMITED_LIVE --signed-by "Bernardo" --stake-usd 5 --max-contracts 10 --day-notional-usd 20 --statement "I approve tiny Kalshi fills on the production account to reconcile fees and settlement."
```
```bash
python3 ops/kalshi_live_proof.py --ticker KXMLBGAME-26SEP031235SFPIT-SF
```
then the same with `--arm`. The ticker is Giants (YES) in Giants at Pirates, 2026-09-03 12:35 ET; any
active two-sided `KXMLBGAME-*` market works. The proof file lands in `/Volumes/Kilos/janus/proofs/`.
After the game settles: `python3 ops/kalshi_live_proof.py --settle <that file>`.

### What the agent does after the armed run

- Read the proof JSON (never quote anything that looks like a key). Check: resting order went
  `resting` → `canceled`; IOC filled ≤ 2; `fee_ok` true (charged fee vs pinned curve at 0.5x); balance
  delta = stake + fee. If `fee_ok` is false the script latched `kill/live` — do NOT remove it; re-pin
  the curve first (`nodes/fees`), with the fill payload as the frozen fixture.
- After `--settle`: realized PnL matches the market result, the reservation is released with a reason,
  `capital_reservations` has no open row for `proof:<ticker>`.
- Then update `BATTERY.md` (row "Kalshi execution proof" → done, with date and proof file name) and
  `CHANGELOG.md`.

## After the proof, in order

1. **Polymarket wallet** (operator): fund a wallet; key in its own 600-mode file at
   `JANUS_PM_WALLET_KEY_PATH` (never in `track_b.env`); `JANUS_PM_FUNDER`, `JANUS_PM_SIGNATURE_TYPE`.
   `py_clob_client` 0.34.6 is installed in Homebrew site-packages. Then a PM proof script mirroring
   `ops/kalshi_live_proof.py` (FOK buy at best ask, min order 5 shares, statuses MATCHED→MINED→CONFIRMED).
2. **NFL** blocks at `EVIDENCE_UNMEASURED`: pre-register a ledger row for the NFL postponement (>48h)
   and cancellation rates, measure from ESPN/NFL schedule history, add to `nodes/settle_wedge/evidence.py`.
3. **Re-run L27 slippage** after NFL/NBA traffic (`research/sports/2026-09-03_kalshi-hedge-window-slippage/`).
4. **Ashburn** (P10) only on explicit approval to spend; another agent left uncommitted `infra/` work on main.
5. **Promotion** per GATE: shadow evidence n, faithfulness replay (zero mismatches, done thrice), then the
   two-venue $5 fills, then arming by override. Arming is never implied by a pass.

## Constraints that bit us, so you do not rediscover them

- Kalshi seq is per subscription sid; `update_subscription` reuses the sid; its `ok` reply consumes a seq.
- Polymarket `book.timestamp` is the last-change time, not send time; the clock monitor is fed by
  `price_change` only.
- KXMLBGAME fee multiplier is 0.5 (NFL/NHL 1.0); never a constant, read from the series payload.
- Kalshi v2 orders: side in YES terms (buy NO = ask at 1−price), fixed-point strings, `time_in_force`.
- Several agents share this worktree/stash: `git status` before trusting any summary; never bare `git stash`.
- `.claude` is excluded from `tests/test_meta.py`'s glob; the commit guard checks pytest's own exit code.
- All data on `/Volumes/Kilos/janus`; kill files under `kill/`; logs may contain identifiers — redact.

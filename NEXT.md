# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-04, early, on main. HANDOFF.md (2026-09-03 21:30 UTC) is the last full handoff;
this file says what happened after it and what is next.

## Done since the handoff

The lane was flapping and the watchdog could not see it: an `IllegalTransition` from a
mis-built state table tore both sockets down 5–20 times a minute for most of 2026-09-03. Fixed
(`nodes/opportunity`), plus: a record error can no longer reach a socket; the size frontier is
computed again (`frontier(proof=…)`); the lane honours the arming override's caps
(`clear(caps=…)`); the Polymarket REST reconciler applies on the event loop (its evaluations were
dying on sqlite's thread check, silently); the watchdog gained `SOCKET_FLAPPING`, `SOCKET_ERROR`
and `LANE_SILENT`. Ledger L36 (the cover-cost distribution, dwell-weighted, per league × quantity
× phase × flapping) is registered and has one run: BLOCKED_STALE holds most of the dwell in every
cell, `kalshi:HEARTBEAT_LOST` alone is 72% of in-play college football, all 19 profitable prints
are SUSPECT, and n for the paper row is 30 by declaration. **F3 is registered and the lane runs
`PAPER_EXECUTION`** (GATE step 7): paper venues, nothing leaves the machine.

## Now — what is left, and whose it is

**Yours, because I am not permitted to place orders, move money, or write the override:**
0. **Fund Kalshi's shard 3** (`python3 ops/kalshi_shards.py --show`, then
   `--move --to 3 --usd 20 --confirm`). The 2026-09-03 proof was refused `user_not_found` there.
1. **Rewrite the override at main's current sha** — the one on disk pins `07541fc` and main has
   moved twice since; `resolve_mode` refuses it. `python3 ops/arming_override.py --force --mode
   LIMITED_LIVE --signed-by "Bernardo" --stake-usd 5 --max-contracts 10 --day-notional-usd 20
   --statement "…names both venues…"`. **Nothing merges to main between this and the two
   `--settle` files.**
2. **The Kalshi proof**: `python3 ops/kalshi_live_proof.py --ticker <live KXMLBGAME-*>` dry, then
   `--arm`; `--settle <file>` after the game. The live tickers are in the store:
   `sqlite3 /Volumes/Kilos/janus/tuples/tuples.sqlite "select short_name, kalshi_event, pm_slug from events where league='mlb' and phase='in:co_listed'"`.
3. **The Polymarket proof**: `python3 ops/polymarket_live_proof.py --slug <pm_slug> --outcome "<label>"`
   dry, then `--arm`; `--settle <file>`. The wallet key file is in place; its funding is yours.
4. **IAM for the box**: carve `iam:PassRole` on `arn:aws:iam::986420598115:role/janus-box` out of
   the `janus-scope` deny (a `NotResource`) or delete the admin user's inline
   `EarshotDenyDirectBoxLaunch`; then `ops/box/launch.sh --go`, the SSM secrets
   (`python3 ops/box/creds.py --dry-run` lists them), and `ops/box/latency.py --host box` for L34.
5. **`nodes/risk/limits.toml`** has no per-league cap for cfb, epl, lal, bun, elc, el1 or ita, so
   the ledger refuses those at `LEAGUE_EXPOSURE` even on paper. Your numbers, your file.
6. **Push main.** Nothing has been pushed since `1479bd6`; the box's SSM sha pointer is stale.
7. Label the blind gold set `nodes/match_generic/gold/nonsports.csv` (ledger L31).

**Mine, in order:**
1. **The Kalshi heartbeat bound.** L36 says a quiet Kalshi market is called HEARTBEAT_LOST most of
   the time it is watched in-play (cfb) and pre-game (everywhere). A quiet market is not a stale
   one; the replica's heartbeat timeout needs the venue's actual keep-alive cadence measured (a
   descriptive row from captured frames) before the bound moves. Until then most of the lane's
   dwell is BLOCKED_STALE by our own rule.
2. After the armed proofs: `--check` both files, flip the BATTERY rows, append the fee
   reconciliation.
3. The `[clock] HALT` print is per poller (nineteen lines per event); make it one line, and
   measure how often the clock check actually flips.
4. Tennis rates (`tennis.walkover_rate` from the Sackmann results files; `delayed_gt7d_rate`
   needs a declared proxy or tennis stays blocked by name), then the replay option that trusts
   socket snapshots for the Polymarket side.
5. Three-way execution through a Polymarket NO token (a leg covering a SET of outcomes), the
   191 unresolved batch-2 soccer names, the football-data.org snapshotter (your token).
6. L28 census runs five more days; L36 re-runs after a clean day to see if n can be computed.

**Time:** F3 accrues under launchd. `python3 ops/watchdog.py` must stay quiet; `LANE_SILENT`,
`SOCKET_FLAPPING` and `SOCKET_ERROR` are the alarms that would have caught yesterday.

## Not now, deliberately

Any real order before the two proofs settle and the operator rewrites the override. Ashburn
before L34 is measured. `venue_cloudbet`, `venue_sxbet`, makers on Polymarket. Registering a
league by editing a flag. Moving the heartbeat bound before its cadence is measured.

## The question that actually matters

L36 answered the first cut: **with the sockets flapping, almost nothing was priced; with them
steady, MLB in-play cost sits at p50 1.030 and about 1% of the dwell is within a cent of
actionable.** The next cut is the same table over a clean day, and the heartbeat bound.

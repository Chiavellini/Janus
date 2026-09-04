# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-04 ~00:30 UTC, on main. HANDOFF.md (2026-09-03 21:30 UTC) is the last full
handoff; CHANGELOG.md carries everything since, dated.

## Where it stands

The lane runs `PAPER_EXECUTION` under ledger F3 on nine leagues. Since the handoff, four things
that were silently wrong are fixed and on main: the state table that flapped both sockets
(5–20 reconnects a minute all day), the frontier that never sized, the reconciler that lost its
evaluations on sqlite's thread check, and — found by L37 — the discovery pass that ran its HTTP
inside the event loop and blinded both sockets for 13% of every hour. The Kalshi fee pin was
half the venue's charge and is re-pinned from the operator's real fill; every recorded cover cost
before 2026-09-04 ~00:16Z understates a Kalshi taker leg by 0.035·P·(1−P) per contract.

**The Kalshi proof filled** (`proofs/kalshi_20260904T000452Z.json`: 2 taker at 0.35, then the
"cancelled" resting bid was hit as a maker at 0.25 — 3 contracts of KC YES, $0.95). It STOPped on
the fee pin, correctly; the cancel had gone to the wrong shard, also fixed. `--settle` runs itself
when the market resolves (a watcher in the agent's session; if it did not, run it). The
Polymarket proof has not run.

## Now — what is left, and whose it is

**Yours, because I cannot send an order or write the override:**
1. **Rewrite the override** — main moved twice since yours (`93a82a8` → `2d2a803`); `resolve_mode`
   refuses it. Same command as before, `--force`.
2. **A second Kalshi proof** so one file passes all six checks (the first fails `resting_cancelled`
   and `fee_ok` on record, both fixed since), then **the Polymarket proof**, dry run and `--arm`,
   any live two-sided game. Then `--settle` both. I run `--check`, flip BATTERY, close the changelog.
3. IAM for the box; `limits.toml` per-league caps for cfb and the soccer leagues; push main
   (nothing pushed since `1479bd6`, the box's SSM sha pointer is stale).
4. Label `nodes/match_generic/gold/nonsports.csv` (L31).

**Mine, in order:**
1. Re-run L37 on a clean hour after the discovery split, then re-run L36: with the sockets fed and
   fees right, the cover-cost table is the real first cut. Recompute n for F3 only to extend.
2. `--check` the settled Kalshi proof; BATTERY rows; the fee reconciliation note.
3. Tennis rates (`tennis.walkover_rate` from the Sackmann results files; `delayed_gt7d_rate`
   needs a declared proxy or tennis stays blocked by name), then the replay option that trusts
   socket snapshots for the Polymarket side.
4. Three-way execution through a Polymarket NO token; the 191 unresolved batch-2 soccer names;
   the football-data.org snapshotter (your token).
5. L28 census runs five more days.

**Time:** F3 accrues under launchd. `python3 ops/watchdog.py` must stay quiet; `LANE_SILENT`,
`SOCKET_FLAPPING` and `SOCKET_ERROR` are the alarms that would have caught 2026-09-03.

## Not now, deliberately

Any real order before the proofs settle and the override is rewritten. Ashburn before L34 is
measured. `venue_cloudbet`, `venue_sxbet`, makers on Polymarket. Registering a league by editing
a flag. Moving the 15 s heartbeat bound: L37 says the bound was never the problem.

## The question that actually matters

L36's first run was taken with the sockets starved and the fees at half. The honest answer to
"what does a cover cost" starts with the first clean day after 2026-09-04 00:25Z.

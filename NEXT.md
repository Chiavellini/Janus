# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-04 ~03:30 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story; HANDOFF.md (2026-09-03 21:30 UTC) the last full handoff.

## Where it stands

The lane runs `PAPER_EXECUTION` under ledger F3 on nine leagues, and tonight it became a
different machine: it prices a game once per 200 ms instead of on every delta (loop lag 0.1 s
where it was 10–85 s), the clock check says whether the host stalled or a clock stepped, the
Kalshi fee curve is pinned from the operator's real fills (taker and maker), three-way soccer
executes as two legs through the Polymarket NO token, tennis has its walkover rate and a forward
collector for its delay rate, and the Polymarket capture no longer subscribes the ITF token that
got the socket dropped every 30 s. The operator's decision stands: test trading only until L36
on clean data shows in-play actionable covers (GATE 2026-09-04 row).

**Not proved:** any edge. F3 is 0 of 30. All 19 profitable prints in history were closing books
under a broken socket with fees at half. The first honest data is tonight's.

## Now — what is left, and whose it is

**Yours, because I cannot send an order or write the override:**
1. **Rewrite the override** (main moved several times tonight; `resolve_mode` refuses the one on
   disk). Then **one clean Kalshi proof** and **the Polymarket proof** (never run), dry and `--arm`;
   `--settle` both. I run `--check`, flip BATTERY, close the changelog.
2. `nodes/risk/limits.toml`: per-league caps for cfb and the soccer leagues, or paper refuses them
   at `LEAGUE_EXPOSURE` (expected until you decide).
3. IAM for the box; push main (nothing pushed since `1479bd6`; the SSM sha is stale); the five
   secrets into SSM; `latency.py --host box` for L34.
4. Label `nodes/match_generic/gold/nonsports.csv` (L31).

**Mine, in order:**
1. Read the 10:10Z re-runs of L37 (clean hour 02:00–03:00Z) and L36 (three fee eras, stall
   windows); recompute F3's n only to extend.
2. Register F4 once `com.janus.watch-settle` (13:30 local) resolves its first rows; tennis then
   prices when the delay rate has a value.
3. Watch the first European soccer game under the new lane (the NO leg in `legs_json`, an
   `[exec]` or `LEAGUE_EXPOSURE` line): three-way execution is built, not yet seen live.
4. L38 over the first 24 h of `loop_lag_s`, beside L34 for the box decision.
5. Then the census's next competitions (UFC needs a card parser; KBO/NPB need citations and
   templates), the 191 unresolved batch-2 names, the football-data.org snapshotter (your token).

**Time:** F3 accrues under launchd. `python3 ops/watchdog.py` must stay quiet; `LANE_SILENT`,
`SOCKET_FLAPPING`, `SOCKET_ERROR` and `HALT STALL` are the alarms that would have caught
2026-09-03. Do not run the full test suite beside a live game on this Mac (ops/README.md).

## Not now, deliberately

Any real order before the proofs settle and the override is rewritten. Ashburn before L34 is
measured. `venue_cloudbet`, `venue_sxbet`, makers on Polymarket. Registering a league by editing a
flag. Widening the Polymarket capture back to ITF until the venue-side drop is understood.

## The question that actually matters

Unchanged: what does a cover cost, per competition and quantity, on clean data. The first clean
night is tonight; L36's 10:10Z run is the first honest cut, and the paper window is the test.

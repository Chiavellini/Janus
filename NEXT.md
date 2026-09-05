# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-05 ~08:30 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

The lane runs `PAPER_EXECUTION` under ledger **F5** (n = 37) on eleven leagues since the 07:53Z
restart: the nine of yesterday plus ATP and WTA. F3 stopped itself: its first unhedged paper leg
(MIL @ CIN, 35.82 of 100) was the coordinator sending a VWAP budget as a per-level IOC limit, and
the fix, the settlement of partial fills, the persisted execution transitions, pinned paper fees,
and two new watchdog alarms went in together. Soccer had never spawned a poller because Polymarket
reworded its description; V3 is registered and all ten co-listed soccer games spawned on the
restart. The lane died once, unseen, of a SIGBUS after 24 h; the host is the reason.

**What the event history says about edge.** 292 profitable prints on clean data. Under L36's label
all but one were SUSPECT; under L40's rule that can be false, **15 are clean** (12 college football
in play at a 2.5% median locked return, 3 MLB). Three paper covers have settled (+$5.00 gross,
+$0.75, and a PARTIAL at −$2.73 that the fix prevents). One print in twenty surviving a real check
is not nothing and is not edge. F5 (execution) and L27 (the gap to a fill) are what test it.

## Now — what is left, and whose it is

**Yours, because I cannot send an order or write the override:**
1. **Regenerate the override** — `nodes/risk/limits.toml` changed (paper caps, six events), so its
   `limits_sha` pin moved along with the runner sha:
   `python3 ops/arming_override.py --mode LIMITED_LIVE --signed-by "…" --statement "…Kalshi and Polymarket…" --stake-usd 5 --max-contracts 10 --day-notional-usd 20 --expires-hours 24 --force`.
   Then **one clean Kalshi proof** and **the first Polymarket proof**, dry then `--arm`, `--settle`
   both; I run `--check` and flip BATTERY.
2. **`FD_TOKEN`** (free, football-data.org) into the credentials env, then
   `launchctl bootstrap gui/$(id -u) ops/com.janus.watch-fd.plist` and move `watch_fd` from
   DISABLED to SLAS in `ops/watchdog.py`. F6 starts accruing; fl1/ere/por unblock at 100 matches.
3. IAM for the box; push main (nothing pushed since `1479bd6`); the five secrets into SSM;
   `latency.py --host box` for L34. L38 says the Mac pages to death under load.
4. Label `nodes/match_generic/gold/nonsports.csv` (1 / 0 per pair, blind to the key).

**Mine, in order:**
1. L27's re-run result into the ledger (running at 07:57Z); the slippage pin if it clears its bar.
2. Watch the first soccer cover under F5 (the `[exec]` line with a `:NO` leg), and the first tennis
   pollers; a tennis cover will almost certainly price out on the 3.6¢ delay reserve until F4's n
   grows — that is the design, say so if asked.
3. The census's 4th run today 20:00Z; when the rank is readable, UFC first (card-aware schedule,
   draw / no-contest rule, both texts, a measured no-contest rate), then KBO/NPB (the tie rate).
   `ops/harvest_templates.py --league nba` the day Kalshi lists basketball (shard move 2026-09-10).
4. A second L40 run after the weekend's soccer; if the clean count stays near 5%, the next question
   is what those 15 prints have in common (league, time in game, quantity) — a new row, not a look.
5. Tennis REPLAYABLE (capture the REST verification; spawn from `watch_events`).

**Time:** F5 accrues under launchd. `python3 ops/watchdog.py` shows one expected line for the next
24 h (`SIGNAL_EXIT … restarted since`); anything else is news. Do not run the full test suite beside
a live game on this Mac (ops/README.md).

## Not now, deliberately

Any real order before the proofs settle and the override is regenerated. Ashburn before L34 is
measured. Registering UFC/KBO/NPB before the census has four runs. Widening the Polymarket capture
back to ITF. Editing L36's or L40's criteria: a rule that disappoints gets a new row.

## The question that actually matters

Unchanged: what does a cover cost, per competition and quantity, on clean data — and now, more
sharply: are the fifteen clean prints real fills? F5 answers the second on paper; the Polymarket
proof is the first real one.

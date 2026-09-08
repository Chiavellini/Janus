# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-08 ~05:55 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

**The lane is LIMITED_LIVE on the Mexico box** (`i-0a8c073c72dcdae11`, `mx-central-1a`, a
c7g.medium: 1 vCPU) since 20:22Z; releases at 20:37, 20:50, 21:04, 21:34 and 22:01Z (`991afe7`:
the smallest size per market). Caps $12 per order, 10 contracts per leg, $250 a day, breaker $25;
the override pins the code tree and expires 2026-09-14. Every box command needs
`JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=i-0a8c073c72dcdae11`. Virginia is stopped.

**No real fill yet.** Twelve real orders today, all leg A on Polymarket: eleven refused by the CLOB
(ten FOK "couldn't be fully filled" on ARI @ KC, one $0.60 under the $1 minimum on RSO @ ELC) and
one `delayed` that vanished. Each taught a fix that is on the box: FAK with a one-tick pad, the $1
minimum in the cover, a 20 s backoff per game, the not-found status as final, leg A's own 6 s
window. The remaining self-inflicted miss was the loop itself: four stalls of 6-11 s were the
executions running on the socket loop, refusing the next cover CLOCK_UNHEALTHY (one across a 13 %
print). The fix (the machine in a worker thread, one flight at a time, store writes on the loop)
went out as `a0d6e11` (22:33Z); its first two real flights each broke something else and were fixed in `a3e888d` and `4b888eb` (CHANGELOG 2026-09-08). The box runs `4b888eb` since 01:33Z.

Balances: Kalshi shard 0 $167.86, shard 3 $102.43, Polymarket $304.07. L41 (per-league slippage)
is still streaming the frames (~4 h in, prints only at the end); MLB is at 1c meanwhile, the
rest at the pooled 4c. The census (L42) has not run: the watchdog says so.

## Now — what is left, and whose it is

**Yours (in order):**
1. **The position resolved itself.** Polymarket redeemed the Zandschulp shares: +$10.18 on $5.80
   paid (pUSD $308.32). Nothing to hedge. The row `789ad9b2` closes through the settlement pass
   once the lane runs again (its Polymarket order is now adopted and correct).
2. **Two no-trade rows** still block new covers on their (finished) matches; the script is fixed
   and on the box (re-asks the venue first, refuses on any trade):
   `bash ops/box/run.sh 'cd /opt/janus && sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box .venv/bin/python3 ops/reconcile_stuck_execution.py c4a9e645 --confirm'`
   and the same with `88eba02e`.
3. **The two unwind proofs (R4), when you are at the keyboard.** Each buys the venue's minimum
   and sells it straight back through the adapter and clearance the protection layer uses, then
   checks the venue's record (cents of spread). Dry run first, then `--arm`. Pick a live game
   market with a two-sided touch:
   `python3 ops/unwind_proof.py --venue kalshi --ticker KXMLBGAME-26SEP08...-XXX` then `--arm`
   `python3 ops/unwind_proof.py --venue polymarket --slug mlb-xxx-yyy-2026-09-08 --outcome "<team>"` then `--arm`
   (from `/Users/bernardodelrio/Code/Janus`, the box's credentials env sourced as for the earlier
   proofs; the override must name LIMITED_LIVE; `--check <proof file>` prints the verdict.)
4. **Do not lift the kill yet.** The plan's condition (`~/.claude/plans/snazzy-wiggling-badger.md`,
   A8): R1-R3 are staged on the box (`c43940d`, override re-signed); still owed: the guard clean for
   a night, both unwind proofs OK, R5 (unwind on) released, and a dated GATE row naming the layer
   ("a chase to $1.00 locked loss per execution and an automatic unwind are authorised"). I will
   say when it is met; the restart is then
   `bash ops/box/run.sh 'sudo -u janus rm -f /srv/janus/kill/live; systemctl restart janus-live-stream'`.

**Mine, in order:**
1. R5 once the proofs pass: `unwind_enabled = true`, `protect_auto = true`, the guard's
   `_protect_off_loop` re-run wired in the lane, the GATE row text for you, the arm statement.
2. The box's CPU ceiling (per-tier evaluation window; 210 pollers at 05:34Z).
3. L41's result into `SLIPPAGE_BY_LEAGUE`; the first three real covers reconciled by hand; the
   coverage queue (NBA/WNBA/NHL on 2026-09-10, the CFB alias rows, UFC/KBO/NPB); L42; the Mac
   lane's retirement; the key rotation and the read-only token after the pilot.

**Time:** `bash ops/box/status.sh` for the box; `python3 ops/watchdog.py` on the Mac. Stop the
bill: `aws ec2 stop-instances --region mx-central-1 --instance-ids i-0a8c073c72dcdae11`.

## Not now, deliberately

Any real order before the GATE row and the override exist. A cap above the row's without a
later dated row. Summing F5, F7 and F8. Editing any registered row's criteria. `ops/box/update.sh`
while an override is live (it invalidates the override; the lane then refuses to start live).

## The question that actually matters

Whether a real hedge lands at the size the venues give. Paper says yes 34 times; the two proofs
say the plumbing does; only F8's first three covers, reconciled to the cent, say it for the machine.

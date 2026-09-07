# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-07 ~22:40 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
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
is the commit after `991afe7`; it releases as soon as the suite is green.

Balances: Kalshi shard 0 $167.86, shard 3 $102.43, Polymarket $304.07. L41 (per-league slippage)
is still streaming the frames (~4 h in, prints only at the end); MLB is at 1c meanwhile, the
rest at the pooled 4c. The census (L42) has not run: the watchdog says so.

## Now — what is left, and whose it is

**Yours:** nothing blocking. Later: a read-only repo token in SSM; rotate the Polymarket signer key
after the pilot.

**Mine, in order:**
1. Release the off-loop execution, then watch the box through Monday Night Football (~00:15Z)
   and the ITF/Challenger evening: `[exec]` lines with `first=` above zero, no `HALT STALL`, no
   `IN_FLIGHT` refusals piling up. The first three real covers reconciled by hand before the
   fourth (fills at the venue's size, fees at the pin, balances to the cent, reservations released).
2. L41's result into `SLIPPAGE_BY_LEAGUE` (its rule: per-league p95 at 3 s, q = 25), ledger line,
   release.
3. Latency, from `ops/latency_report.py` once covers exist: the discovery pass's GIL share on 1
   vCPU (a subprocess, or a c7g.large), balances cached off the path, the pooled Kalshi client.
4. The non-sports census (L42) build; the CFB alias rows the near-miss lines name; coverage in
   census order.
5. Retire the Mac lane after 48 h of the box without SIGNAL_EXIT.

**Time:** `bash ops/box/status.sh` for the box; `python3 ops/watchdog.py` on the Mac. Stop the
bill: `aws ec2 stop-instances --region mx-central-1 --instance-ids i-0a8c073c72dcdae11`.

## Not now, deliberately

Any real order before the GATE row and the override exist. A cap above the row's without a
later dated row. Summing F5, F7 and F8. Editing any registered row's criteria. `ops/box/update.sh`
while an override is live (it invalidates the override; the lane then refuses to start live).

## The question that actually matters

Whether a real hedge lands at the size the venues give. Paper says yes 34 times; the two proofs
say the plumbing does; only F8's first three covers, reconciled to the cent, say it for the machine.

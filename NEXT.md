# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-07 ~06:15 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

**GATE_TO_LIVE step 8 is complete on both venues.** Kalshi proof: 2 @ 0.78, fee at the pin, settled
+$0.42, 7 of 7. Polymarket proof, the venue's first real order: 5.13 @ 0.38 (V2 fills by notional),
fee at the pin read from the balance, settled +$3.18, 7 of 7. On the way the Polymarket adapter moved
to CLOB V2 / pUSD / signature type 3 (the operator's account is a Deposit Wallet); the V1 client had
read the account as empty.

**Two paper series run.** F5 on the Mac: 34 cleared, 33 hedged, 0 unhedged, +$44.73 paper, n = 37.
F7 on the Ashburn box (`i-0c86891ee306de0b8`, launched 05:45Z, lane started 06:04Z):
the same lane, its own data root and clock, n = 37, reported apart from F5 and never summed.

**L34 says OBSERVATION_HOST.** Same-hour runs: the box reaches Kalshi in 51 ms p50 (Mac 184) and
the CLOB in 184 ms (Mac 309; the bar of half was 154, not met; the CLOB answers 200 from the box).
The box is the paper pilot's host; execution from it waits on a later row.

## Now — what is left, and whose it is

**Yours:**
1. **The cutover decision, in 48 h.** If the box shows no `SIGNAL_EXIT` by 2026-09-09 06:00Z, say
   "retire the Mac lane": I stop `com.janus.live-stream` on the Mac, close F5 by count, and the
   Mac keeps only its three daily jobs. Until then both series accrue.
2. **The GATE row.** When F5 or F7 reaches 37, I write the numbers up; moving any lane to
   LIMITED_LIVE needs your dated sentence in GATE_TO_LIVE's amendment log.
3. **Replace the repo token in SSM** with a read-only fine-grained token (`/janus/repo/token` is
   your GitHub login's token today). **Rotate the Polymarket signer key** after the pilot: it is in
   this chat's transcript and in the Mac's zsh history (a flushed prompt, 2026-09-07).
4. Optional: label `nodes/match_generic/gold/nonsports.csv` (L31).

**Mine, in order:**
1. Watch the box's first game-day (the European evening and MLB tonight): `[spawn]` lines, covers
   clearing, settlements, and the loop lag under load, on a host that does not page.
2. The stratified slippage row (L41): per league, clean windows only, time-weighted, at the walked
   depth. L27's pooled 4¢ is the reserve until it runs; whether MLB/cfb in play deserve 1¢ or 4¢ is
   what decides whether the paper returns survive execution.
3. A shared kill switch across hosts (an SSM `/janus/kill/*` the box's watchdog polls); today
   stopping the box is `systemctl stop janus-live-stream` or `aws ec2 stop-instances`.
4. The census's 7th run lands 2026-09-08 20:00Z; then UFC / KBO / NPB in rank order.

**Time:** two lanes accrue under launchd and systemd. `python3 ops/watchdog.py` on the Mac; on the
box `aws ssm send-command --instance-ids i-0c86891ee306de0b8 --document-name AWS-RunShellScript
--parameters 'commands=["sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box /opt/janus/.venv/bin/python3 /opt/janus/ops/watchdog.py"]'`.
Stop the bill any time: `aws ec2 stop-instances --region us-east-1 --instance-ids i-0c86891ee306de0b8`.

## Not now, deliberately

Any real order beyond the two proofs. An execution override on the box (L34 said no). Summing F5
and F7. Editing any registered row's criteria. Relaunching the box without re-pointing
`/janus/repo/sha` (cloud-init checks out that sha).

## The question that actually matters

Are the paper covers real fills? Both venues now fill tiny real orders at the priced book with fees
at the pin; F5/F7 say the prints hedge on paper at +3-7%; L41 says what the hedge really costs.
Those three together are the pilot's answer, and the last one is the next thing built.

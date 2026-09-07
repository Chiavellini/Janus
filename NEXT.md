# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-07 ~18:25 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

**The box is LIMITED_LIVE since 16:18Z (F8) on `5a07e4e`.** At 17:47Z, LAA @ BOS in play, it
priced its first actionable covers: 25 and 100 contracts at a 4.6 % locked return, refused
`CAP_STAKE` by the override ($23.25 and $94 against the $12 cap); the same books at 5 contracts
stay under the $0.10 profit floor because the pooled 4c slippage reserve takes $0.20 of the
$0.22. Every refusal first fetched both venues' balances on the event loop and stalled it 5.6 s.
Fixed on main (caps and floor refused before any round trip); the box has it after the release.

**Main (`b290bb3`+) carries the day's second wave**, none of it on the box yet: the coverage
audit (every unpaired game names its missing venue side; `[unpaired]` / `[near-miss]` lines;
`ops/coverage_report.py`; `COVERAGE_GAP`), tennis by the venues' rosters (live player entities,
Kalshi tennis resolved by full name, Challenger series, the ITF league enabled with its two
reviewed templates: 70 co-listed ITF matches today), the 48 h pairing universe, the Kalshi cursor,
the code-tree pin (`kernel/code_sha`), the live override check (`[arm] STALE`, `ARM_STALE`),
`OVERRIDE_EXPIRING` / `OVERRIDE_STALE`, the cross-host kill (`/janus/kill/*` in SSM), and
`ops/box/release.sh`, the operator's one daily paste.

**Two paper series** (F5 Mac on main; the box's F7 ended when F8 started). L41 runs (3 h+).

## Now — what is left, and whose it is

**Yours:**
1. **The release** (one paste, from `/Users/bernardodelrio/Code/Janus` after `git pull`):
   `bash ops/box/release.sh <sha>` in the quiet hour, or `--now` tonight: the lane holds no
   position and its refusals are what stalls it. The script refuses while a co-listed game is in
   play unless `--now`. After it, the override pins the executable tree, so a docs commit no longer
   needs a re-sign.
2. **The stake cap.** $12 per order admits only the 5-contract size, which the 4c reserve holds
   under the $0.10 floor; L41's per-league reserve is what frees it. A $25 cap would have admitted
   tonight's 25-contract covers ($23.25). That is a new dated GATE row if you want it; the agent
   does not raise caps.
3. Later: a read-only repo token in SSM; rotate the Polymarket signer key after the pilot.

**Mine, in order:**
1. Today's games on both hosts: `[discovery]` for ita, `[spawn]` for tennis, MLB and Monday-night
   NFL; the first priced tennis and Serie A rows; refusals by code. The 2-hourly box check.
2. L41 (running again, unbuffered, ~50 min): per-league slippage into `SLIPPAGE_BY_LEAGUE`, the
   frontier and `_execute` reading the league's value, L27's 4c as the fallback.
3. When the override exists: the first three real covers reconciled by hand before the fourth
   (fills at the venue's size, fees at the pin, balances to the cent, reservations released).
4. Coverage in census order once the 7th run lands (2026-09-08): CFL, esports, Argentine Primera,
   UFC, KBO/NPB; each its own registry row, cited rule, two templates, measured rate, certify.
5. The cross-host kill switch before any cap rises.

**Time:** `python3 ops/watchdog.py` on the Mac; `bash ops/box/status.sh` for the box. Stop the
bill: `aws ec2 stop-instances --region us-east-1 --instance-ids i-0c86891ee306de0b8`.

## Not now, deliberately

Any real order before the GATE row and the override exist. A cap above the row's without a
later dated row. Summing F5, F7 and F8. Editing any registered row's criteria. `ops/box/update.sh`
while an override is live (it invalidates the override; the lane then refuses to start live).

## The question that actually matters

Whether a real hedge lands at the size the venues give. Paper says yes 34 times; the two proofs
say the plumbing does; only F8's first three covers, reconciled to the cent, say it for the machine.

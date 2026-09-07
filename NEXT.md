# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-07 ~20:00 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

**The box cannot place Polymarket orders.** Its first real order (18:45Z, ATL @ PHI, 5 contracts,
every check passed) was refused by the CLOB with HTTP 403 "Trading restricted in your region": AWS
Virginia is a US address, and Polymarket geoblocks order entry from it (reads were always fine,
which is what L34 saw). No order was placed and no money moved. The proofs succeeded from the
Mac, whose egress is Mexico City. Until the Polymarket leg runs from a permitted jurisdiction the
box is a paper host in fact, whatever its mode says. Main now rejects such answers outright and
latches the venue (`VENUE_GEOBLOCKED`); the box still runs `5a07e4e` and will hold a reservation
per attempt until the release.

**Earlier tonight** the box priced its first actionable covers (LAA @ BOS, CEL @ GET, NYM @ MIA,
ATL @ PHI at 25 and 100 contracts, 4–5 % locked) and refused them at the $12 cap; the operator's
rule is the smallest executable size, so a 10-contract rung was added and L41's per-league reserve
(still running, 4.5 h) is what frees the 5-contract rung. Funded: Kalshi shard 0 $247.86, shard 3
(tennis, Challenger, ITF) $22.43, Polymarket $304 pUSD.

**Main (`f019321`+)** carries the day's work: the coverage audit, tennis by the venues' rosters
with Challenger and ITF (70 co-listed ITF matches today), the 48 h universe, the Kalshi cursor, the
code-tree pin, the live override check, the cross-host kill, `release.sh` refusing only on money in
motion, the 10-contract rung, L31 scored (every rejection stratum at precision 1.0; zero
equivalents among the 18 survivors), and the geoblock handling.

## Now — what is left, and whose it is

**Yours (the Mexico move, in the runbook's order, `ops/ASHBURN_SPORTS_RUNBOOK.md` "Mexico"):**
1. IAM: `aws iam put-role-policy --role-name janus-box --policy-name janus-box --policy-document file://infra/iam/janus-box-policy.json`, and the agent policy (`janus-scope`) from `infra/iam/janus-agent-policy.json`.
2. Parameters: `bash ops/box/copy_params.sh mx-central-1 --go`, then `/janus/repo/sha` in that region to main's sha.
3. Launch: `JANUS_BOX_REGION=mx-central-1 bash ops/box/launch.sh --go`; then `export JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=<id>` in every shell.
4. After bootstrap: L34 from Mexico (I append the verdict), the lane in paper, then the two arming pastes.
5. Stop Virginia when Mexico runs. Kalshi shard 3 (tennis) still $22.43: `python3 ops/kalshi_shards.py --move --to 3 --usd 80 --confirm` if wanted.

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

# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-07 ~20:40 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

**The lane is LIMITED_LIVE on the Mexico box** (`i-0a8c073c72dcdae11`, `mx-central-1a`) since
20:22Z, on `eb70b11` since 20:37Z (caps $12 per order, 10 contracts per leg, $250 a day; the smallest executable size, never bigger); every box command needs `JANUS_BOX_REGION=mx-central-1
JANUS_BOX_ID=i-0a8c073c72dcdae11`. Virginia is stopped (its first real order was geoblocked by the
CLOB; its data volume keeps the record). L34 from Mexico: Kalshi 92 ms, CLOB 214 ms (the Mac 170 /
273). 55 co-listed games at the switch, 17 in play; ITF and Challenger included. Funded: Kalshi
shard 0 $248, shard 3 $22, Polymarket $304. The first real order from Mexico is the proof the
geoblock is behind us; the first three covers are reconciled by hand before the fourth.

## Now — what is left, and whose it is

**Yours:** Kalshi shard 3 (tennis) still $22.43: `python3 ops/kalshi_shards.py --move --to 3 --usd 80 --confirm`. Later: a read-only repo token in SSM (both regions); rotate the Polymarket signer key after the pilot.

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

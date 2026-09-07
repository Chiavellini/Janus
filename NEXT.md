# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-07 ~07:10 UTC, on main. CHECKLIST.md is the state list; CHANGELOG.md the dated
story.

## Where it stands

**The operator's decision of 2026-09-07 is small real fills on every live event, from the box.**
Everything the machine can do for that without a signature is done: F8 is registered (spec and
ledger row, PENDING), `limits.toml` carries the pilot's $0.10 profit floor, the box has the code,
the credentials and the collateral, and the two pastes that arm it are written and unrun.

**Three refusals of good books were found and fixed today** (CHANGELOG 2026-09-07, second
entry). Every tennis match that went live after a lane start never synced its Kalshi replica;
every Kalshi book quiet for 5 s on a live socket was called STALE (a third of a million cfb
evaluations in F5); Serie A pointed at Gamma's futures tag and produced nothing for four days
with no reason printed. All three shipped in `ca2d36d`; both lanes restarted on it at 07:00Z.
Whether tennis and Serie A now price is **NOT PROVED until today's games**: the Mac and the box
both watch, and the next `[spawn]` / `[discovery]` lines say.

**Two paper series run** (F5 on the Mac, F7 on the box), each with an era note at the restart.
Not a current bug: the 3,435 `IllegalTransition` reconnects in the Mac's log are from 2026-09-03.

## Now — what is left, and whose it is

**Yours (three pastes, in this order, after reading the draft):**
1. **The GATE row**: `research/sports/2026-09-07_limited-live-f8-box/GATE_ROW_DRAFT.md`. Approve
   or amend the caps ($12 per order, 25 contracts, $60 a day, breaker $25); it goes into
   `GATE_TO_LIVE.md`'s amendment log with the date, in your words.
2. **The override on the box** (your signature; it pins the box's sha and `limits.toml`):
   `bash ops/box/write_override.sh "I approve live trading at small size on all live events the lane covers, from the box, at \$12 per order, 25 contracts and \$60 a day, with the realized-loss breaker at \$25."`
3. **The mode switch**: `bash ops/box/mode.sh LIMITED_LIVE`. The lane refuses the mode until the
   override matches; `bash ops/box/mode.sh PAPER_EXECUTION` is the way back at any time.
Later: replace `/janus/repo/token` with a read-only token; rotate the Polymarket signer key after
the pilot (it is in this chat's transcript and the Mac's zsh history).

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

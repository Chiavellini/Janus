# L56 exact historical overfill acknowledgement — local implementation PASS

Registered before tests in `overfill_spec.yaml`, `flag_resolution_followup.yaml`,
`legacy_persistence_followup.yaml`, and `overfill_export_followup.yaml`. This result
covers overfill acknowledgements/export and the guard's legacy lock classification.
The distinct exact flag211 incident acknowledgement is another agent's work and is
not declared complete by this note.

## Implemented boundary

- Append-only acknowledgement history and explicit operator/dry-digest confirmation
  bind the exact database path, unique owning execution, full order/owned-leg rows,
  RECONCILED/released state, full settlement and released capital reservation,
  source commit/tree/blob membership and exact historical alarm rows.
- No order, fill, position, execution, P&L, reservation or kill field is rewritten by
  this mechanism. Zero-fill terminal rejected/unfilled legs may have null journal
  cash mapped to the existing settlement serializer's exact zero. Positive-fill
  cash remains exact. An unrelated no-order execution is not an owner and does not
  prevent acknowledgement.
- Runtime revalidation includes previously acknowledged IDs even if the order is
  now missing, its mode changed, or its requested quantity no longer looks
  overfilled. Any changed/corrupt/revoked record relatches and flags. No blanket
  released-execution skip exists.
- Only a complete error-free two-venue fill/position pass, with no current orphan,
  mismatch, protection requirement or fee STOP, may resolve exact acknowledged
  overfill alarm IDs. Evidence repeats under the same BEGIN IMMEDIATE writer lock
  as the exact-ID flag coverage check. A snapshot race refuses resolution and
  relatches after the transaction. Unknown/new/equal-timestamp alarms remain.
  This is alarm-specific resolution, not global entry readiness. Kill is untouched.
- `--prepare` opens the target read-only, accepts an explicit CID/source/flag-ID/
  reason proposal, requires the complete exact real-overfill candidate set and
  coverage of every active overfill alarm, and exclusively creates a new manifest.
  Neither preparation nor dry confirmation creates database rows. Confirmation
  is separate and refuses a stale snapshot or history head.
- A fallback lock for a legacy immediate order rolls back and reports generic
  `ORDER_PERSISTENCE_FAILED` with independent kill, never calling the post-only
  hook without an exact marker. Genuine maker-marker errors retain that hook.
  The generic failure has its own watchdog alarm. Historical flag211 is not cleared.

## Evidence and tests

The fixtures freeze exact local data and synthetic Git membership; they prove
mechanics, not the truth of a real venue's settlement source. Actual target source
content remains operator-attested and must be independently checked against the
archived venue cash/redemption evidence before confirmation. The generic code does
not claim to parse external closure semantics independently.

First focused run: 36 passed. Final focused overfill/export/race/legacy-label/health
suite: **53 passed**. Final integrated offline execution, execute, Polymarket and
risk tests: **526 passed in 3.95 seconds**. `git diff --check` passed.

Adversarial coverage includes changed request/fill/venue identity/mode/price/fee,
open/pending/released states, deleted order/reservation, changed settlement, source
content/commit corruption with recomputed outer hashes, wrong confirmation/target,
append-only enforcement/revocation, exact flag ID/type/time attribution, incomplete
scans, missing venues/positions, second overfill, new/same-timestamp unbound alarm,
stale prepare/confirm, exporter mismatch/duplicate/overwrite, and persistence lock
with and without the post-only marker table.

No deployment, account/venue/box mutation, rearm, cap change, kill clearing or new
statistical look occurred. Expected EV effect is neutral on trade economics; this
only prevents exactly reviewed settled historical evidence being classified as
fresh overfill risk. No forward-profit or NFL-readiness claim is made.

## Appended — exact cover redemption sources

Under `cover_redemption_sources_followup.yaml`, proposal flags201/202 now bind
page0004 from commit `df911419de7947ed35cd41b1191f8107fb36bf9d` in addition to the
page0003 BUY source. SHA256 is
`3e0ba1e395ed3737b945246f955803c7da19d345b4fea32195f071786cf1c982`.
Same-token terminal evidence is exact: SF BUY/REDEEM size5.241936 has redemption
cash5.241936; Cubs BUY/REDEEM size7.769231 has redemption cash0 (losing PM leg).
The initial diagnostic incorrectly required redemption cash equal shares for both
and failed on Cubs; the corrected check asserts each recorded cash value rather
than inferring a payout. No accounting snapshot or P&L was changed.

All five CID/flag mappings and eight source references passed offline membership
and hash checks; both same-token quantity/cash comparisons passed. Runbook shell
syntax and `git diff --check` passed. No commit or live action occurred.

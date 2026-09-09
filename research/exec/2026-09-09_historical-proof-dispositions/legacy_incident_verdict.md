# L56 legacy adapter label and exact historical incident: local PASS

No live/venue/box actions, deployment, rearm, cap, kill clearing, original incident
or accounting edits were performed by the descriptive work summarized here.

## Evidence and semantics

The separate operator acknowledgement binds exact flag211 and PM violation1 for
legacy IOC40797bee0f17449ca1e4fa3840125232. Read-only preparation dynamically
exports the full settled order/execution/owned-leg/reservation snapshot from the
explicit target database; this subtask did not read or mutate that database.
The old guard's unconditional persistence hook is Git-bound to commit
f51620e53cdbafe9b4584bbc33d59a9d8fca19eb, `nodes/execute/guard.py` lines292–301,
source SHA2568c7cdfbf3408be50d31a74538d67b2b2125a1bc80b1511ef20cdafd10e7fad71.
The operator attributes the exact incident to that documented mechanism; the code
excerpt is not independent venue cash/closure proof.

The proposal is source-hydrated and works without Git on archive-only releases:
`legacy_incident_proposal.json`, file SHA256
33bca53aee8ec5ed592b13dd368dfd1811e015c3117c2e9f5679534ca5e71ac3.
The immutable confirmation envelope binds exact DB, manifest, operator and linear
predecessor. Any source/identity/state/confirmation mismatch or revocation blocks.
Confirmation appends only; it does not resolve flags.

Fresh complete guard reads must prove both venues present, no errors/orphans/
mismatches/failing findings, all executions and
reservations released, no open/cash-pending orders and empty maker/admission
history. Kalshi must be exactly empty. Polymarket physical token quantities remain
visible and can satisfy this narrow incident-resolution gate only when the same
complete, terminal-page-bounded read proves every positive token is strictly
`redeemable=true`, `currentValue=0`, `curPrice=0`, account-bound, unique, fresh,
and free of contradictory active/resolution fields. The raw batch, pagination,
hashes and full physical projection are retained in the exact resolution marker;
no inventory, cash or P&L row is edited. Missing, stale, malformed, duplicate,
quantity-mismatched, valuable or ambiguous evidence blocks. The exact Maximus
target is zero-unhedged. Released directional rows may
retain historical unhedged amounts: parent confirmed789ad9b2 holds10.175439 and
ffe02ded holds0.0019359999999997157 after release. Their historical accounting is
not current inventory and is never rewritten. All current checks and exact
acknowledgement matching repeat under the exact-resolution writer lock. New or
equal-time incidents remain active; kill is unchanged. After exact resolution,
later legitimate maker activity does not reopen the old label. The acknowledgement
chain itself remains continuously validated: revocation, corruption or changed
bound evidence re-latches and appends a fresh unresolved STOP even after resolution.

## Verification

Two genuine legacy adapter fill/source write REDs produced false post-only
labels before repair, then passed with generic ORDER_PERSISTENCE_FAILED and no
post-only violation rows. A preliminary test setup typo (`tif` versus stored
`time_in_force`) failed before these genuine reproductions; it was not a defect
reproduction. Actual maker failures keep their existing post-only STOP behavior,
quantity high-water, atomic cash-source persistence and provisional finality.

The separately preregistered released-history test also failed before its gate
repair and passed afterward. Realistic 73-remnant, pagination and strict terminal-
zero tests preserve every physical quantity while rejecting incomplete and
contradictory evidence. Incident tests cover exact resolution, all state/
source/flag/violation/confirmation changes, revocation, stale race, new/equal-time
flags, incomplete reads, later maker history and writer-lock revalidation.
The final focused bundle passed 180 tests. The complete repository suite passed
1,252 tests in 65.67s; watchdog self-test, shell syntax checks and `git diff
--check` passed.

```sh
python3 -m pytest -o addopts='' -q nodes/execution/tests nodes/exec_polymarket/tests nodes/execute/tests nodes/risk/tests nodes/account_ledger/tests nodes/reconcile/tests grids/live_stream/tests ops/tests/test_pm_proof.py
```

Use the prepare→dry→explicit-confirm commands in `nodes/execution/README.md` or
the separately owned operator runbook. This local PASS does not authorize release
or clear any independent forward gate, accounting question, flag or live kill.

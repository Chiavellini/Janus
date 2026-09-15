# L127 verdict — MATERIAL_STOP

The first measurement harness incorrectly required a released maker admission to erase its
claimed timestamp. The repository's existing contract instead treats the slot as empty when its
client order is null and its retained timestamp is null or a valid positive value. The corrected
registered harness records that admission as empty. This correction does not change the verdict.

Exact read-only findings:

- The acknowledgement record hash verifies exactly.
- Seventeen maker attempts occurred after the acknowledgement; all seventeen are terminal-proved
  and none is marked violated.
- The admission slot has no client order and a valid retained timestamp.
- There is exactly one post-only violation row, and match_incident with require_idle false verifies
  the original flag, violation, acknowledgement chain, and settled incident exactly.
- There are zero open or unconfirmed orders, unreleased executions, materially unhedged
  executions, or unreleased reservations.
- Twenty ORDER_OVERFILL flags and ORPHAN_FILL 587 remain unresolved. The seven unique overfill
  orders each have valid exact historical acknowledgements, and the manual fill disposition
  computes a valid bounded recovery cursor, but neither fact is a resolution marker.

The registered classification is therefore MATERIAL_STOP. Later maker rows are proved append-only
terminal history, but the global unresolved-material-flags criterion fails. The lane remains
inactive with the original kill restored. No database, flag, kill, order, venue, or code mutation
was performed under L127.

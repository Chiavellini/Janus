# L119 verdict — one null additive reservation field

The current incident differs from the immutable acknowledgement snapshot at exactly one path:
`/settled/reservation/hedged_utc` exists in the current schema with value `null` and is absent from
the stored snapshot. The stored acknowledgement record hash verifies exactly. No stored field
changed or disappeared, and no identity, quantity, price, fee, cash, order/execution state,
settlement, reservation value, flag, or violation value differs.

Under the immutable L119 criterion this is **ADDITIVE_SCHEMA_ONLY**. It justifies a separately
registered compatibility repair restricted to this exact path and null value.

The first ad-hoc measurement command printed `MATERIAL_STOP` because its implementation
incorrectly hard-coded `/settled/order/execution_id` as the only allowed additive path. That
classifier contradicted the already-registered general rule. `results.json` preserves the mistaken
raw label and the criteria-based classification rather than hiding the error. The recursive diff
itself was correct and complete.

No database, acknowledgement, flag, kill, mode, cap, or live policy was changed.


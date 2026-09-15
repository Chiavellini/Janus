# L135 verdict — MATERIAL_STOP

L133's four nonquiet counts are not one identity. The execution and reservation are one real
25-contract ATP cover (`17077a35` / `b292be2a`) with both venue orders filled, fee-complete and zero
unhedged contracts, but no settlement row. It therefore legitimately retains $24.49357 of capital
and cannot be declared quiet.

The post-only admission is a separate empty slot: `client_order_id` is null and only its historical
`claimed_utc` remains. Janus's canonical `_empty_admission_state` accepts exactly this shape; L133's
query incorrectly counted the timestamp alone as an unresolved admission.

Historical persistence violation client `40797bee...` has exact source flag 211 and valid exact
resolution marker 215. Its `pm_post_only_orders` row is absent because the incident itself was the
database-lock persistence failure. L133 recognizes marker 215 cryptographically but incorrectly
requires the impossible missing lifecycle row before consulting it.

Production stayed on release `1be680b`, inactive with both unit PIDs zero and the exact retained kill
unchanged. No provider call, database write, guard, restart, override or account mutation was made by
L135.

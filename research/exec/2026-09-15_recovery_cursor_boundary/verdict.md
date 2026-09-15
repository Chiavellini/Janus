# L129 verdict — EXCLUSIVE_BOUNDARY; two independent resolution blockers measured

The authenticated Polymarket trade reader applies `after` exclusively at an integer timestamp.
For disposition row 4, `recovery_fill_since` returned the fill's exact timestamp 1789409189.0.
The production API returned zero rows at `after=1789409189`; one second earlier it returned exactly
the disposed fill, ID `99f8e62b-0684-446f-baa7-08bb785c3d30`, confirmed at 666.666667 shares and
$0.15. The row-set hashes differ exactly as recorded in `results.json`.

The overfill blocker is separate. There are eleven historical overfill candidates. Seven have
exact acknowledgements and together cover every one of the twenty unresolved flag snapshots.
The other four have no acknowledgement because each passes the existing
`bounded_taker_residual` predicate. Detection deliberately accepts that class, but
`_resolve_acknowledged_overfills.current_evidence` requires an acknowledgement for it anyway and
returns `None`, preventing the covered flags from resolving.

The release remained safe. The lane stopped after systemd's 30-second graceful-stop deadline,
with no remaining unit process, but the timeout left the unit in `failed` rather than `inactive`,
so cleanup correctly reported failure. The exact original kill hash and reason remain present;
orders, executions, unhedged exposure, and reservations were zero in the release proof.

No production state was changed by this measurement.

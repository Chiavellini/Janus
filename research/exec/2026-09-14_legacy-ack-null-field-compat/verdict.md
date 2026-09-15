# L120 verdict — exact legacy acknowledgement null-field compatibility

The local repair satisfies the immutable compatibility boundary. Legacy acknowledgement validation
now uses a recursive comparator that requires exact key presence, value, and type at every path,
except that a stored snapshot missing `/settled/reservation/hedged_utc` may match a current `null`
there. A current non-null `hedged_utc`, a second added field (including another `null`), a removed
field, or an economic/incident change remains invalid.

The allowance is used only by `confirmation_plan` and `match_incident` in
`legacy_incident_ack.py`. It does not change `settled_snapshot`, reservation accounting,
one-cover-per-event behavior, orphan matching, overfill handling, persistence detection, kill
handling, or any current order guard.

The required mutation matrix passes, and the end-to-end legacy-shaped snapshot (field absent in the
stored manifest, current value `null`) confirms and revalidates successfully. The acknowledgement
record, hash, source proof, confirmation envelope, operator, original snapshot, flag, violation,
order, execution, settlement, and reservation rows are not rewritten or re-confirmed by the
repair.

Focused results: 43/43 legacy acknowledgement tests pass; the combined disposition/legacy run is
108/108 and the execution package collects 184 tests. The full repository suite is
**1,601/1,601**, including the two previously flaky box tests on this run.

Replay was rerun against 20,000 captured frames and remains 1,093 rows with digests
`13e4fb08a76c920f` and `4f53cda18c2baa0c`. No production database,
acknowledgement, flag, kill, mode, cap, hurdle, order, or live policy was changed.

Expected EV effect: none directly. This removes only the proved schema-only false STOP; it does not
authorize a kill clear or imply positive live EV.

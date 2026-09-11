# L71 verdict — resolved legacy checker quiescence

Status: **PASS; DEPLOYMENT PENDING**.

The production log after d864447 proves fresh guard passes no longer carried the current adapter
persistence error. They did carry `LEGACY_POSITION_EVIDENCE_BLOCKED` because the old one-time
terminal-zero proof ran despite an empty exact unresolved `POST_ONLY_PERSISTENCE_FAILED` set. That
unrelated line correctly prevented L69's strict safe-pass predicate from resolving flag 530.

The repair returns only after stored acknowledgement validation and exact migration cleanup have
run, and only when `unresolved_flag_rows(..., POST_ONLY_PERSISTENCE_FAILED)` is empty. An invalid
acknowledgement appends a new same-class flag before this boundary; any unresolved row still runs
the complete terminal-zero proof. A regression uses unrelated shared-account positions to prove
the already-resolved path is quiet, while the existing incomplete/new/changed incident tests retain
the fail-closed behavior.

Focused legacy/recovery/clear tests and the complete repository suite pass. No production database,
kill, order, redemption or account state was changed. The failed d864447 release stopped before
lane stop/kill handling and before automatic redemption.

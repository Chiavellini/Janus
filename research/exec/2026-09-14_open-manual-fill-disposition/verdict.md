# L118 verdict — exact open manual fill ownership

Status: **LOCAL PASS; DEPLOYMENT AND CONFIRMATION PENDING**.

The implementation adds the explicit append-only `open_external_manual` action. It binds every
`FillRecord` field to the exact operator statements and authenticated venue/account evidence in
`evidence.json`, whose source is required to be the full Git commit
`5ca42d0205604a8284ad24439a90f05dbd685ceb`. The validator checks source SHA/tree/blob membership,
evidence schema, cash identity and arithmetic, empty Janus order rows, bounded orphan snapshots,
and rejects obvious reusable authentication material.

Only the exact fill ID and complete identity can match. Same-order or otherwise similar future
fills remain orphans. The open action carries no settlement proof and confirmation appends only an
ownership record; it does not alter orders, executions, positions, balances, P&L, reservations,
flags, protection or kill state. Existing settled-proof coverage remains green.

Focused tests: `pytest -q nodes/execution/tests/test_dispositions.py` — **65 passed**. The combined
execution package collects 184 tests. The full repository suite is **1,601/1,601**, including the
two previously flaky box tests on this run. Replay parity remains 1,093 evaluation rows with
digests `13e4fb08a76c920f` / `4f53cda18c2baa0c`.

No database confirmation, guard resolution, kill operation, box operation or release was performed
under L118. A fresh complete guard pass and the operator’s separately reviewed dry-run/confirmation
are still required on the target database. Expected EV effect: none.

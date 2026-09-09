# L52 atomic activity-batch follow-up — local pass, account STOP unchanged

Independent review found that the fresh activity index retained a valid prefix after a later
indexing/iteration exception. That prefix could falsely appear unique, set a fresh fill final
and persist cash authority despite `CASH_ACTIVITY_PENDING`. Criteria were pre-registered in
`atomic_activity_batch_spec.yaml` with an append-only PENDING ledger note before tests.

The exact cases are `[valid_activity, None, duplicate_valid_activity]` and a generator yielding
valid activity then raising. Each is tested both without prior cash authority and after a
SHA-backed $3.71626 cash join. The new partial batch intentionally offers a plausible changed
$3.72626 amount, so the prior-source case detects an invalid new correction too.

All four regression cases **failed before the fix**, demonstrating that incomplete batches
minted fresh source records. `fills()` now builds a private temporary index and publishes it
only after the entire read/iteration completes. Any read/index/iteration exception explicitly
discards the fresh index. No valid prefix is available to the cash join. The independently
verified durable source fallback remains usable and retains the earlier cash/VWAP/finality.

After the fix, all four cases pass. They assert no new source or authoritative-cash audit is
written, fresh fills remain nonfinal with the conservative .36 request price, and previously
proved cash remains exactly $3.71626 with unchanged records and finality.

```sh
python3 -m pytest -o addopts='' -q nodes/exec_polymarket/tests/test_cash_accounting.py -k activity_batch_is_atomic
# Before fix: 4 failed, 28 deselected.
# After fix: 4 passed, 28 deselected in 0.17s.
python3 -m pytest -o addopts='' -q nodes/account_ledger/tests nodes/exec_polymarket/tests nodes/execute/tests nodes/reconcile/tests nodes/risk/tests/test_overfill_health.py
# 183 passed in 1.80s.
git diff --check
# clean
```

Only the PM fresh-batch indexing block, its tests and local documentation/ledger were changed
in this follow-up. No guard/live changes, venue reads, deployments, new test look or EV claim.
All edits remain unstaged; earlier result notes remain intact. The overall current-account
STOP and source-completeness limitations are unchanged.

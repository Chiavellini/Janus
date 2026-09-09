# L52 review follow-up — local regression pass, account STOP unchanged

The earlier 98-test local pass did not cover two important sequences: a cash-authoritative
fill followed by a failed cash reread, and a fresh missing-cash REST trade whose top-level
price differs from its maker-leg VWAP. Review found both defects before deployment. Criteria
were registered in `repair_followup_spec.yaml`; the original L52 spec/result remains unchanged.

The PM adapter now owns an append-only `pm_cash_sources` table, keyed for lookup by immutable
fill ID. Each observation preserves trade/activity JSON, canonical-source SHA256 and observed
time. This is normalized source JSON, not a claim to be the raw HTTP-body hash; the original
L52 external response archives remain the raw-byte authority. The table also preserves orphan
cash before an order exists. Stored source SHA and exact cash identity/quantity are checked on
replay. A legacy `venue_fills.final` bit alone is deliberately not treated as cash authority.

After the $3.71626 Maximus cash join, later timeout, absent reader, empty/ambiguous/malformed
activity or stale MATCHED status retains exact cash, VWAP 0.354098349 and accounting finality.
Adapter recreation uses the same durable source. A valid new authoritative cash correction
appends its source and preserves the old source and old order audit. This does not infer an
automatic reversal from missing rows; FAILED trades remain excluded by the existing contract.

For a fresh unproved cash line, provisional price uses L53 maker-leg VWAP where complete; if
not, it uses the journaled BUY ceiling / SELL floor, never the top-level first-maker price.
An orphan with neither uses the binary cash bounds BUY 1 / SELL 0 and stays nonfinal. The
Maximus regression distinguishes 0.35 from `3.60 / 10.166667` and the 0.36 request ceiling.
Fee-model fixtures now supply explicit maker legs where their test needs a proved price;
there is no automatic fabrication of maker evidence in the fake transport.

Verification:

```sh
python3 -m pytest -o addopts='' -q nodes/exec_polymarket/tests nodes/execute/tests/test_guard_cash_finality.py nodes/execute/tests/test_guard_quantity_coverage.py
# 74 passed in 1.06s
python3 -m pytest -o addopts='' -q nodes/account_ledger/tests nodes/exec_polymarket/tests nodes/execute/tests nodes/reconcile/tests nodes/risk/tests/test_overfill_health.py
# 179 passed in 1.95s
git diff --check
# clean
```

The sequence regression verifies identical persisted fill/source rows after the failure,
pending remains false after guard sync, and settlement still realizes the exact $3.71626
debit. Valid corrected cash appends a second source/audit rather than changing the first.
No guard code was changed in this follow-up; L53's partial-FIFO/quantity preservation remains
owned by that repair. All edits remain local, unstaged and undeployed. No venue read or live
state mutation occurred. The original current-account STOP and source-completeness limitations
are unchanged, and no EV or live-health improvement is claimed.

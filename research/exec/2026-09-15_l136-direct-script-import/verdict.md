# L137 verdict — LOCAL PASS; RELEASE RETRY READY

The helper now derives `/opt/janus` (or the corresponding checkout root) from its own installed
absolute path and inserts it before repository imports. A subprocess regression runs the real file
by absolute path from outside the repository with `PYTHONPATH` removed and reaches `--help` with
exit zero.

Verification:

- focused L136/L137/L133 tests: 45 passed;
- all `ops/box/tests`: 108 passed;
- Bash syntax, Python compilation and `git diff --check`: passed;
- replay: 20,000 frames, 234 pollers, 5,858 evaluations and 1,093 rows; exact unchanged digests
  `13e4fb08a76c920f / 4f53cda18c2baa0c`;
- fresh independent Luna audit: `RELEASE`.

The failed production invocation on `d7366db` stopped before provider or database work. Read-only
post-failure proof showed the lane inactive with both PIDs zero, retained kill SHA-256
`dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83`, zero settlement rows for
the registered execution, state `HEDGED/released=0/unhedged=0`, and its reservation unreleased.
No risk, identity, settlement, guard, kill, entry, or F22 semantics changed under L137.

## Production result

Release `c65d6206eb2a3b91569fda8fc8af06c716c671b8` successfully reached the exact L136 helper. Both
authoritative results were still non-final, so it returned `L136_SETTLE_WAIT` with exit 3. Exact
post-run proof found the unit inactive with `MainPID=0` and `ControlPID=0`, the retained kill digest
unchanged, the execution still `HEDGED/released=0/unhedged=0`, its reservation unreleased, and zero
settlement rows. This is a production WAIT, not a STOP or a failed safety claim.

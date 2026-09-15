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

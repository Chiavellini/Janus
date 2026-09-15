# L142 local verdict — PASS; production observation pending

Each loop-owned maker safety proof is now bounded by the smaller of the existing coordinator poll
interval and the remaining immutable rest deadline. A timeout or error exits the rest and starts
the existing cancellation path; it is never counted as a healthy check or fill. Responsive checks
repeat until fill, named refusal, or deadline.

Structured `maker_guard` evidence records check, timeout and error counts, the last timeout bound
and duration, and the terminal reason/outcome. Taker behavior is untouched. The existing two-second
maker deadline, caps, hurdles, hedge requirements and protection allowances are unchanged.

The F23 scorer now requires that evidence rather than trusting an outcome label. A maker fill must
carry `maker_fill` and zero guard errors/timeouts; a resting terminal zero must carry at least one
successful check, zero errors/timeouts, and a named refusal or deadline. An immediate provider
rejection is the only maker disposition that can validly precede guard evidence. Missing or failed
proof is a registered persistence/reconciliation STOP.

Focused maker tests include a deadline-shorter-than-poll bound, repeated responsive checks,
explicit timeout classification and named refusal/error evidence. They pass as part of the 172-test
focused selection and the complete green suite. Replay digests remain exactly
`13e4fb08a76c920f / 4f53cda18c2baa0c`.

Because F22 is stopped, no production maker rest has yet exercised this fix.

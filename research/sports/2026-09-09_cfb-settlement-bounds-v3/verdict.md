# L60 — CFB settlement correction: STOP

The four current September 10/11 CFB games are exact ESPN-anchored, ordinary Division-I
regular-season fixtures. Polymarket's new rules text is also fully reviewed: its normalized hash
is `a85d52e70c02f6cd`, and it preserves the existing payout semantics on all twelve settlement
dimensions.

The settlement probabilities cannot be carried forward from L32. Its immutable spec excludes
conference championships and FCS playoffs, but `measure.py` accepts every ESPN `season.type == 2`
final through December 15. ESPN labels both conference-title games and FCS playoff games type 2 /
`regular-season`; the frozen diagnostic lists ten such games from one 2025 weekend. More
importantly, L32's numerator is a press-compiled exception table whose own report calls FCS
coverage roughly 70–80% and the resulting rate a FLOOR. It also registers raw point ratios rather
than conservative exact upper bounds.

No preserved complete authoritative original-kickoff schedule exists for all included FBS/FCS
fixtures, so L60 stops before computing a rate. Both CFB evidence keys are withheld. CFB therefore
blocks by the exact codes `EVIDENCE_UNMEASURED:cfb.cancelled_rate` and
`EVIDENCE_UNMEASURED:cfb.postponed_gt48h_rate` and is removed from default discovery until a
complete original-to-terminal corpus passes the registered criteria.

This is a settlement-integrity result, not a profit result. No live, account, order, deployment,
service, kill, override, or cap action occurred.

# L128 verdict — PASS locally; release continuation pending

The L122 proof had conflated the original acknowledgement's historically empty maker table with
current safety after later, legitimate maker attempts. For the exact flag-211 recovery path only,
the proof now validates the original incident with `require_idle=False`, then independently
requires the existing settled-current-database predicate and exactly one post-only violation row.
The real incident matcher binds that sole row to the acknowledged incident.

The helper still requires zero unresolved material flags and global capital quiet before its first
stop. Its read-only pre-proof wait is now bounded to 100 three-second attempts so the ordinary live
guard can append the already-authorized manual-disposition and overfill resolutions while the exact
retained kill continues to block entry. The helper does not resolve or edit database state.

Evidence:

- Twenty-five focused helper tests passed, including terminal/unviolated history acceptance and
  rejection of active, unproved, violated, held-admission, extra-violation, unreleased-execution,
  and unreleased-reservation states.
- The broader 84-test execution/operator set, Bash syntax, and Git whitespace checks passed.
- The integrated suite passed with only the two declared pre-existing FIFO flakes excluded.
- Replay remained 1,093 evaluation rows, zero selections, and exact digests
  `13e4fb08a76c920f` / `4f53cda18c2baa0c`.
- A fresh independent Luna audit returned RELEASE and found no release-blocking safety gap.

No cap, hurdle, size, entry, protection, settlement, or trading behavior changed. Expected EV
effect remains zero per trade.

# L125 verdict — PASS locally; release continuation pending

The first operator-authorized L124 release reached the exact helper and failed closed before any
recovery work. The candidate checkout and signed override were installed, but the original kill
remained byte-identical and continued blocking entry.

Static inspection found 42 hexadecimal groups in the release-SHA guard and 61 in the kill-SHA
guard. They now use exact anchored lowercase hexadecimal expressions of 40 and 64 characters.
Validation occurs before the helper constructs or invokes any remote work.

Evidence:

- Forty-one focused operator/helper safety tests passed.
- The production preamble itself is executed by the new test; valid exact inputs cross the
  validation boundary, while short, long, uppercase, and non-hex inputs for both arguments fail.
- Bash syntax and Git whitespace checks passed.
- The integrated suite passed with only the two declared pre-existing FIFO flakes excluded.
- Replay remained 1,093 evaluation rows, zero selections, and exact digests
  13e4fb08a76c920f / 4f53cda18c2baa0c.
- A separate Luna audit returned RELEASE and found no authority broadening.

No evidence predicate, guard, archive, rollback, stop, cap, hurdle, size, entry, protection, or
settlement behavior changed. Expected EV effect remains zero per trade.

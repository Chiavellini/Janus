# L124 verdict — PASS locally; operator release pending

The registered failure was reproduced by static inspection: the release route read a full
40-character Git SHA but accepted only a 20-character shell pattern. The operator attempt ended
without changing the box checkout; the retained kill and old deployment remained exact.

The route now accepts exactly forty lowercase hexadecimal characters. Its test extracts and
executes the real shell case arm, replaces only the operator helper with a recorder, proves that
the exact full SHA reaches that helper untruncated, and proves that 20-, 39-, and 41-character,
uppercase, and non-hex values fail before the helper.

Evidence:

- Focused release-route tests passed.
- Bash syntax checks and Git diff whitespace checks passed.
- The integrated suite passed with the two declared pre-existing FIFO flakes excluded.
- Replay remained 1,093 evaluation rows, zero selections, and exact digests
  13e4fb08a76c920f / 4f53cda18c2baa0c.
- A separate Luna audit returned RELEASE and found no authority broadening.

No release, kill clear, arm, confirm, mode, override, order, database, venue, or box mutation was
performed by the agent. Expected EV effect remains zero per trade.

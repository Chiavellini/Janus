# L126 verdict — PASS locally; release continuation pending

The operator-authorized release passed exact digest validation and then stopped locally before the
first helper remote call because STARTED was expanded by the local set-u shell.

The production-construction test exposed two more defects before deployment: AUDIT was also
unescaped, and escaped double quotes in an unquoted heredoc would have reached the remote shell as
literal quote characters. The helper now binds only DB, KILL, KILL_SHA, PY, and RELEASE_SHA
locally. Every remote variable and command substitution keeps its dollar for the remote shell,
while ordinary double quotes are emitted as real shell syntax. The remote script assigns STARTED
before using it and passes archive-dir as the expanded, double-quoted AUDIT value.

Evidence:

- Forty-two focused operator/helper safety tests passed.
- The test executes the production helper through real heredoc construction with only the final
  remote invocation replaced.
- Bash syntax and Git whitespace checks passed.
- The integrated suite passed with only the two declared pre-existing FIFO flakes excluded.
- Replay remained 1,093 evaluation rows, zero selections, and exact digests
  13e4fb08a76c920f / 4f53cda18c2baa0c.
- A separate Luna audit initially blocked the literal archive value, then returned RELEASE after
  the corrected remote quoting and complete variable audit.

No evidence predicate, guard, archive, rollback, stop, cap, hurdle, size, entry, protection, or
settlement policy changed. Expected EV effect remains zero per trade.

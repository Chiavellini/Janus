# L136 verdict — LOCAL PASS; PRODUCTION WAITING VENUE FINALITY

The stopped-lane convergence is locally complete. It binds the full deployed release, exact
retained kill bytes, inactive unit with both PIDs zero, exact execution/reservation/order identity
and economics, the exact Polymarket slug, and the complete two-outcome cross-venue mapping. It
fetches only authoritative venue results and uses the existing `apply_settlements`,
`ExposureLedger`, and `OpportunityStore` path.

All state changes run in one `BEGIN IMMEDIATE` transaction with nested commits deferred. The helper
re-proves the stopped unit and retained kill before commit and proves the complete exact post-state
inside the transaction. Provider WAIT, wrong winner, altered mapping/economics/identity, extra held
state, write failure, concurrent unit restart, or kill mutation releases nothing. The kill is never
removed or rewritten by L136.

The corrected L133 predicates accept only the canonical single null-owner admission slot and allow
a missing lifecycle row only when every historical persistence source has a canonical,
cryptographically exact resolution marker. Any absent/invalid marker or present nonterminal or
violating lifecycle row remains a STOP.

Verification:

- focused L136/L133 selection: 44 passed;
- full suite: one occurrence of the two declared pre-existing macOS FIFO flakes, green immediately
  in isolation; no other failure;
- Bash syntax, Python compilation and `git diff --check`: passed;
- replay: 20,000 frames, 234 pollers, 5,858 evaluations, 1,093 rows, exact unchanged digests
  `13e4fb08a76c920f / 4f53cda18c2baa0c`;
- fresh independent Luna audit after all four initial blockers were repaired: `RELEASE`.

Two registered read-only provider checks returned `kalshi=null` and `polymarket=null`. Therefore no
production settlement, release, guard resolution, kill archive, restart, entry, or F22 observation
was attempted under L136. Production remains deployed at `1be680b`, inactive with both PIDs zero,
and the exact retained kill remains present. This is a venue-finality WAIT, not a local PASS applied
to production.

# L54 — conditional maker cap; local implementation and regression pass

The always-maker share bound is proved for the reviewed V2 arithmetic. A signature alone does
not enforce maker role: `postOnly` is a server instruction outside EIP-712. The supervising
operator explicitly accepted the documented CLOB post-only maker promise as the operational
boundary after that limitation was identified. Original registration criteria were not edited.
The route is local and undeployed; this is neither unconditional venue correctness nor live,
NFL-readiness, profitability, EV or Sharpe approval. Immediate/non-post-only BUY stays blocked.

`semantics.md` gives the proof, operator/contract-address trust boundary, matching-race and
price-improvement counterexample outside maker role, bounded deliberate rest, cancellation and
finite late-fill evidence limits. `source_manifest.yaml` pins official CTF V2 commit
`ccc0596074f4dfd62c944fbca4de252893b82b4b` and installed/official SDK1.1.0 commit
`215fc63a8fd6ec3a10c7edb73997c9772d8686d3` with matching file hashes. No independently queried
deployed-bytecode attestation is claimed. No public RPC was configured or used for this task.

## Local changes

- Exact signed M/T validators and tick-floor passive planner; actual T/1e6 never exceeds the
  original authorized share request. Runtime SDK/chain/domain/exchange/collateral/CTF/signers
  are allowlisted before signing. The signed hash and redacted economic wire precede POST.
- Atomic cross-connection singleton before preparation/signing; original deadline persisted;
  final prewire freshness, kill, violation and ownership recheck. No automatic replacement.
- Coordinator performs no blocking reads while deliberately resting. Deadline cancellation is
  the first post-ack network operation, followed by bounded reconciliation. Recovery cancels an
  expired/unknown-deadline GTC before ordinary reads. Dispatch is not venue completion.
- Stable terminal order/trade/cash coverage controls release. Missing responses, cancel failure,
  incomplete projection/cash, role uncertainty and later contradictions retain/reopen STOP.
- Owned-maker projection, exact activity cash identity and source durability are integrated.
  Per-trade/per-order high-water preserves quantity independently of changing role/response
  payload or the smaller quantity covered by old cash. Unknown/conflicting roles cannot finalize.
- Role/cap violations and post-wire persistence failures latch live kill and durable watchdog
  flags. If writes fail, known quantities still return for protection, with a separate persistent
  error; failed terminal writes cannot release admission. Guard can retain validated unpersisted
  fills as cash-pending order totals before same-pass execution/protection reconciliation.
- Existing protective hurdle/loss ceilings are recomputed from actual first-leg fill, with no
  cumulative hedge quantity above the original authorization. Historical/paper planner behavior
  is unchanged; only the local capital-risking grid selects the separate maker planner.

## Review regressions and registration chronology

Initial combined436 passed but independent review found missing cases, so it was explicitly not
treated as completion. Each additional specification/PENDING note preceded its tests; all older
criteria and results remain intact.

- `review_followup.yaml`: persistence-expiry recheck had been independently added immediately
  before registration and was tested GREEN without a RED claim. Restart cancellation and slow
  predeadline status were two RED, then all three targeted cases GREEN.
- `cancel_timing_followup.yaml`: cancellation dispatch cannot wait behind a five-second status
  callback; no predeadline blocking read remains.
- `ws_role_followup.yaml`: five RED within-cap socket role/missing-REST and predeadline-read
  cases became GREEN. Role conflict evidence is retained independently of later updates.
- `singleton_followup.yaml`: concurrent connection and interrupted-preparation restart cases
  were two RED, then GREEN. An initial interruption fixture aborted the test run; the harness
  was corrected before the two-case RED run. Claim retention/release, duplicate IDs and old
  late fill versus newer claim have separate regression assertions.
- `projection_coverage_followup.yaml`: six RED cash6/observed11 and malformed-neighbor cases
  became GREEN. Validated quantity reaches guard despite an incomplete projection; incomplete
  batches mint no fresh cash authority. See the separately owned projection verdict.
- `persistence_domain_followup.yaml` and `socket_quantity_followup.yaml`: ten RED initial
  socket11-to-maker4, status-write and runtime-domain drift cases became GREEN. Additional
  address/name/signer/config mutations use otherwise valid baseline stubs to avoid false passes.
- `prewire_stop_followup.yaml`: three RED old-order violation/new kill/lost claim during
  preparation became GREEN with proven no-send and only the new claim released.
- `fill_persistence_followup.yaml`: accounting-owner RED/GREEN fixtures cover source, audit,
  FIFO, later-prefix and fully unavailable SQL writes, including same-pass guard protection.
  Independent file kill remains attempted when database audit itself cannot be written.
- Full coordinator regressions inject journal failure immediately after POST and prove that
  observed6 and10 still produce exactly6 and10 protective hedge requests with entry stopped.

Exact combined verification command:

```sh
nice -n 19 python3 -m pytest nodes/exec_polymarket/tests nodes/execute/tests nodes/account_ledger/tests nodes/reconcile/tests nodes/risk/tests grids/live_stream/tests ops/tests/test_pm_proof.py -o addopts='' -q
git diff --check
```

The parent lifecycle-owner run passed485 in18.90s before the accounting owner's last two
SQL-failure cases were collected. The accounting-owner stable combined run then passed487
in17.38s; diff check was clean. A final lifecycle-owner confirmation is appended below once
completed. Arithmetic/sizing evidence additionally includes107,325 two-part cases and153 sizing
fixtures; this is not an EVM execution or independent deployed-bytecode proof.

## Limits and handoff

The finite two-second stable-terminal window is an operational evidence rule, not a bound on
arbitrary future venue inconsistency. The operator/matching service and documented address
association remain trusted. Network/server cancellation can complete late; only deliberate rest
and dispatch ordering are bounded. Disk failure plus process power loss cannot preserve a new
fact that never reached storage; the already committed admission and independent kill enforce
recovery STOP pending authoritative reconciliation. No hidden recovery or bypass is provided.

Expected EV effect remains unmeasured: less aggressive fill selection, potentially better maker
price/fees, and prevention of F15's share overshoot conditional on maker role. Existing executable
cover evidence is not reinterpreted as a passive-fill guarantee. A new authorized forward
evaluation is required before economic or NFL-readiness claims.

All changes are unstaged and uncommitted in the designated worktree. No venue/account calls,
credentialed signer, live order/cancel, deployment, service restart, rearm, kill clearing or cap
change occurred. Independent review and the supervising operator own any later promotion; the
existing live kill remains outside this local task's mutation authority.

## Final local confirmation — appended 2026-09-09

The exact combined command above passed **487 tests in16.35s** on the stable shared tree,
including the last two SQL-failure cases; `git diff --check` was clean. This confirms the local
regression result only. No deployment, venue validation, promotion or economic claim follows.

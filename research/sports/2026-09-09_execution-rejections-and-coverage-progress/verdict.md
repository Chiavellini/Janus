# L61 — Live rejection and coverage-progress audit

## Verdict

PASS as a descriptive audit. All five Mexico-local-calendar execution attempts are accounted for
exactly once. One completed two-leg cover settled at **+$0.7798** with zero unhedged quantity. The
other four were not venue rejections: Polymarket accepted each post-only GTC order as live, Janus
canceled it after only 0–273 ms of post-ack resting time, and authoritative reconciliation proved
zero matched quantity and no open remainder.

The execution-level label `ORDER_REJECTED` therefore conflates a clean maker zero-fill with an
actual venue refusal. No recorded zero-fill was caused by a risk refusal, stale-data rejection,
system exception or venue rejection.

## Root cause and current operational state

The maker lifecycle uses the minimum of the quote-expiry deadline and the 500 ms execution
clearance. Network acknowledgement consumed most or all of that clearance. Although the
coordinator nominally permits up to two seconds of deliberate rest, the four orders received only
148, 0, 229 and 273 ms respectively. Extending generic clearance would weaken stale-decision
controls; safe additional rest requires a separate continuously revalidated authorization over the
complementary hedge book, fee, settlement proof and cancel deadline.

The successful TEX–SEA maker order subsequently latched `/srv/janus/kill/live` when its
cancel/late-fill lifecycle remained unresolved. It later reconciled terminally and its admission
lock released, but the kill latch persisted. At the audit time the service was active and ingesting,
while subsequent candidates were refused with `KILL_SWITCH active: live`. The audit made no live
state change.

## Coverage progress

Production remains on `76a68da88164047ba630c74c49cb30c8c33ccefd`. Local coverage HEAD
`d6ed3d6` is two commits ahead and has not been deployed. It adds UCL, removes CFB whose settlement
evidence failed the corrected audit, repairs seven current tennis identities and a duplicate ITF
schedule representation, and adds complete pagination/schema/conflict diagnostics. The enabled
league count remains fourteen; the composition changes.

The frozen L59 snapshot contains 308 registered scheduled rows, 270 complete-slate rows, 263
discovery-ready rows and 45 explicit non-ready rows. The non-ready population is 37 tennis listings
without a usable current Kalshi counterpart, four exact CFB pairs with unmeasured settlement rates,
three exact soccer pairs with league-specific evidence and cap blocks, and one genuine schedule
conflict. The separate 203-row/44-mapping census is only a loose onboarding lead and is not evidence
of canonical co-listing, executable arbitrage or profit.

## Priorities and expected effects

1. Resolve the already-terminal maker incident through the exact operator recovery path. This
   removes the current total execution block without changing edge thresholds.
2. Protect an observed maker fill immediately while lifecycle/accounting reconciliation continues
   fail-closed. TEX–SEA exposed an approximately six-second avoidable hedge delay; the expected
   effect is less hedge slippage and unhedged-tail risk, not a presently quantified EV gain.
3. Design and prospectively evaluate a continuously revalidated maker-rest authorization. The
   expected effect is more maker fills while retaining the one-cent price improvement, offset by
   queue/adverse-selection risk; no EV claim is made before a forward test.
4. Give authoritative maker zero-fills their own terminal taxonomy rather than `ORDER_REJECTED`.
   Direct EV effect is zero; diagnosis and optimization decisions become accurate.
5. When release gates permit, deploy the committed coverage repair; then finish league-specific
   original-schedule evidence for Ligue 1, Portugal and Belgium, where three exact frozen pairs are
   already waiting. Rebuild CFB evidence independently. Keep NBA/WNBA/NHL listing monitors active;
   their present blocker is counterpart absence as well as missing paired template review.

No order, cancel, account, balance, database, kill, override, cap, deployment, restart or service
mutation was performed.

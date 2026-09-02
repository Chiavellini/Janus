# L20 — WTI settlement basis, corrected sources — VERDICT

**`EQUIVALENT` for `KXWTI`. Kalshi's WTI binary settles on exactly the NYMEX CL settlement.**
**`INSUFFICIENT_COVERAGE` for `KXWTIW` (5 sessions) — not claimed either way.**

Test looks spent **0** · quotes read **none** · PnL/outcomes read **none** · IBKR untouched.
Spec: `./spec.yaml` (criteria untouched). Ledger: L20, supersedes L19.

## Result

| series | n | exactly equal | max &#124;diff&#124; | CI95 | exchange-checked | verdict |
|---|---|---|---|---|---|---|
| **KXWTI** | **24** | **24 / 24 (100%)** | **4e-06** | [0.0, 2e-06] | 5/5 agreed | **EQUIVALENT** |
| KXWTIW | 5 | 5 / 5 | 2e-06 | [-1e-06, 2e-06] | 1/1 agreed | INSUFFICIENT_COVERAGE |

`max|diff|` of 4e-06 USD/Bbl is float representation noise in Yahoo's JSON, not a price difference —
every value is identical at the 2 dp Kalshi's own rules specify. **Intra-venue, `KXWTI` and `KXWTIW`
agree on 9/9 shared (session, month) keys**, so the Kalshi WTI settlement value names one number.

Of the 24 KXWTI sessions, **5 were independently checked against CME's own published settlement and
all 5 agreed** — so the primary source is corroborated by the issuing exchange wherever the exchange
still publishes, not merely internally consistent.

## What this licenses

**NYMEX CL options are a valid hedge instrument for Kalshi `KXWTI` binaries.** Kalshi settles on the
daily settlement of the named contract month, and that number is the CL settlement — so a CL option
and a KXWTI binary reference the *same* terminal value, with **no settlement-reference basis to
carry**. This is the condition the `AGENTS.md` 2026-08-14 amendment demands before any cross-
instrument comparison, and for this pair it is now measured rather than assumed.

Consequently **NYMEX Real-Time (NP,L1), $1.55/mo and waiver-eligible above $20 monthly commissions,
is the correct and sufficient data purchase** for the WTI leg. ICE data and ICE options are *not*
needed: although Kalshi names ICE WTI as its source agency, the value it publishes equals the NYMEX
CL settle, which is exactly what ICE WTI cash-settles against.

## What this does NOT license

- **Nothing about `KXWTIW`.** Five sessions is a quarter of the gate; the weekly ladder is unproven.
- **No edge of any kind.** This measures a settlement identity, not a mispricing. Whether Kalshi's
  binaries are cheap or rich against the CL option surface is untouched, needs its own registered
  row, and will need tick-error propagation (trap 9) and the flat-2¢ fee control (trap 3).
- **Nothing outside the covered window.** Yahoo delists expired contracts (JUL 26, AUG 26 → 404), so
  22 older KXWTI sessions are `NO_CL_SETTLE` — counted, never imputed. The sample is the most recent
  contiguous ~24 sessions, declared as a limitation before the run. The relationship is structural,
  so drift is unlikely, but it is **not** established here and must not be claimed.
- **Nothing about the 15-minute commodity series**, which settle on Pyth index feeds that are absent
  from Pyth's public API. Those stay BLOCK on oracle access.

## Method notes

Parsers, contract-month matching, dedupe, and all gates are **imported unchanged from L19** rather
than retyped, so "same question, one source swapped" is literally true. Yahoo was promoted to primary
only because L19 *measured* it equal to CME's own settlement on 5/5 sessions — the promotion is
evidence-backed, and it was done as a new row because L19's sources are immutable.

The contract-month guard remains the load-bearing piece: L19 measured the reference rolling
SEP 26 → OCT 26 between 2026-08-14 and 2026-08-17, and on 2026-08-18 CME's SEP settle was 84.94
against Kalshi's OCT-contract 84.06. A front-month continuous series would have reported ~0.9 USD/Bbl
of basis at every roll — pure construction artifact, and the exact error this project's settlement
rule exists to prevent.

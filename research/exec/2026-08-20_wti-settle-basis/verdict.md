# L19 — WTI settlement basis (Kalshi vs NYMEX CL) — VERDICT

**`INSUFFICIENT_COVERAGE` — 5 sessions against a pre-registered gate of 20. Pair stays BLOCK.**
**But on every session where the comparison was possible, three independent sources agreed EXACTLY.**

Test looks spent **0** · quotes read **none** · PnL/outcomes read **none** · IBKR untouched.
Spec: `./spec.yaml` (criteria untouched). Ledger: L19.

## The measured result

| session | month | Kalshi `expiration_value` | CME CL settle | Yahoo close | diff |
|---|---|---|---|---|---|
| 2026-08-12 | SEP 26 | 83.27 | 83.27 | 83.27 | **0.00** |
| 2026-08-13 | SEP 26 | 81.25 | 81.25 | 81.25 | **0.00** |
| 2026-08-14 | SEP 26 | 82.40 | 82.40 | 82.40 | **0.00** |
| 2026-08-17 | OCT 26 | 83.74 | 83.74 | 83.74 | **0.00** |
| 2026-08-18 | OCT 26 | 84.06 | 84.06 | 84.06 | **0.00** |

`max|diff| = 0.00`, CI **[0.00, 0.00]**, Yahoo corroborated **5/5**, zero within-series stops.
**Intra-venue: `KXWTI` and `KXWTIW` agree on 9/9 shared (session, month) keys**, exactly — so unlike
the index ladders (L15: KXINX vs KXINXU disagreed on 25/39 dates), "the Kalshi WTI settlement value"
does name a single number.

**This is not the answer.** Five sessions is a quarter of the registered gate, so no conclusion is
drawn and the pair stays BLOCK. What it is: an unusually clean preliminary indication that Kalshi's
ICE-WTI settlement value **equals** the NYMEX CL settlement — which is the economically expected
result, since ICE WTI is cash-settled against NYMEX CL.

## The contract roll is the reason the design insisted on month-matching

The reference month rolled **SEP 26 → OCT 26 between 2026-08-14 and 2026-08-17**, and both sides
tracked it. On 2026-08-18 CME's SEP-26 settle was **84.94** while Kalshi settled on the OCT-26
contract at **84.06**. A front-month *continuous* series would have produced a ~0.9 USD/Bbl "basis"
at every roll that is pure construction artifact. The spec forbade that substitution before the run,
and 1,376 of 1,376 included markets parsed a named month — **zero** `MONTH_UNPARSEABLE`.

## Why coverage failed, and why it cannot be fixed by trying harder

**The Kalshi side is fine: 46 sessions for KXWTI, 10 for KXWTIW.** The constraint is entirely on the
CL side:

- **CME's public settlements endpoint serves only recent trade dates** — "no settlements array" on
  **42 of 47** requested sessions, every one of them older than about a week.
- **Yahoo 404s on expired contracts** (JUL 26, AUG 26 are delisted), so it cannot backfill the older
  sessions either.

So per-contract CL settlement history is **not publicly backfillable**. This is the same wall L18
hit from the other side: Kalshi retains ~68 days, CME publishes ~5. The overlap between "Kalshi still
has the binary" and "CME still publishes the settle" is about a week wide, and it only ever gets
narrower for a given session.

**Consequence: this measurement must be collected FORWARD.** One cheap request per trading day
accumulates the exchange-sourced settle before it ages out. At ~20 trading days to reach the gate,
that is roughly four weeks from whenever collection starts — and the clock does not start until
someone starts it.

## What this licenses next (and what it does not)

It does **not** license buying the NYMEX subscription yet, and it does **not** license pricing a CL
option against a Kalshi binary. Both wait for the gate.

It **does** justify a successor row with a corrected source design: Yahoo's per-contract daily close
matched CME's own settlement on **5/5** sessions here, which is measured evidence — not an
assumption — that it carries the settlement rather than an arbitrary last trade. A successor spec may
therefore register Yahoo as a *primary* per-contract source with CME retained as the exchange-sourced
check, and that reaches far more of Kalshi's 46 sessions immediately. That is a **new row**, because
L19's sources are immutable; promoting Yahoo inside L19 after seeing the result would be exactly the
criteria-drift the ledger rules exist to prevent.

## Method notes

Both enumeration channels agreed; union 1,376 settled markets, **0 rejected** on any reason.
Contract months seen: JUL 26, AUG 26, SEP 26, OCT 26. Sources: Kalshi **M1** (the operative value a
position actually settles against), CME **R** (the exchange's own published settlements endpoint),
Yahoo **R and weak by construction** — a daily close is the last trade and not by definition the
settlement, so no row was excluded on Yahoo disagreement; it is reported as corroboration only.

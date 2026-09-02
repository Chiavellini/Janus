# L13 — IBKR live-account read-only capability + entitlement probe — VERDICT

> **SUPERSEDED BY RUN 3 (2026-08-19T04:34Z): `PASS_HFT_READY`, `program_ready = true`.** The
> run-1/run-2 verdict below is preserved verbatim as the pre-subscription state. See §Run 3.
>
> **FILE-HANDLING NOTE (2026-08-19):** `collectors/probe_ibkr.py` **overwrites this file** with a
> short stub on every run. Run 3 clobbered the run-1/run-2 prose, which was restored from session
> context; the `results_run*.json` artifacts were untouched and remain the authoritative record.
> **Copy `verdict.md` aside before every probe run** — `verdict_run1_stub.md` and
> `verdict_run3_stub.md` are the stubs as written by the probe.

**RUNS 1-2 (pre-subscription): BLOCKED_ENTITLEMENT_OR_CONTRACT.** Safety gate PASS · session gate PASS · **program_ready = false**.
Test looks spent **0** · orders placed **0** · outcomes/PnL read **none** · account/session/user/MAC identifiers archived **none**.

Spec: `research/exec/2026-08-18_ibkr-readonly-capability/spec.yaml` (criteria untouched). Ledger: `snooping_ledger.md` L13.
Transport: `lib/ibkr_readonly.py` only. Probe: `collectors/probe_ibkr.py`. Suite: 64/64 hermetic tests green before run 1, 65/65 before run 2 (one test added with the fix).

## Runs (all preserved)

| run | UTC | session (ET) | artifact | note |
|---|---|---|---|---|
| 1 | 2026-08-19T01:09Z | 21:09 ET Tue — Globex open, CBOE GTH open, index feed closed | `results_run1_2026-08-19T0109Z.json` | probe as shipped; XSP mis-resolved to a Toronto STK (code defect, see below) |
| 2 | 2026-08-19T01:12Z | same | `results_run2_2026-08-19T0112Z.json` | after fixing `_underlying` to read `sections[].secType`; criteria and selection rules unchanged |
| 3 | 2026-08-19T04:34Z | 00:34 ET Wed — Globex open, CBOE GTH open, index feed closed | `results_run3_2026-08-19T0434Z.json` | **after the market-data subscriptions; PASS_HFT_READY** |

## Entitlement status by family — RUNS 1-2 (M1 — field 6509 as returned; only `R*` is HFT-ready)

| family | contract selected (deterministic rule) | availability code | status | evidence |
|---|---|---|---|---|
| crypto_futures | **MBT** front unexpired: conid 859040577, exp 2026-08-28. **BTC root: `/trsrv/futures?symbols=BTC` returned 0 contracts** (IBKR appears to list the 5-BTC contract under another symbol, likely `BRR` — R, unverified; outside the registered root list, so not substituted per spec) | `DPB` (bid 64555 / ask 64570, sizes 9/7, `_updated` present) | **BLOCKED_DELAYED** | M1 |
| fed_funds | ZQ front: conid 511851937, expirationDate 2026-09-01 (ltd 2026-08-31, i.e. the AUG26 contract) | `DPB` (bid 96.3675 / ask 96.37) | **BLOCKED_DELAYED** | M1 |
| index_options | SPX (IND, conid 416904) last 7693.26 → month AUG26, strike 7695 → C 884192466 / P 884194442. XSP (IND, conid 137851301) last 769.33 → strike 769 → C 885910373 / P 885910835. Expiry day: `NEAR_EXPIRY_UNRESOLVED` (as registered). Index feeds themselves `Z` (frozen outside RTH). | options `DPBd` (SPX C 67.6/68.5, P 62.3/63.2; XSP C 3.31/3.56, P 2.75/2.98) | **BLOCKED_DELAYED** | M1 |

Interpretation (R — IBKR field-6509 legend): `D` = delayed, `Z` = frozen, `P` = snapshot permitted, `B` = book; trailing `d` unknown, prefix governs.
Both CME Globex and CBOE GTH were open when `D` was observed, so `D` is a subscription state, not a closed-market state.

**Conclusion (runs 1-2):** the live account reaches the gateway, contracts resolve deterministically, quotes and `_updated` timestamps flow, but **no family is real-time on the Web API**. Under the registered rule this is an **access result — not evidence that any edge is zero**. IBKR-dependent HFT inference is STOPPED for all three families until the entitlement changes.

## What is HFT-ready / blocked — RUNS 1-2

- HFT-ready: **nothing** (no `R*` code observed).
- Blocked (entitlement): crypto_futures (MBT), fed_funds (ZQ), index_options (SPX, XSP).
- Blocked (contract discovery, documented): BTC root — 0 contracts under symbol `BTC` on `/trsrv/futures`.

## Contract-discovery notes (M1)

- `/iserver/secdef/search` returns the security type in `sections[]`, not at row level; run 1's `_underlying` tie-broke by conid and chose XSP conid 74580612 (TSE stock). Fixed in `collectors/probe_ibkr.py::_underlying` with `tests/test_ibkr_readonly.py::test_probe_underlying_uses_section_sectype_not_smallest_conid`. Selection rule text in the spec is unchanged.
- SPX/XSP option chains for AUG26 resolve for both rights via `/iserver/secdef/strikes` + `/iserver/secdef/info`; the probe pins month+strike only (registered), the exact expiry day is deferred to any archive spec.
- ZQ `expirationDate` is the settlement day (month+1 day 1) while `ltd` is the last trading day; the probe's rule uses `expirationDate`.

## Environment finding (M1) — recorded because it consumed the session

The gateway was unreachable for ~6 h before the probe: `com.janus.ibkr-gateway` ran as launchd `ProcessType Background` (JVM priority 4, ~100 MB compressed out on this 8 GB host at load 35–57) and its outbound TLS handshake to `api.ibkr.com` exceeded Vert.x's hard-coded 10 s limit, so every proxied `/v1/api` call hung. Fixed on the Janus side only: plist `ProcessType Interactive`, trimmed JVM via `JAVA_TOOL_OPTIONS` in `collectors/run_ibkr_gateway.sh`. Startup went from ~4 min to <1 s and calls answer in ~0.3 s. Authentication was then performed manually by the user (never automated).

## Unblock path — as written after run 2 (superseded by run 3; two guesses were WRONG)

Enable real-time market data for this IBKR user (R, prices unverified): CME Real-Time (NP, L1) for MBT/ZQ; CBOE Indexes; OPRA for SPX/XSP options. Then re-run L13 unchanged (`python3 collectors/probe_ibkr.py`) — during CBOE RTH 09:30–16:15 ET so the index `last` is live — and register the archive spec only for families that come back `R*`.

*Corrected by run 3:* **CME does not cover CBOT** (they are separate $1.55 subscriptions and ZQ is a CBOT product), and **OPRA is not expensive** ($1.50, waiver-eligible) — it was wrongly flagged as the line to defer. "CBOE Indexes" was also the wrong product for the SPX index value; the SPX index feed is **CME S&P Indices** ($6.50, no waiver), which was deliberately not bought.

## Run 3 — 2026-08-19T04:34Z — **PASS_HFT_READY**

**The entitlement hypothesis is confirmed. `program_ready = true` for the first time.**
Criteria untouched; probe re-run unchanged (`collectors/probe_ibkr.py`, no edits since run 2).
Safety gate PASS · session gate PASS (`authenticated true / connected true / competing false`) ·
orders 0 · test looks 0 · identifiers archived 0 (redaction grep **0**) · suite 87/87.

| family | contract | conid | run 2 | **run 3** | status |
|---|---|---|---|---|---|
| crypto_futures | MBT front, exp 2026-08-28 | 859040577 | `DPB` | **`RB`** | **HFT_READY** |
| fed_funds | ZQ AUG26 | 511851937 | `DPB` | **`RB`** | **HFT_READY** |
| index_options | SPX 7695 C / P (AUG26) | 884192466 / 884194442 | `DPBd` | **`RpBd`** | **HFT_READY** |
| index_options | XSP 769 C / P (AUG26) | 885910373 / 885910835 | `DPBd` | **`RpBd`** | **HFT_READY** |
| *(selection aid)* | SPX index | 416904 | `Z` | `Z` | **BLOCKED_FROZEN** |
| *(selection aid)* | XSP index | 137851301 | `Z` | `Z` | **BLOCKED_FROZEN** |

Live quotes at run 3: MBT 64390 / 64405 (sizes 4 / 22) · ZQ 96.3675 / 96.37 (sizes 706,231 /
169,452) · SPX 7695C 63.6 / 64.3, 7695P 65.8 / 66.5 · XSP 769C 2.86 / 3.07, 769P 3.11 / 3.29.

**Unblock action (user, 2026-08-19):** subscribed to **CME Real-Time (NP,L1) $1.55**, **CBOT
Real-Time (NP,L1) $1.55**, **OPRA (US Options Exchanges) (NP,L1) $1.50** — **$4.60/month list, all
three waived above USD 20 monthly commissions**. Two corrections to the run-2 unblock note, which
guessed wrong on both counts: CME does **not** cover CBOT (they are separate $1.55 subscriptions, and
ZQ is a CBOT product), and OPRA is **not** expensive — it is the cheapest of the three and is
waiver-eligible. **CME S&P Indices ($6.50, no waiver) was deliberately NOT bought**, which is why the
two index underlyings remain `Z`.

**Controlled comparison, deliberately not run in RTH.** Runs 1-2 executed at 20:09 CST with Globex
and CBOE GTH open; run 3 executed at 22:34 CST with Globex and GTH open. Same session state, one
variable changed — the subscription. The handoff had recommended RTH so the index `last` would be
live, but that advantage disappeared once the index feed was skipped, and RTH is not a spec
criterion. This isolates the entitlement as the cause.

**The frozen index is not merely stale — it is measurably wrong.** SPX index `last` still reads
**7693.26**, the identical print from 2026-08-19T01:20Z. L15 measured the official 2026-08-18 close
at **7691.76** (Kalshi KXINX matched it exactly, 42/42 dates), so the frozen value carries a
**1.50-point error** and strike selection currently runs off it — run 3 picked SPX 7695 from a wrong
underlying. Tolerable for capture characterization, **must be recorded, and must not be used as an
underlying level in any computation.** Options: buy CME S&P Indices ($6.50), or derive the level from
the `R*` option quotes via put-call parity, which costs nothing and uses only entitled data.

`expiration_day_status` remains `NEAR_EXPIRY_UNRESOLVED` for both underlyings, as registered.

**Consequence:** the spec's `program_ready_rule` ("at least one crypto future and at least one
SPX/XSP option contract must be HFT_READY") is **satisfied**. All three IBKR families are released
from the entitlement STOP. The forward archive may now be registered — as its own new L-row, with
`families_included` filled from this run, **before** the first quote is written.

---

## Run 4 — 2026-08-19T18:53Z — **PASS_HFT_READY in CBOE RTH** (the index-hours question, answered)

Executed at **14:53 ET, inside RTH 09:30–16:15**, at the operator's request. Criteria untouched;
probe unchanged. Safety PASS · session PASS (`authenticated / connected / competing=false`) ·
orders **0** · test looks **0** · redaction grep **0** · suite **104/104**.
Artifact: `results_run4_RTH_2026-08-19T1853Z.json`. Stub the probe wrote: `verdict_run4_stub.md`.

| instrument | conid | run 3 (GTH, 00:34 ET) | **run 4 (RTH, 14:53 ET)** | reading |
|---|---|---|---|---|
| MBT front | 859040577 | `RB` 64390/64405 | **`RB`** 68515/68525 | real-time, unchanged |
| ZQ AUG26 | 511851937 | `RB` 96.3675/96.37 | **`RB`** 96.3675/96.37 | real-time, unchanged |
| SPX near-ATM C/P | 879729743 / 879730160 | `RpBd` | **`RpBd`** 19.9/20.3, 22.1/22.5 | real-time, unchanged |
| XSP near-ATM C/P | 885910383 / 885910841 | `RpBd` | **`RpBd`** 2.31/2.32, 2.49/2.51 | real-time, unchanged |
| **SPX index** | 416904 | **`Z`** (frozen), last 7693.26 | **`D`** (delayed), last **7717.52** | **state changed** |
| **XSP index** | 137851301 | **`Z`** (frozen), last 769.33 | **`D`** (delayed), last **771.72** | **state changed** |

### What run 4 establishes that run 3 could not

**`Z` was a closed-market state; `D` is the subscription state.** Outside RTH both index feeds read
`Z` (frozen). Inside RTH, with the same account and the same unchanged subscriptions, they read `D`
(delayed). That separates the two explanations that were confounded in runs 1–3, and it confirms the
deliberate decision not to buy **CME S&P Indices ($6.50/mo, no waiver)** is what holds the index
underlyings below `R*` — not market hours.

**The frozen-print hazard is materially smaller inside RTH, but not gone.** The SPX index now reads
**7717.52** and moves, rather than the 26-hour-old **7693.26** that run 3 selected a strike from
(and which L15 measured as 1.50 points away from the official close). A delayed print is ~15 minutes
stale rather than a day stale. It is still **not** an underlying level for any computation — the
put-call parity forward from the entitled option quotes remains the correct source.

Consequence for strike selection: run 4's chosen strikes differ from run 3's (SPX conids
879729743/879730160 vs 884192466/884194442) purely because the underlying moved ~24 points overnight.
Deterministic rule, different level, different strike — as registered.

**Entitlement conclusion is unchanged and now holds across both session states:** all three
registered families are `R*` in GTH and in RTH. `program_ready = true`. Nothing about the index
underlyings blocks the registered `program_ready_rule`, which requires one crypto future and one
SPX/XSP option contract.

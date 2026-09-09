# L52 — STOP: current account total withheld

Registered before statement reads on 2026-09-09. Descriptive; no test look or holdout touched.
Sources were read through existing credentials using GET only, without remote file creation,
venue mutation, redemption or deployment. Local fixes below remain undeployed. Root separately
latched the live kill after the confirmed F15 cap violation; this audit did not mutate kills.

## Exact findings

Maximus Jones / JON V MORIYA execution `ceba2013c79e4334b8406ad315b9e78e` began
2026-09-09 04:34:26.486607Z in F15. The local request was 10 contracts at $0.36. Historical
venue GET order event 739 reports `original_size="10"`, `size_matched="10.166667"`,
`price="0.36"`, `order_type="FAK"`. The confirmed CLOB trade independently reports 10.166667.
The Kalshi hedge was 10.17. Both exceed the signed 10-contract cap: STOP, not rounding dust.
Original signed maker/taker request bytes are **not captured**. SDK reconstruction is not a
historical wire artifact. The fresh GET order returned HTTP 200 with literal `null` and proves
neither original size nor no-fill. L53 owns the local quantity repair.

The authoritative PM activity cash debit is **$3.71626**, not the first-maker-price cost plus
a model fee. Its VWAP field is 0.354098349; the CLOB top-level 0.35 is not its VWAP. The two
maker components explain gross $3.60: 6 shares against complementary BUY at 0.65, and
4.166667 shares against same-token SELL at 0.3599999712000023. The source cash charge controls
the total; using its rounded VWAP produces a fee residual $0.116260000467217, which preserves
exact cash. This tiny residual precision is not an additional fee assumption.

Kalshi's settled NO position reports revenue $10.17, cost $6.610500 and fee $0.162000:

`10.17 - 6.610500 - 0.162000 - 3.71626 = -0.318760 USD` → **-$0.32**.

The stored execution detail instead says `settled -0.2765 USD (COVER)`; its PM order average
is 0.35 and fee 0.115645837125, while the execution average remains 0.36. The displayed
discrepancy is $0.042260, exceeding the pre-registered one-cent STOP. Historical rows have
not been edited. Maximus is now a resolved loser: PM position `redeemable=true`, value 0;
its -$3.71626 is not an economically open position at this snapshot.

## Authoritative subtotals, not a reconciled current-account total

The fixed **2026-09-07 00:00 UTC through these 2026-09-09 snapshots** window is explicit and
does not claim to match the screenshots. All 9 Kalshi fills in this window match 8 settlements
exactly in outcome quantity, acquisition cost and paid fees. Every recent PM acquisition is
either redeemed or is a resolved zero-value position. Funding is excluded.

| Scope | Exact USD | Cent presentation |
|---|---:|---:|
| PM trade/redemption cash in fixed window | +10.660473 | +10.66 |
| Kalshi fill-matched settlements in fixed window | +0.507500 | +0.51 |
| Fixed-window descriptive sum | +11.167973 | +11.17 |

The sum includes pre-F15 transactions and one-legged executions; it is **not** an arbitrage-EV
estimate, not all-history account P&L, and not a validated correction to the screenshot total.
The historical screenshot control remains +$10.39 realized and +$6.67 visible trading cash,
with $205.35 funding excluded and Maximus then open. Its exact time/line boundary is missing,
so adding new settlement amounts to that historical total would be unjustified.

PM complete activity contains 203 rows: 141 trades, 57 redemptions and 5 funding entries.
Exact trading cash is **-$95.424133**; deposits **$426.647677**, withdrawals **$19.616588**,
net funding **$407.031089**. Their signed sum is **$311.606956**, matching authenticated CLOB
cash to **$0.000000**. The independent accounting ZIP reports cash/equity $311.606956 and
position value zero. All 73 remaining positive-size PM positions are redeemable and value
zero; none is economically open. 58 closed-position rows are secondary controls, not the
cash source, because their position quantities are rounded. Old redemptions with blank token
IDs retain condition/outcome identity; no token allocation was invented. The latest deposit
is actually $205.34902, presented as $205.35, and never included in trading P&L.

Kalshi's current positions response is empty and cash is $270.3868 (portfolio value zero).
This is a cash/control observation, **not a profit calculation**. Its 105 settlement records
start July 4. The authenticated historical cutoff is July 11; combining 133 ordinary and
192 historical fill observations yields 286 unique fills back to April 11, with 39 byte-field
equivalent overlaps explicitly checked, not double-counted. Settlement records alone do not
cover earlier realized dispositions. A complete old settlement/position cash ledger and
adjustment coverage remain unproven: no lifetime combined account P&L is reported.

Kalshi funding responses contain four applied deposits totaling $1056.52 and one applied
withdrawal $500, separately identified; three failed deposits are excluded. The API omits the
optional funding cursor. The conservative collector preserved raw responses but did not mint
a completion manifest for them. The funding amounts are observed-line subtotals, not an
assertion of independently verified full funding coverage.

## Source integrity and replay

All unmodified response bytes, retrieval times, GET URL/parameters, HTTP status and SHA256
are in `/Volumes/Kilos/janus/accounting/L52`. Financial JSON is parsed with Decimal, not float.
Cent presentation uses ROUND_HALF_UP **after** exact summation; source subcents are retained.
Each imported PM line uses wallet + transaction + kind + condition + asset + outcome + side;
each Kalshi settlement uses exchange + ticker + settled timestamp. Duplicate/conflicting
identities are rejected rather than silently added.

Critical provenance (paths relative to that external archive root):

| Evidence | File | SHA256 |
|---|---|---|
| Historical order event 739, execution and arm | `20260909T094147Z_maximus_journal/journal.json` | `f74d9949cfe9d44b305c78fa02db9b2148c3f80d2ccf20a53a8e39b1304c658f` |
| Confirmed PM trade | `20260909T093018Z_pm_clob_trades/0000.json` | `f79f86a47cb9e215e80078721058621eaa20667a9157765e008d7d87038df58c` |
| PM cash activity | `20260909T093056Z_pm_activity/0004.json` | `3e0ba1e395ed3737b945246f955803c7da19d345b4fea32195f071786cf1c982` |
| Kalshi settlement | `20260909T092847Z_kalshi_settlements/0000.json` | `80fd88a72e5be79549e74758aecc367bbf0ee0726051f9ffb5b7837f9001ffaf` |
| Fresh order lookup, literal null | `20260909T093216Z_pm_clob_maximus_order/0000.json` | `38e0b9de817f645c4bec37c0d4a3e58baecccb040f5718dc069a72c7385a0bed` |

The journal capture at 09:41:45Z independently sees `kill/live` present, `kill/all` absent.
An earlier read at 09:31:59Z saw neither; root reports latching live at 09:33:10Z.

Offline replay, requiring those frozen archives:

```sh
python3 research/accounting/2026-09-09_current-post-f15-reconciliation/replay.py
```

It verifies every consumed page hash and explicit pagination manifest, source identities,
Kalshi overlap equality, recent fill/settlement count-cost-fee equality, and PM cash control.
Its verdict remains `STOP_CURRENT_TOTAL_WITHHELD`. The first CLOB trade fetch exceeded SSM's
stdout limit; no truncated payload was accepted. A later chunked reread verified identical
full-response hashes for all chunks and completed successfully. Error/empty directories and
funding responses were preserved, not promoted to successful collections.

## Local repair and verification

`nodes/account_ledger/statements.py` imports exact authoritative cash and settlement records
without inferring realized status or funding from balances. Historical screenshot tests remain.
The PM adapter obtains GET-only decimal activity and accepts only an unambiguous exact-size
transaction/token/side match. Missing authority, even on CONFIRMED trades or transports with
no cash reader, leaves accounting pending; model fees remain explicitly provisional. Source
activity is appended to the order audit. No read is added inside order encoding/posting.

The guard propagates aggregate MIN(final), then corrects final cash-only execution averages
with a same-state audit entry and no quantity/release/protection change. The existing settlement
revision path retains old/new accounting and updates settlement P&L. Execution fee values are
owned by order/settlement rows, not duplicated into new execution columns. A combined Maximus
regression proves $3.71626 debit, corrected average, -$0.318760 settlement, same RECONCILED/
released state and unchanged prior order events. These are local future behavior fixes, not
a claim that the historical live account was already repaired.

Focused verification command:

**98 tests passed in 1.15s** before the separately coordinated L53 partial-FIFO preservation
follow-up; root/that owner runs the shared integration suite after its final changes.

```sh
python3 -m pytest -o addopts='' -q nodes/account_ledger/tests nodes/exec_polymarket/tests nodes/execute/tests/test_guard.py nodes/execute/tests/test_guard_cash_finality.py nodes/reconcile/tests/test_settle_executions.py
```

Expected executable-EV effect: no claimed improvement. Accurate cash/finality removes a false
profit attribution; L53's quantity protections are evaluated separately. No deployment,
restart, arm/cap change, redemption, order or transfer was performed here.

Official source contracts consulted: [PM activity](https://docs.polymarket.com/api-reference/core/get-user-activity),
[PM accounting snapshot](https://docs.polymarket.com/api-reference/misc/download-an-accounting-snapshot-zip-of-csvs),
[Kalshi historical partition](https://docs.kalshi.com/getting_started/historical_data),
[Kalshi fills](https://docs.kalshi.com/api-reference/portfolio/get-fills),
[Kalshi settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements),
[Kalshi deposits](https://docs.kalshi.com/api-reference/portfolio/get-deposits).

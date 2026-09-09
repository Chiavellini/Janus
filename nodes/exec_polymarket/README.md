# exec_polymarket

**Kind:** `execute`
**Implements:** `client.py` (`PolymarketExecution`, `ClobTransport`, `PyClobTransport`)

The Polymarket order path, disarmed by construction like Kalshi's, with two venue facts baked in.

**BUY submission is blocked (`QUANTITY_CAP_UNPROVEN`, L53).** The V2 signed `makerAmount`
caps collateral spent; `takerAmount` is the minimum received shares at full budget consumption.
`OrderArgsV2.size=10` and REST `original_size=10` therefore do not cap the shares a taker BUY
can receive. F15 filled 10.166667. Cent-exact nominal size/price did not fix this. The real
transport rejects every BUY before signing/posting, including a GTC that could cross immediately;
the adapter also refuses transports with unknown cap semantics. There is no runtime opt-out.
A reviewed venue-enforced quantity bound is required before this route can execute again.
Held-order reads and already-authorized SELL protection remain available.

**Every outcome is its own token.** `buy_no` is refused; the coordinator passes the outcome's
token id as `market_id` with `buy_yes`.

**Matched is not settled.** A `matched` FOK is `FILLED` with `settlement_pending=True` — the CLOB
reported it authoritatively and the other leg must be sent — until `fills()` sees the trade
`CONFIRMED`. `FAILED` trades are never fills; the reconcile node handles the reversal. A
`matched` FAK is `UNCONFIRMED` until `status()` reports `size_matched`.

**No demo environment.** `DEMO_EXECUTION` uses the paper venue for this leg; a real order needs
`LIMITED_LIVE` under the signed override. The first real test of this leg is the $5 fill in
GATE step 8.

**The wallet key moves funds.** `PyClobTransport` reads it from `JANUS_PM_WALLET_KEY_PATH`
(mode 600, refused otherwise), never from `JANUS_CREDS`, never on EC2 without a KMS. EIP-712
order signing, tick-size rounding and L1/L2 auth are delegated to `py_clob_client`, imported
lazily; without it the transport cannot be built and says how to install it. PAPER and SHADOW
need nothing.

## Tests

`tests/test_pm_exec.py` — with a fake transport: the side rule, FOK matched → FILLED pending,
FAK matched → UNCONFIRMED then status, rejection vs transport failure, trade finality, the mode
gate, and the missing-library path.

`tests/test_quantity_cap.py` freezes F15's historical order and trade field projections with
source hashes, reproduces the SDK's nominal 10-share / $3.60 wire amounts without a signer,
and tests refusal before wire. Authenticated taker VWAP uses each maker leg's token and side:
an opposite-outcome maker BUY contributes `1 - maker_price`; a same-token maker SELL contributes
its own price. Missing or inconsistent maker evidence leaves the average unknown so the
coordinator uses the conservative planned BUY ceiling. A top-level trade price is not a VWAP.

## CLOB V2, pUSD and the Deposit Wallet (2026-09-07)

Polymarket replaced its exchange on 2026-04-28: new contracts (CTF Exchange V2
`0xE111180000d2663C0091e4f400237545B87B996B`), a V2 order format (EIP-712 domain version 2; no
fee / nonce / taker fields), and **pUSD** (`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`) as the
collateral instead of USDC.e. `PyClobTransport` wraps `py_clob_client_v2`; the V1 client kept
answering reads and reported the account's collateral as 0.00 while the account held 95.60 pUSD.

The operator's account is a **Deposit Wallet** (Polymarket's smart wallet for accounts deployed
after 2026-05-04; the app shows its address under "for API use only"). It trades with
`JANUS_PM_SIGNATURE_TYPE=3` (EIP-1271) and `JANUS_PM_FUNDER=<that address>`; under signature
types 0, 1 and 2 the exchange reports a balance of 0 for the same account. The settings page's
"Export private key" (via reveal.magic.link) yields the signer key; the signer holds no
collateral itself.

## Authoritative cash finality (L52, 2026-09-09; local repair)

`fills()` joins CLOB trades to the GET-only Data API activity feed by transaction, token and
side, requiring exactly one matching trade/activity and identical size. `usdcSize` controls
cash; activity VWAP controls price, with the cash residual recorded as paid fee. The raw source
amount is retained as a decimal string in an append-only `authoritative_cash` order event.
The existing float execution protocol is only a projection; exact statement replay lives in
`nodes/account_ledger`. No order limit, first-maker price or pinned fee can make a fill
accounting-final. For a fresh unproved fill, missing/conflicting/unavailable activity leaves
quantity known but `final=False`. Missing cash uses maker-leg VWAP if proved, otherwise the
durable order limit (BUY ceiling/SELL floor); an orphan without either uses binary bounds
(BUY 1 / SELL 0), explicitly provisional. No cash read occurs in order encoding.

Proved cash is durable in append-only `pm_cash_sources` records containing source trade/activity
JSON and canonical-source SHA256. This also covers orphan fills before order adoption and
survives adapter restart. Later timeout, absence, ambiguity or stale MATCHED status cannot
overwrite the proved cash/VWAP/finality with a model estimate. A new exact authoritative cash
correction appends a source record; a legacy `venue_fills.final=1` without source proof is not
cash authority. FAILED trades remain excluded under the existing reconciliation contract;
this change does not invent automatic reversal authority.

`tests/test_cash_accounting.py` covers exact Maximus debit/VWAP, delayed and ambiguous cash,
SELL credits, source-event idempotence and GET-only decimal-preserving pagination.
It also verifies durable cash across reader failures/restarts, legacy-final rejection,
append-only cash corrections, conservative missing-cash prices and stable guard/settlement
finality after a failed reread.

Fresh activity indexing is atomic: a read/index/iteration failure discards the entire new
batch, including any otherwise valid prefix. It cannot hide a later duplicate or mint fresh
cash authority. SHA-backed prior cash remains usable through the separate durable fallback.
Regressions cover `[valid, null, duplicate]` and a generator yielding valid then raising,
both without prior authority and with a previously verified cash record.

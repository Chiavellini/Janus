# exec_polymarket

**Kind:** `execute`
**Implements:** `client.py` (`PolymarketExecution`, `ClobTransport`, `PyClobTransport`)

The Polymarket order path, disarmed by construction like Kalshi's, with two venue facts baked in.

**Immediate/non-post-only BUY submission is permitted only by the L65/F20 bounded-taker path.** The V2 signed `makerAmount`
caps collateral spent; `takerAmount` is the minimum received shares at full budget consumption.
`OrderArgsV2.size=10` and REST `original_size=10` therefore do not cap the shares a taker BUY
can receive. F15 filled 10.166667. Cent-exact nominal size/price did not fix this. The real
generic transport route rejects every BUY before signing/posting, including a GTC that could cross immediately.
The dedicated FAK/FOK signer is hard-limited to 10 requested shares and $12 collateral, records
that authorization before POST, and preserves actual price-improvement quantity. Excess strictly
below one contract is the operator-accepted protection-dust residual; larger excess still stops.
A separate L54 post-only route remains available for historical reconciliation but is not selected live.
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
and tests the fixed bounded-taker authorization plus refusal outside it. Authenticated taker VWAP uses each maker leg's token and side:
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

## Post-only maker entry (L54, local and undeployed)

The dedicated route uses exact V2 `GTC`, `postOnly=True`, and `deferExec=True`; FAK/FOK and
ordinary crossing GTC BUY remain refused. Its share bound is conditional on the CLOB honoring
its documented post-only maker guarantee. Post-only is NOT an EIP-712/on-chain restriction;
a malicious or faulty operator can violate the premise. The pinned contract/SDK proof and
explicit trust boundary are in `research/exec/2026-09-09_pm-post-only-share-cap/semantics.md`.

For an always-maker BUY with signed collateral M and shares T, each collateral fill f receives
floor(f*T/M) token units and cumulative collateral fills cannot exceed M. Consequently total
maker receipts cannot exceed T. The adapter validates actual signed integers, not nominal SDK
size: T/1e6 <= authorized contracts, exact cent-share precision, and M/T <= limit. Exact economic
wire fields and the signed hash are durable before POST; the replayable signature is redacted.
An atomic database singleton is committed before preparation/signing, so independent adapters
and interrupted processes cannot create a second unresolved order. Old markers remain intact.

The original clearance and both quotes bound the deliberate rest period. No blocking status,
trade or cash read starts before cancellation dispatch; the coordinator sleeps to the deadline,
records cancel intent, cancels first, then reconciles. The deadline is persisted before POST;
recovery cancels an expired or legacy-unknown deadline before ordinary status I/O. Dispatch is
not a promise of network/venue completion, and GTD's minimum lifetime cannot replace this short
deadline. Any unproved cancel/late-fill lifecycle latches new entry while protecting known fill.

A cancel reply alone never releases admission. Complete matching trade IDs, confirmed maker
fills, authoritative cash, and two stable terminal order observations separated by at least two
seconds are required. Missing answers, partial cash/FIFO, failed reads or role uncertainty stay
pending. The coordinator budgets this declared terminal-proof grace after its ordinary venue
response window, preventing a latch just before already-observed terminal evidence matures; a
genuinely unresolved lifecycle still latches. Later contradictory fills reopen the lifecycle and stop new entry, never clamp holdings.
This is an operational evidence window, not a Byzantine or infinite-future no-fill proof.

Maker fills use their owned order's quantity/token/side/price, with composite source identity
`raw_trade_id:maker:owned_order_id`. Taker/conflicting socket or REST roles and signed-cap breaches
write durable stop evidence and invoke the live kill even below dust. Socket role evidence is
sticky and checked independently of REST. Unknown role cannot be accounting-final. Max observed
quantity survives a smaller cash-backed record: cash for six cannot turn eleven observed shares
back into six or price all eleven. An incomplete projection returns validated quantities as
provisional plus a separate coverage error; it cannot mint fresh cash authority or terminal proof.

`test_post_only_sizing.py`, `test_post_only_lifecycle.py`, and `test_maker_fills.py` cover integer
math, actual wire validation, concurrent admission/restart, rejection/ambiguity, bounded cancel,
late fills, maker identity/role, cash and quantity independence. No live deployment, rearm or EV
claim follows. Expected selection effect: lower fill rate than marketable orders; potentially
better maker price/fees and elimination of the cap breach conditional on maker role. EV/Sharpe
remain unmeasured until separately authorized forward evaluation.

The signing boundary allowlists SDK 1.1.0, Polygon137, the exact V2 EIP-712 name/version, both
reviewed exchange addresses, pUSD collateral, CTF token contract, and both runtime signer chains.
Unknown configuration refuses before signing. This is address/config identity, not deployed
bytecode attestation. Final prewire checks repeat live kill, any durable violation, admission
ownership and original freshness after all preparation/persistence.

Post-wire persistence failure raises `POST_ONLY_PERSISTENCE_FAILED` and a separate adapter/guard
error, but returns the highest observed quantity for protection. In-memory per-order and
per-trade high-water evidence cannot be reduced by a smaller or conflicting later response;
ordinary cash/terminal finality remains blocked. A failed terminal write cannot release admission.
If the disk is truly unavailable, no implementation can durably recreate an unpersisted fact
across power loss: the retained prewire claim and independent kill enforce recovery STOP, and
authoritative re-reconciliation is required. The code does not claim otherwise.

Each fill stages its source proof and cash audit in one transaction; `record_fill` is the final
commit. A write failure rolls back the staged batch, returns all validated prefix quantities as
nonfinal, and keeps an in-process unpersisted-fill high-water for stale/empty rereads. The guard
can persist the union of returned and stored fill IDs as a cash-pending order total for same-pass
protection. If that fallback also cannot write, the persistence failure is explicit; it never
silently declares protection successful or bypasses required execution journaling.

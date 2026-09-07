# exec_polymarket

**Kind:** `execute`
**Implements:** `client.py` (`PolymarketExecution`, `ClobTransport`, `PyClobTransport`)

The Polymarket order path, disarmed by construction like Kalshi's, with two venue facts baked in.

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

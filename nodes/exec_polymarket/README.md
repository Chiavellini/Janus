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

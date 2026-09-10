# redeem_polymarket

**Kind:** `account operation`

**Implements:** `redeem.py`, `run.py`

This box-local oneshot uses Polymarket's pinned official `polymarket-client==0.9.0` to redeem
resolved, positive-value Deposit Wallet positions into pUSD. It never selects zero-value losing
remnants. Trading and redemption use separate processes and Python environments: redemption
failure cannot stop the live lane, change an execution, clear a kill, or authorize an order.

Every condition is journaled in `/srv/janus/redemptions/redemptions.sqlite` before submission.
The exact metadata string recovers the narrow crash window between relayer acceptance and the
transaction-id write. A missing transaction cannot be blindly retried; a confirmed transaction
remains `CONFIRMED_PENDING` until a fresh positions read proves the valuable redeemable position is
gone. The systemd timer runs every ten minutes and the watchdog requires a successful pass within
thirty minutes.

Builder credentials are KMS-encrypted SSM SecureStrings and materialized only into `/run/janus`.
`ops/box/provision_redemption.py` creates them once during the operator's release when the complete
credential set is absent; a partial set is a hard error and no value is printed.

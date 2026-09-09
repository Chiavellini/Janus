# L54 maker-accounting adapter subtask — local regression pass

Scope was agreed with the L54 lifecycle owner before edits; `maker_accounting_spec.yaml` and
the parent L54 PENDING registration preceded tests. This is only an attribution/accounting
integration result, not the overall route proof, promotion approval or an EV claim.

`fill_projection.py` projects authenticated maker trades onto exact owned journal order IDs.
An explicit funder-address match also preserves orphan maker observations before adoption.
Each maker projection uses its own `order_id`, `matched_amount`, `price`, `asset_id` and `side`,
never the other party's top-level taker fields. Source identity is
`<raw trade id>:maker:<owned order id>`; original raw trade and maker objects remain in durable
cash-source provenance. Multiple owned orders in one trade cannot collide. An unattributable
maker or malformed/duplicate owned maker identity is a blocked read, not an inferred taker or
zero fill. Source field/role distinctions follow the official
[authenticated trade schema](https://docs.polymarket.com/api-reference/trade/get-trades) and
[user trade schema](https://docs.polymarket.com/api-reference/wss/user).

Only explicit MAKER role agreement verifies the projected maker. Cash joins use the maker's
transaction/token/side and exact matched quantity. Cash VWAP must agree with the owned maker
price to the source rounding tolerance; the maker price, not a taker price, prices that fill.
Several owned orders sharing one activity cash key remain provisional instead of allocating
aggregate fees/cash by estimate. Ordinary maker SELL credits are distinct from BUY debits.

For recorded post-only orders, an owned order appearing as taker, a contradictory account
role, or a token/side contradiction writes the lifecycle owner's durable
`POST_ONLY_ROLE_VIOLATION` and invokes the provided kill callback before cash reading/accounting.
An unrelated later projection failure cannot hide an already observed owned taker. Per-order
cumulative quantity combines incoming projected fills with durable FIFO and known order
quantity, then calls the lifecycle owner's exact signed-cap check. Violations retain the
unclamped quantity and cannot finalize cash. Unknown post-only role also remains nonfinal;
previously proved cash amount/VWAP is preserved separately through the durable fallback.

L52's SHA-backed cash preservation, append-only corrections, immutable-source identity,
atomic fresh-activity indexing and conservative missing-cash behavior remain covered. The
lifecycle owner separately owns post/submit/status/cancel, outstanding remainder handling,
quantity encoding, stop helpers, protocol/coordinator changes and node README integration.
This subtask does not change guard or lifecycle state machines.

Verification at the shared-tree snapshot:

```sh
python3 -m pytest -o addopts='' -q nodes/exec_polymarket/tests/test_maker_fills.py nodes/exec_polymarket/tests/test_cash_accounting.py
# 53 passed in 0.43s (21 new maker cases plus L52 cash cases)
python3 -m pytest -o addopts='' -q nodes/account_ledger/tests nodes/exec_polymarket/tests nodes/execute/tests nodes/reconcile/tests nodes/risk/tests/test_overfill_health.py
# 374 passed in 2.15s, including concurrent lifecycle-owner changes
git diff --check
# clean
```

Files owned by this subtask:

- `nodes/exec_polymarket/fill_projection.py` (new pure projection).
- `nodes/exec_polymarket/tests/test_maker_fills.py` (new offline fixtures/regressions).
- `nodes/exec_polymarket/client.py`: projection/safety imports, maker-price validation in
  `authoritative_cash_fill`, and `fills()` projection/preflight/role-finality integration only.
- This verdict and `maker_accounting_spec.yaml`.

No signer, credential or venue/account API was used. Only public documentation was consulted.
No order, cancel, transfer, deployment, restart, rearm, kill clearing or cap change occurred.
Edits are local and unstaged. The parent must finish independent review and the overall L54
decision; no live or profitability claim follows from these tests.

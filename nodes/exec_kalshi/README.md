# exec_kalshi

**Kind:** `execute`
**Implements:** `client.py`

The Kalshi order path. Disarmed by construction: `submit()` refuses below `DEMO_EXECUTION`,
refuses without a `RiskClearance`, journals before the POST, sends through the non-retrying
`post_json_once`, and never retries an ambiguous answer — a transport failure is `UNCONFIRMED`
and is resolved through `status()`, which also finds an order by client id when the POST never
answered.

## Verified

2026-09-03, production, read-only: the REST signing scheme is the socket's (RSA-PSS over
`timestamp + METHOD + path`); `GET /portfolio/balance` and `GET /portfolio/orders` answer.
Order endpoints from the v2 docs: `POST /portfolio/events/orders` (side `bid`/`ask` in YES
terms; buying NO is an `ask` at 1 − price), `DELETE /portfolio/events/orders/{id}`,
`GET /portfolio/orders/{id}` (status `resting` / `canceled` / `executed`, `*_fp` counts,
`taker_fees_dollars`), `GET /portfolio/fills`. **Not yet exercised against the demo host**: the
demo has its own credentials; the DEMO round-trip (place → poll → cancel → settle) is GATE step 8.

## Modes

`DEMO_EXECUTION` → `external-api.demo.kalshi.co` with demo credentials. `LIMITED_LIVE` /
`PRODUCTION` → production under the signed override. A capital-risking mode on the demo host is
refused at construction.

## Fees

`average_fee_paid` × fill count on the create ack; `taker_fees_dollars + maker_fees_dollars` on
the order record. GATE step 8 compares these with the pinned curve at the series multiplier.

## Tests

`tests/test_kalshi_exec.py` — YES-terms body mapping, the signature, journal-before-wire, timeout
→ UNCONFIRMED with exactly one POST, 4xx → REJECTED, ack and status mapping, recovery by client
id, fills / balance / cancel-all, the mode gate.

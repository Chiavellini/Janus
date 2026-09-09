# L54 quantity proof and trust boundary

This is a conditional operational proof, not an unconditional on-chain max-received guarantee.
The original specification remains immutable. After the contract audit exposed the unsigned
role boundary, the supervising operator explicitly authorized reliance on Polymarket's documented
post-only maker promise, with per-fill verification and durable STOP on any contradiction. No
live permission, deployment, rearm or profitability approval was given.

## Maker arithmetic

Let M be signed collateral `makerAmount`, T signed share-token `takerAmount`, and f_i the
collateral quantity consumed by maker fill i. The reviewed contract computes maker receipts as
q_i = floor(f_i*T/M). Order status is depleted by maker collateral, so sum(f_i) <= M. Hence:

    sum(q_i) = sum(floor(f_i*T/M)) <= floor(T*sum(f_i)/M) <= T.

This covers partial fills, repeated entries of the same maker hash, complementary transfers and
mint/mixed matching. Price improvement is assigned to the taker; it does not change a maker's
signed receipt ratio. Fees are separate collateral transfers, not extra outcome-token receipts.
The proof assumes a single signed order hash on its bound exchange and ordinary positive Janus
amounts below 2^248; Solidity checked multiplication reverts on overflow. Janus validates these
ranges and exact cross-products, avoiding floating-point round-up in the authorization comparison.
See pinned [Trading.sol](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/exchange/mixins/Trading.sol)
and [CalculatorHelper.sol](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/exchange/libraries/CalculatorHelper.sol).

The SDK's nominal size is not the proof. The adapter inspects actual built/signed integer M/T,
requires T/1e6 <= authorized requested contracts, no more than two share decimals, and M/T <= the
authorized BUY ceiling. The planner floors the passive price to a tick below the observed ask;
if the market moves to cross before matching, the server must reject under its post-only rule.
Tick/rounding rejection is safe; it is never retried as taker. Local exact arithmetic fixtures
covered 107,325 two-part decompositions and 153 sizing cases; this is not an EVM test run.

## Why the service is a necessary premise

`postOnly`, GTC/GTD and expiration are not signed fields in the V2 EIP-712 structure. The
operator submits matching transactions and chooses each order's role. For example, BUY
M=3,600,000,T=10,000,000 used as a taker against SELL M=10,285,714,T=3,600,000 can receive more than
T at an improved price. The on-chain order signature alone cannot prohibit that role. See pinned
[Structs.sol](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/exchange/libraries/Structs.sol)
and [CTFExchange.sol](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/exchange/CTFExchange.sol).

The official [order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle) explicitly
states that post-only guarantees maker execution and crossing post-only orders are rejected.
The installed V2 SDK 1.1.0 sends top-level `postOnly` and supports it only for GTC/GTD. The local
route uses GTC with deferred execution wait, never a FAK/FOK fallback. Installed files match
official commit `215fc63a8fd6ec3a10c7edb73997c9772d8686d3`; hashes and pinned contract identity are
in `source_manifest.yaml`. Official source/config associates the Polygon V2 addresses; deployed
bytecode was not independently queried. An adversarial operator, dishonest role/status feed or
different contract implementation remains outside the accepted trust boundary.

Runtime preparation now allowlists package1.1.0, Polygon137 and the EIP-712 domain name/version,
both V2 exchange addresses, collateral and conditional-token addresses. It checks both SDK
configuration entrypoints and both actual signer chain IDs before invoking signing. The reviewed
domain is added to the durable economic-wire provenance. No public RPC was configured or called
for bytecode attestation; address association remains the accepted boundary, not bytecode identity.

## Rest, cancellation and late fills

A short economic clearance is not extended into a long-lived resting strategy. Rest expires at
the minimum original clearance and selected quotes' freshness deadlines, persisted before POST.
GTD has a minimum expiry buffer unsuitable for the short clearance, so local cancel dispatch is
required. A second freshness check after durable persistence prevents a stale prewire send.
After POST the coordinator does no status/trade/activity I/O until it dispatches cancel; a slow
GET cannot delay that dispatch. Recovery cancels expired or unknown-deadline unresolved orders
before ordinary reads. Network/server cancellation completion can still be delayed; this is
explicitly not an exact-time cancellation guarantee. See [order placement](https://docs.polymarket.com/trading/place-orders)
and [management](https://docs.polymarket.com/trading/manage-orders).

One atomic, durable singleton precedes preparation/signing across database connections. Exact
signed cap/hash/economic wire and cancel deadline precede POST. Ambiguous delivery, missing
status, cancel failure, incomplete role/cash evidence and late-fill ambiguity keep the lock and
reservation; no replacement is attempted. A cancel response alone is not no-fill authority.
Terminal release requires two stable terminal order observations at least two seconds apart,
matching associated-trade IDs and complete confirmed maker/cash coverage. This finite evidence
window is an operational consistency check, not a mathematical bound on arbitrary future
service inconsistency. Any later contradictory fill reopens stop state, retains history and
prevents new admission even if a newer order already owns the singleton.

Immediately before POST, after preparation and durable writes, live kill, all durable post-only
violations and exact singleton ownership are rechecked alongside expiry. An old-order violation
arriving during a new preparation produces a durably recorded no-send and releases only the new
order's own claim. It cannot clear the old stop/history or send through a newly latched kill.

All observed quantity is preserved for protection independently of cash coverage. Owned maker
projection uses maker-specific order/token/side/price/quantity. Socket and REST taker/conflicting
roles or cumulative signed-T breach cause durable STOP/kill before ordinary accounting. Unknown
roles and partial/malformed projection remain provisional, not zero. Actual late fills feed the
existing hedge hurdle/loss-cap protection; cumulative hedge buys never exceed the original
authorized cap. A violation cannot authorize over-buying the hedge or clamping a held position.

Per-order/per-trade high-water quantities survive conflicting smaller socket roles, stale reads
and post-wire persistence failure. Failure to write raises a visible persistence STOP and returns
known holdings for immediate protection, while all terminal/cash finality and admission release
stay blocked. The independent kill and already committed prewire claim protect recovery; the
system cannot promise durability of a new fact through both disk failure and process power loss.

## Economic interpretation

Maker entry changes fill timing and selection. Relative to a taker route, fills may be less
frequent, passive prices/fees may improve, and the F15 share-cap failure is excluded conditional
on the maker premise. None of those facts establish net EV or Sharpe. Existing executable cover
proof stays conservative, and delayed fills are re-evaluated by protective hurdle/loss ceilings.
No NFL-readiness or profitability claim is made before separately authorized forward evidence.

# L53 — F15 share-cap violation

The local fail-closed repair passes. **Real Polymarket BUY entry remains blocked.** The current
wire cannot prove a maximum received-share quantity; no deploy, restart, order, arm/cap change,
or kill clearing occurred in this work. This descriptive repair spends no statistical look and
claims no new EV evidence.

## Cause and evidence

F15 execution `ceba2013c79e4334b8406ad315b9e78e` journaled a 10-share BUY at $0.36. Its historical
GET order response, retained in event739, reports `original_size="10"`,
`size_matched="10.166667"`, and `order_type="FAK"`. A later L52 GET returned literal `null`;
that later absence does not supersede the historical response or confirmed trade. Both original
archive paths and hashes are in `results.json`, and the regression fixture preserves a minimal
field projection with source provenance.

The installed `py-clob-client-v2` 1.1.0 builder maps nominal BUY size 10 and price .36 to
`makerAmount=3600000` and `takerAmount=10000000`. This was reproduced offline without constructing
a signer. **The original signed HTTP request was not captured**, so these wire amounts are a
source-backed reconstruction, not a claimed recovered request.

The exchange specifies `makerAmount` as the maximum asset sent and `takerAmount` as the minimum
asset received. For a BUY those assets are collateral and shares respectively. The signed
10-million-unit received amount therefore expresses a minimum at full budget consumption,
not a maximum share cap. See the pinned [V2 order structure](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/exchange/libraries/Structs.sol#L26).

The taker matching paths enforce minimum proceeds and pass the received surplus to the taker;
order consumption is tracked in the asset sent. A GTC can also cross immediately, so changing
FAK to GTC alone cannot establish a cap. See the pinned
[V2 trading implementation](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/exchange/mixins/Trading.sol#L274).

Confirmed trade `a9bfe2a5-470d-4c59-96df-2460af495118` contains two maker legs:

| Maker leg | Janus quantity | Effective Janus price | Janus collateral |
|---|---:|---:|---:|
| Opposite-outcome BUY at .65 | 6 | .35 | $2.10 |
| Same-outcome SELL at .3599999712000023 | 4.166667 | .3599999712000023 | approximately $1.50 |

The $3.60 budget was spent on 10.166667 shares. Average fill price excluding fees is approximately
`3.60 / 10.166667 = .354098349`; the top-level CLOB trade `.35` is not that average. The nominal
`original_size=10` does not contradict the actual fill. The prior F15 regression asserted only
SDK arguments and therefore never tested the exchange semantics that caused the breach.

## Local behavior

- The real transport rejects BUYs before signing or posting. Adapter-level checks reject
  unknown transport cap semantics too. There is no environment/configuration bypass. SELL
  protection retains its share-denominated sent-asset cap and is still subject to its existing
  clearance and authority.
- The coordinator preserves authoritative overfill quantities, records `ORDER_OVERFILL`,
  latches live, and retains an in-process stop if the kill filesystem write fails. Protection
  of the already-held fill can still run. The guard detects late overfills from durable order
  totals and retries a failed latch. The watchdog exposes the flag even when exposure is below
  the registered dust threshold or the position has since settled.
- Protective quantities floor to venue share precision; cumulative hedge buys remain within
  the original plan quantity across partial-fill retries and guard reruns. Under the observed
  10-share plan, the repaired machine buys at most 10 Kalshi shares and retains the .166667
  first-leg residual with the overfill stop. It cannot create a 10.17-share second leg.
- Authenticated taker-stream averages use maker quantities, asset identities, and sides.
  Opposite-outcome matching converts the maker price through `1 - price`. Missing/inconsistent
  maker evidence preserves the fill quantity with no average; protection then uses its
  conservative planned BUY limit. This avoids understating first-leg cost from a top-level
  price that describes only part of the match. Final account cash and fee authority are L52.

## Verification and limits

124 relevant tests passed in 2.52 seconds, including frozen F15 order/trade replay, installed
SDK amount encoding, prewire refusal across FAK/FOK/GTC and precision boundaries, taker/maker
quantity separation, mixed-maker VWAP, immediate and polled overfill alarms, late-fill alarms,
downward fractional hedging, cumulative hedge-cap enforcement, kill-write failure handling,
and a firing watchdog alarm. `git diff --check` passed. Existing protocol tests use an explicit
scripted fake transport to exercise historical response paths; the real transport is tested
without any signer/client, proving those boundaries are never reached on BUY.

Expected EV effect: prevent unapproved quantity and excess hedge spend. Entry blocking also
removes current live fill opportunities; the resulting opportunity cost is unmeasured. A usable
venue-enforced share cap requires new evidence and review before release. These tests establish
local refusal and protection behavior, not a working live BUY route or permission to resume F15.

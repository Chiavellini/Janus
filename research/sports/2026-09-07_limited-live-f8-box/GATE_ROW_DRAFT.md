# Draft GATE_TO_LIVE amendment row for the operator (2026-09-07)

Not yet in `GATE_TO_LIVE.md`. The row is the operator's decision in the operator's words; the
agent drafted the consequences and the caps and does not write the row, the override, or the
mode switch. To adopt it: approve or amend the caps, then it is appended to the amendment log
with the date, and the two pastes below are the operator's.

| 2026-09-07 | **Small real trading on every enabled league, from the Ashburn box.** Operator statement, verbatim (2026-09-07): *"we should start testing actual fills on actual live events (eventhough small)"*. Caps for the pilot, proposed by the agent and approved by the operator with this row: **$12 stake per order, 25 contracts, $60 notional a day**, the realised-loss breaker at **$25**, `min_net_profit_usd` 0.10 (from 0.50), the 1% locked-return floor unchanged. The box executes; the Mac stays paper (F5). This row overrides two earlier consequences with measured facts: the 2026-09-04 paper-only clause (both proofs have settled 7 of 7; F5 stands at 34 of 37 paper covers, all hedged) and L34's OBSERVATION_HOST consequence for the box (the box is faster than the Mac to both venues: Kalshi 51 vs 184 ms, CLOB 184 vs 309 ms, and the Mac that ran the proofs has paged to death twice). Ledger F8 is the row that reports it: STOP on one unhedged real leg; the first three covers reconciled by hand. Caps may only be raised by a later dated row here. | Known at the time: no edge has been shown on clean data (L40: 15 clean prints of 292; three paper covers settled +$3.02 net); the pooled slippage pin is 4c pending L41; the box's Kalshi shard 0 holds $41.24, shard 3 (tennis) $22.43, the Polymarket account ~$93 pUSD. |

## The operator's two pastes (after the row is in the file and committed)

```bash
bash ops/box/write_override.sh "I approve live trading at small size on all live events the lane covers, from the box, at \$12 per order, 25 contracts and \$60 a day, with the realized-loss breaker at \$25."
```

```bash
bash ops/box/mode.sh LIMITED_LIVE
```

The override pins the box's running sha and its `limits.toml` sha; any later `ops/box/update.sh`
invalidates it and the lane refuses to start in LIMITED_LIVE until it is rewritten.

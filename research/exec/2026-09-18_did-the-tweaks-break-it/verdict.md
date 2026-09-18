# L150 verdict — `DETERIORATION_REAL_AND_LOCALISED` (marginally real; the locus is ATP tennis and the hedge)

**The operator's claim holds, on the arbitrage part alone, but only just — and the cause is not a
loosened entry rule.** Read-only queries against the box's tuple store; nothing was written, traded,
armed or changed.

## 1. The system has made almost nothing from arbitrage

| | covers | total |
|---|---|---|
| **Arbitrage part** (`cover_usd`, both legs hedged) | 25 | **+$0.812** |
| Directional part (`directional_usd`, hedge unfilled — a naked bet) | — | **+$3.365** |
| Realised total | 25 | +$4.178 |

**Four fifths of the lane's lifetime profit came from positions whose hedge did not fill.** That is
not the strategy working; it is an unhedged bet that happened to win, and it is what the protection
layer exists to prevent.

## 2. The deterioration is real, and it is marginal

Arbitrage part only, per settled cover:

| period | covers | total | per cover |
|---|---|---|---|
| through 2026-09-09 | 9 | +$4.159 | **+$0.462** |
| 2026-09-10 onward | 16 | −$3.347 | **−$0.209** |

Event-clustered bootstrap of the difference, 10000 resamples, seed 180924: **95 % interval +$0.0105
to +$1.3708.** It excludes zero, so the drop is distinguishable from this sample's variance — but the
lower bound is one cent. One cover landing differently would put zero inside it. It is real evidence,
not a proof, and it must not be quoted as one.

## 3. The entry rule did NOT loosen — the hedge stopped cooperating

Per contract, from each execution's own recorded plan against its fills:

| | planned edge | actual edge | first-leg slip | hedge slip |
|---|---|---|---|---|
| through 09-09 | +6.0c median | **+9.0c** | −0.6c | **−3.0c (in our favour)** |
| 09-10 onward | +4.3c median | **+2.5c** | 0.0c | **+2.1c (against us)** |

The lane is still *selecting* roughly the same edge it always did (6.0c → 4.3c median). What changed
is what the hedge actually costs: early hedges filled about 3c BETTER than planned, later ones about
2c WORSE — a swing of roughly 5c per contract, which is larger than the entire edge being selected.
This is the same mechanism L-earlier recorded (hedge slippage dwarfs the entry margin, and entry
never prices it); what is new is that it was briefly working in the lane's favour and no longer is.

## 4. The loss is concentrated in one league

Arbitrage part only:

| league | covers | total | per cover | directional |
|---|---|---|---|---|
| elc (soccer) | 2 | +3.605 | +1.803 | 0 |
| mlb | 6 | +1.478 | +0.246 | −1.056 |
| itf | 4 | +0.774 | +0.194 | 0 |
| lal | 1 | +0.180 | +0.180 | 0 |
| ita | 1 | −0.208 | −0.208 | 0 |
| wta | 1 | −0.477 | −0.477 | +0.463 |
| nfl | 1 | −0.877 | −0.877 | −0.262 |
| **atp (tennis)** | **9** | **−3.662** | **−0.407** | **+4.220** |

**ATP is the whole loss**, and its +$4.22 of directional luck is exactly what hid it. Strip the naked
bets and the lane's nine ATP covers lost $3.66 between them, while soccer and baseball made money.

## 5. What this does and does not establish

- It does NOT show that a specific tweak broke the economics: the planned edge is roughly unchanged
  across the whole period, so no loosening of the entry rule is visible in these 25 rows.
- It DOES show the lane's arbitrage has earned approximately nothing over its life, that its apparent
  profit is unhedged luck, and that the later period is worse than the earlier one.
- Per-league samples are tiny (elc n=2). "Trade only soccer" is NOT established by this. The one
  substantial signal is ATP at n=9.
- Fees could not be attributed per cover for the early period: those orders carry no `execution_id`,
  so the early fee figures are missing rather than zero. Fee-per-contract comparisons across the two
  periods are therefore not made here.

## 6. What follows

The obvious next question is whether the hedge's adverse fill is a property of the market (thin
tennis books) or of the lane's own hedging behaviour, and whether restricting leagues by measured
hedge quality turns the arbitrage positive. That is a separate registered row, and it is a better
use of money than F24, which would spend real capital to re-measure what these 25 covers already say.

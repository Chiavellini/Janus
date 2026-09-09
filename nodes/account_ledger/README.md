# Account ledger

Cent-exact reconciliation of venue statement activity. The input is an append-only list of source
lines with unique ids; dollar amounts are decimal strings and are converted to integer cents.

`REALIZED` rows are terminal trade cash flows or venue-reported P&L. `OPEN_POSITION` rows are cash
spent on positions that have not settled. `FUNDING` rows are deposits or withdrawals. The summary
keeps all three scopes separate and defines trading cash flow as realized plus open-position cash
flow. Balances and funding are never inferred from P&L, and model fees are never substituted for a
venue statement line.

This node imports no grid. A workbook or operator command may import it; execution code does not
depend on presentation artifacts.

`statements.py` parses raw Polymarket activity cash amounts and Kalshi settlement records using
`Decimal` without discarding subcents. It checks the archived response SHA256 and constructs
stable venue identities; duplicate identities fail. Polymarket `usdcSize` is used directly,
including cash fees, and is never replaced by `size * price`. A transaction may settle several
tokens, so its hash alone is insufficient as a source identity.

These imports deliberately retain distinct `TRADE_CASH`, `REDEMPTION_CASH`, `FUNDING` and
`SETTLEMENT_PNL` totals. Trade cash flow becomes realized P&L only after a separate, complete
terminal-position reconciliation. Kalshi settlement records do not alone prove completeness
of all account disposals. Existing cent-only screenshot controls remain unchanged; never round
raw venue lines into that format. `present_cents` sums no rows: callers sum exact amounts first,
then present the total with `ROUND_HALF_UP` (half away from zero).

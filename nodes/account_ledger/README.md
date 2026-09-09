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

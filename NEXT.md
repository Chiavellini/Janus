# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-09 after the F15 STOP and the reviewed L52-L56/F18 release candidate.
CHECKLIST.md is the state list; CHANGELOG.md and the F rows in `snooping_ledger.md` are the
append-only history.

## Where it stands

**F15 is STOPPED on the Mexico box** (`i-0a8c073c72dcdae11`, `mx-central-1a`). At 09:33:10Z the
operator-side audit confirmed that a nominal 10-share Polymarket BUY returned 10.166667 shares and
the coordinator hedged 10.17, violating the signed 10-contract cap. The same Maximus execution was
stored about 4.226 cents too high. `kill/live` is deliberately latched. The old `64f54c7` observer may
remain active, but no new first leg may clear; do not clear the kill. F17 produced no evaluation and
is superseded before start. The local F18 candidate restores only a post-only GTC maker-first
Polymarket BUY route; immediate, FAK/FOK and non-post-only BUYs remain blocked. It is fully tested and
reviewed and staged on the Mexico box. Its share cap relies on Polymarket's documented
post-only maker guarantee; the unsigned operator instruction is an explicit venue trust boundary.

L56 preserves the historical execution records while providing append-only, source/hash/operator-
bound dispositions for the two proof fills, five overfills and the one legacy false post-only label.
Only a complete authenticated guard may resolve their exact flag IDs; no class-wide timestamp clear,
P&L rewrite or kill clear is performed. The actual PM account's positive token remnants remain in the
physical position feed. For this narrow incident gate only, a complete fresh paginated read may prove
zero current economic exposure when every token is uniquely account-bound, venue-redeemable, exact
zero value/price and non-contradictory. Unknown or valuable holdings remain a BLOCK.

The arm remains **$12 combined stake, 10 contracts per leg, $250 committed daily notional, $25
realized-loss breaker, $0.10 minimum net profit, 1% locked return, $1 maximum protection loss,
`protect_auto=true`, `unwind_enabled=false`**. Do not raise these caps from coverage work: the new
settlement evidence removes false blocks but supplies no evidence that larger orders preserve EV or
fill quality.

The cent-exact two-screenshot baseline remains **+$10.39 realized trading P&L** and **+$6.67 visible
trading cash flow at that screenshot cutoff**, excluding the +$205.35 external deposit. It is an
acceptance fixture, not a current account total, because the screenshot boundary is not source-bound.
Maximus is no longer open: venue-authoritative cash and settlement prove exact P&L **-$0.318760**
(-$0.32 presentation), versus stored -$0.2765. L52 cash-controls complete Polymarket activity exactly,
separating $407.031089 net funding from -$95.424133 trading cash to authenticated cash $311.606956;
it observes no economically open PM position and no Kalshi position. The source-complete
2026-09-07-to-snapshot subtotal is **+$11.167973**, but it must not be added to the screenshot figure.
The current/lifetime total is withheld until the screenshot boundary and older Kalshi settlement or
disposition history are complete. Any unexplained discrepancy of at least one cent remains a STOP.

## Coverage prepared locally

The reviewed F17 candidate removes the broadest legitimate coverage blocks without substituting
one league's settlement evidence for another:

- **NFL:** 2/2 currently co-listed games pass exact schedule, current rules-template, and settlement
  checks. No cap or template block remains in the local tree.
- **MLS:** 14/14 currently co-listed games pass. L43 measured all 510 original 2025 regular-season
  fixtures, registered conservative cancellation/delay bounds, and binds every proof to an exact
  ESPN regular-season game ID. Preseason, postseason, unknown populations, and unsupported schedule
  sources still fail closed.
- **ITF:** 205/215 current games are co-listed and locally eligible. L46/L47 use a fresh, atomically
  archived 339-page catalog and independent main-draw/qualifying upper bounds. The remaining current
  PM-only games have no Kalshi leg, so they are not cross-venue arbitrages.
- **Eredivisie:** the current 48-hour harvest has 1 schedule game, 1 co-listed and 0 blocked. L50
  independently replayed all 306 regular-season fixture histories and completions and registered
  conservative bounds from 7 delays beyond 48 hours and 0 cancellations. Exact ESPN
  regular-season/game-ID identity is mandatory; playoffs and unknown populations remain blocked.
- Tennis and soccer entity repairs remove verified aliases/cross-references while preserving true
  ambiguity. Estoril and Estrela are now distinct and reseed-safe. A real Sevilla-Valencia schedule
  conflict remains blocked rather than widening time tolerance.

Ligue 1, Portugal, Scotland, and Belgium remain blocked where their own immutable
original-schedule populations are incomplete. MLS evidence is not transferred to them. NBA, WNBA,
and NHL currently have no paired games: NBA has 3 future Kalshi games and no PM moneylines; WNBA
has 23 future PM moneylines and no Kalshi games; NHL has 102 future PM moneylines and no Kalshi
games. Their actual one-sided rule texts are archived, but counterpart review begins only when both
venues list the same game. A one-venue-only listing can never be made into a pure two-leg arbitrage.

## What changed in F17

Rules-template identity now preserves economically substantive numbers, relative deadlines,
absolute deadline dates, clocks, and time zones, preventing silent collisions such as 7 versus 14
days or 50-50 versus 60-40. Discovery carries the certified schedule population into the settlement
proof. An enabled league with no effective cap now raises a risk/watchdog alarm. The box runner uses
a unique temporary script, removing a concurrent-run race. Failed L42/L44/L45/L49 research attempts
remain preserved; only the independently replayed L43/L46/L47/L50 results register evidence.

L51 measured the live worker at about 97.6% of its only vCPU, with 17–25 seconds of venue timestamp
backlog. The local projection cache reduced the sampled Kalshi reader's CPU by 25–29% in two
independent runs while preserving all 19,998 projected books and final health/timestamp state.
Capture gzip level 3 used about 58% less compression CPU with exact frame/timestamp round trips at
25–34% more storage. These are verified offline improvements, not yet a claim about live CPU.

## Immediate next step

The append-only historical manifests are confirmed and the authenticated stopped-lane 72-hour guard
resolved their exact IDs with zero orphan, mismatch, protection need, open order, unreleased capital
or current economic exposure. Keep `kill/live` latched until the operator uses the repository's daily
release paste to re-sign the unchanged arm. Then verify fresh Kalshi, Polymarket market and PM user
streams/clocks before clearing only the reviewed live latch.
The first three covers require hand reconciliation before the fourth. Stop on any cent
discrepancy, non-maker fill, cap breach, late cancel dispatch, protection delay beyond 30 seconds,
orphan, mismatch, missing reservation, post-submit store error, fee above pin, breaker, or stream
alarm. Exact commands and actor boundaries are in
`research/exec/2026-09-09_historical-proof-dispositions/operator_runbook.md`.

The next profit-relevant evidence is per-league executable fill rate and realized net EV under the
unchanged small arm. Coverage creates access, not evidence of profit. Do not raise caps until forward
fills show that executable depth, hedge latency, slippage, and settlement reserves preserve positive
net EV and per-trade Sharpe.

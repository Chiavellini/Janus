# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-09 09:18 UTC from the F15 box diagnosis and the reviewed F17 coverage/performance pass.
CHECKLIST.md is the state list; CHANGELOG.md and the F rows in `snooping_ledger.md` are the
append-only history.

## Where it stands

**F15 remains LIMITED_LIVE on the Mexico box** (`i-0a8c073c72dcdae11`, `mx-central-1a`) on
executable commit `64f54c7`, code tree `0fd7f6eae72cfb98`. The process is active and observing the
current slate, but the watchdog is **ALERT**: the Kalshi socket is flapping with 13 keepalive-timeout
errors across nearly every recent health row. F17 must not be released until this is green. The local
reviewed F17 tree is not deployed and has not changed the arm, submitted an order, or mutated box state.

The arm remains **$12 combined stake, 10 contracts per leg, $250 committed daily notional, $25
realized-loss breaker, $0.10 minimum net profit, 1% locked return, $1 maximum protection loss,
`protect_auto=true`, `unwind_enabled=false`**. Do not raise these caps from coverage work: the new
settlement evidence removes false blocks but supplies no evidence that larger orders preserve EV or
fill quality.

The cent-exact two-screenshot baseline is **+$10.39 realized trading P&L**. It excludes the
**+$205.35 external deposit** and keeps the still-open **-$3.72 Maximus Jones** position separate;
including that open cash outflow gives **+$6.67 visible trading cash flow**. These values are now
explicit ledger acceptance tests. They are a verified historical baseline, not a claim about the
account after later F12-F15 executions. The previous +$8.20515/+7.94929 figures in this file are
retired because they did not reconcile the operator's screenshots. F16 requires venue-authoritative
statements and a hand reconciliation of its first three covers; any discrepancy of at least one
cent is a STOP.

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

The candidate is fully tested locally and F17 is preregistered. Wait for a clean Kalshi socket and
fully green guard/watchdog, verify zero flight/imbalance/unhedged exposure, then release the exact
committed tree with a matching re-signed arm. Hand-reconcile the first three valid F17 covers before
the fourth. Stop on a cent discrepancy, protection delay beyond 30 seconds, orphan, mismatch,
missing reservation, store error after submission, fee above pin, breaker, or socket alarm.

The next profit-relevant evidence is per-league executable fill rate and realized net EV under the
unchanged small arm. Coverage itself is not profit evidence; caps may rise only after forward fills
show that depth, hedge latency, slippage, and settlement reserves preserve positive net EV.

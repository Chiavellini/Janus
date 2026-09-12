#!/usr/bin/env python3
"""The two thresholds, as importable constants (GATE_TO_LIVE step 4 rebuilds every decision by
importing the runner's own constants -- these are them).

    discovery   gross edge > DISCOVERY_MIN_GROSS_EDGE            -> DISCOVERED is recorded
    execution   locked return >= EXECUTION_MIN_LOCKED_RETURN
                and net profit >= EXECUTION_MIN_NET_PROFIT_USD    -> PROFITABLE_UNEXECUTED

Recording every positive theoretical candidate and executing only past a safety margin is the
spec's rule (§7). The risk node applies the execution pair again at clearance, from its own
limits file, so neither side can drift alone.
"""

DISCOVERY_MIN_GROSS_EDGE = 0.0
#: 0.01 -> 0.005 on 2026-09-12 (GATE row of that date). The operator: "even 1 percent edge is
#: excellent edge; hell even 50 bps is excellent". The 24 h to 06:20Z showed 71 game-seconds of
#: after-fee covers between 0.5 % and 1 % against 313 at or above 1 %; the fee is the venue's own
#: reported schedule, so a locked 0.5 % is a locked 0.5 %. `nodes/risk/limits.toml
#: min_locked_return` moves in lockstep; nodes/risk/tests checks the two agree.
EXECUTION_MIN_LOCKED_RETURN = 0.005
#: Lowered 0.50 -> 0.10 on 2026-09-08 to match `nodes/risk/limits.toml min_net_profit_usd`, which
#: the operator lowered for the $12 pilot on 2026-09-07. While the two disagreed THIS constant was
#: the binding one -- it decides whether an opportunity is labelled PROFITABLE_UNEXECUTED at all,
#: and only that status reaches `_execute` -- so the risk file's 0.10 was unreachable and every
#: cover between $0.10 and $0.50 was dropped to DISCOVERED before the risk node ever saw it.
#: 0.10 -> 0.05 on 2026-09-12 together with the return hurdle: at 25 contracts a 0.5 % cover nets
#: about $0.06, so a $0.10 floor would have refused every cover the new hurdle admits.
EXECUTION_MIN_NET_PROFIT_USD = 0.05
STRATEGY_VERSION = "v1-taker-taker-moneyline"

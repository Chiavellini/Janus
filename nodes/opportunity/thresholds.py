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
EXECUTION_MIN_LOCKED_RETURN = 0.01
#: Lowered 0.50 -> 0.10 on 2026-09-08 to match `nodes/risk/limits.toml min_net_profit_usd`, which
#: the operator lowered for the $12 pilot on 2026-09-07. While the two disagreed THIS constant was
#: the binding one -- it decides whether an opportunity is labelled PROFITABLE_UNEXECUTED at all,
#: and only that status reaches `_execute` -- so the risk file's 0.10 was unreachable and every
#: cover between $0.10 and $0.50 was dropped to DISCOVERED before the risk node ever saw it.
EXECUTION_MIN_NET_PROFIT_USD = 0.10
STRATEGY_VERSION = "v1-taker-taker-moneyline"

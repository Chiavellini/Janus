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
EXECUTION_MIN_NET_PROFIT_USD = 0.50
STRATEGY_VERSION = "v1-taker-taker-moneyline"

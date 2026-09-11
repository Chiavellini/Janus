# F20 observation 1 — bounded taker execution during failed clear

Observed execution: `0b425cbe71cb4ca1a919fda622538a07`  
Event: `pm:wta:997437`, Jacquemot v Tikhonova  
Runner: `d3237faa3c1ec50590d58dfcd69ebbda78b280f0`

This order entered during the unsafe interval after the old release script removed `kill/live` and
before its post-start health check failed and restored the kill. It was not evidence that the final
release sequence completed.

Polymarket filled a request for 10 contracts with 10.763158 shares at authoritative average
0.3799999963 and fee $0.12679. That sub-one excess was within the pre-wire bounded-taker record.
Kalshi returned five zero-fill hedge attempts before filling 10 at 0.64 with fee $0.1613. Timings
were 15.24 ms to submit the first leg, 1,019.81 ms to its acknowledgement, 2,143.28 ms to settled
first-leg quantity, 4,571.50 ms to the final hedge submit, and 4,771.32 ms total. Local pre-machine,
database and evaluation-to-execution time were 3.14 ms, 33.22 ms and 59.08 ms respectively; the
dominant delay was venue/order lifecycle plus repeated hedge misses, not Python computation.

The paired 10-contract cover locked a $0.4775 loss after protection crossed the original
break-even level. The 0.7632 residual happened to settle on the winning PM side for +$0.4626,
leaving realized P&L of -$0.014932. It is now RECONCILED and released; all seven owned orders are
terminal/cash-final, both positive fills have final authoritative FIFOs, the settlement is final,
and the reservation is released.

This is one adverse protection/latency observation, not evidence to lift caps or claim positive
F20 EV. It counts as F20's first reconciled cover before the registered fourth-cover boundary.

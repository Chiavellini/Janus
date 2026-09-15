# L141 verdict — 108 signal windows were not 108 safely takeable prints

The exact registered 24-hour window contains 108 included execution records: 95 `BOOK_MOVED`, ten
authoritative terminal zero fills, and three complete covers. They span 15.34 hours from the first
to the last execution record. The registered scalar-settlement execution is the one excluded row.

The 95 pre-wire declines are not 95 independent games. They collapse to 35 events and 49
opportunity identities; an event appears a median two times, p90 eight, and as many as thirteen.
Nevertheless, the sizing series gives each execution its own active signal window, so it is fair to
call the denominator 108 distinct selected windows. It is not fair to call them 108 fills the venue
would have accepted at the signed economics.

Every `BOOK_MOVED` row has structured fresh venue confirmation. Ninety failed the Polymarket
first-leg price/depth check: the REST-confirmed marginal price exceeded the cleared limit by 6c at
the median, 10c at p90, and 13c at maximum. The other five still passed the first-leg check but the
fresh Kalshi hedge exceeded break-even by 1.88c at the median and as much as 5.64c. Therefore none
of the 95 has evidence for a conversion that preserves both-leg depth, fees, settlement proof,
hedge allowance, and the existing caps/hurdles. Sending them anyway would turn an execution metric
into unpriced directional risk.

The planned first leg came from the Polymarket websocket in all 95 cases. At execution start that
book was already 548 ms old at p50 and 810 ms at p90; fresh confirmation completed another 180 ms
after start at p50. The machine-only stages are much smaller: frame-to-evaluation 1.66 ms,
evaluation-to-executor 32.09 ms, worker hop 5.59 ms, clearance 5.55 ms, and database work 8.14 ms at
p50. The direct execution target is therefore the roughly 0.7-second websocket-to-venue-authority
gap, not ordinary Python dispatch. This row does not prove that removing the confirmation would
recover it: historical direct sends had poor fill conversion, and the confirmation is what proves
the edge is gone before capital is exposed.

The correct observed order conversion is three fills from thirteen submitted Polymarket first-leg
orders, or 23.1%. Three covers from 108 selected windows is 2.78%. Thirteen submitted orders are too
few to distinguish a true one-third order conversion rate, but the operator's proposed 36 safe
fills from these 108 windows is contradicted: no declined row has a safe executable
counterfactual.

The profit arithmetic also does not close at 36 covers. The three covers earned $0.82908 after
$1.40092 total fees, an average $0.27636. At that mean, 36 covers produce $9.95. Removing the exact
$0.60932 of Polymarket fees raises the projection to $17.26; even removing both venues' fees raises
it only to $26.76. At the observed economics, $100/day requires roughly 362 covers; with only the
Polymarket fee removed it still requires roughly 209. More conversion and maker fees help, but they
are not jointly sufficient at the present edge and size.

Verdict: PASS as a complete descriptive accounting; CONTRADICTED for one-third of all selected
windows as a safely executable claim; NOT IDENTIFIABLE for a one-third submitted-order fill rate.
No production state or policy changed.

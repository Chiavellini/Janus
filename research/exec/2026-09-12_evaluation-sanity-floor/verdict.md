# L88 verdict — the floor refused nothing real

Date: 2026-09-14. Read-only, from the box's own `stream_evaluations` over the 24 h to ~07:00Z,
under the deployed sha `9387297`.

L88 registered an owed outcome: *"the count of BLOCKED_MATCH rows attributable to the floor, and
whether any of them, inspected by hand, was a genuine cover."* It went unread for two days. This
is that reading.

## The split

`BLOCKED_MATCH` is 1,030,275 rows in the window — 64% of all 1,634,515 evaluations, which is what
drew attention to it. Split by the discriminator L98 left in `legs_json`:

| bucket | rows | share | avg `cents_from_actionable` | gross range |
|---|---|---|---|---|
| **A** — `single_venue` (L98's control) | **1,029,973** | **99.97%** | +7.97 | 0.93 – 1.94 |
| **B** — refused by `MIN_CREDIBLE_GROSS` | **302** | **0.03%** | −30.77 | 0.60 – 0.6972 |

1,029,962 rows carried the control tag, so the box is on the post-L98 release and bucket A is a
real reading rather than an artefact of the tag being absent.

## The answer to the registered question

**No genuine cover was refused.** All 302 bucket-B rows are **one La Liga fixture**,
`espn:lal:401882879`, at gross 0.60–0.6972 and claiming **37–38% locked returns** across every
quantity rung. That is exactly the phantom class the floor was minted for: a three-way market whose
legs do not span the outcome set, so the gross falls far below the ~$1 a true partition must cost,
and the apparent return is an artefact of the missing leg rather than an edge.

Two independent reasons to believe it, beyond the gross:

- **`cents_from_actionable` averages −30.77c** on these rows. The fee-aware distance to actionable
  says they are nowhere near tradeable either, by a measure that does not use the floor at all.
- The richest cover this lane has ever **settled** was planned at 16.7% (`0dfc6df3`, gross ~0.83,
  which paid +$0.38). A 37% locked return is more than double anything real that has ever cleared,
  and the floor's own comment set 0.70 to admit every real edge on record "with better than twice
  the headroom".

## What this does not say

It does not vindicate the *name*. Bucket A is 99.97% of the bucket and is not an identity failure
at all — `single_venue` means the cheapest cover **of any shape** cost at least a dollar, which is
the strongest no-edge statement the lane can make. Reported as `BLOCKED_MATCH` it reads like a
coverage problem and keeps drawing attention that belongs on the sign. Together with `NO_EDGE` it
is 82.6% of all rows correctly saying there was nothing there.

Nor does it license lowering the floor. The measurement says the floor cost nothing over one day on
one slate; the class it refuses is real and was reported at 201% before it existed. L88's own
instruction stands: *"Raise it only with evidence of a genuine cover it refused; lowering it
re-opens the phantom class."*

**Verdict: the floor is free at this threshold, and the owed count is 302 in 24 h, all phantom.**

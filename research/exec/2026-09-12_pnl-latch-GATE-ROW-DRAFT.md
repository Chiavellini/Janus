# GATE_TO_LIVE row, DRAFT — not authorised, not enabled

The operator asked on 2026-09-12 that a run of losing covers should not merely alert but **latch the
live kill automatically**. That is a new automatic trading control, so it needs a dated row in
`GATE_TO_LIVE.md`'s amendment log in the operator's own words. L93 shipped the detection and the
alert only; nothing latches.

What exists today (L93, `nodes/risk/health.cover_pnl_alerts`), alert-only:

- `COVERS_LOSING` — at least `PNL_MAX_LOSERS` (4) of the last `PNL_WINDOW_COVERS` (10) settled real
  covers lost money; reports the window's net.
- `HEDGE_ABOVE_BREAK_EVEN` — at least `PNL_MAX_BELOW_BREAK_EVEN` (3) of that window settled above
  their own break-even.

Measured against the box on 2026-09-12: the last 10 real settled covers were net **−$3.55** with
**8 losers** and **6 above break-even**, so both conditions were already true and unreported.

Suggested row text, for the operator to edit into their own words and date:

> 2026-09-0X: a run of losing covers latches the live kill without waiting for the daily breaker.
> When N of the last M settled real covers lost money, the lane latches `kill/live` and stops real
> entry until a human clears it, exactly as an overfill or a protection failure does. The daily
> realized-loss breaker at $25 is unchanged and remains the outer bound. N = __, M = __.

Two things the operator should decide explicitly before signing:

1. **N and M.** At 4-of-10 the current data would have latched immediately. At measurement size
   ($6/order, 5 contracts) a losing cover costs cents, so a tighter N is cheap; at full size it is
   the difference between stopping after four covers and after twenty-five.
2. **Whether a *settled* window is fast enough.** Settlement can lag the trade by hours, so this
   latches after the fact rather than in flight. A same-session signal would have to read
   `ABOVE_BREAK_EVEN` at HEDGED time instead, which is a different (and more aggressive) control.

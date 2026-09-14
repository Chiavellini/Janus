# Parity evidence for L108

The documented gate `9f41923b8cf055a1` is **stale** — it predates L95–L103, which deliberately
changed evaluation rows (L98 reversed a sign, L99 snapped limits to tick, L101 stopped pricing
stale books and says in its own row to expect the actionable count to FALL).

Measured today with `research/infra/2026-09-12_loop-waste/measure.py`, which replays 20,000
captured frames through the full pipeline:

| tree | ladder | evaluation rows | rows_digest | selections_digest |
|---|---|---|---|---|
| `e297f7d` (the branch point) | (5,10,25,100) | 2,271 | `738ef6b0fee1d25e` | `4f53cda18c2baa0c` |
| this branch, ladder temporarily restored | (5,10,25,100) | 2,271 | `738ef6b0fee1d25e` | `4f53cda18c2baa0c` |
| this branch as shipped | (5,10) | 1,093 | `13e4fb08a76c920f` | `4f53cda18c2baa0c` |

The first two rows are the point: at the **same** ladder, L104, L105 and L108's instrument repairs
reproduce the branch point **exactly**. L106's ladder is this branch's only behaviour change, and
it is registered as such. L109, L110, L111 and L112 were each re-run against the third row and
moved nothing.

Raw runs, in `research/infra/2026-09-12_loop-waste/`:
`results_offline_s0-after.json`, `results_offline_l108-ladder-restored.json` (the second row above,
run with the pre-L106 rungs), `results_offline_l109.json`, `results_offline_l110-l111.json`,
`results_offline_l112.json`.

The `e297f7d` figure was taken in a throwaway detached worktree, since the branch point is not
checked out anywhere; `median_cpu_s` differs between rows only because a shorter ladder evaluates
fewer rungs, and is not a before/after claim.

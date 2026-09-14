# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-14 ~09:00Z, on `claude/hedge-safety-and-speed` (branched from
`claude/hedge-ladder-speed-3b5042c`).

## Where it stands

**Trading is still stopped and should stay stopped until the release below is pasted.** `kill/live`
is latched; the lane is up and pricing but entering nothing. The box (`i-0a8c073c72dcdae11`,
mx-central-1, c7g.medium, 1 vCPU) is healthy: up 6 days, 123 G free, load 0.8, **zero loop stalls
at or above 5 s in the last 24 h**.

The box still runs **`9387297`**. Everything below is committed and **undeployed**, including
`c5f6da4` (L101/L102/L103) which was already waiting when this session began. Suite green at
**1,558**, with two pre-existing flaky tests deselected (see *Known bad* below).

## What this session did, by theme

**The hedge side was unsafe in three ways, and all three are closed.**
- **L104** — every one of 3,373 protect kill latches wrote **no audit flag**. `on_unprotected` runs
  in a worker thread and wrote through the event loop's SQLite connection, so every write raised
  `ProgrammingError` into a blind `except`. The test that covered it called the callback on its own
  thread. `raise_flag` now appears in `grid.py` exactly once and a static test keeps it that way.
- **L105** — nothing bounded the hedge submits an **execution** may make, only those one `protect()`
  call may make. Reproduced: 70 guard hand-overs sent **497 orders for 4,970 contracts** against a
  10-contract position. Two durable ceilings now bound it, counted from `hedge_client_ids`.
- **L106** — the size ladder drops to a **10-contract ceiling**, measured rather than felt: q=10
  keeps **516 of 590** actionable prints/24 h and loses **none** to the $0.05 floor, while q=5 loses
  23% of the surface and removes no further overfill latch. Of eleven real overfills, five exceed
  the one-contract accepted excess at q=25 and only two at q=10.

**The speed work found the target was somewhere else entirely — twice.**
- **L107** decomposed the 2,480 ms path for the first time. **L108 corrects it**, along with two
  other numbers and two broken instruments: stage stamps are cumulative and were differenced as
  medians; `socket_health.frames` is cumulative and was summed as a rate; `b_submit_ms` was stamped
  *inside* the chase loop so it recorded the **last** attempt under a name everyone read as the
  first; and `protect_existing` re-bases `_t0`, so guard re-run rows mix two clocks.
- **L109** — the chase bought the same Kalshi orderbook **twice, microseconds apart**: L75's
  post-zero-fill read `break`s, which skips the sleep, so the budget phase re-read it immediately.
  ~190 ms, proven behaviour-neutral on the registered MORIYA schedule.
- **L110** — the settlement pass held the database's **single write lock across its whole backlog,
  on the event loop**. This is the 2026-09-08 GEA V ZANDSCH incident from the other side. `db_ms`
  max is 37,386 ms. It commits per item now.
- **L111 — the largest finding of the session.** `CLOCK_UNHEALTHY` is overwhelmingly **our own loop
  lag wearing the venues' name**, and while it fires the lane prices *nothing* — `best_cover` is
  unreachable, so an arbitrage inside the window is never computed and can appear in no histogram
  of orders sent. Over 7 days: at 0–1 s of lag the median offset is 0.118 s and 0.5% of ticks read
  unhealthy; at 2–3 s, 7.564 s and 47.6%. Monotonic, entirely **below** the 5 s halt bound, and
  48.9% of unhealthy ticks name **both** venues at once. Today's lag p90 is 2.003 s.
- **L112** — nothing recorded what the Polymarket account channel delivers, so its perfect health
  figures were unfalsifiable. Per-kind counters now, with the verdict rule registered in advance.

**And then the operator asked the question that matters: what moves us toward $100/day.**
- **L113** — the largest attrition in the funnel was readable only by grepping journald. Both
  refusal channels ended at `print()`, and nothing joined prints → orders → covers. Counted now, as
  **counters flushed per report tick, never a row per refusal** — a row apiece is what put 24.7 GB
  in `sizing_decisions` and helped fill the disk on 2026-09-11. Plus `ops/funnel_report.py`.
- **L114** — an event yielded **one cover, ever**: the capital reservation blocked re-entry until
  both venues settled, hours later. At ~40 co-listed events a day that alone caps the lane near
  **40 covers/day ≈ $8-20/day**, which is the same order as `GATE_TO_LIVE`'s independently measured
  "about $20 a day" bound on the whole surface. The lock now ends at the hedge; the capital stays
  committed and every notional cap keeps counting it.

## What to do next, in order

1. **Release. One paste, one frozen tree.** `bash ops/box/release.sh <sha>`. The arming override
   pins the code tree, so every change costs a paste anyway — and the L102 sample needs one tree to
   be homogeneous. **Do not release again until ~50 orders have accumulated.**
2. **The overfill acknowledgement for `0429ef24`**, or the kill re-latches on every restart: the
   guard re-finds it from `orders` on each fresh process and its only dedupe is an in-memory set.
3. **Clear `kill/live` on the box.** `ops/box/kill.sh live --clear` removes only SSM-sourced
   latches; a `protect:`/`guard:` latch must be removed on the box itself.
4. **Then read three things**, and nothing else matters until they are read: the **L102 verdict**
   (the query still needs writing — see below), the **L112 kind counts**, and
   `ops/latency_report.py --since <release>`, whose per-row segment table is now the primary one.
5. **Owed, and not yet done:** the L102 verdict query; the shadow protectability gate; the one-paste
   evidence-gated clear for a protect latch; redemption backoff (three of four venue calls are
   unguarded and a 429 aborts the pass before anything is journaled, on a fixed 10-minute timer
   forever, while `kernel/fetch.py` already has Retry-After, backoff and jitter the SDK bypasses).

## Still open for the operator, whenever you want them

Neither blocks the relaunch; both remove the halt a p90 slippage draw will otherwise take.

- **The unwind proofs** — `ops/box/unwind_proofs.sh`, one paste, cents of spread, waiting since
  2026-09-08. Unlocks `unwind_enabled` and gives the layer a way out other than latching.
- **A dated GATE row raising the per-contract protection allowance.** Note `max_protect_loss_usd`
  must move with it: `loss_allowance` takes the `min`, so raising the per-execution cap alone is a
  no-op — and **so is lowering the contract cap**, which is why NEXT's previous advice on this did
  not work.

## Known bad

`ops/box/tests/test_box.py::test_redemption_builder_cli_keeps_secure_value_off_argv` and
`::test_redemption_secret_pipe_gives_one_payload_per_reader_open` are **flaky at ~65% in
isolation** — a race in the secret-feeding FIFO, pre-existing and untouched. "Suite green" has not
been a reliable signal; both are deselected in verification and a task is queued.

## What not to do

- **Do not raise caps or size** until per-cover EV is measurably positive. Nothing this session
  changed the economics: median booked margin 0.67c against median hedge slippage 3.0c, p90 14c.
- **Do not quote L107's segment table** — use L108's. And do not use `9f41923b8cf055a1` as a parity
  gate; it predates L95. The `e297f7d` baseline is `738ef6b0fee1d25e` / 2,271 rows, and this
  branch's is `13e4fb08a76c920f` / 1,093 rows, moved by L106's ladder alone.
- **Do not size a segment that has no stamp in it.** Cycle 1 scoped Kalshi keep-alive as the highest
  value-per-line item; measured, it is ~3% of the path, and the hedge leg turned out to be the
  *fast* leg. The instruments were wrong four times in one session — differences of medians, summed
  cumulative counters, an overwritten stamp, a re-based clock.
- **Do not read the halt change as licence to price on stale books.** A 3 s loop lag still means 3 s
  old books; what changed is that the refusal ends when the condition does.

## On $100/day, since it was asked

**Nothing this session moved the economics**, and that is the honest headline. The arbitrage
business makes **$0.14/day**: over 7 days `COVER` rows realised +$2.25 and `PARTIAL` cover legs
-$1.28, so **+$0.98 of actual arbitrage**, while +$3.36 of the headline was directional money on
unhedged contracts — luck, not edge.

**The universe has been targeted hard, but mostly before this session** (22 leagues registered, 14
enabled, the daily census, the coverage audit, tennis/ITF, CFB labels, MLS/Eredivisie/UCL). Nothing
was added to it today.

**$100/day is not reachable on the current universe at current caps, and the project measured that
before I arrived** — `GATE_TO_LIVE.md:171`: *"Upper bound of the whole excluded band at 25
contracts: about $20 a day."* It needs roughly **10x the events, 5x the size, and a positive
sign** — all three. The measured funnel says where to look: **84% of events we can see are
Polymarket-only** (342 of 345 unpaired are `kalshi=missing`), and 1,893 actionable prints a day
converted to almost nothing. L113 makes that conversion countable for the first time; L114 removed
one of the two hard ceilings under it.

**Still open, in order:** the other ceiling (the grid's `in_flight` is GLOBAL — while any game
executes, every other game's covers are refused; it needs to be per-event with a small concurrency
bound, carefully, because it was made global to stop 6-11 s loop stalls). Then the sign, which the
slippage report says is a slippage problem and not a coverage one. Then universe, cheapest first:
CFB re-evidence (113 co-listed/48 h, the largest competition in the census), the four blocked
soccer leagues **and their missing `limits.toml` cap rows**, NBA/NHL when the seasons overlap, and
only then spreads/totals (~10x contract pairs, but it needs a market-identity axis the kernel does
not have — `line_abs` has zero producers, and `total 8.5` pairs with `total 9.5` as locked
arbitrage today).

## The question that actually matters

Unchanged, and now measurable: whether a cover's margin can exceed its hedge slippage. Everything
this session did was either safety owed before more real orders, removing the reasons the
measurement could not be trusted, or lifting a ceiling that capped the answer. The economics are
still negative and still undecided.

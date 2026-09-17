# L146 verdict — the defect reproduces in the deployed code

**Registered outcome: `DEFECT_REPRODUCED`.** All three reproductions exhibited the hypothesised
behaviour and **both controls caught theirs**, so the harness is sound.

The tested modules — `nodes/stream_polymarket`, `nodes/book_replica`, `nodes/stream_kalshi`,
`nodes/execute/plan.py`, `kernel/schema.py` — were re-checked at verdict time: byte-identical to the
deployed `59dd5ae`, with no uncommitted change under `nodes/` or `kernel/`. **This is a statement
about the code production runs.**

Every object driven was the real one. Only the Reconciler's REST fetch was substituted; nothing
under test was mocked, subclassed or patched.

## The controls

| | what happened | caught |
|---|---|---|
| **C1** — a lost update **at** the touch | drift counted, replica `RESYNCING`, `HASH_MISMATCH`, resnapshot requested | ✅ |
| **C2** — a Kalshi delta dropped | `gap` returned, replica `RESYNCING`, `SEQ_GAP` | ✅ |

C1 matters more than it looks. It is the **same kind of lost update** as R1, only at the best price
instead of below it. The code catches it at once. So what follows is specific to depth; the check
works where it looks.

## What reproduced

**R1 — phantom depth survives verification.** A book held an ask at 0.22 that the venue had removed.
Sixty agreeing updates arrived. The stream ran **60 checks, counted 0 drift, and the replica reported
no fault on any of them.** `due()` never once selected it for REST. `verified_utc` advanced to the
last update — the book was re-verified sixty times while carrying a level that did not exist.

**R2 — the size at the touch is never compared.** A local touch of 8 against a venue touch of 1:
`agrees_with` returned `True` for both. The replica kept 8, with no drift and no fault.

**R3 — a REST correction is undone by the next update.** A quiet book *was* selected, reconciled
against the truth, and handled exactly as designed: it adopted the REST ladder, was labelled
`source="rest"`, recorded `HASH_MISMATCH`, and incremented `rest_drift`. But the stream's own ladder,
`ps.books`, still held the phantom level. **One ordinary agreeing update later, the phantom was back,
the book was relabelled `"ws"`, and it reported no fault.** The correction lasted exactly one message.

## The cause, isolated

A supporting pin holds everything fixed except traffic: the same book, the same 20 seconds.

- With only socket heartbeats → **selected for reconciliation**.
- With agreeing updates below the touch → **never selected**.

The book is equally stale in both. **The only thing that keeps it out of the REST check is that
someone is trading it.**

## Direction of the error

On the constructed ladders, 25 contracts cost **20.96c** against the stale book and **21.24c** against
the truth — the phantom makes the book look **0.28c cheaper** for a buyer.

**That number is illustrative only.** It is a property of the ladders this row built. It shows the
*direction* — a stale level below the touch understates what a buyer pays, which is the adverse side
L143 and L144 measured — and must never be quoted as a production estimate.

## Fairness to the design

The exclusion of busy books is **deliberate**, and the reason is sound. `reconcile.py:9-11`:
reconciling a busy market against REST "would report timing skew as drift every few seconds." The
stream code also states its own limit plainly (`protocol.py:18-20`): the check verifies the top of
book only, "so an outside REST reconciliation is still the backstop for depth."

The defect is the gap between those two decisions, each reasonable alone. The backstop was designed
to cover depth, but the Reconciler's own filter keeps it off the books where depth matters. And where
it does run, it corrects a copy the stream overwrites. `replica.py:330` also says a quiet book
"forces a resnapshot" when it decays; nothing in the code does that.

## What this proves, and what it does not

**Proves:** the deployed stream code **can** carry a wrong level below the touch, or a wrong touch
size, on an actively traded book indefinitely while reporting it verified — and cannot durably
correct it by REST. Its only recovery is a full websocket `book` event: a reconnect, or a
drift-forced resubscribe, which a below-touch error never triggers.

**Does not prove:**
- **That it happens in production, or how often.** It requires the venue to drop or misdeliver an
  update below the touch. There is supporting evidence that levels do go missing — `protocol.py`
  records that every disagreement measured live on 2026-09-02 was "a genuinely incomplete local book"
  in which "the venue's stated best referenced a level we had never been sent" — but those were at
  the touch, where they are caught. The rate below the touch is unmeasured.
- **That it explains L143's losses.** It is the most specific mechanism found and it points in the
  right direction, but L144's one-sided result is also compatible with timing and selection effects.
  Establishing impact needs a production measurement.

## What would fix it — for a separately registered row

Three changes, in rising order of risk:

1. **Make REST corrections stick.** When `reconcile()` disagrees, write the REST ladder into
   `ps.books` as well as the replica. This only acts where a reconcile already runs, so it adds no
   new false-drift exposure — the smallest and safest step.
2. **Stop a below-touch update from verifying the whole book.** Verify only when the change touched
   the level the claim describes, or treat verification as top-of-book-only and keep a separate depth
   clock.
3. **Depth-check active books on a cadence.** This is the change that answers the timing-skew concern
   directly: compare depth with a tolerance for levels that moved during the REST round trip, rather
   than reporting every difference as drift.

Each changes `nodes/`, which the arming override pins. (2) and (3) change which books the lane will
price from, which is entry-adjacent. Any of them needs its own spec, a `PENDING` row, a dated GATE
amendment, and an operator release. **This row authorises none of them.**

## Separately: quantifying it in production

Measuring the real rate needs replay of the box's captured frames. Those frames cannot leave the box
(no S3 permission, no inbound network, ~24 KB per SSM call), and processing them on the box conflicts
with L51's registered prohibition on bulk capture processing on the live box. That trade-off is the
operator's to make.

---

Pinned by `test_reproduce.py` (10 tests). They assert the defective behaviour on purpose: **a fix
should flip them, not delete them.** Raw output: `results_20260917.json`, schema
`janus.l146.pm_depth_verification.v1`, matching `reproduce.py`. No change to `nodes/`, `grids/`,
`kernel/` or `ops/`; no contact with the box.

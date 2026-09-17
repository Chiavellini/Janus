# L149 verdict — MET its registered criteria; two minor conditional costs recorded; not deployed

**Outcome: criteria met.** On a Polymarket REST disagreement the Reconciler now asks the websocket for a
fresh book (`stream.resnapshot.add(asset_id)` in `Reconciler.apply`) and still never writes REST into
the stream's ladder. **Nothing was deployed.** Production still runs `59dd5ae`, where L146's defect R3
is live.

## Criteria

| Registered criterion | Result |
|---|---|
| A disagreement queues exactly that asset; an agreement does not; a superseded fetch neither reconciles nor queues | Met. `test_a_disagreement_queues_a_websocket_resnapshot`, `test_only_the_disagreeing_asset_is_queued` (added after review), `test_an_agreement_queues_nothing`, `test_a_superseded_fetch_neither_reconciles_nor_queues` |
| After the venue's book, `stream.books` and every replica equal it; a removed level does not return | Met. `test_the_venues_fresh_book_corrects_the_book_and_the_level_stays_gone` |
| The Reconciler never mutates `stream.books` | Met. `test_the_reconciler_never_writes_the_streams_ladder`; a write-through mutant fails 6 tests |
| L148 scenarios WT-1, WT-2, M1, F1, N1/WT-3 end clean once answered | Met. One test each |
| A fake-socket test shows the asset is actually unsubscribed and resubscribed | Met. `test_a_queued_resnapshot_is_actually_unsubscribed_and_resubscribed` drives the real `PolymarketStream.run`; frames sent were exactly unsubscribe then subscribe for `["a"]` |
| Each positive test fails with the line removed | Met. Removing the line fails 6: the queueing, fresh-book, N1, WT-1, WT-2 and integration tests. The other new tests are guards against the other mutants: write-through fails 6, queue-always fails 2, queue-every-asset fails 1 |
| L146 evidence and living test unchanged | Met. No file in `2026-09-17_pm-depth-verification/` changed; its test passes (REST content still does not survive the next update by itself, by design) |
| Focused and full suites pass | Met. Focused 59 passed; full suite 1,778 passed (final tree, including the post-review test) |
| Replay gate reported with its real scope | Rows digest `13e4fb08a76c920f` unchanged (selections digest `4f53cda18c2baa0c` is `sha256("[]")` and checks nothing). **This is not evidence for L149:** the replay harness never constructs the Polymarket Reconciler (its only production construction is `grids/live_stream/grid.py:2139`) |
| Independent adversarial review finds no sequence leaving a stale level once answered | Met. **NO SEQUENCE FOUND** over about 2,600 simulated runs of the real classes (`review_round1.md`) |

## What the review found that this change makes worse

Neither is covered by a criterion and neither blocks, but both are real:

1. **If REST persistently disagrees on a quiet book**, the book now alternates between the socket's
   version and REST's about every 20 s instead of settling on REST's. Because the book's source label
   is part of the sizing input hash, each return re-arms the single-flight guard, and it costs about
   3 resubscribes a minute per such asset. Entries still REST-confirm before sending. How often REST
   persistently disagrees is unknown: `rest_drift` is not persisted.
2. **If the venue applied the unsubscribe but ignored the subscribe**, the asset would stop receiving
   updates and be served on REST content without the 3 s REST freshness bound biting. One real
   capture showed 300 of 305 drift resubscribes answered by a book (median 0.23 s), so this appears
   rare. The existing drift path depends on the same venue behaviour but fails closed.

## Pre-existing defects the review surfaced (not caused or fixed here)

- **Major, fails closed:** a discovery refresh that changes a game's executable specification
  unregisters and re-registers the same Polymarket token in one tick. No subscription frame is sent
  and the ladder is dropped, so the new replica stays DISCONNECTED until the socket reconnects, and
  the name-less unregister also drops the capture watchlist's registration. This blocks entries on
  that game rather than pricing wrongly, so it may cost entry rate. Not investigated further here.
- Minor: after a reconnect, a REST read older than a book the replica already received can be adopted
  (the superseded check compares a version that `disconnected()` resets).
- Note: a malformed answer that fails half-way through `apply_book` can leave stale asks.

## What this does and does not change

- Fixes L146 **R3** on quiet books, the only books the Reconciler selects. **R1 and R2 remain:** active
  books are never depth-checked, and touch size is never compared.
- **Not a profitability lever.** Every live taker entry REST-confirms before sending.
- **Deploying it needs the operator's release**, because it changes `nodes/`, which the arming
  override's code hash covers. It must **not** be deployed during F24: that would change what F24
  measures.

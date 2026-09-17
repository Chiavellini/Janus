# L149 — independent adversarial review, round 1 (2026-09-17)

One reviewer, told to break the change by driving the real `PolymarketStream.run`/`handle`,
`Reconciler.prepare`/`fetch_due`/`apply` and `BookReplica`, with only the socket, REST fetch and clock
modelled. Scratch scripts were not added to the repository.

**Criterion verdict: NO SEQUENCE FOUND** in which, once the queued resnapshot is answered, the stream's
ladder or any registered replica holds a level the venue's book no longer has.

## Method

About 2,600 simulated runs, each with and without the added line, mixing lost below-touch updates,
REST responses up to four versions behind (up to 90 % of reads), reconnects, second owners,
unregister-then-register in one tick, `check()` calls and a venue that ignores re-subscribes. Three
invariants were checked and never failed: right after a `book` is handled, `stream.books` and every
replica registered at that moment equal it; with no loss since that book, `stream.books` matches what
the venue sent; every replica labelled `ws` matches `stream.books`.

Read-only evidence from a real capture (`data/frames/polymarket/2026-09-09/00.jsonl.gz`): 300 of 305
top-of-book drifts were followed by a `book` for that asset, median 0.23 s (two of the other five were
still in flight at end of file). Consistent with the venue answering unsubscribe-then-subscribe, not
proof of it: some of those books may have been triggered by trades.

## Introduced by this change

1. **Minor, conditional, touches the entry path.** If REST keeps disagreeing with the socket on a
   quiet book, the replica alternates between the socket's book and REST's roughly every 20 s. The
   sizing input hash includes `leg.book.source` (`grids/live_stream/grid.py:681-691`), so each return
   to the same socket book counts as a new occurrence and re-arms the single-flight guard. Reproduced:
   59 flips back to the identical socket book in 600 s with the line, 0 without (without it the book
   settles on the REST version). Cost is also about 3 resubscribes per minute per such asset: bounded,
   no livelock. Mitigation: every live entry REST-confirms before sending. Frequency unknown because
   `rest_drift` is not persisted.
2. **Minor, depends on venue behaviour.** If the venue applies the unsubscribe but ignores the
   subscribe, the asset stops receiving updates while the run loop's `subscribed` set still lists it.
   The replica stays usable on REST content re-checked about every 15 s, and because `as_of()` includes
   the socket heartbeat the 3 s REST freshness bound does not bite. The drift path relies on the same
   venue behaviour but invalidates, so it blocks instead. With half of re-subscribes dropped: 33.7k vs
   28.0k steps with an asset getting no updates, and 1,525 vs 1,028 wrong-but-usable REST
   observations. The capture above suggests drops are rare.
3. **Note.** A queued resnapshot is acted on only after the next frame arrives (`stream.py:252-257`),
   up to about 4 s on a quiet socket. Entries left for unregistered assets cost one extra
   unsubscribe/subscribe if the asset returns. `apply` runs on the event loop (`grid.py:1854-1856`);
   `once()` has no production caller. No frame goes out on a closed socket: a failed send reconnects,
   and the reconnect's full subscribe covers the cleared entries.

## Present before this change (not caused or fixed by it)

4. **Minor.** The superseded check compares `updated_utc` keyed by `id(replica)`. A never-synced
   second owner has version 0.0 and `disconnected()` resets it to 0.0, so after a reconnect a REST read
   older than a `book` the replica already received is adopted, marked SYNCED and usable (the 3 s
   bound is measured from the dead socket's last frame). The reconnect's full book fixes it.
5. **Major, fails closed.** A game refresh (`grid.py:441-449`, then `478-481`) unregisters and
   re-registers the same token in one tick. No frame goes out (`stream.py:236-251`) and `stream.books`
   is popped, so the new replica stays DISCONNECTED until a reconnect. The Reconciler cannot rescue it
   (it only selects SYNCED replicas). The name-less unregister also drops the capture watchlist's
   registration. Reproduced. Confirmed by reading the code: `PolymarketStream.unregister` with no
   replica pops every registration and the ladder.
6. **Note.** `apply_book` can replace the bids and then raise on the asks (`protocol.py:52-54`),
   leaving the old asks. A malformed answer on the resnapshot path (which does not pop the entry)
   would keep stale asks and is not retried.

## Tests

- Queueing every registered asset passed all 19 tests: "exactly that asset" was untested. **Closed
  after the review** by `test_only_the_disagreeing_asset_is_queued`, shown to fail on that mutant.
- The N1 test's end state holds without the venue's book (no write-through); only its resnapshot
  assertion depends on the line. M1 and F1 do not depend on the line; they are valid
  "never writes REST into the ladder" tests. Docstring clarified.
- In the fresh-book test the correction assertions hold for any delivered book; only the integration
  test's operation frames show the queue leads to a resubscribe.
- Further mutants were caught: invalidating on queue fails 2, popping `stream.books` fails 6,
  queueing on the superseded path fails 1, queueing only for synced replicas or only the first owner
  fails 2 each.

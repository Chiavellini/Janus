# execution

**Kind:** `pure` + one journal (three tables) on the Janus volume
**Implements:** `journal.py`, `gate.py`, `paper.py` (`PaperVenue`, `RefusingVenue`), `testing.py`

What every execution venue shares, real or not. The contract is `kernel/execution_protocol.py`.

## Position in the grid

```
coordinator ──▶ ExecutionVenue.submit(req, RiskClearance)
                    │  gate.admit: mode ≥ needed, a live unused clearance for THIS opportunity, consumed
                    │  journal.pending BEFORE the wire            (UNCONFIRMED until the venue speaks)
                    ▼
        paper / refusing / exec_kalshi / exec_polymarket
                    │
                    ▼
                journal.record: FILLED | PARTIAL | UNFILLED | UNCONFIRMED | REJECTED, venue words kept
```

## Rules the journal enforces

A row exists before the POST; a process that dies between the two leaves `UNCONFIRMED`, which
`status()` resolves before any retry. A duplicate client order id is refused here, which is
what makes the id idempotent on our side of the wire. `venue_fills` is the FIFO the loss breaker
reads, with the venue-final flag.

## Paper and shadow

`PaperVenue` fills against the exact `Book` the opportunity was priced from, with a latency and
an adverse-move parameter (zero until the slippage buffer is measured). `RefusingVenue` is
SHADOW_LIVE: intent journaled, nothing sent. Both pass the same gate and write the same journal,
so the coordinator cannot tell them from a real venue — which is the point.

## Tests

`tests/test_execution.py`.

## Exact historical overfill acknowledgement (L56)

`overfill_ack.py` is an operator acknowledgement, not an accounting repair or a new
trade authorization. It never edits fills, orders, executions, settlement/P&L or kill.
It binds the complete exact order, unique owning RECONCILED/released execution,
all owned terminal cash-final legs, released capital reservation and settlement
snapshot, with verified immutable Git source bytes and exact historical flag IDs.
Unrelated executions with no orders are allowed; only closed terminal zero-fill
UNFILLED/REJECTED legs may use the settlement serializer's zero price/fee for null
journal values. Positive fills require exact cash evidence.

The operator proposal has `version: 1` and `acknowledgements`, each containing
`client_order_id`, `sources` (full prepared Git proof or `{git_commit, ref, sha256}`),
`reason`, `supersedes_id` (null for the first acknowledgement), and `flag_ids`.
Source refs must identify the evidence the operator actually reviewed; committing
bytes proves immutable membership, not that the venue or the operator is truthful.

Run from the release directory, with explicit real paths and operator identity:

```sh
python3 -m nodes.execution.overfill_ack --db /exact/lane.sqlite --manifest /exact/proposal.json --operator 'operator name' --prepare --output /exact/new-prepared.json
python3 -m nodes.execution.overfill_ack --db /exact/lane.sqlite --manifest /exact/new-prepared.json --operator 'operator name'
python3 -m nodes.execution.overfill_ack --db /exact/lane.sqlite --manifest /exact/new-prepared.json --operator 'operator name' --confirm EXACT_DIGEST_FROM_DRY_RUN
```

Preparation opens the database read-only, exports all specified current snapshots
and exact flag rows, and refuses a candidate set different from all real overfills
or an uncovered active overfill flag. Output creation is exclusive: it never
overwrites a previous proposal. Preparation and dry-run create no database rows.
Confirmation revalidates the target database path, source membership, snapshot,
operator, latest acknowledgement heads and flags inside a writer transaction.
History is append-only; a correction/revocation must supersede the exact latest ID.
Revocation uses a fully prepared manifest with action `revoke`, never deletes history.

Every guard pass revalidates acknowledgements before normal overfill suppression.
Any changed/missing order, source/hash/confirmation, reservation, execution or leg
invalidates the acknowledgement and relatches STOP—even if the changed request
would no longer make the order appear overfilled. A complete error-free two-venue
fill/position pass can append an exact-ID `ORDER_OVERFILL_RESOLVED_EXACT` marker only
when every overfill and unresolved flag is acknowledged; the check repeats under
the writer lock. Unknown/new/same-timestamp alarms remain active. This narrow alarm
resolution never clears the live kill and is not global release readiness.

A legacy immediate-order fallback persistence error is separately reported as
`ORDER_PERSISTENCE_FAILED`, with independent kill protection. Only a proved
post-only marker may invoke the adapter's post-only persistence hook. This labeling
repair does not resolve historical persistence alarms.

Expected EV effect: none on sizing, prices, accounting or entry criteria; it prevents
an exactly reviewed settled incident from being mistaken for new risk. No forward
profit or readiness claim follows from these offline tests.

## Exact historical proof ownership (L56)

`dispositions.py` is an explicit operator acknowledgement, not a cash-finality,
settlement, position, or P&L repair. The guard excludes only an exactly matching
confirmed historical proof fill from orphan classification, and reports the
disposition each pass. Every FillRecord field participates in its hash, including
full-precision quantity/price/fee, IDs, timestamp, asset, side and finality.

Evidence contains exact archived proof bytes and JSON-pointer identity/closure
bindings, plus self-contained Git commit/tree membership proofs. Archive-only
releases verify the bytes without Git or network access. Historical versus current
accounting differences must be explicit; the Sept7 PM proof omitted a fee in its
old P&L, while archived BUY/REDEEM cash gives +3.121138. Its current `final=false`
is preserved and is not promoted by ownership attribution.

The append-only table prevents updates/deletes and requires linear supersession
for corrections or revocation. The recorded confirmation envelope binds the target
database, complete prepared manifest, exact entry membership and previous heads;
runtime verifies it again. Changed/corrupt/unconfirmed/revoked evidence remains an
orphan and STOP. No existing order, fill, accounting, or kill record is rewritten.

For a reviewed prepared manifest, run from the exact release directory:

```sh
python3 -m nodes.execution.dispositions --db /absolute/path/to/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/prepared.json
python3 -m nodes.execution.dispositions --db /absolute/path/to/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/prepared.json --confirm EXACT_DIGEST_FROM_THAT_DRY_RUN
```

Dry-run is database-read-only and displays complete fill facts, source excerpts,
proof/accounting differences, and exact incident rows. Confirmation appends only
if target, manifest and prior heads still match. `--export NEW_FILE` on a local
Git checkout can materialize a source-reference proposal as a self-contained
manifest; it is separate from confirmation and refuses file overwrite.

Only a complete successful guard pass with relevant adapters/positions present,
no errors/orphans/invalid dispositions, and exact coverage of **every** unresolved
orphan flag can append `ORPHAN_FILL_RESOLVED_EXACT`. The writer-locked check also
revalidates current dispositions. The marker closes named IDs only; an unknown,
aged-out or same-timestamp later incident stays active. It never clears the kill.
Abbreviated historical flag text is explicitly operator-bound to full fill
identity in the manifest, not matched by fuzzy text or title similarity.

The orphan reporting cache is cleared across the acknowledgement lifecycle.
Revocation, changed identity or corrupt evidence re-flags in the same process;
current unknown inventory attempts the kill on every pass, including after a
human reset. A failed latch cannot poison the reporting cache.

## Exact historical legacy persistence label (L56)

`legacy_incident_ack.py` separately acknowledges one reviewed historical IOC
database-lock incident that the old guard incorrectly labelled post-only. It
binds the exact lane flag and PM violation, complete settled order/execution/
owned-leg/reservation snapshot, and the Git-proved old guard hook excerpt.
The operator attests that the exact incident came from that documented mechanism;
the code source alone is not independent venue evidence or a fresh cash proof.
No original flag, violation, order, fill, P&L or kill is rewritten.

Preparation dynamically snapshots the explicit incident IDs against the exact
existing database. From a Git checkout (or use an already source-hydrated input):

```sh
python3 -m nodes.execution.legacy_incident_ack --db /absolute/path/to/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/legacy_incident_proposal.json --operator OPERATOR_NAME --repo /absolute/path/to/release --prepare --output /absolute/path/to/NEW_legacy_incident.json
python3 -m nodes.execution.legacy_incident_ack --db /absolute/path/to/tuples.sqlite --manifest /absolute/path/to/NEW_legacy_incident.json --operator OPERATOR_NAME
python3 -m nodes.execution.legacy_incident_ack --db /absolute/path/to/tuples.sqlite --manifest /absolute/path/to/NEW_legacy_incident.json --operator OPERATOR_NAME --confirm EXACT_DIGEST_FROM_THAT_DRY_RUN
```

Prepare and dry-run are read-only; export refuses overwrite. Explicit confirmation
appends an immutable linear record after writer-locked target/source/state/head
revalidation. Revocation appends action `revoke` with the exact prior record ID.
Confirmed records include the reconstructable operator confirmation envelope.

Confirmation never resolves the flag itself. A fresh complete guard pass must
prove both adapters and known empty positions, no read/projection/persistence
errors or other unacknowledged findings, no open/cash-pending orders, unreleased
executions/reservations or current venue inventory, and empty maker/admission history.
The exact bound incident execution must be zero-unhedged; other released historical
directional quantities remain untouched and are not treated as current holdings. Under
one writer lock, every unresolved same-class flag must match exact confirmation
and current bound evidence before named-ID resolution. Unknown/new/equal-time
incidents, changes and revocations block. The historical flag remains visible,
the independent live kill remains latched, and later legitimate maker history
does not reopen an already resolved label.

PM adapter fill/source persistence failures now likewise use the generic
`ORDER_PERSISTENCE_FAILED` unless an exact maker marker exists. Actual maker
failures retain `POST_ONLY_PERSISTENCE_FAILED`; both preserve quantity, cash
atomicity, pending finality and independent stop visibility.

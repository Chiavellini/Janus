# L56 exact historical proof-orphan dispositions

Local orphan component PASS: **39 focused tests**, **571 current combined tests**,
and `git diff --check` pass. Overfill and false-label persistence acknowledgements
are separately owned/registered components, not authorized by this verdict alone.

## Sources and accounting boundary

The original proof JSONs were recovered under `/Volumes/Kilos/janus/proofs/`;
their absence from `/srv/janus/proofs/` does not mean they were lost. Source-only
commit `f4ccffdc7ddceb785dec34c4e9cebca648abe2ff` contains exactly three verified
byte-identical evidence copies:

- Kalshi proof: `1dcb7109f19738adf60f0d83c6bc00469f3b77fa8e568f771d7ec32646cc32c1`.
- PM proof: `c00a94675ca127c9ff49933d7121202cebe0799557b498f573bf80f044c8b63d`.
- L52 PM activity page0003: `fecae07c7f0b31fae93726882002ffb720b66573673b85ef9dc5a39a962343b0`.

The prepared manifest embeds commit/tree/blob membership proofs for the actual
evidence bytes, exact proof JSON-pointer bindings, and supplemental committed
BATTERY lines. Archive-only releases need neither Git nor network to verify it.
The exact current F18 FillRecords and exact flag rows197/198/204/205 are explicitly
operator-bound; abbreviated historical flag text is never a fuzzy ownership join.

**Cash correction:** the old PM proof's `settled.realized_usd=3.18157774` omitted
the actual fee. Archived activity rows36/37 bind the exact token and quantity:
BUY cash2.010439, REDEEM cash5.131577, net **3.121138**. The manifest explicitly
shows old proof price0.38/charged0 versus current VWAP0.3799999493 and
fee0.0604400001709539. Current `final=false` stays false. This is ownership
classification and incident attribution only; no order, fill, settlement, P&L or
kill record is rewritten, and this is not a current-account total.

## Fail-closed controls verified

Every FillRecord field is exact-hashed with finite decimal normalization, strict
booleans and no unknown/missing fields. Any change, corrupt source, corrupt or
empty confirmation, wrong target/manifest membership, revocation or stale writer
head remains an orphan/STOP. Corrections/revocations append linear successors;
schema triggers refuse historical updates/deletes.

The confirmation record includes its complete prepared manifest, target and head
envelope. Runtime reconstructs its digest, entry membership and predecessor.
Review caught the initial missing envelope verification before the first focused
test run; no pre-fix RED claim is made for that case.

Only complete successful fill reads with relevant adapters and known positions,
zero errors/orphans/invalid dispositions, and exact coverage of every unresolved
flag permit automatic incident resolution. Dispositions are revalidated under the
same writer lock as the flag coverage check. `ORPHAN_FILL_RESOLVED_EXACT` closes
named IDs only; corrupt markers, older unknowns, later equal-timestamp flags and
concurrent insertions cannot be blanket-cleared. The kill remains latched.

## Operator commands (not run on the box by this subtask)

From the reviewed release directory, use the exact existing live database path:

```sh
python3 -m nodes.execution.dispositions --db EXACT_EXISTING_BOX_DB --manifest research/exec/2026-09-09_historical-proof-dispositions/prepared.json
python3 -m nodes.execution.dispositions --db EXACT_EXISTING_BOX_DB --manifest research/exec/2026-09-09_historical-proof-dispositions/prepared.json --confirm EXACT_DIGEST_PRINTED_BY_THAT_DRY_RUN
```

Prepared file SHA256:
`e4ef76c29bca39437db6ed51c99409bcbd8e3db8c74848c8a36bab2920dbfa0d`.
Dry-run is read-only and displays complete facts/source excerpts/incident bindings.
Confirmation appends only. A fresh complete guard pass must independently show
that no unacknowledged incident remains; neither command clears the kill or other
flag classes. No box/venue access, orders, deployment or rearming by this subtask.

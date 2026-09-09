# L54 fill-persistence review repair

**Local repair PASS.** No live entry, deployment, current-account total, or EV
claim follows from these synthetic tests.

Registered in `fill_persistence_followup.yaml` under the previously registered
`persistence_domain_followup.yaml`; appended PENDING preceded the first tests.
All seven first-run cases failed RED before implementation, then passed GREEN:

- `journal.record_fill` raises for owned maker quantities 4, 10 and 11, or an
  owned taker quantity 4. The guard previously received no fills.
- Cash-source and authoritative-cash-event writes raise after the held maker
  quantity is validated. The exception previously escaped the adapter.
- A later six-share fill write fails after a four-share prefix succeeds. The
  adapter previously discarded the returned prefix as well as the later fill.

## Repaired contract

Cash source, cash audit event and fill projection are one per-fill transaction:
source/event writes stage without committing, and `journal.record_fill` commits
last. A failed transaction rolls back its incomplete fresh source/audit before
the persistence STOP is reported. Prior committed source evidence stays intact.

Each failed fill keeps its exact identity and highest observed quantity in an
in-process map. Valid quantities still return on that pass and are replayed when
subsequent trade reads are smaller or empty. An error in a later row makes the
entire returned list nonfinal without losing the earlier valid prefix. No cash
read or later successful write automatically clears `persistence_error`.

The separately owned `_persistence_failure` helper attempts the independent live
kill first and keeps a visible in-memory error even when its SQL audit fails.
Role/cap audit failures are isolated so that they cannot suppress a validated
quantity. With **all SQL writes disabled**, maker11 and taker4 still return
nonfinal, the independent kill file latches, the audit failure remains explicit,
and an empty reread cannot erase the quantity.

The lifecycle owner's guard integration merges returned and durable fill
quantities by exact fill ID before order/execution reconciliation. Guard-facing
tests prove partial/full/over-cap inventory reaches protection on that pass,
including a durable4 plus unpersisted6 total of10. If order/execution persistence
also fails, this does not authorize unjournaled protection; STOP and operator
repair remain required. In-process retention is not a claim that failed storage
survives process destruction: durable unresolved admission and the independent
kill prevent an automatic restart from treating absence as a no-fill.

## Verification

- **76 focused tests passed**, covering maker projection, cash accounting,
  cash finality, guard quantity coverage and the new persistence failures.
- **487 combined tests passed** across PM execution, execution/guard, risk,
  account ledger, reconciliation, live-stream grid, and the offline PM proof.
- `git diff --check` passed.

This subtask changed `nodes/exec_polymarket/client.py` (fill persistence/coverage
regions and staged cash-source helper), `tests/test_maker_fills.py`, this
registration/result, and appended ledger notes. Guard/status/kill helpers and
their integrations belong to the parallel L54 owner. All changes are unstaged
and local. No venue/account reads, live writes, signing, orders, deployment,
live restart, arm/cap changes, or kill clearing occurred.

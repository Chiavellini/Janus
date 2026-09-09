# F18 / L56 operator runbook — proposed, not executed

This is an operator-only repair/release sequence. It grants no authority to the
agent to run `release.sh`, sign, restart real trading, or clear kill. The final
reviewed/pushed SHA and green review/tests of the id211 incident implementation are
still required before this becomes a complete paste. Keep `kill/live` latched throughout preparation, reconciliation,
release and stream warm-up. Do not use `release.sh --now`.

## 1. Fix the target and quiesce before checkout

From the reviewed local checkout, substitute the full final committed/pushed SHA:

```sh
export JANUS_BOX_REGION=mx-central-1
export JANUS_BOX_ID=i-0a8c073c72dcdae11
JANUS_RELEASE_SHA=FULL_FINAL_REVIEWED_SHA
bash ops/box/run.sh 'set -euo pipefail; test -f /srv/janus/kill/live; systemctl stop janus-live-stream; test "$(systemctl show -p ActiveState --value janus-live-stream)" = inactive; test "$(systemctl show -p MainPID --value janus-live-stream)" = 0; echo L56_OBSERVER_QUIESCED'
bash ops/box/update.sh "$JANUS_RELEASE_SHA" --no-restart
```

Before stopping, read the current state and require no flight or unresolved resting
order; a stop invokes `cancel_all()` on SIGTERM, so an unexpected resting order is a
separate recovery incident, not an incidental release action. No concurrent
`guard_once`, settlement/proof process, manual DB writer or second operator release
may run during this sequence. Leave the watchdog timer enabled. If another known
DB writer is active, wait for its completion; do not kill an unidentified process.

Stopping *before* moving the checkout avoids mixed old-process/new-module imports
and observer contention. `--no-restart` still changes the checkout and SSM launch
pin; it is not read-only. Separately verify the remote exact HEAD, clean pinned
tree, inactive unit/MainPID0 and existing kill before continuing. **The current
`run.sh`/`update.sh` wrappers can print remote Failed while returning local exit0.**
Read the remote status/output and verify each named success marker; do not trust
`&&` between wrappers as the release gate.

## 2. Read-only proposals and dry confirmations

Run the following on the box as `janus`, inside one serial `run.sh` call. The
standard wrapper is:

```sh
bash ops/box/run.sh <<'REMOTE'
set -euo pipefail
test -f /srv/janus/kill/live
test "$(systemctl show -p MainPID --value janus-live-stream)" = 0
sudo -u janus bash <<'JANUS'
set -euo pipefail
set -a
. /etc/janus.env
set +a
cd /opt/janus
# Insert one reviewed command block from below.
JANUS
REMOTE
```

No credentials are needed for the acknowledgement commands. The proposal files
must be included in the final SHA. Prepare the output under the data volume, not
inside the executable tree; select a fresh release-specific filename each time:

```sh
umask 077
mkdir -p /srv/janus/release-audit/L56
.venv/bin/python3 -m nodes.execution.dispositions --db /srv/janus/tuples/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/prepared.json
.venv/bin/python3 -m nodes.execution.overfill_ack --db /srv/janus/tuples/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/overfill_operator_proposal.json --operator Bernardo --prepare --output /srv/janus/release-audit/L56/overfill-FINAL_SHA.json
.venv/bin/python3 -m nodes.execution.overfill_ack --db /srv/janus/tuples/tuples.sqlite --manifest /srv/janus/release-audit/L56/overfill-FINAL_SHA.json --operator Bernardo
.venv/bin/python3 -m nodes.execution.legacy_incident_ack --db /srv/janus/tuples/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/legacy_incident_proposal.json --operator Bernardo --prepare --output /srv/janus/release-audit/L56/incident211-FINAL_SHA.json
.venv/bin/python3 -m nodes.execution.legacy_incident_ack --db /srv/janus/tuples/tuples.sqlite --manifest /srv/janus/release-audit/L56/incident211-FINAL_SHA.json --operator Bernardo
```

The overfill exporter refuses unexpected/missing candidates, unbound active flags,
stale heads, source mismatch, nonfinal/reopened evidence or output overwrite. Its
exact allowlist is:

| Flag ID | Client order ID | Evidence |
|---|---|---|
| 199 | `9d36d91cf99e46d39b9e579020261c64` | Page3, exact directional PM redemption/net4.250739; not a cover success |
| 200 | `17dd8b4ab307494f99e02306249525d0` | Page3 + exact local released cover/leg/reservation snapshot |
| 201 | `e9a2cddfc6284424be62b01d7be8bb0b` | Page3 SF BUY5.241936 + page4 same-token REDEEM5.241936, cash5.241936 + exact local released cover/leg/reservation snapshot |
| 202 | `a38ae7929a5a4fddbd5d48785e099378` | Page3 Cubs BUY7.769231 + page4 same-token REDEEM7.769231, cash0 for losing PM leg + exact local released cover/leg/reservation snapshot |
| 203 | `40797bee0f17449ca1e4fa3840125232` | Maximus page4 BUY/cash + positions page1 + exact local cover settlement; zero-value redeemable position is not redemption cash |

Page3 is Git-bound to `f4ccffdc7ddceb785dec34c4e9cebca648abe2ff`, SHA256
`fecae07c7f0b31fae93726882002ffb720b66573673b85ef9dc5a39a962343b0`.
Maximus page4 and positions page1 are bound to
`df911419de7947ed35cd41b1191f8107fb36bf9d`, SHA256 respectively
`3e0ba1e395ed3737b945246f955803c7da19d345b4fea32195f071786cf1c982` and
`1b0dba9b99e5bf6f9f7f92217d14ce46a2301682862f952462dcca53ef79d071`.
Full refs and individual operator reasons are in `overfill_operator_proposal.json`.
Independent actual-target source review remains necessary; membership does not
prove source-content truth. Do not substitute page3 for Maximus evidence.

## 3. Separate explicit operator confirmation

Review the exact target path, all five current snapshots, flags and sources, and
the three dry-run digests. Do not automatically scrape and replay a digest in the
same unattended command. In a separate invocation, with the observer still stopped:

```sh
.venv/bin/python3 -m nodes.execution.dispositions --db /srv/janus/tuples/tuples.sqlite --manifest research/exec/2026-09-09_historical-proof-dispositions/prepared.json --confirm EXACT_REVIEWED_ORPHAN_DIGEST
.venv/bin/python3 -m nodes.execution.overfill_ack --db /srv/janus/tuples/tuples.sqlite --manifest /srv/janus/release-audit/L56/overfill-FINAL_SHA.json --operator Bernardo --confirm EXACT_REVIEWED_OVERFILL_DIGEST
.venv/bin/python3 -m nodes.execution.legacy_incident_ack --db /srv/janus/tuples/tuples.sqlite --manifest /srv/janus/release-audit/L56/incident211-FINAL_SHA.json --operator Bernardo --confirm EXACT_REVIEWED_INCIDENT211_DIGEST
```

Record the appended IDs. A second attempt is not idempotent: stale-head rejection
is expected after success. Inspect existing history instead of deleting it or
silently changing `supersedes_id`. If fresh cash or settlement evidence changes an
acknowledged snapshot, stop for a newly reviewed append-only correction and exact
new flag coverage; never make accounting fit the acknowledgement.

The separate id211 command binds only lane flag211 and the exact paired legacy
false-label violation row, linked settled IOC order/execution/reservation evidence,
and verified source. Preparation/confirmation require the known idle database and
empty maker/admission state; confirmation does not resolve the flag. Confirm it
before the following fresh complete resolution guard. It must not delete the
violation, clear a class-wide timestamp or reinterpret a real maker failure. There
is no UPDATE/DELETE workaround. If that proposal or reviewed implementation is
absent from the final SHA, stop here.

## 4. Authenticated 72-hour guard, then exact-state review

Use the same serial `janus` wrapper, now sourcing credentials without printing them:

```sh
set -a
. /run/janus/janus.env
set +a
.venv/bin/python3 ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --since-hours 72
if .venv/bin/python3 ops/watchdog.py; then
  echo WATCHDOG_GREEN
else
  JANUS_WATCHDOG_RC=$?
  test "$JANUS_WATCHDOG_RC" -eq 1
  echo PRE_RELEASE_ALERTS_REQUIRE_OPERATOR_REVIEW
fi
```

Capture the full output as the release evidence. Do not rerun in parallel or while
the observer is active. `guard_once` has no entry clearance, but it intentionally
writes reconciliation/flags and can cancel an expired unresolved maker order;
therefore precheck that no maker order/admission is unresolved. Its exit0 means
only no reported fetch errors, **not** absence of orphans/imbalance/STOP findings.
Require explicitly: errors empty, orphans0, mismatches empty, to_protect empty,
no unconfirmed/open/pending real order, no unreleased execution/reservation, no
unresolved admission/marker, no current persistence/projection error, and every
exact disposition/acknowledgement still valid after the pass. A changed accounting
snapshot is a STOP requiring review, not permission to refresh silently.

Check active flags using `unresolved_flag_rows`, not maximum timestamp or count of
historical rows. Require no unresolved ORPHAN_FILL, ORDER_OVERFILL,
POST_ONLY_ROLE_VIOLATION, POST_ONLY_PERSISTENCE_FAILED or ORDER_PERSISTENCE_FAILED;
the exact resolution records retain their historical rows. Check the id211 module's
own runtime match and unresolved violation semantics as well. The kill remains.

For the exact local post-guard state check, in the same stopped-lane `janus` session:

```sh
.venv/bin/python3 - <<'PY'
import sqlite3
from nodes.execution.overfill_ack import match_overfill_ack
from nodes.execution.legacy_incident_ack import match_incident, idle_database
from nodes.risk.flags import unresolved_flag_rows
c = sqlite3.connect('file:/srv/janus/tuples/tuples.sqlite?mode=ro', uri=True)
c.execute('BEGIN')
idle_database(c)
for cid in ('9d36d91cf99e46d39b9e579020261c64', '17dd8b4ab307494f99e02306249525d0',
            'e9a2cddfc6284424be62b01d7be8bb0b', 'a38ae7929a5a4fddbd5d48785e099378',
            '40797bee0f17449ca1e4fa3840125232'):
    assert match_overfill_ack(c, cid), cid
assert match_incident(c, 211)
for flag in ('ORPHAN_FILL', 'ORDER_OVERFILL', 'POST_ONLY_ROLE_VIOLATION',
             'POST_ONLY_PERSISTENCE_FAILED', 'ORDER_PERSISTENCE_FAILED'):
    assert not unresolved_flag_rows(c, flag), flag
print('L56_EXACT_LOCAL_STATE_OK; live kill must remain')
PY
```

This deliberately strict idle check is for the pre-entry historical state. Do not
reuse its empty-maker-history requirement as a rule against legitimate later F18
orders. The retained false-label violation row is not an entry veto by itself:
current prewire checks the process persistence STOP, live kill, violated maker
markers and singleton ownership. No marker belongs to historical id211.

The deliberate stopped lane/stale override/live kill can explain the pre-release
watchdog alerts; no other alert is waived. No fully green runtime is claimed while
the observer is intentionally stopped. A watchdog runner returns0 even on alerts;
call `ops/watchdog.py` directly and review its output.

## 5. Operator-only daily release, unchanged arm, kill retained

After the preceding evidence is accepted, the operator runs from the local checkout:

```sh
JANUS_ARM_CAPS='12 10 250 168' bash ops/box/release.sh "$JANUS_RELEASE_SHA"
```

This rechecks quiet money, repeats checkout of the *same* SHA, re-signs the existing
statement at12/10/250/168h, and restarts LIMITED_LIVE. The repeated checkout is
intentional: it preserves the repository's operator-only daily-paste boundary.
Do not replace this with an agent-run direct arming command. Verify remote success,
exact SHA and clean code-tree pin, matching limits/override, correct caps, active
LIMITED_LIVE unit, and the live kill still present.

Allow two new report rows from this process. Require fresh connected `kalshi`,
`polymarket` and `polymarket_user` rows; healthy market clock fields and no loop
stall; not merely absence of watchdog socket alerts, which are silent on too few
or stale rows. Run direct watchdog again: only the intended live kill may remain.
Read current order/admission/flight/error state again. Any new incident stops here.

## 6. Explicit final kill clear, with race protection

Clearing the local latch while the observer can independently rewrite it has a
check/delete race. The safest operator clear briefly quiesces the now-verified
same-SHA lane again, verifies MainPID0 and quiet exact state, reviews/hashes the
current `kill/live`, and archives that exact file outside the kill directory before
starting the same already-signed unit. Do not clear while an account/guard writer
or an unresolved holding exists. Do not clear `kill/all`, venue/event/strategy
switches, the breaker or another incident.

If SSM `/janus/kill/live` is still set, the operator must explicitly clear that
parameter *while the local latch remains*, otherwise kill_sync will re-latch it:

```sh
bash ops/box/kill.sh live --clear
```

This does not clear a local breaker/human latch. Never clear `/janus/kill/all` as
part of this repair. Verify the remote parameter result; inspect failures rather
than treating the script's “was not set” as proof of absence.

Final local-file operation is deliberately a separate operator decision. After
quiescing, fresh exact-state/ack/incident checks and the independently reviewed
kill SHA256, use the standard remote wrapper as root for service control:

```sh
systemctl stop janus-live-stream
test "$(systemctl show -p MainPID --value janus-live-stream)" = 0
test "$(sudo -u janus git -C /opt/janus rev-parse HEAD)" = FULL_FINAL_REVIEWED_SHA
# Repeat the reviewed exact-state check above here, as janus, before touching kill.
test -f /srv/janus/kill/live
test "$(sha256sum /srv/janus/kill/live | cut -d ' ' -f1)" = EXACT_REVIEWED_KILL_SHA256
test ! -e /srv/janus/release-audit/L56/live-cleared-FINAL_SHA.json
mv -- /srv/janus/kill/live /srv/janus/release-audit/L56/live-cleared-FINAL_SHA.json
if ! systemctl start janus-live-stream; then
  mv -- /srv/janus/release-audit/L56/live-cleared-FINAL_SHA.json /srv/janus/kill/live
  exit 1
fi
```

The file move is recoverable, preserves the incident reason/time, and clears only
the exact reviewed local latch. After start, verify the unit stays active, new
authenticated stream/clock rows are healthy, the override matches, direct watchdog
reports green, and no new kill/flag/admission/flight fault appears. If any check
fails, independently re-latch live and stop new entry; never repeatedly clear.
The first three F18 covers still require authoritative cash/fill reconciliation
before the fourth, per GATE_TO_LIVE; this runbook does not weaken that boundary.

## Consolidation and non-consolidation

The quiet-state read checks, source preparation and all three dry runs can share one
serial SSM call. The separately reviewed confirmations can share a second. The
single authenticated guard and post-guard SQL/flag checks can share a third. The
operator's `release.sh` already consolidates update/sign/restart. Keep final kill
clear separate; do not auto-confirm from scraped digests, run guard writers in
parallel, or infer remote success from wrapper exit status. Retain the observer
stopped and kill present at every incomplete/failed preflight step.

## Local consistency checks completed (no box commands executed)

The five CID→199–203 mappings and every compact Git source reference in the
overfill proposal were verified offline. The two new Maximus files are exact archive
copies in source-only commit `df911419de7947ed35cd41b1191f8107fb36bf9d`. The current
legacy incident parser exposes the documented prepare/output/operator/dry/confirm
options and the hydrated proposal targets CID40797…, lane flag211, violation1.
Flags201/202 additionally bind the committed page4 terminal redemption source, not
only the page3 BUY. Both exact same-token quantities were checked offline. The
Cubs terminal REDEEM has cash0; it is not a payout equal to its redeemed shares.
All shell blocks passed `bash -n`; `git diff --check` passed. No live proposal was
prepared and no acknowledgement/guard/release/kill command was run.

Open release evidence: final committed/pushed SHA, complete tests/review for that
exact tree, actual-target prepare/dry results, explicit operator-confirmed digests,
and the fresh authenticated guard/runtime checks above. The registered/reviewed
legacy idle repair now distinguishes released historical directional accounting
from current exposure; never change historical quantities to manufacture idle state.

# HANDOFF — Track B, IBKR-dependent program (session 2026-08-18 17:00 → 2026-08-18 19:45 CST)

**Mandate this session:** own the IBKR portion of Track B. Execute the registered **L13** capability
probe, then (only if entitled) register and start a forward archive, characterize it, build the
settlement-reference map. Research + backtest only; nothing armed; every IBKR call through
`lib/ibkr_readonly.py`. **Result: L13 executed → every family DELAYED (entitlement block). No
archive started, no L14 registered, 0 test looks spent, 0 orders, no PnL/outcomes read, no
identifiers persisted.** Everything downstream is built, tested and parked behind the entitlement.

Evidence labels used throughout: **M1** measured directly · **MOD** modelled · **R** researched ·
**U** unknown.

---

## 1. Initial project state (as encountered)

- Read order followed: `AGENTS.md` → `handoffs/TRACK_B_BRIEF.md` → `snooping_ledger.md` →
  `research/exec/2026-08-18_ibkr-readonly-capability/spec.yaml` → `lib/ibkr_readonly.py` →
  `collectors/probe_ibkr.py` → `tests/test_ibkr_readonly.py` → `SHARED_SERVICES.md`.
- Ledger: 0 test looks; L10/L11 (Kalshi/PM Phase A/B) PENDING; **L13 PENDING** with an immutable spec
  (mtime 12:27). Hypothesis registry TB-H01…H10. `state.yaml` had **no** IBKR/L13 entry.
- Hermetic suite: **54/54** green.
- Disk: internal `/` **3.9 GB** free (above the 2 GB floor, but swap lives there); `/Volumes/Kilos` 759 GB.
- **The IBKR gateway was unusable.** `com.janus.ibkr-gateway` was loaded and Java listened on
  `*:5055`, but zero `/v1/api` requests had been served since a 12:31 restart; TLS handshakes never
  completed; `jstack` could not attach; JVM RSS ≈ 3 MB. Host: 8 GB RAM, swap 11.5/12 GB, load 35–57,
  a 6.7 GB `com.apple.Virtualization` VM. Authentication state was **unknown**, not "missing".
- Kalshi/PM Phase-A collector (`com.janus.track-b-collector`) was running; its 17:27 checkpoint
  read PENDING_INSUFFICIENT_DURATION at 31.02 h. **Untouched by me.**
- Inconsistency found early: `collectors/probe_ibkr.py::_underlying` scored `secType` at row level,
  but `/iserver/secdef/search` puts it in `sections[]` — latent bug (bit on XSP, see §2).

## 2. Work completed (with reasoning)

1. **Gateway root cause + fix (M1).** Not auth: the launchd job ran as `ProcessType Background`
   (every thread priority 4, JVM ~100 MB fully compressed out). The gateway proxies each `/v1/api`
   call to `api.ibkr.com`; its outbound TLS handshake exceeded Vert.x's **hard-coded 10 s** limit
   (`gw.message.*.log`: "handshake timed out"), so calls hung while TCP still accepted. Also: IBKR's
   `bin/run.sh` does not `exec` java, so `launchctl bootout` orphans the JVM (needed `pkill -f GatewayStart`).
   Fix (Janus-side only): plist `ProcessType Interactive`; trimmed JVM via `JAVA_TOOL_OPTIONS`
   (C1-only JIT, serial GC, small heap) in the runner. Startup ~4 min → <1 s; calls answer in ~0.3 s.
   User freed memory (their VM) and logged in manually; login was never automated.
2. **L13 executed twice, criteria untouched.** Run 1 (as shipped) mis-resolved XSP to a Toronto STK
   (conid tie-break); fixed `_underlying` to read `sections[].secType`, added a test, re-ran (run 2).
   Both runs preserved. Result: MBT `DPB`, ZQ `DPB`, SPX 7695 C/P and XSP 769 C/P (AUG26) `DPBd`,
   index feeds `Z` outside RTH; **BTC root lists 0 contracts** on `/trsrv/futures` (IBKR symbol
   likely `BRR` — R, outside registered roots, not substituted). `D` observed with Globex and CBOE
   GTH **open** ⇒ subscription state. **BLOCKED_ENTITLEMENT_OR_CONTRACT; program_ready=false.**
   Recorded as an access result, never a null edge.
3. **Forward-archive collector built and hermetically tested, NOT started** (no family passed).
   Design: 1 Hz REST snapshot polling via `IBKRReadOnlyClient`; every poll slot yields a `polls`
   row; failed polls yield reason-coded GAP rows; `MSG` vs `NO_CHANGE` keyed on `_updated`/value
   change (IBKR re-sends full fields each poll — learned in a smoke run); explicit gap reasons
   (`NO_MESSAGE, DISCONNECTED, AUTH_INVALID, AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED, EXPIRED_CONTRACT,
   DELAYED_OR_FROZEN, MARKET_CLOSED, UNKNOWN_RESPONSE, DISK_FLOOR, GATEWAY_ERROR, GATEWAY_TIMEOUT,
   SAFETY_REFUSED, NOT_SELECTED`); deterministic selection (earliest unexpired future per root;
   near-ATM call+put at the earliest maturityDate whose 16:15 ET has not passed — expiry day
   pinned); roll lineage table; privacy denylist at write time; fake-target alarms; DB path forced
   under `/Volumes/Kilos/janus`. Three 45–90 s **smoke runs** against the live gateway (delayed
   data, diagnostic only): 100% polls ok, latency p50 ≈ 250 ms / p95 ≈ 400 ms, 0 leaks, 0 forbidden attempts.
4. **Settlement-reference map v2** with **M1 Kalshi rules text**: KXBTC/KXBTCD hourly ladders settle
   on the 60 × 1 s BRTI average before the strike hour (`close_time` IS the event time); the 17:00 ET
   hour coincides with CME's crypto-futures daily halt 17:00–18:00 ET (R). KXINX/KXINXU settle on
   the end-of-day S&P 500 value at 16:00 ET. KXFED = target-range upper bound; KXFEDDECISION = move
   buckets. Kalshi exposes `expiration_value` on settled markets. **n=1:** Kalshi Aug-18 S&P
   settlement 7691.76 vs IBKR SPX index last 7693.26 (1.5 pt); official close **U**. All pairs
   remain **BLOCK**; a free L-row plan for measuring the S&P basis is written into the map.
5. Governance/records: L13 note appended to the ledger; TB-H11…H14 registered (BLOCKED);
   `state.yaml.track_b_hft.ibkr_capability` block; runbook section in `collectors/TRACK_B.md`.
6. Scheduled (session-only cron, dies with the session): L13 **run 3 during CBOE RTH** at
   07:43 CST 2026-08-19. If the session that created it is gone, do it by hand (§8).

## 3. Files changed (all append-only or behaviour-preserving unless stated)

| file | change | why |
|---|---|---|
| `collectors/com.janus.ibkr-gateway.plist` (+ installed copy `~/Library/LaunchAgents/…`) | `ProcessType` Background → **Interactive** | Background QoS starved the JVM; outbound TLS missed the 10 s limit |
| `collectors/run_ibkr_gateway.sh` | export `JAVA_TOOL_OPTIONS="-XX:TieredStopAtLevel=1 -XX:+UseSerialGC -Xms128m -Xmx640m -Xss512k -XX:ReservedCodeCacheSize=64m -XX:+AlwaysPreTouch"` + comment | fast warm-up / smaller resident footprint on the 8 GB host |
| `collectors/probe_ibkr.py` | `_underlying()` now treats a row as IND if any `sections[].secType == "IND"` | run-1 XSP mis-resolution; L13 selection-rule text unchanged |
| `tests/test_ibkr_readonly.py` | + `test_probe_underlying_uses_section_sectype_not_smallest_conid` | regression for the above |
| `snooping_ledger.md` | L13 row: **appended** EXECUTED note (rows immutable → note, like L12) | record verdict, both runs, entitlement codes |
| `research/exec/HYPOTHESIS_REGISTRY.md` | + TB-H11 (ladder vs option digitals), TB-H12 (MBT/BTC hedge), TB-H13 (FOMC vs ZQ), TB-H14 (IBKR freshness) — all BLOCKED | multiplicity honesty (trap 14) |
| `state.yaml` | + `track_b_hft.ibkr_capability` (verdict, codes, gateway fix, archive readiness, smoke artifacts, settlement-map v2, scheduled re-run, next_action) | state.yaml had no IBKR entry |
| `collectors/TRACK_B.md` | + "IBKR gateway operations" runbook section | restart/diagnose/health-check procedure |
| `research/exec/2026-08-18_ibkr-readonly-capability/verdict.md` | rewritten from the probe's stub into the full L13 verdict | required output of the spec |
| `research/exec/2026-08-18_ibkr-readonly-capability/results.json` | written by the probe (run 2) | spec output |

## 4. Files created

| file | purpose |
|---|---|
| `collectors/ibkr_archive_core.py` | pure mechanics + `ArchiveStorage` (WAL SQLite; tables `instruments, contract_roll, polls, quotes, health`; privacy denylist; selection helpers; session labels; `alarm_decision`) |
| `collectors/collect_ibkr_archive.py` | 1 Hz collector loop (auth/tickle keepalive, deterministic selection + daily reselect + rolls, poll/gap semantics, monitor/alarms, `--self-test`, `--duration-s`, `--families`) |
| `collectors/report_ibkr_archive.py` | read-only gate report (24 h guard, per-instrument mechanics, privacy scan) → `results.json`/`verdict.md` |
| `collectors/run_ibkr_archive.sh`, `collectors/com.janus.ibkr-archive.plist` | launchd wiring for the archive — **not installed** |
| `tests/test_ibkr_archive.py` | 11 hermetic tests (states, privacy, rolls, alarms, transport allowlist, report guard, underlying resolution) |
| `research/exec/2026-08-18_ibkr-forward-archive/settlement_reference_map.yaml` | v2; every pair BLOCK; M1 Kalshi rules facts; n=1 SPX discrepancy; unregistered measurement plan |
| `research/exec/2026-08-18_ibkr-forward-archive/spec_draft_UNREGISTERED.yaml` | L14 draft; **not registered** (no ledger row); fill families from an `R*` L13 before use |
| `research/exec/2026-08-18_ibkr-readonly-capability/results_run1_2026-08-19T0109Z.json`, `results_run2_2026-08-19T0112Z.json`, `verdict_run1_stub.md` | preserved run artifacts |
| `/Volumes/Kilos/janus/ibkr/smoke/archive_smoke{,2,3}_2026-08-19T01Z.sqlite` | diagnostic smoke DBs (delayed data; not research data) |
| `HANDOFF_TRACK_B_IBKR_2026-08-19.md` | this file |
| Memory notes (outside repo, `~/.claude/projects/-Users-bernardodelrio-Code-Janus/memory/`) | host memory-starvation lesson; gateway logs contain identifiers |

## 5. Files intentionally left untouched

- `lib/ibkr_readonly.py` — the allowlist is the safety boundary; no endpoint added (mtime 12:33, pre-session).
- `research/exec/2026-08-18_ibkr-readonly-capability/spec.yaml` — immutable (mtime 12:27).
- L10/L11 specs, `collectors/collect_track_b.py`, `com.janus.track-b-collector` — Kalshi/PM Phase A untouched, still running.
- `AGENTS.md`, `SHARED_SERVICES.md`, `handoffs/TRACK_B_BRIEF.md`, `lib/fees/*`, `lib/schema.py`, `lib/venue_costs.py`.
- IBKR's gateway install under `/Volumes/Kilos/janus/tools/clientportal.gw/` (jar, `bin/run.sh`, `conf.yaml`, logs) — nothing patched; its logs contain user/account/MAC identifiers: grep with redaction, never copy.
- Nothing under `~/Code/Kilos`; no `com.kilos.*` job; the user's VM and Kilos jobs were not killed.

## 6. Source-of-truth documents

`AGENTS.md` (pre-registration, immutability, snooping rules, disk safety, settlement-reference
amendment) · `handoffs/TRACK_B_BRIEF.md` (evidence tiers, IBKR-as-hedge-layer verdict, traps) ·
`snooping_ledger.md` (row/L-row rules) · `research/exec/2026-08-18_ibkr-readonly-capability/spec.yaml`
(L13 criteria; treated as immutable) · `SHARED_SERVICES.md` (Kilos boundary) · the user's session
brief (allowlist, `R*`-only rule, phase order, stop conditions). The 2026-08-17 phase-a spec set the
YAML house style for the L14 draft.

## 7. Current project state vs. initial

- Gateway: **healthy and responsive** (priority 31–37, <1 s start, 0.3 s calls) — was unusable.
- Auth: live account authenticated by the user at ~19:07 CST; will expire on IBKR's schedule.
- L13: **executed, BLOCKED on entitlement** for all three families; nothing `R*`.
- Archive: code + 11 tests ready; L14 **not registered**; nothing collecting.
- Settlement map: all pairs BLOCK, but the Kalshi side is now pinned from the venue (M1).
- Suite: **66/66**. Disk: internal 7–8 GB free (swap shrank), Kilos 759 GB.
- Open uncertainties: (a) whether the user will enable real-time subscriptions; (b) IBKR symbol
  for the 5-BTC contract (`BRR`?) — R, unverified; (c) official S&P close for 2026-08-18 (7691.76
  vs 7693.26 — which is official) — U; (d) `_updated` is the gateway's update time, not an exchange
  timestamp — exchange staleness U; (e) Kalshi indices rulebook "modified Source Agency" clause unread.
- Assumption stated: `D` (delayed) with the relevant sessions open means "not subscribed" (R legend).

## 8. Immediate next steps (prioritized)

1. **User decision:** enable IBKR real-time market data (CME Real-Time NP L1 for MBT/ZQ; CBOE
   Indexes; OPRA for SPX/XSP — R, prices unverified) or accept IBKR is unavailable as a real-time layer.
2. **L13 run 3 in CBOE RTH (09:30–16:15 ET):** `df -h` (abort < 2 GB internal) →
   `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/` (expect 66) →
   `python3 -c "from lib.ibkr_readonly import IBKRReadOnlyClient as C; print(C().auth_status())"`
   (if not authenticated: ask the user to log in at https://localhost:5055; never automate) →
   `PYTHONDONTWRITEBYTECODE=1 python3 collectors/probe_ibkr.py` from the repo root → copy
   `results.json` to `results_run3_RTH_<utc>.json`, redaction-grep it
   (`grep -cE "U[0-9]{6,}|acctId|cookie|([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"` must be 0) → append a
   run-3 row to `verdict.md` and a note to L13 in `snooping_ledger.md`. Criteria unchanged.
3. **Only if some family is `R*`:** rename `spec_draft_UNREGISTERED.yaml` → `spec.yaml` with
   `families_included/excluded` filled from run 3; append `L14 | PENDING` to `snooping_ledger.md`;
   run tests; `python3 collectors/collect_ibkr_archive.py --self-test`; then
   `cp collectors/com.janus.ibkr-archive.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.janus.ibkr-archive.plist`
   (edit `run_ibkr_archive.sh` to pass `--families <R* families>` first). Gate after 24 h with
   `python3 collectors/report_ibkr_archive.py`. Then write L15 characterization (descriptive only).
4. **Independent of IBKR (free, needs its own spec + L-row BEFORE reading):** measure the S&P
   settlement basis — Kalshi `expiration_value` (KXINX/KXINXU) vs CBOE SPXW/XSP PM exercise-settlement
   value vs S&P DJI official close over ≥20 expiries; read Kalshi's indices rulebook clause. Plan
   text is in `settlement_reference_map.yaml`.
5. If the gateway hangs again: `sysctl vm.swapusage; uptime; ps -o pri -p $(pgrep -f GatewayStart)`;
   `grep -c "handshake timed out" /Volumes/Kilos/janus/tools/clientportal.gw/logs/gw.message.*.log`;
   restart per `collectors/TRACK_B.md`. Do not blame auth first.
6. Never: add an endpoint to `lib/ibkr_readonly.py` without review + negative tests + approval;
   enable the `sbd` ladder topic; automate login; compare a Kalshi price to an IBKR price while
   its pair is BLOCK; start the archive under L13.

---

## 9. APPENDED 2026-08-19T04:15Z — session continuation

**Corrections to §2.6 and §8, verified this session.**

- **§2.6 is void: the scheduled L13 run 3 does not exist.** `crontab -l` → *no crontab*. The session
  cron died with its session, as §2.6 warned. `state.yaml` now records `rth_rerun_scheduled: false`
  and the run as an explicit **manual** step. Nothing was installed to replace it (operator's call).
- **Gateway health caveat for tomorrow's preflight.** `com.janus.ibkr-gateway` is up and the
  `ProcessType Interactive` fix held (priority **37**), but the JVM was observed at **RSS ≈ 4.7 MB**
  with swap **5.96/7 GB** and load 8.86 — the paged-out signature that produced the 10 s TLS hangs.
  Add `ps -o pid,pri,rss -p $(pgrep -f GatewayStart)` and `sysctl vm.swapusage` to the §8.2 preflight.
- **Operator decision on §8.1: real-time market data WILL be enabled.** Run 3 should be executed
  after the subscriptions show active in Client Portal — a run before activation only reproduces run 2.

**§8.4 is done, and it did not go where §8.4 expected.** Two L-rows spent (0 test looks):

- **L14 — STOP.** The registered design assumed a settlement date has one Kalshi S&P value. It does
  not: `KXINX` and `KXINXU` publish different `expiration_value` for the same date, same 16:00 ET
  instant, same rules sentence. Criteria not edited; corrected by a new row per ledger rule 6.
- **L15 — measured, per series.** **`KXINX` equals the official S&P 500 close on 42/42 dates, to the
  cent** (CI [0.00, 0.00]) → settlement map **v3**, pair `KALSHI_SPX_LADDER_vs_CBOE_SPX_XSP_OPTIONS`
  is now **`OK_FOR_KXINX_ONLY`**. **`KXINXU` stays BLOCK**: 15/37 exact, max |diff| **0.44** index
  points against `.9999` strikes. **A comparison that does not NAME its series stays BLOCK.**
- **The §7 open uncertainty (c) is resolved, and the answer was IBKR's error.** Official close
  2026-08-18 = **7691.76** = KXINX exactly; the IBKR SPX `last` of 7693.26 was read with the index
  feed **frozen (`Z`)** outside RTH.

**§8.6 prohibitions are unchanged and none were touched.** Nothing IBKR-dependent is unblocked —
L13's entitlement block is separate and survives all of the above. `lib/ibkr_readonly.py`,
the L13 spec, and the Kalshi Phase-A collector were not modified.

**Row numbering:** the archive draft's reserved label "L14" was corrected — it now takes the next
free row at registration, since L14/L15 were spent here.

Suite: **87/87** hermetic (was 66). New: `tests/test_spx_basis.py` (21 tests).

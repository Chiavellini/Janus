# HANDOFF — 2026-09-03 ~21:30 UTC (supersedes the 07:00 UTC handoff)

For the next agent. Read this, then `NEXT.md`, `BATTERY.md`, `GATE_TO_LIVE.md` (its 2026-09-03
amendment) and `snooping_ledger.md` rows L28–L35. The plan this session executed is at
`/Users/bernardodelrio/.claude/plans/help-me-proceed-with-glittery-brook.md`. Do not re-derive what
is below; every number here was measured or verified live today.

## 1. The project as encountered (07:00 UTC)

- Main and the branch `claude/janus-arbitrage-trader-4e6d4d` at `4c2e923`; `com.janus.live-stream`
  running main in SHADOW_LIVE on `--leagues mlb,nfl,nba,wnba,nhl --pre-hours 2`; suite green.
- The Kalshi execution proof stopped one step short of its armed run; the arming override had
  already been rewritten at `4c2e923` (the previous handoff did not know that).
- Six leagues hardcoded in three places; MLB the only league that certified; NFL blocked at
  `EVIDENCE_UNMEASURED`; three-way soccer impossible (two outcomes per game, `soccer_3way` uncited).
- No Polymarket wallet configured; no Ashburn instance ever launched; `ops/ASHBURN_SPORTS_RUNBOOK.md`
  described the retired REST lane; `/Volumes/Kilos/janus/...` spelled by hand in nine places.
- The non-sports matcher (`match/verify.py`) had been dropped from the grid at `5eac384`.
- Unclear at the start and resolved during the day: the operator's actual scope ("every sport and
  every live event both venues list; sports chosen for short contract life"), the NFL 2020
  decision (exclude), the box decisions (a new small instance; both keys with KMS custody).

## 2. What was done (33 commits, `4c2e923..86c87fe`, main = origin/main = the branch)

1. **Proof tooling.** `ops/proof_check.py` (the post-proof checklist as code; `--check` on both
   proof scripts); the Kalshi proof flow drivable offline by a fake venue; the Polymarket proof
   script (`ops/polymarket_live_proof.py`); the proofs use their own database
   (`/Volumes/Kilos/janus/tuples/proofs.sqlite`) and wait for locks.
2. **The Kalshi shard finding.** The first armed run was refused by the venue: `user_not_found`.
   Kalshi sharded its exchange on 2026-08-24 (baseball AND tennis on shard 3; basketball follows
   2026-09-10) and collateral is per shard. Every order now carries its market's `exchange_index`
   (`-1` = auto-route when unreadable, never a silent 0); `balances_by_shard()`; the proof refuses
   `SHARD_UNFUNDED`; `ops/kalshi_shards.py --show` / `--move --to 3 --usd 20 --confirm`.
3. **Coverage.** The co-listing census (ledger L28, daily under `com.janus.census`, two runs so far:
   1,021 co-listed events across 81 competitions); the league registry as one table
   (`nodes/entities/leagues.py`, `enablement()`, `default_leagues()`); three-way soccer as a third
   outcome (IFAB Law 10.1 cited, both venues' texts pinned per competition); college football
   (FBS+FCS); eight more soccer leagues; tennis as a `venue_structured` anchor (Polymarket's own
   events are the schedule; players are entities; Kalshi joins on names and ticker date).
   Twenty leagues registered; **nine run unasked**: mlb, nfl, epl, lal, bun, cfb, elc, el1, ita.
4. **Rates rows.** L30 NFL (L29 closed INCOMPLETE on the São Paulo Friday games), L32 college
   football (FLOOR for FCS), L33 EPL/La Liga/Bundesliga and L35 Championship/League One/Serie A
   (a round-window proxy over openfootball, labelled FLOOR and over-count; `DESIGN.md` records why
   no truer source exists). MLS, fl1, ere, por, scop, bel1, atp, wta block by name.
5. **The lane.** `--leagues enabled` (resolves to `default_leagues()`), `--pre-hours 6`,
   capture-only subscriptions for tennis (`--capture-series`, `--capture-pm-tags`; 30 Kalshi + 50
   Polymarket markets tonight); `kernel/paths.py` (`JANUS_DATA_ROOT`) threaded through every
   guard; portable `ops/run_node.sh` / `run_watchdog.sh` with a df guard; `run_index.py start`
   fixed (it never accepted the module invocation, so the wrapper's start row was never written).
6. **The Ashburn box.** `ops/box/` (launch, cloud-init, systemd units, `creds.py` materialising
   SSM SecureStrings into tmpfs, `latency.py`), the runbook rewritten, ledger L34 registered with
   the Mac baseline measured (Kalshi p50 175 ms, CLOB 407 ms). **Not launched: IAM (§8).**
7. **The generic verifier** recovered into `nodes/match_generic/` (reproduces the archived 51,306
   verdicts); ledger L31 declares its precision bar before any label exists.
8. **Venue facts learned today** (in code comments and the ledger): Cloudflare in front of
   `clob.polymarket.com` answers 403 to any browser User-Agent from a script (`kernel/fetch.py`
   now sends `janus/1.0`); Polymarket runs two soccer texts and two tennis texts side by side;
   Kalshi's balance breakdown rows are dollar strings while the top-level balance is cents.

## 3. Files changed (51) — what and why

- `grids/live_stream/grid.py` — `--leagues enabled`; capture-only watchlist sync and report;
  imports the registry.
- `kernel/fetch.py` — product User-Agent (Cloudflare).
- `nodes/capture/capture.py` — root from `kernel/paths`; the reader stops at the live hour's
  unfinished gzip member.
- `nodes/discovery/discovery.py` — venue-structured leagues take their schedule from Polymarket;
  outcome cardinality from the registry; the draw token; template text from a team market;
  surname outcome labels find their token by suffix.
- `nodes/discovery/README.md`, `tests/test_discovery.py` — census and three-way slate.
- `nodes/entities/seed.py` — reads the registry; Gamma pulls by tag id; players for
  venue-structured leagues (no bare-surname alias; per-tour event filter).
- `nodes/entities/*.csv` — re-seeded for twenty leagues (1,433 teams/players); `aliases_manual.csv`
  gained 78 soccer rows. `unresolved.csv` still lists 191 batch-2 soccer names and 1,070 tennis
  names (doubles pairs and players not currently listed).
- `nodes/exec_kalshi/client.py` — `shard_of()`, `exchange_index` on every order,
  `balances_by_shard()`; tests.
- `nodes/match_sports/sports_match.py` — the draw as a third outcome; Polymarket nickname fallback
  to outcome labels; slug pieces up to eight characters; ticker date for venue-structured leagues.
  `stage1_checkpoint.py` — tag-id pulls.
- `nodes/risk/{breaker,gate,health,kill}.py`, `nodes/store_tuples/store.py` — paths from
  `kernel/paths`; the store waits 30 s for locks.
- `nodes/rules_exhaustive/rules.py` — cited rules for soccer (5 leagues + batch 2), cfb, tennis.
- `nodes/schedule_espn/espn.py` — paths from the registry; per-group scoreboard calls; 1,000 teams.
- `nodes/settle_wedge/{policy,evidence,harvest,pair,equivalence}.py` — 23 templates, 30 pair
  policies; L30/L32/L33/L35 evidence; template scrub; every name suffix stripped on word
  boundaries; the `pm_half_vs_kalshi_result` loss model; `README.md` has the unblock workflow.
- `nodes/venue_polymarket/books.py` — `pm_outcome_tokens` (three-way), `pm_primary_market`.
- `ops/kalshi_live_proof.py` — `--check`, venue seam, `execute_steps`, shard refusal, proofs DB.
- `ops/run_index.py`, `ops/run_node.sh`, `ops/run_watchdog.sh`, `ops/watchdog.py`,
  `ops/com.janus.live-stream.plist`, `ops/README.md`, `ops/ASHBURN_SPORTS_RUNBOOK.md`.
- `BATTERY.md`, `CHANGELOG.md` (append-only entries), `NEXT.md` (overwritten), `README.md`
  (state of the evidence), `snooping_ledger.md` (rows L28–L35, appended results).
- Tests touched for the above: `nodes/{game_poller,replay,rules_exhaustive,settle_wedge,
  match_sports,venue_polymarket,exec_kalshi,entities}/tests/`.

## 4. Files created (106)

`ops/proof_check.py`, `ops/polymarket_live_proof.py`, `ops/kalshi_shards.py`,
`ops/com.janus.census.plist`, `ops/tests/{test_proofs,test_pm_proof,test_shards}.py`;
`ops/box/{launch.sh,user-data.sh,creds.py,latency.py,README.md,systemd/*,tests/test_box.py}`;
`kernel/paths.py`, `kernel/tests/test_paths.py`; `nodes/discovery/{census,watchlist,
venue_schedule}.py` and their tests; `nodes/entities/leagues.py` + `tests/test_leagues.py`;
`nodes/match_generic/{verify,block,score_gold}.py`, `gold/`, `tests/test_verify.py`, `README.md`;
`nodes/schedule_espn/tests/test_espn.py`; `nodes/settle_wedge/tests/test_soccer_three_way.py`;
research rows under `research/sports/2026-09-03_*` (census, nfl v1/v2, cfb, soccer, soccer batch2)
and `research/infra/2026-09-03_ashburn-latency/` (spec + the Mac results file).

## 5. Left untouched, deliberately

- `infra/` on main (another agent's uncommitted IAM files and `.vpc-id`/`.sg-id`): read, never
  edited. Its live trust policy dropped the MFA condition; flagged to the operator, not changed.
- `nodes/execute/plan.py` (two legs, Polymarket first): a three-way cover prices but is not
  planned; the design for two-leg soccer execution through a Polymarket NO token is in NEXT.md §5.
- `nodes/game_poller/poller.py:136` NO ladder (two outcomes only).
- `nodes/risk/limits.toml`, `GATE_TO_LIVE.md`, `AGENTS.md`, the arming override, all credentials.
- `research/sports/2026-09-03_nfl-settlement-wedge-rates/` (L29) stays as the INCOMPLETE record.

## 6. Source-of-truth documents

`AGENTS.md` (sacred rules: pre-registration, never a mid, unknown = BLOCK, canonical key),
`GATE_TO_LIVE.md` with its 2026-09-03 amendment (what the operator waived and what still gates),
`snooping_ledger.md` (immutable rows; every measurement here is a row), `BATTERY.md`, the previous
`HANDOFF.md`, and the operator's own words in this session (scope, 2020 exclusion, box choices,
"both keys with KMS"). Venue truth came from the venues' payloads and docs, quoted in code
comments: Kalshi Create Order V2 and Exchange Sharding pages, the Gamma `/sports` table.

## 7. Where it stands now

- Lane: `com.janus.live-stream` on main `86c87fe`, SHADOW_LIVE, nine leagues, 11–13 co-listed
  games under pollers at a time, tennis captured, watchdog quiet, census daily at 14:00 local.
- Today's evaluations (40,403): the only sub-par covers were the final seconds of three late MLB
  games amid `STALE`/`HASH_MISMATCH` flags on the Polymarket replica — closing books, not a hedge.
  Otherwise the fee floor absorbs a 1–3¢ divergence. Tennis frames exist but an offline replay
  cannot price the Polymarket side (it needs the lane's REST verification).
- **No proof has been placed.** The operator's four commands are in NEXT.md; the agent does not
  run `--arm`, `--confirm`, or write the override (the operator asked twice; refused twice).
- Polymarket credentials are configured on the Mac (key file 600, three env lines).
- The box: code, SSM `/janus/repo/{url,sha}` and the pushed repo are ready; launch denied by IAM.
- Uncertain: L33/L35 rates are a proxy that over-counts cup-related moves (the EPL reserve is
  ~1.9¢ at a 0.50 Polymarket price); soccer/tennis rate rows with true original dates need a
  forward snapshotter; the census join is deliberately loose (`JOIN_WEAK` labels).

## 8. Immediate next steps, in order

1. **Operator, at the machine**, from `/Users/bernardodelrio/Code/Janus` with
   `set -a; . /Volumes/Kilos/janus/credentials/track_b.env; set +a`:
   `python3 ops/arming_override.py --force --mode LIMITED_LIVE --signed-by "Bernardo" --stake-usd 5 --max-contracts 10 --day-notional-usd 20 --statement "..."`,
   `python3 ops/kalshi_shards.py --move --to 3 --usd 20 --confirm`, then
   `python3 ops/kalshi_live_proof.py --ticker <live KXMLBGAME market> --arm` and
   `python3 ops/polymarket_live_proof.py --slug <gamma slug> --outcome "<label>" --arm`; after
   settlement `--settle <file>`. The agent then runs `--check` on both, updates `BATTERY.md`.
   The override pins main's sha: **do not merge to main between the override and the armed runs.**
2. **Operator: IAM for the box.** Either carve `iam:PassRole` on
   `arn:aws:iam::986420598115:role/janus-box` out of the `iam:*` deny in the `janus-agent` role's
   `janus-scope` policy, or delete the admin user's inline `EarshotDenyDirectBoxLaunch`. Then
   `ops/box/launch.sh --go` (as the role: `JANUS_BOX_AMI` pre-resolved), the GitHub read-only
   token and the five secrets into SSM (`python3 ops/box/creds.py --dry-run` lists them), then the
   L34 box run (`ops/box/latency.py --host box`) before the lane starts there.
3. **Agent: the cover-cost distribution row** over the nine leagues (NEXT.md "the question that
   matters"): register before reading; per league and quantity; blocked reasons kept distinct;
   end-of-game rows separated from in-play rows (today's only sub-par prints were closing books).
4. **Agent: tennis rates row** (`tennis.walkover_rate`, `tennis.delayed_gt7d_rate`) from the
   ATP/WTA results archives, so tennis prices live; a replay option that trusts socket snapshots
   for the Polymarket side, so captured tennis can be replayed.
5. **Agent: the three-way NO ladder / two-leg soccer execution** (a leg covering a set of
   outcomes); manual aliases for the 191 unresolved batch-2 names; the forward football-data.org
   snapshotter (needs the operator's free token).
6. Checks after any change: `python3 -m pytest -q` from the tree root; `python3 ops/watchdog.py`
   quiet; `launchctl kickstart -k gui/$(id -u)/com.janus.live-stream` after a merge; the lane's
   `[slate]` and `[watch]` lines in `/Volumes/Kilos/janus/logs/live_stream.stdout.log`.

## 9. Constraints that cost time today, so the next agent does not rediscover them

- Kalshi: collateral per exchange shard; `exchange_index` on the market record; the balance
  breakdown rows are dollar strings; `user_not_found` means an unfunded shard.
- Polymarket: Cloudflare rejects browser User-Agents from scripts; two live soccer texts and two
  tennis texts; a college team's `teams[].name` is the nickname only; tennis outcomes are surnames.
- The wrapper's start row was never written before today; `launchctl kickstart -k` does not reload
  changed plist arguments (bootout + bootstrap does).
- A merge to main moves the runner sha and voids the override; `--settle` does not check it.
- Another agent's `infra/` work sits uncommitted on main; `git checkout --` only what you changed.

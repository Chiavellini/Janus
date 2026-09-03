# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-03, evening, on branch `claude/system-build-handoff-c80a2b` (not yet merged: the
arming override pins the runner sha, and nothing merges to main until the armed Kalshi proof has
written its file).

## Done

Substrate, the streaming lane, exhaustiveness as a proof, P0–P9 of the v1 plan (see
`CHANGELOG.md`). Today: the post-proof checklist as code (`ops/proof_check.py`, `--check`); the
co-listing census (ledger L28, `nodes/discovery/census.py`, daily under `com.janus.census`); the
league registry as one table (`nodes/entities/leagues.py`, `enablement()`); three-way soccer
(epl, lal, bun, mls) carried through as a third outcome with the rule cited and both venues'
texts reviewed, blocking only on unmeasured rates. Entities re-seeded for nine leagues; every
soccer name resolves.

## Now — what is left, and whose it is

**Yours, because I am not permitted to place orders:**
1. **The Kalshi proof on the production account.** The override is already written at the
   current main sha (`4c2e923`) and expires 2026-09-04T06:45Z. From the main checkout, with the
   credentials sourced: the dry run, then `--arm`, on any active two-sided `KXMLBGAME-*`; after
   the game, `--settle <file>`; then `--check <file>` (on this branch, or after the merge).
   If it slips past the expiry, rewrite the override with `--force` (HANDOFF.md).
2. **The merge.** After the armed run: `git merge --ff-only claude/system-build-handoff-c80a2b`
   on main, `launchctl kickstart -k gui/$(id -u)/com.janus.live-stream`, and load
   `ops/com.janus.census.plist` so the census runs daily (`launchctl bootstrap gui/$(id -u) …`).
3. **A funded Polymarket wallet** (key file 600, `JANUS_PM_WALLET_KEY_PATH`) and a new override
   whose statement names Polymarket; then `ops/polymarket_live_proof.py --slug … --outcome …`, dry run
   and `--arm`, on any live two-sided game market (`BATTERY.md`).
4. **Approval to start Ashburn** (billable). Another agent's `infra/` work is on main, uncommitted.
5. **Label the blind gold set** `nodes/match_generic/gold/nonsports.csv` (144 pairs; `label` = 1 if
   both texts are the same contract, else 0; never look at `nonsports.key.json` first). Ledger L31
   declared the bar before any label exists; `score_gold.py` scores it.

**Mine, in order (the operator's decision: coverage first):**
1. The census runs six more days; the rank from the median decides the unblock order
   (`nodes/settle_wedge/README.md`, "Unblocking a competition"). Day one says La Liga, college
   football, EPL, UFC, EFL Championship — and CS2/LoL where the join is weak.
2. Per-competition bounded rates for soccer (`soccer.<code>.postponed_gt48h_rate`,
   `soccer.<code>.cancelled_rate`). The source survey is done: no free source keeps the original
   kickoff, so the row is a round-window proxy (a floor) over openfootball + football-data.co.uk
   with cited cancellations, plus a forward football-data.org snapshotter for true dates —
   `research/sports/2026-09-03_soccer-settlement-wedge-rates/DESIGN.md`. Decide 2020 before
   registering. Until measured, soccer blocks by name.
3. ~~NFL rates~~ done (L30). ~~College football registration~~ done; its `cfb.*` rates need the
   same shape of row (a cited schedule-change table over ESPN's college schedule).
5. Three-way execution WITHOUT a three-leg order: every Polymarket market is Yes/No, so NO on
   the home market pays on {draw, away} and a soccer cover is two legs again (Polymarket NO on one
   side + Kalshi YES on that side, or the mirror). That needs `nodes/cover` to price a leg that
   covers a SET of outcomes (a cover = legs whose covered sets partition the proven outcome set;
   today one leg per outcome), `pm_outcome_tokens` to carry NO tokens, and the exhaustiveness
   proof to check the partition. Then `plan.py` stays two-leg. Sequencing three FOKs is not an
   option: two fills and one reject is an unhedged directional position (GATE cross-venue #2).
6. UCL and every competition ESPN does not schedule as home/away teams. Probed 2026-09-03: ESPN
   `mma/ufc/scoreboard` lists a card as one event with one competition per fight (fighters as
   competitors, no `homeAway`, athlete ids absent) — an anchor for UFC needs a card-aware parser
   and a fighter entity table; `tennis/atp/scoreboard` returns nothing and `cricket/scoreboard`
   404s, so tennis and cricket need the `venue_structured` anchor (participants and start from
   both venues' own fields, a per-competition alias table, a blind gold file scored before the
   lane sees it). UCL needs a club to be one entity across competitions (the xref table keys by
   venue id and refuses the collision today).
7. ~~The Polymarket proof script~~ done (`ops/polymarket_live_proof.py`; tests drive it against a scripted CLOB).
8. ~~The generic verifier~~ recovered into `nodes/match_generic/` (reproduces the archived 51,306
   verdicts exactly); its precision gate is ledger L31 and waits on your labels (below). After the
   labels: a settlement-reference equivalence record per surviving pair (source agency, threshold
   `≥` vs `>`, date), then a `venue_structured` anchor for threshold events.

**Time:** shadow evidence accrues under launchd; re-run L27 after a week of NFL traffic.

## Not now, deliberately

Any order before the risk node clears it. Ashburn before everything is proven locally.
`venue_cloudbet`, `venue_sxbet`, makers on Polymarket. Registering a league by editing a flag:
a league trades only when the rule, both templates and every bounded rate exist.

## The question that actually matters

Unchanged: **what is the distribution of cover cost**, per competition and quantity, with every
blocked reason kept distinct — now over every competition the census says both venues list.

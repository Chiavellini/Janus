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

**Yours, because I am not permitted to place orders or move money:**
0. **Fund Kalshi's shard 3.** Kalshi sharded its exchange (baseball and tennis on shard 3 since
   2026-08-24; basketball follows on 2026-09-10) and an order on an unfunded shard is refused `user_not_found`,
   which is what the first armed proof met. `python3 ops/kalshi_shards.py --show`, then
   `--move --to 3 --usd 20 --confirm`; the proof reads the market's shard and refuses
   `SHARD_UNFUNDED` until the money is there.
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
4. **The Ashburn launch is fenced by IAM** (your other agent's design): the admin user's inline
   policy `EarshotDenyDirectBoxLaunch` denies `ec2:RunInstances`, and the `janus-agent` role's
   `janus-scope` denies `iam:*`, which blocks `iam:PassRole` for the `janus-box` instance profile
   the box needs for SSM. Either carve `iam:PassRole` on `arn:aws:iam::986420598115:role/janus-box`
   out of that deny (a `NotResource`), or drop the inline deny; then `ops/box/launch.sh --go`
   (`JANUS_BOX_AMI` pre-resolved when launching as the role). Everything else for the box is in
   place: repo pushed, `/janus/repo/url` and `/janus/repo/sha` in SSM; the read-only GitHub
   token and the five secrets under `/janus/` are yours (`python3 ops/box/creds.py --dry-run`).
5. **Label the blind gold set** `nodes/match_generic/gold/nonsports.csv` (144 pairs; `label` = 1 if
   both texts are the same contract, else 0; never look at `nonsports.key.json` first). Ledger L31
   declared the bar before any label exists; `score_gold.py` scores it.

**Mine, in order (the operator's decision: coverage first):**
1. The census runs six more days; the rank from the median decides the unblock order
   (`nodes/settle_wedge/README.md`, "Unblocking a competition"). Day one says La Liga, college
   football, EPL, UFC, EFL Championship — and CS2/LoL where the join is weak.
2. ~~Soccer rates~~ done for EPL / La Liga / Bundesliga (L33, a round-window proxy labelled FLOOR;
   the EPL reserve it implies is ~1.9¢ at a 0.50 Polymarket price — large). The truer, smaller
   number needs a forward snapshotter of true original dates (`DESIGN.md`): a free football-data.org
   token (yours) and a daily job like the census. MLS has no rounds and stays blocked.
3. ~~NFL rates~~ done (L30). ~~College football~~ registered and measured (L32; a FLOOR for FCS).
5. Three-way execution WITHOUT a three-leg order: every Polymarket market is Yes/No, so NO on
   the home market pays on {draw, away} and a soccer cover is two legs again (Polymarket NO on one
   side + Kalshi YES on that side, or the mirror). That needs `nodes/cover` to price a leg that
   covers a SET of outcomes (a cover = legs whose covered sets partition the proven outcome set;
   today one leg per outcome), `pm_outcome_tokens` to carry NO tokens, and the exhaustiveness
   proof to check the partition. Then `plan.py` stays two-leg. Sequencing three FOKs is not an
   option: two fills and one reject is an unhedged directional position (GATE cross-venue #2).
6. ~~Tennis anchor~~ built (2026-09-03 evening): atp and wta are `venue_structured` leagues — the
   schedule is Polymarket's own game events, players are entities seeded from both venues, Kalshi
   joins on the players' names and the ticker date; both venues' texts are reviewed (retirement
   SAME; a walkover and a >7-day delay BOUNDED on `tennis.walkover_rate` and
   `tennis.delayed_gt7d_rate`, unmeasured, so tennis blocks by name while its frames are captured).
   Next for tennis: the rates row (walkovers and long delays per tour season from the ATP/WTA
   results archives), and doubles (excluded: a pair is not a player entity yet).
6b. UCL and every other competition ESPN does not schedule as home/away teams. Probed 2026-09-03: ESPN
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

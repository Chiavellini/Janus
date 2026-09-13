# Widening beyond moneyline — spike, 2026-09-13

Read-only spike. No source file, test or ledger touched. Branch `claude/hedge-ladder-speed-3b5042c`
(worktree `system-build-handoff-c80a2b`); `nodes/cover/cover.py`, `grids/live_stream/grid.py`,
`nodes/execute/{coordinator,plan}.py` and `ops/box/*` carry another agent's uncommitted edits.

This spike includes **one new offline measurement** (§4.1) taken from the archived July 2026 corpus
under `data/catalog/`. No venue API was called, no process started.

---

## 0. What it would take — the answer first

**A market family is not a flag here. It is a fourth registry axis that does not exist, plus two new
invariants — LINE AGREEMENT and COMPLEMENT-NOT-MIDDLE — neither of which anything on the sports path
checks.** Nine of the twelve settlement dimensions carry over unchanged, so the work is not in the
wedge policy; it is in **identity**, and the pricer's last-line partition check is count-based
(`nodes/cover/cover.py:248-250`) and therefore blind to both new failure modes.

Minimum honest build, in dependency order:

1. **A line in the identity.** `CanonicalKey.line_abs` exists (`kernel/schema.py:322`) with **zero
   producers and zero consumers repo-wide**; `canonical_key()` never sets it
   (`nodes/match_sports/sports_match.py:110-113`). Same for `Outcome.line_signed`
   (`kernel/schema.py:426`).
2. **A line in the proof key.** `ExhaustiveOutcomeSet` and `SettlementEquivalence` are keyed
   `(league, market_type, period)` (`nodes/rules_exhaustive/rules.py:53`,
   `nodes/settle_wedge/equivalence.py:209-212`). A spread proof under that key is valid for **every
   line at once**.
3. **A family axis in the league registry.** `League` carries one `kalshi_series` ("the game-level
   series") and one `outcomes` count (`nodes/entities/leagues.py:28,32`); both are moneyline's.
4. **A line column in persistence.** No table in the repo can store a line (§3.9).
5. **Kalshi strike ingestion.** `nodes/venue_kalshi/adapter.py:33-38` mints no `NormMarket` at all and
   reads no `floor_strike`/`cap_strike`/`strike_type` — the fields that *are* the line (§4.1).
6. **Per-family exhaustiveness rules with citations, templates, pair verdicts, and push rates** (§2).
7. **A per-series fee read** — `fee_multiplier` is never defaulted (`nodes/fees/models.py:156-159`),
   and the archive shows 441 of 449 spread/total series sit on a **different fee tier** than the
   moneyline series the lane has priced (§4.2).

**Size estimate: bigger than it sounds, but the reason is not the one in `NEXT.md`.** The three-way
soccer precedent is misleading: soccer added a third leg to one market; spreads add an axis of market
identity, and the kernel key, the matcher join, both mint-only proof types, the league registry and
the DB schema are all keyed without it.

**Two genuinely good pieces of news, both newly measured here:**

- **The venues DO quote overlapping lines.** On MLB, 13 of 13 co-listed events shared at least one
  line, for both totals and spreads (§4.1). The question this spike was most afraid of — "is a cover
  even possible?" — answers **yes**.
- **Every one of 4,397 archived Kalshi spread/total markets is a HALF-POINT line. Zero whole-number
  lines.** The push dimension, the thing that makes a spread structurally nastier than a moneyline,
  **does not arise** on the Kalshi side of this corpus (§4.1). And the exhaustiveness argument for a
  same-line cover is a logical complement, not a sport fact — *cleaner* than moneyline (§2.1).

**The one thing that is worse than expected:** Kalshi quotes a deep ladder (11–13 total rungs per
event) where Polymarket quotes 3. So for any PM line there are ~10 non-matching Kalshi rungs on the
same event and side. Without a line key the false-pair ratio is **worse than the 7-in-8 ISM PMI
failure already recorded in this repo** (§1.2).

---

## 1. THE KILLER RISKS — two of them, and the pricer catches neither

### 1.1 Different lines would pair, price, and report locked arbitrage

The join is exact equality on the frozen `CanonicalKey` plus the side:

```
nodes/match_sports/sports_match.py:398-406
    idx[(m.key, m.entity_id)].append(m)             # Polymarket indexed
    for p in idx.get((k.key, k.entity_id), []):     # Kalshi joined
```

`CanonicalKey` is `@dataclass(frozen=True)` (`kernel/schema.py:305`), so equality covers every field
**including `line_abs`**. The join is correct by construction and wrong by omission — the only
constructor never populates it:

```
nodes/match_sports/sports_match.py:110-113
def canonical_key(g, league: str) -> CanonicalKey:
    return CanonicalKey(league=league, participants=g.participants_espn, start_utc=int(g.start_utc),
                        market_type="moneyline", period="game")
```

So every sports key is `(league, participants, start_utc, "moneyline", "game", "win", None, None)`.
For a spread family reached by relaxing the discovery filters, Kalshi `total 8.5` and Polymarket
`total 9.5` on the same game produce **byte-identical keys** and pair.

Nothing downstream recovers it:

- `price_combination` checks covered sets are disjoint, then for singleton legs **only the count**:
  `nodes/cover/cover.py:248-250` — "singleton legs may carry venue ids as outcome names; the count is
  what can be checked."
- The same-book guard is `(liquidity_source, outcome_id)` (`cover.py:262-267`) — different lines have
  different ids, so it stays silent.
- The proofs cannot object: `certify_cover` compares `(league, market_type, period)`
  (`equivalence.py:209-212`); no line in either triple.

Result: a priced "cover" at 0.97 that is a **naked bet on the 8.5-to-9.5 band**, reported as locked
arbitrage and sized by a ladder that believes the edge is guaranteed. This is the +31% EPL bug
(`nodes/rules_exhaustive/rules.py:4-9`) with a new generator, and the exhaustiveness *type* built to
stop that bug cannot see it, because the outcome count really is 2.

### 1.2 The ladder: ~10 false rungs per true one

`idx` is a `defaultdict(list)` and every match is emitted (`sports_match.py:398-406,418`), so with
`line_abs` unset one Kalshi market pairs with every PM line and vice versa — the cross product.

Measured density (§4.1): on a co-listed MLB event Kalshi quotes 11–13 total rungs and PM quotes 3.
**Roughly 10 false pairs per true one.** The repo has already measured this exact failure, on the
non-sports path:

```
nodes/match_generic/verify.py:253-259
    """Kalshi states its threshold STRUCTURALLY; Polymarket states it in prose. Compare them.

    This is the dominant non-sports trap. Kalshi lists a full ladder on one event -- ISM PMI "At
    least 52" through "At least 59" are eight separate markets -- and blocking matched every rung to
    the single PM market at 59, because rung and target share every token but the number. Seven of
    those eight pairs are false and only the matching rung is real."""
```

The guard (`STRIKE_MISMATCH` `:272,280`; `STRIKE_DIRECTION_MISMATCH` `:284,286` for
same-number/opposite-side; `RANGE_VS_THRESHOLD` `:340`) is written, tested
(`nodes/match_generic/tests/test_verify.py:72-92,145`) and **orphaned**: `nodes/match_generic` is
imported by nothing outside itself (grepped across `nodes/ grids/ ops/ kernel/`). The sports lane has
no equivalent. `nodes/match_generic/block.py:46-48` even holds ready-made `spread` and `over_under`
archetype regexes, and `block.py:13,213` records the cost of not using them: the moneyline-vs-O/U
title trap produced **1,602 false candidates**.

**Partial existing fence, and exactly how far it goes.** The slate builder blocks a game when one
entity holds two differing match rows:

```
nodes/discovery/discovery.py:323-326
        ambiguous = [entity for entity, options in candidates.items()
                     if any(option != options[0] for option in options[1:])]
        if ambiguous:
            blocked[gid] = "AMBIGUOUS_DUPLICATE_OUTCOME_MATCH"
```

So the **ladder** case fails closed (loudly, as a whole-game block). But the **single mismatched
line** case of §1.1 — one Kalshi rung, one PM rung, different values — yields exactly one row per
entity, is not ambiguous, and **passes**. The fence catches the noisy failure and lets the dangerous
one through.

### 1.3 SECOND KILLER: a "middle" that passes the partition check

For a spread, `away by over 1.5` and `home by over 1.5` are **not complements** — the band
`|margin| < 1.5` satisfies neither. The archive shows Polymarket lists both sides at the same line
(`mlb-tb-nyy-2026-05-23-spread-away-1pt5` **and** `-spread-home-1pt5`, §4.1).

Two such legs are two legs on two entities, so `offers` gets two keys
(`grids/live_sports/grid.py:191`, keyed on `entity_id`), and the pricer's check is
`len(legs) != len(proof.outcome_ids)` → 2 == 2 → **passes**. It prices as a cover and pays $0 on
every one-run game.

This is the EPL three-way bug reborn in a form the fix for that bug does not cover: the outcome
*count* is right and the outcome *set* is not a partition. The compound-leg path immediately above
(`cover.py:244-247`) does compare `seen_out != set(proof.outcome_ids)` exactly — so the three-way
soccer path is strictly better defended than the two-way path a spread would use.

**A correct spread cover is one market's YES plus the same market's NO, on the same side and the same
line** (Kalshi YES `home by over 1.5` + Polymarket NO `home by over 1.5`) — not two sides.

### 1.4 Push convention — currently a non-issue, and keep it that way

```
kernel/schema.py:235-244
class TiePolicy(str, Enum):
    """Tie/push handling. $0.50 is NOT the same as a returned stake.

    Books use half-point lines specifically to avoid ties, so a whole-number total (push-eligible)
    is a DIFFERENT INSTRUMENT from a half-point total. The schema keeps them apart via `line_abs`."""
```

The schema names `line_abs` as the separator — the dead field from §1.1. But measurement says the
exposure is currently nil: **4,397 of 4,397 archived Kalshi spread/total strikes are half-integers,
zero whole-number** (§4.1). A half-point line cannot push.

So the right move is to **fence rather than model**: refuse any non-half-integer line outright. That
is one predicate, it deletes the entire push dimension from v1, and the data says it costs nothing.
(If a whole-number line ever appears: outcomes become `{cover, not-cover, push}`, neither venue lists
a push contract, and a 2-leg cover is flat only if both venues pay $0.50 a side — the NFL-tie
argument of §2.2.)

### 1.5 What would actually prevent all of this

Nothing today. In order:

1. **Populate `line_abs` (and `line_signed`) from each venue's own text** — never propagated from one
   venue to the other. Keep it a string; `kernel/schema.py:332-335` already refuses a float, with the
   reason ("45.5 as a float invites 45.499999 and a silent non-match").
2. **Add the line to both proof keys** (`rules.py:53`, `equivalence.py:209-212`) so one proof cannot
   span lines.
3. **Make the pricer compare outcome-id SETS, not counts** (`cover.py:248-250`). This is the only fix
   that catches §1.3, and it is the one change that would have caught both killers at the last gate.
4. **Port `strike_mismatch` + the direction check** (`nodes/match_generic/verify.py:253-288`) to the
   sports path as a hard pre-join gate.
5. **Refuse non-half-integer lines** (§1.4).

One accidental safety net, which will be the first thing an implementer deletes: `certify()` defaults
`market_type="moneyline"` (`equivalence.py:103`) and `certify_from_spec` never overrides it
(`nodes/settle_wedge/pair.py:36-46`), while the grid calls `prove(g.league, "moneyline", "game", ...)`
explicitly (`grids/live_sports/grid.py:215`; also `nodes/game_poller/poller.py:148`). Change only the
`prove()` call and `certify_cover` blocks on the triple mismatch. Real, but incidental — a label
comparison, not a line check.

---

## 2. Settlement equivalence for spreads and totals

### 2.1 The argument is *cleaner* than moneyline, for one specific reason

Moneyline exhaustiveness needs a sport fact: "can this game end in a tie?" — which is why every entry
in `RULES` carries a rulebook citation (`nodes/rules_exhaustive/rules.py:56-126`).

A same-line, same-side spread/total cover needs no such fact. `{A wins by over L}` and
`{A does not win by over L}` are **logical complements**: the set is exhaustive by construction, for
any sport, provided (a) `L` is not achievable as an exact margin — guaranteed by a half-integer — and
(b) both venues compute the margin over the **same period**.

So the citation for a spread family is not a tiebreaker rule. It is a statement about the **period**
and the **half-integer**, and it is close to sport-independent. That is a real simplification and it
is worth building around.

### 2.2 What a template pair must assert

Nine dimensions (`nodes/settle_wedge/policy.py:29-31`: `official_source`, `winner_determination`,
`postponement`, `cancellation`, `suspended`, `abandoned`, `player_non_participation`, `retirement`,
`dispute_revision`, `settlement_timing`) are event-and-venue properties, not family properties. For a
league already certified on moneyline they should transfer after a re-read.

What does **not** transfer:

| Assertion | Why it is new |
|---|---|
| **The line, verbatim, and which side it is stated from** | The instrument's identity. PM's slug gives side (`-home-`/`-away-`) and magnitude but **no sign**; the "over" semantics must be *proven* from rules text, not inferred (§4.1) |
| **`overtime`, RE-RULED for margin** | **The sharpest carry-over trap.** OT rarely changes *who won* — which is why the moneyline citations are clean — but routinely changes *by how much* and *the total*. A `SAME` verdict on `overtime` earned against moneyline text does **not** carry to a spread for the same league and same template pair |
| **Push behaviour** | `tie: NA` with the half-integer citation (the safe path, §1.4), or the NFL-tie structure below |
| **Whether the venue lists alternate lines** | Decides whether §1.2 is live |

The NFL tie precedent is the exact structural model for a push, if one is ever admitted:

```
nodes/rules_exhaustive/rules.py:76-84
    ("nfl", "moneyline", "game"): (
        2, "nfl_tie_pays_half_each_side",
        "... {home, away} is therefore NOT a partition of the game's outcomes; it is complete as a COVER
        because both venues pay each side $0.50 on a tie ... so one contract of each side receives
        exactly $1.00 in every terminal state. Valid ONLY paired with a venue pair whose
        settle_wedge verdict on 'tie' is SAME."),
```

### 2.3 Where a new family's proof plugs in — the exact seams

Both proof types are mint-only, so there are two doors and one composer:

| Seam | File:line | What a new family adds |
|---|---|---|
| Exhaustiveness rules | `nodes/rules_exhaustive/rules.py:56-126` (`RULES`, keyed `(league, market_type, period)`) | An entry per league per line class, with a citation; `None` citation blocks (`:137-140`) |
| Template registry | `nodes/settle_wedge/policy.py`, hash lookup at `:803` | One reviewed `Template` per venue, verbatim, with `reviewed_on` |
| Pair verdicts | `nodes/settle_wedge/policy.py:882-893` (`verdicts_for` → `PAIR_POLICY[(a,b)]`) | A verdict per dimension; any `UNKNOWN`/`DIFFERENT` blocks (`equivalence.py:149-152`) |
| Bounded rates | `nodes/settle_wedge/evidence.py` (`equivalence.py:148,153-158`) | A measurement per `evidence_key`, else `EVIDENCE_UNMEASURED` |
| Composition | `nodes/settle_wedge/equivalence.py:204-213` | Nothing today — but this is where a line component belongs |
| Readiness checklist | `nodes/entities/leagues.py:153-175` (`enablement`) | Hardcoded `("moneyline","game")` at `:162`, one `lg.outcomes` at `:168` |

### 2.4 THE TEMPLATE-HASH DILEMMA — now settled, and it is real

A template is the venue's rules text with per-game parts stripped, then hashed
(`nodes/settle_wedge/harvest.py:121-160`, `_sha` at `:163`). The normaliser strips participants, dates
and tickers — and **deliberately keeps numbers**:

```
nodes/settle_wedge/harvest.py:44-45
# Keep decimal points and numeric ratios: $0.50, 0.05 and 2:1 are substantive.
_STRIP = re.compile(r"[\"'“”‘’,;()\[\]]|(?<!\d)[.:]|[.:](?!\d)")
```

and `:122` states the intent: "retaining numbers in settlement rules".

**The archive settles which branch holds: the line is in the venue's own text.** A real Kalshi spread
market (`data/catalog/kalshi_markets.json`):

```
ticker  KXCFLSPREAD-26JUL31MTLOTT-MTL21
title   "Montreal Alouettes wins by over 20.5 points?"
yes_sub_title "Montreal Alouettes wins by over 20.5 points"
floor_strike 20.5   cap_strike None   strike_type "greater"
```

So **every distinct line hashes to a distinct template** → `TEMPLATE_UNKNOWN` → blocked
(`equivalence.py:110-116`) until a human registers it. MLB alone shows 14 distinct total lines and 3
spread lines (§4.1); across leagues and weekly turnover that is an unmaintainable number of
hand-reviewed templates.

The obvious fix is the trap. Add a `template_scrub` regex (`nodes/entities/leagues.py:40-42`, applied
first at `harvest.py:127-128`) to strip the number, and the template hash becomes line-blind —
**destroying the only place in the pipeline where the line was pinned to reviewed text.** You would
then hold a proof that the venues settle spreads equivalently and nothing saying they settle *the
same spread*.

The correct resolution is to do both halves deliberately: **scrub the line out of the template so one
template covers the family, and carry the line in the identity and the proof key as its own checked
component** (§1.5). Either half alone is a live-money bug. This is the load-bearing reason the work is
bigger than it sounds.

Mitigating fact: `strike_type` is `"greater"` for **all 4,397** markets and `floor_strike` is
populated for all 4,397. The line is available **structurally**, so it need not be parsed from prose
on the Kalshi side — once the adapter reads it (§3.8).

### 2.5 Artifact list for one new family

| Artifact | Where | Already handled? |
|---|---|---|
| Kalshi series ticker(s) | `nodes/entities/leagues.py:28` | **No** — one field, moneyline's; `kalshi_series_extra:43-45` is documented as more *game-level* series |
| PM slug/shape recogniser | `nodes/match_sports/sports_match.py:71-76,257-264` | **No** — actively rejects the family |
| Exhaustiveness citation | `nodes/rules_exhaustive/rules.py:56` | **No** |
| Outcome cardinality | `nodes/entities/leagues.py:32` | **No** — one count per league |
| Templates ×2 venues | `nodes/settle_wedge/policy.py` | **No** — zero spread/total templates exist |
| PAIR_POLICY verdicts | `nodes/settle_wedge/policy.py:882-893` | **No** — `overtime` must be re-ruled (§2.2) |
| Push rate | `nodes/settle_wedge/evidence.py` | **Not needed** if half-integer-only (§1.4) |
| Team aliases | `nodes/entities/` | **Yes** — event-level, family-independent |
| Fee params | `GET /series/{T}` → `Leg.fee_overrides` → `params_for` (`nodes/fees/registry.py:130-142`) | **Plumbing yes, values no** — and the tier differs (§4.2) |
| Tick / min order size | `nodes/venue_polymarket/books.py:84-89` | **Yes** — per-market from Gamma, flows automatically |
| PM notional / share floors | `nodes/cover/cover.py:57,63` | **Yes** — venue-wide |
| Kalshi strike ingestion | `nodes/venue_kalshi/` | **No** — reads none of it (§3.8) |
| `line_abs` / `line_signed` producers | `kernel/schema.py:322,426` | **No** — dead fields |
| A line column in the DB | all ~40 `CREATE TABLE`s | **No** (§3.9) |
| `STRATEGY_VERSION` | `nodes/opportunity/thresholds.py:29` = `"v1-taker-taker-moneyline"` | **No** — names the family |

---

## 3. What silently assumes moneyline

Good news first: **the lane fails closed for spreads and totals at six independent layers.** You
cannot accidentally trade one today. The risk lives entirely in what a widening patch removes.

**3.1 Proof keys have no line.** `nodes/rules_exhaustive/rules.py:53` — `RULES` keyed
`(league, market_type, period)`; all ~25 entries are `"moneyline"` (`:57,61,65,68,76,85,107,125`).
`equivalence.py:209-212` composes on the same triple. A `("mlb","total","game")` entry would prove
exhaustiveness **for all lines at once**.

**3.2 `prove()` enforces a COUNT, not a set.** `rules.py:145-149` checks `len(ids) != n`, where `n`
comes from the league row's game-market cardinality (`nodes/entities/leagues.py:32`, used at
`nodes/discovery/discovery.py:262`). Blind to which line the count belongs to.

**3.3 The pricer checks counts, not ids.** `nodes/cover/cover.py:248-250` — the mechanism behind both
§1.1 and §1.3.

**3.4 The league registry is one-market-per-league.** `nodes/entities/leagues.py:24-49`:
`kalshi_series` is "the game-level series" (`:28`); `outcomes` is "the cardinality of the game market"
(`:14-15,32`); `pm_prefix` is "the full-game slug prefix: `{prefix}-{away}-{home}-{date}`" (`:30`), a
shape admitting one market per game. `enablement()` hardcodes
`RULES.get((code, "moneyline", "game"))` (`:162`) and compares to the single `lg.outcomes` (`:168`), so
it cannot express "moneyline ready, totals not".

**3.5 Discovery rejects the families by slug, and the rejection is frozen in tests.**
`sports_match.py:71-76` (`_fullgame_slug`, exact segment count), applied at `:257`, reason literal
`"derivative_event_not_full_game_moneyline"` at `:263`, documented at `:56-60`. Pinned by
`nodes/match_sports/tests/test_match.py:26-30`; cross-family pairing pinned by `:45-48`
(`pair(k, [vm(..., mtype="spread")]) == []`).

**3.6 The census excludes the series, also frozen.** `nodes/discovery/census.py:38-39`
(`GAME_SUFFIXES = ("GAME","FIGHT","MATCH")`), `:241-243` (`is_game_series`), and
`nodes/discovery/tests/test_census.py:58` **asserts `KXMLBSPREAD` is not a game series**. So the
ranking census cannot see spread capacity either.

**3.7 The Polymarket adapter understands exactly two moneyline shapes.**
`nodes/venue_polymarket/books.py:107-142` returns `{}` unless the event is one market carrying the
event slug with two outcomes, or three per-side markets each with
`sportsMarketType == "moneyline"` (`:130`; `:154` for NO tokens; `:101` primary market). Same filter at
`census.py:100,345`, `venue_schedule.py:157`, `sports_match.py:305`, `stage1_checkpoint.py:274`,
`reconcile/settle_executions.py:103`, `watch_settle/settle.py:115` — **eight sites**, each a fence and
each a place a widening patch must be audited.

**3.8 Kalshi strike fields are never ingested.** `nodes/venue_kalshi/adapter.py:33-38` — `discover()`
returns `()`, `normalize()` returns `None`, so no `NormMarket` (and therefore no `CanonicalKey`/
`Outcome`) is ever minted from Kalshi. `nodes/venue_kalshi/books.py:22-52` parses ladder levels and
`fee_type`/`fee_multiplier` only. The one place the sports path touches strikes is
`stage1_checkpoint.py:230-233`, where `strike_type` is compared for conflict detection and
**discarded**. `custom_strike` elsewhere is used purely as a team-UUID carrier
(`sports_match.py:155-157`, `entities/resolve.py:22,27`). The line is in the payload and the lane
throws it away.

**3.9 Nothing can persist a line.** ~40 `CREATE TABLE`s across `store_tuples`, `opportunity`,
`execute`, `discovery`, `reconcile`, `risk`, `exec_polymarket`, `watch_fd`: **no line, handicap,
threshold, strike or market_type column.** `latest_markets.family`
(`nodes/store_tuples/store.py:24-27`) looks promising but only ever receives the literal `"sports"`
(`grids/live_sports/grid.py:196`, `nodes/venue_cloudbet/join.py:246`) — a venue-category tag, not a
market family. The slate spec has no `market_type` field (`discovery.py:398-408`) and the events DDL
has no such column (`discovery.py:426-435`), so `market_type` is **re-asserted from literals
downstream** rather than carried.

**3.10 Title parsing would mangle a line, or silently swallow it.**
`census.py:334-339` (`_split_title`) strips parentheticals, keeps only text **after** a colon, then
splits on `vs`/`v`/`@`. `"Chiefs -3.5"` → `["Chiefs -3.5"]` (one participant → rejected at
`:391-392`); `"Chiefs vs Ravens: Over 47.5"` → `["Over 47.5"]` (**both team names discarded**). Worse,
`norm_tokens` (`:246-248`) keeps only tokens of length ≥ 4, so `"chiefs -3.5"` → `{"chiefs"}` —
**"Chiefs -3.5" and "Chiefs -7" are the same participant** to `participant_match` (`:381-384`).

**3.11 Dead orientation fields.** `line_abs` (`kernel/schema.py:322`) and `line_signed` (`:426`)
appear **only** in `kernel/schema.py` (lines 27, 239, 322, 332, 334-335, 426). `MARKET_TYPES`
(`:50`) — which already contains `"spread"` and `"total"` — is referenced nowhere outside
`schema.py`. Whoever wrote the kernel anticipated this work; nobody wired it.

---

## 4. Evidence — what exists, plus one new measurement

### 4.1 NEW: the venues DO overlap on lines (offline, from the archived corpus)

Prior research had **no** count of co-listed spread/total markets, because every census excluded them
before counting (§3.6, and `research/sports/2026-09-03_co-listing-census/spec.yaml:19-20`). But the
July 2026 raw corpus under `data/` (symlink → `/Volumes/Kilos/janus`, ledger row L1,
`snooping_ledger.md:53`) kept everything the live adapters discard. I measured it in place.

**`data/catalog/kalshi_series.json`** — 12,184 series: **189 containing `SPREAD`, 260 `TOTAL`,
9 `MARGIN`**.

**`data/catalog/kalshi_markets.json`** — 72,351 markets, of which **4,397 spread/total**
(1,617 + 2,780):

- `floor_strike` populated **4,397 / 4,397**; `strike_type` == `"greater"` for **all 4,397**.
- **Half-integer strikes: 4,397 / 4,397. Whole-integer: 0.** → no push exposure in this corpus.
- Rungs per (event, side) for spreads: mostly 2–5, with tails to 19 and 29.

**`data/catalog/pm_markets.json`** — 106,136 markets; PM encodes family, side and line in the slug:
`mlb-tb-nyy-2026-05-23-spread-away-1pt5`, `...-spread-home-1pt5`, `...-total-7pt5`. Both sides are
listed at the same line (the §1.3 middle trap) and multiple lines per game are listed. Note the
archive predates `sportsMarketType` (0 occurrences), so the live PM filter cannot be evaluated from it.

**The join (MLB, the one league in season on 2026-07-25):**

| Family | Events co-listed on both venues | Of those, ≥1 SHARED line |
|---|---|---|
| Totals | 13 | **13** |
| Spreads | 13 | **13** |

Representative rows (PM lines / Kalshi lines / intersection):

```
totals   2026-07-25 kc-det    [7.5, 8.5, 9.5] / [2.5 … 12.5]      -> [7.5, 8.5, 9.5]
totals   2026-07-25 tor-bos   [7.5, 8.5, 9.5] / [1.5 … 11.5]      -> [7.5, 8.5, 9.5]
spreads  2026-07-25 kc-det    [1.5, 2.5]      / [1.5, 2.5, 3.5]   -> [1.5, 2.5]
```

**Reading.** Polymarket's line set is essentially a **subset** of Kalshi's deeper ladder: PM quotes ~3
rungs, Kalshi 11–13. So (a) a same-line cover is available on every co-listed event measured, and the
surface multiplier is real — roughly 3 shared total lines × 2 sides + 2 shared spread lines × 2 sides
≈ 10 contract-pairs per event against 1 for moneyline; and (b) the false-pair ratio without a line key
is ~10:1, worse than the ISM PMI case (§1.2). **Both the opportunity and the hazard are larger than
the brief assumed, for the same structural reason.**

**Honest limits of this measurement.** One venue-snapshot day (2026-07-25), MLB only, n=13 events;
team matching was loose abbreviation containment; NFL/CFB spread *markets* are absent because July is
the offseason (their *series* exist, with fee tiers). It measures **listing, not depth**, and it does
not prove the two venues' "over L" semantics or orientation are identical — that needs rules text.

### 4.2 NEW: the fee tier differs for almost every spread/total series

`data/catalog/kalshi_series.json` carries `fee_type` and `fee_multiplier` per series, so this is
answerable offline:

- **441 of 449** spread/total series: `("quadratic", 1)`
- **8 of 449**: `("quadratic_with_maker_fees", 1)` — including `KXNFLSPREAD`, `KXNFLTOTAL`,
  `KXNBASPREAD`, `KXNBATOTAL`, `KXNCAAFSPREAD`
- `KXMLBSPREAD` / `KXMLBTOTAL` are **plain `quadratic`**, while `KXMLBGAME` is
  `quadratic_with_maker_fees`

This matters because the two tiers differ in **both** coefficient handling and rounding unit:

```
nodes/fees/models.py:153-165
    if ft == "quadratic_with_maker_fees":
        return 1.0, 0.0001              # verified 2026-09-04: multiplier not applied, 1/100 cent
    if ft.startswith("quadratic"):
        return float(mult), 0.01        # multiplier APPLIED, ceil to the whole cent
```

Quantified (taker 0.07, multiplier 1, one order):

| q | p | 1/100-cent tier | whole-cent tier | delta |
|---|---|---|---|---|
| 5 | 0.50 | $0.0875 | $0.0900 | +$0.0025 |
| 5 | 0.80 | $0.0560 | $0.0600 | +$0.0040 |
| 10 | 0.50 | $0.1750 | $0.1800 | +$0.0050 |
| 10 | 0.80 | $0.1120 | $0.1200 | +$0.0080 |

**Material, not decisive.** At 10 contracts the whole-cent ceil costs ~$0.005–0.008 per Kalshi order —
roughly 10–16% of `EXECUTION_MIN_NET_PROFIT_USD = 0.05`
(`nodes/opportunity/thresholds.py:28`). It must be in the model before sizing, and
`grids/live_sports/grid.py:164-171` already blocks a game whose fee schedule was not fetched, so it
fails closed. Worth remembering how this bit before: the lane "had priced every sports leg at half its
real Kalshi fee until this pin" (`models.py:138-147`).

### 4.3 Depth: still zero evidence, confirmed three ways

- `data/sports/stage3/observations_*.csv` header is
  `contracts,cost,edge,fee,game_id,gross,legs,max_leg_age_s,ok,reject,single_venue,utc,venues` — no
  line column, and no spread/total ticker appears in any row.
- `data/match/arb_candidates.json` carries touch prices only (`kalshi_yes_ask/bid`,
  `pm_best_ask/bid`, `pm_liquidity`) — **no ladder, no size at touch**.
- `data/tuples/tuples.sqlite` is fed by the moneyline-only matcher (`grids/live_sports/grid.py:196`),
  so no spread market can have entered it.

The `data/match/` archetype counts (13,143 same-family screened candidates) are **not** a co-listing
count: that pipeline's output was established as a tooling artifact (`snooping_ledger.md:63`, L9), the
archetype is a title regex spanning all 16 categories, matching archetype does not mean matching line,
and `data/match_2026-08-20/verified_candidates.json` holds 237 verified pairs of which **not one** is
a spread or handicap.

**So the thinness claim in `NEXT.md:105` is unmeasured in both directions.** It is a reasonable prior,
not a finding.

### 4.4 The recorded deferrals, and a binding pre-registration

- `research/sports/2026-08-17_stage2-matching/spec.yaml:37-42` — `market_type: moneyline`, with
  `market_type_rationale`: *"Spreads and totals require the line to match EXACTLY … which is a
  strictly harder key and is deliberately deferred."* This spike's §1 is that sentence, mechanised.
- `research/sports/2026-08-17_stage2-matching/verdict.md:117-120,146` — **27 PM derivative events
  rejected**, 15 kept as hard negatives in the gold file. The only existing count, and it is of
  rejections. Ledger row L9, `snooping_ledger.md:63`.
- **`research/sports/2026-08-17_stage3-divergence/spec.yaml:115` — *"Do not reach for spreads/totals
  or another league to rescue it without a NEW registered spec."*** This is a binding
  pre-registration and it governs §5: the work needs its own registered spec, not an extension of an
  existing row.
- `research/sports/2026-09-01_pure-arb-event-scan/spec.yaml:26,31` declared
  `market_types: [moneyline, spread, total]` with a match key including **line** — but the run
  produced one moneyline game. `research/sports/2026-09-01_three-venue-pure-arb/spec.yaml:12,22` says
  the same and contains only a spec: **pending, never run.** The design intent has existed twice and
  has never been executed.
- `NEXT.md:103-106` — "Not now, deliberately", for two reasons: `STRATEGY_VERSION` is moneyline-only,
  and thinner books slip more while slippage is the binding problem.

### 4.5 The depth evidence that does exist argues for caution

`research/exec/2026-09-11_hedge-slippage-sekulic-moriya/verdict.md`, two real **moneyline**
executions:

- Kalshi plan book showed `0.16 × 56.66, 0.17 × 40, 0.18 × 102, 0.19 × 10` — 142 displayed contracts
  across three levels. All gone within **1.64 s**; a 10-contract IOC zero-filled five times and filled
  at 0.19, the fourth level of the plan book.
- "the FIFO at an unchanged touch is not the cause, **the touch was gone**."
- Net on the two covers: −$0.0951 and +$0.14.

Against `EXECUTION_MIN_LOCKED_RETURN = 0.005` and `EXECUTION_MIN_NET_PROFIT_USD = 0.05`
(`thresholds.py:16-28`), displayed depth on the deepest co-listed family evaporating inside two
seconds is the real constraint. A thinner family does not get a better draw. **This is why §5 puts a
depth measurement before any code.**

### 4.6 The cheap measurement that closes the remaining gap

Listing overlap is now answered (§4.1). Fee tiers are answered (§4.2). **Only depth is open**, and it
is the one that decides whether the surface is tradeable.

Cheapest sufficient measurement, in order of cost:

1. **Free, offline, do it first:** archive one Kalshi spread market's `rules_primary`/`rules_secondary`
   and one PM spread market's `description` from the corpus, and settle (a) whether the rules text
   names the line (§2.4 predicts yes), (b) the exact "wins by over L" semantics and orientation on
   both venues, and (c) whether PM's `-home-`/`-away-` maps to Kalshi's per-team ladder as assumed.
   This is a read of two JSON records and it de-risks the entire equivalence argument.
2. **Capture-only depth, using the mechanism that already exists.** `nodes/discovery/watchlist.py`
   is purpose-built for "markets both venues list that the lane cannot yet co-list" (`:1-11`), with
   `nop = lambda _market_id, _now: None` on update (`:90`) — no pricing, no evaluation rows.
   `kalshi_watch(series, …)` (`:24-36`) takes arbitrary series tickers and applies **no market-type or
   strike filter**; `pm_watch_events` (`:44-69`) takes arbitrary tags with a slug-prefix filter
   (default `("atp-","wta-")` at `:45`). The capture series list is an argparse default
   (`grids/live_stream/grid.py:1486`).
   Subscribe ONE league's spread/total series for one slate and measure displayed depth,
   two-sidedness, and touch persistence against the moneyline books captured in the same window.

**Named hazard, do not skip it.** These replicas go on the **shared sockets** (`watchlist.py:84-88`,
L89), and the repo records that on 2026-09-04 "one ITF market's token got the whole socket dropped by
the venue every ~30 s" (`:62-64`). §4.1 measures 11–13 Kalshi rungs per event × ~13 events — hundreds
of new replicas from one league. Cap the token budget hard, watch `socket_health` and the
reconnect/`[record]` counts, and be ready to unsubscribe. Do not run this against the live sockets
during a slate the lane is trading.

---

## 5. Sequencing — smallest provably-safe increment

`research/sports/2026-08-17_stage3-divergence/spec.yaml:115` requires a **new registered spec** before
any of this. Steps 0–4 touch no money and no live decision path. A gate fail is a STOP, not a retry
(`GATE_TO_LIVE.md:7-19`).

**Step 0 — Register the spec; pick the family on the evidence.**
ONE family, ONE league, **half-integer lines only** (§1.4), **same-side YES/NO covers only** (§1.3 —
never away-side against home-side). **Totals before spreads**: one line per event instead of a signed
line per side, so the orientation ambiguity of §2.2 does not arise. MLB is the only league with
corpus evidence (§4.1).
*Gate:* the §4.6-item-1 rules-text read confirms the "over L" semantics and orientation on both
venues. If the two venues' margin/total definitions differ on period, **stop** — nothing else matters.

**Step 1 — Depth measurement, capture-only.**
Per §4.6 item 2, under a hard token cap and off a trading slate.
*Gate:* displayed depth and touch persistence on the shared lines are within a stated factor of the
moneyline books measured in the same window — and the live lane's reconnect/`[record]` counts and
`socket_health` are unchanged. Given §4.5 this is the gate most likely to fail, and failing it here
costs nothing but a slate of frames. **If it fails, stop: the surface is real but untradeable, which
is a complete and valuable answer.**

**Step 2 — Line identity, offline, no new family enabled.**
Populate `CanonicalKey.line_abs` and `Outcome.line_signed`; ingest Kalshi
`floor_strike`/`strike_type` (§3.8); port `strike_mismatch` + the direction check
(`nodes/match_generic/verify.py:253-288`) as a hard pre-join gate; add the line to both proof keys;
**change `cover.py:248-250` to compare outcome-id sets rather than counts** (the one fix that catches
both killers); refuse non-half-integer lines; add the DB column (§3.9).
*Gate:* tests that (a) an `8.5`/`9.5` pair refuses to **pair**, (b) it refuses to **price** even if
hand-forced past the matcher, (c) an away-side + home-side pair at the same line is rejected as a
middle, (d) a whole-number line is refused. **Plus** the existing moneyline decision replay rebuilds
every logged decision with zero mismatches (`GATE_TO_LIVE.md` step 4) — this step edits the kernel key
and the pricer, so it must prove it changed nothing for moneyline.

**Step 3 — The proof artifacts.**
Templates for both venues; `PAIR_POLICY` verdicts with **`overtime` re-ruled for total/margin** and
not inherited from moneyline (§2.2); the exhaustiveness citation built on the complement +
half-integer argument (§2.1); the §2.4 resolution (scrub the line from the template *and* carry it in
the key); the per-series fee tier from the payload (§4.2).
*Gate:* `enablement()` (extended to the family) returns `[]`; a deliberately unregistered line and an
edited rules text each block with a named code.

**Step 4 — Recording-only pricing on real books.**
Price the family with execution disabled; measure the fee-net edge distribution against
`EXECUTION_MIN_LOCKED_RETURN` / `EXECUTION_MIN_NET_PROFIT_USD`.
*Gate:* a measured after-fee edge distribution clearing the hurdle on a non-trivial count of
market-seconds, **and** a hedge-slippage estimate for these books that does not eat it.

**Step 5 — Real money: only behind a new dated GATE row.**
`STRATEGY_VERSION` changes (`thresholds.py:29`), so this is a new strategy, not a wider one. The
operator writes the GATE row naming family, league, line class and caps. Nothing in steps 0–4
requires an arm, an override, or a mode switch, and none should be taken.

---

## 6. Verdict

Widening is not a config change and not "soccer but simpler". It introduces a market-identity axis —
the line — into a system whose kernel key, matcher join, two mint-only proof types, league registry
and entire DB schema are keyed without it. The kernel anticipated exactly this and left
`line_abs`/`line_signed`/`MARKET_TYPES` ready; nothing wired them, and the settlement-equivalence
machinery cannot express "same line" at all.

**Three findings that change the decision:**

1. **The surface is real.** 13 of 13 co-listed MLB events shared at least one line on both venues, in
   both families, and Polymarket's lines are a subset of Kalshi's deeper ladder — roughly a 10×
   contract-pair multiplier per event (§4.1). This is the first time anyone in this repo has measured
   it, and it was free.
2. **The push problem is currently absent, and the exhaustiveness argument is *easier* than
   moneyline.** All 4,397 archived Kalshi spread/total strikes are half-integers, and a same-line
   same-side cover is a logical complement rather than a sport fact (§1.4, §2.1). Fence out
   whole-number lines and this whole class of risk disappears.
3. **Two distinct ways a spread "cover" is not arbitrage, and the pricer's final check catches
   neither**, because it compares outcome *counts* to the proof (`nodes/cover/cover.py:248-250`):
   **different lines** (§1.1 — Kalshi 8.5 against Polymarket 9.5 produces byte-identical canonical
   keys and prices as locked arbitrage on a naked band), and **a middle** (§1.3 — away-by-over-1.5
   plus home-by-over-1.5 is two legs, two entities, count 2 == 2, and pays $0 on every one-run game).
   The ladder density measured in §4.1 makes the first failure ~10:1, worse than the 7-in-8 ISM PMI
   failure already recorded here — and the guard that catches it
   (`nodes/match_generic/verify.py:253-288`) exists, is tested, and is orphaned from the sports lane.

The remaining unknown is the one `NEXT.md:105` asserts without measuring: **depth**. Listing overlap
and fee tiers are now settled offline; thinness is not, and §4.5 says displayed depth on the *deepest*
co-listed family evaporates inside two seconds. So the next action is not code — it is the capture-only
depth measurement of §4.6, which can kill or justify the project for the cost of one slate of frames,
and which must be run off a trading slate under a hard token cap because these replicas share the live
lane's sockets.

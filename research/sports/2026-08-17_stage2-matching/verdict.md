# Stage 2 — cross-venue matching. The first falsifiable result.

**Date:** 2026-08-17 · **Track:** sports · **Ledger row:** L9 · **Spec:** `spec.yaml` (registered
before the matcher existed) · **Prices read: none.**

| Gate | Threshold | Result | |
|---|---|---|---|
| Coverage | ≥ 0.80 | **1.00** (41/41) | PASS |
| Precision | ≥ 0.98 | **1.00** (36/36) — *0.9722 as-run, see below* | PASS |
| Gold recall | not gated | 1.00 (36/36) | — |

**41 completely-paired games · 82 outcome pairs · 0 false positives.**

---

## The headline: n=35 was a tooling artifact

Phase 1 found **35** high-quality matched pairs across the **entire ~100k-market corpus, all
categories**, and concluded from that sample that no tradeable cross-venue arbitrage exists.

Stage 2 finds **41 completely-paired games (82 outcome pairs) in one league, in one 8-day window**,
at precision 1.00, with **no similarity score, no threshold, and no recall cap**.

The corpus phase 1 declared empty is densely populated. Its central negative rested on a matcher
that could not see the pairs.

**What this does NOT establish.** Nothing about edge. No price was read, no orderbook fetched. Both
sides being *listed* is filter one of four; whether prices diverge, whether both sides are
tradeable, and whether depth exists are Stage 3. A dense corpus of perfectly-matched, perfectly-
agreeing markets is still no trade. This result removes an *excuse*, not a *doubt*.

---

## Finding 1 — Kalshi's coverage gap is a 72-hour listing horizon, not a limit

Stage 1 observed Kalshi listing 41 of 99 scheduled MLB games and could not say why. The two
possible explanations have opposite consequences: a listing horizon is harmless, a genuine
coverage limit halves the addressable set.

| Hours to first pitch | Kalshi-listed | Scheduled | Rate |
|---|---|---|---|
| < 24h | 11 | 11 | **1.00** |
| 24–48h | 15 | 15 | **1.00** |
| 48–72h | 15 | 15 | **1.00** |
| 72–96h | 0 | 9 | **0.00** |
| > 96h | 0 | 49 | **0.00** |

A clean step function. **Inside 72 hours Kalshi lists every scheduled game.** The addressable set
is not halved — it is time-shifted.

Two consequences that bind on Stage 3: a forward collector must **poll continuously rather than
snapshot**, because a snapshot taken at the wrong moment sees a fraction of the slate and looks
like a coverage failure; and sampling must begin **inside 72h of first pitch** or it observes
nothing on the Kalshi side.

## Finding 2 — the precision gate failed as-run, and the gold label was wrong

This is the part most worth scrutinising, because it is the shape of every self-serving correction.

**As run, precision was 0.9722 — a FAIL** — on exactly one pair:
`KXMLBGAME-26AUG191420CWSCHC` ↔ `mlb-cws-chc-2026-08-19`.

That is the crosstown Cubs–White Sox game, where Kalshi's rendering is literally *"Chicago WS vs
Chicago C"*. Ground truth from the two venues' own published text:

| | Kalshi | Polymarket |
|---|---|---|
| Teams | Chicago WS vs Chicago C | Chicago White Sox vs. Chicago Cubs |
| Start | Aug 19, 2:20 PM EDT = **18:20:00Z** | **18:20:00Z** |

Identical participants, identical instant. **The matcher was right and the label was wrong.** The
gold labeller used substring containment, and `"chicago ws"` is not a substring of `"chicago white
sox"` — "WS" is an *acronym*, not a prefix. The matcher never had this problem because it joins on
Kalshi's exact `custom_strike` UUID.

**How the correction was made, so it can be checked:**

1. The corrected labeller (prefix **and** acronym aware) was applied **uniformly to all 128 rows**,
   not to the failing row. It produced **exactly one change, 0→1**, and **zero** changes in the
   direction that would have hurt precision.
2. It carries sanity assertions that it still **refuses** to cross-match Cubs↔White Sox — it is not
   merely a more permissive labeller.
3. The correction was **appended as row `g0129` with `supersedes=g0102`**. Row `g0102` is intact in
   the file with its original label and original basis, per the spec's append-never-edit rule. The
   scorer applies corrections last-wins and reports how many it applied.
4. **Both figures are reported everywhere**: 0.9722 as-run, 1.00 corrected.

If you want the conservative reading, take **0.9722 with n=36** and note it is one disputed pair on
a small sample. The gate as written is passed on the corrected labels; the honest summary is that
the matcher made zero errors and the labeller made one.

## Finding 3 — the gold set is *easier* than the live distribution, not harder

Five emitted pairs fell outside the gold file entirely (scored "not judged", not as errors):

| Kalshi label | PM label |
|---|---|
| `A's` | `Athletics` |
| `Chicago C` | `Chicago Cubs` |

Both are the *same* failure mode as Finding 2 — the gold **candidate generator** also used
substring containment, so abbreviated renderings largely never entered the file as positives. The
matcher resolved all five correctly.

So the gold sample **under-represents exactly the hardest naming cases**, which means precision
measured against it is if anything flattering on that axis. Stated here rather than buried: it is
a real limitation of the measurement, and it points the same way as the correction in Finding 2.

Also: the gold set is **n=128 (+1 correction), not the 150 the spec targeted**. The only way to
reach 150 was padding with easy "different teams" negatives, which would have made the precision
gate *easier* to pass. Declined.

## Finding 4 — the three discriminations all fired on live data

The canonical key's non-obvious components each earned their place in this slate:

- **period / market_type.** 27 PM events were rejected as derivatives (`-first-five-winner`,
  `-player-props`, `-nrfi`, spreads, totals). They share the parent's teams *and* its
  `gameStartTime`. Participants-plus-time is not sufficient; 15 sit in the gold file as hard
  negatives.
- **start time, not date.** The STL/CIN doubleheader on 08-17 has two Kalshi events and two PM
  events on one date, separated only by the clock. Both paired correctly.
- **the slug lies.** That doubleheader's G1 pairs to PM slug **`mlb-stl-cin-2026-05-24`** — the May
  makeup game, slug date three months stale — while G2 pairs to `mlb-stl-cin-2026-08-17`. Anything
  keyed on the slug date gets G1 wrong by three months, and would drop precisely the postponed
  games, which are the highest-settlement-wedge subset.

---

## Numbers

| | |
|---|---|
| Scheduled MLB games in window | 99 |
| Kalshi events / markets | 41 / 82 |
| PM events seen / full-game moneyline kept | 112 / 27 rejected as derivative, 5 no schedule match |
| Eligible games (both venues list) | 41 |
| Completely paired (both sides) | **41** |
| Outcome pairs emitted | **82** |
| False positives | **0** |

`near_miss.csv` carries a named reason for every non-match. No silent drops.

## Not done here

No prices. No orderbooks. No depth. No fee arithmetic. Moneyline only — spreads and totals need
the line to match exactly and are deliberately deferred. One league, one 8-day window, one
snapshot. The listing-horizon finding is from a single snapshot's hours-to-start distribution, not
the 7-day repeated sampling the spec described as the fuller method; the step function is clean
enough to act on and should still be confirmed forward.

**0 test looks spent. No holdout touched. Nothing armed.**

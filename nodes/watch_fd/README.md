# watch_fd

**Kind:** `collector` (network in `fetch_matches`; state in `record`; `rates` reads)
**Implements:** `snapshot.py`

A daily snapshot of football-data.org's fixture lists, keeping each match's FIRST-SEEN kickoff and
status beside the live ones. It is the forward source for `soccer.<code>.postponed_gt48h_rate` and
`soccer.<code>.cancelled_rate` (ledger F6) and, once it has a season behind it, a truer source than
the L33/L35 round-window proxy for the leagues already enabled.

## Position in the grid

```
football-data.org /v4/competitions/{PL,ELC,PD,BL1,SA,FL1,DED,PPL}/matches ──▶ [fetch_matches]
        ──▶ [record] fd_matches (first-seen kickoff immutable) ──▶ [rates] ──▶ research/ (F6) ──▶ settle_wedge/evidence
```

**Upstream:** the venue's API and the operator's `FD_TOKEN` (credentials env, sourced by `ops/run_node.sh`).
**Downstream:** `research/sports/2026-09-05_soccer-postponement-forward/measure.py` (the daily job,
`com.janus.watch-fd`), then `nodes/settle_wedge/evidence.py` when the row registers a value.

## Contract

- The token is never in a URL, never logged, never committed. Without it `fetch_matches` raises and
  the job exits non-zero: nothing is guessed.
- `utc_date_first` and `status_first` are written once. football-data.org rewrites `utcDate` in
  place when a match moves; reading the live value would measure every postponement as zero.
- Rates use a TERMINAL denominator (FINISHED, AWARDED, CANCELLED). An open match may yet move.
- Coverage is the free tier's eight competitions. MLS, the Scottish Premiership, the Belgian Pro
  League and League One are not on it and stay blocked by name until another source exists.

## Failure modes

- 403 from the API: the token is wrong or the tier does not include the competition; the run FAILS
  and the watchdog reports it (once the job is registered in `SLAS`).
- A match id that changes across seasons: the primary key is (competition, match_id) so a new id is
  a new row; the season column says which.

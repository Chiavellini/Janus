# L58 — UCL league-phase settlement reserve registered

All 144 original 2024/25 UEFA Champions League league-phase fixtures joined uniquely to
official UEFA Full Time Reports. There were zero cancellations, zero changed match dates,
zero ESPN suspension flags and zero reports outside either conservative completion deadline.
Both separate exact one-sided 95% Clopper-Pearson upper bounds are **0.020588792299495857**.
Neither zero-event observation becomes zero risk. At a $0.50 Polymarket fill, the two dimensions
together reserve **2.05887923 cents**; this is no claim of positive executable EV or realized profit.

The original population is the [UEFA calendar published August 31, 2024](https://editorial.uefa.com/resources/0290-1bbe0f238404-c5dbaf60ad4d-1000/uefa_champions_league_2024-25_league_phase_draw_results_calendar_by_pot.pdf).
Its HTTP Last-Modified is August 31, its PDF title contains the August 31 generation timestamp,
and the [official August 29 draw announcement](https://www.uefa.com/uefachampionsleague/news/028e-1b1125f199a1-ace85e395aa8-1000/)
announces the August 31 calendar and 18:45/21:00 CET kickoff slots. This is pre-event publication
provenance, not a historical-results schedule substituted for an original. Every fixture occurs
twice with matching home/away/date/time from both clubs' panels; the 36 clubs have eight matches
each. SHA256: `088885318834ac759175a4f3cbb762a35e6c61345a6ffe7938f7a0db56037ebf`.

Each final report carries explicit full-time status, both club names, a league-phase matchday
from 1 through 8, the played date and a report-generation timestamp. Names join exactly after
Unicode/punctuation/whitespace normalization; a reviewed 36-club mapping joins the independent
ESPN fixture IDs. The report time bounds completion **from above**: a full-time report already
exists by then. It is not presented as the exact final whistle. The official
[Bayern–Benfica report](https://www.uefa.com/newsfiles/UCL/2025/2041980_FR.pdf), for example,
records the November 6 fixture and was generated November 7 at 00:51:07 CET. Original calendars
and a representative report were visually inspected in addition to full text parsing.

UEFA uses the CET label across summer and winter. To preserve conservative bounds without
assuming its summer offset, originals use UTC+2, the earlier candidate kickoff; final reports
use UTC+1, the later candidate publication. All resulting intervals are 3.6697–6.98 hours.
Delay is adverse at more than 48 elapsed hours **or** on reaching the second Eastern calendar
date after the original, whichever is earlier. A suspension flag also counts adverse.
Any changed date, delay or suspension requires separate source adjudication before registration;
none occurred in this population. No late-publication timestamp was silently replaced by kickoff.

The full hash-bound audit, all 144 normalized fixture/report rows, and every source URL,
retrieval timestamp, byte count and SHA256 are frozen at:

`/Volumes/Kilos/janus/research/ucl-settlement-bounds/audit-9d711e9ef9d93ae65315e53677c558e2fb612bc42158837371375ea9cd3a3367.json`

Its SHA256 is the filename suffix. All 294 source responses (154,512,824 bytes) are on the data
volume, including both original calendar layouts, the official publication/results pages,
the independent ESPN scoreboard, 144 ESPN summaries, and 144 UEFA reports. Re-running the
offline audit reproduced the same complete JSON and SHA256 byte-for-byte. Collection refuses
to replace an existing source; replay verifies source hashes. No data was placed on the root disk.

The ESPN summaries are retained as an explicit rejected source. They contain bulk-update
`keyEvents.wallclock` values; event 720437 (Leverkusen–Milan, October 1) gives kickoff at
November 8 09:22:20Z and full time two seconds later. They cannot establish completion.
ESPN contributes fixture identity, final status, league-phase classification and suspension flags
only. An initial `site.api.espn.com` request returned 403; the repository's working public
`site.web.api.espn.com` host supplied the frozen responses. No authenticated venue/account read occurred.

Commands run from the isolated UCL worktree:

```sh
python3 research/sports/2026-09-09_ucl-settlement-bounds/collect.py
python3 research/sports/2026-09-09_ucl-settlement-bounds/collect.py --summaries
python3 research/sports/2026-09-09_ucl-settlement-bounds/collect.py --uefa-reports
python3 research/sports/2026-09-09_ucl-settlement-bounds/measure.py --archive
python3 -m pytest nodes/settle_wedge/tests -q
git diff --check -- nodes/settle_wedge research/sports/2026-09-09_ucl-settlement-bounds
```

The offline archive command was run twice and reproduced the same digest. The settlement suite
passes all 148 tests, including 26 UCL-focused cases. Before registry publication, successful
certification tests correctly failed with `EVIDENCE_UNMEASURED`. A new exact-ID recertification
test also exposed the pre-existing MLS/Ere-only check in `pair.py`; it now includes UCL. Missing
rates, cross-league substitutions, unknown/foreign phases, malformed source/game IDs, and
nonterminal or ambiguous reports fail closed. The preregistered spec remains unchanged with
SHA256 `9aba153d51455b4dd6008598f180d1b5ba51b2c5b936b3334b7e80b798e632e0`.

Certification is limited to `source=espn`, `league=ucl`, `season_slug=league-phase`, and an exact
`espn:ucl:<digits>` ID matching the slate. Proof records retain population and game ID. Old
group-stage, qualifying, knockout, extra-time and missing classifications remain unmeasured.
The 2023/24 fallback was unnecessary and no old-format transfer was made.

Limitations: one completed season is a small historical population; the separate marginal
95% intervals are not a joint 95% guarantee. Binomial exchangeability does not protect against
correlated cancellations or new geopolitical/weather regimes. Publication provenance trusts
UEFA's official metadata, not an external timestamp authority. Report-generation upper bounds
may overcount late completions if a report is published late; they cannot undercount a completion
that had already happened. These bounds price residual settlement risk and do not establish
liquidity, execution quality, fees, profit, or a permissible larger capital allocation. No commit,
deployment, live-box access, account/order action, restart, kill change or cap change occurred.

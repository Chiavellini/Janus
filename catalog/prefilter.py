#!/usr/bin/env python3
"""Stream a full catalog crawl down to the working scope, without loading it into RAM.

    python3 catalog/prefilter.py --catalog data/catalog_2026-08-20 \
                                 --out-dir data/catalog_2026-08-20_nonsports

WHY STREAMING. The 2026-08-20 crawl is 166 MB (Kalshi, 95,852 markets) + 438 MB (Polymarket,
179,863 markets). `json.loads` on the PM file expands to several GB of Python objects; this host has
8 GB of RAM with swap already at 9.8/11 GB, and AGENTS.md records that background memory pressure has
already killed two collectors. So the array is decoded one object at a time and only survivors are
kept. Output uses the SAME filenames as the crawl, so `match/block.py` and `match/verify.py` consume
it with nothing but a different `--catalog`.

SCOPE (operator decision 2026-08-20): non-sports first. Sports is 52,612 of the 95,852 Kalshi markets
and already has a working canonical-key matcher in `match/sports_match.py`, gated at precision >= 0.98
against `match/gold/mlb_moneyline.csv`. Non-sports has no matcher at all, which is where the missing
`verify.py` stage bites.

MENTIONS ARE EXCLUDED BY DEFAULT. state.yaml:173 parks mention markets pending a read of the CFTC
probe record (NPR 2026-08-13), by operator decision 2026-08-14: "Do not commit build effort before
that read." Mentions fall inside the non-sports scope, so the gate is enforced HERE rather than left
to a convention someone forgets. `--include-mentions` lifts it explicitly and the count is always
reported, so an excluded category can never be mistaken for an empty one.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

#: Kalshi `category` values that are out of scope for this pass.
KALSHI_SPORTS = {"Sports"}

#: A Polymarket event is sports if any tag matches. Tags are far messier than Kalshi's categories --
#: the 2026-08-20 crawl carries `soccer-el1`, `dfb-pokal`, `japan-j-league`, `saudi-professional-league`
#: and dozens more, so this matches on SUBSTRINGS of a vocabulary rather than an exact tag list.
PM_SPORTS_VOCAB = (
    "sport", "soccer", "football", "basketball", "baseball", "hockey", "tennis", "golf",
    "mlb", "nba", "nfl", "nhl", "ncaa", "mls", "ufc", "boxing", "cricket", "rugby", "f1",
    "formula", "olympic", "league", "cup", "liga", "serie-a", "bundesliga", "premier",
    "pokal", "epl", "wnba", "cfb", "games", "esports", "racing", "motogp", "nascar",
)

MENTION_HINTS = ("mention", "will-say", "say-")


def stream_array(path: Path, bufsize: int = 1 << 20):
    """Yield objects from a top-level JSON array one at a time.

    `json.JSONDecoder.raw_decode` parses a single value off the front of a buffer and reports where it
    stopped, so the file can be walked with a bounded window instead of a whole-file parse.
    """
    dec = json.JSONDecoder()
    with path.open() as fh:
        buf = fh.read(bufsize)
        start = buf.find("[")
        if start < 0:
            return
        buf = buf[start + 1:]
        while True:
            buf = buf.lstrip()
            while buf[:1] == ",":
                buf = buf[1:].lstrip()
            if buf[:1] == "]":
                return
            if not buf:
                chunk = fh.read(bufsize)
                if not chunk:
                    return
                buf = chunk
                continue
            try:
                obj, end = dec.raw_decode(buf)
            except ValueError:
                chunk = fh.read(bufsize)
                if not chunk:
                    return
                buf += chunk
                continue
            yield obj
            buf = buf[end:]


def is_kalshi_sports(row: dict) -> bool:
    return (row.get("category") or "") in KALSHI_SPORTS


def is_pm_sports(row: dict) -> bool:
    for t in row.get("tags") or []:
        tl = str(t).lower()
        if any(v in tl for v in PM_SPORTS_VOCAB):
            return True
    return False


def is_kalshi_mention(row: dict) -> bool:
    if (row.get("category") or "") == "Mentions":
        return True
    return "MENTION" in (row.get("series") or "").upper()


def is_pm_mention(row: dict) -> bool:
    hay = " ".join(str(x).lower() for x in (row.get("event_slug"), row.get("slug")) if x)
    return any(h in hay for h in MENTION_HINTS)


def keep(row: dict, *, horizon: float, sports_fn, mention_fn, include_mentions: bool, stats: Counter):
    stats["seen"] += 1
    d = row.get("days_to_close")
    if d is None or not (0 <= d <= horizon):
        stats["drop_horizon"] += 1
        return False
    if not row.get("two_sided"):
        stats["drop_not_two_sided"] += 1
        return False
    if sports_fn(row):
        stats["drop_sports"] += 1
        return False
    if mention_fn(row):
        stats["mentions_seen"] += 1
        if not include_mentions:
            stats["drop_mentions_gated"] += 1
            return False
    stats["kept"] += 1
    return True


def run(src: Path, dst: Path, name: str, *, horizon, sports_fn, mention_fn, include_mentions):
    stats = Counter()
    kept = [r for r in stream_array(src)
            if keep(r, horizon=horizon, sports_fn=sports_fn, mention_fn=mention_fn,
                    include_mentions=include_mentions, stats=stats)]
    dst.write_text(json.dumps(kept))
    print(f"\n{name}: {stats['seen']} seen -> {stats['kept']} kept  ({dst.stat().st_size/1e6:.1f} MB)")
    for k in ("drop_horizon", "drop_not_two_sided", "drop_sports", "mentions_seen",
              "drop_mentions_gated"):
        if stats[k]:
            print(f"    {stats[k]:7d}  {k}")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog_2026-08-20")
    ap.add_argument("--out-dir", default="data/catalog_2026-08-20_nonsports")
    ap.add_argument("--horizon-days", type=float, default=30.0)
    ap.add_argument("--include-mentions", action="store_true",
                    help="lift the state.yaml:173 CFTC gate on mention markets (operator decision)")
    a = ap.parse_args()
    cat, out = Path(a.catalog), Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if a.include_mentions:
        print("!! mention markets INCLUDED -- state.yaml:173 CFTC gate lifted by --include-mentions")
    else:
        print("mention markets EXCLUDED (state.yaml:173 CFTC gate; pass --include-mentions to lift)")

    run(cat / "kalshi_markets.json", out / "kalshi_markets.json", "kalshi",
        horizon=a.horizon_days, sports_fn=is_kalshi_sports, mention_fn=is_kalshi_mention,
        include_mentions=a.include_mentions)
    run(cat / "pm_markets.json", out / "pm_markets.json", "polymarket",
        horizon=a.horizon_days, sports_fn=is_pm_sports, mention_fn=is_pm_mention,
        include_mentions=a.include_mentions)
    print(f"\nwrote {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

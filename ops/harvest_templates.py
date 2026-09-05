#!/usr/bin/env python3
"""Step 3 of the unblock workflow (nodes/settle_wedge/README.md) as a tool: for a league both venues
list, discover its co-listed games, harvest both venues' rules texts exactly as the lane does, and
say which templates they hash to -- or print the first UNKNOWN text verbatim, ready to be read and
recorded as a `Template` in nodes/settle_wedge/policy.py.

    python3 ops/harvest_templates.py --league nba
    python3 ops/harvest_templates.py --league nhl --pre-hours 168     # a week ahead: preseason listings

Read-only against the venues (the same Gamma / Kalshi endpoints discovery uses); writes nothing.
Built 2026-09-05 so the day Kalshi and Polymarket list NBA, WNBA or NHL games, the texts can be
reviewed the same hour instead of the league sitting at TEMPLATE_UNKNOWN for an evening (which
is what happened to soccer on 2026-09-04 when Polymarket reworded its description).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.fetch import Client  # noqa: E402
from nodes.discovery.discovery import co_listed, discover  # noqa: E402
from nodes.entities.leagues import LEAGUES, enablement  # noqa: E402
from nodes.settle_wedge.pair import records_from_spec  # noqa: E402
from nodes.settle_wedge.policy import template_for  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--league", required=True, help="a code in nodes/entities/leagues.py")
    ap.add_argument("--pre-hours", type=float, default=48.0, help="how far ahead to look for listed games")
    ap.add_argument("--full", action="store_true", help="print every text, not just the first unknown per venue")
    a = ap.parse_args()
    if a.league not in LEAGUES:
        print(f"{a.league}: not registered (step 1 first)"); return 2
    print(f"{a.league}: enablement now = {enablement(a.league) or 'ENABLED'}")
    now = datetime.now(timezone.utc)
    d = discover([a.league], now, True, a.pre_hours, Client("harvest-pm", rate=4, burst=8, cache_dir=None),
                 Client("harvest-k", rate=4, burst=8, cache_dir=None))
    slate, blocked = co_listed(d, first_seen={}, now=now.timestamp())
    print(f"{len(d.games)} games from the schedule; {len(slate)} co-listed; blocked: {dict(list(blocked.items())[:5])}")
    shown: set[tuple[str, str]] = set()
    for gid, spec in slate.items():
        recs = records_from_spec(spec, a.league)
        if recs is None:
            print(f"  {spec['short_name']}: no rules text harvested"); continue
        for rec in recs:
            t = template_for(rec.template_hash)
            tag = f"{t.template_id} (reviewed {t.reviewed_on})" if t else "UNKNOWN"
            print(f"  {spec['short_name']:<22} {rec.venue:<10} template {rec.template_hash} -> {tag}")
            if (t is None or a.full) and (rec.venue, rec.template_hash) not in shown:
                shown.add((rec.venue, rec.template_hash))
                print(f"    --- {rec.venue} text ({rec.market_id}) ---")
                print("    " + rec.text.replace("\n", "\n    "))
                print(f"    --- normalised template ({rec.template_hash}) ---")
                print("    " + rec.template_text.replace("\n", "\n    "))
    if not slate:
        print("nothing co-listed yet: the venues do not both list this league today. Re-run when they do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

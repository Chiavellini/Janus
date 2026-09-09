#!/usr/bin/env python3
"""L42: immutable original schedule versus Gamma's authoritative terminal timestamp.

Never reads a book, entry price or P&L. Raw pages and row-level output live on the Janus volume.
An offset cap, duplicated event, absent terminal field, or insufficient parseability is a FAIL,
not permission to use endDate or an ATP/WTA rate. A short page is followed until an EMPTY page.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402
from nodes.watch_settle.settle import upper_bound_95  # noqa: E402

HERE = Path(__file__).resolve().parent
GAMMA = "https://gamma-api.polymarket.com/events"
DELAY_SECONDS = 14 * 86400
START = re.compile(
    r"originally scheduled for ([A-Za-z]+ \d{1,2}, \d{4}) at "
    r"(\d{1,2}:\d{2})\s*(AM|PM)\s+ET\b", re.I)


def sequence(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("not a list")
    return value


def timestamp(value):
    if not value:
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.timestamp()


def original_start(description):
    matches = START.findall(description or "")
    if len(matches) != 1:
        raise ValueError("original schedule is missing or ambiguous")
    date, clock, ampm = matches[0]
    local = datetime.strptime(f"{date} {clock}{ampm.upper()}", "%B %d, %Y %I:%M%p")
    ny = ZoneInfo("America/New_York")
    # An explicit ET date can still be ambiguous or nonexistent at the DST transition.
    a, b = local.replace(tzinfo=ny, fold=0), local.replace(tzinfo=ny, fold=1)
    if a.utcoffset() != b.utcoffset():
        raise ValueError("ambiguous or nonexistent ET clock")
    return a.timestamp()


def terminal_result(market):
    prices = [float(x) for x in sequence(market.get("outcomePrices"))]
    if len(prices) != 2:
        raise ValueError("not two prices")
    if all(abs(p - 0.5) < 1e-9 for p in prices):
        return "HALF"
    if sum(p >= 0.999 for p in prices) == 1 and sum(p <= 0.001 for p in prices) == 1:
        return "WINNER"
    raise ValueError("nonterminal outcome prices")


def classify(event, *, allow_qualifying=False):
    """One auditable disposition per ITF event; only structural exclusions leave the denominator."""
    row = {"id": str(event.get("id", "")), "slug": event.get("slug"), "status": "EXCLUDED"}
    markets = [m for m in event.get("markets", []) if m.get("sportsMarketType") == "moneyline"]
    row["non_moneyline_markets"] = len(event.get("markets", [])) - len(markets)
    if len(markets) != 1:
        row["reason"] = "NO_MONEYLINE" if not markets else "AMBIGUOUS_MONEYLINE"
        row["structural"] = not markets
        return row
    market = markets[0]
    desc = market.get("description") or ""
    row["market_id"] = str(market.get("id", ""))
    try:
        outcomes = sequence(market.get("outcomes"))
    except (ValueError, TypeError):
        row["reason"] = "OUTCOMES_UNPARSEABLE"
        return row
    if len(outcomes) != 2:
        row.update(reason="NOT_TWO_OUTCOMES", structural=True)
        return row
    structure = " ".join([event.get("title") or "", desc, *map(str, outcomes)])
    if re.search(r"\bdoubles\b", structure, re.I) or any("/" in str(o) for o in outcomes):
        row.update(reason="DOUBLES", structural=True)
        return row
    if re.search(r"\bqualifying\b", structure, re.I) and not allow_qualifying:
        row.update(reason="QUALIFYING", structural=True)
        return row
    row["structural"] = False
    try:
        start = original_start(desc)
    except ValueError:
        row["reason"] = "ORIGINAL_START_UNPARSEABLE"
        return row
    row["original_start_utc"] = datetime.fromtimestamp(start, timezone.utc).isoformat()
    # The registered event field takes precedence. An invalid present field is not treated as absent.
    close_value = event.get("closedTime") or market.get("closedTime")
    row["close_source"] = "event.closedTime" if event.get("closedTime") else "market.closedTime"
    try:
        close = timestamp(close_value)
    except (TypeError, ValueError):
        row["reason"] = "AUTHORITATIVE_CLOSE_UNPARSEABLE"
        return row
    row["closed_utc"] = datetime.fromtimestamp(close, timezone.utc).isoformat()
    try:
        result = terminal_result(market)
    except (TypeError, ValueError):
        row["reason"] = "TERMINAL_RESULT_UNPARSEABLE"
        return row
    if not event.get("closed") or not market.get("closed"):
        row["reason"] = "NOT_CLOSED"
        return row
    try:
        row["game_start_difference_seconds"] = timestamp(market.get("gameStartTime")) - start
    except (TypeError, ValueError):
        row["game_start_difference_seconds"] = None
    row.update(status="INCLUDED", result=result, elapsed_seconds=close - start,
               delayed_gt14d=result == "WINNER" and close - start > DELAY_SECONDS,
               half_gt14d=result == "HALF" and close - start > DELAY_SECONDS)
    return row


def enumerate_events(client, archive, *, limit=200):
    """Exhaustive offset pagination ordered by ascending id, stopping only at an empty page."""
    seen = set()
    pages = []
    offset = 0
    while True:
        params = {"tag_slug": "tennis", "closed": "true", "limit": limit,
                  "offset": offset, "order": "id", "ascending": "true"}
        page = client.get_json(GAMMA, params=params, use_cache=False)
        if not isinstance(page, list):
            raise ValueError("Gamma returned a non-list page")
        payload = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()
        path = archive / f"page_{offset:08d}.json.gz"
        with gzip.open(path, "xb") as fh:
            fh.write(payload)
        page_info = {"offset": offset, "rows": len(page), "sha256": hashlib.sha256(payload).hexdigest(),
                     "path": str(path), "params": params}
        pages.append(page_info)
        print(json.dumps({"offset": offset, "rows": len(page), "unique_before_page": len(seen)}), flush=True)
        if not page:
            return pages
        for event in page:
            event_id = str(event.get("id", ""))
            if not event_id or event_id in seen:
                raise ValueError(f"MISSING_OR_DUPLICATED_ID:{event_id}")
            seen.add(event_id)
            yield event
        offset += len(page)


def summarize(rows, *, complete, error=None):
    structural = [r for r in rows if r.get("structural")]
    candidates = [r for r in rows if not r.get("structural")]
    included = [r for r in candidates if r["status"] == "INCLUDED"]
    excluded = [r for r in candidates if r["status"] != "INCLUDED"]
    n = len(included)
    late = sum(r["delayed_gt14d"] for r in included)
    half = sum(r["result"] == "HALF" for r in included)
    parseability = n / len(candidates) if candidates else 0.0
    failures = []
    if not complete:
        failures.append("ENUMERATION_INCOMPLETE")
    if not n:
        failures.append("NO_TERMINAL_ITF_SINGLES")
    if parseability < 0.95:
        failures.append("PARSEABILITY_BELOW_95_PERCENT")
    # The source must expose an authoritative terminal timestamp. Individual missing values also
    # count against parseability; total absence specifically triggers the pre-registered fail.
    if candidates and all(r.get("reason") == "AUTHORITATIVE_CLOSE_UNPARSEABLE" for r in candidates):
        failures.append("AUTHORITATIVE_CLOSE_UNAVAILABLE")
    value = (late / n if n >= 300 else upper_bound_95(late, n)) if n else None
    return {"complete": complete, "error": error, "itf_events": len(rows), "candidate_singles": len(candidates),
            "n": n, "parseability": parseability, "delayed_gt14d": late, "half": half,
            "half_gt14d": sum(r["half_gt14d"] for r in included),
            "closed_before_original_start": sum(r["elapsed_seconds"] < 0 for r in included),
            "start_crosscheck_missing": sum(r["game_start_difference_seconds"] is None for r in included),
            "start_crosscheck_changed": sum(r["game_start_difference_seconds"] not in (None, 0) for r in included),
            "structural_exclusions": dict(Counter(r["reason"] for r in structural)),
            "parse_exclusions": dict(Counter(r["reason"] for r in excluded)),
            "non_moneyline_markets": sum(r["non_moneyline_markets"] for r in rows),
            "upper_bound_95": upper_bound_95(late, n), "registered_value": value if not failures else None,
            "estimator": "point_estimate" if n >= 300 else "one_sided_95_upper_bound",
            "gates": "PASS" if not failures else "FAIL", "gate_failures": failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=ROOT / "data/research/L42_itf_delay")
    args = parser.parse_args()
    if (HERE / "results.json").exists():
        raise SystemExit("Immutable results.json already exists; do not overwrite the registered run")
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = args.archive.resolve() / run
    archive.mkdir(parents=True, exist_ok=False)
    rows, events, error, complete = [], 0, None, False
    client = Client("l42-itf-delay", rate=2.0, burst=2.0)
    try:
        for event in enumerate_events(client, archive):
            events += 1
            if str(event.get("slug", "")).startswith("itf-"):
                rows.append(classify(event))
        complete = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results = summarize(rows, complete=complete, error=error)
    results.update(run=run, tennis_events=events, archive=str(archive),
                   spec_sha256=hashlib.sha256((HERE / "spec.yaml").read_bytes()).hexdigest(),
                   source=GAMMA, http_stats=client.stats)
    with (archive / "rows.json").open("x") as fh:
        json.dump(rows, fh, indent=2, sort_keys=True)
    with (HERE / "results.json").open("x") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["gates"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

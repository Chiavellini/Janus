#!/usr/bin/env python3
"""L44: all mature ITF listings, including still-open and ambiguous terminal cases."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402
from nodes.watch_settle.settle import upper_bound_95  # noqa: E402

_spec = importlib.util.spec_from_file_location("l42_measure", HERE.parent / "2026-09-09_itf-settlement-delay/measure.py")
l42 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(l42)
GAMMA = "https://gamma-api.polymarket.com/events/keyset"
SNAPSHOT = l42.timestamp("2026-09-09T07:24:03Z")
MATURE_BEFORE = SNAPSHOT - 14 * 86400


def classify(event, *, source_closed, qualifying_population=False):
    row = l42.classify(event, allow_qualifying=qualifying_population)
    row.update(source_closed=source_closed, payload_closed=event.get("closed"),
               adverse=False, parseable=True, denominator=False)
    if qualifying_population and not row.get("structural"):
        text = " ".join([event.get("title") or "", *[
            market.get("description") or "" for market in event.get("markets", [])
            if market.get("sportsMarketType") == "moneyline"]])
        if not re.search(r"\bqualifying\b", text, re.I):
            row.update(status="EXCLUDED", structural=True, reason="NOT_QUALIFYING")
    if row.get("structural"):
        return row
    markets = [market for market in event.get("markets", []) if market.get("sportsMarketType") == "moneyline"]
    errors = []
    start = close = result = None
    if len(markets) != 1:
        errors.append("AMBIGUOUS_MONEYLINE")
    else:
        market = markets[0]
        row["market_payload_closed"] = market.get("closed")
        try:
            start = l42.original_start(market.get("description"))
            row["original_start_utc"] = datetime.fromtimestamp(start, timezone.utc).isoformat()
        except (TypeError, ValueError):
            errors.append("ORIGINAL_START_UNPARSEABLE")
        try:
            if len(l42.sequence(market.get("outcomes"))) != 2:
                raise ValueError("not two outcomes")
        except (TypeError, ValueError):
            errors.append("OUTCOMES_UNPARSEABLE")
        if event.get("closed") is True:
            # Only an absent event field permits fallback; a present null/empty value is invalid.
            row["close_source"] = "event.closedTime" if "closedTime" in event else "market.closedTime"
            value = event["closedTime"] if "closedTime" in event else market.get("closedTime")
            try:
                close = l42.timestamp(value)
                row["closed_utc"] = datetime.fromtimestamp(close, timezone.utc).isoformat()
            except (TypeError, ValueError):
                row.pop("closed_utc", None)
                errors.append("AUTHORITATIVE_CLOSE_UNPARSEABLE")
            try:
                result = l42.terminal_result(market)
            except (TypeError, ValueError):
                errors.append("TERMINAL_RESULT_UNPARSEABLE")
            if market.get("closed") is not True:
                errors.append("MONEYLINE_NOT_CLOSED")
        elif event.get("closed") is not False:
            errors.append("CLOSED_STATE_UNPARSEABLE")
    # Parseability covers ALL identified singles. Age excludes a row only from the rate, never
    # from the >=95% completeness gate or its reason-coded missing-field count.
    row.update(parseable=not errors, parse_errors=errors, authoritative_close_parseable=close is not None,
               denominator=start is None or start <= MATURE_BEFORE,
               catalog_state_mismatch=event.get("closed") is not source_closed)
    if errors:
        row.update(status="EXCLUDED", adverse=True, reason=errors[0])
    elif event.get("closed") is False:
        row.update(status="INCLUDED", adverse=True, reason="MATURE_STILL_OPEN")
    else:
        elapsed = close - start
        row.update(status="INCLUDED", result=result, elapsed_seconds=elapsed,
                   delayed_gt14d=result == "WINNER" and elapsed > 14 * 86400,
                   half_gt14d=result == "HALF" and elapsed > 14 * 86400)
        reason = ("HALF" if result == "HALF" else "WINNER_BEFORE_ORIGINAL_START" if elapsed < 0 else
                  "WINNER_AFTER_14D" if elapsed > 14 * 86400 else
                  "CATALOG_STATE_MISMATCH" if row["catalog_state_mismatch"] else "WINNER_WITHIN_14D")
        row.update(reason=reason, adverse=reason != "WINNER_WITHIN_14D")
    if not row["denominator"]:
        row.update(status="EXCLUDED", adverse=False, reason="IMMATURE_AT_SNAPSHOT")
    return row


def merge_transition(previous, current):
    """Preserve one event and the registered age/structural exclusions across catalog passes."""
    if previous.get("structural") and current.get("structural"):
        previous["catalog_state_transition"] = True
        return
    if previous.get("structural"):
        previous.update(current)
    denominator = previous["denominator"] or current["denominator"]
    previous.update(adverse=denominator, denominator=denominator, catalog_state_transition=True,
                    parseable=previous["parseable"] and current["parseable"],
                    parse_errors=sorted(set(previous.get("parse_errors", []) + current.get("parse_errors", []))),
                    payload_closed=previous.get("payload_closed") is True or current.get("payload_closed") is True,
                    authoritative_close_parseable=previous.get("authoritative_close_parseable", False)
                    or current.get("authoritative_close_parseable", False),
                    reason="CLOSED_OPEN_STATE_TRANSITION" if denominator else "IMMATURE_AT_SNAPSHOT")


def enumerate_events(client, archive, *, closed, limit=500):
    """Pass cursors verbatim, validate every id, preserve query/response/hash for every page."""
    seen_ids, seen_cursors = set(), set()
    cursor = None
    page_no = 0
    while True:
        params = {"tag_slug": "tennis", "closed": "true" if closed else "false",
                  "limit": limit, "order": "id", "ascending": "true"}
        if cursor:
            params["after_cursor"] = cursor
        page_path = archive / f"{'closed' if closed else 'open'}_{page_no:06d}.json.gz"
        cached = page_path.exists()
        if cached:
            with gzip.open(page_path, "rt") as fh:
                envelope = json.load(fh)
            if envelope.get("url") != GAMMA or envelope.get("params") != params:
                raise ValueError("ARCHIVE_REQUEST_MISMATCH")
            response = envelope["response"]
            raw = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
            if hashlib.sha256(raw).hexdigest() != envelope.get("sha256"):
                raise ValueError("ARCHIVE_HASH_MISMATCH")
        else:
            response = client.get_json(GAMMA, params=params, use_cache=False)
        if not isinstance(response, dict) or not isinstance(response.get("events"), list):
            raise ValueError("INVALID_KEYSET_RESPONSE")
        page = response["events"]
        raw = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
        envelope = {"url": GAMMA, "params": params, "sha256": hashlib.sha256(raw).hexdigest(),
                    "response": response}
        if not cached:
            with gzip.open(page_path, "xt") as fh:
                json.dump(envelope, fh, ensure_ascii=False, separators=(",", ":"))
            print(json.dumps({"closed": closed, "page": page_no, "rows": len(page),
                              "unique_before_page": len(seen_ids)}), flush=True)
        for event in page:
            raw_id = event.get("id")
            if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)) or not str(raw_id).strip():
                raise ValueError("MISSING_OR_DUPLICATED_ID:invalid")
            event_id = str(raw_id)
            if event_id in seen_ids:
                raise ValueError(f"MISSING_OR_DUPLICATED_ID:{event_id}")
            seen_ids.add(event_id)
            yield event
        next_cursor = response.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("INVALID_CURSOR_TYPE")
        if not page or not next_cursor:
            return
        if next_cursor in seen_cursors:
            raise ValueError("CURSOR_LOOP")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        page_no += 1


def summarize(rows, *, complete, error=None):
    structural = [r for r in rows if r.get("structural")]
    candidates = [r for r in rows if not r.get("structural")]
    mature = [r for r in candidates if r["denominator"]]
    parseability = sum(r["parseable"] for r in candidates) / len(candidates) if candidates else 0
    n, adverse = len(mature), sum(r["adverse"] for r in mature)
    failures = []
    if not complete:
        failures.append("ENUMERATION_INCOMPLETE")
    if not n:
        failures.append("NO_MATURE_ITF_SINGLES")
    if parseability < 0.95:
        failures.append("PARSEABILITY_BELOW_95_PERCENT")
    actual_closed = [r for r in candidates if r.get("payload_closed") is True]
    if not any(r.get("authoritative_close_parseable") for r in actual_closed):
        failures.append("AUTHORITATIVE_CLOSE_UNAVAILABLE")
    upper = upper_bound_95(adverse, n)
    return {"gates": "FAIL" if failures else "PASS", "gate_failures": failures, "complete": complete,
            "error": error, "itf_events": len(rows), "identified_singles": len(candidates),
            "mature_n": n, "adverse": adverse, "adverse_point_estimate": adverse / n if n else None,
            "upper_bound_95": upper, "registered_value": upper if not failures else None,
            "parseability": parseability, "estimator": "one_sided_95_upper_bound_at_all_n",
            "mature_reasons": dict(Counter(r["reason"] for r in mature)),
            "structural_exclusions": dict(Counter(r["reason"] for r in structural)),
            "immature": sum(r.get("reason") == "IMMATURE_AT_SNAPSHOT" for r in candidates),
            "unparseable": dict(Counter(reason for r in candidates for reason in r.get("parse_errors", []))),
            "unparseable_events": sum(not r["parseable"] for r in candidates),
            "actual_closed_candidates": len(actual_closed),
            "catalog_state_transitions": sum(bool(r.get("catalog_state_transition")) for r in rows),
            "catalog_state_mismatches": sum(bool(r.get("catalog_state_mismatch")) for r in rows),
            "snapshot_utc": datetime.fromtimestamp(SNAPSHOT, timezone.utc).isoformat(),
            "mature_before_utc": datetime.fromtimestamp(MATURE_BEFORE, timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=ROOT / "data/research/L44_itf_delay")
    parser.add_argument("--resume", type=Path,
                        help="replay verified archived pages and continue their exact last cursor; no raw overwrite")
    args = parser.parse_args()
    if (HERE / "results.json").exists():
        raise SystemExit("Immutable results already exist; do not overwrite the registered run")
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = args.resume.resolve() if args.resume else args.archive.resolve() / run
    if args.resume:
        if not archive.is_dir():
            raise SystemExit("Resume archive does not exist")
    else:
        archive.mkdir(parents=True, exist_ok=False)
    rows, counts = {}, {"closed": 0, "open": 0}
    complete, error = False, None
    client = Client("l44-itf-delay", rate=2, burst=2)
    try:
        for closed in (True, False):
            for event in enumerate_events(client, archive, closed=closed):
                counts["closed" if closed else "open"] += 1
                if not str(event.get("slug", "")).startswith("itf-"):
                    continue
                event_id = str(event["id"])
                row = classify(event, source_closed=closed)
                if event_id in rows:
                    merge_transition(rows[event_id], row)
                else:
                    rows[event_id] = row
        complete = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results = summarize(list(rows.values()), complete=complete, error=error)
    results.update(run=run, tennis_events=counts, archive=str(archive), source=GAMMA,
                   resumed_from_archive=bool(args.resume),
                   spec_sha256=hashlib.sha256((HERE / "spec.yaml").read_bytes()).hexdigest(),
                   http_stats=client.stats)
    with (archive / "rows.json").open("x") as fh:
        json.dump(list(rows.values()), fh, indent=2, sort_keys=True)
    with (HERE / "results.json").open("x") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["gates"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

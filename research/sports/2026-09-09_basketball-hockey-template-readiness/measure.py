#!/usr/bin/env python3
"""L48: current listing/rule inventory. Public GETs only; no books or outcome scoring."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client
from nodes.discovery.discovery import co_listed, discover
from nodes.entities.leagues import LEAGUES, enablement
from nodes.match_sports.stage1_checkpoint import KALSHI_BASE, PM_GAMMA
from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
from nodes.settle_wedge.pair import records_from_spec
from nodes.settle_wedge.policy import template_for

HERE = Path(__file__).resolve().parent
LEAGUE_CODES = ("nba", "wnba", "nhl")


def write_atomic(path, payload):
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_suffix(path.suffix + ".pending")
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return hashlib.sha256(raw).hexdigest()


def main():
    if (HERE / "results.json").exists():
        raise RuntimeError("Immutable results already exist")
    now = datetime.now(timezone.utc)
    archive = Path("/Volumes/Kilos/janus/research/L48") / now.strftime("%Y%m%dT%H%M%SZ")
    archive.mkdir(parents=True, exist_ok=False)
    manifest, errors = [], []
    original_get = Client.get_json

    def archived_get(client, url, *, params=None, use_cache=True, headers=None):
        if headers:
            raise RuntimeError("L48 uses unauthenticated public requests only")
        request = {"url": url, "params": params, "at": datetime.now(timezone.utc).isoformat()}
        try:
            response = original_get(client, url, params=params, use_cache=False)
        except Exception as exc:
            errors.append({**request, "error": f"{type(exc).__name__}: {exc}"})
            raise
        name = f"response_{len(manifest):04d}.json"
        digest = write_atomic(archive / name, {"request": request, "response": response})
        manifest.append({**request, "path": name, "sha256": digest})
        return response

    def kalshi_events(client, series):
        events = {}
        for status in ("open", "unopened"):
            cursor, seen = None, set()
            while True:
                params = dict(series_ticker=series, status=status, limit=200, with_nested_markets="true")
                if cursor:
                    params["cursor"] = cursor
                page = client.get_json(f"{KALSHI_BASE}/events", params=params)
                for event in page.get("events") or []:
                    events[event["event_ticker"]] = event
                cursor = page.get("cursor")
                if not cursor:
                    break
                if cursor in seen:
                    raise RuntimeError(f"Repeated Kalshi cursor for {series}/{status}")
                seen.add(cursor)
        return list(events.values())

    def gamma_events(client, tags):
        events = {}
        for key, tag in sorted(set(tags)):
            offset = 0
            while True:
                page = client.get_json(f"{PM_GAMMA}/events", params={key: tag, "closed": "false", "limit": 100, "offset": offset})
                if not isinstance(page, list):
                    raise RuntimeError("Gamma response is not an event list")
                for event in page:
                    events[str(event["id"])] = event
                if len(page) < 100:
                    break
                offset += 100
        return list(events.values())

    result = {"ledger_ref": "L48", "as_of": now.isoformat(), "archive": str(archive), "leagues": {}}
    with patch.object(Client, "get_json", archived_get):
        kclient, pclient = Client("L48-k"), Client("L48-p")
        sports = pclient.get_json(f"{PM_GAMMA}/sports")
        for code in LEAGUE_CODES:
            league = LEAGUES[code]
            entry = {"enablement": enablement(code), "templates": {}, "complete": False}
            result["leagues"][code] = entry
            try:
                tags = [("tag_slug", league.pm_tag)]
                for sport in sports:
                    if sport.get("sport") == code and sport.get("primaryTagId"):
                        tags.append(("tag_id", str(sport["primaryTagId"])))
                entry["gamma_tags"] = tags
                k_events = kalshi_events(kclient, league.kalshi_series)
                series = kclient.get_json(f"{KALSHI_BASE}/series/{league.kalshi_series}")
                p_events = gamma_events(pclient, tags)
                entry["kalshi_events"] = [{"id": e.get("event_ticker"), "title": e.get("title")} for e in k_events]
                entry["polymarket_event_count"] = len(p_events)
                entry["polymarket_moneylines"] = []

                def record(rec, participants):
                    approved = template_for(rec.template_hash)
                    group = entry["templates"].setdefault(rec.venue + ":" + rec.template_hash, {
                        "record": asdict(rec), "participants": participants,
                        "reviewed_template": approved.template_id if approved else None, "market_ids": []})
                    group["market_ids"].append(rec.market_id)

                for event in k_events:
                    participants = [m.get("yes_sub_title", "") for m in event.get("markets") or []]
                    for market in event.get("markets") or []:
                        record(harvest_kalshi(market, participants=participants, retrieved_at=now.timestamp(), series=series), participants)
                for event in p_events:
                    for market in event.get("markets") or []:
                        if market.get("sportsMarketType") != "moneyline" or not market.get("gameStartTime"):
                            continue
                        participants = [t.get("name", "") for t in event.get("teams") or []]
                        outcomes = market.get("outcomes") or []
                        if isinstance(outcomes, str):
                            outcomes = json.loads(outcomes)
                        participants += outcomes
                        entry["polymarket_moneylines"].append({"slug": market.get("slug"), "event_slug": event.get("slug"), "start": market.get("gameStartTime"), "participants": participants})
                        record(harvest_polymarket(market, participants=participants, retrieved_at=now.timestamp()), participants)
                discovery = discover([code], now, True, 168, pclient, kclient)
                slate, blocked = co_listed(discovery, first_seen={}, now=now.timestamp())
                entry["discovery"] = {
                    "schedule": [asdict(g) for g in discovery.games], "blocked": blocked,
                    "stats": {key: value[1] for key, value in discovery.per_league.items()},
                    "schedule_failures": discovery.schedule_failures, "co_listed": list(slate),
                    "pair_rules": {gid: [asdict(r) for r in records_from_spec(spec, code) or ()] for gid, spec in slate.items()},
                }
                entry["complete"] = True
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            print(code, "complete=", entry["complete"], "K=", len(entry.get("kalshi_events", [])), "PM moneylines=", len(entry.get("polymarket_moneylines", [])), "pairs=", len(entry.get("discovery", {}).get("co_listed", [])), flush=True)
    result["requests"] = len(manifest)
    result["errors"] = errors
    result["complete"] = not errors and all(v["complete"] for v in result["leagues"].values())
    result["manifest_sha256"] = write_atomic(archive / "manifest.json", manifest)
    write_atomic(HERE / "results.json", result)
    print("result:", HERE / "results.json", "complete:", result["complete"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

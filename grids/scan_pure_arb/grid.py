#!/usr/bin/env python3
"""Bounded, executable pure-arbitrage scan for one event family.

This is intentionally a family scanner, not a venue-wide snapshotter.  The caller names one
Kalshi series and one Polymarket search phrase; only the matching event and its matched outcome
books are fetched.  A binary cross-venue hedge buys YES on one venue and NO on the other, so the
payoff is $1 whichever venue settles first, subject to the semantic/settlement gate.

Example::

    python3 grids/scan_pure_arb/grid.py --kalshi-series KXGRAMAOTY --pm-query grammy --once

No order is submitted.  Results are research artifacts, not trading instructions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.fetch import Client  # noqa: E402
from nodes.fees.models import Fill  # noqa: E402
from nodes.fees.registry import model_for, params_for  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA = "https://gamma-api.polymarket.com"
PM_CLOB = "https://clob.polymarket.com"
SPEC_REF = "research/tuples/2026-09-01_culture-short-horizon/spec.yaml"
RESULTS = ROOT / "research/tuples/2026-09-01_culture-short-horizon/results.json"
VERDICT = ROOT / "research/tuples/2026-09-01_culture-short-horizon/verdict.md"
DB = Path("/Volumes/Kilos/janus/tuples/tuples.sqlite")
QUANTITIES = (5.0, 25.0, 100.0)


def ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def canon(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = value.lower().replace("’", "'")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def k_outcome(subtitle: str) -> str:
    return (subtitle or "").split("::", 1)[0].strip()


def pm_outcome(group_item_title: str) -> str:
    return (group_item_title or "").rsplit(" - ", 1)[0].strip()


def levels(raw: list[Any], *, pm: bool, reverse: bool = False) -> list[tuple[float, float]]:
    out = []
    for row in raw or []:
        try:
            if pm:
                price, size = float(row["price"]), float(row["size"])
            else:
                price, size = float(row[0]), float(row[1])
            if 0 <= price <= 1 and size > 0:
                out.append((price, size))
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    return sorted(out, key=lambda x: x[0], reverse=reverse)


def top(book: list[tuple[float, float]], *, ask: bool) -> float | None:
    if not book:
        return None
    return min(p for p, _ in book) if ask else max(p for p, _ in book)


def depth(book: list[tuple[float, float]]) -> float:
    return sum(size for _, size in book)


def walk(book: list[tuple[float, float]], quantity: float) -> tuple[float, list[tuple[float, float]]] | None:
    """Return total stake and fills for an ascending ask ladder."""
    remaining, cost, fills = quantity, 0.0, []
    for price, size in sorted(book):
        take = min(remaining, size)
        if take > 0:
            cost += take * price
            fills.append((price, take))
            remaining -= take
        if remaining <= 1e-9:
            return cost, fills
    return None


def fee(venue: str, market_id: str, outcome: str, fills: list[tuple[float, float]], params: dict[str, Any]) -> float:
    model = model_for(venue)
    return model.entry_cost([
        Fill(venue=venue, market_id=market_id, outcome_id=outcome, side="buy",
             price=price, contracts=size, liquidity="taker", order_seq=0)
        for price, size in fills
    ], params)


def k_books(payload: dict[str, Any]) -> dict[str, Any]:
    ob = payload.get("orderbook_fp") or payload.get("orderbook") or {}
    yes_bids = levels(ob.get("yes_dollars") or ob.get("yes"), pm=False, reverse=True)
    no_bids = levels(ob.get("no_dollars") or ob.get("no"), pm=False, reverse=True)
    # Kalshi exposes bids for both YES and NO.  Folding the complement is the only valid ask.
    yes_asks = sorted((1 - p, size) for p, size in no_bids)
    no_asks = sorted((1 - p, size) for p, size in yes_bids)
    return {"yes_bids": yes_bids, "yes_asks": yes_asks, "no_bids": no_bids,
            "no_asks": no_asks}


def pm_book(payload: dict[str, Any]) -> dict[str, Any]:
    bids = levels(payload.get("bids"), pm=True, reverse=True)
    asks = levels(payload.get("asks"), pm=True, reverse=False)
    return {"bids": bids, "asks": asks}


def compact_levels(book: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"side": side, "price": round(price, 6), "size": round(size, 6)}
            for side in ("yes_bids", "yes_asks", "no_bids", "no_asks", "bids", "asks")
            for price, size in book.get(side, [])[:10]]


def watch_tier(created: float | None, now: float) -> str:
    if created is None:
        return "unknown_age"
    age_h = max(0.0, now - created) / 3600
    if age_h <= 6:
        return "newborn"
    if age_h <= 24:
        return "recently_born"
    return "short_term"


def choose_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [e for e in events if not e.get("closed") and e.get("active") and
                  "album of the year" in (e.get("title", "") + " " + e.get("slug", "")).lower()]
    return sorted(candidates, key=lambda e: ts(e.get("startDate")) or 0, reverse=True)[0] if candidates else None


def scan(series_ticker: str, pm_query: str, *, db: Path = DB) -> dict[str, Any]:
    started = time.time()
    k = Client("kalshi", rate=4, burst=4, cache_dir=None)
    p = Client("polymarket", rate=4, burst=4, cache_dir=None)
    store = TupleStore(db)
    sweep_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = time.time()
    result: dict[str, Any] = {
        "spec_ref": SPEC_REF, "sweep_id": sweep_id, "started_utc": dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat(),
        "universe": {"kalshi_series": series_ticker, "polymarket_query": pm_query},
        "matches": [], "name_mismatches": [], "summary": {}, "api_stats": {},
    }
    try:
        series_payload = k.get_json(f"{KALSHI}/series/{series_ticker}", use_cache=False)
        series = series_payload.get("series", series_payload)
        km = k.get_json(f"{KALSHI}/markets", params={"series_ticker": series_ticker, "status": "open", "limit": 1000}, use_cache=False).get("markets", [])
        events = p.get_json(f"{PM_GAMMA}/public-search", params={"q": pm_query, "limit": 100}, use_cache=False).get("events", [])
        event = choose_event(events)
        if not event:
            raise RuntimeError("no active Polymarket Album of the Year event found")
        pm_markets = [m for m in event.get("markets", []) if m.get("active") and not m.get("closed")]
        pm_by_name = {canon(pm_outcome(m.get("groupItemTitle", ""))): m for m in pm_markets
                      if not pm_outcome(m.get("groupItemTitle", "")).lower().startswith("placeholder")}
        k_by_name = {canon(k_outcome(m.get("subtitle", ""))): m for m in km
                     if canon(k_outcome(m.get("subtitle", ""))) not in {"", "tie"}}
        for raw in km:
            kn = k_outcome(raw.get("subtitle", ""))
            if not kn or canon(kn) == "tie":
                continue
            key = canon(kn)
            pm = pm_by_name.get(key)
            if pm is None:
                # Keep a compact candidate record; this is useful for spotting naming drift, but
                # never turns a fuzzy name into an executable match.
                same_artist = [m for m in pm_markets if canon((raw.get("subtitle", "").split("::", 1)[-1])) and
                               canon((raw.get("subtitle", "").split("::", 1)[-1])) in canon(m.get("groupItemTitle", ""))]
                result["name_mismatches"].append({"kalshi_id": raw.get("ticker"), "kalshi_outcome": kn,
                    "polymarket_candidates": [m.get("groupItemTitle") for m in same_artist[:3]]})
                continue
            k_id = raw.get("ticker")
            k_payload = k.get_json(f"{KALSHI}/markets/{k_id}/orderbook", params={"depth": 10}, use_cache=False)
            kb = k_books(k_payload)
            toks = json.loads(pm.get("clobTokenIds", "[]"))
            if len(toks) < 2:
                continue
            pb_yes = pm_book(p.get_json(f"{PM_CLOB}/book", params={"token_id": toks[0]}, use_cache=False))
            pb_no = pm_book(p.get_json(f"{PM_CLOB}/book", params={"token_id": toks[1]}, use_cache=False))
            pm_books = {"yes": pb_yes, "no": pb_no}
            event_key = f"grammy:69:aoty:{canon(kn)}"
            settlement_ref = "Recording Academy / grammy.com"
            created_k, created_p = ts(raw.get("created_time")), ts(pm.get("createdAt"))
            created = min(x for x in (created_k, created_p) if x is not None) if (created_k or created_p) else None
            store.market(venue="kalshi", market_id=k_id, family="culture", event_key=event_key, outcome=kn,
                         category=series.get("category", "Entertainment"), created_ts=created_k,
                         close_ts=ts(raw.get("close_time")), status=raw.get("status", "active"),
                         settlement_ref=settlement_ref, watch_tier=watch_tier(created_k, now),
                         metadata={"series": series_ticker, "event_ticker": raw.get("event_ticker"), "rules": raw.get("rules_primary")}, seen_ts=now)
            store.market(venue="polymarket", market_id=str(pm.get("conditionId") or pm.get("id")), family="culture",
                         event_key=event_key, outcome=pm_outcome(pm.get("groupItemTitle", "")), category="Culture",
                         created_ts=created_p, close_ts=ts(pm.get("endDate")), status="active",
                         settlement_ref=settlement_ref, watch_tier=watch_tier(created_p, now),
                         metadata={"event_id": event.get("id"), "market_id": pm.get("id"), "question": pm.get("question")}, seen_ts=now)
            store.quote(venue="kalshi", market_id=k_id, best_bid=top(kb["yes_bids"], ask=False),
                        best_ask=top(kb["yes_asks"], ask=True), bid_depth=depth(kb["yes_bids"]),
                        ask_depth=depth(kb["yes_asks"]), n_bid_levels=len(kb["yes_bids"]),
                        n_ask_levels=len(kb["yes_asks"]), two_sided=bool(kb["yes_bids"] and kb["yes_asks"]),
                        levels=compact_levels(kb), seen_ts=now)
            store.quote(venue="polymarket", market_id=str(pm.get("conditionId") or pm.get("id")),
                        best_bid=top(pb_yes["bids"], ask=False), best_ask=top(pb_yes["asks"], ask=True),
                        bid_depth=depth(pb_yes["bids"]), ask_depth=depth(pb_yes["asks"]),
                        n_bid_levels=len(pb_yes["bids"]), n_ask_levels=len(pb_yes["asks"]),
                        two_sided=bool(pb_yes["bids"] and pb_yes["asks"]),
                        levels=compact_levels(pb_yes) + compact_levels(pb_no), seen_ts=now)

            # PM's description and Kalshi's series source must identify the same event before a
            # quote can be labelled actionable.  Exact outcome names are also required above.
            sem_ok = ("Recording Academy" in settlement_ref and "grammy.com" in
                      (pm.get("description", "") + " " + event.get("title", "")).lower() and
                      "album of the year" in (raw.get("rules_primary", "") + " " + pm.get("description", "")).lower())
            rows = []
            for direction, left_id, left_venue, left_outcome, left_book, right_id, right_venue, right_outcome, right_book in (
                ("K_YES_PM_NO", k_id, "kalshi", "YES", kb["yes_asks"], str(pm.get("conditionId") or pm.get("id")), "polymarket", "NO", pb_no["asks"]),
                ("PM_YES_K_NO", str(pm.get("conditionId") or pm.get("id")), "polymarket", "YES", pb_yes["asks"], k_id, "kalshi", "NO", kb["no_asks"]),
            ):
                qrows = []
                for q in QUANTITIES:
                    l = walk(left_book, q); r = walk(right_book, q)
                    if not l or not r:
                        qrows.append({"quantity": q, "status": "INSUFFICIENT_DEPTH"})
                        continue
                    gross = l[0] + r[0]
                    fees = fee(left_venue, left_id, left_outcome, l[1], params_for(left_venue, {
                        "fee_type": series.get("fee_type"), "fee_multiplier": series.get("fee_multiplier")
                    }) if left_venue == "kalshi" else {"fee_rate": pm.get("feeSchedule", {}).get("rate", 0.05)})
                    fees += fee(right_venue, right_id, right_outcome, r[1], params_for(right_venue, {
                        "fee_type": series.get("fee_type"), "fee_multiplier": series.get("fee_multiplier")
                    }) if right_venue == "kalshi" else {"fee_rate": pm.get("feeSchedule", {}).get("rate", 0.05)})
                    net = q - gross - fees
                    locked = gross + fees
                    qrows.append({"quantity": q, "gross_cost": round(gross, 8), "fees": round(fees, 8),
                                  "net_profit": round(net, 8), "return_locked": round(net / locked, 8) if locked else None,
                                  "status": "ACTIONABLE" if sem_ok and net > 0 and q >= 5 else ("BLOCKED_SEMANTIC" if not sem_ok else "NO_EDGE"),
                                  "legs": [{"venue": left_venue, "market_id": left_id, "outcome": left_outcome},
                                           {"venue": right_venue, "market_id": right_id, "outcome": right_outcome}]})
                best = max((x for x in qrows if x.get("status") == "ACTIONABLE"), key=lambda x: x["net_profit"], default=None)
                tuple_id = f"{event_key}:{direction}"
                status = best["status"] if best else ("BLOCKED_SEMANTIC" if not sem_ok else "NO_EDGE")
                chosen = best or next((x for x in reversed(qrows) if "status" in x), {"status": status})
                changed = store.opportunity(tuple_id=tuple_id, relation_type="cross_venue_same_event", status=status,
                    gross_cost=chosen.get("gross_cost"), fees=chosen.get("fees"), net_profit=chosen.get("net_profit"),
                    return_locked=chosen.get("return_locked"), capacity=chosen.get("quantity"),
                    details={"outcome": kn, "direction": direction, "quantities": qrows,
                             "semantic_gate": sem_ok, "kalshi_rules": raw.get("rules_primary"),
                             "polymarket_question": pm.get("question"), "polymarket_description": pm.get("description")}, seen_ts=now)
                rows.append({"direction": direction, "status": status, "best": best, "all_quantities": qrows,
                             "transition_recorded": changed})
            result["matches"].append({"outcome": kn, "kalshi_id": k_id, "polymarket_id": pm.get("id"),
                                      "polymarket_condition_id": pm.get("conditionId"), "rows": rows,
                                      "rules": {"kalshi": raw.get("rules_primary"), "polymarket": pm.get("description")},
                                      "created": {"kalshi": raw.get("created_time"), "polymarket": pm.get("createdAt")}})
        result["summary"] = {"kalshi_markets": len(km), "polymarket_event_markets": len(pm_markets),
            "exact_matches": len(result["matches"]), "name_mismatches": len(result["name_mismatches"]),
            "actionable_directions": sum(1 for m in result["matches"] for r in m["rows"] if r["status"] == "ACTIONABLE"),
            "event": {"id": event.get("id"), "title": event.get("title"), "startDate": event.get("startDate"), "endDate": event.get("endDate")}}
        result["status"] = "OK"
    except Exception as exc:  # store the failed sweep, then re-raise for a visible nonzero run
        result["status"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        result["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        result["api_stats"] = {"kalshi": k.stats, "polymarket": p.stats}
        store.sweep(sweep_id=sweep_id, started_ts=started, finished_ts=time.time(), universe=f"{series_ticker}:{pm_query}",
                    n_discovered=result.get("summary", {}).get("kalshi_markets", 0) + result.get("summary", {}).get("polymarket_event_markets", 0),
                    n_watched=len(result.get("matches", [])) * 2, n_changed=0,
                    n_opportunities=sum(1 for m in result.get("matches", []) for r in m.get("rows", []) if r.get("status") == "ACTIONABLE"),
                    status=result.get("status", "ERROR"), error=result.get("error"))
        store.commit(); store.close()
    return result


def write_artifacts(result: dict[str, Any]) -> None:
    RESULTS.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    s = result.get("summary", {})
    lines = ["# Pure-arbitrage tuple scan — Grammy fixture", "", f"Status: **{result.get('status')}**", "",
             f"The bounded scan found {s.get('exact_matches', 0)} exact outcome-name matches and "
             f"{s.get('name_mismatches', 0)} naming mismatches. It fetched executable order books only "
             "for those matches; no venue-wide snapshot was persisted.", ""]
    for m in result.get("matches", []):
        for r in m.get("rows", []):
            b = r.get("best") or {}
            lines.append(f"- `{m['outcome']}` `{r['direction']}`: **{r['status']}**, "
                         f"best tested net ${b.get('net_profit', 0):.4f} at q={b.get('quantity', '-')}")
    if result.get("name_mismatches"):
        lines += ["", "Name mismatches were retained as candidates but not treated as equivalent:"]
        lines += [f"- `{x['kalshi_outcome']}` → {x['polymarket_candidates']}" for x in result["name_mismatches"]]
    lines += ["", "This is a quote-level research result. It does not authorize an order; settlement identity, "
              "account-specific fees, live depth, and synchronized execution still require separate validation."]
    VERDICT.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kalshi-series", default="KXGRAMAOTY")
    ap.add_argument("--pm-query", default="grammy")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        assert canon("Beyoncé — Album") == "beyonce album"
        assert pm_outcome("The Life of a Showgirl - Taylor Swift") == "The Life of a Showgirl"
        assert k_outcome("Lux:: Rosalía") == "Lux"
        print("scan_pure_arb selftest OK")
        return
    result = scan(args.kalshi_series, args.pm_query, db=args.db)
    write_artifacts(result)
    print(json.dumps(result.get("summary", {}), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""L18 — Kalshi FOMC ladder settlement characterization. Spec: ./spec.yaml · Ledger L18.

    python3 research/exec/2026-08-19_fomc-ladder-settlement/measure.py [--self-test]

The spec states an EXPECTATION before running: this should fail its coverage gate, because L17
measured (M1) that Kalshi's settled history reaches back only ~68 days and the FOMC meets ~8x a
year. If many meetings turn out to be recoverable, that falsifies L17's retention finding and IS
the result. Either way the count is the deliverable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402
from lib.stats import json_ready, write_csv  # noqa: E402

HERE = Path(__file__).resolve().parent
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DATA_DIR = Path("/Volumes/Kilos/janus/fomc_settlement")
SERIES = ["KXFED", "KXFEDDECISION"]
MIN_MEETINGS = 5

#: KXFED-27APR-T4.25 -> 27APR ; KXFEDDECISION-28JAN-H26 -> 28JAN
MEETING_RE = re.compile(r"^(?:KXFED|KXFEDDECISION)-([0-9]{2}[A-Z]{3})\b")


def meeting_of(ticker: str | None) -> str | None:
    m = MEETING_RE.match(ticker or "")
    return m.group(1) if m else None


def f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def select_markets(markets: list[dict]) -> dict:
    included, rejected = [], []
    for m in markets:
        rec = {"ticker": m.get("ticker"), "series_ticker": m.get("series_ticker"),
               "event_ticker": m.get("event_ticker"), "close_time": m.get("close_time"),
               "expiration_value": f(m.get("expiration_value")), "result": m.get("result")}
        mt = meeting_of(m.get("ticker"))
        if mt is None:
            rejected.append(dict(rec, reason="UNPARSEABLE_MEETING")); continue
        included.append(dict(rec, meeting=mt))
    return {"included": included, "rejected": rejected}


def meetings_per_series(included: list[dict]) -> dict:
    acc = defaultdict(set)
    for r in included:
        s = r["series_ticker"] or (r["ticker"] or "").split("-")[0]
        acc[s].add(r["meeting"])
    return {s: sorted(v) for s, v in acc.items()}


def verdict(shared: list, per_series: dict) -> dict:
    n = len(shared)
    if n < MIN_MEETINGS:
        return {"verdict": "INSUFFICIENT_COVERAGE", "n_shared_meetings": n,
                "why": f"{n} settled meetings shared by both series < the pre-registered "
                       f"{MIN_MEETINGS}; no distribution quoted and NO external comparison attempted",
                "external_comparison": "NOT_REACHED"}
    return {"verdict": "COVERAGE_GATE_PASSED_SEE_RESULTS", "n_shared_meetings": n,
            "why": "the stated expectation was INSUFFICIENT_COVERAGE; it did not hold, which "
                   "falsifies L17's ~68-day retention finding and is itself the result"}


def fetch(client: Client) -> dict:
    by_ticker, counts, pages = {}, {}, 0
    for s in SERIES:
        n = 0
        try:
            for page in client.paginate_cursor(f"{KALSHI}/markets",
                                               {"series_ticker": s, "status": "settled",
                                                "limit": 1000}, "markets"):
                pages += 1
                for m in page:
                    by_ticker[m["ticker"]] = m; n += 1
            counts[f"markets:{s}"] = n
        except Exception as e:  # noqa: BLE001
            counts[f"markets:{s}"] = f"ERROR {e}"
    for s in SERIES:
        n = 0
        try:
            for page in client.paginate_cursor(f"{KALSHI}/events",
                                               {"series_ticker": s, "status": "settled",
                                                "with_nested_markets": "true", "limit": 200},
                                               "events"):
                pages += 1
                for ev in page:
                    for m in ev.get("markets") or []:
                        m.setdefault("event_ticker", ev.get("event_ticker"))
                        m.setdefault("series_ticker", ev.get("series_ticker") or s)
                        by_ticker.setdefault(m["ticker"], m); n += 1
            counts[f"events:{s}"] = n
        except Exception as e:  # noqa: BLE001
            counts[f"events:{s}"] = f"ERROR {e}"
    return {"markets": list(by_ticker.values()), "channel_counts": counts, "pages": pages}


def selftest() -> None:
    assert meeting_of("KXFED-27APR-T4.25") == "27APR"
    assert meeting_of("KXFEDDECISION-28JAN-H26") == "28JAN"
    assert meeting_of("KXINX-26AUG18H1600-T7691") is None
    assert meeting_of(None) is None
    sel = select_markets([{"ticker": "KXFED-26JUN-T4.25", "series_ticker": "KXFED",
                           "expiration_value": "4.25"}])
    assert sel["included"][0]["meeting"] == "26JUN"
    assert verdict([1, 2], {})["verdict"] == "INSUFFICIENT_COVERAGE"
    assert verdict([1, 2], {})["external_comparison"] == "NOT_REACHED"
    assert verdict(list(range(6)), {})["verdict"] == "COVERAGE_GATE_PASSED_SEE_RESULTS"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        selftest(); return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")
    kal = fetch(client)
    sel = select_markets(kal["markets"])
    per = meetings_per_series(sel["included"])
    shared = sorted(set(per.get("KXFED", [])) & set(per.get("KXFEDDECISION", [])))
    v = verdict(shared, per)

    write_csv([{"series": s, "meeting": m} for s, ms in per.items() for m in ms],
              DATA_DIR / "fomc_meetings_recoverable.csv")
    results = {
        "experiment_id": "janus-track-b-fomc-ladder-settlement", "ledger_row": "L18",
        "spec": "research/exec/2026-08-19_fomc-ladder-settlement/spec.yaml",
        "test_looks_spent": 0,
        "channel_counts": kal["channel_counts"], "pages_fetched": kal["pages"],
        "markets_seen_union": len(kal["markets"]),
        "selection": {"included": len(sel["included"]), "rejected": len(sel["rejected"])},
        "meetings_per_series": per,
        "shared_meetings": shared,
        "verdict": v,
        "pair_status": "BLOCK (UNCHANGED) -- ZQ monthly-average-EFFR extraction untouched",
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({"verdict": v, "meetings_per_series": {k: len(x) for k, x in per.items()},
                      "shared": shared, "markets": len(kal["markets"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

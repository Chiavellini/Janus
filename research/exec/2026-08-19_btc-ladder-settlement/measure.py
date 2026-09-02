#!/usr/bin/env python3
"""L17 — Kalshi BTC ladder settlement characterization. Spec: ./spec.yaml · Ledger L17.

    python3 research/exec/2026-08-19_btc-ladder-settlement/measure.py --self-test
    python3 research/exec/2026-08-19_btc-ladder-settlement/measure.py

TWO SEPARATE QUESTIONS, reported separately and never merged:
  (1) INTRA-VENUE — do KXBTC and KXBTCD publish the same expiration_value for the same strike HOUR?
  (2) EXTERNAL    — does that value match a public CF Benchmarks BRTI reference?

(1) IS ASKED FIRST ON PURPOSE. L14 assumed a period had one Kalshi settlement value and stopped when
it did not; L15 then measured KXINX and KXINXU disagreeing on 25 of 39 shared dates despite identical
rules text and a shared contract_url. Until (1) is answered, "the Kalshi BTC settlement value" may not
name a number, and (2) would be measuring a quantity that does not exist.

THE SPOT SUBSTITUTION IS FORBIDDEN, NOT MERELY DISCOURAGED. If no BRTI source is reachable the
external half reports SOURCE_UNAVAILABLE and stops. Coinbase/Binance/Kraken spot, an aggregator, or a
futures price are NOT BRTI -- swapping one in is the settlement-reference category error the
AGENTS.md 2026-08-14 amendment forbids, and the one that produced phase 1's false "efficient open".
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402
from lib.stats import day_block_ci, json_ready, write_csv  # noqa: E402

_L15 = ROOT / "research/exec/2026-08-19_spx-settlement-basis-per-series/measure.py"
_s = importlib.util.spec_from_file_location("l15", _L15)
l15 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l15)

eq2, f, SourceUnparseable = l15.eq2, l15.f, l15.SourceUnparseable
_get_text = l15._get_text

HERE = Path(__file__).resolve().parent
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DATA_DIR = Path("/Volumes/Kilos/janus/btc_settlement")

SERIES = ["KXBTC", "KXBTCD", "KXBTCMAXD"]
MIN_HOURS = 20
EXACT_FRAC_REQUIRED = 0.95
MAX_ABS_ALLOWED = 0.01


# ── pure core ────────────────────────────────────────────────────────────────

def rules_state_brti(text: str | None) -> bool:
    """spec inclusion_rules.market_filter. Require an explicit BRTI/CF-Benchmarks reference."""
    if not text:
        return False
    t = " ".join(text.lower().split())
    return "brti" in t or ("cf benchmarks" in t and "real-time index" in t)


def strike_hour(iso: str) -> str | None:
    """The settlement instant. On these series close_time IS the event time (M1, map v2)."""
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def select_markets(markets: list[dict]) -> dict:
    included, rejected = [], []
    for m in markets:
        val = f(m.get("expiration_value"))
        rec = {"ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"),
               "series_ticker": m.get("series_ticker"), "close_time": m.get("close_time"),
               "expiration_value": val}
        if val is None:
            rejected.append(dict(rec, reason="NO_EXPIRATION_VALUE")); continue
        if not rules_state_brti(m.get("rules_primary")):
            rejected.append(dict(rec, reason="RULES_NOT_BRTI")); continue
        hour = strike_hour(m.get("close_time"))
        if hour is None:
            rejected.append(dict(rec, reason="UNPARSEABLE_CLOSE_TIME")); continue
        included.append(dict(rec, strike_hour=hour))
    return {"included": included, "rejected": rejected}


def dedupe_per_series(included: list[dict]) -> dict:
    """{series: {strike_hour: value}} plus per-(series, hour) STOPs. Cross-series is DATA."""
    acc: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in included:
        s = r["series_ticker"] or r["ticker"].split("-")[0]
        acc[s][r["strike_hour"]].add(round(r["expiration_value"], 6))
    values, stops = {}, {}
    for s, by_hour in acc.items():
        values[s] = {}
        for h, vals in by_hour.items():
            if len(vals) > 1:
                stops[f"{s}|{h}"] = sorted(vals)
            else:
                values[s][h] = vals.pop()
    return {"values": values, "stops": stops}


def compare_series(values: dict, a: str = "KXBTC", b: str = "KXBTCD") -> dict:
    va, vb = values.get(a, {}), values.get(b, {})
    shared = sorted(set(va) & set(vb))
    diffs = [round(va[h] - vb[h], 6) for h in shared]
    out = {"a": a, "b": b, "n_shared_hours": len(shared),
           "n_exactly_equal": sum(1 for h in shared if eq2(va[h], vb[h])),
           "n_only_a": len(set(va) - set(vb)), "n_only_b": len(set(vb) - set(va))}
    if diffs:
        out.update({
            "frac_exactly_equal": round(out["n_exactly_equal"] / len(shared), 6),
            "median": round(statistics.median(diffs), 6),
            "mean": round(statistics.fmean(diffs), 6),
            "min": round(min(diffs), 6), "max": round(max(diffs), 6),
            "max_abs": round(max(abs(x) for x in diffs), 6),
            "single_signed": all(x > 0 for x in diffs) or all(x < 0 for x in diffs),
            "median_abs_bp": round(statistics.median(
                abs(va[h] - vb[h]) / va[h] * 1e4 for h in shared if va[h]), 4),
        })
        try:
            # blocked by DATE, not hour: hours within a day share one BTC path
            lo, hi = day_block_ci(diffs, [h[:10] for h in shared], seed=0)
            out["ci95"] = [round(lo, 6), round(hi, 6)]
        except Exception as e:  # noqa: BLE001
            out["ci95"], out["ci95_error"] = None, str(e)
    return out


def verdict_intra(cmp_: dict) -> dict:
    n = cmp_["n_shared_hours"]
    if n < MIN_HOURS:
        return {"verdict": "INSUFFICIENT_COVERAGE", "why":
                f"{n} shared strike hours < the pre-registered {MIN_HOURS}; no distribution quoted"}
    if cmp_["frac_exactly_equal"] >= EXACT_FRAC_REQUIRED and cmp_["max_abs"] <= MAX_ABS_ALLOWED:
        return {"verdict": "AGREE", "why":
                f"{cmp_['n_exactly_equal']}/{n} exactly equal, max|diff| {cmp_['max_abs']}"}
    return {"verdict": "WEDGE_MEASURED", "why":
            f"frac {cmp_['frac_exactly_equal']} / max|diff| {cmp_['max_abs']} fails the "
            "pre-registered rule; the wedge is the result"}


# ── I/O shell ────────────────────────────────────────────────────────────────

def load_cached_pages() -> dict:
    """Union every page already on disk, WITHOUT fetching more.

    WHY THIS MODE EXISTS. The registered enumeration is unbounded, and these hourly ladders are
    ~20x the index series: the crawl had pulled 1,027,570 markets across 651 pages (2.0 GB) and was
    still going when it was killed. Completing it would cost hours and many GB to answer a question
    whose registered gate is >= 20 shared strike hours -- a bar the cached slice clears by orders of
    magnitude. So the analysis runs on the cached slice and the TRUNCATION IS REPORTED: page count,
    market count, and the covered strike-hour range all appear in results.json. A bounded read that
    says so is honest; a bounded read that reads like full coverage is the failure mode (L12).
    """
    import json as _json
    d = DATA_DIR / "cache"
    by_ticker, pages, bad = {}, 0, 0
    for fp in sorted(d.glob("*.json")):
        try:
            j = _json.loads(fp.read_text())
        except Exception:  # noqa: BLE001
            bad += 1
            continue
        pages += 1
        ms = list(j.get("markets") or [])
        for ev in (j.get("events") or []):
            for m in ev.get("markets") or []:
                m.setdefault("event_ticker", ev.get("event_ticker"))
                m.setdefault("series_ticker", ev.get("series_ticker"))
                ms.append(m)
        for m in ms:
            if m.get("ticker"):
                by_ticker.setdefault(m["ticker"], m)
    return {"markets": list(by_ticker.values()), "pages": pages, "unparseable_pages": bad}


def fetch_kalshi(client: Client) -> dict:
    by_ticker, counts = {}, {}
    for s in SERIES:
        n = 0
        try:
            for page in client.paginate_cursor(f"{KALSHI}/markets",
                                               {"series_ticker": s, "status": "settled",
                                                "limit": 1000}, "markets"):
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
                for ev in page:
                    for m in ev.get("markets") or []:
                        m.setdefault("event_ticker", ev.get("event_ticker"))
                        m.setdefault("series_ticker", ev.get("series_ticker") or s)
                        by_ticker.setdefault(m["ticker"], m); n += 1
            counts[f"events:{s}"] = n
        except Exception as e:  # noqa: BLE001
            counts[f"events:{s}"] = f"ERROR {e}"
    return {"markets": list(by_ticker.values()), "channel_counts": counts}


def fetch_brti() -> tuple[dict, dict]:
    """Pre-declared BRTI candidates. NO spot fallback -- see the spec's FORBIDDEN_SUBSTITUTION."""
    attempts, errs = [
        "https://api.cfbenchmarks.com/api/v1/values?id=BRTI",
        "https://api.cfbenchmarks.com/api/values/BRTI",
        "https://www.cfbenchmarks.com/api/v1/values?id=BRTI",
    ], {}
    for url in attempts:
        try:
            txt = _get_text(url)
            if "<html" in txt[:400].lower():
                raise SourceUnparseable("HTML body, not JSON")
            d = json.loads(txt)
            if not d:
                raise SourceUnparseable("parsed but empty")
            return {"url": url, "payload_keys": sorted(d)[:10]}, errs
        except Exception as e:  # noqa: BLE001
            errs[url] = f"{type(e).__name__}: {str(e)[:100]}"
    return {}, errs


def selftest() -> None:
    assert rules_state_brti("the simple average of the sixty seconds of BRTI before 5 PM EDT")
    assert not rules_state_brti("the end-of-day S&P 500 index value")
    assert not rules_state_brti(None)
    assert strike_hour("2026-08-19T21:00:00Z") == "2026-08-19T21:00Z"
    assert strike_hour("nonsense") is None

    mk = lambda t, s, h, v: {"ticker": t, "event_ticker": "E", "series_ticker": s,
                             "close_time": h, "expiration_value": v,
                             "rules_primary": "average of the sixty seconds of BRTI before"}
    sel = select_markets([mk("A", "KXBTC", "2026-08-19T21:00:00Z", "64000.10"),
                          mk("B", "KXBTCD", "2026-08-19T21:00:00Z", "64000.10")])
    assert len(sel["included"]) == 2
    d = dedupe_per_series(sel["included"])
    assert not d["stops"]
    c = compare_series(d["values"])
    assert c["n_shared_hours"] == 1 and c["n_exactly_equal"] == 1

    # within-series disagreement STOPs; cross-series disagreement is data
    d2 = dedupe_per_series(select_markets([mk("A", "KXBTC", "2026-08-19T21:00:00Z", "1"),
                                           mk("B", "KXBTC", "2026-08-19T21:00:00Z", "2")])["included"])
    assert d2["stops"]
    assert verdict_intra({"n_shared_hours": 5})["verdict"] == "INSUFFICIENT_COVERAGE"
    assert verdict_intra({"n_shared_hours": 25, "frac_exactly_equal": 1.0, "max_abs": 0.0,
                          "n_exactly_equal": 25})["verdict"] == "AGREE"
    assert verdict_intra({"n_shared_hours": 25, "frac_exactly_equal": 0.5, "max_abs": 3.0,
                          "n_exactly_equal": 12})["verdict"] == "WEDGE_MEASURED"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--from-cache", action="store_true",
                    help="analyse pages already on disk; do not fetch more (truncation reported)")
    a = ap.parse_args()
    if a.self_test:
        selftest(); return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")
    if a.from_cache:
        cached = load_cached_pages()
        kal = {"markets": cached["markets"],
               "channel_counts": {"MODE": "from-cache (enumeration TRUNCATED, see truncation)"}}
        truncation = {
            "enumeration_complete": False,
            "why": "the registered enumeration is unbounded; the crawl reached 1,027,570 markets "
                   "over 651 pages (2.0 GB) and was killed before finishing. The registered gate is "
                   ">= 20 shared strike hours, which the cached slice exceeds by orders of magnitude.",
            "pages_analysed": cached["pages"],
            "unparseable_pages": cached["unparseable_pages"],
            "markets_analysed": len(cached["markets"]),
            "caveat": "This is a CONTIGUOUS SLICE in Kalshi's cursor order, not a random sample and "
                      "not the full settled history. The covered strike-hour range is reported below; "
                      "any statement about periods outside it is unsupported.",
        }
    else:
        kal = fetch_kalshi(client)
        truncation = {"enumeration_complete": True}
    sel = select_markets(kal["markets"])
    ded = dedupe_per_series(sel["included"])
    cmp_ = compare_series(ded["values"])
    v_intra = verdict_intra(cmp_)
    brti, brti_errs = fetch_brti()

    per_series_hours = {s: len(v) for s, v in ded["values"].items()}
    write_csv([{"series": s, "strike_hour": h, "expiration_value": v}
               for s, hv in ded["values"].items() for h, v in sorted(hv.items())],
              DATA_DIR / "btc_settlement_values.csv")

    results = {
        "experiment_id": "janus-track-b-btc-ladder-settlement",
        "ledger_row": "L17",
        "spec": "research/exec/2026-08-19_btc-ladder-settlement/spec.yaml",
        "test_looks_spent": 0,
        "channel_counts": kal["channel_counts"],
        "truncation": truncation,
        "markets_seen_union": len(kal["markets"]),
        "strike_hour_range": {
            s_: {"first": min(hv), "last": max(hv), "n": len(hv)}
            for s_, hv in ded["values"].items() if hv},
        "selection": {"included": len(sel["included"]), "rejected": len(sel["rejected"]),
                      "rejected_reasons": {r: sum(1 for x in sel["rejected"] if x["reason"] == r)
                                           for r in {x["reason"] for x in sel["rejected"]}}},
        "strike_hours_per_series": per_series_hours,
        "within_series_stops": ded["stops"],
        "intra_venue": {"comparison": cmp_, "verdict": v_intra},
        "external_brti": ({"verdict": "REACHED", "source": brti} if brti else
                          {"verdict": "SOURCE_UNAVAILABLE", "attempts": brti_errs,
                           "note": "No BRTI source reachable. Per the registered spec, exchange "
                                   "spot / futures are NOT substituted. This is an ACCESS result, "
                                   "never agreement."}),
        "pair_status": "BLOCK (UNCHANGED) -- this row characterizes one half of one side only",
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({"intra_venue": v_intra, "comparison": {k: cmp_.get(k) for k in
                      ("n_shared_hours", "n_exactly_equal", "frac_exactly_equal", "median",
                       "max_abs", "single_signed", "ci95")},
                      "hours_per_series": per_series_hours,
                      "external": results["external_brti"]["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

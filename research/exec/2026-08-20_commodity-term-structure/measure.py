#!/usr/bin/env python3
"""L23 — Kalshi commodity term-structure and settlement-reference map. Spec: ./spec.yaml · Ledger L23.

    python3 research/exec/2026-08-20_commodity-term-structure/measure.py [--self-test]

Opens family 5.6 of the operator's source taxonomy. Kalshi lists the same commodity at up to eight
cadences, which is a term structure -- but a calendar spread across it is only meaningful if those
cadences settle on the SAME reference, and WTI already proved they need not: named-month futures
(daily), front-month futures (far-dated), and the Pyth PYTHOIL index (15-minute). This maps the
references before anything is compared.

SERIES METADATA IS A HINT, NOT THE REFERENCE. `settlement_sources` carries observable mislabels --
KXWHEATW says "Trading Economics - Corn", KXGOLDEOY says "Trading Economics - Copper". The binding
reference is read from each market's own rules_primary, and disagreements are flagged rather than
silently resolved in favour of either.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402
from lib.stats import json_ready, write_csv  # noqa: E402

HERE = Path(__file__).resolve().parent
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DATA_DIR = Path("/Volumes/Kilos/janus/commodity_map")

#: Ordered: the FIRST pattern that matches wins, most specific first.
REFERENCE_PATTERNS = [
    ("NAMED_MONTH_FUTURES", re.compile(r"\(\s*[A-Za-z]+\s+\d{4}\s*contract\s*\)", re.I)),
    ("FRONT_MONTH_FUTURES", re.compile(r"front[- ]month", re.I)),
    ("PYTH_INDEX",          re.compile(r"\bpyth\b", re.I)),
    ("AGENCY_PUBLICATION",  re.compile(r"energy information administration|\beia\b|\busda\b|"
                                       r"federal reserve|bureau of labor|\bAAA\b", re.I)),
    ("THIRD_PARTY_QUOTE",   re.compile(r"trading economics|google finance|\bICE\b|\bornn\b|"
                                       r"trendforce", re.I)),
    # LAST, so any NAMED source above wins first. Reaching this means the binding rules describe a
    # 1-minute candlestick settlement WITHOUT naming whose candlestick it is. That is the finding,
    # not a leftover bucket: KXGOLDD/KXGOLDW/KXSILVERD name no source in primary OR secondary, while
    # KXNATGASD -- same construct -- names Pyth and documents a futures contract roll.
    ("CANDLESTICK_UNNAMED_SOURCE", re.compile(r"1-minute candlestick|one-minute candlestick", re.I)),
]

#: Rules that describe a futures contract roll. Recorded separately because a rolling front-month
#: reference is a different economic object from a spot print, whatever feed carries it.
ROLL_RE = re.compile(r"rolling forward to the next contract|nearest listed contract month", re.I)


def f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── pure core ────────────────────────────────────────────────────────────────

def has_contract_roll(rules_primary: str | None, rules_secondary: str | None = None) -> bool:
    """True when the rules document a futures contract-month roll."""
    return bool(ROLL_RE.search(" ".join(((rules_primary or "") + " " + (rules_secondary or "")).split())))


def classify_reference(rules_primary: str | None, rules_secondary: str | None = None) -> str:
    """Classify the binding settlement reference from the market's OWN rules text."""
    text = " ".join(((rules_primary or "") + " " + (rules_secondary or "")).split())
    if not text.strip():
        return "UNPARSEABLE"
    for name, rx in REFERENCE_PATTERNS:
        if rx.search(text):
            return name
    return "OTHER"


def underlying_of(ticker: str, title: str) -> str:
    """Group key for the term structure. Deliberately coarse and explicit -- an unmatched series is
    reported as its own group rather than force-fitted into a neighbour."""
    t = (title or "").upper() + " " + (ticker or "").upper()
    for key, pats in (
        ("NATGAS", ("NATURAL GAS", "NATGAS", "KXNGAS")),
        ("WTI", ("WTI", "WEST TEXAS")),
        ("BRENT", ("BRENT",)),
        ("GOLD", ("GOLD",)),
        ("SILVER", ("SILVER",)),
        ("COPPER", ("COPPER",)),
        ("HEATING_OIL", ("HEATING OIL", "HOIL")),
        ("GASOLINE_RETAIL", ("GAS PRICE", "AAAGAS")),
        ("CORN", ("CORN",)), ("WHEAT", ("WHEAT",)), ("SOYBEAN", ("SOYBEAN",)),
        ("COFFEE", ("COFFEE",)), ("COCOA", ("COCOA",)), ("SUGAR", ("SUGAR",)),
        ("COBALT", ("COBALT",)), ("LITHIUM", ("LITHIUM",)), ("NICKEL", ("NICKEL",)),
        ("STEEL", ("STEEL",)), ("PLATINUM", ("PLATINUM",)), ("PALLADIUM", ("PALLADIUM",)),
        ("LIVE_CATTLE", ("LIVE CATTLE", "LCATTLE")), ("BEEF", ("BEEF", "KXB65", "KXB85")),
        ("GPU_COMPUTE", ("A100", "B100", "B200", "H100", "H200", "RTX")),
        ("DRAM", ("DDR5", "DRAM")),
        ("AI_TOKEN", ("GPT", "GEMINI", "OPUS", "TOKEN")),
    ):
        if any(p in t for p in pats):
            return key
    return f"UNGROUPED:{ticker}"


def group_verdict(entries: list[dict]) -> dict:
    """COMPARABLE only if every cadence resolves to the same reference class.

    Cadences with NO live or settled markets carry no rules text to classify. Counting them as
    UNPARSEABLE conflated "we could not read this" with "there was nothing to read", and poisoned
    every group that merely had a dormant cadence. They are excluded from the reference set and
    reported as coverage instead.
    """
    live = [e for e in entries if e["reference_class"] != "NO_MARKETS_TO_SAMPLE"]
    n_dormant = len(entries) - len(live)
    if not live:
        return {"verdict": "NO_LIVE_MARKETS", "references": [], "n_dormant_cadences": n_dormant,
                "why": "no cadence of this underlying had a market to sample"}
    refs = {e["reference_class"] for e in live}
    base = {"n_dormant_cadences": n_dormant, "n_classified_cadences": len(live)}
    if "UNPARSEABLE" in refs:
        return {**base, "verdict": "INSUFFICIENT_RULES", "references": sorted(refs),
                "why": "at least one cadence had rules text that could not be classified"}
    if len(refs) > 1:
        return {**base, "verdict": "CROSS_CADENCE_BLOCK", "references": sorted(refs),
                "why": "cadences of the same underlying resolve to DIFFERENT references; a calendar "
                       "spread across them is forbidden until that basis is measured"}
    return {**base, "verdict": "COMPARABLE", "references": sorted(refs),
            "why": "every classified cadence resolves to the same reference class (necessary, not "
                   "sufficient -- the named instrument must still match)"}


def metadata_conflict(series_source_name: str | None, ref_class: str, title: str) -> bool:
    """Flag a series whose advertised source names a DIFFERENT commodity than its own title."""
    if not series_source_name:
        return False
    src = series_source_name.upper()
    others = ("CORN", "COPPER", "WHEAT", "GOLD", "SILVER", "COCOA", "COFFEE", "SUGAR", "NICKEL")
    t = (title or "").upper()
    named = [o for o in others if o in src]
    return bool(named) and not any(o in t for o in named)


def capacity_of(markets: list[dict]) -> dict:
    sp, oi, two = [], 0.0, 0
    for m in markets:
        b, a = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
        if b is None or a is None:
            continue
        sp.append(a - b)
        oi += f(m.get("open_interest_fp")) or 0.0
        if (f(m.get("yes_bid_size_fp")) or 0) > 0 and (f(m.get("yes_ask_size_fp")) or 0) > 0:
            two += 1
    return {"n_rungs": len(sp),
            "spread_median": round(statistics.median(sp), 4) if sp else None,
            "spread_min": round(min(sp), 4) if sp else None,
            "spread_max": round(max(sp), 4) if sp else None,
            "total_oi": round(oi, 2), "rungs_two_sided": two}


# ── I/O shell ────────────────────────────────────────────────────────────────

def fetch(client: Client) -> dict:
    ser = (client.get_json(f"{KALSHI}/series", params={"category": "Commodities"}).get("series")
           or [])
    out = []
    for s in ser:
        tick = s.get("ticker")
        mk, status_used = [], None
        for status in ("open", "settled"):
            try:
                d = client.get_json(f"{KALSHI}/markets",
                                    params={"series_ticker": tick, "status": status, "limit": 200})
                mk = d.get("markets") or []
            except Exception:  # noqa: BLE001
                mk = []
            if mk:
                status_used = status
                break
        src = (s.get("settlement_sources") or [{}])
        out.append({"series": s, "markets": mk, "status_used": status_used,
                    "source_name": (src[0] or {}).get("name")})
    return {"rows": out, "n_series": len(ser)}


def selftest() -> None:
    assert classify_reference("the daily settlement price for WTI crude oil(October 2026 contract) on X") == "NAMED_MONTH_FUTURES"
    assert classify_reference("the front-month settle price for a barrel of West Texas Intermediate") == "FRONT_MONTH_FUTURES"
    assert classify_reference("the average of Pyth Gold before 5 PM") == "PYTH_INDEX"
    assert classify_reference("as published by the Energy Information Administration") == "AGENCY_PUBLICATION"
    assert classify_reference("according to Trading Economics") == "THIRD_PARTY_QUOTE"
    assert classify_reference("") == "UNPARSEABLE"
    assert classify_reference("something entirely novel") == "OTHER"
    # an unnamed candlestick is its own finding, and a NAMED source still wins
    assert classify_reference("the close price of the 1-minute candlestick for gold") == "CANDLESTICK_UNNAMED_SOURCE"
    assert classify_reference("1-minute candlestick", "using Pyth data") == "PYTH_INDEX"
    assert has_contract_roll("x", "rolling forward to the next contract 5 business days before") is True
    assert has_contract_roll("plain spot print") is False
    # named month must win over a bare ICE mention in the same text
    assert classify_reference("ICE WTI crude oil(October 2026 contract)") == "NAMED_MONTH_FUTURES"

    assert underlying_of("KXNATGASD", "Natural Gas Daily") == "NATGAS"
    assert underlying_of("KXWTI15M", "WTI 15-minute") == "WTI"
    assert underlying_of("KXH100MON", "H100 Monthly Price") == "GPU_COMPUTE"
    assert underlying_of("KXZZZ", "Something Odd").startswith("UNGROUPED:")

    g = group_verdict([{"reference_class": "NAMED_MONTH_FUTURES"},
                       {"reference_class": "PYTH_INDEX"}])
    assert g["verdict"] == "CROSS_CADENCE_BLOCK"
    assert group_verdict([{"reference_class": "PYTH_INDEX"}] * 3)["verdict"] == "COMPARABLE"
    assert group_verdict([{"reference_class": "UNPARSEABLE"}])["verdict"] == "INSUFFICIENT_RULES"
    # a dormant cadence must not poison an otherwise-clean group
    g2 = group_verdict([{"reference_class": "PYTH_INDEX"},
                        {"reference_class": "NO_MARKETS_TO_SAMPLE"}])
    assert g2["verdict"] == "COMPARABLE" and g2["n_dormant_cadences"] == 1
    assert group_verdict([{"reference_class": "NO_MARKETS_TO_SAMPLE"}] * 3)["verdict"] == "NO_LIVE_MARKETS"

    assert metadata_conflict("Trading Economics - Corn", "THIRD_PARTY_QUOTE", "Wheat Weekly") is True
    assert metadata_conflict("Trading Economics - Corn", "THIRD_PARTY_QUOTE", "Corn Weekly") is False
    assert metadata_conflict(None, "OTHER", "Anything") is False

    cap = capacity_of([{"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.42",
                        "open_interest_fp": "10", "yes_bid_size_fp": "1", "yes_ask_size_fp": "1"}])
    assert cap["n_rungs"] == 1 and cap["rungs_two_sided"] == 1
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        selftest(); return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")
    data = fetch(client)

    series_rows, groups = [], defaultdict(list)
    for r in data["rows"]:
        s, mk = r["series"], r["markets"]
        sample = mk[0] if mk else {}
        ref = ("NO_MARKETS_TO_SAMPLE" if not mk
               else classify_reference(sample.get("rules_primary"), sample.get("rules_secondary")))
        row = {
            "ticker": s.get("ticker"), "title": s.get("title"), "frequency": s.get("frequency"),
            "fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier"),
            "source_name": r["source_name"], "contract_url": s.get("contract_url"),
            "reference_class": ref, "markets_status": r["status_used"], "n_markets": len(mk),
            "metadata_conflict": metadata_conflict(r["source_name"], ref, s.get("title")),
            "rules_excerpt": (sample.get("rules_primary") or "")[:160],
            "documents_contract_roll": has_contract_roll(sample.get("rules_primary"),
                                                         sample.get("rules_secondary")),
            "names_a_source_in_rules": ref not in ("CANDLESTICK_UNNAMED_SOURCE", "OTHER",
                                                   "UNPARSEABLE", "NO_MARKETS_TO_SAMPLE"),
            **({"capacity": capacity_of(mk)} if r["status_used"] == "open" else {"capacity": None}),
        }
        row["underlying"] = underlying_of(row["ticker"], row["title"])
        series_rows.append(row)
        groups[row["underlying"]].append(row)

    per_group = {}
    for u, entries in groups.items():
        if u.startswith("UNGROUPED:"):
            continue
        per_group[u] = {
            "n_cadences": len(entries),
            "cadences": sorted({e["frequency"] for e in entries}),
            "by_reference": {rc: sorted(e["ticker"] for e in entries if e["reference_class"] == rc)
                             for rc in sorted({e["reference_class"] for e in entries})},
            **group_verdict(entries),
        }

    write_csv([{k: v for k, v in r.items() if k != "capacity"} for r in series_rows],
              DATA_DIR / "commodity_series_map.csv")
    tradeable = [r for r in series_rows if r["capacity"] and r["capacity"]["n_rungs"] > 0]
    results = {
        "experiment_id": "janus-track-b-commodity-term-structure", "ledger_row": "L23",
        "spec": "research/exec/2026-08-20_commodity-term-structure/spec.yaml",
        "test_looks_spent": 0,
        "n_series": data["n_series"],
        "reference_class_counts": {rc: sum(1 for r in series_rows if r["reference_class"] == rc)
                                   for rc in sorted({r["reference_class"] for r in series_rows})},
        "fee_multiplier_counts": {str(k): sum(1 for r in series_rows if r["fee_multiplier"] == k)
                                  for k in sorted({r["fee_multiplier"] for r in series_rows},
                                                  key=lambda x: str(x))},
        "metadata_conflicts": [{"ticker": r["ticker"], "title": r["title"],
                                "source_name": r["source_name"]}
                               for r in series_rows if r["metadata_conflict"]],
        "per_underlying": per_group,
        "series": series_rows,
        "liquidity_census": {
            "series_with_open_markets": len(tradeable),
            "top_by_oi": sorted(
                [{"ticker": r["ticker"], "frequency": r["frequency"], **r["capacity"]}
                 for r in tradeable], key=lambda x: -(x["total_oi"] or 0))[:12],
        },
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({
        "n_series": results["n_series"],
        "reference_classes": results["reference_class_counts"],
        "metadata_conflicts": len(results["metadata_conflicts"]),
        "groups": {u: {"verdict": g["verdict"], "cadences": len(g["cadences"]),
                       "refs": g["references"]} for u, g in sorted(per_group.items())},
        "series_with_open_markets": results["liquidity_census"]["series_with_open_markets"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

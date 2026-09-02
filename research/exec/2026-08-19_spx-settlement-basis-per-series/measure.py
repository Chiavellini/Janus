#!/usr/bin/env python3
"""L15 — S&P 500 settlement basis, PER KALSHI SERIES. Supersedes L14 (STOP).

    python3 research/exec/2026-08-19_spx-settlement-basis-per-series/measure.py --self-test
    python3 research/exec/2026-08-19_spx-settlement-basis-per-series/measure.py

Spec (immutable): research/exec/2026-08-19_spx-settlement-basis-per-series/spec.yaml · Ledger L15.

WHY PER SERIES. L14 measured (M1) that KXINX and KXINXU publish different `expiration_value` for
the same settlement date, the same 16:00 ET instant, and the same rules sentence, on 25 of 39
shared dates. So "the Kalshi S&P settlement value for date D" is not one number and L14's dedupe
rule was ill-defined. Each series is measured separately here; nothing is pooled and no series is
chosen after the fact.

THE INCLUSION RULES ARE L14's, IMPORTED RATHER THAN RETYPED. The spec says "unchanged from L14";
importing the functions makes that literally true instead of approximately true.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import io
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import USER_AGENT, Client  # noqa: E402
from lib.stats import day_block_ci, json_ready, write_csv  # noqa: E402

_L14 = ROOT / "research/exec/2026-08-19_spx-settlement-basis/measure_spx_basis.py"
_s = importlib.util.spec_from_file_location("l14_core", _L14)
l14 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l14)

select_markets = l14.select_markets      # inclusion rules, unchanged from L14 by construction
fetch_kalshi = l14.fetch_kalshi          # both pre-registered enumeration channels
eq2 = l14.eq2
f = l14.f

HERE = Path(__file__).resolve().parent
DATA_DIR = Path("/Volumes/Kilos/janus/spx_basis")
ET = l14.ET

MIN_DATES = 20
EXACT_FRAC_REQUIRED = 0.95
MAX_ABS_ALLOWED = 0.01
REFERENCE_TOL = 0.01


class SourceUnparseable(Exception):
    """spec `source_integrity_guard`. A 200 that does not parse is NOT an empty series.

    L14 lost its primary reference to exactly this: stooq answered 200 with a JavaScript anti-bot
    page, the CSV reader found no rows, and the run reported "0 observations" as though the series
    were simply empty. A missing source and a blocked source must not look the same.
    """


# ── pure core ────────────────────────────────────────────────────────────────

def dedupe_per_series(included: list[dict]) -> dict:
    """{series: {date: value}} plus per-(series,date) STOPs. Cross-series disagreement is DATA."""
    acc: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    tick: dict[tuple, list] = defaultdict(list)
    for r in included:
        s = r["series_ticker"] or r["ticker"].split("-")[0]
        acc[s][r["settlement_date"]].add(round(r["expiration_value"], 6))
        tick[(s, r["settlement_date"])].append(r["ticker"])
    values, stops = {}, {}
    for s, by_date in acc.items():
        values[s] = {}
        for d, vals in by_date.items():
            if len(vals) > 1:
                stops[f"{s}|{d}"] = {"values": sorted(vals), "n_tickers": len(tick[(s, d)])}
            else:
                values[s][d] = vals.pop()
    return {"values": values, "stops": stops}


def join_reference(kalshi_by_date: dict, primary: dict, crosscheck: dict) -> list[dict]:
    """One row per settlement date for one series."""
    rows = []
    for d in sorted(kalshi_by_date):
        p, c = primary.get(d), crosscheck.get(d)
        row = {"settlement_date": d, "kalshi": kalshi_by_date[d], "fred": p, "yahoo": c,
               "official_close": None, "diff": None, "diff_bp": None}
        if p is None:
            row["status"] = "NO_PRIMARY_CLOSE"
        elif c is not None and abs(round(p, 2) - round(c, 2)) > REFERENCE_TOL:
            row["status"] = "REFERENCE_DISAGREE"
        else:
            row["status"] = "CONFIRMED" if c is not None else "PRIMARY_ONLY"
            row["official_close"] = p
        if row["official_close"] is not None:
            row["diff"] = round(row["kalshi"] - row["official_close"], 6)
            row["diff_bp"] = round(1e4 * row["diff"] / row["official_close"], 4)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    head = [r for r in rows if r["status"] == "CONFIRMED"]
    diffs = [r["diff"] for r in head]
    out = {"n_dates_headline": len(head),
           "n_primary_only": sum(1 for r in rows if r["status"] == "PRIMARY_ONLY"),
           "n_reference_disagree": sum(1 for r in rows if r["status"] == "REFERENCE_DISAGREE"),
           "n_no_primary_close": sum(1 for r in rows if r["status"] == "NO_PRIMARY_CLOSE"),
           "n_exactly_equal": sum(1 for r in head if eq2(r["kalshi"], r["official_close"]))}
    if not head:
        out.update({"frac_exactly_equal": None, "median": None, "mean": None, "iqr": None,
                    "max_abs": None, "median_abs_bp": None, "ci95": None})
        return out
    out["frac_exactly_equal"] = round(out["n_exactly_equal"] / len(head), 6)
    out["median"] = round(statistics.median(diffs), 6)
    out["mean"] = round(statistics.fmean(diffs), 6)
    out["max_abs"] = round(max(abs(x) for x in diffs), 6)
    out["median_abs_bp"] = round(statistics.median(abs(r["diff_bp"]) for r in head), 4)
    out["iqr"] = ([round(q, 6) for q in (statistics.quantiles(diffs, n=4)[0],
                                         statistics.quantiles(diffs, n=4)[2])]
                  if len(head) >= 4 else None)
    try:
        # day_block_ci is the (lo, hi) form; block_bootstrap_ci returns a dict.
        lo, hi = day_block_ci(diffs, [r["settlement_date"] for r in head], seed=0)
        out["ci95"] = [round(lo, 6), round(hi, 6)]
    except Exception as e:  # noqa: BLE001
        out["ci95"], out["ci95_error"] = None, str(e)
    return out


def verdict_for_series(summary: dict, stops: list) -> dict:
    """spec `verdict_rule.per_series`. Evaluated, never adjusted."""
    if stops:
        return {"verdict": "WITHIN_SERIES_DATE_DISAGREEMENT", "status": "BLOCK",
                "why": "markets of this series sharing a settlement date disagree on "
                       "expiration_value"}
    n = summary["n_dates_headline"]
    if n == 0 and summary["n_primary_only"] == 0:
        return {"verdict": "REFERENCE_SOURCE_UNAVAILABLE", "status": "BLOCK",
                "why": "no reference close was reachable for any settlement date"}
    if n < MIN_DATES:
        return {"verdict": "INSUFFICIENT_COVERAGE", "status": "BLOCK",
                "why": f"{n} confirmed dates < the pre-registered {MIN_DATES}; no distribution quoted"}
    if summary["frac_exactly_equal"] >= EXACT_FRAC_REQUIRED and summary["max_abs"] <= MAX_ABS_ALLOWED:
        return {"verdict": "MATCHES_OFFICIAL_CLOSE", "status": "OK",
                "why": f"{summary['n_exactly_equal']}/{n} exactly equal at 2 dp, "
                       f"max|diff| {summary['max_abs']} <= {MAX_ABS_ALLOWED}"}
    return {"verdict": "WEDGE_MEASURED", "status": "BLOCK",
            "why": f"frac_exactly_equal {summary['frac_exactly_equal']} / max|diff| "
                   f"{summary['max_abs']} fails the pre-registered rule; the wedge is the result"}


def series_wedge(values: dict, a: str = "KXINX", b: str = "KXINXU") -> dict:
    """The quantity that stopped L14, reported here as a first-class output."""
    va, vb = values.get(a, {}), values.get(b, {})
    shared = sorted(set(va) & set(vb))
    diffs = [round(va[d] - vb[d], 6) for d in shared]
    out = {"a": a, "b": b, "n_shared_dates": len(shared),
           "n_exactly_equal": sum(1 for d in shared if eq2(va[d], vb[d]))}
    if diffs:
        out.update({"median": round(statistics.median(diffs), 6),
                    "mean": round(statistics.fmean(diffs), 6),
                    "min": round(min(diffs), 6), "max": round(max(diffs), 6),
                    "max_abs": round(max(abs(x) for x in diffs), 6),
                    "single_signed": all(x > 0 for x in diffs) or all(x < 0 for x in diffs),
                    "rows": [{"settlement_date": d, a: va[d], b: vb[d],
                              "diff": round(va[d] - vb[d], 6)} for d in shared]})
    return out


# ── I/O shell ────────────────────────────────────────────────────────────────

def _get_text(url: str, timeout: float = 40.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def parse_fred(text: str) -> dict:
    """CSV `observation_date,SP500`; missing sessions are a literal '.'."""
    if "<html" in text[:400].lower():
        raise SourceUnparseable("FRED returned an HTML body, not CSV")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "observation_date" not in (rows[0].keys()):
        raise SourceUnparseable(f"FRED CSV header unrecognized: {list(rows[0].keys()) if rows else None}")
    out = {}
    for r in rows:
        v = f(r.get("SP500"))
        if v is not None:
            out[r["observation_date"]] = v
    if not out:
        raise SourceUnparseable("FRED CSV parsed but held no numeric observations")
    return out


def parse_yahoo(text: str) -> dict:
    if "<html" in text[:400].lower():
        raise SourceUnparseable("Yahoo returned an HTML body, not JSON")
    try:
        d = json.loads(text)
        res = d["chart"]["result"][0]
        ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    except Exception as e:  # noqa: BLE001
        raise SourceUnparseable(f"Yahoo chart JSON unrecognized: {e}") from e
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        day = dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).astimezone(ET).date().isoformat()
        out[day] = float(c)
    if not out:
        raise SourceUnparseable("Yahoo chart parsed but held no closes")
    return out


def fetch_reference() -> tuple[dict, dict, dict]:
    errs = {}
    try:
        fred = parse_fred(_get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"))
    except Exception as e:  # noqa: BLE001
        fred, errs["fred"] = {}, f"{type(e).__name__}: {e}"
    try:
        yahoo = parse_yahoo(_get_text(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote("^GSPC") + "?range=2y&interval=1d"))
    except Exception as e:  # noqa: BLE001
        yahoo, errs["yahoo"] = {}, f"{type(e).__name__}: {e}"
    return fred, yahoo, errs


def selftest() -> None:
    inc = [{"ticker": "KXINX-A", "series_ticker": "KXINX", "settlement_date": "2026-07-07",
            "expiration_value": 7503.85, "event_ticker": "E1"},
           {"ticker": "KXINXU-A", "series_ticker": "KXINXU", "settlement_date": "2026-07-07",
            "expiration_value": 7503.74, "event_ticker": "E2"}]
    d = dedupe_per_series(inc)
    assert not d["stops"], d
    assert d["values"]["KXINX"]["2026-07-07"] == 7503.85
    assert d["values"]["KXINXU"]["2026-07-07"] == 7503.74
    w = series_wedge(d["values"])
    assert w["n_shared_dates"] == 1 and w["max_abs"] == 0.11

    k = {f"2026-07-{i:02d}": 7000.0 + i for i in range(1, 26)}
    rows = join_reference(k, dict(k), dict(k))
    assert verdict_for_series(summarize(rows), [])["status"] == "OK"
    off = {d: v + 0.5 for d, v in k.items()}
    assert verdict_for_series(summarize(join_reference(k, off, dict(off))), [])["verdict"] \
        == "WEDGE_MEASURED"
    bad = dict(k); bad["2026-07-03"] = k["2026-07-03"] + 9
    st = {r["settlement_date"]: r["status"] for r in join_reference(k, dict(k), bad)}
    assert st["2026-07-03"] == "REFERENCE_DISAGREE"
    assert verdict_for_series(summarize(join_reference(k, {}, {})), [])["verdict"] \
        == "REFERENCE_SOURCE_UNAVAILABLE"
    for p, t in ((parse_fred, "<html><body>nope"), (parse_yahoo, "<HTML>nope")):
        try:
            p(t)
            raise AssertionError("expected SourceUnparseable")
        except SourceUnparseable:
            pass
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        selftest()
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")
    kal = fetch_kalshi(client)
    sel = select_markets(kal["markets"])
    ded = dedupe_per_series(sel["included"])
    fred, yahoo, ref_err = fetch_reference()

    per_series, all_rows = {}, []
    for s in sorted(ded["values"]):
        rows = join_reference(ded["values"][s], fred, yahoo)
        stops = [k for k in ded["stops"] if k.startswith(f"{s}|")]
        summ = summarize(rows)
        per_series[s] = {"summary": summ, "verdict": verdict_for_series(summ, stops),
                         "stops": stops, "rows": rows}
        all_rows += [dict(r, series=s) for r in rows]

    wedge = series_wedge(ded["values"])
    write_csv(all_rows, DATA_DIR / "per_series_basis_rows.csv")

    results = {
        "experiment_id": "janus-track-b-spx-settlement-basis-per-series",
        "ledger_row": "L15", "supersedes": "L14",
        "spec": "research/exec/2026-08-19_spx-settlement-basis-per-series/spec.yaml",
        "test_looks_spent": 0,
        "evidence_tiers": {"kalshi_side": "M1",
                           "official_close_side": "R (FRED redistribution of S&P DJI; not primary)",
                           "equals_sp_dji_official_close": "U"},
        "channel_counts": kal["channel_counts"],
        "markets_seen_union": len(kal["markets"]),
        "selection": {"included": len(sel["included"]), "hourly_excluded": len(sel["hourly"]),
                      "rejected": len(sel["rejected"])},
        "reference_sources": {"fred_rows": len(fred), "yahoo_rows": len(yahoo),
                              "errors": ref_err, "stooq": "DROPPED (L14: JS anti-bot page as 200)"},
        "per_series": per_series,
        "series_wedge_KXINX_minus_KXINXU": wedge,
        "caveats": [
            "The official-close side is FRED's redistribution of the S&P DJI series, tier R. "
            "Equality with the S&P DJI OFFICIAL close remains U.",
            "CBOE publishes no independent PM exercise-settlement print; for SPXW/XSP it IS the "
            "official closing index value by rule. Declared in the spec before the run.",
            "No IBKR value appears anywhere in this measurement. The L13 entitlement block is "
            "separate and unaffected by any outcome here.",
            "A Kalshi-vs-option comparison that does not NAME its series stays BLOCK regardless of "
            "how either series scores here.",
        ],
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({s: {"verdict": v["verdict"], "summary": {
        k: v["summary"][k] for k in ("n_dates_headline", "n_exactly_equal", "frac_exactly_equal",
                                     "median", "max_abs", "median_abs_bp")}}
        for s, v in per_series.items()}, indent=2))
    print(json.dumps({k: wedge[k] for k in wedge if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

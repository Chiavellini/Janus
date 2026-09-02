#!/usr/bin/env python3
"""L14 — S&P 500 settlement-reference basis: Kalshi `expiration_value` vs the official close.

    python3 research/exec/2026-08-19_spx-settlement-basis/measure_spx_basis.py --self-test
    python3 research/exec/2026-08-19_spx-settlement-basis/measure_spx_basis.py

Spec (immutable): research/exec/2026-08-19_spx-settlement-basis/spec.yaml · Ledger row L14.

WHAT THIS IS NOT. It reads no quote, computes no strategy return, extracts no implied distribution,
and never places a Kalshi price next to an IBKR price. The pair it serves is BLOCK in the
settlement map and stays BLOCK unless the pre-registered rule fires.

THE IBKR PRINT IS DELIBERATELY ABSENT. The n=1 gap that motivated this (Kalshi 7691.76 vs IBKR SPX
last 7693.26 on 2026-08-18) was read with IBKR's index feed FROZEN — availability code Z, outside
RTH. A frozen print is a competing explanation for that gap, not a reference to measure against, so
the headline is Kalshi vs the official close and IBKR appears nowhere in it.

THE OFFICIAL-CLOSE SIDE IS TIER R, NOT M1. Neither relay is S&P Dow Jones Indices. Two independent
relays agreeing to <= 0.01 gives CONFIRMED_RELAY, which is still R; "equals the S&P DJI OFFICIAL
close" stays U. Every output says so.

CBOE HAS NO THIRD COLUMN HERE, AND THAT IS STRUCTURAL. For PM-settled SPXW/XSP the exercise
settlement value IS the official closing index value by rule — CBOE publishes no independent print.
The separately published SET ticker is AM-settled third-Friday SPX, which the settlement map
already records as a NON-match. Declared in the spec before the run, not discovered after it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lib.fetch import USER_AGENT, Client  # noqa: E402
from lib.stats import day_block_ci, json_ready, write_csv  # noqa: E402

HERE = Path(__file__).resolve().parent
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DATA_DIR = Path("/Volumes/Kilos/janus/spx_basis")
ET = ZoneInfo("America/New_York")

#: Pre-registered in spec.yaml `inclusion_rules.series`. Not extended after the fact.
SERIES = ["KXINX", "KXINXU", "KXINXAB", "KXINXI"]

#: Pre-registered gates. Mirrored from spec.yaml; changing either here is a spec violation.
MIN_DATES = 20
EXACT_FRAC_REQUIRED = 0.95
MAX_ABS_ALLOWED = 0.01

#: A date whose two relays differ by more than this is RELAY_DISAGREE: excluded and counted.
RELAY_TOL = 0.01

STOP_WITHIN_EVENT = "WITHIN_EVENT_DISAGREEMENT"


# ── pure core (no network, no clock) ─────────────────────────────────────────

def f(v):
    """Kalshi returns decimal-dollar STRINGS where it used to return ints. Same helper as
    catalog/enumerate_kalshi.py::f — parse explicitly, never assume a numeric type."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def et_close(iso: str) -> dt.datetime | None:
    """Parse a Kalshi close_time into America/New_York. Returns None if unparseable."""
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(ET)


def closes_at_1600_et(iso: str) -> bool:
    """spec inclusion_rules.market_filter (b). 16:00 America/New_York, to the minute."""
    d = et_close(iso)
    return bool(d and d.hour == 16 and d.minute == 0)


def rules_state_eod_sp500(text: str | None) -> bool:
    """spec inclusion_rules.market_filter (a).

    The rules text measured on 2026-08-19 reads "the end-of-day S&P 500 index value on <date>".
    We require an end-of-day/closing phrase AND an S&P 500 reference — a market naming the index
    without naming the close (an intraday strike) does not qualify.
    """
    if not text:
        return False
    t = " ".join(text.lower().split())
    eod = any(k in t for k in ("end-of-day", "end of day", "closing value", "close value",
                               "closing price", "closing level"))
    spx = "s&p 500" in t or "s&p500" in t
    return eod and spx


def select_markets(markets: list[dict]) -> dict:
    """Apply the pre-registered inclusion rules. Returns included / hourly / rejected buckets.

    `hourly` is the non-16:00-ET bucket: collected and counted, never in the headline.
    """
    included, hourly, rejected = [], [], []
    for m in markets:
        val = f(m.get("expiration_value"))
        rec = {
            "ticker": m.get("ticker"),
            "event_ticker": m.get("event_ticker"),
            "series_ticker": m.get("series_ticker"),
            "close_time": m.get("close_time"),
            "expiration_value": val,
        }
        if val is None:
            rejected.append(dict(rec, reason="NO_EXPIRATION_VALUE"))
            continue
        if not rules_state_eod_sp500(m.get("rules_primary")):
            rejected.append(dict(rec, reason="RULES_NOT_EOD_SP500"))
            continue
        d = et_close(m.get("close_time"))
        if d is None:
            rejected.append(dict(rec, reason="UNPARSEABLE_CLOSE_TIME"))
            continue
        rec["settlement_date"] = d.date().isoformat()
        if not closes_at_1600_et(m.get("close_time")):
            hourly.append(dict(rec, reason="NOT_1600_ET"))
            continue
        included.append(rec)
    return {"included": included, "hourly": hourly, "rejected": rejected}


def dedupe_by_date(included: list[dict]) -> dict:
    """One (settlement_date, expiration_value) per date, with the within-event consistency check.

    A single event whose markets disagree on `expiration_value` would mean we are reading the
    field wrong — which is the exact failure this experiment exists to avoid — so it is a STOP for
    that date, not an average.
    """
    by_event: dict[str, set] = {}
    for r in included:
        by_event.setdefault(r["event_ticker"], set()).add(round(r["expiration_value"], 6))
    bad_events = {e: sorted(v) for e, v in by_event.items() if len(v) > 1}

    by_date: dict[str, set] = {}
    tickers: dict[str, list] = {}
    for r in included:
        by_date.setdefault(r["settlement_date"], set()).add(round(r["expiration_value"], 6))
        tickers.setdefault(r["settlement_date"], []).append(r["ticker"])

    values, stops = {}, {}
    for d, vals in by_date.items():
        if len(vals) > 1:
            stops[d] = {"reason": STOP_WITHIN_EVENT, "values": sorted(vals),
                        "tickers": sorted(tickers[d])}
        else:
            values[d] = vals.pop()
    return {"values": values, "date_stops": stops, "event_stops": bad_events}


def eq2(a: float, b: float) -> bool:
    """"Exactly equal" operationalized at 2 decimal places — the precision both sides publish.
    Stricter than the spec's max_abs <= 0.01 bound, so it cannot loosen the gate."""
    return round(a, 2) == round(b, 2)


def join_relays(kalshi: dict, relay_a: dict, relay_b: dict) -> list[dict]:
    """Join Kalshi settlement values to the two relays. One row per Kalshi settlement date."""
    rows = []
    for d in sorted(kalshi):
        a, b = relay_a.get(d), relay_b.get(d)
        row = {"settlement_date": d, "kalshi": kalshi[d], "relay_a": a, "relay_b": b,
               "official_close": None, "diff": None, "diff_bp": None}
        if a is None and b is None:
            row["status"] = "NO_RELAY_CLOSE"
        elif a is None or b is None:
            row["status"] = "SINGLE_RELAY"
            row["official_close"] = a if a is not None else b
        elif abs(a - b) > RELAY_TOL:
            row["status"] = "RELAY_DISAGREE"
        else:
            row["status"] = "CONFIRMED_RELAY"
            row["official_close"] = a
        if row["official_close"] is not None:
            row["diff"] = round(kalshi[d] - row["official_close"], 6)
            if row["official_close"]:
                row["diff_bp"] = round(1e4 * row["diff"] / row["official_close"], 4)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    """Headline statistics over CONFIRMED_RELAY rows only.

    SINGLE_RELAY rows are counted and reported but excluded from the headline: one relay is one
    unverified third party, and the spec's confirmation standard is two.
    """
    head = [r for r in rows if r["status"] == "CONFIRMED_RELAY"]
    diffs = [r["diff"] for r in head]
    out = {
        "n_dates_headline": len(head),
        "n_confirmed_relay": len(head),
        "n_single_relay": sum(1 for r in rows if r["status"] == "SINGLE_RELAY"),
        "n_relay_disagree": sum(1 for r in rows if r["status"] == "RELAY_DISAGREE"),
        "n_no_relay_close": sum(1 for r in rows if r["status"] == "NO_RELAY_CLOSE"),
        "n_exactly_equal": sum(1 for r in head if eq2(r["kalshi"], r["official_close"])),
    }
    if not head:
        out.update({"frac_exactly_equal": None, "median": None, "iqr": None, "mean": None,
                    "max_abs": None, "median_abs_bp": None, "ci95": None})
        return out
    out["frac_exactly_equal"] = round(out["n_exactly_equal"] / len(head), 6)
    out["median"] = round(statistics.median(diffs), 6)
    out["mean"] = round(statistics.fmean(diffs), 6)
    out["max_abs"] = round(max(abs(x) for x in diffs), 6)
    out["median_abs_bp"] = round(statistics.median(abs(r["diff_bp"]) for r in head), 4)
    if len(head) >= 4:
        q = statistics.quantiles(diffs, n=4)
        out["iqr"] = [round(q[0], 6), round(q[2], 6)]
    else:
        out["iqr"] = None
    try:
        # day_block_ci is the (lo, hi) form; block_bootstrap_ci returns a dict.
        lo, hi = day_block_ci(diffs, [r["settlement_date"] for r in head], seed=0)
        out["ci95"] = [round(lo, 6), round(hi, 6)]
    except Exception as e:  # noqa: BLE001 — a CI failure must not silently vanish
        out["ci95"] = None
        out["ci95_error"] = str(e)
    return out


def verdict(summary: dict, stops: dict) -> dict:
    """The immutable rule from spec.yaml `verdict_rule`. Evaluated, never adjusted."""
    if stops.get("date_stops") or stops.get("event_stops"):
        return {"verdict": STOP_WITHIN_EVENT, "pair_status": "BLOCK",
                "why": "markets sharing a settlement date/event disagree on expiration_value; "
                       "our reading of the field is falsified for those dates"}
    n = summary["n_dates_headline"]
    if summary["n_confirmed_relay"] == 0 and summary["n_single_relay"] == 0:
        return {"verdict": "REFERENCE_SOURCE_UNAVAILABLE", "pair_status": "BLOCK",
                "why": "no relay close was reachable for any settlement date; an unreachable "
                       "source is an access result, never agreement"}
    if n < MIN_DATES:
        return {"verdict": "INSUFFICIENT_COVERAGE", "pair_status": "BLOCK",
                "why": f"{n} confirmed settlement dates < the pre-registered {MIN_DATES}; "
                       "no distribution is quoted"}
    if summary["frac_exactly_equal"] >= EXACT_FRAC_REQUIRED and summary["max_abs"] <= MAX_ABS_ALLOWED:
        return {"verdict": "REFERENCE_BASIS_MEASURED_ZERO", "pair_status": "OK",
                "why": f"{summary['n_exactly_equal']}/{n} dates exactly equal, "
                       f"max|diff| {summary['max_abs']} <= {MAX_ABS_ALLOWED}"}
    return {"verdict": "REFERENCE_BASIS_MEASURED_NONZERO", "pair_status": "BLOCK",
            "why": f"frac_exactly_equal {summary['frac_exactly_equal']} / max|diff| "
                   f"{summary['max_abs']} fails the pre-registered rule; the measured wedge is "
                   "the result and is recorded as the pair's known_basis"}


# ── I/O shell ────────────────────────────────────────────────────────────────

def _get_text(url: str, timeout: float = 40.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def fetch_kalshi(client: Client) -> dict:
    """Both pre-registered channels, union'd, with per-channel counts (L3's lesson)."""
    by_ticker, counts = {}, {}
    for s in SERIES:
        n = 0
        try:
            for page in client.paginate_cursor(f"{KALSHI}/markets",
                                               {"series_ticker": s, "status": "settled",
                                                "limit": 1000}, "markets"):
                for m in page:
                    by_ticker[m["ticker"]] = m
                    n += 1
        except Exception as e:  # noqa: BLE001
            counts[f"markets:{s}"] = f"ERROR {e}"
            continue
        counts[f"markets:{s}"] = n

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
                        by_ticker.setdefault(m["ticker"], m)
                        n += 1
        except Exception as e:  # noqa: BLE001
            counts[f"events:{s}"] = f"ERROR {e}"
            continue
        counts[f"events:{s}"] = n
    return {"markets": list(by_ticker.values()), "channel_counts": counts}


def fetch_stooq() -> dict:
    """Relay A. CSV: Date,Open,High,Low,Close. Dates are session dates, already ET."""
    txt = _get_text("https://stooq.com/q/d/l/?s=%5Espx&i=d")
    out = {}
    for row in csv.DictReader(io.StringIO(txt)):
        c = f(row.get("Close"))
        if row.get("Date") and c is not None:
            out[row["Date"]] = c
    return out


def fetch_yahoo() -> dict:
    """Relay B. Chart JSON; timestamps are session opens in UTC — convert to the ET session date."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote("^GSPC") + "?range=2y&interval=1d")
    d = json.loads(_get_text(url))
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        day = dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).astimezone(ET).date().isoformat()
        out[day] = float(c)
    return out


# ── self-test (pure core, no network) ────────────────────────────────────────

def selftest() -> None:
    m = {"ticker": "KXINX-26AUG18H1600-T7691.9999", "event_ticker": "KXINX-26AUG18H1600",
         "series_ticker": "KXINX", "close_time": "2026-08-18T20:00:00Z",
         "expiration_value": "7691.76",
         "rules_primary": "If the end-of-day S&P 500 index value on Aug 18, 2026 is above ..."}
    sel = select_markets([m])
    assert len(sel["included"]) == 1, sel
    assert sel["included"][0]["settlement_date"] == "2026-08-18"

    hourly = dict(m, ticker="KXINXU-26AUG19H1000-T7800", event_ticker="KXINXU-26AUG19H1000",
                  close_time="2026-08-19T14:00:00Z")
    assert len(select_markets([hourly])["hourly"]) == 1

    norules = dict(m, ticker="X1", rules_primary="If the S&P 500 is above 7000 at 10am ...")
    assert select_markets([norules])["rejected"][0]["reason"] == "RULES_NOT_EOD_SP500"

    dis = [dict(m, ticker="A"), dict(m, ticker="B", expiration_value="7691.77")]
    d = dedupe_by_date(select_markets(dis)["included"])
    assert d["event_stops"] and d["date_stops"], d
    assert verdict(summarize([]), d)["verdict"] == STOP_WITHIN_EVENT

    k = {f"2026-07-{i:02d}": 7000.0 + i for i in range(1, 26)}
    ra = dict(k)
    rb = dict(k)
    rb["2026-07-05"] = k["2026-07-05"] + 5.0          # relay disagreement
    del rb["2026-07-06"]                              # single relay
    rows = join_relays(k, ra, rb)
    st = {r["settlement_date"]: r["status"] for r in rows}
    assert st["2026-07-05"] == "RELAY_DISAGREE" and st["2026-07-06"] == "SINGLE_RELAY"
    s = summarize(rows)
    assert s["n_relay_disagree"] == 1 and s["n_single_relay"] == 1 and s["n_dates_headline"] == 23
    assert verdict(s, {})["verdict"] == "REFERENCE_BASIS_MEASURED_ZERO"

    few = {f"2026-07-{i:02d}": 7000.0 for i in range(1, 6)}
    assert verdict(summarize(join_relays(few, dict(few), dict(few))), {})["verdict"] \
        == "INSUFFICIENT_COVERAGE"

    ra2 = {d: v + 1.5 for d, v in k.items()}
    assert verdict(summarize(join_relays(k, ra2, dict(ra2))), {})["verdict"] \
        == "REFERENCE_BASIS_MEASURED_NONZERO"

    assert verdict(summarize(join_relays(k, {}, {})), {})["verdict"] == "REFERENCE_SOURCE_UNAVAILABLE"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        selftest()
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")

    kal = fetch_kalshi(client)
    sel = select_markets(kal["markets"])
    ded = dedupe_by_date(sel["included"])

    relays, relay_err = {}, {}
    for name, fn in (("stooq", fetch_stooq), ("yahoo", fetch_yahoo)):
        try:
            relays[name] = fn()
        except Exception as e:  # noqa: BLE001 — unreachable is an access result, recorded
            relays[name] = {}
            relay_err[name] = f"{type(e).__name__}: {e}"

    rows = join_relays(ded["values"], relays["stooq"], relays["yahoo"])
    summ = summarize(rows)
    verd = verdict(summ, ded)

    write_csv(rows, DATA_DIR / "spx_settlement_basis_rows.csv")
    write_csv(sel["hourly"], DATA_DIR / "excluded_hourly_rows.csv")

    results = {
        "experiment_id": "janus-track-b-spx-settlement-basis",
        "ledger_row": "L14",
        "spec": "research/exec/2026-08-19_spx-settlement-basis/spec.yaml",
        "test_looks_spent": 0,
        "evidence_tier_headline": "R (official-close side is a third-party relay, not S&P DJI)",
        "kalshi_side_tier": "M1",
        "channel_counts": kal["channel_counts"],
        "markets_seen_union": len(kal["markets"]),
        "selection": {"included": len(sel["included"]), "hourly_excluded": len(sel["hourly"]),
                      "rejected": len(sel["rejected"]),
                      "rejected_reasons": {r: sum(1 for x in sel["rejected"] if x["reason"] == r)
                                           for r in {x["reason"] for x in sel["rejected"]}}},
        "settlement_dates_with_kalshi_value": len(ded["values"]),
        "within_event_stops": ded["event_stops"],
        "within_date_stops": ded["date_stops"],
        "relay_sources": {"stooq": len(relays["stooq"]), "yahoo": len(relays["yahoo"])},
        "relay_errors": relay_err,
        "summary": summ,
        "verdict": verd,
        "rows": rows,
        "caveats": [
            "The official-close side is a third-party relay. Equality with the S&P DJI OFFICIAL "
            "close remains U; this measures agreement with a CONFIRMED_RELAY value.",
            "CBOE publishes no independent PM exercise-settlement print: for SPXW/XSP it IS the "
            "official closing index value by rule. Declared in the spec before the run.",
            "The IBKR SPX print is excluded by design — it was frozen (code Z) when read, so it "
            "is a competing explanation for the n=1 gap, not a reference.",
            "Entitlement remains the separate, unaffected block on every IBKR family (L13).",
        ],
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({"verdict": verd, "summary": summ,
                      "dates": len(ded["values"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

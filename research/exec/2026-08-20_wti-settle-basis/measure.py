#!/usr/bin/env python3
"""L19 — WTI settlement basis: can NYMEX CL options hedge a Kalshi WTI binary?

    python3 research/exec/2026-08-20_wti-settle-basis/measure.py [--self-test]

Spec: ./spec.yaml (immutable) · Ledger L19.

THE GATING PRECONDITION for the project's founding trade. Kalshi's KXWTI/KXWTIW settle on the daily
settlement of ICE WTI Crude Futures for a NAMED contract month; option liquidity is on NYMEX CL.
Those are different contracts, so the difference must be measured before a CL option is ever priced
against a Kalshi WTI binary (AGENTS.md 2026-08-14: an unmeasured basis is a BLOCK).

CONTRACT-MONTH MATCHING IS THE WHOLE GAME. On 2026-08-18 CME's SEP-26 settle was 84.94 while Kalshi
settled its binary on the OCT-26 contract at 84.06. Comparing across months -- or against a
front-month CONTINUOUS series, which splices at every roll -- would manufacture a ~0.9 USD/Bbl
"basis" that is pure construction artifact. Every comparison here is keyed on (session, month).
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import USER_AGENT, Client  # noqa: E402
from lib.stats import day_block_ci, json_ready, write_csv  # noqa: E402

_L15 = ROOT / "research/exec/2026-08-19_spx-settlement-basis-per-series/measure.py"
_s = importlib.util.spec_from_file_location("l15", _L15)
l15 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l15)
eq2, f, SourceUnparseable = l15.eq2, l15.f, l15.SourceUnparseable

HERE = Path(__file__).resolve().parent
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DATA_DIR = Path("/Volumes/Kilos/janus/wti_basis")
SERIES = ["KXWTI", "KXWTIW"]

MIN_SESSIONS = 20
EXACT_FRAC_REQUIRED = 0.95
MAX_ABS_ALLOWED = 0.01

#: CME product id for NYMEX Light Sweet Crude Oil (CL).
CME_CL_PRODUCT = 425
#: Futures month codes. Used to build the Yahoo per-contract symbol (e.g. OCT 2026 -> CLV26.NYM).
MONTH_CODE = {"JAN": "F", "FEB": "G", "MAR": "H", "APR": "J", "MAY": "K", "JUN": "M",
              "JUL": "N", "AUG": "Q", "SEP": "U", "OCT": "V", "NOV": "X", "DEC": "Z"}
MONTHS = {m: i for i, m in enumerate(
    ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
     "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"), 1)}

_MONTH_RE = re.compile(r"WTI crude oil\s*\(\s*([A-Za-z]+)\s+(\d{4})\s*contract\s*\)", re.I)
_DATE_RE = re.compile(r"\bon\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", re.I)


# ── pure core ────────────────────────────────────────────────────────────────

def parse_contract_month(rules: str | None) -> str | None:
    """'...WTI crude oil(October 2026 contract)...' -> 'OCT 26' (CME's own month format)."""
    m = _MONTH_RE.search(rules or "")
    if not m:
        return None
    name, year = m.group(1).upper(), int(m.group(2))
    if name not in MONTHS:
        return None
    return f"{name[:3]} {year % 100:02d}"


def parse_session_date(rules: str | None) -> str | None:
    """'...on August 18, 2026 is above...' -> '2026-08-18'."""
    m = _DATE_RE.search(rules or "")
    if not m:
        return None
    name, day, year = m.group(1).upper(), int(m.group(2)), int(m.group(3))
    if name not in MONTHS:
        return None
    try:
        return dt.date(year, MONTHS[name], day).isoformat()
    except ValueError:
        return None


def yahoo_symbol(cme_month: str) -> str | None:
    """'OCT 26' -> 'CLV26.NYM'."""
    try:
        mon, yy = cme_month.split()
    except ValueError:
        return None
    code = MONTH_CODE.get(mon.upper())
    return f"CL{code}{yy}.NYM" if code else None


def is_wti_daily_settlement_rule(rules: str | None) -> bool:
    t = " ".join((rules or "").lower().split())
    return "daily settlement price for wti crude oil" in t


def select_markets(markets: list[dict]) -> dict:
    included, rejected = [], []
    for m in markets:
        rec = {"ticker": m.get("ticker"), "series_ticker": m.get("series_ticker"),
               "expiration_value": f(m.get("expiration_value"))}
        rules = m.get("rules_primary")
        if rec["expiration_value"] is None:
            rejected.append(dict(rec, reason="NO_EXPIRATION_VALUE")); continue
        if not is_wti_daily_settlement_rule(rules):
            rejected.append(dict(rec, reason="RULES_NOT_WTI_DAILY_SETTLE")); continue
        month = parse_contract_month(rules)
        if month is None:
            # spec: never default to front month
            rejected.append(dict(rec, reason="MONTH_UNPARSEABLE")); continue
        session = parse_session_date(rules)
        if session is None:
            rejected.append(dict(rec, reason="SESSION_DATE_UNPARSEABLE")); continue
        included.append(dict(rec, month=month, session=session))
    return {"included": included, "rejected": rejected}


def dedupe_per_series(included: list[dict]) -> dict:
    """{series: {(session, month): value}} + per-(series, session, month) STOPs."""
    acc: dict[str, dict[tuple, set]] = defaultdict(lambda: defaultdict(set))
    for r in included:
        s = r["series_ticker"] or (r["ticker"] or "").split("-")[0]
        acc[s][(r["session"], r["month"])].add(round(r["expiration_value"], 6))
    values, stops = {}, {}
    for s, by_key in acc.items():
        values[s] = {}
        for k, vals in by_key.items():
            if len(vals) > 1:
                stops[f"{s}|{k[0]}|{k[1]}"] = sorted(vals)
            else:
                values[s][k] = vals.pop()
    return {"values": values, "stops": stops}


def compare_series(values: dict, a: str = "KXWTI", b: str = "KXWTIW") -> dict:
    """Intra-venue, keyed on (session, month) -- NOT session alone."""
    va, vb = values.get(a, {}), values.get(b, {})
    shared = sorted(set(va) & set(vb))
    diffs = [round(va[k] - vb[k], 6) for k in shared]
    out = {"a": a, "b": b, "n_shared": len(shared),
           "n_exactly_equal": sum(1 for k in shared if eq2(va[k], vb[k])),
           "n_same_session_different_month": len(
               {s for s, _ in va} & {s for s, _ in vb}) - len({s for s, _ in shared})}
    if diffs:
        out.update({"frac_exactly_equal": round(out["n_exactly_equal"] / len(shared), 6),
                    "median": round(statistics.median(diffs), 6),
                    "max_abs": round(max(abs(x) for x in diffs), 6)})
    return out


def join_cl(kalshi: dict, cme: dict, yahoo: dict) -> list[dict]:
    """kalshi: {(session, month): value}; cme/yahoo: {(session, month): settle}."""
    rows = []
    for (session, month) in sorted(kalshi):
        k = kalshi[(session, month)]
        c, y = cme.get((session, month)), yahoo.get((session, month))
        row = {"session": session, "month": month, "kalshi": k, "cme_cl": c, "yahoo_cl": y,
               "diff": None, "diff_bp": None,
               "yahoo_agrees": (None if (c is None or y is None) else bool(eq2(c, y)))}
        if c is None:
            row["status"] = "NO_CL_SETTLE"
        else:
            row["status"] = "OK"
            row["diff"] = round(k - c, 6)
            if c:
                row["diff_bp"] = round(1e4 * row["diff"] / c, 4)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    head = [r for r in rows if r["status"] == "OK"]
    diffs = [r["diff"] for r in head]
    out = {"n_sessions": len(head),
           "n_no_cl_settle": sum(1 for r in rows if r["status"] == "NO_CL_SETTLE"),
           "n_exactly_equal": sum(1 for r in head if eq2(r["kalshi"], r["cme_cl"])),
           "yahoo_corroborated": sum(1 for r in head if r["yahoo_agrees"] is True),
           "yahoo_differed": sum(1 for r in head if r["yahoo_agrees"] is False)}
    if not head:
        out.update({"frac_exactly_equal": None, "median": None, "mean": None,
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
    try:
        lo, hi = day_block_ci(diffs, [r["session"] for r in head], seed=0)
        out["ci95"] = [round(lo, 6), round(hi, 6)]
    except Exception as e:  # noqa: BLE001
        out["ci95"], out["ci95_error"] = None, str(e)
    return out


def verdict(summary: dict, stops: dict) -> dict:
    if stops:
        return {"verdict": "WITHIN_SERIES_DISAGREEMENT", "pair_status": "BLOCK",
                "why": "markets of one series sharing a (session, month) disagree on expiration_value"}
    n = summary["n_sessions"]
    if n == 0:
        return {"verdict": "SOURCE_UNAVAILABLE", "pair_status": "BLOCK",
                "why": "no per-contract CL settlement reachable for any session; an access result, "
                       "never agreement"}
    if n < MIN_SESSIONS:
        return {"verdict": "INSUFFICIENT_COVERAGE", "pair_status": "BLOCK",
                "why": f"{n} sessions < the pre-registered {MIN_SESSIONS}; no distribution quoted"}
    if summary["frac_exactly_equal"] >= EXACT_FRAC_REQUIRED and summary["max_abs"] <= MAX_ABS_ALLOWED:
        return {"verdict": "EQUIVALENT", "pair_status": "OK",
                "why": f"{summary['n_exactly_equal']}/{n} exact at 2 dp, max|diff| "
                       f"{summary['max_abs']} <= {MAX_ABS_ALLOWED}",
                "consequence": "NYMEX CL options are a valid hedge instrument for Kalshi WTI "
                               "binaries; NYMEX Real-Time (NP,L1) $1.55/mo is the correct purchase"}
    return {"verdict": "WEDGE_MEASURED", "pair_status": "BLOCK",
            "why": f"frac_exactly_equal {summary['frac_exactly_equal']} / max|diff| "
                   f"{summary['max_abs']} fails the pre-registered rule",
            "consequence": "the measured difference is the pair's known_basis; a CL-based hedge must "
                           "carry it explicitly, and ICE data/options become the alternative"}


# ── I/O shell ────────────────────────────────────────────────────────────────

def _get(url: str, timeout: float = 30.0) -> str:
    r = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return x.read().decode()


def fetch_kalshi(client: Client) -> dict:
    by_ticker, counts = {}, {}
    for s in SERIES:
        for chan, key, params in (
            ("markets", "markets", {"series_ticker": s, "status": "settled", "limit": 1000}),
            ("events", "events", {"series_ticker": s, "status": "settled",
                                  "with_nested_markets": "true", "limit": 200}),
        ):
            n = 0
            try:
                for page in client.paginate_cursor(f"{KALSHI}/{chan}", params, key):
                    for item in page:
                        ms = [item] if key == "markets" else (item.get("markets") or [])
                        for m in ms:
                            if key == "events":
                                m.setdefault("series_ticker", item.get("series_ticker") or s)
                            by_ticker.setdefault(m["ticker"], m)
                            n += 1
                counts[f"{chan}:{s}"] = n
            except Exception as e:  # noqa: BLE001
                counts[f"{chan}:{s}"] = f"ERROR {e}"
    return {"markets": list(by_ticker.values()), "channel_counts": counts}


def fetch_cme_settles(sessions: set[str]) -> tuple[dict, dict]:
    """CME's own published CL settlements, one request per trade date."""
    out, errs = {}, {}
    for session in sorted(sessions):
        d = dt.date.fromisoformat(session)
        url = (f"https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
               f"{CME_CL_PRODUCT}/FUT?tradeDate={d.month:02d}/{d.day:02d}/{d.year}")
        try:
            body = _get(url)
            if "<html" in body[:400].lower():
                raise SourceUnparseable("HTML body, not JSON")
            payload = json.loads(body)
            rows = payload.get("settlements") or []
            if not rows:
                errs[session] = "no settlements array"
                continue
            for r in rows:
                mon = str(r.get("month") or "").strip().upper()
                val = f(str(r.get("settle") or "").replace(",", ""))
                if mon and val is not None:
                    out[(session, mon)] = val
        except Exception as e:  # noqa: BLE001
            errs[session] = f"{type(e).__name__}: {str(e)[:80]}"
    return out, errs


def fetch_yahoo_settles(month_keys: set[str]) -> tuple[dict, dict]:
    """Independent per-contract cross-check.

    CAVEAT recorded in the output: Yahoo's daily `close` is the last trade, which is not by
    definition the exchange SETTLEMENT. Disagreement here is therefore weak evidence, and no row is
    excluded on it -- it is reported as corroboration only.
    """
    out, errs = {}, {}
    for month in sorted(month_keys):
        sym = yahoo_symbol(month)
        if not sym:
            errs[month] = "unmappable month"
            continue
        try:
            body = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                        f"?range=6mo&interval=1d")
            d = json.loads(body)
            res = d["chart"]["result"][0]
            for ts, close in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
                if close is None:
                    continue
                day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()
                out[(day, month)] = float(close)
        except Exception as e:  # noqa: BLE001
            errs[month] = f"{type(e).__name__}: {str(e)[:80]}"
    return out, errs


def selftest() -> None:
    r = "If the daily settlement price for WTI crude oil(October 2026 contract) on August 18, 2026 is above 87.99 USD/Bbl, then the market resolves to Yes."
    assert parse_contract_month(r) == "OCT 26"
    assert parse_session_date(r) == "2026-08-18"
    assert yahoo_symbol("OCT 26") == "CLV26.NYM" and yahoo_symbol("SEP 26") == "CLU26.NYM"
    assert parse_contract_month("no month here") is None
    assert parse_session_date("no date here") is None
    assert is_wti_daily_settlement_rule(r) and not is_wti_daily_settlement_rule("S&P 500 close")

    mk = lambda t, s, v, rules: {"ticker": t, "series_ticker": s, "expiration_value": v,
                                 "rules_primary": rules}
    sel = select_markets([mk("A", "KXWTI", "84.06", r), mk("B", "KXWTIW", "84.06", r),
                          mk("C", "KXWTI", "84.06", "no month, front month must NOT be assumed")])
    assert len(sel["included"]) == 2
    assert sel["rejected"][0]["reason"] == "RULES_NOT_WTI_DAILY_SETTLE"

    d = dedupe_per_series(sel["included"])
    assert not d["stops"]
    c = compare_series(d["values"])
    assert c["n_shared"] == 1 and c["n_exactly_equal"] == 1

    # month matching: same session, different month must NOT pair
    r2 = r.replace("October", "September")
    d2 = dedupe_per_series(select_markets([mk("A", "KXWTI", "84.06", r),
                                           mk("B", "KXWTIW", "84.94", r2)])["included"])
    assert compare_series(d2["values"])["n_shared"] == 0, "cross-month pairing leaked"

    k = {(f"2026-07-{i:02d}", "OCT 26"): 80.0 + i for i in range(1, 26)}
    rows = join_cl(k, dict(k), dict(k))
    assert verdict(summarize(rows), {})["verdict"] == "EQUIVALENT"
    off = {kk: v + 0.5 for kk, v in k.items()}
    assert verdict(summarize(join_cl(k, off, off)), {})["verdict"] == "WEDGE_MEASURED"
    assert verdict(summarize(join_cl(k, {}, {})), {})["verdict"] == "SOURCE_UNAVAILABLE"
    few = {(f"2026-07-{i:02d}", "OCT 26"): 80.0 for i in range(1, 6)}
    assert verdict(summarize(join_cl(few, dict(few), {})), {})["verdict"] == "INSUFFICIENT_COVERAGE"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        selftest(); return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")
    kal = fetch_kalshi(client)
    sel = select_markets(kal["markets"])
    ded = dedupe_per_series(sel["included"])
    intra = compare_series(ded["values"])

    keys = {k for v in ded["values"].values() for k in v}
    cme, cme_err = fetch_cme_settles({s for s, _ in keys})
    yahoo, y_err = fetch_yahoo_settles({m for _, m in keys})

    per_series = {}
    for s, kv in ded["values"].items():
        rows = join_cl(kv, cme, yahoo)
        summ = summarize(rows)
        per_series[s] = {"summary": summ, "verdict": verdict(summ, {
            k: v for k, v in ded["stops"].items() if k.startswith(f"{s}|")}), "rows": rows}

    write_csv([dict(r, series=s) for s, v in per_series.items() for r in v["rows"]],
              DATA_DIR / "wti_settle_basis_rows.csv")
    results = {
        "experiment_id": "janus-track-b-wti-settle-basis", "ledger_row": "L19",
        "spec": "research/exec/2026-08-20_wti-settle-basis/spec.yaml",
        "test_looks_spent": 0,
        "evidence_tiers": {"kalshi_side": "M1 (the operative settlement value)",
                           "cl_side": "R (CME's own published settlements endpoint)",
                           "yahoo_crosscheck": "R, WEAK -- daily close is the last trade, not by "
                                               "definition the exchange settlement"},
        "channel_counts": kal["channel_counts"],
        "markets_seen_union": len(kal["markets"]),
        "selection": {"included": len(sel["included"]), "rejected": len(sel["rejected"]),
                      "rejected_reasons": {r: sum(1 for x in sel["rejected"] if x["reason"] == r)
                                           for r in {x["reason"] for x in sel["rejected"]}}},
        "sessions_per_series": {s: len(v) for s, v in ded["values"].items()},
        "contract_months_seen": sorted({m for _, m in keys}),
        "within_series_stops": ded["stops"],
        "intra_venue_KXWTI_vs_KXWTIW": intra,
        "per_series": per_series,
        "source_errors": {"cme": cme_err, "yahoo": y_err},
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({"intra_venue": intra,
                      "per_series": {s: {"verdict": v["verdict"]["verdict"],
                                         **{k: v["summary"].get(k) for k in
                                            ("n_sessions", "n_exactly_equal", "frac_exactly_equal",
                                             "median", "max_abs", "ci95")}}
                                     for s, v in per_series.items()},
                      "months": results["contract_months_seen"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""L20 — WTI settlement basis, corrected sources. Supersedes L19. Spec: ./spec.yaml · Ledger L20.

Yahoo per-contract close is PRIMARY here, and that promotion is earned: L19 MEASURED it equal to
CME's own published CL settlement on 5/5 sessions. CME is retained as the exchange-sourced check
wherever it still publishes (~5 recent dates). Everything else -- parsers, month matching, dedupe,
gates -- is imported unchanged from L19 rather than retyped, so "same question, one source swapped"
is literally true instead of approximately true.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402
from lib.stats import json_ready, write_csv  # noqa: E402

_L19 = ROOT / "research/exec/2026-08-20_wti-settle-basis/measure.py"
_s = importlib.util.spec_from_file_location("l19", _L19)
l19 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l19)

HERE = Path(__file__).resolve().parent
DATA_DIR = l19.DATA_DIR
eq2 = l19.eq2


def join_cl_yahoo_primary(kalshi: dict, yahoo: dict, cme: dict) -> list[dict]:
    """Yahoo is the settle source; CME is a corroborating exchange check where it still publishes."""
    rows = []
    for key in sorted(kalshi):
        session, month = key
        k, y, c = kalshi[key], yahoo.get(key), cme.get(key)
        row = {"session": session, "month": month, "kalshi": k, "yahoo_cl": y, "cme_cl": c,
               "cme_agrees": (None if (y is None or c is None) else bool(eq2(y, c))),
               "diff": None, "diff_bp": None}
        if y is None:
            row["status"] = "NO_CL_SETTLE"          # expired contract delisted; counted, not imputed
        else:
            row["status"] = "OK"
            row["diff"] = round(k - y, 6)
            if y:
                row["diff_bp"] = round(1e4 * row["diff"] / y, 4)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    head = [r for r in rows if r["status"] == "OK"]
    # Reuse L19's stats core by mapping this row's roles onto its field names: here the SETTLE is
    # Yahoo and the CORROBORATOR is CME -- the inverse of L19. Mapping rather than reimplementing
    # keeps one definition of the statistics.
    out = l19.summarize([dict(r, cme_cl=r["yahoo_cl"], yahoo_agrees=r["cme_agrees"]) for r in rows])
    out["n_corroborated_by_exchange"] = out.pop("yahoo_corroborated", 0)
    out["n_differed_from_exchange"] = out.pop("yahoo_differed", 0)
    out["n_exchange_checked"] = sum(1 for r in head if r["cme_agrees"] is not None)
    out["n_exchange_agreed"] = sum(1 for r in head if r["cme_agrees"] is True)
    out["n_exchange_differed"] = sum(1 for r in head if r["cme_agrees"] is False)
    return out


def selftest() -> None:
    l19.selftest()
    k = {(f"2026-07-{i:02d}", "OCT 26"): 80.0 + i for i in range(1, 26)}
    rows = join_cl_yahoo_primary(k, dict(k), {})
    s = summarize(rows)
    assert l19.verdict(s, {})["verdict"] == "EQUIVALENT"
    assert s["n_exchange_checked"] == 0                      # no CME rows -> no false corroboration
    rows = join_cl_yahoo_primary(k, dict(k), dict(k))
    s = summarize(rows)
    assert s["n_exchange_checked"] == 25 and s["n_exchange_agreed"] == 25
    # a delisted contract must be counted, never imputed
    rows = join_cl_yahoo_primary(k, {}, {})
    assert all(r["status"] == "NO_CL_SETTLE" and r["diff"] is None for r in rows)
    assert l19.verdict(summarize(rows), {})["verdict"] == "SOURCE_UNAVAILABLE"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        selftest(); return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=DATA_DIR / "cache")
    kal = l19.fetch_kalshi(client)
    sel = l19.select_markets(kal["markets"])
    ded = l19.dedupe_per_series(sel["included"])
    intra = l19.compare_series(ded["values"])

    keys = {k for v in ded["values"].values() for k in v}
    yahoo, y_err = l19.fetch_yahoo_settles({m for _, m in keys})
    cme, cme_err = l19.fetch_cme_settles({s for s, _ in keys})

    per_series = {}
    for s, kv in ded["values"].items():
        rows = join_cl_yahoo_primary(kv, yahoo, cme)
        summ = summarize(rows)
        per_series[s] = {"summary": summ, "rows": rows, "verdict": l19.verdict(
            summ, {k: v for k, v in ded["stops"].items() if k.startswith(f"{s}|")})}

    write_csv([dict(r, series=s) for s, v in per_series.items() for r in v["rows"]],
              DATA_DIR / "wti_settle_basis_yahoo_primary_rows.csv")
    results = {
        "experiment_id": "janus-track-b-wti-settle-basis-yahoo-primary",
        "ledger_row": "L20", "supersedes": "L19",
        "spec": "research/exec/2026-08-20_wti-settle-basis-yahoo-primary/spec.yaml",
        "test_looks_spent": 0,
        "evidence_tiers": {"kalshi": "M1 (operative settlement value)",
                           "cl_primary": "R -- Yahoo per-contract close, promoted on L19's measured 5/5 agreement with the exchange",
                           "cl_exchange_check": "R -- CME's own settlements endpoint, ~5 recent dates only"},
        "coverage_limitation": "Yahoo delists expired contracts (JUL26/AUG26 -> 404); those sessions "
                               "are NO_CL_SETTLE. Sample is the most RECENT contiguous window, not a "
                               "random draw. Drift outside it is out of scope.",
        "channel_counts": kal["channel_counts"],
        "markets_seen_union": len(kal["markets"]),
        "selection": {"included": len(sel["included"]), "rejected": len(sel["rejected"])},
        "sessions_per_series": {s: len(v) for s, v in ded["values"].items()},
        "contract_months_seen": sorted({m for _, m in keys}),
        "within_series_stops": ded["stops"],
        "intra_venue_KXWTI_vs_KXWTIW": intra,
        "per_series": per_series,
        "source_errors": {"yahoo": y_err, "cme_check": cme_err},
        "fetch_stats": client.stats,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({"intra_venue": {k: intra.get(k) for k in ("n_shared","n_exactly_equal","max_abs")},
                      "per_series": {s: {"verdict": v["verdict"]["verdict"],
                                         **{k: v["summary"].get(k) for k in
                                            ("n_sessions","n_exactly_equal","frac_exactly_equal",
                                             "median","max_abs","ci95","n_no_cl_settle",
                                             "n_exchange_checked","n_exchange_agreed","n_exchange_differed")}}
                                     for s, v in per_series.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

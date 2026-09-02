#!/usr/bin/env python3
"""L21 — KXWTI ladder coherence, capacity, and implied mean. Spec: ./spec.yaml · Ledger L21.

    python3 research/exec/2026-08-20_wti-ladder-coherence/measure.py [--self-test]

The first actual test of this project's founding claim. Every KXWTI rung is `strike_type: greater`
with a floor_strike, so the quoted YES price IS P(settle > K) and the ladder is a survival function
needing no model to read as a distribution.

THREE THINGS THIS REFUSES TO DO, each because it has cost this project before:
  * count a MID-price coherence violation as a violation (trap 4 -- the phase-1 maker-pricing bug
    that manufactured a 47c "edge" by resting 27c below fair value);
  * call a sub-tick difference a violation (trap 9 -- a 1c tick means every quote carries +/-0.5c);
  * quote a point estimate for the implied mean when the ladder's own bid/ask bracket is wide
    (the honest object is an INTERVAL, and the futures price either falls inside it or does not).
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402
from lib.ibkr_readonly import IBKRReadOnlyClient  # noqa: E402
from lib.stats import json_ready, write_csv  # noqa: E402

_L19 = ROOT / "research/exec/2026-08-20_wti-settle-basis/measure.py"
_s = importlib.util.spec_from_file_location("l19", _L19)
l19 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l19)
parse_contract_month = l19.parse_contract_month

HERE = Path(__file__).resolve().parent
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DATA_DIR = Path("/Volumes/Kilos/janus/wti_ladder")
IBKR_FIELDS = ("31", "84", "85", "86", "88", "6509")

#: Pre-declared in spec.yaml. A 1c tick puts +/-0.5c on each quote, so a gross edge below the
#: combined band of the two quotes is noise, not a violation.
TICK_BAND_USD = 0.01
#: Pre-declared flat control (trap 3). Commodity series are fee_multiplier 1 -- the 0.07 tier.
FLAT_FEE_PER_LEG = 0.02
#: Truncation guard for the implied mean.
P_LOW_REQUIRED, P_HIGH_ALLOWED = 0.98, 0.02


def f(v):
    """Kalshi returns decimal-dollar STRINGS (trap 7). Same helper as catalog/enumerate_kalshi.py."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── pure core ────────────────────────────────────────────────────────────────

def build_ladder(markets: list[dict]) -> dict:
    """One event -> sorted rungs with validated prices. Raises on an out-of-range price."""
    rungs = []
    for m in markets:
        if m.get("strike_type") != "greater":
            continue
        k = f(m.get("floor_strike"))
        bid, ask = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
        if k is None or bid is None or ask is None:
            continue
        for name, p in (("yes_bid", bid), ("yes_ask", ask)):
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"{name} {p} outside [0,1] on {m.get('ticker')}")
        rungs.append({
            "ticker": m.get("ticker"), "strike": k, "bid": bid, "ask": ask,
            "mid": round((bid + ask) / 2.0, 6), "spread": round(ask - bid, 6),
            "bid_size": f(m.get("yes_bid_size_fp")), "ask_size": f(m.get("yes_ask_size_fp")),
            "open_interest": f(m.get("open_interest_fp")), "volume": f(m.get("volume_fp")),
            "no_bid": f(m.get("no_bid_dollars")), "no_ask": f(m.get("no_ask_dollars")),
        })
    rungs.sort(key=lambda r: r["strike"])
    return {"rungs": rungs}


def check_no_side_identity(rungs: list[dict]) -> dict:
    """Phase 1: no_ask == 1 - yes_bid exactly. Asserted as data quality, never used as a quote."""
    checked = viol = 0
    for r in rungs:
        if r["no_ask"] is None:
            continue
        checked += 1
        if abs(r["no_ask"] - (1.0 - r["bid"])) > 1e-9:
            viol += 1
    return {"checked": checked, "identity_violations": viol}


def monotonicity(rungs: list[dict]) -> dict:
    """P(X > K) must be non-increasing in K. Tested on each price series separately."""
    out = {}
    for side in ("bid", "ask", "mid"):
        bad = [{"lower": rungs[i]["ticker"], "upper": rungs[i + 1]["ticker"],
                "k_lower": rungs[i]["strike"], "k_upper": rungs[i + 1]["strike"],
                "p_lower": rungs[i][side], "p_upper": rungs[i + 1][side],
                "increase": round(rungs[i + 1][side] - rungs[i][side], 6)}
               for i in range(len(rungs) - 1) if rungs[i + 1][side] > rungs[i][side] + 1e-12]
        out[side] = {"n_violations": len(bad), "worst": max((b["increase"] for b in bad), default=0.0),
                     "examples": bad[:5]}
    return out


def no_arb(rungs: list[dict], adjacent_only: bool) -> dict:
    """Executable violation: for K1 < K2, yes_ask(K1) < yes_bid(K2).

    YES(K1) pays at least as much as YES(K2) in every state, so buying the lower strike for less
    than the higher strike sells for is riskless. Mid violations are computed alongside but are NOT
    counted -- a violation that exists only at mid is not executable.
    """
    exe, mid_only, noise = [], [], []
    n = len(rungs)
    pairs = ([(i, i + 1) for i in range(n - 1)] if adjacent_only
             else [(i, j) for i in range(n) for j in range(i + 1, n)])
    for i, j in pairs:
        lo, hi = rungs[i], rungs[j]
        gross = round(hi["bid"] - lo["ask"], 6)          # >0 means riskless at the touch
        rec = {"buy": lo["ticker"], "sell": hi["ticker"], "k_buy": lo["strike"],
               "k_sell": hi["strike"], "buy_ask": lo["ask"], "sell_bid": hi["bid"],
               "gross": gross, "fee_net_flat2c": round(gross - 2 * FLAT_FEE_PER_LEG, 6)}
        if gross > 0:
            (exe if gross >= TICK_BAND_USD else noise).append(rec)
        gross_mid = round(hi["mid"] - lo["mid"], 6)
        if gross_mid > 0 and gross <= 0:
            mid_only.append(dict(rec, gross_mid=gross_mid))
    return {
        "n_pairs": len(pairs),
        "executable_violations": sorted(exe, key=lambda r: -r["gross"]),
        "executable_surviving_flat_2c": [r for r in exe if r["fee_net_flat2c"] > 0],
        "within_tick_noise": noise,
        "mid_only_not_counted": mid_only[:10],
        "n_mid_only": len(mid_only),
    }


def capacity(rungs: list[dict]) -> dict:
    sp = [r["spread"] for r in rungs]
    oi = [r["open_interest"] or 0.0 for r in rungs]
    bs = [r["bid_size"] or 0.0 for r in rungs]
    as_ = [r["ask_size"] or 0.0 for r in rungs]
    return {"n_rungs": len(rungs),
            "spread_median": round(statistics.median(sp), 6) if sp else None,
            "spread_min": min(sp, default=None), "spread_max": max(sp, default=None),
            "rungs_with_oi": sum(1 for x in oi if x > 0), "total_oi": round(sum(oi), 2),
            "depth_at_touch_median_bid": round(statistics.median(bs), 2) if bs else None,
            "depth_at_touch_median_ask": round(statistics.median(as_), 2) if as_ else None,
            "rungs_with_two_sided_depth": sum(1 for b, a in zip(bs, as_) if b > 0 and a > 0)}


def implied_mean(rungs: list[dict], side: str) -> dict:
    """E[X] = integral of P(X>K) dK, trapezoidal over the ladder plus the mass below K_1.

    Returns TRUNCATION_MATERIAL rather than a number when the ladder does not span the
    distribution -- the tails are bounded, never extrapolated with an assumed shape.
    """
    if len(rungs) < 2:
        return {"status": "TOO_FEW_RUNGS"}
    ks = [r["strike"] for r in rungs]
    ps = [r[side] for r in rungs]
    p1, pn = ps[0], ps[-1]
    if p1 < P_LOW_REQUIRED or pn > P_HIGH_ALLOWED:
        return {"status": "TRUNCATION_MATERIAL", "p_at_lowest_strike": p1,
                "p_at_highest_strike": pn, "k_low": ks[0], "k_high": ks[-1],
                "why": f"needs p_low >= {P_LOW_REQUIRED} and p_high <= {P_HIGH_ALLOWED}; the "
                       "omitted tails are material so no point estimate is quoted"}
    area = sum(0.5 * (ps[i] + ps[i + 1]) * (ks[i + 1] - ks[i]) for i in range(len(ks) - 1))
    return {"status": "OK", "implied_mean": round(ks[0] + area, 6),
            "p_at_lowest_strike": p1, "p_at_highest_strike": pn,
            "k_low": ks[0], "k_high": ks[-1]}


def cl_delivery_month(expiration_yyyymmdd: str) -> str | None:
    """IBKR CL expirationDate -> CME delivery month. CL Oct-26 stops trading ~2026-09-22, so the
    delivery month is the month AFTER the expiration month. Verified against L19's Kalshi months."""
    try:
        d = dt.datetime.strptime(str(expiration_yyyymmdd), "%Y%m%d").date()
    except (ValueError, TypeError):
        return None
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return f"{('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split())[m-1]} {y % 100:02d}"


def point_vs_futures(mean_mid: dict, fut_bid: float | None, fut_ask: float | None) -> dict:
    """Mid-based point comparison, reported ALONGSIDE the interval and never instead of it.

    The interval is the honest object (trap 4); this exists so a truncated ask side does not throw
    away a mid series that passed its own guard. Labelled mid-based so it is never read as executable.
    """
    if mean_mid.get("status") != "OK":
        return {"status": mean_mid.get("status")}
    if fut_bid is None or fut_ask is None:
        return {"status": "NO_FUTURES_QUOTE", "implied_mean_mid": mean_mid["implied_mean"]}
    fmid = (fut_bid + fut_ask) / 2.0
    return {"status": "OK", "basis": "MID -- not executable; the crossed comparison is the interval",
            "implied_mean_mid": mean_mid["implied_mean"], "futures_mid": round(fmid, 4),
            "gap_usd_bbl": round(mean_mid["implied_mean"] - fmid, 4),
            "gap_bp": round(1e4 * (mean_mid["implied_mean"] - fmid) / fmid, 2)}


def compare_to_futures(mean_bid: dict, mean_ask: dict, fut_bid: float | None,
                       fut_ask: float | None) -> dict:
    """The ladder implies an INTERVAL, not a point. Report whether the futures price falls inside."""
    # Report WHICH side truncated. The first version used `a.get() or b.get()`, which returned the
    # string "OK" as the reason a comparison failed -- an unreadable diagnostic.
    sides = {"bid": mean_bid.get("status"), "ask": mean_ask.get("status")}
    failed = {k: v for k, v in sides.items() if v != "OK"}
    if failed:
        return {"status": "NO_INTERVAL", "failed_sides": failed,
                "ok_sides": {k: v for k, v in sides.items() if v == "OK"},
                "why": "an interval needs both the bid- and ask-side implied means; "
                       f"{sorted(failed)} truncated"}
    lo, hi = mean_bid["implied_mean"], mean_ask["implied_mean"]
    if lo > hi:
        lo, hi = hi, lo
    if fut_bid is None or fut_ask is None:
        return {"status": "NO_FUTURES_QUOTE", "ladder_interval": [round(lo, 4), round(hi, 4)]}
    fmid = (fut_bid + fut_ask) / 2.0
    inside = lo <= fmid <= hi
    return {"status": "OK", "ladder_interval": [round(lo, 4), round(hi, 4)],
            "futures_mid": round(fmid, 4), "futures_bid": fut_bid, "futures_ask": fut_ask,
            "futures_inside_ladder_interval": inside,
            "gap_to_nearest_edge": 0.0 if inside else round(min(abs(fmid - lo), abs(fmid - hi)), 4),
            "interpretation": ("no mispricing detectable at executable prices" if inside else
                               "the futures price lies OUTSIDE the ladder's own bid/ask bracket")}


# ── I/O shell ────────────────────────────────────────────────────────────────

def fetch_kalshi_ladders(client: Client) -> dict:
    ms = []
    for page in client.paginate_cursor(f"{KALSHI}/markets",
                                       {"series_ticker": "KXWTI", "status": "open",
                                        "limit": 1000}, "markets"):
        ms += page
    by_event = defaultdict(list)
    for m in ms:
        by_event[m.get("event_ticker")].append(m)
    return {"markets": ms, "by_event": dict(by_event)}


def fetch_cl_quotes(months_needed: set[str]) -> tuple[dict, dict]:
    """Delayed CL futures (availability D*). Allowlisted endpoints only; nothing persisted."""
    out, errs = {}, {}
    try:
        c = IBKRReadOnlyClient()
        st = c.auth_status()
        if not (st.get("authenticated") and st.get("connected")):
            return {}, {"auth": "gateway not authenticated"}
        rows = (c.futures("CL") or {}).get("CL") or []
        want = {}
        for r in rows:
            mon = cl_delivery_month(r.get("expirationDate"))
            if mon in months_needed and mon not in want:
                want[mon] = int(r["conid"])
        if not want:
            return {}, {"discovery": f"no CL contract matched {sorted(months_needed)}"}
        ids = list(want.values())
        c.snapshot(ids, IBKR_FIELDS)
        time.sleep(1.6)
        snap = c.snapshot(ids, IBKR_FIELDS)
        recv = time.time()
        by_conid = {int(x.get("conid")): x for x in (snap if isinstance(snap, list) else [])
                    if x.get("conid") is not None}
        for mon, cid in want.items():
            row = by_conid.get(cid) or {}
            upd = row.get("_updated")
            out[mon] = {"conid": cid, "bid": f(row.get("84")), "ask": f(row.get("86")),
                        "last": f(row.get("31")), "availability": row.get("6509"),
                        "recv_ts": recv, "ibkr_updated_ms": upd,
                        "staleness_s": (round(recv - int(upd) / 1000.0, 1)
                                        if isinstance(upd, (int, float)) else None)}
    except Exception as e:  # noqa: BLE001
        errs["ibkr"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out, errs


def selftest() -> None:
    mk = lambda t, k, b, a: {"ticker": t, "strike_type": "greater", "floor_strike": k,
                             "yes_bid_dollars": str(b), "yes_ask_dollars": str(a),
                             "no_bid_dollars": str(round(1 - a, 4)),
                             "no_ask_dollars": str(round(1 - b, 4)),
                             "yes_bid_size_fp": "10", "yes_ask_size_fp": "10",
                             "open_interest_fp": "5", "volume_fp": "1"}
    lad = build_ladder([mk("A", 80.0, 0.90, 0.92), mk("B", 81.0, 0.70, 0.72),
                        mk("C", 82.0, 0.50, 0.52)])["rungs"]
    assert [r["strike"] for r in lad] == [80.0, 81.0, 82.0]
    assert check_no_side_identity(lad)["identity_violations"] == 0
    assert monotonicity(lad)["mid"]["n_violations"] == 0
    assert no_arb(lad, adjacent_only=True)["executable_violations"] == []

    # a real executable violation: the LOWER strike is cheaper to buy than the HIGHER sells for
    bad = build_ladder([mk("A", 80.0, 0.40, 0.42), mk("B", 81.0, 0.60, 0.62)])["rungs"]
    na = no_arb(bad, adjacent_only=True)
    assert len(na["executable_violations"]) == 1
    assert na["executable_violations"][0]["gross"] == 0.18
    assert na["executable_violations"][0]["fee_net_flat2c"] == 0.14
    assert monotonicity(bad)["mid"]["n_violations"] == 1

    # sub-tick edge must be noise, not a violation
    tiny = build_ladder([mk("A", 80.0, 0.50, 0.520), mk("B", 81.0, 0.525, 0.55)])["rungs"]
    nt = no_arb(tiny, adjacent_only=True)
    assert nt["executable_violations"] == [] and len(nt["within_tick_noise"]) == 1

    # mid-only violation must NOT be counted as executable
    midonly = build_ladder([mk("A", 80.0, 0.40, 0.60), mk("B", 81.0, 0.45, 0.65)])["rungs"]
    nm = no_arb(midonly, adjacent_only=True)
    assert nm["executable_violations"] == [] and nm["n_mid_only"] == 1

    try:
        build_ladder([mk("X", 80.0, 1.5, 1.6)])
        raise AssertionError("out-of-range price accepted")
    except ValueError:
        pass

    full = build_ladder([mk(f"K{i}", 80.0 + i, max(0.0, 0.99 - i * 0.11),
                           max(0.01, 1.0 - i * 0.11)) for i in range(10)])["rungs"]
    im = implied_mean(full, "mid")
    assert im["status"] in ("OK", "TRUNCATION_MATERIAL")
    narrow = build_ladder([mk("A", 80.0, 0.5, 0.6), mk("B", 90.0, 0.4, 0.5)])["rungs"]
    assert implied_mean(narrow, "mid")["status"] == "TRUNCATION_MATERIAL"

    assert cl_delivery_month("20260922") == "OCT 26"
    assert cl_delivery_month("20260820") == "SEP 26"
    assert cl_delivery_month("20261221") == "JAN 27"
    assert cl_delivery_month("bogus") is None
    assert parse_contract_month("WTI crude oil(October 2026 contract)") == "OCT 26"

    c = compare_to_futures({"status": "OK", "implied_mean": 84.0},
                           {"status": "OK", "implied_mean": 85.0}, 84.2, 84.3)
    assert c["futures_inside_ladder_interval"] is True and c["gap_to_nearest_edge"] == 0.0
    c2 = compare_to_futures({"status": "OK", "implied_mean": 84.0},
                            {"status": "OK", "implied_mean": 85.0}, 90.0, 90.1)
    assert c2["futures_inside_ladder_interval"] is False and c2["gap_to_nearest_edge"] == 5.05
    # a truncated side must name ITSELF, not report "OK" as the failure reason
    c3 = compare_to_futures({"status": "OK", "implied_mean": 84.0},
                            {"status": "TRUNCATION_MATERIAL"}, 84.2, 84.3)
    assert c3["status"] == "NO_INTERVAL" and list(c3["failed_sides"]) == ["ask"]
    assert c3["ok_sides"] == {"bid": "OK"}
    pm = point_vs_futures({"status": "OK", "implied_mean": 84.25}, 84.18, 84.20)
    assert pm["gap_usd_bbl"] == 0.06 and "not executable" in pm["basis"]
    assert point_vs_futures({"status": "TRUNCATION_MATERIAL"}, 1, 2)["status"] == "TRUNCATION_MATERIAL"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        selftest(); return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=None)   # live snapshot: never cached
    kal = fetch_kalshi_ladders(client)
    snap_ts = time.time()

    events, months = {}, set()
    for ev, ms in kal["by_event"].items():
        lad = build_ladder(ms)["rungs"]
        if len(lad) < 2:
            continue
        month = next((parse_contract_month(m.get("rules_primary")) for m in ms
                      if parse_contract_month(m.get("rules_primary"))), None)
        if month:
            months.add(month)
        events[ev] = {"contract_month": month, "rungs": lad}

    cl, cl_err = fetch_cl_quotes(months)

    per_event = {}
    for ev, e in events.items():
        lad = e["rungs"]
        fq = cl.get(e["contract_month"]) or {}
        per_event[ev] = {
            "contract_month": e["contract_month"],
            "close_time": None,
            "no_side_identity": check_no_side_identity(lad),
            "capacity": capacity(lad),
            "monotonicity": monotonicity(lad),
            "no_arb_adjacent": no_arb(lad, adjacent_only=True),
            "no_arb_all_pairs": {k: v for k, v in no_arb(lad, adjacent_only=False).items()
                                 if k in ("n_pairs", "executable_surviving_flat_2c")} |
                                {"n_executable": len(no_arb(lad, adjacent_only=False)["executable_violations"])},
            "implied_mean_bid": implied_mean(lad, "bid"),
            "implied_mean_ask": implied_mean(lad, "ask"),
            "implied_mean_mid": implied_mean(lad, "mid"),
            "futures": fq,
            "part_C": compare_to_futures(implied_mean(lad, "bid"), implied_mean(lad, "ask"),
                                         fq.get("bid"), fq.get("ask")),
            "part_C_mid": point_vs_futures(implied_mean(lad, "mid"), fq.get("bid"), fq.get("ask")),
        }

    write_csv([dict(r, event=ev) for ev, e in events.items() for r in e["rungs"]],
              DATA_DIR / "kxwti_ladder_snapshot.csv")
    results = {
        "experiment_id": "janus-track-b-wti-ladder-coherence", "ledger_row": "L21",
        "spec": "research/exec/2026-08-20_wti-ladder-coherence/spec.yaml",
        "test_looks_spent": 0,
        "snapshot_utc": dt.datetime.fromtimestamp(snap_ts, dt.timezone.utc).isoformat(),
        "n_is_one_for_part_C": True,
        "controls": {"tick_band_usd": TICK_BAND_USD, "flat_fee_per_leg": FLAT_FEE_PER_LEG,
                     "truncation_guard": [P_LOW_REQUIRED, P_HIGH_ALLOWED]},
        "markets_seen": len(kal["markets"]), "events": sorted(events),
        "contract_months": sorted(months),
        "per_event": per_event, "ibkr_errors": cl_err,
    }
    (HERE / "results.json").write_text(json.dumps(json_ready(results), indent=2, sort_keys=True))
    print(json.dumps({ev: {
        "month": v["contract_month"],
        "capacity": {k: v["capacity"][k] for k in ("n_rungs", "spread_median", "total_oi",
                                                   "rungs_with_two_sided_depth")},
        "mono_violations_mid": v["monotonicity"]["mid"]["n_violations"],
        "executable_adjacent": len(v["no_arb_adjacent"]["executable_violations"]),
        "executable_surviving_2c": len(v["no_arb_adjacent"]["executable_surviving_flat_2c"]),
        "within_tick_noise": len(v["no_arb_adjacent"]["within_tick_noise"]),
        "mid_only_not_counted": v["no_arb_adjacent"]["n_mid_only"],
        "part_C": v["part_C"],
    } for ev, v in per_event.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

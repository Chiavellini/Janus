#!/usr/bin/env python3
"""L22 — forward capture of the KXWTI ladder + delayed NYMEX CL futures.

    python3 collectors/collect_wti_ladder.py --self-test
    python3 collectors/collect_wti_ladder.py --once
    python3 collectors/collect_wti_ladder.py                # loop at the registered cadence

Spec: research/exec/2026-08-20_wti-ladder-forward/spec.yaml (immutable) · Ledger L22.

CAPTURE ONLY. This writes rows; it draws no conclusion. The analysis that this data enables is
deliberately a SEPARATE ledger row, because deciding to spend the project's first numbered test look
belongs to the operator and must not arrive as a side effect of starting a collector.

Every scheduled slot writes exactly one snapshot row -- ok or reason-coded. A missing observation is
always an explicit row, never an absence; that distinction is what Phase A lost for two days.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import shutil
import signal
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.fetch import Client  # noqa: E402
from lib.ibkr_readonly import IBKRReadOnlyClient, IBKRSafetyError  # noqa: E402

_L21 = ROOT / "research/exec/2026-08-20_wti-ladder-coherence/measure.py"
_s = importlib.util.spec_from_file_location("l21", _L21)
l21 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l21)

SPEC_REF = "research/exec/2026-08-20_wti-ladder-forward/spec.yaml"
VERSION = "wti-ladder-forward/0.1.0"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DB_PATH = Path("/Volumes/Kilos/janus/wti_ladder/forward.sqlite")
PERIOD_S = 300.0
DISK_FLOOR_BYTES = 2 * 1024**3
IBKR_FIELDS = l21.IBKR_FIELDS

GAP_REASONS = {"KALSHI_ERROR", "KALSHI_EMPTY", "IBKR_AUTH_INVALID", "IBKR_ERROR",
               "IBKR_NO_CONTRACT", "MONTH_UNPARSEABLE", "FRONT_MONTH_RULE", "DISK_FLOOR",
               "MARKET_CLOSED", "UNKNOWN"}

#: Nothing here should ever contain an identifier -- prices and strikes only. Asserted at write time.
FORBIDDEN_TEXT = re.compile(r"acctId|accountId|\bU\d{6,}\b|session|cookie|\bMAC\b|hardware|userId",
                            re.IGNORECASE)
#: L21 measured that far-dated KXWTI events settle on the FRONT-MONTH price -- a time-varying
#: reference L20's CL-equivalence result does not cover. Tagged, never pooled with named months.
FRONT_MONTH_RE = re.compile(r"front-month", re.I)

DDL = """
CREATE TABLE IF NOT EXISTS snapshots(slot_ts REAL PRIMARY KEY, recv_ts REAL, ok INTEGER,
  reason TEXT, n_events INTEGER, n_rungs INTEGER, spec_ref TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS rungs(slot_ts REAL, event TEXT, ticker TEXT, strike REAL, bid REAL,
  ask REAL, mid REAL, spread REAL, bid_size REAL, ask_size REAL, open_interest REAL, volume REAL);
CREATE INDEX IF NOT EXISTS rungs_slot ON rungs(slot_ts);
CREATE TABLE IF NOT EXISTS events(slot_ts REAL, event TEXT, contract_month TEXT, rule_kind TEXT,
  n_rungs INTEGER, spread_median REAL, total_oi REAL, executable_violations INTEGER,
  mono_violations_mid INTEGER, im_bid REAL, im_bid_status TEXT, im_ask REAL, im_ask_status TEXT,
  im_mid REAL, im_mid_status TEXT);
CREATE INDEX IF NOT EXISTS events_slot ON events(slot_ts);
CREATE TABLE IF NOT EXISTS futures(slot_ts REAL, month TEXT, conid INTEGER, bid REAL, ask REAL,
  last REAL, availability TEXT, ibkr_updated_ms REAL, recv_ts REAL, staleness_s REAL);
CREATE TABLE IF NOT EXISTS health(ts REAL, component TEXT, status TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path: Path, enforce_root: bool = True):
        if enforce_root and not str(Path(path).resolve()).startswith("/Volumes/Kilos/"):
            raise ValueError("L22 data must live on /Volumes/Kilos, never the root disk")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(DDL)

    @staticmethod
    def _check(*vals):
        for v in vals:
            if isinstance(v, str) and FORBIDDEN_TEXT.search(v):
                raise ValueError("refusing to persist text matching the privacy denylist")

    def snapshot(self, **kw):
        if kw.get("reason") and kw["reason"] not in GAP_REASONS:
            raise ValueError(f"unregistered gap reason {kw['reason']}")
        self._check(kw.get("reason"))
        self.con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
                         (kw["slot_ts"], kw.get("recv_ts"), int(kw["ok"]), kw.get("reason"),
                          kw.get("n_events", 0), kw.get("n_rungs", 0), SPEC_REF, VERSION))

    def rung(self, slot_ts, event, r):
        self._check(event, r.get("ticker"))
        self.con.execute("INSERT INTO rungs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (slot_ts, event, r["ticker"], r["strike"], r["bid"], r["ask"], r["mid"],
                          r["spread"], r["bid_size"], r["ask_size"], r["open_interest"], r["volume"]))

    def event_row(self, slot_ts, event, month, rule_kind, cap, mono, exe, ims):
        self._check(event, month, rule_kind)
        self.con.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (slot_ts, event, month, rule_kind, cap["n_rungs"], cap["spread_median"],
                          cap["total_oi"], exe, mono,
                          ims["bid"].get("implied_mean"), ims["bid"]["status"],
                          ims["ask"].get("implied_mean"), ims["ask"]["status"],
                          ims["mid"].get("implied_mean"), ims["mid"]["status"]))

    def future(self, slot_ts, month, q):
        self._check(month, q.get("availability"))
        self.con.execute("INSERT INTO futures VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (slot_ts, month, q.get("conid"), q.get("bid"), q.get("ask"), q.get("last"),
                          q.get("availability"), q.get("ibkr_updated_ms"), q.get("recv_ts"),
                          q.get("staleness_s")))

    def health(self, component, status, detail="", ts=None):
        self._check(detail)
        self.con.execute("INSERT INTO health VALUES (?,?,?,?)",
                         (ts or time.time(), component, status, detail[:500]))

    def flush(self):
        self.con.commit()


def rule_kind_of(markets: list[dict]) -> tuple[str, str | None]:
    """(rule_kind, contract_month). Front-month events are tagged, never pooled with named months."""
    for m in markets:
        rules = m.get("rules_primary") or ""
        if FRONT_MONTH_RE.search(rules):
            return "front_month", None
        mon = l21.parse_contract_month(rules)
        if mon:
            return "named_month", mon
    return "unknown", None


def next_slot(now: float, period: float = PERIOD_S) -> float:
    return (int(now // period) + 1) * period


def cycle(store: Store, client: Client, slot_ts: float, *, now=time.time,
          fetch_futures=None) -> dict:
    """One capture cycle. Always writes exactly one snapshots row."""
    free = shutil.disk_usage("/").free
    if free < DISK_FLOOR_BYTES:
        store.snapshot(slot_ts=slot_ts, ok=False, reason="DISK_FLOOR", recv_ts=now())
        store.health("monitor", "DISK_FLOOR", f"internal_free={free}")
        store.flush()
        return {"ok": False, "reason": "DISK_FLOOR"}
    try:
        ms = []
        for page in client.paginate_cursor(f"{KALSHI}/markets",
                                           {"series_ticker": "KXWTI", "status": "open",
                                            "limit": 1000}, "markets"):
            ms += page
    except Exception as e:  # noqa: BLE001
        store.snapshot(slot_ts=slot_ts, ok=False, reason="KALSHI_ERROR", recv_ts=now())
        store.health("kalshi", "error", f"{type(e).__name__}"); store.flush()
        return {"ok": False, "reason": "KALSHI_ERROR"}
    recv = now()
    if not ms:
        store.snapshot(slot_ts=slot_ts, ok=False, reason="KALSHI_EMPTY", recv_ts=recv)
        store.flush()
        return {"ok": False, "reason": "KALSHI_EMPTY"}

    by_event: dict[str, list] = {}
    for m in ms:
        by_event.setdefault(m.get("event_ticker"), []).append(m)

    months, per_event, n_rungs = set(), {}, 0
    for ev, mk in by_event.items():
        rungs = l21.build_ladder(mk)["rungs"]
        if len(rungs) < 2:
            continue
        kind, month = rule_kind_of(mk)
        if kind == "named_month" and month:
            months.add(month)
        per_event[ev] = (rungs, kind, month)
        n_rungs += len(rungs)

    fut = {}
    if months:
        fut, ferr = (fetch_futures or l21.fetch_cl_quotes)(months)
        if ferr:
            store.health("ibkr", "error", json.dumps(ferr)[:200])

    for ev, (rungs, kind, month) in per_event.items():
        for r in rungs:
            store.rung(slot_ts, ev, r)
        cap = l21.capacity(rungs)
        mono = l21.monotonicity(rungs)["mid"]["n_violations"]
        exe = len(l21.no_arb(rungs, adjacent_only=False)["executable_violations"])
        ims = {side: l21.implied_mean(rungs, side) for side in ("bid", "ask", "mid")}
        store.event_row(slot_ts, ev, month, kind, cap, mono, exe, ims)
        if kind == "front_month":
            store.health("selection", "FRONT_MONTH_RULE", ev)
    for month, q in fut.items():
        store.future(slot_ts, month, q)

    store.snapshot(slot_ts=slot_ts, ok=True, recv_ts=recv, n_events=len(per_event), n_rungs=n_rungs)
    store.flush()
    return {"ok": True, "n_events": len(per_event), "n_rungs": n_rungs, "months": sorted(months),
            "futures": sorted(fut)}


def selftest() -> None:
    import tempfile
    l21.selftest()
    assert next_slot(1000.0, 300.0) == 1200.0
    mk = lambda t, k, b, a, rules: {"ticker": t, "strike_type": "greater", "floor_strike": k,
                                    "yes_bid_dollars": str(b), "yes_ask_dollars": str(a),
                                    "no_bid_dollars": str(round(1-a, 4)),
                                    "no_ask_dollars": str(round(1-b, 4)),
                                    "yes_bid_size_fp": "5", "yes_ask_size_fp": "5",
                                    "open_interest_fp": "1", "volume_fp": "1",
                                    "event_ticker": "E", "rules_primary": rules}
    named = "the daily settlement price for WTI crude oil(October 2026 contract) on August 20, 2026"
    front = "the front-month settle price for a barrel of West Texas Intermediate oil"
    assert rule_kind_of([mk("A", 80, .9, .92, named)]) == ("named_month", "OCT 26")
    assert rule_kind_of([mk("A", 80, .9, .92, front)])[0] == "front_month"
    assert rule_kind_of([mk("A", 80, .9, .92, "nothing")]) == ("unknown", None)

    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / "t.sqlite", enforce_root=False)
        try:
            st.snapshot(slot_ts=1.0, ok=False, reason="NOT_A_REGISTERED_REASON")
            raise AssertionError("unregistered gap reason accepted")
        except ValueError:
            pass
        try:
            st.health("x", "y", "sessionId=abc")
            raise AssertionError("privacy denylist not enforced")
        except ValueError:
            pass
        # a cycle with a failing Kalshi client still writes exactly one snapshot row
        class Boom:
            def paginate_cursor(self, *a, **k): raise RuntimeError("down")
        r = cycle(st, Boom(), 100.0)
        assert r["reason"] == "KALSHI_ERROR"
        n = st.con.execute("SELECT COUNT(*) FROM snapshots WHERE slot_ts=100.0").fetchone()[0]
        assert n == 1, "a failed cycle must still write one row"

        class FakeK:
            def paginate_cursor(self, *a, **k):
                yield [mk("A", 80, .95, .96, named), mk("B", 81, .90, .91, named)]
        r = cycle(st, FakeK(), 200.0, fetch_futures=lambda months: ({}, {}))
        assert r["ok"] and r["n_rungs"] == 2 and r["months"] == ["OCT 26"]
        kind = st.con.execute("SELECT rule_kind FROM events WHERE slot_ts=200.0").fetchone()[0]
        assert kind == "named_month"
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    if a.self_test:
        selftest(); return 0

    store = Store(Path(a.db))
    client = Client("kalshi", rate=4.0, burst=8.0, cache_dir=None)
    store.health("collector", "startup", f"version={VERSION} spec={SPEC_REF} period={PERIOD_S}")
    store.flush()
    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(v=True))

    if a.once:
        print(json.dumps(cycle(store, client, next_slot(time.time()) - PERIOD_S), indent=2))
        return 0
    while not stop["v"]:
        slot = next_slot(time.time())
        while time.time() < slot and not stop["v"]:
            time.sleep(min(1.0, max(0.0, slot - time.time())))
        if stop["v"]:
            break
        try:
            cycle(store, client, slot)
        except IBKRSafetyError:
            store.health("safety", "FORBIDDEN_ATTEMPT", "client refused before network"); raise
        except Exception as e:  # noqa: BLE001
            store.snapshot(slot_ts=slot, ok=False, reason="UNKNOWN", recv_ts=time.time())
            store.health("collector", "cycle_error", type(e).__name__); store.flush()
    store.health("collector", "shutdown"); store.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

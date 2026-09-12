#!/usr/bin/env python3
"""L78's offline instrument: the FULL evaluation pipeline (pollers, callbacks, sizing, store) fed
the L51 10k-frame capture prefix, on a real Supervisor with live sizing on and a stub executor.
Paired before/after: CPU seconds, evaluations, sizing sweeps, selections, and digests of the
stream_evaluations rows and of every selection (event, epoch, quantity), which must not change.

    python3 research/infra/2026-09-12_loop-waste/measure.py --label after --runs 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.schema import Mode  # noqa: E402
from nodes.capture.capture import read_frames  # noqa: E402
from nodes.discovery.discovery import load_specs, load_tier_timeline  # noqa: E402
from nodes.opportunity.opportunity import OpportunityStore  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.stream_kalshi.stream import KalshiStream  # noqa: E402
from nodes.stream_polymarket.stream import PolymarketStream  # noqa: E402
from grids.live_stream.grid import Supervisor  # noqa: E402

CAPTURE = Path("/Volumes/Kilos/janus/research/l51-capture-7q8lj2ab/level-3-repeat-0")
SLATE = Path("/Volumes/Kilos/janus/research/l78-slate-20260909T04/slate.sqlite")
PROFILE = False
DAY, HOUR = "2026-09-09", "04"


def frames(venue: str, limit: int):
    out = []
    for fr in read_frames(CAPTURE / venue / DAY / f"{HOUR}.jsonl.gz", venue):
        out.append(fr)
        if len(out) >= limit:
            break
    return out


def build(tmp: Path, specs: dict, timeline: dict):
    store = TupleStore(tmp / "t.sqlite", enforce_volume=False)
    sup = Supervisor([], db=tmp / "t.sqlite")
    sup.store = store
    sup.opportunities = OpportunityStore(store)
    sup.ks = KalshiStream(api_key="replay", private_key=None)
    sup.ps = PolymarketStream()
    sup.mode, sup.limits, sup.ledger = Mode.LIMITED_LIVE, load_limits(), ExposureLedger()
    sup.caps = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}
    sup.balance_snapshot = {"kalshi": 250.0, "polymarket": 250.0}
    sup.balance_snapshot_mono = time.monotonic() + 1e9        # never stale for the run
    sup.coordinator = object()
    sup.retain_days = 0
    selections = []
    sup._execute = lambda s, ev, rec, sizing=None: selections.append((ev.game_id, round(ev.evaluated_utc, 3), ev.quantity))
    slate = {}
    for gid, spec in specs.items():
        tl = timeline.get(gid) or []
        spec = dict(spec)
        spec.setdefault("tier", tl[0][1] if tl else spec.get("tier"))
        spec.setdefault("state", spec.get("state", "in"))
        spec.setdefault("short_name", spec.get("short_name", gid))
        slate[gid] = spec
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        sup.reconcile(slate)
    return sup, store, selections


def run_once(specs, timeline, kf, pf) -> dict:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        sup, store, selections = build(tmp, specs, timeline)
        import io, contextlib
        merged = sorted(kf + pf, key=lambda f: f.received_utc)
        t0 = time.process_time(); w0 = time.perf_counter()
        prof = None
        if PROFILE:
            import cProfile
            prof = cProfile.Profile(); prof.enable()
        with contextlib.redirect_stdout(io.StringIO()):
            for fr in merged:
                if fr.venue == "kalshi":
                    sup.ks.handle(json.loads(fr.raw), now=fr.received_utc, mono=fr.received_mono)
                else:
                    sup.ps.handle(fr.raw, now=fr.received_utc, mono=fr.received_mono)
            store.commit()
        cpu = time.process_time() - t0; wall = time.perf_counter() - w0
        if prof is not None:
            import pstats
            prof.disable(); st = pstats.Stats(prof)
            top = sorted(st.stats.items(), key=lambda kv: kv[1][2], reverse=True)[:30]
            print("== offline self-time top 30 (of %.1f s)" % st.total_tt, file=sys.stderr)
            for k, v in top:
                print(f"{100 * v[2] / st.total_tt:5.1f}%  {v[1]:>8}  {Path(k[0]).name}:{k[1]}:{k[2]}", file=sys.stderr)
        rows = store.con.execute("SELECT game_id, quantity, seen_ts, status, cost, gross, fees, return_locked, blocked_by "
                                 "FROM stream_evaluations ORDER BY seen_ts, game_id, quantity").fetchall()
        norm = [tuple(round(x, 6) if isinstance(x, float) else x for x in r) for r in rows]
        evals = sum(s.evaluations for s in sup.live.values())
        skipped = sum(getattr(s, "sizing_skipped", 0) for s in sup.live.values())
        sizing_rows = store.con.execute("SELECT count(*) FROM sizing_decisions").fetchone()[0]
        store.close()
        return {"cpu_s": round(cpu, 3), "wall_s": round(wall, 3), "frames": len(merged), "pollers": len(sup.live),
                "evaluations": evals, "evaluation_rows": len(rows), "sizing_skipped": skipped, "sizing_rows": sizing_rows,
                "selections": len(selections),
                "rows_digest": hashlib.sha256(json.dumps(norm, default=str).encode()).hexdigest()[:16],
                "selections_digest": hashlib.sha256(json.dumps(sorted(selections)).encode()).hexdigest()[:16]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--frames", type=int, default=10000)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--profile", action="store_true")
    a = ap.parse_args()
    global PROFILE
    PROFILE = a.profile
    slate = TupleStore(SLATE, enforce_volume=False)
    specs, timeline = load_specs(slate), load_tier_timeline(slate)
    slate.close()
    kf, pf = frames("kalshi", a.frames), frames("polymarket", a.frames)
    runs = [run_once(specs, timeline, kf, pf) for _ in range(a.runs)]
    cpus = sorted(r["cpu_s"] for r in runs)
    out = {"label": a.label, "capture": str(CAPTURE), "slate": str(SLATE), "runs": runs, "median_cpu_s": cpus[len(cpus) // 2],
           "digests_stable": len({(r["rows_digest"], r["selections_digest"]) for r in runs}) == 1}
    p = a.out / f"results_offline_{a.label}.json"
    p.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "runs"}, indent=1)); print(json.dumps(runs[0], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

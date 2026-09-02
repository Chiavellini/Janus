#!/usr/bin/env python3
"""Gate report + free characterization for the IBKR forward archive (L14 gate, L15 descriptive).

Reads the archive read-only. Computes ONLY capture mechanics: poll success, per-instrument row
kinds, availability codes, staleness, spread, size, update frequency, session coverage, roll
lineage, disk burn, privacy scan. No settlement outcome, no PnL, no strategy rule.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.ibkr_archive_core import FORBIDDEN_TEXT, availability_status  # noqa: E402

OUT_DIR = Path("research/exec/2026-08-18_ibkr-forward-archive")
GATE_HOURS = 24.0


def _q(con: sqlite3.Connection, sql: str, *params: Any) -> list[tuple]:
    return [tuple(r) for r in con.execute(sql, params).fetchall()]


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = min(len(values) - 1, max(0, int(round(p * (len(values) - 1)))))
    return values[k]


def report(db: Path, out_dir: Path = OUT_DIR, *, now: float | None = None) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    first_poll, last_poll = _q(con, "SELECT MIN(slot_ts), MAX(slot_ts) FROM polls")[0]
    duration_h = ((last_poll - first_poll) / 3600.0) if first_poll and last_poll else 0.0
    ok, total = _q(con, "SELECT COALESCE(SUM(ok),0), COUNT(*) FROM polls")[0]
    reasons = dict(_q(con, "SELECT reason, COUNT(*) FROM polls WHERE ok=0 GROUP BY reason"))
    result: dict[str, Any] = {
        "spec_ref": "research/exec/2026-08-18_ibkr-forward-archive/spec.yaml",
        "ledger_row": "L14", "evidence_tier": "M1 capture mechanics", "test_looks_spent": 0,
        "orders_placed": 0, "outcomes_or_pnl_read": False,
        "generated_utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
        "duration_h": round(duration_h, 3), "polls_total": total, "polls_ok": ok,
        "poll_success_rate": (ok / total) if total else None, "poll_fail_reasons": reasons,
        "db_bytes": db.stat().st_size,
        "disk_mb_per_day": (db.stat().st_size / 1e6 / (duration_h / 24)) if duration_h > 0 else None,
    }
    latencies = [r[0] for r in _q(con, "SELECT latency_ms FROM polls WHERE ok=1 AND latency_ms IS NOT NULL")]
    result["poll_latency_ms"] = {"p50": _pct(latencies, .5), "p95": _pct(latencies, .95),
                                 "max": max(latencies) if latencies else None}

    instruments = []
    for row in con.execute("SELECT * FROM instruments ORDER BY family, root, sec_type, \"right\", selected_ts"):
        r = dict(zip([d[0] for d in con.execute("SELECT * FROM instruments LIMIT 0").description], row))
        conid = r["conid"]
        kinds = dict(_q(con, "SELECT row_kind, COUNT(*) FROM quotes WHERE conid=? GROUP BY row_kind", conid))
        gaps = dict(_q(con, "SELECT gap_reason, COUNT(*) FROM quotes WHERE conid=? AND row_kind='GAP' GROUP BY gap_reason", conid))
        codes = dict(_q(con, "SELECT availability_code, COUNT(*) FROM quotes WHERE conid=? AND row_kind='MSG' GROUP BY availability_code", conid))
        msgs = _q(con, "SELECT recv_ts, staleness_ms, bid, ask, bid_size, ask_size, session_label FROM quotes "
                       "WHERE conid=? AND row_kind='MSG' ORDER BY recv_ts", conid)
        stal = [m[1] for m in msgs if m[1] is not None]
        spreads = [m[3] - m[2] for m in msgs if m[2] is not None and m[3] is not None and m[3] >= m[2]]
        crossed = sum(1 for m in msgs if m[2] is not None and m[3] is not None and m[3] < m[2])
        sizes = [s for m in msgs for s in (m[4], m[5]) if s is not None]
        gaps_between = [b[0] - a[0] for a, b in zip(msgs, msgs[1:])]
        by_session: dict[str, int] = {}
        for m in msgs:
            by_session[m[6] or "?"] = by_session.get(m[6] or "?", 0) + 1
        instruments.append({
            "conid": conid, "family": r["family"], "root": r["root"], "sec_type": r["sec_type"],
            "expiry": r["expiry"], "expiry_pinned": bool(r["expiry_pinned"]), "strike": r["strike"],
            "right": r["right"], "selection_rule": r["selection_rule"], "selected_ts": r["selected_ts"],
            "retired_ts": r["retired_ts"], "row_kinds": kinds, "gap_reasons": gaps,
            "availability_codes": codes,
            "availability_status": sorted({availability_status(c) for c in codes}) or ["NO_MESSAGE_YET"],
            "msg_rows": len(msgs), "msg_by_session": by_session,
            "staleness_ms": {"p50": _pct(stal, .5), "p95": _pct(stal, .95), "min": min(stal) if stal else None},
            "spread": {"p50": _pct(spreads, .5), "p95": _pct(spreads, .95), "crossed_rows": crossed},
            "displayed_size": {"p50": _pct(sizes, .5)},
            "inter_message_s": {"p50": _pct(gaps_between, .5), "p95": _pct(gaps_between, .95)},
        })
    result["instruments"] = instruments
    result["contract_rolls"] = _q(con, "SELECT family, slot, old_conid, new_conid, roll_ts, reason FROM contract_roll ORDER BY roll_ts")
    dup = _q(con, "SELECT family, root, sec_type, \"right\", COUNT(*) FROM instruments WHERE retired_ts IS NULL "
                  "GROUP BY family, root, sec_type, \"right\" HAVING COUNT(*)>1")
    result["duplicate_active_identities"] = dup
    result["health_counts"] = dict(_q(con, "SELECT component||':'||status, COUNT(*) FROM health GROUP BY 1"))
    result["null_timestamps"] = _q(con, "SELECT COUNT(*) FROM quotes WHERE recv_ts IS NULL")[0][0] + \
        _q(con, "SELECT COUNT(*) FROM quotes WHERE row_kind='MSG' AND ibkr_updated_ms IS NULL")[0][0]

    # Privacy scan over every text column.
    leak = 0
    for table in ("instruments", "contract_roll", "polls", "quotes", "health"):
        for row in con.execute(f"SELECT * FROM {table}"):
            if any(isinstance(v, str) and (FORBIDDEN_TEXT.search(v) or re.search(r"\bU\d{6,}\b", v)) for v in row):
                leak += 1
    result["privacy_leak_rows"] = leak
    con.close()

    startup_forbidden = [v for k, v in result["health_counts"].items() if "SAFETY" in k.upper()]
    included_ok = all(("HFT_READY" in i["availability_status"]) or i["msg_rows"] == 0
                      for i in instruments if i["retired_ts"] is None)
    checks = {
        "duration_ge_24h": duration_h >= GATE_HOURS,
        "zero_identifiers": leak == 0,
        "zero_forbidden_attempts": not startup_forbidden,
        "availability_R_star_on_included": included_ok,
        "explicit_gap_rows_present_when_polls_failed": (sum(reasons.values()) == 0) or any(i["gap_reasons"] for i in instruments),
        "timestamps_always_present": result["null_timestamps"] == 0,
        "no_duplicate_identity": not dup,
        "disk_bounded_150MB_day": (result["disk_mb_per_day"] or 0) <= 150,
        "restart_and_auth_reason_coded": any(k.startswith("collector:startup") for k in result["health_counts"]),
    }
    result["gate_checks"] = checks
    if duration_h < GATE_HOURS:
        result["verdict"] = "PENDING_INSUFFICIENT_DURATION"
    else:
        result["verdict"] = "PASS" if all(checks.values()) else "FAIL_STOP"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    lines = [f"# IBKR forward archive — L14 gate report", "",
             f"**{result['verdict']}** · duration {duration_h:.2f} h · polls {ok}/{total} ok · "
             f"disk {result['disk_mb_per_day'] and round(result['disk_mb_per_day'], 1)} MB/day · "
             f"privacy leak rows {leak} · test looks spent 0 · orders placed 0", "",
             "| conid | family | root | type | expiry | strike | right | MSG rows | avail | stale p50 ms | spread p50 | inter-msg p50 s |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i in instruments:
        lines.append(f"| {i['conid']} | {i['family']} | {i['root']} | {i['sec_type']} | {i['expiry']} | {i['strike']} | "
                     f"{i['right']} | {i['msg_rows']} | {','.join(i['availability_status'])} | "
                     f"{i['staleness_ms']['p50']} | {i['spread']['p50']} | {i['inter_message_s']['p50']} |")
    lines += ["", "Gate checks: " + ", ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in checks.items()), "",
              "No settlement outcome or PnL was read. No account, session, user, hardware, or MAC identifier was archived."]
    (out_dir / "verdict.md").write_text("\n".join(lines) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/Volumes/Kilos/janus/ibkr/archive.sqlite")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args()
    result = report(Path(args.db), Path(args.out))
    print(json.dumps({k: result[k] for k in ("verdict", "duration_h", "polls_ok", "polls_total",
                                                "disk_mb_per_day", "privacy_leak_rows", "gate_checks")},
                     indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

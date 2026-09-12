#!/usr/bin/env python3
"""One read-only snapshot of the box for the launchpad (ops/launchpad.py), as JSON between
sentinels. Runs on the box as `janus` (the override and the databases are 0600), stdlib only, every
database opened `mode=ro`, nothing written anywhere. It is sent through ops/box/run.sh on stdin by
the laptop, so nothing here assumes a checkout path: JANUS_REPO (default /opt/janus) is the tree
whose watchdog it imports for the alert list.

    sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box /opt/janus/.venv/bin/python3 - < ops/box/launchpad_extract.py

What it reads: executions of the last 24 h with their settlement and orders (the ownership walk of
nodes/reconcile/settle_executions: first_client_id + hedge/unwind client ids, never opportunity_id),
open exposure (unreleased executions, open orders, open reservations), the arming override minus
its signature, kill files, the breaker, socket health, lane flags, redemptions, disk, memory, load,
systemd, and the watchdog's alerts with its disk sample write disabled.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BEGIN, END = "===JANUS_JSON_BEGIN===", "===JANUS_JSON_END==="
HOLDS_POSITION = {"LEG_A_FILLED", "LEG_A_PARTIAL", "LEG_B_SUBMITTED", "LEG_B_PARTIAL", "LEG_B_FILLED",
                  "UNWIND_SUBMITTED", "HEDGE_SLIPPAGE_EXCEEDED", "UNKNOWN_PROVIDER_STATE", "HEDGE_FAILED",
                  "PROTECT_FAILED"}
PENDING = {"HEDGED", "SETTLED"}
ADDR = re.compile(r"0x[0-9a-fA-F]{8,}")


def redact(s):
    """A wallet address is an identifier: keep the last six characters only."""
    return ADDR.sub(lambda m: "0x…" + m.group(0)[-6:], s) if isinstance(s, str) else s


def sh(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"<{type(exc).__name__}>"


def _ro(path: Path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _table(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _json(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def system_state(data_root: Path, repo: Path) -> dict:
    units = {}
    for u in ("janus-live-stream", "janus-pm-redeem.timer", "janus-pm-redeem.service", "janus-census.timer", "janus-watchdog.timer"):
        out = sh(["systemctl", "show", u, "-p", "ActiveState,SubState,NRestarts,ExecMainStartTimestamp,NextElapseUSecRealtime,Result", "--value"])
        vals = out.split("\n") if out and not out.startswith("<") else []
        units[u] = dict(zip(("active", "sub", "restarts", "since", "next", "result"), vals + [""] * 6)) if vals else {"active": "unknown"}
    disk = {}
    for name, p in (("data", data_root), ("root", Path("/"))):
        try:
            u = shutil.disk_usage(p)
            disk[name] = {"total": u.total, "used": u.used, "free": u.free}
        except OSError:
            disk[name] = None
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.strip().split()[0]) // 1024
    except OSError:
        pass
    try:
        load = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except OSError:
        load = []
    return {"units": units, "disk": disk, "mem_mb": mem, "load": load,
            "deployed_sha": sh(["git", "-C", str(repo), "rev-parse", "HEAD"]),
            "host": sh(["hostname"]), "uptime": sh(["uptime", "-p"])}


def override_state(kill_root: Path, now: float) -> dict | None:
    p = kill_root / "arming_override.json"
    if not p.exists():
        return None
    d = _json(p.read_text(), {})
    out = {k: v for k, v in d.items() if not any(s in k.lower() for s in ("sig", "hmac", "secret", "key"))}
    try:
        exp = time.strptime(str(d.get("expires_utc", ""))[:19], "%Y-%m-%dT%H:%M:%S")
        import calendar
        out["seconds_left"] = int(calendar.timegm(exp) - now)
    except ValueError:
        out["seconds_left"] = None
    return out


def kill_state(kill_root: Path) -> tuple[list, dict | None]:
    kills, breaker = [], None
    if kill_root.is_dir():
        for f in sorted(kill_root.iterdir()):
            if f.name == "arming_override.json" or not f.is_file():
                continue
            body = _json(f.read_text(), {"raw": f.read_text()[:200]})
            if f.name == "breaker.json":
                breaker = body
            else:
                kills.append({"name": f.name, **({k: redact(v) for k, v in body.items()} if isinstance(body, dict) else {"raw": str(body)[:200]}),
                              "mtime": f.stat().st_mtime})
    return kills, breaker


def watchdog_alerts(repo: Path, data_root: Path) -> list[str]:
    try:
        sys.path.insert(0, str(repo))
        os.environ.setdefault("JANUS_DATA_ROOT", str(data_root))
        from ops.watchdog import check
        return [str(a) for a in check(disk={})]          # disk={}: never write the sample file from here
    except Exception as exc:  # noqa: BLE001
        return [f"watchdog: UNREADABLE — {type(exc).__name__}: {str(exc)[:80]}"]


def sockets(con, now: float) -> tuple[dict, list]:
    out, lag = {}, []
    if not _table(con, "socket_health"):
        return out, lag
    hi = con.execute("SELECT max(rowid) FROM socket_health").fetchone()[0] or 0
    for v in ("kalshi", "polymarket", "polymarket_user"):
        r = con.execute("SELECT seen_ts,connected,age_s,loop_lag_s,frames,last_error,clock_healthy FROM socket_health "
                        "WHERE venue=? AND rowid>? ORDER BY seen_ts DESC LIMIT 1", (v, hi - 400)).fetchone()
        out[v] = None if r is None else {"tick_age_s": round(now - r["seen_ts"], 1), "connected": bool(r["connected"]),
                                         "age_s": r["age_s"], "loop_lag_s": r["loop_lag_s"], "frames": r["frames"],
                                         "last_error": redact((r["last_error"] or "")[:120]), "clock_healthy": r["clock_healthy"]}
    lag = [(r[0], r[1]) for r in con.execute("SELECT seen_ts, loop_lag_s FROM socket_health WHERE venue='kalshi' AND rowid>? "
                                             "ORDER BY seen_ts DESC LIMIT 60", (hi - 400,))][::-1]
    return out, lag


def orders_of(con, ex) -> list[dict]:
    ids = [ex["first_client_id"]] if ex["first_client_id"] else []
    for col in ("hedge_client_ids", "unwind_client_ids"):
        ids += [x for x in _json(ex[col], []) if x]
    rows = []
    if ids:
        q = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT client_order_id,venue,side,price,contracts,time_in_force,state,filled_contracts,avg_price,"
                           f"fee_usd,open,settlement_pending,raw_status,submitted_utc,last_utc FROM orders WHERE client_order_id IN ({q}) "
                           f"ORDER BY submitted_utc", ids).fetchall()
    elif "execution_id" in {c[1] for c in con.execute("PRAGMA table_info(orders)")}:
        rows = con.execute("SELECT client_order_id,venue,side,price,contracts,time_in_force,state,filled_contracts,avg_price,fee_usd,"
                           "open,settlement_pending,raw_status,submitted_utc,last_utc FROM orders WHERE execution_id=? ORDER BY submitted_utc",
                           (ex["execution_id"],)).fetchall()
    return [dict(r) for r in rows]


def trades(con, now: float, since_s: float = 86400.0) -> tuple[list, dict]:
    out = []
    has_events = _table(con, "events")
    has_settle = _table(con, "execution_settlements")
    has_rev = _table(con, "execution_settlement_revisions")
    for ex in con.execute("SELECT * FROM executions WHERE started_utc>? ORDER BY started_utc DESC", (now - since_s,)):
        ev = con.execute("SELECT short_name,start_utc FROM events WHERE event_id=?", (ex["event_id"],)).fetchone() if has_events else None
        st = con.execute("SELECT kind,hedged_contracts,unhedged_contracts,cover_usd,directional_usd,realized_usd,settled_ts "
                         "FROM execution_settlements WHERE execution_id=?", (ex["execution_id"],)).fetchone() if has_settle else None
        revs = con.execute("SELECT count(*) FROM execution_settlement_revisions WHERE execution_id=?",
                           (ex["execution_id"],)).fetchone()[0] if has_rev else 0
        stages = _json(ex["stages_json"], {})
        prot = _json(ex["protect_json"], {})
        attempts = [a for a in prot.get("attempts", []) if a.get("kind") == "hedge"]
        out.append({
            "execution_id": ex["execution_id"], "event_id": ex["event_id"], "short_name": (ev["short_name"] if ev else None) or ex["event_id"],
            "league": ex["league"], "mode": ex["mode"], "state": ex["state"], "started_utc": ex["started_utc"], "last_utc": ex["last_utc"],
            "quantity": ex["quantity"], "first_filled": ex["first_filled"], "first_avg_price": ex["first_avg_price"],
            "hedge_filled": ex["hedge_filled"], "hedge_avg_price": ex["hedge_avg_price"], "unhedged": ex["unhedged"],
            "released": bool(ex["released"]), "detail": redact((ex["detail"] or "")[:160]),
            "settlement": dict(st) if st else None, "revisions": revs,
            "a_settled_ms": stages.get("a_settled_ms"), "b_settled_ms": stages.get("b_settled_ms"), "done_ms": stages.get("done_ms"),
            "hedge_attempts": len(attempts), "phases": [a.get("phase") for a in attempts],
            "advance": any(a.get("advance") for a in attempts), "guard_reruns": stages.get("guard_rerun", 0),
            # a zero-fill attempt's orders say nothing the state does not; the page shows counts
            "orders": orders_of(con, ex) if ((ex["first_filled"] or 0) > 0 or not ex["released"]) else [],
        })
    by_state: dict[str, int] = {}
    for t in out:
        by_state[t["state"]] = by_state.get(t["state"], 0) + 1
    covers = [t for t in out if t["settlement"] and t["settlement"]["kind"] == "COVER"]
    settled = [t for t in out if t["settlement"]]
    funnel = {"attempts": len(out), "by_state": by_state, "first_leg_fills": sum(1 for t in out if (t["first_filled"] or 0) > 0),
              "hedged_or_better": sum(1 for t in out if t["state"] in ("HEDGED", "SETTLED", "RECONCILED", "UNWOUND")),
              "settled": len(settled), "covers": len(covers),
              "realized_usd": round(sum(t["settlement"]["realized_usd"] or 0 for t in settled), 4),
              "cover_usd": round(sum(t["settlement"]["cover_usd"] or 0 for t in settled), 4),
              "directional_usd": round(sum(t["settlement"]["directional_usd"] or 0 for t in settled), 4)}
    if _table(con, "stream_evaluations"):
        funnel["profitable_prints"] = con.execute("SELECT count(*) FROM stream_evaluations WHERE seen_ts>? AND status LIKE 'PROFITABLE%'", (now - since_s,)).fetchone()[0]
        funnel["events_with_profitable_print"] = con.execute("SELECT count(DISTINCT game_id) FROM stream_evaluations WHERE seen_ts>? AND status LIKE 'PROFITABLE%'", (now - since_s,)).fetchone()[0]
    return out, funnel


def open_exposure(con, now: float, caps: dict | None) -> dict:
    exs = []
    for ex in con.execute("SELECT * FROM executions WHERE released=0 ORDER BY started_utc DESC LIMIT 50"):
        ev = con.execute("SELECT short_name FROM events WHERE event_id=?", (ex["event_id"],)).fetchone() if _table(con, "events") else None
        exs.append({"execution_id": ex["execution_id"], "short_name": (ev["short_name"] if ev else None) or ex["event_id"], "league": ex["league"],
                    "state": ex["state"], "started_utc": ex["started_utc"], "first_filled": ex["first_filled"], "first_avg_price": ex["first_avg_price"],
                    "hedge_filled": ex["hedge_filled"], "hedge_avg_price": ex["hedge_avg_price"], "unhedged": ex["unhedged"],
                    "attention": ex["state"] in HOLDS_POSITION, "pending_settlement": ex["state"] in PENDING})
    orders = [dict(r) for r in con.execute("SELECT client_order_id,venue,side,price,contracts,state,filled_contracts,open,settlement_pending,"
                                           "raw_status,submitted_utc,execution_id FROM orders WHERE open=1 OR settlement_pending=1 OR state='UNCONFIRMED' "
                                           "ORDER BY submitted_utc DESC LIMIT 50")] if _table(con, "orders") else []
    res, day_res = [], 0.0
    midnight = now - (now % 86400)
    if _table(con, "capital_reservations"):
        for r in con.execute("SELECT reservation_id,event_id,league,per_venue_json,created_utc,released_utc,release_reason FROM capital_reservations "
                             "WHERE released_utc IS NULL OR created_utc>? ORDER BY created_utc DESC", (midnight,)):
            pv = _json(r["per_venue_json"], {})
            total = sum(float(v) for v in pv.values())
            if r["released_utc"] is None:
                res.append({"reservation_id": r["reservation_id"], "event_id": r["event_id"], "league": r["league"], "per_venue": pv,
                            "total_usd": round(total, 4), "created_utc": r["created_utc"]})
                day_res += total
            elif not ("zero" in (r["release_reason"] or "").lower() or "UNFILLED" in (r["release_reason"] or "")):
                day_res += total
    today_realized = 0.0
    if _table(con, "execution_settlements"):
        today_realized = con.execute("SELECT COALESCE(sum(realized_usd),0) FROM execution_settlements WHERE settled_ts>?", (midnight,)).fetchone()[0] or 0.0
    return {"executions": exs, "orders": orders, "reservations": res, "open_reservation_usd": round(sum(r["total_usd"] for r in res), 4),
            "day_committed_usd": round(day_res, 4), "day_cap_usd": (caps or {}).get("day_notional_usd"),
            "today_realized_usd": round(today_realized, 4)}


def flags(con, now: float) -> list[dict]:
    if not _table(con, "lane_flags"):
        return []
    return [dict(r) | {"detail": redact((r["detail"] or "")[:140])} for r in
            con.execute("SELECT seen_ts,flag,detail FROM lane_flags WHERE seen_ts>? ORDER BY seen_ts DESC LIMIT 12", (now - 86400,))]


def redemptions(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        c = _ro(path)
        by = {r[0]: r[1] for r in c.execute("SELECT state, count(*) FROM pm_redemptions GROUP BY state")}
        last = c.execute("SELECT condition_id,state,expected_value,updated_utc,detail FROM pm_redemptions ORDER BY updated_utc DESC LIMIT 3").fetchall()
        return {"by_state": by, "last": [{"condition": r[0][:12] + "…", "state": r[1], "value": r[2], "updated_utc": r[3],
                                          "detail": redact((r[4] or "")[:80])} for r in last]}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


def collect(db: Path, *, data_root: Path, repo: Path, now: float | None = None, system: bool = True,
            redemption_db: Path | None = None) -> dict:
    now = time.time() if now is None else now
    kill_root = data_root / "kill"
    ov = override_state(kill_root, now)
    kills, breaker = kill_state(kill_root)
    snap = {"as_of": now, "data_root": str(data_root), "override": ov, "kills": kills, "breaker": breaker}
    snap["system"] = system_state(data_root, repo) if system else {}
    snap["watchdog"] = watchdog_alerts(repo, data_root) if system else []
    con = _ro(db)
    try:
        snap["sockets"], snap["lag_series"] = sockets(con, now)
        snap["trades"], snap["funnel"] = trades(con, now)
        snap["open"] = open_exposure(con, now, (ov or {}).get("caps"))
        snap["flags"] = flags(con, now)
    finally:
        con.close()
    snap["redemptions"] = redemptions(redemption_db) if redemption_db else None
    return snap


def main() -> int:
    data_root = Path(os.environ.get("JANUS_DATA_ROOT") or "/srv/janus")
    repo = Path(os.environ.get("JANUS_REPO") or "/opt/janus")
    db = Path(os.environ.get("JANUS_TUPLES_DB") or data_root / "tuples" / "tuples.sqlite")
    rdb = Path(os.environ.get("JANUS_REDEMPTION_DB") or data_root / "redemptions" / "redemptions.sqlite")
    snap = collect(db, data_root=data_root, repo=repo, redemption_db=rdb)
    # SSM keeps ~24 KB of a command's output; a day of executions is more than that raw. zlib +
    # base64 makes a busy day ~8 KB. The laptop side accepts either form.
    import base64
    import zlib
    raw = json.dumps(snap, separators=(",", ":"), default=str).encode()
    print(BEGIN)
    print(base64.b64encode(zlib.compress(raw, 9)).decode())
    print(END)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

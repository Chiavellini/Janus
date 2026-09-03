#!/usr/bin/env python3
"""Append-only run index: the one place that knows whether a job is alive.

WHY THIS EXISTS
───────────────
com.janus.convergence crash-looped every 30 seconds from 2026-08-20 to 2026-09-02 -- 15,207
identical tracebacks, 11.9 MB of unrotated stderr -- and nothing noticed for thirteen days. There
was no surface that answered "when did this job last succeed?". `launchctl list` showed an exit
status but no history; the log was write-only; and the collector's own artifacts are overwritten
in place, so a stale success is indistinguishable from a fresh one.

THE START ROW IS THE POINT. It is written by the shell wrapper BEFORE the interpreter is invoked,
so a crash at import, argparse, or config time -- exactly what convergence was doing -- still
leaves a durable trace. A job that has a `started` row and no matching `finished` row is the
signature of a hard crash, and it is what ops/watchdog.py alerts on. A design that only logged
completions could never have seen this failure at all.

Rows are append-only and immutable, like snooping_ledger.md. Corrections are new rows.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.redact import redact_argv  # noqa: E402

#: Never the root disk. /Volumes/Kilos has 678 GB free; / has ~10 GB and is 91% full.
INDEX = Path("/Volumes/Kilos/janus/runs/index.jsonl")

TERMINAL = {"OK", "DEGRADED", "FAILED"}


def _append(path: Path, row: dict) -> None:
    """One line, one row. O_APPEND makes concurrent single-line writes atomic, which matters
    because several collectors share this file and launchd may restart one mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def start(job: str, *, index: Path = INDEX, argv: list[str] | None = None) -> str:
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{job}_{os.getpid()}"
    _append(index, {"ts": round(time.time(), 3), "job": job, "run_id": run_id,
                    "status": "started", "pid": os.getpid(), "host": socket.gethostname(),
                    "argv": redact_argv(argv)})
    return run_id


def finish(job: str, run_id: str, *, exit_code: int, status: str | None = None,
           index: Path = INDEX, **extra) -> str:
    st = status or ("OK" if exit_code == 0 else "FAILED")
    _append(index, {"ts": round(time.time(), 3), "job": job, "run_id": run_id,
                    "status": st, "exit": exit_code, **extra})
    return st


def last_per_job(index: Path = INDEX) -> dict[str, dict]:
    """Reduce the log to the newest row per job. A malformed line is skipped, never fatal --
    this file is read by the watchdog, and a watchdog that dies on bad input is worse than none."""
    out: dict[str, dict] = {}
    if not index.exists():
        return out
    for line in index.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        job = row.get("job")
        if not job:
            continue
        prev = out.get(job)
        if prev is None or row.get("ts", 0) >= prev.get("ts", 0):
            out[job] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("job"); s.add_argument("rest", nargs="*")
    f = sub.add_parser("finish")
    f.add_argument("job"); f.add_argument("run_id")
    f.add_argument("--exit", type=int, required=True)
    f.add_argument("--status", choices=sorted(TERMINAL))
    t = sub.add_parser("tail"); t.add_argument("-n", type=int, default=20)
    sub.add_parser("selftest")
    a = ap.parse_args()

    if a.cmd == "start":
        print(start(a.job, argv=a.rest))
    elif a.cmd == "finish":
        print(finish(a.job, a.run_id, exit_code=a.exit, status=a.status))
    elif a.cmd == "tail":
        rows = INDEX.read_text(errors="replace").splitlines()[-a.n:] if INDEX.exists() else []
        for r in rows:
            print(r)
    elif a.cmd == "selftest":
        selftest()
    return 0


def selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        idx = Path(d) / "index.jsonl"
        rid = start("demo", index=idx, argv=["--once"])
        assert last_per_job(idx)["demo"]["status"] == "started"
        finish("demo", rid, exit_code=0, index=idx)
        assert last_per_job(idx)["demo"]["status"] == "OK"
        finish("demo", rid, exit_code=3, index=idx)
        assert last_per_job(idx)["demo"]["status"] == "FAILED"
        # a corrupt line must not kill a reader
        with idx.open("a") as fh:
            fh.write("{not json\n")
        assert last_per_job(idx)["demo"]["status"] == "FAILED"
        # append-only: nothing is ever rewritten
        assert len(idx.read_text().splitlines()) == 4
    print("run_index selftest OK")


if __name__ == "__main__":
    raise SystemExit(main())

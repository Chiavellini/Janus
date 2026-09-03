#!/usr/bin/env python3
"""The latency row (ledger L34): the same measurement on the Mac and on the box, compared on paper.

    python3 ops/box/latency.py --host mac --samples 100 --out research/infra/2026-09-03_ashburn-latency/results_mac_<ts>.json

Per venue host: TCP connect, TLS handshake, and first byte of one small GET, from a fresh
connection every sample, at a steady cadence, plus Cloudflare's answer to clob.polymarket.com
(the status code -- a 403 from a datacenter address is a finding, not noise). Reports p50/p90/p95
per stage. Reads no prices, no outcomes.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

HOSTS = {
    "kalshi": ("api.elections.kalshi.com", "/trade-api/v2/exchange/status"),
    "polymarket_clob": ("clob.polymarket.com", "/time"),
    "polymarket_gamma": ("gamma-api.polymarket.com", "/sports"),
}
UA = "janus/1.0 (+python-urllib)"


def one(host: str, path: str, timeout: float = 10.0) -> dict:
    t0 = time.perf_counter()
    s = socket.create_connection((host, 443), timeout=timeout)
    t1 = time.perf_counter()
    ctx = ssl.create_default_context()
    ss = ctx.wrap_socket(s, server_hostname=host)
    t2 = time.perf_counter()
    ss.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {UA}\r\nAccept: application/json\r\nConnection: close\r\n\r\n".encode())
    first = ss.recv(64)
    t3 = time.perf_counter()
    ss.close()
    status = int(first.split(b" ")[1]) if first.startswith(b"HTTP/") and len(first.split(b" ")) > 1 else None
    return {"connect_ms": (t1 - t0) * 1000, "tls_ms": (t2 - t1) * 1000, "first_byte_ms": (t3 - t2) * 1000,
            "total_ms": (t3 - t0) * 1000, "status": status}


def quantiles(xs: list[float]) -> dict:
    if not xs:
        return {}
    xs = sorted(xs)
    q = statistics.quantiles(xs, n=100) if len(xs) >= 2 else [xs[0]] * 99
    return {"n": len(xs), "p50": round(q[49], 2), "p90": round(q[89], 2), "p95": round(q[94], 2),
            "min": round(xs[0], 2), "max": round(xs[-1], 2)}


def summarize(samples: dict[str, list[dict]]) -> dict:
    out = {}
    for venue, rows in samples.items():
        ok = [r for r in rows if "error" not in r]
        out[venue] = {stage: quantiles([r[stage] for r in ok]) for stage in ("connect_ms", "tls_ms", "first_byte_ms", "total_ms")}
        out[venue]["statuses"] = {str(s): sum(1 for r in ok if r["status"] == s) for s in sorted({r["status"] for r in ok}, key=str)}
        out[venue]["errors"] = len(rows) - len(ok)
    return out


def run(samples: int, cadence_s: float, log=print) -> dict:
    data: dict[str, list[dict]] = {v: [] for v in HOSTS}
    for i in range(samples):
        for venue, (host, path) in HOSTS.items():
            try:
                data[venue].append(one(host, path))
            except Exception as exc:  # noqa: BLE001
                data[venue].append({"error": type(exc).__name__})
        if i % 10 == 9:
            log(f"  {i + 1}/{samples}")
        time.sleep(cadence_s)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True, help="a label for where this runs: mac | box")
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--cadence", type=float, default=1.0, help="seconds between rounds")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    started = datetime.now(timezone.utc)
    data = run(a.samples, a.cadence)
    res = {"host": a.host, "started_utc": started.isoformat(), "finished_utc": datetime.now(timezone.utc).isoformat(),
           "samples": a.samples, "cadence_s": a.cadence, "hosts": {k: v[0] for k, v in HOSTS.items()},
           "summary": summarize(data), "raw": data}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1) + "\n")
    for venue, s in res["summary"].items():
        print(f"{a.host:4s} {venue:17s} total p50 {s['total_ms'].get('p50')} p95 {s['total_ms'].get('p95')} ms | "
              f"connect p50 {s['connect_ms'].get('p50')} | tls p50 {s['tls_ms'].get('p50')} | statuses {s['statuses']} errors {s['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

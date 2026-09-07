#!/usr/bin/env python3
"""The cross-host kill. The box's kill files under /srv/janus/kill are local (kernel/paths); until
2026-09-07 `kill/all` on the Mac stopped nothing on the box, and stopping the box meant a session
or `aws ec2 stop-instances`. Now two SSM parameters are the shared switch:

    /janus/kill/all      every mode that sends or simulates an order
    /janus/kill/live     LIMITED_LIVE and PRODUCTION

The Mac sets or clears them with ops/box/kill.sh; this script, run by the box's watchdog job
every five minutes (ops/run_watchdog.sh, JANUS_HOST=box), mirrors them into the local files
nodes/risk/kill.py reads per clearance:

  parameter present, value not "0"  -> latch the local file with reason "ssm: ..." (if absent)
  parameter absent or "0"           -> remove the local file ONLY if its reason starts "ssm"

A file latched locally -- by the breaker, or a human's `touch` -- is never removed from here: a
kill that a remote parameter could lift is not a kill. Nothing here prints a secret; the values
are the Mac's own stamp. Refuses to run off the box.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from nodes.risk.kill import KillSwitches  # noqa: E402

PARAMETERS: dict[str, str] = {"all": "/janus/kill/all", "live": "/janus/kill/live"}
REGION = os.environ.get("JANUS_BOX_REGION", "us-east-1")   # written into /etc/janus.env by user-data.sh


def read_parameters(ssm, names: Mapping[str, str] = PARAMETERS) -> dict[str, str | None]:
    """switch name -> the parameter's value, or None when it does not exist."""
    out: dict[str, str | None] = {}
    for switch, name in names.items():
        try:
            out[switch] = str(ssm.get_parameter(Name=name)["Parameter"]["Value"])
        except Exception as exc:  # noqa: BLE001 -- boto3's ParameterNotFound is built per client
            if type(exc).__name__ != "ParameterNotFound":
                raise
            out[switch] = None
    return out


def _latched_by_ssm(path: Path) -> bool:
    try:
        return str(json.loads(path.read_text() or "{}").get("reason", "")).startswith("ssm")
    except (OSError, ValueError):
        return False          # unreadable: assume a human's; never remove it


def sync(values: Mapping[str, str | None], kill: KillSwitches) -> list[str]:
    """Mirror the parameters into the kill directory. Returns what changed, for the log."""
    actions: list[str] = []
    for switch, value in values.items():
        path = kill.root / switch
        wanted = value is not None and value.strip() != "0"
        if wanted:
            if path.exists():
                continue                                   # already latched, by us or by someone here
            kill.latch(switch, reason=f"ssm: {value.strip()[:120]}")
            actions.append(f"latched {switch} (ssm)")
        elif path.exists() and _latched_by_ssm(path):
            path.unlink()
            actions.append(f"released {switch} (ssm parameter cleared)")
    return actions


def main(argv: list[str] | None = None, *, client_factory=None, env: Mapping[str, str] | None = None,
         kill: KillSwitches | None = None) -> int:
    env = os.environ if env is None else env
    if env.get("JANUS_HOST") != "box":
        print("kill_sync: not the box (JANUS_HOST != box); nothing to mirror")
        return 0
    try:
        if client_factory is None:
            import boto3  # type: ignore

            def client_factory():
                return boto3.client("ssm", region_name=REGION)
        values = read_parameters(client_factory())
        actions = sync(values, kill if kill is not None else KillSwitches())
    except Exception as exc:  # noqa: BLE001 -- the watchdog job must report, never crash
        print(f"kill_sync FAILED: {type(exc).__name__}: {exc}")
        return 1
    state = " ".join(f"{k}={'set' if v is not None and v.strip() != '0' else 'clear'}" for k, v in sorted(values.items()))
    print(f"kill_sync: {state}" + (f"; {', '.join(actions)}" if actions else "; no change"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

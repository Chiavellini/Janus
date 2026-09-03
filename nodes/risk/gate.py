#!/usr/bin/env python3
"""The mode gate: what a process is allowed to do is decided ONCE, at start, and never escalates.

Inputs are the operator's `--mode`, the environment, the kill switches, which credentials are
present, and -- for any mode that risks capital -- the signed arming override (GATE_TO_LIVE step
9: verbatim operator statement, sha pins of the runner and the limits, hard caps, an expiry).
Any inconsistency refuses to start. A `LIVE=1` in the environment of a non-live mode refuses to
start too (GATE step 7): the shadow arm must be STRUCTURALLY unable to post.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from kernel.schema import Mode
from nodes.risk.kill import KillSwitches
from nodes.risk.limits import RiskLimits

OVERRIDE_PATH = Path("/Volumes/Kilos/janus/kill/arming_override.json")


@dataclass(frozen=True)
class Refused:
    code: str
    detail: str


@dataclass(frozen=True)
class Resolved:
    mode: Mode
    caps: Mapping[str, float]           # from the override for live modes; {} otherwise
    override_sha: str | None


def _read_override(path: Path) -> dict | Refused:
    if not path.exists():
        return Refused("NO_OVERRIDE", f"{path} does not exist; arming is a separate, signed, human decision")
    try:
        d = json.loads(path.read_text())
    except ValueError as exc:
        return Refused("OVERRIDE_UNREADABLE", f"{type(exc).__name__}")
    for key in ("operator_statement", "mode", "runner_sha", "limits_sha", "caps", "expires_utc", "signed_by"):
        if key not in d:
            return Refused("OVERRIDE_INCOMPLETE", f"missing {key!r}")
    return d


def resolve_mode(requested: str, *, env: Mapping[str, str], kill: KillSwitches, limits: RiskLimits,
                 runner_sha: str, credentials_present: Mapping[str, bool],
                 override_path: Path | str = OVERRIDE_PATH, now: float | None = None) -> Resolved | Refused:
    try:
        mode = Mode(requested)
    except ValueError:
        return Refused("UNKNOWN_MODE", f"{requested!r} is not one of {[m.value for m in Mode]}")
    live_env = env.get("LIVE") or env.get("JANUS_LIVE")
    if live_env and not mode.risks_capital:
        return Refused("LIVE_IN_NON_LIVE_MODE",
                       f"LIVE={live_env!r} is set but the mode is {mode.value}; the shadow arm must be "
                       "structurally unable to post -- unset it")
    if mode.rank >= Mode.PAPER_EXECUTION.rank and kill.active():
        return Refused("KILL_ALL", "the `all` switch is present")
    if mode.risks_capital and kill.active(live=True):
        return Refused("KILL_LIVE", "the `live` switch is present (latched by the breaker or a human)")
    if mode.sends_real_orders:
        missing = [v for v, ok in credentials_present.items() if not ok]
        if missing:
            return Refused("CREDENTIALS", f"no credentials for {missing}")
    if not mode.risks_capital:
        return Resolved(mode, {}, None)
    d = _read_override(Path(override_path))
    if isinstance(d, Refused):
        return d
    if d["mode"] != mode.value:
        return Refused("OVERRIDE_MODE", f"override authorises {d['mode']!r}, requested {mode.value!r}")
    if d["runner_sha"] != runner_sha:
        return Refused("OVERRIDE_RUNNER_SHA", f"override pins runner {d['runner_sha']!r}, running {runner_sha!r}")
    if d["limits_sha"] != limits.sha:
        return Refused("OVERRIDE_LIMITS_SHA", f"override pins limits {d['limits_sha']!r}, loaded {limits.sha!r}")
    exp = datetime.fromisoformat(str(d["expires_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    t = now if now is not None else datetime.now(timezone.utc).timestamp()
    if t >= exp:
        return Refused("OVERRIDE_EXPIRED", f"override expired at {d['expires_utc']}")
    caps = {k: float(v) for k, v in dict(d["caps"]).items()}
    if not caps or any(v <= 0 for v in caps.values()):
        return Refused("OVERRIDE_CAPS", "caps must be present and positive")
    if not str(d["operator_statement"]).strip() or not str(d["signed_by"]).strip():
        return Refused("OVERRIDE_UNSIGNED", "operator_statement and signed_by must be non-empty")
    import hashlib
    return Resolved(mode, caps, hashlib.sha256(Path(override_path).read_bytes()).hexdigest()[:16])

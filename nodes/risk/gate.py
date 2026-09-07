#!/usr/bin/env python3
"""The mode gate: what a process is allowed to do is decided ONCE, at start, and never escalates.

Inputs are the operator's `--mode`, the environment, the kill switches, which credentials are
present, and -- for any mode that risks capital -- the signed arming override (GATE_TO_LIVE step
9: verbatim operator statement, sha pins of the code tree and the limits, hard caps, an expiry).
Any inconsistency refuses to start. A `LIVE=1` in the environment of a non-live mode refuses to
start too (GATE step 7): the shadow arm must be STRUCTURALLY unable to post.

Since 2026-09-07 the override pins `code_sha` (kernel/code_sha: nodes, grids, kernel, the runner,
the box units) rather than the whole checkout's HEAD; `runner_sha` is still written and logged,
for the record, and is no longer compared. The lane re-reads the override on every report tick
through `override_state()` and refuses real orders when it has expired or stopped matching.
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

from kernel.paths import OVERRIDE_PATH  # noqa: E402,F401


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
    for key in ("operator_statement", "mode", "runner_sha", "code_sha", "limits_sha", "caps", "expires_utc", "signed_by"):
        if key not in d:
            # An override written before 2026-09-07 has no code_sha: an old file, never a match.
            return Refused("OVERRIDE_INCOMPLETE", f"missing {key!r}")
    return d


def _expiry_ts(d: Mapping) -> float:
    return datetime.fromisoformat(str(d["expires_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def override_state(path: Path | str, *, code_sha: str, limits_sha: str, now: float | None = None) -> dict:
    """What the override says right now, for the lane's report tick and the watchdog. Pure: reads
    one file, never raises. `present` is False for a missing, unreadable or incomplete file;
    `mode` is the override's own claim, or None."""
    t = now if now is not None else datetime.now(timezone.utc).timestamp()
    out = {"present": False, "expires_utc": None, "seconds_left": None,
           "code_matches": False, "limits_matches": False, "mode": None}
    d = _read_override(Path(path))
    if isinstance(d, Refused):
        return out
    try:
        exp = _expiry_ts(d)
    except (ValueError, TypeError):
        return out
    out.update(present=True, expires_utc=str(d["expires_utc"]), seconds_left=exp - t,
               code_matches=(str(d["code_sha"]) == code_sha), limits_matches=(str(d["limits_sha"]) == limits_sha),
               mode=str(d["mode"]))
    return out


def stale_reason(state: Mapping, *, code_sha: str, limits_sha: str) -> str | None:
    """None while an `override_state()` still authorises real orders; otherwise why it does not,
    in the words the lane prints and the watchdog reports."""
    if not state.get("present"):
        return "override missing or incomplete"
    if (state.get("seconds_left") or 0.0) <= 0.0:
        return f"override expired at {state.get('expires_utc')}"
    if not state.get("code_matches"):
        return f"override pins a different code tree (running {code_sha})"
    if not state.get("limits_matches"):
        return f"override pins different limits (loaded {limits_sha})"
    return None


def resolve_mode(requested: str, *, env: Mapping[str, str], kill: KillSwitches, limits: RiskLimits,
                 runner_sha: str, code_sha: str, credentials_present: Mapping[str, bool],
                 override_path: Path | str = OVERRIDE_PATH, now: float | None = None) -> Resolved | Refused:
    """`runner_sha` is for the record (the caller logs it) and is no longer compared; `code_sha`
    (kernel/code_sha.code_tree_sha) is the pin."""
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
    if d["code_sha"] != code_sha:
        return Refused("OVERRIDE_CODE_SHA", f"override pins code tree {d['code_sha']!r}, running {code_sha!r} "
                                           f"(runner {str(runner_sha)[:12]!r}, for the record)")
    if d["limits_sha"] != limits.sha:
        return Refused("OVERRIDE_LIMITS_SHA", f"override pins limits {d['limits_sha']!r}, loaded {limits.sha!r}")
    exp = _expiry_ts(d)
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

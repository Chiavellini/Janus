#!/usr/bin/env python3
"""Write the arming override (GATE_TO_LIVE step 9) from the operator's own statement.

    python3 ops/arming_override.py --mode LIMITED_LIVE --signed-by "Bernardo" --stake-usd 5 \\
        --max-contracts 10 --day-notional-usd 20 --expires-hours 24 \\
        --statement "I approve one tiny Kalshi fill on the production account to reconcile fees."

The file pins the CODE TREE (kernel/code_sha: nodes, grids, kernel, the runner, the box units --
not the whole checkout, since 2026-09-07) and the limits file, so a change to either invalidates
it and a docs or research commit does not. The whole-checkout HEAD is written too, for the record.
It refuses to write from a dirty or unreadable tree, and refuses to overwrite an existing override
without --force. The statement is yours; nothing here writes one for you.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.code_sha import code_tree_sha, runner_head_sha  # noqa: E402
from nodes.risk.gate import OVERRIDE_PATH  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", required=True, choices=["LIMITED_LIVE", "PRODUCTION"])
    ap.add_argument("--statement", required=True, help="your verbatim authorisation")
    ap.add_argument("--signed-by", required=True)
    ap.add_argument("--stake-usd", type=float, required=True, help="max stake per order")
    ap.add_argument("--max-contracts", type=float, default=10.0)
    ap.add_argument("--day-notional-usd", type=float, required=True)
    ap.add_argument("--expires-hours", type=float, default=24.0)
    ap.add_argument("--path", type=Path, default=OVERRIDE_PATH)
    ap.add_argument("--root", type=Path, default=ROOT, help="the checkout whose code tree is pinned (default: this one)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--experiment", choices=["F22"], help="explicitly authorize a preregistered live experiment")
    ap.add_argument("--experiment-spec", type=Path, help="repo-relative immutable experiment spec to pin")
    ap.add_argument("--assignment-algorithm", help="versioned assignment algorithm to pin")
    a = ap.parse_args()
    if not a.statement.strip() or not a.signed_by.strip():
        print("the statement and the signer must be non-empty", file=sys.stderr)
        return 2
    if a.path.exists() and not a.force:
        print(f"{a.path} exists; pass --force to replace it", file=sys.stderr)
        return 2
    code_sha = code_tree_sha(a.root)
    if code_sha in ("dirty", "unknown"):
        print(f"refusing to pin a {code_sha} code tree at {a.root}: commit (or discard) every change under "
              "nodes/, grids/, kernel/, ops/run_node.sh and ops/box/systemd first", file=sys.stderr)
        return 2
    sha = runner_head_sha(a.root)
    limits = load_limits()
    d = {"operator_statement": a.statement, "signed_by": a.signed_by, "mode": a.mode, "runner_sha": sha,
         "code_sha": code_sha, "limits_sha": limits.sha,
         "caps": {"stake_usd": a.stake_usd, "max_contracts": a.max_contracts, "day_notional_usd": a.day_notional_usd},
         "expires_utc": (datetime.now(timezone.utc) + timedelta(hours=a.expires_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "written_utc": datetime.now(timezone.utc).isoformat()}
    if a.experiment:
        if not a.experiment_spec or not a.assignment_algorithm:
            print("--experiment requires --experiment-spec and --assignment-algorithm", file=sys.stderr)
            return 2
        try:
            spec = (a.root / a.experiment_spec).resolve(strict=True)
            spec.relative_to(a.root.resolve())
        except (OSError, ValueError) as exc:
            print(f"experiment spec must be a readable file inside the checkout: {exc}", file=sys.stderr)
            return 2
        d["experiment"] = {"row_id": a.experiment, "spec_path": a.experiment_spec.as_posix(),
                           "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
                           "assignment_algorithm": a.assignment_algorithm}
    a.path.parent.mkdir(parents=True, exist_ok=True)
    a.path.write_text(json.dumps(d, indent=2) + "\n")
    a.path.chmod(0o600)
    print(f"wrote {a.path}\n  mode {a.mode}, code {code_sha} (runner {sha[:12]}, for the record), limits {limits.sha}, "
          f"caps {d['caps']}, expires {d['expires_utc']}")
    print(f"  sha256 {hashlib.sha256(a.path.read_bytes()).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

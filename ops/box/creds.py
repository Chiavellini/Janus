#!/usr/bin/env python3
"""Materialise the box's credentials from SSM Parameter Store into tmpfs, at boot, and nowhere else.

    python3 ops/box/creds.py --into /run/janus            # the systemd oneshot (root, then chown)
    python3 ops/box/creds.py --into /run/janus --dry-run  # names only, nothing fetched

CUSTODY. Every secret is an SSM SecureString under /janus/ (KMS-encrypted at rest; the janus-box
role may GetParameter with decryption and nothing else). This script writes them into a tmpfs
directory (mode 700; files mode 600; gone at reboot) and an env file the lane sources through
JANUS_CREDS. The Polymarket wallet key -- the one that moves funds -- goes into its own file named
by JANUS_PM_WALLET_KEY_PATH, as on the Mac (nodes/exec_polymarket/README.md: never on EC2 without
KMS; this is KMS-encrypted custody with the key in process memory, not HSM signing).

Nothing here prints a value. A missing parameter is reported by NAME and the lane refuses to
start, which is the same shape as a missing file on the Mac.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

#: SSM name -> (destination file under --into, or None for an env value), env variable name.
LAYOUT = {
    "/janus/kalshi/api_key": (None, "JANUS_KALSHI_API_KEY"),
    "/janus/kalshi/private_key": ("kalshi_private_key.pem", "JANUS_KALSHI_PRIVATE_KEY_PATH"),
    "/janus/polymarket/wallet_key": ("pm_wallet.key", "JANUS_PM_WALLET_KEY_PATH"),
    "/janus/polymarket/funder": (None, "JANUS_PM_FUNDER"),
    "/janus/polymarket/signature_type": (None, "JANUS_PM_SIGNATURE_TYPE"),
}
OPTIONAL = {"/janus/polymarket/wallet_key", "/janus/polymarket/funder", "/janus/polymarket/signature_type"}


def fetch(names, *, region: str = "us-east-1") -> dict[str, str]:
    """Names -> values, decrypted. boto3 is imported here so the tests never need it."""
    import boto3  # type: ignore
    ssm = boto3.client("ssm", region_name=region)
    out: dict[str, str] = {}
    for i in range(0, len(names), 10):
        r = ssm.get_parameters(Names=names[i:i + 10], WithDecryption=True)
        for p in r.get("Parameters", []):
            out[p["Name"]] = p["Value"]
    return out


def materialise(values: dict[str, str], into: Path, *, layout=LAYOUT, optional=OPTIONAL) -> tuple[Path, list[str]]:
    """Write files and the env file under `into`; return (env file, missing names). Never logs a value."""
    into.mkdir(parents=True, exist_ok=True)
    os.chmod(into, 0o700)
    env_lines, missing = [], []
    for name, (filename, var) in layout.items():
        if name not in values or not str(values[name]).strip():
            if name not in optional:
                missing.append(name)
            continue
        if filename:
            p = into / filename
            p.write_text(values[name].strip() + "\n")
            os.chmod(p, 0o600)
            env_lines.append(f"{var}={p}")
        else:
            env_lines.append(f"{var}={values[name].strip()}")
    env = into / "janus.env"
    env.write_text("# materialised from SSM at boot; tmpfs; never copy elsewhere\n" + "\n".join(env_lines) + "\n")
    os.chmod(env, 0o600)
    return env, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--into", type=Path, default=Path("/run/janus"))
    ap.add_argument("--region", default=os.environ.get("JANUS_BOX_REGION", "us-east-1"))
    ap.add_argument("--dry-run", action="store_true", help="print the parameter names and destinations; fetch nothing")
    a = ap.parse_args()
    if a.dry_run:
        for name, (filename, var) in LAYOUT.items():
            print(f"{name:36s} -> {var}" + (f" (file {a.into / filename})" if filename else "") + ("  [optional]" if name in OPTIONAL else ""))
        return 0
    values = fetch(list(LAYOUT), region=a.region)
    env, missing = materialise(values, a.into)
    if missing:
        print("missing SSM parameters (by name; the lane will refuse to start): " + ", ".join(missing), file=sys.stderr)
        return 2
    print(f"credentials materialised under {a.into} (env file {env}); {len(values)} parameters, none printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

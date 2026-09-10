#!/usr/bin/env python3
"""Provision one Polymarket builder credential into SSM without ever printing a secret.

The box role is read-only.  The operator runs this locally as part of release.sh, using the same
AWS authority that already writes the code pointer and arming override.  Existing complete
credentials are left unchanged; a partial set is a hard stop rather than an implicit rotation.
"""
from __future__ import annotations

import argparse
import os


BUILDER_NAMES = {
    "key": "/janus/polymarket/builder_api_key",
    "secret": "/janus/polymarket/builder_secret",
    "passphrase": "/janus/polymarket/builder_passphrase",
}
SOURCE_NAMES = (
    "/janus/polymarket/wallet_key",
    "/janus/polymarket/funder",
    "/janus/polymarket/signature_type",
)


def get_values(ssm, names) -> dict[str, str]:
    response = ssm.get_parameters(Names=list(names), WithDecryption=True)
    return {row["Name"]: str(row["Value"]) for row in response.get("Parameters", [])}


def credential_fields(value) -> dict[str, str]:
    """Normalize the V2 client's response, which is a dict in 1.1.0."""
    if isinstance(value, dict):
        raw = value
    else:
        raw = {name: getattr(value, name, None) for name in ("key", "secret", "passphrase")}
    aliases = {"key": ("key", "apiKey", "api_key"), "secret": ("secret",),
               "passphrase": ("passphrase",)}
    out = {}
    for field, candidates in aliases.items():
        found = next((raw.get(name) for name in candidates if raw.get(name)), None)
        if not found:
            raise RuntimeError(f"Polymarket returned an incomplete builder credential ({field} missing)")
        out[field] = str(found)
    return out


def provision(*, ssm, make_client) -> str:
    present = get_values(ssm, BUILDER_NAMES.values())
    have = {field for field, name in BUILDER_NAMES.items() if present.get(name, "").strip()}
    if have == set(BUILDER_NAMES):
        return "already configured"
    if have:
        raise RuntimeError("partial Polymarket builder credential in SSM; refusing implicit rotation")

    source = get_values(ssm, SOURCE_NAMES)
    missing = [name for name in SOURCE_NAMES if not source.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing source credential(s): " + ", ".join(missing))
    client = make_client(source)
    client.set_api_creds(client.create_or_derive_api_key())
    fields = credential_fields(client.create_builder_api_key())
    for field, name in BUILDER_NAMES.items():
        ssm.put_parameter(Name=name, Type="SecureString", Value=fields[field], Overwrite=False)
    return "created and stored"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default=os.environ.get("JANUS_BOX_REGION", "mx-central-1"))
    args = ap.parse_args()
    import boto3  # type: ignore
    from py_clob_client_v2.client import ClobClient

    ssm = boto3.client("ssm", region_name=args.region)

    def make_client(source):
        return ClobClient("https://clob.polymarket.com", 137,
                          key=source[SOURCE_NAMES[0]].strip(),
                          signature_type=int(source[SOURCE_NAMES[2]]),
                          funder=source[SOURCE_NAMES[1]].strip())

    result = provision(ssm=ssm, make_client=make_client)
    print(f"Polymarket redemption builder credential: {result} (values not printed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Put the Polymarket signing key into its 600-mode file, safely.

    python3 ops/set_pm_key.py                  # hidden prompt
    python3 ops/set_pm_key.py --from-clipboard # reads the key from the clipboard, then clears it

Prompts for the key without echoing it, accepts only a 64-hex private key (with or without 0x),
writes /Volumes/Kilos/janus/credentials/pm_wallet.key (mode 600, replacing the old file only
after the new key validates), and prints the ADDRESS it controls -- never the key. Exists because
on 2026-09-07 a `pbpaste > pm_wallet.key` wrote clipboard text over a valid key.
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.paths import CREDENTIALS  # noqa: E402

DEST = CREDENTIALS / "pm_wallet.key"


def main() -> int:
    if "--from-clipboard" in sys.argv:
        # The key is read straight from the macOS clipboard, validated, and the clipboard is then
        # cleared. Nothing is typed, echoed or printed.
        import subprocess
        raw = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["pbcopy"], input="", text=True)
    else:
        raw = getpass.getpass("Polymarket private key (hidden; 64 hex chars, 0x optional): ").strip()
    if not re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", raw):
        print(f"refused: that is {len(raw)} characters and not a 64-hex private key; nothing written", file=sys.stderr)
        return 2
    key = raw if raw.startswith("0x") else "0x" + raw
    from eth_account import Account
    addr = Account.from_key(key).address
    tmp = DEST.with_suffix(".key.new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key + "\n")
    os.replace(tmp, DEST)
    os.chmod(DEST, 0o600)
    print(f"wrote {DEST} (mode 600). This key controls address {addr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

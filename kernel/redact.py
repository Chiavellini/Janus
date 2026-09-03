#!/usr/bin/env python3
"""Credential hygiene at the two places a secret can leak without anyone typing it.

Credentials arrive through the environment (`JANUS_CREDS`, sourced by ops/run_node.sh) and are
sent in headers, so nothing puts one in a URL or a cache key. Two channels remain open:

1. argv. `ops/run_index.py` persists a job's argv verbatim into the append-only run index, and
   the index is forever. No flag carries a secret today; `redact_argv` is what keeps a future
   `--api-key ...` from being written to disk the first time someone adds one.
2. exception text. A websockets handshake failure can echo the request, including the
   `KALSHI-ACCESS-*` headers, and the stream nodes stored `str(exc)` into a field that is printed
   on every reconnect. `brief_error` keeps the type and the first line only.

Both are pure and tiny. They are in the kernel because ops/ and nodes/ both need them.
"""

from __future__ import annotations

import re

_SENSITIVE = re.compile(r"(key|secret|token|passw|private|credential|auth)", re.IGNORECASE)
REDACTED = "<redacted>"


def redact_argv(argv: list[str] | None) -> list[str]:
    """Blank the VALUE of any flag whose name looks like it carries a secret.

    Handles `--api-key VALUE`, `--api-key=VALUE` and `-k VALUE` shapes. Flag names are kept so the
    row still says what the job was asked to do.
    """
    out: list[str] = []
    hide_next = False
    for tok in argv or []:
        if hide_next:
            out.append(REDACTED)
            hide_next = False
            continue
        if tok.startswith("-"):
            name, eq, value = tok.partition("=")
            if _SENSITIVE.search(name):
                if eq:
                    out.append(f"{name}={REDACTED}")
                else:
                    out.append(tok)
                    hide_next = True
                continue
        out.append(tok)
    return out


def brief_error(exc: BaseException, *, limit: int = 200) -> str:
    """`TypeName: first line`, capped. Never the whole message, which may quote a request."""
    first = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {first[:limit]}"

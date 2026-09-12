"""JSON decoding for the hot path (L81, 2026-09-12): orjson when the environment has it, the
standard library otherwise. Same result for the venues' frames (objects, arrays, strings, finite
numbers; orjson refuses NaN/Infinity, which no venue frame carries and which the stdlib would
decode into floats the pricing rejects anyway). Encoding stays on the standard library everywhere:
the capture format and every journal row are produced by `json.dumps` and must not drift."""
from __future__ import annotations

import json

try:  # pragma: no cover - which branch runs depends on the environment
    import orjson as _orjson

    def loads(s):
        """Decode `s` (str or bytes). Falls back to the stdlib for anything orjson refuses, so a
        frame that decodes today keeps decoding identically."""
        try:
            return _orjson.loads(s)
        except Exception:  # noqa: BLE001
            return json.loads(s)
    BACKEND = "orjson"
except ImportError:  # pragma: no cover
    loads = json.loads
    BACKEND = "json"

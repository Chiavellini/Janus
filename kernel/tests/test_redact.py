#!/usr/bin/env python3
"""The two channels a secret could leak through without anyone typing it into a URL."""
from __future__ import annotations

from kernel.redact import REDACTED, brief_error, redact_argv


def test_secret_flag_values_are_blanked_in_every_shape():
    argv = ["--leagues", "mlb", "--api-key", "sk-live-123", "--private-key-path=/tmp/k.pem",
            "-t", "tok", "--once"]
    out = redact_argv(argv)
    assert "sk-live-123" not in out and "/tmp/k.pem" not in " ".join(out)
    assert out == ["--leagues", "mlb", "--api-key", REDACTED, f"--private-key-path={REDACTED}",
                   "-t", "tok", "--once"]


def test_short_flags_are_only_redacted_when_their_name_says_so():
    """`-t tok` above stays: a one-letter flag says nothing, and blanking every value would make
    the run index useless. The rule is on the NAME, never a guess about the value."""
    assert redact_argv(["-k", "v"]) == ["-k", "v"]
    assert redact_argv(["--token", "v"]) == ["--token", REDACTED]


def test_ordinary_argv_passes_through_unchanged():
    argv = ["--leagues", "mlb,nfl", "--pre-hours", "2", "--once"]
    assert redact_argv(argv) == argv
    assert redact_argv(None) == []


def test_brief_error_keeps_type_and_first_line_only():
    exc = RuntimeError("server rejected WebSocket connection: HTTP 401\n"
                       "KALSHI-ACCESS-SIGNATURE: abcdef\nKALSHI-ACCESS-KEY: k-1")
    s = brief_error(exc)
    assert s == "RuntimeError: server rejected WebSocket connection: HTTP 401"
    assert "abcdef" not in s and "k-1" not in s


def test_brief_error_caps_a_long_first_line():
    assert len(brief_error(ValueError("x" * 1000))) <= len("ValueError: ") + 200

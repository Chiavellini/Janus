#!/usr/bin/env python3
"""The box tooling offline: credentials land in tmpfs with the right modes and never in the log;
the latency summary is arithmetic over samples."""
from __future__ import annotations

import os

from ops.box import creds, latency, provision_redemption


def test_credentials_materialise_into_600_files_and_an_env_file_without_printing(tmp_path, capsys):
    values = {"/janus/kalshi/api_key": "kal-key-123", "/janus/kalshi/private_key": "-----BEGIN RSA-----\nabc\n-----END-----",
              "/janus/polymarket/wallet_key": "0x" + "ab" * 32, "/janus/polymarket/funder": "0xF00D",
              "/janus/polymarket/signature_type": "1",
              "/janus/polymarket/builder_api_key": "builder-key",
              "/janus/polymarket/builder_secret": "builder-secret",
              "/janus/polymarket/builder_passphrase": "builder-pass"}
    into = tmp_path / "run" / "janus"
    env, missing = creds.materialise(values, into)
    assert missing == []
    assert (into.stat().st_mode & 0o777) == 0o700
    for f in ("kalshi_private_key.pem", "pm_wallet.key", "janus.env"):
        assert ((into / f).stat().st_mode & 0o777) == 0o600
    text = env.read_text()
    assert f"JANUS_KALSHI_PRIVATE_KEY_PATH={into / 'kalshi_private_key.pem'}" in text
    assert f"JANUS_PM_WALLET_KEY_PATH={into / 'pm_wallet.key'}" in text
    assert "JANUS_KALSHI_API_KEY=kal-key-123" in text and "JANUS_PM_SIGNATURE_TYPE=1" in text
    assert "JANUS_PM_BUILDER_API_KEY=builder-key" in text
    assert (into / "pm_wallet.key").read_text().strip() == "0x" + "ab" * 32
    assert "abab" not in capsys.readouterr().out


def test_a_missing_required_parameter_is_named_and_an_optional_one_is_not(tmp_path):
    env, missing = creds.materialise({"/janus/kalshi/api_key": "k"}, tmp_path / "j")
    assert missing == ["/janus/kalshi/private_key"]
    assert "JANUS_PM_WALLET_KEY_PATH" not in env.read_text()


def test_partial_builder_credential_is_not_materialised_silently(tmp_path):
    values = {"/janus/kalshi/api_key": "k", "/janus/kalshi/private_key": "pem",
              "/janus/polymarket/builder_api_key": "only-one"}
    _env, missing = creds.materialise(values, tmp_path / "j")
    assert missing == ["/janus/polymarket/builder_passphrase", "/janus/polymarket/builder_secret"]


class _Ssm:
    def __init__(self, values):
        self.values, self.puts = dict(values), []
    def get_parameters(self, *, Names, WithDecryption):
        assert WithDecryption
        return {"Parameters": [{"Name": name, "Value": self.values[name]}
                                for name in Names if name in self.values]}
    def put_parameter(self, **kwargs):
        assert kwargs["Type"] == "SecureString" and kwargs["Overwrite"] is False
        self.puts.append(kwargs)


def test_redemption_builder_provision_is_complete_and_idempotent():
    source = {name: value for name, value in zip(provision_redemption.SOURCE_NAMES,
                                                 ("wallet", "funder", "1"))}
    ssm = _Ssm(source)
    class Client:
        def create_or_derive_api_key(self): return "l2"
        def set_api_creds(self, creds): assert creds == "l2"
        def create_builder_api_key(self):
            return {"key": "key", "secret": "secret", "passphrase": "pass"}
    assert provision_redemption.provision(ssm=ssm, make_client=lambda values: Client()) == "created and stored"
    assert {row["Name"] for row in ssm.puts} == set(provision_redemption.BUILDER_NAMES.values())
    for row in ssm.puts:
        ssm.values[row["Name"]] = row["Value"]
    ssm.puts.clear()
    assert provision_redemption.provision(ssm=ssm, make_client=lambda values: None) == "already configured"
    assert not ssm.puts


def test_redemption_builder_cli_keeps_secure_value_off_argv():
    import json
    import os
    import stat
    import subprocess
    calls = []
    def runner(argv, **kwargs):
        pipe_arg = next(value for value in argv if value.startswith("file://"))
        pipe_path = pipe_arg.removeprefix("file://")
        mode = os.stat(pipe_path).st_mode
        payloads = []
        for _ in range(2):
            with open(pipe_path) as stream:
                payloads.append(stream.read())
        calls.append((argv, kwargs, mode, payloads))
        return subprocess.CompletedProcess(argv, 0, stdout='{"Version":1}', stderr="")
    ssm = provision_redemption.AwsCliSsm("mx-central-1", runner=runner)
    secret = "secret-never-in-process-list"
    ssm.put_parameter(Name="/janus/test", Type="SecureString", Value=secret, Overwrite=False)
    argv, kwargs, mode, payloads = calls[0]
    assert secret not in " ".join(argv)
    assert argv[argv.index("--region"):argv.index("--region") + 2] == ["--region", "mx-central-1"]
    assert argv[argv.index("--output"):argv.index("--output") + 2] == ["--output", "json"]
    assert stat.S_ISFIFO(mode) and stat.S_IMODE(mode) == 0o600
    assert all(json.loads(payload)["Value"] == secret for payload in payloads)
    assert kwargs["input"] is None and kwargs["capture_output"] is True
    assert not os.path.exists(next(value.removeprefix("file://") for value in argv
                                   if value.startswith("file://")))


def test_redemption_secret_pipe_gives_one_payload_per_reader_open():
    """A reader that dawdles between opening the pipe and draining it still sees one payload.

    The AWS CLI opens the FIFO, reads, closes, then opens again.  A feeder that reopens for write
    while the first reader is still attached writes into the stream that reader is draining, so it
    receives both payloads and the CLI's second read comes back empty."""
    import json
    import subprocess
    import time
    seen = {}
    def runner(argv, **kwargs):
        pipe_path = next(v.removeprefix("file://") for v in argv if v.startswith("file://"))
        with open(pipe_path) as stream:      # blocking open pairs with the feeder's first write
            time.sleep(0.05)                 # the window a reopening feeder used to write into
            seen["payload"] = stream.read()
        return subprocess.CompletedProcess(argv, 0, stdout='{"Version":1}', stderr="")
    ssm = provision_redemption.AwsCliSsm("mx-central-1", runner=runner)
    ssm.put_parameter(Name="/janus/test", Type="SecureString", Value="one-payload", Overwrite=False)
    assert json.loads(seen["payload"])["Value"] == "one-payload"


def test_redemption_builder_cli_parses_decrypted_parameter_response():
    import subprocess
    def runner(argv, **kwargs):
        assert "--with-decryption" in argv and kwargs["input"] is None
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"Parameters":[{"Name":"/janus/a","Value":"v"}]}', stderr="")
    ssm = provision_redemption.AwsCliSsm("mx-central-1", runner=runner)
    assert provision_redemption.get_values(ssm, ["/janus/a"]) == {"/janus/a": "v"}


def test_latency_summary_quantiles_and_statuses():
    rows = [{"connect_ms": i, "tls_ms": 2 * i, "first_byte_ms": 3 * i, "total_ms": 6 * i, "status": 200 if i % 5 else 403} for i in range(1, 101)]
    rows.append({"error": "timeout"})
    s = latency.summarize({"kalshi": rows})["kalshi"]
    assert s["total_ms"]["n"] == 100 and 290 <= s["total_ms"]["p50"] <= 310 and s["total_ms"]["p95"] >= 560
    assert s["statuses"] == {"200": 80, "403": 20} and s["errors"] == 1


def test_cloud_init_installs_every_interpreter_the_units_need_and_the_v2_venue_client():
    """2026-09-07: every unit ran /usr/bin/zsh and cloud-init installed no zsh (203/EXEC on first
    boot); the venv pinned the V1 Polymarket client the venue no longer accepts."""
    from pathlib import Path
    box = Path(__file__).resolve().parents[1]
    ud = (box / "user-data.sh").read_text()
    apt = next(l for l in ud.splitlines() if "apt-get install" in l)
    pip = next(l for l in ud.splitlines() if "pip\" install" in l and "--upgrade pip" not in l)
    for unit in (box / "systemd").glob("*.service"):
        for line in unit.read_text().splitlines():
            if line.startswith("ExecStart="):
                interp = line.split("=", 1)[1].split()[0]
                name = interp.rsplit("/", 1)[-1]
                if name not in ("python3", "mkdir", "chown") and not interp.startswith("/opt/janus/.venv"):
                    assert f" {name}" in apt, f"{unit.name} runs {interp} but cloud-init does not install it"
    assert "py-clob-client-v2" in pip and "py-clob-client=" not in pip and " py-clob-client " not in pip + " "
    assert "'polymarket-client==0.9.0'" in ud
    assert any("janus-pm-redeem.timer" in line for line in ud.splitlines()
               if "systemctl enable --now" in line)
    lane = (box / "systemd" / "janus-live-stream.service").read_text()
    assert "--mode PAPER_EXECUTION" in lane and "--leagues enabled" in lane


def test_release_preflight_uses_the_registered_protection_dust_threshold():
    """A fractional PM price-improvement remainder below venue minimum is not an unhedged STOP."""
    from pathlib import Path
    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    assert "load_limits().protect.protect_dust_contracts" in release
    assert "ABS(unhedged) > ?" in release


def test_partial_builder_provision_refuses_rotation():
    import pytest
    one = {provision_redemption.BUILDER_NAMES["key"]: "existing"}
    with pytest.raises(RuntimeError, match="partial"):
        provision_redemption.provision(ssm=_Ssm(one), make_client=lambda _values: None)


def test_false_latch_warms_under_kill_and_passes_epoch_through_sudo():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "clear_false_maker_latch.sh").read_text()
    assert "clear_false_maker_latch.py clear" in script and "--retain" in script
    assert 'env JANUS_CLEAR_STARTED="\\$JANUS_CLEAR_STARTED"' in script
    assert script.index("systemctl start janus-live-stream") < script.index(
        "clear_false_maker_latch.py activate")
    assert script.index("POST_START_STREAMS_GREEN") < script.index(
        "clear_false_maker_latch.py activate")
    assert script.index("PRE_CLEAR_RISK_FLAGS_QUIET") < script.index("systemctl stop janus-live-stream")
    assert "ORDER_PERSISTENCE_FAILED" in script


def test_redemption_unit_overrides_the_trading_interpreter_at_exec():
    from pathlib import Path
    unit = (Path(__file__).resolve().parents[1] / "systemd" / "janus-pm-redeem.service").read_text()
    line = next(row for row in unit.splitlines() if row.startswith("ExecStart="))
    assert "JANUS_PYTHON=/opt/janus/.redeem-venv/bin/python3" in line
    assert "/opt/janus/ops/run_node.sh pm_redeem" in line

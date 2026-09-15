#!/usr/bin/env python3
"""The box tooling offline: credentials land in tmpfs with the right modes and never in the log;
the latency summary is arithmetic over samples."""
from __future__ import annotations

import os
import re
import shlex
import subprocess

import pytest

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


def test_release_routes_only_registered_flag211_digest_to_separate_helper():
    from pathlib import Path
    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    digest = "a9613b6dff2499e3da6fe4aa2b872fa02f955aaefb043e60725f289603c249f6"
    assert digest in release
    assert "clear_legacy_incident_latch.sh" in release
    assert "clear_false_maker_latch.sh" in release
    assert release.index("case \"$LIVE_KILL_SHA\"") < release.index("clear_legacy_incident_latch.sh")


def test_release_classifies_the_three_reviewed_kill_reasons_and_rejects_unknowns():
    from pathlib import Path
    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    assert "clear_guard_failure_latch.sh" in release
    assert "dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83" in release
    assert "GUARD_FAILED" not in release.split("case \"$LIVE_KILL_REASON\"", 1)[0]
    assert "unknown or malformed live-kill reason; refusing generic clear" in release
    assert "unknown provider state:'*'post-only cancel/late-fill lifecycle unresolved:'" in release


def test_release_routes_the_exact_f22_instrumentation_stop_to_a_stopped_lane_recovery():
    from pathlib import Path
    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    helper = (Path(__file__).resolve().parents[1] / "clear_f22_instrumentation_latch.sh").read_text()
    digest = "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636"
    reason = "F22 STOP: terminal maker zero-fill fee evidence is NULL; strict report classifies persistence_or_reconciliation_failure"
    assert digest in release and digest in helper and reason in release
    assert "clear_f22_instrumentation_latch.sh" in release
    route = release[release.index("KILL_ROUTE=f22_instrumentation"):]
    assert "KILL_ROUTE=f22_instrumentation" in release
    assert "[ \"$KILL_ROUTE\" = guard ] || [ \"$KILL_ROUTE\" = f22_instrumentation ]" in release
    assert helper.index("STOPPED_EXACT_F22_INSTRUMENTATION_PROOF_OK") < helper.index("systemctl start janus-live-stream")
    assert helper.index("STOPPED_GUARD_PASS_2_OK") < helper.index("clear_f22_instrumentation_latch.py activate")
    assert "F23_AUTHORITY_REQUIRED" in helper and "F22_INSTRUMENTATION_ROLLBACK_KILL_ABSENT" in helper


def test_release_kill_reason_selector_accepts_one_line_plus_transport_blank_only():
    """AWS text output adds a newline after already newline-terminated SSM stdout (L134)."""
    from pathlib import Path

    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    start = release.index("single_nonempty_line() {")
    end = release.index("\n}", start) + 2
    function = release[start:end]
    assert "| single_nonempty_line || true" in release

    def select(payload: str):
        harness = function + "\nsingle_nonempty_line"
        return subprocess.run(("bash", "-c", harness), input=payload, text=True,
                              capture_output=True, check=False)

    expected = "guard failed: exact registered reason"
    accepted = select(expected + "\n\n")
    assert accepted.returncode == 0
    assert accepted.stdout == expected + "\n"
    for rejected in ("", "\n\n", "unreviewed prefix\n" + expected + "\n"):
        result = select(rejected)
        assert result.returncode != 0
        assert result.stdout == ""


def test_guard_recovery_route_does_not_restart_before_exact_stopped_lane_proof():
    """A generic mode restart can let the guard append a third source and invalidate L133."""
    from pathlib import Path
    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    classify = release.index('case "$LIVE_KILL_REASON" in')
    branch = release.index('if [ "$KILL_ROUTE" = guard ]', classify)
    helper = release.index('bash "$HERE/clear_guard_failure_latch.sh"', branch)
    generic = release.index('bash "$HERE/mode.sh" LIMITED_LIVE', branch)
    assert classify < branch < generic < helper
    block = release[branch:release.index('if [ "$LIVE_KILL_SHA" != none ]', branch)]
    assert 'if [ "$KILL_ROUTE" = guard ]' in block
    assert 'keep lane stopped' in block


def test_override_supports_closed_f22_and_defaults_to_exact_f23_authority():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "write_override.sh").read_text()
    assert "EXPERIMENT=${JANUS_EXPERIMENT:-F23}" in script
    assert "--experiment F22" in script and "--experiment F23" in script
    assert "--experiment-spec research/sports/2026-09-15_limited-live-f22-maker-vs-taker/spec.yaml" in script
    assert "--experiment-spec research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml" in script
    assert "--assignment-algorithm janus:f22:entry-arm:v1" in script
    assert "--assignment-algorithm janus:f23:entry-arm:v1" in script
    f23 = (Path(__file__).resolve().parents[1] / "f23_arm_statement.txt").read_text().strip()
    assert f23 == "we want to be able to prove we can or cannot reach the goal with the system as is and fix whatever is necessary to reach it."


def _f22_recovery_fixture():
    import sqlite3
    from importlib import import_module

    helper = import_module("ops.box.clear_f22_instrumentation_latch")
    con = sqlite3.connect(":memory:")
    con.executescript("""
      CREATE TABLE f22_decisions(
        id INTEGER PRIMARY KEY, event_id TEXT, forward_row_id TEXT,
        assignment_algorithm TEXT, digest TEXT, arm TEXT, sizing_input_hash TEXT,
        sizing_occurrence INTEGER, sizing_book_epoch TEXT, selected_quantity REAL, execution_id TEXT
      );
      CREATE TABLE executions(
        execution_id TEXT PRIMARY KEY, event_id TEXT, opportunity_id TEXT, state TEXT,
        first_client_id TEXT, hedge_client_ids TEXT, first_filled REAL, hedge_filled REAL,
        unhedged REAL, released INTEGER
      );
      CREATE TABLE orders(
        client_order_id TEXT, venue TEXT, venue_order_id TEXT, state TEXT,
        filled_contracts REAL, avg_price REAL, fee_usd REAL, open INTEGER, settlement_pending INTEGER,
        execution_id TEXT
      );
      CREATE TABLE capital_reservations(reservation_id TEXT, released_utc REAL);
      CREATE TABLE pm_post_only_orders(client_order_id TEXT, terminal_proved INTEGER, violated INTEGER);
      CREATE TABLE pm_post_only_admission(slot INTEGER, client_order_id TEXT);
    """)
    for row_id, expected in helper.F22_SOURCES.items():
        event, exid = expected["event_id"], expected["execution_id"]
        cid, oid = expected["first_client_id"], expected["venue_order_id"]
        con.execute("INSERT INTO f22_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (row_id, event, "F22", "janus:f22:entry-arm:v1", expected["digest"], "maker",
                     expected["sizing_input_hash"], 1, expected["sizing_book_epoch"],
                     expected["selected_quantity"], exid))
        con.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (exid, event, expected["opportunity_id"], "ORDER_UNFILLED", cid, "[]", 0.0, 0.0, 0.0, 1))
        con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (cid, "polymarket", oid, "UNFILLED", 0.0, None, None, 0, 0, exid))
        con.execute("INSERT INTO pm_post_only_orders VALUES(?,?,?)", (cid, 1, 0))
    con.execute("INSERT INTO pm_post_only_admission VALUES(1,NULL)")
    con.commit()
    return helper, con


def test_f22_recovery_proves_exact_source_execution_and_single_pm_order():
    helper, con = _f22_recovery_fixture()
    out = helper._quiet(con)
    assert out["zero_flight"] and out["zero_unhedged"]

    exid = "785f1ce65f61402c9d940e001be2f41e"
    con.execute("UPDATE executions SET event_id='wrong-event' WHERE execution_id=?", (exid,))
    try:
        helper._quiet(con)
    except RuntimeError as exc:
        assert f"source execution {exid} changed" in str(exc)
    else:
        raise AssertionError("event/execution mismatch must block exact recovery")

    helper, con = _f22_recovery_fixture()
    con.execute("UPDATE f22_decisions SET event_id='wrong-event' WHERE id=1")
    con.execute("UPDATE executions SET event_id='wrong-event' WHERE execution_id=?", (exid,))
    with pytest.raises(RuntimeError, match="source decision identity changed"):
        helper._quiet(con)


def test_f22_recovery_rejects_hedge_ids_or_extra_order_lineage():
    for mutation, expected in (
        (lambda con: con.execute("UPDATE executions SET hedge_client_ids='[\\\"hedge\\\"]' WHERE execution_id='785f1ce65f61402c9d940e001be2f41e'"),
         "source execution 785f1ce65f61402c9d940e001be2f41e changed"),
        (lambda con: con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)",
                                 ("k-one", "kalshi", "k-order-one", "UNFILLED", 0.0, None, None, 0, 0, "785f1ce65f61402c9d940e001be2f41e")),
         "source order for 785f1ce65f61402c9d940e001be2f41e"),
    ):
        helper, con = _f22_recovery_fixture()
        mutation(con)
        con.commit()
        with pytest.raises(RuntimeError, match=expected):
            helper._quiet(con)


def test_release_legacy_route_passes_an_exact_full_deployed_sha_to_the_helper():
    """The L122 route must preserve the box's full checkout SHA verbatim."""
    from pathlib import Path

    release = (Path(__file__).resolve().parents[1] / "release.sh").read_text()
    route_start = release.index('      case "$DEPLOYED_SHA" in')
    helper_call = '      bash "$HERE/clear_legacy_incident_latch.sh" "$DEPLOYED_SHA" "$LIVE_KILL_SHA"'
    route_end = release.index(helper_call, route_start) + len(helper_call)
    route = release[route_start:route_end].replace(
        'bash "$HERE/clear_legacy_incident_latch.sh"', "record_helper"
    )
    pattern = re.search(r"\n        (\[0-9a-f\].*?) ;;", route).group(1)
    assert pattern.count("[0-9a-f]") == 40

    def run(deployed_sha):
        harness = f'''\
set -eu
DEPLOYED_SHA={shlex.quote(deployed_sha)}
LIVE_KILL_SHA=kill-digest
record_helper() {{ printf 'helper:%s:%s\\n' "$1" "$2"; }}
{route}
'''
        return subprocess.run(("bash", "-c", harness), text=True, capture_output=True, check=False)

    full_sha = "0123456789abcdef" * 2 + "01234567"
    result = run(full_sha)
    assert result.returncode == 0
    assert result.stdout.strip() == f"helper:{full_sha}:kill-digest"

    for invalid in (full_sha[:20], full_sha[:-1], full_sha + "a", full_sha.upper(), full_sha[:-1] + "g"):
        result = run(invalid)
        assert result.returncode == 2
        assert "helper:" not in result.stdout


def test_legacy_clear_shell_uses_fresh_root_audit_and_complete_credentialed_guards():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "clear_legacy_incident_latch.sh").read_text()
    assert "mktemp -d" in script and "chown janus:janus" in script and "chmod 700" in script
    assert script.count("--require-complete-quiet") == 2
    assert "source /run/janus/janus.env" in script
    assert "pre_proved=0" in script and "PRE_STOP_LEGACY_211_PROOF_FAILED" in script
    assert script.index("pre_proved=0") < script.index("# Complete real two-venue guard pass")
    assert "LEGACY_211_ROLLBACK_RESTORE_FAILED" in script
    assert "LEGACY_211_ROLLBACK_STOP_FAILED" in script
    assert "LEGACY_211_ROLLBACK_KILL_ABSENT" in script
    restore_line = next(line for line in script.splitlines() if "clear_legacy_incident_latch.py restore" in line)
    assert "--archive" in restore_line and "--kill" in restore_line and "|| true" not in restore_line
    assert "rev-parse --verify HEAD" in (Path(__file__).resolve().parents[1] / "release.sh").read_text()


def test_redemption_unit_overrides_the_trading_interpreter_at_exec():
    from pathlib import Path
    unit = (Path(__file__).resolve().parents[1] / "systemd" / "janus-pm-redeem.service").read_text()
    line = next(row for row in unit.splitlines() if row.startswith("ExecStart="))
    assert "JANUS_PYTHON=/opt/janus/.redeem-venv/bin/python3" in line
    assert "/opt/janus/ops/run_node.sh pm_redeem" in line

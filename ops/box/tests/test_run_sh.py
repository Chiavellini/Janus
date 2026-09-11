import os
import subprocess
from pathlib import Path


def test_remote_failure_propagates_to_local_exit(tmp_path):
    fake = tmp_path / "aws"
    fake.write_text("""#!/bin/sh
case "$*" in
  *send-command*) echo cmd-1 ;;
  *\"--query Status\"*) echo Failed ;;
  *StandardOutputContent*) echo remote-output ;;
  *StandardErrorContent*) echo remote-error ;;
  *) exit 2 ;;
esac
""")
    fake.chmod(0o755)
    script = Path(__file__).resolve().parents[1] / "run.sh"
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    result = subprocess.run(["bash", str(script), "exit 7"], env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert "status=Failed" in result.stdout
    assert "remote-output" in result.stdout and "remote-error" in result.stdout

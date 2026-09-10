# L67 verdict — actual AWS CLI secret-pipe compatibility pass

Date: 2026-09-10

The installed AWS CLI was tested locally with a benign `put-parameter --generate-cli-skeleton
output` payload and was observed to open a named `--cli-input-json` source twice. The implemented
adapter therefore feeds the identical JSON through a short-lived mode-600 FIFO exactly twice. Only
the FIFO path enters argv; credential bytes remain in process and pipe buffers, never a regular
file, environment value, argv, stdout, stderr, or exception. The FIFO is removed after every call.

Read-only SSM inspection immediately after the failed 8f5afd4 paste found all three source fields
and zero of three builder fields. No partial credential write exists. Both failed release attempts
stopped before checkout, runtime sync, override signing, restart, kill clear, order, or redemption.

The actual installed CLI accepts the FIFO parser path in non-networking skeleton validation. Unit
tests prove FIFO type/mode, two-read delivery, cleanup and secret exclusion. The complete repository
suite passes at 100%; focused release/redemption/clear tests, Python compilation, shell syntax and
diff checks pass. F20 remains undeployed and pending.

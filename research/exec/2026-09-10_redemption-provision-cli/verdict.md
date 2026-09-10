# L66 verdict — local AWS CLI provisioning compatibility pass

Date: 2026-09-10

The first `7399498` release stopped at step zero because the operator laptop's selected `python3`
did not include `boto3`. It stopped before checkout, runtime sync, override signing, restart, kill
clear, order, or redemption.

`provision_redemption.py` now implements its minimal SSM interface through the AWS CLI already used
by the operator workflow. Decrypted reads are parsed from JSON. New SecureString payloads are
supplied through `/dev/stdin`; the secret value is absent from argv and output. The helper preserves
the original all-or-none credential rule, `Overwrite=false`, selected region, and builder-key flow.

The complete repository suite passes at 100%. Focused provisioning, redemption, release and exact
clear tests pass, as do Python compilation, shell syntax and diff checks. No external state was
changed while implementing or testing L66.

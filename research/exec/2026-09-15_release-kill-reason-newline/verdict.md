# L134 local verdict — PASS; release retry pending

Two exact release attempts stopped before provision or checkout because the SSM reason response had
one expected nonblank line followed by a transport-added blank line, while `release.sh` selected
plain `tail -1`. AWS command records independently preserved the exact expected reason and proved
that the box remained at `f7c9c1b` under the unchanged registered kill.

The release now accepts exactly one nonblank response line, preserving its bytes, and treats empty,
blank-only or multiple nonblank lines as missing evidence. Exact reason and digest classification is
unchanged. The focused release harness, all 42 box/recovery tests, Bash syntax and `git diff --check`
passed. A fresh Luna audit confirmed the root cause and returned the patch as the safest retry.

No checkout, override, mode, helper, kill, account or database mutation occurred during the failed
attempts or L134 verification.

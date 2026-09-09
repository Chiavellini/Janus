# L58 source-integrity follow-up passed

Independent review found a validation gap: iterating only discovered metadata sidecars could
leave a consumed source unverified when its sidecar was missing. `source_manifest()` now verifies
the six known root responses before deriving the exact 144 ESPN and 144 UEFA descendant IDs.
The complete source and sidecar filename sets must match those 294 expected responses exactly.
Every response requires its own correctly located nonsymlink sidecar with matching absolute path,
exact request URL, successful status, headers, timezone-bearing retrieval timestamp, byte count
and SHA256. Unknown source/sidecar files, missing responses/sidecars, duplicate identities, changed
paths, and mismatched hashes fail closed before fixture parsing.

Only the two explicitly named generated preview PNGs and content-addressed `audit-<64hex>.json`
outputs are excluded from source enumeration; they are never consumed as source evidence.

All 38 UCL-focused tests and all 160 settlement tests pass. Twelve added cases cover the complete
294-source set, missing report/source/sidecar, missing original metadata, tampering, orphan files,
duplicate-path substitution, wrong request URL/status and missing retrieval timezone. These cases
use synthetic temporary files and never modify the frozen research evidence. Targeted diff check
passes.

Command `python3 research/sports/2026-09-09_ucl-settlement-bounds/measure.py --archive` reproduces
the exact original audit SHA256
`9d711e9ef9d93ae65315e53677c558e2fb612bc42158837371375ea9cd3a3367`: 294 source records,
144 joined fixtures, zero failures, and both bounds unchanged at `0.020588792299495857`.
The existing content-addressed audit was compared byte-for-byte without rewriting it.
No network, account, live-box, order, deployment or commit action occurred in this follow-up.
The original preregistered criteria, source bytes, results and prior verdict remain unchanged.

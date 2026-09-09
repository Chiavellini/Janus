# L44 — FAIL: interrupted archive, no evidence or cap registered

The corrected replay stopped on an invalid JSON document in raw page 256. A local research
process interruption had landed during gzip JSON writing. The incomplete page, all 256 complete
pages, and `results.json` remain intact under
`/Volumes/Kilos/janus/research/L44_itf_delay/20260909T072716Z/` and this research directory.
The required complete closed/open cursor enumerations were not achieved.

The partial main-draw counts became visible in the failure output: 9,948 identified mature
singles; 158 conservatively adverse (121 HALF, 6 winners closed after fourteen days, 31 winners
closed before their original starts). These are an incomplete-catalog diagnostic, not an
admissible frequency or live-trading evidence. `registered_value` is null.

Independent review corrected three implementation defects before this result: strict rejection
of present invalid event close fields instead of market-field fallback; validation of required
fields on immature rows for the all-singles parseability gate; and actual payload closed-state
validation rather than requested-catalog state. Null event ids also fail explicitly. Twenty-seven
research regression cases pass, but passing software tests does not complete a missing catalog.

L46 must use a new, complete archive with atomic page writes. This row's criteria, raw archive,
and failure output are preserved; no ITF evidence or risk allowance is registered from it.

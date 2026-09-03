# kernel — the edges between nodes

Not a node. The kernel is the set of **contracts nodes share**: the types that travel along the
edges of the grid, the HTTP client every source uses, and the statistics primitives the gates
require. Nodes depend on the kernel. The kernel depends on nothing in `nodes/` or `grids/`.

| File | What it is |
|---|---|
| `schema.py` | `CanonicalKey`, `NormMarket`, `Book`, `Quote`, `SettleRef`, `VoidPolicy`, `TiePolicy`, `LIQUIDITY_SOURCES`. These are the edge types of the dataflow graph. |
| `fetch.py` | Per-host token-bucket rate limiter, `Retry-After` handling on 429, exponential backoff with jitter on 5xx, and a deliberately **non-retrying** `post_json_once` for trading endpoints. |
| `stats.py` | Permutation, block bootstrap, deflated Sharpe, BH-FDR. Required by the five gates in `GATE_TO_LIVE.md`. Copied from Kilos, not imported. |
| `venue_protocol.py` | The venue adapter `Protocol`. `normalize()` is declared PURE. |
| `venue_registry.py` | Adapter registry and dispatch. Kalshi, Polymarket and Cloudbet are registered. |
| `redact.py` | `redact_argv`, `brief_error` — credential hygiene at the two leak channels. |

## Invariants that live here and are not yet enforced

`schema.py` states that a `SettleRef` whose `provenance` is `"assumed"` *"makes the classifier
BLOCK, not shrug."* **There is no such classifier.** `VoidPolicy`/`TiePolicy` are populated by
`nodes/venue_cloudbet` and read by nothing. Building `nodes/settle_wedge` closes this.

`venue_protocol.py` declares `normalize()` pure. That is now enforced mechanically by the
`_no_network` autouse fixture in the repo-root `conftest.py`, not merely asserted in prose.

`fetch.py` is tested as of 2026-09-02 (`kernel/tests/test_fetch.py`: backoff, `Retry-After`,
the 422 offset-cap signal, `post_json_once` never retrying, the cache). `redact.py` holds the
two credential-hygiene helpers (argv redaction, exception brevity); `ops/run_index` and both
stream nodes use them.

#!/usr/bin/env python3
"""Stage 3b — LLM equivalence adjudication. The stage `match/block.py:7` specifies and that was
never written.

    python3 match/adjudicate.py --match-dir data/match_2026-08-20 --limit 20   # smoke
    python3 match/adjudicate.py --match-dir data/match_2026-08-20              # full run

WHY. Blocking is recall-optimised and "expected, even, to emit garbage"; the deterministic layer of
`match/verify.py` removes what STRUCTURE can remove (strike ladders, subjects, dates, qualifiers,
settlement feeds, reciprocal-best). What survives is genuinely ambiguous and can only be settled by
reading both rules texts. Measured on the 2026-08-20 non-sports corpus the deterministic layer alone
still leaves ~41% of markets carrying an implausible edge — the residual false-pair rate — which in a
small-and-diffuse-edge regime is fatal, because a real 1-2c gap and a false-pair artifact are
indistinguishable.

NO PRICES ARE READ HERE. Equivalence is a property of the two rules texts. The adjudicator never
sees a quote, a spread or an edge, so it cannot be pulled toward whichever pairing looks profitable.
This is also why the MEASUREMENT pipeline runs verify-then-screen: screening first would condition
the surviving population on the outcome being measured.

UNSURE IS A REAL VERDICT. It is never folded into either bucket. Those are the pairs that must not
be traded and must not be counted as evidence either way.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODEL = "claude-opus-5"
BATCH = 8                 # pairs per request; small enough that each still gets real attention
MAX_WORKERS = 6
MAX_RULES_CHARS = 2500    # per leg; enough for a settlement clause, bounded against a runaway doc

SYSTEM = """You adjudicate whether two prediction-market contracts, one on Kalshi and one on \
Polymarket, are THE SAME CONTRACT — meaning a trader holding one and the opposite side of the other \
is exposed to no residual risk beyond fees.

Answer EQUIVALENT only if ALL hold:
- the same underlying event and subject
- the same threshold/strike and the same direction across it
- the same resolution date/period
- settlement references that cannot disagree (same source, or sources that must produce the same \
answer). If the two contracts could resolve differently on some realisable outcome, they are NOT \
equivalent, however similar the titles.

Answer NOT_EQUIVALENT when you can name a concrete scenario where one resolves YES and the other NO.

Answer UNSURE when the supplied text is insufficient to decide. UNSURE is a real answer and is \
strongly preferred over guessing — a wrong EQUIVALENT injects a fabricated edge into a trading \
study, which is far more costly than an abstention.

Traps seen in this corpus:
- trigger-set asymmetry: Kalshi "AI / Artificial Intelligence" (either utterance) vs Polymarket \
"AI" alone. Kalshi's condition is a strict SUPERSET, so it is worth more forever with no arbitrage \
in it. NOT_EQUIVALENT.
- settlement-reference splits: Polymarket resolving crypto off a Chainlink TWAP vs Kalshi off CF \
Benchmarks BRTI. Different products. NOT_EQUIVALENT.
- ladder rungs: "at least 52" vs "at least 59" on the same index.
- same number, different subject: an "Insidious" Rotten Tomatoes threshold vs a "Mutiny" one.
- superlative vs threshold: "which scores highest" vs "will it score at least 60"."""


class Adjudication(BaseModel):
    pair_id: int = Field(description="the pair_id given in the input, echoed back")
    verdict: str = Field(description="EQUIVALENT, NOT_EQUIVALENT, or UNSURE")
    reason: str = Field(description="one sentence; if NOT_EQUIVALENT, name the divergent scenario")
    confidence: float = Field(description="0.0-1.0")


class Batch(BaseModel):
    adjudications: list[Adjudication]


def render(pair: dict, pid: int) -> str:
    def clip(s):
        return (str(s or "")[:MAX_RULES_CHARS]).strip()
    return (f"<pair id={pid}>\n"
            f"KALSHI title: {clip(pair.get('kalshi_text'))}\n"
            f"KALSHI rules: {clip(pair.get('kalshi_rules'))}\n"
            f"KALSHI settlement_sources: {clip(pair.get('kalshi_settlement_sources'))}\n"
            f"PM question: {clip(pair.get('pm_text'))}\n"
            f"PM rules: {clip(pair.get('pm_rules'))}\n"
            f"PM resolution_source: {clip(pair.get('pm_resolution_source'))}\n"
            f"</pair>")


def adjudicate_batch(client, chunk: list[tuple[int, dict]]) -> list[dict]:
    body = "\n\n".join(render(p, pid) for pid, p in chunk)
    try:
        r = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            messages=[{"role": "user",
                       "content": f"Adjudicate each pair. Return one entry per pair_id.\n\n{body}"}],
            output_format=Batch,
        )
        got = {a.pair_id: a for a in r.parsed_output.adjudications}
    except Exception as e:                                            # noqa: BLE001
        # a failed batch is UNSURE with the cause recorded -- never silently dropped, and never
        # silently accepted as equivalent
        return [{"pair_id": pid, "verdict": "UNSURE", "reason": f"ADJUDICATION_ERROR {type(e).__name__}",
                 "confidence": 0.0} for pid, _ in chunk]
    out = []
    for pid, _ in chunk:
        a = got.get(pid)
        out.append({"pair_id": pid, "verdict": a.verdict, "reason": a.reason,
                    "confidence": a.confidence} if a else
                   {"pair_id": pid, "verdict": "UNSURE", "reason": "NO_RESPONSE_FOR_PAIR",
                    "confidence": 0.0})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-dir", default="data/match_2026-08-20")
    ap.add_argument("--limit", type=int, default=None, help="smoke-test on the first N pairs")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    md = Path(a.match_dir)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2
    import anthropic
    client = anthropic.Anthropic()

    pairs = [json.loads(l) for l in (md / "undecided.jsonl").read_text().splitlines() if l.strip()]
    if a.limit:
        pairs = pairs[:a.limit]
    indexed = list(enumerate(pairs))
    chunks = [indexed[i:i + BATCH] for i in range(0, len(indexed), BATCH)]
    print(f"adjudicating {len(pairs)} pairs in {len(chunks)} batches of {BATCH} on {MODEL}")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, res in enumerate(ex.map(lambda c: adjudicate_batch(client, c), chunks), 1):
            results.extend(res)
            print(f"  batch {i}/{len(chunks)} done", flush=True)

    merged = []
    for pid, p in indexed:
        r = next((x for x in results if x["pair_id"] == pid), None) or {
            "verdict": "UNSURE", "reason": "MISSING", "confidence": 0.0}
        merged.append({**p, "adjudication": r["verdict"], "adjudication_reason": r["reason"],
                       "adjudication_confidence": r["confidence"]})

    out = Path(a.out) if a.out else md / "adjudicated.json"
    out.write_text(json.dumps(merged, indent=1))
    from collections import Counter
    c = Counter(m["adjudication"] for m in merged)
    print(f"\nverdicts: {dict(c)}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

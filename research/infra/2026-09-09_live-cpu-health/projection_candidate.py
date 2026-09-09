"""Offline L51 candidate. Content-keyed derivation, no sequence/time assumptions."""
from __future__ import annotations

import dataclasses
import importlib.util
import itertools
import json
import random
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from kernel.schema import Quote, fold_complement_bids
from nodes.capture.capture import read_frames
from nodes.stream_kalshi.protocol import TickerBook


def quoted_side(book, side):
    cache = getattr(book, "_quoted_ladders", None)
    if cache is None:
        cache = book._quoted_ladders = {}
    levels = tuple(sorted(getattr(book, side).items(), reverse=True))
    old = cache.get(side)
    if old is None or old[0] != levels:
        old = [levels, tuple(Quote(p, s) for p, s in levels), None]
        cache[side] = old
    return old


def cached_project(self, outcome="yes"):
    own_side, other_side = ("yes", "no") if outcome == "yes" else ("no", "yes")
    own, other = quoted_side(self, own_side), quoted_side(self, other_side)
    if other[2] is None:
        other[2] = fold_complement_bids(other[1])
    return ([(q.price, q.size) for q in own[1]], [(q.price, q.size) for q in other[2]])


def validate(reference):
    rng = random.Random(51)
    book = TickerBook()
    comparisons = 0
    for i in range(2000):
        side = rng.choice(("yes", "no"))
        levels = getattr(book, side)
        price = rng.randrange(101) / 100
        if i % 17 == 0:
            setattr(book, side, {rng.randrange(101) / 100: float(rng.randrange(100)) for _ in range(50)})
        elif i % 7 == 0:
            levels.pop(price, None)
        else:
            levels[price] = float(rng.randrange(1000))
        for outcome in ("yes", "no"):
            want = reference(book, outcome)
            got = cached_project(book, outcome)
            assert got == want
            got[0].clear()
            got[1].append((0.5, 9999.0))
            assert cached_project(book, outcome) == want
            comparisons += 2
    for invalid in (float("nan"), float("inf"), -0.01, 1.01):
        book.yes = {invalid: 1.0}
        for method in (reference, cached_project):
            try:
                method(book, "yes")
            except ValueError:
                pass
            else:
                raise AssertionError("invalid price accepted")
    return comparisons


def main():
    spec = importlib.util.spec_from_file_location("l51_measure", Path(__file__).with_name("measure.py"))
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    frames = list(itertools.islice(read_frames('/Volumes/Kilos/janus/frames/kalshi/2026-09-09/04.jsonl.gz', 'kalshi'), 10000))
    reference = TickerBook.project
    result = {"comparisons": validate(reference), "frames": len(frames), "baseline": [], "candidate": []}
    for _ in range(3):
        result["baseline"].append(measure.reader_run(frames, 'kalshi', 454)["cpu_s"])
        with patch.object(TickerBook, 'project', cached_project):
            result["candidate"].append(measure.reader_run(frames, 'kalshi', 454)["cpu_s"])
    result["median_baseline_s"] = statistics.median(result["baseline"])
    result["median_candidate_s"] = statistics.median(result["candidate"])
    result["reduction"] = 1 - result["median_candidate_s"] / result["median_baseline_s"]
    print(json.dumps(result, indent=2))
    Path(__file__).with_name('results_projection_candidate_01.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()

"""ITF evidence is population-specific, exhaustive, upper-bounded, and independently replayed."""
import hashlib
import json
import math
from pathlib import Path
import tomllib

import pytest

from nodes.settle_wedge.evidence import EVIDENCE

ROOT = Path(__file__).resolve().parents[3]
POPULATIONS = (
    ("tennis.itf.delayed_gt14d_rate", "2026-09-09_itf-delay-atomic"),
    ("tennis.itf.qualifying.delayed_gt14d_rate", "2026-09-09_itf-qualifying-atomic"),
)


@pytest.mark.parametrize("key,directory", POPULATIONS)
def test_itf_population_is_registered_only_from_its_own_complete_pass(key, directory):
    research = ROOT / "research/sports" / directory
    path = research / "results.json"
    result = json.loads(path.read_text()) if path.exists() else None
    if result is None or result["gates"] != "PASS":
        assert key not in EVIDENCE
        return
    evidence = EVIDENCE[key]
    assert result["complete"] and not result["gate_failures"]
    assert result["parseability"] >= 0.95 and result["actual_closed_candidates"] > 0
    assert result["spec_sha256"] == hashlib.sha256((research / "spec.yaml").read_bytes()).hexdigest()
    assert result["estimator"] == "one_sided_95_upper_bound_at_all_n"
    assert evidence.value == result["registered_value"] == result["upper_bound_95"]
    assert evidence.value >= result["adverse_point_estimate"] and evidence.value > 0
    assert evidence.n == result["mature_n"]
    assert evidence.research_ref == f"research/sports/{directory}/spec.yaml"
    assert (research / "verdict.md").exists()
    if "qualifying" in key:
        assert result["source_row"] == "L46" and result["network_requests"] == 0
    else:
        replay = json.loads((research / "verification.json").read_text())
        assert replay["status"] == "PASS" and replay["network_requests"] == 0
        assert replay["results_byte_identical"] and replay["rows_byte_identical"]
        assert replay["original_results_sha256"] == replay["replayed_results_sha256"]
        assert replay["original_results_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert replay["original_rows_sha256"] == replay["replayed_rows_sha256"]


@pytest.mark.parametrize("key,directory", POPULATIONS)
def test_registered_itf_bound_recomputes_independently_from_preserved_counts(key, directory):
    result = json.loads((ROOT / "research/sports" / directory / "results.json").read_text())
    count, n, z = result["adverse"], result["mature_n"], 1.6449
    # Algebraically equivalent Wilson closed form; does not call the measurement's helper.
    upper = ((2 * count + z * z + z * math.sqrt(z * z + 4 * count * (1 - count / n)))
             / (2 * (n + z * z))) if count else min(1, 3 / n)
    assert EVIDENCE[key].value == pytest.approx(upper, rel=1e-14, abs=1e-16)
    assert sum(result["mature_reasons"].values()) == n
    assert n - result["mature_reasons"].get("WINNER_WITHIN_14D", 0) == count


def test_itf_paper_cap_requires_its_own_measured_main_draw_population():
    limits = tomllib.loads((ROOT / "nodes/risk/limits.toml").read_text())
    allowance = limits["events"]["per_league_usd"].get("itf", 0)
    if "tennis.itf.delayed_gt14d_rate" in EVIDENCE:
        assert allowance == 200.0
    else:
        assert allowance == 0


def test_registered_main_draw_and_qualifying_populations_partition_the_same_catalog():
    main = json.loads((ROOT / "research/sports" / POPULATIONS[0][1] / "results.json").read_text())
    qualifying = json.loads((ROOT / "research/sports" / POPULATIONS[1][1] / "results.json").read_text())
    assert main["gates"] == qualifying["gates"] == "PASS"
    assert main["archive"] == qualifying["archive"]
    assert main["tennis_events"] == qualifying["tennis_events"]
    assert main["structural_exclusions"]["QUALIFYING"] == qualifying["identified_singles"]
    assert qualifying["structural_exclusions"]["NOT_QUALIFYING"] == main["identified_singles"]
    assert main["identified_singles"] + qualifying["identified_singles"] == main["itf_events"]


def test_failed_itf_enumerations_stay_failed_and_supply_no_evidence():
    for directory in ("2026-09-09_itf-settlement-delay", "2026-09-09_itf-settlement-delay-keyset",
                      "2026-09-09_itf-qualifying-delay"):
        result = json.loads((ROOT / "research/sports" / directory / "results.json").read_text())
        assert result["gates"] == "FAIL" and result["registered_value"] is None
        assert not any(row.research_ref == f"research/sports/{directory}/spec.yaml" for row in EVIDENCE.values())

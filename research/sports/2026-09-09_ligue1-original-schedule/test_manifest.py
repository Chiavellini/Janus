"""Synthetic-only tests for the L62 no-terminal-before-freeze firewall."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("manifest.py")
SPEC = importlib.util.spec_from_file_location("l62_manifest", MODULE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def fixture(tmp_path: Path):
    root = tmp_path / "ligue1-L62"
    root.mkdir()
    sources = []
    for label, kind in (("season-membership", "fixture_membership"),
                        ("dated-schedule-batches", "original_schedule")):
        raw = root / f"{label}.pdf"
        raw.write_bytes(f"official {label}".encode())
        meta = root / f"{label}.meta.json"
        body = {
            "label": label, "kind": kind,
            "url": "https://www.lfp.fr/source", "final_url": "https://ligue1.com/final",
            "request_started_utc": "2026-09-09T10:00:00Z",
            "request_finished_utc": "2026-09-09T10:00:01Z", "status": 200,
            "bytes": raw.stat().st_size, "media_type": "application/pdf", "path": str(raw),
            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        }
        meta.write_text(json.dumps(body))
        sources.append({"label": label, "kind": kind, "path": str(raw), "metadata_path": str(meta)})
    manifest = {"archive_root": str(root), "sources": sources}
    return root, manifest


def freeze(root: Path, manifest: dict):
    manifest_path = root / "source_manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    lineage = m.verify(manifest, archive_root=root)
    by_label = {row["label"]: row["sha256"] for row in lineage["sources"]}
    membership = {"label": "season-membership", "sha256": by_label["season-membership"]}
    schedule = {"label": "dated-schedule-batches", "sha256": by_label["dated-schedule-batches"]}
    fixtures = []
    clubs = [f"club-{n:02d}" for n in range(18)]
    for home in clubs:
        for away in clubs:
            if home == away:
                continue
            fixtures.append({
                "home_id": home, "away_id": away,
                "phase": "regular_season",
                "original_lower_utc": "2025-08-14T22:00:00Z",
                "candidates": [{"local_date": "2025-08-15", "timezone": "Europe/Paris",
                                "published_clock": "20:45", "source": dict(schedule)}],
                "source_history": [dict(membership), dict(schedule)],
            })
    bounds = {
        "id": "L62", "season": "2025/26", "competition": "French Ligue 1",
        "phase": "regular_season", "source_manifest_sha256": m.digest(manifest_path),
        "source_lineage_sha256": hashlib.sha256(canonical(lineage)).hexdigest(),
        "fixtures": fixtures,
    }
    bounds_path = root / "original_bounds.json"
    bounds_path.write_bytes(canonical(bounds))
    return manifest_path, bounds_path, bounds


def cert(root, manifest_path, bounds_path):
    return m.verify_original_freeze(archive_root=root, manifest_sha256=m.digest(manifest_path),
                                    bounds_sha256=m.digest(bounds_path))


def test_complete_original_pair_and_306_fixture_freeze_verify(tmp_path):
    root, manifest = fixture(tmp_path)
    assert m.verify(manifest, archive_root=root)["source_count"] == 2
    mp, bp, _ = freeze(root, manifest)
    assert cert(root, mp, bp).fixture_count == 306


@pytest.mark.parametrize("mutation", ["missing_raw", "missing_meta", "bad_status", "bad_hash",
                                       "bad_size", "bad_url", "bad_time", "bad_kind"])
def test_integrity_failures_block(tmp_path, mutation):
    root, manifest = fixture(tmp_path)
    item = manifest["sources"][0]
    raw, meta = Path(item["path"]), Path(item["metadata_path"])
    if mutation == "missing_raw":
        raw.unlink()
    elif mutation == "missing_meta":
        meta.unlink()
    else:
        body = json.loads(meta.read_text())
        if mutation == "bad_status": body["status"] = 500
        elif mutation == "bad_hash": body["sha256"] = "0" * 64
        elif mutation == "bad_size": body["bytes"] += 1
        elif mutation == "bad_url": body["url"] = "https://espn.com/not-original"
        elif mutation == "bad_time": body["request_finished_utc"] = "2026-09-09T09:59:00Z"
        elif mutation == "bad_kind": body["kind"] = item["kind"] = "espn_summary"
        meta.write_text(json.dumps(body))
    with pytest.raises((ValueError, FileNotFoundError)):
        m.verify(manifest, archive_root=root)


def test_duplicate_or_orphan_or_path_escape_blocks(tmp_path):
    root, manifest = fixture(tmp_path)
    root.joinpath("orphan.bin").write_bytes(b"x")
    with pytest.raises(ValueError, match="orphan"):
        m.verify(manifest, archive_root=root)
    root.joinpath("orphan.bin").unlink()
    manifest["sources"].append(dict(manifest["sources"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        m.verify(manifest, archive_root=root)
    manifest["sources"] = [{**manifest["sources"][0], "path": str(tmp_path / "outside")},
                           manifest["sources"][1]]
    with pytest.raises(ValueError, match="escapes"):
        m.verify(manifest, archive_root=root)


@pytest.mark.parametrize("mutation", ["empty", "305", "307", "duplicate", "club_counts",
                                       "missing_date", "bad_date", "lineage", "manifest_drift",
                                       "noncanonical", "membership_only", "missing_candidates",
                                       "missing_history", "bad_phase", "not_earliest", "not_midnight",
                                       "duplicate_refs", "shuffled"])
def test_noncompliant_freeze_blocks_before_transport(tmp_path, mutation):
    root, manifest = fixture(tmp_path)
    mp, bp, bounds = freeze(root, manifest)
    if mutation == "empty": bounds = {}
    elif mutation == "305": bounds["fixtures"] = bounds["fixtures"][:-1]
    elif mutation == "307": bounds["fixtures"].append(dict(bounds["fixtures"][0], away_id="club-extra"))
    elif mutation == "duplicate": bounds["fixtures"][1] = dict(bounds["fixtures"][0])
    elif mutation == "club_counts": bounds["fixtures"][0]["home_id"] = "club-extra"
    elif mutation == "missing_date": bounds["fixtures"][0].pop("original_lower_utc")
    elif mutation == "bad_date": bounds["fixtures"][0]["original_lower_utc"] = "unbounded"
    elif mutation == "lineage": bounds["fixtures"][0]["source_history"][0]["sha256"] = "0" * 64
    elif mutation == "membership_only":
        bounds["fixtures"][0]["source_history"] = bounds["fixtures"][0]["source_history"][:1]
    elif mutation == "missing_candidates": bounds["fixtures"][0].pop("candidates")
    elif mutation == "missing_history": bounds["fixtures"][0].pop("source_history")
    elif mutation == "bad_phase": bounds["fixtures"][0]["phase"] = "cup"
    elif mutation == "not_earliest":
        first = bounds["fixtures"][0]
        first["candidates"].append({**first["candidates"][0], "local_date": "2025-08-14"})
    elif mutation == "not_midnight": bounds["fixtures"][0]["original_lower_utc"] = "2025-08-14T23:00:00Z"
    elif mutation == "duplicate_refs":
        bounds["fixtures"][0]["source_history"].append(dict(bounds["fixtures"][0]["source_history"][0]))
    elif mutation == "shuffled": bounds["fixtures"][0], bounds["fixtures"][1] = bounds["fixtures"][1], bounds["fixtures"][0]
    elif mutation == "manifest_drift":
        mp.write_bytes(mp.read_bytes() + b" ")
    if mutation != "manifest_drift":
        bp.write_bytes((json.dumps(bounds).encode() if mutation == "noncanonical" else canonical(bounds)))
    calls = []
    with pytest.raises(ValueError):
        m.terminal_request("espn_inventory", lambda *args: calls.append(args), "request",
                           archive_root=root,
                           manifest_sha256=(m.digest(mp) if mutation != "manifest_drift" else bounds.get("source_manifest_sha256", "0" * 64)),
                           bounds_sha256=m.digest(bp))
    assert calls == []


def test_terminal_transport_runs_only_after_exact_certificate(tmp_path):
    root, manifest = fixture(tmp_path)
    mp, bp, _ = freeze(root, manifest)
    calls = []
    result = m.terminal_request("espn_inventory", lambda req, certificate: calls.append(req) or certificate,
                                "season", archive_root=root, manifest_sha256=m.digest(mp),
                                bounds_sha256=m.digest(bp))
    assert calls == ["season"] and result.fixture_count == 306

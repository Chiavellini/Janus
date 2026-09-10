#!/usr/bin/env python3
"""Offline L62 source/freeze firewall. No function here performs acquisition by itself."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ARCHIVE_ROOT = Path("/Volumes/Kilos/janus/research/ligue1-L62")
ORIGINAL_KINDS = frozenset({"fixture_membership", "original_schedule"})
TERMINAL_KINDS = frozenset({"espn_inventory", "espn_summary", "completion", "cancellation", "terminal"})
OFFICIAL_HOSTS = frozenset({"lfp.fr", "www.lfp.fr", "ligue1.com", "www.ligue1.com"})
SHA256 = re.compile(r"[0-9a-f]{64}")
EXPECTED_FIXTURES, EXPECTED_CLUBS = 306, 18


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _inside(path: Path, root: Path) -> Path:
    resolved, resolved_root = path.resolve(), root.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ValueError(f"path escapes L62 archive root: {path}")
    return resolved


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(parsed.timestamp()):
        raise ValueError(f"non-finite {label}")
    return parsed


def authorize_source_kind(kind: str) -> None:
    """Only original-source acquisition is allowed without a validated freeze."""
    if kind in ORIGINAL_KINDS:
        return
    if kind in TERMINAL_KINDS:
        raise ValueError(f"terminal source kind {kind} requires terminal_request with a verified freeze")
    raise ValueError(f"unknown L62 source kind: {kind}")


def verify(manifest: dict, *, archive_root: Path = ARCHIVE_ROOT) -> dict:
    """Verify the declared complete original-source set and return its stable lineage summary."""
    if Path(manifest.get("archive_root", "")).resolve() != archive_root.resolve():
        raise ValueError("manifest archive_root does not match the L62 archive root")
    rows = manifest.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest sources must be a non-empty list")
    labels, kinds, declared_paths, output = set(), set(), set(), []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("source entry must be an object")
        label, kind = item.get("label"), item.get("kind")
        if not isinstance(label, str) or not label or label in labels:
            raise ValueError(f"missing or duplicate source label: {label!r}")
        authorize_source_kind(str(kind))
        labels.add(label)
        kinds.add(str(kind))
        raw = _inside(Path(str(item.get("path", ""))), archive_root)
        meta = _inside(Path(str(item.get("metadata_path", ""))), archive_root)
        if raw in declared_paths or meta in declared_paths or raw == meta:
            raise ValueError(f"duplicate source path: {label}")
        declared_paths.update((raw, meta))
        if not raw.is_file() or not meta.is_file() or not meta.name.endswith(".meta.json"):
            raise ValueError(f"missing raw/metadata pair: {label}")
        metadata = json.loads(meta.read_text())
        required = {"label", "kind", "url", "final_url", "request_started_utc",
                    "request_finished_utc", "status", "bytes", "media_type", "path", "sha256"}
        if set(metadata) < required:
            raise ValueError(f"metadata fields missing: {label}")
        if metadata["label"] != label or metadata["kind"] != kind:
            raise ValueError(f"metadata identity mismatch: {label}")
        if _inside(Path(str(metadata["path"])), archive_root) != raw:
            raise ValueError(f"metadata raw path mismatch: {label}")
        for key in ("url", "final_url"):
            parsed = urlparse(str(metadata[key]))
            if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
                raise ValueError(f"non-official source URL: {label} {key}")
        if _utc(metadata["request_finished_utc"], "request_finished_utc") < _utc(
                metadata["request_started_utc"], "request_started_utc"):
            raise ValueError(f"request timestamps reversed: {label}")
        if metadata["status"] != 200:
            raise ValueError(f"failed request cannot count as a source: {label}")
        if not isinstance(metadata["bytes"], int) or metadata["bytes"] <= 0 or raw.stat().st_size != metadata["bytes"]:
            raise ValueError(f"byte length mismatch: {label}")
        if not isinstance(metadata["media_type"], str) or not metadata["media_type"].strip():
            raise ValueError(f"missing media type: {label}")
        if not isinstance(metadata["sha256"], str) or not SHA256.fullmatch(metadata["sha256"]):
            raise ValueError(f"invalid sha256: {label}")
        if digest(raw) != metadata["sha256"]:
            raise ValueError(f"raw source overwritten or hash mismatch: {label}")
        output.append({"label": label, "kind": kind, "sha256": metadata["sha256"],
                       "metadata_sha256": digest(meta)})
    if kinds != ORIGINAL_KINDS:
        raise ValueError(f"original source kinds incomplete: {sorted(kinds)}")
    actual = {p.resolve() for p in archive_root.rglob("*") if p.is_file()}
    ignored = {archive_root.resolve() / name for name in
               ("source_manifest.json", "original_bounds.json", "original_freeze_certificate.json")}
    orphan = actual - declared_paths - ignored
    if orphan:
        raise ValueError("orphan source files: " + ", ".join(sorted(str(p) for p in orphan)))
    return {"source_count": len(output), "sources": sorted(output, key=lambda x: x["label"])}


class FreezeCertificate(NamedTuple):
    manifest_sha256: str
    bounds_sha256: str
    canonical_bounds_sha256: str
    fixture_count: int


def verify_original_freeze(*, archive_root: Path = ARCHIVE_ROOT,
                           manifest_sha256: str, bounds_sha256: str) -> FreezeCertificate:
    """Validate exact source lineage and the complete, canonical 306-fixture bounds artifact."""
    if not SHA256.fullmatch(str(manifest_sha256)) or not SHA256.fullmatch(str(bounds_sha256)):
        raise ValueError("freeze hashes must be lowercase SHA256")
    manifest_path, bounds_path = archive_root / "source_manifest.json", archive_root / "original_bounds.json"
    if not manifest_path.is_file() or digest(manifest_path) != manifest_sha256:
        raise ValueError("source manifest missing or hash drift")
    if not bounds_path.is_file() or digest(bounds_path) != bounds_sha256:
        raise ValueError("original bounds missing or hash drift")
    manifest, bounds = json.loads(manifest_path.read_text()), json.loads(bounds_path.read_text())
    lineage = verify(manifest, archive_root=archive_root)
    if bounds_path.read_bytes() != _canonical(bounds):
        raise ValueError("original_bounds.json is not canonical byte-for-byte")
    if (not isinstance(bounds, dict) or bounds.get("id") != "L62" or bounds.get("season") != "2025/26"
            or bounds.get("competition") != "French Ligue 1" or bounds.get("phase") != "regular_season"):
        raise ValueError("wrong L62 bounds population identity")
    expected_lineage_sha = hashlib.sha256(_canonical(lineage)).hexdigest()
    if bounds.get("source_manifest_sha256") != manifest_sha256:
        raise ValueError("bounds do not pin the exact source manifest")
    if bounds.get("source_lineage_sha256") != expected_lineage_sha:
        raise ValueError("bounds source-lineage hash drift")
    fixtures = bounds.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != EXPECTED_FIXTURES:
        raise ValueError(f"original bounds must contain exactly {EXPECTED_FIXTURES} fixtures")
    lineage_by_label = {row["label"]: row for row in lineage["sources"]}
    pairs, home, away = set(), {}, {}
    for index, row in enumerate(fixtures):
        exact = {"home_id", "away_id", "phase", "original_lower_utc", "candidates", "source_history"}
        if not isinstance(row, dict) or set(row) != exact:
            raise ValueError(f"fixture {index} is not an object")
        h, a = row.get("home_id"), row.get("away_id")
        if not isinstance(h, str) or not h or not isinstance(a, str) or not a or h == a:
            raise ValueError(f"fixture {index} has invalid canonical club ids")
        if (h, a) in pairs:
            raise ValueError(f"duplicate ordered fixture: {h} vs {a}")
        pairs.add((h, a))
        home[h], away[a] = home.get(h, 0) + 1, away.get(a, 0) + 1
        if row.get("phase") != "regular_season":
            raise ValueError(f"fixture {index} is not regular season")
        source_history = row.get("source_history")
        if not isinstance(source_history, list) or not source_history:
            raise ValueError(f"fixture {index} has no source lineage")
        history_labels = []
        for source in source_history:
            declared = lineage_by_label.get(source.get("label")) if isinstance(source, dict) else None
            if (not isinstance(source, dict) or set(source) != {"label", "sha256"} or declared is None
                    or source.get("sha256") != declared["sha256"]):
                raise ValueError(f"fixture {index} source lineage mismatch")
            history_labels.append(source["label"])
        if len(history_labels) != len(set(history_labels)):
            raise ValueError(f"fixture {index} has duplicate source lineage")
        history_kinds = {lineage_by_label[label]["kind"] for label in history_labels}
        if not ORIGINAL_KINDS <= history_kinds:
            raise ValueError(f"fixture {index} must bind membership and original-schedule sources")
        candidates = row.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"fixture {index} has no dated candidates")
        local_dates = []
        candidate_keys = set()
        for candidate in candidates:
            candidate_exact = {"local_date", "timezone", "published_clock", "source"}
            if not isinstance(candidate, dict) or set(candidate) != candidate_exact:
                raise ValueError(f"fixture {index} candidate schema mismatch")
            if candidate["timezone"] != "Europe/Paris" or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(candidate["published_clock"])):
                raise ValueError(f"fixture {index} candidate clock/timezone invalid")
            try:
                local_date = date.fromisoformat(str(candidate["local_date"]))
            except ValueError as exc:
                raise ValueError(f"fixture {index} candidate date invalid") from exc
            source = candidate["source"]
            declared = lineage_by_label.get(source.get("label")) if isinstance(source, dict) else None
            if (not isinstance(source, dict) or set(source) != {"label", "sha256"}
                    or declared is None or declared["kind"] != "original_schedule"
                    or source.get("sha256") != declared["sha256"] or source["label"] not in history_labels):
                raise ValueError(f"fixture {index} candidate lacks exact original-schedule lineage")
            key = (local_date.isoformat(), candidate["published_clock"], source["label"])
            if key in candidate_keys:
                raise ValueError(f"fixture {index} has duplicate candidate")
            candidate_keys.add(key)
            local_dates.append(local_date)
        earliest = datetime.combine(min(local_dates), time.min, ZoneInfo("Europe/Paris")).astimezone(timezone.utc)
        derived = earliest.isoformat().replace("+00:00", "Z")
        if row.get("original_lower_utc") != derived:
            raise ValueError(f"fixture {index} lower bound is not earliest Europe/Paris local midnight")
    clubs = set(home) | set(away)
    if len(clubs) != EXPECTED_CLUBS or any(home.get(c) != 17 or away.get(c) != 17 for c in clubs):
        raise ValueError("club counts must be exactly 18 clubs with 17 home and 17 away")
    ordered = sorted(fixtures, key=lambda row: (row["home_id"], row["away_id"]))
    if fixtures != ordered:
        raise ValueError("fixtures are not in canonical home/away order")
    normalized = {**bounds, "fixtures": ordered}
    canonical_sha = hashlib.sha256(_canonical(normalized)).hexdigest()
    return FreezeCertificate(manifest_sha256, bounds_sha256, canonical_sha, len(fixtures))


def terminal_request(kind: str, transport: Callable, request, *, archive_root: Path = ARCHIVE_ROOT,
                     manifest_sha256: str, bounds_sha256: str):
    """The only terminal transport boundary: validate the freeze before invoking transport."""
    if kind not in TERMINAL_KINDS:
        raise ValueError(f"not a terminal source kind: {kind}")
    certificate = verify_original_freeze(
        archive_root=archive_root, manifest_sha256=manifest_sha256, bounds_sha256=bounds_sha256)
    return transport(request, certificate)


if __name__ == "__main__":
    print("Use verify_original_freeze with separately recorded manifest and bounds SHA256 values.")

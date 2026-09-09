import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("l47_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_qualifying_cannot_read_failed_or_missing_l46_source(tmp_path, monkeypatch):
    monkeypatch.setattr(m.source, "HERE", tmp_path)
    with pytest.raises(ValueError, match="NO_RESULT"):
        m.verified_source_archive()
    (tmp_path / "results.json").write_text(json.dumps({"gates": "FAIL", "complete": False}))
    with pytest.raises(ValueError, match="DID_NOT_PASS"):
        m.verified_source_archive()


def test_qualifying_scorer_cannot_fill_in_missing_source_pages_over_the_network(tmp_path):
    with pytest.raises(ValueError, match="NETWORK_FORBIDDEN"):
        list(m.scoring.enumerate_events(m.OfflineOnly(), tmp_path, closed=True))

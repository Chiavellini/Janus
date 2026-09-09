import gzip
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("l46_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_atomic_page_roundtrip_and_existing_target_is_never_overwritten(tmp_path):
    path = tmp_path / "page.json.gz"
    m.atomic_json(path, {"a": [1, "é"]}, compressed=True)
    with gzip.open(path, "rt") as fh:
        assert json.load(fh) == {"a": [1, "é"]}
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        m.atomic_json(path, {"changed": True}, compressed=True)
    assert path.read_bytes() == original and not list(tmp_path.glob("*.pending"))


def test_interrupted_archive_write_never_exposes_a_final_page(tmp_path, monkeypatch):
    def interrupted(self, data):
        raise KeyboardInterrupt("simulated collector interruption")
    monkeypatch.setattr(m.gzip.GzipFile, "write", interrupted)
    path = tmp_path / "page.json.gz"
    with pytest.raises(KeyboardInterrupt):
        m.atomic_json(path, {"a": [1]}, compressed=True)
    assert not path.exists()
    assert len(list(tmp_path.glob("*.pending"))) == 1


class Client:
    def __init__(self, pages):
        self.pages = iter(pages)

    def get_json(self, *args, **kwargs):
        return next(self.pages)


@pytest.mark.parametrize("bad", [None, "", True, {}, []])
def test_invalid_event_ids_fail(tmp_path, bad):
    cl = Client([{"events": [{"id": bad}], "next_cursor": None}])
    with pytest.raises(ValueError, match="MISSING_OR_INVALID_ID"):
        list(m.enumerate_events(cl, tmp_path, closed=True))


@pytest.mark.parametrize("bad", [False, 0, [], {}])
def test_invalid_cursor_types_are_not_treated_as_terminal(tmp_path, bad):
    cl = Client([{"events": [{"id": "1"}], "next_cursor": bad}])
    with pytest.raises(ValueError, match="INVALID_OR_LOOPING_CURSOR"):
        list(m.enumerate_events(cl, tmp_path, closed=True))
    with pytest.raises(ValueError, match="INVALID_CURSOR_TYPE"):
        list(m.scoring.enumerate_events(Client([]), tmp_path, closed=True))


def test_short_pages_and_terminal_cursor_are_archived_for_offline_verification(tmp_path):
    cl = Client([{"events": [{"id": "1"}], "next_cursor": "opaque"},
                 {"events": [{"id": "2"}], "next_cursor": None}])
    assert len(list(m.enumerate_events(cl, tmp_path, closed=True))) == 2
    class Offline:
        def get_json(self, *args, **kwargs):
            raise AssertionError("must use complete archived cursor chain")
    assert len(list(m.scoring.enumerate_events(Offline(), tmp_path, closed=True))) == 2

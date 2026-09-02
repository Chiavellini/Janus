#!/usr/bin/env python3
"""Hermetic tests for the IBKR forward-archive collector. No network, no credentials, no Kilos."""

from __future__ import annotations

import datetime as dt
import sqlite3
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.ibkr_archive_core import (  # noqa: E402
    FIELDS, ArchiveStorage, alarm_decision, availability_status, nearest_strike, quote_row,
    select_front_future, select_option_expiry, session_label,
)
from collectors.collect_ibkr_archive import Collector, selftest  # noqa: E402
from lib.ibkr_readonly import IBKRReadOnlyClient, IBKRResponseError  # noqa: E402

ET = ZoneInfo("America/New_York")
ALLOWED_CLIENT_METHODS = {"auth_status", "tickle", "initialize_accounts", "search_contracts",
                          "futures", "option_strikes", "option_contracts", "snapshot"}


class FakeClock:
    def __init__(self, t0: float):
        self.t = t0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += max(0.0, s)


class FakeClient:
    """Canned IBKR responses. Deliberately leaks account/session/MAC-looking fields so the tests can
    prove they never reach disk."""

    def __init__(self, *, authenticated=True, snapshot_error=None):
        self.calls: list[str] = []
        self.authenticated = authenticated
        self.snapshot_error = snapshot_error
        self.snapshot_calls = 0
        self.snapshot_payload = None

    def _rec(self, name):
        self.calls.append(name)

    def auth_status(self):
        self._rec("auth_status")
        return {"authenticated": self.authenticated, "connected": True, "competing": False,
                "MAC": "00:11:22:33:44:55", "session": "deadbeef"}

    def tickle(self):
        self._rec("tickle")
        return {"session": "cafebabe", "iserver": {"authStatus": {"authenticated": True}}}

    def initialize_accounts(self):
        self._rec("initialize_accounts")
        return {"accounts": ["U1234567"], "acctId": "U1234567", "isPaper": False}

    def futures(self, *symbols):
        self._rec("futures")
        return {"BTC": [{"conid": 3, "symbol": "BTC", "expirationDate": "20260925"},
                        {"conid": 2, "symbol": "BTC", "expirationDate": "20260828"}],
                "MBT": [{"conid": 5, "symbol": "MBT", "expirationDate": "20260828"}],
                "ZQ": [{"conid": 7, "symbol": "ZQ", "expirationDate": "20260831"}]}

    def search_contracts(self, symbol, *, sec_type=None):
        self._rec("search_contracts")
        return [{"conid": 100 if symbol == "SPX" else 200, "symbol": symbol, "secType": "IND",
                 "sections": [{"secType": "OPT", "months": "AUG26;SEP26"}]}]

    def option_strikes(self, conid, month, *, exchange=None):
        self._rec("option_strikes")
        return {"call": [6300, 6400, 6500], "put": [6300, 6400, 6500]}

    def option_contracts(self, conid, month, strike, right, *, exchange=None):
        self._rec("option_contracts")
        base = 1000 if conid == 100 else 2000
        return [{"conid": base + (1 if right == "C" else 2), "maturityDate": "20260818", "symbol": "SPX"},
                {"conid": base + (3 if right == "C" else 4), "maturityDate": "20260819", "symbol": "SPX"}]

    def snapshot(self, conids, fields):
        self._rec("snapshot")
        assert set(fields) <= set(FIELDS)
        self.snapshot_calls += 1
        if self.snapshot_error:
            raise IBKRResponseError(self.snapshot_error)
        if self.snapshot_payload is not None:
            return self.snapshot_payload
        out = []
        for c in conids:
            row = {"conid": c, "_updated": 1_787_000_000_000, "6509": "RpB", "acctId": "U1234567"}
            if c in (100, 200):
                row.update({"31": "C6400.5"})
            elif c in (2, 5, 7):
                row.update({"31": "112000", "84": "111990", "86": "112010", "88": "3", "85": "2"})
            out.append(row)
        return out


T0 = dt.datetime(2026, 8, 19, 1, 0, tzinfo=dt.timezone.utc).timestamp()   # 21:00 ET Tue Aug 18


def _dump(db: Path) -> str:
    con = sqlite3.connect(db)
    text = "\n".join(str(tuple(r)) for t in ("instruments", "contract_roll", "polls", "quotes", "health")
                     for r in con.execute(f"SELECT * FROM {t}"))
    con.close()
    return text


def test_quote_row_projects_allowlist_only_and_distinguishes_no_message():
    row = quote_row({"conid": 2, "_updated": 1000, "6509": "RpB", "31": "C1.5", "84": "1", "86": "2",
                     "acctId": "U1", "position": 3}, recv_ts=2.0)
    assert row["row_kind"] == "MSG" and row["last"] == 1.5 and row["staleness_ms"] == 1000
    assert "acctId" not in row and "position" not in row
    assert quote_row({"conid": 2, "_updated": 1000, "6509": "RpB"}, 2.0)["row_kind"] == "NO_CHANGE"
    assert availability_status("DpB") != "HFT_READY" and availability_status(None) != "HFT_READY"


def test_session_labels_follow_pinned_exchange_clocks():
    rth = dt.datetime(2026, 8, 19, 10, 0, tzinfo=ET).timestamp()
    gth = dt.datetime(2026, 8, 19, 21, 0, tzinfo=ET).timestamp()
    gap = dt.datetime(2026, 8, 19, 17, 0, tzinfo=ET).timestamp()
    sat = dt.datetime(2026, 8, 22, 12, 0, tzinfo=ET).timestamp()
    assert session_label(rth, "OPT") == "RTH" and session_label(gth, "OPT") == "GTH"
    assert session_label(gap, "OPT") == "CLOSED" and session_label(sat, "OPT") == "CLOSED"
    assert session_label(rth, "FUT") == "GLOBEX" and session_label(gap, "FUT") == "MAINTENANCE"
    assert session_label(sat, "FUT") == "CLOSED"


def test_selection_rules_are_deterministic():
    raw = {"BTC": [{"conid": 3, "symbol": "BTC", "expirationDate": "20260925"},
                   {"conid": 2, "symbol": "BTC", "expirationDate": "20260828"},
                   {"conid": 1, "symbol": "BTC", "expirationDate": "20260731"}],
           "MBT": [{"conid": 9, "symbol": "MBT", "expirationDate": "20260828"}]}
    assert select_front_future(raw, "BTC", dt.date(2026, 8, 18))["conid"] == 2
    assert select_front_future(raw, "MBT", dt.date(2026, 8, 18))["conid"] == 9
    assert nearest_strike({"call": [6300, 6400], "put": [6300, 6400]}, 6350) == 6300
    info = [{"conid": 11, "maturityDate": "20260818"}, {"conid": 12, "maturityDate": "20260819"}]
    before_close = dt.datetime(2026, 8, 18, 15, 0, tzinfo=ET).timestamp()
    after_close = dt.datetime(2026, 8, 18, 16, 30, tzinfo=ET).timestamp()
    assert select_option_expiry(info, before_close)["conid"] == 11
    assert select_option_expiry(info, after_close) == {"conid": 12, "expiry": "20260819",
                                                       "expiry_pinned": 1, "exchange": None,
                                                       "symbol": None}


def test_storage_refuses_system_disk_and_forbidden_text():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            ArchiveStorage(Path(tmp) / "x.sqlite")           # not under /Volumes/Kilos/janus
        st = ArchiveStorage(Path(tmp) / "x.sqlite", enforce_data_root=False)
        with pytest.raises(ValueError):
            st.health("auth", "x", "acctId=U1234567")
        with pytest.raises(ValueError):
            st.gap(1, 1.0, "made_up_reason", "RTH")
        st.close()


def test_collector_end_to_end_states_and_privacy():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "a.sqlite"
        st = ArchiveStorage(db, enforce_data_root=False)
        clock = FakeClock(T0)
        client = FakeClient()
        c = Collector(client, st, families={"crypto_futures", "fed_funds", "index_options"},
                      now=clock.now, sleep=clock.sleep,
                      disk_usage=lambda p: type("U", (), {"free": 10 ** 12})())
        c.run(duration_s=40)
        st.close()
        assert set(client.calls) <= ALLOWED_CLIENT_METHODS
        con = sqlite3.connect(db)
        active = con.execute("SELECT root, sec_type, expiry, expiry_pinned, strike, \"right\" FROM instruments "
                             "WHERE retired_ts IS NULL ORDER BY conid").fetchall()
        # BTC front, MBT front, ZQ, SPX idx, XSP idx, 2 SPX opts, 2 XSP opts = 9 instruments.
        assert len(active) == 9
        assert ("BTC", "FUT", "20260828", 1, None, None) in active
        # Option expiry pinned to the exact day and strike nearest 6400.5 -> 6400.
        assert ("SPX", "OPT", "20260819", 1, 6400.0, "C") in active
        polls = con.execute("SELECT ok, reason FROM polls").fetchall()
        assert polls and all(ok == 1 and reason is None for ok, reason in polls)
        kinds = dict(con.execute("SELECT row_kind, COUNT(*) FROM quotes GROUP BY row_kind").fetchall())
        assert kinds.get("MSG", 0) > 0 and "GAP" not in kinds
        # Options rows carry no quote fields in the fake -> NO_CHANGE heartbeats, not fake prices.
        assert kinds.get("NO_CHANGE", 0) > 0
        assert con.execute("SELECT COUNT(*) FROM quotes WHERE recv_ts IS NULL").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM contract_roll").fetchone()[0] == 9
        con.close()
        text = _dump(db)
        for bad in ("U1234567", "acctId", "deadbeef", "cafebabe", "00:11:22:33:44:55"):
            assert bad not in text


def test_collector_reason_codes_gaps_when_unauthenticated_or_gateway_fails():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "b.sqlite"
        st = ArchiveStorage(db, enforce_data_root=False)
        clock = FakeClock(T0)
        client = FakeClient(authenticated=False)
        c = Collector(client, st, families={"crypto_futures"}, now=clock.now, sleep=clock.sleep,
                      disk_usage=lambda p: type("U", (), {"free": 10 ** 12})())
        c.run(duration_s=5)
        assert "snapshot" not in client.calls
        reasons = {r[0] for r in st.con.execute("SELECT DISTINCT reason FROM polls")}
        assert reasons == {"AUTH_INVALID"}
        assert st.con.execute("SELECT COUNT(*) FROM quotes WHERE row_kind='GAP' AND gap_reason='AUTH_INVALID'"
                              ).fetchone()[0] > 0
        st.close()

        db2 = Path(tmp) / "c.sqlite"
        st2 = ArchiveStorage(db2, enforce_data_root=False)
        client2 = FakeClient(snapshot_error="IBKR gateway request failed: The read operation timed out")
        c2 = Collector(client2, st2, families={"crypto_futures"}, now=clock.now, sleep=clock.sleep,
                       disk_usage=lambda p: type("U", (), {"free": 10 ** 12})())
        c2.run(duration_s=5)
        assert {r[0] for r in st2.con.execute("SELECT DISTINCT reason FROM polls")} == {"GATEWAY_TIMEOUT"}
        assert st2.con.execute("SELECT COUNT(*) FROM quotes WHERE gap_reason='GATEWAY_TIMEOUT'").fetchone()[0] > 0
        st2.close()


def test_collector_marks_missing_conid_as_no_message_and_rolls_without_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "d.sqlite"
        st = ArchiveStorage(db, enforce_data_root=False)
        clock = FakeClock(T0)
        client = FakeClient()
        client.snapshot_payload = [{"conid": 2, "_updated": 1, "6509": "RpB", "31": "1"}]  # MBT/ZQ absent
        c = Collector(client, st, families={"crypto_futures", "fed_funds"}, now=clock.now,
                      sleep=clock.sleep, disk_usage=lambda p: type("U", (), {"free": 10 ** 12})())
        c.run(duration_s=3)
        gaps = st.con.execute("SELECT DISTINCT conid FROM quotes WHERE gap_reason='NO_MESSAGE'").fetchall()
        assert {g[0] for g in gaps} == {5, 7}
        # A reselect that returns a different front contract retires the old one and records lineage.
        c._swap("crypto_futures", "FUT:BTC", {"root": "BTC", "conid": 3, "sec_type": "FUT",
                "expiry": "20260925", "expiry_pinned": 1, "exchange": None, "strike": None,
                "right": None, "underlying_conid": None, "selection_rule": "earliest_unexpired_by_root"},
                clock.now(), "test_roll")
        rows = st.con.execute("SELECT conid, retired_ts FROM instruments WHERE root='BTC' ORDER BY conid").fetchall()
        assert [r[0] for r in rows] == [2, 3] and rows[0][1] is not None and rows[1][1] is None
        assert tuple(st.con.execute("SELECT old_conid,new_conid FROM contract_roll WHERE reason='test_roll'").fetchone()) == (2, 3)
        # No duplicate active identity per slot.
        dup = st.con.execute("SELECT root, COUNT(*) FROM instruments WHERE retired_ts IS NULL AND sec_type='FUT' "
                             "GROUP BY root HAVING COUNT(*)>1").fetchall()
        assert dup == []
        st.close()


def test_fake_target_alarms_and_disk_floor_stop():
    selftest()
    assert alarm_decision(free_bytes=10 ** 12, disk_floor_bytes=2 ** 31, last_ok_poll_age_s=1,
                          max_poll_age_s=120, poll_success_rate=1.0, min_poll_success_rate=0.98,
                          authenticated=True) == []
    with tempfile.TemporaryDirectory() as tmp:
        st = ArchiveStorage(Path(tmp) / "e.sqlite", enforce_data_root=False)
        clock = FakeClock(T0)
        c = Collector(FakeClient(), st, families={"crypto_futures"}, now=clock.now, sleep=clock.sleep,
                      disk_usage=lambda p: type("U", (), {"free": 1})())
        alarms = c.monitor()
        assert "disk_floor" in alarms and c.stop is True
        st.close()


def test_readonly_client_surface_is_the_only_transport():
    public = {n for n in dir(IBKRReadOnlyClient) if not n.startswith("_")}
    assert ALLOWED_CLIENT_METHODS <= public
    assert not any(w in n.lower() for n in public for w in ("order", "trade", "post", "reply"))


def test_report_guards_duration_and_scans_privacy():
    from collectors.report_ibkr_archive import report
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "r.sqlite"
        st = ArchiveStorage(db, enforce_data_root=False)
        clock = FakeClock(T0)
        c = Collector(FakeClient(), st, families={"crypto_futures", "index_options"}, now=clock.now,
                      sleep=clock.sleep, disk_usage=lambda p: type("U", (), {"free": 10 ** 12})())
        c.run(duration_s=20)
        st.close()
        out = Path(tmp) / "out"
        res = report(db, out, now=clock.now())
        assert res["verdict"] == "PENDING_INSUFFICIENT_DURATION"
        assert res["privacy_leak_rows"] == 0 and res["test_looks_spent"] == 0 and res["orders_placed"] == 0
        assert res["gate_checks"]["zero_identifiers"] and res["gate_checks"]["no_duplicate_identity"]
        assert (out / "results.json").exists() and (out / "verdict.md").exists()
        text = (out / "results.json").read_text()
        for bad in ("U1234567", "acctId", "deadbeef"):
            assert bad not in text


def test_core_underlying_conid_uses_section_sectype():
    from collectors.ibkr_archive_core import underlying_conid
    raw = [{"conid": "137851301", "symbol": "XSP", "sections": [{"secType": "IND"}, {"secType": "OPT"}]},
           {"conid": "74580612", "symbol": "XSP", "sections": [{"secType": "STK"}, {"secType": "OPT"}]}]
    assert underlying_conid(raw, "XSP") == 137851301


# ── put-call parity underlying (added 2026-08-19, L13 run 3) ─────────────────

def test_parity_forward_beats_the_frozen_index_on_the_measured_case():
    """Real numbers from L13 run 3. The frozen SPX index read 7693.26 — the same print as 26 h
    earlier, and 1.50 pt from the official close L15 measured at 7691.76. Parity off the entitled
    option quotes lands materially closer, which is the whole reason for the change."""
    from collectors.ibkr_archive_core import forward_from_parity
    call = {"bid": 63.6, "ask": 64.3}
    put = {"bid": 65.8, "ask": 66.5}
    fwd = forward_from_parity(call, put, 7695.0)
    assert fwd is not None
    assert abs(fwd - 7691.76) < abs(7693.26 - 7691.76)


def test_parity_forward_is_none_without_a_two_sided_book_on_both_legs():
    """A one-sided or crossed book gives no usable mid. Guessing one would reintroduce exactly the
    silent-defect problem this replaces, so it must refuse rather than approximate."""
    from collectors.ibkr_archive_core import forward_from_parity
    good = {"bid": 63.6, "ask": 64.3}
    assert forward_from_parity(good, None, 7695.0) is None
    assert forward_from_parity(good, {"bid": None, "ask": 66.5}, 7695.0) is None
    assert forward_from_parity(good, {"bid": 0, "ask": 66.5}, 7695.0) is None
    assert forward_from_parity(good, {"bid": 67.0, "ask": 66.5}, 7695.0) is None   # crossed
    assert forward_from_parity(None, None, 7695.0) is None


def test_parity_forward_is_the_parity_identity():
    from collectors.ibkr_archive_core import forward_from_parity
    # C mid 10, P mid 4 at K=100 -> F = 100 + 6
    assert forward_from_parity({"bid": 9, "ask": 11}, {"bid": 3, "ask": 5}, 100.0) == 106.0
    # symmetric book at the money -> F == K
    assert forward_from_parity({"bid": 4, "ask": 6}, {"bid": 4, "ask": 6}, 100.0) == 100.0


def test_parity_never_used_as_an_index_level():
    """It is a FORWARD (the discount factor is dropped), not spot. The docstring must say so, so a
    later reader cannot mistake it for an index print."""
    from collectors import ibkr_archive_core as core
    doc = core.forward_from_parity.__doc__ or ""
    assert "FORWARD" in doc and "NOT spot" in doc


def test_auth_401_is_an_auth_state_not_a_gateway_error():
    """Regression: the first live run wrote 98 poll rows reasoned GATEWAY_ERROR while the real
    cause was an expired session, because check_auth() classified every IBKRResponseError the same
    way and auth_reason propagates into poll rows. The spec requires these states stay distinct."""
    import collectors.collect_ibkr_archive as mod

    class Boom:
        def __init__(self, msg): self.msg = msg
        def auth_status(self): raise mod.IBKRResponseError(self.msg)

    class Sink:
        def __init__(self): self.rows = []
        def health(self, *a, **k): self.rows.append(a)

    def build(msg):
        c = mod.Collector.__new__(mod.Collector)
        c.client, c.storage = Boom(msg), Sink()
        c.now, c.authenticated, c.accounts_initialized = (lambda: 0.0), True, True
        c.forbidden_attempts, c.auth_reason, c.last_auth_check = 0, "AUTH_INVALID", 0.0
        return c

    c = build("IBKR HTTP 401: ")
    c.check_auth()
    assert c.auth_reason == "AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED"
    assert c.authenticated is False and c.accounts_initialized is False

    c = build("IBKR HTTP 401: ")
    c.authenticated = False              # never was logged in this session
    c.check_auth()
    assert c.auth_reason == "AUTH_INVALID"

    c = build("IBKR gateway request failed: timed out")
    c.check_auth()
    assert c.auth_reason == "GATEWAY_TIMEOUT"

    c = build("IBKR HTTP 500: boom")
    c.check_auth()
    assert c.auth_reason == "GATEWAY_ERROR"


def test_restart_does_not_create_a_second_active_row_for_the_same_contract():
    """Registered checkpoint: "no duplicate active contract identity per slot across rolls". The
    first restart produced two un-retired rows each for MBT and ZQ, because _swap's identity map is
    in-memory and a restart started it empty."""
    import tempfile, sqlite3
    from pathlib import Path
    import collectors.collect_ibkr_archive as mod
    from collectors.ibkr_archive_core import ArchiveStorage

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "a.sqlite"
        st = ArchiveStorage(str(db), enforce_data_root=False)
        spec = {"root": "MBT", "conid": 111, "sec_type": "FUT", "exchange": "CME",
                "expiry": "20260828", "expiry_pinned": 1, "strike": None, "right": None,
                "underlying_conid": None, "selection_rule": "r", "slot": "FUT:MBT",
                "family": "crypto_futures"}
        st.add_instrument("crypto_futures", spec, 1000.0)
        st.flush()

        c = mod.Collector.__new__(mod.Collector)
        c.storage, c.instruments = st, {}
        c.load_active_instruments()
        assert 111 in c.instruments and c.instruments[111]["slot"] == "FUT:MBT"

        # _swap on the same conid must be a no-op, not a second insert
        c.now = lambda: 2000.0
        c._swap("crypto_futures", "FUT:MBT", dict(spec), 2000.0, "restart")
        st.flush()
        n = sqlite3.connect(str(db)).execute(
            "SELECT COUNT(*) FROM instruments WHERE retired_ts IS NULL AND conid=111").fetchone()[0]
        assert n == 1, f"expected 1 active row, got {n}"


def test_last_known_level_seeds_a_strike_when_the_index_gives_no_last():
    """XSP deferred its entire option selection because the unbought (frozen) index feed returned
    no `last`. No seed means no instrument at all, which is strictly worse than a rough seed that
    put-call parity then corrects."""
    import tempfile
    from pathlib import Path
    from collectors.ibkr_archive_core import ArchiveStorage

    with tempfile.TemporaryDirectory() as d:
        st = ArchiveStorage(str(Path(d) / "b.sqlite"), enforce_data_root=False)
        assert st.last_known_level(None) is None
        assert st.last_known_level(999) is None
        st.quote({"recv_ts": 10.0, "ibkr_updated_ms": None, "conid": 999, "row_kind": "MSG",
                  "gap_reason": None, "last": 769.33, "bid": None, "ask": None, "bid_size": None,
                  "ask_size": None, "availability_code": "Z", "staleness_ms": None,
                  "fields_present": "31"}, "CLOSED")
        st.flush()
        assert st.last_known_level(999) == 769.33


def test_missing_option_selection_is_retried_not_left_until_the_daily_reselect():
    """Startup option selection failed on two consecutive restarts, and the only other attempt is
    the 13:35Z daily reselect — so an unattended capture would run for hours with no option legs,
    which is the entire point of the index_options family."""
    import collectors.collect_ibkr_archive as mod

    class Sink:
        def __init__(self): self.rows = []
        def health(self, *a, **k): self.rows.append(a)

    c = mod.Collector.__new__(mod.Collector)
    c.storage, c.families, c.authenticated = Sink(), {"index_options"}, True
    c.instruments = {1: {"sec_type": "IND"}}          # index present, no OPT
    c.last_selection_retry = 0.0
    c.now = lambda: 10_000.0
    called = []
    c.select_options = lambda reason: called.append(reason)
    c.select_futures = lambda reason: called.append("fut")

    c.retry_missing_selections()
    assert called == ["retry_missing"]

    called.clear()                                     # throttled inside the window
    c.now = lambda: 10_000.0 + mod.Collector.RETRY_SELECTION_S - 1
    c.retry_missing_selections()
    assert called == []

    called.clear()                                     # and not retried once an OPT is active
    c.instruments[2] = {"sec_type": "OPT"}
    c.now = lambda: 10_000.0 + 10 * mod.Collector.RETRY_SELECTION_S
    c.retry_missing_selections()
    assert called == []

    c.authenticated = False                            # never retries while unauthenticated
    c.instruments = {1: {"sec_type": "IND"}}
    c.last_selection_retry = 0.0
    c.retry_missing_selections()
    assert called == []


def test_reauth_is_rate_limited_and_latches_off_when_sso_is_dead():
    """The recovery path must not become a retry loop against IBKR. Once the gateway says the SSO
    session is gone, only a human login helps, so further attempts are pure abuse."""
    import collectors.collect_ibkr_archive as mod

    class Sink:
        def __init__(self): self.rows = []
        def health(self, *a, **k): self.rows.append(a[1])

    class Client:
        def __init__(self, body): self.body, self.calls = body, 0
        def reauthenticate(self):
            self.calls += 1
            return self.body

    def build(body):
        c = mod.Collector.__new__(mod.Collector)
        c.storage, c.client = Sink(), Client(body)
        c.sso_dead, c.last_reauth_attempt, c.forbidden_attempts = False, 0.0, 0
        return c

    # live SSO -> attempt recorded, and rate-limited within the window
    c = build({"message": "re-authenticated"})
    c.try_reauthenticate(1000.0)
    assert c.client.calls == 1 and "REAUTH_ATTEMPTED" in c.storage.rows
    c.try_reauthenticate(1000.0 + mod.Collector.REAUTH_MIN_INTERVAL_S - 1)
    assert c.client.calls == 1, "rate limit did not hold"
    c.try_reauthenticate(1000.0 + mod.Collector.REAUTH_MIN_INTERVAL_S + 1)
    assert c.client.calls == 2

    # dead SSO -> latches off permanently, no matter how much time passes
    c = build({"error": "not logged in"})
    c.try_reauthenticate(1000.0)
    assert c.sso_dead and "SSO_DEAD_HUMAN_LOGIN_REQUIRED" in c.storage.rows
    for t in (2000.0, 99_000.0, 10**6):
        c.try_reauthenticate(t)
    assert c.client.calls == 1, "kept hammering a dead SSO session"


def test_reauth_propagates_a_safety_error_rather_than_swallowing_it():
    """If the transport ever refuses the call, that is a boundary violation and must surface."""
    import collectors.collect_ibkr_archive as mod

    class Sink:
        def health(self, *a, **k): pass

    class Client:
        def reauthenticate(self): raise mod.IBKRSafetyError("blocked")

    c = mod.Collector.__new__(mod.Collector)
    c.storage, c.client = Sink(), Client()
    c.sso_dead, c.last_reauth_attempt, c.forbidden_attempts = False, 0.0, 0
    try:
        c.try_reauthenticate(1000.0)
    except mod.IBKRSafetyError:
        assert c.forbidden_attempts == 1
        return
    raise AssertionError("IBKRSafetyError was swallowed")


def test_session_lifetime_is_recorded_on_drop():
    """Session lifetime was guessed at three times and measured zero times. Now it is emitted."""
    import collectors.collect_ibkr_archive as mod

    class Sink:
        def __init__(self): self.rows = []
        def health(self, *a, **k): self.rows.append((a[1], a[2] if len(a) > 2 else ""))

    c = mod.Collector.__new__(mod.Collector)
    c.storage = Sink()
    c.session_started_ts = 1000.0
    c._note_session_end(1450.0, was_authenticated=True)
    assert any(k == "BROKERAGE_LINK_DOWN" and "lifetime_s=450.0" in v for k, v in c.storage.rows)
    assert c.session_started_ts is None

    c.storage = Sink()                       # never authenticated -> nothing to report
    c._note_session_end(2000.0, was_authenticated=False)
    assert c.storage.rows == []

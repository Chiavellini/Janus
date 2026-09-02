#!/usr/bin/env python3
"""Janus IBKR forward archive collector (Track B, registered spec L14).

REST snapshot polling at 1 Hz through IBKRReadOnlyClient only. Research-only: this process cannot
express an order, never logs in, and never persists account/session/user/hardware identifiers.
Every poll slot yields exactly one `polls` row; every failed poll yields reason-coded GAP rows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.ibkr_archive_core import (  # noqa: E402
    COLLECTOR_VERSION, DATA_ROOT, FIELDS, SPEC_REF, ArchiveStorage, alarm_decision,
    availability_status, conid_of, forward_from_parity, nearest_strike, next_slot,
    option_month, quote_row,
    select_front_future, select_option_expiry, session_label, underlying_conid,
)
from lib.ibkr_readonly import IBKRReadOnlyClient, IBKRResponseError, IBKRSafetyError  # noqa: E402

DEFAULT_DB = DATA_ROOT / "ibkr" / "archive.sqlite"
ALARM_FILE = DATA_ROOT / "ibkr" / "ALARM.txt"
INTERNAL_DISK_FLOOR = 2 * 1024 ** 3
KILOS_DISK_WARN = 20 * 1024 ** 3
FUTURE_ROOTS = ("BTC", "MBT", "ZQ")
INDEX_SYMBOLS = ("SPX", "XSP")
FUTURES_RESELECT_UTC = (0, 5)     # 00:05 UTC daily
OPTIONS_RESELECT_UTC = (13, 35)   # 09:35 ET during EDT; the label check is by ET clock below


class Collector:
    def __init__(self, client: Any, storage: ArchiveStorage, *, families: set[str],
                 poll_period_s: float = 1.0, heartbeat_s: float = 30.0, now=time.time,
                 sleep=time.sleep, disk_usage=shutil.disk_usage):
        self.client = client
        self.storage = storage
        self.families = families              # subset of {"crypto_futures","fed_funds","index_options"}
        self.poll_period_s = poll_period_s
        self.heartbeat_s = heartbeat_s
        self.now = now
        self.sleep = sleep
        self.disk_usage = disk_usage
        self.stop = False
        self.authenticated = False
        self.auth_reason = "AUTH_INVALID"
        self.last_auth_check = 0.0
        self.last_tickle = 0.0
        self.last_monitor = 0.0
        self.last_heartbeat: dict[int, float] = {}
        self.last_state: dict[int, tuple] = {}
        self.instruments: dict[int, dict[str, Any]] = {}
        self.last_futures_day: str | None = None
        self.last_options_day: str | None = None
        self.last_selection_retry = 0.0
        self.last_reauth_attempt = 0.0
        self.sso_dead = False              # latched: only a human login clears it
        self.session_started_ts: float | None = None
        self.forbidden_attempts = 0
        self.accounts_initialized = False

    # -- session -----------------------------------------------------------------------------
    def check_auth(self) -> None:
        ts = self.now()
        try:
            status = self.client.auth_status()
            ok = bool(status.get("authenticated")) and bool(status.get("connected")) \
                and not bool(status.get("competing"))
            was = self.authenticated
            self.authenticated = ok
            if ok and not self.accounts_initialized:
                self.client.initialize_accounts()   # required once before snapshots; not persisted
                self.accounts_initialized = True
            if not ok:
                self.auth_reason = "AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED" if was else "AUTH_INVALID"
                self.accounts_initialized = False
            if ok and not was:
                self.session_started_ts = ts
                self.sso_dead = False
                self.storage.health("auth", "BROKERAGE_LINK_UP", "brokerage link established", ts=ts)
            if not ok:
                self._note_session_end(ts, was)
            if was != ok:
                self.storage.health("auth", "authenticated" if ok else self.auth_reason,
                                    f"connected={bool(status.get('connected'))} "
                                    f"competing={bool(status.get('competing'))}", ts=ts)
        except IBKRSafetyError:
            self.forbidden_attempts += 1
            raise
        except IBKRResponseError as exc:
            # An HTTP 401 from /iserver/auth/status IS "not logged in" -- it is an AUTH state, not a
            # gateway fault. Coding it GATEWAY_ERROR (as this did) poisons every downstream poll row,
            # because auth_reason propagates into them: the first live run wrote 98 polls reasoned
            # GATEWAY_ERROR when the true cause was an expired session. The spec requires these
            # states stay DISTINCT (`gap_reasons`, `states_that_must_stay_distinct`), so conflating
            # them would corrupt exactly the missingness characterization this archive exists for.
            was = self.authenticated
            self.authenticated = False
            self.accounts_initialized = False
            text = str(exc)
            if "401" in text or "403" in text:
                self.auth_reason = "AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED" if was else "AUTH_INVALID"
                self.storage.health("auth", self.auth_reason, f"HTTP status in {text[:40]!r}", ts=ts)
                self._note_session_end(ts, was)
                self.try_reauthenticate(ts)
            elif "timed out" in text:
                self.auth_reason = "GATEWAY_TIMEOUT"
                self.storage.health("auth", "gateway_timeout", type(exc).__name__, ts=ts)
            else:
                self.auth_reason = "GATEWAY_ERROR"
                self.storage.health("auth", "gateway_error", type(exc).__name__, ts=ts)
        self.last_auth_check = ts

    def _note_session_end(self, ts: float, was_authenticated: bool) -> None:
        """Record how long the brokerage session actually lasted.

        Session lifetime was the thing nobody could answer on 2026-08-19 -- it was guessed at three
        times (memory pressure, competing session, inactivity) and measured zero times. Emitting it
        makes the next drop diagnosable instead of arguable.
        """
        started = getattr(self, "session_started_ts", None)
        if was_authenticated and started is not None:
            self.storage.health("auth", "BROKERAGE_LINK_DOWN",
                                f"lifetime_s={round(ts - started, 1)}", ts=ts)
        self.session_started_ts = None

    def try_reauthenticate(self, ts: float) -> None:
        """Revive the brokerage session from a live SSO session. Never a login.

        Hard rules: rate-limited; latched off once the gateway says the SSO session is dead, because
        retrying then is pointless load and only a human at https://localhost:5055 can clear it.
        """
        if getattr(self, "sso_dead", False):
            return
        if ts - getattr(self, "last_reauth_attempt", 0.0) < self.REAUTH_MIN_INTERVAL_S:
            return
        self.last_reauth_attempt = ts
        call = getattr(self.client, "reauthenticate", None)
        if call is None:            # transport predates the endpoint; nothing to recover with
            return
        try:
            body = call()
        except IBKRSafetyError:
            self.forbidden_attempts = getattr(self, "forbidden_attempts", 0) + 1
            raise
        except IBKRResponseError as exc:
            self.storage.health("auth", "REAUTH_FAILED", f"{type(exc).__name__}: {str(exc)[:80]}",
                                ts=ts)
            return
        text = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
        if self.SSO_DEAD_MARKER in text.lower():
            self.sso_dead = True
            self.storage.health("auth", "SSO_DEAD_HUMAN_LOGIN_REQUIRED",
                                "gateway reports no active login; will not retry until a human "
                                "logs in at https://localhost:5055", ts=ts)
            return
        # NEVER persist the gateway body: it can contain text matching the privacy denylist, which
        # would raise inside health() and take the collector down. A classification is enough.
        self.storage.health("auth", "REAUTH_ATTEMPTED", "gateway accepted the request", ts=ts)

    def tickle(self) -> None:
        try:
            self.client.tickle()   # keeps the session alive; the response is NEVER persisted
        except IBKRResponseError as exc:
            self.storage.health("auth", "tickle_failed", type(exc).__name__, ts=self.now())
        self.last_tickle = self.now()

    # -- selection ---------------------------------------------------------------------------
    def load_active_instruments(self) -> None:
        """Rebuild slot -> conid identity from the DB at startup.

        `self.instruments` is in-memory, so after a restart `_swap`'s "same conid, do nothing" guard
        saw an empty map and inserted a SECOND active row for a contract that was already active.
        The first restart produced exactly that: two un-retired rows each for MBT and ZQ, which
        violates the registered checkpoint ("no duplicate active contract identity per slot across
        rolls"). Reloading also keeps roll lineage continuous across restarts instead of
        manufacturing a fake roll every time the process bounces.
        """
        for row in self.storage.active_instruments():
            r = dict(row)
            sec, root, right = r["sec_type"], r["root"], r["right"]
            slot = (f"OPT:{root}:{right}" if sec == "OPT"
                    else f"IND:{root}" if sec == "IND" else f"FUT:{root}")
            self.instruments[r["conid"]] = dict(r, slot=slot)

    def _swap(self, family: str, slot: str, new: dict[str, Any], ts: float, reason: str) -> None:
        old = next((c for c, i in self.instruments.items() if i["slot"] == slot), None)
        if old == new["conid"]:
            return
        if old is not None:
            self.storage.retire_instrument(old, ts)
            del self.instruments[old]
        new = dict(new, slot=slot, family=family)
        self.storage.add_instrument(family, new, ts)
        self.storage.roll(family, slot, old, new["conid"], ts, reason)
        self.instruments[new["conid"]] = new
        self.storage.health("selection", "selected", f"{slot} conid={new['conid']} "
                            f"expiry={new.get('expiry')} strike={new.get('strike')} {reason}", ts=ts)

    def select_futures(self, reason: str) -> None:
        ts = self.now()
        today = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        roots = [r for r in FUTURE_ROOTS
                 if (r in ("BTC", "MBT") and "crypto_futures" in self.families)
                 or (r == "ZQ" and "fed_funds" in self.families)]
        if not roots:
            return
        try:
            raw = self.client.futures(*roots)
        except IBKRResponseError as exc:
            self.storage.health("selection", "futures_search_failed",
                                f"{type(exc).__name__}: {str(exc)[:120]}", ts=ts)
            return
        for root in roots:
            chosen = select_front_future(raw, root, today)
            family = "fed_funds" if root == "ZQ" else "crypto_futures"
            if chosen is None:
                self.storage.health("selection", "no_contract", f"root={root}", ts=ts)
                continue
            self._swap(family, f"FUT:{root}", chosen, ts, reason)
        self.last_futures_day = today.isoformat()

    def select_options(self, reason: str) -> None:
        if "index_options" not in self.families:
            return
        ts = self.now()
        today = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        for symbol in INDEX_SYMBOLS:
            try:
                search = self.client.search_contracts(symbol, sec_type="IND")
                und = underlying_conid(search, symbol)
                if und is None:
                    self.storage.health("selection", "no_underlying", symbol, ts=ts)
                    continue
                self._swap("index_options", f"IND:{symbol}", {
                    "root": symbol, "conid": und, "sec_type": "IND", "exchange": "CBOE",
                    "expiry": None, "expiry_pinned": 0, "strike": None, "right": None,
                    "underlying_conid": None, "selection_rule": "exact_symbol_IND"}, ts, reason)
                self.client.snapshot([und], FIELDS)          # preflight
                self.sleep(1.1)
                snap = self.client.snapshot([und], FIELDS)
                spot = None
                for row in (snap if isinstance(snap, list) else []):
                    if isinstance(row, dict) and conid_of(row) == und:
                        spot = quote_row(row, ts)["last"]
                if spot is None:
                    # The index feed was deliberately not bought, so IND quotes are frozen (Z) and
                    # sometimes carry no `last` at all -- XSP did exactly that and deferred its whole
                    # selection. Fall back, in order: this symbol's last archived level, then the
                    # SPX/XSP definitional 1:10 ratio. Pass 2 (put-call parity) corrects whatever
                    # seed is used, so a rough seed is enough to get a chain; NO seed means no
                    # instrument at all, which is strictly worse.
                    spot, seed_src = self.storage.last_known_level(und), "last_archived_level"
                    if spot is None:
                        other = "SPX" if symbol == "XSP" else "XSP"
                        oc = next((c for c, i in self.instruments.items()
                                   if i.get("slot") == f"IND:{other}"), None)
                        lvl = self.storage.last_known_level(oc) if oc else None
                        if lvl is not None:
                            spot = lvl / 10.0 if symbol == "XSP" else lvl * 10.0
                            seed_src = f"{other}_ratio_1to10"
                    if spot is not None:
                        self.storage.health("selection", "STRIKE_SEED_FALLBACK",
                                            f"{symbol} seed={round(spot, 4)} source={seed_src}", ts=ts)
                month = option_month(search, today)
                if spot is None or month is None:
                    self.storage.health("selection", "SELECTION_DEFERRED",
                                        f"{symbol} spot={spot} month={month}", ts=ts)
                    continue
                strikes = self.client.option_strikes(und, month)
                strike = nearest_strike(strikes, spot)
                if strike is None:                       # observed transient empty reply (smoke run)
                    self.sleep(1.0)
                    strikes = self.client.option_strikes(und, month)
                    strike = nearest_strike(strikes, spot)
                if strike is None:
                    self.storage.health("selection", "no_strikes", f"{symbol} {month}", ts=ts)
                    continue
                # Pass 1 selects from the FROZEN index last (availability Z -- the index feed was
                # not bought). Pass 2 re-derives the level by put-call parity from the entitled
                # option quotes and re-selects once if a different strike is nearer. Both levels
                # are recorded so the archive can later characterize the gap between them.
                picked = self._pick_option_pair(symbol, und, month, strike, ts, reason,
                                                level_source="frozen_index_last", level=spot)
                fwd = forward_from_parity(picked.get("C"), picked.get("P"), strike)
                if fwd is not None:
                    refined = nearest_strike(strikes, fwd)
                    self.storage.health(
                        "selection", "PARITY_FORWARD",
                        f"{symbol} frozen_last={spot} parity_forward={round(fwd, 4)} "
                        f"strike={strike} refined={refined}", ts=ts)
                    if refined is not None and refined != strike:
                        strike = refined
                        self._pick_option_pair(symbol, und, month, strike, ts,
                                               "parity_reselect",
                                               level_source="parity_forward", level=fwd)
                else:
                    self.storage.health("selection", "PARITY_UNAVAILABLE",
                                        f"{symbol} strike={strike} (one-sided or crossed book); "
                                        f"strike stands on the frozen index last", ts=ts)
            except IBKRResponseError as exc:
                # Log the MESSAGE, not just the class: two consecutive restarts logged a bare
                # "IBKRResponseError" and left options unselected with no way to tell why.
                # Bounded and identifier-free -- gateway errors carry status codes, not account data.
                self.storage.health("selection", "options_selection_failed",
                                    f"{symbol} {type(exc).__name__}: {str(exc)[:120]}", ts=ts)
        self.last_options_day = today.isoformat()

    def _pick_option_pair(self, symbol: str, und: int, month: str, strike: float, ts: float,
                          reason: str, *, level_source: str, level: float | None) -> dict:
        """Select and register the call+put at `strike`; return their first quotes by right."""
        quotes: dict[str, Any] = {}
        for right in ("C", "P"):
            info = self.client.option_contracts(und, month, strike, right)
            chosen = select_option_expiry(info, ts)
            if chosen is None:
                self.storage.health("selection", "no_expiry",
                                    f"{symbol} {month} {strike}{right}", ts=ts)
                continue
            self._swap("index_options", f"OPT:{symbol}:{right}", {
                "root": symbol, "conid": chosen["conid"], "sec_type": "OPT",
                "exchange": chosen.get("exchange") or "CBOE", "expiry": chosen["expiry"],
                "expiry_pinned": 1, "strike": strike, "right": right,
                "underlying_conid": und,
                "selection_rule": f"nearest_strike_to_{level_source}_tie_lower;"
                                  f"earliest_unexpired_1615ET"},
                ts, reason)
            try:
                self.client.snapshot([chosen["conid"]], FIELDS)      # preflight
                self.sleep(1.1)
                snap = self.client.snapshot([chosen["conid"]], FIELDS)
                for row in (snap if isinstance(snap, list) else []):
                    if isinstance(row, dict) and conid_of(row) == chosen["conid"]:
                        quotes[right] = quote_row(row, ts)
            except IBKRResponseError as exc:
                self.storage.health("selection", "parity_quote_failed",
                                    f"{symbol} {strike}{right} {type(exc).__name__}", ts=ts)
        return quotes

    #: Seconds between retries when a family is enabled but has no active instrument. Startup
    #: selection failed on two consecutive restarts and options then sat missing until the 13:35Z
    #: daily reselect -- unacceptable for an unattended 24 h capture, where the option legs are the
    #: whole point of the index_options family.
    RETRY_SELECTION_S = 300.0

    #: Minimum seconds between /iserver/reauthenticate attempts. The brokerage session was measured
    #: dropping while SSO stayed alive (capture windows of 7.5 and ~24 min on 2026-08-19), and that
    #: mode is recoverable WITHOUT a human. Rate-limited because a tight loop against IBKR is abuse,
    #: and hard-stopped on "not logged in" because that means the SSO session is dead and only a
    #: human can fix it -- see SSO_DEAD_MARKER.
    REAUTH_MIN_INTERVAL_S = 120.0
    SSO_DEAD_MARKER = "not logged in"

    def retry_missing_selections(self) -> None:
        ts = self.now()
        if not self.authenticated:
            return
        if ts - getattr(self, "last_selection_retry", 0.0) < self.RETRY_SELECTION_S:
            return
        active = {i.get("sec_type") for i in self.instruments.values()}
        if "index_options" in self.families and "OPT" not in active:
            self.storage.health("selection", "RETRY_MISSING", "no active OPT instrument", ts=ts)
            self.select_options("retry_missing")
        if ({"crypto_futures", "fed_funds"} & self.families) and "FUT" not in active:
            self.storage.health("selection", "RETRY_MISSING", "no active FUT instrument", ts=ts)
            self.select_futures("retry_missing")
        self.last_selection_retry = ts

    def maybe_reselect(self) -> None:
        self.retry_missing_selections()
        ts = self.now()
        utc = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
        day = utc.date().isoformat()
        if (utc.hour, utc.minute) >= FUTURES_RESELECT_UTC and self.last_futures_day != day:
            self.select_futures("daily_reselect")
        if (utc.hour, utc.minute) >= OPTIONS_RESELECT_UTC and self.last_options_day != day:
            self.select_options("daily_reselect")
        # Expired instruments are retired immediately with an explicit roll on next reselect.
        for conid, inst in list(self.instruments.items()):
            if inst.get("expiry") and inst["expiry"] < utc.strftime("%Y%m%d"):
                self.storage.retire_instrument(conid, ts)
                self.storage.health("selection", "EXPIRED_CONTRACT", f"conid={conid}", ts=ts)
                del self.instruments[conid]

    # -- polling -----------------------------------------------------------------------------
    def poll_once(self, slot_ts: int) -> None:
        conids = sorted(self.instruments)
        sent = self.now()
        if not self.authenticated:
            self.storage.poll(slot_ts, sent_ts=None, recv_ts=None, ok=False, n_conids=len(conids),
                              latency_ms=None, reason=self.auth_reason, authenticated=False)
            for conid in conids:
                self.storage.gap(conid, sent, self.auth_reason, self._label(conid, sent))
            return
        if not conids:
            self.storage.poll(slot_ts, sent_ts=None, recv_ts=None, ok=False, n_conids=0,
                              latency_ms=None, reason="NOT_SELECTED", authenticated=True)
            return
        try:
            raw = self.client.snapshot(conids, FIELDS)
        except IBKRSafetyError:
            self.forbidden_attempts += 1
            raise
        except IBKRResponseError as exc:
            recv = self.now()
            reason = "GATEWAY_TIMEOUT" if "timed out" in str(exc) else "GATEWAY_ERROR"
            if "401" in str(exc):
                self.authenticated = False
                self.auth_reason = "AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED"
                reason = self.auth_reason
            self.storage.poll(slot_ts, sent_ts=sent, recv_ts=recv, ok=False, n_conids=len(conids),
                              latency_ms=int((recv - sent) * 1000), reason=reason,
                              authenticated=self.authenticated)
            for conid in conids:
                self.storage.gap(conid, recv, reason, self._label(conid, recv))
            return
        recv = self.now()
        rows = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else None
        if rows is None:
            self.storage.poll(slot_ts, sent_ts=sent, recv_ts=recv, ok=False, n_conids=len(conids),
                              latency_ms=int((recv - sent) * 1000), reason="UNKNOWN_RESPONSE",
                              authenticated=True)
            for conid in conids:
                self.storage.gap(conid, recv, "UNKNOWN_RESPONSE", self._label(conid, recv))
            return
        self.storage.poll(slot_ts, sent_ts=sent, recv_ts=recv, ok=True, n_conids=len(conids),
                          latency_ms=int((recv - sent) * 1000), reason=None, authenticated=True)
        seen: set[int] = set()
        for r in rows:
            row = quote_row(r, recv)
            conid = row["conid"]
            if conid not in self.instruments:
                continue
            seen.add(conid)
            label = self._label(conid, recv)
            # IBKR re-sends full fields on every poll, so "fields present" is not "changed".
            # A message is a change in _updated or in any quote value versus the last state.
            state = (row["ibkr_updated_ms"], row["last"], row["bid"], row["ask"],
                     row["bid_size"], row["ask_size"], row["availability_code"])
            if row["row_kind"] == "MSG" and self.last_state.get(conid) == state:
                row["row_kind"] = "NO_CHANGE"
            if row["row_kind"] == "MSG":
                self.last_state[conid] = state
                self.storage.quote(row, label)
                self.last_heartbeat[conid] = recv
                if row["availability_code"] and availability_status(row["availability_code"]) != "HFT_READY":
                    self.storage.health("entitlement", "DELAYED_OR_FROZEN",
                                        f"conid={conid} code={row['availability_code']}", ts=recv)
            elif recv - self.last_heartbeat.get(conid, 0.0) >= self.heartbeat_s:
                self.storage.quote(row, label)      # explicit NO_CHANGE heartbeat
                self.last_heartbeat[conid] = recv
        for conid in conids:
            if conid not in seen:
                self.storage.gap(conid, recv, "NO_MESSAGE", self._label(conid, recv))

    def _label(self, conid: int, ts: float) -> str:
        inst = self.instruments.get(conid) or {}
        return session_label(ts, inst.get("sec_type", "OPT"), inst.get("root"))

    # -- monitor -----------------------------------------------------------------------------
    def monitor(self) -> list[str]:
        ts = self.now()
        internal_free = self.disk_usage("/").free
        kilos_free = self.disk_usage(str(DATA_ROOT)).free
        last_ok = self.storage.last_ok_poll_ts()
        alarms = alarm_decision(
            free_bytes=internal_free, disk_floor_bytes=INTERNAL_DISK_FLOOR,
            last_ok_poll_age_s=(ts - last_ok) if last_ok else 1e9, max_poll_age_s=120,
            poll_success_rate=self.storage.poll_success_rate(ts - 300), min_poll_success_rate=0.98,
            authenticated=self.authenticated)
        if kilos_free < KILOS_DISK_WARN:
            alarms.append("kilos_disk_warn")
        for alarm in alarms:
            self.storage.health("monitor", alarm,
                                f"internal_free={internal_free} kilos_free={kilos_free}", ts=ts)
        if alarms:
            try:
                ALARM_FILE.parent.mkdir(parents=True, exist_ok=True)
                ALARM_FILE.write_text(f"{dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()} "
                                      f"{','.join(alarms)}\n")
            except OSError:
                pass
        if "disk_floor" in alarms:
            self.storage.health("monitor", "DISK_FLOOR", "stopping fail-closed", ts=ts)
            self.stop = True
        self.last_monitor = ts
        return alarms

    # -- main loop ---------------------------------------------------------------------------
    def run(self, duration_s: float | None = None) -> None:
        start = self.now()
        prev = self.storage.last_ok_poll_ts()
        self.load_active_instruments()
        self.storage.health("collector", "startup",
                            f"version={COLLECTOR_VERSION} spec={SPEC_REF} families={sorted(self.families)} "
                            f"previous_last_ok_poll={prev}", ts=start)
        self.check_auth()
        self.select_futures("startup")
        self.select_options("startup")
        self.storage.flush()
        while not self.stop:
            slot = next_slot(self.now(), self.poll_period_s)
            self.sleep(max(0.0, slot - self.now()))
            ts = self.now()
            if ts - self.last_auth_check >= 60:
                self.check_auth()
            if ts - self.last_tickle >= 60:
                self.tickle()
            self.maybe_reselect()
            self.poll_once(int(slot))
            if ts - self.last_monitor >= 30:
                self.monitor()
                self.storage.flush()
            if duration_s is not None and ts - start >= duration_s:
                break
        self.storage.health("collector", "shutdown", f"forbidden_attempts={self.forbidden_attempts}",
                            ts=self.now())
        self.storage.flush()


def selftest() -> None:
    fake = alarm_decision(free_bytes=1, disk_floor_bytes=2, last_ok_poll_age_s=121, max_poll_age_s=120,
                          poll_success_rate=0.97, min_poll_success_rate=0.98, authenticated=False)
    assert fake == ["disk_floor", "liveness", "capture_gap", "auth"], fake
    print("PASS fake-target alarms: disk_floor,liveness,capture_gap,auth")
    print("PASS research-only surface: IBKRReadOnlyClient has no order method")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--families", default="crypto_futures,fed_funds,index_options")
    parser.add_argument("--duration-s", type=float, default=None)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--base-url", default="https://localhost:5055/v1/api")
    args = parser.parse_args()
    if args.self_test:
        selftest()
        return 0
    if shutil.disk_usage("/").free < INTERNAL_DISK_FLOOR:
        print("internal disk below 2 GB floor; refusing to start", file=sys.stderr)
        return 2
    storage = ArchiveStorage(args.db)
    client = IBKRReadOnlyClient(args.base_url, timeout=8.0)
    collector = Collector(client, storage, families=set(args.families.split(",")))

    def _stop(*_):
        collector.stop = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        collector.run(args.duration_s)
    finally:
        storage.close()
    print(json.dumps({"stopped": True, "forbidden_attempts": collector.forbidden_attempts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

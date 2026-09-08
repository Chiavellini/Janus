"""The position guard (2026-09-08): the venue's fills are the truth, the rows are the claim."""
from __future__ import annotations

from types import SimpleNamespace

from kernel.execution_protocol import FillRecord, OrderState, Position
from kernel.schema import ExecutionState as X, FillState
from nodes.execute.guard import PositionGuard
from nodes.execute.plan import LegPlan, Plan
from nodes.execute.records import Execution, ExecutionRecords
from nodes.execution.journal import Journal
from nodes.risk.flags import recent_flags
from nodes.risk.kill import KillSwitches
from nodes.risk.limits import ProtectLimits
from nodes.store_tuples.store import TupleStore

T0 = 1_000_000.0
TOK = "111703077666529355124773019378339323057832673993959133601043704236649357701734"


class Venue:
    """Scripted fills/positions/status; records what was asked."""
    def __init__(self, venue, fills=(), positions=None, status=None):
        self.venue, self._fills, self._positions, self._status = venue, list(fills), positions, status
        self.asked = []

    def fills(self, *, since_utc):
        return [f for f in self._fills if f.ts >= since_utc]

    def positions(self):
        return self._positions

    def status(self, cid):
        self.asked.append(cid)
        return self._status or OrderState(self.venue, cid, None, FillState.UNCONFIRMED, 0.0, None, None, "NOT_FOUND", T0)


def _plan():
    first = LegPlan("polymarket", TOK, TOK, "buy_yes", 0.58, 10.0, "ioc", vwap=0.57)
    hedge = LegPlan("kalshi", "KXATPMATCH-26SEP07GEAVAN-GEA", "KXATPMATCH-26SEP07GEAVAN-GEA", "buy_yes", 0.31, 10.0, "ioc", vwap=0.31)
    return Plan("pm:atp:974082:moneyline:v1:10", "pm:atp:974082", "atp", 10.0, first, hedge, 0.9901, 0.0272)


def _world(tmp_path, *, venues, kill=None):
    main = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    worker = TupleStore(tmp_path / "t.sqlite", enforce_volume=False, check_same_thread=False, isolation_level="IMMEDIATE")
    journal, records = Journal(worker), ExecutionRecords(worker)
    g = PositionGuard(venues=venues, journal=journal, records=records, store=main, limits=ProtectLimits(),
                      started_utc=T0, kill=kill, log=lambda *_: None, clock=lambda: T0 + 300)
    return main, journal, records, g


def _gea_row(journal, records, *, state=X.UNKNOWN_PROVIDER_STATE, released=False):
    """The 01:39Z shape: leg A journaled UNCONFIRMED with no venue id, the execution holding with nothing filled."""
    p = _plan()
    ex = Execution("789ad9b2", p.opportunity_id, p.event_id, "atp", "LIMITED_LIVE", 10.0, T0 + 100, first_client_id="a1")
    records.start(ex, plan={"first": p.first.__dict__, "hedge": p.hedge.__dict__, "max_cost": p.max_cost_per_contract, "fee": p.fee_per_contract}, books={})
    records.move(ex, X.LEG_A_SUBMITTED, now=T0 + 100.1)
    from kernel.execution_protocol import OrderRequest
    journal.pending(OrderRequest("polymarket", TOK, TOK, "buy_yes", 0.58, 10.0, "ioc", "a1", p.opportunity_id), mode="LIMITED_LIVE", now=T0 + 100.1)
    if released:
        ex.released = True
    records.move(ex, state, now=T0 + 130, detail="machine error after LEG_A_SUBMITTED")
    return ex


def test_the_gea_shape_is_adopted_corrected_flagged_and_handed_to_protection(tmp_path):
    trade = FillRecord("polymarket", "0xorder", "5fc95d33", 10.175, 0.57, 0.0, True, T0 + 101, True, market_id=TOK, side="buy_yes")
    pm = Venue("polymarket", fills=[trade], positions=[Position("polymarket", TOK, "yes", 10.175, 0.57, T0 + 300)])
    ks = Venue("kalshi", fills=[], positions=[])
    main, journal, records, g = _world(tmp_path, venues={"polymarket": pm, "kalshi": ks})
    _gea_row(journal, records)
    snap = g.fetch()
    assert pm.asked == ["a1"], "the UNCONFIRMED order was re-polled through status()"
    assert snap.adopted == [("a1", "0xorder")] and journal.get("a1")["venue_order_id"] == "0xorder"
    assert journal.get("a1")["state"] == "FILLED" and journal.get("a1")["filled_contracts"] == 10.175
    rep = g.apply(snap)
    ex = records.load("789ad9b2")
    assert ex.first_filled == 10.175 and ex.first_avg_price == 0.57 and ex.unhedged == 10.175 and ex.corrected_utc == T0 + 300
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and rep.corrected == ["789ad9b2"] and rep.to_protect == ["789ad9b2"]
    assert not rep.orphans and not rep.mismatches, "the venue's position matches the fill seen"
    flags = {f for f, in main.con.execute("SELECT DISTINCT flag FROM lane_flags")}
    assert {"UNHEDGED_POSITION", "GUARD_CORRECTED"} <= flags
    # a second pass is quiet: nothing new to correct, the alarm said once
    rep2 = g.apply(g.fetch())
    assert rep2.corrected == [] and not any(x.startswith("UNHEDGED") for x in rep2.findings)
    assert rep2.to_protect == ["789ad9b2"], "but the naked row is still handed over every pass"


def test_a_fill_no_row_claims_is_an_orphan_that_latches_the_live_kill(tmp_path):
    stray = FillRecord("kalshi", "k-777", "kf1", 5.0, 0.40, 0.01, True, T0 + 50, True, market_id="KXMLBGAME-X", side="buy_yes")
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    main, journal, records, g = _world(tmp_path, venues={"kalshi": Venue("kalshi", fills=[stray], positions=[])}, kill=kill)
    rep = g.apply(g.fetch())
    assert rep.orphans == [stray] and any(x.startswith("ORPHAN_FILL") for x in rep.findings)
    assert kill.active(live=True) == ["live"]
    assert recent_flags(tmp_path / "t.sqlite", "ORPHAN_FILL", now=T0 + 300)


def test_a_hedged_execution_whose_fills_match_is_quiet(tmp_path):
    from kernel.execution_protocol import OrderRequest
    p = _plan()
    fa = FillRecord("polymarket", "pa", "f-a", 10.0, 0.57, 0.0, True, T0 + 101, True, market_id=TOK, side="buy_yes")
    fb = FillRecord("kalshi", "kb", "f-b", 10.0, 0.31, 0.02, True, T0 + 102, True, market_id=p.hedge.market_id, side="buy_yes")
    main, journal, records, g = _world(tmp_path, venues={
        "polymarket": Venue("polymarket", [fa], [Position("polymarket", TOK, "yes", 10.0, 0.57, T0 + 300)]),
        "kalshi": Venue("kalshi", [fb], [Position("kalshi", p.hedge.market_id, "yes", 10.0, None, T0 + 300)])})
    ex = Execution("hedged01", p.opportunity_id, p.event_id, "atp", "LIMITED_LIVE", 10.0, T0 + 100, first_client_id="a2",
                   first_filled=10.0, first_avg_price=0.57, hedge_filled=10.0, hedge_avg_price=0.31)
    records.start(ex, plan={"first": p.first.__dict__, "hedge": p.hedge.__dict__, "max_cost": 0.99, "fee": 0.02}, books={})
    for st in (X.LEG_A_SUBMITTED, X.LEG_A_FILLED, X.LEG_B_SUBMITTED, X.LEG_B_FILLED, X.HEDGED):
        records.move(ex, st, now=T0 + 101)
    journal.pending(OrderRequest("polymarket", TOK, TOK, "buy_yes", 0.58, 10.0, "ioc", "a2", p.opportunity_id), mode="LIMITED_LIVE", now=T0 + 100.5)
    journal.pending(OrderRequest("kalshi", p.hedge.market_id, p.hedge.market_id, "buy_yes", 0.31, 10.0, "ioc", "b2", p.opportunity_id, hedge=True), mode="LIMITED_LIVE", now=T0 + 101.5)
    from kernel.execution_protocol import Ack
    journal.record(Ack("polymarket", "a2", "pa", FillState.FILLED, 10.0, 0.57, 0.0, "matched", T0 + 101), kind="ack")
    journal.record(Ack("kalshi", "b2", "kb", FillState.FILLED, 10.0, 0.31, 0.02, "executed", T0 + 102), kind="ack")
    rep = g.apply(g.fetch())
    assert rep.corrected == [] and rep.to_protect == [] and rep.orphans == [] and rep.findings == []


def test_a_released_rejection_the_venue_contradicts_is_reopened(tmp_path):
    trade = FillRecord("polymarket", "0xlate", "late1", 10.0, 0.57, 0.0, True, T0 + 101, True, market_id=TOK, side="buy_yes")
    main, journal, records, g = _world(tmp_path, venues={"polymarket": Venue("polymarket", [trade], None)})
    _gea_row(journal, records, state=X.ORDER_REJECTED, released=True)
    rep = g.apply(g.fetch())
    ex = records.load("789ad9b2")
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and not ex.released and ex.first_filled == 10.0
    assert rep.to_protect == ["789ad9b2"]
    tr = [r[0] for r in records.store.con.execute("SELECT detail FROM execution_transitions WHERE execution_id='789ad9b2' ORDER BY id")]
    assert any(d.startswith("guard reopen") for d in tr) and any(d.startswith("guard: venue fills") for d in tr)


def test_fills_today_carries_settlements_and_young_unconfirmed_orders(tmp_path):
    from kernel.execution_protocol import OrderRequest
    main, journal, records, g = _world(tmp_path, venues={})
    ex = Execution("s1", "o", "e", "mlb", "LIMITED_LIVE", 5.0, T0 + 100)
    records.start(ex, plan={}, books={})
    records.write_unwind_settlement(ex, realized_usd=-0.42, legs=[], now=T0 + 290)
    paper = Execution("p1", "o", "e", "mlb", "PAPER_EXECUTION", 5.0, T0 + 100)
    records.start(paper, plan={}, books={})
    records.write_unwind_settlement(paper, realized_usd=+9.0, legs=[], now=T0 + 291)   # paper: never the breaker's
    journal.pending(OrderRequest("kalshi", "K", "K", "buy_yes", 0.4, 1.0, "ioc", "young", "o"), mode="LIMITED_LIVE", now=T0 + 280)
    journal.pending(OrderRequest("kalshi", "K", "K", "buy_yes", 0.4, 1.0, "ioc", "old", "o"), mode="LIMITED_LIVE", now=T0 - 5000)
    fills = g.fills_today(T0 + 300)
    states = {f.fill_id: f.state for f in fills}
    assert states["s1"] is FillState.FILLED and states["young"] is FillState.UNCONFIRMED and "old" not in states and "p1" not in states
    assert sum(f.realized_usd for f in fills) == -0.42
    from nodes.risk.breaker import LossBreaker
    b = LossBreaker(path=tmp_path / "breaker.json", enforce_volume=False)
    assert b.day_pnl(fills, fills[0].day) is None, "an UNCONFIRMED order keeps the day's PnL unknown"
    assert b.evaluate(fills, max_daily_loss_usd=25.0, day=fills[0].day) is not None


def test_a_position_the_fills_do_not_explain_is_a_mismatch(tmp_path):
    fa = FillRecord("polymarket", "pa", "f-a", 10.0, 0.57, 0.0, True, T0 + 101, True, market_id=TOK, side="buy_yes")
    pm = Venue("polymarket", [fa], [Position("polymarket", TOK, "yes", 25.0, 0.5, T0 + 300)])
    main, journal, records, g = _world(tmp_path, venues={"polymarket": pm})
    rep = g.apply(g.fetch())
    assert rep.mismatches and "venue holds 25" in rep.mismatches[0] and rep.orphans == [fa]

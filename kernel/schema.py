#!/usr/bin/env python3
"""Venue-agnostic market schema. The thing Janus never had.

Phase 1 handled every venue ad hoc: each enumerator wrote its own field names, the candidate-generation stage
carried a hardcoded text extractor per venue, an earlier screen enumerated exactly two trade
directions as literal strings (`A_kalshiYES_pmNO`), and the pair key was the 2-tuple
`(kalshi_ticker, pm_condition_id)`. A third venue meant touching five files. There was no
dataclass, Protocol, registry or normalized record anywhere in the repo.

This module is the fix. Everything downstream — matcher, cover screen, fee engine, wedge
classifier — speaks `NormMarket` and nothing else.

────────────────────────────────────────────────────────────────────────────
THE TWO INVARIANTS THAT MAKE ONE SCHEMA COVER FOUR VENUE SHAPES
────────────────────────────────────────────────────────────────────────────
1. EVERY PRICE IS A YES-PROBABILITY IN [0,1].
   Not cents. Not decimal odds. Not American odds. Conversion happens ONLY inside an adapter,
   never at a call site. This directly prevents the Kilos incident where `kalshi_snapshots.yes_bid`
   (a probability) was read as cents, pricing a 30c ask as 0.3c and manufacturing +37.5c/trade.
   `assert_price_range()` exists to be called on every array at load.

2. EVERY SIZE IS IN CONTRACTS = UNITS OF $1 PAYOUT.
   A sportsbook is then structurally identical to an ask level: a stake limit S at decimal odds d
   is `contracts = S * d` available at `price = 1/d`. A Betfair back at odds d is the same. This
   is what lets a one-sided bookmaker price and a two-sided CLOB share one cover enumerator.

Orientation lives on the OUTCOME (`line_signed`), never in the key. `CanonicalKey.participants`
is a SORTED tuple, because home/away designation is not reliable across venues — Polymarket's own
rules say a rescheduled soccer match with reversed home/away is "fundamentally changed". Blocking
on an oriented pair silently drops half the candidates.

No network. No I/O. Pure data + validation, so it is unit-testable against frozen fixtures and
`normalize()` stays deterministic (the byte-identical-on-rerun gate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

# ══════════════════════════════════════════════════════════════════════════
# Controlled vocabularies — small on purpose. An unknown value is an error,
# never a silent passthrough, because a typo'd market_type does not fail; it
# just never matches, and a matcher that silently drops is how you get n=35.
# ══════════════════════════════════════════════════════════════════════════

#: Bet/market families. Follows the SportsGameOdds `betTypeID` decomposition.
MARKET_TYPES = frozenset({"moneyline", "spread", "total", "btts", "prop", "outright"})

#: Period is FIRST CLASS. It is precisely the axis on which venues silently disagree:
#: Polymarket includes overtime by default EXCEPT for soccer, where 90'+stoppage governs.
#: Matching a regulation-time contract to a with-OT contract is a settlement wedge, not a pair.
PERIODS = frozenset({"game", "reg", "h1", "h2", "q1", "q2", "q3", "q4",
                     "p1", "p2", "p3", "set1", "set2", "set3", "set4", "set5"})

#: Where a Book's ladder came from. A REST fallback is labelled, never silently equal to a socket.
BOOK_SOURCES = frozenset({"ws", "rest", "unknown"})

#: Non-participant sides. Participant sides carry a canonical entity id instead.
GENERIC_SIDES = frozenset({"over", "under", "draw", "yes", "no"})


class OpportunityStatus(str, Enum):
    """Where one candidate cover stands. NEVER collapse these: NO_EDGE, BLOCKED_DEPTH,
    BLOCKED_STALE and BLOCKED_RULES are four different conclusions, and a lane that reports one
    uninformative null for all of them cannot say whether the edge exists.

    These names are the faithfulness contract (GATE_TO_LIVE step 4 rebuilds every logged decision
    by importing the runner's own constants). Name once; never rename.
    """
    DISCOVERED = "DISCOVERED"                      # gross edge > 0 but below the execution threshold
    BLOCKED_MATCH = "BLOCKED_MATCH"                # identity not proven (two books are one, no pair)
    BLOCKED_RULES = "BLOCKED_RULES"                # exhaustiveness or settlement equivalence unproven
    BLOCKED_STALE = "BLOCKED_STALE"                # a book is not SYNCED, fresh, and verified
    BLOCKED_DEPTH = "BLOCKED_DEPTH"                # the ladder cannot fill the size
    BLOCKED_FEES = "BLOCKED_FEES"                  # gross edge > 0, fee-net edge <= 0
    BLOCKED_BALANCE = "BLOCKED_BALANCE"            # capital or venue balance cannot cover it
    NO_EDGE = "NO_EDGE"                            # the venues agree: gross cost >= 1
    PROFITABLE_UNEXECUTED = "PROFITABLE_UNEXECUTED"  # clears the execution threshold; not sent
    EXECUTION_PENDING = "EXECUTION_PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    HEDGED = "HEDGED"
    FAILED_HEDGE = "FAILED_HEDGE"
    SETTLED = "SETTLED"
    RECONCILED = "RECONCILED"

    @property
    def is_block(self) -> bool:
        return self.value.startswith("BLOCKED_")


class ExecutionState(str, Enum):
    """The two-leg state machine. A trade is arbitrage only once it reaches HEDGED; everything
    before that is an unhedged position that was never authorised."""
    DETECTED = "DETECTED"
    VALIDATED = "VALIDATED"
    CAPITAL_RESERVED = "CAPITAL_RESERVED"
    LEG_A_SUBMITTED = "LEG_A_SUBMITTED"
    LEG_A_PARTIAL = "LEG_A_PARTIAL"
    LEG_A_FILLED = "LEG_A_FILLED"
    LEG_B_SUBMITTED = "LEG_B_SUBMITTED"
    LEG_B_PARTIAL = "LEG_B_PARTIAL"
    LEG_B_FILLED = "LEG_B_FILLED"
    HEDGED = "HEDGED"
    #: The protection layer selling the naked side back (2026-09-08): a stage, like LEG_B_SUBMITTED.
    UNWIND_SUBMITTED = "UNWIND_SUBMITTED"
    #: Everything the first leg bought (and any over-hedge) was sold back: nothing is held, the
    #: reservation is released, the realized loss (bounded by the protect cap) is settled at once.
    UNWOUND = "UNWOUND"
    SETTLED = "SETTLED"
    RECONCILED = "RECONCILED"
    # failure states -- each is a distinct fact about the venue, never a retry hint
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    UNKNOWN_PROVIDER_STATE = "UNKNOWN_PROVIDER_STATE"
    PARTIAL_FILL = "PARTIAL_FILL"
    HEDGE_UNAVAILABLE = "HEDGE_UNAVAILABLE"
    HEDGE_SLIPPAGE_EXCEEDED = "HEDGE_SLIPPAGE_EXCEEDED"
    MARKET_SUSPENDED = "MARKET_SUSPENDED"
    VENUE_DISCONNECTED = "VENUE_DISCONNECTED"
    BALANCE_CHANGED = "BALANCE_CHANGED"

    @property
    def is_failure(self) -> bool:
        return self in _EXECUTION_FAILURES

    @property
    def holds_position(self) -> bool:
        """A failure that may have left contracts on a venue: leg A filled and the hedge did not
        (fully). Not terminal -- it ends at RECONCILED through the settlement pass, which marks
        the hedged part as a cover and the rest at the venue's result (2026-09-05, F3's STOP)."""
        return self in _HOLDING_FAILURES

    @property
    def is_terminal(self) -> bool:
        return self is ExecutionState.RECONCILED or (self in _EXECUTION_FAILURES and self not in _HOLDING_FAILURES)


_HOLDING_FAILURES = frozenset({
    ExecutionState.PARTIAL_FILL, ExecutionState.HEDGE_SLIPPAGE_EXCEEDED, ExecutionState.UNKNOWN_PROVIDER_STATE,
    # The machine reaches HEDGE_UNAVAILABLE only after leg A filled (a hedge the venue refused), so it
    # holds a position like the others. Until 2026-09-07 it was terminal: leg A filled, never settled,
    # the reservation held for good and no alarm.
    ExecutionState.HEDGE_UNAVAILABLE,
})
_EXECUTION_FAILURES = frozenset({
    ExecutionState.ORDER_REJECTED, ExecutionState.ORDER_TIMEOUT, ExecutionState.UNWOUND,
    ExecutionState.UNKNOWN_PROVIDER_STATE, ExecutionState.PARTIAL_FILL,
    ExecutionState.HEDGE_UNAVAILABLE, ExecutionState.HEDGE_SLIPPAGE_EXCEEDED,
    ExecutionState.MARKET_SUSPENDED, ExecutionState.VENUE_DISCONNECTED,
    ExecutionState.BALANCE_CHANGED,
})


class FillState(str, Enum):
    """Three-way, never two. An unresolved or errored poll is UNCONFIRMED, not UNFILLED:
    collapsing them overstates PnL, blinds the loss breaker, and makes retries double-buy."""
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    UNFILLED = "UNFILLED"        # the venue AUTHORITATIVELY reports nothing filled
    UNCONFIRMED = "UNCONFIRMED"  # no answer, a timeout, an ambiguous answer
    REJECTED = "REJECTED"


class Mode(str, Enum):
    """How much a process is allowed to do. Ordered; a process asserts it never runs above the mode
    it was started with, and NO mode may silently escalate to the next (spec §14)."""
    OFFLINE_REPLAY = "OFFLINE_REPLAY"        # captured frames, paper venues
    SHADOW_LIVE = "SHADOW_LIVE"              # live books, refusing venues: records intent only
    PAPER_EXECUTION = "PAPER_EXECUTION"      # live books, simulated fills against the same books
    DEMO_EXECUTION = "DEMO_EXECUTION"        # Kalshi demo host; Polymarket has no demo -> paper
    LIMITED_LIVE = "LIMITED_LIVE"            # real venues under hard caps from a signed override
    PRODUCTION = "PRODUCTION"

    @property
    def rank(self) -> int:
        return _MODE_ORDER.index(self)

    def allows(self, needed: "Mode") -> bool:
        """True if a process in this mode may perform an action that needs `needed`. OFFLINE_REPLAY
        ranks lowest because it touches nothing live, yet it drives PAPER venues: that one
        exception is named here rather than by reordering the ranks."""
        return self.rank >= needed.rank or (self is Mode.OFFLINE_REPLAY and needed is Mode.PAPER_EXECUTION)

    @property
    def executes(self) -> bool:
        """Whether this mode sends orders to ANY venue, paper included."""
        return self is Mode.OFFLINE_REPLAY or self.rank >= Mode.PAPER_EXECUTION.rank

    @property
    def sends_real_orders(self) -> bool:
        return self.rank >= Mode.DEMO_EXECUTION.rank

    @property
    def risks_capital(self) -> bool:
        return self.rank >= Mode.LIMITED_LIVE.rank


_MODE_ORDER = (Mode.OFFLINE_REPLAY, Mode.SHADOW_LIVE, Mode.PAPER_EXECUTION,
               Mode.DEMO_EXECUTION, Mode.LIMITED_LIVE, Mode.PRODUCTION)


class KeyProvenance(str, Enum):
    """How a CanonicalKey was derived. Determines how much it may be trusted.

    Kalshi's own docs advise AGAINST parsing ticker strings to infer relationships, and recommend
    `series_ticker`/`event_ticker`/`category`/`tags`. So TICKER_PARSE is a high-recall blocking
    signal that must AGREE with another source before a pair is promoted — never ground truth.
    """
    API_STRUCTURED = "api_structured"   # venue exposes the fields directly. Trust.
    TICKER_PARSE = "ticker_parse"       # decoded from an id string. Corroborate before promoting.
    TITLE_REGEX = "title_regex"         # parsed from display text. Weakest.
    LLM_ASSISTED = "llm_assisted"       # proposed by a model. Review queue only, never auto-commit.


class VoidPolicy(str, Enum):
    """What a venue pays when an event does not happen as scheduled.

    This enum is the sports analogue of the measured 5.70% opposite-settle rate that killed the
    crypto two-leg. A book VOIDs and returns stake at par; Polymarket settles at LAST FAIR MARKET
    PRICE. A "hedged" pair across those two is not flat on cancellation — it has real P&L.
    """
    VOID_RETURN_STAKE = "void_return_stake"
    LAST_FAIR_MARKET_PRICE = "last_fair_market_price"
    RESOLVE_FIFTY = "resolve_50"
    UNKNOWN = "unknown"                 # -> the wedge classifier BLOCKS. Never treated as zero risk.


class TiePolicy(str, Enum):
    """Tie/push handling. $0.50 is NOT the same as a returned stake.

    Books use half-point lines specifically to avoid ties, so a whole-number total (push-eligible)
    is a DIFFERENT INSTRUMENT from a half-point total. The schema keeps them apart via `line_abs`.
    """
    PUSH_RETURN_STAKE = "push"
    RESOLVE_FIFTY = "resolve_50"
    THIRD_OUTCOME = "third_outcome"     # explicit 3-way market; the draw is its own leg
    UNKNOWN = "unknown"


# ══════════════════════════════════════════════════════════════════════════
# Validation helpers
# ══════════════════════════════════════════════════════════════════════════

PRICE_EPS = 1e-9


def assert_price_range(values, *, label: str = "price") -> None:
    """Every price in this project is a probability in [0,1]. Assert it, loudly, at every load.

    Exists because the repo has TWO live unit traps in the same field name: `kalshi_snapshots`
    stores probabilities where a reader may expect cents, and the live Kalshi REST API now returns
    decimal-dollar STRINGS (`yes_bid_dollars`). Neither fails loudly on its own.
    """
    for v in (values if isinstance(values, (list, tuple)) else [values]):
        if v is None:
            continue
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"{label}: non-finite {v!r}")
        if f < -PRICE_EPS or f > 1.0 + PRICE_EPS:
            raise ValueError(
                f"{label}: {f!r} outside [0,1]. Prices in this schema are PROBABILITIES, "
                f"not cents and not odds — convert inside the adapter.")


def decimal_odds_to_price(d: float) -> float:
    """Decimal odds -> implied probability. The only sanctioned conversion, adapter-side."""
    if d <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {d!r}")
    return 1.0 / d


def american_odds_to_price(a: float) -> float:
    """American odds -> implied probability. Adapter-side only."""
    if a >= 100:
        return 100.0 / (a + 100.0)
    if a <= -100:
        return -a / (-a + 100.0)
    raise ValueError(f"american odds must be >= +100 or <= -100, got {a!r}")


def stake_to_contracts(stake_usd: float, price: float) -> float:
    """A bookmaker stake limit expressed as contracts = units of $1 payout.

    stake S at price p returns S/p on a win, so it IS S/p contracts offered at p. This single
    line is what makes a one-sided sportsbook quote fit the same `Book` as a CLOB ask level.
    """
    if not (PRICE_EPS < price <= 1.0):
        raise ValueError(f"price must be in (0,1], got {price!r}")
    return stake_usd / price


# ══════════════════════════════════════════════════════════════════════════
# The schema
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CanonicalKey:
    """What makes two markets on different venues THE SAME MARKET.

    This is the phase-1 fix. Matching was done on title-Jaccard, which is actively anti-correlated
    with truth for sports: "Lakers beat Celtics" and "Will the Los Angeles Lakers win?" share
    almost no tokens, while "Lakers vs Celtics Nov 3" and "Lakers vs Celtics Nov 17" share nearly
    all of them. Kalshi already encodes this key structurally; Polymarket needs parsing. Parse
    both, then join on equality.
    """
    league: str                          # "nba","mlb","epl","atp" — controlled per-league vocab
    participants: tuple[str, ...]        # SORTED canonical entity ids. Orientation-free.
    start_utc: int                       # scheduled start, unix seconds
    market_type: str                     # one of MARKET_TYPES
    period: str                          # one of PERIODS
    stat: str = "win"                    # "win","points","goals","strikeouts",...
    subject: str | None = None           # entity the stat attaches to; None = game-level
    line_abs: str | None = None          # Decimal-as-STRING ("45.5"); None for moneyline

    def __post_init__(self) -> None:
        if self.market_type not in MARKET_TYPES:
            raise ValueError(f"unknown market_type {self.market_type!r}; known: {sorted(MARKET_TYPES)}")
        if self.period not in PERIODS:
            raise ValueError(f"unknown period {self.period!r}; known: {sorted(PERIODS)}")
        if tuple(sorted(self.participants)) != tuple(self.participants):
            raise ValueError(
                f"participants must be SORTED for orientation-free blocking, got {self.participants!r}")
        # line_abs is a string on purpose: 45.5 as a float invites 45.499999 and a silent
        # non-match against another venue's 45.5. String equality is exact and debuggable.
        if self.line_abs is not None and not isinstance(self.line_abs, str):
            raise TypeError(f"line_abs must be a string, got {type(self.line_abs).__name__}")

    def blocking_key(self) -> tuple:
        """Coarse key for grouping candidates. Deliberately excludes line and side."""
        return (self.league, self.participants, self.market_type, self.period)


@dataclass(frozen=True)
class Quote:
    """One price level. `price` is a YES-probability; `size` is contracts ($1 payout units)."""
    price: float
    size: float
    is_synthetic: bool = False          # True if folded from the complement side (see Book)

    def __post_init__(self) -> None:
        assert_price_range(self.price, label="Quote.price")
        if self.size < 0:
            raise ValueError(f"size must be >= 0, got {self.size!r}")


@dataclass(frozen=True)
class Book:
    """One outcome's two-sided depth.

    KALSHI FOLDING. Kalshi's orderbook endpoint returns BIDS ONLY — a YES ask is expressible only
    as a NO bid at the complementary price. Any code that reads the returned arrays as if they
    were bids-and-asks sees half the market. Adapters MUST fold:

        yes_asks = [(1 - p, size) for p, size in no_bids]

    and mark those levels `is_synthetic=True`. `fold_complement_bids()` below is the one
    implementation; do not write a second.

    STALENESS. `fetched_utc` is not decoration. Polymarket's rate limiter QUEUES rather than
    rejects, so a throttled response is a STALE quote wearing a fresh wall-clock timestamp. Two
    legs fetched seconds apart, one of them minutes stale, fabricates divergence out of nothing.
    The cover screen hard-rejects on `max_leg_quote_age_s`.

    PROVENANCE. `source` says whether the ladder came off the socket or a REST fallback; a REST
    book is visibly labelled and held to a stricter freshness bound (spec §8). `server_utc` is
    the venue's own timestamp when the frame carries one, else None -- never a local guess.
    `received_mono` is the local monotonic receive clock, immune to wall-clock steps.
    """
    bids: tuple[Quote, ...] = ()        # descending price — liquidity to SELL this outcome into
    asks: tuple[Quote, ...] = ()        # ascending price  — liquidity to BUY this outcome from
    fetched_utc: float = 0.0
    depth_truncated: bool = False
    one_sided: bool = False             # bookmaker: bids empty by construction, not by chance
    source: str = "unknown"             # "ws" | "rest" | "unknown"
    server_utc: float | None = None
    received_mono: float | None = None

    def __post_init__(self) -> None:
        if self.source not in BOOK_SOURCES:
            raise ValueError(f"Book.source must be one of {sorted(BOOK_SOURCES)}, got {self.source!r}")

    @property
    def best_bid(self) -> Quote | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Quote | None:
        return self.asks[0] if self.asks else None

    def depth_to(self, limit_price: float) -> float:
        """Contracts buyable at or below `limit_price`. The capacity primitive.

        Capacity is promoted to a FIRST-PASS screen in this project, not a late portfolio step:
        phase 1's mentions track found capacity ($4 median at touch) binding before edge did.
        """
        return sum(q.size for q in self.asks if q.price <= limit_price + PRICE_EPS)


def fold_complement_bids(bids: tuple[Quote, ...]) -> tuple[Quote, ...]:
    """Complement-side bids -> this side's asks, ascending. The Kalshi fold, in one place.

    A NO bid at p IS a YES ask at 1-p in the same book. This is also why single-condition YES+NO
    arbitrage is structurally impossible on Kalshi rather than merely competed away:
    `yes_ask + no_ask = 2 - (yes_bid + no_bid) >= 1` identically. Verified 0 exceptions in
    124,437 markets.
    """
    out = [Quote(price=1.0 - q.price, size=q.size, is_synthetic=True) for q in bids]
    return tuple(sorted(out, key=lambda q: q.price))


@dataclass(frozen=True)
class Outcome:
    """One tradeable leg of a market. Orientation lives HERE, not in the CanonicalKey."""
    outcome_id: str                     # venue-native (clobTokenId / ticker / selectionId)
    canonical_side: str                 # participant id, or a member of GENERIC_SIDES
    book: Book
    line_signed: str | None = None      # "-3.5" from this side's view; None for moneyline
    can_sell: bool = True               # can you exit before resolution
    can_short_direct: bool = False      # can you open a naked short (vs buying the complement)
    complement_of: str | None = None    # outcome_id this is the arithmetic complement of


@dataclass(frozen=True)
class SettleRef:
    """How this venue decides who won. Input to the wedge classifier.

    `provenance` is load-bearing: a field marked "assumed" makes the classifier BLOCK, not shrug.
    An unknown ruleset is not zero risk. Pricing an unmodelled wedge at zero is exactly what made
    the crypto pair look like 100c when it was worth 94.30c.
    """
    source_agency: str | None = None    # Kalshi names one per contract, filed with the CFTC
    oracle: str | None = None           # "uma","chainlink","brti","pyth","official_league"
    void_policy: VoidPolicy = VoidPolicy.UNKNOWN
    tie_policy: TiePolicy = TiePolicy.UNKNOWN
    ot_included: bool | None = None     # PM: True by default, False for soccer
    dnp_policy: VoidPolicy = VoidPolicy.UNKNOWN
    retirement_policy: str | None = None
    revision_policy: str | None = None  # books never reprice after settling; Kalshi may
    dispute_mechanism: str | None = None  # "none","uma_bond_2h","exchange_review"
    settle_lag_h_p50: float | None = None  # UMA can take days; a book settles in minutes
    terms_url: str | None = None
    provenance: str = "assumed"         # "harvested_pdf"|"api_field"|"venue_default"|"assumed"


@dataclass(frozen=True)
class NormMarket:
    """One market on one venue, normalized. The only record type downstream code sees."""
    venue: str
    liquidity_source: str               # see below — NOT the same as `venue`
    venue_market_id: str
    outcomes: tuple[Outcome, ...]
    fee_model_id: str
    settle_ref: SettleRef
    raw_title: str
    fetched_utc: float

    key: CanonicalKey | None = None
    key_confidence: float = 0.0
    key_provenance: KeyProvenance = KeyProvenance.TITLE_REGEX

    # PROVEN exhaustive, never inferred from len(outcomes). Phase 1 burned four separate scans on
    # this: `mutually_exclusive` does NOT mean exhaustive. KXLAPRIMARY listed 2 candidates with no
    # "other"; band partitions excluded their tails; PM negRisk groups append placeholder legs
    # resting at ask 1.00 (nobel-peace-prize-winner-2026 sampled 20 of 71 actual legs). Buying all
    # legs of a non-exhaustive set guarantees nothing. A partition scan that does not verify
    # exhaustiveness FROM THE RULES TEXT is a random-number generator.
    #
    # This used to be `exhaustive: bool`. A bool can be asserted by any caller; that is what let a
    # grid price 3-way EPL as a two-leg cover. It is now the PROOF itself -- an
    # `ExhaustiveOutcomeSet` minted by `nodes/rules_exhaustive`, opaque to the kernel -- or None.
    proof: object | None = None

    fee_params: Mapping[str, Any] = field(default_factory=dict)
    tick: float = 0.01
    min_order_contracts: float = 1.0
    close_utc: int | None = None
    rules_text: str | None = None
    rules_url: str | None = None

    def outcome(self, outcome_id: str) -> Outcome | None:
        return next((o for o in self.outcomes if o.outcome_id == outcome_id), None)

    @property
    def overround(self) -> float | None:
        """sum(best asks) - 1. The embedded-vig diagnostic.

        For a bookmaker this IS the fee — family (c) charges no commission because the cost is
        already in the price. Recorded for attribution; never double-counted as a fee.
        """
        best = [o.book.best_ask for o in self.outcomes]
        if not best or any(b is None for b in best):
            return None
        return sum(b.price for b in best) - 1.0

    @property
    def max_quote_age_s(self) -> float:
        """Oldest leg quote age within this market, at `fetched_utc`."""
        ages = [self.fetched_utc - o.book.fetched_utc for o in self.outcomes if o.book.fetched_utc]
        return max(ages) if ages else 0.0


# ══════════════════════════════════════════════════════════════════════════
# liquidity_source — the field that prevents arbitraging a book against itself
# ══════════════════════════════════════════════════════════════════════════
#
# Robinhood, Webull and IBKR all ROUTE to Kalshi's order book. Same liquidity, different fee
# layer on top. They are distinct VENUES (different fees, different access) but a single
# LIQUIDITY SOURCE. Without this distinction the cover enumerator will eventually report a
# beautiful arbitrage between Kalshi and Robinhood, which is an accounting error wearing a
# profit's clothes.
#
# Robinhood acquired 90% of MIAXdx in Jan 2026 and may split-route some sports contracts to its
# own venue later; if that is ever confirmed, those contracts get their own liquidity_source.
LIQUIDITY_SOURCES = {
    "kalshi": "kalshi_clob",
    "robinhood": "kalshi_clob",
    "webull": "kalshi_clob",
    "ibkr_kalshi": "kalshi_clob",
    "polymarket": "pm_clob",
    "smarkets": "smarkets_exchange",
    "matchbook": "matchbook_exchange",
    "betfair": "betfair_exchange",
    "sxbet": "sxbet_clob",
    "cloudbet": "cloudbet_sportsbook",
    "pinnacle": "pinnacle_book",
}


def liquidity_source_for(venue: str) -> str:
    """Venue -> liquidity source. Unknown venues get their own, which is the safe default."""
    return LIQUIDITY_SOURCES.get(venue, f"{venue}_unknown")


def selftest() -> None:
    """Assert the invariants hold. Run in CI."""
    # prices are probabilities, and the guard actually fires
    assert_price_range([0.0, 0.5, 1.0])
    for bad in (1.5, -0.01, 50.0):
        try:
            assert_price_range(bad)
            raise AssertionError(f"price guard failed to fire on {bad}")
        except ValueError:
            pass

    # odds conversions
    assert abs(decimal_odds_to_price(2.0) - 0.5) < 1e-12
    assert abs(american_odds_to_price(-110) - (110.0 / 210.0)) < 1e-12
    assert abs(american_odds_to_price(+100) - 0.5) < 1e-12
    # a -110/-110 two-way books an overround of ~4.76%
    assert abs((american_odds_to_price(-110) * 2 - 1.0) - 0.047619) < 1e-5

    # a $500 stake limit at decimal 2.0 is 1000 contracts at price 0.50
    assert abs(stake_to_contracts(500.0, 0.5) - 1000.0) < 1e-9

    # the Kalshi fold: NO bids at 0.22 -> YES asks at 0.78, marked synthetic
    folded = fold_complement_bids((Quote(0.22, 100.0), Quote(0.21, 50.0)))
    assert [round(q.price, 4) for q in folded] == [0.78, 0.79], folded
    assert all(q.is_synthetic for q in folded)

    # participants must be sorted — orientation-free blocking
    k = CanonicalKey(league="nba", participants=("BOS", "LAL"), start_utc=1_777_000_000,
                     market_type="moneyline", period="game")
    assert k.blocking_key() == ("nba", ("BOS", "LAL"), "moneyline", "game")
    ok = dict(league="nba", participants=("BOS", "LAL"), start_utc=1,
              market_type="moneyline", period="game")
    for bad in (
        {"participants": ("LAL", "BOS")},           # unsorted
        {"market_type": "ml"},                      # not in vocabulary
        {"period": "fulltime"},                     # not in vocabulary
    ):
        try:
            CanonicalKey(**{**ok, **bad})
            raise AssertionError(f"CanonicalKey accepted {bad}")
        except ValueError:
            pass

    # there is no proof by default — you must MINT one
    m = NormMarket(venue="kalshi", liquidity_source="kalshi_clob", venue_market_id="X",
                   outcomes=(), fee_model_id="kalshi_quadratic", settle_ref=SettleRef(),
                   raw_title="t", fetched_utc=0.0)
    assert m.proof is None
    assert m.settle_ref.provenance == "assumed"
    assert m.settle_ref.void_policy is VoidPolicy.UNKNOWN

    # the same-book guard
    assert liquidity_source_for("robinhood") == liquidity_source_for("kalshi") == "kalshi_clob"
    assert liquidity_source_for("polymarket") != liquidity_source_for("kalshi")
    assert liquidity_source_for("some_new_venue") == "some_new_venue_unknown"

    # overround: a -110/-110 two-way market
    p = american_odds_to_price(-110)
    two_way = NormMarket(
        venue="pinnacle", liquidity_source="pinnacle_book", venue_market_id="Y",
        outcomes=(
            Outcome("home", "BOS", Book(asks=(Quote(p, 1000.0),), one_sided=True)),
            Outcome("away", "LAL", Book(asks=(Quote(p, 1000.0),), one_sided=True)),
        ),
        fee_model_id="embedded", settle_ref=SettleRef(), raw_title="t", fetched_utc=0.0)
    assert abs(two_way.overround - 0.047619) < 1e-5, two_way.overround

    print("schema selftest OK")


if __name__ == "__main__":
    selftest()

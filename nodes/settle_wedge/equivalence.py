#!/usr/bin/env python3
"""Settlement equivalence as a TYPE. The second proof a cover needs, and their composition.

`nodes/rules_exhaustive` proves the outcome set is complete. This proves the two venues pay the
same thing in every situation the game can end in -- or, where they do not, that the difference
is bounded and priced. Same pattern: a token only `certify()` can mint, from records only
`harvest` produces, against a policy only a human has written. `CoverProof` composes the two and is
what `nodes/cover` requires; a bare ExhaustiveOutcomeSet no longer reaches the pricer.

Unknown is a BLOCK. A template nobody has reviewed, a dimension nobody has ruled on, a bounded
dimension whose probability nobody has measured: each is `NotEquivalent`, with a name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from nodes.rules_exhaustive.rules import ExhaustiveOutcomeSet
from nodes.settle_wedge import evidence as _evidence
from nodes.settle_wedge.harvest import RulesRecord
from nodes.settle_wedge.policy import DIMENSIONS, Verdict, template_for, verdicts_for

_MINT = object()

REJECT_SETTLEMENT = "settlement_not_equivalent"


@dataclass(frozen=True)
class SettlementEquivalence:
    """PROOF that two venue contracts pay equivalently, with the priced residual. Minted only by
    `certify()`."""
    league: str
    market_type: str
    period: str
    venue_a: str
    venue_b: str
    template_a: str
    template_b: str
    rules_hash_a: str
    rules_hash_b: str
    verdicts: tuple[Verdict, ...]
    rates: Mapping[str, float]
    _mint: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._mint is not _MINT:
            raise TypeError("SettlementEquivalence cannot be constructed directly; call certify().")

    @property
    def bounded(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.outcome == "BOUNDED")

    def settlement_buffer(self, legs: Sequence[tuple[str, float]]) -> float:
        """USD per contract reserved for the priced residual, given (venue, fill price) per leg.

        kalshi_fair_vs_pm_half: on cancellation Kalshi pays ~its own price, Polymarket pays 0.5,
        so the cover loses max(0, p_pm - 0.5) when the Polymarket leg is the favourite.
        kalshi_fair_vs_pm_result: on a late makeup Kalshi pays ~its own price and Polymarket pays
        the eventual result, 0 or 1; worst case the Polymarket leg pays 0 -> loss p_pm.
        Each is probability x loss, summed over the bounded dimensions. Conservative by design.
        """
        buf = 0.0
        for v in self.bounded:
            p = self.rates[v.evidence_key]
            for venue, price in legs:
                if venue != "polymarket":
                    continue
                if v.loss_model == "kalshi_fair_vs_pm_half":
                    buf += p * max(0.0, price - 0.5)
                elif v.loss_model == "kalshi_fair_vs_pm_result":
                    buf += p * price
                elif v.loss_model == "pm_half_vs_kalshi_result":
                    # Polymarket pays 0.50 a side while Kalshi pays the result: when the Polymarket
                    # side is the winner the cover collects 0.50 instead of 1.00.
                    buf += p * 0.5
                else:
                    raise ValueError(f"unknown loss model {v.loss_model!r}")
        return buf

    def as_record(self) -> dict:
        return {"league": self.league, "market_type": self.market_type, "period": self.period,
                "venue_a": self.venue_a, "venue_b": self.venue_b, "template_a": self.template_a,
                "template_b": self.template_b, "rules_hash_a": self.rules_hash_a,
                "rules_hash_b": self.rules_hash_b,
                "dimensions": {v.dimension: v.outcome for v in self.verdicts},
                "rates": dict(self.rates)}


@dataclass(frozen=True)
class NotEquivalent:
    """Why the two contracts are not proven equivalent. A BLOCK, with a name."""
    code: str          # TEMPLATE_UNKNOWN | PAIR_UNREVIEWED | DIMENSION_DIFFERENT | DIMENSION_UNKNOWN | EVIDENCE_UNMEASURED | LEAGUE_MISMATCH
    detail: str
    dimension: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


def certify(rec_a: RulesRecord, rec_b: RulesRecord, *, league: str, market_type: str = "moneyline",
            period: str = "game",
            rates: Mapping[str, float] | None = None) -> SettlementEquivalence | NotEquivalent:
    """The ONLY way to obtain a SettlementEquivalence. `rates` defaults to the evidence registry;
    tests inject their own so the buffer arithmetic can be pinned without a measurement."""
    ta, tb = template_for(rec_a.template_hash), template_for(rec_b.template_hash)
    for rec, t in ((rec_a, ta), (rec_b, tb)):
        if t is None:
            return NotEquivalent("TEMPLATE_UNKNOWN",
                                 f"{rec.venue} rules text for {rec.market_id} matches no reviewed template "
                                 f"(template_hash {rec.template_hash}); read it and register it",
                                 context={"venue": rec.venue, "template_hash": rec.template_hash,
                                          "template_text": rec.template_text[:400]})
        if league not in t.leagues:
            return NotEquivalent("LEAGUE_MISMATCH",
                                 f"{t.template_id} is reviewed for {sorted(t.leagues)}, not {league}",
                                 context={"template_id": t.template_id})
    verdicts = verdicts_for(ta.template_id, tb.template_id)
    if verdicts is None:
        return NotEquivalent("PAIR_UNREVIEWED",
                             f"no reviewed verdicts for ({ta.template_id}, {tb.template_id})",
                             context={"template_a": ta.template_id, "template_b": tb.template_id})
    ruled = {v.dimension for v in verdicts}
    missing = [d for d in DIMENSIONS if d not in ruled]
    if missing:
        return NotEquivalent("DIMENSION_UNKNOWN", f"no verdict on {missing}", dimension=missing[0])
    r = _evidence.rates(rates)
    for v in verdicts:
        if v.outcome in ("DIFFERENT", "UNKNOWN"):
            return NotEquivalent("DIMENSION_DIFFERENT" if v.outcome == "DIFFERENT" else "DIMENSION_UNKNOWN",
                                 f"{v.dimension}: {v.detail}", dimension=v.dimension)
        if v.outcome == "BOUNDED":
            if v.evidence_key not in r:
                return NotEquivalent("EVIDENCE_UNMEASURED",
                                     f"{v.dimension} is bounded by {v.evidence_key!r}, which no registered "
                                     f"measurement supplies", dimension=v.dimension,
                                     context={"evidence_key": v.evidence_key})
    used = {v.evidence_key: r[v.evidence_key] for v in verdicts if v.outcome == "BOUNDED"}
    return SettlementEquivalence(league, market_type, period, rec_a.venue, rec_b.venue, ta.template_id,
                                 tb.template_id, rec_a.rules_hash, rec_b.rules_hash, tuple(verdicts),
                                 used, _mint=_MINT)


@dataclass(frozen=True)
class CoverProof:
    """Both proofs, checked against each other. What `nodes/cover` requires."""
    exhaustive: ExhaustiveOutcomeSet
    equivalence: SettlementEquivalence
    _mint: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._mint is not _MINT:
            raise TypeError("CoverProof cannot be constructed directly; call certify_cover().")

    def settlement_buffer(self, legs: Sequence[tuple[str, float]]) -> float:
        # NOTE (2026-09-04): a Polymarket NO leg on a three-way team market is charged like any
        # Polymarket leg, including against the cancellation state in which it actually wins (the
        # team markets resolve No). Conservative by construction; named here, not refined.
        return self.equivalence.settlement_buffer(legs)

    @property
    def outcome_ids(self) -> tuple[str, ...]:
        """The proven outcome set, sorted at mint; what a cover's legs must partition."""
        return tuple(self.exhaustive.outcome_ids)


def certify_cover(exhaustive: ExhaustiveOutcomeSet,
                  equivalence: SettlementEquivalence) -> CoverProof | NotEquivalent:
    if not isinstance(exhaustive, ExhaustiveOutcomeSet) or not isinstance(equivalence, SettlementEquivalence):
        return NotEquivalent("PROOF_MISSING", "a CoverProof needs both an ExhaustiveOutcomeSet and a "
                             "SettlementEquivalence, minted by their own modules")
    key_e = (exhaustive.league, exhaustive.market_type, exhaustive.period)
    key_s = (equivalence.league, equivalence.market_type, equivalence.period)
    if key_e != key_s:
        return NotEquivalent("LEAGUE_MISMATCH", f"exhaustiveness is for {key_e}, equivalence for {key_s}")
    return CoverProof(exhaustive, equivalence, _mint=_MINT)

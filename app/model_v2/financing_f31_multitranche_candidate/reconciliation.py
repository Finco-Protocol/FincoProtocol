"""Candidate multi-tranche source/use reconciliation — released rules, pure.

Mirrors the released F3 reconciliation rules
(``financial_engine/financing/multisenior.run_multisenior_financing``):
aggregate senior = sum of contractual commitments; the gearing cap is a
constraint (never a resizing authority); contractual dated senior draws fund
uses first and the equity allocator fills the residual; a period whose dated
draws exceed its funded uses fails closed; canonical-CFADS coverage of the
TOTAL contractual service of all tranches in each operating period.

Equity commitments (share capital, share premium, other committed equity,
additional equity) are DEPLETING pools across ALL construction periods, in the
released waterfall order (``finco_core.construction.allocator``): a commitment
drawn in one period is no longer available in a later one, and the aggregate
actual draws per source, the senior draws and the total project uses are
reconciled at the end.

``total_project_uses_keur`` / ``period_uses_keur`` / ``cfads_by_period`` are
SUPPLIED canonical authority outputs — the candidate never recomputes project
uses or CFADS, and a missing or invalid CFADS value fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
from typing import Mapping, Optional, Sequence

from finco_core.inputs.financing_instruments import FinancingError

from app.model_v2.financing_f31_multitranche_candidate.schedules import (
    CandidateFacilitySchedule,
    TOLERANCE_KEUR,
)


@dataclass(frozen=True)
class EquityDrawRow:
    """Per-construction-period equity fill after contractual senior draws."""

    period_position: int
    period_uses_keur: float
    senior_draw_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    residual_keur: float


@dataclass(frozen=True)
class MultitrancheReconciliation:
    aggregate_senior_commitment_keur: float
    total_project_uses_keur: float
    gearing_capacity_keur: float
    per_period: tuple[EquityDrawRow, ...]
    sources_uses_residual_keur: float
    additional_equity_keur: float
    total_senior_drawn_keur: float = 0.0
    total_share_capital_drawn_keur: float = 0.0
    total_share_premium_drawn_keur: float = 0.0
    total_other_committed_equity_drawn_keur: float = 0.0
    total_additional_equity_drawn_keur: float = 0.0
    #: (operating period index, TOTAL contractual debt service of all tranches)
    aggregate_service_by_period: tuple[tuple[int, float], ...] = ()


def _equity_fill(residual: float, *, share_capital: float, share_premium: float,
                 other_equity: float, additional_equity: float) -> tuple[float, float, float, float, float]:
    """Released funding order: share capital -> premium -> other -> additional.

    The four amounts are the REMAINING (not yet drawn) commitments at the
    start of the period. Whatever the stack cannot fund is returned as the
    positive leftover (an unfunded use, failed closed by the caller).
    """
    share_capital_used = min(share_capital, max(0.0, residual))
    residual -= share_capital_used
    share_premium_used = min(share_premium, max(0.0, residual))
    residual -= share_premium_used
    other_used = min(other_equity, max(0.0, residual))
    residual -= other_used
    additional_used = min(additional_equity, max(0.0, residual))
    residual -= additional_used
    return share_capital_used, share_premium_used, other_used, additional_used, residual


def reconcile_multitranche_sources_uses(
    facilities: Sequence[CandidateFacilitySchedule],
    *,
    total_project_uses_keur: float,
    period_uses_keur: Sequence[float],
    gearing_ratio: float,
    share_capital_keur: float,
    share_premium_keur: float,
    other_equity_keur: float,
    additional_equity_keur: Optional[float] = None,
    cfads_by_period: Optional[Mapping[int, float]] = None,
) -> MultitrancheReconciliation:
    """Reconcile N tranches against the canonical uses. Fail closed on any
    released rule violation; never resize commitments.

    ``cfads_by_period`` (operating period index -> canonical CFADS, kEUR) is
    REQUIRED evidence: ``None`` (the default) raises
    ``F3_CFADS_EVIDENCE_MISSING`` so coverage of contractual service can never
    be skipped by omission."""
    if not facilities:
        raise FinancingError("F3_MULTITRANCHE_COUNT_UNSUPPORTED", "no facilities")
    if additional_equity_keur is None:
        raise FinancingError(
            "F3_MULTITRANCHE_ADDITIONAL_EQUITY_REQUIRED",
            "the residual equity output of the canonical stack must be "
            "supplied (candidate never sizes equity)")
    total_uses = _amount(total_project_uses_keur, "total_project_uses_keur")
    gearing = _amount(gearing_ratio, "gearing_ratio")
    share_capital = _amount(share_capital_keur, "share_capital_keur")
    share_premium = _amount(share_premium_keur, "share_premium_keur")
    other_equity = _amount(other_equity_keur, "other_equity_keur")
    additional_equity = _amount(additional_equity_keur, "additional_equity_keur")
    uses = tuple(_amount(u, f"period_uses_keur[{k}]") for k, u in enumerate(period_uses_keur))
    senior_total = fsum(f.commitment_keur for f in facilities)
    gearing_capacity = total_uses * gearing
    if senior_total > gearing_capacity + TOLERANCE_KEUR:
        raise FinancingError(
            "F3_AGGREGATE_GEARING_CAP_EXCEEDED",
            f"aggregate senior {senior_total} > gearing capacity "
            f"{gearing_capacity}")
    for facility in facilities:
        if len(facility.construction_draws_keur) != len(uses):
            raise FinancingError(
                "F3_CONSTRUCTION_USES_DO_NOT_RECONCILE",
                f"{facility.instrument_id}: {len(facility.construction_draws_keur)} "
                f"dated draw periods vs {len(uses)} construction use periods")
        drawn_total = fsum(facility.construction_draws_keur)
        if drawn_total > facility.commitment_keur + TOLERANCE_KEUR:
            raise FinancingError(
                "F3_DRAWDOWN_EXCEEDS_COMMITMENT",
                f"{facility.instrument_id}: dated draws {drawn_total} exceed "
                f"its commitment {facility.commitment_keur}")
    draws_by_period = _draws_by_construction_period(facilities, len(uses))
    if abs(fsum(uses) - total_uses) > TOLERANCE_KEUR:
        raise FinancingError(
            "F3_CONSTRUCTION_USES_DO_NOT_RECONCILE",
            f"period uses {fsum(uses)} != total uses {total_uses}")
    # DEPLETING commitment pools across ALL construction periods: the amount a
    # source has already supplied is never available again.
    remaining = {"share_capital": share_capital, "share_premium": share_premium,
                 "other": other_equity, "additional": additional_equity}
    rows = []
    cumulative_residual = 0.0
    for position, period_uses in enumerate(uses):
        drawn = draws_by_period[position]
        if drawn > period_uses + TOLERANCE_KEUR:
            raise FinancingError(
                "F3_PERIOD_OVERFUNDING",
                f"dated senior draws {drawn} exceed that period's funded "
                f"uses {period_uses}")
        share_capital_used, share_premium_used, other_used, additional_used, leftover = \
            _equity_fill(
                max(0.0, period_uses - drawn),
                share_capital=remaining["share_capital"],
                share_premium=remaining["share_premium"],
                other_equity=remaining["other"],
                additional_equity=remaining["additional"])
        remaining["share_capital"] -= share_capital_used
        remaining["share_premium"] -= share_premium_used
        remaining["other"] -= other_used
        remaining["additional"] -= additional_used
        cumulative_residual += leftover
        rows.append(EquityDrawRow(
            period_position=position, period_uses_keur=period_uses,
            senior_draw_keur=drawn, share_capital_draw_keur=share_capital_used,
            share_premium_draw_keur=share_premium_used,
            other_committed_equity_draw_keur=other_used,
            additional_equity_draw_keur=additional_used,
            residual_keur=leftover))
    # Aggregate reconciliation of ACTUAL allocated source amounts.
    totals = {
        "share_capital": fsum(r.share_capital_draw_keur for r in rows),
        "share_premium": fsum(r.share_premium_draw_keur for r in rows),
        "other": fsum(r.other_committed_equity_draw_keur for r in rows),
        "additional": fsum(r.additional_equity_draw_keur for r in rows),
    }
    commitments = {"share_capital": share_capital, "share_premium": share_premium,
                   "other": other_equity, "additional": additional_equity}
    for source, drawn_total in totals.items():
        if drawn_total > commitments[source] + TOLERANCE_KEUR:
            raise FinancingError(
                "F3_EQUITY_COMMITMENT_EXCEEDED",
                f"{source}: drawn {drawn_total} exceeds its commitment {commitments[source]}")
    senior_drawn = fsum(r.senior_draw_keur for r in rows)
    allocated = senior_drawn + fsum(totals.values())
    if abs(cumulative_residual) > TOLERANCE_KEUR or abs(allocated - total_uses) > TOLERANCE_KEUR:
        raise FinancingError(
            "F3_SOURCES_USES_UNRECONCILED",
            f"allocated sources {allocated} (unfunded {cumulative_residual}) "
            f"do not equal total project uses {total_uses}")
    service = _aggregate_service_by_period(facilities)
    _check_contractual_service_coverage(service, cfads_by_period)
    return MultitrancheReconciliation(
        aggregate_senior_commitment_keur=senior_total,
        total_project_uses_keur=total_uses,
        gearing_capacity_keur=gearing_capacity,
        per_period=tuple(rows),
        sources_uses_residual_keur=cumulative_residual,
        additional_equity_keur=additional_equity,
        total_senior_drawn_keur=senior_drawn,
        total_share_capital_drawn_keur=totals["share_capital"],
        total_share_premium_drawn_keur=totals["share_premium"],
        total_other_committed_equity_drawn_keur=totals["other"],
        total_additional_equity_drawn_keur=totals["additional"],
        aggregate_service_by_period=tuple(sorted(service.items())))


def _amount(value, label: str) -> float:
    """Finite, non-negative, non-boolean number; anything else fails closed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not isfinite(float(value)) or value < 0:
        raise FinancingError("F3_MULTITRANCHE_INPUT_INVALID",
                             f"{label} must be a finite non-negative number, got {value!r}")
    return float(value)


def _draws_by_construction_period(
        facilities: Sequence[CandidateFacilitySchedule],
        period_count: int) -> tuple[float, ...]:
    """Sum of dated draws across tranches per construction period."""
    return tuple(
        fsum(f.construction_draws_keur[position] for f in facilities)
        for position in range(period_count))


def _aggregate_service_by_period(
        facilities: Sequence[CandidateFacilitySchedule]) -> dict[int, float]:
    """TOTAL contractual debt service of ALL tranches, per operating period."""
    per_period: dict[int, list[float]] = {}
    for facility in facilities:
        if len(facility.period_indices) != len(facility.debt_service_keur):
            raise FinancingError(
                "F3_FACILITY_AGGREGATE_HANDSHAKE_FAILED",
                f"{facility.instrument_id}: period indices and debt service differ in length")
        for index, service in zip(facility.period_indices, facility.debt_service_keur):
            per_period.setdefault(index, []).append(service)
    return {index: fsum(values) for index, values in per_period.items()}


def _check_contractual_service_coverage(
        service_by_period: Mapping[int, float],
        cfads_by_period: Optional[Mapping[int, float]]) -> None:
    """Released rule: contractual service is never resized by available cash.

    The TOTAL service of all tranches in an operating period is compared with
    that period's supplied CFADS — a tranche passing individually proves
    nothing about the aggregate. Every period with contractual service
    REQUIRES a supplied CFADS value: absent evidence is never treated as zero
    or as a pass, and an invalid value (non-finite, boolean, non-numeric) is
    rejected as malformed.
    """
    if cfads_by_period is None:
        raise FinancingError(
            "F3_CFADS_EVIDENCE_MISSING",
            "the canonical CFADS by operating period must be supplied; "
            "coverage of contractual service is never skipped")
    for index in sorted(service_by_period):
        total_service = service_by_period[index]
        if total_service <= TOLERANCE_KEUR:
            continue                      # no contractual service -> no CFADS requirement
        if index not in cfads_by_period:
            raise FinancingError(
                "F3_CFADS_EVIDENCE_MISSING",
                f"no CFADS supplied for operating period {index} with "
                f"contractual service {total_service}")
        cfads = cfads_by_period[index]
        if isinstance(cfads, bool) or not isinstance(cfads, (int, float)) \
                or not isfinite(float(cfads)):
            raise FinancingError(
                "F3_CFADS_EVIDENCE_INVALID",
                f"CFADS for operating period {index} is not a finite number: {cfads!r}")
        if total_service > cfads + TOLERANCE_KEUR:
            raise FinancingError(
                "F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL",
                f"{index}: total contractual service {total_service} of all "
                f"tranches exceeds CFADS {cfads}")

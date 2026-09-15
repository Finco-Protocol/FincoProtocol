"""Pure G2A funding-stack and construction draw reconciliation."""

from __future__ import annotations

import math
from datetime import date

from finco_core.inputs import SponsorFundingMode
from finco_core.construction.allocator import ConstructionPeriodAllocation

from financial_engine.financing.contracts import (
    ConstructionFundingPeriod,
    ConstructionFundingResult,
    NonConstructionFcUse,
)


GENERIC_MVP_DRAW_POLICY = "GENERIC_MVP_SPONSOR_FIRST_LINEAR_USES"


def reconcile_financing_stack(
    *,
    total_project_uses_keur: float,
    final_senior_commitment_keur: float,
    junior_or_other_main_project_funding_keur: float,
    share_capital_keur: float,
    share_premium_keur: float,
    other_equity_funding_before_shl_keur: float,
    sponsor_funding_mode: SponsorFundingMode,
) -> tuple[float, float]:
    """Return (derived SHL cash principal, derived additional equity).

    Canonical sponsor funding stack (G2A_SHARE_PREMIUM_SOURCE_OMITTED fix):
      1. Share Capital
      2. Share Premium  <- explicitly subtracted; not silently aliased
      3. Other explicit committed equity before residual
      4. Derived residual: SHL (SHARE_CAPITAL_THEN_SHL) or additional equity (EQUITY_ONLY)

    residual = Uses - Senior - Junior - Share Capital - Share Premium - Other Committed Equity
    """
    values = (
        total_project_uses_keur,
        final_senior_commitment_keur,
        junior_or_other_main_project_funding_keur,
        share_capital_keur,
        share_premium_keur,
        other_equity_funding_before_shl_keur,
    )
    if any(value < 0.0 for value in values):
        raise ValueError("G2A funding-stack inputs must be non-negative")

    residual = (
        total_project_uses_keur
        - final_senior_commitment_keur
        - junior_or_other_main_project_funding_keur
        - share_capital_keur
        - share_premium_keur
        - other_equity_funding_before_shl_keur
    )
    if residual < -1e-8:
        raise ValueError(
            "G2A_FIXED_SOURCES_EXCEED_TOTAL_PROJECT_USES: "
            f"funding excess={-residual:.9f} kEUR"
        )
    residual = max(0.0, residual)
    if sponsor_funding_mode == SponsorFundingMode.SHARE_CAPITAL_THEN_SHL:
        return residual, 0.0
    if sponsor_funding_mode == SponsorFundingMode.EQUITY_ONLY:
        return 0.0, residual
    raise ValueError(f"Unsupported sponsor_funding_mode={sponsor_funding_mode!r}")


def build_construction_funding_schedule(
    *,
    construction_period_count: int,
    total_project_uses_keur: float,
    senior_keur: float,
    junior_keur: float,
    share_capital_keur: float,
    share_premium_keur: float,
    other_committed_equity_keur: float,
    additional_equity_keur: float,
    shl_cash_keur: float,
    shl_cash_per_period_keur: "tuple[float, ...] | None" = None,
    post_construction_shl_cash_contribution_keur: float = 0.0,
    period_dates: "tuple[tuple[date | None, date | None, date | None], ...] | None" = None,
    period_uses_keur: "tuple[float, ...] | None" = None,
    shl_allocation_per_period_keur: "tuple[float, ...] | None" = None,
    canonical_economic_allocations: "tuple[ConstructionPeriodAllocation, ...] | None" = None,
) -> ConstructionFundingResult:
    """Allocate linear generic uses through the documented sponsor-first waterfall.

    Waterfall order (capital-class transparency):
      Share Capital -> Share Premium -> Other Committed Equity -> Additional Equity
      -> SHL -> Junior -> Senior

    When canonical_economic_allocations is provided (PR-9 path), those allocations
    are used directly as Layer A — no economic waterfall is recomputed and no fallback
    is attempted. Legacy callers (period_uses_keur, shl_allocation_per_period_keur,
    shl_cash_per_period_keur, or none) are unchanged.
    """
    if construction_period_count <= 0:
        raise ValueError("construction_period_count must be positive")
    # Validate period_dates length when provided.
    if period_dates is not None and len(period_dates) != construction_period_count:
        raise ValueError(
            f"G2A_PERIOD_DATES_LENGTH_MISMATCH: period_dates length {len(period_dates)} "
            f"!= construction_period_count {construction_period_count}"
        )
    # PR-9: validate canonical_economic_allocations when provided.
    if canonical_economic_allocations is not None:
        if len(canonical_economic_allocations) != construction_period_count:
            raise ValueError(
                "PR9_CANONICAL_ALLOCATION_LENGTH_MISMATCH: "
                f"canonical_economic_allocations length {len(canonical_economic_allocations)} "
                f"!= construction_period_count {construction_period_count}"
            )
        # Per-row value validation (Section A2.1-1): finite and non-negative before any state mutation.
        _DRAW_FIELDS = (
            "share_capital_draw_keur", "share_premium_draw_keur",
            "other_committed_equity_draw_keur", "additional_equity_draw_keur",
            "shl_draw_keur", "junior_draw_keur", "senior_draw_keur",
        )
        for _ri, _row in enumerate(canonical_economic_allocations):
            for _field in ("period_uses_keur",) + _DRAW_FIELDS + ("total_sources_keur", "residual_keur"):
                _val = getattr(_row, _field)
                if not math.isfinite(_val):
                    raise ValueError(
                        f"PR9_CANONICAL_ALLOCATION_INVALID_VALUE: "
                        f"row={_ri}, field={_field}, value={_val!r} is not finite"
                    )
            if _row.period_uses_keur < 0.0:
                raise ValueError(
                    f"PR9_CANONICAL_ALLOCATION_INVALID_VALUE: "
                    f"row={_ri}, period_uses_keur={_row.period_uses_keur:.9f} < 0"
                )
            for _field in _DRAW_FIELDS:
                _val = getattr(_row, _field)
                if _val < 0.0:
                    raise ValueError(
                        f"PR9_CANONICAL_ALLOCATION_INVALID_VALUE: "
                        f"row={_ri}, field={_field}, value={_val:.9f} < 0 (negative draws prohibited)"
                    )
            # Recompute period sources from primitive draws; do not trust total_sources_keur.
            _computed_sources = (
                _row.share_capital_draw_keur + _row.share_premium_draw_keur
                + _row.other_committed_equity_draw_keur + _row.additional_equity_draw_keur
                + _row.shl_draw_keur + _row.junior_draw_keur + _row.senior_draw_keur
            )
            if abs(_computed_sources - _row.period_uses_keur) > 1e-6:
                raise ValueError(
                    f"PR9_CANONICAL_ALLOCATION_INVALID_VALUE: "
                    f"row={_ri}, computed_sources={_computed_sources:.9f} != "
                    f"period_uses_keur={_row.period_uses_keur:.9f} "
                    f"(primitive draws must balance period uses)"
                )
        # Aggregate source-cap overdraw validation (Section A2-10): no source drawn beyond cap.
        _cap_checks = (
            ("senior", senior_keur, sum(a.senior_draw_keur for a in canonical_economic_allocations)),
            ("shl", shl_cash_keur, sum(a.shl_draw_keur for a in canonical_economic_allocations)),
            ("junior", junior_keur, sum(a.junior_draw_keur for a in canonical_economic_allocations)),
            ("share_capital", share_capital_keur, sum(a.share_capital_draw_keur for a in canonical_economic_allocations)),
            ("share_premium", share_premium_keur, sum(a.share_premium_draw_keur for a in canonical_economic_allocations)),
            ("other_committed_equity", other_committed_equity_keur, sum(a.other_committed_equity_draw_keur for a in canonical_economic_allocations)),
            ("additional_equity", additional_equity_keur, sum(a.additional_equity_draw_keur for a in canonical_economic_allocations)),
        )
        for _src_name, _cap, _total_draw in _cap_checks:
            if _total_draw > _cap + 1e-6:
                raise ValueError(
                    f"PR9_CANONICAL_ALLOCATION_SOURCE_CAP_OVERDRAW: "
                    f"source={_src_name}, total_draw={_total_draw:.9f} > cap={_cap:.9f} kEUR"
                )
    # Validate per-period SHL draws when provided.
    if shl_cash_per_period_keur is not None:
        if len(shl_cash_per_period_keur) != construction_period_count:
            raise ValueError(
                "G2A_SHL_PER_PERIOD_LENGTH_MISMATCH: shl_cash_per_period_keur length "
                f"{len(shl_cash_per_period_keur)} != construction_period_count {construction_period_count}"
            )
        if post_construction_shl_cash_contribution_keur < 0.0 or not math.isfinite(
            post_construction_shl_cash_contribution_keur
        ):
            raise ValueError(
                "G2A_POST_CONSTRUCTION_SHL_CONTRIBUTION_INVALID: "
                f"{post_construction_shl_cash_contribution_keur!r}"
            )
        if abs(
            sum(shl_cash_per_period_keur)
            + post_construction_shl_cash_contribution_keur
            - shl_cash_keur
        ) > 1e-6:
            raise ValueError(
                "G2A_SHL_PER_PERIOD_SUM_MISMATCH: sum of per-period SHL draws "
                f"plus post-construction contribution "
                f"{post_construction_shl_cash_contribution_keur:.6f} != "
                f"shl_cash_keur {shl_cash_keur:.6f}"
            )
    # Validate explicit period uses vector when provided.
    if period_uses_keur is not None:
        if len(period_uses_keur) != construction_period_count:
            raise ValueError(
                "G2A_PERIOD_USES_LENGTH_MISMATCH: period_uses_keur length "
                f"{len(period_uses_keur)} != construction_period_count {construction_period_count}"
            )
        if abs(sum(period_uses_keur) - total_project_uses_keur) > 1e-6:
            raise ValueError(
                "G2A_PERIOD_USES_SUM_MISMATCH: sum of period uses "
                f"{sum(period_uses_keur):.6f} != total_project_uses_keur {total_project_uses_keur:.6f}"
            )
    # Validate SHL allocation vector when provided.
    if shl_allocation_per_period_keur is not None:
        if len(shl_allocation_per_period_keur) != construction_period_count:
            raise ValueError(
                "G2A_SHL_ALLOCATION_LENGTH_MISMATCH: shl_allocation_per_period_keur length "
                f"{len(shl_allocation_per_period_keur)} != construction_period_count {construction_period_count}"
            )
        if sum(shl_allocation_per_period_keur) > shl_cash_keur + 1e-6:
            raise ValueError(
                "G2A_SHL_ALLOCATION_SUM_MISMATCH: construction SHL allocation "
                f"{sum(shl_allocation_per_period_keur):.6f} exceeds "
                f"shl_cash_keur {shl_cash_keur:.6f}"
            )
    source_caps = {
        "share": share_capital_keur,
        "share_premium": share_premium_keur,
        "other_committed": other_committed_equity_keur,
        "additional_equity": additional_equity_keur,
        "shl": shl_cash_keur,
        "junior": junior_keur,
        "senior": senior_keur,
    }
    if abs(sum(source_caps.values()) - total_project_uses_keur) > 1e-7:
        raise ValueError("G2A_SOURCES_DO_NOT_EQUAL_USES")

    remaining = dict(source_caps)
    cumulative = {key: 0.0 for key in source_caps}
    cumulative_uses = 0.0
    opening_unutilised = 0.0  # prefunding bridge roll-forward
    rows: list[ConstructionFundingPeriod] = []
    for index in range(1, construction_period_count + 1):
        draws: dict[str, float] = {}

        if canonical_economic_allocations is not None:
            # PR-9 Layer A: use pre-computed canonical allocations exactly.
            # No recomputation, no fallback. Fail-closed: if the allocation is wrong,
            # the shortfall check below will raise.
            _a = canonical_economic_allocations[index - 1]
            uses = _a.period_uses_keur
            draws = {
                "share": _a.share_capital_draw_keur,
                "share_premium": _a.share_premium_draw_keur,
                "other_committed": _a.other_committed_equity_draw_keur,
                "additional_equity": _a.additional_equity_draw_keur,
                "shl": _a.shl_draw_keur,
                "junior": _a.junior_draw_keur,
                "senior": _a.senior_draw_keur,
            }
            for key in draws:
                remaining[key] -= draws[key]
                cumulative[key] += draws[key]
        elif period_uses_keur is not None:
            uses = period_uses_keur[index - 1]
            if shl_allocation_per_period_keur is not None:
                # BLOCKER 1 fix: Layer A (economic allocation) drives period need; Layer B (cash
                # contribution) is tracked only in the prefunding bridge, NOT subtracted from Uses.
                _econ_shl = shl_allocation_per_period_keur[index - 1]
                draws["shl"] = _econ_shl
                remaining["shl"] -= _econ_shl
                cumulative["shl"] += _econ_shl
                need = uses - _econ_shl
                for key in ("share", "share_premium", "other_committed", "additional_equity",
                            "junior", "senior"):
                    draw = min(need, remaining[key])
                    if draw < -1e-9:
                        raise ValueError(
                            f"G2A_NEGATIVE_SOURCE_DRAW: period={index}, source={key}, draw={draw:.9f}"
                        )
                    draw = max(0.0, draw)
                    draws[key] = draw
                    remaining[key] -= draw
                    cumulative[key] += draw
                    need -= draw
            else:
                # period_uses_keur only (no explicit SHL allocation); default waterfall.
                need = uses
                for key in ("share", "share_premium", "other_committed", "additional_equity",
                            "shl", "junior", "senior"):
                    draw = min(need, remaining[key])
                    draws[key] = draw
                    remaining[key] -= draw
                    cumulative[key] += draw
                    need -= draw
        elif shl_cash_per_period_keur is not None:
            # Legacy: no explicit period uses vector; linear interpolation.
            uses = (
                total_project_uses_keur / construction_period_count
                if index < construction_period_count
                else total_project_uses_keur - cumulative_uses
            )
            # Legacy BLOCKER C fix: no explicit allocation vector; cash == allocation (PRO_RATA).
            # Non-SHL sources fill remaining need in waterfall order.
            draws["shl"] = shl_cash_per_period_keur[index - 1]
            remaining["shl"] -= draws["shl"]
            cumulative["shl"] += draws["shl"]
            need = uses - draws["shl"]
            for key in ("share", "share_premium", "other_committed", "additional_equity",
                        "junior", "senior"):
                draw = min(need, remaining[key])
                draws[key] = draw
                remaining[key] -= draw
                cumulative[key] += draw
                need -= draw
        else:
            uses = (
                total_project_uses_keur / construction_period_count
                if index < construction_period_count
                else total_project_uses_keur - cumulative_uses
            )
            need = uses
            for key in ("share", "share_premium", "other_committed", "additional_equity",
                        "shl", "junior", "senior"):
                draw = min(need, remaining[key])
                draws[key] = draw
                remaining[key] -= draw
                cumulative[key] += draw
                need -= draw

        if abs(uses - sum(draws.values())) > 1e-6:
            raise ValueError(
                f"PR9_CANONICAL_CONSTRUCTION_ALLOCATION_FAIL_CLOSED: "
                f"period={index}, shortfall={uses - sum(draws.values()):.9f} kEUR"
                if canonical_economic_allocations is not None
                else f"G2A_PERIOD_FUNDING_SHORTFALL: period={index}, shortfall={uses - sum(draws.values())}"
            )

        sources = sum(draws.values())
        cumulative_uses += uses
        cumulative_sources = sum(cumulative.values())
        # Populate canonical period dates when provided.
        _p_start: date | None = None
        _p_end: date | None = None
        _cf_date: date | None = None
        if period_dates is not None:
            _p_start, _p_end, _cf_date = period_dates[index - 1]
        # Prefunding bridge fields.
        # draws["shl"] holds the Layer A economic allocation.
        # Layer B (Sponsor cash contribution) comes from shl_cash_per_period_keur when provided.
        _shl_allocation = draws["shl"]   # Layer A: economic allocation
        _shl_contribution = (
            shl_cash_per_period_keur[index - 1]   # Layer B: actual Sponsor cash timing
            if shl_cash_per_period_keur is not None
            else _shl_allocation               # PRO_RATA/legacy: cash == allocation
        )
        _closing_unutilised = opening_unutilised + _shl_contribution - _shl_allocation
        if _closing_unutilised < -1e-6:
            raise ValueError(
                f"G2A_NEGATIVE_UNUTILISED_SHL_CASH: period={index}, "
                f"closing={_closing_unutilised:.9f}"
            )
        _closing_unutilised = max(0.0, _closing_unutilised)
        rows.append(ConstructionFundingPeriod(
            period_index=index,
            project_cash_uses_keur=uses,
            senior_draw_keur=draws["senior"],
            junior_or_other_main_funding_draw_keur=draws["junior"],
            share_capital_draw_keur=draws["share"],
            share_premium_draw_keur=draws["share_premium"],
            other_committed_equity_draw_keur=draws["other_committed"],
            additional_equity_draw_keur=draws["additional_equity"],
            shl_cash_draw_keur=draws["shl"],
            total_sponsor_cash_draw_keur=(
                draws["share"] + draws["share_premium"] + draws["other_committed"]
                + draws["additional_equity"] + draws["shl"]
            ),
            total_sources_keur=sources,
            sources_uses_difference_keur=sources - uses,
            cumulative_project_cash_uses_keur=cumulative_uses,
            cumulative_senior_draw_keur=cumulative["senior"],
            cumulative_junior_or_other_main_funding_draw_keur=cumulative["junior"],
            cumulative_share_capital_draw_keur=cumulative["share"],
            cumulative_share_premium_draw_keur=cumulative["share_premium"],
            cumulative_other_committed_equity_draw_keur=cumulative["other_committed"],
            cumulative_additional_equity_draw_keur=cumulative["additional_equity"],
            cumulative_shl_cash_draw_keur=cumulative["shl"],
            cumulative_total_sources_keur=cumulative_sources,
            cumulative_sources_uses_difference_keur=cumulative_sources - cumulative_uses,
            period_start=_p_start,
            period_end=_p_end,
            cashflow_date=_cf_date,
            shl_allocation_to_uses_keur=_shl_allocation,
            sponsor_shl_cash_contribution_keur=_shl_contribution,
            opening_unutilised_shl_cash_keur=opening_unutilised,
            closing_unutilised_shl_cash_keur=_closing_unutilised,
        ))
        opening_unutilised = _closing_unutilised

    construction_uses_total = cumulative_uses  # sum of all period Uses already accumulated
    _nc_fc_use: "NonConstructionFcUse | None" = None
    if canonical_economic_allocations is not None:
        non_construction_fc_uses = total_project_uses_keur - construction_uses_total
        if non_construction_fc_uses < -1e-6:
            raise ValueError(
                "PR9_CANONICAL_ALLOCATION_USES_SCOPE_MISMATCH: "
                f"sum(canonical period uses)={construction_uses_total:.9f} > "
                f"total_project_uses_keur={total_project_uses_keur:.9f}, "
                f"excess={-non_construction_fc_uses:.9f} kEUR"
            )
        if non_construction_fc_uses > 1e-6:
            # Fund non-construction FC uses (e.g. CASH_DSRA) from remaining sources
            # in waterfall order. These uses do NOT enter Stage-B2 IDC.
            _nc_need = non_construction_fc_uses
            _nc_draws: dict[str, float] = {}
            for _k in ("share", "share_premium", "other_committed", "additional_equity",
                       "shl", "junior", "senior"):
                _d = min(_nc_need, remaining[_k])
                _d = max(0.0, _d)
                _nc_draws[_k] = _d
                remaining[_k] -= _d
                _nc_need -= _d
            _nc_total = sum(_nc_draws.values())
            if abs(_nc_total - non_construction_fc_uses) > 1e-6:
                raise ValueError(
                    "PR9_CANONICAL_ALLOCATION_USES_SCOPE_MISMATCH: "
                    f"non-construction FC uses={non_construction_fc_uses:.9f} kEUR "
                    f"could not be funded from remaining sources (funded={_nc_total:.9f} kEUR)"
                )
            _nc_fc_use = NonConstructionFcUse(
                policy="NON_CONSTRUCTION_FC_USES",
                uses_keur=non_construction_fc_uses,
                senior_draw_keur=_nc_draws["senior"],
                shl_draw_keur=_nc_draws["shl"],
                junior_draw_keur=_nc_draws["junior"],
                share_capital_draw_keur=_nc_draws["share"],
                share_premium_draw_keur=_nc_draws["share_premium"],
                other_committed_equity_draw_keur=_nc_draws["other_committed"],
                additional_equity_draw_keur=_nc_draws["additional_equity"],
                total_sources_keur=_nc_total,
                residual_keur=_nc_total - non_construction_fc_uses,
            )

    # Final combined source-cap assertion (Section A2.1-5): construction + NC draws <= declared caps.
    if canonical_economic_allocations is not None:
        _combined_cap_checks = (
            ("share_capital", share_capital_keur,
             sum(a.share_capital_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.share_capital_draw_keur if _nc_fc_use else 0.0)),
            ("share_premium", share_premium_keur,
             sum(a.share_premium_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.share_premium_draw_keur if _nc_fc_use else 0.0)),
            ("other_committed_equity", other_committed_equity_keur,
             sum(a.other_committed_equity_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.other_committed_equity_draw_keur if _nc_fc_use else 0.0)),
            ("additional_equity", additional_equity_keur,
             sum(a.additional_equity_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.additional_equity_draw_keur if _nc_fc_use else 0.0)),
            ("shl", shl_cash_keur,
             sum(a.shl_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.shl_draw_keur if _nc_fc_use else 0.0)),
            ("junior", junior_keur,
             sum(a.junior_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.junior_draw_keur if _nc_fc_use else 0.0)),
            ("senior", senior_keur,
             sum(a.senior_draw_keur for a in canonical_economic_allocations)
             + (_nc_fc_use.senior_draw_keur if _nc_fc_use else 0.0)),
        )
        for _src_name, _cap, _combined_draw in _combined_cap_checks:
            if _combined_draw > _cap + 1e-6:
                raise ValueError(
                    f"PR9_CANONICAL_ALLOCATION_COMBINED_SOURCE_CAP_OVERDRAW: "
                    f"source={_src_name}, combined_draw={_combined_draw:.9f} > cap={_cap:.9f} kEUR"
                )

    _total_audit_uses = construction_uses_total + (_nc_fc_use.uses_keur if _nc_fc_use else 0.0)
    _total_audit_sources = (
        sum(row.total_sources_keur for row in rows)
        + (_nc_fc_use.total_sources_keur if _nc_fc_use else 0.0)
    )
    return ConstructionFundingResult(
        policy=GENERIC_MVP_DRAW_POLICY,
        periods=tuple(rows),
        maximum_period_difference_keur=max(abs(row.sources_uses_difference_keur) for row in rows),
        maximum_cumulative_difference_keur=max(
            abs(row.cumulative_sources_uses_difference_keur) for row in rows
        ),
        non_construction_fc_use=_nc_fc_use,
        total_audit_uses_keur=_total_audit_uses,
        total_audit_sources_keur=_total_audit_sources,
        total_audit_residual_keur=_total_audit_sources - _total_audit_uses,
    )

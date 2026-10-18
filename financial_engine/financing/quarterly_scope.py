"""RC-7B matched 3/3 candidate: structural scope boundary (D-05, D-09, D-11, D-12).

Every financing, reserve and revenue configuration outside the reviewed
candidate scope is refused BEFORE any calculation with a typed reason. Nothing
is silently zeroed, re-gridded, split or defaulted. Technology admission
(Solar/Wind only) is enforced by the application workspace, which owns the
project type; this module enforces the engine-visible structure.

This module grants no approval. All twelve decisions remain OPEN and product
admission remains closed (see docs/model_v2/RC7B_QUARTERLY_DECISION_MATRIX.md).
"""
from __future__ import annotations

from dateutil.relativedelta import relativedelta

QUARTERLY_SCOPE_AUTHORITY = "RC7B_QUARTERLY_CANDIDATE_SCOPE_V1"


class QuarterlyScopeUnsupported(ValueError):
    """Typed refusal; the message starts with a ``QUARTERLY_*`` reason code."""


def is_quarterly_project(project_inputs) -> bool:
    info = getattr(project_inputs, "info", None)
    return getattr(info, "operating_calendar_policy", None) is not None


def _refuse(code: str, detail: str) -> None:
    raise QuarterlyScopeUnsupported(f"{code}: {detail}")


def require_supported_quarterly_project(pi) -> None:
    """Fail closed unless ``pi`` is inside the RC-7B candidate structure."""
    from finco_core.inputs import (
        DebtServiceReserveSupportMode, PeriodFrequency, ProjectInputs, SponsorFundingMode,
    )
    from finco_core.inputs._models import QuarterlyProjectInfo

    if type(pi) is not ProjectInputs:
        _refuse("QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED",
                f"{type(pi).__name__}: Junior, multi-Senior and other instrument subtypes are excluded (D-12)")
    info = pi.info
    if type(info) is not QuarterlyProjectInfo or info.period_frequency is not PeriodFrequency.QUARTERLY:
        _refuse("QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED", "typed QuarterlyProjectInfo required")

    tech, fin, rev, tax = pi.technical, pi.financing, pi.revenue, pi.tax
    if tech.bess_enabled or tech.bess is not None or getattr(tech, "bess_native_config_json", ""):
        _refuse("QUARTERLY_TECHNOLOGY_UNSUPPORTED", "storage/BESS is outside the candidate scope (D-12)")

    # D-12 financing structure: one Senior, equity-only sponsor funding, no SHL.
    if fin.sponsor_funding_mode is not SponsorFundingMode.EQUITY_ONLY:
        _refuse("QUARTERLY_SHL_UNSUPPORTED",
                f"sponsor_funding_mode={fin.sponsor_funding_mode!r}; only EQUITY_ONLY is admitted (D-12)")
    if fin.shl_amount_keur or fin.clean_shl_principal_keur or fin.shl_construction_day_count_fraction:
        _refuse("QUARTERLY_SHL_UNSUPPORTED", "shareholder-loan amounts are outside the candidate scope (D-12)")
    if fin.junior_or_other_project_funding_keur:
        _refuse("QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED", "junior/other project funding is excluded (D-12)")

    # D-09: reserves are NONE only; refused, never treated as zero.
    if (fin.dsra_support_mode is not DebtServiceReserveSupportMode.NONE
            or fin.dsra_target_policy is not None
            or fin.debt_service_reserve_requirement_keur
            or int(fin.dsra_months or 0) != 0
            or pi.capex.reserve_accounts_keur):
        _refuse("QUARTERLY_RESERVE_POLICY_PENDING_D09",
                "DSRA/DSRF and reserve accounts await an explicit quarterly reserve policy; set dsra_months=0")

    construction = fin.construction_financing
    vat = construction.vat_facility if construction is not None else None
    if vat is not None and getattr(vat, "enabled", False):
        _refuse("QUARTERLY_VAT_FACILITY_UNSUPPORTED", "an enabled VAT facility is outside the candidate scope")

    # D-05 / D-04: revenue and OPEX inputs authored on a period grid or a dated
    # contract are handed to their owners; the candidate refuses them.
    # Subtype-only fields (multistream revenue, native BESS) default to absent.
    if getattr(rev, "multistream_config_json", ""):
        _refuse("QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED", "multistream revenue contracts (Revenue V2/V3)")
    for name in ("co2_sales_schedule", "balancing_cost_schedule"):
        schedule = getattr(rev, name)
        if schedule is not None and schedule.semiannual_values:
            _refuse("QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED", f"revenue.{name} is keyed to six-month rows")
    if rev.first_merchant_operating_period_index is not None or rev.ppa_tariff_by_operating_period:
        _refuse("QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED",
                "first-merchant row index / per-row tariff vector is keyed to six-month rows")
    if rev.market_prices_by_calendar_year_eur_mwh:
        _refuse("QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED", "calendar-year market price curve")
    if rev.ppa_indexation_start_policy is not None or rev.ppa_indexation_start_date is not None:
        _refuse("QUARTERLY_PPA_INDEXATION_HANDOFF_REQUIRED", "dated PPA indexation (PPA-01)")
    if pi.hierarchical_opex_capability is not None:
        _refuse("QUARTERLY_HIERARCHICAL_OPEX_HANDOFF_REQUIRED", "hierarchical OPEX awaits an explicit annual clock")
    ppa_years = float(rev.ppa_term_years)
    if not ppa_years.is_integer():
        _refuse("QUARTERLY_PPA_TERM_UNSUPPORTED", f"ppa_term_years={rev.ppa_term_years!r}")
    if ppa_years > 0:
        _require_boundary_ppa_expiry(info, int(ppa_years))

    # Valuation: a per-model-period quoted rate has no quarterly meaning without
    # explicit authority; only date-based ACT/365 discounting is admitted.
    from finco_core.inputs.valuation import DiscountConvention
    for name in ("project", "coverage"):
        policy = getattr(pi.valuation, name, None) if pi.valuation is not None else None
        if policy is not None and policy.discount_convention is not DiscountConvention.ACT_365_FIXED:
            _refuse("QUARTERLY_VALUATION_CONVENTION_UNSUPPORTED",
                    f"valuation.{name}.discount_convention={policy.discount_convention!r}")

    # D-11: annual limitations are never divided by four.
    if tax.atad_enabled or tax.thin_cap_enabled or tax.interest_limitation_policy is not None:
        _refuse("QUARTERLY_TAX_POLICY_UNSUPPORTED", "ATAD / thin-cap / interest limitation (D-11)")


def _require_boundary_ppa_expiry(info, ppa_years: int) -> None:
    from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency
    engine = PeriodEngine(info.financial_close, info.construction_months, info.horizon_years, ppa_years,
                          frequency=PeriodFrequency.QUARTERLY, cod_date=info.cod_date,
                          operating_calendar_policy=info.operating_calendar_policy)
    expiry = engine.cod + relativedelta(years=ppa_years)
    if any(p.start_date < expiry < p.end_date for p in engine.operation_periods()):
        _refuse("QUARTERLY_INTRAPERIOD_PPA_EXPIRY_UNSUPPORTED",
                f"PPA expiry {expiry.isoformat()} falls inside a quarter; no intra-quarter split is invented (D-05)")


__all__ = ["QUARTERLY_SCOPE_AUTHORITY", "QuarterlyScopeUnsupported", "is_quarterly_project",
           "require_supported_quarterly_project"]

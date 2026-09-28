"""Machine-readable methodology and metric authority registry for FINCO Model.

P1.1 Institutional Model Trust Pack — canonical metric registry.

Each MetricAuthority entry maps a published metric to its exact source file,
function, formula, unit, sign convention, and period timing.  This module is
the SINGLE SOURCE OF TRUTH for "what does this number mean and where does it
come from."

USAGE
-----
    from app.model_methodology_registry import METRIC_REGISTRY, metric_by_key
    m = metric_by_key("ebitda")
    print(m.formula)  # "revenue_keur - opex_keur"
    print(m.source_file)  # "finco_core/ebitda.py"

PROMOTION PROCEDURE
-------------------
When a new quantity is exposed in the product:
1. Add a MetricAuthority entry below.
2. Run test_p1_1_institutional_trust_pack.py — the registry completeness test
   will fail until the source file and function are confirmed to exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricAuthority:
    key: str
    label: str
    unit: str
    sign_convention: str
    formula: str
    source_file: str
    source_function: str
    period_timing: str
    period_frequency: str = "SEMESTRIAL"
    notes: str = ""


@dataclass(frozen=True)
class InstitutionalGap:
    """Explicitly documented limitation for institutional/lender use."""
    key: str
    description: str
    implications: str
    workaround: str = ""


METRIC_REGISTRY: tuple[MetricAuthority, ...] = (
    MetricAuthority(
        key="production",
        label="Production",
        unit="MWh",
        sign_convention="positive = generation",
        formula="capacity_mw × operating_hours × availability × (1 - degradation)^year",
        source_file="finco_core/revenue/generation.py",
        source_function="full_generation_schedule",
        period_timing="period-end",
    ),
    MetricAuthority(
        key="revenue",
        label="Revenue",
        unit="kEUR",
        sign_convention="positive = inflow to SPV",
        formula="production_mwh × blended_tariff_eur_mwh (PPA + merchant blend)",
        source_file="finco_core/revenue/generation.py",
        source_function="full_revenue_schedule",
        period_timing="period-end",
    ),
    MetricAuthority(
        key="opex",
        label="OPEX",
        unit="kEUR",
        sign_convention="positive = cost (expense convention — subtracted in EBITDA)",
        formula="sum(item.y1_amount_keur × (1 + inflation_rate)^(year-1)) × period_day_fraction",
        source_file="finco_core/opex/projections.py",
        source_function="opex_schedule_period",
        period_timing="period-end",
    ),
    MetricAuthority(
        key="ebitda",
        label="EBITDA",
        unit="kEUR",
        sign_convention="positive = operating surplus",
        formula="revenue_keur - opex_keur",
        source_file="finco_core/ebitda.py",
        source_function="calculate_ebitda_keur",
        period_timing="period-end",
    ),
    MetricAuthority(
        key="cash_tax",
        label="Cash Tax Paid",
        unit="kEUR",
        sign_convention="positive = outflow",
        formula="taxable_income × corporate_rate (paid in H2 of each calendar year; H1 accrued only)",
        source_file="financial_engine/tax/engine.py",
        source_function="calculate_tax",
        period_timing="H2 period-end of each tax year",
        notes=(
            "H1 cash tax = 0 (accrual only). "
            "Taxable income = EBITDA − tax_depreciation − deductible_interest + reintegrations. "
            "Two tax periodisation modes exist: CALENDAR_YEAR (default) and "
            "MODEL_YEAR_PAIRING (lender-case override)."
        ),
    ),
    MetricAuthority(
        key="cfads",
        label="CFADS",
        unit="kEUR",
        sign_convention="positive = cash available for debt service (pre-debt)",
        formula="ebitda + financing_income - cash_tax_paid",
        source_file="financial_engine/cfads.py",
        source_function="calculate_canonical_cfads",
        period_timing="period-end",
        notes="Pre-debt-service, pre-DSRA. financing_income from unrestricted cash interest.",
    ),
    MetricAuthority(
        key="dscr",
        label="DSCR — clean engine (authoritative)",
        unit="ratio",
        sign_convention="n/a",
        formula="cfads / debt_service",
        source_file="financial_engine/senior_debt/sculpting.py",
        source_function="build_schedule",
        period_timing="period-end",
        notes=(
            "AUTHORITATIVE definition used for debt sizing and covenant reporting. "
            "Numerator = CFADS (EBITDA + financing_income - cash_tax). "
            "Zero-DS periods: DSCR = None (no division). "
            "IMPORTANT: the legacy utility finco_core/debt/covenants.py::dscr() uses "
            "EBITDA (not CFADS) as numerator and returns inf for zero DS — "
            "this is NOT the sizing or covenant definition."
        ),
    ),
    MetricAuthority(
        key="dscr_legacy_covenant_utility",
        label="DSCR — legacy covenant utility (NOT used for sizing)",
        unit="ratio",
        sign_convention="n/a",
        formula="ebitda_keur / debt_service_keur",
        source_file="finco_core/debt/covenants.py",
        source_function="dscr",
        period_timing="standalone utility only",
        notes=(
            "Legacy utility function. Uses EBITDA, not CFADS, as numerator. "
            "Returns float('inf') when debt_service <= 0. "
            "NOT called from the main debt sizing or waterfall path. "
            "INSTITUTIONAL GAP: the two DSCR definitions differ whenever "
            "financing_income != 0 or cash_tax != 0."
        ),
    ),
    MetricAuthority(
        key="senior_debt_service",
        label="Senior Debt Service",
        unit="kEUR",
        sign_convention="positive = outflow from SPV",
        formula="senior_interest + senior_principal",
        source_file="financial_engine/senior_debt/sculpting.py",
        source_function="build_schedule",
        period_timing="period-end",
    ),
    MetricAuthority(
        key="senior_interest",
        label="Senior Interest",
        unit="kEUR",
        sign_convention="positive = cost to SPV",
        formula="opening_balance × all_in_rate × day_fraction_ACT_360",
        source_file="financial_engine/senior_debt/interest.py",
        source_function="calculate_interest",
        period_timing="period-end",
        notes="ACT/360 exclusive day-count convention.",
    ),
    MetricAuthority(
        key="llcr",
        label="LLCR",
        unit="ratio",
        sign_convention="n/a",
        formula="PV(CFADS over remaining loan life, at senior all-in rate) / outstanding_debt",
        source_file="financial_engine/valuation/model.py",
        source_function="build_decision_complete_valuation_summary",
        period_timing="period-end — informational reporting metric only",
        notes=(
            "LLCR is NOT a debt sizing constraint. It is computed post-sizing as a "
            "covenant reporting metric. In the Solar Reference, LLCR = None "
            "(status: C2_COVERAGE_CFADS_CASE_NOT_CONFIGURED)."
        ),
    ),
    MetricAuthority(
        key="project_irr",
        label="Project IRR (Unlevered)",
        unit="decimal (e.g. 0.1156 = 11.56%)",
        sign_convention="n/a",
        formula=(
            "XIRR over: construction outflows (hard CAPEX, negative) "
            "at construction period dates + operating (EBITDA - unlevered_cash_tax) at period ends"
        ),
        source_file="financial_engine/project_returns/model.py",
        source_function="_project_return",
        period_timing="dated cash-flows",
        notes=(
            "Unlevered: excludes all financing (no senior debt, no SHL, no DSRA). "
            "Authority code: C1_UNLEVERED_HARD_CAPEX_PLUS_EBITDA_MINUS_ZERO_FINANCING_INTEREST_CASH_TAX. "
            "XIRR solver: robust_xirr() = Newton-Raphson primary, bisection fallback."
        ),
    ),
    MetricAuthority(
        key="equity_irr",
        label="Pure Equity IRR (EQUITY_ONLY method)",
        unit="decimal",
        sign_convention="n/a",
        formula=(
            "XIRR over: equity draws (share_capital + share_premium + committed, negative) "
            "at construction dates + legal equity distributions (positive) at operating period ends"
        ),
        source_file="financial_engine/sponsor_returns/model.py",
        source_function="run_project_sponsor_returns_model",
        period_timing="dated cash-flows",
        notes="EQUITY_ONLY method: SHL excluded. Series: pure_equity_net_cashflow_keur.",
    ),
    MetricAuthority(
        key="total_sponsor_xirr",
        label="Total Sponsor XIRR",
        unit="decimal",
        sign_convention="n/a",
        formula=(
            "XIRR over: equity draws + SHL draws (all negative) at construction dates "
            "+ equity distributions + SHL cash interest receipts + SHL principal receipts (all positive)"
        ),
        source_file="financial_engine/sponsor_returns/model.py",
        source_function="run_project_sponsor_returns_model",
        period_timing="dated cash-flows",
        notes=(
            "Includes all sponsor capital: share capital, share premium, SHL. "
            "Series: total_sponsor_net_cashflow_keur."
        ),
    ),
    MetricAuthority(
        key="xirr_year_fraction",
        label="XIRR Year Fraction Convention",
        unit="dimensionless",
        sign_convention="n/a",
        formula="(date - date[0]).days / 365.0",
        source_file="finco_core/sponsor/xirr.py",
        source_function="xirr",
        period_timing="date-aware (not period-averaged)",
        notes=(
            "365-day year, Excel-compatible. "
            "NOT actual/365 or actual/actual — fixed 365. "
            "Institutional gap: periodic annualisation would yield a different result for "
            "very short or very long first periods."
        ),
    ),
)

INSTITUTIONAL_GAPS: tuple[InstitutionalGap, ...] = (
    InstitutionalGap(
        key="DSCR_DUAL_DEFINITION",
        description=(
            "Two DSCR definitions exist in the codebase: "
            "(1) Clean engine (authoritative): CFADS / senior_DS with None for zero-DS periods. "
            "(2) Legacy utility (finco_core/debt/covenants.py): EBITDA / senior_DS with inf for zero-DS."
        ),
        implications=(
            "Results differ whenever financing_income ≠ 0 or cash_tax ≠ 0. "
            "Lender analysis relying on the covenant utility may see a higher numerator than the engine reports."
        ),
        workaround=(
            "Always use financial_engine/senior_debt/sculpting.py::build_schedule for DSCR "
            "in sizing and covenant reporting. The legacy utility is not called from the production path."
        ),
    ),
    InstitutionalGap(
        key="XIRR_NOT_PERIODIC_IRR",
        description=(
            "FINCO uses true date-aware XIRR (365-day year). "
            "Bank models often compute a periodic IRR from semi-annual cash flows then annualise: "
            "(1 + r_semi)^2 - 1. These are numerically different."
        ),
        implications=(
            "Project IRR in FINCO (11.56% for Solar Reference) is not directly comparable "
            "to a periodic-semi-annual IRR × 2. The difference is material for short first periods."
        ),
        workaround="Use the XIRR output directly. Do not convert to periodic convention.",
    ),
    InstitutionalGap(
        key="THIN_CAP_ATAD_ONLY",
        description=(
            "Interest deductibility limitation follows ATAD (Directive 2016/1164/EU): "
            "30% of EBITDA rule with group carve-outs. "
            "Country-specific thin-capitalisation rules (e.g., France 3:1 debt-to-equity, "
            "Netherlands earnings stripping, UK corporate interest restriction) are NOT implemented."
        ),
        implications=(
            "In jurisdictions with thin-cap rules stricter than ATAD, the modelled tax "
            "may be understated. FINCO is a pre-feasibility / indicative model, not a "
            "tax-filing system."
        ),
        workaround="Apply a jurisdiction-specific haircut to deductible interest outside the model.",
    ),
    InstitutionalGap(
        key="DSRF_NO_DRAW_ENGINE",
        description=(
            "DSRF (Debt Service Reserve Facility — letter-of-credit format) has a fee engine "
            "but NO draw engine. The reserve support gate uses DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE. "
            "Actual draws from a LoC are not modelled."
        ),
        implications=(
            "DSRF cash availability is overstated if the LoC would be drawn but the model "
            "treats the gate as open. For project-specific models using DSRF, the distribution "
            "gate Component D (DSRA underfunding) may not fire correctly."
        ),
    ),
    InstitutionalGap(
        key="J_DSRA_NOT_MODELLED",
        description=(
            "Junior DSRA gate (distribution gate Component E) is always False. "
            "J-DSRA balance is hardcoded to 0 for no-junior-debt projects."
        ),
        implications="Not material for single-tranche senior-only capital structures.",
    ),
    InstitutionalGap(
        key="JUNIOR_DEBT_NOT_IMPLEMENTED",
        description=(
            "run_project_shareholder_waterfall_model raises ValueError "
            "('G2C_JUNIOR_DEBT_WATERFALL_NOT_IMPLEMENTED') if junior_or_other_project_funding_keur > 0."
        ),
        implications="Mezzanine or junior tranche structures cannot be modelled.",
    ),
    InstitutionalGap(
        key="SINGLE_CURRENCY_KEUR",
        description="All monetary values are in kEUR. Multi-currency structures are not in scope for V1.",
        implications="FX exposure, currency swaps, and non-EUR projects require conversion outside the model.",
    ),
    InstitutionalGap(
        key="FINANCIAL_STATEMENTS_NOT_CONNECTED_TO_CLEAN_ENGINE",
        description=(
            "The formal balance sheet and cash-flow statement "
            "(finco_core/financial_statements/) use WaterfallPeriod objects from the "
            "legacy engine path. They are not connected to the clean Phase 2C engine result pipeline. "
            "_PHASE_2C_UNAVAILABLE = ('financial_statements', 'returns')."
        ),
        implications=(
            "BS/CFS in the export workbook may reflect a different path than the KPIs "
            "computed via the clean engine. Reconciliation between KPI outputs and formal "
            "financial statements should be treated with care."
        ),
    ),
    InstitutionalGap(
        key="REFINANCING_NOT_MODELLED",
        description="Senior debt runs to its contractual maturity. Refinancing is not implemented.",
        implications=(
            "Models with a practical refinancing date (e.g., year 7 re-fi of a 15-year loan) "
            "cannot capture the lower margin post-re-fi. Project IRR will be understated "
            "if a material refinancing benefit is expected."
        ),
    ),
    InstitutionalGap(
        key="CANONICAL_LAST_RUN_NO_UUID",
        description=(
            "ResolvedExportAuthority.run_id = None for the CANONICAL_LAST_RUN export path. "
            "The workspace stores a compact-timestamp last_runtime_snapshot_id, not a UUID run_id. "
            "Canonical export provenance cannot be cross-referenced to a RunRecord by UUID."
        ),
        implications=(
            "Audit trail linking exported workbook to a specific RunRecord by UUID is not available "
            "on the canonical path. The git_sha and input_fingerprint remain traceable."
        ),
    ),
)

_REGISTRY_BY_KEY: dict[str, MetricAuthority] = {m.key: m for m in METRIC_REGISTRY}
_GAPS_BY_KEY: dict[str, InstitutionalGap] = {g.key: g for g in INSTITUTIONAL_GAPS}


def metric_by_key(key: str) -> MetricAuthority | None:
    return _REGISTRY_BY_KEY.get(key)


def gap_by_key(key: str) -> InstitutionalGap | None:
    return _GAPS_BY_KEY.get(key)


def registry_keys() -> frozenset[str]:
    return frozenset(_REGISTRY_BY_KEY)


def gap_keys() -> frozenset[str]:
    return frozenset(_GAPS_BY_KEY)

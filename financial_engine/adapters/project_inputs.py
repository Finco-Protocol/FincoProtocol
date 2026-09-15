"""financial_engine.adapters.project_inputs — Generic ProjectInputs → OperatingModelInput adapter.

One generic mapping for all projects. No project-code dispatch, no project-name
references, no factory invocation, no file loading.

Depreciation metadata is obtained generically from ProjectInputs.capex.capex_items().
The financing tenor (senior_tenor_years) is mapped explicitly to
financial_cost_useful_life_years so the clean engine carries no financing dependency.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.inputs import ProjectInputs
    from finco_core.inputs.book_depreciable_asset_basis import BookDepreciableAssetBasis

from finco_core.inputs import SHLRepaymentMethod, TaxPeriodisationMode
from finco_core.inputs._models import ShlConstructionInterestMethod

from financial_engine.inputs import (
    CalendarInput,
    CapitalisationGateEquityInput,
    CapexItemForDep,
    DebtSizingCaseInput,
    DepreciationInput,
    InputProvenance,
    OpexInput,
    OpexLineInput,
    OperatingModelInput,
    RevenueInput,
    ShareholderLoanModelInput,
    TechnicalInput,
    YieldScenario,
    PeriodAxisConvention,
)
from financial_engine.ppa_indexation import PpaIndexationStartPolicy
from financial_engine.shl.contracts import ShlDayCountConvention, ShlRepaymentMode


_CLEAN_SHL_REPAYMENT_MODE_MAP = {
    SHLRepaymentMethod.BULLET: ShlRepaymentMode.BULLET,
    SHLRepaymentMethod.CASH_SWEEP: ShlRepaymentMode.CASH_SWEEP,
    # Persisted pre-PR-6 projects may carry this source-description alias. It
    # maps explicitly to the same natural CASH_SWEEP arithmetic and is no
    # longer emitted by canonical factories.
    SHLRepaymentMethod.PARTIAL_PAY_SWEEP: ShlRepaymentMode.CASH_SWEEP,
}


def _coerce_shl_day_count(raw: object) -> ShlDayCountConvention:
    text = str(raw or "").strip().upper().replace("/", "_").replace("-", "_").replace(" ", "_")
    aliases = {
        "ACT_365_FIXED": ShlDayCountConvention.ACT_365_FIXED,
        "ACT_365_FIXED_INCLUSIVE": ShlDayCountConvention.ACT_365_FIXED,
        "ACTUAL_365_FIXED": ShlDayCountConvention.ACT_365_FIXED,
        "ACT_360": ShlDayCountConvention.ACT_360,
        "ACTUAL_360": ShlDayCountConvention.ACT_360,
        "PERIOD_AXIS_ACTUAL_YEAR": ShlDayCountConvention.PERIOD_AXIS_ACTUAL_YEAR,
    }
    if text in aliases:
        return aliases[text]
    raise ValueError(
        "SHL_DAY_COUNT_CONVENTION_EXPLICIT_INPUT_REQUIRED: "
        f"unsupported shl_day_count_convention={raw!r}"
    )


def from_project_inputs(
    inputs: "ProjectInputs",
    *,
    source_id: str = "",
    baseline_commit_sha: str = "",
    book_basis: "BookDepreciableAssetBasis | None" = None,
) -> OperatingModelInput:
    """Adapt a canonical ProjectInputs to a clean OperatingModelInput.

    Maps capex items generically from inputs.capex.capex_items().
    Maps financing.senior_tenor_years → depreciation.financial_cost_useful_life_years
    explicitly (no silent default).
    """
    info = inputs.info
    tech = inputs.technical
    rev = inputs.revenue

    # PR-7: fail-closed yield scenario mapping. Every supported canonical
    # scenario must map explicitly; unknown strings (including P99-1y, which the
    # clean engine does not model) raise instead of silently becoming P50.
    canonical_yield = str(getattr(tech, "yield_scenario", "")).strip()
    if canonical_yield == "P_50":
        yield_scenario = YieldScenario.P50
    elif canonical_yield == "P90-10y":
        yield_scenario = YieldScenario.P90_10Y
    else:
        raise ValueError(
            "YIELD_SCENARIO_EXPLICIT_MAPPING_REQUIRED: "
            f"technical.yield_scenario={tech.yield_scenario!r} has no explicit "
            "clean-engine mapping. Supported values: 'P_50', 'P90-10y'. "
            "P99-1y is not modelled by the clean engine and must fail closed."
        )

    calendar = CalendarInput(
        financial_close=info.financial_close,
        construction_months=info.construction_months,
        horizon_years=info.horizon_years,
        ppa_years=float(rev.ppa_term_years),
        cod_date=info.cod_date,
        period_axis_convention=PeriodAxisConvention(
            getattr(info, "period_axis_convention").value
            if hasattr(getattr(info, "period_axis_convention", None), "value")
            else getattr(
                info,
                "period_axis_convention",
                PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS.value,
            )
        ),
    )

    technical = TechnicalInput(
        capacity_mw=tech.capacity_mw,
        yield_scenario=yield_scenario,
        operating_hours_p50=tech.operating_hours_p50,
        operating_hours_p90_10y=tech.operating_hours_p90_10y,
        pv_degradation=tech.pv_degradation,
        plant_availability=tech.plant_availability,
        grid_availability=tech.grid_availability,
    )

    co2_semiannual: tuple[float, ...] = ()
    if rev.co2_sales_schedule is not None and rev.co2_sales_schedule.semiannual_values:
        co2_semiannual = tuple(rev.co2_sales_schedule.semiannual_values)

    _policy_str = getattr(rev, "ppa_indexation_start_policy", None)
    if _policy_str is None:
        _ppa_policy = None
    else:
        try:
            _ppa_policy = PpaIndexationStartPolicy(_policy_str)
        except ValueError:
            raise ValueError(
                f"Invalid ppa_indexation_start_policy: {_policy_str!r}. "
                f"Valid values: {[e.value for e in PpaIndexationStartPolicy]}"
            )
    _ppa_index_start_date = getattr(rev, "ppa_indexation_start_date", None)

    revenue = RevenueInput(
        ppa_base_tariff_eur_mwh=rev.ppa_base_tariff,
        ppa_term_years=float(rev.ppa_term_years),
        ppa_index=rev.ppa_index,
        ppa_production_share=rev.ppa_production_share,
        market_prices_curve_eur_mwh=tuple(rev.market_prices_curve),
        market_inflation=rev.market_inflation,
        balancing_cost_pv_fraction=rev.balancing_cost_pv,
        balancing_cost_wind_eur_mwh=rev.balancing_cost_wind_eur_mwh,
        co2_enabled=rev.co2_enabled,
        co2_price_eur_mwh=rev.co2_price_eur,
        first_merchant_operating_period_index=rev.first_merchant_operating_period_index,
        co2_price_semiannual_eur_mwh=co2_semiannual,
        co2_price_eur_per_mwh_scalar=rev.co2_certificate_price_eur_per_mwh,
        balancing_cost_eur_per_mwh=rev.balancing_cost_eur_per_mwh,
        ppa_indexation_start_policy=_ppa_policy,
        ppa_indexation_start_date=_ppa_index_start_date,
        merchant_price_calendar_start_year=rev.market_price_calendar_start_year,
        merchant_prices_by_calendar_year_eur_mwh=tuple(
            rev.market_prices_by_calendar_year_eur_mwh
        ),
    )

    opex_items = tuple(
        OpexLineInput(
            name=item.name,
            y1_amount_keur=item.y1_amount_keur,
            annual_inflation=item.annual_inflation,
            step_changes=tuple(item.step_changes),
            percentage_of_opex=item.percentage_of_opex,
        )
        for item in inputs.opex
    )

    _hcap = inputs.hierarchical_opex_capability
    _hier_model = _hcap.opex_model if _hcap is not None else None
    _hier_ext: tuple[tuple[str, tuple[float, ...]], ...] = (
        _hcap.external_annual_series if _hcap is not None else ()
    )
    _senior_tenor: int | None = (
        inputs.financing.senior_tenor_years if _hcap is not None else None
    )

    def _to_dep_item(item) -> CapexItemForDep:
        return CapexItemForDep(
            name=item.name,
            amount_keur=item.amount_keur,
            asset_class_code=item.asset_class.value,
            useful_life_override=item.useful_life_override,
        )

    if book_basis is not None:
        # Canonical basis: convert BookDepreciableAssetBasis components to CapexItemForDep.
        # Replaces the implicit CapexStructure.book_depreciable_capex_items() path.
        book_capex_items_for_dep = tuple(
            CapexItemForDep(
                name=c.name,
                amount_keur=c.amount_keur,
                asset_class_code=c.asset_class_code,
                useful_life_override=c.useful_life_override,
            )
            for c in book_basis.components
            if c.amount_keur != 0.0
        )
    else:
        # Delegate to the canonical builder — not directly to book_depreciable_capex_items().
        from financial_engine.book_basis import build_book_depreciable_asset_basis
        _fallback_basis = build_book_depreciable_asset_basis(inputs.capex)
        book_capex_items_for_dep = tuple(
            CapexItemForDep(
                name=c.name,
                amount_keur=c.amount_keur,
                asset_class_code=c.asset_class_code,
                useful_life_override=c.useful_life_override,
            )
            for c in _fallback_basis.components
            if c.amount_keur != 0.0
        )

    from finco_core.inputs._models import TaxDepreciationMode
    if inputs.tax.tax_dep_basis_source_owned:
        if inputs.tax.tax_depreciation_mode != TaxDepreciationMode.BOOK_BASED_PERCENTAGE:
            raise ValueError(
                f"tax_dep_basis_source_owned=True but tax_depreciation_mode is "
                f"{inputs.tax.tax_depreciation_mode!r}; only BOOK_BASED_PERCENTAGE "
                f"is supported for source-owned book-dep basis."
            )
        pct = inputs.tax.tax_deductible_book_dep_pct
        if abs(pct - 1.0) > 1e-9:
            raise ValueError(
                f"tax_dep_basis_source_owned=True with tax_deductible_book_dep_pct={pct!r}. "
                f"Only pct=1.0 is policy-defined for the book-based tax dep path. "
                f"Partial-percentage book-based tax depreciation is not yet modeled."
            )
        tax_capex_items_for_dep = book_capex_items_for_dep
    else:
        tax_capex_items_for_dep = tuple(
            _to_dep_item(item) for item in inputs.capex.tax_depreciable_capex_items()
        )

    financial_cost_useful_life_years: int = inputs.financing.senior_tenor_years

    return OperatingModelInput(
        calendar=calendar,
        technical=technical,
        revenue=revenue,
        opex=OpexInput(
            items=opex_items,
            hierarchical_model=_hier_model,
            hierarchical_external_annual_series=_hier_ext,
            senior_debt_tenor_years=_senior_tenor,
        ),
        depreciation=DepreciationInput(
            book_capex_items_for_depreciation=book_capex_items_for_dep,
            tax_capex_items_for_depreciation=tax_capex_items_for_dep,
            financial_cost_useful_life_years=financial_cost_useful_life_years,
        ),
        source=InputProvenance(
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
        ),
    )


def build_senior_debt_model_input_from_project_inputs(
    project_inputs: "ProjectInputs",
    source_id: str = "",
    baseline_commit_sha: str = "",
    *,
    debt_sizing_case: DebtSizingCaseInput | None = None,
) -> object:
    """Assemble a complete SeniorDebtModelInput from canonical ProjectInputs.

    The Base operating/tax/debt fundamentals are adapted from ``project_inputs``.
    ProjectInputs.financing.debt_sizing_case is the canonical project-owned bank
    case. Callers may still supply ``debt_sizing_case`` as an explicit test or
    diagnostic override. When both are absent in legacy payloads, the serialized
    FinancingParams default resolves to P90-10y with Base merchant pricing.

    This argument is deliberately project-identity-free. It is the smallest clean
    runtime contract required before persistence/UI surfaces own the same fields.
    """
    from financial_engine.inputs import SeniorDebtModelInput
    from financial_engine.adapters.tax_inputs import build_tax_contract_from_project_inputs
    from financial_engine.senior_debt.project_adapter import (
        build_senior_debt_contract_from_project_inputs,
    )
    from financial_engine.orchestrator import run_operating_model

    operating = from_project_inputs(
        project_inputs, source_id=source_id, baseline_commit_sha=baseline_commit_sha
    )
    op_result = run_operating_model(operating)
    operating_periods = tuple(op_result.periods)

    tax = build_tax_contract_from_project_inputs(
        project_inputs,
        complete_financing_interest_will_be_injected=True,
    )

    policy, inputs = build_senior_debt_contract_from_project_inputs(
        project_inputs, operating_periods
    )

    if debt_sizing_case is not None:
        resolved_debt_sizing_case = debt_sizing_case
    else:
        canonical_case = project_inputs.financing.debt_sizing_case
        resolved_debt_sizing_case = DebtSizingCaseInput(
            production_yield_scenario=YieldScenario(
                canonical_case.production_yield_scenario.value
            ),
            merchant_price_calendar_start_year=canonical_case.merchant_price_calendar_start_year,
            merchant_prices_by_calendar_year_eur_mwh=(
                canonical_case.merchant_prices_by_calendar_year_eur_mwh
            ),
            market_prices_curve_eur_mwh=canonical_case.market_prices_curve_eur_mwh,
            tax_periodisation_mode_override=(
                canonical_case.tax_periodisation_mode_override.value
                if canonical_case.tax_periodisation_mode_override is not None
                else None
            ),
            source_label=canonical_case.source_label,
        )
    shareholder_loan = _build_shareholder_loan_model_input_from_project_inputs(
        project_inputs,
        operating_periods,
        senior_debt_maturity_period_index=policy.maturity_period_index,
    )

    # PR-3B: map FinancingParams DSRA policy to clean CashDsraInput.
    # Uses the SHARED resolver so that adapter and project_uses always agree on
    # the effective requirement — COD_FUNDING_HANDSHAKE invariant.
    # target_policy and dsra_months carry Operation CONFIGURATION only; the latter
    # is the legacy operation-only compatibility alias. The actual dynamic
    # required_balance_schedule is built in the orchestrator AFTER Senior debt solve,
    # using the final Senior DS schedule (causal ordering: Senior → target → model).
    from financial_engine.dsra.contracts import CashDsraInput
    from financial_engine.dsra.target import DsraTargetPolicy
    from financial_engine.financing.reserve_policy import resolve_cash_dsra_requirement_keur
    fin = project_inputs.financing
    _raw_policy = getattr(fin, "dsra_target_policy", None)
    # Fail-closed resolution: None → FIXED_AMOUNT; known string → enum; else raise.
    if _raw_policy is None:
        _target_policy = DsraTargetPolicy.FIXED_AMOUNT
    elif _raw_policy == DsraTargetPolicy.FIXED_AMOUNT.value:
        _target_policy = DsraTargetPolicy.FIXED_AMOUNT
    elif _raw_policy == DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS.value:
        _target_policy = DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS
    else:
        raise ValueError(
            f"DSRA_TARGET_POLICY_INVALID: dsra_target_policy={_raw_policy!r} is not a "
            "recognised DsraTargetPolicy value. "
            f"Supported: None (→ FIXED_AMOUNT), {DsraTargetPolicy.FIXED_AMOUNT.value!r}, "
            f"{DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS.value!r}."
        )
    # Preserve configured Operation months exactly — do not substitute defaults.
    _dsra_months = getattr(fin, "dsra_months", 6)
    if _dsra_months is None:
        _dsra_months = 6  # only None (absent) gets a default; explicit 0 is preserved
    dsra = CashDsraInput(
        mode=fin.dsra_support_mode,
        requirement_keur=resolve_cash_dsra_requirement_keur(project_inputs),
        target_policy=_target_policy,
        dsra_months=_dsra_months,
    )

    # U2 Correction F: pass cash/reserve interest policy for post-solver injection.
    _cash_policy = getattr(project_inputs, "cash_reserve_interest_policy", None)
    return SeniorDebtModelInput(
        operating=operating,
        tax=tax,
        senior_debt_policy=policy,
        senior_debt_inputs=inputs,
        debt_sizing_case=resolved_debt_sizing_case,
        shareholder_loan=shareholder_loan,
        cash_reserve_interest_policy=_cash_policy,
        dsra=dsra,
        capitalisation_gate_equity=(
            CapitalisationGateEquityInput(
                share_capital_keur=project_inputs.financing.share_capital_keur,
                legal_reserve_cap_fraction=project_inputs.tax.legal_reserve_cap,
            )
            if project_inputs.tax.interest_limitation_policy is not None
            else None
        ),
    )


def _build_shareholder_loan_model_input_from_project_inputs(
    project_inputs: "ProjectInputs",
    periods: tuple,
    *,
    senior_debt_maturity_period_index: int | None = None,
) -> ShareholderLoanModelInput | None:
    """Map canonical ProjectInputs to the clean B5 SHL financing contract.

    The mapping is project-identity-free. A project with no configured SHL
    principal produces ``None`` so the senior-debt-only path remains unchanged.
    """
    financing = project_inputs.financing

    clean_principal = getattr(financing, "clean_shl_principal_keur", None)
    if clean_principal is None:
        legacy_amount = float(getattr(financing, "shl_amount_keur", 0.0) or 0.0)
        legacy_method = str(getattr(financing, "shl_repayment_method", "") or "").strip().lower()
        if legacy_amount > 0.0 and legacy_method in {
            "cash_sweep", "partial_pay_sweep", "pik_then_sweep", "fcf_waterfall"
        }:
            raise ValueError(
                "CLEAN_SHL_CONTRACT_AUTHORITY_REQUIRED: "
                "positive legacy SHL with cash-sweep mechanics requires explicit "
                "clean_shl_principal_keur and generic clean SHL contract fields"
            )
        return None
    amount = float(clean_principal or 0.0)
    if amount <= 0.0:
        return None

    rate = float(getattr(financing, "shl_rate", 0.0) or 0.0)
    if rate <= 0.0:
        raise ValueError("ProjectInputs clean SHL requires positive shl_rate")

    method = getattr(financing, "clean_shl_repayment_method", None)
    if not isinstance(method, SHLRepaymentMethod) or method not in _CLEAN_SHL_REPAYMENT_MODE_MAP:
        raise ValueError(
            "UNSUPPORTED_SHL_REPAYMENT_MODE_FAILS_CLOSED: "
            "clean SHL requires typed FinancingParams.clean_shl_repayment_method "
            "with BULLET or CASH_SWEEP semantics, "
            f"got {method!r}"
        )

    construction_dcf_raw = getattr(financing, "shl_construction_day_count_fraction", None)
    if construction_dcf_raw is None:
        raise ValueError(
            "SHL_CONSTRUCTION_DCF_IS_EXPLICIT_INPUT_NOT_BACKSOLVED_FROM_IDC: "
            "shl_construction_day_count_fraction is required for clean SHL"
        )
    construction_dcf = float(construction_dcf_raw)

    maturity = getattr(financing, "shl_maturity_period_index", None)
    if (
        maturity is None
        and method == SHLRepaymentMethod.BULLET
        and int(getattr(financing, "shl_tenor_years", 0) or 0) == 0
        and senior_debt_maturity_period_index is not None
    ):
        # Existing generic financing contract: tenor 0 means bullet one year
        # after Senior payoff. Generic projects are semestrial, hence +2 periods.
        maturity = int(senior_debt_maturity_period_index) + 2
    if maturity is None:
        raise ValueError(
            "SHL_MATURITY_PERIOD_EXPLICIT_INPUT_REQUIRED: "
            "do not infer maturity from model horizon"
        )

    repayment_start = getattr(financing, "shl_principal_eligibility_start_period", None)
    if repayment_start is None and method == SHLRepaymentMethod.BULLET:
        repayment_start = maturity
    if repayment_start is None:
        raise ValueError(
            "SHL_PRINCIPAL_ELIGIBILITY_START_PERIOD_EXPLICIT_INPUT_REQUIRED"
        )

    first_operating = next((p.period_index for p in periods if p.is_operation), None)
    if first_operating is None:
        raise ValueError("ProjectInputs SHL requires at least one operating period")
    period_indices = frozenset(p.period_index for p in periods)
    repayment_start_index = int(repayment_start)
    maturity_index = int(maturity)
    if repayment_start_index not in period_indices:
        raise ValueError(
            "SHL_REPAYMENT_START_NOT_ON_PERIOD_GRID_FAILS_CLOSED: "
            f"repayment_start_period_index={repayment_start_index}"
        )
    if maturity_index not in period_indices:
        raise ValueError(
            "SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED: "
            f"maturity_period_index={maturity_index}"
        )
    if repayment_start_index < int(first_operating):
        raise ValueError(
            "SHL_PRINCIPAL_ELIGIBILITY_START_PERIOD_INVALID: "
            "repayment start must not precede first operating period"
        )
    if maturity_index < int(first_operating):
        raise ValueError(
            "SHL_MATURITY_PERIOD_INVALID: maturity must not precede first operating period"
        )
    if repayment_start_index > maturity_index:
        raise ValueError("maturity_period_index must be >= repayment_start_period_index")

    repayment_mode = _CLEAN_SHL_REPAYMENT_MODE_MAP[method]

    return ShareholderLoanModelInput(
        initial_principal_keur=amount,
        annual_fixed_rate=rate,
        day_count_convention=_coerce_shl_day_count(
            getattr(financing, "shl_day_count_convention", None)
        ),
        construction_day_count_fraction=construction_dcf,
        repayment_mode=repayment_mode,
        repayment_start_period_index=repayment_start_index,
        maturity_period_index=maturity_index,
        convergence_tolerance_keur=1e-4,
        convergence_relative_tolerance=1e-9,
        maximum_iterations=50,
        source_label="project_inputs.financing",
        construction_interest_method=getattr(financing, 'shl_construction_interest_method', ShlConstructionInterestMethod.SIMPLE),
    )

"""Covenant-gated shareholder waterfall model.

The waterfall consumes canonical project inputs and applies a deterministic
sequence: post-senior cash, reserve roll-forward, distribution-account gate,
shareholder-loan service, and residual equity distribution. Distribution
covenants are evaluated before shareholder-loan and equity cash releases.

The implementation is project-identity-free. Reference models provide typed
policy inputs; no source material formulas, fixture vectors, or project-specific
output-fitting constants are embedded in this module."""
from __future__ import annotations

import dataclasses
from datetime import date

from finco_core.inputs import DebtServiceReserveSupportMode, ProjectInputs, SponsorFundingMode
from finco_core.inputs._models import ShlInterestDeductibilityMode
from finco_core.engine.period_engine import map_period_vector
from finco_core.inputs.cash_reserve_interest_schedule import (
    build_unrestricted_cash_schedule,
    build_cash_reserve_interest_schedules,
)

from financial_engine.adapters.project_inputs import (
    _build_shareholder_loan_model_input_from_project_inputs,
)
from financial_engine.inputs import PeriodFinancingIncomeInput
from financial_engine.tax.interest_limitation import (
    roll_forward_equity_state,
    EquityStatePeriodInput,
)
from financial_engine.financing.contracts import (
    ConstructionFundingPeriod,
    ProjectFinancingResult,
)
from financial_engine.financing.project import run_project_financing_model
from financial_engine.financing.dsrf import compute_dsrf_fee_schedule
from financial_engine.dsra.contracts import CashDsraPeriodResult
from financial_engine.results import ProjectModelResult
from financial_engine.shl.contracts import ShlRepaymentMode
from financial_engine.shl.production import compute_shareholder_loan_schedules
from financial_engine.shareholder_waterfall.contracts import (
    CovenantGatedWaterfallPeriod,
    CovenantGatedWaterfallResult,
    DistributionGateStatus,
    ReserveSupportGateStatus,
)
from financial_engine.sponsor_returns.contracts import ReturnMetricStatus
from financial_engine.sponsor_returns.model import compute_gated_sponsor_return_metrics
from financial_engine.project_returns.model import (
    build_decision_complete_return_summary,
)
from financial_engine.valuation.model import (
    build_decision_complete_valuation_summary,
)

_G2C_DA_STATUS_CAUSAL = "G2C_DISTRIBUTION_ACCOUNT_CAUSAL_CF108_CF109_CF110_SOURCE_PROVEN"
_G2C_DEDUCTIBLE_FEEDBACK_STATUS = "G2C_DEDUCTIBLE_SHL_COVENANT_FEEDBACK_NOT_YET_CLOSED"
_DSRF_NO_DRAW_STATUS = "DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE"
_G2C_RESERVE_GATE_STATUS = (
    "G2C_SENIOR_CASH_DSRA_CAUSALLY_CLOSED_"
    "J_DSRA_AND_DSRF_DRAW_NOT_IMPLEMENTED"
)
_FLOAT_TOLERANCE = 1e-9
# O.9: Greenfield axiom — all construction funding is allocated to project Uses
# (senior debt, SHL, equity) plus reserves at financial close. No uncommitted
# cash enters the operating company on day one. Causal chain:
#   ProjectFinancingResult.construction_funding → project Uses (capex + IDC + fees)
#   DSRA funded at tranche draw → DSRA reserve (not unrestricted cash)
#   Residual → zero by construction (balanced sources = uses)
# This is not a calibration choice; it is a structural axiom of greenfield project finance.
_GREENFIELD_OPENING_UNRESTRICTED_CASH_KEUR: float = 0.0

# P.6: Typed authority contract for opening unrestricted cash.
# Authority must be SOURCE_PROVEN_EXPLICIT_ZERO or CAUSALLY_DERIVED_ZERO.
# UNRESOLVED fails closed — prevents silent zero from masking missing provenance.
_OPENING_UC_AUTHORITY: str = "CAUSALLY_DERIVED_ZERO"
# Causal derivation: greenfield axiom above (O.9). Not policy-defined from a
# specific workbook cell. A project with a non-zero opening UC must supply
# SOURCE_PROVEN_EXPLICIT_ZERO with a workbook cell reference.
_OPENING_UC_AUTHORITY_VALID = frozenset({
    "SOURCE_PROVEN_EXPLICIT_ZERO",
    "CAUSALLY_DERIVED_ZERO",
})


def _resolve_opening_uc_keur(authority: str) -> float:
    """P.6: Fail closed if opening UC authority is UNRESOLVED."""
    if authority not in _OPENING_UC_AUTHORITY_VALID:
        raise ValueError(
            f"P.6 OPENING_UC_AUTHORITY_UNRESOLVED: authority={authority!r} is not "
            "SOURCE_PROVEN_EXPLICIT_ZERO or CAUSALLY_DERIVED_ZERO. "
            "Provide workbook cell reference (SOURCE_PROVEN_EXPLICIT_ZERO) or "
            "a causal derivation (CAUSALLY_DERIVED_ZERO)."
        )
    return _GREENFIELD_OPENING_UNRESTRICTED_CASH_KEUR


def _evaluate_reserve_support_gate(
    dsra_mode: "DebtServiceReserveSupportMode",
    requirement_keur: float,
    dsrf_commitment_keur: float,
    is_construction: bool,
    target_met: bool = True,
) -> ReserveSupportGateStatus:
    """Evaluate reserve support gate for one period — informational only.

    NONE      → NOT_APPLICABLE
    CASH_DSRA → PASS_NEUTRAL_SOURCE_PROVEN if req=0, else PASS/FAIL_REQUIREMENT_NOT_MET
    DSRF      → DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE

    IMPORTANT: This status is DESCRIPTIVE / DIAGNOSTIC only.
    It does NOT independently alter cash flow or block distributions.
    The causal gate block comes from comp_d in CF109 (DA inflow calculation).

    Remaining limitations:
      1. J-DSRA: component E always False (not modelled).
      2. DSRF has fee treatment but no draw engine.
      3. period_index <= senior_last_period_index remains the documented proxy
         for the source G4 <= B11 maturity condition.
    """
    from finco_core.inputs import DebtServiceReserveSupportMode
    if is_construction:
        return ReserveSupportGateStatus.CONSTRUCTION
    if dsra_mode == DebtServiceReserveSupportMode.NONE:
        return ReserveSupportGateStatus.NOT_APPLICABLE
    if dsra_mode == DebtServiceReserveSupportMode.DSRF:
        return ReserveSupportGateStatus.DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE
    # CASH_DSRA
    if requirement_keur <= 0.0:
        return ReserveSupportGateStatus.PASS_NEUTRAL_SOURCE_PROVEN
    return ReserveSupportGateStatus.PASS if target_met else ReserveSupportGateStatus.FAIL_REQUIREMENT_NOT_MET


def _add_months(d: date, months: int) -> date:
    import calendar
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _construction_period_date(financial_close: date, period_index: int) -> date:
    return _add_months(financial_close, period_index - 1)


def _validated_dsra_periods_by_index(
    model_result: ProjectModelResult,
    dsra_mode: DebtServiceReserveSupportMode,
) -> dict[int, CashDsraPeriodResult]:
    """Index canonical PR-3B periods and fail closed on ambiguous alignment."""
    schedules = model_result.cash_dsra
    if schedules is None:
        if dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA:
            raise ValueError(
                "G2C_CASH_DSRA_RESULT_REQUIRED: dsra_support_mode=CASH_DSRA but "
                "model_result.cash_dsra is None. Run PR-3B DSRA before G2C."
            )
        return {}

    expected = {period.period_index: period.is_construction for period in model_result.periods}
    indexed: dict[int, CashDsraPeriodResult] = {}
    for period_result in schedules.period_results:
        idx = period_result.period_index
        if idx in indexed:
            raise ValueError(
                f"G2C_CASH_DSRA_DUPLICATE_PERIOD_INDEX: period {idx} appears more than once."
            )
        indexed[idx] = period_result

    extras = sorted(set(indexed) - set(expected))
    if extras:
        raise ValueError(
            "G2C_CASH_DSRA_UNEXPECTED_PERIOD_RESULT: canonical DSRA contains "
            f"periods not present in the downstream model: {extras}."
        )

    if dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA:
        missing = sorted(set(expected) - set(indexed))
        if missing:
            raise ValueError(
                "G2C_CASH_DSRA_PERIOD_RESULT_REQUIRED: active CASH_DSRA is missing "
                f"canonical period results: {missing}."
            )

    for idx, period_result in indexed.items():
        if period_result.is_construction != expected[idx]:
            raise ValueError(
                "G2C_CASH_DSRA_PERIOD_CLASSIFICATION_MISMATCH: "
                f"period {idx} model is_construction={expected[idx]} but canonical "
                f"DSRA is_construction={period_result.is_construction}."
            )
    return indexed


def run_project_shareholder_waterfall_model(
    project_inputs: ProjectInputs,
    *,
    source_id: str = "",
    baseline_commit_sha: str = "",
) -> CovenantGatedWaterfallResult:
    """Compute G2C covenant-gated shareholder waterfall from G2A financing results.

    Adds DSCR distribution lockup gate (project_inputs.financing.lockup_dscr) on top
    of the G2B SHL-gated distribution mechanics.

    Policy-defined ordering: gate is UPSTREAM of SHL service.
    DA roll-forward per CF108/CF109/CF110 source formulas.
    BULLET fail-closed: equity=0, metrics=None after underfunded maturity balloon.
    """
    # G2C_JUNIOR_DEBT_WATERFALL_NOT_IMPLEMENTED: junior debt service (G95) is modeled
    # as CF95=0 in G2C. If junior debt is configured, the waterfall is unsupported.
    _junior_keur = getattr(project_inputs.financing, "junior_or_other_project_funding_keur", 0.0) or 0.0
    if _junior_keur > 0.0:
        raise ValueError(
            "G2C_JUNIOR_DEBT_WATERFALL_NOT_IMPLEMENTED: "
            f"junior_or_other_project_funding_keur={_junior_keur:.0f} kEUR is configured. "
            "G2C assumes CF95=0 (no junior debt service). "
            "Junior debt waterfall is not modeled; result would be incorrect."
        )

    fin = project_inputs.financing
    info = project_inputs.info
    tax = project_inputs.tax

    # U2 Phase L: accounting cap parameters
    _share_capital_keur = getattr(fin, "share_capital_keur", 0.0) or 0.0
    _cash_reserve_policy = getattr(project_inputs, "cash_reserve_interest_policy", None)
    _distribution_accounting_policy = getattr(project_inputs, "distribution_accounting_policy", None)
    _dist_accounting_enabled = (
        _distribution_accounting_policy is not None
        and getattr(_distribution_accounting_policy, "enabled", False)
    )
    _dividend_wht_rate = (
        _distribution_accounting_policy.dividend_wht_rate
        if _dist_accounting_enabled
        else 0.0
    )
    _legal_reserve_cap = (
        _distribution_accounting_policy.legal_reserve_cap_fraction
        if _dist_accounting_enabled
        else getattr(getattr(project_inputs, "tax", None), "legal_reserve_cap", 0.10)
    )

    # U2 Phase L: outer fixed-point state
    _MAX_U2_ITER = 50
    _U2_TOL = 1e-4  # kEUR
    _fi_by_idx: dict[int, float] = {}        # financing income per period_index
    _prev_fi: dict[int, float] = {}
    _prev_uc: dict[int, float] = {}
    _prev_gd: dict[int, float] = {}
    _uc_closing_by_idx: dict[int, float] = {}
    _gd_by_idx: dict[int, float] = {}
    _fi_schedule = None
    financing: ProjectFinancingResult  # declared; assigned inside loop

    # S.2: ONE reusable accounting + FI transition used for both the convergence
    # loop and the final idempotence check (S.4). All arithmetic lives here only.
    def _u2_accounting_and_fi_pass(
        _model_result,
        _fi_for_ni: dict[int, float],
        _wp_input: list,
        _opening_eq_retained: float,
        _dsra_by_idx: dict[int, float],
    ):
        """Full accounting/dividend/UC/FI causal chain for one U2 transition.

        Returns (new_wp, uc_closing_by_idx, gd_by_idx, re_closing_by_idx,
                 lr_closing_by_idx, next_fi_by_idx, fi_schedule).
        Captures outer parameters from run_project_shareholder_waterfall_model.
        """
        _op_by_idx = {p.period_index: p for p in _model_result.periods if p.is_operation}
        _sint_by_idx: dict[int, float] = {}
        if _model_result.senior_debt is not None:
            _sd_inner = _model_result.senior_debt
            for _si, _sidx in enumerate(_sd_inner.period_indices):
                _sint_by_idx[_sidx] = _sd_inner.senior_interest_keur[_si]
        _cit_by_idx_inner: dict[int, float] = {}
        if _model_result.tax_and_cfads is not None:
            _ta_inner = _model_result.tax_and_cfads
            for _ti, _tidx in enumerate(_ta_inner.period_indices):
                _cit_by_idx_inner[_tidx] = _ta_inner.tax_keur[_ti]

        _uc_c = 0.0  # rolling unrestricted cash carry (starts at greenfield zero)
        _eq_ret = _opening_eq_retained
        _eq_res = 0.0  # legal reserve starts at 0 for greenfield
        _uc_out: dict[int, float] = {}
        _gd_out: dict[int, float] = {}
        _re_out: dict[int, float] = {}
        _lr_out: dict[int, float] = {}
        _new_wp_list: list = []

        for _wp in _wp_input:
            if _wp.is_construction:
                _new_wp_list.append(_wp)
                continue
            _idx = _wp.period_index
            _op = _op_by_idx.get(_idx)
            if _op is None:
                _new_wp_list.append(_wp)
                continue
            _ni = (
                _op.ebitda_keur
                - _op.book_depreciation_keur
                + _fi_for_ni.get(_idx, 0.0)
                - _sint_by_idx.get(_idx, 0.0)
                - _wp.shl_gross_interest_keur
                - _cit_by_idx_inner.get(_idx, 0.0)
            )
            _fcf_div = _wp.legal_equity_distribution_keur

            # Accounting cap (dividends=0 to get capacity)
            _eq_cap_res = roll_forward_equity_state(
                (EquityStatePeriodInput(period_index=_idx, net_income_keur=_ni, gross_dividends_keur=0.0),),
                share_capital_keur=_share_capital_keur,
                legal_reserve_cap_fraction=_legal_reserve_cap,
                opening_legal_reserve_keur=_eq_res,
                opening_retained_earnings_keur=_eq_ret,
            )[0]
            _acct_cap = max(0.0, _eq_cap_res.closing_retained_earnings_keur)
            _cash_cap = _uc_c + _fcf_div
            _distributable = max(0.0, min(_acct_cap, _cash_cap))
            _gross_div = _distributable
            _wht = _gross_div * _dividend_wht_rate
            _net_div = _gross_div * (1.0 - _dividend_wht_rate)
            _change_uc = _fcf_div - _gross_div
            _uc_closing = _uc_c + _change_uc

            # Closing equity state with actual dividends
            _eq_actual_res = roll_forward_equity_state(
                (EquityStatePeriodInput(period_index=_idx, net_income_keur=_ni, gross_dividends_keur=_gross_div),),
                share_capital_keur=_share_capital_keur,
                legal_reserve_cap_fraction=_legal_reserve_cap,
                opening_legal_reserve_keur=_eq_res,
                opening_retained_earnings_keur=_eq_ret,
            )[0]
            _eq_res = _eq_actual_res.closing_legal_reserve_keur
            _eq_ret = _eq_actual_res.closing_retained_earnings_keur

            _uc_out[_idx] = _uc_closing
            _gd_out[_idx] = _gross_div
            _re_out[_idx] = _eq_ret
            _lr_out[_idx] = _eq_res

            _new_wp_list.append(dataclasses.replace(
                _wp,
                fcf_for_dividends_keur=_fcf_div,
                accounting_dividend_capacity_keur=_acct_cap,
                cash_dividend_capacity_keur=_cash_cap,
                distributable_keur=_distributable,
                gross_dividend_paid_keur=_gross_div,
                dividend_wht_rate=_dividend_wht_rate,
                dividend_wht_keur=_wht,
                net_dividend_received_keur=_net_div,
                unrestricted_cash_opening_keur=_uc_c,
                change_in_unrestricted_cash_keur=_change_uc,
                unrestricted_cash_closing_keur=_uc_closing,
                opening_legal_reserve_keur=_eq_actual_res.opening_legal_reserve_keur,
                legal_reserve_transfer_keur=_eq_actual_res.legal_reserve_transfer_keur,
                closing_legal_reserve_keur=_eq_actual_res.closing_legal_reserve_keur,
                pure_equity_net_cashflow_keur=_net_div,
                total_sponsor_net_cashflow_keur=(
                    _net_div + _wp.shl_cash_interest_receipt_keur + _wp.shl_principal_receipt_keur
                ),
            ))
            _uc_c = _uc_closing

        # FI computation from resulting UC schedule
        _next_fi_out: dict[int, float] = {}
        _fi_sched_out = None
        if _cash_reserve_policy is not None:
            _all_incr: dict[int, float] = {}
            for _ap in _model_result.periods:
                _aidx = _ap.period_index
                if _ap.is_construction:
                    _all_incr[_aidx] = 0.0
                else:
                    _wp_m = next((w for w in _new_wp_list if w.period_index == _aidx), None)
                    _all_incr[_aidx] = (
                        _wp_m.change_in_unrestricted_cash_keur if _wp_m is not None else 0.0
                    )
            _policy_auth = getattr(_distribution_accounting_policy, "opening_uc_authority", None)
            _eff_auth = (
                _OPENING_UC_AUTHORITY
                if _policy_auth is None or _policy_auth == "UNRESOLVED"
                else _policy_auth
            )
            _uc_sched_out = build_unrestricted_cash_schedule(
                periods=_model_result.periods,
                authority="SOURCE_PROVEN",
                authoritative_period_cash_increments=_all_incr,
                opening_cash_keur=_resolve_opening_uc_keur(_eff_auth),
            )
            _fi_sched_out = build_cash_reserve_interest_schedules(
                periods=_model_result.periods,
                policy=_cash_reserve_policy,
                unrestricted_cash_schedule=_uc_sched_out,
                dsra_balance_by_period=_dsra_by_idx if _dsra_by_idx else None,
                dsra_balance_authority="SOURCE_PROVEN" if _dsra_by_idx else None,
            )
            for _fr in _fi_sched_out.period_results:
                if _fr.calculated_financing_income_keur != 0.0:
                    _next_fi_out[_fr.period_index] = _fr.calculated_financing_income_keur

        return _new_wp_list, _uc_out, _gd_out, _re_out, _lr_out, _next_fi_out, _fi_sched_out

    for _u2_iter in range(1, _MAX_U2_ITER + 2):
        # Build PeriodFinancingIncomeInput tuple from current state
        _fi_inputs: tuple = tuple(
            PeriodFinancingIncomeInput(
                period_index=idx,
                financing_income_keur=val,
                authority="SOURCE_PROVEN",
            )
            for idx, val in _fi_by_idx.items()
            if val != 0.0
        )
        financing = run_project_financing_model(
            project_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
            _u2_period_financing_income=_fi_inputs if _fi_inputs else None,
        )

        model_result: ProjectModelResult = financing.project_model_result  # type: ignore[assignment]

        distribution_lockup_dscr: float = fin.lockup_dscr
        financial_close: date = info.financial_close

        # Reserve support gate inputs
        from finco_core.inputs import DebtServiceReserveSupportMode
        dsra_mode = fin.dsra_support_mode
        reserve_requirement_keur: float = getattr(fin, "debt_service_reserve_requirement_keur", 0.0) or 0.0
        dsrf_commitment_keur: float = getattr(fin, "dsrf_commitment_keur", 0.0) or 0.0

        # ── Build lookup maps ─────────────────────────────────────────────────────
        construction_periods_by_index: dict[int, ConstructionFundingPeriod] = {
            p.period_index: p for p in financing.construction_funding.periods
        }

        if model_result.post_senior_cash is None:
            raise ValueError("G2C requires post_senior_cash; clean engine did not produce it")

        # Independently-derived canonical axes (Correction C / TASK 1):
        #   expected_full_axis  — all model period indices from model_result.periods
        #   expected_op_axis    — operating-only period indices
        expected_full_axis: tuple[int, ...] = tuple(
            p.period_index for p in model_result.periods
        )
        expected_op_axis: tuple[int, ...] = tuple(
            p.period_index for p in model_result.periods if p.is_operation
        )

        signed_post_senior_by_idx: dict[int, float] = map_period_vector(
            model_result.post_senior_cash.period_indices,
            model_result.post_senior_cash.cash_after_senior_before_reserves_keur,
            label="shareholder_waterfall.post_senior_cash",
            expected_indices=expected_full_axis,
        )

        # DSCR lookup — None where no Senior DS
        base_dscr_by_idx: dict[int, float | None] = {}
        senior_ds_nonzero_by_idx: dict[int, bool] = {}
        senior_last_period_index: int | None = None
        if model_result.senior_debt is not None:
            sd = model_result.senior_debt
            ds_arr = sd.senior_debt_service_keur
            # Senior axis: derive independently from CanonicalAxisContract when present
            # (populated by the clean orchestrator from typed SeniorDebtPolicy bounds).
            # For legacy paths (no axis_contract), derive from canonical periods + SD policy
            # bounds via build_senior_debt_model_input_from_project_inputs.
            # NEVER use tuple(sd.period_indices) as expected_senior_axis (self-validation).
            _axis_contract = getattr(model_result, "axis_contract", None)
            if _axis_contract is not None:
                expected_senior_axis: tuple[int, ...] = _axis_contract.senior_axis
            else:
                # Correction G: fail closed — no fallback for active Senior consumers.
                # CanonicalAxisContract must be present when Senior debt is active.
                raise ValueError(
                    "CANONICAL_AXIS_CONTRACT_MISSING: Senior debt schedule is active but "
                    "model_result.axis_contract is absent. Active Senior consumers require "
                    "a CanonicalAxisContract with an independently derived senior_axis. "
                    "Run run_senior_debt_model (Phase 2C) to populate the contract."
                )
            base_dscr_by_idx = map_period_vector(
                sd.period_indices, sd.base_dscr, label="shareholder_waterfall.base_dscr",
                expected_indices=expected_senior_axis,
            )
            senior_ds_by_idx = map_period_vector(
                sd.period_indices, ds_arr, label="shareholder_waterfall.senior_debt_service",
                expected_indices=expected_senior_axis,
            )
            senior_ds_nonzero_by_idx = {idx: ds > 0.0 for idx, ds in senior_ds_by_idx.items()}
            nonzero_ds = [i for i, ds in senior_ds_by_idx.items() if ds > 0.0]
            if nonzero_ds:
                senior_last_period_index = max(nonzero_ds)

        period_date_by_idx: dict[int, date] = {
            p.period_index: p.period_end for p in model_result.periods
        }
        period_start_by_idx: dict[int, date] = {
            p.period_index: p.period_start for p in model_result.periods
        }

        # ── DSRF commitment fee schedule ──────────────────────────────────────────
        from finco_core.inputs import DsrfCommitmentFeeTreatment
        _fee_treatment = getattr(fin, "dsrf_fee_treatment", DsrfCommitmentFeeTreatment.POST_SENIOR_CASH)
        if _fee_treatment != DsrfCommitmentFeeTreatment.POST_SENIOR_CASH:
            raise ValueError(
                f"G2C_UNSUPPORTED_DSRF_FEE_TREATMENT: {_fee_treatment!r}. "
                "Only POST_SENIOR_CASH is implemented "
                "(EXPLICIT_GENERIC_MVP_POLICY_POST_SENIOR_CASH). "
                "No other DSRF fee treatment is supported."
            )
        dsrf_fee_by_idx: dict[int, float] = {}
        if dsra_mode == DebtServiceReserveSupportMode.DSRF:
            dsrf_req = getattr(fin, "debt_service_reserve_requirement_keur", 0.0) or 0.0
            if dsrf_req > 0.0 and fin.dsrf_commitment_keur < dsrf_req:
                raise ValueError(
                    f"G2C_DSRF_COMMITMENT_BELOW_REQUIRED_RESERVE: "
                    f"commitment={fin.dsrf_commitment_keur} < required={dsrf_req}"
                )
            if fin.dsrf_commitment_keur > 0 and fin.dsrf_commitment_fee_rate_pa > 0.0:
                op_indices = [p.period_index for p in model_result.periods if p.is_operation]
                op_starts = [period_start_by_idx[i] for i in op_indices]
                op_ends = [period_date_by_idx[i] for i in op_indices]
                dsrf_schedule = compute_dsrf_fee_schedule(
                    op_indices, op_starts, op_ends,
                    fin.dsrf_commitment_keur,
                    fin.dsrf_commitment_fee_rate_pa,
                    senior_last_period_index=senior_last_period_index if fin.dsrf_fee_expires_at_senior_maturity else None,
                    day_count_convention=fin.dsrf_day_count,
                )
                dsrf_fee_by_idx = map_period_vector(
                    dsrf_schedule.period_indices,
                    dsrf_schedule.dsrf_commitment_fee_keur,
                    label="shareholder_waterfall.dsrf_commitment_fee",
                    expected_indices=expected_op_axis,
                )

        # ── PR-3 CASH_DSRA roll-forward lookup ───────────────────────────────────
        # CASH_DSRA: consume model_result.cash_dsra as the one clean reserve authority.
        # NONE/DSRF: model_result.cash_dsra is a neutral pass-through (cash_after_dsra == signed_post_senior).
        # Build per-period lookup maps from the canonical PR-3B result. Active
        # CASH_DSRA alignment is validated before any financial calculation.
        dsra_periods_by_idx = _validated_dsra_periods_by_index(model_result, dsra_mode)
        dsra_opening_by_idx: dict[int, float] = {}
        dsra_closing_by_idx: dict[int, float] = {}
        dsra_required_by_idx: dict[int, float] = {}
        cash_after_dsra_by_idx: dict[int, float] = {}
        dsra_top_up_by_idx: dict[int, float] = {}
        dsra_draw_by_idx: dict[int, float] = {}
        dsra_release_by_idx: dict[int, float] = {}
        dsra_target_met_by_idx: dict[int, bool] = {}

        if dsra_periods_by_idx:
            for pr in dsra_periods_by_idx.values():
                i = pr.period_index
                dsra_opening_by_idx[i] = pr.opening_balance_keur
                dsra_closing_by_idx[i] = pr.closing_balance_keur
                dsra_required_by_idx[i] = pr.required_balance_keur
                cash_after_dsra_by_idx[i] = pr.cash_after_dsra_keur
                dsra_top_up_by_idx[i] = pr.top_up_keur
                dsra_draw_by_idx[i] = pr.draw_to_cover_shortfall_keur
                dsra_release_by_idx[i] = pr.release_keur
                dsra_target_met_by_idx[i] = pr.target_met
        else:
            # NONE or DSRF may omit PR-3B because both are neutral reserve modes.
            for period in model_result.periods:
                if not period.is_operation:
                    continue
                i = period.period_index
                dsra_opening_by_idx[i] = 0.0
                dsra_closing_by_idx[i] = 0.0
                dsra_required_by_idx[i] = 0.0
                dsra_top_up_by_idx[i] = 0.0
                dsra_draw_by_idx[i] = 0.0
                dsra_release_by_idx[i] = 0.0
                dsra_target_met_by_idx[i] = True
                # cash_after_dsra_by_idx filled during the gate loop below for NONE/DSRF

        # J-DSRA: NOT_APPLICABLE for no-junior-debt projects.
        # Gate component E = False (both ending and target = 0).
        j_dsra_target_keur = 0.0
        j_dsra_closing_keur = 0.0

        # ── Phase 1: DA roll-forward + CF109 5-component gate ────────────────────
        # CF108: da_available[t] = reserve_adjusted_cash[t] - dsrf_fee[t]
        #                           + da_closing[t-1]
        # CF109: IF(AND(OR(A,B,C,D,E), within_senior_maturity), 0, da_available)
        # CF110: da_closing[t] = da_available[t] - release[t]
        #
        # Note: signed_post_senior here corresponds to G94 (FCF for junior debt),
        # plus G95 (junior DS = 0) plus G106 (J-DSRA movement = 0).
        # For no-junior-debt projects: G94 = signed_post_senior directly.

        gate_info_by_idx: dict[int, tuple] = {}
        da_info_by_idx: dict[int, tuple] = {}  # idx → (opening, inflow, available, release, closing, booleans...)
        gated_cash_all_periods: list[float] = []

        da_closing_prev: float = 0.0  # DA closing of prior period (F110 in first op period = 0)

        for period in model_result.periods:
            idx = period.period_index
            if period.is_construction:
                gated_cash_all_periods.append(0.0)
                continue

            if idx not in signed_post_senior_by_idx:
                raise ValueError(
                    f"G2C: operating period {idx} absent from post_senior_cash schedule"
                )
            signed_post_senior = signed_post_senior_by_idx[idx]
            dsrf_fee = dsrf_fee_by_idx.get(idx, 0.0)

            # PR-4: DA inflow sourced from canonical PR-3B reserve-adjusted cash.
            if idx in cash_after_dsra_by_idx:
                reserve_adjusted_cash = cash_after_dsra_by_idx[idx]
            elif dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA:
                # Defensive assertion after whole-schedule validation: never substitute
                # pre-reserve cash for an active reserve period.
                raise ValueError(
                    "G2C_CASH_DSRA_PERIOD_RESULT_REQUIRED: active CASH_DSRA has no "
                    f"canonical cash_after_dsra for operating period {idx}."
                )
            else:
                reserve_adjusted_cash = signed_post_senior
                cash_after_dsra_by_idx[idx] = reserve_adjusted_cash
            da_inflow = reserve_adjusted_cash - dsrf_fee

            # CF108: DA available = inflow + prior closing
            da_available = da_inflow + da_closing_prev

            # Gate components (CF109 policy-defined)
            dscr_val = base_dscr_by_idx.get(idx)
            has_senior_ds = senior_ds_nonzero_by_idx.get(idx, False)
            comp_a = (dscr_val is not None and has_senior_ds and dscr_val < distribution_lockup_dscr)
            comp_b = False  # operating period, not construction
            comp_c = da_available < 0.0
            # PR-4: component D uses actual PR-3 closing vs required (not static target).
            if dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA:
                dsra_closing_keur = dsra_closing_by_idx[idx]
                dsra_required_keur = dsra_required_by_idx[idx]
            else:
                dsra_closing_keur = dsra_closing_by_idx.get(idx, 0.0)
                dsra_required_keur = dsra_required_by_idx.get(idx, 0.0)
            comp_d = dsra_closing_keur < dsra_required_keur - _FLOAT_TOLERANCE
            comp_e = j_dsra_closing_keur < j_dsra_target_keur  # False always (no J-DSRA)

            # within_senior_maturity: gate active only if we're within senior debt term
            # Source: G$4 <= $B$11 ($B$11 = Senior Debt Maturity years)
            # We use period index <= senior_last_period_index as proxy
            if senior_last_period_index is not None:
                within_senior_maturity = idx <= senior_last_period_index
            else:
                within_senior_maturity = False

            gate_locked = (comp_a or comp_b or comp_c or comp_d or comp_e) and within_senior_maturity

            # CF109: IF(AND(OR(A,B,C,D,E), within_senior_maturity), 0, G108)
            # Preserve signed output — do NOT clip with max(0, da_available).
            if gate_locked:
                da_release = 0.0
                # Use LOCKED_DSCR_BELOW_LOCKUP only when comp_A is the trigger.
                # When gate locked by another component (C/D/E), use LOCKED_COVENANT_GATE.
                gate_status = (
                    DistributionGateStatus.LOCKED_DSCR_BELOW_LOCKUP
                    if comp_a
                    else DistributionGateStatus.LOCKED_COVENANT_GATE
                )
            elif dscr_val is None or not has_senior_ds:
                # No DSCR available: gate open (no debt to covenant)
                da_release = da_available  # signed CF109 output
                gate_status = DistributionGateStatus.DSCR_UNAVAILABLE_GATE_OPEN
            else:
                da_release = da_available  # signed CF109 output
                gate_status = DistributionGateStatus.OPEN

            # CF110 = CF108 - CF109: DA closing balance
            # Invariant: da_available = da_release + da_closing always holds.
            # When gate open and da_available > 0: release = available, closing = 0
            # When gate open and da_available < 0: release = 0, closing = available (negative shortfall)
            # When gate locked: release = 0, closing = da_available (accumulated in DA)
            da_closing = da_available - da_release
            fcf_for_distribution = da_release  # signed CF109 output when open; 0 when locked
            # covenant_locked: per-period legacy view (positive locked cash this period)
            covenant_locked = max(0.0, da_available) if gate_locked else 0.0
            cash_shortfall = max(0.0, -(signed_post_senior - dsrf_fee))

            gate_info_by_idx[idx] = (gate_status, fcf_for_distribution, covenant_locked, dsrf_fee, signed_post_senior, cash_shortfall, reserve_adjusted_cash)
            da_info_by_idx[idx] = (
                da_closing_prev,   # opening
                da_inflow,         # inflow (net of DSRF fee)
                da_available,      # available (CF108)
                da_release,        # release (CF109)
                da_closing,        # closing (CF110)
                comp_a, comp_b, comp_c, comp_d, comp_e,
                within_senior_maturity,
            )
            # SHL scheduler needs non-negative available cash (signed FCF not usable for service)
            gated_cash_all_periods.append(max(0.0, fcf_for_distribution))
            da_closing_prev = da_closing

        # ── Phase 2: SHL schedule using project-owned policy ─────────────────────
        shl_opening_by_idx: dict[int, float] = {}
        shl_gross_by_idx: dict[int, float] = {}
        shl_cash_int_by_idx: dict[int, float] = {}
        shl_pik_by_idx: dict[int, float] = {}
        shl_principal_by_idx: dict[int, float] = {}
        shl_closing_by_idx: dict[int, float] = {}

        has_shl = financing.derived_shl_cash_principal_keur > 0.0
        shl_maturity_idx: int | None = None
        shl_repayment_mode: ShlRepaymentMode | None = None
        if has_shl:
            dynamic_limitation = getattr(
                project_inputs.tax, "interest_limitation_policy", None
            )
            shl_model_input = (
                financing.shareholder_loan_model_input
                if dynamic_limitation is not None and dynamic_limitation.enabled
                else None
            )
            if shl_model_input is None:
                shl_model_input = _build_shareholder_loan_model_input_from_project_inputs(
                    project_inputs,
                    model_result.periods,
                    senior_debt_maturity_period_index=senior_last_period_index,
                )
            if shl_model_input is not None:
                if abs(shl_model_input.initial_principal_keur - financing.derived_shl_cash_principal_keur) > 1e-4:
                    shl_model_input = dataclasses.replace(
                        shl_model_input,
                        initial_principal_keur=financing.derived_shl_cash_principal_keur,
                    )
                shl_maturity_idx = shl_model_input.maturity_period_index
                shl_repayment_mode = shl_model_input.repayment_mode

                gated_shl_schedule = compute_shareholder_loan_schedules(
                    model_result.periods,
                    shl_model_input,
                    gated_cash_all_periods,
                    diagnostics=None,
                )
                # SHL schedule axis must match the full canonical period axis (Rule 4).
                expected_shl_axis: tuple[int, ...] = expected_full_axis
                for label, values, target in (
                    ("opening", gated_shl_schedule.shl_opening_keur, shl_opening_by_idx),
                    ("gross_interest", gated_shl_schedule.shl_gross_interest_keur, shl_gross_by_idx),
                    ("cash_interest", gated_shl_schedule.shl_cash_interest_keur, shl_cash_int_by_idx),
                    ("pik_interest", gated_shl_schedule.shl_pik_interest_keur, shl_pik_by_idx),
                    ("principal", gated_shl_schedule.shl_principal_keur, shl_principal_by_idx),
                    ("closing", gated_shl_schedule.shl_closing_keur, shl_closing_by_idx),
                ):
                    target.update(map_period_vector(
                        gated_shl_schedule.period_indices,
                        values,
                        label=f"shareholder_waterfall.shl_{label}",
                        expected_indices=expected_shl_axis,
                    ))

        # ── Phase 3: Deductible SHL feedback check ───────────────────────────────
        shl_deductible = (
            getattr(tax, "shl_interest_deductibility", ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE)
            != ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE
        )
        gate_locks_any = any(
            info[0] in (
                DistributionGateStatus.LOCKED_DSCR_BELOW_LOCKUP,
                DistributionGateStatus.LOCKED_COVENANT_GATE,
            )
            for info in gate_info_by_idx.values()
        )
        shl_pik_differs_from_g2a = has_shl and gate_locks_any and any(
            shl_pik_by_idx.get(idx, 0.0) > 0.0 for idx in gate_info_by_idx
        )
        deductible_feedback_active = shl_deductible and shl_pik_differs_from_g2a

        # ── Phase 4: Assemble per-period records ──────────────────────────────────
        waterfall_periods: list[CovenantGatedWaterfallPeriod] = []

        # --- Construction periods ---
        for k in sorted(construction_periods_by_index.keys()):
            cp = construction_periods_by_index[k]
            cf_date = _construction_period_date(financial_close, k)

            share_cap = cp.share_capital_draw_keur
            share_prem = cp.share_premium_draw_keur
            other_committed = cp.other_committed_equity_draw_keur
            add_eq = cp.additional_equity_draw_keur
            shl_draw = cp.shl_cash_draw_keur

            pure_equity_net = -(share_cap + share_prem + other_committed + add_eq)
            total_sponsor_net = pure_equity_net - shl_draw

            waterfall_periods.append(CovenantGatedWaterfallPeriod(
                period_index=k,
                cashflow_date=cf_date,
                is_construction=True,
                base_dscr=None,
                distribution_lockup_dscr=distribution_lockup_dscr,
                distribution_gate_status=DistributionGateStatus.CONSTRUCTION,
                debt_service_reserve_requirement_keur=0.0,
                initial_funded_dsra_keur=(
                    reserve_requirement_keur
                    if dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA
                    else 0.0
                ),
                reserve_support_gate_status=ReserveSupportGateStatus.CONSTRUCTION,
                signed_post_senior_keur=0.0,
                dsrf_commitment_fee_keur=0.0,
                reserve_adjusted_cash_keur=0.0,
                dsra_top_up_keur=0.0,
                dsra_draw_keur=0.0,
                dsra_release_keur=0.0,
                fcf_for_distribution_keur=0.0,
                covenant_locked_keur=0.0,
                # DA fields: zero during construction
                distribution_account_opening_keur=0.0,
                distribution_account_inflow_keur=0.0,
                distribution_account_available_keur=0.0,
                gate_component_dscr_below_lockup=False,
                gate_component_construction=True,
                gate_component_da_negative=False,
                gate_component_dsra_underfunded=False,
                gate_component_j_dsra_underfunded=False,
                within_senior_maturity=True,
                distribution_account_release_keur=0.0,
                distribution_account_closing_keur=0.0,
                shl_cash_input_keur=0.0,
                # DSRA: zero during construction
                senior_dsra_target_keur=0.0,
                senior_dsra_opening_keur=0.0,
                senior_dsra_closing_keur=0.0,
                # BULLET: not applicable during construction
                shl_bullet_unpaid_at_maturity=False,
                shl_opening_balance_keur=0.0,
                shl_gross_interest_keur=0.0,
                shl_cash_interest_receipt_keur=0.0,
                shl_pik_keur=0.0,
                contractual_shl_principal_due_keur=0.0,
                actual_shl_principal_paid_keur=0.0,
                unpaid_shl_principal_keur=0.0,
                actual_shl_closing_balance_keur=0.0,
                shl_principal_receipt_keur=0.0,
                shl_closing_balance_keur=0.0,
                legal_equity_distribution_keur=0.0,
                # U2 Phase L: zero during construction
                fcf_for_dividends_keur=0.0,
                accounting_dividend_capacity_keur=0.0,
                cash_dividend_capacity_keur=0.0,
                distributable_keur=0.0,
                gross_dividend_paid_keur=0.0,
                dividend_wht_rate=0.0,
                dividend_wht_keur=0.0,
                net_dividend_received_keur=0.0,
                unrestricted_cash_opening_keur=0.0,
                change_in_unrestricted_cash_keur=0.0,
                unrestricted_cash_closing_keur=0.0,
                cash_shortfall_keur=0.0,
                share_capital_contribution_keur=share_cap,
                share_premium_contribution_keur=share_prem,
                other_committed_equity_contribution_keur=other_committed,
                additional_equity_contribution_keur=add_eq,
                shl_cash_contribution_keur=shl_draw,
                pure_equity_net_cashflow_keur=pure_equity_net,
                total_sponsor_net_cashflow_keur=total_sponsor_net,
            ))

        # --- Operating periods ---
        # actual_shl_carry: causal closing balance to override contractual scheduler
        actual_shl_carry: float | None = None
        # bullet_unpaid_active: once True, equity=0 and post-maturity SHL terms = 0
        bullet_unpaid_active: bool = False

        for period in model_result.periods:
            if not period.is_operation:
                continue
            idx = period.period_index
            cf_date = period_date_by_idx[idx]

            gate_status, fcf_for_distribution, covenant_locked, dsrf_fee, signed_post_senior, cash_shortfall, reserve_adjusted_cash = gate_info_by_idx[idx]

            (
                da_opening, da_inflow, da_available, da_release, da_closing,
                comp_a, comp_b, comp_c, comp_d, comp_e, within_sm,
            ) = da_info_by_idx[idx]

            # BULLET post-maturity: once balloon was underfunded, no SHL terms exist.
            # Do NOT read from contractual scheduler — it shows 0 post-maturity which is
            # consistent but we track via actual_shl_carry for causal opening.
            is_post_maturity = bullet_unpaid_active

            # SHL opening: use actual carry-forward if available (causal), else contractual.
            if actual_shl_carry is not None:
                shl_opening = actual_shl_carry
            else:
                shl_opening = shl_opening_by_idx.get(idx, 0.0)

            at_maturity = (shl_maturity_idx is not None and idx == shl_maturity_idx)

            if is_post_maturity:
                # Post-maturity with unpaid BULLET: no terms (do not invent default interest).
                shl_gross = 0.0
                actual_shl_cash_int = 0.0
                shl_pik = 0.0
                contractual_shl_principal = 0.0
                actual_shl_principal = 0.0
            else:
                shl_gross = shl_gross_by_idx.get(idx, 0.0)
                actual_shl_cash_int = shl_cash_int_by_idx.get(idx, 0.0)
                shl_pik = shl_pik_by_idx.get(idx, 0.0)
                actual_shl_principal = shl_principal_by_idx.get(idx, 0.0)
                contractual_shl_principal = (
                    shl_opening + shl_pik
                    if shl_repayment_mode == ShlRepaymentMode.BULLET and at_maturity
                    else actual_shl_principal
                )

            unpaid_shl_principal = (
                max(0.0, contractual_shl_principal - actual_shl_principal)
                if not is_post_maturity
                else 0.0
            )
            actual_shl_closing = (
                shl_closing_by_idx.get(idx, 0.0)
                if not is_post_maturity
                else shl_opening
            )

            # Detect underfunded BULLET at its contractual maturity period
            if (
                at_maturity
                and has_shl
                and shl_repayment_mode == ShlRepaymentMode.BULLET
                and unpaid_shl_principal > 1e-6
            ):
                bullet_unpaid_active = True

            if has_shl:
                actual_shl_carry = actual_shl_closing

            shl_bullet_flag = bullet_unpaid_active

            # BULLET fail-closed: block equity distributions after unresolved BULLET
            if bullet_unpaid_active and not at_maturity:
                distribution = 0.0
            else:
                shl_service_actual = actual_shl_cash_int + actual_shl_principal
                distribution = max(0.0, fcf_for_distribution - shl_service_actual)

            pure_equity_net = distribution
            total_sponsor_net = pure_equity_net + actual_shl_cash_int + actual_shl_principal

            if dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA:
                dsra_op = dsra_opening_by_idx[idx]
                dsra_cl = dsra_closing_by_idx[idx]
                dsra_req = dsra_required_by_idx[idx]
                dsra_top_up = dsra_top_up_by_idx[idx]
                dsra_draw = dsra_draw_by_idx[idx]
                dsra_rel = dsra_release_by_idx[idx]
                target_met = dsra_target_met_by_idx[idx]
            else:
                dsra_op = dsra_opening_by_idx.get(idx, 0.0)
                dsra_cl = dsra_closing_by_idx.get(idx, 0.0)
                dsra_req = dsra_required_by_idx.get(idx, 0.0)
                dsra_top_up = dsra_top_up_by_idx.get(idx, 0.0)
                dsra_draw = dsra_draw_by_idx.get(idx, 0.0)
                dsra_rel = dsra_release_by_idx.get(idx, 0.0)
                target_met = dsra_target_met_by_idx.get(idx, True)

            waterfall_periods.append(CovenantGatedWaterfallPeriod(
                period_index=idx,
                cashflow_date=cf_date,
                is_construction=False,
                base_dscr=base_dscr_by_idx.get(idx),
                distribution_lockup_dscr=distribution_lockup_dscr,
                distribution_gate_status=gate_status,
                debt_service_reserve_requirement_keur=dsra_req,
                initial_funded_dsra_keur=(
                    reserve_requirement_keur
                    if dsra_mode == DebtServiceReserveSupportMode.CASH_DSRA
                    else 0.0
                ),
                reserve_support_gate_status=_evaluate_reserve_support_gate(
                    dsra_mode, dsra_req, dsrf_commitment_keur,
                    is_construction=False, target_met=target_met,
                ),
                signed_post_senior_keur=signed_post_senior,
                dsrf_commitment_fee_keur=dsrf_fee,
                reserve_adjusted_cash_keur=reserve_adjusted_cash,
                dsra_top_up_keur=dsra_top_up,
                dsra_draw_keur=dsra_draw,
                dsra_release_keur=dsra_rel,
                fcf_for_distribution_keur=fcf_for_distribution,
                covenant_locked_keur=covenant_locked,
                distribution_account_opening_keur=da_opening,
                distribution_account_inflow_keur=da_inflow,
                distribution_account_available_keur=da_available,
                gate_component_dscr_below_lockup=comp_a,
                gate_component_construction=comp_b,
                gate_component_da_negative=comp_c,
                gate_component_dsra_underfunded=comp_d,
                gate_component_j_dsra_underfunded=comp_e,
                within_senior_maturity=within_sm,
                distribution_account_release_keur=da_release,
                distribution_account_closing_keur=da_closing,
                shl_cash_input_keur=max(0.0, da_release),
                senior_dsra_target_keur=dsra_req,
                senior_dsra_opening_keur=dsra_op,
                senior_dsra_closing_keur=dsra_cl,
                shl_bullet_unpaid_at_maturity=shl_bullet_flag,
                shl_opening_balance_keur=shl_opening,
                shl_gross_interest_keur=shl_gross,
                shl_cash_interest_receipt_keur=actual_shl_cash_int,
                shl_pik_keur=shl_pik,
                contractual_shl_principal_due_keur=contractual_shl_principal,
                actual_shl_principal_paid_keur=actual_shl_principal,
                unpaid_shl_principal_keur=unpaid_shl_principal,
                actual_shl_closing_balance_keur=actual_shl_closing,
                shl_principal_receipt_keur=actual_shl_principal,
                shl_closing_balance_keur=actual_shl_closing,
                legal_equity_distribution_keur=distribution,
                # U2 Phase L: filled in the second pass below
                fcf_for_dividends_keur=0.0,
                accounting_dividend_capacity_keur=0.0,
                cash_dividend_capacity_keur=0.0,
                distributable_keur=0.0,
                gross_dividend_paid_keur=0.0,
                dividend_wht_rate=0.0,
                dividend_wht_keur=0.0,
                net_dividend_received_keur=0.0,
                unrestricted_cash_opening_keur=0.0,
                change_in_unrestricted_cash_keur=0.0,
                unrestricted_cash_closing_keur=0.0,
                cash_shortfall_keur=cash_shortfall,
                share_capital_contribution_keur=0.0,
                share_premium_contribution_keur=0.0,
                other_committed_equity_contribution_keur=0.0,
                additional_equity_contribution_keur=0.0,
                shl_cash_contribution_keur=0.0,
                pure_equity_net_cashflow_keur=pure_equity_net,
                total_sponsor_net_cashflow_keur=total_sponsor_net,
            ))

        # ── U2 Phase L: Accounting cap second pass ────────────────────────────
        if not _dist_accounting_enabled:
            # Preserve frozen G2C semantics: gross = net = legal_equity_distribution.
            # Correction N: compute proper UC roll-forward for post-BULLET-fail-closed periods.
            # Causal identity (N.2):
            #   unallocated = shl_cash_input - shl_cash_interest - shl_principal - gross_dividend
            # For normal periods = 0 (G2C first pass fully allocates released cash).
            # For post-BULLET-fail-closed: SHL service=0, dist=0 → unallocated = shl_cash_input.
            # Physical cash stays in SPV as UC (cannot be distributed, not applied to SHL).
            _new_wp = []
            _uc_running: float = 0.0  # UC carry across operating periods
            for _wp in waterfall_periods:
                _dist = _wp.legal_equity_distribution_keur
                if _wp.is_construction:
                    _uc_op = 0.0
                    _uc_chg = 0.0
                    _uc_cl = 0.0
                else:
                    _shl_in = float(getattr(_wp, "shl_cash_input_keur", 0.0) or 0.0)
                    _shl_ci = float(getattr(_wp, "shl_cash_interest_receipt_keur", 0.0) or 0.0)
                    _shl_pr = float(getattr(_wp, "actual_shl_principal_paid_keur", 0.0) or 0.0)
                    _unalloc = _shl_in - _shl_ci - _shl_pr - _dist
                    # Fail closed if materially negative (rounding is acceptable).
                    if _unalloc < -1e-6:
                        raise ValueError(
                            f"G2C generic trapped-cash identity: unallocated_released_cash="
                            f"{_unalloc:.6f} kEUR at period {_wp.period_index} — "
                            f"negative means cash over-allocated; shl_in={_shl_in:.4f}, "
                            f"shl_ci={_shl_ci:.4f}, shl_pr={_shl_pr:.4f}, dist={_dist:.4f}"
                        )
                    _unalloc = max(0.0, _unalloc)
                    _uc_op = _uc_running
                    _uc_chg = _unalloc
                    _uc_cl = _uc_op + _unalloc
                    _uc_running = _uc_cl
                _new_wp.append(dataclasses.replace(
                    _wp,
                    fcf_for_dividends_keur=_dist,
                    accounting_dividend_capacity_keur=_dist,
                    cash_dividend_capacity_keur=_dist,
                    distributable_keur=_dist,
                    gross_dividend_paid_keur=_dist,
                    dividend_wht_rate=0.0,
                    dividend_wht_keur=0.0,
                    net_dividend_received_keur=_dist,
                    unrestricted_cash_opening_keur=_uc_op,
                    change_in_unrestricted_cash_keur=_uc_chg,
                    unrestricted_cash_closing_keur=_uc_cl,
                    # pure_equity_net_cashflow_keur and total_sponsor_net_cashflow_keur
                    # keep the original values set in the first pass
                ))
            waterfall_periods = _new_wp
            # Skip U2 fixed-point entirely — no cash reserve interest without distribution policy
            break

        # M.5: COD opening equity state from construction P&L
        _shl_pik = getattr(financing, "shl_construction_pik_keur", 0.0) or 0.0
        _const_pl = getattr(project_inputs.tax, "construction_pl", None)
        _pre_op_opex = getattr(_const_pl, "pre_operational_opex_keur", 0.0) if _const_pl else 0.0
        _construction_net_income = -(_shl_pik + _pre_op_opex)

        # S.2: Use the ONE reusable transition helper for accounting/dividend/UC/FI.
        (
            waterfall_periods, _uc_closing_by_idx, _gd_by_idx,
            _re_closing_by_idx, _lr_closing_by_idx, _new_fi_by_idx, _fi_schedule,
        ) = _u2_accounting_and_fi_pass(
            model_result,
            _fi_by_idx,
            waterfall_periods,
            _construction_net_income,
            dsra_opening_by_idx,
        )

        # ── Convergence check ────────────────────────────────────────────────────
        _all_idx = set(_new_fi_by_idx) | set(_fi_by_idx)
        _fi_converged = all(
            abs(_new_fi_by_idx.get(i, 0.0) - _fi_by_idx.get(i, 0.0)) < _U2_TOL
            for i in _all_idx
        )
        _uc_idx = set(_uc_closing_by_idx) | set(_prev_uc)
        _uc_converged = all(
            abs(_uc_closing_by_idx.get(i, 0.0) - _prev_uc.get(i, 0.0)) < _U2_TOL
            for i in _uc_idx
        )
        _gd_idx = set(_gd_by_idx) | set(_prev_gd)
        _gd_converged = all(
            abs(_gd_by_idx.get(i, 0.0) - _prev_gd.get(i, 0.0)) < _U2_TOL
            for i in _gd_idx
        )
        _converged = _fi_converged and _uc_converged and _gd_converged

        if _u2_iter > _MAX_U2_ITER and not _converged:
            raise ValueError("U2_CASH_RESERVE_INTEREST_FIXED_POINT_NOT_CONVERGED")

        _prev_fi = _fi_by_idx.copy()
        _prev_uc = _uc_closing_by_idx.copy()
        _prev_gd = _gd_by_idx.copy()
        _fi_by_idx = _new_fi_by_idx

        if _converged:
            break

    # ── S.4: True final idempotence — final_1 = T(converged_FI), final_2 = T(final_1.next_FI) ──
    # Both final_1 and final_2 use the ONE reusable _u2_accounting_and_fi_pass helper (S.2/S.3).
    # Assert max|FI2−FI1|, max|UC2−UC1|, max|gd2−gd1|, max|nd2−nd1|, max|RE2−RE1|,
    # max|LR2−LR1| ≤ _U2_TOL. Return final_2 objects.
    _final1_fi_sched = None

    # M.11 / final_1: re-run financing with converged FI, then run accounting pass
    _fi_inputs_final: tuple = tuple(
        PeriodFinancingIncomeInput(
            period_index=idx,
            financing_income_keur=val,
            authority="SOURCE_PROVEN",
        )
        for idx, val in _fi_by_idx.items()
        if val != 0.0
    )
    financing = run_project_financing_model(
        project_inputs,
        source_id=source_id,
        baseline_commit_sha=baseline_commit_sha,
        _u2_period_financing_income=_fi_inputs_final if _fi_inputs_final else None,
    )

    _final1_fi_sched = None
    if _dist_accounting_enabled and _cash_reserve_policy is not None:
        _f1_mr: ProjectModelResult = financing.project_model_result  # type: ignore[assignment]
        _f1_shl_pik = getattr(financing, "shl_construction_pik_keur", 0.0) or 0.0
        _f1_const_pl = getattr(project_inputs.tax, "construction_pl", None)
        _f1_pre_op = getattr(_f1_const_pl, "pre_operational_opex_keur", 0.0) if _f1_const_pl else 0.0
        _f1_eq_ret_base = -(_f1_shl_pik + _f1_pre_op)
        (
            _f1_wp, _f1_uc, _f1_gd, _f1_re, _f1_lr, _f1_next_fi, _final1_fi_sched,
        ) = _u2_accounting_and_fi_pass(
            _f1_mr, _fi_by_idx, waterfall_periods, _f1_eq_ret_base, dsra_opening_by_idx,
        )

        # M.12 / final_2: re-run financing with final_1.next_FI, then accounting pass
        _f2_fi_inputs: tuple = tuple(
            PeriodFinancingIncomeInput(
                period_index=idx,
                financing_income_keur=val,
                authority="SOURCE_PROVEN",
            )
            for idx, val in _f1_next_fi.items()
            if val != 0.0
        )
        _financing2 = run_project_financing_model(
            project_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
            _u2_period_financing_income=_f2_fi_inputs if _f2_fi_inputs else None,
        )
        _f2_mr: ProjectModelResult = _financing2.project_model_result  # type: ignore[assignment]
        _f2_shl_pik = getattr(_financing2, "shl_construction_pik_keur", 0.0) or 0.0
        _f2_const_pl = getattr(project_inputs.tax, "construction_pl", None)
        _f2_pre_op = getattr(_f2_const_pl, "pre_operational_opex_keur", 0.0) if _f2_const_pl else 0.0
        _f2_eq_ret_base = -(_f2_shl_pik + _f2_pre_op)
        (
            _f2_wp, _f2_uc, _f2_gd, _f2_re, _f2_lr, _f2_next_fi, _f2_fi_sched,
        ) = _u2_accounting_and_fi_pass(
            _f2_mr, _f1_next_fi, _f1_wp, _f2_eq_ret_base, dsra_opening_by_idx,
        )

        # Assert idempotence: |final_2 − final_1| < _U2_TOL for all six quantities
        _idem_uc_idx = set(_f1_uc) | set(_f2_uc)
        _idem_uc = max(
            (abs(_f2_uc.get(i, 0.0) - _f1_uc.get(i, 0.0)) for i in _idem_uc_idx),
            default=0.0,
        )
        if _idem_uc > _U2_TOL:
            raise ValueError(
                f"Q7_IDEMPOTENCE_UC_RESIDUAL: ΔUC={_idem_uc:.6e} > {_U2_TOL:.6e}. "
                "M.11 UC not idempotent."
            )
        _idem_gd_idx = set(_f1_gd) | set(_f2_gd)
        _idem_gd = max(
            (abs(_f2_gd.get(i, 0.0) - _f1_gd.get(i, 0.0)) for i in _idem_gd_idx),
            default=0.0,
        )
        if _idem_gd > _U2_TOL:
            raise ValueError(
                f"Q7_IDEMPOTENCE_GROSS_DIV_RESIDUAL: Δgross_div={_idem_gd:.6e} > {_U2_TOL:.6e}. "
                "M.11 gross dividends not idempotent."
            )
        _idem_nd = _idem_gd * (1.0 - _dividend_wht_rate)
        if _idem_nd > _U2_TOL:
            raise ValueError(
                f"Q7_IDEMPOTENCE_NET_DIV_RESIDUAL: Δnet_div={_idem_nd:.6e} > {_U2_TOL:.6e}."
            )
        _idem_fi_idx = set(_f1_next_fi) | set(_f2_next_fi)
        _idem_fi = max(
            (abs(_f2_next_fi.get(i, 0.0) - _f1_next_fi.get(i, 0.0)) for i in _idem_fi_idx),
            default=0.0,
        )
        if _idem_fi > _U2_TOL:
            raise ValueError(
                f"Q7_O4_FULL_TRANSITION_RESIDUAL_NOT_CONVERGED: ΔFI={_idem_fi:.6e} > "
                f"_U2_TOL={_U2_TOL:.6e}. M.11 re-financing broke the U2 fixed-point."
            )
        _idem_re_idx = set(_f1_re) | set(_f2_re)
        _idem_re = max(
            (abs(_f2_re.get(i, 0.0) - _f1_re.get(i, 0.0)) for i in _idem_re_idx),
            default=0.0,
        )
        _idem_lr_idx = set(_f1_lr) | set(_f2_lr)
        _idem_lr = max(
            (abs(_f2_lr.get(i, 0.0) - _f1_lr.get(i, 0.0)) for i in _idem_lr_idx),
            default=0.0,
        )

        # Return final_2 objects (S.4)
        waterfall_periods = _f2_wp
        financing = _financing2
        if _f2_fi_sched is not None:
            financing = dataclasses.replace(financing, cash_reserve_interest_schedules=_f2_fi_sched)
    elif _final1_fi_sched is not None:
        financing = dataclasses.replace(financing, cash_reserve_interest_schedules=_final1_fi_sched)
    elif _fi_schedule is not None:
        financing = dataclasses.replace(financing, cash_reserve_interest_schedules=_fi_schedule)

    # ── Aggregate totals ──────────────────────────────────────────────────────
    total_sc = sum(p.share_capital_contribution_keur for p in waterfall_periods)
    total_sp = sum(p.share_premium_contribution_keur for p in waterfall_periods)
    total_oce = sum(p.other_committed_equity_contribution_keur for p in waterfall_periods)
    total_ae = sum(p.additional_equity_contribution_keur for p in waterfall_periods)
    total_le = total_sc + total_sp + total_oce + total_ae
    total_shl_contrib = sum(p.shl_cash_contribution_keur for p in waterfall_periods)
    total_sponsor_contrib = total_le + total_shl_contrib

    total_shl_int_recd = sum(p.shl_cash_interest_receipt_keur for p in waterfall_periods)
    total_shl_prin_recd = sum(p.shl_principal_receipt_keur for p in waterfall_periods)
    total_distributions = sum(p.legal_equity_distribution_keur for p in waterfall_periods)
    total_gross_div = sum(p.gross_dividend_paid_keur for p in waterfall_periods)
    total_net_div = sum(p.net_dividend_received_keur for p in waterfall_periods)
    total_covenant_locked = sum(p.covenant_locked_keur for p in waterfall_periods)
    # N.2: sponsor receipts uses net dividends when distribution accounting is enabled,
    # or the original legal_equity_distribution sum (=gross=net) otherwise.
    total_sponsor_receipts = (
        (total_net_div if _dist_accounting_enabled else total_distributions)
        + total_shl_int_recd + total_shl_prin_recd
    )
    total_dsrf_fee = sum(p.dsrf_commitment_fee_keur for p in waterfall_periods)
    # Sum of positive DA closings = total locked cash in DA (shortfall negatives excluded)
    total_da_locked = sum(
        max(0.0, p.distribution_account_closing_keur)
        for p in waterfall_periods if not p.is_construction
    )

    # Gate summary
    operating_with_ds = [
        p for p in waterfall_periods
        if not p.is_construction and p.distribution_gate_status != DistributionGateStatus.DSCR_UNAVAILABLE_GATE_OPEN
    ]
    periods_locked = sum(
        1 for p in waterfall_periods
        if p.distribution_gate_status in (
            DistributionGateStatus.LOCKED_DSCR_BELOW_LOCKUP,
            DistributionGateStatus.LOCKED_COVENANT_GATE,
        )
    )
    periods_with_ds = len(operating_with_ds)

    # ── Return metrics — delegated to G2B authority ───────────────────────────
    pe_cfs = [p.pure_equity_net_cashflow_keur for p in waterfall_periods]
    pe_dates = [p.cashflow_date for p in waterfall_periods]
    ts_cfs = [p.total_sponsor_net_cashflow_keur for p in waterfall_periods]

    (
        pe_xirr, pe_xirr_status,
        pe_moic, pe_moic_status,
        ts_xirr, ts_xirr_status,
        ts_moic, ts_moic_status,
    ) = compute_gated_sponsor_return_metrics(
        cashflow_dates=pe_dates,
        pure_equity_cashflows=pe_cfs,
        total_sponsor_cashflows=ts_cfs,
        total_legal_equity_contributed_keur=total_le,
        total_sponsor_contributed_keur=total_sponsor_contrib,
    )

    # Fail-closed overrides: BULLET takes priority; deductible feedback applies when no BULLET.
    if bullet_unpaid_active:
        _bu = ReturnMetricStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY
        pe_xirr = None; pe_xirr_status = _bu
        pe_moic = None; pe_moic_status = _bu
        ts_xirr = None; ts_xirr_status = _bu
        ts_moic = None; ts_moic_status = _bu
    elif deductible_feedback_active:
        _fb = ReturnMetricStatus.UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED
        pe_xirr = None; pe_xirr_status = _fb
        pe_moic = None; pe_moic_status = _fb
        ts_xirr = None; ts_xirr_status = _fb
        ts_moic = None; ts_moic_status = _fb

    deductible_feedback_status = (
        _G2C_DEDUCTIBLE_FEEDBACK_STATUS if deductible_feedback_active else None
    )
    # N.1: return summary uses net dividends so that legal_equity.total_receipts_keur
    # is consistent with pure_equity_net_cashflow_keur (post-WHT).
    # For non-distribution-accounting projects: gross == net (no WHT applied).
    _legal_equity_receipts = total_net_div if _dist_accounting_enabled else total_distributions
    return_summary = build_decision_complete_return_summary(
        project_inputs=project_inputs,
        financing=financing,
        waterfall_periods=tuple(waterfall_periods),
        pure_equity_xirr=pe_xirr,
        pure_equity_xirr_status=pe_xirr_status,
        pure_equity_moic=pe_moic,
        pure_equity_moic_status=pe_moic_status,
        total_sponsor_xirr=ts_xirr,
        total_sponsor_xirr_status=ts_xirr_status,
        total_sponsor_moic=ts_moic,
        total_sponsor_moic_status=ts_moic_status,
        total_legal_equity_contributed_keur=total_le,
        total_legal_equity_distributions_keur=_legal_equity_receipts,
        total_sponsor_contributed_keur=total_sponsor_contrib,
        total_sponsor_receipts_keur=total_sponsor_receipts,
        deductible_shl_covenant_feedback_status=deductible_feedback_status,
        shl_repayment_mode=(
            shl_repayment_mode.value if shl_repayment_mode is not None else None
        ),
        shl_maturity_period_index=shl_maturity_idx,
    )
    valuation_summary = build_decision_complete_valuation_summary(
        project_inputs=project_inputs,
        financing=financing,
        project_return=return_summary.project,
        senior_terminal=return_summary.terminal.senior,
    )

    return CovenantGatedWaterfallResult(
        financing_result=financing,
        distribution_lockup_dscr=distribution_lockup_dscr,
        waterfall_periods=tuple(waterfall_periods),
        total_share_capital_contributed_keur=total_sc,
        total_share_premium_contributed_keur=total_sp,
        total_other_committed_equity_contributed_keur=total_oce,
        total_additional_equity_contributed_keur=total_ae,
        total_legal_equity_contributed_keur=total_le,
        total_shl_cash_contributed_keur=total_shl_contrib,
        total_sponsor_contributed_keur=total_sponsor_contrib,
        total_shl_cash_interest_received_keur=total_shl_int_recd,
        total_shl_principal_received_keur=total_shl_prin_recd,
        total_legal_equity_distributions_keur=total_gross_div,
        total_covenant_locked_keur=total_covenant_locked,
        total_sponsor_receipts_keur=total_sponsor_receipts,
        total_gross_dividend_paid_keur=total_gross_div,
        total_net_dividend_received_keur=total_net_div,
        pure_equity_xirr=pe_xirr,
        pure_equity_xirr_status=pe_xirr_status,
        pure_equity_moic=pe_moic,
        pure_equity_moic_status=pe_moic_status,
        total_sponsor_xirr=ts_xirr,
        total_sponsor_xirr_status=ts_xirr_status,
        total_sponsor_moic=ts_moic,
        total_sponsor_moic_status=ts_moic_status,
        periods_locked_by_dscr=periods_locked,
        total_periods_with_senior_ds=periods_with_ds,
        total_dsrf_commitment_fee_keur=total_dsrf_fee,
        total_distribution_account_locked_keur=total_da_locked,
        distribution_account_status=_G2C_DA_STATUS_CAUSAL,
        shl_bullet_unpaid_at_maturity=bullet_unpaid_active,
        reserve_support_gate_status_summary=_G2C_RESERVE_GATE_STATUS,
        deductible_shl_covenant_feedback_status=deductible_feedback_status,
        return_summary=return_summary,
        valuation_summary=valuation_summary,
    )

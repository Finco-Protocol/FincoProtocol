"""financial_engine.financial_statements.assembly — Phase C3 statement assembly.

Clean sources → statement assembly → presentation. STRICTLY DOWNSTREAM:
consumes only already-authoritative clean-engine results attached to the
G2C result; performs roll-forwards and identity checks; never recomputes
tax, debt, SHL or distributions; never feeds back into the engine.

Canonical axis: the model period grid (model.periods). G2C waterfall
periods live on their own 1-based construction+operating axis and are
joined by cashflow_date == period_end (date join, validated — mismatch
fails closed with STATEMENT_PERIOD_AXIS_MISMATCH).

Axis validation contract (Correction A): every consumed schedule axis
(tax, Senior, SHL, DSRA) must be a duplicate-free, gap-free contiguous run
of model period indices; schedules may END early (SHL ends at payoff,
Senior at maturity) — later model periods carry the terminal balance
forward causally. Gaps, duplicates, extra indices or a wrong start fail
closed. No decorative governance flags.

PF cash boundaries (Correction A):
  fcf_banks_keur        = canonical Base CFADS (TaxAndCfadsSchedules.cfads_keur)
  post_senior_cash_keur = G2C signed_post_senior_keur (DIFFERENT R84-style
                          boundary) — exposed as separate lines; identity
                          fcf_banks − senior_debt_service = post_senior_cash
                          proved per period by the C3 suite.
  Construction financing cash rows come from the typed
  ConstructionFundingResult authority joined on the construction axis's
  OWN canonical dates — never silently zeroed; an unmapped construction
  date fails closed.
"""
from __future__ import annotations

from datetime import date

from financial_engine.financial_statements.contracts import (
    AccountingPolicies,
    AccountingPolicyAuthority,
    BalanceSheetPeriod,
    BookCapitalizationTreatment,
    FixedAssetRollForwardPeriod,
    FinancialStatementsResult,
    IncomeStatementPeriod,
    LineAuthority,
    PFCashWaterfallPeriod,
    RetainedEarningsPeriod,
    StatementStatus,
    TaxBridgePeriod,
)

_TOLERANCE_KEUR = 1e-6


def _at(vector, position: int):
    try:
        value = vector[position]
    except (IndexError, TypeError, KeyError):
        return None
    return None if value is None else float(value)


def _is_finite(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) != float("inf")


class _AxisMismatch(ValueError):
    def __init__(self, detail: str):
        super().__init__(f"STATEMENT_PERIOD_AXIS_MISMATCH: {detail}")
        self.detail = detail


class _TypedUnavailable(ValueError):
    """Internal fail-closed signal carrying its own statement status."""

    def __init__(self, status, detail: str):
        super().__init__(f"{status.value}: {detail}")
        self.status = status
        self.detail = detail


def _expected_axis_contract(model_periods, project_inputs):
    """Build the PR-F1 CanonicalAxisContract from the canonical model periods
    and the production Senior policy (Correction B §5-§6: reuse the existing
    axis authority; never self-author a weaker C3 axis definition)."""
    from finco_core.engine.axis_contract import CanonicalAxisContract
    from financial_engine.senior_debt.project_adapter import (
        build_senior_debt_contract_from_project_inputs,
    )
    try:
        senior_policy, _ = build_senior_debt_contract_from_project_inputs(
            project_inputs, tuple(model_periods)
        )
    except Exception as exc:
        raise _AxisMismatch(
            f"senior policy reconstruction failed: {type(exc).__name__}: {exc}"
        ) from exc
    return CanonicalAxisContract.from_periods_and_policy(
        tuple(model_periods), senior_policy
    )


def _axis_checked(name: str, period_indices, values, expected_indices):
    """Correction C §16: single dedicated axis-validation helper.

    Runs the canonical PR-F1 map_period_vector authority (exact expected
    indices + parallel-vector length enforcement) and converts ONLY the
    known canonical axis error codes (AXIS_* / PERIOD_VECTOR_*) into the
    internal _AxisMismatch signal. Any other ValueError is an unexpected
    defect and propagates unchanged."""
    from finco_core.engine.period_engine import map_period_vector
    try:
        return map_period_vector(
            period_indices, values, label=name, expected_indices=expected_indices
        )
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith(("AXIS_PERIOD_", "PERIOD_VECTOR_")):
            raise _AxisMismatch(msg) from exc
        raise


def _map_opening_re_label(apc) -> str:
    """Map apc.preconstruction_retained_earnings_authority to the correct LineAuthority string.

    USER_CONFIGURED is explicitly NOT SOURCE_PROVEN — it is user input, not source evidence.
    """
    auth = getattr(apc, "preconstruction_retained_earnings_authority", None)
    if auth is None:
        return LineAuthority.UNRESOLVED.value
    auth_val = getattr(auth, "value", str(auth))
    if auth_val == "SOURCE_PROVEN":
        return LineAuthority.SOURCE_PROVEN_CONFIGURATION.value
    elif auth_val == "USER_CONFIGURED":
        return LineAuthority.USER_CONFIGURED_ACCOUNTING_POLICY.value
    elif auth_val == "GENERIC_FINCO_POLICY":
        return LineAuthority.GENERIC_FINCO_ACCOUNTING_POLICY.value
    else:
        return LineAuthority.UNRESOLVED.value


def _fail_closed(status: StatementStatus, detail: str) -> FinancialStatementsResult:
    return FinancialStatementsResult(
        status=status,
        project_inputs_summary={},
        income_statement_status=status,
        income_statement_periods=(),
        tax_bridge_status=status,
        tax_bridge_periods=(),
        terminal_unpaid_tax_keur=None,
        cash_flow_status=status,
        pf_cash_waterfall_periods=(),
        fixed_asset_status=status,
        fixed_asset_periods=(),
        retained_earnings_status=status,
        retained_earnings_periods=(),
        balance_sheet_status=status,
        balance_sheet_periods=(),
        accounting_policies=AccountingPolicies(),
        unavailable_reasons={"detail": detail},
    )


def assemble_decision_complete_financial_statements(
    g2c_result,
    project_inputs=None,
) -> FinancialStatementsResult:
    """Public entry — converts internal _AxisMismatch into a typed
    STATEMENT_PERIOD_AXIS_MISMATCH result (fail closed, nothing zeroed)."""
    try:
        return _assemble_statements_checked(g2c_result, project_inputs)
    except _TypedUnavailable as exc:
        return _fail_closed(exc.status, exc.detail)
    except _AxisMismatch as exc:
        return _fail_closed(StatementStatus.STATEMENT_PERIOD_AXIS_MISMATCH, exc.detail)
    # Correction C §16: the public exception contract is NARROW — only
    # _TypedUnavailable and _AxisMismatch become typed fail-closed results.
    # Unexpected generic ValueError must propagate (no broad masking).


def _assemble_statements_checked(g2c_result, project_inputs):
    fin = g2c_result.financing_result
    model = fin.project_model_result
    op = model.operating_schedules
    tax = model.tax_and_cfads
    senior = model.senior_debt
    shl = model.shareholder_loan
    dsra = getattr(model, "cash_dsra", None)
    wps = g2c_result.waterfall_periods

    # B1 fix: blocker-reasons registry initialized before any branch can
    # write to it (construction-None previously wrote before init).
    unavailable: dict[str, str] = {}

    model_periods = list(model.periods)
    model_indices = [p.period_index for p in model_periods]

    # Correction B §5-§7: exact canonical axes from the PR-F1 authority plus
    # parallel-vector length enforcement through map_period_vector. No
    # weaker independent C3 axis definition, no raw dict(zip(...)).
    contract = _expected_axis_contract(model_periods, project_inputs)

    # Validation pass: each consumed vector must match its canonical axis
    # exactly (indices AND length) — _axis_checked raises _AxisMismatch
    # otherwise and lets unexpected ValueErrors propagate.
    _axis_checked(
        "operating", op.period_indices, op.revenue_keur, contract.full_axis)
    _axis_checked(
        "tax", tax.period_indices, tax.taxable_profit_keur, contract.full_axis)
    _axis_checked(
        "shl", shl.period_indices, shl.shl_gross_interest_keur, contract.full_axis)
    # Correction D: remove self-authorization fallback.  The only valid
    # source for senior_expected is the independently-derived axis contract
    # (PR-F1 authority).  Falling back to tuple(senior.period_indices) would
    # validate the senior result against ITSELF — any axis defect in the
    # solver output would pass silently.  When contract.senior_axis is None
    # the project has no senior debt; the solver result must also be empty.
    if contract.senior_axis is None:
        if tuple(senior.period_indices):
            raise _AxisMismatch(
                "senior_axis absent from axis contract but senior result "
                f"carries {len(senior.period_indices)} period(s); axis "
                "contract must be rebuilt to include the senior policy."
            )
        senior_expected: tuple = ()
    else:
        senior_expected = contract.senior_axis
    _axis_checked(
        "senior", senior.period_indices, senior.senior_interest_keur,
        senior_expected)
    if dsra is not None:
        _axis_checked(
            "dsra",
            [pr.period_index for pr in dsra.period_results],
            [pr.closing_balance_keur for pr in dsra.period_results],
            contract.full_axis)

    # Position maps for O(1) access (validated above).
    op_pos = {i: pos for pos, i in enumerate(op.period_indices)}
    tax_pos = {i: pos for pos, i in enumerate(tax.period_indices)}
    shl_pos = {i: pos for pos, i in enumerate(shl.period_indices)}
    senior_pos = {i: pos for pos, i in enumerate(senior.period_indices)}
    dsra_pos: dict[int, int] = {}
    if dsra is not None:
        dsra_pos = {pr.period_index: pos for pos, pr in enumerate(dsra.period_results)}

    for label, vec in (
        ("senior.principal", senior.senior_principal_keur),
        ("senior.ds", senior.senior_debt_service_keur),
        ("senior.closing", senior.senior_debt_closing_keur),
        ("shl.principal", shl.shl_principal_keur),
        ("shl.closing", shl.shl_closing_keur),
        ("tax.cit_accrual", tax.tax_keur),
        ("tax.cash", tax.corporate_tax_cash_keur),
    ):
        _axis_checked(
            label,
            senior.period_indices if label.startswith("senior") else (
                shl.period_indices if label.startswith("shl") else tax.period_indices),
            vec,
            senior_expected
            if label.startswith("senior") else contract.full_axis)

    # G2C waterfall date join with duplicate/missing detection.
    wp_by_date: dict = {}
    for w in wps:
        d = getattr(w, "cashflow_date", None)
        if d is None:
            raise _AxisMismatch("G2C waterfall period without a cashflow date")
        if d in wp_by_date:
            raise _AxisMismatch(f"G2C waterfall has a duplicate cashflow date: {d}")
        wp_by_date[d] = w
    # Every OPERATING model period must have a dated G2C counterpart.
    # Construction stubs without a G2C event are allowed: their cash
    # movements are covered by the construction funding authority (joined
    # on construction's own dates below), not by the operating waterfall.
    unmatched_operating = [
        p.period_index for p in model_periods
        if getattr(p, "is_operation", False)
        and getattr(p, "period_end", None) not in wp_by_date
    ]
    if unmatched_operating:
        raise _AxisMismatch(
            "operating model periods without a dated G2C waterfall "
            f"counterpart: {unmatched_operating[:10]}"
        )

    # Phase C3 Correction A: construction financing is exposed at its OWN
    # native grain as a separate statement section (typed
    # ConstructionFundingResult authority, pass-through — no re-allocation
    # onto the model grid, no silent zeroing). Operating PF rows carry no
    # construction fields; the construction section carries all
    # construction uses/sources. PF cash is therefore complete: the
    # operating waterfall AND the construction section are both
    # authoritative.
    construction_rows: list = []
    construction_grain = "native_construction_axis"
    non_construction_fc_row = None
    funding_audit: dict = {}
    cfr = getattr(fin, "construction_funding", None)
    if cfr is None:
        # B1: truthful typed fail-closed result — no NameError, no silent
        # None, no fabricated zero construction cash.
        raise _TypedUnavailable(
            StatementStatus.PF_CASH_CONSTRUCTION_AUTHORITY_UNAVAILABLE,
            "no construction funding authority is attached to this run; "
            "the PF statement cannot claim a complete sources/uses bridge "
            "without it.",
        )
    from financial_engine.financial_statements.contracts import (
        ConstructionFundingStatementRow,
    )
    for cp in getattr(cfr, "periods", ()) or ():
        construction_rows.append(ConstructionFundingStatementRow(
            funding_period_index=cp.period_index,
            period_start=getattr(cp, "period_start", None),
            period_end=getattr(cp, "period_end", None),
            cashflow_date=getattr(cp, "cashflow_date", None),
            project_cash_uses_keur=float(getattr(cp, "project_cash_uses_keur", 0.0) or 0.0),
            senior_draw_keur=float(getattr(cp, "senior_draw_keur", 0.0) or 0.0),
            junior_or_other_funding_draw_keur=float(
                getattr(cp, "junior_or_other_main_funding_draw_keur", 0.0) or 0.0),
            share_capital_draw_keur=float(getattr(cp, "share_capital_draw_keur", 0.0) or 0.0),
            share_premium_draw_keur=float(getattr(cp, "share_premium_draw_keur", 0.0) or 0.0),
            other_committed_equity_draw_keur=float(
                getattr(cp, "other_committed_equity_draw_keur", 0.0) or 0.0),
            additional_equity_draw_keur=float(
                getattr(cp, "additional_equity_draw_keur", 0.0) or 0.0),
            shl_cash_draw_keur=float(getattr(cp, "shl_cash_draw_keur", 0.0) or 0.0),
            total_sponsor_cash_draw_keur=float(
                getattr(cp, "total_sponsor_cash_draw_keur", 0.0) or 0.0),
            total_sources_keur=float(getattr(cp, "total_sources_keur", 0.0) or 0.0),
            sources_uses_difference_keur=float(
                getattr(cp, "sources_uses_difference_keur", 0.0) or 0.0),
        ))

    # Correction B §10/§12: non-construction FC/COD funding use exposed
    # exactly once as a funding movement; funding audit identity proven:
    #   construction uses + FC/COD uses == total_audit_uses
    #   construction sources + FC/COD sources == total_audit_sources
    #   total residual ≈ 0
    non_construction_fc_row = None
    total_constr_uses = sum(r.project_cash_uses_keur for r in construction_rows)
    total_constr_sources = sum(r.total_sources_keur for r in construction_rows)
    ncu = getattr(cfr, "non_construction_fc_use", None) if cfr is not None else None
    if ncu is not None:
        from financial_engine.financial_statements.contracts import (
            NonConstructionFcFundingStatementRow,
        )
        non_construction_fc_row = NonConstructionFcFundingStatementRow(
            kind="FC_COD",
            policy=ncu.policy,
            uses_keur=ncu.uses_keur,
            senior_draw_keur=ncu.senior_draw_keur,
            shl_draw_keur=ncu.shl_draw_keur,
            junior_draw_keur=ncu.junior_draw_keur,
            share_capital_draw_keur=ncu.share_capital_draw_keur,
            share_premium_draw_keur=ncu.share_premium_draw_keur,
            other_committed_equity_draw_keur=ncu.other_committed_equity_draw_keur,
            additional_equity_draw_keur=ncu.additional_equity_draw_keur,
            total_sources_keur=ncu.total_sources_keur,
        )
    funding_audit = {
        "construction_uses_keur": total_constr_uses,
        "construction_sources_keur": total_constr_sources,
        "non_construction_fc_uses_keur": getattr(ncu, "uses_keur", 0.0) or 0.0,
        "non_construction_fc_sources_keur": getattr(ncu, "total_sources_keur", 0.0) or 0.0,
        "total_audit_uses_keur": getattr(cfr, "total_audit_uses_keur", None)
        if cfr is not None else None,
        "total_audit_sources_keur": getattr(cfr, "total_audit_sources_keur", None)
        if cfr is not None else None,
        "total_audit_residual_keur": getattr(cfr, "total_audit_residual_keur", None)
        if cfr is not None else None,
    }

    pnl_periods: list[IncomeStatementPeriod] = []
    tax_periods: list[TaxBridgePeriod] = []
    pf_periods: list[PFCashWaterfallPeriod] = []
    fa_periods: list[FixedAssetRollForwardPeriod] = []
    re_periods: list[RetainedEarningsPeriod] = []
    bs_periods: list[BalanceSheetPeriod] = []

    # I.12: initial equity includes construction funding equity draws so the
    # BS is not missing pre-COD share capital/premium from period 1 onward.
    _construction_sc_total = sum(r.share_capital_draw_keur for r in construction_rows)
    _construction_sp_total = sum(r.share_premium_draw_keur for r in construction_rows)
    _nc_fc_sc = float(getattr(non_construction_fc_row, "share_capital_draw_keur", 0.0) or 0.0) if non_construction_fc_row else 0.0
    _nc_fc_sp = float(getattr(non_construction_fc_row, "share_premium_draw_keur", 0.0) or 0.0) if non_construction_fc_row else 0.0

    cumulative_book_dep = 0.0
    cumulative_share_capital = _construction_sc_total + _nc_fc_sc
    cumulative_share_premium = _construction_sp_total + _nc_fc_sp
    non_finite = False
    # I.2/I.3: CIT accrual vs cash timing roll-forward.
    # Opening = 0 (explicit greenfield causal policy: no pre-project tax liability).
    _cit_roll_open: float = 0.0
    _cit_close_by_idx: dict[int, float] = {}

    # Correction B §18: causal opening retained earnings at COD from typed
    # construction accounting. Construction-period NI is complete when the
    # typed SHL construction accounting is EXPENSE_TO_PNL (policy-defined
    # for Generic Wind Reference/Generic Solar Reference): NI = -SHL gross interest (EBITDA/book dep zero
    # rows, CIT accrual 0 on the construction loss).
    tax_pol = getattr(project_inputs, "tax", None) if project_inputs is not None else None
    treatment_value = getattr(
        getattr(tax_pol, "shl_construction_accounting", None), "value", None)

    # Correction E: accounting provenance from typed config supplied by the
    # project factory.  Assembly never reads project identity (code, name,
    # country+code combination, or any whitelist) to derive accounting
    # behaviour.  When no config is provided the generic/unavailable defaults
    # apply — no implicit activation of policy-defined policies.
    from financial_engine.financial_statements.contracts import (
        AccountingPolicyConfig as _APC,
    )
    _raw_apc = getattr(project_inputs, "accounting_policy_config", None) if project_inputs is not None else None
    _apc: _APC = _raw_apc if isinstance(_raw_apc, _APC) else _APC()

    # SHL construction accounting authority comes from typed config.
    if treatment_value == "expense_to_pnl":
        _shl_accounting_authority = _apc.shl_construction_accounting_authority
        if _shl_accounting_authority == AccountingPolicyAuthority.UNRESOLVED:
            _shl_accounting_authority = AccountingPolicyAuthority.GENERIC_FINCO_POLICY
    elif treatment_value is None:
        _shl_accounting_authority = AccountingPolicyAuthority.UNRESOLVED
    else:
        _shl_accounting_authority = AccountingPolicyAuthority.GENERIC_FINCO_POLICY

    _book_cap_authority = _apc.book_capitalization_authority
    _opening_re_pol_authority = _apc.opening_re_authority
    # H.3: FI authority comes from the U2 schedule itself, not from a C3 policy flag.
    # Resolution:
    #   schedule is None + policy None/disabled → FI=0, ZERO_BY_POLICY
    #   schedule is None + policy enabled+unresolved → FINANCING_INCOME_AUTHORITY_UNAVAILABLE
    #   schedule present, authority != UNRESOLVED → consume schedule authority
    _cri = getattr(fin, "cash_reserve_interest_schedules", None)
    _cri_policy = getattr(project_inputs, "cash_reserve_interest_policy", None) if project_inputs is not None else None
    _fi_by_period: dict = {}
    _fi_authority_str: str = "ZERO_BY_POLICY"
    _fi_resolved: bool = True  # default: zero by policy (no schedule, no enabled policy)
    if _cri is not None:
        # H.4: validate FI axis using canonical axis contract.
        _fi_axis_indices = [int(pr.period_index) for pr in _cri.period_results]
        _fi_dates = {int(pr.period_index): (pr.period_start, pr.period_end) for pr in _cri.period_results}
        # Uniqueness check.
        if len(_fi_axis_indices) != len(set(_fi_axis_indices)):
            raise _AxisMismatch(
                "FI schedule has duplicate period_index entries"
            )
        # I.7: exact ordered identity (not sorted) — wrong order must fail closed.
        _model_ordered = [int(getattr(mp, "period_index", i)) for i, mp in enumerate(model_periods)]
        if _fi_axis_indices != _model_ordered:
            raise _AxisMismatch(
                f"FI schedule period indices (ordered) {_fi_axis_indices} "
                f"do not match model period indices (ordered) {_model_ordered}"
            )
        # I.7: also require period_start and period_end match at each position.
        for _fi_pr, _mp_chk in zip(_cri.period_results, model_periods):
            _fi_ps = getattr(_fi_pr, "period_start", None)
            _fi_pe = getattr(_fi_pr, "period_end", None)
            _mp_ps = getattr(_mp_chk, "period_start", None)
            _mp_pe = getattr(_mp_chk, "period_end", None)
            if _fi_ps != _mp_ps:
                raise _AxisMismatch(
                    f"FI period {_fi_pr.period_index} period_start={_fi_ps} "
                    f"!= model period_start={_mp_ps}"
                )
            if _fi_pe != _mp_pe:
                raise _AxisMismatch(
                    f"FI period {_fi_pr.period_index} period_end={_fi_pe} "
                    f"!= model period_end={_mp_pe}"
                )
        # Consume values and authority.
        for _pr in _cri.period_results:
            _fi_by_period[int(_pr.period_index)] = float(_pr.calculated_financing_income_keur)
        _raw_cri_auth = getattr(_cri, "authority", None)
        if _raw_cri_auth is None or str(_raw_cri_auth) == AccountingPolicyAuthority.UNRESOLVED.value:
            _fi_resolved = False
            _fi_authority_str = "UNRESOLVED"
        else:
            _fi_authority_str = str(_raw_cri_auth)
    elif _cri_policy is not None and getattr(_cri_policy, "enabled", False):
        # Policy enabled but no schedule produced → authority gap.
        _fi_resolved = False
        _fi_authority_str = "FINANCING_INCOME_AUTHORITY_UNAVAILABLE"
    # else: no policy / policy disabled → FI=0, ZERO_BY_POLICY, resolved.

    # GFA component classification: from typed config when present, otherwise generic.
    _book_cap_components = _apc.book_capitalization_components or {
        "hard_capex": BookCapitalizationTreatment.CAPITALIZE_FIXED_ASSET.value,
        "shl_construction_interest": BookCapitalizationTreatment.EXPENSE_PNL.value,
    }
    # J.3: LR activation comes from the upstream distribution accounting
    # policy (project_inputs.distribution_accounting_policy), NOT from
    # AccountingPolicyConfig.legal_reserve_policy.  C3 is NOT a second LR
    # authority — it consumes the LR that the G2C waterfall already computed
    # under the upstream DA policy.  Three-case semantics:
    #   A. DA enabled + valid upstream authority → require all LR fields from wp
    #   B. DA disabled → LR = zero by policy
    #   C. DA enabled + UNRESOLVED authority → LEGAL_RESERVE_AUTHORITY_UNAVAILABLE
    _da_policy = (
        getattr(project_inputs, "distribution_accounting_policy", None)
        if project_inputs is not None else None
    )
    _lr_policy_enabled = bool(getattr(_da_policy, "enabled", False))
    # K.3: LR provenance maps from upstream DA policy, not _apc.legal_reserve_authority.
    _da_auth_raw = getattr(_da_policy, "authority", None)
    _da_auth_val = getattr(_da_auth_raw, "value", str(_da_auth_raw)) if _da_auth_raw is not None else None
    if _lr_policy_enabled:
        if _da_auth_val == "SOURCE_PROVEN":
            _legal_reserve_authority = AccountingPolicyAuthority.SOURCE_PROVEN
        elif _da_auth_val == "GENERIC_FINCO_POLICY":
            _legal_reserve_authority = AccountingPolicyAuthority.GENERIC_FINCO_POLICY
        else:
            _legal_reserve_authority = AccountingPolicyAuthority.UNRESOLVED
    else:
        _legal_reserve_authority = AccountingPolicyAuthority.GENERIC_FINCO_POLICY  # zero-by-policy
    # Correction G §13-§17: opening RE authority comes from typed
    # preconstruction_retained_earnings_authority, NOT from SHL treatment.
    # SHL treatment being EXPENSE_TO_PNL is a necessary accounting mechanic
    # (it determines whether construction NI flows through P&L), but does NOT
    # by itself prove the pre-construction equity starting balance.
    # Both preconstruction RE value AND authority must be present and resolved.
    _pre_re_keur = getattr(_apc, "preconstruction_retained_earnings_keur", None)
    _pre_re_auth = getattr(
        _apc, "preconstruction_retained_earnings_authority", AccountingPolicyAuthority.UNRESOLVED
    )
    _pre_re_auth_val = getattr(_pre_re_auth, "value", str(_pre_re_auth))
    _pre_re_authoritative = (
        _pre_re_keur is not None
        and _pre_re_auth_val in ("SOURCE_PROVEN", "GENERIC_FINCO_POLICY", "USER_CONFIGURED")
        and treatment_value == "expense_to_pnl"
    )
    if _pre_re_authoritative:
        opening_re_authority = True
        opening_re_status = StatementStatus.OK
    else:
        opening_re_authority = False
        opening_re_status = (
            StatementStatus.OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE
        )
    if not opening_re_authority:
        if _pre_re_auth_val == "UNRESOLVED" or _pre_re_keur is None:
            unavailable["opening_retained_earnings"] = (
                "OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE: "
                "preconstruction_retained_earnings_keur or its authority is UNRESOLVED; "
                "typed pre-construction equity starting balance required."
            )
        else:
            unavailable["opening_retained_earnings"] = (
                "OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE: the typed SHL "
                "construction accounting treatment is not EXPENSE_TO_PNL; no causal "
                "construction-P&L authority to derive opening RE."
            )
    # U1 Integration: canonical book depreciable asset basis drives GFA.
    # ProjectFinancingResult.book_depreciable_asset_basis is the ONLY financial
    # authority for C3 Gross Fixed Assets. All four projects (Solar, Wind,
    # Generic Solar Reference, Generic Wind Reference) expose a non-None basis after U1 merge.
    # No independent CFR-field reading for GFA. No policy-map-as-GFA-authority.
    basis = getattr(fin, "book_depreciable_asset_basis", None)
    gfa_keur: float | None = None
    gfa_report: dict = {}
    _gfa_unavailable_msg: str | None = None
    if basis is not None:
        gfa_keur = basis.total_keur
        gfa_report = {
            "canonical_book_gfa_keur": gfa_keur,
            "canonical_book_basis_authority": basis.authority,
            "canonical_book_basis_components": [
                {
                    "code": c.code,
                    "name": c.name,
                    "amount_keur": c.amount_keur,
                    "asset_class_code": c.asset_class_code,
                    "useful_life_override": c.useful_life_override,
                    "provenance": c.provenance,
                }
                for c in basis.components
            ],
        }
        # Audit: cfin raw IDC for Generic Wind Reference terminal IDC evidence (non-authoritative — does NOT drive GFA).
        _cfin_audit = getattr(fin, "construction_financing", None)
        if _cfin_audit is not None:
            _raw_idc = sum(_cfin_audit.senior_idc_accrual_keur)
            _cap_vec = _cfin_audit.senior_idc_capitalized_uses_keur
            _cap_idc = sum(_cap_vec) if _cap_vec is not None else None
            gfa_report["audit"] = {
                "senior_idc_raw_keur": _raw_idc,
                "senior_idc_capitalized_keur": _cap_idc,
                "senior_idc_terminal_excluded_keur": (
                    _raw_idc - _cap_idc if _cap_idc is not None else None
                ),
                "total_capitalized_financing_keur": float(
                    getattr(_cfin_audit, "total_capitalized_financing_keur", 0.0) or 0.0
                ),
                "non_authoritative": True,
            }
    else:
        _gfa_unavailable_msg = (
            "CANONICAL_BOOK_BASIS_UNAVAILABLE: "
            "ProjectFinancingResult.book_depreciable_asset_basis is None; "
            "the upstream canonical BookDepreciableAssetBasis was not populated for this run."
        )

    construction_ni_sum = 0.0
    cod_opening_re: float | None = None
    # Collect operating period data for post-loop RE/legal-reserve build.
    _op_re_inputs: list = []
    dsra_by_idx = (
        {pr.period_index: pr for pr in dsra.period_results} if dsra is not None else {}
    )

    for mp in model_periods:
        idx = mp.period_index
        oi = op_pos.get(idx)
        ti = tax_pos.get(idx)
        si = senior_pos.get(idx)
        shi = shl_pos.get(idx)
        wp = wp_by_date.get(getattr(mp, "period_end", None))
        dpr = dsra_by_idx.get(idx)

        revenue = float(getattr(mp, "revenue_keur", 0.0) or 0.0)
        opex = float(getattr(mp, "opex_keur", 0.0) or 0.0)
        ebitda = float(getattr(mp, "ebitda_keur", 0.0) or 0.0)
        book_dep = float(getattr(mp, "book_depreciation_keur", 0.0) or 0.0)
        # H.2: EBIT = EBITDA - BookDep. FI is NOT added to EBIT.
        ebit = float(getattr(mp, "ebit_keur", 0.0) or 0.0)
        # H.5: FI authority is from the U2 schedule contract, never from value != 0.
        fi = _fi_by_period.get(int(idx), 0.0)
        _fi_auth_label = (
            LineAuthority.EXISTING_CLEAN_AUTHORITY.value
            if _cri is not None
            else LineAuthority.GENERIC_FINCO_ACCOUNTING_POLICY.value
        )

        senior_int = _at(senior.senior_interest_keur, si) if si is not None else 0.0
        senior_int = senior_int or 0.0
        # P&L SHL interest = G2C canonical gross (cash + PIK) when waterfall period present;
        # G2C is authoritative because BS uses actual_shl_closing_balance_keur from the same
        # G2C output — using the SHL schedule axis instead would break the BS identity.
        if wp is not None and hasattr(wp, "shl_gross_interest_keur"):
            shl_gross = float(getattr(wp, "shl_gross_interest_keur", 0.0) or 0.0)
        else:
            shl_gross = _at(shl.shl_gross_interest_keur, shi) if shi is not None else 0.0
        shl_gross = shl_gross or 0.0
        # H.2: NetFinancial = FI - SeniorInterest - SHLGrossInterest; EBT = EBIT + NetFinancial.
        net_financial = fi - senior_int - shl_gross
        ebt = ebit + net_financial
        cit_accrual = _at(tax.tax_keur, ti) if ti is not None else 0.0
        cit_accrual = cit_accrual or 0.0
        # I.2: CIT roll-forward per period (all periods, construction + operating).
        _cash_tax_period = _at(tax.corporate_tax_cash_keur, ti) if ti is not None else 0.0
        _cash_tax_period = _cash_tax_period or 0.0
        _cit_roll_close = _cit_roll_open + cit_accrual - _cash_tax_period
        _cit_close_by_idx[int(idx)] = _cit_roll_close
        _cit_roll_open = _cit_roll_close
        net_income = ebt - cit_accrual

        for v in (revenue, opex, ebitda, book_dep, fi, ebit, senior_int, shl_gross,
                  ebt, cit_accrual, net_income):
            if not _is_finite(v):
                non_finite = True

        pnl_periods.append(IncomeStatementPeriod(
            period_index=int(idx),
            period_start=getattr(mp, "period_start", None),
            period_end=getattr(mp, "period_end", None),
            is_construction=bool(getattr(mp, "is_construction", False)),
            revenue_keur=revenue,
            opex_keur=opex,
            ebitda_keur=ebitda,
            book_depreciation_keur=book_dep,
            financing_income_keur=fi,
            ebit_keur=ebit,
            senior_interest_expense_keur=senior_int,
            shl_interest_expense_keur=shl_gross,
            net_financial_result_keur=net_financial,
            earnings_before_tax_keur=ebt,
            cit_accrual_keur=cit_accrual,
            net_income_keur=net_income,
            authority={
                "revenue": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "opex": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "ebitda": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "book_depreciation": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "financing_income": _fi_auth_label,
                "senior_interest": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "shl_interest": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "cit_accrual": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
                "ebit_ebt_net_financial_net_income": LineAuthority.DERIVED_ACCOUNTING_ROLL_FORWARD.value,
            },
        ))

        tax_periods.append(TaxBridgePeriod(
            period_index=int(idx),
            taxable_income_before_losses_keur=_at(tax.taxable_income_before_losses_audit_keur, ti),
            taxable_profit_after_losses_keur=_at(tax.taxable_profit_after_losses_audit_keur, ti),
            fiscal_reintegration_keur=_at(tax.fiscal_reintegration_audit_keur, ti),
            tax_loss_opening_keur=_at(tax.tax_loss_opening_audit_keur, ti),
            tax_loss_used_keur=_at(tax.tax_loss_used_audit_keur, ti),
            tax_loss_closing_keur=_at(tax.tax_loss_closing_audit_keur, ti),
            tax_depreciation_keur=_at(tax.tax_depreciation_audit_keur, ti),
            cit_accrual_keur=_at(tax.cit_accrual_audit_keur, ti),
            cash_tax_current_period_keur=_at(tax.cash_tax_current_period_audit_keur, ti),
            corporate_tax_cash_keur=_at(tax.corporate_tax_cash_keur, ti),
            cash_tax_bridge_reconciliation_keur=_at(tax.cash_tax_bridge_reconciliation_keur, ti),
        ))

        wp = wp if wp is not None else type("EmptyWp", (), {})()  # attribute-safe empty
        # Correction A — PF cash boundaries:
        #   fcf_banks_keur        = canonical Base CFADS (tax vector);
        #   post_senior_cash_keur = G2C signed_post_senior_keur (R84-style
        #                           post-Senior boundary) — a DIFFERENT
        #                           concept, never used as FCF Banks.
        base_cfads = _at(tax.cfads_keur, ti) or 0.0
        post_senior = float(getattr(wp, "signed_post_senior_keur", 0.0) or 0.0)
        senior_ds = _at(senior.senior_debt_service_keur, si) or 0.0
        pf_periods.append(PFCashWaterfallPeriod(
            period_index=int(idx),
            cashflow_date=getattr(mp, "period_end", None),
            is_construction=bool(getattr(mp, "is_construction", False)),
            revenue_cash_keur=revenue,
            opex_cash_keur=opex,
            ebitda_keur=ebitda,
            cash_tax_keur=_at(tax.corporate_tax_cash_keur, ti) or 0.0,
            fcf_banks_keur=base_cfads,
            senior_debt_service_keur=senior_ds,
            post_senior_cash_keur=post_senior,
            senior_cash_interest_keur=senior_int,
            senior_principal_keur=_at(senior.senior_principal_keur, si) or 0.0,
            dsra_top_up_keur=float(getattr(wp, "dsra_top_up_keur", 0.0) or 0.0),
            dsra_draw_keur=float(getattr(wp, "dsra_draw_keur", 0.0) or 0.0),
            dsra_release_keur=float(getattr(wp, "dsra_release_keur", 0.0) or 0.0),
            distribution_account_inflow_keur=float(
                getattr(wp, "distribution_account_inflow_keur", 0.0) or 0.0),
            distribution_account_release_keur=float(
                getattr(wp, "distribution_account_release_keur", 0.0) or 0.0),
            distribution_account_closing_keur=float(
                getattr(wp, "distribution_account_closing_keur", 0.0) or 0.0),
            shl_cash_interest_keur=float(getattr(wp, "shl_cash_interest_receipt_keur", 0.0) or 0.0),
            shl_pik_keur=float(getattr(wp, "shl_pik_keur", 0.0) or 0.0),
            shl_principal_paid_keur=float(
                getattr(wp, "actual_shl_principal_paid_keur", 0.0) or 0.0),
            shl_unpaid_principal_keur=float(
                getattr(wp, "unpaid_shl_principal_keur", 0.0) or 0.0),
            legal_equity_distribution_keur=float(
                getattr(wp, "legal_equity_distribution_keur", 0.0) or 0.0),
        ))

        # Fixed assets: accumulated BOOK depreciation roll-forward is causal.
        # GFA is computed from ConstructionFinancingResult when available
        # (policy-defined projects with a senior construction financing run);
        # NFA = GFA − cumulative book depreciation (no disposals during ops).
        cumulative_book_dep += book_dep
        _nfa = (gfa_keur - cumulative_book_dep) if gfa_keur is not None else None
        fa_periods.append(FixedAssetRollForwardPeriod(
            period_index=int(idx),
            period_end=getattr(mp, "period_end", None),
            book_depreciation_keur=book_dep,
            accumulated_book_depreciation_keur=cumulative_book_dep,
            gross_fixed_assets_keur=gfa_keur,
            accumulated_depreciation_on_disposals_keur=0.0,
            net_fixed_assets_keur=_nfa,
        ))

        # RE inputs collection: construction periods accumulate NI for COD opening RE.
        # Operating periods are queued with gross_dividend_paid_keur (H.9: gross, not net).
        # H.7: UC consumed directly from canonical typed field. EmptyWp proxy has no such field → None.
        _wp_is_real = hasattr(wp, "unrestricted_cash_closing_keur")
        _wp_uc_close = wp.unrestricted_cash_closing_keur if _wp_is_real else None
        _wp_lr_open = getattr(wp, "opening_legal_reserve_keur", None) if _wp_is_real else None
        _wp_lr_transfer = getattr(wp, "legal_reserve_transfer_keur", None) if _wp_is_real else None
        _wp_lr_close = getattr(wp, "closing_legal_reserve_keur", None) if _wp_is_real else None
        # H.9: use gross_dividend_paid_keur for RE roll-forward (gross corporate, not net-of-WHT).
        gross_div = float(getattr(wp, "gross_dividend_paid_keur", 0.0) or 0.0) if _wp_is_real else 0.0
        legal_dist = float(getattr(wp, "legal_equity_distribution_keur", 0.0) or 0.0) if _wp_is_real else 0.0
        is_construction_period = bool(getattr(mp, "is_construction", False))
        if is_construction_period:
            if opening_re_authority:
                construction_ni_sum += net_income
        else:
            # Store: period_index, net_income, gross_div, period_end, wp_lr_open, wp_lr_transfer, wp_lr_close
            _op_re_inputs.append(
                (int(idx), net_income, gross_div, getattr(mp, "period_end", None),
                 _wp_lr_open, _wp_lr_transfer, _wp_lr_close)
            )

        # Balance sheet: build with canonical clean balances; equity filled post-loop.
        # J.5: Construction SC/SP already initialized from ConstructionFundingResult
        # draws (I.12). Only add operating-period G2C contributions here to avoid
        # double-counting. Construction-period wps (is_construction_period=True) carry
        # the same capital draw as the construction authority — adding them again would
        # overstate equity.
        if not is_construction_period and _wp_is_real:
            cumulative_share_capital += float(
                getattr(wp, "share_capital_contribution_keur", 0.0) or 0.0)
            cumulative_share_premium += float(
                getattr(wp, "share_premium_contribution_keur", 0.0) or 0.0)
        dsra_close = (
            float(dpr.closing_balance_keur) if dpr is not None else None
        )
        # H.7: UC is the canonical typed field; None when wp absent (not zero).
        _uc_val = _wp_uc_close
        bs_periods.append(BalanceSheetPeriod(
            period_index=int(idx),
            period_end=getattr(mp, "period_end", None),
            # Carry 0.0 post-repayment (si is None after senior axis ends) so BS check
            # runs for all operating periods, not just the senior-active window.
            senior_debt_balance_keur=_at(senior.senior_debt_closing_keur, si) if si is not None else 0.0,
            shl_balance_keur=(
                float(getattr(wp, "actual_shl_closing_balance_keur", 0.0) or 0.0)
                if _wp_is_real else None
            ),
            shl_unpaid_principal_keur=(
                float(getattr(wp, "unpaid_shl_principal_keur", 0.0) or 0.0)
                if _wp_is_real else None
            ),
            distribution_account_balance_keur=(
                float(getattr(wp, "distribution_account_closing_keur", 0.0) or 0.0)
                if _wp_is_real else None
            ),
            dsra_balance_keur=dsra_close,
            unrestricted_cash_keur=_wp_uc_close,
            gross_fixed_assets_keur=gfa_keur,
            accumulated_book_depreciation_keur=cumulative_book_dep,
            share_capital_keur=cumulative_share_capital,
            share_premium_keur=cumulative_share_premium,
            retained_earnings_keur=None,   # filled post-loop
            balance_check_keur=None,        # filled post-loop
        ))

    # H.8/I.8: canonical LR comes from CovenantGatedWaterfallPeriod (U2 upstream output).
    # C3 must NOT recompute LR. No roll_forward_equity_state call.
    # I.8: policy-aware per-period fail-closed validation.
    cod_opening_re = (
        (_pre_re_keur + construction_ni_sum) if opening_re_authority and _pre_re_keur is not None
        else None
    )
    _lr_computed = False
    _lr_zero_by_policy = False

    if _lr_policy_enabled:
        # All three canonical fields required; closing = opening + transfer; continuity.
        _lr_identity_ok = True
        _prev_lr_close_val: float | None = None
        for _check_item in _op_re_inputs:
            _pidx_c, _, _, _, _wlr_o_c, _wlr_t_c, _wlr_cl_c = _check_item
            if _wlr_o_c is None or _wlr_t_c is None or _wlr_cl_c is None:
                _lr_identity_ok = False
                break
            _o_f = float(_wlr_o_c); _t_f = float(_wlr_t_c); _cl_f = float(_wlr_cl_c)
            if abs(_o_f + _t_f - _cl_f) > 1e-4:
                _lr_identity_ok = False
                break
            if _prev_lr_close_val is not None and abs(_o_f - _prev_lr_close_val) > 1e-4:
                _lr_identity_ok = False
                break
            _prev_lr_close_val = _cl_f
        _lr_computed = _lr_identity_ok and bool(_op_re_inputs)
    else:
        # LR not enabled: zero by policy (status OK for generic Solar/Wind).
        _lr_zero_by_policy = True
        _lr_computed = True

    _lr_closing_by_idx: dict = {}
    _re_open = cod_opening_re
    re_periods_by_idx: dict = {}
    for _pidx, _ni, _gdiv, _pend, _wlr_open, _wlr_transfer, _wlr_close in _op_re_inputs:
        # J.4: Fail-closed on missing LR fields — no silent 0.0 substitute.
        # When DA policy is enabled, missing or invalid LR transfer → RE unavailable.
        if _lr_policy_enabled:
            if _wlr_transfer is None or not _lr_computed:
                # LR required but missing: RE unavailable for this and all subsequent periods.
                _lrt_alloc: float | None = None
                _lrt = 0.0  # unused for RE calc below; RE will be None anyway
            else:
                _lrt_alloc = float(_wlr_transfer)
                _lrt = _lrt_alloc
        else:
            _lrt_alloc = None  # zero by policy → allocation is None (not reported as a line)
            _lrt = 0.0  # zero by policy
        _lr_close_val = float(_wlr_close) if _wlr_close is not None else None
        if _lr_close_val is not None and _lr_computed:
            _lr_closing_by_idx[_pidx] = _lr_close_val
        elif not _lr_policy_enabled:
            _lr_closing_by_idx[_pidx] = 0.0  # zero by policy
        # H.9/I.9: RE closing = opening + NI - gross_dividend - LR_transfer.
        # J.4: RE closing is None when LR is required but unavailable.
        _lrt_for_re = _lrt_alloc if _lr_policy_enabled else 0.0
        _re_close = (
            None if (_re_open is None or (_lr_policy_enabled and _lrt_alloc is None))
            else _re_open + _ni - _gdiv - (_lrt_for_re or 0.0)
        )
        re_periods_by_idx[_pidx] = (_re_open, _re_close, _wlr_close, _pend, _ni, _gdiv, _lrt_for_re)
        re_periods.append(RetainedEarningsPeriod(
            period_index=_pidx,
            period_end=_pend,
            opening_retained_earnings_keur=_re_open,
            net_income_keur=_ni,
            legal_equity_distribution_keur=_gdiv,
            legal_reserve_allocation_keur=_lrt_alloc,
            closing_retained_earnings_keur=_re_close,
        ))
        if _re_open is not None and _re_close is not None:
            _re_open = _re_close
        elif _lr_policy_enabled and _lrt_alloc is None:
            _re_open = None  # propagate unavailability

    # H.10/I.5: rebuild BS periods with equity and CIT timing balance populated.
    _bs_by_idx = {bsp.period_index: bsp for bsp in bs_periods}
    bs_periods = []
    _tolerance = 1e-4
    for _bsp_orig in sorted(_bs_by_idx.values(), key=lambda x: x.period_index):
        _bidx = _bsp_orig.period_index
        _re_info = re_periods_by_idx.get(_bidx)
        _re_close_val = _re_info[1] if _re_info is not None else None
        _lr_close_bsp = float(_lr_closing_by_idx[_bidx]) if _bidx in _lr_closing_by_idx else None
        # I.2/I.5: CIT timing balance for this period.
        _net_cit = _cit_close_by_idx.get(_bidx)
        # I.11: real BS identity.
        # Assets = NFA + UC + DSRA + DA (CIT receivable handled via signed net_cit).
        # L+E = Senior + SHL + SC + SP + LR + RE.
        # balance_check = Assets - L+E_excl_cit - net_cit_payable (should be 0).
        # Positive net_cit = liability (on L+E side); negative = receivable (asset side).
        _nfa_v = (
            (_bsp_orig.gross_fixed_assets_keur - _bsp_orig.accumulated_book_depreciation_keur)
            if _bsp_orig.gross_fixed_assets_keur is not None else None
        )
        _balance_check: float | None = None
        if (
            _nfa_v is not None
            and _bsp_orig.unrestricted_cash_keur is not None
            and _bsp_orig.dsra_balance_keur is not None
            and _bsp_orig.distribution_account_balance_keur is not None
            and _re_close_val is not None
            and _lr_close_bsp is not None
            and _bsp_orig.shl_balance_keur is not None
            and _bsp_orig.share_capital_keur is not None
            and _bsp_orig.share_premium_keur is not None
            and _net_cit is not None
        ):
            _total_assets = (
                _nfa_v
                + _bsp_orig.unrestricted_cash_keur
                + _bsp_orig.dsra_balance_keur
                + _bsp_orig.distribution_account_balance_keur
            )
            _total_le_excl_cit = (
                (_bsp_orig.senior_debt_balance_keur or 0.0)
                + (_bsp_orig.shl_balance_keur or 0.0)
                + (_bsp_orig.share_capital_keur or 0.0)
                + (_bsp_orig.share_premium_keur or 0.0)
                + _lr_close_bsp
                + _re_close_val
            )
            _balance_check = _total_assets - _total_le_excl_cit - _net_cit
        bs_periods.append(BalanceSheetPeriod(
            period_index=_bidx,
            period_end=_bsp_orig.period_end,
            senior_debt_balance_keur=_bsp_orig.senior_debt_balance_keur,
            shl_balance_keur=_bsp_orig.shl_balance_keur,
            shl_unpaid_principal_keur=_bsp_orig.shl_unpaid_principal_keur,
            distribution_account_balance_keur=_bsp_orig.distribution_account_balance_keur,
            dsra_balance_keur=_bsp_orig.dsra_balance_keur,
            unrestricted_cash_keur=_bsp_orig.unrestricted_cash_keur,
            gross_fixed_assets_keur=_bsp_orig.gross_fixed_assets_keur,
            accumulated_book_depreciation_keur=_bsp_orig.accumulated_book_depreciation_keur,
            share_capital_keur=_bsp_orig.share_capital_keur,
            share_premium_keur=_bsp_orig.share_premium_keur,
            net_cit_payable_keur=_net_cit,
            legal_reserve_keur=_lr_close_bsp,
            retained_earnings_keur=_re_close_val,
            balance_check_keur=_balance_check,
        ))

    # I.13: status logic — only OK after each component is behaviorally complete.
    _fixed_asset_status = (
        StatementStatus.OK if gfa_keur is not None
        else StatementStatus.BOOK_CAPITALIZATION_BASIS_UNAVAILABLE
    )
    _legal_reserve_status = (
        StatementStatus.OK if _lr_computed
        else StatementStatus.LEGAL_RESERVE_AUTHORITY_UNAVAILABLE
    )
    # UC resolved when canonical field present for all OPERATING BS periods.
    _op_period_indices = {_pidx for _pidx, *_ in _op_re_inputs}
    _uc_resolved = all(
        bsp.unrestricted_cash_keur is not None
        for bsp in bs_periods
        if bsp.period_index in _op_period_indices
    ) if _op_period_indices else True
    _uc_status = StatementStatus.OK if _uc_resolved else StatementStatus.UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE
    # I.2: CIT timing balance is always computed (causal roll-forward from 0).
    _cit_payable_computed = bool(_cit_close_by_idx)
    # I.10: BS complete only when EVERY applicable operating period has a non-None balance_check.
    _op_bs_periods_list = [bsp for bsp in bs_periods if bsp.period_index in _op_period_indices]
    _op_bs_checks = [bsp.balance_check_keur for bsp in _op_bs_periods_list]
    _bs_coverage_complete = bool(_op_bs_checks) and all(v is not None for v in _op_bs_checks)
    _bs_identity_ok = _bs_coverage_complete and all(abs(v) <= _tolerance for v in _op_bs_checks if v is not None)
    _bs_complete = (
        _uc_resolved and _lr_computed and opening_re_authority
        and _cit_payable_computed and _bs_identity_ok
    )
    _bs_status = (
        StatementStatus.OK if _bs_complete else (
            StatementStatus.BALANCE_SHEET_DOES_NOT_BALANCE if _op_bs_checks and not _bs_identity_ok else
            StatementStatus.LEGAL_RESERVE_AUTHORITY_UNAVAILABLE if not _lr_computed else
            StatementStatus.OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE if not opening_re_authority else
            StatementStatus.TAX_PAYABLE_AUTHORITY_UNAVAILABLE if not _cit_payable_computed else
            StatementStatus.UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE
        )
    )
    # K.2: _re_complete derived from actual operating RE periods, not just opening authority.
    # For LR-enabled projects: require opening authority + LR computed +
    # every operating period's closing RE is non-None + continuity (opening[t+1]==closing[t]).
    # For LR-disabled (zero-by-policy): require opening authority + every closing non-None.
    _re_periods_ok = bool(re_periods)
    _re_closings_all_present = all(
        p.closing_retained_earnings_keur is not None for p in re_periods
    )
    _re_continuity_ok = True
    _prev_re_close: float | None = None
    for rp in re_periods:
        if rp.opening_retained_earnings_keur is not None and _prev_re_close is not None:
            if abs(rp.opening_retained_earnings_keur - _prev_re_close) > 1e-4:
                _re_continuity_ok = False
                break
        _prev_re_close = rp.closing_retained_earnings_keur
    _re_complete = (
        opening_re_authority
        and _re_periods_ok
        and _re_closings_all_present
        and _re_continuity_ok
        and (_lr_computed or not _lr_policy_enabled)
    )
    _re_status = (
        StatementStatus.OK if _re_complete else (
            StatementStatus.LEGAL_RESERVE_AUTHORITY_UNAVAILABLE if not _lr_computed else
            StatementStatus.OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE
        )
    )
    # K.5: Overall status gates ALL required statement statuses explicitly.
    # No decorative unused variables.
    _income_status = (
        StatementStatus.OK if _fi_resolved else StatementStatus.FINANCING_INCOME_AUTHORITY_UNAVAILABLE
    )
    _fa_status = _fixed_asset_status
    if non_finite:
        overall = StatementStatus.NON_FINITE_RESULT
    elif _income_status != StatementStatus.OK:
        overall = _income_status
    elif _fa_status != StatementStatus.OK:
        overall = _fa_status
    elif _re_status != StatementStatus.OK:
        overall = _re_status
    elif _legal_reserve_status != StatementStatus.OK:
        overall = _legal_reserve_status
    elif _uc_status != StatementStatus.OK:
        overall = _uc_status
    elif _bs_status != StatementStatus.OK:
        overall = _bs_status
    else:
        overall = StatementStatus.OK

    if gfa_keur is None and _gfa_unavailable_msg is None:
        _gfa_unavailable_msg = (
            "CANONICAL_BOOK_BASIS_UNAVAILABLE: "
            "book_depreciable_asset_basis is absent from the financing result."
        )
    # I.4: terminal CIT reconciliation (informational; same definition as roll-forward).
    _terminal_cit_rollforward = _cit_roll_open  # final closing balance after last period
    _terminal_unpaid_tax = float(getattr(tax, "terminal_unpaid_tax_keur", 0.0) or 0.0)
    _terminal_cit_reconciled = abs(_terminal_cit_rollforward - _terminal_unpaid_tax) <= 1e-4

    unavailable.update({
        **({"gross_fixed_assets": _gfa_unavailable_msg} if gfa_keur is None else {}),
        **({} if _lr_computed else {
            "legal_reserve": (
                "LEGAL_RESERVE_AUTHORITY_UNAVAILABLE: CovenantGatedWaterfallPeriod "
                "legal reserve fields missing or identity check failed."
            )
        }),
        **({} if _uc_resolved else {
            "unrestricted_cash": (
                "UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE: unrestricted_cash_closing_keur "
                "absent for one or more operating BS periods."
            )
        }),
        **({} if _fi_resolved else {
            "financing_income": (
                f"FINANCING_INCOME_AUTHORITY_UNAVAILABLE: {_fi_authority_str}"
            ),
        }),
        **({} if _bs_identity_ok else (
            {
                "balance_sheet_identity": (
                    "BALANCE_SHEET_DOES_NOT_BALANCE: one or more operating periods have "
                    f"abs(balance_check) > tolerance={_tolerance}"
                )
            } if _op_bs_checks else {}
        )),
    })

    return FinancialStatementsResult(
        status=overall,
        project_inputs_summary={
            "model_period_count": len(model_periods),
            "waterfall_period_count": len(wps),
            "g2c_dscr_authority": senior.binding_constraint,
            "construction_rows_mapped": len(construction_rows),
        },
        # H.3: income_statement_status OK when FI authority is resolved from U2 schedule
        # or when FI is zero-by-policy (no enabled policy, no schedule).
        income_statement_status=(
            StatementStatus.OK if _fi_resolved
            else StatementStatus.FINANCING_INCOME_AUTHORITY_UNAVAILABLE
        ),
        income_statement_periods=tuple(pnl_periods),
        tax_bridge_status=StatementStatus.OK,
        tax_bridge_periods=tuple(tax_periods),
        terminal_unpaid_tax_keur=float(getattr(tax, "terminal_unpaid_tax_keur", 0.0) or 0.0),
        cash_flow_status=StatementStatus.OK,
        pf_cash_waterfall_periods=tuple(pf_periods),
        construction_funding_rows=tuple(construction_rows),
        construction_funding_grain=construction_grain,
        non_construction_fc_row=non_construction_fc_row,
        funding_audit=funding_audit,
        fixed_asset_status=_fixed_asset_status,
        fixed_asset_periods=tuple(fa_periods),
        retained_earnings_status=_re_status,
        retained_earnings_periods=tuple(re_periods),
        opening_retained_earnings_status=opening_re_status,
        cod_opening_retained_earnings_keur=cod_opening_re,
        legal_reserve_status=_legal_reserve_status,
        unrestricted_cash_status=_uc_status,
        balance_sheet_status=_bs_status,
        balance_sheet_periods=tuple(bs_periods),
        accounting_policies=AccountingPolicies(
            shl_construction_accounting_authority=_shl_accounting_authority,
            legal_reserve_authority=_legal_reserve_authority,
            book_capitalization_authority=_book_cap_authority,
            opening_re_authority=_opening_re_pol_authority,
            cash_interest_income_authority=AccountingPolicyAuthority.UNRESOLVED,  # deprecated; authority from schedule
            book_capitalization_components=_book_cap_components,
            provenance={
                "baseline": "clean-engine results only (no legacy statement modules)",
                "axis": "model.periods; G2C joined by cashflow_date == period_end",
                "fi_authority": _fi_authority_str,
                "fi_schedule_present": _cri is not None,
                "lr_source": (
                    "CovenantGatedWaterfallPeriod (U2 canonical)" if (_lr_computed and _lr_policy_enabled)
                    else ("ZERO_BY_POLICY" if _lr_zero_by_policy else "UNAVAILABLE")
                ),
                "lr_closing_by_period": _lr_closing_by_idx,
                "gfa_computed": gfa_keur is not None,
                "gfa_report": gfa_report,
                "cit_roll_opening_policy": "GENERIC_FINCO_ACCOUNTING_POLICY: greenfield opening CIT balance = 0",
                "cit_terminal_reconciled": _terminal_cit_reconciled,
                "cit_terminal_rollforward_keur": _terminal_cit_rollforward,
                "cit_terminal_unpaid_tax_keur": _terminal_unpaid_tax,
                "construction_sc_keur": _construction_sc_total,
                "construction_sp_keur": _construction_sp_total,
                "bs_identity_checks": len(_op_bs_checks),
                "bs_coverage_complete": _bs_coverage_complete,
                "bs_max_residual": max((abs(v) for v in _op_bs_checks if v is not None), default=None),
            },
        ),
        unavailable_reasons=unavailable,
        authority_labels={
            "pnl": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
            "tax_bridge": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
            "pf_cash_waterfall": LineAuthority.EXISTING_CLEAN_AUTHORITY.value,
            "accumulated_book_depreciation": (
                LineAuthority.DERIVED_ACCOUNTING_ROLL_FORWARD.value),
            "retained_earnings_movements": (
                LineAuthority.DERIVED_ACCOUNTING_ROLL_FORWARD.value),
            "net_cit_payable": LineAuthority.DERIVED_ACCOUNTING_ROLL_FORWARD.value,
            "gross_fixed_assets": (
                LineAuthority.EXISTING_CLEAN_AUTHORITY.value if gfa_keur is not None
                else LineAuthority.UNRESOLVED.value
            ),
            "unrestricted_cash": (
                LineAuthority.EXISTING_CLEAN_AUTHORITY.value if _uc_resolved
                else LineAuthority.UNRESOLVED.value
            ),
            "opening_retained_earnings": (
                _map_opening_re_label(_apc)
                if opening_re_authority else LineAuthority.UNRESOLVED.value
            ),
            "legal_reserve": (
                LineAuthority.EXISTING_CLEAN_AUTHORITY.value
                if (_lr_computed and _lr_policy_enabled)
                else (
                    LineAuthority.GENERIC_FINCO_ACCOUNTING_POLICY.value
                    if _lr_zero_by_policy
                    else LineAuthority.UNRESOLVED.value
                )
            ),
        },
    )

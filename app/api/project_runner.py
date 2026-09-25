"""Production financial run API — Phase B4 clean-only single authority."""
from app.output_tables import build_waterfall_table, build_revenue_table, build_debt_table, build_returns_table, aggregate_period_table_annual


def _period_label(period) -> str:
    """Build a human-readable period label from the backend period object."""
    year_index = getattr(period, "year_index", None)
    period_in_year = getattr(period, "period_in_year", None)
    period_number = getattr(period, "period", None)

    if year_index is not None and period_in_year is not None:
        return f"Y{int(year_index)}-H{int(period_in_year)}"
    if period_number is not None:
        return f"P{int(period_number)}"
    return "Selected period"


def _build_runtime_derivation_evidence(result, project_inputs=None):
    """Return read-only derivation evidence sourced from WaterfallResult."""
    operation_periods = [
        period
        for period in getattr(result, "periods", [])
        if getattr(period, "is_operation", False)
    ]
    dscr_periods = [
        period
        for period in getattr(result, "periods", [])
        if getattr(period, "is_operation", False) and float(getattr(period, "senior_ds_keur", 0.0) or 0.0) > 0.0
    ]
    if not operation_periods:
        return {}

    operation_period_count = len(operation_periods)
    representative_operation_period = min(operation_periods, key=lambda period: getattr(period, "period", 0))
    total_cfads = sum(float(getattr(period, "cf_after_tax_keur", 0.0) or 0.0) for period in dscr_periods)
    total_senior_ds = sum(float(getattr(period, "senior_ds_keur", 0.0) or 0.0) for period in dscr_periods)

    capex = getattr(project_inputs, "capex", None)
    capex_items_attr = getattr(capex, "capex_items", None)
    capex_items = capex_items_attr() if callable(capex_items_attr) else ()

    evidence = {
        "senior_debt": {},
        "capex": {
            "display_value_keur": getattr(capex, "total_capex", None),
            "summary_method": (
                "CAPEX Total is sourced from the authoritative CAPEX structure used by the backend run. "
                "When upstream user sub-line materialization or scenario overrides are present, this displayed total "
                "reflects that authoritative structure."
            ),
            "authoritative_source": "CapexStructure.total_capex",
            "category_count": len(capex_items),
            "hierarchy_source": "CapexStructure named fields surfaced through capex.capex_items().",
            "audit_source": "ProjectInputs.capex.total_capex and ProjectInputs.capex.capex_items()",
        },
        "revenue": {
            "display_value_keur": getattr(result, "total_revenue_keur", None),
            "summary_method": "Total revenue from backend operating periods.",
            "period_formula": "Revenue_t = WaterfallPeriod.revenue_keur",
            "period_count": operation_period_count,
            "sample_period_label": _period_label(representative_operation_period),
            "sample_generation_mwh": getattr(representative_operation_period, "generation_mwh", None),
            "sample_revenue_keur": getattr(representative_operation_period, "revenue_keur", None),
            "audit_source": "WaterfallResult.total_revenue_keur and WaterfallResult.periods[].revenue_keur, generation_mwh",
            # Full operating-period series — authoritative WaterfallResult.periods[].
            # Formatted/summed by the presentation layer; economics are unchanged.
            "revenue_periods": [
                {
                    "period_label": _period_label(p),
                    "generation_mwh": getattr(p, "generation_mwh", None),
                    "revenue_keur": getattr(p, "revenue_keur", None),
                }
                for p in operation_periods
            ],
        },
        "ebitda": {
            "display_value_keur": getattr(result, "total_ebitda_keur", None),
            "summary_method": "Total EBITDA from backend operating periods.",
            "period_formula": "EBITDA_t = Revenue_t - OPEX_t",
            "period_count": operation_period_count,
            "sample_period_label": _period_label(representative_operation_period),
            "sample_revenue_keur": getattr(representative_operation_period, "revenue_keur", None),
            "sample_opex_keur": getattr(representative_operation_period, "opex_keur", None),
            "sample_ebitda_keur": getattr(representative_operation_period, "ebitda_keur", None),
            "audit_source": "WaterfallResult.total_ebitda_keur and WaterfallResult.periods[].revenue_keur, opex_keur, ebitda_keur",
        },
        "opex": {
            "display_value_keur": getattr(result, "total_opex_keur", None),
            "summary_method": "Total OPEX from backend operating periods.",
            "period_formula": "OPEX_t = WaterfallPeriod.opex_keur",
            "period_count": operation_period_count,
            "sample_period_label": _period_label(representative_operation_period),
            "sample_opex_keur": getattr(representative_operation_period, "opex_keur", None),
            "audit_source": "WaterfallResult.total_opex_keur and WaterfallResult.periods[].opex_keur",
        },
    }

    sample_senior_balance = getattr(representative_operation_period, "senior_balance_keur", None)
    sample_senior_principal = getattr(representative_operation_period, "senior_principal_keur", None)
    sample_senior_interest = getattr(representative_operation_period, "senior_interest_keur", None)
    sample_senior_ds = getattr(representative_operation_period, "senior_ds_keur", None)
    if sample_senior_balance is not None and sample_senior_principal is not None:
        evidence["senior_debt"] = {
            "display_value_keur": float(sample_senior_balance or 0.0) + float(sample_senior_principal or 0.0),
            "summary_method": (
                "Opening senior debt amount from backend operating-period debt schedule evidence. "
                "The displayed amount is anchored to the first operating-period senior balance and principal repayment fields."
            ),
            "period_count": operation_period_count,
            "sample_period_label": _period_label(representative_operation_period),
            "sample_senior_interest_keur": sample_senior_interest,
            "sample_senior_principal_keur": sample_senior_principal,
            "sample_senior_debt_service_keur": sample_senior_ds,
            "audit_source": (
                "WaterfallResult.periods[].senior_balance_keur, senior_principal_keur, "
                "senior_interest_keur, senior_ds_keur"
            ),
        }
    if not dscr_periods:
        return evidence

    representative_dscr_period = min(dscr_periods, key=lambda period: getattr(period, "period", 0))
    evidence.update({
        "dscr": {
            "display_value": getattr(result, "actual_avg_dscr", None),
            "summary_method": "Average of operating-period DSCR values with positive senior debt service.",
            "period_formula": "DSCR_t = CFADS_t / Senior Debt Service_t",
            "period_count": len(dscr_periods),
            "total_cfads_keur": total_cfads,
            "total_senior_debt_service_keur": total_senior_ds,
            "sample_period_label": _period_label(representative_dscr_period),
            "sample_cfads_keur": getattr(representative_dscr_period, "cf_after_tax_keur", None),
            "sample_senior_debt_service_keur": getattr(representative_dscr_period, "senior_ds_keur", None),
            "sample_dscr": getattr(representative_dscr_period, "dscr", None),
            "audit_source": "WaterfallResult.periods[].cf_after_tax_keur, senior_ds_keur, dscr",
        },
        "cfads": {
            "display_value_keur": total_cfads,
            "summary_method": "Total CFADS across operating periods with positive senior debt service.",
            "period_formula": "CFADS_t = WaterfallPeriod.cf_after_tax_keur",
            "period_count": len(dscr_periods),
            "sample_period_label": _period_label(representative_dscr_period),
            "sample_ebitda_keur": getattr(representative_dscr_period, "ebitda_keur", None),
            "sample_tax_keur": getattr(representative_dscr_period, "tax_keur", None),
            "sample_cfads_keur": getattr(representative_dscr_period, "cf_after_tax_keur", None),
            "audit_source": "WaterfallResult.periods[].cf_after_tax_keur (supporting fields shown: ebitda_keur, tax_keur)",
        },
    })
    return evidence


def _sanitize_df(df):
    """Replace inf/nan floats in a DataFrame with None for JSON safety.

    Uses astype(object).replace() rather than map() because pandas map()
    silently drops inf values without actually replacing them when the
    dtype is float64.
    """
    return df.astype(object).replace({float('inf'): None, float('-inf'): None, float('nan'): None})


def run_project(project_type: str, scenario: str, period_view: str = "Semiannual",
               project_inputs_override=None, use_dualrun_validation: bool = False):
    """Phase B4 production run — ONE clean financial engine, no legacy switch.

    resolve typed inputs → classify clean production authority → one clean
    G2C calculation → read-only presentation serialization. Blocked or
    unregistered inputs fail closed with a typed error and
    calculation_count == 0 — there is no legacy financial execution seam in
    production; unsupported compatibility paths fail closed.
    """
    return _run_project_impl(
        project_type, scenario, period_view, project_inputs_override,
        use_dualrun_validation,
    )


def _run_project_impl(project_type: str, scenario: str, period_view: str = "Semiannual",
                      project_inputs_override=None, use_dualrun_validation: bool = False):
    # ── Phase B4: single production financial authority, clean-only ──────────
    #   CLEAN_PRODUCTION_READY → ONE clean G2C calculation + read-only adapter
    #                            (no legacy waterfall, no legacy sponsor engine);
    #   blocked / unclassified  → typed fail-closed error, zero calculations.
    # Never a silent fallback; never both engines in one run; NO legacy
    # execution seam exists anywhere in the production app surface.
    clean_run = None
    authority_decision = None
    _pr8_inputs = None
    if project_type != "Portfolio":
        # PR-8 correction pass: NO exception-driven fallback. Resolution and
        # classification plumbing failures raise the typed
        # ProductionAuthorityResolutionError and execute ZERO engines (clean
        # or legacy). Validation ERRORS on user overrides are input problems,
        # not routing problems: they surface as UNCLASSIFIED fail-closed
        # errors below (no engine executes on that path).
        from app.services.production_financial_authority import (
            ProductionAuthorityResolutionError,
        )
        from app.services.production_waterfall_seam import classify_or_fail

        if project_inputs_override is not None:
            from domain.validation import validate_project_inputs
            issues = list(validate_project_inputs(project_inputs_override))
            if not [i for i in issues if i.severity == "error"]:
                _pr8_inputs = project_inputs_override
        elif project_type in (
            "Generic Wind Reference", "Generic Solar Reference",
            "Generic Data Center Reference", "Test 1", "Test 2", "Solar", "Wind",
        ):
            from app import project_factories as _pf
            try:
                _pr8_inputs = {
                    "Generic Wind Reference": _pf.create_generic_wind_reference,
                    "Generic Solar Reference": _pf.create_generic_solar_reference,
                    "Generic Data Center Reference": _pf.create_generic_data_center_reference,
                    "Test 1": _pf.create_default_solar_project,
                    "Test 2": _pf.create_default_wind_project,
                    "Solar": _pf.create_default_solar_project,
                    "Wind": _pf.create_default_wind_project,
                }[project_type]()
            except ProductionAuthorityResolutionError:
                raise
            except Exception as exc:
                raise ProductionAuthorityResolutionError(
                    reason_code="PR8_FACTORY_RESOLUTION_FAILURE",
                    detail=(
                        f"factory resolution for project_type={project_type!r} "
                        f"raised {type(exc).__name__}: {exc}. Production "
                        "routing fails closed — no engine executes."
                    ),
                ) from exc

        if _pr8_inputs is not None:
            authority_decision = classify_or_fail(_pr8_inputs)

        if (
            authority_decision is not None
            and authority_decision.promoted
            and use_dualrun_validation
        ):
            # The dual-run flag is an unsupported diagnostic; it may
            # never pull a clean-ready production project back to legacy.
            raise ProductionAuthorityResolutionError(
                reason_code="PR8_DUALRUN_DIAGNOSTIC_UNAVAILABLE_ON_CLEAN_ROUTE",
                detail=(
                    "use_dualrun_validation is not available on the clean "
                    "production route; this diagnostic contract is not "
                    "registered for production execution."
                ),
            )

    if (
        clean_run is None
        and authority_decision is not None
        and authority_decision.promoted
    ):
        # Deliberately OUTSIDE the try/except above: a clean production
        # failure is a fail-closed error (CleanProductionRunUnavailable) and
        # must surface — never a silent legacy fallback.
        from app.services.production_financial_authority import run_clean_production

        clean_run = run_clean_production(_pr8_inputs, scenario, project_type=project_type)

    if clean_run is not None:
        from app.demo_result import DemoResult
        from app.services.clean_presentation_adapter import (
            build_clean_waterfall_view,
        )
        demo = DemoResult(
            project_type=project_type,
            result=build_clean_waterfall_view(clean_run),
            project_inputs=clean_run.project_inputs,
            messages=[],
            integration_status="full",
            integration_note="Clean production financial authority (PR-8): "
                             "single G2C calculation, read-only presentation adapter.",
        )
    elif (
        authority_decision is not None
        and not authority_decision.promoted
    ):
        # Phase B4: fail-closed — no legacy production fallthrough.
        # A classified-but-not-promoted project raises a typed error.
        # Production callers receive CLEAN_NOT_READY; calculation_count == 0.
        # There is no production legacy engine to fall back to.
        from app.services.production_financial_authority import CleanNotReadyError

        raise CleanNotReadyError(
            classification=authority_decision.classification.value,
            reason_code=authority_decision.reason_code,
            detail=(
                f"{authority_decision.detail}  "
                "(Phase B4: the production financial authority is clean-only; "
                "this contract is not registered for production execution. "
                "No alternate runtime is permitted.)"
            ),
            runtime_authority="clean_not_ready",
            calculation_count=0,
        )
    else:
        # Unclassified type (Portfolio / unknown project_type / override with
        # validation errors) on the production path — Phase B4 fail-closed.
        from app.services.production_financial_authority import CleanNotReadyError

        raise CleanNotReadyError(
            classification="UNCLASSIFIED",
            reason_code="PR8_PROJECT_TYPE_NOT_CLASSIFIED",
            detail=(
                f"project_type={project_type!r} was not resolved to a typed "
                "ProjectInputs and could not be classified. Phase B4: the "
                "production financial authority is clean-only; this project "
                "type is not registered for production execution."
            ),
            runtime_authority="clean_not_ready",
            calculation_count=0,
        )
    result = demo.result

    # Build tables
    wf = build_waterfall_table(result)
    rev = build_revenue_table(result)
    debt = build_debt_table(result)
    returns = build_returns_table(result)

    if period_view == "Annual":
        wf = aggregate_period_table_annual(wf)
        rev = aggregate_period_table_annual(rev)
        debt = aggregate_period_table_annual(debt)

    # Sanitize inf/nan (e.g. DSCR col has inf when debt is fully repaid)
    wf = _sanitize_df(wf)
    rev = _sanitize_df(rev)
    debt = _sanitize_df(debt)
    returns = _sanitize_df(returns)

    # Phase D1: assemble financial statements from the already-computed waterfall result.
    # assemble_financial_statements() is an offline assembly step — no new financial
    # calculations are performed here; it reads from WaterfallResult.periods fields that
    # run_waterfall() already computed. waterfall_core.py does NOT import this module
    # (separation of concerns verified by test_excel_parity_characterization.py C8).
    # C3 handoff: build_clean_waterfall_view() passes financial_statements_result
    # through from CleanProductionRun onto CleanWaterfallView (result). Serialize it
    # using the existing _serialize_financial_statements() — no new calculations.
    financial_statements_payload = None
    try:
        _fs_result = getattr(result, "financial_statements_result", None)
        if _fs_result is not None:
            financial_statements_payload = _serialize_financial_statements(_fs_result)
    except Exception:
        # FS serialization failure must never break the run path.
        financial_statements_payload = None

    # Phase E2: assemble senior debt schedule from the already-computed waterfall result.
    # _serialize_debt_schedule() reads per-period fields already computed by the waterfall
    # engine. No new financial calculations are performed here.
    debt_schedule_payload = None
    try:
        debt_schedule_payload = _serialize_debt_schedule(result)
    except Exception:
        # Debt schedule serialization failure must never break the run path.
        debt_schedule_payload = None

    # Phase F2: assemble tax schedule from the already-computed waterfall result.
    # _serialize_tax_schedule() reads per-period fields already computed by the waterfall
    # engine. No new financial calculations are performed here.
    tax_schedule_payload = None
    try:
        tax_schedule_payload = _serialize_tax_schedule(result)
    except Exception:
        # Tax schedule serialization failure must never break the run path.
        tax_schedule_payload = None

    # Phase G1: assemble distribution schedule from the already-computed waterfall result.
    # _serialize_distribution_schedule() reads per-period fields already computed by the
    # waterfall engine. No new financial calculations are performed here.
    distribution_schedule_payload = None
    try:
        distribution_schedule_payload = _serialize_distribution_schedule(result)
    except Exception:
        # Distribution schedule serialization failure must never break the run path.
        distribution_schedule_payload = None

    # Phase H2: call the Sponsor engine AFTER the waterfall completes.
    # project_runner.py calls the Sponsor engine's public interface — standard dependency
    # direction (runner calls engine). Neither engine is modified. No circular imports.
    # _serialize_sponsor_schedule() reads from SponsorCashflowResult / SponsorIrrResult /
    # SponsorMoicResult — no new sponsor economics are computed here.
    # PR-8 promoted (clean) runs: the legacy sponsor engine (hardcoded capital
    # structures) is NOT invoked — the G2C sponsor result is serialized
    # read-only instead.
    # Phase B4: sponsor schedule is serialized read-only from the clean G2C
    # result (the legacy sponsor engine with hardcoded capital structures no
    # longer exists in production).
    from app.services.clean_presentation_adapter import (
        build_clean_sponsor_schedule,
    )
    sponsor_schedule_payload = build_clean_sponsor_schedule(clean_run)

    payload = {
        "project_type": project_type,
        "scenario": scenario,
        "period_view": period_view,
        "integration_status": getattr(demo, 'integration_status', 'full'),
        "integration_note": getattr(demo, 'integration_note', None),
        "messages": getattr(demo, 'messages', []),
        "debt_schedule": debt_schedule_payload,
        "tax_schedule": tax_schedule_payload,
        "distribution_schedule": distribution_schedule_payload,
        "kpis": {
            # CapEx and debt
            "total_capex_keur": getattr(getattr(demo, "project_inputs", None), "capex", None).total_capex if getattr(getattr(demo, "project_inputs", None), "capex", None) is not None else None,
            # Revenue / EBITDA / OpEx
            "total_revenue_keur": result.total_revenue_keur,
            "total_ebitda_keur": result.total_ebitda_keur,
            "total_opex_keur": getattr(result, 'total_opex_keur', None),
            # Distributions
            "total_distributions_keur": getattr(result, 'total_distribution_keur', None),
            # Returns
            "project_irr": result.project_irr,
            "equity_irr": result.equity_irr,
            "sponsor_irr": getattr(result, 'sponsor_irr', None),
            "project_npv_keur": getattr(result, 'project_npv', None),
            "equity_npv_keur": getattr(result, 'equity_npv', None),
            # Debt service
            "total_senior_ds_keur": getattr(result, 'total_senior_ds_keur', None),
            "total_shl_service_keur": getattr(result, 'total_shl_service_keur', None),
            # Tax
            "total_tax_keur": getattr(result, 'total_tax_keur', None),
            # DSCR / LLCR
            "target_dscr": getattr(result, 'target_dscr', None),
            "min_dscr": result.actual_min_dscr,
            "avg_dscr": result.actual_avg_dscr,
            "min_llcr": getattr(result, 'min_llcr', None),
            # Lockup
            "periods_in_lockup": getattr(result, 'periods_in_lockup', None),
        },
        "dualrun_validation": getattr(result, '_dualrun_validation', None),
        "derivation_evidence": _build_runtime_derivation_evidence(result, demo.project_inputs),
        "financial_statements": financial_statements_payload,
        "sponsor_schedule": sponsor_schedule_payload,
        "tables": {
            "waterfall": wf.to_dict(orient="records"),
            "revenue": rev.to_dict(orient="records"),
            "debt": debt.to_dict(orient="records"),
            "returns": returns.to_dict(orient="records"),
        }
    }
    # Gearing fields from the same clean_run — no second engine calculation.
    try:
        _fr = clean_run.g2c_result.financing_result
        _capex_total = getattr(getattr(demo, "project_inputs", None), "capex", None)
        _capex_total = _capex_total.total_capex if _capex_total is not None else None
        if _capex_total and _capex_total > 0:
            payload["kpis"]["actual_gearing_pct"] = (
                _fr.final_senior_commitment_keur / _capex_total
            )
        payload["kpis"]["gearing_cap_pct"] = getattr(_fr, "gearing_ratio", None)
        payload["kpis"]["senior_debt_keur"] = getattr(_fr, "final_senior_commitment_keur", None)
    except Exception:
        pass

    # Phase B4: machine-readable clean production-authority lineage.
    payload["runtime_authority"] = (
        getattr(demo.result, "_authority_metadata", None)
        or clean_run.authority_metadata
    )
    return payload


def _serialize_financial_statements(fs) -> dict:
    """Serialize FinancialStatementsResult to a JSON-safe dict for sessionStorage.

    Phase D1: read-only serialization of already-assembled engine output.
    No financial calculations are performed here.

    Structure returned:
      {
        "pnl": {"periods": [...], "row_labels": {...}},
        "balance_sheet": {"periods": [...]},
        "pf_cash_waterfall": {"periods": [...]},
      }
    """
    def _fmt_date(d):
        return d.isoformat() if d else None

    def _f(v):
        """Round to 2dp for display; handle non-finite values."""
        try:
            f = float(v)
            if f != f or abs(f) == float("inf"):
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    # P&L periods — FinancialStatementsResult uses income_statement_periods;
    # retained_earnings_keur comes from the parallel retained_earnings_periods.
    re_by_idx = {
        rp.period_index: rp
        for rp in (fs.retained_earnings_periods or ())
    }
    pnl_periods = []
    for p in fs.income_statement_periods:
        rp = re_by_idx.get(p.period_index)
        pnl_periods.append({
            "period": p.period_index,
            "date": _fmt_date(p.period_end),
            "revenues_keur": _f(p.revenue_keur),
            "operating_expenses_keur": _f(p.opex_keur),
            "depreciation_keur": _f(p.book_depreciation_keur),
            "ebit_keur": _f(p.ebit_keur),
            "senior_interest_expense_keur": _f(p.senior_interest_expense_keur),
            "shl_interest_expense_keur": _f(p.shl_interest_expense_keur),
            "earnings_before_tax_keur": _f(p.earnings_before_tax_keur),
            "cit_accrual_keur": _f(p.cit_accrual_keur),
            "net_income_keur": _f(p.net_income_keur),
            "retained_earnings_keur": _f(rp.closing_retained_earnings_keur if rp else None),
            "net_dividends_keur": _f(rp.legal_equity_distribution_keur if rp else None),
        })

    # Balance sheet periods — FinancialStatementsResult.balance_sheet_periods
    # BS fields: unrestricted_cash_keur (cash), senior_debt_balance_keur (senior),
    # accumulated_book_depreciation_keur (not directly needed for row defs).
    # net_fixed_assets_keur is not a direct field — derive from gross - accum_depr if available.
    fa_by_idx = {
        fp.period_index: fp
        for fp in (getattr(fs, "fixed_asset_periods", None) or ())
    }
    bs_periods = []
    for p in fs.balance_sheet_periods:
        fa = fa_by_idx.get(p.period_index)
        net_fixed = _f(fa.net_fixed_assets_keur if fa else None)
        bs_periods.append({
            "period_index": p.period_index,
            "date": _fmt_date(p.period_end),
            "net_fixed_assets_keur": net_fixed,
            "dsra_balance_keur": _f(p.dsra_balance_keur),
            "cash_keur": _f(p.unrestricted_cash_keur),
            "total_assets_keur": None,  # not directly on BalanceSheetPeriod
            "share_capital_keur": _f(p.share_capital_keur),
            "retained_earnings_keur": _f(p.retained_earnings_keur),
            "shl_balance_keur": _f(p.shl_balance_keur),
            "senior_balance_keur": _f(p.senior_debt_balance_keur),
            "total_liabilities_equity_keur": None,
            "balance_check_keur": _f(p.balance_check_keur),
        })

    # PF Cash Waterfall periods — FinancialStatementsResult.pf_cash_waterfall_periods
    pf_periods = []
    for p in fs.pf_cash_waterfall_periods:
        # senior_total_ds = cash interest + principal
        senior_ds = _f(
            (p.senior_cash_interest_keur or 0) + (p.senior_principal_keur or 0)
        )
        # dsra_funding = top-up minus draw
        dsra_fund = _f(
            (p.dsra_top_up_keur or 0) - (p.dsra_draw_keur or 0)
        )
        # fcf_junior = post_senior_cash after DSRA movements
        fcf_jr = _f(
            (p.post_senior_cash_keur or 0)
            - (p.dsra_top_up_keur or 0)
            + (p.dsra_draw_keur or 0)
            + (p.dsra_release_keur or 0)
        )
        # fcf_for_distribution = distribution_account inflow (before SHL/equity)
        fcf_dist = _f(p.distribution_account_inflow_keur)
        # net_dividends = legal equity distributions
        net_div = _f(p.legal_equity_distribution_keur)
        pf_periods.append({
            "period_index": p.period_index,
            "date": _fmt_date(p.cashflow_date),
            "revenue_cash_keur": _f(p.revenue_cash_keur),
            "opex_cash_keur": _f(p.opex_cash_keur),
            "ebitda_cash_keur": _f(p.ebitda_keur),
            "cash_tax_keur": _f(p.cash_tax_keur),
            "fcf_banks_keur": _f(p.fcf_banks_keur),
            "senior_total_ds_keur": senior_ds,
            "dsra_funding_keur": dsra_fund,
            "dsra_release_keur": _f(p.dsra_release_keur),
            "fcf_junior_keur": fcf_jr,
            "fcf_for_distribution_keur": fcf_dist,
            "net_dividends_keur": net_div,
        })

    return {
        "pnl": {"periods": pnl_periods},
        "balance_sheet": {"periods": bs_periods},
        "pf_cash_waterfall": {"periods": pf_periods},
        "source": "assemble_financial_statements(WaterfallResult)",
    }


def _serialize_debt_schedule(result) -> dict:
    """Serialize the senior debt schedule from WaterfallResult to a JSON-safe dict.

    Phase E2/E5: read-only serialization of already-computed engine output.
    No financial calculations are performed here — only reads fields already
    set by the waterfall engine on each WaterfallPeriod.

    Structure returned:
      {
        "periods": [
          {
            "period": int,
            "date": str (ISO),
            "year_index": int,
            "period_in_year": int,
            "is_operation": bool,
            "senior_balance_keur": float | None,
            "senior_principal_keur": float | None,
            "senior_interest_keur": float | None,
            "senior_ds_keur": float | None,
            "dscr": float | None,
            "dsra_balance_keur": float | None,
            "dsra_contribution_keur": float | None,
          },
          ...
        ],
        "summary": {
          "total_senior_ds_keur": float | None,
          "actual_min_dscr": float | None,
          "actual_avg_dscr": float | None,
          "target_dscr": float | None,
        },
        "source": "WaterfallResult.periods (per-period engine output)",
      }
    """
    def _fmt_date(d):
        return d.isoformat() if d else None

    def _f(v):
        """Round to 2dp for display; handle non-finite values."""
        try:
            f = float(v)
            if f != f or abs(f) == float("inf"):
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    periods_out = []
    for p in getattr(result, "periods", []):
        periods_out.append({
            "period": getattr(p, "period", None),
            "date": _fmt_date(getattr(p, "date", None)),
            "year_index": getattr(p, "year_index", None),
            "period_in_year": getattr(p, "period_in_year", None),
            "is_operation": bool(getattr(p, "is_operation", False)),
            "senior_balance_keur": _f(getattr(p, "senior_balance_keur", None)),
            "senior_principal_keur": _f(getattr(p, "senior_principal_keur", None)),
            "senior_interest_keur": _f(getattr(p, "senior_interest_keur", None)),
            "senior_ds_keur": _f(getattr(p, "senior_ds_keur", None)),
            "dscr": _f(getattr(p, "dscr", None)),
            "dsra_balance_keur": _f(getattr(p, "dsra_balance_keur", None)),
            "dsra_contribution_keur": _f(getattr(p, "dsra_contribution_keur", None)),
        })

    return {
        "periods": periods_out,
        "summary": {
            "total_senior_ds_keur": _f(getattr(result, "total_senior_ds_keur", None)),
            "actual_min_dscr": _f(getattr(result, "actual_min_dscr", None)),
            "actual_avg_dscr": _f(getattr(result, "actual_avg_dscr", None)),
            "target_dscr": _f(getattr(result, "target_dscr", None)),
            "min_llcr": _f(getattr(result, "min_llcr", None)),
            "periods_in_lockup": getattr(result, "periods_in_lockup", None),
        },
        "source": "WaterfallResult.periods (per-period engine output)",
    }


def _serialize_tax_schedule(result) -> dict:
    """Serialize the tax schedule from WaterfallResult to a JSON-safe dict.

    Phase F2: read-only serialization of already-computed engine output.
    No financial calculations are performed here — only reads fields already
    set by the waterfall engine on each WaterfallPeriod.

    Structure returned:
      {
        "periods": [
          {
            "period": int,
            "date": str (ISO),
            "year_index": int,
            "period_in_year": int,
            "is_operation": bool,
            "taxable_profit_keur": float | None,
            "tax_keur": float | None,
            "cf_after_tax_keur": float | None,
            "corporate_tax_cash_keur": float | None,
            "tax_depreciation_audit_keur": float | None,
            "taxable_income_before_losses_audit_keur": float | None,
            "tax_loss_opening_audit_keur": float | None,
            "tax_loss_used_audit_keur": float | None,
            "tax_loss_closing_audit_keur": float | None,
            "taxable_profit_after_losses_audit_keur": float | None,
            "cit_accrual_audit_keur": float | None,
            "cash_tax_current_period_audit_keur": float | None,
          },
          ...
        ],
        "summary": {
          "total_tax_keur": float | None,
        },
        "source": "WaterfallResult.periods (per-period engine output)",
      }
    """
    def _fmt_date(d):
        return d.isoformat() if d else None

    def _f(v):
        """Round to 2dp for display; handle non-finite values."""
        try:
            f = float(v)
            if f != f or abs(f) == float("inf"):
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    periods_out = []
    for p in getattr(result, "periods", []):
        periods_out.append({
            "period": getattr(p, "period", None),
            "date": _fmt_date(getattr(p, "date", None)),
            "year_index": getattr(p, "year_index", None),
            "period_in_year": getattr(p, "period_in_year", None),
            "is_operation": bool(getattr(p, "is_operation", False)),
            "taxable_profit_keur": _f(getattr(p, "taxable_profit_keur", None)),
            "tax_keur": _f(getattr(p, "tax_keur", None)),
            "cf_after_tax_keur": _f(getattr(p, "cf_after_tax_keur", None)),
            "corporate_tax_cash_keur": _f(getattr(p, "corporate_tax_cash_keur", None)),
            "tax_depreciation_audit_keur": _f(getattr(p, "tax_depreciation_audit_keur", None)),
            "taxable_income_before_losses_audit_keur": _f(getattr(p, "taxable_income_before_losses_audit_keur", None)),
            "tax_loss_opening_audit_keur": _f(getattr(p, "tax_loss_opening_audit_keur", None)),
            "tax_loss_used_audit_keur": _f(getattr(p, "tax_loss_used_audit_keur", None)),
            "tax_loss_closing_audit_keur": _f(getattr(p, "tax_loss_closing_audit_keur", None)),
            "taxable_profit_after_losses_audit_keur": _f(getattr(p, "taxable_profit_after_losses_audit_keur", None)),
            "cit_accrual_audit_keur": _f(getattr(p, "cit_accrual_audit_keur", None)),
            "cash_tax_current_period_audit_keur": _f(getattr(p, "cash_tax_current_period_audit_keur", None)),
        })

    return {
        "periods": periods_out,
        "summary": {
            "total_tax_keur": _f(getattr(result, "total_tax_keur", None)),
        },
        "source": "WaterfallResult.periods (per-period engine output)",
    }


def _serialize_distribution_schedule(result) -> dict:
    """Serialize the distribution schedule from WaterfallResult to a JSON-safe dict.

    Phase G1: read-only serialization of already-computed engine output.
    No financial calculations are performed here — only reads fields already
    set by the waterfall engine on each WaterfallPeriod.

    Structure returned:
      {
        "periods": [...],
        "summary": {...},
        "source": "WaterfallResult.periods (per-period engine output)",
      }
    """
    def _fmt_date(d):
        return d.isoformat() if d else None

    def _f(v):
        """Round to 2dp for display; handle non-finite values."""
        try:
            f = float(v)
            if f != f or abs(f) == float("inf"):
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    periods_out = []
    for p in getattr(result, "periods", []):
        periods_out.append({
            "period": getattr(p, "period", None),
            "date": _fmt_date(getattr(p, "date", None)),
            "year_index": getattr(p, "year_index", None),
            "period_in_year": getattr(p, "period_in_year", None),
            "is_operation": bool(getattr(p, "is_operation", False)),
            "distribution_keur": _f(getattr(p, "distribution_keur", None)),
            "cash_sweep_keur": _f(getattr(p, "cash_sweep_keur", None)),
            "cum_distribution_keur": _f(getattr(p, "cum_distribution_keur", None)),
            "lockup_active": bool(getattr(p, "lockup_active", False)),
            "cf_after_reserves_keur": _f(getattr(p, "cf_after_reserves_keur", None)),
            "dsra_balance_keur": _f(getattr(p, "dsra_balance_keur", None)),
            "dsra_contribution_keur": _f(getattr(p, "dsra_contribution_keur", None)),
            "mra_balance_keur": _f(getattr(p, "mra_balance_keur", None)),
            "mra_contribution_keur": _f(getattr(p, "mra_contribution_keur", None)),
            "legacy_distribution_keur": _f(getattr(p, "legacy_distribution_keur", None)),
            "da_paid_distribution_keur": _f(getattr(p, "da_paid_distribution_keur", None)),
            "distribution_source": getattr(p, "distribution_source", "") or "",
            "distribution_wiring_delta_keur": _f(getattr(p, "distribution_wiring_delta_keur", None)),
        })

    total_dist = getattr(result, "total_distribution_keur", None)
    raw_source = getattr(result, "distribution_source", "") or ""
    # Normalise empty distribution_source to a meaningful label
    distribution_source_label = raw_source if raw_source else (
        "waterfall" if (total_dist and total_dist > 0) else "none"
    )
    return {
        "periods": periods_out,
        "summary": {
            "total_distribution_keur": _f(total_dist),
            "legacy_distribution_keur": _f(getattr(result, "legacy_distribution_keur", None)),
            "da_paid_distribution_keur": _f(getattr(result, "da_paid_distribution_keur", None)),
            "distribution_source": distribution_source_label,
            "distribution_wiring_delta_keur": _f(getattr(result, "distribution_wiring_delta_keur", None)),
        },
        "source": "WaterfallResult.periods (per-period engine output)",
    }


def _serialize_sponsor_schedule(cashflow_result, irr_result, moic_result) -> dict:
    """Serialize sponsor engine results to a JSON-safe dict for sessionStorage.

    Phase H2: read-only serialization of already-computed engine output.
    No sponsor economic calculations are performed here — only reads fields
    from SponsorCashflowResult, SponsorIrrResult, SponsorMoicResult.

    Structure returned:
      {
        "periods": [
          {
            "period_index": int,
            "equity_injected_keur": float | None,
            "distribution_received_keur": float | None,
            "wht_on_distribution_keur": float | None,
            "net_cashflow_keur": float | None,
            "capital_account_balance_keur": float | None,
          },
          ...
        ],
        "summary": {
          "total_equity_injected_keur": float | None,
          "total_distributions_received_keur": float | None,
          "total_wht_keur": float | None,
          "total_net_cashflow_keur": float | None,
          "gross_sponsor_return_multiple": float | None,
          "gross_sponsor_irr": float | None,
          "gross_sponsor_moic": float | None,
          "xirr_converged": bool,
          "investor_id": str,
          "entity_code": str,
        },
        "source": "SponsorCashflowRunner + SponsorIrrRunner + SponsorMoicRunner",
      }
    """
    def _f(v):
        """Round to 2dp for display; handle non-finite values."""
        try:
            f = float(v)
            if f != f or abs(f) == float("inf"):
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    periods_out = []
    for p in getattr(cashflow_result, "period_results", []):
        periods_out.append({
            "period_index": getattr(p, "period_index", None),
            "equity_injected_keur": _f(getattr(p, "equity_injected_keur", None)),
            "distribution_received_keur": _f(getattr(p, "distribution_received_keur", None)),
            "wht_on_distribution_keur": _f(getattr(p, "wht_on_distribution_keur", None)),
            "net_cashflow_keur": _f(getattr(p, "net_cashflow_keur", None)),
            "capital_account_balance_keur": _f(getattr(p, "capital_account_balance_keur", None)),
        })

    # IRR from SponsorIrrResult
    gross_irr = getattr(irr_result, "gross_sponsor_irr", None)
    xirr_converged = bool(getattr(irr_result, "xirr_converged", False))

    # MOIC from SponsorMoicResult
    gross_moic = getattr(moic_result, "gross_sponsor_moic", None)

    return {
        "periods": periods_out,
        "summary": {
            "total_equity_injected_keur": _f(getattr(cashflow_result, "total_equity_injected_keur", None)),
            "total_distributions_received_keur": _f(getattr(cashflow_result, "total_distributions_received_keur", None)),
            "total_wht_keur": _f(getattr(cashflow_result, "total_wht_keur", None)),
            "total_net_cashflow_keur": _f(getattr(cashflow_result, "total_net_cashflow_keur", None)),
            "gross_sponsor_return_multiple": _f(getattr(cashflow_result, "gross_sponsor_return_multiple", None)),
            "gross_sponsor_irr": _f(gross_irr),
            "gross_sponsor_moic": _f(gross_moic),
            "xirr_converged": xirr_converged,
            "investor_id": getattr(cashflow_result, "investor_id", ""),
            "entity_code": getattr(cashflow_result, "entity_code", ""),
        },
        "source": "SponsorCashflowRunner + SponsorIrrRunner + SponsorMoicRunner",
    }

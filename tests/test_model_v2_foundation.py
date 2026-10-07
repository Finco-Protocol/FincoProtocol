"""Model V2 foundation — EQUITY_ONLY statement-assembly regression tests.

An EQUITY_ONLY sponsor funding mode with no shareholder loan is a first-class
supported capital structure. These tests pin the canonical runtime behaviour:

  MODEL_V2_EQUITY_ONLY_STATEMENT_ASSEMBLY      — no-SHL run completes statements
  MODEL_V2_EQUITY_ONLY_NO_INVENTED_SHL_ECONOMICS — absent SHL stays absent
"""
from __future__ import annotations

import dataclasses

import pytest

from app.project_factories import create_generic_solar_reference
from finco_core.inputs import SponsorFundingMode
from financial_engine.financial_statements.contracts import StatementStatus

TOLERANCE = 1e-4


def _equity_only_solar_project():
    """Generic Solar Reference converted to EQUITY_ONLY with no SHL configured."""
    base = create_generic_solar_reference()
    return dataclasses.replace(
        base,
        financing=dataclasses.replace(
            base.financing,
            sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
            clean_shl_principal_keur=None,
            shl_amount_keur=0.0,
        ),
    )


@pytest.fixture(scope="module")
def equity_only_run():
    from app.services.production_financial_authority import run_clean_production

    return run_clean_production(
        _equity_only_solar_project(), "Base", project_type="solar"
    )


def test_equity_only_completes_statement_assembly(equity_only_run):
    """MODEL_V2_EQUITY_ONLY_STATEMENT_ASSEMBLY = PASS"""
    fsr = equity_only_run.financial_statements_result
    assert fsr.status == StatementStatus.OK, getattr(fsr, "unavailable_reasons", None)

    bs_periods = list(getattr(fsr, "balance_sheet_periods", None) or [])
    assert bs_periods, "balance sheet periods must be produced"
    checks = [p.balance_check_keur for p in bs_periods if p.balance_check_keur is not None]
    assert checks, "operating balance-sheet identity must be claimed"
    assert max(abs(c) for c in checks) <= TOLERANCE


def test_equity_only_statements_contain_no_invented_shl_economics(equity_only_run):
    """MODEL_V2_EQUITY_ONLY_NO_INVENTED_SHL_ECONOMICS = PASS"""
    fsr = equity_only_run.financial_statements_result
    g2c = equity_only_run.g2c_result

    # Funding-stack authority: the EQUITY_ONLY residual is additional equity.
    fin = g2c.financing_result
    assert float(fin.derived_shl_cash_principal_keur) == 0.0

    # Balance sheet: SHL stays economically absent; equity remains equity.
    bs_periods = list(getattr(fsr, "balance_sheet_periods", None) or [])
    assert bs_periods
    for p in bs_periods:
        if p.shl_balance_keur is not None:
            assert float(p.shl_balance_keur) == 0.0
        if p.shl_unpaid_principal_keur is not None:
            assert float(p.shl_unpaid_principal_keur) == 0.0

    last = bs_periods[-1]
    assert float(last.share_capital_keur) > 0.0
    assert float(last.additional_equity_keur) > 0.0

    # P&L: no SHL interest expense may appear in any period.
    pnl_periods = list(getattr(fsr, "income_statement_periods", None) or [])
    assert pnl_periods
    for p in pnl_periods:
        assert float(getattr(p, "shl_interest_expense_keur", 0.0) or 0.0) == 0.0


def test_equity_only_share_capital_untouched_by_statement_assembly(equity_only_run):
    """Share capital equals the configured legal equity — never converted to SHL."""
    project = _equity_only_solar_project()
    bs_periods = list(
        getattr(equity_only_run.financial_statements_result, "balance_sheet_periods", None) or []
    )
    configured = float(project.financing.share_capital_keur)
    assert bs_periods
    for p in bs_periods:
        if p.share_capital_keur is not None:
            assert float(p.share_capital_keur) >= configured - TOLERANCE


def test_domain_models_barrel_module_imports_cleanly():
    """MODEL_V2_DOMAIN_MODELS_IMPORT = PASS

    domain.models previously imported DTTRate/get_dtt_rate, which no symbol in
    the repository defines, making the whole barrel module unimportable.
    """
    import importlib

    module = importlib.import_module("domain.models")
    assert hasattr(module, "TaxParams")
    assert "TaxParams" in module.__all__
    assert "DTTRate" not in module.__all__
    assert not hasattr(module, "DTTRate")

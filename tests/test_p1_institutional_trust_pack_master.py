"""P1 master Trust Pack consolidation guards.

The heavy runtime/reconciliation proof already lives in P1.2/P1.3. This file
protects the canonical worked-case identity, authority reuse and truthful
presentation boundaries, and adds one deterministic Solar DSRA reconciliation
that was not already explicit in the institutional pack.
"""
from __future__ import annotations

import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METHODOLOGY_DOC = ROOT / "docs" / "trust" / "FINCO_MODEL_METHODOLOGY.md"
WORKED_SOLAR_DOC = ROOT / "docs" / "trust" / "FINCO_WORKED_SOLAR_RECONCILIATION.md"
REVIEW_DOSSIER = ROOT / "docs" / "review" / "P1_INSTITUTIONAL_TRUST_PACK.md"


def test_p1_master_canonical_solar_identity_is_existing_protected_reference():
    """Master worked case reuses generic_solar_reference; no new economics model."""
    from app.project_factories import create_generic_solar_reference
    from domain.inputs import PeriodFrequency

    pi = create_generic_solar_reference()

    assert pi.info.name == "Generic Solar Reference"
    assert pi.info.code == "REF-SOLAR-A"
    assert pi.info.company == "Synthetic Sponsor A"
    assert pi.info.country_iso == "XA"
    assert float(pi.technical.capacity_mw) == 64.0
    assert int(pi.info.construction_months) == 14
    assert int(pi.info.horizon_years) == 25
    assert pi.info.period_frequency is PeriodFrequency.SEMESTRIAL


def test_p1_master_methodology_reuses_machine_registry_authorities():
    """Narrative points to the existing registry; it does not redefine metrics."""
    from app.model_methodology_registry import METRIC_REGISTRY

    by_key = {entry.key: entry for entry in METRIC_REGISTRY}
    expected = {
        "cash_tax": ("financial_engine/tax/engine.py", "calculate_tax"),
        "cfads": ("financial_engine/cfads.py", "calculate_canonical_cfads"),
        "dscr": ("financial_engine/senior_debt/sculpting.py", "build_schedule"),
        "project_irr": ("financial_engine/project_returns/model.py", "_project_return"),
        "equity_irr": (
            "financial_engine/sponsor_returns/model.py",
            "compute_gated_sponsor_return_metrics",
        ),
        "total_sponsor_xirr": (
            "financial_engine/sponsor_returns/model.py",
            "compute_gated_sponsor_return_metrics",
        ),
        "initial_senior_debt": (
            "financial_engine/financing/project.py",
            "run_project_financing_model",
        ),
    }

    for key, (source_file, source_function) in expected.items():
        assert key in by_key, f"missing methodology authority: {key}"
        assert by_key[key].source_file == source_file
        assert by_key[key].source_function == source_function


def test_p1_master_trust_pack_already_exposes_methodology_and_evidence_lanes():
    """Existing Trust Pack remains discovery surface; no parallel docs app needed."""
    from app.ui import trust_pack

    assert trust_pack._METHODOLOGY_PAGE_URL == "/model/methodology"
    for key in (
        "cfads",
        "dscr",
        "project_irr",
        "equity_irr",
        "total_sponsor_xirr",
        "total_capex",
        "initial_senior_debt",
        "xirr_year_fraction",
    ):
        assert key in trust_pack._METHODOLOGY_KEYS

    source = (ROOT / "app" / "ui" / "trust_pack.py").read_text(encoding="utf-8")
    for authority_label in (
        "Reference Regression Check",
        "Run Integrity",
        "Signed Run Certificate",
        "FINCO VERIFY",
        "Institutional export",
    ):
        assert authority_label in source


def test_p1_master_reuses_existing_runtime_reconciliation_suites():
    """Master pack must reference existing P1.2/P1.3 proof, not duplicate it."""
    p12 = (ROOT / "tests" / "test_p1_2_xlsx_export_reconciliation.py").read_text(
        encoding="utf-8"
    )
    p13 = (ROOT / "tests" / "test_p1_3_institutional_validation.py").read_text(
        encoding="utf-8"
    )

    for marker in (
        "XLSX_SOURCES_USES_RECONCILE",
        "XLSX_SOURCES_USES_NOT_RESIDUAL_BALANCED",
        "XLSX_RETURNS_SERIALIZED_VALUES_MATCH_RUNTIME",
        "XLSX_LAST_RUN_COMPOSITE_IDENTITY_EXACT",
        "XLSX_ENGINE_VERSION_RUN_BOUND",
    ):
        assert marker in p12

    for marker in (
        "P1_3_BALANCE_SHEET_IDENTITY_SOLAR",
        "P1_3_DEBT_ROLLFORWARD_SOLAR",
        "P1_3_CASH_WATERFALL_IDENTITY",
        "P1_3_SAME_CANONICAL_RUN_RECONCILIATION",
        "P1_3_HISTORICAL_ENGINE_VERSION_PRESERVED",
        "P1_3_CORRUPTION_RUN_IDENTITY_MISMATCH",
    ):
        assert marker in p13


def test_p1_master_dsra_documentation_matches_current_project_uses_authority():
    """DSRA wording reflects Project Uses + funding stack, not stale blanket prose."""
    uses_source = (
        ROOT / "financial_engine" / "financing" / "project_uses.py"
    ).read_text(encoding="utf-8")
    stack_source = (ROOT / "financial_engine" / "financing" / "stack.py").read_text(
        encoding="utf-8"
    )
    reserve_source = (
        ROOT / "financial_engine" / "financing" / "reserve_policy.py"
    ).read_text(encoding="utf-8")

    assert "cash_reserve_funding" in uses_source
    assert "resolve_cash_dsra_requirement_keur" in uses_source
    assert "G2A_SOURCES_DO_NOT_EQUAL_USES" in stack_source
    assert "COD_FUNDING_HANDSHAKE" in reserve_source

    methodology = METHODOLOGY_DOC.read_text(encoding="utf-8")
    assert "does **not** justify a blanket statement" in methodology
    assert "funded through the canonical project funding stack" in methodology


def test_p1_master_solar_dsra_funding_and_rollforward_reconcile():
    """Canonical Solar DSRA reconciles from Project Uses through G2C movement."""
    from app.project_factories import create_generic_solar_reference
    from app.services.production_financial_authority import run_clean_production

    run = run_clean_production(
        create_generic_solar_reference(),
        "Base",
        project_type="Generic Solar Reference",
    )
    g2c = run.g2c_result
    financing = g2c.financing_result

    reserve_use = float(financing.project_uses.reserve_account_funding_keur)
    policy_funding = float(run.authority_metadata["initial_dsra_funding_keur"])
    assert reserve_use > 0.0
    assert math.isclose(reserve_use, policy_funding, rel_tol=0.0, abs_tol=1e-4)

    fc_use = financing.construction_funding.non_construction_fc_use
    assert fc_use is not None, "Solar CASH_DSRA must have a typed COD/FC funding use"
    assert math.isclose(float(fc_use.uses_keur), reserve_use, rel_tol=0.0, abs_tol=1e-4)
    assert math.isclose(
        float(fc_use.total_sources_keur), reserve_use, rel_tol=0.0, abs_tol=1e-4
    )
    assert abs(float(fc_use.residual_keur)) <= 1e-4

    operating = [period for period in g2c.waterfall_periods if not period.is_construction]
    assert operating, "Solar G2C must contain operating periods"
    first = operating[0]
    assert math.isclose(
        float(first.initial_funded_dsra_keur), reserve_use, rel_tol=0.0, abs_tol=1e-4
    )
    assert math.isclose(
        float(first.senior_dsra_opening_keur), reserve_use, rel_tol=0.0, abs_tol=1e-4
    )

    previous_closing = None
    for period in operating:
        opening = float(period.senior_dsra_opening_keur)
        closing = float(period.senior_dsra_closing_keur)
        expected_closing = (
            opening
            + float(period.dsra_top_up_keur)
            - float(period.dsra_draw_keur)
            - float(period.dsra_release_keur)
        )
        assert math.isclose(closing, expected_closing, rel_tol=0.0, abs_tol=1e-4), (
            f"DSRA roll-forward mismatch in period {period.period_index}: "
            f"opening={opening}, expected_closing={expected_closing}, closing={closing}"
        )
        if previous_closing is not None:
            assert math.isclose(
                opening, previous_closing, rel_tol=0.0, abs_tol=1e-4
            ), f"DSRA continuity mismatch in period {period.period_index}"
        previous_closing = closing


def test_p1_master_runtime_statement_pass_is_distinct_from_xlsx_statement_surface():
    """Runtime BS/cash are proven; institutional XLSX statement trace stays explicit."""
    production_source = (
        ROOT / "app" / "services" / "production_financial_authority.py"
    ).read_text(encoding="utf-8")
    workbook_source = (
        ROOT / "app" / "export" / "institutional_workbook.py"
    ).read_text(encoding="utf-8")
    p13 = (ROOT / "tests" / "test_p1_3_institutional_validation.py").read_text(
        encoding="utf-8"
    )

    assert "assemble_decision_complete_financial_statements" in production_source
    assert "financial_statements_result" in production_source
    assert "P1_3_BALANCE_SHEET_IDENTITY_SOLAR" in p13
    assert "P1_3_CASH_WATERFALL_IDENTITY" in p13

    # P1 completeness (PR #155): the institutional export now serializes
    # the clean C3 statements via the verbatim field-mapping adapter --
    # still no second statement engine, same run identity.
    assert "serialize_clean_statements" in workbook_source
    assert "financial_statements_result" in workbook_source
    assert "statements = None" not in workbook_source

    worked = WORKED_SOLAR_DOC.read_text(encoding="utf-8")
    dossier = REVIEW_DOSSIER.read_text(encoding="utf-8")
    for text in (worked, dossier):
        assert "BALANCE_SHEET_RECONCILIATION = PASS" in text
        assert "CASH_RECONCILIATION = PASS" in text
        assert "XLSX_STATEMENT_VALUE_TRACE = PASS" in text
        assert "XLSX_STATEMENT_RUN_BINDING = BY_CONSTRUCTION" in text
        assert "XLSX_CROSS_RUN_SOURCE_PROVENANCE = NOT_AVAILABLE" in text
        assert "XLSX_STATEMENT_TRACE = NOT_AVAILABLE" not in text


def test_p1_master_docs_cover_required_institutional_topics():
    methodology = METHODOLOGY_DOC.read_text(encoding="utf-8")
    worked = WORKED_SOLAR_DOC.read_text(encoding="utf-8")

    required_methodology_topics = (
        "Total Project Uses",
        "Sources & Uses",
        "DSRA / DSRF",
        "CFADS",
        "Senior debt draw, IDC, fees and sculpting",
        "Shareholder loans",
        "Financial statements and cash waterfall",
        "Project and sponsor returns",
        "Last Run, Working Copy and run identity",
        "Reference Regression Check",
        "Run Integrity",
        "Signed Run",
        "FINCO Verify",
    )
    for topic in required_methodology_topics:
        assert topic in methodology

    for trace_step in (
        "Inputs",
        "CAPEX / construction economics",
        "Sources & Uses",
        "Debt draw / IDC / fees",
        "Revenue / OPEX",
        "CFADS",
        "Debt service / DSCR",
        "Tax",
        "Cash waterfall",
        "Clean financial statements",
        "Project return",
        "Sponsor return",
        "Last Run",
        "Institutional XLSX",
        "Trust Pack",
    ):
        assert trace_step in worked

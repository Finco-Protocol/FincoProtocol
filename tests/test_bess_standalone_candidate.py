"""BESS02 explicit-input handoff: synthetic sources, no release flag changes."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
import json
from unittest.mock import patch

import pytest

from app.services import bess_standalone_candidate as candidate
from domain.bess.synthetic import example
from finco_core.inputs.senior_rate_schedule import (
    SeniorDayCountConvention, SeniorDebtInterestConfig, SeniorRateMode, SeniorRateSchedule,
)


@pytest.fixture
def explicit_inputs():
    # Existing synthetic policy is an isolated test vector, never project
    # creation authority or a statement of jurisdictional/merchant approval.
    from app.workbook.bess_config import native_base_inputs
    p = native_base_inputs()
    costs = {name: replace(getattr(p.capex, name), amount_keur=(25 if name == "epc_contract" else 5 if name in {"production_units", "epc_other"} else 0),
                           useful_life_override=5 if name == "epc_contract" else 10)
             for name in p.capex._CAPEX_ITEM_FIELDS}
    return replace(p,
        info=replace(p.info, country_iso="XC", financial_close=date(2027, 1, 1), construction_months=12,
                     cod_date=date(2028, 1, 1), horizon_years=3),
        technical=replace(p.technical, capacity_mw=1, bess=None),
        capex=replace(p.capex, **costs),
        opex=(replace(p.opex[0], y1_amount_keur=1, annual_inflation=0),),
        revenue=replace(p.revenue, ppa_base_tariff=0, ppa_term_years=0, ppa_production_share=0),
        financing=replace(p.financing, share_capital_keur=1, senior_tenor_years=2, gearing_ratio=.5,
            senior_debt_interest_config=SeniorDebtInterestConfig(enabled=True,
                rate_schedule=SeniorRateSchedule(mode=SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE,
                                                explicit_all_in_rates=(.055,) * 4),
                day_count=SeniorDayCountConvention.ACT_360)))


def native_document():
    return {"version": 1, "configuration": example("2028-01-01T00:00:00Z", "2030-12-31T00:00:00Z"),
            "variable_om_eur_per_dc_mwh": 1}


def declaration(project, raw):
    return {"version": 1, "cost_basis": "MANUAL_DECLARED_KEUR", "source_ref": "synthetic-explicit-test-basis",
            **candidate.declaration_basis(project, json.dumps(raw)),
            "policy_references": {k: "synthetic-policy-" + k for k in candidate.POLICY_REFERENCES}}


def prepare(project, raw=None, doc=None):
    raw = raw or native_document()
    doc = doc if doc is not None else declaration(project, raw)
    return candidate.prepare_candidate(project, json.dumps(raw), json.dumps(doc))


def test_preparation_does_not_call_factory_engine_writer_or_change_source(explicit_inputs):
    source_before = deepcopy(asdict(explicit_inputs))
    raw = native_document()
    raw_before = deepcopy(raw)
    with patch("app.project_factories.create_default_bess_project", side_effect=AssertionError("factory")), \
         patch("app.services.production_financial_authority.run_clean_production", side_effect=AssertionError("financial Run")), \
         patch("app.persistence.projects_repository.save_project", side_effect=AssertionError("project write")), \
         patch("app.persistence.workspace_repository.save_workspace_state", side_effect=AssertionError("draft write")):
        prepared = prepare(explicit_inputs, raw)
    assert asdict(explicit_inputs) == source_before and raw == raw_before
    assert prepared.project_inputs.capex is explicit_inputs.capex
    assert prepared.project_inputs.financing is explicit_inputs.financing
    assert prepared.project_inputs.tax is explicit_inputs.tax
    assert prepared.project_inputs.accounting_policy_config is explicit_inputs.accounting_policy_config
    assert prepared.project_inputs.technical.bess is None
    assert prepared.project_inputs.technical.bess_native_config_json
    assert len(prepared.period_axis) == 6
    assert sum(p[3] for p in prepared.period_axis) == (366 + 365 + 365 - 1) * 24
    review = prepared.review()
    assert review["identity_scope"] == "CANDIDATE_CONTENT_ONLY_NOT_RUN_OR_WORKSPACE_IDENTITY"
    assert review["policy_reference_scope"] == "USER_DECLARED_PROVENANCE_NOT_FINANCIAL_OWNER_APPROVAL"
    assert review["capability"]["financial_calculation_count"] == 0
    assert not review["capability"]["persisted"]
    assert not any(review["capability"][k] for k in ("create_supported", "save_supported", "run_supported"))


def test_existing_operating_engine_has_gross_revenue_and_every_cost_exactly_once(explicit_inputs):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    prepared = prepare(explicit_inputs)
    result = run_operating_model(from_project_inputs(prepared.project_inputs))
    for period in result.periods:
        if not period.is_operation:
            assert period.revenue_keur == period.opex_keur == 0
            continue
        # Independent closed-form daily vector, no production dispatch or
        # settlement function is used to calculate these expectations.
        days = Decimal((period.period_end - period.period_start).days)
        gross = days * Decimal(".81") * Decimal(100) / 1000
        purchase = days * Decimal(1) * Decimal(40) / 1000
        auxiliary = days * 24 * Decimal(".01") * Decimal(40) / 1000
        import_fees = days * (Decimal(1) + 24 * Decimal(".01")) * Decimal(2) / 1000
        export_fees = days * Decimal(".81") * Decimal(1) / 1000
        throughput = days * (Decimal(1) * Decimal(".9") + Decimal(".81") / Decimal(".9"))
        variable_om = throughput * Decimal(1) / 1000
        fixed_om = Decimal(str(period.day_fraction))
        costs = purchase + auxiliary + import_fees + export_fees + variable_om + fixed_om
        assert period.revenue_keur == pytest.approx(float(gross), abs=1e-10)
        assert period.opex_keur == pytest.approx(float(costs), abs=1e-10)
        assert period.ebitda_keur == pytest.approx(float(gross - costs), abs=1e-10)
        assert period.book_depreciation_keur > 0
    # This operating proof is not a canonical successful Run or a persisted ID.
    from app.services.production_financial_authority import run_clean_production, CleanProductionRunUnavailable
    with pytest.raises(CleanProductionRunUnavailable, match="BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED"):
        run_clean_production(prepared.project_inputs, project_type="Storage")


@pytest.mark.parametrize("fault", ["native-edit", "source-cost-edit", "source-policy-edit", "power-cost-basis", "asset-cost-basis",
                                  "missing-zero-asset", "asset-class", "asset-spending", "forged-ready"])
def test_changed_cost_power_policy_or_native_inputs_require_new_exact_declaration(explicit_inputs, fault):
    raw = native_document()
    doc = declaration(explicit_inputs, raw)
    project = explicit_inputs
    if fault == "native-edit": raw["configuration"]["battery"]["installed_energy_mwh"] = 4
    elif fault == "source-cost-edit": project = replace(project, capex=replace(project.capex, epc_contract=replace(project.capex.epc_contract, amount_keur=30)))
    elif fault == "source-policy-edit": project = replace(project, tax=replace(project.tax, corporate_rate=.23))
    elif fault == "power-cost-basis": doc["battery_basis"]["discharge_power_mw"] = 2
    elif fault == "asset-cost-basis": doc["asset_costs"]["epc_contract"]["amount_keur"] = 30
    elif fault == "missing-zero-asset": doc["asset_costs"].pop("grid_connection")
    elif fault == "asset-class": doc["asset_costs"]["epc_contract"]["asset_class"] = "civil_grid"
    elif fault == "asset-spending": doc["asset_costs"]["epc_contract"]["spending_profile"] = [1, 0]
    else: doc["ready"] = True
    with pytest.raises(candidate.BessStandaloneCandidateError): prepare(project, raw, doc)


@pytest.mark.parametrize("fault,reason", [
    ("legacy", "STANDALONE_NATIVE_ONLY"), ("hybrid", "STANDALONE_NATIVE_ONLY"),
    ("power", "DECLARED_POWER_MISMATCH"), ("ppa", "DUPLICATE_REVENUE"),
    ("co2", "DUPLICATE_REVENUE"), ("accounting", "ACCOUNTING_AND_CASH_TAX"),
    ("cash-tax", "ACCOUNTING_AND_CASH_TAX"), ("life", "ASSET_BOOK_LIFE"),
    ("country", "TAX_JURISDICTION"), ("horizon", "TWO_YEAR_SEMIANNUAL"),
    ("floating", "EXPLICIT_ALL_IN_RATE"), ("no-rates", "EXPLICIT_ALL_IN_RATE"),
    ("short-rates", "EXPLICIT_ALL_IN_RATE"), ("nan-rate", "PROJECT_INPUTS_INVALID"),
    ("axis", "FINANCE_AXIS"), ("inventory", "INVENTORY_FINANCIAL"),
])
def test_unsupported_project_semantics_fail_closed(explicit_inputs, fault, reason):
    project = explicit_inputs
    raw = native_document()
    if fault == "legacy":
        from app.workbook.bess_config import native_base_inputs
        project = replace(project, technical=replace(project.technical, bess=native_base_inputs().technical.bess))
    elif fault == "hybrid": project = replace(project, technical=replace(project.technical, operating_hours_p50=1))
    elif fault == "power": project = replace(project, technical=replace(project.technical, capacity_mw=2))
    elif fault == "ppa": project = replace(project, revenue=replace(project.revenue, ppa_base_tariff=30))
    elif fault == "co2": project = replace(project, revenue=replace(project.revenue, co2_enabled=True))
    elif fault == "accounting": project = replace(project, accounting_policy_config=None)
    elif fault == "cash-tax": project = replace(project, tax=replace(project.tax, clean_cash_tax_timing_enabled=False))
    elif fault == "life": project = replace(project, capex=replace(project.capex, epc_contract=replace(project.capex.epc_contract, useful_life_override=None)))
    elif fault == "country": project = replace(project, info=replace(project.info, country_iso=""))
    elif fault == "horizon": project = replace(project, info=replace(project.info, horizon_years=1))
    elif fault == "no-rates": project = replace(project, financing=replace(project.financing, senior_debt_interest_config=None))
    elif fault in {"floating", "short-rates", "nan-rate"}:
        cfg = project.financing.senior_debt_interest_config
        schedule = cfg.rate_schedule
        if fault == "floating": schedule = replace(schedule, mode=SeniorRateMode.FLOATING_PLUS_MARGIN)
        elif fault == "short-rates": schedule = replace(schedule, explicit_all_in_rates=(.055,))
        else: schedule = replace(schedule, explicit_all_in_rates=(float("nan"),) * 4)
        project = replace(project, financing=replace(project.financing, senior_debt_interest_config=replace(cfg, rate_schedule=schedule)))
    elif fault == "axis": raw["configuration"]["end"] = "2029-01-01T00:00:00Z"
    elif fault == "inventory": raw["configuration"]["battery"]["initial_energy_mwh"] = .1
    with pytest.raises(candidate.BessStandaloneCandidateError, match=reason): prepare(project, raw)


def test_creator_is_unconditionally_closed_before_database_or_reference_mutation(explicit_inputs, monkeypatch):
    from app.workbook import bess_config
    from app.services.project_library_service import CLONEABLE_TEMPLATE_SOURCES
    assert bess_config.ACTIVATION_ENABLED is False
    assert "generic_storage_reference" not in CLONEABLE_TEMPLATE_SOURCES
    monkeypatch.setenv("FINCO_BESS02_ENABLED", "true")
    monkeypatch.setenv("FINCO_BESS_COMMERCIAL", "true")
    prepared = prepare(explicit_inputs)
    with patch("app.persistence.projects_repository.save_project", side_effect=AssertionError("project write")), \
         patch("app.persistence.workspace_repository.save_workspace_state", side_effect=AssertionError("draft write")), \
         patch("app.services.project_library_service.create_working_copy", side_effect=AssertionError("reference clone")):
        for payload in (prepared, {"ready": True, "activation_enabled": True}, {"user_id": "__reference__"}):
            with pytest.raises(candidate.BessStandaloneCandidateError, match="CANONICAL_CREATOR_RELEASE_CLOSED"):
                candidate.create_standalone_project(payload, user_id="synthetic", csrf_valid=True)
    assert not any(candidate.capability()[k] for k in ("create_supported", "save_supported", "run_supported"))
    assert bess_config.ACTIVATION_ENABLED is False


@pytest.mark.parametrize("fault", ["missing-policy", "empty-policy", "bad-number", "duplicate-key", "over-size", "unapproved-cost-method"])
def test_declaration_is_strict_and_has_no_missing_defaults(explicit_inputs, fault):
    raw = native_document()
    doc = declaration(explicit_inputs, raw)
    if fault == "missing-policy": doc["policy_references"].pop("funding")
    elif fault == "empty-policy": doc["policy_references"]["tax_jurisdiction"] = ""
    elif fault == "bad-number": doc["battery_basis"]["usable_energy_mwh"] = True
    elif fault == "unapproved-cost-method": doc["cost_basis"] = "ESTIMATED_EUR_PER_MWH"
    serialized = json.dumps(doc)
    if fault == "duplicate-key": serialized = serialized.replace('"version": 1', '"version": 1, "version": 1', 1)
    if fault == "over-size": serialized = " " * (candidate.MAX_DECLARATION_BYTES + 1)
    with pytest.raises(candidate.BessStandaloneCandidateError):
        candidate.prepare_candidate(explicit_inputs, json.dumps(raw), serialized)

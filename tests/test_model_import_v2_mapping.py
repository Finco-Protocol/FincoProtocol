"""Import V2: deterministic mapping benchmark, number formats, units, structured targets, negative safety.

Independently synthetic, generic labels only.  Nothing here calls a model engine, a network or a provider.
"""
from __future__ import annotations

import ast
import csv
import io
from decimal import Decimal
from pathlib import Path

import pytest

from app.model_import import mapping
from app.model_import.intake import IntakeError, extract_proposals, normalize_value
from app.model_import.mapping import (
    NumberFormatError, classify_cell, parse_localized_number, rank_candidates, validate_candidate,
)

SOLAR = dict(project_type="Solar", template_source="generic_solar_reference")
DC = dict(project_type="Data Center", template_source="generic_data_center_reference")
EV = dict(project_type="EV Charging", template_source="generic_ev_charging_reference")

# (label, unit, sheet, expected) — expected: a field id (must be SCALAR + confident), a kind string
# (non-scalar, read-only), "UNSUPPORTED" (nothing convincing) or "CASCADE" (recognised, not batch-applyable).
BENCHMARK = [
    ("Full load hours", "h/yr", "Technical", "project_setup.technical.p50_hours"),
    ("Project life", "years", "General", "project_setup.technical.horizon_years"),
    ("Construction period", "months", "General", "project_setup.technical.construction_months"),
    ("Commissioning date", "date", "General", "project_setup.technical.cod_date"),
    ("EPC contract", "EUR", "CAPEX", "capex.C.epc_contract"),
    ("Grid interconnection cost", "kEUR", "CAPEX", "capex.C.grid_connection"),
    ("Insurances", "kEUR", "CAPEX", "capex.C.insurances"),
    ("Audit and legal", "kEUR", "CAPEX", "capex.D.audit_legal"),
    ("Insurance", "kEUR/yr", "OPEX", "opex.lines.insurance"),
    ("Insurance (annual)", "kEUR/yr", "OPEX", "opex.lines.insurance"),
    ("Security per year", "EUR", "OPEX", "opex.lines.security"),
    ("Audit, accounting and legal (annual)", "kEUR/yr", "OPEX", "opex.lines.audit_accounting_legal"),
    ("PPA tariff", "EUR/MWh", "Revenue", "revenue.ppa.base_tariff"),
    ("PPA escalation", "%", "Revenue", "revenue.ppa.index"),
    ("PPA term", "years", "Revenue", "revenue.ppa.term_years"),
    ("Cost of debt", "%", "Financing", "debt.senior.interest_rate_pct"),
    ("Leverage", "%", "Financing", "debt.senior.gearing_pct"),
    ("Loan tenor", "years", "Financing", "debt.senior.tenor_years"),
    ("Target DSCR", "x", "Financing", "debt.senior.target_dscr"),
    ("Corporate income tax", "%", "Tax", "tax.assumptions.cit_rate_pct"),
    ("Tax losses carried forward", "years", "Tax", "tax.assumptions.loss_carryforward_years"),
    ("Installed capacity (MW)", None, "Technical", "CASCADE"),
    ("Nameplate capacity", "kW", "General", "CASCADE"),
    ("Junior debt amount", "kEUR", "Financing", "FINANCING_INSTRUMENT"),
    ("Mezzanine tranche rate", "%", "Financing", "FINANCING_INSTRUMENT"),
    ("Preferred equity coupon", "%", "Financing", "FINANCING_INSTRUMENT"),
    ("Merchant price curve", "EUR/MWh", "Revenue", "REVENUE_CONTRACT"),
    ("CfD strike price", "EUR/MWh", "Revenue", "REVENUE_CONTRACT"),
    ("Transformer", "kEUR", "CAPEX", "CAPEX_LINE"),
    ("Weather station", "", "General", "UNSUPPORTED"),
    ("Random notes", "", "General", "UNSUPPORTED"),
]


def _classify(label, unit, sheet, **tech):
    return classify_cell(label=label, unit=unit, sheet=sheet, **(tech or SOLAR))


def test_benchmark_never_reports_a_wrong_confident_scalar_and_recalls_the_clear_cases():
    scalar_expected = [b for b in BENCHMARK if "." in b[3]]
    correct = 0
    for label, unit, sheet, expected in BENCHMARK:
        got = _classify(label, unit, sheet)
        suggestion = got["suggestion"] or {}
        if "." in expected:
            # a confident scalar is either the right one or absent; a wrong one is a hard failure
            if got["target_kind"] == "SCALAR":
                assert suggestion["field_id"] == expected, (label, suggestion["field_id"])
                correct += 1
        elif expected == "CASCADE":
            assert got["target_kind"] == "UNSUPPORTED" and got["apply_support"] == "UNSUPPORTED_FOR_APPLY", label
            assert suggestion["field_id"] == "project_setup.technical.capacity_mw"
        elif expected == "UNSUPPORTED":
            assert got["target_kind"] == "UNSUPPORTED" and got["apply_support"] == "NONE", label
        else:
            assert got["target_kind"] == expected and got["apply_support"] == "UNSUPPORTED_FOR_APPLY", (label, got["target_kind"])
            assert got["suggestion"]["field_id"] is None
    assert correct / len(scalar_expected) >= 0.9, f"recall {correct}/{len(scalar_expected)}"


def test_ranking_is_deterministic_and_carries_an_explanation_not_a_probability():
    a = rank_candidates(label="Insurance", unit="kEUR/yr", sheet="OPEX", **SOLAR)
    b = rank_candidates(label="Insurance", unit="kEUR/yr", sheet="OPEX", **SOLAR)
    assert [c.as_dict() for c in a] == [c.as_dict() for c in b]
    assert a[0].field_id == "opex.lines.insurance" and a[0].explanation
    assert set(a[0].as_dict()) == {"kind", "field_id", "label", "category", "confidence", "score", "explanation",
                                   "applyable", "owner"}
    assert a[0].confidence in {"high", "medium", "low"}            # a category, never "87% sure"


def test_capex_and_opex_wording_resolve_the_same_label_by_context_and_unit():
    capex = _classify("Insurance", "kEUR", "CAPEX")
    opex = _classify("Insurance", "kEUR/yr", "OPEX")
    assert capex["suggestion"]["field_id"] == "capex.C.insurances" and capex["category"] == "CAPEX"
    assert opex["suggestion"]["field_id"] == "opex.lines.insurance" and opex["category"] == "OPEX"


def test_dimensionally_incompatible_units_are_never_candidates():
    assert rank_candidates(label="PPA tariff", unit="kEUR", sheet="Revenue", **SOLAR) == []
    assert rank_candidates(label="Loan tenor", unit="%", sheet="Financing", **SOLAR) == []
    assert _classify("Target DSCR", "MW", "Financing")["target_kind"] == "UNSUPPORTED"


def test_technology_applicability_is_enforced_by_the_registry_not_by_wording():
    dc = classify_cell(label="Occupancy Y2", unit="%", sheet="Revenue", **DC)
    solar = classify_cell(label="Occupancy Y2", unit="%", sheet="Revenue", **SOLAR)
    ev = classify_cell(label="Equivalent full load hours stabilized", unit="h", sheet="Revenue", **EV)
    assert dc["target_kind"] == "SCALAR" and dc["suggestion"]["field_id"] == "revenue.data_center.occupancy_y2"
    assert solar["target_kind"] != "SCALAR" or solar["suggestion"]["field_id"] != "revenue.data_center.occupancy_y2"
    assert ev["suggestion"] is not None and ev["suggestion"]["field_id"] == "revenue.ev_charging.hours_stabilized"


def test_structured_documents_can_never_be_a_scalar_target():
    for field_id in mapping.STRUCTURED_FIELD_OWNERS:
        assert validate_candidate(field_id=field_id, **SOLAR) == (False, "UNSUPPORTED_FOR_APPLY")
    for label in ("Revenue contracts", "Two-Senior configuration", "Bankability configuration"):
        got = _classify(label, "", "Revenue")
        assert got["target_kind"] in ("UNSUPPORTED", "FINANCING_INSTRUMENT", "REVENUE_CONTRACT")
        assert (got["suggestion"] or {}).get("field_id") not in mapping.STRUCTURED_FIELD_OWNERS


@pytest.mark.parametrize("field_id,expected", [
    ("does.not.exist", "IMPORT_UNKNOWN_FIELD"),
    ("capex.C.epc_contract", "OK"),
    ("project_setup.identity.project_name", "BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT"),
    ("revenue.data_center.occupancy_y1", "BATCH_FIELD_NOT_APPLICABLE"),
    ("project_setup.technical.capacity_mw", "BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT"),
])
def test_validate_candidate_is_the_single_gate_for_forged_or_inapplicable_targets(field_id, expected):
    ok, why = validate_candidate(field_id=field_id, **SOLAR)
    assert (why == expected) and (ok == (expected == "OK"))


@pytest.mark.parametrize("text,expected", [
    ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("1 234,5", "1234.5"), ("1 234,5", "1234.5"),
    ("12,5", "12.5"), ("1234.5", "1234.5"), ("0.125", "0.125"), ("12.5", "12.5"), ("1234.567", "1234.567"), ("1.234.567", "1234567"),
    ("1,234,567", "1234567"), ("7,5", "7.5"), ("-3,25", "-3.25"), ("1 234 567,89", "1234567.89"),
])
def test_unambiguous_european_and_us_number_formats_are_read(text, expected):
    assert parse_localized_number(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["1,234", "18.000", "1.234", "12.500", "1.2.3", "1,2,3", "12 34", "1,234,56", "abc", "", "1.234,5,6", "1,,2", "--1"])
def test_ambiguous_or_malformed_numbers_are_rejected_never_guessed(text):
    with pytest.raises(NumberFormatError):
        parse_localized_number(text)


@pytest.mark.parametrize("field,value,unit,expected", [
    ("capex.C.epc_contract", "1.200.000,50", "EUR", "1200.0005"),
    ("capex.C.epc_contract", "1200,5", "kEUR", "1200.5"),
    ("opex.lines.security", "75000", "EUR/yr", "75"),
    ("revenue.ppa.base_tariff", "0.062", "EUR/kWh", "62.000"),
    ("revenue.ev_charging.charging_price", "380", "EUR/MWh", "0.380"),
    ("debt.senior.gearing_pct", "0,75", "fraction", "75.00"),
    ("debt.senior.gearing_pct", "75", "%", "75"),
    ("debt.senior.gearing_pct", "7,5 %", "", "7.5"),
])
def test_unit_and_scale_normalisation_including_european_numbers(field, value, unit, expected):
    assert Decimal(normalize_value(field, value, unit)) == Decimal(expected)


@pytest.mark.parametrize("field,value,unit,code", [
    ("debt.senior.gearing_pct", "75", "", "IMPORT_PERCENT_SCALE_AMBIGUOUS"),
    ("capex.C.epc_contract", "120000", "", "IMPORT_CURRENCY_UNIT_REQUIRED"),
    ("capex.C.epc_contract", "1,234", "EUR", "IMPORT_NUMBER_FORMAT_AMBIGUOUS"),
    ("debt.senior.gearing_pct", "75 %", "fraction", "IMPORT_PERCENT_SCALE_CONFLICT"),
    ("debt.senior.tenor_years", "15", "MW", "IMPORT_UNIT_INCOMPATIBLE"),
    ("revenue.ppa.base_tariff", "=A1*2", "EUR/MWh", "IMPORT_FORMULA_NOT_AUTHORITATIVE"),
])
def test_unit_and_format_errors_stay_unresolved(field, value, unit, code):
    with pytest.raises(IntakeError, match=code):
        normalize_value(field, value, unit)


def _csv(rows, **tech):
    buf = io.StringIO()
    csv.writer(buf, delimiter="\t").writerows(rows)
    return extract_proposals(buf.getvalue().encode("utf-8"), "synthetic.csv", **(tech or SOLAR))


def test_extraction_adds_ranked_suggestions_but_never_marks_them_ready():
    result = _csv([["Assumption", "Value", "Unit"], ["CAPEX"], ["Grid interconnection cost", "1.200.000,50", "EUR"],
                   ["OPEX"], ["Insurance", "42,5", "kEUR/yr"], ["capex.C.commissioning", "300", "kEUR"]])
    by = {p["label"]: p for p in result["proposals"]}
    ranked = by["Grid interconnection cost"]
    assert ranked["field_id"] == "capex.C.grid_connection" and ranked["mapping_method"] == "ranked_candidate"
    assert ranked["status"] == "needs_review" and ranked["normalized_value"] == "1200.0005"
    assert ranked["category"] == "CAPEX" and ranked["explanation"] and ranked["section"] == "CAPEX"
    assert by["Insurance"]["field_id"] == "opex.lines.insurance" and by["Insurance"]["category"] == "OPEX"
    assert by["capex.C.commissioning"]["status"] == "ready"            # only an exact id is "ready"
    assert all(p["status"] != "ready" for p in result["proposals"] if p["mapping_method"] == "ranked_candidate")


def test_label_embedded_units_are_used_only_when_explicit_in_the_file():
    result = _csv([["Assumption", "Value"], ["EPC contract (kEUR)", "1500"], ["EPC other", "10"]])
    first, second = result["proposals"]
    assert first["source_unit"] == "kEUR" and first["unit_origin"] == "label_text" and first["status"] == "needs_review"
    assert second["source_unit"] is None and second["status"] == "invalid"            # no unit: never guessed


def test_duplicate_targets_and_ambiguous_labels_are_queued_not_merged():
    result = _csv([["Assumption", "Value", "Unit"], ["Insurance", "40", "kEUR/yr"], ["Insurance annual", "55", "kEUR/yr"]])
    assert all(p["duplicate_target"] and p["status"] == "needs_review" for p in result["proposals"])
    assert {p["reason"] for p in result["proposals"]} == {"IMPORT_DUPLICATE_TARGET_REQUIRES_REVIEW"}


def test_structured_and_unsupported_rows_are_read_only_with_the_owning_editor_named():
    result = _csv([["Assumption", "Value", "Unit"], ["Junior debt amount", "500", "kEUR"], ["Merchant price curve", "55", "EUR/MWh"],
                   ["Transformer", "120", "kEUR"], ["Installed capacity", "20", "MW"], ["Weather station", "x", ""]])
    by = {p["label"]: p for p in result["proposals"]}
    for label, kind in (("Junior debt amount", "FINANCING_INSTRUMENT"), ("Merchant price curve", "REVENUE_CONTRACT"),
                        ("Transformer", "CAPEX_LINE")):
        row = by[label]
        assert row["status"] == "unsupported_for_apply" and row["reason"] == "UNSUPPORTED_FOR_APPLY"
        assert row["target_kind"] == kind and row["field_id"] is None and row["owner_editor"]
    # exact registry label of a cascade field: the V1 gate keeps it unsupported with the precise reason
    assert by["Installed capacity"]["status"] == "unsupported"
    assert by["Installed capacity"]["reason"] == "BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT"
    near = _csv([["Assumption", "Value", "Unit"], ["Nameplate capacity", "20", "MW"]])["proposals"][0]
    assert near["status"] == "unsupported_for_apply" and near["recognized_target"]["field_id"] == "project_setup.technical.capacity_mw"
    assert by["Weather station"]["status"] == "unsupported" and by["Weather station"]["reason"] == "IMPORT_UNSUPPORTED_LABEL"


def test_formula_cells_are_never_normalised_or_inferred():
    result = _csv([["Assumption", "Value", "Unit"], ["EPC contract", "=SUM(A1:A3)", "EUR"]])
    row = result["proposals"][0]
    # The label may still match, but a formula can never be approved or normalised into a value.
    assert row["status"] == "invalid" and row["reason"] == "IMPORT_FORMULA_NOT_AUTHORITATIVE"
    assert row["normalized_value"] is None


def test_mapping_module_has_no_network_model_or_writer_imports():
    tree = ast.parse(Path(mapping.__file__).read_text(encoding="utf-8"))
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    forbidden = ("requests", "httpx", "urllib", "socket", "openai", "anthropic", "subprocess", "financial_engine",
                 "finco_core", "app.persistence")
    assert not [m for m in names if m.startswith(forbidden)]
    source = Path(mapping.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source and "exec(" not in source and "API_KEY" not in source

"""Import V2 Correction A: lossless unit provenance and truthful approval semantics.

The signed approved ticket keeps the original value, the extracted unit, the user's chosen unit, the final canonical
unit, the normalised value, the original suggestion and every user correction.  A user correction is never presented
as an untouched automatic mapping.  Same signed-ticket mechanism, no stored workbook, no new writer.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.model_import.intake import IntakeError, extract_proposals, normalize_value
from app.model_import.review import ImportReviewError, resolve_review, seal_approved, seal_preview, unseal_approved
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import save
from tests.test_model_import_v2_review_security import (  # noqa: F401
    OWNER, _apply, _approved_ticket, _confirm, _evidence, _hash, _preview, _routes, _ws,
)

SOLAR = dict(project_type="Solar", template_source="generic_solar_reference")
TAB = "Assumption\tValue\tUnit\n"


def _resolve(csv_text, selections):
    result = extract_proposals(csv_text.encode("utf-8"), "synthetic.csv", encoding="utf-8", **SOLAR)
    ticket = seal_preview(owner="o", project_id="p", scenario_id=None, content_hash="h", workbook_version="v",
                          digest="d", proposals=result["proposals"])
    preview, approved = resolve_review(ticket=ticket, owner="o", project_id="p", selections=selections, **SOLAR)
    return result["proposals"], approved


def test_untouched_exact_id_mapping_stays_automatic_and_records_both_units():
    _, [row] = _resolve(TAB + "capex.C.epc_contract\t120000\tEUR\n",
                        {"keep_0": "on", "field_0": "capex.C.epc_contract", "unit_0": "EUR"})
    assert row["mapping_origin"] == "automatic" and row["method"] == "exact_field_id"
    assert (row["extracted_unit"], row["chosen_unit"], row["canonical_unit"]) == ("EUR", "EUR", "kEUR")
    assert row["original_value"] == "120000" and Decimal(row["normalized_value"]) == Decimal("120")
    assert row["unit_corrected"] is False and row["field_remapped"] is False and row["corrections"] == []
    assert row["suggested_field_id"] == row["field_id"] == "capex.C.epc_contract" and row["correction_note"] == ""
    assert row["suggested_normalized"] == "120" and row["suggested_method"] == "exact_field_id"


def test_unit_corrected_without_changing_the_field_is_user_reviewed_and_keeps_both_units():
    _, [row] = _resolve(TAB + "capex.C.epc_contract\t120000\tEUR\n",
                        {"keep_0": "on", "field_0": "capex.C.epc_contract", "unit_0": "kEUR"})
    assert row["unit_corrected"] is True and row["corrections"] == ["SOURCE_UNIT_CORRECTED"]
    assert row["mapping_origin"] == "user_reviewed" and row["method"] == "manual_reviewed"
    assert row["suggested_method"] == "exact_field_id"                      # the original automatic method is kept
    assert (row["extracted_unit"], row["chosen_unit"], row["canonical_unit"]) == ("EUR", "kEUR", "kEUR")
    assert Decimal(row["normalized_value"]) == Decimal("120000")            # the user's unit decides the value
    assert row["suggested_normalized"] == "120"                             # ...while the automatic outcome is retained
    assert row["field_remapped"] is False and "from EUR to kEUR" in row["correction_note"]
    assert "corrected by the user from EUR" in row["normalization"]


@pytest.mark.parametrize("field,value,unit,expected,canonical", [
    ("capex.C.epc_contract", "120000", "EUR", "120", "kEUR"),
    ("revenue.ppa.base_tariff", "0,062", "EUR/kWh", "62", "EUR/MWh"),
    ("revenue.ev_charging.charging_price", "380", "EUR/MWh", "0.38", "EUR/kWh"),
    ("debt.senior.gearing_pct", "0,75", "fraction", "75", "%"),
    ("debt.senior.gearing_pct", "75", "%", "75", "%"),
])
def test_automatic_conversions_keep_original_extracted_and_canonical_units(field, value, unit, expected, canonical):
    template = "generic_ev_charging_reference" if "ev_charging" in field else "generic_solar_reference"
    ptype = "EV Charging" if "ev_charging" in field else "Solar"
    result = extract_proposals((TAB + f"{field}\t{value}\t{unit}\n").encode(), "s.csv", encoding="utf-8",
                               project_type=ptype, template_source=template)
    ticket = seal_preview(owner="o", project_id="p", scenario_id=None, content_hash="h", workbook_version="v",
                          digest="d", proposals=result["proposals"])
    _, [row] = resolve_review(ticket=ticket, owner="o", project_id="p", project_type=ptype, template_source=template,
                              selections={"keep_0": "on", "field_0": field, "unit_0": unit})
    assert Decimal(row["normalized_value"]) == Decimal(expected) and row["canonical_unit"] == canonical
    assert row["extracted_unit"] == row["chosen_unit"] == unit and row["unit_corrected"] is False
    assert row["mapping_origin"] == "automatic"


def test_percent_versus_fraction_correction_is_flagged_and_changes_the_value_visibly():
    _, [row] = _resolve(TAB + "debt.senior.gearing_pct\t0,75\tfraction\n",
                        {"keep_0": "on", "field_0": "debt.senior.gearing_pct", "unit_0": "%"})
    assert row["unit_corrected"] and row["mapping_origin"] == "user_reviewed"
    assert Decimal(row["normalized_value"]) == Decimal("0.75") and row["suggested_normalized"] == "75.00"
    assert (row["extracted_unit"], row["chosen_unit"]) == ("fraction", "%")


def test_ambiguous_number_formatting_is_rejected_at_review_not_normalised():
    with pytest.raises(ImportReviewError, match="IMPORT_NUMBER_FORMAT_AMBIGUOUS"):
        _resolve(TAB + "capex.C.epc_contract\t1,234\tEUR\n",
                 {"keep_0": "on", "field_0": "capex.C.epc_contract", "unit_0": "EUR"})
    with pytest.raises(ImportReviewError, match="IMPORT_NUMBER_FORMAT_AMBIGUOUS"):
        _resolve(TAB + "opex.lines.security\t18.000\tEUR/yr\n",
                 {"keep_0": "on", "field_0": "opex.lines.security", "unit_0": "EUR/yr"})


def test_manually_remapped_field_keeps_the_original_suggestion():
    proposals, [row] = _resolve(TAB + "Grid interconnection cost\t300\tkEUR\n",
                                {"keep_0": "on", "field_0": "capex.C.commissioning", "unit_0": "kEUR"})
    assert proposals[0]["field_id"] == "capex.C.grid_connection"
    assert row["field_remapped"] and row["suggested_field_id"] == "capex.C.grid_connection"
    assert row["field_id"] == "capex.C.commissioning" and row["corrections"] == ["FIELD_REMAPPED"]
    assert row["mapping_origin"] == "user_reviewed" and row["suggested_method"] == "ranked_candidate"
    assert row["unit_corrected"] is False and "capex.C.grid_connection" in row["correction_note"]


def test_manual_value_override_is_identified_and_the_unit_choice_is_recorded_but_unused():
    _, [row] = _resolve(TAB + "capex.C.epc_contract\t120000\tEUR\n",
                        {"keep_0": "on", "field_0": "capex.C.epc_contract", "unit_0": "kEUR", "manual_0": "99"})
    assert row["value_overridden"] and row["value"] == "99" and row["unit_corrected"] is False
    assert row["corrections"] == ["VALUE_OVERRIDDEN"] and row["chosen_unit"] == "kEUR"
    assert "not used" in row["correction_note"] and row["normalization"].startswith("manual FINCO value")


def test_an_absent_unit_field_is_not_a_correction_and_keeps_the_extracted_unit():
    _, [row] = _resolve(TAB + "capex.C.epc_contract\t120000\tEUR\n", {"keep_0": "on", "field_0": "capex.C.epc_contract"})
    assert row["chosen_unit"] == "EUR" and not row["unit_corrected"] and row["mapping_origin"] == "automatic"
    assert Decimal(row["normalized_value"]) == Decimal("120")


def test_explicitly_clearing_the_unit_is_a_user_choice_and_is_rejected_where_a_unit_is_required():
    with pytest.raises(ImportReviewError, match="IMPORT_CURRENCY_UNIT_REQUIRED"):
        _resolve(TAB + "capex.C.epc_contract\t120000\tEUR\n",
                 {"keep_0": "on", "field_0": "capex.C.epc_contract", "unit_0": ""})


def test_kw_to_mw_conversion_is_lossless_at_the_normaliser():
    assert Decimal(normalize_value("project_setup.technical.capacity_mw", "20000", "kW")) == Decimal("20")
    with pytest.raises(IntakeError, match="IMPORT_UNIT_INCOMPATIBLE"):
        normalize_value("project_setup.technical.capacity_mw", "20", "EUR")


def test_approved_ticket_round_trips_the_provenance_and_rejects_tampering():
    _, approved = _resolve(TAB + "capex.C.epc_contract\t120000\tEUR\n",
                           {"keep_0": "on", "field_0": "capex.C.epc_contract", "unit_0": "kEUR"})
    preview = {"owner": "o", "project_id": "p", "scenario_id": None, "content_hash": "h", "workbook_version": "v",
               "digest": "d", "rows": [{}]}
    ticket = seal_approved(preview, approved)
    body = unseal_approved(ticket, owner="o", project_id="p")
    assert body["approved"][0]["extracted_unit"] == "EUR" and body["approved"][0]["chosen_unit"] == "kEUR"
    assert body["approved"][0]["corrections"] == ["SOURCE_UNIT_CORRECTED"] and body["approval_event"] == "USER_CONFIRMED_REVIEW"
    with pytest.raises(ImportReviewError, match="IMPORT_REVIEW_EXPIRED_OR_TAMPERED"):
        unseal_approved(ticket[:-4] + "AAAA", owner="o", project_id="p")
    with pytest.raises(ImportReviewError, match="IMPORT_REVIEW_OWNER_MISMATCH"):
        unseal_approved(ticket, owner="someone-else", project_id="p")


CSV = TAB + "capex.C.epc_contract\t120000\tEUR\nInsurance (annual)\t42,5\tkEUR/yr\n"


def test_confirm_and_result_pages_show_truthful_original_to_approved_provenance(env):
    project = env.create("solar")
    history = tuple(h.history_id for h in get_run_history(OWNER, project.project_id))
    _, ticket = _preview(env, project, CSV)
    untouched = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.epc_contract", unit_0="EUR")
    assert untouched.status_code == 200
    assert 'data-testid="unit-corrected"' not in untouched.text and "automatic" in untouched.text
    assert "extracted unit <strong>EUR</strong>" in untouched.text

    corrected = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.epc_contract", unit_0="kEUR",
                         keep_1="on", field_1="opex.lines.security", unit_1="kEUR/yr")
    assert corrected.status_code == 200
    page = corrected.text
    assert page.count('data-testid="unit-corrected"') == 1 and "corrected by you" in page
    assert "user reviewed" in page and "SOURCE_UNIT" not in page            # human wording, not codes
    assert "Suggested field" in page and "opex.lines.insurance" in page     # row 1 was remapped by the user
    result = _apply(env, project, _approved_ticket(corrected))
    assert result.status_code == 200 and "Import Apply result" in result.text
    assert result.text.count('data-testid="unit-corrected"') == 1 and 'data-testid="mapping-origin"' in result.text
    assert "from EUR to kEUR" in result.text and "extracted unit <strong>EUR</strong>" in result.text
    pis = ProjectInputSet.from_snapshot(_ws(project).draft_snapshot, workbook=WORKBOOK)
    assert float(pis.get("capex.C.epc_contract")) == pytest.approx(120000)      # exactly what the user approved
    assert tuple(h.history_id for h in get_run_history(OWNER, project.project_id)) == history   # no Run yet


def test_tampered_ticket_stale_composite_and_all_or_nothing_still_hold(env):
    project = env.create("solar")
    _, ticket = _preview(env, project, CSV)
    confirm = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.epc_contract", unit_0="EUR")
    approved = _approved_ticket(confirm)
    before = _evidence(project)
    tampered = _apply(env, project, approved[:-4] + "AAAA")
    assert tampered.status_code == 422 and "Import Apply result" not in tampered.text
    assert _evidence(project) == before
    save(env, project, "9", field="debt.senior.tenor_years")                 # a concurrent edit moves the composite CAS
    moved = _evidence(project)
    stale = _apply(env, project, approved)
    assert stale.status_code in (409, 422) and "Import Apply result" not in stale.text
    assert _evidence(project) == moved                                        # no partial Apply
    bad = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.epc_contract", unit_0="EUR",
                   keep_1="on", field_1="opex.lines.insurance", unit_1="kEUR/yr", manual_1="not-a-number")
    assert bad.status_code == 422 and _evidence(project) == moved

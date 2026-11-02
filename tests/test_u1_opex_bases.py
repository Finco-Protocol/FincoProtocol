"""PR-U1: the six OPEX group base amounts are described read-only (field id, saved value, whether they can change the Run); nothing is written."""
from __future__ import annotations

import pytest

from app.cost_line_ledger.opex_bases import OPEX_BASE_FIELD_BY_GROUP, opex_bases
from tests.test_model_react_wf2_projections_v1 import env, costlines  # noqa: F401  (shared real-app fixture)

SIX = {"B.04": "opex.lines.cleaning_materials", "B.05": "opex.lines.security", "B.08": "opex.lines.power_expenses",
       "B.10": "opex.lines.audit_accounting_legal", "B.11": "opex.lines.bank_fees", "B.12": "opex.lines.environmental_social"}


def test_exactly_the_six_registry_fields_in_group_order():
    assert OPEX_BASE_FIELD_BY_GROUP == SIX and list(SIX) == list(OPEX_BASE_FIELD_BY_GROUP)
    from app.workbook.registry import WORKBOOK
    for field_id in SIX.values():
        spec = WORKBOOK.field(field_id)
        assert spec.editable and spec.unit == "kEUR/yr"


def test_values_are_plain_decimal_text_and_authority_notes_make_a_base_read_only():
    values = {"opex.lines.security": 20.5, "opex.lines.bank_fees": "7", "opex.lines.power_expenses": None, "opex.lines.cleaning_materials": "abc"}
    out = {b["group"]: b for b in opex_bases(values.get, {"B.11": "Sum of line items — edit on the OPEX sheet"}, protected=False)}
    assert out["B.05"]["value"] == "20.5" and out["B.05"]["editable"] is True and out["B.05"]["note"] is None
    assert out["B.08"]["value"] == "" and out["B.04"]["value"] == ""                                  # absent / not a number: blank, never 0
    assert out["B.11"]["editable"] is False and "line items" in out["B.11"]["note"]                  # the Run does not take this scalar
    locked = opex_bases(values.get, {}, protected=True)
    assert all(b["editable"] is False and b["note"] == "Read-only project" for b in locked)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_route_lists_the_six_bases_only_on_the_opex_sheet_and_changes_nothing(env, kind):
    record = env.create(kind)
    before = costlines(env, record, "opex")
    assert [b["group"] for b in before["projection"]["bases"]] == list(SIX)
    assert all(b["editable"] is True for b in before["projection"]["bases"])
    assert "bases" not in costlines(env, record, "capex")["projection"]
    after = costlines(env, record, "opex")
    assert after["save"]["content_hash"] == before["save"]["content_hash"] and after["lines"] == before["lines"]      # a read, nothing else


def test_data_center_power_expenses_base_is_not_offered_as_editable():
    from app.v2.opex_authority import opex_group_authority_notes

    notes = opex_group_authority_notes("any-project", "generic_data_center_reference")
    out = {b["group"]: b for b in opex_bases(lambda f: None, notes, protected=False)}
    assert out["B.08"]["editable"] is False and "technology drivers" in out["B.08"]["note"]

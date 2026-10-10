"""Workflow C — deterministic evidence, unit and signed review contract.

Only synthetic input data. No external AI, financial engine, or real customer
file. XLSX is created entirely in-memory for reproducible test evidence.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime

import pytest
from openpyxl import Workbook

from app.model_import.intake import IntakeError, extract_proposals, normalize_value
from app.model_import.review import (
    ImportReviewError, resolve_review, seal_approved, seal_preview,
    unseal_approved, unseal_preview,
)
from app.workbook.registry import WORKBOOK

SOLAR = {"project_type": "Solar", "template_source": "generic_solar_reference"}


def _csv(lines):
    return extract_proposals(lines.encode("utf-8"), "synthetic.csv", **SOLAR)


def test_solar_csv_exact_mapping_mixed_eur_keur_and_percent():
    result = _csv(
        "Assumption,Value,Unit\n"
        "capex.C.epc_contract,1200000,EUR\n"
        "revenue.ppa.index,0.025,fraction\n"
        "project_setup.technical.cod_date,2029-05-15,date\n"
    )
    assert result["detected"] == 3
    rows = result["proposals"]
    assert rows[0]["normalized_value"] == "1200"
    assert rows[1]["normalized_value"] == "2.500"
    assert rows[2]["normalized_value"] == "2029-05-15"
    assert all(row["mapping_method"] == "exact_field_id" for row in rows)
    assert all(row["status"] == "ready" for row in rows)
    assert rows[0]["source_cell"] == "B2"


def test_opex_yearly_eur_to_keur_strict_conversion():
    assert normalize_value("opex.lines.technical_management", "120000", "EUR/yr") == "120"
    assert normalize_value("opex.lines.technical_management", "120", "kEUR/yr") == "120"


def test_percent_scale_requires_explicit_authority():
    with pytest.raises(IntakeError, match="IMPORT_PERCENT_SCALE_AMBIGUOUS"):
        normalize_value("revenue.ppa.index", "0.025", None)
    with pytest.raises(IntakeError, match="IMPORT_PERCENT_SCALE_CONFLICT"):
        normalize_value("revenue.ppa.index", "2.5%", "fraction")
    assert normalize_value("revenue.ppa.index", "2.5%", "") == "2.5"


def test_duplicate_target_cannot_be_silently_applied():
    rows = _csv(
        "Assumption,Value,Unit\n"
        "revenue.ppa.index,2,%\n"
        "revenue.ppa.index,3,%\n"
    )["proposals"]
    assert len(rows) == 2
    assert all(r["status"] == "needs_review" for r in rows)
    assert all(r["reason"] == "IMPORT_DUPLICATE_TARGET_REQUIRES_REVIEW" for r in rows)


def test_csv_formula_not_authoritative_even_with_cached_like_text():
    row = _csv("Assumption,Value,Unit\nrevenue.ppa.index,=SUM(2+2),%\n")["proposals"][0]
    assert row["status"] == "invalid"
    assert row["reason"] == "IMPORT_FORMULA_NOT_AUTHORITATIVE"


def test_wind_multisheet_xlsx_date_and_percent_format():
    book = Workbook()
    first = book.active
    first.title = "Project Inputs"
    first.append(["Assumption", "Value", "Unit"])
    first.append(["project_setup.technical.cod_date", datetime(2029, 7, 1), "date"])
    second = book.create_sheet("Financial Drivers")
    second.append(["Field", "Value", "Unit"])
    second.append(["revenue.ppa.index", 0.03, ""])
    second["B2"].number_format = "0.00%"
    data = io.BytesIO()
    book.save(data)
    result = extract_proposals(data.getvalue(), "wind_synthetic.xlsx",
                               project_type="Wind", template_source="generic_wind_reference")
    assert result["source_sheets"] == 2
    assert result["detected"] == 2
    assert result["proposals"][0]["normalized_value"] == "2029-07-01"
    assert result["proposals"][1]["normalized_value"] == "3.00"
    assert result["proposals"][1]["status"] == "ready"


def test_untrusted_xlsx_external_links_rejected_before_openpyxl():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("[Content_Types].xml", "synthetic")
        z.writestr("xl/workbook.xml", "synthetic")
        z.writestr("xl/externalLinks/externalLink1.xml", "no network")
    with pytest.raises(IntakeError, match="IMPORT_XLSX_ACTIVE_OR_EXTERNAL_CONTENT"):
        extract_proposals(data.getvalue(), "synthetic.xlsx", **SOLAR)


@pytest.mark.parametrize("name,data", [
    ("sample.xlsm", b"some-data"),
    ("sample.xls", b"some-data"),
    ("sample.csv", b""),
    ("sample.csv", b"x" * (2 * 1024 * 1024 + 1)),
])
def test_unsupported_or_oversized_file_rejected(name, data):
    with pytest.raises(IntakeError):
        extract_proposals(data, name, **SOLAR)


def _ticket(rows):
    return seal_preview(
        owner="synthetic-u", project_id="synthetic-project",
        scenario_id=None, content_hash="a" * 64, workbook_version=WORKBOOK.version,
        digest="b" * 64, proposals=rows,
    )


def test_signed_review_approved_only_and_cannot_change_owner():
    proposals = _csv(
        "Assumption,Value,Unit\n"
        "revenue.ppa.index,0.025,fraction\n"
        "project_setup.technical.horizon_years,28,years\n"
    )["proposals"]
    ticket = _ticket(proposals)
    body = unseal_preview(ticket, owner="synthetic-u", project_id="synthetic-project")
    assert len(body["rows"]) == 2
    with pytest.raises(ImportReviewError, match="IMPORT_REVIEW_OWNER_MISMATCH"):
        unseal_preview(ticket, owner="foreign", project_id="synthetic-project")
    preview, approved = resolve_review(
        ticket=ticket, owner="synthetic-u", project_id="synthetic-project",
        selections={"keep_0": "on", "field_0": "revenue.ppa.index", "unit_0": "fraction"},
        **SOLAR,
    )
    assert len(approved) == 1
    assert approved[0]["value"] == "2.500"
    approved_ticket = seal_approved(preview, approved)
    signed = unseal_approved(approved_ticket, owner="synthetic-u", project_id="synthetic-project")
    assert len(signed["approved"]) == 1
    assert signed["source_count"] == 2


def test_signed_review_disallows_duplicate_approved_targets():
    rows = _csv(
        "Assumption,Value,Unit\n"
        "revenue.ppa.index,0.02,fraction\n"
        "revenue.ppa.index,0.03,fraction\n"
    )["proposals"]
    with pytest.raises(ImportReviewError, match="IMPORT_DUPLICATE_TARGET"):
        resolve_review(
            ticket=_ticket(rows), owner="synthetic-u", project_id="synthetic-project",
            selections={
                "keep_0": "on", "field_0": "revenue.ppa.index", "unit_0": "fraction",
                "keep_1": "on", "field_1": "revenue.ppa.index", "unit_1": "fraction",
            }, **SOLAR,
        )



def test_currency_missing_unit_remains_unresolved():
    with pytest.raises(IntakeError, match="IMPORT_CURRENCY_UNIT_REQUIRED"):
        normalize_value("capex.C.epc_contract", "120000", "")
    rows = _csv("Assumption,Value,Unit\ncapex.C.epc_contract,120000,\n")["proposals"]
    assert rows[0]["status"] == "invalid"
    assert rows[0]["reason"] == "IMPORT_CURRENCY_UNIT_REQUIRED"


def test_incompatible_numeric_units_fail_closed():
    with pytest.raises(IntakeError, match="IMPORT_UNIT_INCOMPATIBLE"):
        normalize_value("project_setup.technical.horizon_years", "25", "MW")
    with pytest.raises(IntakeError, match="IMPORT_UNIT_INCOMPATIBLE"):
        normalize_value("revenue.ppa.base_tariff", "60", "years")

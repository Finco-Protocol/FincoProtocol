"""Synthetic fixtures for the tax reference registry tests.

Everything here is fictional (ZZ/ZZ1/ZZ2 pseudo-countries, invented amounts).
No private dataset content appears in committed tests; the real T01-B/T01-C
corpus is exercised only via the environment-gated test in
test_private_dataset.py.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

HEADER = [
    "rule_id", "jurisdiction_code", "subnational_scope", "industry_scope",
    "entity_scope", "tax_category", "subrule", "asset_class",
    "recipient_country", "income_type", "value", "value_unit",
    "value_currency", "threshold_min", "threshold_max", "condition_logic",
    "formula_or_method", "law_effective_from", "law_effective_to",
    "law_status", "primary_legal_title", "primary_section", "primary_url",
    "professional_source_url", "professional_last_reviewed", "accessed_at",
    "source_status", "review_due", "confidence", "advisor_required",
    "finco_current_behavior", "reference_workbook_behavior", "parity_gap",
    "implementation_dependency", "evidence_id",
]


def base_row(**overrides) -> dict:
    row = {key: "" for key in HEADER}
    row.update(
        {
            "rule_id": "ZZ-CIT-001",
            "jurisdiction_code": "ZZ",
            "tax_category": "CIT",
            "subrule": "standard rate",
            "value": "21",
            "value_unit": "pct",
            "law_effective_from": "2024-01-01",
            "law_status": "IN_FORCE",
            "professional_source_url": "https://example.test/zz-cit",
            "accessed_at": "2026-11-07",
            "source_status": "SECONDARY_ONLY",
            "confidence": "MEDIUM",
            "advisor_required": "true",
            "evidence_id": "EV-SYNTH-ZZ-CIT",
        }
    )
    row.update(overrides)
    return row


def rows_to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


@pytest.fixture()
def zz_single(tmp_path: Path) -> Path:
    path = tmp_path / "zz_single.csv"
    path.write_text(rows_to_csv([base_row()]), encoding="utf-8")
    return path


@pytest.fixture()
def zz_pair(tmp_path: Path) -> Path:
    """Two versions of the same synthetic corpus for compare() testing."""
    old = tmp_path / "zz_old.csv"
    new = tmp_path / "zz_new.csv"
    old.write_text(
        rows_to_csv(
            [
                base_row(),
                base_row(
                    rule_id="ZZ-NOL-001",
                    tax_category="NOL",
                    subrule="carryforward",
                    value="5",
                    value_unit="years",
                    source_status="SECONDARY_ONLY",
                ),
            ]
        ),
        encoding="utf-8",
    )
    new.write_text(
        rows_to_csv(
            [
                # changed: rate value + window end + verification upgrade
                base_row(value="22", law_effective_to="2027-12-31",
                         source_status="PRIMARY_CONFIRMED",
                         primary_url="https://example.test/zz-law"),
                # unchanged NOL row
                base_row(
                    rule_id="ZZ-NOL-001",
                    tax_category="NOL",
                    subrule="carryforward",
                    value="5",
                    value_unit="years",
                    source_status="SECONDARY_ONLY",
                ),
                # added dated second window (disjoint)
                base_row(
                    rule_id="ZZ-CIT-002",
                    subrule="standard rate",
                    value="20",
                    law_effective_from="2028-01-01",
                    law_effective_to="2029-12-31",
                ),
            ]
        ),
        encoding="utf-8",
    )
    return old, new

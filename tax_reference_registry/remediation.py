"""T01-E remediation-report generator: deterministic, offline, stdlib-only.

Produces a per-row remediation report from any 35-column CSV that the
standard loader can read. Each row gets: admission status, rejection reason,
remediation disposition candidate, and a stable evidence reference. The report
is advisory only — it never mutates the source dataset, never promotes
verification, and never activates a profile.

Public API:
  generate_remediation_report(csv_path, *, private_markers=()) -> dict
"""
from __future__ import annotations

import dataclasses
from typing import Any

from tax_reference_registry.loader import LoadResult, RowError, load_records


@dataclasses.dataclass(frozen=True)
class RemediationRow:
    rule_id: str
    jurisdiction_code: str
    tax_category: str
    subrule: str
    admission: str  # "accepted" | "rejected"
    rejection_reason: str  # "" when accepted
    disposition: str  # advisory: "OK" | "NEEDS_PRIMARY_URL" | "NEEDS_STRUCTURED_VALUE" | ...
    evidence_id: str


_DISPOSITION_BY_REASON = {
    "FALSE_VERIFIED_STATUS": "NEEDS_PRIMARY_URL",
    "VALUE_UNPARSED": "NEEDS_STRUCTURED_VALUE",
    "MISSING_ESSENTIAL_PROVENANCE": "NEEDS_CITATION_OR_EVIDENCE_ID",
    "DUPLICATE_RULE_ID": "DEDUPLICATE",
    "OVERLAPPING_WINDOWS": "RESOLVE_WINDOW",
    "CONTRADICTORY_WINDOW": "RESOLVE_WINDOW",
    "UNIT_UNPARSED": "NORMALIZE_UNIT",
    "UNSUPPORTED_CURRENCY": "MAP_CURRENCY",
    "UNSUPPORTED_ASSET_CLASS": "MAP_ASSET_CLASS",
    "UNSUPPORTED_TAX_CATEGORY": "MAP_CATEGORY",
    "UNSUPPORTED_LAW_STATUS": "MAP_LAW_STATUS",
    "UNSUPPORTED_SOURCE_STATUS": "MAP_SOURCE_STATUS",
    "UNSUPPORTED_CONFIDENCE": "MAP_CONFIDENCE",
    "UNPARSABLE_BOOL": "PARSE_BOOL",
    "MISSING_RULE_ID": "SUPPLY_RULE_ID",
    "MISSING_JURISDICTION": "SUPPLY_JURISDICTION",
    "BAD_JURISDICTION_CODE": "FIX_CODE",
    "THRESHOLD_UNPARSED": "PARSE_THRESHOLD",
    "PRIVATE_METADATA_SUSPECTED": "REMOVE_PRIVATE_MARKER",
}


def generate_remediation_report(
    csv_path: str,
    *,
    private_markers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Produce a sorted, deterministic remediation report from a 35-column CSV."""
    result: LoadResult = load_records(
        csv_path, source_path=csv_path, private_markers=private_markers
    )
    error_index: dict[int, RowError] = {}
    for err in result.errors:
        error_index[err.row_number] = err

    loaded_ids = {r.rule_id for r in result.records}
    rows: list[RemediationRow] = []
    for rec in result.records:
        rows.append(
            RemediationRow(
                rule_id=rec.rule_id,
                jurisdiction_code=rec.jurisdiction_code,
                tax_category=rec.tax_category.value,
                subrule=rec.subrule or "",
                admission="accepted",
                rejection_reason="",
                disposition="OK",
                evidence_id=rec.evidence_id or "",
            )
        )
    for err in result.errors:
        disposition = _DISPOSITION_BY_REASON.get(err.reason, "MANUAL_REVIEW")
        rows.append(
            RemediationRow(
                rule_id=err.rule_id,
                jurisdiction_code=err.jurisdiction_code,
                tax_category="",
                subrule="",
                admission="rejected",
                rejection_reason=err.reason,
                disposition=disposition,
                evidence_id="",
            )
        )
    rows.sort(key=lambda r: (r.jurisdiction_code, r.rule_id, r.admission))

    by_reason: dict[str, int] = {}
    for err in result.errors:
        by_reason[err.reason] = by_reason.get(err.reason, 0) + 1
    by_disposition: dict[str, int] = {}
    for row in rows:
        if row.admission == "rejected":
            by_disposition[row.disposition] = by_disposition.get(row.disposition, 0) + 1

    return {
        "tag": "T01E_REMEDIATION_REPORT_V1",
        "source": csv_path,
        "rows_read": result.rows_read,
        "accepted": result.valid,
        "rejected": result.invalid,
        "countries": sorted(result.countries()),
        "rejection_reasons": dict(sorted(by_reason.items())),
        "dispositions": dict(sorted(by_disposition.items())),
        "warnings_count": len(result.warnings),
        "rows": [dataclasses.asdict(r) for r in rows],
    }

"""Deterministic 35-column CSV importer with per-row error reporting.

Design rules (T01-D contract):
- Inspect the actual header; do not assume fields exist. Unknown columns are
  rejected by default (they are the vector for accidental client metadata).
- Duplicate rule IDs, overlapping contradictory effective windows for the same
  scope key, unparsed units/currencies, false verified statuses, unsupported
  asset classes and missing essential provenance are REJECTED per row.
- Ambiguity is never converted into a default tax value: text rates fail as
  VALUE_UNPARSED, unparsed dates are preserved verbatim with a warning.
- Private-marker scan: caller-supplied markers (never embedded identities)
  reject rows whose text fields contain them.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from tax_reference_registry.enums import (
    AssetClass,
    CONFIDENCE_VALUES,
    COUNTRY_CODE_EXCEPTIONS,
    LawStatus,
    REQUIRED_COLUMNS,
    SOURCE_STATUS_CANONICAL,
    TaxCategory,
    VerificationStatus,
)
from tax_reference_registry.records import (
    EffectiveWindow,
    ParsedValue,
    TaxRuleRecord,
    parse_date,
    parse_value,
)

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Deterministic unit grammar: descriptive token(s), no delimiter noise.
#: Full closed-vocabulary rejection would reject the whole real corpus; the
#: registry is reference-only and performs no arithmetic on units, so units are
#: syntax-validated and classified, never evaluated.
_UNIT_ALLOWED = re.compile(r"^[A-Za-z0-9 %/._()‰€+-]{1,120}$")


@dataclasses.dataclass(frozen=True)
class RowError:
    rule_id: str
    jurisdiction_code: str
    row_number: int
    reason: str
    detail: str


@dataclasses.dataclass(frozen=True)
class RowWarning:
    rule_id: str
    jurisdiction_code: str
    row_number: int
    reason: str
    detail: str


@dataclasses.dataclass
class LoadResult:
    records: list[TaxRuleRecord]
    errors: list[RowError]
    warnings: list[RowWarning]
    rows_read: int = 0
    source_path: str = ""

    @property
    def valid(self) -> int:
        return len(self.records)

    @property
    def invalid(self) -> int:
        return len(self.errors)

    def countries(self) -> set[str]:
        return {r.jurisdiction_code for r in self.records}

    def report(self) -> dict:
        rows = []
        err_by_id = {}
        for e in self.errors:
            err_by_id.setdefault((e.rule_id, e.row_number), []).append(e.reason)
        warn_by_id = {}
        for w in self.warnings:
            warn_by_id.setdefault((w.rule_id, w.row_number), []).append(w.reason)
        seen = set()
        for rec in self.records:
            key = (rec.rule_id, -1)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "rule_id": rec.rule_id,
                    "jurisdiction_code": rec.jurisdiction_code,
                    "status": "loaded",
                    "verification": rec.verification.value,
                    "reason_ids": warn_by_id.get(key, []),
                }
            )
        for e in self.errors:
            key = (e.rule_id, e.row_number)
            rows.append(
                {
                    "rule_id": e.rule_id,
                    "jurisdiction_code": e.jurisdiction_code,
                    "status": "rejected",
                    "verification": None,
                    "reason_ids": err_by_id.get(key, [e.reason]),
                }
            )
        rows.sort(key=lambda r: (r["jurisdiction_code"], r["rule_id"], r["status"]))
        unverified = sum(
            1 for r in self.records if r.verification is not VerificationStatus.PRIMARY_CONFIRMED
        )
        conflict = sum(
            1 for r in self.records if r.verification is VerificationStatus.CONFLICT
        )
        return {
            "valid": self.valid,
            "invalid": self.invalid,
            "unverified": unverified,
            "conflict": conflict,
            "countries": len(self.countries()),
            "rules": len(self.records),
            "rows_read": self.rows_read,
            "source_path": self.source_path,
            "warnings_count": len(self.warnings),
            "rows": rows,
        }


def _clean(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    return text or None


def _decimal_or_none(raw: str | None) -> Decimal | None:
    text = _clean(raw)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def load_records(
    source,
    *,
    source_path: str = "",
    private_markers: Sequence[str] = (),
    allow_extra_columns: bool = False,
) -> LoadResult:
    """Load reference records from a CSV path or text/file object.

    Raises RecordFormatError for structurally incompatible input (not CSV,
    wrong delimiter, empty file, missing required columns, unknown columns
    when allow_extra_columns=False).
    """
    errors: list[RowError] = []
    warnings: list[RowWarning] = []
    records: list[TaxRuleRecord] = []

    if hasattr(source, "read"):
        text = source.read()
    else:
        with open(source, "r", encoding="utf-8-sig", newline="") as handle:
            text = handle.read()
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig", errors="replace")
    if not text.strip():
        raise RecordFormatError("EMPTY_FILE: no content to parse.")
    if text.lstrip().startswith(("{", "[")):
        raise RecordFormatError("NOT_CSV: content looks like JSON, not CSV.")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise RecordFormatError("NO_HEADER: CSV header row missing.")
    header = [h.strip() for h in reader.fieldnames]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise RecordFormatError(
            "MISSING_COLUMNS: required columns absent: " + ", ".join(missing)
        )
    extra = [c for c in header if c not in REQUIRED_COLUMNS]
    if extra and not allow_extra_columns:
        raise RecordFormatError(
            "UNKNOWN_COLUMNS: unexpected columns present (foreign-metadata "
            "vector): " + ", ".join(extra)
        )
    reader.fieldnames = header
    markers = [m for m in private_markers if m]
    rows_read = 0
    seen_rule_ids: set[str] = set()
    scope_windows: dict[tuple[str, str, str, str], list[tuple]] = {}
    for row_number, raw_row in enumerate(reader, start=2):
        rows_read += 1
        row = {
            k: (v if isinstance(v, str) else ("" if v is None else str(v)))
            for k, v in raw_row.items()
            if k is not None
        }
        _ingest_row(
            row, row_number, markers, records, errors, warnings,
            seen_rule_ids, scope_windows,
        )
    return LoadResult(
        records=records,
        errors=errors,
        warnings=warnings,
        rows_read=rows_read,
        source_path=source_path,
    )


class RecordFormatError(ValueError):
    pass


def _ingest_row(
    row, row_number, markers, records, errors, warnings, seen_rule_ids, scope_windows
) -> None:
    rule_id = _clean(row.get("rule_id")) or ""
    jurisdiction = _clean(row.get("jurisdiction_code")) or ""

    def err(reason: str, detail: str) -> None:
        errors.append(
            RowError(
                rule_id=rule_id or f"<row {row_number}>",
                jurisdiction_code=jurisdiction or "<none>",
                row_number=row_number,
                reason=reason,
                detail=detail,
            )
        )

    def warn(reason: str, detail: str) -> None:
        warnings.append(
            RowWarning(
                rule_id=rule_id or f"<row {row_number}>",
                jurisdiction_code=jurisdiction or "<none>",
                row_number=row_number,
                reason=reason,
                detail=detail,
            )
        )

    if not rule_id:
        err("MISSING_RULE_ID", "rule_id empty")
        return
    if rule_id in seen_rule_ids:
        err("DUPLICATE_RULE_ID", f"{rule_id}: appears more than once in input")
        return
    seen_rule_ids.add(rule_id)
    if not jurisdiction:
        err("MISSING_JURISDICTION", f"{rule_id}: jurisdiction_code empty")
        return
    upper_jur = jurisdiction.upper()
    if len(upper_jur) != 2 or not upper_jur.isalpha():
        err("BAD_JURISDICTION_CODE", f"{rule_id}: {jurisdiction!r} is not a 2-letter code")
        return
    if upper_jur not in COUNTRY_CODE_EXCEPTIONS and not upper_jur.isascii():
        err("BAD_JURISDICTION_CODE", f"{rule_id}: non-ASCII code {jurisdiction!r}")
        jurisdiction = upper_jur
    else:
        jurisdiction = upper_jur

    # Private-marker scan (caller-supplied markers only; none embedded here).
    for marker in markers:
        for col, text in row.items():
            if marker and marker.lower() in (text or "").lower():
                err(
                    "PRIVATE_METADATA_SUSPECTED",
                    f"{rule_id}: marker {marker!r} found in column {col}",
                )
                return

    try:
        tax_category = TaxCategory(_clean(row.get("tax_category")) or "")
    except ValueError:
        err(
            "UNSUPPORTED_TAX_CATEGORY",
            f"{rule_id}: {row.get('tax_category')!r}",
        )
        return

    asset_raw = _clean(row.get("asset_class"))
    asset_class = None
    if asset_raw:
        try:
            asset_class = AssetClass(asset_raw)
        except ValueError:
            err("UNSUPPORTED_ASSET_CLASS", f"{rule_id}: {asset_raw!r}")
            return

    # Value: exact numeric (single or tier set); text rates rejected.
    value = parse_value(row.get("value"))
    if row.get("value") and row.get("value").strip() and value is None:
        err(
            "VALUE_UNPARSED",
            f"{rule_id}: non-numeric value {row.get('value')!r} (ambiguity is "
            "never converted into a default)",
        )
        return

    unit = _clean(row.get("value_unit"))
    if unit is not None and not _UNIT_ALLOWED.match(unit):
        err("UNIT_UNPARSED", f"{rule_id}: {unit!r}")
        return
    threshold_min = _decimal_or_none(row.get("threshold_min"))
    threshold_max = _decimal_or_none(row.get("threshold_max"))
    if row.get("threshold_min") and row.get("threshold_min").strip() and threshold_min is None:
        err("THRESHOLD_UNPARSED", f"{rule_id}: {row.get('threshold_min')!r}")
        return
    if row.get("threshold_max") and row.get("threshold_max").strip() and threshold_max is None:
        err("THRESHOLD_UNPARSED", f"{rule_id}: {row.get('threshold_max')!r}")
        return

    currency_raw = _clean(row.get("value_currency"))
    value_currency = None
    if currency_raw:
        from tax_reference_registry.currency import KnownCurrency

        try:
            value_currency = KnownCurrency(currency_raw.upper()).value
        except ValueError:
            err("UNSUPPORTED_CURRENCY", f"{rule_id}: {currency_raw!r}")
            return

    # Dates: ISO accepted; other formats preserved with a warning.
    from_dt, from_unparsed = parse_date(row.get("law_effective_from"))
    if from_unparsed:
        warn("DATE_UNPARSED", f"{rule_id}: law_effective_from {row.get('law_effective_from')!r}")
    to_dt, to_unparsed = parse_date(row.get("law_effective_to"))
    if to_unparsed:
        warn("DATE_UNPARSED", f"{rule_id}: law_effective_to {row.get('law_effective_to')!r}")
    if (
        from_dt is not None
        and to_dt is not None
        and from_dt > to_dt
        and not (from_unparsed or to_unparsed)
    ):
        err(
            "CONTRADICTORY_WINDOW",
            f"{rule_id}: effective_from {from_dt} after effective_to {to_dt}",
        )
        return
    window = EffectiveWindow(
        effective_from=from_dt,
        effective_to=to_dt,
        effective_from_raw=row.get("law_effective_from") or "",
        effective_to_raw=row.get("law_effective_to") or "",
        from_unparsed=from_unparsed,
        to_unparsed=to_unparsed,
    )

    law_raw = (_clean(row.get("law_status")) or "UNKNOWN").upper()
    if law_raw not in LawStatus.__members__:
        err("UNSUPPORTED_LAW_STATUS", f"{rule_id}: {law_raw!r}")
        return
    law_status = LawStatus[law_raw]

    source_raw = (_clean(row.get("source_status")) or "").upper()
    if source_raw not in SOURCE_STATUS_CANONICAL:
        err("UNSUPPORTED_SOURCE_STATUS", f"{rule_id}: {source_raw!r}")
        return
    verification, law_override = SOURCE_STATUS_CANONICAL[source_raw]
    if law_override is not None and law_status is LawStatus.IN_FORCE:
        # e.g. PROPOSED_NOT_LAW harvest rows: canonical law status becomes DRAFT.
        law_status = law_override

    # False-verified guard: PRIMARY_CONFIRMED requires a primary citation URL.
    primary_url = _clean(row.get("primary_url"))
    if verification is VerificationStatus.PRIMARY_CONFIRMED and not primary_url:
        err(
            "FALSE_VERIFIED_STATUS",
            f"{rule_id}: PRIMARY_CONFIRMED without primary_url citation",
        )
        return

    accessed_dt, accessed_unparsed = parse_date(row.get("accessed_at"))
    if accessed_dt is None:
        err("MISSING_ESSENTIAL_PROVENANCE", f"{rule_id}: accessed_at missing/unparsable")
        return
    professional_url = _clean(row.get("professional_source_url"))
    evidence_id = _clean(row.get("evidence_id"))
    if not primary_url and not professional_url and not evidence_id:
        err(
            "MISSING_ESSENTIAL_PROVENANCE",
            f"{rule_id}: no primary_url, professional_source_url or evidence_id "
            "pointer present",
        )
        return

    confidence = (_clean(row.get("confidence")) or "").upper()
    if confidence and confidence not in CONFIDENCE_VALUES:
        err("UNSUPPORTED_CONFIDENCE", f"{rule_id}: {confidence!r}")
        return

    advisor_raw = (_clean(row.get("advisor_required")) or "").strip().lower()
    if advisor_raw not in {"true", "false", "1", "0", "yes", "no"}:
        err("UNPARSABLE_BOOL", f"{rule_id}: advisor_required {row.get('advisor_required')!r}")
        return
    advisor_required = advisor_raw in {"true", "1", "yes"}

    review_dt, review_unparsed = parse_date(row.get("review_due"))
    if review_unparsed:
        warn("DATE_UNPARSED", f"{rule_id}: review_due {row.get('review_due')!r}")
    last_reviewed_dt, last_unparsed = parse_date(row.get("professional_last_reviewed"))
    if last_unparsed:
        warn(
            "DATE_UNPARSED",
            f"{rule_id}: professional_last_reviewed "
            f"{row.get('professional_last_reviewed')!r}",
        )

    records.append(
        TaxRuleRecord(
            rule_id=rule_id,
            jurisdiction_code=jurisdiction,
            subnational_scope=_clean(row.get("subnational_scope")),
            industry_scope=_clean(row.get("industry_scope")),
            entity_scope=_clean(row.get("entity_scope")),
            tax_category=tax_category,
            subrule=_clean(row.get("subrule")),
            asset_class=asset_class,
            recipient_country=_clean(row.get("recipient_country")),
            income_type=_clean(row.get("income_type")),
            value=value if value is not None else ParsedValue(),
            value_unit=unit,
            value_currency=value_currency,
            threshold_min=threshold_min,
            threshold_max=threshold_max,
            condition_logic=_clean(row.get("condition_logic")),
            formula_or_method=_clean(row.get("formula_or_method")),
            window=window,
            law_status=law_status,
            primary_legal_title=_clean(row.get("primary_legal_title")),
            primary_section=_clean(row.get("primary_section")),
            primary_url=primary_url,
            professional_source_url=professional_url,
            professional_last_reviewed=last_reviewed_dt,
            professional_last_reviewed_raw=row.get("professional_last_reviewed") or "",
            accessed_at=accessed_dt,
            source_status_raw=source_raw,
            verification=verification,
            review_due=review_dt,
            confidence=confidence or None,
            advisor_required=advisor_required,
            finco_current_behavior=_clean(row.get("finco_current_behavior")),
            reference_workbook_behavior=_clean(row.get("reference_workbook_behavior")),
            parity_gap=_clean(row.get("parity_gap")),
            implementation_dependency=_clean(row.get("implementation_dependency")),
            evidence_id=evidence_id,
        )
    )

    # Overlapping contradictory windows for the same scope key (loader-level,
    # per-row): only fully bounded windows participate.
    if window.effective_from is not None and window.effective_to is not None:
        scope_key = (
            jurisdiction,
            _clean(row.get("subnational_scope")) or "",
            tax_category.value,
            _clean(row.get("subrule")) or "",
        )
        for (other_from, other_to, other_id) in scope_windows.get(scope_key, []):
            if window.effective_from <= other_to and other_from <= window.effective_to:
                err(
                    "OVERLAPPING_WINDOWS",
                    f"{rule_id}: window {window.effective_from}..{window.effective_to} "
                    f"overlaps {other_id} ({other_from}..{other_to})",
                )
                return
        scope_windows.setdefault(scope_key, []).append(
            (window.effective_from, window.effective_to, rule_id)
        )

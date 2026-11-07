"""Registry store: dedupe, windows, compare, explain, export.

The registry is append/versioned only: ``compare`` never overwrites, never
deduces legal updates, and never merges records. Baseline preservation is the
caller's contract (19-country rows keep their rule_ids and content verbatim);
``compare`` exposes additions/changes/expiries so that preservation is
checkable, not assumed.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
from typing import Iterable, Sequence

from tax_reference_registry.enums import LawStatus, RateScheduleMode, TaxCategory
from tax_reference_registry.records import ParsedValue, TaxRuleRecord


class UnknownRuleError(KeyError):
    pass


class DuplicateRuleIdError(ValueError):
    pass


class OverlappingWindowError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class ExplainResult:
    rule_id: str
    jurisdiction_code: str
    subnational_scope: str | None
    tax_category: str
    subrule: str | None
    value: str
    value_unit: str | None
    value_currency: str | None
    threshold_min: str | None
    threshold_max: str | None
    window: str
    law_status: str
    verification: str
    source_status_raw: str
    is_verified: bool
    is_operative_on_asof: bool
    primary_citation: str | None
    primary_section: str | None
    professional_source: str | None
    professional_last_reviewed: str
    accessed_at: str
    evidence_id: str | None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _fmt_value(value: ParsedValue) -> str:
    if value.tiers:
        return "TIER_SET[" + " / ".join(str(t) for t in value.tiers) + "]"
    if value.single is not None:
        return str(value.single)
    return "<none>"


class TaxReferenceRegistry:
    """Immutable store built once from validated records."""

    def __init__(self, records: Sequence[TaxRuleRecord], *, as_of: _dt.date | None = None) -> None:
        by_id: dict[str, TaxRuleRecord] = {}
        for rec in records:
            if rec.rule_id in by_id:
                raise DuplicateRuleIdError(f"DUPLICATE_RULE_ID: {rec.rule_id}")
            by_id[rec.rule_id] = rec
        # Overlapping contradictory windows for the same scope key.
        scope_groups: dict[tuple, list[TaxRuleRecord]] = {}
        for rec in records:
            scope_groups.setdefault(rec.scope_key(), []).append(rec)
        for key, group in scope_groups.items():
            bounded = [
                r
                for r in group
                if r.window.effective_from is not None and r.window.effective_to is not None
            ]
            bounded.sort(key=lambda r: (r.window.effective_from, r.rule_id))
            for i in range(len(bounded) - 1):
                a, b = bounded[i], bounded[i + 1]
                if a.window.overlaps(b.window):
                    raise OverlappingWindowError(
                        f"OVERLAPPING_WINDOWS: {a.rule_id} and {b.rule_id} "
                        f"for scope key {key}"
                    )
        self._records = tuple(records)
        self._by_id = by_id
        self._as_of = as_of or _dt.date.today()

    @classmethod
    def from_records(cls, records: Iterable[TaxRuleRecord], **kw) -> "TaxReferenceRegistry":
        return cls(list(records), **kw)

    # ── queries ────────────────────────────────────────────────────────────
    @property
    def records(self) -> tuple[TaxRuleRecord, ...]:
        return self._records

    def countries(self) -> set[str]:
        return {r.jurisdiction_code for r in self._records}

    def rules_count(self) -> int:
        return len(self._records)

    def get(self, rule_id: str) -> TaxRuleRecord:
        try:
            return self._by_id[rule_id]
        except KeyError:
            raise UnknownRuleError(rule_id) from None

    def for_country(self, jurisdiction_code: str) -> tuple[TaxRuleRecord, ...]:
        code = jurisdiction_code.upper()
        return tuple(r for r in self._records if r.jurisdiction_code == code)

    def is_operative_on(self, rule_id: str, day: _dt.date | None = None) -> bool:
        rec = self.get(rule_id)
        return rec.is_operative_on(day or self._as_of)

    def rate_schedule_mode(self, rule_id: str) -> RateScheduleMode:
        """Classify a CIT record's schedule representation (FLAT/TIERED) from
        its own value. DATED_SERIES is detected only when multiple records for
        the same scope key carry disjoint bounded windows — classification
        only, never computation."""
        rec = self.get(rule_id)
        if rec.tax_category is not TaxCategory.CIT:
            return RateScheduleMode.UNKNOWN
        if rec.value.is_tiered:
            return RateScheduleMode.TIERED
        same_key = [
            r
            for r in self._records
            if r.scope_key() == rec.scope_key() and r.rule_id != rec.rule_id
        ]
        dated_peers = [
            r
            for r in same_key
            if r.window.effective_from is not None and not r.window.overlaps(rec.window)
        ]
        if rec.window.effective_from is not None and dated_peers:
            return RateScheduleMode.DATED_SERIES
        if rec.value.single is not None:
            return RateScheduleMode.FLAT
        return RateScheduleMode.UNKNOWN

    # ── explain ────────────────────────────────────────────────────────────
    def explain(self, jurisdiction_code: str, rule_id: str) -> ExplainResult:
        rec = self.get(rule_id)
        if rec.jurisdiction_code != jurisdiction_code.upper():
            raise UnknownRuleError(
                f"rule {rule_id} does not belong to {jurisdiction_code}"
            )
        return ExplainResult(
            rule_id=rec.rule_id,
            jurisdiction_code=rec.jurisdiction_code,
            subnational_scope=rec.subnational_scope,
            tax_category=rec.tax_category.value,
            subrule=rec.subrule,
            value=_fmt_value(rec.value),
            value_unit=rec.value_unit,
            value_currency=rec.value_currency,
            threshold_min=str(rec.threshold_min) if rec.threshold_min is not None else None,
            threshold_max=str(rec.threshold_max) if rec.threshold_max is not None else None,
            window=f"[{rec.window.effective_from_raw or 'open'} .. "
            f"{rec.window.effective_to_raw or 'open'}]",
            law_status=rec.law_status.value,
            verification=rec.verification.value,
            source_status_raw=rec.source_status_raw,
            is_verified=rec.is_verified,
            is_operative_on_asof=rec.is_operative_on(self._as_of),
            primary_citation=rec.primary_url,
            primary_section=rec.primary_section,
            professional_source=rec.professional_source_url,
            professional_last_reviewed=rec.professional_last_reviewed_raw,
            accessed_at=rec.accessed_at.isoformat(),
            evidence_id=rec.evidence_id,
        )

    # ── compare (version diff; no overwrites, no deduced updates) ─────────
    def compare(
        self,
        other: "TaxReferenceRegistry",
        *,
        reference_day: _dt.date | None = None,
    ) -> dict:
        day = reference_day or self._as_of
        # self = NEW registry, other = OLD registry (new_reg.compare(old_reg)).
        new_ids = {r.rule_id for r in self._records}
        old_ids = {r.rule_id for r in other._records}
        added = sorted(new_ids - old_ids)
        removed = sorted(old_ids - new_ids)
        changed = []
        verification_changes = []
        for rid in sorted(old_ids & new_ids):
            a, b = other._by_id[rid], self._by_id[rid]
            delta = a.compare_to(b)
            if delta["changed_fields"]:
                changed.append(delta)
            if a.verification is not b.verification:
                verification_changes.append(
                    {
                        "rule_id": rid,
                        "from": a.verification.value,
                        "to": b.verification.value,
                    }
                )
        expired = sorted(
            rid
            for rid in new_ids
            if self._by_id[rid].window.effective_to is not None
            and self._by_id[rid].window.effective_to < day
            and rid not in removed
        )
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "verification_changes": verification_changes,
            "expired_as_of": day.isoformat(),
            "expired": expired,
            "counts": {
                "old": len(old_ids),
                "new": len(new_ids),
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
            },
        }

    # ── export (whitelist only; NON_ACTIVATABLE_REFERENCE_ONLY) ───────────
    EXPORT_FIELDS = (
        "rule_id",
        "jurisdiction_code",
        "subnational_scope",
        "tax_category",
        "subrule",
        "value",
        "value_unit",
        "value_currency",
        "law_effective_from_raw",
        "law_effective_to_raw",
        "law_status",
        "verification",
        "is_verified",
        "source_status_raw",
        "evidence_id",
    )

    def export_candidates(self) -> dict:
        rows = []
        for rec in self._records:
            rows.append(
                {
                    "rule_id": rec.rule_id,
                    "jurisdiction_code": rec.jurisdiction_code,
                    "subnational_scope": rec.subnational_scope,
                    "tax_category": rec.tax_category.value,
                    "subrule": rec.subrule,
                    "value": _fmt_value(rec.value),
                    "value_unit": rec.value_unit,
                    "value_currency": rec.value_currency,
                    "law_effective_from_raw": rec.window.effective_from_raw,
                    "law_effective_to_raw": rec.window.effective_to_raw,
                    "law_status": rec.law_status.value,
                    "verification": rec.verification.value,
                    "is_verified": rec.is_verified,
                    "source_status_raw": rec.source_status_raw,
                    "evidence_id": rec.evidence_id,
                }
            )
        rows.sort(key=lambda r: (r["jurisdiction_code"], r["rule_id"]))
        return {
            "tag": "NON_ACTIVATABLE_REFERENCE_ONLY",
            "note": (
                "Reference summary only. Free-text and behavior columns are "
                "deliberately excluded; activation is not implemented and all "
                "country profiles remain CANDIDATE_NOT_ACTIVE."
            ),
            "countries": sorted(self.countries()),
            "rules": len(rows),
            "candidates": rows,
        }

"""Phase 6D.2 — Tax assumptions snapshot models.

Immutable read-only audit artifacts capturing template configuration
at a point in time. No active model wiring. No persistence.

CAVEAT: Values-only. No editable persistence. No workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


_AUDIT_NOTE = (
    "AUDIT-ONLY: This snapshot is a read-only governance artifact. "
    "It does not modify active model outputs or trigger any workflow."
)


@dataclass(frozen=True)
class TaxTemplateSnapshot:
    """Immutable snapshot of a single TaxTemplate.

    Captures template identity, CIT structure, depreciation rules,
    and WHT configuration for audit/review purposes.
    """

    template_name: str
    country_code: str
    tax_year: int
    cit_structure: str  # "None" | "Flat" | "Progressive"
    cit_tiers_summary: tuple[str, ...]  # e.g. ("10%", "15%") or ("18% flat",)
    loss_carryforward_years: int | None
    has_interest_limitation: bool
    has_wht_dividend: bool
    has_wht_interest: bool
    depreciation_rules_summary: tuple[str, ...]  # e.g. ("buildings: straight_line: 20yr", ...)
    metadata: tuple[tuple[str, str], ...]
    created_at: datetime
    snapshot_label: str | None = None
    audit_note: str = field(default=_AUDIT_NOTE)

    def __post_init__(self):
        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, 'metadata', tuple(self.metadata))
        if not isinstance(self.cit_tiers_summary, tuple):
            object.__setattr__(self, 'cit_tiers_summary', tuple(self.cit_tiers_summary))
        if not isinstance(self.depreciation_rules_summary, tuple):
            object.__setattr__(self, 'depreciation_rules_summary', tuple(self.depreciation_rules_summary))


@dataclass(frozen=True)
class TaxOverrideSnapshot:
    """Immutable snapshot of a single TaxTemplateOverride."""

    override_name: str
    field_path: str
    override_value: str | float | int | bool | None
    reason: str | None
    created_at: datetime
    audit_note: str = field(default=_AUDIT_NOTE)


@dataclass(frozen=True)
class ResolvedTaxConfigSnapshot:
    """Immutable snapshot of a single ResolvedTaxConfig.

    Captures the effective resolved template plus override details
    for governance review.
    """

    template_name: str
    country_code: str
    tax_year: int
    effective_cit_structure: str
    override_count: int
    overrides_summary: tuple[str, ...]  # e.g. ("withholding_tax_dividends → 10%", ...)
    resolved_metadata: tuple[tuple[str, str], ...]
    created_at: datetime
    snapshot_label: str | None = None
    audit_note: str = field(default=_AUDIT_NOTE)

    def __post_init__(self):
        if not isinstance(self.overrides_summary, tuple):
            object.__setattr__(self, 'overrides_summary', tuple(self.overrides_summary))
        if not isinstance(self.resolved_metadata, tuple):
            object.__setattr__(self, 'resolved_metadata', tuple(self.resolved_metadata))


@dataclass(frozen=True)
class TaxAssumptionSnapshot:
    """Top-level immutable snapshot grouping all tax assumption artifacts.

    Root artifact for Phase 6D.2 audit export. Encapsulates one or more
    template snapshots, override snapshots, and resolved config snapshots.

    Self-contained: only stores immutable snapshot dataclasses and tuples.
    No references to mutable or mutable-derived original objects.
    """

    template_snapshots: tuple[TaxTemplateSnapshot, ...]
    override_snapshots: tuple[TaxOverrideSnapshot, ...]
    resolved_config_snapshots: tuple[ResolvedTaxConfigSnapshot, ...]
    snapshot_label: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    audit_note: str = field(default=_AUDIT_NOTE)

    def __post_init__(self):
        if not isinstance(self.template_snapshots, tuple):
            object.__setattr__(self, 'template_snapshots', tuple(self.template_snapshots))
        if not isinstance(self.override_snapshots, tuple):
            object.__setattr__(self, 'override_snapshots', tuple(self.override_snapshots))
        if not isinstance(self.resolved_config_snapshots, tuple):
            object.__setattr__(self, 'resolved_config_snapshots', tuple(self.resolved_config_snapshots))

    @property
    def has_templates(self) -> bool:
        return len(self.template_snapshots) > 0

    @property
    def has_overrides(self) -> bool:
        return len(self.override_snapshots) > 0

    @property
    def has_resolved_configs(self) -> bool:
        return len(self.resolved_config_snapshots) > 0

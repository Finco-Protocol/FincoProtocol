"""Phase 6D.2 — Snapshot builders for tax assumption artifacts.

Pure functions — no mutation, no side effects, no active model wiring.

CAVEAT: Values-only. No editable persistence. No workflow.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from finco_core.tax.assumptions_snapshot import (
    TaxAssumptionSnapshot,
    TaxTemplateSnapshot,
    TaxOverrideSnapshot,
    ResolvedTaxConfigSnapshot,
)

if TYPE_CHECKING:
    from finco_core.tax.templates.inputs import (
        TaxTemplate,
        TaxTemplateOverride,
        ResolvedTaxConfig,
    )


_AUDIT_NOTE = (
    "AUDIT-ONLY: This snapshot is a read-only governance artifact. "
    "It does not modify active model outputs or trigger any workflow."
)


def build_tax_template_snapshot(
    template: TaxTemplate,
    snapshot_label: str | None = None,
) -> TaxTemplateSnapshot:
    """Build an immutable snapshot from a single TaxTemplate.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    template : TaxTemplate
        Source tax template (not mutated).
    snapshot_label : str | None, optional
        Optional human-readable label for this snapshot.

    Returns
    -------
    TaxTemplateSnapshot
        Immutable snapshot capturing template configuration.
        No references to the original TaxTemplate object.
    """
    n_tiers = len(template.cit_tiers)
    if n_tiers == 0:
        cit_structure = "None"
    elif n_tiers == 1:
        cit_structure = "Flat"
    else:
        cit_structure = "Progressive"

    cit_tiers_summary = tuple(
        f"{tier.tax_rate:.0%}"
        for tier in template.cit_tiers
    )

    depreciation_rules_summary = tuple(
        f"{rule.asset_category}: {rule.method}: "
        f"{int(rule.useful_life_years) if rule.useful_life_years else 'N/A'}yr"
        for rule in template.depreciation_rules
    )

    # Normalize metadata to tuple of tuples
    metadata = tuple(
        (str(k), str(v))
        for k, v in (dict(template.metadata).items()
                     if hasattr(template, 'metadata') and template.metadata
                     else ())
    )

    return TaxTemplateSnapshot(
        template_name=template.template_name,
        country_code=template.country_code,
        tax_year=template.tax_year,
        cit_structure=cit_structure,
        cit_tiers_summary=cit_tiers_summary,
        loss_carryforward_years=template.loss_carryforward_years,
        has_interest_limitation=template.interest_limitation_pct_ebitda is not None,
        has_wht_dividend=template.withholding_tax_dividends > 0.0,
        has_wht_interest=template.withholding_tax_interest > 0.0,
        depreciation_rules_summary=depreciation_rules_summary,
        metadata=metadata,
        created_at=datetime.now(timezone.utc),
        snapshot_label=snapshot_label,
        audit_note=_AUDIT_NOTE,
    )


def build_tax_override_snapshot(
    override: TaxTemplateOverride,
) -> TaxOverrideSnapshot:
    """Build an immutable snapshot from a single TaxTemplateOverride.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    override : TaxTemplateOverride
        Source override (not mutated).

    Returns
    -------
    TaxOverrideSnapshot
        Immutable snapshot capturing override details.
    """
    return TaxOverrideSnapshot(
        override_name=override.override_name,
        field_path=override.field_path,
        override_value=override.override_value,
        reason=override.reason,
        created_at=datetime.now(timezone.utc),
        audit_note=_AUDIT_NOTE,
    )


def build_resolved_tax_config_snapshot(
    resolved: ResolvedTaxConfig,
    snapshot_label: str | None = None,
) -> ResolvedTaxConfigSnapshot:
    """Build an immutable snapshot from a single ResolvedTaxConfig.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    resolved : ResolvedTaxConfig
        Source resolved config (not mutated).
    snapshot_label : str | None, optional
        Optional human-readable label for this snapshot.

    Returns
    -------
    ResolvedTaxConfigSnapshot
        Immutable snapshot capturing resolved configuration.
        No references to the original ResolvedTaxConfig object.
    """
    n_tiers = len(resolved.resolved_template.cit_tiers)
    if n_tiers == 0:
        effective_cit_structure = "None"
    elif n_tiers == 1:
        effective_cit_structure = "Flat"
    else:
        effective_cit_structure = "Progressive"

    overrides_summary = tuple(
        f"{ovr.field_path} → {ovr.override_value!r}"
        for ovr in resolved.overrides
    )

    # Normalize resolved_metadata
    resolved_metadata = tuple(
        (str(k), str(v))
        for k, v in (dict(resolved.resolved_metadata).items()
                     if hasattr(resolved, 'resolved_metadata') and resolved.resolved_metadata
                     else ())
    )

    return ResolvedTaxConfigSnapshot(
        template_name=resolved.resolved_template.template_name,
        country_code=resolved.resolved_template.country_code,
        tax_year=resolved.resolved_template.tax_year,
        effective_cit_structure=effective_cit_structure,
        override_count=len(resolved.overrides),
        overrides_summary=overrides_summary,
        resolved_metadata=resolved_metadata,
        created_at=datetime.now(timezone.utc),
        snapshot_label=snapshot_label,
        audit_note=_AUDIT_NOTE,
    )


def build_tax_assumption_snapshot(
    templates: tuple[TaxTemplate, ...],
    resolved_configs: tuple[ResolvedTaxConfig, ...] = (),
    overrides: tuple[TaxTemplateOverride, ...] = (),
    snapshot_label: str | None = None,
) -> TaxAssumptionSnapshot:
    """Build the top-level TaxAssumptionSnapshot from all tax inputs.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    templates : tuple[TaxTemplate, ...]
        Source tax templates (not mutated; used only to build snapshots).
    resolved_configs : tuple[ResolvedTaxConfig, ...], optional
        Source resolved configs (not mutated; used only to build snapshots).
    overrides : tuple[TaxTemplateOverride, ...], optional
        Source overrides (not mutated; used only to build snapshots).
    snapshot_label : str | None, optional
        Optional human-readable label for this snapshot.

    Returns
    -------
    TaxAssumptionSnapshot
        Top-level immutable snapshot storing only snapshot dataclasses.
        Original objects are not stored — only derived immutable representations.
    """
    template_snapshots = tuple(
        build_tax_template_snapshot(tmpl, snapshot_label=snapshot_label)
        for tmpl in templates
    )
    override_snapshots = tuple(
        build_tax_override_snapshot(ovr)
        for ovr in overrides
    )
    resolved_config_snapshots = tuple(
        build_resolved_tax_config_snapshot(cfg, snapshot_label=snapshot_label)
        for cfg in resolved_configs
    )

    return TaxAssumptionSnapshot(
        template_snapshots=template_snapshots,
        override_snapshots=override_snapshots,
        resolved_config_snapshots=resolved_config_snapshots,
        snapshot_label=snapshot_label,
        audit_note=_AUDIT_NOTE,
    )

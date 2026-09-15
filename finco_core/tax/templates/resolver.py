"""Phase 6A — Tax template resolver.

Applies TaxTemplateOverride objects to a base TaxTemplate immutably,
producing a ResolvedTaxConfig. No mutation of the base template.

Phase 6A supports:
- Simple top-level field overrides (e.g., "withholding_tax_interest")
- Metadata key overrides (e.g., "metadata.note", "metadata.source")
"""
from __future__ import annotations

from finco_core.tax.templates.inputs import (
    TaxTemplate,
    TaxTemplateOverride,
    ResolvedTaxConfig,
    CITTier,
    TaxDepreciationRule,
)


# Valid top-level override targets (TaxTemplate direct fields)
_VALID_TOP_LEVEL_FIELDS = frozenset({
    "country_code",
    "template_name",
    "tax_year",
    "cit_tiers",
    "depreciation_rules",
    "withholding_tax_dividends",
    "withholding_tax_interest",
    "loss_carryforward_years",
    "thin_cap_ratio",
    "interest_limitation_pct_ebitda",
    "metadata",
})

# Metadata key override prefix
_METADATA_PREFIX = "metadata."


def resolve_tax_template(
    base_template: TaxTemplate,
    overrides: tuple[TaxTemplateOverride, ...],
) -> ResolvedTaxConfig:
    """Apply overrides to a TaxTemplate and return a ResolvedTaxConfig.

    This is a **pure function**: the base_template is never mutated.
    Override application is order-preserving; on duplicate field_path,
    the last override wins.

    Supports two override patterns:
    - Top-level field: field_path like "withholding_tax_interest"
    - Metadata key: field_path like "metadata.note"

    Parameters
    ----------
    base_template : TaxTemplate
        The template to apply overrides to.
    overrides : tuple[TaxTemplateOverride, ...]
        Zero or more overrides to apply. Empty tuple = no change.

    Returns
    -------
    ResolvedTaxConfig
        Contains base_template, resolved_template (with overrides applied),
        the override list, and merged metadata.

    Raises
    ------
    ValueError
        If an override targets an invalid field_path, or if override values
        fail TaxTemplate validation.

    >>> result.resolved_template.withholding_tax_interest
    0.05
    """
    # Separate top-level overrides from metadata key overrides
    top_level_overrides: dict[str, TaxTemplateOverride] = {}
    metadata_key_overrides: dict[str, TaxTemplateOverride] = {}

    for ov in overrides:
        if ov.field_path.startswith(_METADATA_PREFIX):
            key = ov.field_path[len(_METADATA_PREFIX):]
            metadata_key_overrides[key] = ov
        elif ov.field_path in _VALID_TOP_LEVEL_FIELDS:
            top_level_overrides[ov.field_path] = ov
        else:
            raise ValueError(
                f"Invalid override field_path {ov.field_path!r}. "
                f"Valid fields: {sorted(_VALID_TOP_LEVEL_FIELDS)} "
                f"or 'metadata.<key>' patterns."
            )

    # Build resolved fields from base template
    fields = {
        "country_code": base_template.country_code,
        "template_name": base_template.template_name,
        "tax_year": base_template.tax_year,
        "cit_tiers": base_template.cit_tiers,
        "depreciation_rules": base_template.depreciation_rules,
        "withholding_tax_dividends": base_template.withholding_tax_dividends,
        "withholding_tax_interest": base_template.withholding_tax_interest,
        "loss_carryforward_years": base_template.loss_carryforward_years,
        "thin_cap_ratio": base_template.thin_cap_ratio,
        "interest_limitation_pct_ebitda": base_template.interest_limitation_pct_ebitda,
        "metadata": dict(base_template.metadata),
    }

    # Apply top-level overrides
    for field_path, ov in top_level_overrides.items():
        fields[field_path] = ov.override_value

    # Apply metadata key overrides
    for meta_key, ov in metadata_key_overrides.items():
        fields["metadata"][meta_key] = ov.override_value

    # Coerce list→tuple for cit_tiers and depreciation_rules if overridden
    for list_field in ("cit_tiers", "depreciation_rules"):
        val = fields[list_field]
        if isinstance(val, list):
            fields[list_field] = tuple(val)
        elif not isinstance(val, tuple):
            raise ValueError(
                f"{list_field} override must be list or tuple, got {type(val).__name__}"
            )

    # Whole-field metadata override (top-level, not metadata.<key>)
    if "metadata" in top_level_overrides:
        override_md = top_level_overrides["metadata"].override_value
        if isinstance(override_md, dict):
            fields["metadata"] = dict(override_md)
        elif isinstance(override_md, tuple):
            fields["metadata"] = dict(override_md)
        else:
            fields["metadata"] = dict(override_md)

    # Build resolved metadata as tuple of tuples
    resolved_metadata_tuples = tuple(
        (str(k), str(v)) for k, v in fields["metadata"].items()
    )

    # Construct the resolved TaxTemplate (validation runs via __post_init__)
    try:
        resolved_template = TaxTemplate(
            country_code=fields["country_code"],
            template_name=fields["template_name"],
            tax_year=fields["tax_year"],
            cit_tiers=fields["cit_tiers"],
            depreciation_rules=fields["depreciation_rules"],
            withholding_tax_dividends=fields["withholding_tax_dividends"],
            withholding_tax_interest=fields["withholding_tax_interest"],
            loss_carryforward_years=fields["loss_carryforward_years"],
            thin_cap_ratio=fields["thin_cap_ratio"],
            interest_limitation_pct_ebitda=fields["interest_limitation_pct_ebitda"],
            metadata=resolved_metadata_tuples,
        )
    except Exception as e:
        raise ValueError(
            f"Override produced invalid resolved TaxTemplate: {e}"
        ) from e

    return ResolvedTaxConfig(
        base_template=base_template,
        resolved_template=resolved_template,
        overrides=tuple(overrides),
        resolved_metadata=resolved_metadata_tuples,
    )
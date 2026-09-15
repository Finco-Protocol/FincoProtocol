"""Phase 6B.4 — SPV tax engine input models.

Immutable dataclasses that carry inputs to run_spv_tax_engine().
No mutation, no side effects, no waterfall wiring.

CAVEAT: These are pure input containers. No cashflow wiring,
no deferred tax accounting, no HoldCo logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from finco_core.tax.templates.inputs import ResolvedTaxConfig

__all__ = [
    "SPVTaxEngineInputs",
]


@dataclass(frozen=True)
class SPVTaxEngineInputs:
    """Complete inputs for running the SPV tax engine.

    All inputs are required and validated at construction time.

    Attributes
    ----------
    entity_code : str
        Entity identifier. Must be non-empty.
    resolved_tax_config : ResolvedTaxConfig
        Resolved tax template for this entity's jurisdiction and year.
        Must have a depreciation rule matching ``depreciation_rule_asset_category``.
    ebitda_by_period_keur : tuple[float, ...]
        EBITDA per period in kEUR.
    deductible_interest_by_period_keur : tuple[float, ...]
        Deductible interest expense per period in kEUR.
    book_depreciation_by_period_keur : tuple[float, ...]
        Book (accounting) depreciation charge per period in kEUR.
    asset_cost_keur : float
        Total asset cost in kEUR. Must be >= 0.
    depreciation_rule_asset_category : str
        Asset category key matching a rule in ``resolved_tax_config``.
    non_deductible_addbacks_by_period_keur : tuple[float, ...]
        Non-deductible addbacks (e.g., entertainment, provisions) per period in kEUR.
    loss_carryforward_years : int | None
        Loss carryforward years. None = unlimited. Not yet vintage-tracked (6B.3).

    Validation (in ``__post_init__``)
    ---------------------------------
    - entity_code non-empty
    - asset_cost_keur >= 0
    - all tuples same length
    - ``depreciation_rule_asset_category`` exists in resolved_tax_config
    - ``non_deductible_addbacks_by_period_keur`` optional (defaults to all-zero tuple)
    """
    entity_code: str
    resolved_tax_config: ResolvedTaxConfig
    ebitda_by_period_keur: tuple[float, ...]
    deductible_interest_by_period_keur: tuple[float, ...]
    book_depreciation_by_period_keur: tuple[float, ...]
    asset_cost_keur: float
    depreciation_rule_asset_category: str
    non_deductible_addbacks_by_period_keur: tuple[float, ...] = ()
    loss_carryforward_years: Optional[int] = None

    def __post_init__(self):
        """Validate all inputs."""
        # entity_code non-empty
        if not self.entity_code or not self.entity_code.strip():
            raise ValueError("entity_code must be non-empty")

        # asset_cost_keur >= 0
        if self.asset_cost_keur < 0.0:
            raise ValueError(
                f"asset_cost_keur must be >= 0, got {self.asset_cost_keur}"
            )

        # Validate required tuples have same length
        required_tuples = (
            ("ebitda_by_period_keur", self.ebitda_by_period_keur),
            ("deductible_interest_by_period_keur", self.deductible_interest_by_period_keur),
            ("book_depreciation_by_period_keur", self.book_depreciation_by_period_keur),
        )
        required_lengths = {name: len(t) for name, t in required_tuples}
        if len(set(required_lengths.values())) > 1:
            raise ValueError(
                f"ebitda, deductible_interest, and book_depreciation tuples "
                f"must have same length, got {required_lengths}"
            )

        # non_deductible_addbacks_by_period_keur is optional:
        # - empty tuple means all-zero addbacks (default)
        # - otherwise must match required tuple length
        n = len(self.ebitda_by_period_keur)  # reference length from required tuples
        addbacks_len = len(self.non_deductible_addbacks_by_period_keur)
        if addbacks_len != 0 and addbacks_len != n:
            raise ValueError(
                f"non_deductible_addbacks_by_period_keur must be empty (default "
                f"all-zero) or same length as other tuples ({n}), got {addbacks_len}"
            )

        # depreciation_rule_asset_category exists in resolved_tax_config
        resolved_template = self.resolved_tax_config.resolved_template
        rule_categories = {
            rule.asset_category for rule in resolved_template.depreciation_rules
        }
        if self.depreciation_rule_asset_category not in rule_categories:
            raise ValueError(
                f"depreciation_rule_asset_category "
                f"'{self.depreciation_rule_asset_category}' not found in "
                f"resolved_tax_config depreciation rules: {rule_categories}"
            )

        # loss_carryforward_years validation (if provided)
        if self.loss_carryforward_years is not None:
            if not isinstance(self.loss_carryforward_years, int) or self.loss_carryforward_years < 0:
                raise ValueError(
                    f"loss_carryforward_years must be None or non-negative int, "
                    f"got {self.loss_carryforward_years}"
                )

        # non_deductible_addbacks_by_period_keur defaults to zeros if empty
        # (handled by field default, but check here for explicit empty tuple
        # that was passed — still valid, just means no addbacks)
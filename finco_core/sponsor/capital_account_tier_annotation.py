"""Phase 7C-4 — Capital account tier annotation.

Extends SponsorCapitalAccount entries with optional tier-level distribution
annotations so waterfall allocations can be traced back to tier-level events.

Schema-only: no allocation logic, no mutation of input results.

Design goals:
- Deterministic, audit-safe, frozen dataclasses
- Optional tier reference fields (backward-compatible with existing entries)
- No mutation of WaterfallAllocationResult inputs
- Future multi-tier compatibility
- Serialization-friendly (all JSON-serializable scalars)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from finco_core.sponsor.sponsor_capital_account import (
    CapitalAccountEntry,
    SponsorCapitalAccount,
)
from finco_core.sponsor.sponsor_waterfall_tier import TierType

__all__ = [
    "TierAnnotation",
    "TierAnnotatedCapitalAccountEntry",
    "TierAnnotatedSponsorCapitalAccount",
    "from_waterfall_allocation_result",
]


# ── TierAnnotation ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TierAnnotation:
    """Optional tier-level annotation for a capital account entry.

    Immutable. Allows a capital account entry to be traced back to a specific
    waterfall tier allocation event.

    Attributes
    ----------
    tier_index : int | None
        Tier index from SponsorWaterfallTier. None if not tier-linked.
    tier_type : TierType | None
        Type of the tier that generated this allocation. None if not tier-linked.
    sponsor_code : str | None
        Sponsor code this allocation was attributed to. None if not tier-linked.
    allocated_amount_keur : float | None
        Amount allocated from this tier to the sponsor. None if not tier-linked.
    source_note : str
        Human-readable note describing the allocation source.
        Examples: "preferred_return_accrual_allocation", "roc_repayment",
        "gp_catch_up_allocation", "promote_split", "residual_split"
    """
    tier_index: int | None = None
    tier_type: TierType | None = None
    sponsor_code: str | None = None
    allocated_amount_keur: float | None = None
    source_note: str = ""

    def __post_init__(self):
        if self.tier_index is not None and not isinstance(self.tier_index, int):
            raise TypeError(f"tier_index must be int or None, got {type(self.tier_index).__name__}")
        if self.tier_index is not None and self.tier_index < 0:
            raise ValueError(f"tier_index must be >= 0, got {self.tier_index}")
        if self.tier_type is not None and not isinstance(self.tier_type, TierType):
            raise TypeError(f"tier_type must be TierType or None, got {type(self.tier_type).__name__}")
        for fname, val in [
            ("sponsor_code", self.sponsor_code),
            ("source_note", self.source_note),
        ]:
            if val is not None and not isinstance(val, str):
                raise TypeError(f"{fname} must be str or None, got {type(val).__name__}")
        if self.allocated_amount_keur is not None:
            if not isinstance(self.allocated_amount_keur, (int, float)):
                raise TypeError(
                    f"allocated_amount_keur must be float or None, "
                    f"got {type(self.allocated_amount_keur).__name__}"
                )
            if math.isnan(self.allocated_amount_keur) or math.isinf(self.allocated_amount_keur):
                raise ValueError(
                    f"allocated_amount_keur must be finite, got {self.allocated_amount_keur}"
                )
            if self.allocated_amount_keur < 0.0:
                raise ValueError(
                    f"allocated_amount_keur must be >= 0, got {self.allocated_amount_keur}"
                )

    @staticmethod
    def empty() -> TierAnnotation:
        """Return an empty (no-tier) annotation."""
        return TierAnnotation()

    @property
    def is_empty(self) -> bool:
        """True if this annotation carries no tier information."""
        return (
            self.tier_index is None
            and self.tier_type is None
            and self.sponsor_code is None
            and self.allocated_amount_keur is None
            and self.source_note == ""
        )


# ── TierAnnotatedCapitalAccountEntry ───────────────────────────────────────

@dataclass(frozen=True)
class TierAnnotatedCapitalAccountEntry:
    """Immutable capital account entry with optional tier annotation.

    This is a new schema type (not a subclass) that wraps CapitalAccountEntry
    with an optional TierAnnotation. Existing CapitalAccountEntry behavior
    is fully preserved.

    Attributes
    ----------
    entry : CapitalAccountEntry
        The underlying capital account entry.
    annotation : TierAnnotation
        Optional tier annotation. Use TierAnnotation.empty() for entries
        that are not tier-linked.
    audit_note : str
        Fixed audit note.
    """
    entry: CapitalAccountEntry
    annotation: TierAnnotation = field(default_factory=TierAnnotation)
    audit_note: str = field(
        default="AUDIT-ONLY: tier-annotated capital account entry — read-only annotation artifact"
    )

    def __post_init__(self):
        if not isinstance(self.entry, CapitalAccountEntry):
            raise TypeError("entry must be CapitalAccountEntry")
        if not isinstance(self.annotation, TierAnnotation):
            raise TypeError("annotation must be TierAnnotation")
        if not isinstance(self.audit_note, str):
            raise TypeError("audit_note must be str")

    @property
    def is_tier_annotated(self) -> bool:
        """True if this entry carries a non-empty tier annotation."""
        return not self.annotation.is_empty


# ── TierAnnotatedSponsorCapitalAccount ─────────────────────────────────────

@dataclass(frozen=True)
class TierAnnotatedSponsorCapitalAccount:
    """Immutable capital account with tier-annotated entries.

    Attributes
    ----------
    investor_id : str
        Sponsor/investor identifier.
    entity_code : str
        Target entity code.
    entries : tuple[TierAnnotatedCapitalAccountEntry, ...]
        Ordered ledger of tier-annotated capital account entries.
    total_contributed_keur : float
        Sum of all contribution amounts.
    total_distributions_keur : float
        Sum of all distribution amounts.
    net_contributed_keur : float
        total_contributed - total_distributions.
    final_balance_keur : float | None
        Final balance. May be negative (return phase).
    metadata : tuple[tuple[str, Any], ...]
        Key-value metadata.
    notes : tuple[str, ...]
        Audit notes.
    """
    investor_id: str
    entity_code: str
    entries: tuple[TierAnnotatedCapitalAccountEntry, ...]
    total_contributed_keur: float
    total_distributions_keur: float
    net_contributed_keur: float
    final_balance_keur: float | None = None
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def audit_note(self) -> str:
        return (
            "AUDIT-ONLY: tier-annotated sponsor capital account is a read-only "
            "governance artifact. It does not modify any waterfall result or trigger payments."
        )

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def __post_init__(self):
        if not isinstance(self.investor_id, str) or not self.investor_id.strip():
            raise ValueError("investor_id must be non-empty string")
        if not isinstance(self.entity_code, str) or not self.entity_code.strip():
            raise ValueError("entity_code must be non-empty string")
        if not isinstance(self.entries, (list, tuple)):
            raise TypeError("entries must be tuple")
        object.__setattr__(self, "entries", tuple(self.entries))
        if len(self.entries) == 0:
            raise ValueError("entries cannot be empty")

        eps = 1e-6
        total_contrib = sum(
            e.entry.amount_keur
            for e in self.entries
            if e.entry.entry_type == "contribution"
        )
        total_distrib = sum(
            e.entry.amount_keur
            for e in self.entries
            if e.entry.entry_type == "distribution"
        )
        if abs(total_contrib - self.total_contributed_keur) > eps:
            raise ValueError(
                f"total_contributed_keur ({self.total_contributed_keur}) does not reconcile "
                f"with entries sum ({total_contrib:.6f})"
            )
        if abs(total_distrib - self.total_distributions_keur) > eps:
            raise ValueError(
                f"total_distributions_keur ({self.total_distributions_keur}) does not reconcile "
                f"with entries sum ({total_distrib:.6f})"
            )

        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))


# ── Conversion from WaterfallAllocationResult ──────────────────────────────

def from_waterfall_allocation_result(
    result: Any,
    sponsor_code: str,
    entity_code: str = "HOLDCO",
) -> TierAnnotatedSponsorCapitalAccount:
    """Convert a WaterfallAllocationResult into tier-annotated capital account entries.

    Pure function. Does not mutate the input result.

    Each tier allocation for the given sponsor_code becomes one "distribution" entry
    annotated with the tier metadata. Entries are sorted by (period_index, tier_index).

    Parameters
    ----------
    result : WaterfallAllocationResult
        The waterfall allocation result (from Phase 7C-3 runner).
    sponsor_code : str
        Only entries for this sponsor_code are included.
    entity_code : str
        Target entity code for the capital account.

    Returns
    -------
    TierAnnotatedSponsorCapitalAccount
        Frozen capital account with one entry per tier allocation per period.
    """
    from finco_core.sponsor.waterfall_allocation_result import (
        WaterfallAllocationResult,
        PeriodWaterfallResult,
    )

    if not isinstance(result, WaterfallAllocationResult):
        raise TypeError(
            f"result must be WaterfallAllocationResult, got {type(result).__name__}"
        )

    annotated_entries: list[TierAnnotatedCapitalAccountEntry] = []
    running_balance = 0.0
    total_contrib = 0.0
    total_distrib = 0.0

    for period_result in result.period_results:
        if not isinstance(period_result, PeriodWaterfallResult):
            raise TypeError(
                f"period_result must be PeriodWaterfallResult, got {type(period_result).__name__}"
            )
        p = period_result.period_index

        for tier_entry in period_result.tier_entries:
            alloc = tier_entry.allocation_for(sponsor_code)
            if alloc <= 0.0:
                continue

            tier_index = tier_entry.tier_index
            tier_type = tier_entry.tier_type
            source_note = _source_note_for_tier(tier_type)

            annotation = TierAnnotation(
                tier_index=tier_index,
                tier_type=tier_type,
                sponsor_code=sponsor_code,
                allocated_amount_keur=alloc,
                source_note=source_note,
            )

            base_entry = CapitalAccountEntry(
                entry_type="distribution",
                period_index=p,
                amount_keur=alloc,
                running_balance_keur=0.0,  # caller computes running balance
                investor_id=sponsor_code,
                source="distribution_from_holdco",  # valid CA source; detailed tier type in TierAnnotation.source_note
            )

            annotated_entries.append(
                TierAnnotatedCapitalAccountEntry(
                    entry=base_entry,
                    annotation=annotation,
                )
            )

            total_distrib += alloc
            running_balance -= alloc  # negative = return phase

    # Sort by (period_index, tier_index)
    annotated_entries.sort(key=lambda e: (e.entry.period_index, e.annotation.tier_index or 0))

    # Set correct running balances
    sorted_entries = annotated_entries
    annotated_entries = []
    cumulative = 0.0
    for ae in sorted_entries:
        cumulative += ae.entry.amount_keur
        adjusted_entry = CapitalAccountEntry(
            entry_type=ae.entry.entry_type,
            period_index=ae.entry.period_index,
            amount_keur=ae.entry.amount_keur,
            running_balance_keur=-cumulative,  # distributions reduce balance
            investor_id=ae.entry.investor_id,
            source=ae.entry.source,
            notes=ae.entry.notes,
        )
        annotated_entries.append(
            TierAnnotatedCapitalAccountEntry(
                entry=adjusted_entry,
                annotation=ae.annotation,
            )
        )

    return TierAnnotatedSponsorCapitalAccount(
        investor_id=sponsor_code,
        entity_code=entity_code,
        entries=tuple(annotated_entries),
        total_contributed_keur=total_contrib,
        total_distributions_keur=total_distrib,
        net_contributed_keur=total_contrib - total_distrib,
        final_balance_keur=-(total_distrib),
    )


def _source_note_for_tier(tier_type: TierType) -> str:
    """Return a canonical source note string for a tier type."""
    mapping = {
        TierType.RETURN_OF_CAPITAL: "return_of_capital",
        TierType.PREFERRED_RETURN: "preferred_return_allocation",
        TierType.GP_CATCH_UP: "gp_catch_up_allocation",
        TierType.PROMOTE: "promote_split",
        TierType.RESIDUAL: "residual_split",
    }
    return mapping.get(tier_type, f"tier_{tier_type.value}")

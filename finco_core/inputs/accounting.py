"""finco_core.inputs.accounting — canonical accounting policy types.

These are INPUT types supplied by project factories (outside financial_engine/).
No imports from financial_engine — only stdlib, dataclasses, enum.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AccountingPolicyAuthority(str, Enum):
    """Typed provenance of each accounting policy choice.

    SOURCE_PROVEN      — value or treatment traced to workbook evidence for
                         THIS project (Generic Solar Reference / Generic Wind Reference only, after explicit
                         source-trace audit).
    GENERIC_FINCO_POLICY — standard Finco default applied without a
                           project-specific source trace (Solar / Wind).
    USER_CONFIGURED    — value supplied by user configuration that overrides
                         the generic default (not yet in use; reserved for
                         future interactive configuration).
    NOT_APPLICABLE     — the policy dimension does not apply to this project
                         (e.g. legal reserve where Generic Market An-law SPV criteria
                         are not met).
    UNRESOLVED         — provenance not yet established; output for that
                         dimension is blocked or surfaced as unavailable.
    """

    SOURCE_PROVEN = "SOURCE_PROVEN"
    GENERIC_FINCO_POLICY = "GENERIC_FINCO_POLICY"
    USER_CONFIGURED = "USER_CONFIGURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class BookCapitalizationTreatment(str, Enum):
    """Typed classification of how a cost component is capitalized in the
    book fixed-asset (GFA) ledger.

    CAPITALIZE_FIXED_ASSET       — included in Gross Fixed Assets; subject
                                   to book depreciation.
    EXPENSE_PNL                  — expensed directly to P&L; never in GFA.
    RESTRICTED_CURRENT_ASSET     — funded and ring-fenced (e.g. DSRA);
                                   separate balance-sheet line, not GFA.
    UNRESTRICTED_CURRENT_ASSET   — working capital or similar; separate
                                   current-asset line, not GFA.
    NOT_APPLICABLE               — component does not arise in this project.
    UNRESOLVED                   — treatment not yet determined; GFA
                                   contribution cannot be claimed.
    """

    CAPITALIZE_FIXED_ASSET = "CAPITALIZE_FIXED_ASSET"
    EXPENSE_PNL = "EXPENSE_PNL"
    RESTRICTED_CURRENT_ASSET = "RESTRICTED_CURRENT_ASSET"
    UNRESTRICTED_CURRENT_ASSET = "UNRESTRICTED_CURRENT_ASSET"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class LegalReservePolicy:
    """Explicit typed activation of the legal-reserve roll-forward.

    Must be set by a project factory (outside financial_engine/) where workbook
    or policy evidence exists.  Assembly never activates legal reserve from a
    scalar default — only an explicit LegalReservePolicy(enabled=True) triggers
    the roll-forward kernel.
    """

    enabled: bool
    cap_fraction: float
    authority: AccountingPolicyAuthority = AccountingPolicyAuthority.GENERIC_FINCO_POLICY


@dataclass(frozen=True)
class AccountingPolicyConfig:
    """Typed accounting-policy INPUT provided by project factories.

    Assembly reads this config exclusively — it may NOT read project identity
    (code, name, country+code combination, or any identity whitelist) to derive
    accounting behaviour.  Factories in app/ are identity-aware and populate
    this config with the appropriate authorities.

    Defaults produce the generic/unavailable behaviour (no legal reserve,
    GENERIC_FINCO_POLICY authority for all dimensions).
    """

    book_capitalization_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.GENERIC_FINCO_POLICY
    )
    book_capitalization_components: dict = field(default_factory=dict)
    shl_construction_accounting_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.GENERIC_FINCO_POLICY
    )
    opening_re_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.GENERIC_FINCO_POLICY
    )
    legal_reserve_policy: "LegalReservePolicy | None" = None
    legal_reserve_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.GENERIC_FINCO_POLICY
    )
    cash_interest_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )
    # Pre-construction retained earnings: typed equity starting point at the
    # first model period.  For a newly incorporated SPV with zero opening RE,
    # set to 0.0 with SOURCE_PROVEN authority (after source trace) or
    # GENERIC_FINCO_POLICY (for standard new-SPV assumption).
    # Default UNRESOLVED means assembly cannot derive authoritative opening RE.
    preconstruction_retained_earnings_keur: "float | None" = None
    preconstruction_retained_earnings_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )

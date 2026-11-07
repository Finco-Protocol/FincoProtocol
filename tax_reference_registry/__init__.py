"""FINCO T01-D — Versioned Tax Reference Registry Foundation.

Offline, reference-only registry for statutory tax-rule evidence across 34
jurisdictions. This package stores and explains reference records; it never
computes a project tax rate, never selects a rate for a run, and never
activates a country profile.

Separation guarantees (by construction):
  (a) legal effectiveness   -> LawStatus / EffectiveWindow
  (b) evidence confidence   -> VerificationStatus (+ raw harvest status preserved)
  (c) app activation        -> activation.py fails CLOSED unconditionally

No module outside this package may import it (enforced by a repo scan test);
nothing in the released engine (financial_engine/**, finco_core/**) references
it. All 34 country profiles are CANDIDATE_NOT_ACTIVE in this phase.

Public API (stdlib only, offline, deterministic):
  load_records(path_or_file, *, private_markers=()) -> LoadResult
  TaxReferenceRegistry.from_records / .compare / .explain /
  .export_candidates / .is_operative_on
  cli.main (validate | compare | explain | export-candidates)
"""
from __future__ import annotations

__all__ = [
    "LawStatus",
    "VerificationStatus",
    "TaxCategory",
    "RateScheduleMode",
    "KnownCurrency",
    "CurrencyPolicy",
    "NoImplicitFxError",
    "TaxRuleRecord",
    "EffectiveWindow",
    "LoadResult",
    "RowError",
    "TaxReferenceRegistry",
    "ActivationBlockedError",
    "activate_country",
    "get_effective_run_profile",
    "NO_IMPLICIT_FX",
]

__version__ = "0.1.0"

from tax_reference_registry.enums import (
    LawStatus,
    RateScheduleMode,
    TaxCategory,
    VerificationStatus,
)
from tax_reference_registry.currency import (
    CurrencyPolicy,
    KnownCurrency,
    NoImplicitFxError,
    NO_IMPLICIT_FX,
)
from tax_reference_registry.records import (
    EffectiveWindow,
    TaxRuleRecord,
)
from tax_reference_registry.loader import LoadResult, RowError, load_records
from tax_reference_registry.registry import TaxReferenceRegistry
from tax_reference_registry.activation import (
    ActivationBlockedError,
    activate_country,
    get_effective_run_profile,
)

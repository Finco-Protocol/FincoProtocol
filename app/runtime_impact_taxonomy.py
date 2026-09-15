"""Phase 24A: Runtime Impact Taxonomy

Canonical4-state taxonomy for FINCO Model UI surfaces.
Replaces legacy runtime impact labels with standardized primary states.

Primary States
-------------
Drives model
    Input is runtime-effective and directly affects calculation outputs.
    User should understand changes alter model results.

Display only
    Field is visible/reference/displayed but does not currently affect
    runtime calculations. User should not expect formula impact.

Pending
    Field/section is planned or captured but not yet wired.
    Could become runtime-effective in a later phase.

Needs review
    Field/section has ambiguous mapping, unresolved source issue,
    validation concern, or requires human/model review before being trusted.

Sub-reasons (for tooltip/helper text, not primary labels)
---------------------------------------------------------
Timing only — field is used for construction timing/draw schedule only
Reference only   — field is shown for reference, not runtime-effective
Pending treatment — field is captured but treatment is pending
Pending runtime source — runtime source not yet connected
Not comparable — scope mismatch prevents comparison
Deferred — field is intentionally deferred
Not applicable — field does not apply to this project/scenario
Reference policy   — field value comes from an explicit reference-model policy
Frozen schedule  — field uses a frozen/scheduled value, not computed
Source locked     — source is locked (e.g., Excel calibration)
Validation warning — field has a validation concern
Reference variance known gap — documented difference from validated reference behavior

Legacy Mapping
--------------
Maps legacy labels to canonical primary states.

Legacy label -> Canonical state
------------------------- ------------------
"Drives model"            -> Drives model
"backend_authoritative"   -> Drives model
"app_mapped" + affects    -> Drives model
"Timing only"             -> Display only
"Reference only"          -> Display only
"Display only"           -> Display only
"Pending treatment"       -> Pending
"Pending runtime source"  -> Pending
"Deferred"                -> Pending
"Not applicable"          -> Display only
"Not comparable" -> Needs review
"Needs review"            -> Needs review
"mismatch"                -> Needs review
"Unknown"                 -> Needs review
"Pending runtime source"  -> Pending
"reference-policy"          -> Drives model (with sub-reason)
"frozen schedule"         -> Drives model (with sub-reason)

Frozen Senior DS Treatment
--------------------------
Generic Wind Reference and Generic Solar Reference senior debt schedule:
- Primary state: Drives model
- Sub-reason: "Explicit reference schedule"
- Do NOT claim solver/sculpting is active

CAPEX Treatment
---------------
CAPEX Phase 21 is display/schema only:
- C.16 Project Rights: Pending (not runtime-effective)
- M1-M18 schedule: Display only (timing-only, not IDC runtime)
- EPC/Grid totals (aggregate_total scope): Drives model
- C.16 children with treatment_resolved: Drives model

Tax Treatment
--------------
Actual runtime-effective tax fields: Drives model
Pending/future tax treatment: Pending or Needs review
"""

from __future__ import annotations

from enum import Enum


class RuntimeImpactStatus(str, Enum):
    """Canonical runtime impact states for FINCO Model UI surfaces."""

    DRIVES_MODEL = "Drives model"
    DISPLAY_ONLY = "Display only"
    PENDING = "Pending"
    NEEDS_REVIEW = "Needs review"


# Canonical states as flat strings for UI display
CANONICAL_STATES = tuple(s.value for s in RuntimeImpactStatus)

# Sub-reasons for tooltip/helper text (not primary labels)
SUB_REASONS = {
    "timing_only": "Timing only — used for construction draw/timing only, not IDC runtime",
    "reference_only": "Reference only — shown for reference, not runtime-effective",
    "pending_treatment": "Pending treatment — captured but not yet wired to runtime",
    "pending_runtime_source": "Pending runtime source — runtime source not yet connected",
    "not_comparable": "Not comparable — scope mismatch prevents direct comparison",
    "deferred": "Deferred — intentionally deferred to a later phase",
    "not_applicable": "Not applicable — does not apply to this project/scenario",
    "fixture_backed": "Reference policy — value from an explicit reference-model policy",
    "frozen_schedule": "Frozen schedule — frozen per-period value, not computed",
    "source_locked": "Source locked — from Excel calibration, locked",
    "validation_warning": "Validation warning — field has a validation concern",
    "excel_parity_known_gap": "Reference variance known gap — documented difference from validated reference behavior",
}

# Legacy label -> canonical state mapping
LEGACY_TO_CANONICAL = {
    # Drives model variants
    "Drives model": RuntimeImpactStatus.DRIVES_MODEL,
    "backend_authoritative": RuntimeImpactStatus.DRIVES_MODEL,
    # Display only variants
    "Timing only": RuntimeImpactStatus.DISPLAY_ONLY,
    "Reference only": RuntimeImpactStatus.DISPLAY_ONLY,
    "Display only": RuntimeImpactStatus.DISPLAY_ONLY,
    "Not applicable": RuntimeImpactStatus.DISPLAY_ONLY,
    # Pending variants
    "Pending treatment": RuntimeImpactStatus.PENDING,
    "Pending runtime source": RuntimeImpactStatus.PENDING,
    "Deferred": RuntimeImpactStatus.PENDING,
    # Needs review variants
    "Not comparable": RuntimeImpactStatus.NEEDS_REVIEW,
    "Needs review": RuntimeImpactStatus.NEEDS_REVIEW,
    "mismatch": RuntimeImpactStatus.NEEDS_REVIEW,
    "Unknown": RuntimeImpactStatus.NEEDS_REVIEW,
    "scope_mismatch": RuntimeImpactStatus.NEEDS_REVIEW,
    "mapping_mismatch": RuntimeImpactStatus.NEEDS_REVIEW,
}


def map_legacy_to_canonical(legacy_label: str) -> RuntimeImpactStatus:
    """Map a legacy runtime impact label to a canonical state.

    Parameters
    ----------
    legacy_label : str
        Legacy label string from UI or backend.

    Returns
    -------
    RuntimeImpactStatus
        Canonical state. Falls back to NEEDS_REVIEW for unknown labels.
    """
    return LEGACY_TO_CANONICAL.get(legacy_label, RuntimeImpactStatus.NEEDS_REVIEW)


def get_sub_reason(key: str) -> str | None:
    """Get sub-reason text for a given key.

    Parameters
    ----------
    key : str
        Sub-reason key (e.g., "timing_only", "fixture_backed").

    Returns
    -------
    str or None
        Sub-reason text, or None if key not found.
    """
    return SUB_REASONS.get(key)


def get_frozen_senior_ds_taxonomy() -> dict:
    """Return the canonical taxonomy for frozen senior DS surfaces.

    Used by Generic Wind Reference and Generic Solar Reference senior debt schedule UI surfaces.
    """
    return {
        "primary": RuntimeImpactStatus.DRIVES_MODEL,
        "sub_reason": SUB_REASONS["fixture_backed"],
        "note": "Explicit reference schedule — DSCR is backward-computed from frozen service",
 "sculpting_active": False,
    }


def get_capex_taxonomy() -> dict:
    """Return the canonical taxonomy for CAPEX surfaces.

    CAPEX Phase 21 is display/schema only.
    """
    return {
        "c16_project_rights": {
            "primary": RuntimeImpactStatus.PENDING,
            "sub_reason": SUB_REASONS["pending_treatment"],
            "note": "C.16 Project Rights not runtime-effective",
        },
        "m1_m18_schedule": {
            "primary": RuntimeImpactStatus.DISPLAY_ONLY,
            "sub_reason": SUB_REASONS["timing_only"],
            "note": "M1-M18 schedule is timing-only, not IDC runtime",
        },
        "epc_grid_totals": {
            "primary": RuntimeImpactStatus.DRIVES_MODEL,
            "sub_reason": None,
            "note": "EPC/Grid totals are aggregate CAPEX totals",
        },
    }

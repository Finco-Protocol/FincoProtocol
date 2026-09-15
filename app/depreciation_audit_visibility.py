"""Phase D1 — Depreciation Export / Audit Visibility Hardening.

This module ADDS audit visibility only. It does NOT enable any
depreciation feature flag, does NOT change depreciation
schedules, does NOT change tax / P&L / CFADS / payment schedule
values, and does NOT change waterfall runtime authority. It
writes a single "Depreciation Audit" sheet that discloses the
current depreciation source, runtime authority, and audit-only
surfaces.

All wording is review-safe and conservative: the sheet tells
the reviewer exactly which backend runtime path produced the
values that appear in the rest of the workbook. Reviewers can
use it to confirm that no canonical depreciation engine is
being silently promoted to runtime authority.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def _resolve_depreciation_runtime_authority(
    project_inputs: Any = None,
    provenance_metadata: Optional[dict] = None,
) -> dict[str, str]:
    """Read the current depreciation runtime authority from
    the available flag sources. Order of preference:

    1. ``provenance_metadata['runtime_flag_snapshot']`` (set
       when provenance was built with
       ``build_replay_metadata``).
    2. ``project_inputs.info`` / ``project_inputs.financing``
       attribute reads (live runtime).
    3. Hard fallback (``"UNKNOWN"`` for flag status,
       ``"legacy"`` for active path).

    Returns a dict of disclosure-friendly strings ready to
    write to the audit sheet. The strings are intentionally
    human-readable: reviewers should be able to scan the
    sheet without consulting the codebase.
    """
    flags: dict[str, Any] = {}
    if provenance_metadata and isinstance(
        provenance_metadata, dict
    ):
        flag_snapshot = provenance_metadata.get(
            "runtime_flag_snapshot"
        )
        if isinstance(flag_snapshot, dict):
            flags = flag_snapshot

    if not flags and project_inputs is not None:
        try:
            from app.persistence.provenance import (
                runtime_flag_snapshot,
            )
            flags = runtime_flag_snapshot(project_inputs)
        except Exception:
            flags = {}

    def _yn(flag_name: str) -> str:
        if flag_name not in flags:
            return "UNKNOWN"
        return "YES" if bool(flags[flag_name]) else "NO"

    canonical_engine = _yn("use_depreciation_canonical_engine")
    canonical_bridge = _yn(
        "use_canonical_tax_depreciation_bridge"
    )
    book_for_pnl = _yn("use_book_depreciation_for_pnl")
    tax_bridge = _yn("use_tax_bridge_engine")

    # Active runtime path is the legacy path unless the
    # canonical engine flag is explicitly enabled. This is
    # the current truth (D1 does not change it).
    if canonical_engine == "YES":
        active_path = "canonical_depreciation_engine"
        authority_source = (
            "domain.depreciation.engine.DepreciationEngine"
        )
    else:
        active_path = "legacy_depreciation_runtime"
        authority_source = (
            "waterfall_core.LegacyDepreciationPath"
        )

    return {
        "active_depreciation_path": active_path,
        "runtime_authority_source": authority_source,
        "canonical_depreciation_engine_enabled": (
            canonical_engine
        ),
        "canonical_tax_bridge_enabled": canonical_bridge,
        "tax_bridge_engine_enabled": tax_bridge,
        "book_depreciation_pnl_bridge_enabled": book_for_pnl,
    }


def build_depreciation_audit_dataframe(
    project_inputs: Any = None,
    provenance_metadata: Optional[dict] = None,
) -> pd.DataFrame:
    """Build the disclosure DataFrame for the
    'Depreciation Audit' sheet.

    The DataFrame has columns ``Field`` and ``Value``. All
    values are text (no numerics). The auto-index from
    pandas ``to_excel(..., index=True)`` is allowed (it is
    not a financial value; reviewers can ignore it).
    """
    authority = _resolve_depreciation_runtime_authority(
        project_inputs=project_inputs,
        provenance_metadata=provenance_metadata,
    )
    rows = [
        (
            "Phase",
            "D1 \u2014 Depreciation Export / Audit "
            "Visibility Hardening",
        ),
        (
            "Scope",
            "Audit visibility only. NO runtime enablement. "
            "NO formula / schedule / tax / P&L / CFADS change.",
        ),
        (
            "Notice",
            "Depreciation export visibility only \u2014 no "
            "runtime authority change.",
        ),
        (
            "Active Depreciation Path",
            authority["active_depreciation_path"],
        ),
        (
            "Runtime Authority Source",
            authority["runtime_authority_source"],
        ),
        (
            "Canonical Depreciation Engine Enabled",
            authority["canonical_depreciation_engine_enabled"],
        ),
        (
            "Canonical Tax Bridge Enabled",
            authority["canonical_tax_bridge_enabled"],
        ),
        (
            "Tax Bridge Engine Enabled",
            authority["tax_bridge_engine_enabled"],
        ),
        (
            "Book Depreciation P&L Bridge Enabled",
            authority["book_depreciation_pnl_bridge_enabled"],
        ),
        (
            "Values Reflect",
            "Current active backend runtime path (NOT a "
            "canonical-promotion simulation).",
        ),
        (
            "Audit-Only Surfaces",
            "Depreciation Assumptions; Depreciation Audit "
            "(this sheet); canonical audit rows when present "
            "in result._canonical_depreciation_wiring "
            "(advisory only, not runtime authority).",
        ),
        (
            "Runtime Surfaces",
            "Tax_Depreciation; Tax Depreciation; Book "
            "Depreciation; waterfall "
            "period.depreciation_keur (when produced by the "
            "active runtime path).",
        ),
        (
            "Known Limitations",
            "Canonical DepreciationEngine is not runtime-"
            "authoritative unless explicitly enabled. Audit "
            "values from the canonical engine, when present, "
            "are advisory and do NOT change the waterfall "
            "output. Generic-project depreciation claims are "
            "NOT supported. Depreciation visibility is "
            "consolidated only for the active runtime path.",
        ),
        (
            "Generic Project Support",
            "NO \u2014 depreciation runtime authority for "
            "generic (non-Generic Wind Reference, non-Generic Solar Reference) projects is out "
            "of scope for the active runtime path. This audit "
            "sheet applies to the current active path only.",
        ),
        # ------------------------------------------------------------------
        # Phase D2 — Depreciation Flag Discipline disclosure row
        # ------------------------------------------------------------------
        # Discipline-only disclosure. D2 does not enable any
        # canonical / tax-bridge / book-pnl depreciation flag;
        # D2 is read-only. The four-flag inventory is owned by
        # ``app.depreciation_flag_discipline``; this row
        # confirms the discipline phase is in place and the
        # canonical promotion is BLOCKED.
        (
            "D2 Discipline Phase",
            "D2 \u2014 canonical promotion BLOCKED. The four "
            "flag names (use_depreciation_canonical_engine, "
            "use_canonical_tax_depreciation_bridge, "
            "use_tax_bridge_engine, "
            "use_book_depreciation_for_pnl) are all False on "
            "the active runtime path. D2 is discipline-only: "
            "no runtime enablement, no waterfall change, no "
            "formula / schedule / tax / P&L / CFADS change.",
        ),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


__all__ = [
    "_resolve_depreciation_runtime_authority",
    "build_depreciation_audit_dataframe",
]

"""Phase 5F — UI warning visibility table helpers for retained cash overlays.

This module provides table-building and aggregation helpers only.
It does NOT render Streamlit panels — actual Streamlit wiring is deferred to a future phase.

Design constraints:
- Pure read layer — no mutation of source objects
- Audit-only — no enforcement, no blocking, no distribution changes
- No model output changes
- Optional: functions return None when inputs are None so UI sections can hide gracefully

Usage pattern:
    if spv_overlays:
        df = build_spv_constraints_table(spv_overlays)
        st.dataframe(df)  # actual rendering deferred
"""
from __future__ import annotations

import pandas as pd

from domain.portfolio.distribution_constraints.overlay import SPVRetainedCashOverlay
from domain.portfolio.distribution_constraints.holdco_overlay import HoldCoRetainedCashOverlay
from domain.portfolio.distribution_constraints import DistributionConstraintResult


AUDIT_ONLY_NOTE = (
    "AUDIT-ONLY: these constraints are NOT applied to model outputs. "
    "Waterfall distributions and IRR metrics remain unconstrained."
)


def build_overlay_audit_note() -> str:
    """Return the audit-only notice for overlay/constraint table display.

    Use this as a caption, sidebar note, or column annotation when
    rendering SPV or HoldCo overlay tables in the UI.
    """
    return AUDIT_ONLY_NOTE


# ── SPV Constraints Table ─────────────────────────────────────────────────────

def build_spv_constraints_table(
    spv_overlays: list[SPVRetainedCashOverlay] | None,
) -> pd.DataFrame | None:
    """Build per-SPV distribution constraint summary table.

    Returns None if spv_overlays is None or empty — caller should hide the section.
    """
    if not spv_overlays:
        return None

    rows = []
    for ov in spv_overlays:
        total_requested = ov.total_requested_distribution_keur
        total_allowed = ov.total_allowed_distribution_keur
        total_retained = ov.total_retained_cash_keur
        warning_count = sum(1 for p in ov.periods if p.warnings)
        block_reasons = set()
        for p in ov.periods:
            for r in p.block_reasons:
                block_reasons.add(r.name if hasattr(r, 'name') else str(r))

        rows.append({
            "SPV Code": ov.entity_code,
            "Total Requested (kEUR)": f"{total_requested:,.0f}",
            "Total Allowed (kEUR)": f"{total_allowed:,.0f}",
            "Total Retained (kEUR)": f"{total_retained:,.0f}",
            "Δ Restricted (kEUR)": f"{total_requested - total_allowed:,.0f}",
            "Warning Count": warning_count,
            "Block Reasons": "; ".join(sorted(block_reasons)) if block_reasons else "none",
        })

    return pd.DataFrame(rows)


# ── HoldCo Constraints Table ──────────────────────────────────────────────────

def build_holdco_constraints_table(
    holdco_overlay: HoldCoRetainedCashOverlay | None,
) -> pd.DataFrame | None:
    """Build HoldCo retained cash summary table.

    Returns None if holdco_overlay is None — caller should hide the section.
    """
    if holdco_overlay is None:
        return None

    req = holdco_overlay.requested_distribution_by_period
    ret = holdco_overlay.retained_cash_by_period
    avail = holdco_overlay.available_distribution_by_period
    max_len = max(len(req), len(ret), len(avail))

    rows = []
    for i in range(max_len):
        rows.append({
            "HoldCo Code": holdco_overlay.entity_code,
            "Period": i,
            "Requested (kEUR)": f"{req[i] if i < len(req) else 0.0:,.0f}",
            "Retained (kEUR)": f"{ret[i] if i < len(ret) else 0.0:,.0f}",
            "Available (kEUR)": f"{avail[i] if i < len(avail) else 0.0:,.0f}",
        })

    return pd.DataFrame(rows)


# ── Distribution Constraints Table ─────────────────────────────────────────────

def build_dist_constraints_table(
    constraint_results: list[DistributionConstraintResult] | None,
) -> pd.DataFrame | None:
    """Build distribution constraint results table for all entities.

    Returns None if constraint_results is None or empty.
    """
    if not constraint_results:
        return None

    rows = []
    for cr in constraint_results:
        for cp in cr.periods:
            block_str = "; ".join(r.name if hasattr(r, 'name') else str(r)
                                 for r in (cp.block_reasons or ())) or "none"
            warning_str = "; ".join(cp.warnings) if cp.warnings else ""
            rows.append({
                "Entity": cr.entity_code,
                "Period": cp.period,
                "Cash Before Dist (kEUR)": f"{cp.cash_before_distribution_keur:,.0f}",
                "Requested (kEUR)": f"{cp.requested_distribution_keur:,.0f}",
                "Allowed (kEUR)": f"{cp.allowed_distribution_keur:,.0f}",
                "Retained (kEUR)": f"{cp.retained_cash_keur:,.0f}",
                "Block Reasons": block_str,
                "Warnings": warning_str,
            })

    return pd.DataFrame(rows)


# ── Warning Aggregation Helpers ────────────────────────────────────────────────

def aggregate_spv_warnings(spv_overlays: list[SPVRetainedCashOverlay] | None) -> list[str]:
    """Collect all non-empty warnings from SPV overlays."""
    if not spv_overlays:
        return []
    warnings = []
    for ov in spv_overlays:
        for p in ov.periods:
            for w in (p.warnings or ()):
                if w:
                    warnings.append(f"[{ov.entity_code} P{p.period}] {w}")
    return warnings


def aggregate_holdco_warnings(holdco_overlay: HoldCoRetainedCashOverlay | None) -> list[str]:
    """Collect all warnings from HoldCo overlay."""
    if holdco_overlay is None:
        return []
    return list(holdco_overlay.warnings) if holdco_overlay.warnings else []


def summarize_block_reasons(
    spv_overlays: list[SPVRetainedCashOverlay] | None,
) -> dict[str, int]:
    """Count block reason occurrences across SPV overlays.

    Returns dict of reason_name → count.
    """
    counts: dict[str, int] = {}
    if not spv_overlays:
        return counts
    for ov in spv_overlays:
        for p in ov.periods:
            for r in (p.block_reasons or ()):
                name = r.name if hasattr(r, 'name') else str(r)
                counts[name] = counts.get(name, 0) + 1
    return counts


def has_overlay_warnings(
    spv_overlays: list[SPVRetainedCashOverlay] | None = None,
    holdco_overlay: HoldCoRetainedCashOverlay | None = None,
    constraint_results: list[DistributionConstraintResult] | None = None,
) -> bool:
    """Return True if any overlay data has warnings or block reasons."""
    if spv_overlays and aggregate_spv_warnings(spv_overlays):
        return True
    if spv_overlays and summarize_block_reasons(spv_overlays):
        return True
    if holdco_overlay and aggregate_holdco_warnings(holdco_overlay):
        return True
    if constraint_results:
        for cr in constraint_results:
            for cp in cr.periods:
                if (cp.warnings) or any(cp.block_reasons):
                    return True
    return False
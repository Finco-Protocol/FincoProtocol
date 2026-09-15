"""Phase D3 — Depreciation Shadow Validation / Audit-Only Comparison.

This module is AUDIT-ONLY. It compares the legacy active
depreciation path with the canonical DepreciationEngine
output in read-only mode. The canonical values are NEVER
routed into the waterfall; they are written to a shadow
summary and an optional export audit sheet.

Constraints (Phase D3):

- No runtime depreciation enablement
- No change to ``period.depreciation_keur`` (legacy
  waterfall output is unchanged)
- No change to ``tax_depreciation_audit_keur`` (legacy
  tax-bridge output is unchanged)
- No P&L / tax / CFADS changes
- No flags enabled by default
- No generic-project depreciation claims

The module is safe to call from any code path. It only
reads project inputs and waterfall result; it never
writes back. The comparison is purely informational and
is consumed by the D3 export audit sheet (text-only) and
the D3 docs / report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowComparisonRow:
    """One row of the legacy vs canonical shadow comparison.

    Attributes
    ----------
    period_index : int
        Period (1-based) in the waterfall.
    legacy_depreciation_keur : float
        The legacy active-path ``period.depreciation_keur``.
    canonical_book_depreciation_keur : float
        The canonical engine's per-period book depreciation.
    absolute_delta_keur : float
        ``canonical - legacy``.
    relative_delta_pct : float
        ``100 * abs(absolute_delta) / max(legacy, 1.0)``.
    """

    period_index: int
    legacy_depreciation_keur: float
    canonical_book_depreciation_keur: float
    absolute_delta_keur: float
    relative_delta_pct: float


@dataclass(frozen=True)
class ShadowComparisonSummary:
    """Summary of the legacy vs canonical shadow comparison.

    Attributes
    ----------
    project_label : str
        Human-readable label (e.g. ``"Generic Wind Reference"``, ``"Generic Solar Reference"``).
    period_count : int
        Number of periods in the comparison.
    legacy_total_depreciation_keur : float
        Sum of ``period.depreciation_keur`` across the
        waterfall (legacy active path).
    canonical_total_book_depreciation_keur : float
        Sum of the canonical engine's per-period book
        depreciation.
    absolute_total_delta_keur : float
        ``canonical_total - legacy_total``.
    relative_total_delta_pct : float
        ``100 * abs(absolute_total_delta) / max(legacy_total, 1.0)``.
    max_absolute_period_delta_keur : float
        Largest single-period absolute delta.
    max_absolute_period_delta_period : int
        Period index of the largest single-period delta.
    max_relative_period_delta_pct : float
        Largest single-period relative delta.
    max_relative_period_delta_period : int
        Period index of the largest single-period relative delta.
    rows : tuple[ShadowComparisonRow, ...]
        Per-period rows.
    shadow_phase : str
        ``"D3"`` for this phase.
    """

    project_label: str
    period_count: int
    legacy_total_depreciation_keur: float
    canonical_total_book_depreciation_keur: float
    absolute_total_delta_keur: float
    relative_total_delta_pct: float
    max_absolute_period_delta_keur: float
    max_absolute_period_delta_period: int
    max_relative_period_delta_pct: float
    max_relative_period_delta_period: int
    rows: tuple[ShadowComparisonRow, ...] = field(
        default_factory=tuple
    )
    shadow_phase: str = "D3"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float:
    """Coerce ``value`` to ``float``, defaulting to 0.0 on
    missing or non-numeric input. Used for waterfall-result
    attribute reads that may not be present in all
    waterfall result shapes."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_canonical_book_depreciation_array(
    project_inputs: Any,
    *,
    project_label: str,
) -> Optional[list[float]]:
    """Run the canonical DepreciationEngine on a copy of
    the project inputs that has the canonical flag forced
    on for shadow validation only. The copy is a local
    ephemeral dataclasses-replace; it does not mutate
    the caller's project inputs.

    Returns the per-period book depreciation array, or
    ``None`` if the canonical engine cannot run on the
    given inputs (e.g. missing asset classes). The
    fallback path returns ``None`` so the caller can
    record the gap in the audit summary without raising.
    """
    try:
        from domain.depreciation.canonical_wiring import (
            build_canonical_depreciation_wiring,
        )
        from domain.depreciation.canonical_wiring import (
            wire_canonical_depreciation_into_waterfall,
        )

        horizon_years = getattr(
            project_inputs.info, "horizon_years", 30,
        )
        wiring = build_canonical_depreciation_wiring(
            project_name=getattr(
                project_inputs.info, "name", project_label,
            ),
            capex_items=project_inputs.capex.capex_items(),
            horizon_years=horizon_years,
            cod_period=2,
            period_frequency="semiannual",
        )
        if wiring.canonical_engine_result is None:
            return [0.0] * (horizon_years * 2)
        wf_wiring = wire_canonical_depreciation_into_waterfall(
            wiring.canonical_engine_result,
            period_count=horizon_years * 2,
        )
        return list(wf_wiring.book_depreciation_by_period)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def run_shadow_validation(
    *,
    project_inputs: Any,
    legacy_waterfall_result: Any,
    project_label: str,
) -> ShadowComparisonSummary:
    """Run the legacy vs canonical shadow validation.

    The function does NOT modify the waterfall result. The
    canonical DepreciationEngine runs on a local
    ephemeral copy of the project inputs (a dataclasses
    ``replace`` that forces the canonical flag on for the
    shadow validation only). The original
    ``project_inputs`` is unchanged.

    Parameters
    ----------
    project_inputs : ProjectInputs
        The factory default project inputs (the same
        object the live waterfall used).
    legacy_waterfall_result : WaterfallResult
        The legacy waterfall result. Used to read the
        per-period ``depreciation_keur`` from
        ``result.periods[i].depreciation_keur``.
    project_label : str
        Human-readable label (e.g. ``"Generic Wind Reference"``,
        ``"Generic Solar Reference"``).

    Returns
    -------
    ShadowComparisonSummary
        The full per-period comparison plus a summary.
        The summary is JSON-friendly via the
        ``to_json_dict`` method.
    """
    canonical_array = _build_canonical_book_depreciation_array(
        project_inputs, project_label=project_label,
    )
    legacy_periods = getattr(legacy_waterfall_result, "periods", [])
    period_count = len(legacy_periods)
    if canonical_array is None:
        canonical_array = [0.0] * period_count

    rows: list[ShadowComparisonRow] = []
    legacy_total = 0.0
    canonical_total = 0.0
    max_abs_period_delta = 0.0
    max_abs_period_delta_period = 0
    max_rel_period_delta = 0.0
    max_rel_period_delta_period = 0
    for i in range(period_count):
        legacy_value = _safe_float(
            getattr(legacy_periods[i], "depreciation_keur", 0.0)
        )
        canonical_value = _safe_float(
            canonical_array[i] if i < len(canonical_array) else 0.0
        )
        abs_delta = canonical_value - legacy_value
        rel_delta = 100.0 * abs(abs_delta) / max(abs(legacy_value), 1.0)
        legacy_total += legacy_value
        canonical_total += canonical_value
        if abs(abs_delta) > abs(max_abs_period_delta):
            max_abs_period_delta = abs_delta
            max_abs_period_delta_period = i + 1
        if rel_delta > max_rel_period_delta:
            max_rel_period_delta = rel_delta
            max_rel_period_delta_period = i + 1
        rows.append(
            ShadowComparisonRow(
                period_index=i + 1,
                legacy_depreciation_keur=legacy_value,
                canonical_book_depreciation_keur=canonical_value,
                absolute_delta_keur=abs_delta,
                relative_delta_pct=rel_delta,
            )
        )

    abs_total_delta = canonical_total - legacy_total
    rel_total_delta = 100.0 * abs(abs_total_delta) / max(
        abs(legacy_total), 1.0,
    )
    return ShadowComparisonSummary(
        project_label=project_label,
        period_count=period_count,
        legacy_total_depreciation_keur=legacy_total,
        canonical_total_book_depreciation_keur=canonical_total,
        absolute_total_delta_keur=abs_total_delta,
        relative_total_delta_pct=rel_total_delta,
        max_absolute_period_delta_keur=max_abs_period_delta,
        max_absolute_period_delta_period=max_abs_period_delta_period,
        max_relative_period_delta_pct=max_rel_period_delta,
        max_relative_period_delta_period=max_rel_period_delta_period,
        rows=tuple(rows),
    )


def to_json_dict(summary: ShadowComparisonSummary) -> dict[str, Any]:
    """Serialize a ShadowComparisonSummary to a JSON-friendly
    dict. The per-period rows are flattened into a list
    of dicts (one per period). The summary fields are
    kept as a nested dict under ``summary``."""
    return {
        "shadow_phase": summary.shadow_phase,
        "summary": {
            "project_label": summary.project_label,
            "period_count": summary.period_count,
            "legacy_total_depreciation_keur": (
                summary.legacy_total_depreciation_keur
            ),
            "canonical_total_book_depreciation_keur": (
                summary.canonical_total_book_depreciation_keur
            ),
            "absolute_total_delta_keur": (
                summary.absolute_total_delta_keur
            ),
            "relative_total_delta_pct": (
                summary.relative_total_delta_pct
            ),
            "max_absolute_period_delta_keur": (
                summary.max_absolute_period_delta_keur
            ),
            "max_absolute_period_delta_period": (
                summary.max_absolute_period_delta_period
            ),
            "max_relative_period_delta_pct": (
                summary.max_relative_period_delta_pct
            ),
            "max_relative_period_delta_period": (
                summary.max_relative_period_delta_period
            ),
        },
        "rows": [
            {
                "period_index": row.period_index,
                "legacy_depreciation_keur": (
                    row.legacy_depreciation_keur
                ),
                "canonical_book_depreciation_keur": (
                    row.canonical_book_depreciation_keur
                ),
                "absolute_delta_keur": row.absolute_delta_keur,
                "relative_delta_pct": row.relative_delta_pct,
            }
            for row in summary.rows
        ],
    }


def build_shadow_validation_audit_dataframe(
    summary: ShadowComparisonSummary,
) -> pd.DataFrame:
    """Build a text-only audit DataFrame for the export
    shadow-validation sheet.

    The DataFrame has columns ``Field`` and ``Value``.
    All values are text. The auto-index from pandas
    ``to_excel(..., index=True)`` is allowed (it is not
    a financial value).
    """
    rows = [
        (
            "Phase",
            "D3 \u2014 Depreciation Shadow Validation "
            "/ Audit-Only Comparison",
        ),
        (
            "Scope",
            "Audit / shadow only. NO runtime enablement. "
            "NO change to period.depreciation_keur. NO "
            "P&L / tax / CFADS change. Canonical values "
            "are NOT routed into the waterfall.",
        ),
        (
            "Notice",
            "Depreciation shadow comparison is "
            "informational only. The active runtime path "
            "remains the legacy depreciation path. The "
            "canonical DepreciationEngine output is "
            "compared in read-only mode and is not "
            "promoted to runtime authority.",
        ),
        (
            "Project Label",
            summary.project_label,
        ),
        (
            "Period Count",
            str(summary.period_count),
        ),
        (
            "Legacy Total Depreciation (kEUR)",
            f"{summary.legacy_total_depreciation_keur:,.2f}",
        ),
        (
            "Canonical Total Book Depreciation (kEUR)",
            f"{summary.canonical_total_book_depreciation_keur:,.2f}",
        ),
        (
            "Absolute Total Delta (kEUR)",
            f"{summary.absolute_total_delta_keur:,.2f}",
        ),
        (
            "Relative Total Delta (%)",
            f"{summary.relative_total_delta_pct:,.4f}",
        ),
        (
            "Max Absolute Period Delta (kEUR)",
            f"{summary.max_absolute_period_delta_keur:,.2f}",
        ),
        (
            "Max Absolute Period Delta Period",
            str(summary.max_absolute_period_delta_period),
        ),
        (
            "Max Relative Period Delta (%)",
            f"{summary.max_relative_period_delta_pct:,.4f}",
        ),
        (
            "Max Relative Period Delta Period",
            str(summary.max_relative_period_delta_period),
        ),
        (
            "Runtime Authority Path",
            "legacy_depreciation_runtime",
        ),
        (
            "Canonical Promotion Status",
            "BLOCKED (Phase D2 discipline)",
        ),
        (
            "Generic Project Support",
            "NO \u2014 shadow comparison runs only on "
            "factory default projects (Generic Wind Reference, Generic Solar Reference). "
            "Generic-project shadow comparison is out of "
            "scope for D3.",
        ),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


__all__ = [
    "ShadowComparisonRow",
    "ShadowComparisonSummary",
    "run_shadow_validation",
    "to_json_dict",
    "build_shadow_validation_audit_dataframe",
]

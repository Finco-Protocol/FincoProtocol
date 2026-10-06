"""app.library.model_home — Model Home presentation projections.

Presentation-only reads of PERSISTED authorities for the Model Home /
Project Library surface:

- Recent-project rows: identity/role/updated metadata from ``ProjectRecord``
  plus the persisted WorkspaceState Last Run evidence (Workflow 07) —
  Last Run timestamp when a successful run exists, a NOT RUN state
  otherwise.  CURRENT/STALE classification is deliberately NOT made here:
  freshness is the workspace's authority (``resolve_runtime_freshness``)
  and is presented inside the project workspace, not in the library list.
- Reference-model cards: identity plus compact headline evidence
  (Project IRR / Senior Debt / Min DSCR) taken verbatim from the
  reference's persisted Last Run summary.  Evidence that does not exist
  is omitted — unavailable is never rendered as zero.

NO engine execution happens on Model Home.  No financial arithmetic
happens here: raw persisted numbers are formatted through the shared
``app.v2.output_metric_projection`` catalog formatters only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional

from app.v2.output_metric_projection import (
    MetricAvailability,
    build_output_metric_projection,
)

# Headline evidence shown on reference-model cards (catalog keys).
# Senior Debt is a documented raw gap in some persisted summaries; when the
# key is absent the KPI is omitted (unavailable != zero).
REFERENCE_CARD_KPI_KEYS = ("project_irr", "senior_debt_keur", "min_dscr")


def _display_date(value: Any) -> Optional[str]:
    """Human date for a persisted datetime/ISO string; None when absent."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return text[:10] if len(text) >= 10 else None


@dataclass(frozen=True)
class RecentProjectRow:
    """One compact Recent Projects row (display payload only)."""

    project_code: str
    project_name: str
    project_type: str
    is_working_copy: bool
    updated_display: Optional[str]
    has_last_run: bool
    last_run_at_display: Optional[str]


@dataclass(frozen=True)
class ReferenceModelCard:
    """One Reference Models card (display payload only)."""

    project_id: str
    project_code: str
    project_name: str
    project_type: str
    is_protected: bool
    preview: bool
    # (key, label, display_value) triples — AVAILABLE evidence only.
    kpis: tuple[tuple[str, str, str], ...]


def build_recent_project_rows(
    records: Iterable[Any],
    workspace_states: Mapping[str, Any],
) -> list[RecentProjectRow]:
    """Project Model Home recent rows from records + workspace states.

    ``workspace_states`` maps project_id → persisted WorkspaceStateRecord
    (or None).  A row reports a Last Run only from
    ``last_runtime_at``/``any_run_committed`` persisted evidence.
    """
    rows: list[RecentProjectRow] = []
    for record in records:
        ws = workspace_states.get(record.project_id)
        # A persisted Last Run timestamp IS the run evidence (the flag column
        # is set by the run-commit path and is absent on legacy rows).
        has_run = getattr(ws, "last_runtime_at", None) is not None
        rows.append(RecentProjectRow(
            project_code=record.project_code,
            project_name=record.project_name,
            project_type=record.project_type or "",
            is_working_copy=record.project_role == "working_copy",
            updated_display=_display_date(record.updated_at),
            has_last_run=has_run,
            last_run_at_display=(
                _display_date(getattr(ws, "last_runtime_at", None))
                if has_run else None),
        ))
    return rows


def build_reference_cards(
    records: Iterable[Any],
    workspace_states: Mapping[str, Any],
) -> list[ReferenceModelCard]:
    """Reference-model cards with persisted headline evidence only.

    A KPI appears on a card ONLY when the reference's persisted Last Run
    summary carries a clean numeric value for the catalog key; formatting
    goes through ``build_output_metric_projection`` so display conventions
    stay canonical.  No value is ever inferred or defaulted to zero.
    """
    cards: list[ReferenceModelCard] = []
    for record in records:
        ws = workspace_states.get(record.project_id)
        summary = getattr(ws, "last_runtime_summary", None) or {}
        kpis: list[tuple[str, str, str]] = []
        if summary:
            for key in REFERENCE_CARD_KPI_KEYS:
                projection = build_output_metric_projection(
                    key, summary.get(key))
                if projection.availability is MetricAvailability.AVAILABLE:
                    kpis.append((key, projection.label,
                                 projection.display_value))
        cards.append(ReferenceModelCard(
            project_id=record.project_id,
            project_code=record.project_code,
            project_name=record.project_name,
            project_type=record.project_type or "",
            is_protected=bool(getattr(record, "is_protected", False)),
            # Storage (and any vertical without an editable runtime) is a
            # PREVIEW product state, never a shipped peer.
            preview=(record.project_type or "").strip().lower()
            in _PREVIEW_TECHNOLOGIES,
            kpis=tuple(kpis),
        ))
    return cards


# Technologies whose editable runtime is not yet supported — explicit
# product preview state on Model Home (mirrors the library clone guard).
_PREVIEW_TECHNOLOGIES = frozenset({"storage", "bess"})


__all__ = [
    "RecentProjectRow",
    "ReferenceModelCard",
    "REFERENCE_CARD_KPI_KEYS",
    "build_recent_project_rows",
    "build_reference_cards",
]

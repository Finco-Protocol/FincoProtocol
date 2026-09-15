"""
Workbook V2 — RuntimeResult: canonical domain object for one engine run.

Architecture position:

  WaterfallRunner.run()
      ↓
  run_project() → result dict (kpis, financial_statements, debt_schedule, …)
      ↓
  RuntimeResult                          ← immutable aggregate of all run output
      │
      ├─ .runtime_summary                ← RuntimeSummary dict (KPIs)
      ├─ .financial_statements           ← FS payload (or None)
      ├─ .debt_schedule                  ← debt schedule payload (or None)
      ├─ .tax_schedule                   ← tax schedule payload (or None)
      ├─ .distribution_schedule          ← distribution schedule payload (or None)
      ├─ .sponsor_schedule               ← sponsor schedule payload (or None)
      ├─ .to_sessionstorage_script()     ← JS that hydrates sessionStorage on page load
      └─ .from_workspace_state(ws)       ← reconstruct from persisted WorkspaceStateRecord

Design invariants:
- RuntimeResult is immutable (frozen dataclass).
- All schedule payloads are optional — a successful run may produce no sponsor
  schedule (generic_wind projects) or no distribution schedule.
- to_sessionstorage_script() emits the same JS that run_service._build_sessionstorage_save_tag()
  would emit for the same payloads, so sessionStorage can be hydrated from the
  DB-persisted RuntimeResult on page load without a model re-run.
- DB is the authoritative store.  sessionStorage is a write-through cache:
  populated during a run (by run_service) and on page load (by main_web via
  RuntimeResult.to_sessionstorage_script()).  sessionStorage is NOT the source of truth.
- No engine code, no formula code, no parity target code is touched here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Optional

from app.utils.script_json import dumps_for_script as _dumps_for_script


class _FrozenEncoder(json.JSONEncoder):
    """JSON encoder that serialises MappingProxyType as dict."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, MappingProxyType):
            return dict(obj)
        return super().default(obj)

    def encode(self, obj: Any) -> str:
        # Intercept the full structure so nested MappingProxyType is handled.
        return super().encode(self._thaw(obj))

    @staticmethod
    def _thaw(obj: Any) -> Any:
        """Recursively convert MappingProxyType → dict for JSON serialisation."""
        if isinstance(obj, MappingProxyType):
            return {k: _FrozenEncoder._thaw(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_FrozenEncoder._thaw(item) for item in obj]
        return obj


def _dumps(obj: Any) -> str:
    """json.dumps that handles MappingProxyType at every nesting level."""
    return json.dumps(_FrozenEncoder._thaw(obj))


def _dumps_script_safe(obj: Any) -> str:
    """HTML-script-safe variant of _dumps: escapes <, >, &, U+2028, U+2029."""
    return _dumps_for_script(_FrozenEncoder._thaw(obj))

if TYPE_CHECKING:
    from app.persistence.records import WorkspaceStateRecord


def _freeze(obj: Any) -> Any:
    """Recursively convert JSON-like dicts into MappingProxyType (read-only).

    dict  → MappingProxyType, with each value recursively frozen.
    list  → new list whose elements are recursively frozen.
              Lists stay as lists so that equality checks against plain Python
              structures (e.g. ``rr.financial_statements == SAMPLE_FS``) continue
              to work; it is the *dict* nodes at every depth that become read-only.
    other → returned as-is (str, int, float, bool, None are already immutable).

    This guarantees that direct dict mutation fails at *every* nesting level
    (rr.runtime_summary["k"] = v raises TypeError; so does
    rr.financial_statements["periods"][0]["revenue_keur"] = v).
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_freeze(item) for item in obj]
    return obj

# sessionStorage key names — single source of truth in the Python layer.
# Templates read these keys; they must never diverge.
_SS_KEY_FINANCIAL_STATEMENTS = "lastFinancialStatements"
_SS_KEY_DEBT_SCHEDULE = "lastDebtSchedule"
_SS_KEY_TAX_SCHEDULE = "lastTaxSchedule"
_SS_KEY_DISTRIBUTION_SCHEDULE = "lastDistributionSchedule"
_SS_KEY_SPONSOR_SCHEDULE = "lastSponsorSchedule"
_SS_KEY_RUNTIME_SUMMARY = "lastRuntimeSummary"


@dataclass(frozen=True)
class RuntimeResult:
    """
    Immutable aggregate of all output from one WaterfallRunner run.

    Produced by the run_service after a successful engine call and
    persisted to the DB so that schedule data survives page refresh.

    Attributes
    ----------
    snapshot_id : str
        Compact UTC ISO string identifying this run (e.g. "20260710T123456Z").
        Matches WorkspaceStateRecord.last_runtime_snapshot_id.

    ran_at : str
        Full ISO-8601 UTC timestamp when the run completed.

    origin : str
        Run provenance: "saved_state" | "workspace_base" | form-origin value.

    runtime_summary : dict[str, Any]
        RuntimeSummary.to_dict() — KPI dict (project_irr, equity_irr, avg_dscr,
        total_revenue_keur, …).  Always present on a successful run.

    financial_statements : dict[str, Any] | None
        Payload from assemble_financial_statements().  None when not produced.

    debt_schedule : dict[str, Any] | None
        Payload from _serialize_debt_schedule().  None when not produced.

    tax_schedule : dict[str, Any] | None
        Payload from _serialize_tax_schedule().  None when not produced.

    distribution_schedule : dict[str, Any] | None
        Payload from _serialize_distribution_schedule().  None when not produced.

    sponsor_schedule : dict[str, Any] | None
        Payload from _serialize_sponsor_schedule().  None when not produced.
    """

    snapshot_id: str
    ran_at: str
    origin: str
    runtime_summary: dict[str, Any]
    financial_statements: Optional[dict[str, Any]]
    debt_schedule: Optional[dict[str, Any]]
    tax_schedule: Optional[dict[str, Any]]
    distribution_schedule: Optional[dict[str, Any]]
    sponsor_schedule: Optional[dict[str, Any]]

    def __post_init__(self) -> None:
        """Freeze all mutable payload fields so nested mutation also fails.

        frozen=True prevents attribute *re-assignment*, but a plain dict
        field can still be mutated in-place (e.g. rr.runtime_summary["k"] = 1).
        _freeze() converts every dict/list recursively to MappingProxyType/tuple
        so that neither top-level nor nested mutation is possible.

        object.__setattr__ is required because frozen=True blocks normal assignment.
        """
        _PAYLOAD_FIELDS = (
            "runtime_summary",
            "financial_statements",
            "debt_schedule",
            "tax_schedule",
            "distribution_schedule",
            "sponsor_schedule",
        )
        for field in _PAYLOAD_FIELDS:
            val = getattr(self, field)
            if val is not None:
                object.__setattr__(self, field, _freeze(val))

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_run_result(
        cls,
        result: dict[str, Any],
        *,
        runtime_summary: dict[str, Any],
        snapshot_id: str,
        ran_at: str,
        origin: str,
    ) -> "RuntimeResult":
        """
        Build a RuntimeResult from the dict returned by run_project().

        Parameters
        ----------
        result : dict
            The dict from run_project() with keys: kpis, financial_statements,
            debt_schedule, tax_schedule, distribution_schedule, sponsor_schedule, …
        runtime_summary : dict
            Pre-built RuntimeSummary.to_dict() (already formatted by run_service).
        snapshot_id : str
            Compact UTC ISO run identifier.
        ran_at : str
            Full ISO-8601 UTC timestamp.
        origin : str
            Run provenance label.
        """
        return cls(
            snapshot_id=snapshot_id,
            ran_at=ran_at,
            origin=origin,
            runtime_summary=runtime_summary,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )

    @classmethod
    def from_workspace_state(cls, ws: "WorkspaceStateRecord") -> Optional["RuntimeResult"]:
        """
        Reconstruct a RuntimeResult from a persisted WorkspaceStateRecord.

        Returns None when no run has been persisted (last_runtime_snapshot_id
        is absent or last_runtime_summary is empty).
        """
        if not ws.last_runtime_snapshot_id:
            return None
        if not ws.last_runtime_summary:
            return None

        def _non_empty(d: dict) -> Optional[dict]:
            return d if d else None

        return cls(
            snapshot_id=ws.last_runtime_snapshot_id or "",
            ran_at=(
                ws.last_runtime_at.isoformat()
                if ws.last_runtime_at is not None
                else ""
            ),
            origin=ws.last_runtime_origin or "",
            runtime_summary=ws.last_runtime_summary,
            financial_statements=_non_empty(getattr(ws, "last_financial_statements", {}) or {}),
            debt_schedule=_non_empty(getattr(ws, "last_debt_schedule", {}) or {}),
            tax_schedule=_non_empty(getattr(ws, "last_tax_schedule", {}) or {}),
            distribution_schedule=_non_empty(getattr(ws, "last_distribution_schedule", {}) or {}),
            sponsor_schedule=_non_empty(getattr(ws, "last_sponsor_schedule", {}) or {}),
        )

    # ------------------------------------------------------------------ #
    # sessionStorage hydration                                             #
    # ------------------------------------------------------------------ #

    def to_sessionstorage_script(self) -> str:
        """
        Return a ``<script>`` block that hydrates sessionStorage from this
        RuntimeResult.

        Emits the same JS format that run_service._build_sessionstorage_save_tag()
        produces, so the templates read identically from a run-time write and
        from a page-load restore.

        The double-serialization (json.dumps(json.dumps(payload))) matches the
        existing convention used by _build_sessionstorage_save_tag().
        """
        parts: list[str] = []

        def _set_or_remove(key: str, payload: Optional[Any]) -> None:
            if payload:
                # Double-serialise using the HTML-script-safe serializer.
                # The inner call (_dumps_script_safe) converts the payload to a
                # JSON string with <, >, & and U+2028/U+2029 unicode-escaped so
                # an HTML parser cannot terminate the enclosing script element.
                # The outer json.dumps wraps that safe string in a JS string
                # literal.  Mirrors run_service._build_sessionstorage_save_tag().
                parts.append(
                    f'sessionStorage.setItem({json.dumps(key)}, '
                    + json.dumps(_dumps_script_safe(payload))
                    + ');'
                )
            else:
                parts.append(f'sessionStorage.removeItem({json.dumps(key)});')

        _set_or_remove(_SS_KEY_FINANCIAL_STATEMENTS, self.financial_statements)
        _set_or_remove(_SS_KEY_DEBT_SCHEDULE, self.debt_schedule)
        _set_or_remove(_SS_KEY_TAX_SCHEDULE, self.tax_schedule)
        _set_or_remove(_SS_KEY_DISTRIBUTION_SCHEDULE, self.distribution_schedule)
        _set_or_remove(_SS_KEY_SPONSOR_SCHEDULE, self.sponsor_schedule)
        parts.append(
            f'sessionStorage.setItem({json.dumps(_SS_KEY_RUNTIME_SUMMARY)}, '
            + json.dumps(_dumps_script_safe(self.runtime_summary))
            + ');'
        )

        if not parts:
            return ""
        return "<script>" + "".join(parts) + "</script>"

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def has_schedules(self) -> bool:
        """Return True if at least one schedule payload is present."""
        return any([
            self.financial_statements,
            self.debt_schedule,
            self.tax_schedule,
            self.distribution_schedule,
            self.sponsor_schedule,
        ])

    def __repr__(self) -> str:
        schedules = sum(1 for s in [
            self.financial_statements, self.debt_schedule, self.tax_schedule,
            self.distribution_schedule, self.sponsor_schedule,
        ] if s)
        return (
            f"RuntimeResult(snapshot_id={self.snapshot_id!r}, "
            f"origin={self.origin!r}, schedules={schedules}/5)"
        )

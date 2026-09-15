"""app.v2.output_metric_projection — Single presentation contract for KPI display.

OutputMetricProjection is the canonical way to pass a financial KPI from the
authoritative RuntimeResult to a template.  It carries the raw value alongside
the display string so templates never need to reformat and tests can assert
the raw value without parsing display strings.

No financial arithmetic is performed here.  All values originate from the
persisted RuntimeResult.  The builder functions are pure presentation formatters.

Authority contract (NO_FORMAT_PARSE_FORMAT):
  raw_value MUST be a raw numeric float from the engine output, or None.
  Pre-formatted strings such as "8.50%" or "1.45x" are NEVER accepted as
  raw_value inputs — that path is deleted.  The flow is:
      engine raw float  →  raw_value=0.085  →  display_value="8.50%"
  Never:
      display_value="8.50%"  →  parse back to float  →  raw_value=0.085
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


# Sentinel displayed when a value is unavailable — never "NOT_AVAILABLE"
NOT_AVAILABLE = "—"


class MetricAvailability(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"   # not in runtime_summary schema version
    RUN_REQUIRED = "run_required"     # no RuntimeResult exists
    STALE = "stale"                   # result exists but inputs changed


@dataclass(frozen=True)
class OutputMetricProjection:
    """Immutable presentation bundle for one financial KPI.

    Attributes
    ----------
    key : str
        Canonical identifier, e.g. ``"project_irr"``.
    label : str
        Human-readable label, e.g. ``"Project IRR"``.
    raw_value : float | None
        The authoritative raw value from RuntimeResult, or None when unavailable.
        MUST be a raw numeric — never a pre-formatted string.
    display_value : str
        Pre-formatted string for template rendering.  Either a human-friendly
        formatted number (``"8.50%"``) or the NOT_AVAILABLE sentinel (``"—"``).
        Never ``"NOT_AVAILABLE"`` — that sentinel must not reach templates.
    unit : str
        Unit label for axis/tooltip use, e.g. ``"%"``, ``"x"``, ``"kEUR"``.
        Empty string when not applicable.
    availability : MetricAvailability
        Whether the value is meaningful for the current model state.
    source : str
        Provenance tag — ``"runtime_summary"`` or ``"debt_schedule.summary"``.
    scenario_id : str | None
        Scenario this projection belongs to, or None for the active scenario.
    run_timestamp : str | None
        ISO-8601 timestamp of the run that produced this value, or None.
    freshness : str
        ``"current"`` | ``"stale"`` | ``"not_run"`` — mirrors model state
        in a template-friendly string.
    """

    key: str
    label: str
    raw_value: Optional[float]
    display_value: str                  # "8.50%" | "1.45x" | "—"
    unit: str                           # "%" | "x" | "kEUR" | ""
    availability: MetricAvailability
    source: str                         # "runtime_summary" | "debt_schedule.summary"
    scenario_id: Optional[str] = None
    run_timestamp: Optional[str] = None
    freshness: str = "not_run"          # "current" | "stale" | "not_run"

    @property
    def is_available(self) -> bool:
        return self.availability == MetricAvailability.AVAILABLE

    @property
    def is_stale(self) -> bool:
        return self.freshness == "stale"

    @property
    def css_freshness_class(self) -> str:
        """CSS modifier class for freshness indicator."""
        return {
            "current": "v2-kpi-tile--current",
            "stale":   "v2-kpi-tile--stale",
            "not_run": "v2-kpi-tile--notrun",
        }.get(self.freshness, "v2-kpi-tile--notrun")


# ── Canonical KPI catalog (consolidated with scenario_kpi_projection.KPI_CATALOG) ── #
#
# Single source of truth.  scenario_kpi_projection.KPI_CATALOG is a subset that
# re-exports from here for backwards compatibility.
#
# Tuple: (key, label, unit, fmt, source)
#   key    — canonical engine kpi dict key
#   label  — human display label
#   unit   — "%" | "x" | "kEUR" | ""
#   fmt    — "pct" | "ratio" | "keur"  (drives _fmt_*)
#   source — "runtime_summary" | "debt_schedule.summary"
#
# Raw authority gaps (NOT in result["kpis"] from project_runner.py):
#   senior_debt_keur   — not in kpis; documented gap, raw_value=None until upstream provides it
#   total_cfads_keur   — not in kpis; documented gap, raw_value=None until upstream provides it
KPI_CATALOG: list[tuple] = [
    ("project_irr",        "Project IRR",    "%",    "pct",   "runtime_summary"),
    ("equity_irr",         "Equity IRR",     "%",    "pct",   "runtime_summary"),
    ("min_dscr",           "Min DSCR",       "x",    "ratio", "runtime_summary"),
    ("avg_dscr",           "Avg DSCR",       "x",    "ratio", "runtime_summary"),
    ("min_llcr",           "Min LLCR",       "x",    "ratio", "debt_schedule.summary"),
    ("target_dscr",        "Target DSCR",    "x",    "ratio", "debt_schedule.summary"),
    ("senior_debt_keur",   "Senior Debt",    "kEUR", "keur",  "runtime_summary"),
    ("total_capex_keur",   "Total CAPEX",    "kEUR", "keur",  "runtime_summary"),
    ("total_revenue_keur", "Total Revenue",  "kEUR", "keur",  "runtime_summary"),
    ("total_ebitda_keur",  "Total EBITDA",   "kEUR", "keur",  "runtime_summary"),
    ("total_cfads_keur",   "Total CFADS",    "kEUR", "keur",  "runtime_summary"),
    ("equity_npv_keur",    "Equity NPV",     "kEUR", "keur",  "runtime_summary"),
]

# Fast lookup sets derived from catalog
_PCT_KEYS   = frozenset(k for k, *_, fmt, _ in KPI_CATALOG if fmt == "pct")
_RATIO_KEYS = frozenset(k for k, *_, fmt, _ in KPI_CATALOG if fmt == "ratio")
_KEUR_KEYS  = frozenset(k for k, *_, fmt, _ in KPI_CATALOG if fmt == "keur")


# ── Pure numeric formatters (accept raw float only) ─────────────────────── #

def _safe_float(v: Any) -> Optional[float]:
    """Convert a raw numeric value to float, returning None for non-numeric input.

    IMPORTANT: strings such as "8.50%" are considered non-numeric and return None.
    The caller must never pass a pre-formatted string expecting a meaningful float.
    """
    if v is None:
        return None
    if isinstance(v, str):
        # Strings are non-numeric in this context — pre-formatted strings must not
        # be fed here.  Return None so the display path produces "—".
        return None
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fmt_pct(f: float) -> str:
    """Format raw decimal fraction as percentage string. 0.085 → '8.50%'."""
    return f"{f * 100:.2f}%"


def _fmt_ratio(f: float) -> str:
    """Format raw float as 'X.XXx' coverage ratio. 1.32 → '1.32x'."""
    return f"{f:.2f}x"


def _fmt_keur(f: float) -> str:
    """Format raw float as thousands-separated kEUR string. 27000.0 → '27,000 kEUR'."""
    return f"{f:,.0f} kEUR"


def _apply_fmt(f: float, fmt: str) -> str:
    if fmt == "pct":
        return _fmt_pct(f)
    if fmt == "ratio":
        return _fmt_ratio(f)
    if fmt == "keur":
        return _fmt_keur(f)
    return str(f)


# ── Builder functions ─────────────────────────────────────────────────────── #

def build_output_metric_projection(
    key: str,
    raw_numeric: Any,
    *,
    freshness: str = "not_run",
    scenario_id: Optional[str] = None,
    run_timestamp: Optional[str] = None,
) -> OutputMetricProjection:
    """Build a single OutputMetricProjection from a raw numeric engine value.

    Parameters
    ----------
    key : str
        KPI catalog key, e.g. ``"project_irr"``.
    raw_numeric : float | int | None
        Raw authoritative value from engine output (RuntimeResult.kpis dict).
        MUST be numeric or None.  Pre-formatted strings are rejected — they
        produce raw_value=None and display_value="—".
    freshness : str
        ``"current"`` | ``"stale"`` | ``"not_run"``.
    """
    catalog_entry = next((c for c in KPI_CATALOG if c[0] == key), None)
    label  = catalog_entry[1] if catalog_entry else key
    unit   = catalog_entry[2] if catalog_entry else ""
    fmt    = catalog_entry[3] if catalog_entry else ""
    source = catalog_entry[4] if catalog_entry else "runtime_summary"

    raw_float = _safe_float(raw_numeric)

    if raw_float is None:
        display = NOT_AVAILABLE
        if freshness == "not_run":
            avail = MetricAvailability.RUN_REQUIRED
        elif freshness == "stale":
            avail = MetricAvailability.STALE
        else:
            avail = MetricAvailability.NOT_AVAILABLE
    else:
        display = _apply_fmt(raw_float, fmt)
        avail = MetricAvailability.AVAILABLE

    return OutputMetricProjection(
        key=key,
        label=label,
        raw_value=raw_float,
        display_value=display,
        unit=unit,
        availability=avail,
        source=source,
        scenario_id=scenario_id,
        run_timestamp=run_timestamp,
        freshness=freshness,
    )


def build_overview_metric_projections(
    runtime_summary: dict,
    debt_summary: dict,
    *,
    freshness: str = "not_run",
    scenario_id: Optional[str] = None,
    run_timestamp: Optional[str] = None,
) -> dict[str, OutputMetricProjection]:
    """Build all KPI projections for the Overview sheet.

    Returns a dict keyed by metric key for easy template access.
    All values sourced from already-persisted RuntimeResult — no arithmetic.

    raw_value correctness:
      - project_irr, equity_irr: decimal fractions (0.085 = 8.5%)
      - min_dscr, avg_dscr, min_llcr, target_dscr: ratios (1.15)
      - *_keur: absolute kEUR floats (27000.0)
      - senior_debt_keur, total_cfads_keur: NOT in result["kpis"] — raw_value=None (documented gap)
    """
    projections: dict[str, OutputMetricProjection] = {}

    for entry in KPI_CATALOG:
        key, _label, _unit, _fmt, source = entry
        if source == "runtime_summary":
            val = runtime_summary.get(key)
        else:
            val = debt_summary.get(key)
        projections[key] = build_output_metric_projection(
            key, val,
            freshness=freshness,
            scenario_id=scenario_id,
            run_timestamp=run_timestamp,
        )

    return projections


def extract_numeric_runtime_kpis(runtime_summary: Any) -> dict:
    """Extract canonical numeric KPI values from a v2 persisted runtime_summary dict.

    Fail-closed: only keys present in KPI_CATALOG are considered.
    Only int/float (non-NaN, non-inf) values pass; str/dict/list/bool/NaN/inf are
    rejected and excluded from the result.

    Parameters
    ----------
    runtime_summary : any
        Raw runtime_summary payload (may be MappingProxyType or plain dict).

    Returns
    -------
    dict[str, float]
        Filtered dict with only clean numeric KPI values.
    """
    if not runtime_summary:
        return {}
    rs: dict = dict(runtime_summary) if not isinstance(runtime_summary, dict) else runtime_summary
    allowed_keys = {entry[0] for entry in KPI_CATALOG}
    result: dict = {}
    for key in allowed_keys:
        v = rs.get(key)
        if v is None:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            try:
                f = float(v)
                if f != f or abs(f) == float("inf"):
                    continue
                result[key] = f
            except (TypeError, ValueError):
                continue
    return result

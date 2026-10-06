"""Model V2 Canonical Analytics - typed, run-bound, read-only surface.

Workflow 06 scope. Canonical Analytics is PRODUCTIZATION / NORMALIZATION of
outputs the canonical engine already calculated. It is NOT a calculator:

  - it never reruns the engine in production code;
  - it never reconstructs statements, cash flows, IRR, DSCR, LLCR/PLCR;
  - it never aggregates raw financial series (no sum/min/max of economics);
  - it never infers a missing metric from nearby values;
  - it never substitutes zero for an unavailable value.

Values pass through the Workflow 04 Calculation Trace verbatim (which itself
passes canonical results through verbatim), so the two surfaces cannot
disagree: Analytics answers "what is the canonical value/status/unit?",
Calculation Trace answers "where did that value come from?".

RUN-BOUND ONLY: a snapshot always carries a complete Workflow 04
``RunIdentity`` (snapshot id, composite hash, workbook/engine versions,
optional project/scenario ids). A Working Copy draft can never be presented
as a canonical run. If the Working Copy changes afterwards, the historical
snapshot is immutable content and still describes the Last Run until a new
successful canonical run exists. A failed run produces no snapshot at all.

Status semantics reuse the repository vocabulary where one exists: the
canonical engine status travels verbatim on every metric
(``source_status`` - e.g. CoverageStatus / ProjectNpvStatus /
ReturnMetricStatus values), and ``CanonicalMetricStatus`` expresses
availability using the run-integrity token spellings (UNAVAILABLE /
NOT_APPLICABLE) extended with AVAILABLE and AUTHORITY_MISSING (a metric
FINCO has no canonical authority for yet). MISSING != ZERO and
UNAVAILABLE != ZERO are structural: value is None unless status is
AVAILABLE, and a legitimate economic 0.0 stays AVAILABLE 0.0.

Deterministic: the same canonical run produces a byte-identical serialized
snapshot; the fingerprint is a content-integrity helper only and never
replaces run identity (Workflow 04 principle).

Governance: exact-path authorized support file under
docs/model_v2/ACTIVE_EPIC_SCOPE.json. domain/analytics/** remains frozen
and untouched; no Revenue Runtime (Workflow 05B) files are used.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from app.model_v2.assumption_register import (
    AssumptionContextKind,
    AssumptionSourceKind,
    RegisterContext,
    RunIdentity,
    ValuePresence,
    canonical_json,
)
from app.model_v2.calculation_trace import (
    TraceCompleteness,
    build_calculation_trace,
)

CANONICAL_ANALYTICS_SCHEMA_ID = "finco.model-v2.canonical-analytics"
CANONICAL_ANALYTICS_SCHEMA_VERSION = 1

GENERATED_FROM_AUTHORITY = (
    "app.services.production_financial_authority.run_clean_production -> "
    "financial_engine.shareholder_waterfall."
    "run_project_shareholder_waterfall_model (canonical G2C result)"
)


class CanonicalMetricStatus(str, Enum):
    """Availability semantics; token spellings follow run-integrity."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AUTHORITY_MISSING = "AUTHORITY_MISSING"


class MetricCategory(str, Enum):
    RETURNS = "RETURNS"
    VALUATION = "VALUATION"
    DEBT_COVERAGE = "DEBT_COVERAGE"
    OPERATING = "OPERATING"
    UNIT_ECONOMICS = "UNIT_ECONOMICS"
    FUTURE = "FUTURE"


# The canonical Workflow 04 trace output keys are REUSED as metric ids for
# every metric the trace carries (Workflow 06 contract: same stable output
# identity; Analytics never recalculates what Trace already passed through).
_TRACE_BACKED_METRICS: tuple[tuple[str, str, str], ...] = (
    # (metric_id == trace output_key, category, unit)
    ("project_xirr", "RETURNS", "fraction"),
    ("pure_equity_xirr", "RETURNS", "fraction"),
    ("total_sponsor_xirr", "RETURNS", "fraction"),
    ("project_npv_keur", "VALUATION", "kEUR"),
    ("senior_debt_keur", "DEBT_COVERAGE", "kEUR"),
    ("min_dscr", "DEBT_COVERAGE", "ratio"),
    ("min_llcr", "DEBT_COVERAGE", "ratio"),
    ("min_plcr", "DEBT_COVERAGE", "ratio"),
    ("total_revenue_keur", "OPERATING", "kEUR"),
    ("total_opex_keur", "OPERATING", "kEUR"),
    ("total_ebitda_keur", "OPERATING", "kEUR"),
    ("total_tax_keur", "OPERATING", "kEUR"),
)

# Canonical MOIC authorities live on the G2C result but are not (yet) trace
# outputs; values pass through verbatim from the canonical result objects.
_G2C_METRICS: tuple[tuple[str, str, str, str], ...] = (
    # (metric_id, category, unit, g2c attribute)
    ("pure_equity_moic", "RETURNS", "multiple", "pure_equity_moic"),
    ("total_sponsor_moic", "RETURNS", "multiple", "total_sponsor_moic"),
)
_MOIC_STATUS_ATTRS = {
    "pure_equity_moic": "pure_equity_moic_status",
    "total_sponsor_moic": "total_sponsor_moic_status",
}

# Reserved vocabulary for metrics FINCO has no canonical authority for yet
# (Workflow 06 contract: ids may be reserved; values may never be faked).
_FUTURE_METRICS: tuple[tuple[str, str, str], ...] = (
    ("lcoe", "UNIT_ECONOMICS", "EUR/MWh"),
    ("wacc", "FUTURE", "fraction"),
    ("payback", "FUTURE", "years"),
    ("discounted_payback", "FUTURE", "years"),
    ("cash_yield", "FUTURE", "fraction"),
)

_LCOE_AUTHORITY_NOTE = (
    "no canonical LCOE authority on the production path: "
    "domain/analytics/lcoe.py is a frozen orphaned extra (no production "
    "caller, dead component helper) and domain/analytics/scenarios.py "
    "carries only a private presentation variant; creating a Workflow 06 "
    "formula is forbidden - a reviewed canonical authority decision is the "
    "future seam"
)


@dataclass(frozen=True)
class CanonicalMetric:
    """One canonical output exposed verbatim with authority and status."""

    metric_id: str
    category: str
    value: float | int | None
    unit: str
    status: CanonicalMetricStatus
    source_status: str | None
    source_authority: str | None
    methodology_ref: str | None
    trace_ref: str | None
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "metric_id": self.metric_id,
            "category": self.category,
            "value": self.value,
            "unit": self.unit,
            "status": self.status.value,
            "source_status": self.source_status,
            "source_authority": self.source_authority,
            "methodology_ref": self.methodology_ref,
            "trace_ref": self.trace_ref,
            "notes": self.notes,
        }


def _metric_from_trace_entry(entry, category: str, unit: str) -> CanonicalMetric:
    """Map a Workflow 04 trace entry to a canonical metric (verbatim)."""
    if entry.value_presence is ValuePresence.PRESENT:
        status = CanonicalMetricStatus.AVAILABLE
    elif entry.completeness is TraceCompleteness.UNAVAILABLE:
        source_status = entry.status
        if source_status is not None and "NOT_APPLICABLE" in source_status:
            status = CanonicalMetricStatus.NOT_APPLICABLE
        else:
            status = CanonicalMetricStatus.UNAVAILABLE
    else:
        raise ValueError(
            f"ANALYTICS_TRACE_ENTRY_INVALID: trace entry {entry.output_key} "
            "has neither a value nor an UNAVAILABLE completeness; analytics "
            "refuses to guess."
        )
    return CanonicalMetric(
        metric_id=entry.output_key,
        category=category,
        value=entry.output_value,
        unit=unit,
        status=status,
        source_status=entry.status,
        source_authority=entry.authority,
        methodology_ref=entry.methodology_key,
        trace_ref=entry.output_key,
        notes=entry.notes,
    )


# ---------------------------------------------------------------------------
# Builder + snapshot container
# ---------------------------------------------------------------------------

_MOIC_AUTHORITY = (
    "financial_engine/shareholder_waterfall/model.py::"
    "run_project_shareholder_waterfall_model (CovenantGatedWaterfallResult)"
)


def _canonical_status_text(value):
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _moic_metric(g2c, metric_id, category, unit, attribute):
    raw = getattr(g2c, attribute)
    raw_status = getattr(g2c, _MOIC_STATUS_ATTRS[metric_id])
    source_status = _canonical_status_text(raw_status)
    if raw is not None:
        status = CanonicalMetricStatus.AVAILABLE
    elif source_status is not None and "NOT_APPLICABLE" in source_status:
        status = CanonicalMetricStatus.NOT_APPLICABLE
    else:
        status = CanonicalMetricStatus.UNAVAILABLE
    methodology = "equity_irr" if metric_id == "pure_equity_moic" else "total_sponsor_xirr"
    return CanonicalMetric(
        metric_id=metric_id,
        category=category,
        value=raw,
        unit=unit,
        status=status,
        source_status=source_status,
        source_authority=_MOIC_AUTHORITY,
        methodology_ref=methodology,
        trace_ref=None,
        notes="verbatim CovenantGatedWaterfallResult pass-through",
    )


def _future_metric(metric_id, category, unit, note):
    return CanonicalMetric(
        metric_id=metric_id,
        category=category,
        value=None,
        unit=unit,
        status=CanonicalMetricStatus.AUTHORITY_MISSING,
        source_status=None,
        source_authority=None,
        methodology_ref=None,
        trace_ref=None,
        notes=note,
    )


def _prove_scenario_identity(run_scenario, scenario_id):
    """Repository-native scenario consistency rule (Correction A1).

    The canonical scenario designation of a clean production run is the
    scenario registry name carried by ``clean_run.scenario`` (the exact
    tokens of app/scenario_manager.py, e.g. "Base", "Downside", "Upside",
    "Bank"); no normalization convention exists or is invented here. When
    the caller supplies ``RunIdentity.scenario_id``, it must be exactly
    that canonical designation - a snapshot may never carry mutually
    contradictory scenario identities.
    """
    if scenario_id is None or run_scenario is None:
        return
    if scenario_id != run_scenario:
        raise ValueError(
            "ANALYTICS_SCENARIO_IDENTITY_MISMATCH: run identity declares "
            f"scenario_id {scenario_id!r} but the clean run's canonical "
            f"scenario designation is {run_scenario!r}; a snapshot may not "
            "combine contradictory scenario identities."
        )


# Schema-v1 canonical metric manifest: metric_id -> (category, unit).
_CANONICAL_MANIFEST: dict[str, tuple[str, str]] = {
    metric_id: (category, unit)
    for metric_id, category, unit in _TRACE_BACKED_METRICS
}
_CANONICAL_MANIFEST.update(
    (metric_id, (category, unit))
    for metric_id, category, unit, _attribute in _G2C_METRICS
)
_CANONICAL_MANIFEST.update(
    (metric_id, (category, unit))
    for metric_id, category, unit in _FUTURE_METRICS
)


def build_canonical_analytics(clean_run, *, run_identity, trace=None,
                              composition_hash=None):
    """Build the run-bound canonical analytics snapshot for one clean run.

    Pure function over canonical authorities: the Workflow 04 Calculation
    Trace (built or supplied) is the verbatim value source; MOIC metrics
    pass through the G2C result directly; reserved ids stay AUTHORITY_MISSING.
    Raises ValueError on a missing/incomplete run identity or a supplied
    trace that does not bind the same run identity.
    """
    if not isinstance(run_identity, RunIdentity):
        raise ValueError(
            "ANALYTICS_RUN_IDENTITY_REQUIRED: canonical analytics is "
            "run-bound only; supply a complete Workflow 04 RunIdentity."
        )
    from app.model_v2.assumption_register import _validate_run_identity

    _validate_run_identity(run_identity)
    _prove_scenario_identity(clean_run.scenario, run_identity.scenario_id)
    if trace is None:
        trace = build_calculation_trace(
            clean_run,
            context=RegisterContext.for_run_bound(
                run_identity=run_identity,
                state_provenance=AssumptionSourceKind.UNKNOWN,
            ),
        )
    else:
        if trace.context.context_kind is not AssumptionContextKind.RUN_BOUND:
            raise ValueError(
                "ANALYTICS_TRACE_CONTEXT_MISMATCH: canonical analytics is "
                "run-bound; a WORKING_COPY trace cannot explain a canonical "
                "run snapshot."
            )
        if trace.context.run_identity != run_identity:
            raise ValueError(
                "ANALYTICS_TRACE_IDENTITY_MISMATCH: supplied trace was built "
                "for a different run identity; refusing to mix lineages."
            )
        if trace.engine_version != run_identity.engine_version \
                or trace.workbook_version != run_identity.workbook_version:
            raise ValueError(
                "ANALYTICS_TRACE_VERSION_MISMATCH: supplied trace carries "
                f"engine/workbook versions {trace.engine_version!r}/"
                f"{trace.workbook_version!r} which contradict the run "
                f"identity's {run_identity.engine_version!r}/"
                f"{run_identity.workbook_version!r}; refusing contradictory "
                "version metadata."
            )
    entries = []
    for metric_id, category, unit in _TRACE_BACKED_METRICS:
        entries.append(_metric_from_trace_entry(trace.entry(metric_id),
                                                category, unit))
    g2c = clean_run.g2c_result
    for metric_id, category, unit, attribute in _G2C_METRICS:
        entries.append(_moic_metric(g2c, metric_id, category, unit, attribute))
    entries.append(_future_metric("lcoe", "UNIT_ECONOMICS", "EUR/MWh",
                                  _LCOE_AUTHORITY_NOTE))
    for metric_id, category, unit in _FUTURE_METRICS[1:]:
        entries.append(_future_metric(
            metric_id, category, unit,
            "no canonical authority exists in the repository; future seam",
        ))
    entries.sort(key=lambda m: m.metric_id)
    return CanonicalAnalyticsSnapshot(
        schema_id=CANONICAL_ANALYTICS_SCHEMA_ID,
        schema_version=CANONICAL_ANALYTICS_SCHEMA_VERSION,
        run_identity=run_identity,
        composition_hash=composition_hash,
        scenario=clean_run.scenario,
        metrics=tuple(entries),
        engine_version=run_identity.engine_version,
        workbook_version=run_identity.workbook_version,
        generated_from_authority=GENERATED_FROM_AUTHORITY,
    )


@dataclass(frozen=True)
class CanonicalAnalyticsSnapshot:
    """Immutable, run-bound, deterministically serializable analytics."""

    schema_id: str
    schema_version: int
    run_identity: RunIdentity
    composition_hash: str | None
    scenario: str
    metrics: tuple[CanonicalMetric, ...]
    engine_version: str
    workbook_version: str
    generated_from_authority: str

    def metric(self, metric_id):
        for candidate in self.metrics:
            if candidate.metric_id == metric_id:
                return candidate
        raise KeyError(metric_id)

    def category(self, category):
        return tuple(m for m in self.metrics if m.category == category)

    @property
    def fingerprint(self) -> str:
        """Content digest (integrity helper only - never a run authority)."""
        digest = hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8"))
        return f"sha256:{digest.hexdigest()}"

    def to_dict(self) -> dict:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "run_identity": self.run_identity.to_dict(),
            "composition_hash": self.composition_hash,
            "scenario": self.scenario,
            "engine_version": self.engine_version,
            "workbook_version": self.workbook_version,
            "generated_from_authority": self.generated_from_authority,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "metric_count": len(self.metrics),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw):
        if raw.get("schema_id") != CANONICAL_ANALYTICS_SCHEMA_ID:
            raise ValueError(
                "SCHEMA_ID_MISMATCH: expected "
                f"{CANONICAL_ANALYTICS_SCHEMA_ID!r}, got {raw.get('schema_id')!r}"
            )
        if raw.get("schema_version") != CANONICAL_ANALYTICS_SCHEMA_VERSION:
            raise ValueError(
                "SCHEMA_VERSION_UNSUPPORTED: expected "
                f"{CANONICAL_ANALYTICS_SCHEMA_VERSION}, "
                f"got {raw.get('schema_version')!r}"
            )
        identity_raw = raw.get("run_identity")
        if not isinstance(identity_raw, dict):
            raise ValueError(
                "ANALYTICS_DESERIALIZE_INVALID: run_identity missing"
            )
        identity = RunIdentity(**{
            key: value
            for key, value in identity_raw.items()
            if key in RunIdentity.__dataclass_fields__
        })
        from app.model_v2.assumption_register import _validate_run_identity

        _validate_run_identity(identity)
        # Correction A3: the deserialized document must be internally
        # consistent - duplicated identity metadata may never contradict
        # itself. No silent repair.
        document_engine = str(raw.get("engine_version", "unknown"))
        document_workbook = str(raw.get("workbook_version", "unknown"))
        if document_engine != identity.engine_version \
                or document_workbook != identity.workbook_version:
            raise ValueError(
                "ANALYTICS_IDENTITY_CONTRADICTION: document versions "
                f"{document_engine!r}/{document_workbook!r} contradict the "
                f"run identity's {identity.engine_version!r}/"
                f"{identity.workbook_version!r}."
            )
        _prove_scenario_identity(raw.get("scenario"), identity.scenario_id)
        metrics_raw = raw.get("metrics")
        if not isinstance(metrics_raw, list):
            raise ValueError("ANALYTICS_DESERIALIZE_INVALID: metrics missing")
        # Correction A4: schema-v1 must be the canonical Workflow 06 metric
        # manifest - exact id set, canonical categories and units.
        manifest = _CANONICAL_MANIFEST
        seen = set()
        for item in metrics_raw:
            metric_id = (item or {}).get("metric_id")
            if metric_id in seen:
                raise ValueError(
                    f"ANALYTICS_METRIC_DUPLICATE: {metric_id!r} appears twice."
                )
            seen.add(metric_id)
            if metric_id not in manifest:
                raise ValueError(
                    f"ANALYTICS_METRIC_UNKNOWN: {metric_id!r} is not part of "
                    "the canonical Workflow 06 metric set."
                )
        missing = sorted(mid for mid in manifest if mid not in seen)
        if missing:
            raise ValueError(
                f"ANALYTICS_METRIC_MISSING: {missing} absent from the "
                "canonical metric set."
            )
        if raw.get("metric_count") != len(metrics_raw):
            raise ValueError(
                "ANALYTICS_METRIC_COUNT_MISMATCH: declared metric_count "
                f"{raw.get('metric_count')!r} != {len(metrics_raw)} metrics."
            )
        metrics = []
        for item in metrics_raw:
            metric = _metric_from_dict(item)
            expected_category, expected_unit = manifest[metric.metric_id]
            if metric.category != expected_category \
                    or metric.unit != expected_unit:
                raise ValueError(
                    "ANALYTICS_METRIC_MANIFEST_MISMATCH: "
                    f"{metric.metric_id!r} declares "
                    f"({metric.category!r}, {metric.unit!r}) but the "
                    f"canonical manifest requires "
                    f"({expected_category!r}, {expected_unit!r})."
                )
            metrics.append(metric)
        return cls(
            schema_id=CANONICAL_ANALYTICS_SCHEMA_ID,
            schema_version=CANONICAL_ANALYTICS_SCHEMA_VERSION,
            run_identity=identity,
            composition_hash=raw.get("composition_hash"),
            scenario=raw.get("scenario"),
            engine_version=str(raw.get("engine_version", "unknown")),
            workbook_version=str(raw.get("workbook_version", "unknown")),
            generated_from_authority=str(
                raw.get("generated_from_authority", "")
            ),
            metrics=tuple(metrics),
        )

    @classmethod
    def from_json(cls, text):
        def _reject(name):
            raise ValueError(
                f"ANALYTICS_VALUE_NOT_FINITE: JSON literal {name!r}"
            )

        return cls.from_dict(json.loads(text, parse_constant=_reject))


_METRIC_FIELDS = frozenset(
    {
        "metric_id",
        "category",
        "value",
        "unit",
        "status",
        "source_status",
        "source_authority",
        "methodology_ref",
        "trace_ref",
        "notes",
    }
)


def _metric_from_dict(item):
    if not isinstance(item, dict) or set(item) != _METRIC_FIELDS:
        raise ValueError(
            f"ANALYTICS_METRIC_INVALID: field mismatch for "
            f"{(item or {}).get('metric_id')!r}"
        )
    try:
        status = CanonicalMetricStatus(item["status"])
    except ValueError as exc:
        raise ValueError(
            "ANALYTICS_METRIC_INVALID: unknown status in "
            f"{item.get('metric_id')!r} ({exc})"
        ) from None
    value = item["value"]
    if value is not None and status is not CanonicalMetricStatus.AVAILABLE:
        raise ValueError(
            f"ANALYTICS_METRIC_INVALID: {item['metric_id']!r} carries a "
            f"value with status {status.value}; only AVAILABLE metrics may "
            "carry values."
        )
    if value is None and status is CanonicalMetricStatus.AVAILABLE:
        raise ValueError(
            f"ANALYTICS_METRIC_INVALID: {item['metric_id']!r} is AVAILABLE "
            "without a value."
        )
    if isinstance(value, bool):
        raise ValueError(
            f"ANALYTICS_VALUE_TYPE_INVALID: {item['metric_id']!r} carries a "
            "bool; metric values are numbers or null."
        )
    if isinstance(value, float) and (
        value != value or value in (float("inf"), float("-inf"))
    ):
        raise ValueError(f"ANALYTICS_VALUE_NOT_FINITE: {item['metric_id']!r}")
    return CanonicalMetric(
        metric_id=item["metric_id"],
        category=item["category"],
        value=value,
        unit=item["unit"],
        status=status,
        source_status=item["source_status"],
        source_authority=item["source_authority"],
        methodology_ref=item["methodology_ref"],
        trace_ref=item["trace_ref"],
        notes=item["notes"],
    )


__all__ = [
    "CANONICAL_ANALYTICS_SCHEMA_VERSION",
    "CANONICAL_ANALYTICS_SCHEMA_ID",
    "CanonicalAnalyticsSnapshot",
    "CanonicalMetric",
    "CanonicalMetricStatus",
    "MetricCategory",
    "build_canonical_analytics",
]

"""Model V2 Calculation Trace - lineage/explanation foundation (read-only).

Workflow 04 scope. The trace is a lineage graph over EXISTING canonical
outputs. It is NOT a second financial engine, and the no-shadow-engine rule
is absolute:

  MAY
    - read canonical result values (pass-through, never recomputed);
    - read canonical model inputs (via the Workflow 04 Assumption Register);
    - point at methodology authority (app/model_methodology_registry.py
      entries and canonical producer module::function identities);
    - record dependency references (assumption ids, output keys);
    - build a deterministic lineage document.

  MAY NOT
    - independently compute IRR, DSCR, debt size, tax, revenue or
      depreciation;
    - re-derive any financial quantity from other quantities;
    - replace run/workbook/project identity.

Completeness is explicit and honest (``TraceCompleteness``): a trace entry
is AUTHORITY_ONLY unless the repository provides enough authoritative
lineage to prove a COMPLETE formula tree - which no current target does.
Where the canonical authority reports a metric unavailable (statused None),
the trace says UNAVAILABLE. PARTIAL and COMPLETE are typed seams for future,
individually reviewed workflows; this workflow never emits them.

Every numeric value on a trace entry is a verbatim pass-through of the
canonical result (or of the canonical read-only presentation adapter's
aggregation of result vectors). No NaN/Inf is ever serialized; provenance
that cannot be proved is not claimed.

Governance: exact-path authorized support file under
docs/model_v2/ACTIVE_EPIC_SCOPE.json. No engine, persistence, or Workflow 02
RevenuePlan code is modified.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from app.model_v2.assumption_register import (
    AssumptionContextKind,
    AssumptionSourceKind,
    RegisterContext,
    RunIdentity,
    ValuePresence,
    _validate_run_identity,
    canonical_json,
    engine_version,
    workbook_version,
)

CALCULATION_TRACE_SCHEMA_ID = "finco.model-v2.calculation-trace"
CALCULATION_TRACE_SCHEMA_VERSION = 1


class TraceCompleteness(str, Enum):
    """Typed completeness - never fake a complete formula tree."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    AUTHORITY_ONLY = "AUTHORITY_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class TraceEntry:
    """One traced output: pass-through value plus honest lineage."""

    trace_id: str
    output_key: str
    output_label: str
    output_value: float | int | str | None
    value_presence: ValuePresence
    unit: str
    status: str | None
    methodology_key: str | None
    authority: str
    formula_ref: str | None
    referenced_assumption_ids: tuple[str, ...]
    referenced_output_keys: tuple[str, ...]
    completeness: TraceCompleteness
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "output_key": self.output_key,
            "output_label": self.output_label,
            "output_value": self.output_value,
            "value_presence": self.value_presence.value,
            "unit": self.unit,
            "status": self.status,
            "methodology_key": self.methodology_key,
            "authority": self.authority,
            "formula_ref": self.formula_ref,
            "referenced_assumption_ids": list(self.referenced_assumption_ids),
            "referenced_output_keys": list(self.referenced_output_keys),
            "completeness": self.completeness.value,
            "notes": self.notes,
        }


_TRACE_ENTRY_FIELDS = (
    "trace_id",
    "output_key",
    "output_label",
    "output_value",
    "value_presence",
    "unit",
    "status",
    "methodology_key",
    "authority",
    "formula_ref",
    "referenced_assumption_ids",
    "referenced_output_keys",
    "completeness",
    "notes",
)


def _check_finite_trace(trace_id: str, value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(
                f"TRACE_VALUE_NOT_FINITE: {trace_id} = {value!r}; NaN/Inf "
                "never enter the trace."
            )


def trace_entry_from_dict(raw: Mapping[str, Any]) -> TraceEntry:
    keys = set(raw)
    expected = set(_TRACE_ENTRY_FIELDS)
    if keys != expected:
        raise ValueError(
            "TRACE_ENTRY_INVALID: field mismatch for "
            f"{raw.get('trace_id')!r} "
            f"(missing={sorted(expected - keys)}, "
            f"unknown={sorted(keys - expected)})"
        )
    try:
        presence = ValuePresence(raw["value_presence"])
        completeness = TraceCompleteness(raw["completeness"])
    except ValueError as exc:
        raise ValueError(
            f"TRACE_ENTRY_INVALID: unknown enum in {raw.get('trace_id')!r} "
            f"({exc})"
        ) from None
    kwargs = {name: raw[name] for name in _TRACE_ENTRY_FIELDS}
    kwargs["value_presence"] = presence
    kwargs["completeness"] = completeness
    kwargs["referenced_assumption_ids"] = tuple(
        kwargs["referenced_assumption_ids"]
    )
    kwargs["referenced_output_keys"] = tuple(kwargs["referenced_output_keys"])
    entry = TraceEntry(**kwargs)
    _check_finite_trace(entry.trace_id, entry.output_value)
    if entry.output_value is None and \
            entry.value_presence is not ValuePresence.MISSING:
        raise ValueError(
            f"TRACE_ENTRY_INVALID: {entry.trace_id} has no value but is not "
            "marked MISSING."
        )
    if entry.output_value is not None and \
            entry.value_presence is not ValuePresence.PRESENT:
        raise ValueError(
            f"TRACE_ENTRY_INVALID: {entry.trace_id} has a value but is not "
            "marked PRESENT."
        )
    if entry.completeness is TraceCompleteness.UNAVAILABLE and \
            entry.output_value is not None:
        raise ValueError(
            f"TRACE_ENTRY_INVALID: {entry.trace_id} carries a value but is "
            "marked UNAVAILABLE."
        )
    return entry


# ---------------------------------------------------------------------------
# Methodology authority (read-only reuse of the central registry)
# ---------------------------------------------------------------------------


def _registry_entry(key):
    from app.model_methodology_registry import METRIC_REGISTRY

    for candidate in METRIC_REGISTRY:
        if candidate.key == key:
            return candidate
    return None


def _methodology(methodology_key):
    """(authority, formula_ref) from the central registry, or direct pins."""
    if methodology_key is None:
        return None, None
    record = _registry_entry(methodology_key)
    if record is None:
        return None, None
    authority = f"{record.source_file}::{record.source_function}"
    if record.production_caller:
        authority = f"{authority} (production caller: {record.production_caller})"
    return authority, record.formula


# Direct engine producers for outputs the central methodology registry does
# not yet carry a key for. Pinned from the canonical engine source; verified
# by tests/test_model_v2_calculation_trace.py. Adding registry keys is a
# coordinator-owned change (guardrails §5) and is intentionally NOT done here.
_DIRECT_AUTHORITIES = {
    "project_npv_keur": "financial_engine/valuation/model.py::calculate_project_npv",
    "min_plcr": "financial_engine/valuation/model.py::calculate_lender_coverage",
}


# ---------------------------------------------------------------------------
# Pass-through extraction (no recomputation anywhere)
# ---------------------------------------------------------------------------


def _status_text(value):
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _extract_outputs(clean_run):
    """Read the canonical result surface, pass-through only.

    Scalars come from the G2C result objects. Aggregate totals come from the
    canonical read-only presentation adapter (build_clean_waterfall_view),
    which is itself a pass-through aggregation over canonical vectors.
    """
    from app.services.clean_presentation_adapter import build_clean_waterfall_view

    view = build_clean_waterfall_view(clean_run)
    g2c = clean_run.g2c_result
    npv = g2c.valuation_summary.project_npv
    coverage = g2c.valuation_summary.lender_coverage
    financing = g2c.financing_result
    project_return = g2c.return_summary.project

    outputs = {
        "project_xirr": (
            project_return.project_xirr, _status_text(project_return.project_xirr_status),
        ),
        "pure_equity_xirr": (
            g2c.pure_equity_xirr, _status_text(g2c.pure_equity_xirr_status),
        ),
        "total_sponsor_xirr": (
            g2c.total_sponsor_xirr, _status_text(g2c.total_sponsor_xirr_status),
        ),
        "project_npv_keur": (npv.npv_keur, _status_text(npv.status)),
        "senior_debt_keur": (financing.final_senior_commitment_keur, None),
        "min_dscr": (view.actual_min_dscr, None),
        "min_llcr": (coverage.llcr.ratio, _status_text(coverage.llcr.status)),
        "min_plcr": (coverage.plcr.ratio, _status_text(coverage.plcr.status)),
        "total_revenue_keur": (view.total_revenue_keur, None),
        "total_opex_keur": (view.total_opex_keur, None),
        "total_ebitda_keur": (view.total_ebitda_keur, None),
        "total_tax_keur": (view.total_tax_keur, None),
    }
    return outputs


# output_key -> (trace_id, label, unit, methodology_key)
_TRACE_TARGETS = {
    "project_xirr": ("trace.project_xirr", "Project XIRR", "fraction",
                     "project_irr"),
    "pure_equity_xirr": ("trace.pure_equity_xirr", "Pure Equity XIRR",
                         "fraction", "equity_irr"),
    "total_sponsor_xirr": ("trace.total_sponsor_xirr", "Total Sponsor XIRR",
                           "fraction", "total_sponsor_xirr"),
    "project_npv_keur": ("trace.project_npv_keur", "Project NPV", "kEUR", None),
    "senior_debt_keur": ("trace.senior_debt_keur", "Senior Debt Amount",
                         "kEUR", "initial_senior_debt"),
    "min_dscr": ("trace.min_dscr", "Minimum DSCR", "ratio", "dscr"),
    "min_llcr": ("trace.min_llcr", "Minimum LLCR", "ratio", "llcr"),
    "min_plcr": ("trace.min_plcr", "Minimum PLCR", "ratio", None),
    "total_revenue_keur": ("trace.total_revenue_keur", "Total Revenue",
                           "kEUR", "revenue"),
    "total_opex_keur": ("trace.total_opex_keur", "Total OPEX", "kEUR",
                        "opex"),
    "total_ebitda_keur": ("trace.total_ebitda_keur", "Total EBITDA", "kEUR",
                          "ebitda"),
    "total_tax_keur": ("trace.total_tax_keur", "Total Cash Tax", "kEUR",
                       "cash_tax"),
}

# Referenced-assumption selection rules (documented, deterministic):
# section-level references over the Workflow 04 Assumption Register. These
# name the assumption families the canonical methodology consumes; they do
# NOT claim a per-formula derivation tree (completeness stays AUTHORITY_ONLY).
_CFO_DRIVER_SECTIONS = ("TECHNICAL", "REVENUE")
_EQUITY_INPUT_IDS = (
    "financing.share_capital_keur",
    "financing.share_premium_keur",
    "financing.shl_amount_keur",
    "financing.shl_rate",
)
_DEBT_SIZING_IDS = (
    "financing.gearing_ratio",
    "financing.senior_debt_amount_keur",
    "financing.senior_tenor_years",
    "financing.target_dscr",
    "financing.base_rate",
    "financing.margin_bps",
    "financing.debt_sizing_mode",
)
_OUTPUT_DEPENDENCIES = {
    "project_xirr": {"sections": _CFO_DRIVER_SECTIONS,
                     "amounts": ("CAPEX", "OPEX"),
                     "ids": _EQUITY_INPUT_IDS + ("tax.corporate_rate",)},
    "pure_equity_xirr": {"sections": _CFO_DRIVER_SECTIONS,
                         "amounts": ("CAPEX", "OPEX"),
                         "ids": _EQUITY_INPUT_IDS},
    "total_sponsor_xirr": {"sections": _CFO_DRIVER_SECTIONS,
                           "amounts": ("CAPEX", "OPEX"),
                           "ids": _EQUITY_INPUT_IDS},
    "project_npv_keur": {"sections": _CFO_DRIVER_SECTIONS,
                         "amounts": ("CAPEX", "OPEX"),
                         "ids": _EQUITY_INPUT_IDS
                         + ("tax.corporate_rate",
                            "valuation.project.annual_discount_rate")},
    "senior_debt_keur": {"sections": (), "amounts": (),
                         "ids": _DEBT_SIZING_IDS},
    "min_dscr": {"sections": _CFO_DRIVER_SECTIONS, "amounts": ("OPEX",),
                 "ids": _DEBT_SIZING_IDS},
    "min_llcr": {"sections": _CFO_DRIVER_SECTIONS, "amounts": (),
                 "ids": _DEBT_SIZING_IDS
                 + ("valuation.coverage.annual_discount_rate",)},
    "min_plcr": {"sections": _CFO_DRIVER_SECTIONS, "amounts": (),
                 "ids": _DEBT_SIZING_IDS
                 + ("valuation.coverage.annual_discount_rate",)},
    "total_revenue_keur": {"sections": _CFO_DRIVER_SECTIONS, "amounts": (),
                           "ids": ()},
    "total_opex_keur": {"sections": (), "amounts": ("OPEX",), "ids": ()},
    "total_ebitda_keur": {"sections": _CFO_DRIVER_SECTIONS,
                          "amounts": ("CAPEX", "OPEX"), "ids": ()},
    "total_tax_keur": {"sections": _CFO_DRIVER_SECTIONS,
                       "amounts": ("CAPEX", "OPEX"),
                       "ids": ("tax.corporate_rate",)},
}


def _collect_references(register, output_key):
    """Deterministic referenced-assumption selection (rule-documented)."""
    if register is None:
        return ()
    rule = _OUTPUT_DEPENDENCIES.get(output_key)
    if rule is None:
        return ()
    known = {entry.assumption_id for entry in register.entries}
    selected = set()
    for section in rule["sections"]:
        selected.update(
            entry.assumption_id
            for entry in register.section(section)
            if entry.value_presence is ValuePresence.PRESENT
        )
    for section in rule["amounts"]:
        selected.update(
            entry.assumption_id
            for entry in register.section(section)
            if entry.assumption_id.endswith(".amount_keur")
            or entry.assumption_id.endswith(".y1_amount_keur")
        )
    for assumption_id in rule["ids"]:
        if assumption_id in known:
            selected.add(assumption_id)
        else:
            raise ValueError(
                "TRACE_REFERENCE_UNKNOWN_ASSUMPTION: "
                f"{assumption_id} referenced by {output_key} does not exist "
                "in the supplied AssumptionRegister."
            )
    return tuple(sorted(selected))


def build_calculation_trace(clean_run, *, context, assumption_register=None):
    """Build the immutable Calculation Trace for one canonical production run.

    Pure function over the canonical result: values are pass-through only.
    ``context`` may be WORKING_COPY (preview-time explanation) or RUN_BOUND
    (committed-run explanation); the context is recorded verbatim and never
    altered. ``assumption_register`` must have been built from the SAME
    input state as the run (effective inputs) or references fail closed.
    """
    if context.context_kind is AssumptionContextKind.RUN_BOUND \
            and context.run_identity is None:
        raise ValueError(
            "TRACE_CONTEXT_INVALID: RUN_BOUND trace requires a complete "
            "run identity."
        )
    outputs = _extract_outputs(clean_run)
    entries = []
    for output_key, (trace_id, label, unit, methodology_key) in _TRACE_TARGETS.items():
        value, status = outputs[output_key]
        present = value is not None
        if present:
            authority, formula_ref = _methodology(methodology_key)
            if authority is None:
                authority = _DIRECT_AUTHORITIES.get(output_key)
            completeness = TraceCompleteness.AUTHORITY_ONLY
            notes = (
                "value passed through from the canonical result; lineage "
                "recorded at authority level"
            )
        else:
            authority = _DIRECT_AUTHORITIES.get(output_key)
            formula_ref = None
            completeness = TraceCompleteness.UNAVAILABLE
            notes = (
                "canonical authority reported this metric unavailable "
                "(statused); recorded as UNAVAILABLE, never as zero"
            )
        references = _collect_references(assumption_register, output_key)
        entries.append(
            TraceEntry(
                trace_id=trace_id,
                output_key=output_key,
                output_label=label,
                output_value=value,
                value_presence=(
                    ValuePresence.PRESENT if present else ValuePresence.MISSING
                ),
                unit=unit,
                status=status,
                methodology_key=methodology_key,
                authority=authority,
                formula_ref=formula_ref,
                referenced_assumption_ids=references,
                referenced_output_keys=(),
                completeness=completeness,
                notes=notes,
            )
        )
    entries.sort(key=lambda e: e.trace_id)
    return CalculationTrace(
        context=context,
        entries=tuple(entries),
        engine_version=engine_version(),
        workbook_version=workbook_version(),
    )


@dataclass(frozen=True)
class CalculationTrace:
    """Immutable, deterministically ordered lineage document."""

    context: RegisterContext
    entries: tuple[TraceEntry, ...]
    engine_version: str
    workbook_version: str

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8"))
        return f"sha256:{digest.hexdigest()}"

    def entry(self, output_key):
        for candidate in self.entries:
            if candidate.output_key == output_key:
                return candidate
        raise KeyError(output_key)

    def to_dict(self):
        return {
            "schema_id": CALCULATION_TRACE_SCHEMA_ID,
            "schema_version": CALCULATION_TRACE_SCHEMA_VERSION,
            "context": self.context.to_dict(),
            "engine_version": self.engine_version,
            "workbook_version": self.workbook_version,
            "entries": [entry.to_dict() for entry in self.entries],
            "entry_count": len(self.entries),
        }

    def to_json(self):
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw):
        if raw.get("schema_id") != CALCULATION_TRACE_SCHEMA_ID:
            raise ValueError(
                "SCHEMA_ID_MISMATCH: expected "
                f"{CALCULATION_TRACE_SCHEMA_ID!r}, got {raw.get('schema_id')!r}"
            )
        if raw.get("schema_version") != CALCULATION_TRACE_SCHEMA_VERSION:
            raise ValueError(
                "SCHEMA_VERSION_UNSUPPORTED: expected "
                f"{CALCULATION_TRACE_SCHEMA_VERSION}, "
                f"got {raw.get('schema_version')!r}"
            )
        context_raw = raw.get("context")
        if not isinstance(context_raw, dict):
            raise ValueError("TRACE_DESERIALIZE_INVALID: context missing")
        try:
            context_kind = AssumptionContextKind(context_raw["context_kind"])
            state_provenance = AssumptionSourceKind(context_raw["state_provenance"])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"TRACE_DESERIALIZE_INVALID: unknown context enum ({exc})"
            ) from None
        run_identity = None
        if context_raw.get("run_identity") is not None:
            run_identity = RunIdentity(**{
                key: value
                for key, value in context_raw["run_identity"].items()
                if key in RunIdentity.__dataclass_fields__
            })
            _validate_run_identity(run_identity)
        entries_raw = raw.get("entries")
        if not isinstance(entries_raw, list):
            raise ValueError("TRACE_DESERIALIZE_INVALID: entries missing")
        entries = tuple(trace_entry_from_dict(entry) for entry in entries_raw)
        return cls(
            context=RegisterContext(
                context_kind=context_kind,
                state_provenance=state_provenance,
                run_identity=run_identity,
                workbook_composite_hash=context_raw.get(
                    "workbook_composite_hash"
                ),
                notes=context_raw.get("notes"),
            ),
            entries=entries,
            engine_version=str(raw.get("engine_version", "unknown")),
            workbook_version=str(raw.get("workbook_version", "unknown")),
        )

    @classmethod
    def from_json(cls, text):
        def _reject(name):
            raise ValueError(
                f"TRACE_VALUE_NOT_FINITE: JSON literal {name!r} is not "
                "representable in a trace."
            )

        return cls.from_dict(json.loads(text, parse_constant=_reject))



__all__ = [
    "CALCULATION_TRACE_SCHEMA_VERSION",
    "CALCULATION_TRACE_SCHEMA_ID",
    "CalculationTrace",
    "TraceCompleteness",
    "TraceEntry",
    "build_calculation_trace",
    "trace_entry_from_dict",
]

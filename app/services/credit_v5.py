"""Read-only Credit V5 over the existing V3/V4 committed-evidence projections.

No solver, repository, Working Copy or contractual-policy inference lives here.
HTTP-supplied constraints are hypothetical; supported metrics use their persisted
V3 basis. Rankings never mix metrics, units or economic intervals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
import math
from typing import Any, Sequence

from app.v2.credit_decision_projection import HISTORICAL, RunInput, build_credit_decision
from app.v2.credit_v4_evidence import _periods

SCHEMA = "INSTITUTIONAL_CREDIT_V5_READONLY_V1"
# metric -> (direction, unit, V3 section, V3 cell)
METRICS = {
    "min_dscr": ("MIN", "x", None, None),
    "min_llcr": ("MIN", "x", "capacity", "min_llcr"),
    "max_gearing": ("MAX", "fraction", "structure", "actual_gearing"),
    "min_equity_keur": ("MIN", "kEUR", "structure", "equity_sources"),
    "max_balloon_keur": ("MAX", "kEUR", "maturity", "balance_at_maturity"),
}
UNSUPPORTED = ("debt_to_equity", "reserve_coverage", "max_maturity_years", "resized_debt")


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def difference(a: float, b: float) -> float:
    # Decimal on the persisted decimal representations avoids display subtraction
    # noise. This is analytical headroom, not a recomputed financial model value.
    with localcontext() as ctx:
        ctx.prec = 40
        result = float(Decimal(str(a)) - Decimal(str(b)))
    if not math.isfinite(result):
        raise ValueError("CREDIT_V5_ARITHMETIC_NONFINITE")
    return result


@dataclass(frozen=True)
class Constraint:
    metric: str
    threshold: float | None = None
    name: str = ""

    def __post_init__(self):
        if self.metric not in METRICS and self.metric not in UNSUPPORTED:
            raise ValueError("CREDIT_V5_METRIC_UNSUPPORTED")
        if not isinstance(self.name, str) or len(self.name) > 100:
            raise ValueError("CREDIT_V5_CONSTRAINT_NAME_INVALID")
        if self.threshold is not None:
            value = number(self.threshold)
            if value is None or value < 0 or (self.metric in ("min_dscr", "min_llcr") and value == 0):
                raise ValueError("CREDIT_V5_THRESHOLD_INVALID")
            if self.metric == "max_gearing" and value > 1:
                raise ValueError("CREDIT_V5_GEARING_REQUIRES_FRACTION")


@dataclass(frozen=True)
class PeriodHeadroom:
    index: int | None
    start: str | None
    end: str | None
    value: float | None
    absolute: float | None
    relative: float | None
    state: str
    reason: str = ""


@dataclass(frozen=True)
class Assessment:
    name: str
    metric: str
    unit: str
    threshold: float | None
    authority: str
    state: str
    reason: str
    observations: tuple[PeriodHeadroom, ...]
    minimum_headroom: float | None
    worst_period: str | None
    first_breach: str | None
    breach_count: int | None
    complete: bool
    source: str


@dataclass(frozen=True)
class RunCredit:
    history_id: str
    snapshot_id: str
    composite_hash: str
    scenario_id: str | None
    ran_at: str
    engine_version: str | None
    integrity: str
    frequency: str
    freshness: str
    constraints: tuple[Assessment, ...]
    restrictive_groups: tuple[tuple[str, tuple[str, ...]], ...]
    sizing_evidence: tuple[tuple[str, float | str | None], ...]
    minimum_dscr: float | None
    senior_commitment_keur: float | None
    scheduled_service_keur: float | None
    equity_sources_keur: float | None
    intervals: tuple[tuple[str | None, str], ...]
    comparison_eligible: bool


@dataclass(frozen=True)
class RunComparison:
    history_id: str
    reference_id: str
    state: str
    reason: str
    delta_min_dscr: float | None = None
    delta_senior_keur: float | None = None
    delta_service_keur: float | None = None
    delta_equity_keur: float | None = None
    # (constraint name, change in minimum headroom, change in breach count)
    policy_changes: tuple[tuple[str, float | None, int | None], ...] = ()


@dataclass(frozen=True)
class CreditAnalysis:
    schema: str
    runs: tuple[RunCredit, ...]
    comparisons: tuple[RunComparison, ...]
    observed_dscr_order: tuple[str, ...]
    contractual_policy: str = "UNAVAILABLE_NO_RUN_BOUND_CONTRACTUAL_THRESHOLD_AUTHORITY"
    sizing: str = "PERSISTED_CAPACITY_ONLY_NO_RESIZING_OR_NEW_SOLVE"


def _cell(view, section, key):
    return number(view.get(section, {}).get(key, {}).get("v"))


def _headroom(index, start, end, actual, constraint, direction, missing=""):
    if constraint.threshold is None:
        return PeriodHeadroom(index, start, end, actual, None, None, "UNAVAILABLE", "THRESHOLD_NOT_SUPPLIED")
    if missing or actual is None:
        return PeriodHeadroom(index, start, end, None, None, None, "UNAVAILABLE", missing or "VALUE_NOT_PERSISTED")
    head = difference(actual, constraint.threshold) if direction == "MIN" else difference(constraint.threshold, actual)
    relative = head / constraint.threshold if constraint.threshold > 0 else None
    if relative is not None and not math.isfinite(relative):
        relative = None
    return PeriodHeadroom(index, start, end, actual, head, relative,
                          "BREACH" if head < 0 else "AT_LIMIT" if head == 0 else "SATISFIED")


def _assess(view, parsed, constraint):
    metric = constraint.metric
    name = constraint.name or metric
    observations = []
    if metric not in METRICS:
        unit, source, reason = "", "NONE", "NO_SUPPORTED_PERSISTED_METRIC_OR_METHODOLOGY"
    else:
        direction, unit, section, key = METRICS[metric]
        reason = ""
        source = f"CreditV3.{section}.{key}" if section else "integrity_evidence.senior_debt.periods.reported_dscr"
        if view.get("operating_frequency", "6/6") != "6/6":
            reason = "QUARTERLY_RELEASE_CLOSED_NOT_ADMITTED_BY_V5"
        elif view["structure"]["state"] != "AVAILABLE":
            reason = "FINANCING_EVIDENCE_INVALID_OR_UNAVAILABLE"
        elif metric == "min_dscr":
            if not parsed["valid"]:
                reason = parsed["reason"]
            else:
                columns = {c["date"]: c for c in view["timeline"]["columns"]}
                for end, row in parsed["by_date"].items():
                    col = columns[end]
                    service = row.get("debt_service")
                    start = parsed["starts"].get(end)
                    if service == 0:
                        observations.append(PeriodHeadroom(col["index"], start, end, None, None, None,
                                                           "NOT_APPLICABLE", "ZERO_SCHEDULED_DEBT_SERVICE"))
                        continue
                    missing = ("DEBT_SERVICE_MISSING_OR_NEGATIVE" if service is None or service < 0 else
                               "PERIOD_INTERVAL_UNPROVEN" if start is None or start >= end else "")
                    observations.append(_headroom(col["index"], start, end, row.get("dscr"), constraint, direction, missing))
        else:
            if section == "maturity":
                actual = number(view["structure"]["maturity"][key]["v"])
                end = view["structure"]["tenor"]["contractual_maturity_date"]["v"]
                try:
                    date.fromisoformat(end)
                except (TypeError, ValueError):
                    end = None
                missing = "CONTRACTUAL_MATURITY_DATE_MISSING" if end is None else ""
            else:
                actual, end, missing = _cell(view, section, key), None, ""
            if actual is not None and actual < 0:
                missing = "NEGATIVE_FINANCING_EVIDENCE"
            observations.append(_headroom(None, None, end, actual, constraint, direction, missing))
    evaluated = [r for r in observations if r.absolute is not None]
    unknown = any(r.state == "UNAVAILABLE" for r in observations)
    complete = bool(evaluated) and not unknown and not reason
    worst = min(evaluated, key=lambda r: r.absolute) if evaluated else None
    breaches = [r for r in evaluated if r.state == "BREACH"]
    failure_state = ("UNSUPPORTED" if reason == "NO_SUPPORTED_PERSISTED_METRIC_OR_METHODOLOGY" or
                     reason == "QUARTERLY_RELEASE_CLOSED_NOT_ADMITTED_BY_V5" else "DATA_MISMATCH")
    state = (failure_state if reason else "UNAVAILABLE" if not observations or
             (not evaluated and unknown) else "PARTIAL" if unknown else
             "NOT_APPLICABLE" if not evaluated else "BREACH" if breaches else
             "AT_LIMIT" if worst.absolute == 0 else "SATISFIED")
    return Assessment(name, metric, unit, constraint.threshold, "HYPOTHETICAL_ANALYST_PROPOSED", state,
                      reason or ("THRESHOLD_NOT_SUPPLIED" if constraint.threshold is None else
                                 "INCOMPLETE_EVALUATION" if unknown else ""), tuple(observations),
                      worst.absolute if worst else None, worst.end if worst else None,
                      breaches[0].end if breaches else None, len(breaches) if evaluated else None, complete, source)


def _validate_entry(entry, owner_id, project_id):
    if entry.user_id != owner_id or entry.project_id != project_id:
        raise ValueError("CREDIT_V5_RUN_SCOPE_MISMATCH")
    if not all(isinstance(v, str) and v.strip() for v in
               (entry.history_id, entry.runtime_snapshot_id, entry.composite_hash, entry.ran_at)):
        raise ValueError("CREDIT_V5_RUN_IDENTITY_MISSING")
    from app.run_integrity.evidence import evidence_digest
    evidence = entry.integrity_evidence
    if not isinstance(evidence, dict) or evidence.get("digest") != evidence_digest(evidence):
        raise ValueError("CREDIT_V5_INTEGRITY_DIGEST_INVALID")
    binding = entry.runtime_summary.get("financing_evidence", {}).get("run_binding")
    expected = {"snapshot_id": entry.runtime_snapshot_id, "composite_hash": entry.composite_hash,
                "scenario_id": entry.last_runtime_scenario_id}
    if not isinstance(binding, dict) or not set(expected).issubset(binding) or any(binding.get(k) != v for k, v in expected.items()):
        raise ValueError("CREDIT_V5_FINANCING_RUN_BINDING_MISMATCH")
    if entry.model_v2_binding is not None:
        from app.model_v2.persistence import validate_run_binding_payload
        bound = validate_run_binding_payload(entry.model_v2_binding)
        if bound["snapshot_id"] != entry.runtime_snapshot_id or bound["scenario_id"] != entry.last_runtime_scenario_id:
            raise ValueError("CREDIT_V5_MODEL_V2_BINDING_MISMATCH")


def analyze_runs(entries: Sequence[Any], constraints: Sequence[Constraint], *,
                 owner_id: str, project_id: str, project_code: str) -> CreditAnalysis:
    """Pure entry point; callers must load entries using owner-scoped history reads.

    V3/V4 remain the financial/interval projection authorities. No current-input
    thresholds or freshness assertions are attached to these historical Runs.
    """
    if not 1 <= len(entries) <= 3 or not 1 <= len(constraints) <= 12:
        raise ValueError("CREDIT_V5_SELECTION_LIMIT")
    names = [c.name or c.metric for c in constraints]
    if len(set(names)) != len(names):
        raise ValueError("CREDIT_V5_DUPLICATE_CONSTRAINT")
    for entry in entries:
        _validate_entry(entry, owner_id, project_id)
    data = build_credit_decision([RunInput(e, HISTORICAL, scenario_label=e.active_scenario_name or "Unavailable")
                                  for e in entries], project_code=project_code)
    results = []
    for view in data["runs"]:
        parsed = _periods(view)
        if parsed["valid"]:
            columns = view["timeline"]["columns"]
            for previous, current in zip(columns, columns[1:]):
                if current["index"] != previous["index"] + 1 or current.get("start") != previous["date"]:
                    parsed = {**parsed, "valid": False, "reason": "PERIOD_CONTINUITY_MISMATCH"}
                    break
        assessments = tuple(_assess(view, parsed, c) for c in constraints)
        groups = []
        for metric in sorted({c.metric for c in assessments if c.complete}):
            peers = [c for c in assessments if c.metric == metric and c.complete]
            lowest = min(c.minimum_headroom for c in peers)
            groups.append((metric, tuple(c.name for c in peers if c.minimum_headroom == lowest)))
        ident = view["identity"]
        dscr_rows = [r for r in parsed["by_date"].values() if r.get("debt_service") is not None and r["debt_service"] > 0]
        complete_dscr = parsed["valid"] and not parsed["missing"] and dscr_rows
        intervals = tuple((parsed.get("starts", {}).get(d), d) for d in parsed["by_date"])
        eligible = bool(complete_dscr and all(s and s < e for s, e in intervals) and
                        view.get("operating_frequency", "6/6") == "6/6" and
                        view["structure"]["state"] == "AVAILABLE" and ident["integrity"] == "PASS")
        sizing = tuple((key, view["capacity"][key]["v"]) for key in
                       ("dscr_debt_capacity", "gearing_debt_capacity", "final_commitment", "binding_constraint"))
        results.append(RunCredit(
            ident["history_id"], ident["snapshot_id"], ident["composite_hash"], ident["scenario_id"],
            ident["ran_at"], ident["engine_version"], ident["integrity"], view.get("operating_frequency", "6/6"),
            "HISTORICAL_NOT_ASSERTED_CURRENT", assessments, tuple(groups), sizing,
            min(r["dscr"] for r in dscr_rows) if complete_dscr else None,
            _cell(view, "structure", "commitment"), _cell(view, "capacity", "debt_service_total"),
            _cell(view, "structure", "equity_sources"), intervals, eligible))
    comparisons = []
    base = results[0]
    for run in results[1:]:
        reason = ("PERIOD_INTERVALS_NOT_IDENTICAL_OR_INCOMPLETE" if not (base.comparison_eligible and
                  run.comparison_eligible and run.intervals == base.intervals) else
                  "ENGINE_VERSION_MISMATCH_OR_UNKNOWN" if not base.engine_version or base.engine_version != run.engine_version else "")
        if reason:
            comparisons.append(RunComparison(run.history_id, base.history_id, "NOT_COMPARABLE", reason))
            continue
        def delta(a, b):
            return difference(a, b) if a is not None and b is not None else None
        changes = tuple((c.name, delta(c.minimum_headroom, b.minimum_headroom) if c.complete and b.complete else None,
                         c.breach_count - b.breach_count if c.complete and b.complete else None)
                        for c, b in zip(run.constraints, base.constraints))
        comparisons.append(RunComparison(run.history_id, base.history_id, "OBSERVED_CHANGE", "NOT_A_CAUSAL_OR_MATERIALITY_VERDICT",
                            delta(run.minimum_dscr, base.minimum_dscr), delta(run.senior_commitment_keur, base.senior_commitment_keur),
                            delta(run.scheduled_service_keur, base.scheduled_service_keur),
                            delta(run.equity_sources_keur, base.equity_sources_keur), changes))
    comparable = all(c.state == "OBSERVED_CHANGE" for c in comparisons) and all(r.comparison_eligible for r in results)
    order = tuple(r.history_id for r in sorted(results, key=lambda r: (-r.minimum_dscr, r.history_id))) if comparable else ()
    return CreditAnalysis(SCHEMA, tuple(results), tuple(comparisons), order)

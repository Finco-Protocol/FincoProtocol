"""app.v2.developer_decision_projection — investment-decision evidence panel (presentation only).

* Project NPV is shown ONLY from the persisted Last Run (``runtime_summary.project_npv_keur``)
  and is unavailable today (the run does not persist it).  Never derived here.
* Expected NPV (probability-weighted) requires a reviewed typed decision-analytics contract.
  Each required condition is evaluated against what the repository actually provides; since
  none of the contract exists, the metric is unavailable, with the exact missing authority.
  Project NPV and Expected NPV never share a label or authority.
* Development margin has no approved definition -> unavailable (no competing MOIC invented).
* No BUY / SELL / "recommended" language is produced anywhere.
* Stage / Perspective are non-economic metadata shown verbatim from the project record;
  an unset value is shown as "Not set" and is never inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.model_v2.project_metadata import normalize_perspective, normalize_stage

NOT_SET = "Not set"


@dataclass(frozen=True)
class Condition:
    key: str
    requirement: str
    satisfied: bool
    evidence: str


# The eight preconditions for a probability-weighted Expected NPV.  ``satisfied`` is False
# for each because the repository provides no such authority; the evidence names what exists.
EXPECTED_NPV_CONDITIONS: tuple[Condition, ...] = (
    Condition("typed_scenarios", "A typed, versioned set of mutually exclusive outcome scenarios", False,
              "Scenarios are Working-Copy overrides, not a typed outcome set."),
    Condition("typed_probabilities", "Typed probability per scenario, user-entered, summing to 100%", False,
              "No probability input exists on any persisted contract."),
    Condition("probability_authority", "Owner/approval authority for the probabilities", False,
              "No persisted owner or approval record for probabilities."),
    Condition("canonical_scenario_npv", "A canonical, persisted NPV for every scenario Run", False,
              "runtime_summary.project_npv_keur is not persisted by the model run."),
    Condition("discount_authority", "One approved discount-rate / valuation-date authority shared by all scenarios", False,
              "No approved valuation authority (WACC and valuation date are reserved vocabulary only)."),
    Condition("run_binding", "Each scenario NPV bound to an immutable Run History entry", False,
              "Run History does not carry per-scenario NPV."),
    Condition("freshness", "All scenario Runs CURRENT against their inputs", False,
              "Not evaluable without the preceding authorities."),
    Condition("reviewed_contract", "A reviewed typed decision-analytics contract with export parity", False,
              "No decision-analytics contract exists in finco_core / domain/analytics."),
)


@dataclass(frozen=True)
class DecisionMetric:
    key: str
    label: str
    display: str
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class DecisionPanel:
    project_npv: DecisionMetric
    expected_npv: DecisionMetric
    development_margin: DecisionMetric
    conditions: tuple[Condition, ...]
    proposal: str
    run_state: str            # NOT_RUN | CURRENT | STALE


def _persisted_npv(runtime_summary: Optional[dict]) -> Optional[float]:
    value = (runtime_summary or {}).get("project_npv_keur")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def build_decision_panel(runtime_summary: Optional[dict], *, run_state: str) -> DecisionPanel:
    state = run_state if run_state in ("CURRENT", "STALE") else "NOT_RUN"
    npv = _persisted_npv(runtime_summary) if state != "NOT_RUN" else None
    if npv is not None:
        project_npv = DecisionMetric(
            "project_npv", "Project NPV (canonical Last Run)",
            f"{npv:,.0f} kEUR" + (" · prior run" if state == "STALE" else ""), True)
    else:
        project_npv = DecisionMetric(
            "project_npv", "Project NPV (canonical Last Run)", "—", False,
            "No Last Run." if state == "NOT_RUN"
            else "Not persisted by the model run (authority gap) — never derived here.")
    unmet = [c.requirement for c in EXPECTED_NPV_CONDITIONS if not c.satisfied]
    expected_npv = DecisionMetric(
        "expected_npv", "Expected NPV (probability-weighted)", "—", False,
        f"{len(unmet)} of {len(EXPECTED_NPV_CONDITIONS)} required conditions are not met.")
    margin = DecisionMetric(
        "development_margin", "Development margin", "—", False,
        "No approved definition exists; no competing MOIC is created.")
    return DecisionPanel(
        project_npv=project_npv, expected_npv=expected_npv, development_margin=margin,
        conditions=EXPECTED_NPV_CONDITIONS,
        proposal=(
            "Proposal (not implemented): a typed OutcomeScenarioSet (id, label, probability, owner, "
            "approval) in finco_core, one persisted canonical NPV per scenario Run under a single "
            "approved valuation authority, bound to Run History and covered by export parity. "
            "Expected NPV would then be sum(p_i x NPV_i) over CURRENT Runs only."),
        run_state=state,
    )


@dataclass(frozen=True)
class ProjectMeta:
    stage: str
    perspective: str
    stage_set: bool
    perspective_set: bool
    developer_emphasis: bool


def build_project_meta(project_record: Any) -> ProjectMeta:
    """Display-only stage / perspective.  Never inferred; never an input to any calculation."""
    try:
        stage = normalize_stage(getattr(project_record, "project_stage", None))
    except ValueError:
        stage = None
    try:
        persp = normalize_perspective(getattr(project_record, "model_perspective", None))
    except ValueError:
        persp = None
    stage_val = getattr(stage, "value", stage)
    persp_val = getattr(persp, "value", persp)
    return ProjectMeta(
        stage=str(stage_val) if stage_val else NOT_SET,
        perspective=str(persp_val) if persp_val else NOT_SET,
        stage_set=bool(stage_val), perspective_set=bool(persp_val),
        developer_emphasis=str(persp_val or "").upper() == "DEVELOPER",
    )


__all__ = [
    "Condition", "DecisionMetric", "DecisionPanel", "EXPECTED_NPV_CONDITIONS",
    "ProjectMeta", "build_decision_panel", "build_project_meta",
]

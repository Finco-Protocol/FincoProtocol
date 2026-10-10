"""Evidence carriers for the Model Quality evaluator.

``QualityEvidence`` is a read-only view over what the system already persisted for the Last Run
(runtime summary, run-bound financing evidence, Run Integrity evidence, run identity) plus
optional typed ``ProjectTerms``.  Nothing here executes the engine or recomputes a financial
quantity; thresholds are never invented.  A threshold that was not supplied stays ``None`` and the
dependent check is UNAVAILABLE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# Reserve regimes the terms builder can PROVE from typed inputs.
RESERVE_NONE = "NONE"                        # explicitly no reserve
RESERVE_CASH_FIXED = "CASH_DSRA_FIXED"       # cash DSRA with a fixed requirement (target is a typed input)
RESERVE_DSRF = "DSRF"                        # standby facility: not cash funded at close
RESERVE_AUTOMATIC = "AUTOMATIC_PEAK"         # engine-derived target; not persisted with the Run

# Canonical Senior absolute precision (the solver's own convergence tolerance, kEUR).
DEFAULT_TERMINAL_TOLERANCE_KEUR = 1e-4

# SHL terminal-state precision.  This mirrors the canonical terminal-state classifier
# (financial_engine.project_returns.model._TOL), which decides REPAID / UNPAID_AT_CONTRACTUAL_MATURITY /
# NOT_APPLICABLE.  It is deliberately NOT the Senior solver tolerance (1e-4): the SHL terminal contract
# has its own, stricter precision.  A test pins this constant to the engine value (parity only).
SHL_TERMINAL_TOLERANCE_KEUR = 1e-7

# The typed canonical SHL terminal statuses (mirrors financial_engine.project_returns.contracts
# .ShlTerminalStatus; a test pins the parity).  Any other value is not a status.
SHL_TERMINAL_STATUSES = ("REPAID", "UNPAID_AT_CONTRACTUAL_MATURITY",
                         "OUTSTANDING_WITHIN_CONTRACTUAL_TERM", "NOT_APPLICABLE")


@dataclass(frozen=True)
class ProjectTerms:
    """Typed project thresholds.  Every field is optional; absent means 'not supplied'.

    ``provenance`` records where each supplied value came from (for example the effective
    typed input path).  FINCO cannot tell a defaulted input from a contractually negotiated one,
    so values read from typed inputs carry the authority ``PROJECT_INPUT`` and are not described
    as lender covenants unless the caller says so via ``contractual=True``.
    """

    min_dscr_covenant: Optional[float] = None     # explicit financing-document minimum DSCR
    lockup_dscr: Optional[float] = None
    min_llcr: Optional[float] = None
    reserve_regime: Optional[str] = None
    dsra_target_keur: Optional[float] = None
    contingency_amount_keur: Optional[float] = None
    contingency_base_keur: Optional[float] = None
    contingency_policy_min_pct: Optional[float] = None   # fraction (0.05 = 5%)
    contractual: bool = False
    provenance: Mapping[str, str] = field(default_factory=dict)

    def authority(self, key: str) -> str:
        source = self.provenance.get(key)
        kind = "CONTRACTUAL_TERM" if self.contractual else "PROJECT_INPUT"
        return f"{kind}:{source}" if source else kind


def terms_from_project_inputs(project_inputs: Any, *, contractual: bool = False) -> ProjectTerms:
    """Read the typed thresholds of an EFFECTIVE ProjectInputs (read-only; no engine)."""
    from finco_core.inputs import DebtServiceReserveSupportMode

    fin = project_inputs.financing
    support = getattr(fin, "dsra_support_mode", None)
    requirement = float(getattr(fin, "debt_service_reserve_requirement_keur", 0.0) or 0.0)
    policy = getattr(fin, "dsra_target_policy", None)
    target: Optional[float] = None
    if support is DebtServiceReserveSupportMode.DSRF:
        regime = RESERVE_DSRF
    elif support is DebtServiceReserveSupportMode.CASH_DSRA and policy == "fixed_amount" and requirement > 0:
        regime, target = RESERVE_CASH_FIXED, requirement
    elif support is DebtServiceReserveSupportMode.NONE and policy == "fixed_amount" and requirement == 0:
        regime = RESERVE_NONE
    else:
        regime = RESERVE_AUTOMATIC
    prov = {
        "lockup_dscr": "financing.lockup_dscr",
        "min_llcr": "financing.min_llcr",
        "reserve_regime": "financing.dsra_support_mode",
        "dsra_target_keur": "financing.debt_service_reserve_requirement_keur",
    }
    return ProjectTerms(
        lockup_dscr=_num(getattr(fin, "lockup_dscr", None)),
        min_llcr=_num(getattr(fin, "min_llcr", None)),
        reserve_regime=regime, dsra_target_keur=target,
        contractual=contractual, provenance=prov,
    )


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


@dataclass(frozen=True)
class QualityEvidence:
    freshness: Optional[str] = None                     # CURRENT | STALE | NOT_RUN | None (unknown)
    runtime_summary: Optional[Mapping[str, Any]] = None
    integrity_evidence: Optional[Mapping[str, Any]] = None
    # ``last_sponsor_schedule["summary"]`` of the committed Run: carries the canonical terminal financial
    # state (including the SHL contractual maturity index).  Persisted in the same atomic commit as the
    # Last Run and appended to Run History; never read from the editable Working Copy.
    sponsor_summary: Optional[Mapping[str, Any]] = None
    snapshot_id: Optional[str] = None
    composite_hash: Optional[str] = None
    run_at: Optional[str] = None
    engine_version: Optional[str] = None
    last_run_scenario_id: Optional[str] = None
    active_scenario_id: Optional[str] = None
    scenario_known: bool = False                        # True when the active scenario was supplied
    terms: ProjectTerms = field(default_factory=ProjectTerms)
    terminal_tolerance_keur: float = DEFAULT_TERMINAL_TOLERANCE_KEUR
    shl_terminal_tolerance_keur: float = SHL_TERMINAL_TOLERANCE_KEUR

    @property
    def has_last_run(self) -> bool:
        return bool(self.runtime_summary) or bool(self.integrity_evidence) or bool(self.snapshot_id)

    @property
    def run_identity(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id, "composite_hash": self.composite_hash,
            "run_at": self.run_at, "engine_version": self.engine_version,
            "scenario_id": self.last_run_scenario_id,
        }


def evidence_from_workspace(ws: Any, *, freshness: Optional[str], terms: Optional[ProjectTerms] = None,
                            active_scenario_id: Optional[str] = None, scenario_known: bool = False) -> QualityEvidence:
    """Build evidence from a persisted workspace record (read-only attribute access)."""
    identity = getattr(ws, "last_runtime_identity", None) or {}
    sponsor_schedule = getattr(ws, "last_sponsor_schedule", None)
    sponsor_summary = sponsor_schedule.get("summary") if isinstance(sponsor_schedule, Mapping) else None
    ran_at = getattr(ws, "last_runtime_at", None)
    return QualityEvidence(
        freshness=freshness,
        runtime_summary=getattr(ws, "last_runtime_summary", None) or None,
        integrity_evidence=getattr(ws, "last_integrity_evidence", None) or None,
        sponsor_summary=sponsor_summary if isinstance(sponsor_summary, Mapping) else None,
        snapshot_id=getattr(ws, "last_runtime_snapshot_id", None) or None,
        composite_hash=getattr(ws, "last_runtime_composite_hash", None) or None,
        run_at=ran_at.isoformat() if hasattr(ran_at, "isoformat") else (str(ran_at) if ran_at else None),
        engine_version=(identity.get("engine_version") if isinstance(identity, Mapping) else None),
        last_run_scenario_id=getattr(ws, "last_runtime_scenario_id", None),
        active_scenario_id=active_scenario_id, scenario_known=scenario_known,
        terms=terms or ProjectTerms(),
    )

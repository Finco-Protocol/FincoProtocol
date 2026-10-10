"""The Model Quality check registry: 30 stable, typed checks, each over real persisted evidence.

Stable identities: ``QM-<CAT>-<NNN>`` never changes meaning; a retired check keeps its id reserved.
Threshold authority is stated per check: an arithmetic identity, the canonical solver precision, a
project-supplied term, or "none" (existence checks).  No threshold here is an industry default or a
FinModels-derived number; advisory ranges are never promoted to covenants.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.model_quality import evaluators as ev
from app.model_quality.contracts import Category, CheckClass, CheckStatus, QualityCheck, Severity
from app.model_quality.evaluators import Context, Evaluator, Outcome
from app.model_quality.evidence import QualityEvidence

M, C, A, E = (CheckClass.MATHEMATICAL_INTEGRITY, CheckClass.CONTRACTUAL_COVENANT,
              CheckClass.ADVISORY_RISK, CheckClass.EVIDENCE_AVAILABILITY)
CRIT, HIGH, MED, LOW = Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW

IDENTITY_AUTH = "RUN_INTEGRITY tolerance (app.run_integrity.contracts)"
ARITH_AUTH = "arithmetic identity (tolerance 1e-6 kEUR)"
NO_THRESHOLD = "none (existence / well-formedness)"


@dataclass(frozen=True)
class CheckDefinition:
    check_id: str
    category: Category
    check_class: CheckClass
    severity: Severity
    title: str
    description: str
    unit: str
    threshold_authority: str
    evidence_source: str
    evaluator: Evaluator
    assumptions: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    navigation: str = "tab-overview"


def _d(*args, **kw) -> CheckDefinition:
    return CheckDefinition(*args, **kw)


CAT = Category
REGISTRY: tuple[CheckDefinition, ...] = (
    # A. Accounting integrity
    _d("QM-ACC-001", CAT.ACCOUNTING_INTEGRITY, M, CRIT, "Balance sheet balances",
       "Assets equal liabilities plus equity in every period with a complete balance sheet (Run Integrity).",
       "kEUR", IDENTITY_AUTH, "run_integrity_evidence.balance_sheet", ev.integrity_check("BALANCE_SHEET_BALANCES"),
       outputs=("balance_sheet",), navigation="tab-fs"),
    _d("QM-ACC-002", CAT.ACCOUNTING_INTEGRITY, M, HIGH, "Sponsor return flows reconcile",
       "Published XIRR values reproduce from the committed sponsor cash flows (Run Integrity).",
       "ratio", IDENTITY_AUTH, "run_integrity_evidence.sponsor", ev.integrity_check("SPONSOR_RETURN_INPUTS_RECONCILE"),
       outputs=("equity_irr", "total_sponsor_xirr"), navigation="tab-returns"),
    _d("QM-ACC-003", CAT.ACCOUNTING_INTEGRITY, M, HIGH, "EBITDA equals revenue minus OPEX",
       "Persisted total EBITDA equals persisted total revenue minus total OPEX.",
       "kEUR", ARITH_AUTH, "runtime_summary", ev.ebitda_identity,
       outputs=("total_revenue_keur", "total_opex_keur", "total_ebitda_keur"), navigation="tab-fs"),
    _d("QM-ACC-004", CAT.ACCOUNTING_INTEGRITY, E, MED, "Return metrics published",
       "Project, equity and sponsor returns are published; a genuine 0.0 counts as published, a missing value does not.",
       "count", NO_THRESHOLD, "runtime_summary", ev.return_metric_availability,
       outputs=("project_irr", "equity_irr", "total_sponsor_xirr"), navigation="tab-returns"),
    # B. Sources & Uses
    _d("QM-SU-001", CAT.SOURCES_USES, M, CRIT, "Sources equal Uses",
       "Total Sources equal total Uses with developer reimbursement and fee itemised (Run Integrity).",
       "kEUR", IDENTITY_AUTH, "run_integrity_evidence.sources_uses", ev.integrity_check("SOURCES_EQUAL_USES"),
       outputs=("total_project_uses_keur",), navigation="tab-debt"),
    _d("QM-SU-002", CAT.SOURCES_USES, M, HIGH, "Construction funding reconciles",
       "Run-bound construction funding shows no period or cumulative Sources/Uses difference.",
       "kEUR", ARITH_AUTH, "runtime_summary.financing_evidence.construction_funding", ev.construction_funding_reconciliation,
       outputs=("financing_evidence",), navigation="tab-debt"),
    _d("QM-SU-003", CAT.SOURCES_USES, E, LOW, "Developer uses itemised",
       "Developer reimbursement and fee are present as separate Uses; absent evidence is never read as zero.",
       "kEUR", NO_THRESHOLD, "run_integrity_evidence.sources_uses.summary", ev.developer_uses_itemised,
       outputs=("development_cost_reimbursement_keur", "developer_fee_keur"), navigation="tab-debt"),
    # C. Senior debt / bankability
    _d("QM-SD-001", CAT.SENIOR_DEBT, M, CRIT, "Senior debt roll-forward",
       "Opening plus draws less principal equals closing in every period (Run Integrity).",
       "kEUR", IDENTITY_AUTH, "run_integrity_evidence.senior_debt", ev.integrity_check("SENIOR_DEBT_ROLLFORWARD"),
       outputs=("senior_debt_keur",), navigation="tab-debt"),
    _d("QM-SD-002", CAT.SENIOR_DEBT, M, HIGH, "Interest and debt service consistent",
       "Interest equals opening x rate x day fraction and debt service equals interest plus principal (Run Integrity).",
       "kEUR", IDENTITY_AUTH, "run_integrity_evidence.senior_debt", ev.integrity_check("INTEREST_DEBT_SERVICE_CONSISTENCY"),
       outputs=("total_senior_ds_keur",), navigation="tab-debt"),
    _d("QM-SD-003", CAT.SENIOR_DEBT, M, HIGH, "DSCR equals CFADS over debt service",
       "Reported DSCR equals base CFADS divided by debt service (Run Integrity).",
       "ratio", IDENTITY_AUTH, "run_integrity_evidence.senior_debt", ev.integrity_check("DSCR_EQUALS_CFADS_OVER_DEBT_SERVICE"),
       outputs=("min_dscr", "avg_dscr"), navigation="tab-debt"),
    _d("QM-SD-004", CAT.SENIOR_DEBT, M, HIGH, "Sculpted debt service fits allowed debt service",
       "Scheduled debt service never exceeds bank CFADS over the target DSCR (Run Integrity).",
       "kEUR", IDENTITY_AUTH, "run_integrity_evidence.senior_debt", ev.integrity_check("DSCR_SCULPTING_FEASIBLE"),
       assumptions=("financing.target_dscr",), outputs=("target_dscr",), navigation="tab-debt"),
    _d("QM-SD-005", CAT.SENIOR_DEBT, M, HIGH, "Solver result authoritative",
       "The Senior solver terminated CONVERGED with an authoritative result. Convergence is not lender approval.",
       "flag", NO_THRESHOLD, "run_integrity_evidence.senior_debt.diagnostics", ev.solver_authority,
       outputs=("senior_debt_keur",), navigation="tab-debt"),
    _d("QM-SD-006", CAT.SENIOR_DEBT, M, MED, "Actual gearing within requested cap",
       "Actual funded gearing (never the requested value) does not exceed the requested gearing cap.",
       "fraction", "requested gearing cap (financing.gearing_ratio)", "runtime_summary", ev.actual_vs_requested_gearing,
       assumptions=("financing.gearing_ratio",), outputs=("actual_gearing_pct", "gearing_cap_pct"), navigation="tab-debt"),
    _d("QM-SD-007", CAT.SENIOR_DEBT, A, HIGH, "Minimum DSCR vs sizing target",
       "FAIL below 1.0x (CFADS does not cover debt service); WARNING below the effective period sizing target. "
       "The sizing target is a model assumption, not a lender covenant.",
       "ratio", "arithmetic (1.0x) and the effective sizing target", "run_integrity_evidence.senior_debt.periods",
       ev.minimum_dscr, assumptions=("financing.target_dscr",), outputs=("min_dscr", "target_dscr"), navigation="tab-debt"),
    # D. Cash / liquidity
    _d("QM-CASH-001", CAT.CASH_LIQUIDITY, M, HIGH, "No unfunded cash deficit",
       "No negative cash or reserve balance without a funding source (Run Integrity).",
       "kEUR", IDENTITY_AUTH, "run_integrity_evidence.cash", ev.integrity_check("NO_UNFUNDED_CASH_DEFICIT"),
       navigation="tab-fs"),
    _d("QM-CASH-002", CAT.CASH_LIQUIDITY, C, HIGH, "DSRA funded to its proven target",
       "Initial cash DSRA funding meets the typed fixed requirement. Evaluated only when that target is proven; "
       "a dynamic or missing target is UNAVAILABLE, a standby DSRF is not cash funded.",
       "kEUR", "typed financing.debt_service_reserve_requirement_keur", "run_integrity_evidence.sources_uses + project terms",
       ev.dsra_funding_vs_target, assumptions=("financing.dsra_support_mode", "financing.debt_service_reserve_requirement_keur"),
       outputs=("initial_dsra_funding_keur",), navigation="tab-debt"),
    # E. Covenants
    _d("QM-COV-001", CAT.COVENANTS, C, HIGH, "Minimum DSCR covenant",
       "Minimum base DSCR vs a supplied financing-document minimum. Never inferred when not supplied.",
       "ratio", "supplied project term (min_dscr_covenant)", "run_integrity_evidence + project terms", ev.covenant_min_dscr,
       outputs=("min_dscr",), navigation="tab-debt"),
    _d("QM-COV-002", CAT.COVENANTS, C, MED, "Distribution lock-up threshold",
       "Minimum base DSCR vs the project's lock-up DSCR. A trigger restricts distributions; it is not a default.",
       "ratio", "project input financing.lockup_dscr", "run_integrity_evidence + project terms", ev.lockup_dscr,
       assumptions=("financing.lockup_dscr",), outputs=("min_dscr", "periods_in_lockup"), navigation="tab-debt"),
    _d("QM-COV-003", CAT.COVENANTS, C, HIGH, "Minimum LLCR requirement",
       "Persisted minimum LLCR vs the project's requirement; UNAVAILABLE when the Run does not publish an LLCR.",
       "ratio", "project input financing.min_llcr", "runtime_summary + project terms", ev.llcr_requirement,
       assumptions=("financing.min_llcr",), outputs=("min_llcr",), navigation="tab-debt"),
    _d("QM-COV-004", CAT.COVENANTS, C, MED, "Covenant ordering",
       "Supplied thresholds are ordered minimum covenant <= lock-up <= sizing target.",
       "ratio", "supplied project terms and the effective sizing target", "project terms", ev.covenant_ordering,
       assumptions=("financing.lockup_dscr", "financing.target_dscr"), navigation="tab-debt"),
    # F. CAPEX / construction
    _d("QM-CAP-001", CAT.CAPEX_CONSTRUCTION, A, MED, "Contingency adequacy vs project policy",
       "Contingency share of its base vs the project's documented minimum; not evaluated without a documented policy.",
       "fraction", "supplied project policy (contingency_policy_min_pct)", "project terms", ev.contingency_adequacy,
       outputs=("total_capex_keur",), navigation="tab-capex"),
    # G. Revenue
    _d("QM-REV-001", CAT.REVENUE, E, MED, "Revenue evidence complete",
       "The persisted revenue derivation lists every period it claims.",
       "count", NO_THRESHOLD, "runtime_summary.revenue_derivation", ev.revenue_evidence_complete,
       outputs=("total_revenue_keur",), navigation="tab-revenue"),
    _d("QM-REV-002", CAT.REVENUE, M, HIGH, "Revenue periods sum to total revenue",
       "The sum of persisted period revenue equals the published total revenue.",
       "kEUR", ARITH_AUTH, "runtime_summary.revenue_derivation", ev.revenue_periods_reconcile,
       outputs=("total_revenue_keur",), navigation="tab-revenue"),
    # H. Terminal liability
    _d("QM-TERM-001", CAT.TERMINAL_LIABILITY, M, CRIT, "Senior fully settled at maturity",
       "Closing Senior principal at the final contractual period is within canonical solver precision. "
       "An unsupported balloon is a blocking finding (PR #233 protection).",
       "kEUR", "canonical Senior solver precision (1e-4 kEUR)", "run_integrity_evidence.senior_debt.periods",
       ev.senior_settled_at_maturity, outputs=("senior_debt_keur",), navigation="tab-debt"),
    _d("QM-TERM-002", CAT.TERMINAL_LIABILITY, M, HIGH, "Shareholder loan settled at contractual maturity",
       "The committed SHL balance is within the SHL terminal precision at the contractual maturity period "
       "proven by the Run's canonical terminal state, and no SHL liability remains after it. Sponsor return "
       "statuses are corroboration only. NOT_APPLICABLE only when the canonical terminal state proves no SHL.",
       "kEUR", "SHL terminal precision (1e-7 kEUR, canonical terminal-state classifier)",
       "sponsor_schedule.summary.terminal_financial_state.shareholder_loan + integrity_evidence.balance_sheet[].shl",
       ev.shl_terminal, outputs=("total_sponsor_xirr", "terminal_financial_state"), navigation="tab-returns"),
    # I. Provenance and freshness
    _d("QM-PRV-001", CAT.PROVENANCE_FRESHNESS, M, HIGH, "Evidence digest intact",
       "The committed integrity evidence is unaltered since commit (Run Integrity).",
       "flag", IDENTITY_AUTH, "run_integrity_evidence.digest", ev.integrity_check("EVIDENCE_DIGEST"),
       navigation="tab-run-history"),
    _d("QM-PRV-002", CAT.PROVENANCE_FRESHNESS, E, HIGH, "Run identity complete",
       "Snapshot id, composite hash, run time and engine version are all present.",
       "count", NO_THRESHOLD, "workspace last-run identity", ev.run_identity_complete, navigation="tab-run-history"),
    _d("QM-PRV-003", CAT.PROVENANCE_FRESHNESS, E, MED, "Last Run is current",
       "CURRENT when the Last Run matches the Working Copy; STALE means this evaluation describes the prior Run.",
       "flag", NO_THRESHOLD, "canonical runtime freshness", ev.freshness, navigation="tab-overview"),
    _d("QM-PRV-004", CAT.PROVENANCE_FRESHNESS, E, MED, "Financing evidence bound to this Run",
       "Run-bound financing evidence names this exact snapshot, composite hash and scenario.",
       "flag", NO_THRESHOLD, "runtime_summary.financing_evidence.run_binding", ev.financing_evidence_bound,
       navigation="tab-run-history"),
    _d("QM-PRV-005", CAT.PROVENANCE_FRESHNESS, E, LOW, "Scenario identity",
       "The active scenario is the scenario the Last Run was produced under.",
       "flag", NO_THRESHOLD, "workspace active scenario vs last-run scenario", ev.scenario_identity,
       navigation="tab-scenarios"),
)

assert len({d.check_id for d in REGISTRY}) == len(REGISTRY), "duplicate check ids"


def _build(definition: CheckDefinition, outcome: Outcome) -> QualityCheck:
    return QualityCheck(
        check_id=definition.check_id, category=definition.category, check_class=definition.check_class,
        title=definition.title, description=definition.description, status=outcome.status,
        severity=definition.severity, measured_value=outcome.value, measured_unit=definition.unit,
        threshold_value=outcome.threshold, threshold_authority=definition.threshold_authority,
        evidence_source=definition.evidence_source, reason_code=outcome.reason,
        related_assumption_ids=definition.assumptions, related_output_keys=definition.outputs,
        navigation_target=definition.navigation, detail=outcome.detail,
    )


def run_registry(evidence: QualityEvidence) -> tuple[QualityCheck, ...]:
    """Evaluate every registered check.  Never raises; malformed evidence is UNAVAILABLE, never PASS."""
    context = Context(evidence)
    results = []
    for definition in REGISTRY:
        if not evidence.has_last_run:
            outcome = ev._unavailable("NO_LAST_RUN")
        else:
            try:
                outcome = definition.evaluator(context)
            except Exception:  # noqa: BLE001 - malformed evidence must never become PASS or crash the surface
                outcome = ev._unavailable("CHECK_EVIDENCE_MALFORMED")
        results.append(_build(definition, outcome))
    return tuple(results)

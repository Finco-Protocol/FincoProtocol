"""finco_core.engine — Engine orchestration: PeriodEngine and DistributionAccountEngine.

V2-4: Authoritative. finco_core.engine.period_engine and domain.distribution_account are compatibility shims.
"""
from finco_core.engine.period_engine import PeriodMeta, PeriodEngine, hash_engine_for_cache
from finco_core.engine.distribution_account import (
    DistributionAccountEngine,
    DistributionAccountInputs,
    DistributionAccountPeriodInput,
    R99R102GateInputs,
    DistributionAccountResult,
    DistributionAccountPeriodResult,
    DistributionGateResult,
    R99InputResult,
    BLOCKED_REASONS,
    evaluate_r99_gate,
    evaluate_r102_gate,
    evaluate_dscr_gate,
    evaluate_lockup_gate,
    evaluate_reference_scope_guard,
    evaluate_cash_gate,
    DistributionAuditRow,
    compute_reference_covenant_input_period,
)
__all__ = [
    "PeriodMeta", "PeriodEngine", "hash_engine_for_cache",
    "DistributionAccountEngine", "DistributionAccountInputs", "DistributionAccountPeriodInput",
    "R99R102GateInputs", "DistributionAccountResult", "DistributionAccountPeriodResult",
    "DistributionGateResult", "R99InputResult", "BLOCKED_REASONS",
    "evaluate_r99_gate", "evaluate_r102_gate", "evaluate_dscr_gate",
    "evaluate_lockup_gate", "evaluate_reference_scope_guard", "evaluate_cash_gate",
    "DistributionAuditRow", "compute_reference_covenant_input_period",
]

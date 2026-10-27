"""Resolve an opted-in SHL contract on the canonical calendar, without pricing."""
from finco_core.inputs.shl_timing import ShlTimingBasis, ShlTimingIssue


def resolve_shl_timing(financing, periods, senior_maturity):
    basis = financing.shl_timing_basis
    if not isinstance(basis, ShlTimingBasis):
        raise ValueError("SHL_TIMING_BASIS_INVALID")
    if basis is ShlTimingBasis.ABSOLUTE_INDEX:
        return (financing.shl_principal_eligibility_start_period,
                financing.shl_maturity_period_index)
    operating = tuple(p for p in periods if p.is_operation)
    if not operating or senior_maturity is None:
        raise ValueError("SHL_TIMING_SENIOR_CALENDAR_AUTHORITY_REQUIRED")
    indices = [p.period_index for p in operating]
    if len(set(indices)) != len(indices) or indices != sorted(indices):
        raise ValueError("SHL_TIMING_PERIOD_AXIS_INVALID")
    if senior_maturity not in indices:
        raise ValueError("SHL_TIMING_SENIOR_MATURITY_NOT_ON_CALENDAR")
    eligible = next((p.period_index for p in operating if p.period_index > senior_maturity), None)
    if eligible is None:
        raise ValueError("GENERIC_SHL_POLICY_UNSERVICEABLE: no operating period after Senior maturity")
    return eligible, operating[-1].period_index


def timing_evidence(financing, periods, shl_terminal):
    operating = tuple(p for p in periods if p.is_operation)
    maturity = shl_terminal.contractual_maturity_period_index
    drift = (maturity is not None and operating and maturity != operating[-1].period_index)
    return {
        "contract_version": "SHL_TIMING_V1",
        "basis": financing.shl_timing_basis.value,
        "maturity_period_index": maturity,
        "model_end_period_index": operating[-1].period_index if operating else None,
        "issues": [ShlTimingIssue.SHL_MATURITY_NOT_AT_MODEL_END.value] if drift else [],
        "historical_inputs_reinterpreted": False,
    }

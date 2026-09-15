"""Debt schedule reconciliation helper."""
from typing import Any


def build_debt_schedule_rows(result: Any) -> list[dict]:
    """Build debt schedule reconciliation rows from a DemoResult or WaterfallResult.

    Returns list of dicts with columns:
        period, date, opening_senior_debt, senior_interest, senior_principal,
        total_senior_ds, closing_senior_debt, cfads, dscr

    Handles DemoResult (result.waterfall_result IS the WaterfallResult) and raw WaterfallResult.
    Supports both IterativeSculptResult (field: payments) and ClosedFormSculptResult (field: payment_schedule).

    Sculpt schedule semantics:
    - balance_sched[0] = initial debt (opening balance before first operation period)
    - balance_sched[1..n] = closing balance AFTER operation periods 1..n
    - balance_sched has n_op_periods + 1 entries (initial + n closing balances)
    - balance_sched[n] = 0 when loan is fully repaid
    
    Mapping:
    - opening[op_idx] = balance_sched[op_idx] (initial debt for op_idx=0)
    - closing[op_idx] = balance_sched[op_idx + 1] (shifted by 1)
    - This means opening[op_idx] = closing[op_idx - 1] for op_idx > 0
    """
    # Unwrap DemoResult → WaterfallResult
    wf = None
    if hasattr(result, "result") and hasattr(result, "waterfall_result"):
        wf = result.waterfall_result
    elif hasattr(result, "periods"):
        wf = result

    if wf is None:
        return []

    periods = wf.periods if hasattr(wf, "periods") else []
    if not periods:
        return []

    sculpt = wf.sculpting_result if hasattr(wf, "sculpting_result") and wf.sculpting_result else None

    # Resolve sculpt schedule fields
    if sculpt:
        debt_keur = sculpt.debt_keur
        interest_sched = sculpt.interest_schedule
        principal_sched = sculpt.principal_schedule
        balance_sched = sculpt.balance_schedule
        dscr_sched = sculpt.dscr_schedule
        payment_sched = getattr(sculpt, "payments", None) or getattr(sculpt, "payment_schedule", [])
    else:
        debt_keur = 0.0
        interest_sched = principal_sched = balance_sched = dscr_sched = []
        payment_sched = []

    # Build CFADS per operation period
    op_periods = [p for p in periods if p.is_operation]
    cfads_list = [p.ebitda_keur for p in op_periods]

    rows = []
    op_idx = 0  # operation period index for sculpt schedule lookup

    for p in periods:
        if not p.is_operation:
            continue

        # Opening balance: balance_sched[op_idx]
        # For op_idx=0: initial debt (debt_keur = balance_sched[0])
        # For op_idx>0: closing of previous period = balance_sched[op_idx]
        if sculpt and op_idx < len(balance_sched):
            opening = balance_sched[op_idx]
        elif op_idx == 0:
            opening = debt_keur
        else:
            opening = 0.0

        # Closing balance: balance_sched[op_idx + 1]
        # (balance_sched is shifted by 1 relative to closing balances)
        if sculpt and op_idx + 1 < len(balance_sched):
            closing = balance_sched[op_idx + 1]
        else:
            closing = 0.0

        # Determine interest/principal from sculpt schedule
        if sculpt and op_idx < len(interest_sched):
            si = interest_sched[op_idx]
            sp = principal_sched[op_idx]
            total_ds = payment_sched[op_idx] if op_idx < len(payment_sched) else si + sp
            dscr_val = dscr_sched[op_idx] if op_idx < len(dscr_sched) else 0.0
        else:
            si = p.senior_interest_keur
            sp = p.senior_principal_keur
            total_ds = p.senior_ds_keur
            dscr_val = p.dscr
            closing = p.senior_balance_keur

        # Use waterfall CFADS
        cfads = p.ebitda_keur

        # Guard against inf/nan DSCR
        if dscr_val == float('inf') or (isinstance(dscr_val, float) and dscr_val != dscr_val):
            dscr_val = 0.0
        elif dscr_val <= 0:
            dscr_val = 0.0

        rows.append({
            "period": p.period,
            "date": p.date,
            "opening_senior_debt": round(opening, 1),
            "senior_interest": round(si, 1),
            "senior_principal": round(sp, 1),
            "total_senior_ds": round(total_ds, 1),
            "closing_senior_debt": round(closing, 1),
            "cfads": round(cfads, 1),
            "dscr": round(dscr_val, 3) if dscr_val else 0.0,
        })
        op_idx += 1

    return rows
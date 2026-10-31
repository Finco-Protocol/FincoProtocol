"""FIN-V2-D01: one canonical Senior all-in rate-shock authority for every sensitivity surface.

A requested interest shock is applied to the rate the clean Senior engine ACTUALLY consumes — the typed explicit all-in
period vector (``financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates``) — and to nothing else.

Why this module exists
----------------------
The legacy and lender-case surfaces shifted ``financing.base_rate``.  That field is auxiliary state: with an explicit
all-in schedule (every shipped reference and every F01-verified working copy) the engine never reads it, so a "+100 bps"
shock returned a valid-looking result in which every KPI was unchanged.  The two-driver matrix already shocked the typed
vector (``sensitivity_matrix._senior_rate_percent`` + ``ProjectInputSet.with_value``); this module gives the remaining
surfaces the same semantics through the same setter, never a second implementation of the %/ratio conversion.

Contract (``RATE_SHOCK_CONTRACT``)
----------------------------------
* ``FLAT`` typed schedule (uniform vector): every period moves by ``bps`` basis points; 5.5 % + 100 bps -> 6.5 %.
* ``CALIBRATED`` / non-uniform / absent explicit vector: REFUSED (``RATE_SHOCK_CALIBRATED_SCHEDULE``) — a scalar cannot
  faithfully shift a contractual period schedule and no schedule is invented.
* Bankability-owned rates (when the owning snapshot is available): REFUSED, exactly as the Save path refuses them.
* Out-of-range result (outside the 0..20 % human-percent contract of ``_validated_rate_percent``): REFUSED.
* A shock that does not change the effective vector: REFUSED (``RATE_SHOCK_NOT_APPLIED``) — never a flat "result".
* Unit boundary: the human-percent value is converted to a ratio exactly once, inside
  ``input_adapter._set_financing_interest_rate``.  Historical rows without ``human_percent_v1`` provenance are never
  migrated or reinterpreted (``RATE_UNIT_PROVENANCE_AMBIGUOUS`` from the F01 authority is surfaced unchanged).

Project IRR is unlevered and legitimately does not move under a rate shock; the financing-dependent KPIs
(``FINANCING_DEPENDENT_KPIS``) are the ones an applied shock is expected to move.  Nothing here reads or edits a result.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

RATE_SHOCK_CONTRACT = "senior_all_in_rate_bps_v1"

#: Rate bounds of the human-percent contract (``input_adapter._validated_rate_percent``): 0..20 %.
MIN_RATE_PERCENT = 0.0
MAX_RATE_PERCENT = 20.0

#: Sensitivity KPIs that depend on Senior pricing.  ``project_irr`` (unlevered) is deliberately NOT in this set.
FINANCING_DEPENDENT_KPIS = frozenset({
    "total_senior_ds_keur", "total_tax_keur", "total_distribution_keur", "equity_irr", "equity_npv",
    "actual_avg_dscr", "min_dscr", "min_llcr", "_cfads_keur",
})
# Base CFADS includes cash tax and can move with the interest tax shield.
UNLEVERED_KPIS = frozenset({"project_irr", "total_revenue_keur", "total_ebitda_keur"})


class RateShockRefusal(ValueError):
    """A requested rate shock cannot be applied faithfully.  ``code`` is the stable typed reason."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def _finite_bps(bps: Any) -> float:
    if isinstance(bps, bool) or not isinstance(bps, (int, float)) or not math.isfinite(float(bps)):
        raise RateShockRefusal("RATE_SHOCK_LEVEL_INVALID", "the shock must be a finite number of basis points")
    return float(bps)


def effective_senior_rate_percent(proj: Any) -> float:
    """The uniform Senior all-in rate in HUMAN PERCENT, from the typed authority the engine consumes."""
    from app.input_adapter import senior_rate_authority

    mode, ratio, _periods = senior_rate_authority(proj)
    if mode != "FLAT" or ratio is None:
        raise RateShockRefusal(
            "RATE_SHOCK_CALIBRATED_SCHEDULE",
            "the Senior all-in rate is a contractual period schedule, not one scalar; a shock would be invented")
    if not proj.financing.senior_debt_interest_config.enabled:
        raise RateShockRefusal("RATE_SHOCK_SENIOR_PRICING_DISABLED", "Senior interest is not priced by the typed schedule")
    return ratio * 100.0


def shocked_rate_percent(current_percent: float, bps: float) -> float:
    """``current + bps/100`` in percentage points.  Same arithmetic as the two-driver matrix (``level * 0.01``)."""
    shocked = current_percent + bps * 0.01
    if not math.isfinite(shocked) or not MIN_RATE_PERCENT <= shocked <= MAX_RATE_PERCENT:
        raise RateShockRefusal(
            "RATE_SHOCK_OUT_OF_RANGE",
            f"{current_percent:g}% {bps:+g} bps = {shocked:g}% is outside the supported 0..20% all-in rate range")
    return shocked


def assert_rate_not_owned(snapshot: Optional[Mapping[str, Any]]) -> None:
    """Refuse when the owning snapshot proves the bankability configuration owns the Senior rate vector."""
    if not snapshot:
        return
    from app.workbook.bankability_config import SNAPSHOT_KEY, parse_config

    try:
        owned = parse_config(snapshot.get(SNAPSHOT_KEY)).get("rates_pct") is not None
    except Exception as exc:  # noqa: BLE001 - an unreadable owner is never treated as "not owned"
        raise RateShockRefusal("RATE_SHOCK_OWNER_UNREADABLE", str(exc)[:120]) from exc
    if owned:
        raise RateShockRefusal(
            "RATE_SHOCK_BANKABILITY_OWNED",
            "the bankability configuration owns the Senior rates; edit or reset that configuration first")


def apply_rate_shock_bps(proj: Any, bps: Any, *, snapshot: Optional[Mapping[str, Any]] = None) -> Any:
    """Return ``proj`` with the Senior all-in rate vector shifted by ``bps`` basis points, or raise ``RateShockRefusal``.

    A zero shock is the identity (the same object).  A non-zero shock always changes the effective vector or refuses.
    """
    bps_f = _finite_bps(bps)
    if bps_f == 0.0:
        return proj
    assert_rate_not_owned(snapshot)
    from app.input_adapter import _set_financing_interest_rate, senior_rate_authority

    before = effective_senior_rate_percent(proj)
    target = shocked_rate_percent(before, bps_f)
    shocked = _set_financing_interest_rate(proj, target)          # the single %/ratio conversion boundary (F01)
    if shocked is proj or senior_rate_authority(shocked) == senior_rate_authority(proj):
        raise RateShockRefusal(
            "RATE_SHOCK_NOT_APPLIED",
            f"{bps_f:+g} bps did not change the effective Senior rate vector ({before:g}%)")
    return shocked


def rate_shock_evidence(before: Any, after: Any, bps: Any) -> dict:
    """Auditable before/after of the effective vector (percent), for rows, summaries and tests."""
    return {
        "contract": RATE_SHOCK_CONTRACT,
        "bps": float(bps),
        "before_pct": effective_senior_rate_percent(before),
        "after_pct": effective_senior_rate_percent(after),
    }


def plan_one_driver_rate_points(pis_base: Any, steps_pp: list) -> list:
    """Workbook (ProjectInputSet) plan for the V2 one-driver interest sensitivity.

    ``steps_pp`` are percentage-point offsets (``-2.0`` == -200 bps).  Returns one dict per step:
    ``{"step", "new_value": <human-percent str or None for the unshocked base>, "original_pct", "refusal": None | RateShockRefusal}``.
    Raises ``RateShockRefusal`` before any model execution when the effective rate cannot be shocked faithfully at all
    (calibrated schedule, bankability-owned, ambiguous unit); a single out-of-range step is carried as that step's ``refusal``.
    Reads the typed authority, never the raw snapshot scalar, so it cannot misread a stored unit.
    """
    from app.input_adapter import RateUnitProvenanceError, assert_debt_scalar_edit_allowed
    from app.workbook.service import WorkbookService

    field_id = "debt.senior.interest_rate_pct"
    try:
        proj = WorkbookService.to_projectinputs(pis_base)
    except RateUnitProvenanceError as exc:
        raise RateShockRefusal(exc.code, str(exc)[:160]) from exc
    except ValueError as exc:
        raise RateShockRefusal("RATE_SHOCK_BASE_UNAVAILABLE", str(exc)[:160]) from exc
    try:
        assert_debt_scalar_edit_allowed(pis_base, field_id)
    except ValueError as exc:
        text = str(exc)
        if "bankability" in text.lower():
            code = "RATE_SHOCK_BANKABILITY_OWNED"
        elif "calibrated" in text.lower():
            code = "RATE_SHOCK_CALIBRATED_SCHEDULE"
        else:
            code = "RATE_SHOCK_BASE_UNAVAILABLE"
        raise RateShockRefusal(code, text[:160]) from exc
    original = effective_senior_rate_percent(proj)
    plan = []
    for step in steps_pp:
        if step == 0:
            plan.append({"step": step, "new_value": None, "original_pct": original, "refusal": None})
            continue
        try:
            target = shocked_rate_percent(original, float(step) * 100.0)
        except RateShockRefusal as exc:       # one unrepresentable step (e.g. below 0 %) fails alone; the others still run
            plan.append({"step": step, "new_value": None, "original_pct": original, "refusal": exc})
            continue
        plan.append({"step": step, "new_value": str(target), "original_pct": original, "refusal": None})
    return plan

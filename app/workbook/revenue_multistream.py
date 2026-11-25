"""Workspace bridge to the explicit dated revenue authority, never a calculator."""
from dataclasses import fields, replace

from domain.revenue.multistream_runtime import parse_config

FIELD_ID = "revenue.multistream.contracts"
SNAPSHOT_KEY = "rev_multistream_config_json"


def assert_legacy_pricing_edit(snapshot, field_id):
    if snapshot.get(SNAPSHOT_KEY) and field_id.startswith(("revenue.ppa.", "revenue.merchant.")):
        raise ValueError("REVENUE_V2_PRICING_AUTHORITY: edit the explicit revenue contracts instead of legacy pricing")


def canonical_json(raw):
    config = parse_config(raw)
    return config.canonical_json if config is not None else ""


def apply_config(inputs, raw, *, project_type):
    config = parse_config(raw)
    if config is None:
        return inputs
    if str(project_type).strip().lower() != config.technology:
        raise ValueError("REVENUE_V2_TECHNOLOGY: contract technology must match the project")
    if getattr(config, "has_rec", False) and inputs.revenue.co2_enabled:
        raise ValueError("REVENUE_V3_REC_LEGACY_CONFLICT: explicit REC cannot coexist with legacy certificate revenue")
    from finco_core.inputs._models import RevenueParams
    from finco_core.inputs.revenue_multistream import MultiStreamRevenueParams
    revenue = MultiStreamRevenueParams(**{f.name: getattr(inputs.revenue, f.name) for f in fields(RevenueParams)},
                                       multistream_config_json=config.canonical_json)
    candidate = replace(inputs, revenue=revenue)
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    engine = _build_period_engine(from_project_inputs(candidate))
    if getattr(config, "has_contractual_indexation", False):
        if engine.cod != candidate.info.cod_date:
            raise ValueError("REVENUE_V2_TIMELINE_COD: Project Timeline and PeriodEngine COD disagree")
        config.validate_axis(engine.periods(), project_cod=candidate.info.cod_date, date_aware=engine.dated_life_end_exclusive is not None)
    else:
        config.validate_axis(engine.periods(), date_aware=engine.dated_life_end_exclusive is not None)
    if getattr(config, "has_absolute_annual_quantity", False):
        from finco_core.engine.date_authority import assert_grid_conserves_operating_life
        assert_grid_conserves_operating_life(candidate, engine)
        config.validate_global_p50_cap(candidate)
    return candidate


def assess_snapshot_bank_case_readiness(snapshot, *, scenario_overrides=None):
    """Non-mutating bank-case R04 readiness assessment for a workspace snapshot.

    Returns ``None`` when no explicit R04 absolute-annual contract book is active.
    Never triggers a financing/tax Run and never mutates persistence.
    """
    effective = dict(snapshot or {})
    if scenario_overrides:
        from app.persistence.scenarios_repository import resolve_scenario_snapshot
        effective = resolve_scenario_snapshot(effective, scenario_overrides)
    raw = (effective.get(SNAPSHOT_KEY) or "").strip()
    if not raw:
        return None
    try:
        config = parse_config(raw)
        if config is None or not getattr(config, "has_absolute_annual_quantity", False):
            return None
        from app.workbook.input_set import ProjectInputSet
        pi = ProjectInputSet.from_snapshot(effective).to_projectinputs()
        return config.assess_bank_case_readiness(pi).to_dict()
    except Exception as exc:  # noqa: BLE001 - fail closed with typed diagnostic
        err_code = getattr(exc, "code", "R04_READINESS_UNAVAILABLE")
        is_p50_cap = err_code == "R04_GLOBAL_P50_CAP_EXCEEDED"
        return {
            "applicable": True,
            "runnable": False,
            "status": "P50_CAP_EXCEEDED" if is_p50_cap else "INVALID_CONTRACT",
            "cap_envelope_basis": "P50",
            "error_code": err_code,
            "message": str(exc),
            "remediation": (
                "Reduce declared annual physical PPA quantities or adjust contract dates so total physical commitments fit within the P50 envelope."
                if is_p50_cap
                else "Review revenue contract dates, quantities, and project timeline."
            ),
            "shortfall_periods": [],
            "details": dict(getattr(exc, "details", {}) or {}),
        }

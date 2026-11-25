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


def assess_workspace_bank_case_readiness(ws, owner: str):
    """Non-mutating R04 bank-case readiness for an active workspace, enforcing Run scenario authority."""
    snap = dict(getattr(ws, "draft_snapshot", None) or {})
    active_scenario_id = getattr(ws, "active_scenario_id", None)
    if not active_scenario_id:
        if not (snap.get(SNAPSHOT_KEY) or "").strip():
            return None
        return assess_snapshot_bank_case_readiness(snap)

    from app.persistence.scenarios_repository import get_scenario
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.scenario_override_authority import resolve_effective_scenario_inputs
    from app.workbook.service import WorkbookService

    sc_rec = get_scenario(active_scenario_id, owner)
    sc_overrides = dict(getattr(sc_rec, "overrides", None) or {}) if sc_rec is not None else {}
    has_r04_book = bool((snap.get(SNAPSHOT_KEY) or "").strip() or (sc_overrides.get(SNAPSHOT_KEY) or "").strip())
    if not has_r04_book:
        return None

    try:
        if sc_rec is None:
            raise ValueError("SCENARIO_NOT_FOUND: Active scenario could not be found. Please re-select a scenario and try again.")
        if getattr(sc_rec, "archived", False):
            raise ValueError("SCENARIO_ARCHIVED: Active scenario has been archived. Please re-select a scenario and try again.")
        if getattr(sc_rec, "project_id", None) != getattr(ws, "project_id", ""):
            raise ValueError("SCENARIO_PROJECT_MISMATCH: Active scenario does not belong to this project. Please re-select and try again.")
        pis = ProjectInputSet.from_snapshot(snap)
        base_override = WorkbookService.to_projectinputs(pis)
        resolved_pi, _ = resolve_effective_scenario_inputs(
            pis,
            base_override,
            project_id=getattr(ws, "project_id", ""),
            sc_rec=sc_rec,
        )
        sc_raw = (getattr(resolved_pi.revenue, "multistream_config_json", "") or "").strip()
        if not sc_raw:
            return None
        cfg = parse_config(sc_raw)
        if cfg is None or not getattr(cfg, "has_absolute_annual_quantity", False):
            return None
        return cfg.assess_bank_case_readiness(resolved_pi).to_dict()
    except Exception as exc:  # noqa: BLE001 - fail closed; never report READY for stale/invalid scenario
        msg = str(exc)
        err_code = getattr(exc, "code", None)
        if not err_code:
            for prefix in (
                "Q4_SCENARIO_SOURCE_CHANGED_REPREVIEW_REQUIRED",
                "Q4_SCENARIO_OVERRIDE_AUTHORITY_INVALID",
                "Q4_WORKBOOK_MAPPING_CHANGED",
                "Q4_SCENARIO_OVERRIDE_VALUE_INVALID",
                "Q4_SCENARIO_ENGINE_INPUT_MISMATCH",
                "SCENARIO_OVERRIDE_UNBOUND",
                "SCENARIO_NOT_FOUND",
                "SCENARIO_ARCHIVED",
                "SCENARIO_PROJECT_MISMATCH",
            ):
                if prefix in msg:
                    err_code = prefix
                    break
        is_p50_cap = err_code == "R04_GLOBAL_P50_CAP_EXCEEDED"
        is_scenario_err = bool(err_code and (err_code.startswith("SCENARIO_") or err_code.startswith("Q4_")))
        return {
            "applicable": True,
            "runnable": False,
            "status": (
                "P50_CAP_EXCEEDED"
                if is_p50_cap
                else ("SCENARIO_UNAVAILABLE" if is_scenario_err else "INVALID_CONTRACT")
            ),
            "cap_envelope_basis": "P50",
            "error_code": err_code or "R04_READINESS_UNAVAILABLE",
            "message": msg,
            "remediation": (
                "Re-select, repair, or re-preview the active scenario before running R04 physical contracts."
                if is_scenario_err
                else "Review revenue contract dates, quantities, and project timeline."
            ),
            "shortfall_periods": [],
            "details": dict(getattr(exc, "details", {}) or {}),
        }

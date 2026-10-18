"""RC-7 test helper: commit a REAL engine Run through the production persistence path.

Mirrors the production commit (kpis + run-bound financing_evidence + integrity evidence) so
the institutional reporting tests exercise genuine persisted evidence, never hand-made dicts.
"""
from __future__ import annotations

import datetime

KINDS = {
    "solar": ("Solar", "generic_solar_reference", "create_generic_solar_reference"),
    "wind": ("Wind", "generic_wind_reference", "create_generic_wind_reference"),
    "ev": ("EV Charging", "generic_ev_charging_reference", "create_generic_ev_charging_reference"),
    "data_center": ("Data Center", "generic_data_center_reference", "create_generic_data_center_reference"),
}


def init_db(tmp_path, monkeypatch, name="rc7.db"):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / name))
    db.init_db()


def create_project(kind: str, uid: str | None = None, suffix: str = ""):
    """Create a user project + base scenario; returns (project_record, uid, snap, pi, base_sc)."""
    from app import project_factories
    from app.auth import new_demo_user_id
    from app.persistence.projects_repository import create_project_record
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario
    from app.persistence.workspace_repository import save_workspace_state

    ptype, template, factory = KINDS[kind]
    uid = uid or new_demo_user_id()
    code = f"rc7{kind[:3]}{suffix}_" + uid[-6:]
    pi = getattr(project_factories, factory)()
    snap = {
        "project_type": ptype, "template_source": template, "project_origin": "user_created",
        "project_name": pi.info.name, "country_market": pi.info.country_iso,
        "capacity_mw": str(pi.technical.capacity_mw), "cod_date": str(pi.info.cod_date),
        "construction_months": str(pi.info.construction_months), "horizon_years": str(pi.info.horizon_years),
        "tariff_eur_mwh": str(pi.revenue.ppa_base_tariff), "ppa_term_years": str(pi.revenue.ppa_term_years),
        "p50_hours": str(pi.technical.operating_hours_p50),
        "opex_y1_keur": str(sum(i.y1_amount_keur for i in pi.opex)),
        "total_capex_keur": str(pi.capex.total_capex),
        "interest_rate_pct": str(pi.financing.all_in_rate * 100),
        "tenor_years": str(pi.financing.senior_tenor_years), "target_dscr": str(pi.financing.target_dscr),
    }
    pr = create_project_record(user_id=uid, project_code=code, project_name=f"RC7 {kind}{suffix}",
                               project_type=ptype, project_origin="user_created",
                               template_source=template, baseline_snapshot=snap)
    save_workspace_state(user_id=uid, project_id=pr.project_id, project_code=code,
                         draft_snapshot=snap, saved_snapshot=snap)
    base_sc = get_or_create_base_case_scenario(
        user_id=uid, project_id=pr.project_id, project_code=code, project_name=pr.project_name,
        project_type=ptype, source_project_template=template, base_input_set=snap, governance_state={})
    # production runs happen with the scenario already active on the workspace; commit under that
    # identity so the Run's composite hash equals the Working Copy's until the Working Copy is edited
    save_workspace_state(user_id=uid, project_id=pr.project_id, project_code=code, draft_snapshot=snap,
                         saved_snapshot=snap, active_scenario_id=base_sc.scenario_id,
                         active_scenario_name=base_sc.scenario_name)
    return pr, uid, snap, pi, base_sc


def commit_run(pr, uid, pi, base_sc, kind: str, *, ran_at=None, snapshot_id=None):
    """Run the real engine and commit like the production path; returns (result, snapshot_id)."""
    from app.api.project_runner import run_project
    from app.persistence.workspace_repository import v2_atomic_run_commit
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    _, template, _ = KINDS[kind]
    content_hash = assemble_consistent_for_get(
        user_id=uid, project_id=pr.project_id, workbook_version=WORKBOOK.version).composite_hash
    result = run_project(template, "Base", project_inputs_override=pi)
    ran_at = ran_at or datetime.datetime.now(datetime.timezone.utc)
    snapshot_id = snapshot_id or ran_at.strftime("%Y%m%dT%H%M%S%fZ")
    kpis = dict(result["kpis"])
    if "financing_evidence" in result:
        kpis["financing_evidence"] = {**result["financing_evidence"], "run_binding": {
            "snapshot_id": snapshot_id, "composite_hash": content_hash, "scenario_id": base_sc.scenario_id}}
    v2_atomic_run_commit(
        user_id=uid, project_id=pr.project_id, project_code=pr.project_code,
        expected_composite_hash=content_hash, runtime_snapshot_id=snapshot_id, runtime_origin="v2_run",
        runtime_summary=kpis, financial_statements=result.get("financial_statements"),
        debt_schedule=result.get("debt_schedule"), tax_schedule=result.get("tax_schedule"),
        distribution_schedule=result.get("distribution_schedule"), sponsor_schedule=result.get("sponsor_schedule"),
        integrity_evidence=result.get("integrity_evidence"),
        active_scenario_id=base_sc.scenario_id, active_scenario_name=base_sc.scenario_name,
        last_runtime_scenario_id=base_sc.scenario_id, ran_at=ran_at)
    return result, snapshot_id

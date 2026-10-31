#!/usr/bin/env python3
"""Minimal reproduction + boundary sweep for the reference-seeded SHL maturity fail-closed refusal. Uses ONLY app operations on a disposable DB.
1) Fresh reference-seeded project (no fixture inputs), ONE Save-All cell change (horizon_years), materialise like the Run route, run.
2) Sweep horizon x construction. 3) DIAGNOSTIC (not a fix): re-derive SHL indices with resolve_generic_shl_policy on the same materialised inputs, run.
python -I wnd_minimal_repro.py --repo R --out JSON [--tech wind|solar]"""
import argparse, json, os, sys, tempfile, uuid, math, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--out", required=True); ap.add_argument("--tech", default="wind"); a = ap.parse_args()
os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07min_"), "d.db"); C.repo_setup(a.repo)
from dataclasses import replace
from app.services.reference_seed_service import create_reference_seeded_project
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.registry import WORKBOOK
from app.workbook.service import WorkbookService
from app.workbook.workbook_identity import assemble_consistent_for_get
from app.v2.save_all_commands import save_all, SaveAllInput
from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
from app.api.project_runner import run_project
from app.generic_shl_policy import resolve_generic_shl_policy
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
tsrc, key = ("generic_wind_reference", "Wind") if a.tech == "wind" else ("generic_solar_reference", "Solar")
uid = "on07min"; wv = WORKBOOK.version

def fresh(cap_mw):
    rec = create_reference_seeded_project(user_id=uid, template_source=tsrc, requested_name=f"min-{uuid.uuid4().hex[:6]}", capacity_mw=cap_mw, country_market="XA")
    pr, _ = resolve_accessible_project(uid, rec.project_code); return rec, pr

def edit(rec, pr, cells):
    for fid, val in cells:
        h = assemble_consistent_for_get(uid, rec.project_id, wv).composite_hash
        save_all(project_record=pr, user_id=uid, data=SaveAllInput(request_id="m-" + uuid.uuid4().hex[:12], workbook_version=wv, content_hash=h, scenario_id=None, cells=((fid, val),)))

def materialise(rec):
    ws = get_workspace_state(uid, rec.project_id)
    o = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    o = replace(o, capex=apply_user_sub_lines_replacing_base(o.capex, project_id=rec.project_id, scenario_overrides=None))
    return replace(o, opex=apply_user_sub_lines_to_opex(o.opex, project_id=rec.project_id, scenario_overrides=None))

def grid_last(o):
    return [p.index for p in _build_period_engine(from_project_inputs(o)).periods()][-1]

def attempt(o):
    try:
        r = run_project(key, "Base", "Semiannual", project_inputs_override=o)
        return ("RUN_OK" if r.get("kpis") else "NO_KPIS"), None
    except Exception as e:
        s = str(e); code = next((c for c in ("SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED", "SHL_MATURITY_RESIDUAL_FAILS_CLOSED", "GENERIC_SHL_POLICY_UNSERVICEABLE", "PERIOD_AXIS_COD_MISMATCH") if c in s), type(e).__name__)
        return "REFUSED", code + ("" if code != type(e).__name__ else ": " + s[:120])

out = {"tech": a.tech, "rows": []}
rec0, pr0 = fresh(40.0); o0 = materialise(rec0)
out["reference_defaults"] = {"construction_months": o0.info.construction_months, "horizon_years": o0.info.horizon_years, "senior_tenor_years": o0.financing.senior_tenor_years,
    "shl_maturity": o0.financing.shl_maturity_period_index, "shl_elig_start": o0.financing.shl_principal_eligibility_start_period, "grid_last": grid_last(o0), "cod": str(o0.info.cod_date)}
print("reference defaults:", out["reference_defaults"])
d_h = o0.info.horizon_years; d_c = o0.info.construction_months
horizons = [h for h in range(d_h - 4, d_h + 4)]
for h in horizons:
    rec, pr = fresh(40.0)
    if h != d_h: edit(rec, pr, [("project_setup.technical.horizon_years", str(h))])
    o = materialise(rec); st, err = attempt(o)
    o2 = resolve_generic_shl_policy(o); st2, err2 = attempt(o2) if True else (None, None)
    row = {"edit": f"horizon_years={h} (only)", "horizon": h, "construction_months": o.info.construction_months, "grid_last": grid_last(o), "stored_shl_maturity": o.financing.shl_maturity_period_index,
           "policy_formula_maturity": math.ceil(o.info.construction_months / 6) + 2 * h - 1, "maturity_on_grid": o.financing.shl_maturity_period_index <= grid_last(o),
           "as_materialised": st, "refusal": err, "DIAG_policy_rederived_maturity": o2.financing.shl_maturity_period_index, "DIAG_rederived_result": st2, "DIAG_rederived_refusal": err2}
    out["rows"].append(row); print({k: row[k] for k in ("edit", "grid_last", "stored_shl_maturity", "as_materialised", "refusal", "DIAG_rederived_result", "DIAG_rederived_refusal")})
json.dump(out, open(a.out, "w"), indent=1, default=str)

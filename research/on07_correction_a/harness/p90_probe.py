#!/usr/bin/env python3
"""Is P90/P99 independently settable on the user-created route? Fresh reference-seeded Solar; (a) P50 changed via Save All; (b) a P90 snapshot key written
directly is NOT a guarded path (reported only to show the engine honours it, not as a user route). python -I p90_probe.py --repo R --out JSON"""
import argparse, json, os, sys, tempfile, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import on07_common as C
ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07p90_"), "d.db"); C.repo_setup(a.repo)
from app.services.reference_seed_service import create_reference_seeded_project
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.registry import WORKBOOK
from app.workbook.service import WorkbookService
from app.workbook.workbook_identity import assemble_consistent_for_get
from app.v2.save_all_commands import save_all, SaveAllInput
uid, wv = "p90", WORKBOOK.version
rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="p90", capacity_mw=60.0, country_market="XA")
pr, _ = resolve_accessible_project(uid, rec.project_code)
def tech():
    ws = get_workspace_state(uid, rec.project_id); o = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws)); t = o.technical
    return {"p50": t.operating_hours_p50, "p90_10y": t.operating_hours_p90_10y, "p99_1y": t.operating_hours_p99_1y, "snapshot_p90": ws.draft_snapshot.get("operating_hours_p90_10y"), "snapshot_p99": ws.draft_snapshot.get("operating_hours_p99_1y")}
out = {"seeded": tech()}
for v in ("1600", "1500"):
    save_all(project_record=pr, user_id=uid, data=SaveAllInput(request_id="p-" + uuid.uuid4().hex[:10], workbook_version=wv, content_hash=assemble_consistent_for_get(uid, rec.project_id, wv).composite_hash,
             scenario_id=None, cells=(("project_setup.technical.p50_hours", v),))); out[f"after_p50_{v}"] = tech()
out["registry_fields_matching_p90_p99"] = [f.field_id for f in WORKBOOK.all_fields() if "p90" in f.field_id.lower() or "p99" in f.field_id.lower()]
print(json.dumps(out, indent=1)); json.dump(out, open(a.out, "w"), indent=1)

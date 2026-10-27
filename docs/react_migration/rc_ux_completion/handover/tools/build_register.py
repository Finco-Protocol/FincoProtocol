import csv, io, sys
import subprocess; ROOT=subprocess.check_output(["git","rev-parse","--show-toplevel"],text=True).strip()+"/docs/react_migration/rc_ux_completion/"
cols=["original_audit_source","original_gap_id","original_severity","affected_screen_workflow","legacy_behavior","current_react_behavior","required_functionality","implementation_owner_module","canonical_api_engine_authority","verification_test","status","evidence_location","reason_for_deferral"]
A="Audit A (FINCO_Legacy_React_Audit_2026-10-27) 04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv"
B="Audit B (FINCO_REACT_MVP_AUDIT) REACT_MVP_P0_P1_P2_FINDINGS.md"
src=list(csv.DictReader(open(ROOT+"audit_inputs/AUDIT_A_04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv",encoding="utf-8")))
by={r["GAP ID"]:r for r in src}
# three rows of the supplied CSV are column-shifted (unquoted commas); recovered from the audit's own prose (05/12/10)
fix={
 "GAP-R11":dict(Severity="P2",Feature="Institutional export + signed run certificate + reference regression trigger",Legacy="Trust Pack: XLSX export after first run; Ed25519 signed attestation; regression evidence on demand",React="Trust section shows DEFERRED for regression + certificate; export not located in workbook UI",Req="Surface /workbook/export, /workbook/trust/certificate and /workbook/trust/validation in React Trust"),
 "GAP-R12":dict(Severity="P2",Feature="Credit decision / lender covenant / IC pack surfaces",Legacy="Legacy /scenarios surfaces: lender-case, covenant, credit-summary, ic-pack, credit-pack (+ /v2/credit-decision v4/v5)",React="Absent",Req="Either JSON projections or an explicit documented Legacy-only gate"),
 "GAP-R27":dict(Severity="P2 (Legacy, needs repro)",Feature="Scenario 'Edit' cross-project navigation",Legacy="One observation: Edit led to a different project's revenue sheet (workflow-5)",React="n/a",Req="Reproduce; fix router if real. Acceptance: Edit always opens the same project's sheets"),
}
status={}
def S(i,st,mod="",auth="",test="TBD",ev="",why="",req=None):
    status[i]=dict(st=st,mod=mod,auth=auth,test=test,ev=ev,why=why,req=req)
RCM="docs/react_migration/rc_m_integrated/02_PARITY_GAP_REGISTER.csv"
S("GAP-R1","CLOSED","app/v2/react_new_project.py; frontend/src/app/newProject/","canonical project creation (atomic request-keyed)","tests/test_model_react_rcm_new_project_v1.py; tests/model_react_rcm_new_project_acceptance.py",RCM+" (#388)")
S("GAP-R2","CLOSED","app/v2/react_analysis.py; frontend/src/app/analysis/SensitivityPanel.tsx","run_matrix_points (canonical sensitivity)","tests/test_model_react_rcm_sensitivity_v1.py; tests/model_react_rcm_analysis_acceptance.py",RCM+" (#388); 5x5 not compared cell-by-cell against Legacy")
S("GAP-R3","CLOSED","app/v2/react_goal_seek.py; frontend/src/app/analysis/GoalSeekPanel.tsx","canonical goal-seek solver + CAS apply","tests/test_model_react_rcm_goal_seek_v1.py",RCM+" (#388); Solar/Wind only (Legacy V1 scope)")
S("GAP-R4","OPEN","app/v2/whatif.py (adapter pending)","whatif.preview/commit; canonical Run","TBD","")
S("GAP-R5","PARTIAL","app/v2/react_financing.py; frontend/src/app/financing/","bankability/financing JSON + canonical writers","tests/test_model_react_rcm_financing_v1.py",RCM+" (#388)","Two-Senior editing is release-closed (authority decision pending); period-schedule FLAT/CALIBRATED depth to be re-verified; SHL/valuation binding waits for FIN-V2 #391")
S("GAP-R6","PARTIAL","app/v2/react_investors.py; frontend/src/app/financing/InvestorsPanel.tsx","investor_f4_router agreement","tests/test_model_react_rcm_investors_v1.py",RCM+" (#388)","SHL controls read-only until FIN-V2 #391 releases an editable SHL authority")
S("GAP-R9","CLOSED","app/v2/react_capex.py; frontend/src/app/capex/CapexStudio.tsx","app.capex_profiles (build_plan, save_profiles) via the existing /v2/capex/spending-profiles/save","tests/test_model_react_rcux_capex_v1.py (16 incl. Legacy-twin Run equality); tests/model_react_rcux_capex_acceptance.py (10 Chromium nodes)","docs/react_migration/rc_ux_completion/05_LANE_A_CAPEX.md")
for i in ("GAP-R7","GAP-R8","GAP-R10","GAP-R11","GAP-R12","GAP-R14","GAP-R14a","GAP-R15","GAP-R16","GAP-R17","GAP-R20","GAP-R21","GAP-R22","GAP-R23"):
    S(i,"OPEN")
S("GAP-R13","CLOSED","app/v2/react_compare.py; frontend/src/app/runs/","insights history + build_compare_rows over immutable Run evidence","tests/test_model_react_rcux_compare_v1.py (18); tests/model_react_rcux_runs_acceptance.py (8 Chromium nodes via the consolidation role)","docs/react_migration/rc_ux_completion/04_LANE_B_RUNS_COMPARE.md")
S("GAP-R18","CLOSED","FIN-VAL F01 (#389, merged before the RC-UX base)","typed rate contract human_percent_v1","tests/test_model_react_rcm_f01_rate_matrix_v1.py (#388 evidence)",RCM+" / 08_OPEN_OWNER_AUTHORIZATIONS item 7","")
for i in ("GAP-R19","GAP-R24","GAP-R25","GAP-R26"):
    S(i,"INTENTIONALLY DEFERRED","Legacy Jinja/HTMX templates (not in RC-UX scope)","n/a (Legacy front end)","n/a","","Legacy-UI defect: RC-UX adds no Legacy router/template change (prompt section 4A). The shared canonical writer is exercised separately (see RC_UX evidence for GAP-R19)")
S("GAP-R27","OPEN","Legacy router (suspect, needs repro)","","TBD","","Single observation in a Legacy audit session; not reproduced")
S("GAP-R28","OPEN","frontend hash router (suspect, needs repro)","","TBD (20 mixed-interaction acceptance planned)","","")
rows=[]
for gid,r in by.items():
    r=dict(r)
    if gid in fix:
        f=fix[gid]; r.update({"Severity":f["Severity"],"Feature":f["Feature"],"Legacy behavior (evidence)":f["Legacy"],"React observed behavior":f["React"],"Remediation direction":f["Req"],"Module":r.get("Module","")})
    s=status[gid]
    rows.append({
     "original_audit_source":A,"original_gap_id":gid,"original_severity":r["Severity"],
     "affected_screen_workflow":f'{r["Module"]} / {r["Feature"]}',"legacy_behavior":r["Legacy behavior (evidence)"],
     "current_react_behavior":r["React observed behavior"]+" [audit time, repo head 6f10f392]","required_functionality":r["Remediation direction"],
     "implementation_owner_module":s["mod"],"canonical_api_engine_authority":s["auth"] or r["Technical assessment"] if gid not in fix else s["auth"],
     "verification_test":s["test"] if s["test"]!="TBD" else "Audit acceptance: "+(r["Acceptance test"] if gid not in fix else fix[gid]["Req"]),
     "status":s["st"],"evidence_location":s["ev"],"reason_for_deferral":s["why"]})
auditB=[
("F01","P0","Financing percentage projection and Save disagree with typed debt authority","CLOSED","FIN-VAL F01 (#389)","tests/test_model_react_rcm_f01_rate_matrix_v1.py (4 verticals x 4 F01 rates)",RCM,""),
("F02","P1","Statements identify Data Center, Wind and EV projects as a placeholder Solar project","OPEN","frontend/src/finco/_workbook/StatementWorkbook.tsx; WorkspaceView.tsx","Chromium check on four verticals required","","Source still contains the demo fallback in FincoShell.tsx; WorkspaceView passes projectIdentity - verification on all four verticals pending"),
("G01","P1","D-029 release-closed despite executable client paths (governance gap)","BLOCKED","docs/model_v2/d029 (owner decision register)","n/a","","Owner release disposition is a Financial/Security Owner decision, not an RC-UX code task"),
("F03","P2","Short Run identifiers collide within the same hour","CLOSED","frontend/src/app/runIdentity.tsx","existing identity presentation (RC-REACT-MVP); reused by the RC-UX Run history","",""),
("F04","P2","Assumption grid copy says CAPEX/OPEX writer is out of scope","CLOSED","copy removed (no 'out of this PR' text in app/v2/react_workspace_router.py or frontend/src/app)","grep proof at base f79e251","",""),
("F05","P2","Capacity labels duplicate their unit","OPEN","registry labels / Field component","Chromium check on Data Center and EV required","","verification pending"),
("F06","P2","Results prints a literal Unicode escape in DSCR guidance","CLOSED","frontend/src/app/FinancialResults.tsx","grep proof: no literal \\u2192 in frontend/src/app at base f79e251","",""),
("U01","P2","Inputs are excessively long and repeat field/table scaffolding","OPEN","frontend/src/app/CanonicalInputGrid.tsx","","",""),
("U02","P2","Engineering/governance details dominate routine forms","OPEN","frontend/src/app/workflow/SheetFieldsEditor.tsx","","",""),
("U03","P2","Mobile top navigation hides later destinations without a strong cue","CLOSED","frontend/src/app/WorkspaceNav.tsx (overflow cue, scroll buttons, position text)","existing acceptance (RC-REACT-MVP)","","Re-verified in RC-UX viewport tests"),
]
for fid,sev,title,st,mod,test,ev,why in auditB:
    rows.append({"original_audit_source":B,"original_gap_id":fid,"original_severity":sev,"affected_screen_workflow":title,"legacy_behavior":"n/a (React MVP acceptance audit)","current_react_behavior":"See audit_inputs/AUDIT_B_REACT_MVP_P0_P1_P2_FINDINGS.md","required_functionality":title,"implementation_owner_module":mod,"canonical_api_engine_authority":"","verification_test":test,"status":st,"evidence_location":ev,"reason_for_deferral":why})
scope=[("RCUX-A1","Revenue Studio V2","GAP-R7/R8/R20/R23"),("RCUX-A2","CAPEX Studio V2","GAP-R9"),("RCUX-A3","Excel/CSV Import Workspace","GAP-R10"),("RCUX-B1","Analysis Workspace V3 (what-if / commit / run / compare)","GAP-R4/R22"),("RCUX-C1","Financing & Sponsor UI / Reserve layout","GAP-R5/R6; FIN-V2"),("RCUX-C2","Institutional Reporting UI","GAP-R11/R12"),("RCUX-C3","Library & Navigation","GAP-R14/R14a"),("RCUX-C4","Diagnostics & UX polish","GAP-R15/R16/R17/R21; U01/U02/F02/F05")]
for gid,t,m in scope:
    rows.append({"original_audit_source":"RC-UX prompt scope (implementation priority; maps to "+m+")","original_gap_id":gid,"original_severity":"n/a (implementation scope row)","affected_screen_workflow":t,"legacy_behavior":"see mapped audit rows","current_react_behavior":"see mapped audit rows","required_functionality":t,"implementation_owner_module":"","canonical_api_engine_authority":"","verification_test":"TBD","status":"OPEN","evidence_location":"","reason_for_deferral":""})
w=csv.DictWriter(open(ROOT+"RC_UX_MASTER_GAP_REGISTER.csv","w",newline="",encoding="utf-8"),fieldnames=cols,quoting=csv.QUOTE_ALL); w.writeheader(); w.writerows(rows)
from collections import Counter
print(len(rows), Counter(r["status"] for r in rows))

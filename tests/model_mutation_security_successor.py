"""Exact SEC-01/02 successor candidate; no merge/deploy/financial release authority.

Historical RC-SEC pins/ancestry remain in rc_sec_csrf_successor. This candidate
recognizes only the separately reviewed implementation, its callers and tests.
"""
from __future__ import annotations
import ast,hashlib,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE_HEAD='1800bf6092af650f18aa6ae70e9df221797090fd'
BLOBS={
    "app/library/router.py": "2b9a0bdc2ccfbde2f1b6e9401ee6ad935382e6b5",
    "app/templates/v2/partials/_financing_bankability.html": "468d085022705c5042563895fa133952f323e193",
    "app/templates/v2/partials/_v2_export_controls.html": "f4fd7c4e0eafc9771f0837c328d4a15759ec286c",
    "app/templates/v2/partials/field_editor.html": "80c300d670381b54857a8294862be53478333224",
    "app/templates/v2/partials/sheet_capex.html": "608b0a4a1cafe69acf5e5989cda732504a75aafe",
    "app/templates/v2/partials/sheet_inputs.html": "23c5200c15a17158f4c60608cd448d11237a0650",
    "app/templates/v2/partials/sheet_opex.html": "8a84abaa862abbd9400cec2ce1813297fab69f0b",
    "app/templates/v2/partials/sheet_project_setup.html": "525ed229f23d31b0821f125fb939d7112dcaf09b",
    "app/templates/v2/partials/sheet_revenue.html": "6bd3d56e3f9b47638469b3f37394bda1cc48dd81",
    "app/templates/v2/partials/sheet_scenarios.html": "80810af133f31356579b252aabfe89a3875847d1",
    "app/templates/v2/partials/sheet_senior_debt.html": "cc48931f18d6e24323fd17fcca6d1b5c90ba2a87",
    "app/templates/v2/partials/sheet_tax.html": "43d7d1e77eaf86a1ee271fbe955089478df43ac3",
    "app/templates/v2/partials/sheet_trust.html": "3991e466b7a6ebf44a61dbbc8510e466a975fec9",
    "app/v2/capex_router.py": "64dcb10740303e516ed7855e671d316d298db693",
    "app/v2/grid_router.py": "8511db3a5d8ab8129d930c8a77bccea788d2b4a9",
    "app/v2/opex_router.py": "d2d1251a48aaba73dfe00f02a07171fb7b9d5e0a",
    "app/v2/post_run_ui.py": "5c30ffa0761f0664161ea7385b53cab12f4da5a5",
    "app/v2/react_poc_router.py": "895e201189882a847b18c24a4f074ec4282e2fd3",
    "app/v2/react_workspace_router.py": "84a41c2e95975a4ab77e31da8b4428651bbfd462",
    "app/v2/router.py": "cbff734453400269589d9fcc5cec702cbc239b55",
    "app/workbook/financing_csrf.py": "ab96d84d1639e83c532c66c6fa3e8276b72824e5",
    "app/workbook/mutation_csrf.py": "f68dd57649cf7fc1a9fdfc7b86ea987cd2b6326b",
    "frontend/src/app/FinancialResults.tsx": "99126471e6e8f9ea8cee8030b11ffe09673821f1",
    "frontend/src/app/WorkspaceView.tsx": "19614dd386d76b3bf4edbe929c8e045bfe41bd2c",
    "frontend/src/app/types.ts": "57af23a933828889583765243e347b9739875b48",
    "frontend/src/app/workflow/ModelExportView.tsx": "0f86be3903b0086bbcd297de7edc9e9efd40f528",
    "frontend/src/app/workflow/ScenarioKpiComparison.tsx": "21ea6d79a3f53bba9afe7e2a5afed2aa43b5f32c",
    "frontend/src/app/workflow/ScenarioWorkspace.tsx": "324922d117639cce8c7ec94cd7129ec67b15f5fb",
    "frontend/src/app/workflow/workflowApi.ts": "646c574c9342450bb233f0314354ab612d4a1e49",
    "frontend/src/app/workflow/workflowShared.tsx": "52f1aa62c4a19091cc5d868aa3bd5c55f7206c54",
    "frontend/src/styles/rc-react-mvp.css": "5a94b395fc1fc328965664851f07f84282a8eeca",
    "static/js/cost_staging.js": "23a561c522aec5749962f08b7908732ee8b99767",
    "static/react/finco-react.css": "b260d8d0fda3b271efbd29d48ed8ee442e7a6d2a",
    "static/react/finco-react.js": "c5a8a5ed17326a4ec275ba9e4f573bd47f630486",
    "tests/insights_browser_fixture.py": "8a9d2da2be29df2e2642e26b10318fb090904f54",
    "tests/model_mutation_cookie_policy_acceptance.py": "6fb1ac0bc03b499cd75bacdde92e1d110fd1cf70",
    "tests/model_mutation_csrf.py": "f69b7f086aaf91ad0cf39416ff24558a83f0abf8",
    "tests/model_react_mvp_acceptance.py": "525dce2ca34c5fa8744f5d7e4e63100b1611af48",
    "tests/model_react_wf2_browser_acceptance.py": "a0c509edcd788a8c7441133d0e4b3bc885085c43",
    "tests/run_clone_csrf.py": "07731bc839b3ea8f78dfd361432ac2200b0c14b5",
    "tests/test_capex_numbering_contingency.py": "28d005d8f43a0225221bd3fa1f9934cc50ba3bb8",
    "tests/test_correction_a_required_gates.py": "7d6c923ec0d870429c0a7a4d857dedf79ff1cd8b",
    "tests/test_cost_batch_save_v1.py": "ce04c6bd16837a36d01c7f474fb9b51a185236c2",
    "tests/test_cost_workspace_consistency_v1.py": "2cbd42850dbc9d5e4d6c3c1a4e9a342976d2c30c",
    "tests/test_cost_workspace_parity_v1.py": "d64647fb7859a828b764b4266045662d4d8611aa",
    "tests/test_data_center_correction_a.py": "630a38db65377aceeb8f76bca7a6e777cb6935ba",
    "tests/test_developer_economics_persistence_v1.py": "3c8abff39182b3ace5029215fef1a5e92b42be95",
    "tests/test_ev_charging_acceptance.py": "41dce1c4c8a63360f230f013a5c12ece50ae765a",
    "tests/test_ev_charging_efficiency_authority.py": "ed7e1cc038e48ada886ace1c6be0f6baf3854c55",
    "tests/test_ev_charging_range_parity.py": "3675298fd66edd94ff936cc59c0e78e50e482528",
    "tests/test_f0_senior_maturity_integrity.py": "6addb07c5feee572709bb5fbbc7ae09f83ab6af8",
    "tests/test_financing_f35b_csrf.py": "73894bd976f973c3be2ab32ad284073c87ad5de7",
    "tests/test_financing_f38_trace.py": "f2a24c84a2e8bef282ed4ee26bc47c317bf47ed7",
    "tests/test_financing_f3_junior_workspace.py": "7f020467c0c3c4d07530c2387f90b626af3b45ea",
    "tests/test_gf_f05_scenario_freshness.py": "d9583ac12800d1e57d77ec9f60b7dd594e2925ea",
    "tests/test_golden_flow_correction_b.py": "bb8e78cfd54e41760e3cdbb84e7829ebf59d35fe",
    "tests/test_investor_f4_workspace.py": "f6d7a1c965e364f6bb3f1dd4ec8d48011ae03b67",
    "tests/test_model_credit_decision_v3_real_runs.py": "61ec7bead5f71b29e38677ef9a6b1f8c562387a7",
    "tests/test_model_credit_decision_v3_scenarios.py": "3e307eb0072a89f1ef6b5a02272ff665f584288b",
    "tests/test_model_decision_workspace_v2.py": "a546fe089fc30b3b19e36cb42eff19848d89b326",
    "tests/test_model_diagnostics_v2_real_runs.py": "d75bfe5021b51014b69b4b31f1f272c782c2ae57",
    "tests/test_model_financing_bankability.py": "c3d4267e5ad007c12103c2daae05ffea10f5260d",
    "tests/test_model_financing_f2.py": "de22a07e418e406149417a7b2b1da9944bacd161",
    "tests/test_model_financing_f3_workspace.py": "7b58625a077283ad303f192e0dadfba0fe1b3828",
    "tests/test_model_hybrid_inputs_grid_f3_negative.py": "f728fa6a2f5e3a7c34adcb3745e8229867f5d5d2",
    "tests/test_model_hybrid_inputs_grid_routes.py": "1e91ee671a60e9ac5a52d673df4f85939620eeb8",
    "tests/test_model_import_excel_migration_journey.py": "8ba42bd9030ba86187bb7def2e1ccba801e29657",
    "tests/test_model_import_excel_migration_security.py": "a1454d2c0917199b76b15fc53ee24c0f59c21e48",
    "tests/test_model_insight_q3_route.py": "f32e938853c696f405e5d18c7a4ff1d5aaf97864",
    "tests/test_model_insight_q3_scenario_identity.py": "d8e58499b2a03b29e06852e6a121aadf384778da",
    "tests/test_model_mutation_request_security_v1.py": "26bd7df75b880a39cda2076a4ca4e3b4b82f75b9",
    "tests/test_model_outputs_workspace.py": "8c226e60e8059856faa60f39f86eef066c0da3da",
    "tests/test_model_q4_whatif.py": "c5170fbfbd8329da8569973f168f004e3a3886c7",
    "tests/test_model_react_correction_b_v1.py": "16d93f7f091a81212b5093b5cf70fff0aad13975",
    "tests/test_model_react_insights_v1.py": "29b07e518eef65a9ade11f141d433594cc6ee82a",
    "tests/test_model_react_outcome_integrity_v1.py": "f43179b925560ab402f802ccbc78a40ae4e02580",
    "tests/test_model_react_poc_v1.py": "329285220b53af5406b5926dd402a23ff298442c",
    "tests/test_model_react_rc_ux_b_v1.py": "4867262985bab3ec3a3c5c3f0d5bb817d6efe670",
    "tests/test_model_react_ux02_workspace_v1.py": "540642547e796ad9a6481ec8e5e462a5a05f9c76",
    "tests/test_model_react_ux07_v1.py": "b26dac0532b33a143240792c09c7907ad8edb890",
    "tests/test_model_react_wf2_financial_authority_v1.py": "e876662938ec3ed6563440e5a2620a0aa5a8f8a8",
    "tests/test_model_react_wf2_projections_v1.py": "31798a7fd10828f8ad2b0f50c91138ad2fb21f3e",
    "tests/test_model_v7_diagnostics_routes.py": "19427b26c3543755b935490e3794d4adeb6d1aca",
    "tests/test_model_workspace_consolidation_browser.py": "76692a9edc8da4418e29c2d8dc52d3847f4eac34",
    "tests/test_portfolio_monitoring_real_runs.py": "2f095d831317d4661a9c2e6255a5f9e2c8e67ad1",
    "tests/test_post_run_request_context.py": "6d07139d12fd4f90bd10630392e00da3eb155919",
    "tests/test_ppa01_contractual_workspace.py": "bb939001d2c8ee56fd1679e1410d836548294866",
    "tests/test_ppa01_rounding_workspace.py": "6ad95572a52740b6b1141838a8caf2f834d682c6",
    "tests/test_ppa01_save_scenario_run_chain.py": "457a2a4197e8e44c2db765aa8a657838d1bdb34f",
    "tests/test_pr161_contingency_identity.py": "6c9a0270adbffe428fe882583af7b96b98574e8c",
    "tests/test_rc2_integration_acceptance.py": "815c5ca959ca026950d23d3442ac56aaf32c3e16",
    "tests/test_rc5_s7_effective_input_evidence.py": "057e2ecc991f8d3cbbcbf6c1e5d06699eca45696",
    "tests/test_rc5_scenario_effective_input_safety.py": "1bc97d4b70a6d029e0e828dc066903272764d402",
    "tests/test_rc7b_quarterly_production_acceptance.py": "d2bdc540f095d4b5cc3d5f8749a447896ffc2985",
    "tests/test_rc7b_quarterly_run_workspace.py": "cda5a689377c7042f6f1fff028a8e05ab27b783a",
    "tests/test_react_mvp_rc_sec.py": "578d7228f24a9991ff18493323548386d41d1727",
    "tests/test_revenue_v2_advanced_route.py": "8fdc4998a65244483e59b2bf1c35e17c67c6ec91",
    "tests/test_revenue_v3_workspace.py": "8891862b42e5c843f5e2b44184c42c5f3f67dbf9",
    "tests/test_sc34_project_identity.py": "f648f4a9a7b58836d0ff735c881068dc18ac03c5",
    "tests/test_sc34_run_failure_explanation.py": "2cbc185c3d0f07704da596989ec960448ba301f9",
    "tests/test_sc34_run_status_dimensions.py": "28d3a43998855d9ded1b57272d3b7d3d326156b5",
    "tests/test_sc34_statements_drilldown.py": "ece953731db7592ba6c168358bf9002201133a9e",
    "tests/test_scenario_tariff_authority_v2.py": "410b0a9389cd9f3730567b5ef1e4938212200e7d",
    "tests/test_staging_acceptance_a.py": "e5eb455c32c083d258621c07ae5ef080ae6890c6",
    "tests/test_u2_1_v2_export.py": "6d8f0595c927d7c3b057d7d56492bf3d5139d3a1",
    "tests/test_u2_2_returns_surface.py": "54661f059c38018c3c224c17a16ee95d5b1b0da9",
    "tests/test_v2_scenario_overrides.py": "c2d47c29bf3cde7ca4a2713220dace34f4f1ac3f",
    "tests/test_v9p2a_odr_run_commit_safety.py": "958d6fd4b5c6e85063e6c15ace18829835785f13",
    "tests/test_wf05_wf07_integration.py": "f9231eea484ae05d2a0e3e3a8ab6b1ee329865e0",
    "tests/test_wf07_revenue_workspace.py": "0d2a4895dc85d4e5a5f359b302b2ace53d379814",
    "tests/test_workflow_c_statements_analytics_trace.py": "ddf247a2216e830f55b5545059cbb30c9713f8ea",
    "tests/wfa_support.py": "d2f07df1b8ba6cf7dc96c9bed408f4e8989adf0b"
}
CONSUMERS={'app/v2/react_poc_router.py', 'app/v2/opex_router.py', 'app/v2/grid_router.py', 'app/v2/router.py', 'app/v2/capex_router.py', 'app/v2/post_run_ui.py', 'app/v2/react_workspace_router.py'}
TOKEN_MODULE="app/workbook/mutation_csrf.py"
# Correction C admits exact reviewed browser-only changes. The original SOURCE_HEAD
# and all 112 BLOBS above remain immutable and independently verified.
BROWSER_CORRECTION_PATH="tests/model_mutation_cookie_policy_acceptance.py"
BROWSER_CORRECTION_SOURCE_HEAD="afd8597f99964bb212866764c2e6f961e6e9f7fa"
BROWSER_CORRECTION_PARENT="d1a15b47c0999df7de4ef55df22f81f4bb0013a7"
BROWSER_CORRECTION_BLOB="878ca6771db323681c3cd49ec77cf7e149244e94"
PPA_CORRECTION_PATH="tests/model_react_wf2_browser_acceptance.py"
PPA_CORRECTION_SOURCE_HEAD="cd3910debeaaa64c763600dd821608c8867b3009"
PPA_CORRECTION_PARENT="afd8597f99964bb212866764c2e6f961e6e9f7fa"
PPA_CORRECTION_BLOB="34a1be8ae3e3fbd165115ff13a2888b2fb602c39"
# FIN-VAL B2/C1 admits exact reviewed successors of six pinned files (additive; every original pin above stays
# immutable and each historical parent blob is still verified at SOURCE_HEAD). Any further drift needs a new review.
FINVAL_B2C1_SUCCESSORS={
    "app/templates/v2/partials/sheet_opex.html":"3220115c7565420b03694def6a8d8ad3a0ec042e",
    "app/v2/react_workspace_router.py":"aee8e13815cc02f3e7ae43c57925aa6679515719",
    "app/v2/router.py":"f92bdd593406ab1c04d343af75fba86d80055414",
    "frontend/src/app/WorkspaceView.tsx":"5e14876224a9444151aa57b243291dbb98b2891e",
    "frontend/src/app/types.ts":"d5077405dd2c316fe3ee006250287d11835382f4",
    "static/react/finco-react.js":"4b74bb50f43c665136e8fcac11e0a9beead08f8b",
}
# D-029 (PR #384) admits exact reviewed successors of the three pinned files the Run-intent integration had to change
# (the Run route, the React bundle built from the reviewed WorkflowBar/api/runIntent sources and, by explicit Financial Owner
# authorization in Correction B, the mandatory consolidation browser file that gained the seven D-029 Chromium wrappers).  Additive: every
# original pin and the FIN-VAL B2/C1 layer above stay immutable and individually verified at SOURCE_HEAD.  Any further
# drift of either file needs a new review.  Owner authorization for exactly these paths was relayed in the PR thread.
D029_RUN_INTENT_SUCCESSORS={
    "app/v2/router.py":"37f18a0e35c0e0a9ede5d71a0f9dfc906a68c7c2",
    "static/react/finco-react.js":"907cfa53e07c78e03cd12dd537a806832dfeb7e8",    # Correction B: the seven real-Chromium D-029 wrappers the mandatory Browser Acceptance role executes (additive only).
    "tests/test_model_workspace_consolidation_browser.py":"f1a762a4f7bbfca34e8e93c74fbba3042d970665",
}
# React Institutional Model MVP correction (Overnight B) admits exact reviewed successors of the twelve pinned files the
# presentation-level correction had to change: the React workspace router projections, six React sources, the rebuilt
# React bundle (JS and CSS) and three acceptance files (the mandatory consolidation browser file gained only additive
# ``test_onb_*`` wrappers).  Additive: every original pin, the FIN-VAL B2/C1 layer and the D-029 layer above stay immutable and
# individually verified; ``app/v2/router.py`` and the CSRF token module are NOT in this layer and remain pinned to the D-029 /
# original blobs.  Owner authorization for exactly these presentation-level paths was given in the Overnight B task statement
# (Financial Owner scope, section 0) and is recorded in docs/react_migration/overnight_b/, not independently verified here.
REACT_MVP_CORRECTION_SUCCESSORS={
    "app/v2/react_workspace_router.py":"db088accc730f3364dad347d1bb523e2463e1bbe",
    "frontend/src/app/FinancialResults.tsx":"69b7123f25d511f57797bba76004c653bcdaeab4",
    "frontend/src/app/WorkspaceView.tsx":"eed73f37765f55ada26fe4bcb937c857d6e92dda",
    "frontend/src/app/types.ts":"0a4eff084f0d49e4e9eb2608c687f11c00c11060",
    "frontend/src/app/workflow/ModelExportView.tsx":"d4534de001d7d3cf89206905156c519d8b51c4b5",
    "frontend/src/app/workflow/ScenarioWorkspace.tsx":"7ec94910f41d3e727084671823c5739d480700da",
    "frontend/src/app/workflow/workflowShared.tsx":"6de23ad7c469c0ba197697dda10afe494426751a",
    "static/react/finco-react.css":"adbc32f079ee5a77cf3bf1228a8b46d76f0245dd",
    "static/react/finco-react.js":"0f85e69fd9b3a398d82d61b95243ccfd46d4b9d2",
    "tests/model_react_mvp_acceptance.py":"10885eab163fa556c42e4f27fb3814e0bd442640",
    "tests/model_react_wf2_browser_acceptance.py":"ce6d7f5e2c5fc6f4fe9a985b2b4724011889511f",
    "tests/test_model_workspace_consolidation_browser.py":"6f91b8c9376ba65c27aab34ea39651cef351b2e9",
}

# FIN-VAL F01: exact additive projection-only successor; historical layers
# above remain individually admitted. No CSRF, CAS or Run gate is changed.
FINVAL_RATE_SUCCESSORS={
    "app/v2/router.py":"8fe930c5a1ac876de0d3a98fff689f34af646a68",
}
ROUTES={
    "app/v2/router.py": {
        **{"v2_scenario_"+op: "scenario-"+op.replace("_","-") for op in ("create","select","rename","archive","update_overrides","remove_override")},
        "v2_workbook_update":"workbook-update", "v2_reference_seed_reset":"reference-seed-reset", "v2_workbook_export":"workbook-export"},
    "app/v2/capex_router.py": {**{"capex_line_"+op:"capex-"+op for op in ("add","update","deactivate","reactivate","reorder")},"capex_contingency_set":"capex-contingency"},
    "app/v2/opex_router.py": {"opex_line_"+op:"opex-"+op for op in ("add","update","deactivate","reactivate","reorder")},
    "app/v2/grid_router.py": {"grid_save":"grid-save","grid_cost_lines_save":"grid-cost-lines-save"},
}


def git_blob(source):
    raw=source.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


def _function(tree,name):
    matches=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(matches)!=1:raise ValueError("missing/duplicate handler "+name)
    return matches[0]


def _call(node,name):
    return [n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==name]


def _reject(gate,code):
    if not gate.body or not isinstance(gate.body[0],ast.Return):return False
    value=gate.body[0].value
    if (not isinstance(value,ast.Call) or not isinstance(value.func,ast.Name)
            or value.func.id not in ("JSONResponse","_json")):return False
    return (any(k.arg=="status_code" and isinstance(k.value,ast.Constant) and k.value.value==code for k in value.keywords)
            or any(isinstance(a,ast.Constant) and a.value==code for a in value.args))


def _dotted_calls(node,dotted):
    out=[]
    for n in ast.walk(node):
        if isinstance(n,ast.Call):
            name=ast.unparse(n.func)
            if name==dotted:out.append(n)
    return out


def d029_run_order_violations(source):
    """Structural D-029 invariants of the Run route, independent of any byte pin.

    An intent id is not authorization: the ledger is consulted only after authentication, project resolution,
    ownership and the purpose-bound Run CSRF; the protected-reference refusal is evaluated by the same call that
    would otherwise read the ledger; reservation precedes the engine; the intent is finalized INSIDE the atomic
    commit (never by a second writer).  Applies only to a router that carries the intent lifecycle."""
    if "run_intent_id" not in source:return []
    errors=[]
    try:
        fn=_function(ast.parse(source),"v2_workbook_run")
        first=lambda d:min([c.lineno for c in _dotted_calls(fn,d)] or [10**9])
        order=("resolve_accessible_project","validate_csrf_token","_ri.decide","_ri.reserve_and_start",
               "run_model_process","v2_atomic_run_commit","_ri.committed_decision")
        lines=[first(d) for d in order]
        if any(l>=10**9 for l in lines) or lines!=sorted(lines) or len(set(lines))!=len(lines):
            errors.append("run intent lifecycle out of order: "+", ".join("%s@%s"%(d,l) for d,l in zip(order,lines)))
        if len(_dotted_calls(fn,"validate_csrf_token"))!=1:errors.append("run intent: validator duplicated")
        decide=_dotted_calls(fn,"_ri.decide")
        if len(decide)!=1:errors.append("run intent: reconciliation must be a single call")
        else:
            keywords={k.arg:ast.unparse(k.value) for k in decide[0].keywords}
            if keywords.get("actor_id")!="workspace_owner" or keywords.get("project_id")!="project_record.project_id":
                errors.append("run intent: reconciliation scope is not the owner/project")
            if keywords.get("protected_reference")!="is_protected_reference(project_record)":
                errors.append("run intent: protected-reference refusal not evaluated before the ledger")
            if keywords.get("workbook_version")!="workbook_version" or keywords.get("content_hash")!="content_hash":
                errors.append("run intent: reconciliation must use the ORIGINAL submitted binding")
        commits=_dotted_calls(fn,"v2_atomic_run_commit")
        if len(commits)!=1 or not any(k.arg=="run_intent" and ast.unparse(k.value)=="_ri_reservation" for k in commits[0].keywords):
            errors.append("run intent: atomic commit must receive the reservation (single history writer)")
        if _dotted_calls(fn,"_ri.finalize") or _dotted_calls(fn,"finalize_cursor"):
            errors.append("run intent: no finalization outside the atomic commit transaction")
    except (ValueError,TypeError,AttributeError) as exc:
        errors.append("run intent: invalid route source: "+type(exc).__name__)
    return errors


def _browser_layers():
    return {
        BROWSER_CORRECTION_PATH:(BROWSER_CORRECTION_SOURCE_HEAD,BROWSER_CORRECTION_PARENT,BROWSER_CORRECTION_BLOB),
        PPA_CORRECTION_PATH:(PPA_CORRECTION_SOURCE_HEAD,PPA_CORRECTION_PARENT,PPA_CORRECTION_BLOB),
    }


# F01 complete rate contract; historical layers above are immutable.
FINVAL_F01_COMPLETE_SUCCESSORS={'app/v2/router.py': '2ec6b05a7d730e1034348da632d37efc6bfa9c3b', 'app/v2/grid_router.py': '0d1ab6c05b7d4f53f9d4a341818e107969bcccc0'}


def violations(sources,*,check_pin=True):
    errors=[];trees={}
    for path,expected in BLOBS.items():
        text=sources.get(path)
        if not isinstance(text,str):errors.append(path+": missing source");continue
        layer=_browser_layers().get(path)
        admitted={expected,layer[2]} if layer else {expected}
        if path in FINVAL_B2C1_SUCCESSORS:admitted=admitted|{FINVAL_B2C1_SUCCESSORS[path]}
        if path in D029_RUN_INTENT_SUCCESSORS:admitted=admitted|{D029_RUN_INTENT_SUCCESSORS[path]}
        if path in REACT_MVP_CORRECTION_SUCCESSORS:admitted=admitted|{REACT_MVP_CORRECTION_SUCCESSORS[path]}
        if path in FINVAL_RATE_SUCCESSORS:admitted=admitted|{FINVAL_RATE_SUCCESSORS[path]}
        if path in FINVAL_F01_COMPLETE_SUCCESSORS:admitted=admitted|{FINVAL_F01_COMPLETE_SUCCESSORS[path]}
        if check_pin and git_blob(text) not in admitted:errors.append(path+": unreviewed blob")
        if path.endswith(".py"):
            try:trees[path]=ast.parse(text)
            except (SyntaxError,ValueError):errors.append(path+": unparsable source")
    if errors:return errors
    try:
        for path,handlers in ROUTES.items():
            for name,operation in handlers.items():
                fn=_function(trees[path],name);calls=_call(fn,"validate_mutation_token")
                admitted=[]
                for c in calls:
                    if len(c.args)==4 and isinstance(c.args[3],ast.Constant) and c.args[3].value==operation:
                        admitted.append(c)
                if len(admitted)!=1:errors.append(name+": missing/duplicated operation gate");continue
                call=admitted[0]
                expected_project="body.project" if name=="grid_save" else "project"
                expected_token=("body.csrf_token" if name=="grid_save" else "csrf_token" if name=="grid_cost_lines_save"
                                else "(await request.form()).get('csrf_token')")
                if (ast.unparse(call.args[0])!="request" or ast.unparse(call.args[1])!=expected_project
                        or ast.dump(call.args[2],include_attributes=False)!=ast.dump(ast.parse(expected_token,mode="eval").body,include_attributes=False)):
                    errors.append(name+": session/resource/transport binding changed")
                gates=[n for n in ast.walk(fn) if isinstance(n,ast.If) and isinstance(n.test,ast.UnaryOp)
                       and isinstance(n.test.op,ast.Not) and n.test.operand is call and _reject(n,403)]
                if len(gates)!=1:errors.append(name+": not an immediate fail-closed403 gate");continue
                gate=gates[0]
                # Every actual candidate writer must follow the request gate.
                writers={"get_or_create_base_case_scenario","add_scenario","select_scenario","rename_scenario","archive_scenario",
                         "update_scenario_overrides","remove_scenario_override","remove_scenario_overrides","reset_reference_seeded_lines",
                         "add_capex_line","update_capex_line","deactivate_capex_line","reactivate_capex_line","reorder_capex_lines",
                         "add_opex_line","update_opex_line","deactivate_opex_line","reactivate_opex_line","reorder_opex_lines",
                         "set_contingency_percentage","update_cost_lines_batch","build_canonical_last_run_institutional_workbook_export"}
                if any(c.lineno<=gate.lineno for c in ast.walk(fn) if isinstance(c,ast.Call)
                       and ((isinstance(c.func,ast.Name) and c.func.id in writers)
                            or (isinstance(c.func,ast.Attribute) and c.func.attr in ("apply_batch_draft_update","apply_field_draft_update","apply_draft_update","record_export")))):
                    errors.append(name+": gate after writer")
                if name.startswith("v2_scenario_"):
                    refs=[n for n in fn.body if isinstance(n,ast.If) and isinstance(n.test,ast.Call)
                          and isinstance(n.test.func,ast.Name) and n.test.func.id=="is_protected_reference" and _reject(n,409)]
                    if len(refs)!=1 or refs[0].lineno>=gate.lineno:errors.append(name+": reference gate missing/late")
        errors.extend(d029_run_order_violations(sources["app/v2/router.py"]))
        # Token implementation is independently pinned, and retained even in
        # no-byte-pin mutation tests: no hidden helper bypass is admissible.
        if git_blob(sources[TOKEN_MODULE])!=BLOBS[TOKEN_MODULE]:errors.append("mutation token authority changed")
        from tests import rc_sec_csrf_successor as old
        old_sources={p:sources[p] for p in old.BLOBS}
        errors.extend(old.violations(old_sources,check_pin=False))
    except (KeyError,ValueError,TypeError,AttributeError) as exc:errors.append("invalid security source: "+type(exc).__name__)
    return errors


def current_mutation_successor_valid(*,repo=None):
    root=Path(repo) if repo is not None else ROOT
    try:
        sources={p:(root/p).read_text(encoding="utf-8") for p in BLOBS}
        if violations(sources):return False
        # Centralizing validation must not make additional unreviewed callers
        # disappear from the historical validator-file inventory.
        consumers=set()
        for path in list((root/"app").rglob("*.py"))+[root/"main_web.py"]:
            if "mutation_csrf" in path.read_text(encoding="utf-8"):
                consumers.add(path.relative_to(root).as_posix())
        if consumers!=CONSUMERS:return False
        listing=subprocess.check_output(["git","ls-tree","-r",SOURCE_HEAD],cwd=root).decode("utf-8")
        pinned={line.split("\t",1)[1]:line.split("\t",1)[0].split()[2] for line in listing.splitlines()}
        if any(pinned.get(p)!=blob for p,blob in BLOBS.items()):return False
        subprocess.run(["git","merge-base","--is-ancestor",SOURCE_HEAD,"HEAD"],cwd=root,check=True,capture_output=True)
        def read_git(*args):
            return subprocess.check_output(["git",*args],cwd=root,stderr=subprocess.PIPE).decode("utf-8").strip()
        for path,(source,parent,blob) in _browser_layers().items():
            # provenance is verified while the layer's blob OR a later admitted successor of the path is current
            if git_blob(sources[path]) not in {blob,REACT_MVP_CORRECTION_SUCCESSORS.get(path)}:continue
            if read_git("rev-parse",source+"^:"+path)!=BLOBS[path]:return False
            if read_git("rev-list","--parents","-n","1",source).split()!=[source,parent]:return False
            if read_git("rev-parse",source+":"+path)!=blob:return False
            if read_git("diff-tree","--no-commit-id","--name-only","-r",source).splitlines()!=[path]:return False
            subprocess.run(["git","merge-base","--is-ancestor",source,"HEAD"],cwd=root,check=True,capture_output=True)
        return True
    except (OSError,subprocess.SubprocessError,SyntaxError,ValueError,TypeError,UnicodeError,AttributeError):return False

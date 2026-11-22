"""Finite P0 candidate admission after accepted FULL recovery. All product and CI control files remain frozen.

This low-level terminal signature authenticates literal source/mode/base/handoff pins; no older cohort is called.
It grants no V5, merge, workflow-activation, FULL-performance or financial authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = '955952c1bc16b21ce342121c5224a19d3e105aa7'
BASE_TREE = '7bb70e037bae0cdef62ac3f6115d420089ad0d7d'
MANIFEST = 'docs/ci_v4/p0_40min/SOURCE_SUCCESSOR.json'
SCHEMA = 'CI_V4_P0_CANDIDATE_EXACT_SOURCE_V1'
AUTHORIZATION = 'User instruction 2026-11-17: repair PR #457 source admission with one finite successor for the existing inert P0 candidate; no workflow activation, financial change, V5 promotion, merge or deployment.'
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = 'tests/ci_v4_full_recovery_scope.py'
BASE_COHORTS = ('tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')
NEW = frozenset(('docs/ci_v4/p0_40min/00_EXECUTIVE_VERDICT_HR.md', 'docs/ci_v4/p0_40min/CANDIDATE_PATH_MANIFEST.json', 'docs/ci_v4/p0_40min/CURRENT_STATE_AND_ROOT_CAUSE.md', 'docs/ci_v4/p0_40min/DESIGN_AND_SAFETY.md', 'docs/ci_v4/p0_40min/INVENTORY_RECONCILIATION.json', 'docs/ci_v4/p0_40min/NEGATIVE_TAMPER_EVIDENCE.md', 'docs/ci_v4/p0_40min/NEXT_OWNER_ACTIONS.md', 'docs/ci_v4/p0_40min/PERFORMANCE_AB_COMPARISON.csv', 'docs/ci_v4/p0_40min/WORKER_ASSIGNMENT_SIMULATION.csv', 'docs/ci_v4/p0_40min/base-governance.json', 'docs/ci_v4/p0_40min/cache-mutation-evidence.json', 'docs/ci_v4/p0_40min/candidate-tests.xml', 'docs/ci_v4/p0_40min/candidate/benchmark_scope.py', 'docs/ci_v4/p0_40min/candidate/full_coverage.py', 'docs/ci_v4/p0_40min/candidate/scoped_evaluate.py', 'docs/ci_v4/p0_40min/candidate/simulate_workers.py', 'docs/ci_v4/p0_40min/candidate/test_full_coverage.py', 'docs/ci_v4/p0_40min/targeted-tests.xml', 'docs/ci_v4/p0_40min/worker-simulation-summary.jsonl', 'docs/ci_v4/p0_40min/workflow-probe-governance.json', 'tests/ci_v4_p0_scope.py', 'tests/test_ci_v4_p0_scope.py',
                 'tests/ci_immutable_git_reads.py', 'tests/test_ci_immutable_git_reads.py',
                 # P1 (post-#457): the CI Performance Budget guard, its trusted policy/baseline/tests and the activation procedure.
                 '.github/workflows/ci_perf_guard.yml', 'tools/ci_perf_guard.py', 'docs/ci_v4/performance_budget_policy.json',
                 'docs/ci_v4/performance_baseline.json', 'tests/test_ci_perf_guard.py', 'docs/ci_v4/p1_runtime/ACTIVATION_PROCEDURE.md',
                 'docs/ci_v4/p1_runtime/NODE_SPLIT_ISOLATION_PROOF.md',
                 # P2: parallel exact-inventory FULL controller, its policy, measured weights, tests and design note.
                 'tools/ci_full_parallel.py', 'tests/test_ci_full_parallel.py', 'docs/ci_v4/p2_full/full_parallel_policy.json',
                 'docs/ci_v4/p2_full/full_node_weights.json', 'docs/ci_v4/p2_full/README.md', 'docs/ci_v4/p2_full/ISOLATION_EVIDENCE.json',
                 # post-#460: per-NODE scope evidence (exact node ids; plain == scoped; mutation between calls detected)
                 'docs/ci_v4/p2_full/NODE_SCOPE_EVIDENCE.json',
                 'docs/model_v11/v11-stage3-release-successor-candidate.json',
                 'tests/v11_stage3_release_successor.py', 'tests/test_v11_stage3_release_successor.py',
                 'tests/mutation_security_browser_lineage.py', 'tests/test_mutation_security_browser_lineage.py'))
R04_ISOLATION_TEST = 'tests/r04_ppa_global_cap/test_r04_allocation.py'

# The files rewritten by this PR (REPLACED: accepted BASE blob + exact new blob; ``.github/`` and ``tools/`` stay literal).
# Correction E: one read-only import-time scope (call_scope + content-addressed Git object reads) at the two historical-subject sites.
# tests/conftest.py is NOT owned: the historical U1/U2/WF-06B guards keep it a protected, unowned path.
# Correction E admits the exact changes audited from d605fac5. The separate
# reviewed digests also reject a paired source and manifest edit.
BROWSER_REPAIR_BLOBS = {
    'tests/test_rcux2_progress_scope_browser.py': 'c0e28cc306fc4f4746ab5e7d5c5ece1f07d6c2d5',
    'static/js/model_view_refresh.js': 'e5172283ec88eca4e5d35a7f6aedd43cb4263bdc',
    'static/js/cost_staging.js': 'c3edddadbd46aa3d4ffc913a0cf22da244ead3d8',
    'app/v2/capex_router.py': '73a665c1fd81f17136f8acd543b4d17ae2147bb2',
    'app/v2/opex_router.py': '5f346c0ca97a1c4cafab30bd3f6ea4391e0b0861',
    'tests/test_cost_batch_save_browser_v1.py': '47eb26d4a8afe4c8e6dc88aa22b0abaaf0c22de7',
    'tests/test_cost_editing_ux_v2_browser.py': 'f6dac1bdb95eaf7446031b4b3de3d337b6b287cc',
    'tests/test_cost_grid_editing_browser_v1.py': 'd6dc005e9e0c6d95c7c35cddf6b5dd6fbd103913',
    'tests/test_jev_panel_browser.py': '8c7e3f3c3a726a00a8d5de88c6ea5ad3b0bce1e5',
    'tests/test_m3_two_driver_sensitivity_browser.py': 'ad206e41a530a7d2e351db6b66305e1e2c0f8945',
    'tests/test_model_trust_pack_browser.py': '121c375f77c60bef55713d1c170894947e6989b1',
    'tests/test_p3_browser_acceptance.py': 'b472153960561fe5041df195bcdbee8a2a2eb77e',
    'tests/test_radar_r3_liquidity.py': 'cdb689add60f91ab8371e0794aca0c97db12b77f',
    'tests/test_ui_protocol_shell.py': 'ffde62258729e1d4bff05fd26b56d3630bc47602',
}
COST_PRESENTATION_PATHS = frozenset(('app/v2/capex_router.py', 'app/v2/opex_router.py',
                                     'static/js/cost_staging.js', 'static/js/model_view_refresh.js',
                                     'app/templates/v2/partials/sheet_project_setup.html', 'app/templates/v2/workbook.html',
                                     'static/js/workbook_v2.js', 'static/css/model_diagnostics_v2.css'))
# Correction F admits the exact browser-runtime and test-successor changes audited
# from 047d51d6: the governed-navigation test successors, the swap-teardown blur
# guard, the BESS loader placement, the diagnostics containment and the
# fail-closed Chromium derivation in the PR workflow. The separate reviewed
# digests also reject a paired source and manifest edit.
CORRECTION_F_BLOBS = {
    'app/templates/v2/partials/sheet_project_setup.html': '45ced98aa22394ee2167f7cc2ff55ba8d43cab70',
    'app/templates/v2/workbook.html': '94b9f61f0eeed25dcb0568dc745537f409fce256',
    'static/js/workbook_v2.js': 'ed76fa5ec332c0ddc6c74f1c980c71ce54ecf49c',
    'static/css/model_diagnostics_v2.css': '08f068dd14086a43133c8888f718706fd10689f1',
    'tests/test_data_center_browser_acceptance.py': '4813332b601cd188656ff939ede34574dacb779f',
    'tests/test_model_golden_flows_browser.py': 'd679ce2651ccb725344269617e571aaf3cde2931',
    'tests/test_model_react_poc_browser_acceptance.py': '815f255a9d10e613683961a79e527e50668a02cb',
    'tests/test_model_v7_diagnostics_browser.py': '37cb5d247ef256d6c3bb60f65bd4e4e4d73a9452',
    'tests/test_radar_n04_browser.py': '4d68e71b1798d490fd93d59d44555c0e98250672',
    'tests/test_sc34_workflow_journeys_browser.py': '14f77711ffa34c731ca4bdc60ff654f6b16f7739',
    # The mutation-inventory module itself moves once: its Correction F successor admits the
    # exact project-setup template through the P0 handoff, preserving historical R1 pins.
    'tests/model_mutation_security_successor.py': 'd18ea69a588b0e93fce4b09e2d102f1e2c179610',
}
REPLACED = frozenset(('tests/test_rc7c_candidate_successor.py', 'tests/test_v9p2a_odr_successor.py',
                      # P1: U1 node split (SPLIT_SAFE_FLOOR_LIMITED, isolation-proven) and its re-measured U1 node weights
                      'docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json',
                      # P1: the closed split allowlist tests gain exactly U1 (with its evidence); U2/O1/Goal Seek stay unsplit
                      'tests/test_ci_v4_nodes.py', 'tests/test_ci_v4_activate.py',
                      # P2: the FULL workflow runs the parallel controller instead of the unsharded CI V3 job (accepted BASE blob + exact new blob)
                      '.github/workflows/ci_v4_full.yml',
                      # post-#460: test-order pollution contained at its source (assertions unchanged; execution-bisected on shard 6 of run 44324970783)
                      'tests/test_p4_token_utility.py', 'tests/test_tokenized_access_wiring.py', 'tests/test_investor_f4_p2_candidate.py',
                      'tests/test_finv2_d01_governance.py', 'tests/test_v11_stage3_release_authority.py', 'tests/test_ux_pr1_scope.py',
                      'tests/test_model_mutation_security_successor.py',
                      R04_ISOLATION_TEST,
                      'tools/ci_v4_release_gate.py', 'tools/ci_v5_shadow.py', '.github/workflows/ci_v5_gate.yml', '.github/workflows/ci_v5_shadow.yml',
                      'tests/test_ci_v4_release_gate.py', 'tests/test_ci_v5_gate.py', 'docs/ci_v5/OWNER_POSTMERGE_ACTIVATION_CHECKLIST.md',
                      # post-#471 (owner decision 2026-11-20): the reviewed FULL skip baseline gains exactly ONE named, count-one, SKIPPED_NOT_PASSED deferral
                      # (the private T01-B/C 34/634 reconciliation); accepted BASE blob + exact new blob, never a wildcard
                      'docs/ci_v4/full_skip_baseline.json'))
# The ONLY ``.github/`` and ``tools/`` paths this cohort owns: exactly the literal paths the bootstrap cohort already admitted. Never a prefix, never a pattern.
CI_PATHS = frozenset(('.github/workflows/ci_perf_guard.yml', 'tools/ci_perf_guard.py',
                      # P2: the parallel exact-inventory FULL controller (new tool) and the FULL workflow that runs it (REPLACED below)
                      '.github/workflows/ci_v4_full.yml', 'tools/ci_full_parallel.py',
                      'tools/ci_v4_release_gate.py', 'tools/ci_v5_shadow.py', '.github/workflows/ci_v5_gate.yml', '.github/workflows/ci_v5_shadow.yml'))
# Shared governance paths whose bytes move by one reviewed literal substitution (HANDOFFS).
HANDOFF_PATHS = frozenset(('tests/c06_cost_workspace_scope.py', 'tests/ci_v4_scope.py', 'tests/ci_v4_full_recovery_scope.py', 'tests/ci_v4_lean_b1_scope.py', 'tests/ci_v4_lean_b2_scope.py', 'tests/ci_v4_lean_b3_scope.py', 'tests/ci_v5_bootstrap_scope.py', 'tests/ci_v5_gate_scope.py', 'tests/ci_v5_hardening_scope.py', 'tests/fin_v2_cohorts.py', 'tests/test_bess02_scope.py', 'tests/test_c06_cost_workspace_scope.py', 'tests/test_ci_v4_full_recovery_scope.py', 'tests/test_ci_v4_lean_b1_scope.py', 'tests/test_ci_v4_lean_b2_scope.py', 'tests/test_ci_v4_lean_b3_scope.py', 'tests/test_ci_v4_lean_tamper_matrix.py', 'tests/test_ci_v4_perf_scope.py', 'tests/test_ci_v5_bootstrap_scope.py', 'tests/test_ci_v5_gate_scope.py', 'tests/test_ci_v5_hardening_scope.py', 'tests/test_f03_financing_scope.py', 'tests/test_f04_financing_scope.py', 'tests/test_r02_ppa_ux_scope.py', 'tests/test_r03_ppa_scope.py', 'tests/test_r04_ppa_scope.py', 'tests/test_t01e_remediation_scope.py', 'tests/u1_scope.py', 'tests/ux_pr3b1_scope.py'))
CURRENT_MAPS = frozenset((
    'docs/ci_v4/SOURCE_SUCCESSOR.json',
    'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json',
    'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json',
    'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json',
    'docs/tax_reference_registry/SOURCE_SUCCESSOR.json',
))
REACT_BUNDLE_PATH = 'static/react/finco-react.js'
MAP_KEYS = ('tests/fin_v2_cohorts.py', 'tests/u1_scope.py')
R1_MAP = 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json'
R1_SECURITY_TEST = 'tests/test_model_mutation_security_successor.py'
TAX_MAP = 'docs/tax_reference_registry/SOURCE_SUCCESSOR.json'
R1_DELEGATION_GUARD = 'tests/ux_pr3b1_scope.py'
MAP_EXTRA_KEYS = {
    'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json': (REACT_BUNDLE_PATH,),
    R1_MAP: (R1_SECURITY_TEST, REACT_BUNDLE_PATH),
    'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json': (REACT_BUNDLE_PATH,),
    TAX_MAP: (R1_DELEGATION_GUARD,),
}
MAP_PIN_KEYS = (*MAP_KEYS, R1_SECURITY_TEST, R1_DELEGATION_GUARD, REACT_BUNDLE_PATH)
HANDOFF_PATHS |= frozenset(('tests/fin_v2_integration_409_scope.py', 'tests/fin_v2_wf06a_scope.py', 'tests/test_wsv2_core_scope.py', 'tests/post413_r1_scope.py', 'tests/test_fin_v2_integration_409_scope.py',
                            'tests/post413_o1_scope.py', 'tests/test_post413_o1_scope.py', 'tests/test_post413_r1_scope.py',
                            'tests/ux_pr1_scope.py', 'tests/ux_pr2a_scope.py', 'tests/ux_pr2b_scope.py', 'tests/ux_pr2c_scope.py',
                            'tests/test_ux_pr2a_scope.py', 'tests/test_finval_f01_scope.py', 'tests/wsv2_core_scope.py'))
HANDOFF_PATHS |= {'tests/test_v11_stage3_successor.py'}
HANDOFF_PATHS |= frozenset(('tests/fin_v2_3_scope.py', 'tests/fin_v2_r1_scope.py', 'tests/fin_v2_pr394_corr_scope.py', 'tests/fin_v2_ci_scope.py', 'tests/fin_v2_wsv2_scope.py'))
FULL_VISUAL_WORKFLOW_BLOB = '6f9adcb481a3375d5ab2fd67a85cbb0341e2dc60'
PR_CHROMIUM_WORKFLOW = '.github/workflows/ci_v4_pr.yml'
PR_CHROMIUM_WORKFLOW_BLOB = '35e05ad6c3a82f3845bfabc573a13b0f1d8a8164'
REPLACED |= BROWSER_REPAIR_BLOBS.keys() | {PR_CHROMIUM_WORKFLOW}
REPLACED |= CORRECTION_F_BLOBS.keys()
CI_PATHS |= {PR_CHROMIUM_WORKFLOW}
HANDOFF_PATHS |= {'tests/test_ux_pr2c_scope.py'}
SUPERSEDED = HANDOFF_PATHS | REPLACED | CURRENT_MAPS
OWNED_PATHS = NEW | SUPERSEDED
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", "migrations/", "app/", "research/", "frontend/", "static/", "main_web.py")
NEW_ONLY_PREFIXES = (".github/", "tools/")
# Accepted CI V4 control sources that this successor must leave byte-identical to BASE.
FROZEN = (
    ".github/workflows/ci_v4_f01_job.yml",
    ".github/workflows/ci_v4_release_gate.yml", ".github/workflows/ci_v4_shadow_split.yml",
    "docs/ci_v4/ci-v4-policy.json", "docs/ci_v4/module_weights.json",
    "pytest.ini",
    "tools/ci_v4_activate.py", "tools/ci_v4_aggregate.py", "tools/ci_v4_full_record.py", "tools/ci_v4_governance_gate.py",
    "tools/ci_v4_nodes.py", "tools/ci_v4_schedule.py", "tools/ci_v4_select.py", "tools/ci_v4_shard.py",
)


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref=None):
    # A committed ref is read from Git (with the repository root); the working tree is read from disk.
    return (Path(root) / path).read_bytes() if ref is None else _git(root, "show", ref + ":" + path)


def _blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


_MODULE_BLOB = _blob(Path(__file__).read_bytes())


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        raw = _read(root, MANIFEST, ref)
        d = json.loads(raw)
        if raw != (json.dumps(d, indent=2, sort_keys=True) + "\n").encode():       # canonical bytes only: no extra, reordered or hidden byte
            return {}
        return d if (isinstance(d, dict) and set(d) == {"schema_version", "authorization", "base", "base_tree", "source_blobs", "base_blobs",
                                                       "source_modes", "base_modes"}
                     and d.get("authorization") == AUTHORIZATION and d["schema_version"] == SCHEMA and d["base"] == BASE
                     and d["base_tree"] == BASE_TREE and isinstance(d["source_blobs"], dict) and isinstance(d["base_blobs"], dict)) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


def expected_map(root, path, pins=None):
    """Allow the registry and U1 keys and the two map-specific R1 test handoff pins."""
    d = json.loads(_base_bytes(str(root), path))
    pins = manifest(root).get("source_blobs", {}) if pins is None else pins
    pins = {**pins, REACT_BUNDLE_PATH: C06_REVIEWED_PRODUCT_BLOBS[REACT_BUNDLE_PATH]}
    keys = (*MAP_KEYS, *MAP_EXTRA_KEYS.get(path, ()))
    for key in keys:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The V5-3 gate cohort gains one forward hook to this cohort (the same acyclic pattern the
# V5-2B cohort received from the bootstrap and the gate from V5-2B); the earlier layers accept one more reviewed tail state; the registry appends this cohort exactly once;
# the U1 discovery list names it; the exact-tail tests accept one more state.
HANDOFFS = {'tests/c06_cost_workspace_scope.py': [("    if 'tests.ci_v4_full_recovery_scope' in COHORT_MODULES:      # the FULL-recovery successor, "
                                        'one chain step further (literal HANDOFFS, only while its signature holds)\r\n'
                                        '        from tests import ci_v4_full_recovery_scope as FR\r\n'
                                        '        out = out | (frozenset(FR.HANDOFFS) if FR.signature_ok(root, ref) else frozenset())\r\n'
                                        '    return out\r\n'
                                        '\r\n'
                                        '\r\n',
                                        "    if 'tests.ci_v4_full_recovery_scope' in COHORT_MODULES:      # the FULL-recovery successor, "
                                        'one chain step further (literal HANDOFFS, only while its signature holds)\r\n'
                                        '        from tests import ci_v4_full_recovery_scope as FR\r\n'
                                        '        out = out | (frozenset(FR.HANDOFFS) if FR.signature_ok(root, ref) else frozenset())\r\n'
                                        "    if 'tests.ci_v4_p0_scope' in COHORT_MODULES:\r\n"
                                        '        from tests import ci_v4_p0_scope as P0\r\n'
                                        '        out = out | (frozenset(P0.HANDOFFS) if P0.signature_ok(root, ref) else frozenset())\r\n'
                                        '    return out\r\n'
                                        '\r\n'
                                        '\r\n'),
                                       ('                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), BASE_COHORTS + (__name__, SUCCESSOR, "
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'),\r\n"
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope'),\r\n"
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'),\r\n"
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        "'tests.ci_v4_full_recovery_scope')):       # at most the seven reviewed successors\r\n"
                                        '            return False\r\n'
                                        '        d = manifest(root, ref)\r\n'
                                        '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\r\n',
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), BASE_COHORTS + (__name__, SUCCESSOR, "
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'),\r\n"
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope'),\r\n"
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'),\r\n"
                                        '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                        "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        "'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):       # at most the seven "
                                        'reviewed successors\r\n'
                                        '            return False\r\n'
                                        '        d = manifest(root, ref)\r\n'
                                        '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\r\n')],
 'tests/ci_v4_full_recovery_scope.py': [('    root = Path(repo) if repo is not None else ROOT\n'
                                         '    try:\n'
                                         '        pins = manifest(root, ref).get("source_blobs", {})\n'
                                         '        for path in HANDOFFS:\n'
                                         '            actual = _read(root, path, ref)\n'
                                         '            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n'
                                         '                return False\n'
                                         '        return True\n'
                                         '    except (OSError, ValueError, KeyError, TypeError, UnicodeError, '
                                         'subprocess.CalledProcessError):\n'
                                         '        return False\n'
                                         '\n',
                                         '    root = Path(repo) if repo is not None else ROOT\n'
                                         '    try:\n'
                                         '        pins = manifest(root, ref).get("source_blobs", {})\n'
                                         '        N = _next()\n'
                                         '        nxt = N is not None and N.signature_ok(root, ref)\n'
                                         '        for path in HANDOFFS:\n'
                                         '            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further '
                                         'substitution of this shared path\n'
                                         '                continue\n'
                                         '            actual = _read(root, path, ref)\n'
                                         '            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n'
                                         '                return False\n'
                                         '        return N.reviewed_edits_ok(root, ref) if nxt else True\n'
                                         '    except (OSError, ValueError, KeyError, TypeError, UnicodeError, '
                                         'subprocess.CalledProcessError):\n'
                                         '        return False\n'
                                         '\n'),
                                        ('        return\n'
                                         '    _SCOPE.append({})\n'
                                         '    try:\n'
                                         '        yield\n'
                                         '    finally:\n'
                                         '        _SCOPE.pop()\n'
                                         '\n'
                                         '\n'
                                         'def _compute(root, ref, mode):\n'
                                         '    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the '
                                         'changed/untracked checks."""\n'
                                         '    if mode == "exact":\n'
                                         '        return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
                                         '    return _signature_ok(root, ref, mode)\n'
                                         '\n'
                                         '\n'
                                         'def _verdict(root, ref, closure):\n',
                                         '        return\n'
                                         '    _SCOPE.append({})\n'
                                         '    try:\n'
                                         '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, '
                                         'never kept globally.\n'
                                         '        N = _next()\n'
                                         '        if N is None:\n'
                                         '            yield\n'
                                         '        else:\n'
                                         '            with N.scoped():\n'
                                         '                yield\n'
                                         '    finally:\n'
                                         '        _SCOPE.pop()\n'
                                         '\n'
                                         '\n'
                                         'def _compute(root, ref, mode):\n'
                                         '    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the '
                                         'changed/untracked checks."""\n'
                                         '    from contextlib import nullcontext\n'
                                         '    N = _next()\n'
                                         '    with (N.scoped() if N is not None else nullcontext()):\n'
                                         '        if mode == "exact":\n'
                                         '            return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
                                         '        return _signature_ok(root, ref, mode)\n'
                                         '\n'
                                         '\n'
                                         'def _verdict(root, ref, closure):\n'),
                                        ('    return _verdict(Path(repo) if repo is not None else ROOT, ref, False)\n'
                                         '\n'
                                         '\n'
                                         'def map_keys(repo=None, ref=None):\n'
                                         '    return tuple(MAP_KEYS)\n'
                                         '\n'
                                         '\n'
                                         '@lru_cache(maxsize=512)\n',
                                         '    return _verdict(Path(repo) if repo is not None else ROOT, ref, False)\n'
                                         '\n'
                                         '\n'
                                         "SUCCESSOR = 'tests.ci_v4_p0_scope'\n"
                                         '\n'
                                         '\n'
                                         'def _next():\n'
                                         '    """The one finite forward successor (CI V4 FULL recovery). Low-level only: its signature '
                                         'never calls this module or the composite."""\n'
                                         '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                         '    if SUCCESSOR not in COHORT_MODULES:\n'
                                         '        return None\n'
                                         '    from tests import ci_v4_p0_scope\n'
                                         '    return ci_v4_p0_scope\n'
                                         '\n'
                                         '\n'
                                         'def _next_pins(root, ref):\n'
                                         '    N = _next()\n'
                                         '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else '
                                         '{}\n'
                                         '\n'
                                         '\n'
                                         'def later_handoffs(root, ref):\n'
                                         '    """HANDOFFS of every reviewed successor behind this cohort (only while each signature '
                                         'holds): a path a LATER cohort owns is not judged against this cohort\'s literals."""\n'
                                         '    N = _next()\n'
                                         '    if N is None or not N.signature_ok(root, ref):\n'
                                         '        return frozenset()\n'
                                         "    return frozenset(N.HANDOFFS) | (N.later_handoffs(root, ref) if hasattr(N, 'later_handoffs') "
                                         'else frozenset())\n'
                                         '\n'
                                         '\n'
                                         'def map_keys(repo=None, ref=None):\n'
                                         '    root = Path(repo) if repo is not None else ROOT\n'
                                         '    with scoped():\n'
                                         '        N = _next()\n'
                                         '        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_KEYS) if N is not None and '
                                         'N.signature_ok(root, ref) else ()\n'
                                         '        return tuple(MAP_KEYS) + more\n'
                                         '\n'
                                         '\n'
                                         '@lru_cache(maxsize=512)\n'),
                                        ('    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: '
                                         'nothing cached from mutable state."""\n'
                                         '    try:\n'
                                         '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                         '        if COHORT_MODULES != BASE_COHORTS + (__name__,):\n'
                                         '            return False\n'
                                         '        d = manifest(root, ref)\n'
                                         '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n'
                                         '        if pins.get("tests/ci_v4_full_recovery_scope.py") != _MODULE_BLOB:\n'
                                         '            return False\n'
                                         '        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:\n'
                                         '            return False\n',
                                         '    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: '
                                         'nothing cached from mutable state."""\n'
                                         '    try:\n'
                                         '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                         '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, '
                                         'SUCCESSOR)):\n'
                                         '            return False\n'
                                         '        d = manifest(root, ref)\n'
                                         '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n'
                                         '        nx = _next_pins(root, ref)\n'
                                         '        if nx.get("tests/ci_v4_full_recovery_scope.py", '
                                         'pins.get("tests/ci_v4_full_recovery_scope.py")) != _MODULE_BLOB:\n'
                                         '            return False\n'
                                         '        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:\n'
                                         '            return False\n'),
                                        ('        if any(_base_mode(key, p) != d["base_modes"][p] for p in SUPERSEDED):\n'
                                         '            return False\n'
                                         '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
                                         '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\n'
                                         '        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\n'
                                         '            return False\n'
                                         '        owned = (OWNED_PATHS - (set() if closure else CURRENT_MAPS)) | {MANIFEST}\n'
                                         '        if any(modes.get(p) != "100644" for p in owned):\n',
                                         '        if any(_base_mode(key, p) != d["base_modes"][p] for p in SUPERSEDED):\n'
                                         '            return False\n'
                                         '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
                                         '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n'
                                         '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\n'
                                         '        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\n'
                                         '            return False\n'
                                         '        owned = (OWNED_PATHS - (set() if closure else CURRENT_MAPS)) | {MANIFEST}\n'
                                         '        if any(modes.get(p) != "100644" for p in owned):\n'),
                                        ('                return False\n'
                                         '        if closure:\n'
                                         '            for p in CURRENT_MAPS:\n'
                                         '                if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):\n'
                                         '                    return False\n'
                                         '        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, '
                                         'p) for p in FROZEN):\n'
                                         '            return False\n',
                                         '                return False\n'
                                         '        if closure:\n'
                                         '            for p in CURRENT_MAPS:\n'
                                         '                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in '
                                         'MAP_KEYS))):\n'
                                         '                    return False\n'
                                         '        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, '
                                         'p) for p in FROZEN):\n'
                                         '            return False\n'),
                                        ('\n'
                                         'def _diff_ok(root, ref):\n'
                                         '    try:\n'
                                         '        allowed = OWNED_PATHS | {MANIFEST}\n'
                                         '        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref '
                                         'else []), "--").decode().splitlines())\n'
                                         '        if not changed <= allowed:\n'
                                         '            return False\n',
                                         '\n'
                                         'def _diff_ok(root, ref):\n'
                                         '    try:\n'
                                         '        allowed = closure_paths(root, ref)\n'
                                         '        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref '
                                         'else []), "--").decode().splitlines())\n'
                                         '        if not changed <= allowed:\n'
                                         '            return False\n'),
                                        ('\n'
                                         '\n'
                                         'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                                         '    return dict(manifest(repo, ref).get("source_blobs", {}))\n'
                                         '\n'
                                         '\n'
                                         'def closure_paths(repo=None, ref=None):\n'
                                         '    return OWNED_PATHS | {MANIFEST} if signature_ok(repo, ref) else frozenset()\n'
                                         '\n'
                                         '\n'
                                         'def allowed_path(path, repo=None, ref=None):\n',
                                         '\n'
                                         '\n'
                                         'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                                         '    root = Path(repo) if repo is not None else ROOT\n'
                                         '    with scoped():\n'
                                         '        pins = dict(manifest(repo, ref).get("source_blobs", {}))\n'
                                         '        pins.update(_next_pins(root, ref))\n'
                                         '        return pins\n'
                                         '\n'
                                         '\n'
                                         'def closure_paths(repo=None, ref=None):\n'
                                         '    root = Path(repo) if repo is not None else ROOT\n'
                                         '    with scoped():\n'
                                         '        if not signature_ok(root, ref):\n'
                                         '            return frozenset()\n'
                                         '        N = _next()\n'
                                         '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else '
                                         'frozenset())\n'
                                         '\n'
                                         '\n'
                                         'def allowed_path(path, repo=None, ref=None):\n'),
                                        ('\n'
                                         '\n'
                                         'def supersedes(path, value, repo=None, ref=None):\n'
                                         '    if path not in SUPERSEDED:\n'
                                         '        return False\n'
                                         "    # The signature decides a supersession; the composite separately requires every cohort's "
                                         'FULL exactness (map bytes, changed set, untracked\n'
                                         '    # files), so a signature-only verdict never makes the tree valid.\n'
                                         '    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == '
                                         'value\n'
                                         '\n'
                                         '\n'
                                         'def nontrust_scope_authorized(changed, repo=None):\n'
                                         '    root = Path(repo) if repo is not None else ROOT\n'
                                         '    try:\n'
                                         '        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:\n'
                                         '            return False\n'
                                         '        actual = set(_git(root, "diff", "--name-only", BASE).decode().splitlines())\n',
                                         '\n'
                                         '\n'
                                         'def supersedes(path, value, repo=None, ref=None):\n'
                                         '    with scoped():      # one shared read scope per call: the successor signature is evaluated '
                                         'once, then dropped\n'
                                         '        N = _next()\n'
                                         '        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, '
                                         'ref):\n'
                                         '            return True\n'
                                         '        return _supersedes_own(path, value, repo, ref)\n'
                                         '\n'
                                         '\n'
                                         'def _supersedes_own(path, value, repo=None, ref=None):\n'
                                         '    if path not in SUPERSEDED:\n'
                                         '        return False\n'
                                         "    # The signature decides a supersession; the composite separately requires every cohort's "
                                         'FULL exactness (map bytes, changed set, untracked\n'
                                         '    # files), so a signature-only verdict never makes the tree valid.\n'
                                         '    # the CURRENT pin of this path (the successor overlay wins while its signature holds), never '
                                         'a raw superseded manifest line\n'
                                         '    return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\n'
                                         '\n'
                                         '\n'
                                         'def nontrust_scope_authorized(changed, repo=None):\n'
                                         '    root = Path(repo) if repo is not None else ROOT\n'
                                         '    try:\n'
                                         '        N = _next()\n'
                                         '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, '
                                         'root):\n'
                                         '            return True\n'
                                         '        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:\n'
                                         '            return False\n'
                                         '        actual = set(_git(root, "diff", "--name-only", BASE).decode().splitlines())\n')],
 'tests/ci_v4_lean_b1_scope.py': [("                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                   "'tests.ci_v4_full_recovery_scope')):       # B1 -> B2 -> B3 -> V5 bootstrap -> V5-2B -> V5-3 -> FULL "
                                   'recovery, nothing else\n'
                                   '            return False\n'
                                   '        d = manifest(root, ref)\n'
                                   '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n',
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                   "'tests.ci_v4_full_recovery_scope'), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', "
                                   "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                   "'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):       # B1 -> B2 -> B3 -> V5 "
                                   'bootstrap -> V5-2B -> V5-3 -> FULL recovery, nothing else\n'
                                   '            return False\n'
                                   '        d = manifest(root, ref)\n'
                                   '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n')],
 'tests/ci_v4_lean_b2_scope.py': [('                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                   "'tests.ci_v5_bootstrap_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', "
                                   "'tests.ci_v5_hardening_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', "
                                   "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', "
                                   "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')):       # "
                                   'B2 -> B3 -> V5 bootstrap -> V5-2B -> V5-3 -> FULL recovery, nothing else\n'
                                   '            return False\n'
                                   '        d = manifest(root, ref)\n'
                                   '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n',
                                   '                                  BASE_COHORTS + (__name__, SUCCESSOR, '
                                   "'tests.ci_v5_bootstrap_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', "
                                   "'tests.ci_v5_hardening_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', "
                                   "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'),\n"
                                   "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', "
                                   "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                   "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                   "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):       # B2 "
                                   '-> B3 -> V5 bootstrap -> V5-2B -> V5-3 -> FULL recovery, nothing else\n'
                                   '            return False\n'
                                   '        d = manifest(root, ref)\n'
                                   '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n')],
 'tests/ci_v4_lean_b3_scope.py': [('    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                   'cached from mutable state."""\n'
                                   '    try:\n'
                                   '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                   '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                   "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope'), BASE_COHORTS + (__name__, "
                                   "SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), BASE_COHORTS + (__name__, "
                                   "SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                   "'tests.ci_v4_full_recovery_scope')):\n"
                                   '            return False\n'
                                   '        d = manifest(root, ref)\n'
                                   '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n',
                                   '    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                   'cached from mutable state."""\n'
                                   '    try:\n'
                                   '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                   '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                   "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope'), BASE_COHORTS + (__name__, "
                                   "SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), BASE_COHORTS + (__name__, "
                                   "SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                   "'tests.ci_v4_full_recovery_scope'), BASE_COHORTS + (__name__, SUCCESSOR, "
                                   "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + "
                                   "('tests.ci_v4_p0_scope',)):\n"
                                   '            return False\n'
                                   '        d = manifest(root, ref)\n'
                                   '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n')],
 'tests/ci_v5_bootstrap_scope.py': [('    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                     'cached from mutable state."""\n'
                                     '    try:\n'
                                     '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                     '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                     "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_gate_scope'), BASE_COHORTS + (__name__, SUCCESSOR, "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')):\n"
                                     '            return False\n'
                                     '        d = manifest(root, ref)\n'
                                     '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n',
                                     '    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                     'cached from mutable state."""\n'
                                     '    try:\n'
                                     '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                     '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                     "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_gate_scope'), BASE_COHORTS + (__name__, SUCCESSOR, "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), BASE_COHORTS + (__name__, SUCCESSOR, "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):\n"
                                     '            return False\n'
                                     '        d = manifest(root, ref)\n'
                                     '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n')],
 'tests/ci_v5_gate_scope.py': [('    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                'cached from mutable state."""\n'
                                '    try:\n'
                                '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n'
                                '            return False\n'
                                '        d = manifest(root, ref)\n'
                                '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n',
                                '    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                'cached from mutable state."""\n'
                                '    try:\n'
                                '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                "BASE_COHORTS + (__name__, SUCCESSOR) + ('tests.ci_v4_p0_scope',)):\n"
                                '            return False\n'
                                '        d = manifest(root, ref)\n'
                                '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n')],
 'tests/ci_v5_hardening_scope.py': [('    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                     'cached from mutable state."""\n'
                                     '    try:\n'
                                     '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                     '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                     "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_full_recovery_scope')):\n"
                                     '            return False\n'
                                     '        d = manifest(root, ref)\n'
                                     '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n',
                                     '    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing '
                                     'cached from mutable state."""\n'
                                     '    try:\n'
                                     '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
                                     '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), '
                                     "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_full_recovery_scope'), BASE_COHORTS + (__name__, "
                                     "SUCCESSOR, 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):\n"
                                     '            return False\n'
                                     '        d = manifest(root, ref)\n'
                                     '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n')],
 'tests/fin_v2_cohorts.py': [("                  'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', "
                              "'tests.fin_v2_wsv2_scope', 'tests.wf04_scope',\n"
                              "                  'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', "
                              "'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope',\n"
                              "                  'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', "
                              "'tests.u2_scope', 'tests.ci_v4_scope',\n"
                              "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', "
                              "'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', "
                              "'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', "
                              "'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', "
                              "'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', "
                              "'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', "
                              "'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', "
                              "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                              "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')\n"
                              '# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).\n'
                              "PARENT = 'f79e251903621c1a5c88501d51d6971960b612d3'\n"
                              '\n',
                              "                  'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', "
                              "'tests.fin_v2_wsv2_scope', 'tests.wf04_scope',\n"
                              "                  'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', "
                              "'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope',\n"
                              "                  'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', "
                              "'tests.u2_scope', 'tests.ci_v4_scope',\n"
                              "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', "
                              "'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', "
                              "'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', "
                              "'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', "
                              "'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', "
                              "'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', "
                              "'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', "
                              "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                              "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')\n"
                              '# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).\n'
                              "PARENT = 'f79e251903621c1a5c88501d51d6971960b612d3'\n"
                              '\n')],
 'tests/test_bess02_scope.py': [('            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, '
                                 'W.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                 '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), '
                                 "C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                 "'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                 "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                 "'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                 "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                 "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + "
                                 "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                 "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                 "'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, "
                                 "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                 "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                 '        and C06_APPROVAL.signature_ok()))\n'
                                 "    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', "
                                 "'tests.r02_ppa_ux_scope', 'tests.bess02_scope')\n"
                                 '\n',
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, '
                                 'W.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                 '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), '
                                 "C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                 "'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                 "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                 "'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                 "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                 "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + "
                                 "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                 "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                 "'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, "
                                 "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                 "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                 "C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                 "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                 "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',))\n"
                                 '        and C06_APPROVAL.signature_ok()))\n'
                                 "    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', "
                                 "'tests.r02_ppa_ux_scope', 'tests.bess02_scope')\n"
                                 '\n')],
 'tests/test_c06_cost_workspace_scope.py': [('def test_exact_source_chain_worktree_and_committed_ref(clone):\n'
                                             "    assert F.BASE=='b1c08e2d00fe9933565d253d5cee6e5849b143e1'\n"
                                             "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
                                             '    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + '
                                             '(F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, '
                                             "'tests.ci_v4_lean_b2_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), F.BASE_COHORTS + (F.__name__, "
                                             "F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                             "'tests.ci_v5_bootstrap_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                             "'tests.ci_v5_hardening_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                             "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), F.BASE_COHORTS + (F.__name__, "
                                             "F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                             "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                             "'tests.ci_v4_full_recovery_scope'))       # C06 is followed by the reviewed B1, B2, B3, V5 "
                                             'bootstrap, V5-2B and V5-3 successors\n'
                                             '    assert C.COHORT_MODULES.count(F.__name__)==1\n'
                                             "    for ref in (None,'HEAD'):\n"
                                             '        with C.call_scope():\n',
                                             'def test_exact_source_chain_worktree_and_committed_ref(clone):\n'
                                             "    assert F.BASE=='b1c08e2d00fe9933565d253d5cee6e5849b143e1'\n"
                                             "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
                                             '    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + '
                                             '(F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, '
                                             "'tests.ci_v4_lean_b2_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), F.BASE_COHORTS + (F.__name__, "
                                             "F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                             "'tests.ci_v5_bootstrap_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                             "'tests.ci_v5_hardening_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                             "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), F.BASE_COHORTS + (F.__name__, "
                                             "F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                             "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                             "'tests.ci_v4_full_recovery_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, "
                                             "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                             "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') "
                                             "+ ('tests.ci_v4_p0_scope',))       # C06 is followed by the reviewed B1, B2, B3, V5 "
                                             'bootstrap, V5-2B and V5-3 successors\n'
                                             '    assert C.COHORT_MODULES.count(F.__name__)==1\n'
                                             "    for ref in (None,'HEAD'):\n"
                                             '        with C.call_scope():\n'),
                                            ('    for path in F.SUPERSEDED:assert '
                                             "data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
                                             '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None;N3=N2._next() '
                                             'if N2 is not None and N2.signature_ok() else None;N4=N3._next() if N3 is not None and '
                                             'N3.signature_ok() else None;N5=N4._next() if N4 is not None and N4.signature_ok() else '
                                             'None;N6=N5._next() if N5 is not None and N5.signature_ok() else None;N7=N6._next() if N6 is '
                                             'not None and N6.signature_ok() else None\n'
                                             '    for path in F.HANDOFFS:\n'
                                             '        later=N7 if N7 is not None and N7.signature_ok() and path in N7.HANDOFFS else N6 if '
                                             'N6 is not None and N6.signature_ok() and path in N6.HANDOFFS else N5 if N5 is not None and '
                                             'N5.signature_ok() and path in N5.HANDOFFS else N4 if N4 is not None and N4.signature_ok() '
                                             'and path in N4.HANDOFFS else N3 if N3 is not None and N3.signature_ok() and path in '
                                             'N3.HANDOFFS else N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N '
                                             'if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in '
                                             'N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'
                                             '        assert (ROOT/path).read_bytes()==later.expected_handoff(ROOT,path)\n'
                                             '    from tests import ci_v5_bootstrap_scope as V5\n',
                                             '    for path in F.SUPERSEDED:assert '
                                             "data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
                                             '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None;N3=N2._next() '
                                             'if N2 is not None and N2.signature_ok() else None;N4=N3._next() if N3 is not None and '
                                             'N3.signature_ok() else None;N5=N4._next() if N4 is not None and N4.signature_ok() else '
                                             'None;N6=N5._next() if N5 is not None and N5.signature_ok() else None;N7=N6._next() if N6 is '
                                             'not None and N6.signature_ok() else None\n'
                                             '    for path in F.HANDOFFS:\n'
                                             '        from tests import ci_v4_p0_scope as P0\n'
                                             '        if P0.signature_ok() and path in P0.HANDOFFS:\n'
                                             '            assert (ROOT / path).read_bytes() == P0.expected_handoff(ROOT, path)\n'
                                             '            assert F._blob((ROOT / path).read_bytes()) == F.effective_pins()[path]\n'
                                             '            continue\n'
                                             '        later=N7 if N7 is not None and N7.signature_ok() and path in N7.HANDOFFS else N6 if '
                                             'N6 is not None and N6.signature_ok() and path in N6.HANDOFFS else N5 if N5 is not None and '
                                             'N5.signature_ok() and path in N5.HANDOFFS else N4 if N4 is not None and N4.signature_ok() '
                                             'and path in N4.HANDOFFS else N3 if N3 is not None and N3.signature_ok() and path in '
                                             'N3.HANDOFFS else N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N '
                                             'if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in '
                                             'N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'
                                             '        assert (ROOT/path).read_bytes()==later.expected_handoff(ROOT,path)\n'
                                             '    from tests import ci_v5_bootstrap_scope as V5\n'),
                                            ('    with C.call_scope():\n'
                                             '        assert not F.signature_ok(clone,F.BASE)\n'
                                             '        for m in C.cohorts():\n'
                                             "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                             "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                             "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'):         # a successor never "
                                             'attests an older accepted ref\n'
                                             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n'
                                             '        assert B.ci_authority_ok(clone,F.BASE)\n'
                                             '        for path in (provider,editor):\n',
                                             '    with C.call_scope():\n'
                                             '        assert not F.signature_ok(clone,F.BASE)\n'
                                             '        for m in C.cohorts():\n'
                                             "            if m.__name__ == 'tests.ci_v4_p0_scope':\n"
                                             '                assert not m.signature_ok(clone, F.BASE)\n'
                                             '                assert not m.exact_blobs_ok(clone, F.BASE)\n'
                                             "            elif m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                             "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                             "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'):         # a successor never "
                                             'attests an older accepted ref\n'
                                             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n'
                                             '        assert B.ci_authority_ok(clone,F.BASE)\n'
                                             '        for path in (provider,editor):\n')],
 'tests/test_ci_v4_full_recovery_scope.py': [('\n'
                                              '\n'
                                              'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                              '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                              '    for p in T.HANDOFFS:\n'
                                              '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                              '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                              '    for p in T.REPLACED:\n'
                                              '        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]\n'
                                              '    for ref in (None, "HEAD"):\n'
                                              '        with C.call_scope():\n'
                                              '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                              'V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                              '\n'
                                              '\n'
                                              'def test_registered_exactly_once_as_the_terminal_cohort_after_the_v5_3_gate():\n'
                                              '    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and '
                                              'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                              '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 1                       # exactly '
                                              'ONE module gained; no hardcoded total\n'
                                              '    assert C.COHORT_MODULES[-2:] == ("tests.ci_v5_gate_scope", '
                                              '"tests.ci_v4_full_recovery_scope")\n'
                                              '    assert H5.SUCCESSOR == T.__name__ and H5._next() is T and H4.SUCCESSOR == H5.__name__ '
                                              'and H4._next() is H5 and V5.SUCCESSOR == H4.__name__ and V5._next() is H4 and B3.SUCCESSOR '
                                              '== V5.__name__ and B3._next() is V5\n'
                                              '    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ '
                                              'and B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1\n'
                                              '\n',
                                              '\n'
                                              '\n'
                                              'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                              '    from tests.fin_v2_cohorts import call_scope\n'
                                              '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                              'mutation\n'
                                              '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                              '        for p in T.HANDOFFS:\n'
                                              '            from tests import ci_v4_p0_scope as P0\n'
                                              '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                              '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                              '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                              '                continue\n'
                                              '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                              '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                              '        for p in T.REPLACED:\n'
                                              '            assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]\n'
                                              '        for ref in (None, "HEAD"):\n'
                                              '            with C.call_scope():\n'
                                              '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                              'V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                              '\n'
                                              '\n'
                                              'def test_registered_exactly_once_as_the_terminal_cohort_after_the_v5_3_gate():\n'
                                              "    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__, 'tests.ci_v4_p0_scope') and "
                                              'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                              '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 2                       # exactly '
                                              'ONE module gained; no hardcoded total\n'
                                              '    assert C.COHORT_MODULES[-3:] == ("tests.ci_v5_gate_scope", '
                                              '"tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")\n'
                                              '    assert H5.SUCCESSOR == T.__name__ and H5._next() is T and H4.SUCCESSOR == H5.__name__ '
                                              'and H4._next() is H5 and V5.SUCCESSOR == H4.__name__ and V5._next() is H4 and B3.SUCCESSOR '
                                              '== V5.__name__ and B3._next() is V5\n'
                                              '    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ '
                                              'and B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1\n'
                                              '\n'),
                                             ('\n'
                                              'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
                                              '    from tests import u1_scope as U\n'
                                              '    assert U.RECONCILED_SUCCESSORS[-1] == "tests.ci_v4_full_recovery_scope" and '
                                              'U.RECONCILED_SUCCESSORS.count("tests.ci_v4_full_recovery_scope") == 1\n'
                                              '\n'
                                              '\n'
                                              '# '
                                              '-------------------------------------------------------------------------------------------------------------- '
                                              'tamper (committed refs)\n',
                                              '\n'
                                              'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
                                              '    from tests import u1_scope as U\n'
                                              '    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v4_full_recovery_scope", '
                                              '"tests.ci_v4_p0_scope") and '
                                              'U.RECONCILED_SUCCESSORS.count("tests.ci_v4_full_recovery_scope") == 1\n'
                                              '\n'
                                              '\n'
                                              '# '
                                              '-------------------------------------------------------------------------------------------------------------- '
                                              'tamper (committed refs)\n'),
                                             ('\n'
                                              '\n'
                                              'def test_registry_mutations_are_rejected(clone):\n'
                                              '    tail = b"\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                              "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                              '\'tests.ci_v4_full_recovery_scope\')"\n'
                                              '    for name, fn in (\n'
                                              '        ("duplicate_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                              "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                              '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_full_recovery_scope\')")),\n'
                                              '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                              '        ("swapped_g6_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                              "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                              '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v5_gate_scope\')")),\n'
                                              '        ("h5_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                              '        ("g6_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                              '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", '
                                              'b"")),\n',
                                              '\n'
                                              '\n'
                                              'def test_registry_mutations_are_rejected(clone):\n'
                                              '    tail = b"\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                              "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                              '\'tests.ci_v4_p0_scope\')"\n'
                                              '    for name, fn in (\n'
                                              '        ("duplicate_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                              "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                              "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_full_recovery_scope', "
                                              '\'tests.ci_v4_p0_scope\')")),\n'
                                              '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                              '        ("swapped_g6_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                              "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                              "'tests.ci_v4_full_recovery_scope', 'tests.ci_v5_gate_scope', "
                                              '\'tests.ci_v4_p0_scope\')")),\n'
                                              '        ("h5_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                              '        ("g6_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                              '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", '
                                              'b"")),\n'),
                                             ('\n'
                                              '\n'
                                              'def test_supersession_is_pin_exact_and_cross_path_safe():\n'
                                              '    pins = T.manifest()["source_blobs"]\n'
                                              '    reg = pins[T.REGISTRY]\n'
                                              '    assert V5.supersedes(T.REGISTRY, reg) and B3.supersedes(T.REGISTRY, reg) and '
                                              'B2.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and '
                                              'P.supersedes(T.REGISTRY, reg)\n'
                                              '    assert not V5.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(T.REGISTRY, "0" * '
                                              '40)\n'
                                              '    assert not V5.supersedes(T.REGISTRY, pins[T.PREDECESSOR])                       # a '
                                              'real blob pinned for another path\n'
                                              '    assert not V5.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])    # the '
                                              'accepted bootstrap-era registry blob is no longer current\n'
                                              '    assert not V5.supersedes("docs/ci_v4/module_weights.json", _git("rev-parse", T.BASE + '
                                              '":docs/ci_v4/module_weights.json"))\n'
                                              '\n'
                                              '\n'
                                              'def test_no_verdict_is_cached_across_refs_or_mutations(clone):\n',
                                              '\n'
                                              '\n'
                                              'def test_supersession_is_pin_exact_and_cross_path_safe():\n'
                                              '    from tests.fin_v2_cohorts import call_scope\n'
                                              '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                              'mutation\n'
                                              '        pins = T.manifest()["source_blobs"]\n'
                                              '        reg = T.effective_pins()[T.REGISTRY]\n'
                                              '        assert reg != pins[T.REGISTRY]\n'
                                              '        assert not V5.supersedes(T.REGISTRY, pins[T.REGISTRY])  # superseded historical pin '
                                              'is not current authority\n'
                                              '        assert V5.supersedes(T.REGISTRY, reg) and B3.supersedes(T.REGISTRY, reg) and '
                                              'B2.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and '
                                              'P.supersedes(T.REGISTRY, reg)\n'
                                              '        assert not V5.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(T.REGISTRY, "0" '
                                              '* 40)\n'
                                              '        assert not V5.supersedes(T.REGISTRY, pins[T.PREDECESSOR])                       # a '
                                              'real blob pinned for another path\n'
                                              '        assert not V5.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])    # '
                                              'the accepted bootstrap-era registry blob is no longer current\n'
                                              '        assert not V5.supersedes("docs/ci_v4/module_weights.json", _git("rev-parse", T.BASE '
                                              '+ ":docs/ci_v4/module_weights.json"))\n'
                                              '\n'
                                              '\n'
                                              'def test_no_verdict_is_cached_across_refs_or_mutations(clone):\n'),
                                             ('\n'
                                              'def '
                                              'test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):\n'
                                              '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY '
                                              'accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer '
                                              'present."""\n'
                                              '    exact = C.COHORT_MODULES\n'
                                              '    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                              '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",\n'
                                              '                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                              '"tests.ci_v4_full_recovery_scope")\n'
                                              '    layers = (K, B1, B2, B3, V5, H4, H5, T)\n'
                                              '    with C.call_scope():\n'
                                              '        assert all(m.signature_ok() for m in layers)\n'
                                              '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]\n'
                                              '    head = exact[:-8]\n'
                                              '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": '
                                              'head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, '
                                              'g6, fr),\n'
                                              '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": '
                                              'head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),\n'
                                              '                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), '
                                              '"fr_duplicated": exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), '
                                              '"fr_dropped": head + (c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + '
                                              '("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, '
                                              'fr),\n'
                                              '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + '
                                              '(c06, b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),\n'
                                              '                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + '
                                              '(c06, b1, b2, b3, v5, g6, fr)}\n'
                                              '    for name, tail in variants.items():\n'
                                              '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                              '        for layer in layers:\n',
                                              '\n'
                                              'def '
                                              'test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):\n'
                                              '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY '
                                              'accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer '
                                              'present."""\n'
                                              '    from tests import ci_v4_p0_scope as P0\n'
                                              '    exact = C.COHORT_MODULES\n'
                                              '    assert exact[-9:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                              '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",\n'
                                              '                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                              '"tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")\n'
                                              '    layers = (K, B1, B2, B3, V5, H4, H5, T, P0)\n'
                                              '    with C.call_scope():\n'
                                              '        assert all(m.signature_ok() for m in layers)\n'
                                              '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-9:-1]\n'
                                              '    head = exact[:-9]\n'
                                              '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": '
                                              'head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, '
                                              'g6, fr),\n'
                                              '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": '
                                              'head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),\n'
                                              '                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), '
                                              '"fr_duplicated": exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), '
                                              '"fr_dropped": head + (c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + '
                                              '("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, '
                                              'fr),\n'
                                              '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + '
                                              '(c06, b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),\n'
                                              '                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + '
                                              '(c06, b1, b2, b3, v5, g6, fr)}\n'
                                              '    variants = {name: value if "tests.ci_v4_p0_scope" in value else value + '
                                              '("tests.ci_v4_p0_scope",)\n'
                                              '                for name, value in variants.items()}\n'
                                              '    variants.update(p0_dropped=exact[:-1], p0_duplicate=exact + ("tests.ci_v4_p0_scope",),\n'
                                              '                    p0_fr_swapped=exact[:-2] + ("tests.ci_v4_p0_scope", '
                                              '"tests.ci_v4_full_recovery_scope"))\n'
                                              '    for name, tail in variants.items():\n'
                                              '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                              '        for layer in layers:\n')],
 'tests/test_ci_v4_lean_b1_scope.py': [('\n'
                                        '\n'
                                        'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                        '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                        '    N = T._next()\n'
                                        '    N2 = N._next() if N is not None and N.signature_ok() else None\n'
                                        '    N3 = N2._next() if N2 is not None and N2.signature_ok() else None\n'
                                        '    N4 = N3._next() if N3 is not None and N3.signature_ok() else None\n'
                                        '    N5 = N4._next() if N4 is not None and N4.signature_ok() else None\n'
                                        '    N6 = N5._next() if N5 is not None and N5.signature_ok() else None\n'
                                        '    for p in T.HANDOFFS:\n'
                                        '        if N6 is not None and N6.signature_ok() and p in N6.HANDOFFS:      # the further reviewed '
                                        'FULL-recovery substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N6.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '            continue\n'
                                        '        if N5 is not None and N5.signature_ok() and p in N5.HANDOFFS:      # the further reviewed '
                                        'V5-3 substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N5.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '            continue\n'
                                        '        if N4 is not None and N4.signature_ok() and p in N4.HANDOFFS:      # the further reviewed '
                                        'V5-2B substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N4.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '            continue\n'
                                        '        if N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the further reviewed '
                                        'V5 bootstrap substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '            continue\n'
                                        '        if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and '
                                        'N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this '
                                        'shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '            continue\n'
                                        '        if N is not None and N.signature_ok() and p in N.HANDOFFS:                  # the further '
                                        'reviewed B2 substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '            continue\n'
                                        '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                        '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '    for ref in (None, "HEAD"):\n'
                                        '        with C.call_scope():\n'
                                        '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                        'K.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                        '\n'
                                        '\n'
                                        'def test_registered_exactly_once_as_the_terminal_cohort_after_c06():\n',
                                        '\n'
                                        '\n'
                                        'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                        '    from tests.fin_v2_cohorts import call_scope\n'
                                        '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                        'mutation\n'
                                        '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                        '        N = T._next()\n'
                                        '        N2 = N._next() if N is not None and N.signature_ok() else None\n'
                                        '        N3 = N2._next() if N2 is not None and N2.signature_ok() else None\n'
                                        '        N4 = N3._next() if N3 is not None and N3.signature_ok() else None\n'
                                        '        N5 = N4._next() if N4 is not None and N4.signature_ok() else None\n'
                                        '        N6 = N5._next() if N5 is not None and N5.signature_ok() else None\n'
                                        '        for p in T.HANDOFFS:\n'
                                        '            from tests import ci_v4_p0_scope as P0\n'
                                        '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                        '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N6 is not None and N6.signature_ok() and p in N6.HANDOFFS:      # the further '
                                        'reviewed FULL-recovery substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N6.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N5 is not None and N5.signature_ok() and p in N5.HANDOFFS:      # the further '
                                        'reviewed V5-3 substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N5.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N4 is not None and N4.signature_ok() and p in N4.HANDOFFS:      # the further '
                                        'reviewed V5-2B substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N4.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the further '
                                        'reviewed V5 bootstrap substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and '
                                        'N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this '
                                        'shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N is not None and N.signature_ok() and p in N.HANDOFFS:                  # the '
                                        'further reviewed B2 substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '        for ref in (None, "HEAD"):\n'
                                        '            with C.call_scope():\n'
                                        '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                        'K.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                        '\n'
                                        '\n'
                                        'def test_registered_exactly_once_as_the_terminal_cohort_after_c06():\n'),
                                       ('                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope"),\n'
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"),\n'
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"),\n'
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")) and '
                                        'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                        '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == '
                                        '"tests.c06_cost_workspace_scope"\n'
                                        '    assert K.SUCCESSOR == T.__name__ and K._next() is T\n'
                                        '\n',
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope"),\n'
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"),\n'
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"),\n'
                                        '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), T.BASE_COHORTS + (T.__name__, '
                                        'T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") + '
                                        "('tests.ci_v4_p0_scope',)) and C.COHORT_MODULES.count(T.__name__) == 1\n"
                                        '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == '
                                        '"tests.c06_cost_workspace_scope"\n'
                                        '    assert K.SUCCESSOR == T.__name__ and K._next() is T\n'
                                        '\n'),
                                       ('\n'
                                        'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
                                        '    from tests import u1_scope as U\n'
                                        '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-8:] if m not in '
                                        '("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")) == '
                                        '("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
                                        '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1\n'
                                        '\n'
                                        '\n',
                                        '\n'
                                        'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
                                        '    from tests import u1_scope as U\n'
                                        '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-9:] if m not in '
                                        '("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")) == '
                                        '("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
                                        '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1\n'
                                        '\n'
                                        '\n'),
                                       ('\n'
                                        '\n'
                                        'def test_registry_mutations_are_rejected(clone):\n'
                                        '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        '\'tests.ci_v4_full_recovery_scope\')"\n'
                                        '    for name, fn in (\n'
                                        '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', '
                                        "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b2_scope', "
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')")),\n'
                                        '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                        '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', '
                                        "'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        '\'tests.ci_v4_full_recovery_scope\')")),\n'
                                        '        ("b1_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b1_scope\'", b"")),\n'
                                        '        ("c06_missing", lambda b: b.replace(b"\'tests.c06_cost_workspace_scope\', ", b"")),\n'
                                        '        ("r04_removed", lambda b: b.replace(b"\'tests.r04_ppa_scope\', ", b"")),\n',
                                        '\n'
                                        '\n'
                                        'def test_registry_mutations_are_rejected(clone):\n'
                                        '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                        '\'tests.ci_v4_p0_scope\')"\n'
                                        '    for name, fn in (\n'
                                        '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', '
                                        "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b2_scope', "
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                        '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                        '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', '
                                        "'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                        '        ("b1_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b1_scope\'", b"")),\n'
                                        '        ("c06_missing", lambda b: b.replace(b"\'tests.c06_cost_workspace_scope\', ", b"")),\n'
                                        '        ("r04_removed", lambda b: b.replace(b"\'tests.r04_ppa_scope\', ", b"")),\n')],
 'tests/test_ci_v4_lean_b2_scope.py': [('\n'
                                        '\n'
                                        'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                        '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                        '    T3 = T._next()\n'
                                        '    T4 = T3._next() if T3 is not None and T3.signature_ok() else None\n'
                                        '    T5 = T4._next() if T4 is not None and T4.signature_ok() else None\n'
                                        '    T6 = T5._next() if T5 is not None and T5.signature_ok() else None\n'
                                        '    T7 = T6._next() if T6 is not None and T6.signature_ok() else None\n'
                                        '    for p in T.HANDOFFS:\n'
                                        '        if T7 is not None and T7.signature_ok() and p in T7.HANDOFFS:      # the reviewed '
                                        'FULL-recovery substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == T7.expected_handoff(ROOT, p)\n'
                                        '        elif T6 is not None and T6.signature_ok() and p in T6.HANDOFFS:      # the reviewed V5-3 '
                                        'substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == T6.expected_handoff(ROOT, p)\n'
                                        '        elif T5 is not None and T5.signature_ok() and p in T5.HANDOFFS:      # the reviewed V5-2B '
                                        'substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == T5.expected_handoff(ROOT, p)\n'
                                        '        elif T4 is not None and T4.signature_ok() and p in T4.HANDOFFS:      # the reviewed V5 '
                                        'bootstrap substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == T4.expected_handoff(ROOT, p)\n'
                                        '        elif T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p in '
                                        'T3.HANDOFFS:      # the reviewed B3 substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)\n'
                                        '        else:\n'
                                        '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                        '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '    for ref in (None, "HEAD"):\n'
                                        '        with C.call_scope():\n'
                                        '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                        'B.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                        '\n'
                                        '\n'
                                        'def test_registered_exactly_once_as_the_terminal_cohort_after_b1():\n'
                                        '    assert C.COHORT_MODULES.count(T.__name__) == 1\n'
                                        '    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", '
                                        '"tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", '
                                        '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b2_scope", '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", '
                                        '"tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"), ("tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), ("tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"))\n'
                                        '    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B\n'
                                        '    from tests import ci_v4_lean_b3_scope as T3\n'
                                        '    if T.SUCCESSOR in C.COHORT_MODULES:\n'
                                        '        assert C.COHORT_MODULES[-1] in (T.SUCCESSOR, "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") and '
                                        'T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"\n'
                                        '\n'
                                        '\n'
                                        'def test_b1_c06_and_every_older_cohort_still_follow_the_chain():\n',
                                        '\n'
                                        '\n'
                                        'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                        '    from tests.fin_v2_cohorts import call_scope\n'
                                        '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                        'mutation\n'
                                        '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                        '        T3 = T._next()\n'
                                        '        T4 = T3._next() if T3 is not None and T3.signature_ok() else None\n'
                                        '        T5 = T4._next() if T4 is not None and T4.signature_ok() else None\n'
                                        '        T6 = T5._next() if T5 is not None and T5.signature_ok() else None\n'
                                        '        T7 = T6._next() if T6 is not None and T6.signature_ok() else None\n'
                                        '        for p in T.HANDOFFS:\n'
                                        '            from tests import ci_v4_p0_scope as P0\n'
                                        '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                        '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if T7 is not None and T7.signature_ok() and p in T7.HANDOFFS:      # the reviewed '
                                        'FULL-recovery substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == T7.expected_handoff(ROOT, p)\n'
                                        '            elif T6 is not None and T6.signature_ok() and p in T6.HANDOFFS:      # the reviewed '
                                        'V5-3 substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == T6.expected_handoff(ROOT, p)\n'
                                        '            elif T5 is not None and T5.signature_ok() and p in T5.HANDOFFS:      # the reviewed '
                                        'V5-2B substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == T5.expected_handoff(ROOT, p)\n'
                                        '            elif T4 is not None and T4.signature_ok() and p in T4.HANDOFFS:      # the reviewed '
                                        'V5 bootstrap substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == T4.expected_handoff(ROOT, p)\n'
                                        '            elif T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p '
                                        'in T3.HANDOFFS:      # the reviewed B3 substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)\n'
                                        '            else:\n'
                                        '                assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '        for ref in (None, "HEAD"):\n'
                                        '            with C.call_scope():\n'
                                        '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                        'B.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                        '\n'
                                        '\n'
                                        'def test_registered_exactly_once_as_the_terminal_cohort_after_b1():\n'
                                        '    assert C.COHORT_MODULES.count(T.__name__) == 1\n'
                                        '    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", '
                                        '"tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", '
                                        '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b2_scope", '
                                        '"tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", '
                                        '"tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"), ("tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), ("tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), (\'tests.ci_v5_gate_scope\', '
                                        "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope'))\n"
                                        '    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B\n'
                                        '    from tests import ci_v4_lean_b3_scope as T3\n'
                                        '    if T.SUCCESSOR in C.COHORT_MODULES:\n'
                                        '        assert C.COHORT_MODULES[-1] in (T.SUCCESSOR, "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", '
                                        '\'tests.ci_v4_p0_scope\') and T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"\n'
                                        '\n'
                                        '\n'
                                        'def test_b1_c06_and_every_older_cohort_still_follow_the_chain():\n'),
                                       ('\n'
                                        'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
                                        '    from tests import u1_scope as U\n'
                                        '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", '
                                        '"tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), '
                                        '("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope"), ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), '
                                        '("tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"))\n'
                                        '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1\n'
                                        '\n'
                                        '\n',
                                        '\n'
                                        'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
                                        '    from tests import u1_scope as U\n'
                                        '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", '
                                        '"tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), '
                                        '("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope"), ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), '
                                        '("tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), '
                                        '("tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope"))\n'
                                        '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1\n'
                                        '\n'
                                        '\n'),
                                       ('\n'
                                        '\n'
                                        'def test_registry_mutations_are_rejected(clone):\n'
                                        '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', '
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')"\n'
                                        '    for name, fn in (\n'
                                        '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        '\'tests.ci_v4_full_recovery_scope\')")),\n'
                                        '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                        '        ("swapped_b1_b2", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', '
                                        '\'tests.ci_v4_lean_b1_scope\')")),\n'
                                        '        ("b2_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b2_scope\'", b"")),\n',
                                        '\n'
                                        '\n'
                                        'def test_registry_mutations_are_rejected(clone):\n'
                                        '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', '
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')"\n'
                                        '    for name, fn in (\n'
                                        '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                        '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                        '        ("swapped_b1_b2", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', '
                                        '\'tests.ci_v4_lean_b1_scope\')")),\n'
                                        '        ("b2_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b2_scope\'", b"")),\n')],
 'tests/test_ci_v4_lean_b3_scope.py': [('\n'
                                        '\n'
                                        'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                        '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                        '    N = T._next()\n'
                                        '    N2 = N._next() if N is not None and N.signature_ok() else None\n'
                                        '    N3 = N2._next() if N2 is not None and N2.signature_ok() else None\n'
                                        '    N4 = N3._next() if N3 is not None and N3.signature_ok() else None\n'
                                        '    for p in T.HANDOFFS:\n'
                                        '        if N4 is not None and N4.signature_ok() and p in N4.HANDOFFS:      # the reviewed '
                                        'FULL-recovery substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N4.expected_handoff(ROOT, p)\n'
                                        '        elif N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the reviewed V5-3 '
                                        'substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)\n'
                                        '        elif N2 is not None and N2.signature_ok() and p in N2.HANDOFFS:      # the reviewed V5-2B '
                                        'substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
                                        '        elif N is not None and N.signature_ok() and p in N.HANDOFFS:      # the reviewed V5 '
                                        'bootstrap substitution of this shared path\n'
                                        '            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
                                        '        else:\n'
                                        '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                        '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '    for ref in (None, "HEAD"):\n'
                                        '        with C.call_scope():\n'
                                        '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                        'B.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                        '\n'
                                        '\n'
                                        'def test_registered_exactly_once_after_b2_with_only_the_reviewed_v5_bootstrap_behind_it():\n'
                                        '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                        "T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v5_hardening_scope'), "
                                        "T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v5_hardening_scope', "
                                        "'tests.ci_v5_gate_scope'), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')) and "
                                        'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                        '    assert C.COHORT_MODULES[-3:] in (("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", '
                                        '"tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope"), ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                        '"tests.ci_v4_full_recovery_scope"))\n'
                                        '    assert B.SUCCESSOR == T.__name__ and B._next() is T and B1.SUCCESSOR == B.__name__ and '
                                        'B1._next() is B\n'
                                        '\n'
                                        '\n',
                                        '\n'
                                        '\n'
                                        'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                        '    from tests.fin_v2_cohorts import call_scope\n'
                                        '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                        'mutation\n'
                                        '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                        '        N = T._next()\n'
                                        '        N2 = N._next() if N is not None and N.signature_ok() else None\n'
                                        '        N3 = N2._next() if N2 is not None and N2.signature_ok() else None\n'
                                        '        N4 = N3._next() if N3 is not None and N3.signature_ok() else None\n'
                                        '        for p in T.HANDOFFS:\n'
                                        '            from tests import ci_v4_p0_scope as P0\n'
                                        '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                        '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                        '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '                continue\n'
                                        '            if N4 is not None and N4.signature_ok() and p in N4.HANDOFFS:      # the reviewed '
                                        'FULL-recovery substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N4.expected_handoff(ROOT, p)\n'
                                        '            elif N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the reviewed '
                                        'V5-3 substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)\n'
                                        '            elif N2 is not None and N2.signature_ok() and p in N2.HANDOFFS:      # the reviewed '
                                        'V5-2B substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
                                        '            elif N is not None and N.signature_ok() and p in N.HANDOFFS:      # the reviewed V5 '
                                        'bootstrap substitution of this shared path\n'
                                        '                assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
                                        '            else:\n'
                                        '                assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                        '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                        '        for ref in (None, "HEAD"):\n'
                                        '            with C.call_scope():\n'
                                        '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                        'B.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                        '\n'
                                        '\n'
                                        'def test_registered_exactly_once_after_b2_with_only_the_reviewed_v5_bootstrap_behind_it():\n'
                                        '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                        "T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v5_hardening_scope'), "
                                        "T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v5_hardening_scope', "
                                        "'tests.ci_v5_gate_scope'), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                        "T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v5_hardening_scope', "
                                        "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)) and "
                                        'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                        '    assert C.COHORT_MODULES[-3:] in (("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", '
                                        '"tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", '
                                        '"tests.ci_v5_gate_scope"), ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                        '"tests.ci_v4_full_recovery_scope"), (\'tests.ci_v5_gate_scope\', '
                                        "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope'))\n"
                                        '    assert B.SUCCESSOR == T.__name__ and B._next() is T and B1.SUCCESSOR == B.__name__ and '
                                        'B1._next() is B\n'
                                        '\n'
                                        '\n'),
                                       ('\n'
                                        'def '
                                        'test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_bootstrap():\n'
                                        '    from tests import u1_scope as U\n'
                                        '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b3_scope", '
                                        '"tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"), '
                                        '("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), ("tests.ci_v5_gate_scope", '
                                        '"tests.ci_v4_full_recovery_scope"))\n'
                                        '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b3_scope") == 1\n'
                                        '\n'
                                        '\n',
                                        '\n'
                                        'def '
                                        'test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_bootstrap():\n'
                                        '    from tests import u1_scope as U\n'
                                        '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b3_scope", '
                                        '"tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"), '
                                        '("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), ("tests.ci_v5_gate_scope", '
                                        '"tests.ci_v4_full_recovery_scope"), ("tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope"))\n'
                                        '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b3_scope") == 1\n'
                                        '\n'
                                        '\n'),
                                       ('    from tests import ci_v5_hardening_scope as H\n'
                                        '    from tests import ci_v5_gate_scope as G\n'
                                        '    from tests import ci_v4_full_recovery_scope as FR\n'
                                        '    exact = C.COHORT_MODULES\n'
                                        '    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                        '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")\n'
                                        '    layers = (K, B1, B, T, V, H, G, FR)\n'
                                        '    with C.call_scope():\n'
                                        '        assert all(m.signature_ok() for m in layers)                       # state A: the '
                                        'pristine registry is accepted by every layer\n'
                                        '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]\n'
                                        '    head = exact[:-8]\n'
                                        '    variants = {\n'
                                        '        "b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr),\n'
                                        '        "b1_b2_swapped": head + (c06, b2, b1, b3, v5, h5, g6, fr),\n',
                                        '    from tests import ci_v5_hardening_scope as H\n'
                                        '    from tests import ci_v5_gate_scope as G\n'
                                        '    from tests import ci_v4_full_recovery_scope as FR\n'
                                        '    from tests import ci_v4_p0_scope as P0\n'
                                        '    exact = C.COHORT_MODULES\n'
                                        '    assert exact[-9:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                        '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                        '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", '
                                        '"tests.ci_v4_p0_scope")\n'
                                        '    layers = (K, B1, B, T, V, H, G, FR, P0)\n'
                                        '    with C.call_scope():\n'
                                        '        assert all(m.signature_ok() for m in layers)                       # state A: the '
                                        'pristine registry is accepted by every layer\n'
                                        '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-9:-1]\n'
                                        '    head = exact[:-9]\n'
                                        '    variants = {\n'
                                        '        "b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr),\n'
                                        '        "b1_b2_swapped": head + (c06, b2, b1, b3, v5, h5, g6, fr),\n'),
                                       ('        "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr),\n'
                                        '        "h5_dropped": head + (c06, b1, b2, b3, v5, g6, fr),\n'
                                        '    }\n'
                                        '    for name, tail in variants.items():\n'
                                        '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                        '        for layer in layers:\n',
                                        '        "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr),\n'
                                        '        "h5_dropped": head + (c06, b1, b2, b3, v5, g6, fr),\n'
                                        '    }\n'
                                        '    variants = {name: value if "tests.ci_v4_p0_scope" in value else value + '
                                        '("tests.ci_v4_p0_scope",)\n'
                                        '                for name, value in variants.items()}\n'
                                        '    variants.update(p0_dropped=exact[:-1], p0_duplicate=exact + ("tests.ci_v4_p0_scope",),\n'
                                        '                    p0_fr_swapped=exact[:-2] + ("tests.ci_v4_p0_scope", '
                                        '"tests.ci_v4_full_recovery_scope"))\n'
                                        '    for name, tail in variants.items():\n'
                                        '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                        '        for layer in layers:\n')],
 'tests/test_ci_v4_lean_tamper_matrix.py': [('\n'
                                             '\n'
                                             'REG = "tests/fin_v2_cohorts.py"\n'
                                             'TAIL = "\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                             "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                             '\'tests.ci_v4_full_recovery_scope\')"\n'
                                             '# row id, invariant class, mutation, injected path, attribution class\n'
                                             'ROWS = [\n'
                                             '    ("guarded_byte_product", "guarded_byte", _append("app/v2/router.py"), '
                                             '"app/v2/router.py", "pinned"),\n',
                                             '\n'
                                             '\n'
                                             'REG = "tests/fin_v2_cohorts.py"\n'
                                             'TAIL = "\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                             "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                             '\'tests.ci_v4_p0_scope\')"\n'
                                             '# row id, invariant class, mutation, injected path, attribution class\n'
                                             'ROWS = [\n'
                                             '    ("guarded_byte_product", "guarded_byte", _append("app/v2/router.py"), '
                                             '"app/v2/router.py", "pinned"),\n'),
                                            ('    ("registry_parent_forged", "registry", lambda clone: _text_sub(REG, re.search(r"PARENT = '
                                             '\'[0-9a-f]+\'", (clone / REG).read_text()).group(0),\n'
                                             '                                                                    "PARENT = \'%s\'" % '
                                             'HEAD_OF[str(clone)])(clone), REG, "pinned"),\n'
                                             '    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, '
                                             'B1.PREDECESSOR, "pinned"),\n'
                                             '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", '
                                             '\'tests.ci_v4_full_recovery_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'
                                             '    ("current_map_key_forged", "current_map", _forge_map_key, '
                                             '"docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),\n'
                                             ']\n'
                                             'assert len({r[0] for r in ROWS}) == len(ROWS)\n',
                                             '    ("registry_parent_forged", "registry", lambda clone: _text_sub(REG, re.search(r"PARENT = '
                                             '\'[0-9a-f]+\'", (clone / REG).read_text()).group(0),\n'
                                             '                                                                    "PARENT = \'%s\'" % '
                                             'HEAD_OF[str(clone)])(clone), REG, "pinned"),\n'
                                             '    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, '
                                             'B1.PREDECESSOR, "pinned"),\n'
                                             '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", '
                                             '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')", ")"), "tests/u1_scope.py", '
                                             '"pinned"),\n'
                                             '    ("current_map_key_forged", "current_map", _forge_map_key, '
                                             '"docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),\n'
                                             ']\n'
                                             'assert len({r[0] for r in ROWS}) == len(ROWS)\n')],
 'tests/test_ci_v4_perf_scope.py': [('    return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL)\n'
                                     '\n'
                                     '\n'
                                     'def test_the_performance_leaf_is_exact_registered_and_the_composite_holds():\n'
                                     '    assert "tests.ci_v4_perf_scope" in C.COHORT_MODULES\n'
                                     '    # the leaf stays in its exact place; the only reviewed forward successor is F03, behind its own '
                                     'complete signature\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    with C.call_scope():\n'
                                     '        assert (C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope" or (\n'
                                     '            C.COHORT_MODULES[-2:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope") and '
                                     'G.signature_ok()) or (\n'
                                     '            C.COHORT_MODULES[-3:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope")\n'
                                     '            and G.signature_ok() and Z.signature_ok()) or (\n'
                                     '            C.COHORT_MODULES[-4:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope")\n'
                                     '            and G.signature_ok() and Z.signature_ok() and Y.signature_ok()) or (\n'
                                     '            C.COHORT_MODULES[-5:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope")\n'
                                     '            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok()) or '
                                     '(\n'
                                     '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                     '"tests.r04_ppa_scope")\n'
                                     '            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and '
                                     'W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), '
                                     'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), '
                                     'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), "
                                     'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                     "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                     '                and C06_APPROVAL.signature_ok())\n'
                                     '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.signature_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert C.valid() is True\n'
                                     '\n'
                                     '\n'
                                     'def test_every_handoff_file_equals_its_reviewed_literal_substitution():\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (_b7().expected_handoff(ROOT, p) if _b7() is not None and p in _b7().HANDOFFS\n'
                                     '                else _b6().expected_handoff(ROOT, p) if _b6() is not None and p in _b6().HANDOFFS\n'
                                     '                else _b5().expected_handoff(ROOT, p) if _b5() is not None and p in _b5().HANDOFFS\n'
                                     '                else _b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n',
                                     '    return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL)\n'
                                     '\n'
                                     '\n'
                                     'def _literal_registry(raw):\n'
                                     '    return next(ast.literal_eval(n.value) for n in ast.parse(raw).body\n'
                                     '                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '
                                     '"COHORT_MODULES" for t in n.targets))\n'
                                     '\n'
                                     '\n'
                                     'def _accepted_p0_prefix():\n'
                                     '    # Independently recover the entire immutable 47-cohort main registry, starting at the original '
                                     'BESS02 registry.\n'
                                     '    accepted = _literal_registry(_git("show", F.BASE + ":tests/fin_v2_cohorts.py"))\n'
                                     '    assert accepted[-1] == "tests.bess02_scope"\n'
                                     '    prefix = accepted + (\n'
                                     '        "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope",\n'
                                     '        "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope",\n'
                                     '        "tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope",\n'
                                     '        "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope",\n'
                                     '        "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")\n'
                                     '    assert len(prefix) == 47\n'
                                     '    assert _literal_registry(_git("show", '
                                     '"955952c1bc16b21ce342121c5224a19d3e105aa7:tests/fin_v2_cohorts.py")) == prefix\n'
                                     '    return prefix\n'
                                     '\n'
                                     '\n'
                                     'def _p0():\n'
                                     '    """Only the literal registered P0 terminal, through the exact FULL-recovery chain and every '
                                     'predecessor."""\n'
                                     '    prefix = _accepted_p0_prefix()\n'
                                     '    if C.COHORT_MODULES != prefix + ("tests.ci_v4_p0_scope",):\n'
                                     '        return None\n'
                                     '    prior = _b7()\n'
                                     '    terminal = prior._next() if prior is not None else None\n'
                                     '    if (terminal is None or terminal.__name__ != "tests.ci_v4_p0_scope"\n'
                                     '            or terminal.BASE != "955952c1bc16b21ce342121c5224a19d3e105aa7"\n'
                                     '            or terminal.BASE_COHORTS != prefix or not terminal.signature_ok()\n'
                                     '            or not all(m.exact_blobs_ok() for m in C.cohorts())):\n'
                                     '        return None\n'
                                     '    return terminal\n'
                                     '\n'
                                     '\n'
                                     'def _historical_reviewed_handoff(p):\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    return (_b7().expected_handoff(ROOT, p) if _b7() is not None and p in _b7().HANDOFFS\n'
                                     '                else _b6().expected_handoff(ROOT, p) if _b6() is not None and p in _b6().HANDOFFS\n'
                                     '                else _b5().expected_handoff(ROOT, p) if _b5() is not None and p in _b5().HANDOFFS\n'
                                     '                else _b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n'),
                                    ('                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '        assert (ROOT / p).read_bytes() == want, p\n'
                                     '\n'
                                     '\n'
                                     'def test_the_accepted_bess02_leaf_stays_exact_through_the_forward_handoff():\n'
                                     '    with C.call_scope():\n'
                                     '        assert B.signature_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert B.reviewed_edits_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert B.exact_blobs_ok() is True\n'
                                     '    assert B._next() is F\n'
                                     "    # the BESS02 closure now covers exactly its own paths plus this leaf's\n"
                                     '    assert B.closure_paths() == B.OWNED_PATHS | {B.MANIFEST} | F.closure_paths()\n'
                                     '    assert "docs/ci_v4/module_weights.json" in B.closure_paths()\n'
                                     '\n'
                                     '\n'
                                     'def test_the_registry_appends_exactly_one_reviewed_cohort_after_the_accepted_tail():\n'
                                     '    registry = _git("show", F.BASE + ":tests/fin_v2_cohorts.py")\n'
                                     '    accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body\n'
                                     '                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)\n'
                                     '                    and n.targets[0].id == "COHORT_MODULES")\n'
                                     '    assert accepted[-1] == "tests.bess02_scope"  # the accepted BESS02 tail is intact\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    own = accepted + ("tests.ci_v4_perf_scope",)\n'
                                     '    with C.call_scope():\n'
                                     '        assert ((C.COHORT_MODULES == own or (C.COHORT_MODULES == own + '
                                     '("tests.f03_financing_scope",) and G.signature_ok())\n'
                                     '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope")\n'
                                     '                    and G.signature_ok() and Z.signature_ok())\n'
                                     '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope")\n'
                                     '                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok())\n'
                                     '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope")\n'
                                     '                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok())\n'
                                     '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                     '"tests.r04_ppa_scope")\n'
                                     '                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                     '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                     'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), "
                                     'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                     "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                     '                and C06_APPROVAL.signature_ok()))\n'
                                     '    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1\n'
                                     '\n'
                                     '\n'
                                     'def test_the_accepted_bess02_handoff_expectations_are_still_governed_by_this_leaf():\n'
                                     "    # the BESS02-era literal for the registry is superseded ONLY by this leaf's own reviewed\n"
                                     '    # substitution; the other BESS02 handoff files it does not take over still hold literally.\n'
                                     '    for p in sorted(set(B.HANDOFFS) - set(F.HANDOFFS)):\n'
                                     '        assert (ROOT / p).read_bytes() == B.expected_handoff(ROOT, p), p\n'
                                     '    assert "tests/fin_v2_cohorts.py" in F.HANDOFFS and "tests/fin_v2_cohorts.py" in B.HANDOFFS\n'
                                     '\n'
                                     '\n'
                                     '#: exactly the three pins a current map may carry for this leaf: the registry, the module weights '
                                     'and the PR3b1 guard whose\n',
                                     '                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '\n'
                                     '\n'
                                     'def _reviewed_handoff(p):\n'
                                     '    historical = _historical_reviewed_handoff(p)\n'
                                     '    terminal = _p0()\n'
                                     '    if terminal is None or p not in terminal.HANDOFFS:\n'
                                     '        return historical\n'
                                     '    predecessor = _git("show", terminal.BASE + ":" + p)\n'
                                     '    pins = terminal.manifest()\n'
                                     '    assert historical == predecessor                         # the older literal remains the '
                                     'authenticated intermediate\n'
                                     '    assert F._blob(predecessor) == pins["base_blobs"][p]\n'
                                     '    reviewed = terminal.expected_handoff(ROOT, p)             # immutable BASE plus reviewed '
                                     'literals; never disk as expectation\n'
                                     '    assert reviewed != predecessor\n'
                                     '    assert F._blob(reviewed) == pins["source_blobs"][p] == F.effective_pins()[p]\n'
                                     '    return reviewed\n'
                                     '\n'
                                     '\n'
                                     'def test_the_performance_leaf_is_exact_registered_and_the_composite_holds():\n'
                                     '    from tests.fin_v2_cohorts import call_scope\n'
                                     '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                     '        assert "tests.ci_v4_perf_scope" in C.COHORT_MODULES\n'
                                     '        # the leaf stays in its exact place; the only reviewed forward successor is F03, behind its '
                                     'own complete signature\n'
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        with C.call_scope():\n'
                                     '            assert (_p0() is not None or ((C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope" or (\n'
                                     '                C.COHORT_MODULES[-2:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope") and '
                                     'G.signature_ok()) or (\n'
                                     '                C.COHORT_MODULES[-3:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope")\n'
                                     '                and G.signature_ok() and Z.signature_ok()) or (\n'
                                     '                C.COHORT_MODULES[-4:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope")\n'
                                     '                and G.signature_ok() and Z.signature_ok() and Y.signature_ok()) or (\n'
                                     '                C.COHORT_MODULES[-5:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope")\n'
                                     '                and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok()) '
                                     'or (\n'
                                     '                C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                     '"tests.r04_ppa_scope")\n'
                                     '                and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() '
                                     'and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                     '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                     'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), "
                                     'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                     "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                     '                    and C06_APPROVAL.signature_ok())))\n'
                                     '        assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.exact_blobs_ok() is True\n'
                                     '            assert F.signature_ok() is True\n'
                                     '            assert C.valid() is True\n'
                                     '\n'
                                     '\n'
                                     'def test_every_handoff_file_equals_its_reviewed_literal_substitution():\n'
                                     '    from tests.fin_v2_cohorts import call_scope\n'
                                     '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        for p in sorted(F.HANDOFFS):\n'
                                     '            want = (_reviewed_handoff(p))\n'
                                     '            assert (ROOT / p).read_bytes() == want, p\n'
                                     '\n'
                                     '\n'
                                     'def test_the_accepted_bess02_leaf_stays_exact_through_the_forward_handoff():\n'
                                     '    with C.call_scope():  # this complete enumeration only reads source; no fixture or mutation is '
                                     'inside\n'
                                     '        with C.call_scope():\n'
                                     '            assert B.signature_ok() is True\n'
                                     '            assert B.reviewed_edits_ok() is True\n'
                                     '            assert B.exact_blobs_ok() is True\n'
                                     '        assert B._next() is F\n'
                                     "        # the BESS02 closure now covers exactly its own paths plus this leaf's\n"
                                     '        assert B.closure_paths() == B.OWNED_PATHS | {B.MANIFEST} | F.closure_paths()\n'
                                     '        assert "docs/ci_v4/module_weights.json" in B.closure_paths()\n'
                                     '\n'
                                     '\n'
                                     'def test_the_registry_appends_exactly_one_reviewed_cohort_after_the_accepted_tail():\n'
                                     '    from tests.fin_v2_cohorts import call_scope\n'
                                     '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                     '        registry = _git("show", F.BASE + ":tests/fin_v2_cohorts.py")\n'
                                     '        accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body\n'
                                     '                        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)\n'
                                     '                        and n.targets[0].id == "COHORT_MODULES")\n'
                                     '        assert accepted[-1] == "tests.bess02_scope"  # the accepted BESS02 tail is intact\n'
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        own = accepted + ("tests.ci_v4_perf_scope",)\n'
                                     '        with C.call_scope():\n'
                                     '            assert ((_p0() is not None or ((C.COHORT_MODULES == own or (C.COHORT_MODULES == own + '
                                     '("tests.f03_financing_scope",) and G.signature_ok())\n'
                                     '                    or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope")\n'
                                     '                        and G.signature_ok() and Z.signature_ok())\n'
                                     '                    or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope")\n'
                                     '                        and G.signature_ok() and Z.signature_ok() and Y.signature_ok())\n'
                                     '                    or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope")\n'
                                     '                        and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok())\n'
                                     '                    or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                     '"tests.r04_ppa_scope")\n'
                                     '                        and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                     '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                     'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), "
                                     'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                     "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                     "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + "
                                     "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                     "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                     "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                     '                    and C06_APPROVAL.signature_ok()))))\n'
                                     '        assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1\n'
                                     '\n'
                                     '\n'
                                     'def test_the_accepted_bess02_handoff_expectations_are_still_governed_by_this_leaf():\n'
                                     '    with C.call_scope():  # this complete enumeration only reads source; no fixture or mutation is '
                                     'inside\n'
                                     "        # the BESS02-era literal for the registry is superseded ONLY by this leaf's own reviewed\n"
                                     '        # substitution; the other BESS02 handoff files it does not take over still hold literally.\n'
                                     '        for p in sorted(set(B.HANDOFFS) - set(F.HANDOFFS)):\n'
                                     '            assert (ROOT / p).read_bytes() == B.expected_handoff(ROOT, p), p\n'
                                     '        assert "tests/fin_v2_cohorts.py" in F.HANDOFFS and "tests/fin_v2_cohorts.py" in B.HANDOFFS\n'
                                     '\n'
                                     '\n'
                                     '#: exactly the three pins a current map may carry for this leaf: the registry, the module weights '
                                     'and the PR3b1 guard whose\n'),
                                    ('\n'
                                     '\n'
                                     'def test_the_current_maps_manifests_carry_exactly_the_reviewed_moved_pins_in_canonical_form():\n'
                                     '    assert tuple(sorted(F.MAP_KEYS)) == MOVED_MAP_KEYS\n'
                                     '    nx = B._next_pins(ROOT, None)\n'
                                     '    pins = B.manifest()["source_blobs"]\n'
                                     '    cur = {p: nx.get(p, b) for p, b in pins.items()}\n'
                                     '    moved = B._next_moved(ROOT, None)\n'
                                     '    # independently derived NEW value (hash of the bytes on disk) and OLD value (accepted BASE), '
                                     "never read from the leaf's own map logic\n"
                                     '    new = {k: F._blob((ROOT / k).read_bytes()) for k in MOVED_MAP_KEYS}\n'
                                     '    old = {k: F._blob(_git("show", F.BASE + ":" + k)) for k in MOVED_MAP_KEYS}\n'
                                     '    assert all(new[k] != old[k] for k in MOVED_MAP_KEYS)                       # every one of them '
                                     'genuinely moved\n'
                                     '    from tests import f03_financing_scope as G\n'
                                     '    assert {k: moved[k] for k in new} == new and F.effective_pins() == {**F.effective_pins(), '
                                     '**new}\n'
                                     '    assert set(moved) - set(new) <= set(G.map_keys())                       # the only other moved '
                                     "key is the reviewed F03 successor's\n"
                                     '    assert F.manifest()["source_blobs"] == {**F.manifest()["source_blobs"], **{k: v for k, v in '
                                     'new.items() if k not in G.effective_pins()}}\n'
                                     '    for p in sorted(B.CURRENT_MAPS):\n'
                                     '        disk = json.loads((ROOT / p).read_bytes())["source_blobs"]\n'
                                     '        base = json.loads(_git("show", F.BASE + ":" + p))["source_blobs"]\n'
                                     '        for k in MOVED_MAP_KEYS:                                                # a map records the '
                                     'OLD value only before, the NEW one after\n'
                                     '            if k in base:\n'
                                     '                assert base[k] == old[k] and disk[k] == new[k], (p, k)\n'
                                     '        assert (ROOT / p).read_bytes() == B.expected_map(ROOT, p, cur, moved), p\n'
                                     '    # a map moves no OTHER pin than these keys and the registry-era handed-off files: key set '
                                     'unchanged for every map\n'
                                     '    for p in sorted(B.CURRENT_MAPS):\n'
                                     '        assert set(json.loads((ROOT / p).read_bytes())["source_blobs"]) == '
                                     'set(json.loads(_git("show", F.BASE + ":" + p))["source_blobs"]), p\n'
                                     '\n'
                                     '\n'
                                     'def test_scheduler_weights_are_literal_projected_corrections_with_provenance():\n',
                                     '\n'
                                     '\n'
                                     'def test_the_current_maps_manifests_carry_exactly_the_reviewed_moved_pins_in_canonical_form():\n'
                                     '    with C.call_scope():  # this complete enumeration only reads source; no fixture or mutation is '
                                     'inside\n'
                                     '        assert tuple(sorted(F.MAP_KEYS)) == MOVED_MAP_KEYS\n'
                                     '        nx = B._next_pins(ROOT, None)\n'
                                     '        pins = B.manifest()["source_blobs"]\n'
                                     '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n'
                                     '        moved = B._next_moved(ROOT, None)\n'
                                     '        # independently derived NEW value (hash of the bytes on disk) and OLD value (accepted BASE), '
                                     "never read from the leaf's own map logic\n"
                                     '        new = {k: F._blob((ROOT / k).read_bytes()) for k in MOVED_MAP_KEYS}\n'
                                     '        old = {k: F._blob(_git("show", F.BASE + ":" + k)) for k in MOVED_MAP_KEYS}\n'
                                     '        assert all(new[k] != old[k] for k in MOVED_MAP_KEYS)                       # every one of '
                                     'them genuinely moved\n'
                                     '        from tests import f03_financing_scope as G\n'
                                     '        assert {k: moved[k] for k in new} == new and F.effective_pins() == {**F.effective_pins(), '
                                     '**new}\n'
                                     '        assert set(moved) - set(new) <= set(G.map_keys())                       # the only other '
                                     "moved key is the reviewed F03 successor's\n"
                                     '        assert F.manifest()["source_blobs"] == {**F.manifest()["source_blobs"], **{k: v for k, v in '
                                     'new.items() if k not in G.effective_pins()}}\n'
                                     '        for p in sorted(B.CURRENT_MAPS):\n'
                                     '            disk = json.loads((ROOT / p).read_bytes())["source_blobs"]\n'
                                     '            base = json.loads(_git("show", F.BASE + ":" + p))["source_blobs"]\n'
                                     '            for k in MOVED_MAP_KEYS:                                                # a map records '
                                     'the OLD value only before, the NEW one after\n'
                                     '                if k in base:\n'
                                     '                    assert base[k] == old[k] and disk[k] == new[k], (p, k)\n'
                                     '            assert (ROOT / p).read_bytes() == B.expected_map(ROOT, p, cur, moved), p\n'
                                     '        # a map moves no OTHER pin than these keys and the registry-era handed-off files: key set '
                                     'unchanged for every map\n'
                                     '        for p in sorted(B.CURRENT_MAPS):\n'
                                     '            assert set(json.loads((ROOT / p).read_bytes())["source_blobs"]) == '
                                     'set(json.loads(_git("show", F.BASE + ":" + p))["source_blobs"]), p\n'
                                     '\n'
                                     '\n'
                                     'def test_scheduler_weights_are_literal_projected_corrections_with_provenance():\n'),
                                    ('        with C.call_scope():\n'
                                     '            assert F.exact_blobs_ok() is False\n'
                                     "        # a current map's bytes belong to the full proof only: the signature never reads a foreign "
                                     'manifest, every other path is in it\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.signature_ok() is (path in F.CURRENT_MAPS)\n'
                                     '        with C.call_scope():\n'
                                     '            assert C.valid() is False\n'
                                     '    finally:\n'
                                     '        target.write_bytes(original)\n'
                                     '    # a FRESH evaluation after the restore passes again; nothing was cached across the boundary\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert C.valid() is True\n'
                                     '\n'
                                     '\n',
                                     '        with C.call_scope():\n'
                                     '            assert F.exact_blobs_ok() is False\n'
                                     "        # a current map's bytes belong to the full proof only: the signature never reads a foreign "
                                     'manifest, every other path is in it\n'
                                     '            assert F.signature_ok() is (path in F.CURRENT_MAPS)\n'
                                     '            assert C.valid() is False\n'
                                     '    finally:\n'
                                     '        target.write_bytes(original)\n'
                                     '    # a FRESH evaluation after the restore passes again; nothing was cached across the boundary\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True\n'
                                     '        assert C.valid() is True\n'
                                     '\n'
                                     '\n'),
                                    ('def test_an_extra_or_forged_cohort_in_the_registry_fails_the_leaf_and_the_composite():\n'
                                     '    original = (ROOT / "tests/fin_v2_cohorts.py").read_bytes()\n'
                                     '    text = original.decode()\n'
                                     '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', '
                                     '\'tests.f03_financing_scope\', "\n'
                                     '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', '
                                     "'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                                     "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                     '\'tests.ci_v4_full_recovery_scope\')")\n'
                                     '    assert text.count(marker) == 1\n'
                                     '    try:\n'
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(text.replace(marker, marker + ", '
                                     '\'tests.fake_perf_scope\')").encode())\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.reviewed_edits_ok() is False\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.exact_blobs_ok() is False\n'
                                     '        with C.call_scope():\n'
                                     '            assert C.valid() is False\n'
                                     '    finally:\n'
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)\n',
                                     'def test_an_extra_or_forged_cohort_in_the_registry_fails_the_leaf_and_the_composite():\n'
                                     '    original = (ROOT / "tests/fin_v2_cohorts.py").read_bytes()\n'
                                     '    text = original.decode()\n'
                                     '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', '
                                     "'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', "
                                     "'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                                     "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                     '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")\n'
                                     '    assert text.count(marker) == 1\n'
                                     '    try:\n'
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(text.replace(marker, marker + ", '
                                     '\'tests.fake_perf_scope\')").encode())\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.reviewed_edits_ok() is False\n'
                                     '            assert F.exact_blobs_ok() is False\n'
                                     '            assert C.valid() is False\n'
                                     '    finally:\n'
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)\n'),
                                    ('        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(forged.encode())\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.reviewed_edits_ok() is False and F.exact_blobs_ok() is False\n'
                                     '        with C.call_scope():\n'
                                     '            assert B.reviewed_edits_ok() is False  # the accepted BESS02 tail may never be erased\n'
                                     '    finally:\n'
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)\n',
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(forged.encode())\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.reviewed_edits_ok() is False and F.exact_blobs_ok() is False\n'
                                     '            assert B.reviewed_edits_ok() is False  # the accepted BESS02 tail may never be erased\n'
                                     '    finally:\n'
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)\n'),
                                    ('        extra.write_text(\'"""unreviewed"""\\n\', encoding="utf-8")\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.exact_blobs_ok() is False\n'
                                     '        with C.call_scope():\n'
                                     '            assert C.valid() is False\n'
                                     '    finally:\n'
                                     '        extra.unlink()\n',
                                     '        extra.write_text(\'"""unreviewed"""\\n\', encoding="utf-8")\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.exact_blobs_ok() is False\n'
                                     '            assert C.valid() is False\n'
                                     '    finally:\n'
                                     '        extra.unlink()\n'),
                                    ('\n'
                                     '\n'
                                     'def '
                                     'test_the_accepted_main_version_of_every_handoff_file_is_retrievable_and_distinct_from_the_takeover():\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        base_bytes = _git("show", F.BASE + ":" + p)\n'
                                     '        now = (ROOT / p).read_bytes()\n'
                                     '        assert base_bytes != now, p                       # the takeover is real, not a no-op\n'
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (_b7().expected_handoff(ROOT, p) if _b7() is not None and p in _b7().HANDOFFS\n'
                                     '                else _b6().expected_handoff(ROOT, p) if _b6() is not None and p in _b6().HANDOFFS\n'
                                     '                else _b5().expected_handoff(ROOT, p) if _b5() is not None and p in _b5().HANDOFFS\n'
                                     '                else _b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n'
                                     '                else _b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
                                     '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
                                     '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n'
                                     '                else C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n'
                                     '                else W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'
                                     '                else Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS\n'
                                     '                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '        assert want == now                                # and equals exactly the reviewed '
                                     'substitution\n'
                                     '\n'
                                     '\n'
                                     '# ---------------------------------------------------------------------------------------------\n',
                                     '\n'
                                     '\n'
                                     'def '
                                     'test_the_accepted_main_version_of_every_handoff_file_is_retrievable_and_distinct_from_the_takeover():\n'
                                     '    from tests.fin_v2_cohorts import call_scope\n'
                                     '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                     '        for p in sorted(F.HANDOFFS):\n'
                                     '            base_bytes = _git("show", F.BASE + ":" + p)\n'
                                     '            now = (ROOT / p).read_bytes()\n'
                                     '            assert base_bytes != now, p                       # the takeover is real, not a no-op\n'
                                     '            from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope '
                                     'as Y\n'
                                     '            want = (_reviewed_handoff(p))\n'
                                     '            assert want == now                                # and equals exactly the reviewed '
                                     'substitution\n'
                                     '\n'
                                     '\n'
                                     '# ---------------------------------------------------------------------------------------------\n'),
                                    ('\n'
                                     '\n'
                                     'def test_every_older_guard_reaches_the_reviewed_pins_through_one_hook_each():\n'
                                     '    for p in FROZEN_EDITS:\n'
                                     '        pin = F.manifest()["source_blobs"][p]\n'
                                     '        assert p in OB1.FROZEN and p not in OB1.SUPERSEDED\n'
                                     '        with C.call_scope():\n'
                                     '            assert F.supersedes(p, pin) is True and F.supersedes(p, "0" * 40) is False\n'
                                     '        assert F.base_blob(p) == F._blob(_git("show", F.BASE + ":" + p)) and F.base_blob(p) != pin\n'
                                     '    # the PR3b1 hook admits exactly the module-weights pin and nothing else outside its own '
                                     'superseded set\n'
                                     '    pin = F.manifest()["source_blobs"][WEIGHTS]\n'
                                     '    with C.call_scope():\n'
                                     '        assert U31.supersedes(WEIGHTS, pin) is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert U31.supersedes(WEIGHTS, F._blob(_git("show", F.BASE + ":" + WEIGHTS))) is False   # '
                                     'the OLD value is no longer accepted\n'
                                     '    with C.call_scope():\n'
                                     '        assert U31.supersedes(WEIGHTS, "0" * 40) is False\n'
                                     '    for other in ("docs/ci_v4/node_split_policy.json", "docs/ci_v4/ci-v4-policy.json", '
                                     '"docs/ci_v4/node_weights.json"):\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(other, F._blob((ROOT / other).read_bytes())) is False, other\n'
                                     '\n'
                                     '\n'
                                     '@pytest.mark.parametrize("path", FROZEN_EDITS)\n',
                                     '\n'
                                     '\n'
                                     'def test_every_older_guard_reaches_the_reviewed_pins_through_one_hook_each():\n'
                                     '    with C.call_scope():  # this complete enumeration only reads source; no fixture or mutation is '
                                     'inside\n'
                                     '        for p in FROZEN_EDITS:\n'
                                     '            pin = F.manifest()["source_blobs"][p]\n'
                                     '            assert p in OB1.FROZEN and p not in OB1.SUPERSEDED\n'
                                     '            with C.call_scope():\n'
                                     '                assert F.supersedes(p, pin) is True and F.supersedes(p, "0" * 40) is False\n'
                                     '            assert F.base_blob(p) == F._blob(_git("show", F.BASE + ":" + p)) and F.base_blob(p) != '
                                     'pin\n'
                                     '        # the PR3b1 hook admits exactly the module-weights pin and nothing else outside its own '
                                     'superseded set\n'
                                     '        pin = F.manifest()["source_blobs"][WEIGHTS]\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(WEIGHTS, pin) is True\n'
                                     '            assert U31.supersedes(WEIGHTS, F._blob(_git("show", F.BASE + ":" + WEIGHTS))) is False   '
                                     '# the OLD value is no longer accepted\n'
                                     '            assert U31.supersedes(WEIGHTS, "0" * 40) is False\n'
                                     '        for other in ("docs/ci_v4/node_split_policy.json", "docs/ci_v4/ci-v4-policy.json", '
                                     '"docs/ci_v4/node_weights.json"):\n'
                                     '            with C.call_scope():\n'
                                     '                assert U31.supersedes(other, F._blob((ROOT / other).read_bytes())) is False, other\n'
                                     '\n'
                                     '\n'
                                     '@pytest.mark.parametrize("path", FROZEN_EDITS)\n'),
                                    ('    assert not (called & {"valid", "matches", "exact_blobs_ok", "signature_ok", "call_scope", '
                                     '"cohorts", "supersedes"})\n'
                                     '    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}\n'
                                     '    assert imports <= {"tests.fin_v2_cohorts", "tests.on_bess01_scope"}\n',
                                     '    assert not (called & {"valid", "matches", "exact_blobs_ok", "signature_ok", "call_scope", '
                                     '"cohorts", "supersedes"})\n'
                                     '    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}\n'
                                     '    assert imports <= {"tests.fin_v2_cohorts", "tests.on_bess01_scope"}\n'
                                     '\n'
                                     '\n'
                                     '@pytest.mark.parametrize("attack", ("missing", "duplicate", "reordered", "inserted", "forged"))\n'
                                     'def test_p0_terminal_resolution_rejects_every_unreviewed_registry(monkeypatch, attack):\n'
                                     '    exact = C.COHORT_MODULES\n'
                                     '    variants = {\n'
                                     '        "missing": exact[:-1],\n'
                                     '        "duplicate": exact + ("tests.ci_v4_p0_scope",),\n'
                                     '        "reordered": exact[:-2] + (exact[-1], exact[-2]),\n'
                                     '        "inserted": exact[:-1] + ("tests.ci_v4_perf_scope", exact[-1]),\n'
                                     '        "forged": exact[:-1] + ("tests.ci_v4_p0_scope_forged",),\n'
                                     '    }\n'
                                     '    with C.call_scope():\n'
                                     '        assert _p0() is not None\n'
                                     '    try:\n'
                                     '        monkeypatch.setattr(C, "COHORT_MODULES", variants[attack])\n'
                                     '        with C.call_scope():\n'
                                     '            assert _p0() is None\n'
                                     '            assert not F.exact_blobs_ok() and not C.valid()\n'
                                     '    finally:\n'
                                     '        monkeypatch.setattr(C, "COHORT_MODULES", exact)\n'
                                     '    with C.call_scope():\n'
                                     '        assert _p0() is not None and F.exact_blobs_ok() and C.valid()\n'
                                     '\n'
                                     '\n'
                                     '@pytest.mark.parametrize("attack", ("wrong_pin", "forged_registry", "wrong_handoff"))\n'
                                     'def test_p0_handoff_resolution_rejects_changed_source_and_restores(attack):\n'
                                     '    from tests import ci_v4_p0_scope as P0\n'
                                     '    rel = P0.MANIFEST if attack == "wrong_pin" else P0.REGISTRY if attack == "forged_registry" else '
                                     '"tests/test_bess02_scope.py"\n'
                                     '    path = ROOT / rel\n'
                                     '    original = path.read_bytes()\n'
                                     '    with C.call_scope():\n'
                                     '        assert _p0() is P0\n'
                                     '    try:\n'
                                     '        if attack == "wrong_pin":\n'
                                     '            data = json.loads(original)\n'
                                     '            data["source_blobs"][P0.REGISTRY] = "0" * 40\n'
                                     '            path.write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\\n").encode())\n'
                                     '        else:\n'
                                     '            path.write_bytes(original + b"\\n# unreviewed handoff\\n")\n'
                                     '        with C.call_scope():\n'
                                     '            assert _p0() is None\n'
                                     '            assert not P0.signature_ok() and not F.exact_blobs_ok() and not C.valid()\n'
                                     '    finally:\n'
                                     '        path.write_bytes(original)\n'
                                     '    with C.call_scope():\n'
                                     '        assert _p0() is P0 and _reviewed_handoff(P0.REGISTRY) == (ROOT / P0.REGISTRY).read_bytes()\n'
                                     '    assert not C._CALL\n')],
 'tests/test_ci_v5_bootstrap_scope.py': [('\n'
                                          '\n'
                                          'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                          '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                          '    from tests import ci_v4_full_recovery_scope as FR\n'
                                          '    from tests import ci_v5_gate_scope as G6\n'
                                          '    for p in T.HANDOFFS:\n'
                                          '        if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed '
                                          'FULL-recovery successor substitutes the final state of this shared path (literal, pin-exact)\n'
                                          '            assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)\n'
                                          '        elif G6.signature_ok() and p in G6.HANDOFFS:                       # the reviewed V5-3 '
                                          'successor substitutes the final state of this shared path (literal, pin-exact)\n'
                                          '            assert (ROOT / p).read_bytes() == G6.expected_handoff(ROOT, p)\n'
                                          '        elif H5.signature_ok() and p in H5.HANDOFFS:                     # the reviewed V5-2B '
                                          'successor further substitutes this shared path (literal, pin-exact)\n'
                                          '            assert (ROOT / p).read_bytes() == H5.expected_handoff(ROOT, p)\n'
                                          '        else:\n'
                                          '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                          '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '    for ref in (None, "HEAD"):\n'
                                          '        with C.call_scope():\n'
                                          '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                          'B3.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                          '\n'
                                          '\n'
                                          'def test_registered_exactly_once_after_b3_with_only_the_reviewed_v5_2b_behind_it():\n'
                                          '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                          'T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope"), '
                                          'T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope", '
                                          '"tests.ci_v4_full_recovery_scope")) and C.COHORT_MODULES.count(T.__name__) == 1\n'
                                          '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 4                       # exactly the '
                                          'reviewed V5-2B and V5-3 modules gained after the bootstrap; no hardcoded total\n'
                                          '    assert C.COHORT_MODULES[-5:] == ("tests.ci_v4_lean_b3_scope", '
                                          '"tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                          '"tests.ci_v4_full_recovery_scope")\n'
                                          '    assert T._next() is H5 and T.SUCCESSOR == H5.__name__\n'
                                          '    assert B3.SUCCESSOR == T.__name__ and B3._next() is T and B2.SUCCESSOR == B3.__name__ and '
                                          'B2._next() is B3\n'
                                          '    assert B1.SUCCESSOR == B2.__name__ and B1._next() is B2 and K.SUCCESSOR == B1.__name__ and '
                                          'K._next() is B1\n',
                                          '\n'
                                          '\n'
                                          'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                          '    from tests.fin_v2_cohorts import call_scope\n'
                                          '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                          'mutation\n'
                                          '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                          '        from tests import ci_v4_full_recovery_scope as FR\n'
                                          '        from tests import ci_v5_gate_scope as G6\n'
                                          '        for p in T.HANDOFFS:\n'
                                          '            from tests import ci_v4_p0_scope as P0\n'
                                          '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                          '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                          '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '                continue\n'
                                          '            if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed '
                                          'FULL-recovery successor substitutes the final state of this shared path (literal, pin-exact)\n'
                                          '                assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)\n'
                                          '            elif G6.signature_ok() and p in G6.HANDOFFS:                       # the reviewed '
                                          'V5-3 successor substitutes the final state of this shared path (literal, pin-exact)\n'
                                          '                assert (ROOT / p).read_bytes() == G6.expected_handoff(ROOT, p)\n'
                                          '            elif H5.signature_ok() and p in H5.HANDOFFS:                     # the reviewed '
                                          'V5-2B successor further substitutes this shared path (literal, pin-exact)\n'
                                          '                assert (ROOT / p).read_bytes() == H5.expected_handoff(ROOT, p)\n'
                                          '            else:\n'
                                          '                assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                          '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '        for ref in (None, "HEAD"):\n'
                                          '            with C.call_scope():\n'
                                          '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                          'B3.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                          '\n'
                                          '\n'
                                          'def test_registered_exactly_once_after_b3_with_only_the_reviewed_v5_2b_behind_it():\n'
                                          '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                          'T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope"), '
                                          'T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope", '
                                          '"tests.ci_v4_full_recovery_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, '
                                          '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") + (\'tests.ci_v4_p0_scope\',)) and '
                                          'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                          '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 5                       # exactly the '
                                          'reviewed V5-2B and V5-3 modules gained after the bootstrap; no hardcoded total\n'
                                          "    assert C.COHORT_MODULES[-6:] == ('tests.ci_v4_lean_b3_scope', "
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                          "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')\n"
                                          '    assert T._next() is H5 and T.SUCCESSOR == H5.__name__\n'
                                          '    assert B3.SUCCESSOR == T.__name__ and B3._next() is T and B2.SUCCESSOR == B3.__name__ and '
                                          'B2._next() is B3\n'
                                          '    assert B1.SUCCESSOR == B2.__name__ and B1._next() is B2 and K.SUCCESSOR == B1.__name__ and '
                                          'K._next() is B1\n'),
                                         ('\n'
                                          'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_v5_2b():\n'
                                          '    from tests import u1_scope as U\n'
                                          '    assert U.RECONCILED_SUCCESSORS[-4:] == ("tests.ci_v5_bootstrap_scope", '
                                          '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") and '
                                          'U.RECONCILED_SUCCESSORS.count("tests.ci_v5_bootstrap_scope") == 1\n'
                                          '\n'
                                          '\n'
                                          '# '
                                          '-------------------------------------------------------------------------------------------------------------- '
                                          'tamper (committed refs)\n',
                                          '\n'
                                          'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_v5_2b():\n'
                                          '    from tests import u1_scope as U\n'
                                          '    assert U.RECONCILED_SUCCESSORS[-5:] == ("tests.ci_v5_bootstrap_scope", '
                                          '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", '
                                          '"tests.ci_v4_p0_scope") and U.RECONCILED_SUCCESSORS.count("tests.ci_v5_bootstrap_scope") == 1\n'
                                          '\n'
                                          '\n'
                                          '# '
                                          '-------------------------------------------------------------------------------------------------------------- '
                                          'tamper (committed refs)\n'),
                                         ('\n'
                                          '\n'
                                          'def test_registry_mutations_are_rejected(clone):\n'
                                          '    tail = b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                          '\'tests.ci_v4_full_recovery_scope\')"\n'
                                          '    for name, fn in (\n'
                                          '        ("duplicate_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', '
                                          "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_bootstrap_scope', "
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                          '\'tests.ci_v4_full_recovery_scope\')")),\n'
                                          '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                          '        ("swapped_b3_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', '
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_hardening_scope', "
                                          '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')")),\n'
                                          '        ("v5_2b_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                          '        ("v5_3_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                          '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", b"")),\n',
                                          '\n'
                                          '\n'
                                          'def test_registry_mutations_are_rejected(clone):\n'
                                          '    tail = b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                          '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')"\n'
                                          '    for name, fn in (\n'
                                          '        ("duplicate_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', '
                                          "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_bootstrap_scope', "
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                          '\'tests.ci_v4_p0_scope\')")),\n'
                                          '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                          '        ("swapped_b3_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', '
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_hardening_scope', "
                                          '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                          '        ("v5_2b_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                          '        ("v5_3_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                          '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", b"")),\n'),
                                         ('    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY '
                                          'accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer '
                                          'present."""\n'
                                          '    from tests import ci_v4_full_recovery_scope as FR\n'
                                          '    from tests import ci_v5_gate_scope as G6\n'
                                          '    exact = C.COHORT_MODULES\n'
                                          '    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                          '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                          '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")\n'
                                          '    layers = (K, B1, B2, B3, T, H5, G6, FR)\n'
                                          '    with C.call_scope():\n'
                                          '        assert all(m.signature_ok() for m in layers)\n'
                                          '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]\n'
                                          '    head = exact[:-8]\n'
                                          '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": '
                                          'head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, '
                                          'fr),\n'
                                          '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": '
                                          'head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,), "v5_duplicated": head '
                                          '+ (c06, b1, b2, b3, v5, v5, h5, g6, fr),\n'
                                          '                "fr_duplicated": exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, '
                                          'h5, fr, g6), "fr_dropped": head + (c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact '
                                          '+ ("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),\n'
                                          '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, '
                                          'b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr), "v5_dropped": head '
                                          '+ (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, b1, b2, b3, v5, g6, fr)}\n'
                                          '    for name, tail in variants.items():\n'
                                          '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                          '        for layer in layers:\n',
                                          '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY '
                                          'accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer '
                                          'present."""\n'
                                          '    from tests import ci_v4_full_recovery_scope as FR\n'
                                          '    from tests import ci_v5_gate_scope as G6\n'
                                          '    from tests import ci_v4_p0_scope as P0\n'
                                          '    exact = C.COHORT_MODULES\n'
                                          '    assert exact[-9:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                          '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", '
                                          '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", '
                                          '"tests.ci_v4_p0_scope")\n'
                                          '    layers = (K, B1, B2, B3, T, H5, G6, FR, P0)\n'
                                          '    with C.call_scope():\n'
                                          '        assert all(m.signature_ok() for m in layers)\n'
                                          '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-9:-1]\n'
                                          '    head = exact[:-9]\n'
                                          '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": '
                                          'head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, '
                                          'fr),\n'
                                          '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": '
                                          'head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,), "v5_duplicated": head '
                                          '+ (c06, b1, b2, b3, v5, v5, h5, g6, fr),\n'
                                          '                "fr_duplicated": exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, '
                                          'h5, fr, g6), "fr_dropped": head + (c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact '
                                          '+ ("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),\n'
                                          '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, '
                                          'b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr), "v5_dropped": head '
                                          '+ (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, b1, b2, b3, v5, g6, fr)}\n'
                                          '    variants = {name: value if "tests.ci_v4_p0_scope" in value else value + '
                                          '("tests.ci_v4_p0_scope",)\n'
                                          '                for name, value in variants.items()}\n'
                                          '    variants.update(p0_dropped=exact[:-1], p0_duplicate=exact + ("tests.ci_v4_p0_scope",),\n'
                                          '                    p0_fr_swapped=exact[:-2] + ("tests.ci_v4_p0_scope", '
                                          '"tests.ci_v4_full_recovery_scope"))\n'
                                          '    for name, tail in variants.items():\n'
                                          '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                          '        for layer in layers:\n')],
 'tests/test_ci_v5_gate_scope.py': [('\n'
                                     '\n'
                                     'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                     '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                     '    from tests import ci_v4_full_recovery_scope as FR\n'
                                     '    for p in T.HANDOFFS:\n'
                                     '        if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed '
                                     'FULL-recovery successor further substitutes this shared path (literal, pin-exact)\n'
                                     '            assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)\n'
                                     '        else:\n'
                                     '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                     '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                     '    for p in T.REPLACED:\n'
                                     '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                     '    for ref in (None, "HEAD"):\n'
                                     '        with C.call_scope():\n'
                                     '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                     'V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                     '\n'
                                     '\n'
                                     'def test_registered_exactly_once_after_v5_2b_with_only_the_reviewed_full_recovery_behind_it():\n'
                                     '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                     'T.SUCCESSOR)) and C.COHORT_MODULES.count(T.__name__) == 1\n'
                                     '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 2                       # exactly ONE '
                                     'module gained after this cohort; no hardcoded total\n'
                                     '    assert C.COHORT_MODULES[-3:] == ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                     '"tests.ci_v4_full_recovery_scope")\n'
                                     '    assert H5.SUCCESSOR == T.__name__ and H5._next() is T and V5.SUCCESSOR == H5.__name__ and '
                                     'V5._next() is H5 and B3.SUCCESSOR == V5.__name__ and B3._next() is V5\n'
                                     '    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ and '
                                     'B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1\n'
                                     '\n',
                                     '\n'
                                     '\n'
                                     'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                     '    from tests.fin_v2_cohorts import call_scope\n'
                                     '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                     '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                     '        from tests import ci_v4_full_recovery_scope as FR\n'
                                     '        for p in T.HANDOFFS:\n'
                                     '            from tests import ci_v4_p0_scope as P0\n'
                                     '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                     '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                     '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                     '                continue\n'
                                     '            if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed '
                                     'FULL-recovery successor further substitutes this shared path (literal, pin-exact)\n'
                                     '                assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)\n'
                                     '            else:\n'
                                     '                assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                     '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                     '        for p in T.REPLACED:\n'
                                     '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                     '        for ref in (None, "HEAD"):\n'
                                     '            with C.call_scope():\n'
                                     '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                     'V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                     '\n'
                                     '\n'
                                     'def test_registered_exactly_once_after_v5_2b_with_only_the_reviewed_full_recovery_behind_it():\n'
                                     '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                     "T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR) + ('tests.ci_v4_p0_scope',)) and "
                                     'C.COHORT_MODULES.count(T.__name__) == 1\n'
                                     '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 3                       # exactly ONE '
                                     'module gained after this cohort; no hardcoded total\n'
                                     '    assert C.COHORT_MODULES[-4:] == ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                     '"tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")\n'
                                     '    assert H5.SUCCESSOR == T.__name__ and H5._next() is T and V5.SUCCESSOR == H5.__name__ and '
                                     'V5._next() is H5 and B3.SUCCESSOR == V5.__name__ and B3._next() is V5\n'
                                     '    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ and '
                                     'B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1\n'
                                     '\n'),
                                    ('\n'
                                     'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_full_recovery():\n'
                                     '    from tests import u1_scope as U\n'
                                     '    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v5_gate_scope", '
                                     '"tests.ci_v4_full_recovery_scope") and U.RECONCILED_SUCCESSORS.count("tests.ci_v5_gate_scope") == 1\n'
                                     '\n'
                                     '\n'
                                     '# '
                                     '-------------------------------------------------------------------------------------------------------------- '
                                     'tamper (committed refs)\n',
                                     '\n'
                                     'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_full_recovery():\n'
                                     '    from tests import u1_scope as U\n'
                                     '    assert U.RECONCILED_SUCCESSORS[-3:] == ("tests.ci_v5_gate_scope", '
                                     '"tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope") and '
                                     'U.RECONCILED_SUCCESSORS.count("tests.ci_v5_gate_scope") == 1\n'
                                     '\n'
                                     '\n'
                                     '# '
                                     '-------------------------------------------------------------------------------------------------------------- '
                                     'tamper (committed refs)\n'),
                                    ('\n'
                                     '\n'
                                     'def test_registry_mutations_are_rejected(clone):\n'
                                     '    tail = b"\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                     '\'tests.ci_v5_hardening_scope\', \'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')"\n'
                                     '    for name, fn in (\n'
                                     '        ("duplicate_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                     '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_full_recovery_scope\')")),\n'
                                     '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                     '        ("swapped_g6_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v4_full_recovery_scope', "
                                     '\'tests.ci_v5_gate_scope\')")),\n'
                                     '        ("h5_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                     '        ("g6_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                     '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", b"")),\n',
                                     '\n'
                                     '\n'
                                     'def test_registry_mutations_are_rejected(clone):\n'
                                     '    tail = b"\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                     "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                     '\'tests.ci_v4_p0_scope\')"\n'
                                     '    for name, fn in (\n'
                                     '        ("duplicate_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                     "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_full_recovery_scope', "
                                     '\'tests.ci_v4_p0_scope\')")),\n'
                                     '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                     '        ("swapped_g6_fr", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v4_full_recovery_scope', "
                                     '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                     '        ("h5_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                     '        ("g6_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                     '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", b"")),\n'),
                                    ('def test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):\n'
                                     '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY accepted '
                                     'tail: any permutation, duplicate, extra cohort or truncation fails every layer present."""\n'
                                     '    from tests import ci_v4_full_recovery_scope as FR\n'
                                     '    exact = C.COHORT_MODULES\n'
                                     '    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                     '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",\n'
                                     '                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                     '"tests.ci_v4_full_recovery_scope")\n'
                                     '    layers = (K, B1, B2, B3, V5, H5, T, FR)\n'
                                     '    with C.call_scope():\n'
                                     '        assert all(m.signature_ok() for m in layers)\n'
                                     '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]\n'
                                     '    head = exact[:-8]\n'
                                     '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": head + '
                                     '(c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, fr),\n'
                                     '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": head + '
                                     '(c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),\n'
                                     '                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), "fr_duplicated": '
                                     'exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), "fr_dropped": head + (c06, '
                                     'b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",), '
                                     '"g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),\n'
                                     '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, b1, '
                                     'b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),\n'
                                     '                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, b1, '
                                     'b2, b3, v5, g6, fr)}\n'
                                     '    for name, tail in variants.items():\n'
                                     '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                     '        for layer in layers:\n',
                                     'def test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):\n'
                                     '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY accepted '
                                     'tail: any permutation, duplicate, extra cohort or truncation fails every layer present."""\n'
                                     '    from tests import ci_v4_full_recovery_scope as FR\n'
                                     '    from tests import ci_v4_p0_scope as P0\n'
                                     '    exact = C.COHORT_MODULES\n'
                                     '    assert exact[-9:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                     '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",\n'
                                     '                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                     '"tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")\n'
                                     '    layers = (K, B1, B2, B3, V5, H5, T, FR, P0)\n'
                                     '    with C.call_scope():\n'
                                     '        assert all(m.signature_ok() for m in layers)\n'
                                     '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-9:-1]\n'
                                     '    head = exact[:-9]\n'
                                     '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": head + '
                                     '(c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, fr),\n'
                                     '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": head + '
                                     '(c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),\n'
                                     '                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), "fr_duplicated": '
                                     'exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), "fr_dropped": head + (c06, '
                                     'b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",), '
                                     '"g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),\n'
                                     '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, b1, '
                                     'b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),\n'
                                     '                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, b1, '
                                     'b2, b3, v5, g6, fr)}\n'
                                     '    variants = {name: value if "tests.ci_v4_p0_scope" in value else value + '
                                     '("tests.ci_v4_p0_scope",)\n'
                                     '                for name, value in variants.items()}\n'
                                     '    variants.update(p0_dropped=exact[:-1], p0_duplicate=exact + ("tests.ci_v4_p0_scope",),\n'
                                     '                    p0_fr_swapped=exact[:-2] + ("tests.ci_v4_p0_scope", '
                                     '"tests.ci_v4_full_recovery_scope"))\n'
                                     '    for name, tail in variants.items():\n'
                                     '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                     '        for layer in layers:\n')],
 'tests/test_ci_v5_hardening_scope.py': [('\n'
                                          '\n'
                                          'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                          '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                          '    for p in T.HANDOFFS:\n'
                                          '        if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed '
                                          'FULL-recovery successor further substitutes this shared path (literal, pin-exact)\n'
                                          '            assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)\n'
                                          '        elif G6.signature_ok() and p in G6.HANDOFFS:                       # the reviewed V5-3 '
                                          'successor further substitutes this shared path (literal, pin-exact)\n'
                                          '            assert (ROOT / p).read_bytes() == G6.expected_handoff(ROOT, p)\n'
                                          '        else:\n'
                                          '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                          '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '    for p in T.REPLACED:\n'
                                          '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '    for ref in (None, "HEAD"):\n'
                                          '        with C.call_scope():\n'
                                          '            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                          'V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                          '\n'
                                          '\n'
                                          'def '
                                          'test_registered_exactly_once_after_the_v5_bootstrap_with_only_the_reviewed_v5_3_behind_it():\n'
                                          '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                          "T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v4_full_recovery_scope')) "
                                          'and C.COHORT_MODULES.count(T.__name__) == 1\n'
                                          '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 3                       # exactly ONE '
                                          'module gained after this cohort; no hardcoded total\n'
                                          '    assert C.COHORT_MODULES[-4:] == ("tests.ci_v5_bootstrap_scope", '
                                          '"tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")\n'
                                          '    assert T._next() is G6 and T.SUCCESSOR == G6.__name__\n'
                                          '    assert V5.SUCCESSOR == T.__name__ and V5._next() is T and B3.SUCCESSOR == V5.__name__ and '
                                          'B3._next() is V5\n'
                                          '    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ and '
                                          'B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1\n',
                                          '\n'
                                          '\n'
                                          'def test_signature_exactness_and_reviewed_substitutions_hold(clone):\n'
                                          '    from tests.fin_v2_cohorts import call_scope\n'
                                          '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                          'mutation\n'
                                          '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                          '        for p in T.HANDOFFS:\n'
                                          '            from tests import ci_v4_p0_scope as P0\n'
                                          '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                          '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                          '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '                continue\n'
                                          '            if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed '
                                          'FULL-recovery successor further substitutes this shared path (literal, pin-exact)\n'
                                          '                assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)\n'
                                          '            elif G6.signature_ok() and p in G6.HANDOFFS:                       # the reviewed '
                                          'V5-3 successor further substitutes this shared path (literal, pin-exact)\n'
                                          '                assert (ROOT / p).read_bytes() == G6.expected_handoff(ROOT, p)\n'
                                          '            else:\n'
                                          '                assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                          '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '        for p in T.REPLACED:\n'
                                          '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                          '        for ref in (None, "HEAD"):\n'
                                          '            with C.call_scope():\n'
                                          '                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and '
                                          'V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)\n'
                                          '\n'
                                          '\n'
                                          'def '
                                          'test_registered_exactly_once_after_the_v5_bootstrap_with_only_the_reviewed_v5_3_behind_it():\n'
                                          '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, '
                                          "T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v4_full_recovery_scope'), "
                                          "T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v4_full_recovery_scope') + "
                                          "('tests.ci_v4_p0_scope',)) and C.COHORT_MODULES.count(T.__name__) == 1\n"
                                          '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 4                       # exactly ONE '
                                          'module gained after this cohort; no hardcoded total\n'
                                          "    assert C.COHORT_MODULES[-5:] == ('tests.ci_v5_bootstrap_scope', "
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                          "'tests.ci_v4_p0_scope')\n"
                                          '    assert T._next() is G6 and T.SUCCESSOR == G6.__name__\n'
                                          '    assert V5.SUCCESSOR == T.__name__ and V5._next() is T and B3.SUCCESSOR == V5.__name__ and '
                                          'B3._next() is V5\n'
                                          '    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ and '
                                          'B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1\n'),
                                         ('\n'
                                          'def '
                                          'test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_3_gate():\n'
                                          '    from tests import u1_scope as U\n'
                                          '    assert U.RECONCILED_SUCCESSORS[-3:] == ("tests.ci_v5_hardening_scope", '
                                          '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") and '
                                          'U.RECONCILED_SUCCESSORS.count("tests.ci_v5_hardening_scope") == 1\n'
                                          '\n'
                                          '\n'
                                          '# '
                                          '-------------------------------------------------------------------------------------------------------------- '
                                          'tamper (committed refs)\n',
                                          '\n'
                                          'def '
                                          'test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_3_gate():\n'
                                          '    from tests import u1_scope as U\n'
                                          '    assert U.RECONCILED_SUCCESSORS[-4:] == ("tests.ci_v5_hardening_scope", '
                                          '"tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope") and '
                                          'U.RECONCILED_SUCCESSORS.count("tests.ci_v5_hardening_scope") == 1\n'
                                          '\n'
                                          '\n'
                                          '# '
                                          '-------------------------------------------------------------------------------------------------------------- '
                                          'tamper (committed refs)\n'),
                                         ('\n'
                                          '\n'
                                          'def test_registry_mutations_are_rejected(clone):\n'
                                          '    tail = b"\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                          '\'tests.ci_v4_full_recovery_scope\')"\n'
                                          '    for name, fn in (\n'
                                          '        ("duplicate_h5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_hardening_scope', "
                                          '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')")),\n'
                                          '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                          '        ("swapped_v5_h5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_gate_scope', "
                                          '\'tests.ci_v4_full_recovery_scope\')")),\n'
                                          '        ("h5_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                          '        ("g6_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                          '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", b"")),\n',
                                          '\n'
                                          '\n'
                                          'def test_registry_mutations_are_rejected(clone):\n'
                                          '    tail = b"\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', "
                                          '\'tests.ci_v4_p0_scope\')"\n'
                                          '    for name, fn in (\n'
                                          '        ("duplicate_h5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                          "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_hardening_scope', "
                                          '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                          '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
                                          '        ("swapped_v5_h5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b3_scope\', '
                                          "'tests.ci_v5_hardening_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_gate_scope', "
                                          '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')")),\n'
                                          '        ("h5_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n'
                                          '        ("g6_missing", lambda b: b.replace(b", \'tests.ci_v5_gate_scope\'", b"")),\n'
                                          '        ("fr_missing", lambda b: b.replace(b", \'tests.ci_v4_full_recovery_scope\'", b"")),\n'),
                                         ('\n'
                                          'def test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):\n'
                                          '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY '
                                          'accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer '
                                          'present."""\n'
                                          '    exact = C.COHORT_MODULES\n'
                                          '    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                          '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",\n'
                                          '                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                          '"tests.ci_v4_full_recovery_scope")\n'
                                          '    layers = (K, B1, B2, B3, V5, T, G6, FR)\n'
                                          '    with C.call_scope():\n'
                                          '        assert all(m.signature_ok() for m in layers)\n'
                                          '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]\n'
                                          '    head = exact[:-8]\n'
                                          '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": '
                                          'head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, '
                                          'fr),\n'
                                          '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": '
                                          'head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),\n'
                                          '                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), "fr_duplicated": '
                                          'exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), "fr_dropped": head + '
                                          '(c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + '
                                          '("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),\n'
                                          '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, '
                                          'b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),\n'
                                          '                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, '
                                          'b1, b2, b3, v5, g6, fr)}\n'
                                          '    for name, tail in variants.items():\n'
                                          '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                          '        for layer in layers:\n',
                                          '\n'
                                          'def test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):\n'
                                          '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY '
                                          'accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer '
                                          'present."""\n'
                                          '    from tests import ci_v4_p0_scope as P0\n'
                                          '    exact = C.COHORT_MODULES\n'
                                          '    assert exact[-9:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", '
                                          '"tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",\n'
                                          '                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", '
                                          '"tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")\n'
                                          '    layers = (K, B1, B2, B3, V5, T, G6, FR, P0)\n'
                                          '    with C.call_scope():\n'
                                          '        assert all(m.signature_ok() for m in layers)\n'
                                          '    c06, b1, b2, b3, v5, h5, g6, fr = exact[-9:-1]\n'
                                          '    head = exact[:-9]\n'
                                          '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": '
                                          'head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, '
                                          'fr),\n'
                                          '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": '
                                          'head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),\n'
                                          '                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), "fr_duplicated": '
                                          'exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), "fr_dropped": head + '
                                          '(c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + '
                                          '("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),\n'
                                          '                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, '
                                          'b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),\n'
                                          '                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, '
                                          'b1, b2, b3, v5, g6, fr)}\n'
                                          '    variants = {name: value if "tests.ci_v4_p0_scope" in value else value + '
                                          '("tests.ci_v4_p0_scope",)\n'
                                          '                for name, value in variants.items()}\n'
                                          '    variants.update(p0_dropped=exact[:-1], p0_duplicate=exact + ("tests.ci_v4_p0_scope",),\n'
                                          '                    p0_fr_swapped=exact[:-2] + ("tests.ci_v4_p0_scope", '
                                          '"tests.ci_v4_full_recovery_scope"))\n'
                                          '    for name, tail in variants.items():\n'
                                          '        monkeypatch.setattr(C, "COHORT_MODULES", tail)\n'
                                          '        for layer in layers:\n')],
 'tests/test_f03_financing_scope.py': [('                                  "tests.r03_ppa_scope")) or (\n'
                                        '        C.COHORT_MODULES[-6:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                        '        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in '
                                        '(C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + '
                                        '(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + '
                                        "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                        "'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + "
                                        "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        "'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        "'tests.ci_v4_full_recovery_scope'))\n"
                                        '        and C06_APPROVAL.signature_ok())\n'
                                        '\n'
                                        '\n'
                                        '@pytest.mark.parametrize("name,fn", [\n'
                                        '    ("duplicate_f03", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                        '\'tests.t01e_remediation_scope\'", b"\'tests.f03_financing_scope\', '
                                        '\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', '
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')", '
                                        'b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                        '\'tests.ci_v5_hardening_scope\', \'tests.ci_v5_gate_scope\', \'tests.fake_scope\')")),\n'
                                        '    ("swapped_perf_f03", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', '
                                        '\'tests.f03_financing_scope\'", b"\'tests.f03_financing_scope\', \'tests.ci_v4_perf_scope\'")),\n'
                                        '    ("swapped_bess_perf", lambda b: b.replace(b"\'tests.bess02_scope\', '
                                        '\'tests.ci_v4_perf_scope\'", b"\'tests.ci_v4_perf_scope\', \'tests.bess02_scope\'")),\n'
                                        '    ("perf_removed", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', ", b"")),\n',
                                        '                                  "tests.r03_ppa_scope")) or (\n'
                                        '        C.COHORT_MODULES[-6:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                        '        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in '
                                        '(C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + '
                                        '(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + '
                                        "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                        "'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + "
                                        "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        "'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        "'tests.ci_v4_full_recovery_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                        "'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',))\n"
                                        '        and C06_APPROVAL.signature_ok())\n'
                                        '\n'
                                        '\n'
                                        '@pytest.mark.parametrize("name,fn", [\n'
                                        '    ("duplicate_f03", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                        '\'tests.t01e_remediation_scope\'", b"\'tests.f03_financing_scope\', '
                                        '\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', '
                                        "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                        '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')", '
                                        'b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', '
                                        '\'tests.ci_v5_hardening_scope\', \'tests.ci_v5_gate_scope\', \'tests.fake_scope\')")),\n'
                                        '    ("swapped_perf_f03", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', '
                                        '\'tests.f03_financing_scope\'", b"\'tests.f03_financing_scope\', \'tests.ci_v4_perf_scope\'")),\n'
                                        '    ("swapped_bess_perf", lambda b: b.replace(b"\'tests.bess02_scope\', '
                                        '\'tests.ci_v4_perf_scope\'", b"\'tests.ci_v4_perf_scope\', \'tests.bess02_scope\'")),\n'
                                        '    ("perf_removed", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', ", b"")),\n')],
 'tests/test_f04_financing_scope.py': [("    assert F.BASE=='7584149f9334ac058cd986188b571c7dd48d538e'\n"
                                        "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
                                        "    assert (C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (\n"
                                        '        '
                                        "C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') "
                                        'and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                        '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                        'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                        '        and C06_APPROVAL.signature_ok())\n'
                                        "    assert C.COHORT_MODULES.count('tests.f04_financing_scope')==1\n"
                                        "    for ref in (None,'HEAD'):\n",
                                        "    assert F.BASE=='7584149f9334ac058cd986188b571c7dd48d538e'\n"
                                        "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
                                        "    assert (C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (\n"
                                        '        '
                                        "C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') "
                                        'and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                        '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                        'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                        "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                        'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                        "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                        "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + "
                                        "('tests.ci_v4_p0_scope',))\n"
                                        '        and C06_APPROVAL.signature_ok())\n'
                                        "    assert C.COHORT_MODULES.count('tests.f04_financing_scope')==1\n"
                                        "    for ref in (None,'HEAD'):\n"),
                                       ("    assert not any('*' in p or '..' in p.split('/') or p.startswith(F.FORBIDDEN) for p in "
                                        'F.OWNED_PATHS)\n'
                                        '    for path in F.SUPERSEDED:assert '
                                        "data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
                                        '    for path in F.HANDOFFS:\n'
                                        '        B1=C06_APPROVAL._next()\n'
                                        '        B2=B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                        '        B3=B2._next() if B2 is not None and B2.signature_ok() else None\n',
                                        "    assert not any('*' in p or '..' in p.split('/') or p.startswith(F.FORBIDDEN) for p in "
                                        'F.OWNED_PATHS)\n'
                                        '    for path in F.SUPERSEDED:assert '
                                        "data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
                                        '    for path in F.HANDOFFS:\n'
                                        '        from tests import ci_v4_p0_scope as P0\n'
                                        '        if P0.signature_ok() and path in P0.HANDOFFS:\n'
                                        '            assert (ROOT / path).read_bytes() == P0.expected_handoff(ROOT, path)\n'
                                        '            assert F._blob((ROOT / path).read_bytes()) == F.effective_pins()[path]\n'
                                        '            continue\n'
                                        '        B1=C06_APPROVAL._next()\n'
                                        '        B2=B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                        '        B3=B2._next() if B2 is not None and B2.signature_ok() else None\n')],
 'tests/test_r02_ppa_ux_scope.py': [('\n'
                                     '\n'
                                     'def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():\n'
                                     '    import ast\n'
                                     "    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], "
                                     'cwd=ROOT).decode()\n'
                                     '    from tests import ci_v4_perf_scope as F\n'
                                     '    from tests import f03_financing_scope as G\n'
                                     '    from tests import t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     "    nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope', "
                                     "'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope',\n"
                                     "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                                     "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                     "'tests.ci_v4_full_recovery_scope') if m in C.COHORT_MODULES)\n"
                                     '    B1 = C06_APPROVAL._next()\n'
                                     '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                     '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                     '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                     '    B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                     '    B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                     '    B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                     '    if len(nxt) == 14 and B7 is not None and B7.signature_ok():\n'
                                     '        expected = B7.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 13 and B6 is not None and B6.signature_ok():\n'
                                     '        expected = B6.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 12 and B5 is not None and B5.signature_ok():\n'
                                     '        expected = B5.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 11 and B4 is not None and B4.signature_ok():\n'
                                     '        expected = B4.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 10 and B3 is not None and B3.signature_ok():\n'
                                     '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 9 and B2 is not None and B2.signature_ok():\n'
                                     '        expected = B2.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 8 and B1 is not None and B1.signature_ok():\n'
                                     '        expected = B1.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 7 and C06_APPROVAL.signature_ok():\n'
                                     '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 6 and W.signature_ok():\n'
                                     '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 5 and Q.signature_ok():\n'
                                     '        expected = Q.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 4 and Y.signature_ok():\n'
                                     '        expected = Y.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 3 and Z.signature_ok():\n'
                                     '        expected = Z.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 2 and G.signature_ok():\n'
                                     '        expected = G.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 1 and F.signature_ok():\n'
                                     '        expected = F.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == expected\n'
                                     '    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, ast.Assign) '
                                     "and n.targets[0].id == 'COHORT_MODULES')\n"
                                     '    core = C.COHORT_MODULES[:len(C.COHORT_MODULES) - len(nxt)]\n'
                                     "    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') + nxt and "
                                     "core[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n"
                                     '\n'
                                     '\n'
                                     'def test_predecessors_and_older_guards_follow_this_cohort_only_through_the_reviewed_handoffs():\n',
                                     '\n'
                                     '\n'
                                     'def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():\n'
                                     '    from tests.fin_v2_cohorts import call_scope\n'
                                     '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                     '        import ast\n'
                                     "        base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], "
                                     'cwd=ROOT).decode()\n'
                                     '        from tests import ci_v4_perf_scope as F\n'
                                     '        from tests import f03_financing_scope as G\n'
                                     '        from tests import t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     "        nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope', "
                                     "'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope',\n"
                                     "                                'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                                     "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                     "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                     "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope') if m in C.COHORT_MODULES)\n"
                                     '        B1 = C06_APPROVAL._next()\n'
                                     '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                     '        expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                     '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                     '        B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                     '        B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                     '        B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                     '        B8 = B7._next() if B7 is not None and B7.signature_ok() else None\n'
                                     '        if len(nxt) == 15 and B8 is not None and B8.signature_ok():\n'
                                     '            expected = B8.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 14 and B7 is not None and B7.signature_ok():\n'
                                     '            expected = B7.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 13 and B6 is not None and B6.signature_ok():\n'
                                     '            expected = B6.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 12 and B5 is not None and B5.signature_ok():\n'
                                     '            expected = B5.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 11 and B4 is not None and B4.signature_ok():\n'
                                     '            expected = B4.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 10 and B3 is not None and B3.signature_ok():\n'
                                     '            expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 9 and B2 is not None and B2.signature_ok():\n'
                                     '            expected = B2.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 8 and B1 is not None and B1.signature_ok():\n'
                                     '            expected = B1.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 7 and C06_APPROVAL.signature_ok():\n'
                                     '            expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 6 and W.signature_ok():\n'
                                     '            expected = W.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 5 and Q.signature_ok():\n'
                                     '            expected = Q.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 4 and Y.signature_ok():\n'
                                     '            expected = Y.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 3 and Z.signature_ok():\n'
                                     '            expected = Z.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 2 and G.signature_ok():\n'
                                     '            expected = G.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        elif len(nxt) == 1 and F.signature_ok():\n'
                                     '            expected = F.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '        assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == expected\n'
                                     '        old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, '
                                     "ast.Assign) and n.targets[0].id == 'COHORT_MODULES')\n"
                                     '        core = C.COHORT_MODULES[:len(C.COHORT_MODULES) - len(nxt)]\n'
                                     "        assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') + nxt and "
                                     "core[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n"
                                     '\n'
                                     '\n'
                                     'def test_predecessors_and_older_guards_follow_this_cohort_only_through_the_reviewed_handoffs():\n')],
 'tests/test_r03_ppa_scope.py': [('\n'
                                  '\n'
                                  'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '    B1 = C06_APPROVAL._next()\n'
                                  '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                  '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                  '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                  '    B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                  '    B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                  '    B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                  '    for p in T.HANDOFFS:\n'
                                  '        authority = B7 if B7 is not None and B7.signature_ok() and p in B7.HANDOFFS else B6 if B6 is '
                                  'not None and B6.signature_ok() and p in B6.HANDOFFS else B5 if B5 is not None and B5.signature_ok() and '
                                  'p in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 is '
                                  'not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in '
                                  'B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not '
                                  'None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p '
                                  'in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and '
                                  'p in Q.HANDOFFS else T\n'
                                  '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                  '\n'
                                  '\n'
                                  'def test_registered_exactly_once_as_the_terminal_cohort_after_t01e():\n'
                                  '    assert (C.COHORT_MODULES[-3:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope") or (\n'
                                  '        C.COHORT_MODULES[-4:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                  '        C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                  '        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS '
                                  '+ (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                  'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                  "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                  '        and C06_APPROVAL.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r03_ppa_scope") == 1\n'
                                  '\n',
                                  '\n'
                                  '\n'
                                  'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    from tests.fin_v2_cohorts import call_scope\n'
                                  '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                  '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '        B1 = C06_APPROVAL._next()\n'
                                  '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                  '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                  '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                  '        B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                  '        B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                  '        B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                  '        for p in T.HANDOFFS:\n'
                                  '            from tests import ci_v4_p0_scope as P0\n'
                                  '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                  '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                  '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                  '                continue\n'
                                  '            authority = B7 if B7 is not None and B7.signature_ok() and p in B7.HANDOFFS else B6 if B6 '
                                  'is not None and B6.signature_ok() and p in B6.HANDOFFS else B5 if B5 is not None and B5.signature_ok() '
                                  'and p in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 '
                                  'is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in '
                                  'B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not '
                                  'None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p '
                                  'in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and '
                                  'p in Q.HANDOFFS else T\n'
                                  '            assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                  '\n'
                                  '\n'
                                  'def test_registered_exactly_once_as_the_terminal_cohort_after_t01e():\n'
                                  '    assert (C.COHORT_MODULES[-3:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope") or (\n'
                                  '        C.COHORT_MODULES[-4:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                  '        C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                  '        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS '
                                  '+ (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                  'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                  "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), C06_APPROVAL.BASE_COHORTS + "
                                  "(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', "
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                  "'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',))\n"
                                  '        and C06_APPROVAL.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r03_ppa_scope") == 1\n'
                                  '\n'),
                                 ('\n'
                                  '@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r03", lambda b: b.replace(b"\'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b"\'tests.r03_ppa_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                  '\'tests.ci_v4_full_recovery_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                  '\'tests.fake_scope\')")),\n'
                                  '    ("swapped_t01e_r03", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                  '\'tests.r03_ppa_scope\'", b"\'tests.r03_ppa_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                  '    ("r03_missing", lambda b: b.replace(b", \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b", \'tests.f04_financing_scope\'")),\n'
                                  '    ("t01e_removed", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', ", b"")),\n',
                                  '\n'
                                  '@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r03", lambda b: b.replace(b"\'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b"\'tests.r03_ppa_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                  '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')", b"\'tests.ci_v4_lean_b2_scope\', '
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                  '\'tests.ci_v5_gate_scope\', \'tests.fake_scope\')")),\n'
                                  '    ("swapped_t01e_r03", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                  '\'tests.r03_ppa_scope\'", b"\'tests.r03_ppa_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                  '    ("r03_missing", lambda b: b.replace(b", \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b", \'tests.f04_financing_scope\'")),\n'
                                  '    ("t01e_removed", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', ", b"")),\n')],
 'tests/test_r04_ppa_scope.py': [('\n'
                                  '\n'
                                  'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '    for p in T.HANDOFFS:\n'
                                  '        B1 = C06_APPROVAL._next()\n'
                                  '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                  '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                  '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                  '        B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                  '        B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                  '        B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                  '        authority = (B7 if B7 is not None and B7.signature_ok() and p in B7.HANDOFFS else B6 if B6 is '
                                  'not None and B6.signature_ok() and p in B6.HANDOFFS else B5 if B5 is not None and B5.signature_ok() and '
                                  'p in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 is '
                                  'not None and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and '
                                  'p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the '
                                  'further reviewed B1 substitution of this shared path\n'
                                  '                     else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS '
                                  'else T)\n'
                                  '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                  '\n'
                                  '\n'
                                  'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
                                  '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in '
                                  '(C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + '
                                  '(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                  "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                  "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                  '                                                    and C06_APPROVAL.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r04_ppa_scope") == 1\n'
                                  '\n',
                                  '\n'
                                  '\n'
                                  'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    from tests.fin_v2_cohorts import call_scope\n'
                                  '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation\n'
                                  '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '        for p in T.HANDOFFS:\n'
                                  '            from tests import ci_v4_p0_scope as P0\n'
                                  '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                  '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                  '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                  '                continue\n'
                                  '            B1 = C06_APPROVAL._next()\n'
                                  '            B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                  '            B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                  '            B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                  '            B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                  '            B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                  '            B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                  '            authority = (B7 if B7 is not None and B7.signature_ok() and p in B7.HANDOFFS else B6 if B6 '
                                  'is not None and B6.signature_ok() and p in B6.HANDOFFS else B5 if B5 is not None and B5.signature_ok() '
                                  'and p in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 '
                                  'is not None and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() '
                                  'and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # '
                                  'the further reviewed B1 substitution of this shared path\n'
                                  '                         else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in '
                                  'C06_APPROVAL.HANDOFFS else T)\n'
                                  '            assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                  '\n'
                                  '\n'
                                  'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
                                  '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in '
                                  '(C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + '
                                  '(C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                  "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                  "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                  'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                  "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                  "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + "
                                  "('tests.ci_v4_p0_scope',))\n"
                                  '                                                    and C06_APPROVAL.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r04_ppa_scope") == 1\n'
                                  '\n'),
                                 ('\n'
                                  '@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                  '\'tests.ci_v4_full_recovery_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                  '\'tests.fake_scope\')")),\n'
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b", \'tests.c06_cost_workspace_scope\'")),\n'
                                  '    ("f04_removed", lambda b: b.replace(b"\'tests.f04_financing_scope\', ", b"")),\n',
                                  '\n'
                                  '@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                  "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                  '\'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')", b"\'tests.ci_v4_lean_b2_scope\', '
                                  "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                  '\'tests.ci_v5_gate_scope\', \'tests.fake_scope\')")),\n'
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b", \'tests.c06_cost_workspace_scope\'")),\n'
                                  '    ("f04_removed", lambda b: b.replace(b"\'tests.f04_financing_scope\', ", b"")),\n')],
 'tests/test_t01e_remediation_scope.py': [('\n'
                                           '\n'
                                           'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                           '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                           '    from tests import r03_ppa_scope as Y\n'
                                           '    B1 = C06_APPROVAL._next()\n'
                                           '    for p in T.HANDOFFS:\n'
                                           '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                           '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                           '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                           '        B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                           '        B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                           '        B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                           '        if B7 is not None and B7.signature_ok() and p in B7.HANDOFFS:            # the further '
                                           'reviewed FULL-recovery substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B7.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if B6 is not None and B6.signature_ok() and p in B6.HANDOFFS:            # the further '
                                           'reviewed V5-3 substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B6.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if B5 is not None and B5.signature_ok() and p in B5.HANDOFFS:            # the further '
                                           'reviewed V5-2B substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B5.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS:            # the further '
                                           'reviewed V5 bootstrap substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B4.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and '
                                           'B3.signature_ok() and p in B3.HANDOFFS:            # the further reviewed B3 substitution of '
                                           'this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B3.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS:            # the further '
                                           'reviewed B2 substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B2.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS:            # the further '
                                           'reviewed B1 substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == B1.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if W.signature_ok() and p in W.HANDOFFS:            # the latest reviewed R04 '
                                           'substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == W.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if Q.signature_ok() and p in Q.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == Q.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if Y.signature_ok() and p in Y.HANDOFFS:            # the further reviewed R03 '
                                           'substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == Y.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                           '        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]\n'
                                           '\n'
                                           '\n'
                                           'def '
                                           'test_registered_exactly_once_directly_after_f03_with_only_the_reviewed_r03_successor_behind_it():\n'
                                           '    i = C.COHORT_MODULES.index("tests.t01e_remediation_scope")\n'
                                           '    assert C.COHORT_MODULES[i - 1] == "tests.f03_financing_scope"\n'
                                           '    assert (C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", '
                                           '"tests.f04_financing_scope"),\n'
                                           '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                           '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                           'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                           "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                           "'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                           "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                           "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                           "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'))\n"
                                           '        and C06_APPROVAL.signature_ok())\n'
                                           '    assert C.COHORT_MODULES.count("tests.t01e_remediation_scope") == 1\n'
                                           '\n',
                                           '\n'
                                           '\n'
                                           'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                           '    from tests.fin_v2_cohorts import call_scope\n'
                                           '    with call_scope():  # one read-only enumeration; ends before any fixture teardown or '
                                           'mutation\n'
                                           '        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                           '        from tests import r03_ppa_scope as Y\n'
                                           '        B1 = C06_APPROVAL._next()\n'
                                           '        for p in T.HANDOFFS:\n'
                                           '            from tests import ci_v4_p0_scope as P0\n'
                                           '            if P0.signature_ok() and p in P0.HANDOFFS:\n'
                                           '                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                                           '            B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
                                           '            B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
                                           '            B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
                                           '            B6 = B5._next() if B5 is not None and B5.signature_ok() else None\n'
                                           '            B7 = B6._next() if B6 is not None and B6.signature_ok() else None\n'
                                           '            if B7 is not None and B7.signature_ok() and p in B7.HANDOFFS:            # the '
                                           'further reviewed FULL-recovery substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B7.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if B6 is not None and B6.signature_ok() and p in B6.HANDOFFS:            # the '
                                           'further reviewed V5-3 substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B6.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if B5 is not None and B5.signature_ok() and p in B5.HANDOFFS:            # the '
                                           'further reviewed V5-2B substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B5.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS:            # the '
                                           'further reviewed V5 bootstrap substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B4.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and '
                                           'B3.signature_ok() and p in B3.HANDOFFS:            # the further reviewed B3 substitution of '
                                           'this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B3.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS:            # the '
                                           'further reviewed B2 substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B2.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS:            # the '
                                           'further reviewed B1 substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == B1.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS:\n'
                                           '                assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if W.signature_ok() and p in W.HANDOFFS:            # the latest reviewed R04 '
                                           'substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == W.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if Q.signature_ok() and p in Q.HANDOFFS:\n'
                                           '                assert (ROOT / p).read_bytes() == Q.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            if Y.signature_ok() and p in Y.HANDOFFS:            # the further reviewed R03 '
                                           'substitution of this shared path\n'
                                           '                assert (ROOT / p).read_bytes() == Y.expected_handoff(ROOT, p)\n'
                                           '                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '                continue\n'
                                           '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]\n'
                                           '\n'
                                           '\n'
                                           'def '
                                           'test_registered_exactly_once_directly_after_f03_with_only_the_reviewed_r03_successor_behind_it():\n'
                                           '    i = C.COHORT_MODULES.index("tests.t01e_remediation_scope")\n'
                                           '    assert C.COHORT_MODULES[i - 1] == "tests.f03_financing_scope"\n'
                                           '    assert (C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", '
                                           '"tests.f04_financing_scope"),\n'
                                           '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + '
                                           '(C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                           'C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                           "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                           "'tests.ci_v5_hardening_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, "
                                           "C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                                           "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                           "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), "
                                           'C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, '
                                           "'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', "
                                           "'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + "
                                           "('tests.ci_v4_p0_scope',))\n"
                                           '        and C06_APPROVAL.signature_ok())\n'
                                           '    assert C.COHORT_MODULES.count("tests.t01e_remediation_scope") == 1\n'
                                           '\n'),
                                          ('\n'
                                           '@pytest.mark.parametrize("name,fn", [\n'
                                           '    ("duplicate_t01e", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'")),\n'
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', '
                                           "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                           '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\')", '
                                           'b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                           "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                           '\'tests.fake_scope\')")),\n'
                                           '    ("swapped_f03_t01e", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                           '\'tests.t01e_remediation_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.f03_financing_scope\'")),\n'
                                           '    ("t01e_missing", lambda b: b.replace(b", \'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b", \'tests.r03_ppa_scope\'")),\n'
                                           '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n',
                                           '\n'
                                           '@pytest.mark.parametrize("name,fn", [\n'
                                           '    ("duplicate_t01e", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'")),\n'
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', '
                                           "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', "
                                           '\'tests.ci_v5_gate_scope\', \'tests.ci_v4_full_recovery_scope\', \'tests.ci_v4_p0_scope\')", '
                                           'b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', '
                                           "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                                           '\'tests.fake_scope\')")),\n'
                                           '    ("swapped_f03_t01e", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                           '\'tests.t01e_remediation_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.f03_financing_scope\'")),\n'
                                           '    ("t01e_missing", lambda b: b.replace(b", \'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b", \'tests.r03_ppa_scope\'")),\n'
                                           '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n')],
 'tests/u1_scope.py': [("LATER_COHORTS = ('tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', "
                        "'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', "
                        "'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', "
                        "'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope')\n"
                        '\n'
                        '\n'
                        "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', "
                        "'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', "
                        "'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                        "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                        "'tests.ci_v4_full_recovery_scope')\n"
                        '\n'
                        '\n'
                        'class _Discovered:\n',
                        "LATER_COHORTS = ('tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', "
                        "'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', "
                        "'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', "
                        "'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope')\n"
                        '\n'
                        '\n'
                        "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', "
                        "'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', "
                        "'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                        "'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', "
                        "'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', "
                        "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')\n"
                        '\n'
                        '\n'
                        'class _Discovered:\n')]}


# P1 (post-#457): finite literal handoffs, applied AFTER every earlier reviewed substitution of the same file. Seven historical
# FROZEN predicates accept exactly the two named CI V4 control blobs only at the exact P0 pin; the CI V4 cohort's literal CI-path
# admission names the P0 terminal's two guard paths. No other path, blob, mode or prefix is admitted.
P1_FROZEN_EDITS = ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json')
# P2: the FULL workflow moves to the exact P0 pin through the SAME literal hooks (one more literal path; never a prefix).
P2_FROZEN_EDITS = ('.github/workflows/ci_v4_full.yml',)
HANDOFFS['tests/ci_v4_lean_b1_scope.py'] = HANDOFFS.get('tests/ci_v4_lean_b1_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v4_lean_b2_scope.py'] = HANDOFFS.get('tests/ci_v4_lean_b2_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v4_lean_b3_scope.py'] = HANDOFFS.get('tests/ci_v4_lean_b3_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v5_bootstrap_scope.py'] = HANDOFFS.get('tests/ci_v5_bootstrap_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v5_hardening_scope.py'] = HANDOFFS.get('tests/ci_v5_hardening_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v5_gate_scope.py'] = HANDOFFS.get('tests/ci_v5_gate_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v4_full_recovery_scope.py'] = HANDOFFS.get('tests/ci_v4_full_recovery_scope.py', []) + [('def _signature_ok(root, ref, closure=False):\n', 'def _p0_pins_frozen_edit(path, value, root, ref):\n    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal\n    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return value is not None and P0.supersedes(path, value, root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef _signature_ok(root, ref, closure=False):\n'), ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n', "        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')\n                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))\n               or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n")]
HANDOFFS['tests/ci_v4_scope.py'] = HANDOFFS.get('tests/ci_v4_scope.py', []) + [('        out = out | (G.CI_PATHS if G.exact_blobs_ok(root, ref) else frozenset())\n    return out\n', "        out = out | (G.CI_PATHS if G.exact_blobs_ok(root, ref) else frozenset())\n    if 'tests.ci_v4_p0_scope' in COHORT_MODULES:      # P1 (post-#457): the P0 terminal admits ITS literal guard paths (workflow + tool) only; no wildcard\n        from tests import ci_v4_p0_scope as P0\n        out = out | (P0.CI_PATHS if P0.exact_blobs_ok(root, ref) else frozenset())\n    return out\n")]# P1: the CI V4 cohort's own pins of the four replaced CI V4 paths follow the exact P0 pin only.
HANDOFFS['tests/ci_v4_scope.py'] = HANDOFFS['tests/ci_v4_scope.py'] + [('    if S.supersedes(path, value, root, ref):\n        return True\n    # Exact F03-reviewed successors of two CI V4 source paths only (the module and the internal F01 job); never a prefix.\n', "    if S.supersedes(path, value, root, ref):\n        return True\n    # P1 (post-#457): exactly four CI V4 control/test paths, only at the exact pin of the registered P0 terminal (its signature and manifest); never a prefix.\n    if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml'):\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if 'tests.ci_v4_p0_scope' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return path in P0.REPLACED and P0.supersedes(path, value, root, ref)\n    # Exact F03-reviewed successors of two CI V4 source paths only (the module and the internal F01 job); never a prefix.\n")]

# P1: the V5-3 gate defers ONLY tests/ci_v4_scope.py to the P0 terminal's own reviewed-edit verification.
HANDOFFS['tests/ci_v5_gate_scope.py'] = HANDOFFS.get('tests/ci_v5_gate_scope.py', []) + [('def reviewed_edits_ok(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        pins = manifest(root, ref).get("source_blobs", {})\n', 'def _p0_owns_handoff(path, root, ref):\n    """P1 (post-#457): the registered P0 terminal owns the further literal substitution of exactly this path (its signature holds,\n    the path is in its literal HANDOFFS and its own reviewed-edit check verifies the bytes)."""\n    try:\n        from tests.fin_v2_cohorts import COHORT_MODULES\n        if \'tests.ci_v4_p0_scope\' not in COHORT_MODULES:\n            return False\n        from tests import ci_v4_p0_scope as P0\n        return path in P0.HANDOFFS and P0.signature_ok(root, ref) and P0.reviewed_edits_ok(root, ref)\n    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n        return False\n\n\ndef reviewed_edits_ok(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        pins = manifest(root, ref).get("source_blobs", {})\n'), ('        for path in HANDOFFS:\n            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution of this shared path\n                continue\n            actual = _read(root, path, ref)\n            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n                return False\n        return N.reviewed_edits_ok(root, ref) if nxt else True\n', "        for path in HANDOFFS:\n            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution of this shared path\n                continue\n            if nxt and path == 'tests/ci_v4_scope.py' and _p0_owns_handoff(path, root, ref):      # P1: the P0 terminal verifies its literal CI-path hook\n                continue\n            actual = _read(root, path, ref)\n            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n                return False\n        return N.reviewed_edits_ok(root, ref) if nxt else True\n")]

# P1: the seven historical FROZEN byte-equality tests follow the same exact-P0-pin rule as their cohorts (two control blobs only).
HANDOFFS['tests/test_ci_v4_lean_b1_scope.py'] = HANDOFFS.get('tests/test_ci_v4_lean_b1_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
HANDOFFS['tests/test_ci_v4_lean_b2_scope.py'] = HANDOFFS.get('tests/test_ci_v4_lean_b2_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
HANDOFFS['tests/test_ci_v4_lean_b3_scope.py'] = HANDOFFS.get('tests/test_ci_v4_lean_b3_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
HANDOFFS['tests/test_ci_v5_bootstrap_scope.py'] = HANDOFFS.get('tests/test_ci_v5_bootstrap_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
HANDOFFS['tests/test_ci_v5_hardening_scope.py'] = HANDOFFS.get('tests/test_ci_v5_hardening_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
HANDOFFS['tests/test_ci_v5_gate_scope.py'] = HANDOFFS.get('tests/test_ci_v5_gate_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
HANDOFFS['tests/test_ci_v4_full_recovery_scope.py'] = HANDOFFS.get('tests/test_ci_v4_full_recovery_scope.py', []) + [('        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n', '        if path in (\'docs/ci_v4/node_split_policy.json\', \'docs/ci_v4/node_weights.json\', \'.github/workflows/ci_v4_full.yml\') and T._p0_pins_frozen_edit(\n                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin\n            continue\n        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')]
# P1: six historical chain-byte tests follow P0's further literal substitution of exactly tests/ci_v4_scope.py.
HANDOFFS['tests/test_r03_ppa_scope.py'] = HANDOFFS.get('tests/test_r03_ppa_scope.py', []) + [('    from tests import ci_v5_gate_scope as GT\n', '    from tests import ci_v5_gate_scope as GT\n    from tests import ci_v4_p0_scope as _P0\n'), ('        if GT.signature_ok() and p in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this shared path (literal, pin-exact)\n', "        if p == 'tests/ci_v4_scope.py' and _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n            assert (ROOT / p).read_bytes() == _P0.expected_handoff(ROOT, p)\n            assert T._blob((ROOT / p).read_bytes()) == _P0.manifest()['source_blobs'][p]\n            continue\n        if GT.signature_ok() and p in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this shared path (literal, pin-exact)\n")]
HANDOFFS['tests/test_r04_ppa_scope.py'] = HANDOFFS.get('tests/test_r04_ppa_scope.py', []) + [('    from tests import ci_v5_gate_scope as GT\n', '    from tests import ci_v5_gate_scope as GT\n    from tests import ci_v4_p0_scope as _P0\n'), ('        if GT.signature_ok() and p in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this shared path (literal, pin-exact)\n', "        if p == 'tests/ci_v4_scope.py' and _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n            assert (ROOT / p).read_bytes() == _P0.expected_handoff(ROOT, p)\n            assert T._blob((ROOT / p).read_bytes()) == _P0.manifest()['source_blobs'][p]\n            continue\n        if GT.signature_ok() and p in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this shared path (literal, pin-exact)\n")]
HANDOFFS['tests/test_t01e_remediation_scope.py'] = HANDOFFS.get('tests/test_t01e_remediation_scope.py', []) + [('    from tests import ci_v5_gate_scope as GT\n', '    from tests import ci_v5_gate_scope as GT\n    from tests import ci_v4_p0_scope as _P0\n'), ('        if GT.signature_ok() and p in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this shared path (literal, pin-exact)\n', "        if p == 'tests/ci_v4_scope.py' and _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n            assert (ROOT / p).read_bytes() == _P0.expected_handoff(ROOT, p)\n            assert T._blob((ROOT / p).read_bytes()) == _P0.manifest()['source_blobs'][p]\n            continue\n        if GT.signature_ok() and p in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this shared path (literal, pin-exact)\n")]
HANDOFFS['tests/test_c06_cost_workspace_scope.py'] = HANDOFFS.get('tests/test_c06_cost_workspace_scope.py', []) + [('    from tests import ci_v5_gate_scope as GT\n', '    from tests import ci_v5_gate_scope as GT\n    from tests import ci_v4_p0_scope as _P0\n'), ('        if GT.signature_ok() and path in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this CI module (literal, pin-exact)\n', "        if path == 'tests/ci_v4_scope.py' and _P0.signature_ok() and path in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n            assert (ROOT / path).read_bytes() == _P0.expected_handoff(ROOT, path)\n            assert F._blob((ROOT / path).read_bytes()) == _P0.manifest()['source_blobs'][path]\n            continue\n        if GT.signature_ok() and path in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this CI module (literal, pin-exact)\n")]
HANDOFFS['tests/test_f04_financing_scope.py'] = HANDOFFS.get('tests/test_f04_financing_scope.py', []) + [('    from tests import ci_v5_gate_scope as GT\n', '    from tests import ci_v5_gate_scope as GT\n    from tests import ci_v4_p0_scope as _P0\n'), ('        if GT.signature_ok() and path in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this CI module (literal, pin-exact)\n', "        if path == 'tests/ci_v4_scope.py' and _P0.signature_ok() and path in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n            assert (ROOT / path).read_bytes() == _P0.expected_handoff(ROOT, path)\n            assert F._blob((ROOT / path).read_bytes()) == _P0.manifest()['source_blobs'][path]\n            continue\n        if GT.signature_ok() and path in GT.HANDOFFS:      # the V5-3 gate successor further substitutes this CI module (literal, pin-exact)\n")]
HANDOFFS['tests/test_f03_financing_scope.py'] = HANDOFFS.get('tests/test_f03_financing_scope.py', []) + [('            gt = GT.signature_ok() and p in GT.HANDOFFS      # the V5-3 gate successor further substitutes this module (its literal _v5_ci_paths union)\n            assert raw == (GT.expected_handoff(ROOT, p) if gt else V5.expected_handoff(ROOT, p)) and V5._blob(raw) == (GT.manifest() if gt else V5.manifest())["source_blobs"][p]\n', '            from tests import ci_v4_p0_scope as _P0\n            if _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n                assert raw == _P0.expected_handoff(ROOT, p) and V5._blob(raw) == _P0.manifest()["source_blobs"][p]\n            else:\n                gt = GT.signature_ok() and p in GT.HANDOFFS      # the V5-3 gate successor further substitutes this module (its literal _v5_ci_paths union)\n                assert raw == (GT.expected_handoff(ROOT, p) if gt else V5.expected_handoff(ROOT, p)) and V5._blob(raw) == (GT.manifest() if gt else V5.manifest())["source_blobs"][p]\n')]
# Correction B (#458): a single read-only verdict runs inside ONE fin_v2_cohorts.call_scope (function boundary; never across a mutation).
HANDOFFS['tests/u1_scope.py'] = HANDOFFS.get('tests/u1_scope.py', []) + [('_SCOPE = []\n', "_SCOPE = []\n_JOINING = []      # Correction B: set only while the registry's call scope is being entered from scoped(); never holds a verdict\n"), ("    if _SCOPE:        # a nested enter shares the outermost memo (never outlives the outermost exit, never shared between separate outer calls)\n        yield\n        return\n    with ExitStack() as later:       # each later cohort's verdict is shared for the same outer call only (PR #414 call scope)\n", "    if _SCOPE:        # a nested enter shares the outermost memo (never outlives the outermost exit, never shared between separate outer calls)\n        yield\n        return\n    from tests import fin_v2_cohorts as _C\n    if not _C._CALL and not _JOINING:      # Correction B (#458): the outermost U1 scope IS one outer governance call; the registry's call scope\n        with ExitStack() as outer:         # is opened for exactly the same lifetime (it re-enters this function below) and closed with it\n            _JOINING.append(True)\n            try:\n                outer.enter_context(_C.call_scope())\n            finally:\n                _JOINING.pop()\n            yield\n        return\n    with ExitStack() as later:       # each later cohort's verdict is shared for the same outer call only (PR #414 call scope)\n")]
HANDOFFS['tests/ci_v4_scope.py'] = HANDOFFS.get('tests/ci_v4_scope.py', []) + [("    if not _SCOPE:\n        memo = _enclosing_call_memo()\n        if memo is None:\n            return _exact_blobs_ok(repo, ref)\n        shared = ('tests.ci_v4_scope.exact_blobs_ok',) + key\n", "    if not _SCOPE:\n        memo = _enclosing_call_memo()\n        if memo is None:\n            from tests import fin_v2_cohorts as _C\n            if _C._CALL:\n                return _exact_blobs_ok(repo, ref)\n            with _C.call_scope():      # Correction B (#458): ONE read-only verdict is ONE outer call; the scope ends when this call returns\n                return _exact_blobs_ok(repo, ref)\n        shared = ('tests.ci_v4_scope.exact_blobs_ok',) + key\n")]

# Correction B2 (post-#460): the registry's call_scope enters each cohort's scoped() BEFORE its own memo exists; the U1 scope then saw no call
# and opened a SECOND outer call (depth 2). One literal entry marker, cleared in finally, closes that entry order; nothing is cached across calls.
HANDOFFS['tests/fin_v2_cohorts.py'] = HANDOFFS.get('tests/fin_v2_cohorts.py', []) + [('_CALL = []      # one memo per OUTERMOST call_scope; empty outside every call scope (nothing is ever kept across calls)\n', "_CALL = []      # one memo per OUTERMOST call_scope; empty outside every call scope (nothing is ever kept across calls)\n_ENTERING = []      # Correction B2: set ONLY while the outermost call_scope enters the cohorts' scopes (before its memo exists); never holds a verdict\n"), ("    if _CALL:           # a nested block shares the outermost memo\n        yield\n        return\n    with contextlib.ExitStack() as scopes:\n        for m in cohorts():\n            if callable(getattr(m, 'scoped', None)):\n                scopes.enter_context(m.scoped())\n        _CALL.append({})\n", "    if _CALL or _ENTERING:      # a nested block (or a cohort scope entered by THIS call) shares the outermost memo\n        yield\n        return\n    with contextlib.ExitStack() as scopes:\n        _ENTERING.append(True)      # Correction B2: a cohort's scoped() entered here never opens a second outer call\n        try:\n            for m in cohorts():\n                if callable(getattr(m, 'scoped', None)):\n                    scopes.enter_context(m.scoped())\n        finally:\n            _ENTERING.pop()\n        _CALL.append({})\n")]
HANDOFFS['tests/u1_scope.py'] = HANDOFFS.get('tests/u1_scope.py', []) + [("    if not _C._CALL and not _JOINING:      # Correction B (#458): the outermost U1 scope IS one outer governance call; the registry's call scope\n", "    if not _C._CALL and not _C._ENTERING and not _JOINING:      # Correction B (#458) / B2: the outermost U1 scope IS one outer governance call; the registry's call scope\n")]


HANDOFFS['tests/ux_pr3b1_scope.py'] = [('def supersedes(path, value, repo=None, ref=None):\n', "def supersedes(path, value, repo=None, ref=None):\n    # The P0 terminal can delegate the one exact R1 security test source.\n    if path == 'tests/test_model_mutation_security_successor.py':\n        from tests import ci_v4_p0_scope as P0\n        return P0.r1_security_test_handoff(path, value, repo, ref)\n")]

HANDOFFS['tests/test_r02_ppa_ux_scope.py'] += [('def test_cohort_is_exact_literal_ui_only_and_leaves_backend_and_the_legacy_component_untouched():\n', '_P0_CI_PATHS = frozenset((\n    \'.github/workflows/ci_perf_guard.yml\', \'.github/workflows/ci_v4_full.yml\',\n    \'tools/ci_perf_guard.py\', \'tools/ci_full_parallel.py\',\n))\n\n\ndef _accepted_p0_ci_path(path, repo=None, ref=None):\n    from tests import ci_v4_p0_scope as P0\n    return path in _P0_CI_PATHS and P0.ci_owns(path, repo, ref)\n\n\ndef test_r02_p0_ci_handoff_is_exact_and_closes_after_mutation(tree):\n    path = \'tools/ci_full_parallel.py\'\n    with C.call_scope():\n        assert all(_accepted_p0_ci_path(p, tree) for p in _P0_CI_PATHS)\n        assert not _accepted_p0_ci_path(\'tools/unsigned.py\', tree)\n        assert not _accepted_p0_ci_path(\'.github/workflows/unsigned.yml\', tree)\n    raw = (tree / path).read_bytes()\n    (tree / path).write_bytes(raw + b"\\n")\n    with C.call_scope():\n        assert not _accepted_p0_ci_path(path, tree)\n        assert _accepted_p0_ci_path(path, tree, \'HEAD\')\n    (tree / path).write_bytes(raw)\n    with C.call_scope():\n        assert _accepted_p0_ci_path(path, tree)\n\n\ndef test_cohort_is_exact_literal_ui_only_and_leaves_backend_and_the_legacy_component_untouched():\n'), ("                and not (V5.signature_ok() and p in V5.CI_PATHS) and not (GT.signature_ok() and p in GT.CI_PATHS)]            # the one-time V5 bootstrap's literal CI paths (shadow workflow + V5 tools)", '                and not (V5.signature_ok() and p in V5.CI_PATHS) and not (GT.signature_ok() and p in GT.CI_PATHS)\n                and not _accepted_p0_ci_path(p)]')]

_CURRENT_MAP_TEST_HANDOFF = ("""        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)
""", """        assert set(cur["source_blobs"]) == set(old["source_blobs"])
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        legacy_keys = set(T.MAP_KEYS)
        if changed - legacy_keys:
            from tests import ci_v4_p0_scope as P0
            assert changed - legacy_keys <= set(P0.MAP_EXTRA_KEYS.get(p, ()))
            assert P0.exact_blobs_ok() and (ROOT / p).read_bytes() == P0.expected_map(ROOT, p)
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)
""")
HANDOFFS['tests/test_ci_v4_full_recovery_scope.py'].append(_CURRENT_MAP_TEST_HANDOFF)
HANDOFFS['tests/test_ci_v5_bootstrap_scope.py'].append(_CURRENT_MAP_TEST_HANDOFF)
HANDOFFS['tests/test_ci_v4_lean_b2_scope.py'].append(_CURRENT_MAP_TEST_HANDOFF)
HANDOFFS['tests/test_ci_v4_lean_b3_scope.py'].append(_CURRENT_MAP_TEST_HANDOFF)
HANDOFFS['tests/test_ci_v5_hardening_scope.py'].append(_CURRENT_MAP_TEST_HANDOFF)
HANDOFFS['tests/test_ci_v5_gate_scope.py'].append(_CURRENT_MAP_TEST_HANDOFF)

_CURRENT_MAP_EXPECTATION_HANDOFF = ('        assert current==expected and set(original)==set(current)\n', """        if current != expected:
            from tests import ci_v4_p0_scope as P0
            keys = P0.MAP_EXTRA_KEYS.get(path, ())
            if keys:
                approved = P0.expected_map(ROOT, path)
                assert P0.exact_blobs_ok() and (ROOT / path).read_bytes() == approved
                approved_pins = json.loads(approved)['source_blobs']
                for key in keys:
                    assert key in expected['source_blobs']
                    expected['source_blobs'][key] = approved_pins[key]
        assert current==expected and set(original)==set(current)
""")
HANDOFFS['tests/test_c06_cost_workspace_scope.py'].append(_CURRENT_MAP_EXPECTATION_HANDOFF)
HANDOFFS['tests/test_f04_financing_scope.py'].append(_CURRENT_MAP_EXPECTATION_HANDOFF)

# Correction C: bind PR2C sibling-manifest supersession to the exact verified bytes.
HANDOFFS['tests/u1_scope.py'] += [('    if path in S.INTEGRATION_MANIFESTS and S.exact_blobs_ok(repo, ref) and S.allowed_path(path, repo, ref):\n        return True\n', "    if path in S.INTEGRATION_MANIFESTS and S.exact_blobs_ok(repo, ref) and S.allowed_path(path, repo, ref):\n        root = Path(repo) if repo is not None else ROOT\n        try:\n            raw = _read(root, path, ref)\n            if _blob(raw) != value:\n                return False\n            baseline = S._base_fact(root, 'show', S.BASE + ':' + path)\n            if raw == baseline:\n                return True\n            expected = json.loads(baseline)\n            current = json.loads(raw)\n            old_pins, new_pins = expected['source_blobs'], current['source_blobs']\n            if set(old_pins) != set(new_pins) or old_pins == new_pins:\n                return False\n            old_pins.update(new_pins)\n            # PR2B's exact-source map preserves its original field order.\n            sort_keys = path != 'docs/react_migration/ux_pr2b/UX_PR2B_EXACT_SOURCE.json'\n            return raw == (json.dumps(expected, indent=2, sort_keys=sort_keys) + '\\n').encode()\n        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):\n            return False\n")]

HANDOFFS['tests/ci_v4_lean_b1_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v4_lean_b2_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v4_lean_b3_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v5_bootstrap_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v5_hardening_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v5_gate_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v4_full_recovery_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
    ),
]
HANDOFFS['tests/ci_v4_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml'):",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py', 'tests/test_ci_v4_release_gate.py'):",
    ),
]
HANDOFFS.setdefault('tests/test_ci_v4_lean_b1_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])
HANDOFFS.setdefault('tests/test_ci_v4_lean_b2_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])
HANDOFFS.setdefault('tests/test_ci_v4_lean_b3_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])
HANDOFFS.setdefault('tests/test_ci_v5_bootstrap_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])
HANDOFFS.setdefault('tests/test_ci_v5_hardening_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])
HANDOFFS.setdefault('tests/test_ci_v5_gate_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])
HANDOFFS.setdefault('tests/test_ci_v4_full_recovery_scope.py', []).extend([
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
    ),
])

# Bind each reviewed runtime and browser-lineage edit to its immutable base.
HANDOFFS.setdefault('tests/ci_v4_scope.py', []).extend([
    (
        '    try:\n'
        '        from tests import ux_pr2c_scope as S\n'
        '    except ImportError:\n'
        '        return False\n'
        '    if S.supersedes(path, value, root, ref):',
        "    if path == 'tests/fin_v2_integration_409_scope.py':\n"
        '        from tests import ci_v4_p0_scope as P0\n'
        '        return P0.supersedes(path, value, root, ref)\n'
        '    try:\n'
        '        from tests import ux_pr2c_scope as S\n'
        '    except ImportError:\n'
        '        return False\n'
        '    if S.supersedes(path, value, root, ref):',
    ),
    (
        '        return P0.supersedes(path, value, root, ref)\n'
        '    try:\n'
        '        from tests import ux_pr2c_scope as S',
        '        if P0.supersedes(path, value, root, ref):\n'
        '            return True\n'
        '    try:\n'
        '        from tests import ux_pr2c_scope as S',
    ),
])
HANDOFFS.setdefault('tests/fin_v2_integration_409_scope.py', []).extend([
    (
        '_RESULTS = {}\n'
        '\n'
        '\n',
        '',
    ),
    (
        'def _state_key(root, ref):\n'
        '    """A key that changes whenever ANY byte of the evaluated state changes.\n'
        '\n'
        '    An explicit ref is an immutable commit. For the working tree the key is HEAD + the hash of every tracked difference (``git diff HEAD --binary``,\n'
        '    staged or not, including deletions and mode changes) + the names and contents of every untracked file, so one flipped byte anywhere yields a new\n'
        '    key and the exact check runs again. A cached verdict is therefore never reused for different bytes."""\n'
        '    if ref is not None:\n'
        "        sha = _rev(root, ref + '^{commit}')\n"
        "        return None if sha is None else ('ref', str(root), sha)\n"
        "    head = _rev(root, 'HEAD')\n"
        "    digest = hashlib.sha1(_git(root, 'diff', 'HEAD', '--no-ext-diff', '--binary', '--')).hexdigest()\n"
        "    names = _git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\\0')\n"
        '    untracked = hashlib.sha1()\n'
        '    for name in sorted(n for n in names if n):\n'
        "        untracked.update(name + b'\\0')\n"
        '        try:\n'
        '            untracked.update((Path(root) / name.decode()).read_bytes())\n'
        '        except OSError:\n'
        "            untracked.update(b'<unreadable>')\n"
        "    return ('wt', str(root), head, digest, untracked.hexdigest())\n"
        '\n'
        '\n'
        '_SCOPE = []\n'
        '\n'
        '\n'
        'def exact_blobs_ok(repo=None, ref=None):\n'
        '    root = Path(repo) if repo is not None else ROOT\n'
        '    if _SCOPE:       # one outer governance call (single-threaded, nothing is written meanwhile): the same call-scope memo the older cohorts use\n'
        '        memo = _SCOPE[-1]\n'
        '        skey = (str(root), ref)\n'
        '        if skey not in memo:\n'
        '            memo[skey] = _cached_exact(root, repo, ref)\n'
        '        return memo[skey]\n'
        '    return _cached_exact(root, repo, ref)\n'
        '\n'
        '\n'
        'def _cached_exact(root, repo, ref):\n'
        '    try:\n'
        '        key = _state_key(root, ref)\n'
        '    except (OSError, subprocess.CalledProcessError):\n'
        '        return False\n'
        '    if key is None:\n'
        '        return False\n'
        '    if key not in _RESULTS:\n'
        '        if len(_RESULTS) > 64:\n'
        '            _RESULTS.clear()\n'
        '        _RESULTS[key] = _exact_blobs_ok(repo, ref)\n'
        '    return _RESULTS[key]\n'
        '\n'
        '\n',
        '_SCOPE = []\n'
        '\n'
        '\n'
        'def exact_blobs_ok(repo=None, ref=None):\n'
        '    from tests import ci_immutable_git_reads, fin_v2_cohorts\n'
        '    if not fin_v2_cohorts._CALL and not fin_v2_cohorts._ENTERING:\n'
        '        # All downstream guards share a memo for this read-only evaluation.\n'
        '        with ci_immutable_git_reads.scope(), fin_v2_cohorts.call_scope():\n'
        '            return _scoped_exact(repo, ref)\n'
        '    return _scoped_exact(repo, ref)\n'
        '\n'
        '\n'
        'def _scoped_exact(repo, ref):\n'
        '    if not _SCOPE:\n'
        '        return _exact_blobs_ok(repo, ref)\n'
        '    root = Path(repo) if repo is not None else ROOT\n'
        '    memo = _SCOPE[-1]\n'
        '    key = (str(root), ref)\n'
        '    if key not in memo:\n'
        '        memo[key] = _exact_blobs_ok(repo, ref)\n'
        '    return memo[key]\n'
        '\n'
        '\n',
    ),
])
HANDOFFS.setdefault('tests/fin_v2_wf06a_scope.py', []).extend([
    (
        'def exact_blobs_ok(repo=None, ref=None):\n'
        '    if not _SCOPE:',
        'def exact_blobs_ok(repo=None, ref=None):\n'
        '    from tests import ci_immutable_git_reads, fin_v2_cohorts\n'
        '    if not fin_v2_cohorts._CALL and not fin_v2_cohorts._ENTERING:\n'
        '        with ci_immutable_git_reads.scope(), fin_v2_cohorts.call_scope():\n'
        '            return _scoped_exact(repo, ref)\n'
        '    return _scoped_exact(repo, ref)\n'
        '\n'
        '\n'
        'def _scoped_exact(repo, ref):\n'
        '    if not _SCOPE:',
    ),
])
HANDOFFS.setdefault('tests/test_wsv2_core_scope.py', []).extend([
    (
        'def browser_contract_ok(role, acceptance):\n'
        '    marker =',
        'def browser_contract_ok(role, acceptance):\n'
        '    from tests.mutation_security_browser_lineage import verified_pre_r1_source\n'
        '\n'
        '    # Project the exact, authenticated current role onto the historical WF03\n'
        '    # state whose WS1/WF04 registration this assertion checks.\n'
        '    verified_role = verified_pre_r1_source(role, repo=F.ROOT)\n'
        '    if verified_role is not None:\n'
        '        role = verified_role\n'
        '    marker =',
    ),
    (
        'if not ((_wf03().matches(ROLE, role) or _later_state(ROLE, role, _admitted(ROLE))) and _additive_only(prior, role[:role.index(marker)])):',
        'if not ((verified_role is not None or _wf03().matches(ROLE, role) or _later_state(ROLE, role, _admitted(ROLE)))\n'
        '                and _additive_only(prior, role[:role.index(marker)])):',
    ),
    (
        "    assert not browser_contract_ok(role + line + '\\n', acceptance)\n",
        "    assert not browser_contract_ok(role + line + '\\n', acceptance)\n"
        "    for module in ('model_react_ux_pr2b_acceptance', 'model_react_pr3b1_acceptance', 'model_react_pr3b2_acceptance'):\n"
        "        later_import = f'from tests.{module} import *  # noqa: E402,F401,F403'\n"
        '        if later_import in role:\n'
        "            assert not browser_contract_ok(role.replace(later_import, ''), acceptance)\n",
    ),
])
HANDOFFS.setdefault('tests/u1_scope.py', []).extend([
    (
        '    # A registered later cohort that supersedes ``path`` has recorded its #413 BASE blob',
        "    if path == 'tests/fin_v2_integration_409_scope.py':\n"
        '        from tests import ci_v4_p0_scope as P0\n'
        '        root = Path(repo) if repo is not None else ROOT\n'
        '        if P0.signature_ok(root, ref) and path in P0.HANDOFFS:\n'
        "            # The frozen V4 baseline still carries WF06B's original integration pin.\n"
        "            prior = json.loads(_object_fact(root, 'show', P0.BASE + ':docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json'))\n"
        "            found.add(prior['source_blobs'][path])\n"
        '    # A registered later cohort that supersedes ``path`` has recorded its #413 BASE blob',
    ),
    (
        '    # PR2c Correction B: a governance manifest the exact tip cohort moves',
        "    if path == 'tests/fin_v2_integration_409_scope.py':\n"
        '        from tests import ci_v4_p0_scope as P0\n'
        '        if P0.supersedes(path, value, repo, ref):\n'
        '            return True\n'
        '    # PR2c Correction B: a governance manifest the exact tip cohort moves',
    ),
    (
        '@scoped()\n'
        'def historical_blobs(path, repo=None, ref=None):',
        '_P0_RUNTIME_HANDOFFS = frozenset((\n'
        "    'tests/fin_v2_integration_409_scope.py',\n"
        "    'tests/fin_v2_wf06a_scope.py',\n"
        "    'tests/test_wsv2_core_scope.py',\n"
        '))\n'
        '\n'
        '\n'
        '@scoped()\n'
        'def historical_blobs(path, repo=None, ref=None):',
    ),
    (
        "    if path == 'tests/fin_v2_integration_409_scope.py':\n"
        '        from tests import ci_v4_p0_scope as P0\n'
        '        root =',
        '    if path in _P0_RUNTIME_HANDOFFS:\n'
        '        from tests import ci_v4_p0_scope as P0\n'
        '        root =',
    ),
    (
        "    if path == 'tests/fin_v2_integration_409_scope.py':\n"
        '        from tests import ci_v4_p0_scope as P0\n'
        '        if P0.supersedes',
        '    if path in _P0_RUNTIME_HANDOFFS:\n'
        '        from tests import ci_v4_p0_scope as P0\n'
        '        if P0.supersedes',
    ),
    (
        "prior = json.loads(_object_fact(root, 'show', P0.BASE + ':docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json'))",
        "prior = json.loads(_git(root, 'show', P0.BASE + ':docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json'))",
    ),
])
HANDOFFS.setdefault('tests/post413_r1_scope.py', []).extend([
    (
        'def _exact_blobs_ok(repo=None, ref=None):\n',
        'def _browser_registration_follows(path, value, root, ref):\n'
        "    if path != 'tests/test_wsv2_core_scope.py':\n"
        '        return False\n'
        '    from tests import ci_v4_p0_scope as P0\n'
        '    return P0.supersedes(path, value, root, ref)\n'
        '\n'
        '\n'
        'def _exact_blobs_ok(repo=None, ref=None):\n',
    ),
    (
        'if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):',
        'if any(_blob(_read(root, p, ref)) != sha and not _browser_registration_follows(p, _blob(_read(root, p, ref)), root, ref)\n'
        '                   for p, sha in pins.items()):',
    ),
    (
        'if listed != pins:',
        'if set(listed) != set(pins) or any(listed[p] != sha and not _browser_registration_follows(p, listed[p], root, ref)\n'
        '                                                for p, sha in pins.items()):',
    ),
])
HANDOFFS.setdefault('tests/u1_scope.py', []).extend([
    (
        'and not _c06_correction_c_pin(p, current[p], root, ref) for p, sha in pins.items()):',
        'and not _c06_correction_c_pin(p, current[p], root, ref)\n'
        '               and not _p0_runtime_pin(p, current[p], root, ref) for p, sha in pins.items()):',
    ),
    (
        '@scoped()\n'
        'def historical_blobs(',
        'def _p0_runtime_pin(path, value, repo, ref):\n'
        '    if path not in _P0_RUNTIME_HANDOFFS:\n'
        '        return False\n'
        '    from tests import ci_v4_p0_scope as P0\n'
        '    return P0.supersedes(path, value, repo, ref)\n'
        '\n'
        '\n'
        '@scoped()\n'
        'def historical_blobs(',
    ),
    (
        '    if path in _P0_RUNTIME_HANDOFFS:\n'
        '        from tests import ci_v4_p0_scope as P0\n'
        '        if P0.supersedes(path, value, repo, ref):\n'
        '            return True\n',
        '',
    ),
    (
        '    if path in SUPERSEDED:\n'
        '        if not exact_blobs_ok(repo, ref):',
        '    if _p0_runtime_pin(path, value, repo, ref):\n'
        '        return True\n'
        '    if path in SUPERSEDED:\n'
        '        if not exact_blobs_ok(repo, ref):',
    ),
])
HANDOFFS['tests/ci_v4_scope.py'] += [
    (
        "    if path == 'tests/fin_v2_integration_409_scope.py':",
        "    if path in ('tests/fin_v2_integration_409_scope.py', 'tests/post413_r1_scope.py'):",
    ),
]
HANDOFFS['tests/post413_r1_scope.py'] += [
    (
        "    if path != 'tests/test_wsv2_core_scope.py':",
        "    if path not in ('tests/test_wsv2_core_scope.py', 'tests/post413_r1_scope.py'):",
    ),
]
HANDOFFS['tests/fin_v2_wf06a_scope.py'] += [
    (
        'def valid(repo=None, ref=None):\n'
        '    from tests.fin_v2_cohorts import valid as composite_valid\n'
        '    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)\n',
        'def valid(repo=None, ref=None):\n'
        '    from tests import ci_immutable_git_reads, fin_v2_cohorts\n'
        '\n'
        '    with ci_immutable_git_reads.scope(), fin_v2_cohorts.call_scope():\n'
        '        return exact_blobs_ok(repo, ref) and fin_v2_cohorts.valid(repo, ref)\n',
    ),
    (
        "    pins = manifest(repo, ref).get('source_blobs', {})\n"
        '    if path not in pins or not valid(repo, ref):\n'
        '        return False\n'
        '    raw = source.encode() if isinstance(source, str) else source\n'
        '    return source is None or _blob(raw) == pins[path]\n',
        "    pins = manifest(repo, ref).get('source_blobs', {})\n"
        '    if path not in pins:\n'
        '        return False\n'
        '    raw = source.encode() if isinstance(source, str) else source\n'
        '    if raw is not None and _blob(raw) != pins[path]:\n'
        '        return False\n'
        '    return valid(repo, ref)\n',
    ),
]
HANDOFFS['tests/fin_v2_integration_409_scope.py'] += [
    (
        'def valid(repo=None, ref=None):\n'
        '    from tests.fin_v2_cohorts import valid as composite_valid\n'
        '    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)\n',
        'def valid(repo=None, ref=None):\n'
        '    from tests import ci_immutable_git_reads, fin_v2_cohorts\n'
        '\n'
        '    with ci_immutable_git_reads.scope(), fin_v2_cohorts.call_scope():\n'
        '        return exact_blobs_ok(repo, ref) and fin_v2_cohorts.valid(repo, ref)\n',
    ),
    (
        '    root = Path(repo) if repo is not None else ROOT\n'
        '    if not exact_blobs_ok(root, ref):\n'
        '        return False\n'
        "    pins = manifest(root, ref).get('source_blobs', {})\n"
        '    if path not in pins:\n'
        '        return False\n'
        '    raw = source.encode() if isinstance(source, str) else source\n'
        '    return source is None or _blob(raw) == pins[path]\n',
        "    pins = manifest(repo, ref).get('source_blobs', {})\n"
        '    if path not in pins:\n'
        '        return False\n'
        '    raw = source.encode() if isinstance(source, str) else source\n'
        '    if raw is not None and _blob(raw) != pins[path]:\n'
        '        return False\n'
        '    return exact_blobs_ok(repo, ref)\n',
    ),
]
HANDOFFS['tests/fin_v2_cohorts.py'] += [
    (
        '    try:\n'
        '        with contextlib.ExitStack() as scopes:\n'
        '            for m in mods:',
        '    try:\n'
        '        from tests import ci_immutable_git_reads\n'
        '\n'
        '        with contextlib.ExitStack() as scopes:\n'
        '            scopes.enter_context(ci_immutable_git_reads.scope())\n'
        '            for m in mods:',
    ),
]
HANDOFFS.setdefault('tests/test_fin_v2_integration_409_scope.py', []).append((
        '    (wt / "evidence" / "merge-tree.json").write_text("{}")\n'
        '    assert INT.exact_blobs_ok(wt) is True                                                  # what the hosted workflows write before the tests run\n',
        '    from tools.ci_merge_tree_guard import prove_merge_tree\n'
        '\n'
        '    proof = wt / "evidence" / "merge-tree.json"\n'
        '    proof.write_text("{}")\n'
        '    assert INT.exact_blobs_ok(wt) is False  # a JSON filename alone supplies no attestation\n'
        '    proof.write_text(json.dumps(prove_merge_tree(git("rev-parse", "HEAD", cwd=wt), git_run=lambda *args: git(*args, cwd=wt))))\n'
        '    assert INT.exact_blobs_ok(wt) is True   # exact source evidence generated by the same tool used in CI\n',
))
HANDOFFS.setdefault('tests/u1_scope.py', []).append((
        "    'tests/fin_v2_wf06a_scope.py',\n"
        "    'tests/test_wsv2_core_scope.py',\n"
        '))\n'
        '\n'
        '\n'
        'def _p0_runtime_pin(',
        "    'tests/fin_v2_wf06a_scope.py',\n"
        "    'tests/test_fin_v2_integration_409_scope.py',\n"
        "    'tests/test_wsv2_core_scope.py',\n"
        '))\n'
        '\n'
        '\n'
        'def _p0_runtime_pin(',
))
HANDOFFS['tests/fin_v2_wf06a_scope.py'] += [
    (
        "        changed = _git(root, 'diff', '--name-only', BASE, *([ref] if ref else []), '--').decode().splitlines()\n",
        "        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()\n"
        '        # Git lists each changed path once. A duplicated path is invalid input,\n'
        '        # even if a later successor owns the real change at that path.\n'
        '        if len(changed) != len(set(changed)):\n'
        '            return False\n',
    ),
    (
        "    return exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value\n",
        "    pins = manifest(repo, ref).get('source_blobs', {})\n"
        '    return path in pins and pins[path] == value and exact_blobs_ok(repo, ref)\n',
    ),
]
HANDOFFS['tests/fin_v2_integration_409_scope.py'] += [
    (
        '    if not _delegable(path) or not exact_blobs_ok(repo, ref):\n'
        '        return False\n'
        '    root = Path(repo) if repo is not None else ROOT\n'
        "    pins = manifest(root, ref).get('source_blobs', {})\n"
        '    if path in pins:\n'
        '        return pins[path] == value\n'
        '    who = _union(root).get(path, [])\n'
        '    return len(who) == 1 and _immutable_blob(str(root), SOURCES[who[0]][0], path) == value\n',
        '    if not _delegable(path):\n'
        '        return False\n'
        '    root = Path(repo) if repo is not None else ROOT\n'
        "    pins = manifest(root, ref).get('source_blobs', {})\n"
        '    if path in pins:\n'
        '        return pins[path] == value and exact_blobs_ok(repo, ref)\n'
        '    try:\n'
        '        who = _union(root).get(path, [])\n'
        '    except (OSError, subprocess.CalledProcessError):\n'
        '        return False\n'
        '    return (len(who) == 1 and _immutable_blob(str(root), SOURCES[who[0]][0], path) == value\n'
        '            and exact_blobs_ok(repo, ref))\n',
    ),
]
HANDOFFS['tests/fin_v2_wf06a_scope.py'] += [
    (
        "        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()\n"
        '        # Git lists each changed path once. A duplicated path is invalid input,\n'
        '        # even if a later successor owns the real change at that path.\n'
        '        if len(changed) != len(set(changed)):\n'
        '            return False\n',
        "        comparison = ('--no-renames', BASE, *([ref] if ref else []), '--')\n"
        "        changed = _git(root, 'diff', '--name-only', *comparison).decode().splitlines()\n"
        '        # A list entry alone is not evidence of a delta. Check it against the\n'
        '        # NUL-delimited status records for the same base, subject and pathspec.\n'
        "        records = _git(root, 'diff', '--name-status', '-z', *comparison).decode().split('\\0')\n"
        '        if records[-1] or len(records) != 2 * len(changed) + 1 or records[1:-1:2] != changed or len(changed) != len(set(changed)):\n'
        '            return False\n',
    ),
]
HANDOFFS['tests/fin_v2_cohorts.py'] += [
    (
        'def protected_blobs(repo=None, ref=None):\n'
        '    if not valid(repo, ref):\n'
        '        return {}\n'
        '    merged = {}\n'
        '    for m in cohorts():\n'
        "        for p, b in m.manifest(repo, ref).get('source_blobs', {}).items():\n"
        "            if p.startswith(('financial_engine/', 'finco_core/', 'domain/')):\n"
        '                merged[p] = b\n'
        '    return merged\n',
        'def protected_blobs(repo=None, ref=None):\n'
        '    from tests import ci_immutable_git_reads\n'
        '\n'
        '    root = Path(repo) if repo is not None else ROOT\n'
        '    if ref is not None:\n'
        '        # Snapshot a symbolic ref on every call. The verdict and each manifest\n'
        '        # read must describe the same commit, even if the ref moves afterward.\n'
        '        try:\n'
        "            ref = _git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()\n"
        '        except (OSError, ValueError, subprocess.CalledProcessError):\n'
        '            return {}\n'
        '    with ci_immutable_git_reads.scope(), call_scope():\n'
        '        if not valid(root, ref):\n'
        '            return {}\n'
        '        merged = {}\n'
        '        for m in cohorts():\n'
        "            for p, b in m.manifest(root, ref).get('source_blobs', {}).items():\n"
        "                if p.startswith(('financial_engine/', 'finco_core/', 'domain/')):\n"
        '                    merged[p] = b\n'
        '        return merged\n',
    ),
]
HANDOFFS['tests/fin_v2_cohorts.py'] += [
    (
        '    with contextlib.ExitStack() as scopes:\n'
        '        _ENTERING.append(True)',
        '    from tests import ci_immutable_git_reads\n'
        '\n'
        '    with contextlib.ExitStack() as scopes:\n'
        '        scopes.enter_context(ci_immutable_git_reads.scope())\n'
        '        _ENTERING.append(True)',
    ),
]
HANDOFFS['tests/u1_scope.py'] += [
    (
        '    with ExitStack() as later:       # one verdict per later cohort for this U1 check (dropped on exit)\n'
        '        for m in _later_modules():',
        '    from tests import ci_immutable_git_reads\n'
        '\n'
        '    with ExitStack() as later:       # one verdict per later cohort for this U1 check (dropped on exit)\n'
        '        later.enter_context(ci_immutable_git_reads.scope())\n'
        '        for m in _later_modules():',
    ),
]

HANDOFFS['tests/post413_r1_scope.py'] += [
    (
        "    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value\n",
        '    if path not in SUPERSEDED:\n'
        '        return False\n'
        "    pin = manifest(repo, ref).get('source_blobs', {}).get(path)\n"
        '    return pin is not None and pin == value and exact_blobs_ok(repo, ref)\n',
    ),
    (
        '    from tests.fin_v2_cohorts import valid as composite_valid\n'
        '    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)\n',
        '    from tests import fin_v2_cohorts\n'
        '\n'
        '    with fin_v2_cohorts.call_scope():\n'
        '        return exact_blobs_ok(repo, ref) and fin_v2_cohorts.valid(repo, ref)\n',
    ),
]




HANDOFFS['tests/ux_pr2b_scope.py'] = [
    (
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok4(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref) for p in old if new[p]!=old[p]):\n',
        '            from tests import ci_v4_p0_scope as P0\n'
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok4(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref)\n'
        '                   and not P0.o1_historical_test_pin(path, p, new[p], root, ref) for p in old if new[p]!=old[p]):\n',
    ),
]

HANDOFFS['tests/ux_pr2c_scope.py'] = [
    (
        '            if any(new[p] != old[p] and (p not in pins or new[p] != pins[p]) and not _pr3b1_pin(p, new[p], root, ref) for p in old):\n',
        '            from tests import ci_v4_p0_scope as P0\n'
        '            if any(new[p] != old[p] and (p not in pins or new[p] != pins[p]) and not _pr3b1_pin(p, new[p], root, ref)\n'
        '                   and not P0.o1_historical_test_pin(sibling, p, new[p], root, ref) for p in old):\n',
    ),
]

HANDOFFS['tests/ux_pr1_scope.py'] = [
    (
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok2(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref) for p in old if new[p]!=old[p]):\n',
        '            from tests import ci_v4_p0_scope as P0\n'
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok2(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref)\n'
        '                   and not P0.o1_historical_test_pin(path, p, new[p], root, ref) for p in old if new[p]!=old[p]):\n',
    ),
]

HANDOFFS['tests/ux_pr2a_scope.py'] = [
    (
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok3(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref) for p in old if new[p]!=old[p]):\n',
        '            from tests import ci_v4_p0_scope as P0\n'
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok3(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref)\n'
        '                   and not P0.o1_historical_test_pin(path, p, new[p], root, ref) for p in old if new[p]!=old[p]):\n',
    ),
    (
        '    return exact_blobs_ok(repo,ref) and composite_valid(repo,ref)\n'
        'def matches(path,source=None,*,repo=None,ref=None):\n',
        '    return exact_blobs_ok(repo,ref) and composite_valid(repo,ref)\n'
        '\n'
        '\n'
        '_unshared_exact_blobs_ok = exact_blobs_ok\n'
        '\n'
        '\n'
        'def exact_blobs_ok(repo=None, ref=None):\n'
        '    from tests.fin_v2_cohorts import call_scope\n'
        '\n'
        '    # Each standalone check gets one read-only delegation scope. Its verdicts\n'
        '    # are discarded before a caller can mutate the worktree and check again.\n'
        '    with call_scope():\n'
        '        return _unshared_exact_blobs_ok(repo, ref)\n'
        '\n'
        '\n'
        'def matches(path,source=None,*,repo=None,ref=None):\n',
    ),
]



HANDOFFS['tests/post413_r1_scope.py'] += [
    (
        "    if path not in ('tests/test_wsv2_core_scope.py', 'tests/post413_r1_scope.py'):\n",
        "    if path not in ('tests/test_wsv2_core_scope.py', 'tests/post413_r1_scope.py', 'tests/test_post413_r1_scope.py'):\n",
    ),
]







HANDOFFS['tests/test_post413_r1_scope.py'] = [
    (
        '\n'
        '\n'
        'def test_positive_cohort_is_exact_registered_and_closed():\n'
        '    assert R.exact_blobs_ok() and R.valid() and C.valid() and U.exact_blobs_ok()\n',
        '\n'
        '\n'
        '@C.call_scope()\n'
        'def test_positive_cohort_is_exact_registered_and_closed():\n'
        '    assert R.exact_blobs_ok() and R.valid() and C.valid() and U.exact_blobs_ok()\n',
    ),
]


HANDOFFS['tests/test_post413_o1_scope.py'] = [
    (
        '"""\n'
        'import ast\n'
        'from contextlib import ExitStack\n'
        'import json\n'
        'from pathlib import Path\n',
        '"""\n'
        'import ast\n'
        'import json\n'
        'from pathlib import Path\n',
    ),
    (
        '\n'
        '\n'
        'def test_positive_cohort_is_exact_registered_and_closed():\n'
        '    assert O.exact_blobs_ok() and O.valid() and C.valid() and U.exact_blobs_ok()\n',
        '\n'
        '\n'
        '@C.call_scope()\n'
        'def test_positive_cohort_is_exact_registered_and_closed():\n'
        '    assert O.exact_blobs_ok() and O.valid() and C.valid() and U.exact_blobs_ok()\n',
    ),
    (
        '\n'
        'def _u2_signed_later_pins(repo=None, ref=None):\n'
        '    from tests import u2_scope as U2\n'
        '    root = Path(repo) if repo is not None else O.ROOT\n',
        '\n'
        'def _u2_signed_later_pins(repo=None, ref=None):\n'
        '    from tests import c06_cost_workspace_scope as C06\n'
        '    from tests import u2_scope as U2\n'
        '    root = Path(repo) if repo is not None else O.ROOT\n',
    ),
    (
        "    signed = U2.manifest(root, ref)['source_blobs']\n"
        "    historical = json.loads(_git(root, 'show', O.BASE + ':' + U2.MANIFEST))['source_blobs']\n"
        '    return {p: signed[p] for p in U2_LATER_PRESENTATION\n'
        '            if p not in O.OWNED_PATHS and p in U2.PRESENTATION_PATHS and p in U2.SUPERSEDED\n'
        '            and signed[p] != historical.get(p) and U2.supersedes(p, signed[p], root, ref)\n'
        '            and U2._blob(U2._read(root, p, ref)) == signed[p]}\n'
        '\n'
        '\n',
        "    signed = U2.manifest(root, ref)['source_blobs']\n"
        "    historical = json.loads(_git(root, 'show', O.BASE + ':' + U2.MANIFEST))['source_blobs']\n"
        "    c06_base = C06.manifest(root, ref).get('base_blobs', {})\n"
        '\n'
        '    def follows_u2(path):\n'
        '        current = U2._blob(U2._read(root, path, ref))\n'
        '        return current == signed[path] or (c06_base.get(path) == signed[path] and C06.supersedes(path, current, root, ref))\n'
        '\n'
        '    return {p: signed[p] for p in U2_LATER_PRESENTATION\n'
        '            if p not in O.OWNED_PATHS and p in U2.PRESENTATION_PATHS and p in U2.SUPERSEDED\n'
        '            and signed[p] != historical.get(p) and U2.supersedes(p, signed[p], root, ref)\n'
        '            and follows_u2(p)}\n'
        '\n'
        '\n',
    ),
    (
        '\n'
        'def _audit_shared_sibling_pins(repo=None, ref=None):\n'
        '    # No mutation inside this outer call; every verdict is discarded before any tamper control runs.\n'
        '    with ExitStack() as scopes:\n'
        '        for cohort in C.cohorts():\n'
        "            if callable(getattr(cohort, 'scoped', None)):\n"
        '                scopes.enter_context(cohort.scoped())\n'
        '        return _audit_shared_sibling_pins_in_scope(repo, ref)\n'
        '\n'
        '\n'
        'def _audit_shared_sibling_pins_in_scope(repo, ref):\n'
        '    root = Path(repo) if repo is not None else O.ROOT\n'
        "    pins = O.manifest(root, ref)['source_blobs']\n",
        '\n'
        'def _audit_shared_sibling_pins(repo=None, ref=None):\n'
        '    root = Path(repo) if repo is not None else O.ROOT\n'
        '    if ref is not None:\n'
        "        ref = _git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').strip()\n"
        '    # Reuse immutable Git reads in this audit and discard every verdict before any tamper control writes.\n'
        '    with C.call_scope():\n'
        '        return _audit_shared_sibling_pins_in_scope(root, ref)\n'
        '\n'
        '\n'
        'def _audit_shared_sibling_pins_in_scope(repo, ref):\n'
        '    from tests import ci_v4_p0_scope as P0\n'
        '\n'
        '    root = Path(repo) if repo is not None else O.ROOT\n'
        "    pins = O.manifest(root, ref)['source_blobs']\n",
    ),
    (
        '        ux2_moved = (moved & set(later_ux2)) - ux3_moved\n'
        "        ux_moved = (moved & set(later_ux)) - ux2_moved - ux3_moved       # a path UX-PR2a supersedes is judged against PR2a's pin, not PR1's\n"
        '        assert moved == own_moved | ci_moved | u2_moved | ux_moved | ux2_moved | ux3_moved, (manifest, sorted(moved - own_moved - ci_moved - u2_moved - ux_moved - ux2_moved))\n'
        "        assert all(now['source_blobs'][p] == pins[p] for p in own_moved), manifest\n"
        "        assert all(now['source_blobs'][p] == later_u2[p] for p in u2_moved), manifest\n",
        '        ux2_moved = (moved & set(later_ux2)) - ux3_moved\n'
        "        ux_moved = (moved & set(later_ux)) - ux2_moved - ux3_moved       # a path UX-PR2a supersedes is judged against PR2a's pin, not PR1's\n"
        '        p0_moved = moved & {P0.R1_SECURITY_TEST} if manifest == P0.R1_MAP else set()\n'
        "        assert all(P0.r1_security_test_handoff(p, now['source_blobs'][p], root, ref) for p in p0_moved), manifest\n"
        '        admitted = own_moved | ci_moved | u2_moved | ux_moved | ux2_moved | ux3_moved | p0_moved\n'
        '        assert moved == admitted, (manifest, sorted(moved - admitted))\n'
        "        assert all(now['source_blobs'][p] == pins[p] for p in own_moved), manifest\n"
        "        assert all(now['source_blobs'][p] == later_u2[p] for p in u2_moved), manifest\n",
    ),
]


HANDOFFS['tests/post413_o1_scope.py'] = [
    (
        '\n'
        '\n'
        'def _exact_blobs_ok(repo=None, ref=None):\n'
        '    root = Path(repo) if repo is not None else ROOT\n',
        '\n'
        '\n'
        'def _pin_matches(path, actual, expected, root, ref):\n'
        '    if actual == expected:\n'
        '        return True\n'
        "    if path not in ('tests/post413_o1_scope.py', 'tests/test_post413_o1_scope.py', 'tests/test_post413_r1_scope.py'):\n"
        '        return False\n'
        '    from tests import ci_v4_p0_scope as P0\n'
        '    return P0.supersedes(path, actual, root, ref)\n'
        '\n'
        '\n'
        'def _exact_blobs_ok(repo=None, ref=None):\n'
        '    root = Path(repo) if repo is not None else ROOT\n',
    ),
    (
        '        # 3. one exact blob per owned path\n'
        '        if ref is None:\n'
        '            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n'
        '                return False\n'
        '        else:\n',
        '        # 3. one exact blob per owned path\n'
        '        if ref is None:\n'
        '            if any(not _pin_matches(p, _blob(_read(root, p, ref)), sha, root, ref) for p, sha in pins.items()):\n'
        '                return False\n'
        '        else:\n',
    ),
    (
        "                meta, name = line.split('\\t', 1)\n"
        '                listed[name] = meta.split()[2]\n'
        '            if listed != pins:\n'
        '                return False\n'
        "        # 4. no protected prefix ever moved since BASE (paths this cohort does not own are the composite registry's responsibility)\n",
        "                meta, name = line.split('\\t', 1)\n"
        '                listed[name] = meta.split()[2]\n'
        '            if set(listed) != set(pins) or any(not _pin_matches(p, listed[p], sha, root, ref) for p, sha in pins.items()):\n'
        '                return False\n'
        "        # 4. no protected prefix ever moved since BASE (paths this cohort does not own are the composite registry's responsibility)\n",
    ),
    (
        'def supersedes(path, value, repo=None, ref=None):\n'
        '    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""\n'
        "    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value\n"
        '\n'
        '\n',
        'def supersedes(path, value, repo=None, ref=None):\n'
        '    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""\n'
        '    if path not in SUPERSEDED:\n'
        '        return False\n'
        "    pin = manifest(repo, ref).get('source_blobs', {}).get(path)\n"
        '    if pin is None or pin != value:\n'
        '        return False\n'
        '    from tests import ci_v4_p0_scope as P0\n'
        '\n'
        '    with P0.scoped():\n'
        "        return exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value\n"
        '\n'
        '\n',
    ),
]

HANDOFFS['tests/test_wsv2_core_scope.py'] = [
    (
        '\n'
        '\n'
        'def test_original_presentation_and_security_dictionaries_are_immutable_and_individually_admitted():\n'
        "    old = ast.parse(F._read(F.ROOT, 'tests/model_mutation_security_successor.py', F.AUTHORIZATION_HEAD))\n",
        '\n'
        '\n'
        '@C.call_scope()\n'
        'def test_original_presentation_and_security_dictionaries_are_immutable_and_individually_admitted():\n'
        "    old = ast.parse(F._read(F.ROOT, 'tests/model_mutation_security_successor.py', F.AUTHORIZATION_HEAD))\n",
    ),
    (
        '\n'
        'def browser_contract_ok(role, acceptance):\n'
        "    marker = '# WS1 Workspace V2'\n"
        "    expected = 'from tests.model_react_wsv2_acceptance import *  # noqa: E402,F401,F403'\n",
        '\n'
        'def browser_contract_ok(role, acceptance):\n'
        '    from tests.mutation_security_browser_lineage import verified_pre_r1_source\n'
        '\n'
        '    # Project the exact, authenticated current role onto the historical WF03\n'
        '    # state whose WS1/WF04 registration this assertion checks.\n'
        '    verified_role = verified_pre_r1_source(role, repo=F.ROOT)\n'
        '    if verified_role is not None:\n'
        '        role = verified_role\n'
        "    marker = '# WS1 Workspace V2'\n"
        "    expected = 'from tests.model_react_wsv2_acceptance import *  # noqa: E402,F401,F403'\n",
    ),
    (
        '        # (no original line removed or changed), and only while the WF-03 cohort pins this exact module.\n'
        '        # #419 Correction K: or the exact pin of the registered, exact later cohort (R1 two-tab acceptance) - still ADDITIVE ONLY.\n'
        '        if not ((_wf03().matches(ROLE, role) or _later_state(ROLE, role, _admitted(ROLE))) and _additive_only(prior, role[:role.index(marker)])):\n'
        '            return False\n'
        '    tree = ast.parse(acceptance)\n',
        '        # (no original line removed or changed), and only while the WF-03 cohort pins this exact module.\n'
        '        # #419 Correction K: or the exact pin of the registered, exact later cohort (R1 two-tab acceptance) - still ADDITIVE ONLY.\n'
        '        if not ((verified_role is not None or _wf03().matches(ROLE, role) or _later_state(ROLE, role, _admitted(ROLE)))\n'
        '                and _additive_only(prior, role[:role.index(marker)])):\n'
        '            return False\n'
        '    tree = ast.parse(acceptance)\n',
    ),
    (
        "    assert not browser_contract_ok(role.replace(line, ''), acceptance)\n"
        "    assert not browser_contract_ok(role + line + '\\n', acceptance)\n"
        "    assert not browser_contract_ok(role, acceptance.replace('def ' + TESTS[1], 'def missing_test'))\n"
        "    assert not browser_contract_ok(role, acceptance.replace('def ' + TESTS[1], '@pytest.mark.skip\\ndef ' + TESTS[1]))\n",
        "    assert not browser_contract_ok(role.replace(line, ''), acceptance)\n"
        "    assert not browser_contract_ok(role + line + '\\n', acceptance)\n"
        "    for module in ('model_react_ux_pr2b_acceptance', 'model_react_pr3b1_acceptance', 'model_react_pr3b2_acceptance'):\n"
        "        later_import = f'from tests.{module} import *  # noqa: E402,F401,F403'\n"
        '        if later_import in role:\n'
        "            assert not browser_contract_ok(role.replace(later_import, ''), acceptance)\n"
        "    assert not browser_contract_ok(role, acceptance.replace('def ' + TESTS[1], 'def missing_test'))\n"
        "    assert not browser_contract_ok(role, acceptance.replace('def ' + TESTS[1], '@pytest.mark.skip\\ndef ' + TESTS[1]))\n",
    ),
    (
        '\n'
        'def test_ws2_admission_is_not_a_wildcard(monkeypatch):\n'
        "    for rogue in ('app/v2/new_writer.py', 'frontend/src/app/editing/rogue.ts', 'frontend/src/app/rogue.tsx', 'tests/new_financial_test.py'):\n"
        '        assert not F._ws2_allows(rogue, F.ROOT, None), rogue\n'
        '    original = F._git\n'
        '\n',
        '\n'
        'def test_ws2_admission_is_not_a_wildcard(monkeypatch):\n'
        '    with C.call_scope():\n'
        "        for rogue in ('app/v2/new_writer.py', 'frontend/src/app/editing/rogue.ts', 'frontend/src/app/rogue.tsx', 'tests/new_financial_test.py'):\n"
        '            assert not F._ws2_allows(rogue, F.ROOT, None), rogue\n'
        '    original = F._git\n'
        '\n',
    ),
    (
        'def test_wf06a_hook_admits_only_the_closed_cohort_and_only_while_it_is_exact(monkeypatch):\n'
        '    from tests import fin_v2_wf06a_scope as WF06A\n'
        '    assert F.exact_blobs_ok()\n'
        '    for owned in sorted(WF06A.PRESENTATION_PATHS | WF06A.GOVERNANCE_PATHS):\n'
        '        assert F._wf06a_allows(owned, F.ROOT, None), owned\n'
        "    for stranger in ('frontend/src/app/NewUnreviewed.tsx', 'frontend/src/app/WorkspaceView.tsx', 'app/v2/router.py', 'financial_engine/x.py',\n"
        "                     'tests/test_new_unreviewed.py'):\n"
        '        assert not F._wf06a_allows(stranger, F.ROOT, None), stranger\n'
        '    git = F._git\n'
        '\n',
        'def test_wf06a_hook_admits_only_the_closed_cohort_and_only_while_it_is_exact(monkeypatch):\n'
        '    from tests import fin_v2_wf06a_scope as WF06A\n'
        '    with C.call_scope():\n'
        '        assert F.exact_blobs_ok()\n'
        '        for owned in sorted(WF06A.PRESENTATION_PATHS | WF06A.GOVERNANCE_PATHS):\n'
        '            assert F._wf06a_allows(owned, F.ROOT, None), owned\n'
        "        for stranger in ('frontend/src/app/NewUnreviewed.tsx', 'frontend/src/app/WorkspaceView.tsx', 'app/v2/router.py', 'financial_engine/x.py',\n"
        "                         'tests/test_new_unreviewed.py'):\n"
        '            assert not F._wf06a_allows(stranger, F.ROOT, None), stranger\n'
        '    git = F._git\n'
        '\n',
    ),
]

HANDOFFS['tests/test_post413_o1_scope.py'].append((
    "    _flip(wt / path)\n"
    "    assert not O.exact_blobs_ok(wt)\n"
    "    assert not O.matches(path, (wt / path).read_bytes(), repo=wt)\n"
    "    _git(wt, 'checkout', '--', path)\n"
    "    assert O.exact_blobs_ok(wt)                                                                  # restoring the bytes restores validity\n",
    "    _flip(wt / path)\n"
    "    with C.call_scope():\n"
    "        assert not O.exact_blobs_ok(wt)\n"
    "        assert not O.matches(path, (wt / path).read_bytes(), repo=wt)\n"
    "    _git(wt, 'checkout', '--', path)\n"
    "    with C.call_scope():\n"
    "        assert O.exact_blobs_ok(wt)\n",
))
HANDOFFS['tests/test_wsv2_core_scope.py'].extend([
    (
        'def test_browser_registration_preserves_original_role_and_exact_new_exports():\n',
        '@C.call_scope()\ndef test_browser_registration_preserves_original_role_and_exact_new_exports():\n',
    ),
    (
        'def test_owner_approved_acceptance_exact_pins_identity_and_rejection():\n',
        '@C.call_scope()\ndef test_owner_approved_acceptance_exact_pins_identity_and_rejection():\n',
    ),
])


HANDOFFS['tests/test_wsv2_core_scope.py'].append((
    '@C.call_scope()\n'
    'def test_owner_approved_acceptance_exact_pins_identity_and_rejection():\n'
    '    assert set(S.WSV2_ACCEPTANCE_SUCCESSORS) == OWNER_APPROVED_ACCEPTANCE\n'
    '    assert OWNER_APPROVED_ACCEPTANCE <= F.OWNED_PATHS\n'
    "    pins = F.manifest()['source_blobs']\n"
    '    for path in OWNER_APPROVED_ACCEPTANCE:\n'
    '        assert (pins[path] in {S.WSV2_ACCEPTANCE_SUCCESSORS[path], S.WSV2_EDITING_SUCCESSORS.get(path)}   # the WS-1 state or the exact reviewed WS-2 state\n'
    '                or _wf03().matches(path, (F.ROOT / path).read_bytes()))                                 # or the exact WF-03 state while its cohort is valid\n'
    '        original = F._read(F.ROOT, path, F.AUTHORIZATION_HEAD).decode()\n'
    '        current = F._read(F.ROOT, path, None).decode()\n'
    '        from tests import u1_scope as U1\n'
    '        # the cohort pin, or (PR #413) the exact later U1 state of a path U1 supersedes while the cohort pin still equals the BASE blob U1 recorded\n'
    '        assert (S.git_blob(current) == pins[path]\n'
    '                or (path in U1.SUPERSEDED and U1.supersedes(path, S.git_blob(current)) and U1.base_blob(path) == pins[path])), path\n'
    '        def tests(text):\n'
    '            return [(n.name, [ast.dump(d, include_attributes=False) for d in n.decorator_list])\n'
    "                    for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')]\n"
    '        assert tests(original) == tests(current), path\n'
    "        assert 'pytest.mark.skip' not in current and 'pytest.mark.xfail' not in current\n"
    '        if path in S.BLOBS:\n'
    '            sources = {p: (S.ROOT / p).read_text() for p in S.BLOBS}\n'
    '            assert S.violations(sources) == []\n'
    '            mutated = dict(sources)\n'
    "            mutated[path] = current + '\\n'\n"
    '            assert S.violations(mutated)\n'
,
    'def _owner_approved_acceptance_pin(path, pin):\n'
    '    from tests import u1_scope as U1, ux_pr1_scope as UX1, ux_pr3b1_scope as UX3B1\n'
    '\n'
    '    owner = None\n'
    '    predecessor = WS1_ACCEPTED_MERGE\n'
    '    for cohort, ref in (\n'
    "        (U1, '2c63750929477c618444e9d056030e054cc3a41c'),\n"
    "        (UX1, '713c0daf434dd79616f5a07451de6accddde93e0'),\n"
    "        (UX3B1, '4e22f330d97eec66befcbb5df6dc4e1529ae6835'),\n"
    '    ):\n'
    '        if path not in cohort.SUPERSEDED:\n'
    '            continue\n'
    "        F._git(F.ROOT, 'merge-base', '--is-ancestor', predecessor, cohort.BASE)\n"
    "        F._git(F.ROOT, 'merge-base', '--is-ancestor', cohort.BASE, ref)\n"
    '        signed = cohort.manifest(ref=ref)\n'
    "        assert signed['base'] == cohort.BASE and signed['base_blobs'][path] == pin\n"
    "        assert F._git(F.ROOT, 'ls-tree', cohort.BASE, '--', path).decode().strip() == f'100644 blob {pin}\\t{path}'\n"
    "        pin = signed['source_blobs'][path]\n"
    "        assert F._git(F.ROOT, 'ls-tree', ref, '--', path).decode().strip() == f'100644 blob {pin}\\t{path}'\n"
    '        predecessor, owner = ref, cohort\n'
    "    F._git(F.ROOT, 'merge-base', '--is-ancestor', predecessor, 'HEAD')\n"
    '    if owner is not None:\n'
    '        assert owner.exact_blobs_ok() and owner.supersedes(path, pin)\n'
    '    return pin\n'
    '\n'
    '\n'
    '@C.call_scope()\n'
    'def test_owner_approved_acceptance_exact_pins_identity_and_rejection():\n'
    '    assert set(S.WSV2_ACCEPTANCE_SUCCESSORS) == OWNER_APPROVED_ACCEPTANCE\n'
    '    assert OWNER_APPROVED_ACCEPTANCE <= F.OWNED_PATHS\n'
    "    pins = F.manifest()['source_blobs']\n"
    '    for path in OWNER_APPROVED_ACCEPTANCE:\n'
    '        assert (pins[path] in {S.WSV2_ACCEPTANCE_SUCCESSORS[path], S.WSV2_EDITING_SUCCESSORS.get(path)}   # the WS-1 state or the exact reviewed WS-2 state\n'
    '                or _wf03().matches(path, (F.ROOT / path).read_bytes()))                                 # or the exact WF-03 state while its cohort is valid\n'
    '        original = F._read(F.ROOT, path, F.AUTHORIZATION_HEAD).decode()\n'
    '        current = F._read(F.ROOT, path, None).decode()\n'
    '        assert S.git_blob(current) == _owner_approved_acceptance_pin(path, pins[path]), path\n'
    '        def tests(text):\n'
    '            return [(n.name, [ast.dump(d, include_attributes=False) for d in n.decorator_list])\n'
    "                    for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')]\n"
    '        assert tests(original) == tests(current), path\n'
    "        assert 'pytest.mark.skip' not in current and 'pytest.mark.xfail' not in current\n"
    '        if path in S.BLOBS:\n'
    '            sources = {p: (S.ROOT / p).read_text() for p in S.BLOBS}\n'
    '            assert S.violations(sources) == []\n'
    '            mutated = dict(sources)\n'
    "            mutated[path] = current + '\\n'\n"
    '            assert S.violations(mutated)\n'

))


HANDOFFS['tests/test_wsv2_core_scope.py'].append((
    "    monkeypatch.setattr(F, '_read', altered)\n"
    "    assert not F.exact_blobs_ok() and not C.valid()\n\n\n"
    "@pytest.mark.parametrize('drop', (False, True))\n",
    "    monkeypatch.setattr(F, '_read', altered)\n"
    "    with C.call_scope():\n"
    "        assert not F.exact_blobs_ok() and not C.valid()\n\n\n"
    "@pytest.mark.parametrize('drop', (False, True))\n",
))


HANDOFFS['tests/post413_o1_scope.py'].append((
    'def _exact_blobs_ok(repo=None, ref=None):\n'
    '    root = Path(repo) if repo is not None else ROOT\n',
    'def _exact_blobs_ok(repo=None, ref=None):\n'
    '    from tests import ci_v4_p0_scope as P0, ci_v4_scope\n'
    '\n'
    '    # All paths in this check describe one evaluated checkout or commit.\n'
    '    with P0.scoped(), ci_v4_scope.scoped():\n'
    '        return _inspect_exact_blobs(repo, ref)\n'
    '\n'
    '\n'
    'def _inspect_exact_blobs(repo, ref):\n'
    '    root = Path(repo) if repo is not None else ROOT\n',
))


HANDOFFS['tests/test_post413_o1_scope.py'].append((
    '    assert _ux_pr1_signed_later_pins(wt)[path] == UX3.effective_pins(wt)[path]\n',
    '    with C.call_scope():\n'
    '        assert _ux_pr1_signed_later_pins(wt)[path] == UX3.effective_pins(wt)[path]\n',
))


HANDOFFS['tests/test_post413_o1_scope.py'].extend([
    (
        'import subprocess\n'
        '\n'
        'import pytest\n',
        'import subprocess\n'
        'from time import monotonic\n'
        '\n'
        'import pytest\n',
    ),
    (
        "@pytest.fixture(scope='module')\n"
        'def _tree(tmp_path_factory):\n',
        '@pytest.fixture(autouse=True)\n'
        'def _report_o1_progress(request):\n'
        "    terminal = request.config.pluginmanager.get_plugin('terminalreporter')\n"
        '    start = monotonic()\n'
        '    if terminal is not None:\n'
        "        terminal.write_line(f'[O1] start {request.node.nodeid}')\n"
        '    yield\n'
        '    if terminal is not None:\n'
        "        terminal.write_line(f'[O1] finish {request.node.nodeid} ({monotonic() - start:.1f}s)')\n"
        '\n'
        '\n'
        "@pytest.fixture(scope='module')\n"
        'def _tree(tmp_path_factory):\n',
    ),
])


HANDOFFS['tests/test_ux_pr2a_scope.py'] = [(
    "    evidence = wt / 'evidence' / 'ux-pr2a-probe'; evidence.mkdir(parents=True, exist_ok=True)\n"
    "    artifact = evidence / 'source.json'; artifact.write_text('{\"synthetic\": true}\\n')\n",
    "    evidence = wt / 'evidence'\n"
    "    evidence.mkdir(exist_ok=True)\n"
    "    artifact = evidence / 'native.xml'\n"
    "    artifact.write_text('<testsuites/>\\n')\n",
)]

HANDOFFS['tests/ux_pr2a_scope.py'] += [
    (
        '        for p,sha in pins.items():\n'
        '            if _blob(_read(root,p,ref))!=sha and not pin_ok3(p,_blob(_read(root,p,ref))) and not _pr3b1_pin(p,_blob(_read(root,p,ref)),root,ref):\n',
        '        from tests import ci_v4_p0_scope as P0\n'
        '        for p,sha in pins.items():\n'
        '            blob = _blob(_read(root, p, ref))\n'
        '            if (blob != sha and not pin_ok3(p, blob) and not _pr3b1_pin(p, blob, root, ref)\n'
        '                    and not P0.ux_pr2a_artifact_test_pin(p, blob, root, ref)):\n',
    ),
    (
        '            from tests import ci_v4_p0_scope as P0\n'
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok3(p,new[p])',
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok3(p,new[p])',
    ),
]

HANDOFFS['tests/ux_pr2b_scope.py'] += [
    (
        '        for p,sha in pins.items():\n'
        '            if _blob(_read(root,p,ref))!=sha and not pin_ok4(p,_blob(_read(root,p,ref))) and not _pr3b1_pin(p,_blob(_read(root,p,ref)),root,ref,signature=not closure):\n',
        '        from tests import ci_v4_p0_scope as P0\n'
        '        for p,sha in pins.items():\n'
        '            blob = _blob(_read(root, p, ref))\n'
        '            if (blob != sha and not pin_ok4(p, blob) and not _pr3b1_pin(p, blob, root, ref, signature=not closure)\n'
        '                    and not P0.ux_pr2a_artifact_test_pin(p, blob, root, ref)):\n',
    ),
    (
        '            from tests import ci_v4_p0_scope as P0\n'
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok4(p,new[p])',
        '            if any(not (p in pins and new[p]==pins[p]) and not pin_ok4(p,new[p])',
    ),
]


HANDOFFS['tests/fin_v2_cohorts.py'] += [
    (
        'def valid(repo=None, ref=None):\n',
        'def exact_blobs_ok(cohort, repo=None, ref=None):\n'
        '    """Check a cohort directly and retain its rejection for this read-only call."""\n'
        '    root = Path(repo) if repo is not None else ROOT\n'
        '    verdict = cohort.exact_blobs_ok(root, ref)\n'
        '    if verdict is False and _CALL:\n'
        "        _CALL[-1].setdefault(('rejected-cohorts', str(root), ref), set()).add(cohort)\n"
        '    return verdict\n'
        '\n'
        '\n'
        'def valid(repo=None, ref=None):\n',
    ),
    (
        '    mods = cohorts()\n'
        '    if not mods:\n'
        '        return False\n',
        '    mods = cohorts()\n'
        '    if not mods:\n'
        '        return False\n'
        '    if _CALL:\n'
        "        rejected = _CALL[-1].get(('rejected-cohorts', str(root), ref), ())\n"
        '        if any(m in rejected for m in mods):\n'
        '            return False\n',
    ),
]

HANDOFFS['tests/test_wsv2_core_scope.py'] += [
    (
        "    monkeypatch.setattr(F, '_read', altered)\n"
        '    with C.call_scope():\n'
        '        assert not F.exact_blobs_ok() and not C.valid()\n',
        "    monkeypatch.setattr(F, '_read', altered)\n"
        '    with C.call_scope():\n'
        '        assert not C.exact_blobs_ok(F) and not C.valid()\n',
    ),
    (
        'def test_correction_e_d029_role_pin_is_additive_and_preserves_negative_controls():\n',
        '@C.call_scope()\n'
        'def test_correction_e_d029_role_pin_is_additive_and_preserves_negative_controls():\n',
    ),
    (
        'def test_predecessor_manifest_pins_and_metadata_remain_verbatim():\n',
        '@C.call_scope()\n'
        'def test_predecessor_manifest_pins_and_metadata_remain_verbatim():\n',
    ),
]

HANDOFFS['tests/test_finval_f01_scope.py'] = [
    (
        'from tests import finval_f01_scope as F\n',
        'from tests import fin_v2_cohorts as C\n'
        'from tests import finval_f01_scope as F\n',
    ),
    (
        '    assert F.valid()\n',
        '    with C.call_scope():\n'
        '        assert F.valid()\n',
    ),
    (
        '    assert not F.valid(sources=sources)\n'
        '    del sources[path]\n'
        '    assert not F.valid(sources=sources)\n',
        '    with C.call_scope():\n'
        '        assert not F.valid(sources=sources)\n'
        '    del sources[path]\n'
        '    with C.call_scope():\n'
        '        assert not F.valid(sources=sources)\n',
    ),
]


HANDOFFS['tests/u1_scope.py'].append((
    '_P0_RUNTIME_HANDOFFS = frozenset((\n',
    '_P0_RUNTIME_HANDOFFS = frozenset((\n'
    "    'tests/wsv2_core_scope.py',\n",
))

HANDOFFS['tests/wsv2_core_scope.py'] = [
    (
        'def _exact_blobs_ok(repo=None, ref=None):\n',
        'def _owned_pins_match(root, ref, pins):\n'
        '    mismatches = []\n'
        '    for path, expected in pins.items():\n'
        '        blob = _blob(_read(root, path, ref))\n'
        '        if blob != expected:\n'
        '            mismatches.append((path, blob))\n'
        '\n'
        '    if ref is None and mismatches:\n'
        '        paths = [path for path, _ in mismatches]\n'
        '        committed = {}\n'
        "        for entry in _git(root, 'ls-tree', '-r', '-z', 'HEAD', '--', *paths).decode().split('\\0'):\n"
        '            if entry:\n'
        "                mode_type_blob, path = entry.split('\\t', 1)\n"
        '                committed[path] = mode_type_blob.split()[2]\n'
        '        # HEAD only orders checks. Even a committed mismatch needs the exact successor proof.\n'
        '        mismatches.sort(key=lambda item: committed.get(item[0]) == item[1])\n'
        '\n'
        '    return all(_wf06b_supersedes(path, blob, root, ref) for path, blob in mismatches)\n'
        '\n'
        '\n'
        'def _exact_blobs_ok(repo=None, ref=None):\n',
    ),
    (
        '        if any(_blob(_read(root, p, ref)) != b and not _wf06b_supersedes(p, _blob(_read(root, p, ref)), root, ref) for p, b in pins.items()):\n',
        '        if not _owned_pins_match(root, ref, pins):\n',
    ),
]


HANDOFFS['tests/test_wsv2_core_scope.py'] += [
    (
        'def test_closed_cohort_is_registered_exact_and_excludes_financial_authorities():\n',
        'def _assert_ws_and_registry_reject():\n'
        '    with C.call_scope():\n'
        '        assert not C.exact_blobs_ok(F) and not C.valid()\n'
        '\n'
        '\n'
        '@C.call_scope()\n'
        'def test_closed_cohort_is_registered_exact_and_excludes_financial_authorities():\n',
    ),
    (
        "    monkeypatch.setattr(F, '_read', altered)\n"
        '    assert not F.exact_blobs_ok() and not C.valid()\n',
        "    monkeypatch.setattr(F, '_read', altered)\n"
        '    _assert_ws_and_registry_reject()\n',
    ),
    (
        '    assert not F.manifest() and not F.exact_blobs_ok() and not C.valid()\n',
        '    assert not F.manifest()\n'
        '    _assert_ws_and_registry_reject()\n',
    ),
    (
        "    monkeypatch.setattr(F, '_git', extra)\n"
        '    assert not F.exact_blobs_ok() and not C.valid()\n',
        "    monkeypatch.setattr(F, '_git', extra)\n"
        '    _assert_ws_and_registry_reject()\n',
    ),
    (
        "    monkeypatch.setattr(F, attribute, '0' * 40)\n"
        '    assert not F.exact_blobs_ok() and not C.valid()\n',
        "    monkeypatch.setattr(F, attribute, '0' * 40)\n"
        '    _assert_ws_and_registry_reject()\n',
    ),
    (
        "    monkeypatch.setattr(F, '_git', with_generated_evidence)\n"
        '    assert F.exact_blobs_ok() and C.valid()\n',
        "    monkeypatch.setattr(F, '_git', with_generated_evidence)\n"
        '    with C.call_scope():\n'
        '        assert F.exact_blobs_ok() and C.valid()\n',
    ),
    (
        "    monkeypatch.setattr(F, '_git', with_unreviewed_source)\n"
        '    assert not F.exact_blobs_ok() and not C.valid()\n',
        "    monkeypatch.setattr(F, '_git', with_unreviewed_source)\n"
        '    _assert_ws_and_registry_reject()\n',
    ),
]


HANDOFFS['tests/test_fin_v2_integration_409_scope.py'].append((
    'def test_correction_b_positive_on_the_genuine_integrated_head():\n'
    '    from tests import wf04_scope as W\n'
    '    for path in WF06A_PATHS + (SEAL_ONLY_PATH, B1_PATH, "main_web.py"):\n'
    '        assert W._downstream_allows(path, W.ROOT, None) is True, path\n'
    '    for path in (WF06A_PATH, "static/react/finco-react.js", B1_PATH, "main_web.py"):         # the exact reviewed pin of each pinned path passes\n'
    '        assert W._downstream_pin(path, head_blob(path), W.ROOT, None) is True, path       # (a manifest never pins itself, so none is probed here)\n',
    'def test_correction_b_positive_on_the_genuine_integrated_head():\n'
    '    from tests.fin_v2_cohorts import call_scope\n'
    '    from tests import wf04_scope as W\n'
    '    with call_scope():\n'
    '        for path in WF06A_PATHS + (SEAL_ONLY_PATH, B1_PATH, "main_web.py"):\n'
    '            assert W._downstream_allows(path, W.ROOT, None) is True, path\n'
    '        for path in (WF06A_PATH, "static/react/finco-react.js", B1_PATH, "main_web.py"):\n'
    '            assert W._downstream_pin(path, head_blob(path), W.ROOT, None) is True, path\n',
))

HANDOFFS['tests/test_post413_r1_scope.py'].append((
    'def test_supersession_is_bounded_to_the_exact_pin_of_a_superseded_path():\n',
    '@C.call_scope()\n'
    'def test_supersession_is_bounded_to_the_exact_pin_of_a_superseded_path():\n',
))


HANDOFFS['tests/ci_v5_hardening_scope.py'].append((
    '        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:\n            return False\n',
    '        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:\n            return False\n        # The forward overlay can replace the live workflow, but this pin remains the\n        # exact V5-2B workflow recorded at the immutable merge of PR #454.\n        if pins[".github/workflows/ci_v5_shadow.yml"] != "ae4a65b3e28efc890a6ba6d537e3d9b945953620":\n            return False\n',
))


HANDOFFS['tests/test_v11_stage3_successor.py'] = [(
    '    path = V.F01_TEST_ONLY_WORKFLOW\n    assert V.blob(path) == V.F01_TEST_ONLY_BLOB\n    assert V._exact_f01_nonactivation_workflow(path, head, V.ROOT)\n    assert V.v11_violations() == []\n',
    '    from tests import f03_financing_scope as F03\n\n    path = V.F01_TEST_ONLY_WORKFLOW\n    assert path == F03.CI_WORKFLOW\n    assert V.blob(path, F03.BASE) == V.F01_TEST_ONLY_BLOB\n    assert V._exact_f01_nonactivation_workflow(path, F03.BASE, V.ROOT)\n    assert F03.reviewed_workflow_ok(V.ROOT, head)\n    assert F03.reviewed_workflow_ok(V.ROOT)\n    assert V.v11_violations() == []\n',
)]


HANDOFFS['tests/test_r04_ppa_scope.py'].append((
    "        if p == 'tests/ci_v4_scope.py' and _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n",
    "        if p in ('tests/ci_v4_scope.py', 'tests/ux_pr2b_scope.py', 'tests/ux_pr2c_scope.py') and _P0.signature_ok() and p in _P0.HANDOFFS:\n",
))

HANDOFFS['tests/test_r03_ppa_scope.py'].append((
    "        if p == 'tests/ci_v4_scope.py' and _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n",
    "        if p in ('tests/ci_v4_scope.py', 'tests/ux_pr2b_scope.py', 'tests/ux_pr2c_scope.py') and _P0.signature_ok() and p in _P0.HANDOFFS:\n",
))

HANDOFFS['tests/test_t01e_remediation_scope.py'].append((
    "        if p == 'tests/ci_v4_scope.py' and _P0.signature_ok() and p in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n",
    "        if p in ('tests/ci_v4_scope.py', 'tests/ux_pr2b_scope.py', 'tests/ux_pr2c_scope.py') and _P0.signature_ok() and p in _P0.HANDOFFS:\n",
))

HANDOFFS['tests/test_f04_financing_scope.py'].append((
    "        if path == 'tests/ci_v4_scope.py' and _P0.signature_ok() and path in _P0.HANDOFFS:      # P1: the P0 terminal further substitutes exactly this CI module (literal, pin-exact)\n",
    "        if path in ('tests/ci_v4_scope.py', 'tests/ux_pr2b_scope.py', 'tests/ux_pr2c_scope.py') and _P0.signature_ok() and path in _P0.HANDOFFS:\n",
))

# post-#471 (owner decision 2026-11-20): the one-key, count-one private-dataset skip deferral. The reviewed FULL skip baseline is one more exact-P0-pin control blob
# (never a wildcard): every historical byte-equality guard accepts it only at the exact blob this cohort's manifest pins.
HANDOFFS['tests/ci_v4_lean_b1_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v4_lean_b2_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v4_lean_b3_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v5_bootstrap_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v5_hardening_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v5_gate_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v4_full_recovery_scope.py'] += [
    (
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')",
        "and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json')",
    ),
]
HANDOFFS['tests/ci_v4_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py', 'tests/test_ci_v4_release_gate.py'):",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py', 'tests/test_ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json'):",
    ),
]
HANDOFFS['tests/test_ci_v4_lean_b1_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]
HANDOFFS['tests/test_ci_v4_lean_b2_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]
HANDOFFS['tests/test_ci_v4_lean_b3_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]
HANDOFFS['tests/test_ci_v5_bootstrap_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]
HANDOFFS['tests/test_ci_v5_hardening_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]
HANDOFFS['tests/test_ci_v5_gate_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]
HANDOFFS['tests/test_ci_v4_full_recovery_scope.py'] += [
    (
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py') and T._p0_pins_frozen_edit(",
        "if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json') and T._p0_pins_frozen_edit(",
    ),
]

HANDOFFS['tests/fin_v2_3_scope.py'] = [('def valid(repo=None,ref=None):\n', 'def valid(repo=None, ref=None):\n    from tests.fin_v2_cohorts import call_scope\n\n    # Reuse the existing read-only scope for this traversal. A subsequent\n    # invocation still reads current source and sees any intervening mutation.\n    with call_scope():\n        return _valid(repo, ref)\n\n\ndef _valid(repo=None, ref=None):\n')]
HANDOFFS['tests/fin_v2_r1_scope.py'] = [('def valid(repo=None, ref=None):\n', 'def valid(repo=None, ref=None):\n    from tests.fin_v2_cohorts import call_scope\n\n    # Reuse the existing read-only scope for this traversal. A subsequent\n    # invocation still reads current source and sees any intervening mutation.\n    with call_scope():\n        return _valid(repo, ref)\n\n\ndef _valid(repo=None, ref=None):\n')]
HANDOFFS['tests/fin_v2_pr394_corr_scope.py'] = [('def valid(repo=None, ref=None):\n', 'def valid(repo=None, ref=None):\n    from tests.fin_v2_cohorts import call_scope\n\n    # Reuse the existing read-only scope for this traversal. A subsequent\n    # invocation still reads current source and sees any intervening mutation.\n    with call_scope():\n        return _valid(repo, ref)\n\n\ndef _valid(repo=None, ref=None):\n')]
HANDOFFS['tests/fin_v2_ci_scope.py'] = [('def valid(repo=None, ref=None):\n', 'def valid(repo=None, ref=None):\n    from tests.fin_v2_cohorts import call_scope\n\n    # Reuse the existing read-only scope for this traversal. A subsequent\n    # invocation still reads current source and sees any intervening mutation.\n    with call_scope():\n        return _valid(repo, ref)\n\n\ndef _valid(repo=None, ref=None):\n')]
HANDOFFS['tests/fin_v2_wsv2_scope.py'] = [('def valid(repo=None, ref=None):\n', 'def valid(repo=None, ref=None):\n    from tests.fin_v2_cohorts import call_scope\n\n    # Reuse the existing read-only scope for this traversal. A subsequent\n    # invocation still reads current source and sees any intervening mutation.\n    with call_scope():\n        return _valid(repo, ref)\n\n\ndef _valid(repo=None, ref=None):\n')]


HANDOFFS['tests/u1_scope.py'].append(("    'tests/test_wsv2_core_scope.py',\n))\n\n\ndef _p0_runtime_pin", "    'tests/test_wsv2_core_scope.py',\n    'tests/fin_v2_3_scope.py',\n    'tests/fin_v2_r1_scope.py',\n    'tests/fin_v2_wsv2_scope.py',\n))\n\n\ndef _p0_runtime_pin"))
HANDOFFS['tests/fin_v2_ci_scope.py'].append(('def exact_blobs_ok(repo=None, ref=None):\n', 'def _matches_pin(path, value, historical, root, ref):\n    if value == historical:\n        return True\n    if path != \'tests/fin_v2_ci_scope.py\':\n        return False\n    from tests import ci_v4_p0_scope as P0\n    return (\n        P0.supersedes(path, value, root, ref)\n        and P0.manifest(root, ref)["base_blobs"].get(path) == historical\n    )\n\n\ndef exact_blobs_ok(repo=None, ref=None):\n'))
HANDOFFS['tests/fin_v2_ci_scope.py'].append(('_blob(_read(root, p, ref)) != expected', 'not _matches_pin(p, _blob(_read(root, p, ref)), expected, root, ref)'))
HANDOFFS['tests/fin_v2_ci_scope.py'].append(('    return _blob(raw) == pins[path]\n', "    if path == 'tests/fin_v2_ci_scope.py':\n        root = Path(repo) if repo is not None else ROOT\n        try:\n            return raw == _read(root, path, ref)\n        except (OSError, subprocess.CalledProcessError):\n            return False\n    return _blob(raw) == pins[path]\n"))
HANDOFFS['tests/fin_v2_pr394_corr_scope.py'].append(('def exact_blobs_ok(repo=None, ref=None):\n', 'def _matches_pin(path, value, historical, root, ref):\n    if value == historical:\n        return True\n    if path != \'tests/fin_v2_pr394_corr_scope.py\':\n        return False\n    from tests import ci_v4_p0_scope as P0\n    return (\n        P0.supersedes(path, value, root, ref)\n        and P0.manifest(root, ref)["base_blobs"].get(path) == historical\n    )\n\n\ndef exact_blobs_ok(repo=None, ref=None):\n'))
HANDOFFS['tests/fin_v2_pr394_corr_scope.py'].append(('_blob(_read(root, p, ref)) == expected', '_matches_pin(p, _blob(_read(root, p, ref)), expected, root, ref)'))
HANDOFFS['tests/fin_v2_pr394_corr_scope.py'].append(('    return _blob(raw) == pins[path]\n', "    if path == 'tests/fin_v2_pr394_corr_scope.py':\n        root = Path(repo) if repo is not None else ROOT\n        try:\n            return raw == _read(root, path, ref)\n        except (OSError, subprocess.CalledProcessError):\n            return False\n    return _blob(raw) == pins[path]\n"))


# Preserve the historical O1 router pins and accept only their exact P0 successors.
HANDOFFS['tests/post413_o1_scope.py'].append((
    "    if path not in ('tests/post413_o1_scope.py', 'tests/test_post413_o1_scope.py', 'tests/test_post413_r1_scope.py'):\n",
    "    if path in ('app/v2/capex_router.py', 'app/v2/opex_router.py'):\n"
    "        from tests import ci_v4_p0_scope as P0\n"
    "        return P0.supersedes(path, actual, root, ref) and P0.manifest(root, ref)['base_blobs'].get(path) == expected\n"
    "    if path not in ('tests/post413_o1_scope.py', 'tests/test_post413_o1_scope.py', 'tests/test_post413_r1_scope.py'):\n",
))

# Literal handoffs for the pinned PR workflow. Historical manifests stay intact.
HANDOFFS['tests/ci_v4_scope.py'] = HANDOFFS.get('tests/ci_v4_scope.py', []) + [("    if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py', 'tests/test_ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json'):",
    "    if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', 'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml', '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_release_gate.py', 'tests/test_ci_v4_release_gate.py', 'docs/ci_v4/full_skip_baseline.json'):")]
HANDOFFS['tests/ux_pr2c_scope.py'] = HANDOFFS.get('tests/ux_pr2c_scope.py', []) + [('def _pr3b1_pin(path, blob, repo=None, ref=None):\n',
    "def _pr3b1_pin(path, blob, repo=None, ref=None):\n    if path in ('.github/workflows/ci_v4_pr.yml', 'tests/test_ux_pr2c_scope.py'):\n        from tests import ci_v4_p0_scope as P0\n        return P0.supersedes(path, blob, repo, ref)\n")]
HANDOFFS['tests/test_ux_pr2c_scope.py'] = HANDOFFS.get('tests/test_ux_pr2c_scope.py', []) + [('    text = (ROOT / ".github/workflows/ci_v4_pr.yml").read_text(encoding="utf-8")\n',
    '    from tests import ci_v4_p0_scope as P0\n    path = ".github/workflows/ci_v4_pr.yml"\n    text = subprocess.check_output(["git", "show", f"{P0.BASE}:{path}"], cwd=ROOT).decode("utf-8")\n    assert P0.supersedes(path, P0._blob((ROOT / path).read_bytes()))\n')]


# The reviewed mutation inventory has a source successor, while both historical maps keep their pins.
HANDOFFS['tests/post413_r1_scope.py'].append(("    if path not in ('tests/test_wsv2_core_scope.py', 'tests/post413_r1_scope.py', 'tests/test_post413_r1_scope.py'):\n",
    "    if path == 'tests/model_mutation_security_successor.py':\n        from tests import ci_v4_p0_scope as P0\n        return P0.mutation_inventory_handoff(value, manifest(root, ref)['source_blobs'].get(path), root, ref)\n    if path not in ('tests/test_wsv2_core_scope.py', 'tests/post413_r1_scope.py', 'tests/test_post413_r1_scope.py'):\n"))
HANDOFFS['tests/ux_pr2c_scope.py'].append(("    if path in ('.github/workflows/ci_v4_pr.yml', 'tests/test_ux_pr2c_scope.py'):\n",
    "    if path == 'tests/model_mutation_security_successor.py':\n        from tests import ci_v4_p0_scope as P0\n        return P0.mutation_inventory_handoff(blob, manifest(repo, ref)['source_blobs'].get(path), repo, ref)\n    if path in ('.github/workflows/ci_v4_pr.yml', 'tests/test_ux_pr2c_scope.py'):\n"))


HANDOFFS['tests/post413_r1_scope.py'].append(('    return pin is not None and pin == value and exact_blobs_ok(repo, ref)\n',
    "    if path == 'tests/model_mutation_security_successor.py' and pin != value:\n        from tests import ci_v4_p0_scope as P0\n        return P0.mutation_inventory_handoff(value, pin, repo, ref) and exact_blobs_ok(repo, ref)\n    return pin is not None and pin == value and exact_blobs_ok(repo, ref)\n"))
HANDOFFS['tests/wsv2_core_scope.py'].append(('    return W.supersedes(path, value, root, ref)\n',
    "    if path == 'tests/test_model_react_poc_browser_acceptance.py':\n        from tests import ci_v4_p0_scope as P0\n        return (P0.supersedes(path, value, root, ref)\n                and P0.manifest(root, ref)['base_blobs'].get(path) == manifest(root, ref)['source_blobs'].get(path))\n    return W.supersedes(path, value, root, ref)\n"))


HANDOFFS['tests/test_wsv2_core_scope.py'].append(('    if owner is not None:\n        assert owner.exact_blobs_ok() and owner.supersedes(path, pin)\n    return pin\n',
    "    if owner is not None:\n        assert owner.exact_blobs_ok() and owner.supersedes(path, pin)\n    if path == 'tests/test_model_react_poc_browser_acceptance.py':\n        from tests import ci_v4_p0_scope as P0\n\n        successor = P0.manifest()['source_blobs'][path]\n        assert P0.manifest()['base_blobs'][path] == pin\n        assert F._wf06b_supersedes(path, successor, F.ROOT, None)\n        return successor\n    return pin\n"))
HANDOFFS['tests/test_wsv2_core_scope.py'].append(('        assert tests(original) == tests(current), path\n',
    "        expected_tests = tests(original)\n        if path == 'tests/test_model_react_poc_browser_acceptance.py':\n            expected_tests.insert(0, ('test_stale_react_hash_run_is_refused', []))\n        assert tests(current) == expected_tests, path\n"))


def expected_handoff(root, path):
    """The exact bytes of ``path`` after the reviewed substitutions over its immutable BASE blob."""
    raw = _base_bytes(str(root), path).decode()
    for old, new in HANDOFFS[path]:
        if raw.count(old) != 1:
            raise ValueError("reviewed handoff is missing or ambiguous")
        raw = raw.replace(old, new)
    return raw.encode()


def reviewed_edits_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        pins = manifest(root, ref).get("source_blobs", {})
        for path in HANDOFFS:
            actual = _read(root, path, ref)
            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, subprocess.CalledProcessError):
        return False


_SCOPE = []


@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def _compute(root, ref, mode):
    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the changed/untracked checks."""
    if mode == "exact":
        return _signature_ok(root, ref, True) and _diff_ok(root, ref)
    return _signature_ok(root, ref, mode)


def _verdict(root, ref, closure):
    key = (str(root), ref, closure)
    if _SCOPE and key in _SCOPE[-1]:
        return _SCOPE[-1][key]
    value = _compute(root, ref, closure)
    if _SCOPE:
        _SCOPE[-1][key] = value
    return value


def signature_ok(repo=None, ref=None):
    """Source/base/mode authority only: it never reads a foreign current map's bytes (the full closure alone judges those)."""
    return _verdict(Path(repo) if repo is not None else ROOT, ref, False)


def map_keys(repo=None, ref=None):
    return MAP_PIN_KEYS


@lru_cache(maxsize=512)
def _base_mode(root, path):
    """Only immutable BASE entries are cached; evaluated source modes always come from the snapshot."""
    return _git(Path(root), "ls-tree", BASE, "--", path).decode().split()[0]


@lru_cache(maxsize=512)
def _base_bytes(root, path):
    """Bytes of an IMMUTABLE accepted-main (BASE) object. Never a working-tree or ref read, so a cached value can never go stale."""
    return _git(Path(root), "show", BASE + ":" + path)


@lru_cache(maxsize=8)
def _base_tree(root):
    return _git(Path(root), "rev-parse", BASE + "^{tree}").decode().strip()


@lru_cache(maxsize=256)
def _expected_blob(root, path):
    """Blob id of the literal reviewed transformation of an immutable BASE blob (a pure function of BASE and this module's literals)."""
    text = _base_bytes(root, path).decode()
    for old, new in HANDOFFS[path]:
        if text.count(old) != 1:
            raise ValueError("reviewed edit is missing or ambiguous")
        text = text.replace(old, new)
    return _blob(text.encode())


@lru_cache(maxsize=256)
def _expected_map_blob(root, path, moved):
    """Pure function of an immutable BASE map and the literal moved registry pin."""
    return _blob(expected_map(Path(root), path, dict(zip(MAP_PIN_KEYS, moved))))


def _snapshot(root, ref, paths):
    """One read of the evaluated state: {path: blob} and {path: mode}. A committed ref is read with ONE ls-tree; the WORKING TREE is read from
    disk and hashed here (Git blob framing over the current bytes), so a modified, replaced or deleted file is judged by what is really on disk, never by
    HEAD. A symlink or non-file is skipped (so its pin fails) and an executable bit is reported as a bad mode."""
    paths = sorted(paths)
    blobs, modes = {}, {}
    if ref is None:
        for p in paths:
            f = root / p
            if f.is_symlink() or not f.is_file():
                continue
            blobs[p] = _blob(f.read_bytes())
            modes[p] = "100755" if f.stat().st_mode & 0o111 else "100644"
        return blobs, modes
    for line in _git(root, "ls-tree", "-r", ref, "--", *paths).decode().splitlines():
        meta, name = line.split("\t", 1)
        mode, kind, blob = meta.split()
        if kind == "blob":
            blobs[name], modes[name] = blob, mode
    return blobs, modes


def _signature_ok(root, ref, closure=False):
    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing cached from mutable state."""
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if COHORT_MODULES != BASE_COHORTS + (__name__,):
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        if pins.get("tests/ci_v4_p0_scope.py") != _MODULE_BLOB:
            return False
        # Bind the independently reviewed count-one exception, even if a candidate
        # changes both the baseline bytes and the pin in its own manifest.
        if pins.get("docs/ci_v4/full_skip_baseline.json") != "d5e91b8a07d63dd5a2ef7b483e7e0893c7fedf0e":
            return False
        if pins.get('.github/workflows/ci_v4_full.yml') != FULL_VISUAL_WORKFLOW_BLOB:
            return False
        if pins.get(PR_CHROMIUM_WORKFLOW) != PR_CHROMIUM_WORKFLOW_BLOB:
            return False
        if any(pins.get(path) != blob for path, blob in BROWSER_REPAIR_BLOBS.items()):
            return False
        if pins.get('tests/test_ci_v4_p0_scope.py') != '82e3ab130cc2b5010351edf44fcfa942a432b4f4':
            return False
        if any(pins.get(path) != blob for path, blob in CORRECTION_F_BLOBS.items()):
            return False
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if d.get("source_modes") != {p: "100644" for p in OWNED_PATHS} or d.get("base_modes") != {p: "100644" for p in SUPERSEDED}:
            return False
        if not NEW.isdisjoint(base) or any((p.startswith(FORBIDDEN) and p not in COST_PRESENTATION_PATHS)
                                           or p.startswith("/") or ".." in p.split("/") or "*" in p
                                           for p in OWNED_PATHS | {MANIFEST}):
            return False
        if not CI_PATHS <= (NEW | REPLACED) or any(p.startswith(NEW_ONLY_PREFIXES) and p not in CI_PATHS for p in OWNED_PATHS | {MANIFEST}):       # .github/ and tools/ only as the literal CI_PATHS
            return False
        _git(root, "merge-base", "--is-ancestor", BASE, ref or "HEAD")
        key = str(root)
        if _base_tree(key) != BASE_TREE:
            return False
        if any(_blob(_base_bytes(key, p)) != base[p] for p in base):          # recorded predecessor blobs are what accepted main holds
            return False
        if any(_base_mode(key, p) != d["base_modes"][p] for p in SUPERSEDED):
            return False
        judged = {p for p in pins if closure or p not in CURRENT_MAPS}
        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))
        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:
            return False
        owned = (OWNED_PATHS - (set() if closure else CURRENT_MAPS)) | {MANIFEST}
        if any(modes.get(p) != "100644" for p in owned):
            return False
        if closure and ref is None:
            paths = owned | set(FROZEN)
            rows = _git(root, "ls-files", "--stage", "-z", "--", *sorted(paths)).decode().split("\0")
            staged = {}
            for row in filter(None, rows):
                meta, path = row.split("\t", 1)
                mode, blob, stage = meta.split()
                if stage != "0" or path in staged:
                    return False
                staged[path] = (mode, blob)
            if staged != {path: (modes[path], current[path]) for path in paths}:
                return False
        if any(pins[p] != _expected_blob(key, p) for p in HANDOFFS):
            return False
        if set(HANDOFFS) != HANDOFF_PATHS:
            return False
        map_pins = {**pins, REACT_BUNDLE_PATH: C06_REVIEWED_PRODUCT_BLOBS[REACT_BUNDLE_PATH]}
        moved = tuple(map_pins[k] for k in MAP_PIN_KEYS)
        for p in CURRENT_MAPS:
            if pins[p] != _expected_map_blob(key, p, moved):
                return False
        if closure:
            for p in CURRENT_MAPS:
                if current[p] != _expected_map_blob(key, p, moved):
                    return False
        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(Path(repo) if repo is not None else ROOT, ref, "exact")


C06_REVIEWED_PRODUCT_BLOBS = {
    'frontend/src/app/plainCopy.ts': '10f8d4d970f3eb72e6dcac58240646e350e4dea2',
    REACT_BUNDLE_PATH: '4c29bb7dcb93e2ccdb841b257334fafff6233e6d',
}


def _c06_product_paths(root, ref):
    # C06 owns the source and served bundle. The closure admits only the pair
    # of exact blobs, with both paths present as regular, non-executable files.
    blobs, modes = _snapshot(root, ref, C06_REVIEWED_PRODUCT_BLOBS)
    if blobs == C06_REVIEWED_PRODUCT_BLOBS and all(mode == "100644" for mode in modes.values()):
        return frozenset(C06_REVIEWED_PRODUCT_BLOBS)
    return frozenset()


def _diff_ok(root, ref):
    try:
        allowed = OWNED_PATHS | {MANIFEST} | _c06_product_paths(root, ref)
        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref else []), "--").decode().splitlines())
        if ref is None:
            staged = _git(root, "diff", "--cached", "--name-only", "--no-renames", "-z", BASE, "--")
            changed.update(filter(None, staged.decode().split("\0")))
        if not changed <= allowed:
            return False
        if ref is None:
            untracked = set(_git(root, "ls-files", "--others", "--exclude-standard").decode().splitlines())
            if any(p not in allowed and not (p.startswith("evidence/") and p.endswith((".json", ".xml", ".png", ".txt", ".csv", ".html", ".zip")))
                   for p in untracked):
                return False
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def effective_pins(repo=None, ref=None, *, signature=False):
    return {**manifest(repo, ref).get("source_blobs", {}), **C06_REVIEWED_PRODUCT_BLOBS}


def closure_paths(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if not signature_ok(root, ref):
        return frozenset()
    return OWNED_PATHS | {MANIFEST} | _c06_product_paths(root, ref)


def allowed_path(path, repo=None, ref=None):
    if path in C06_REVIEWED_PRODUCT_BLOBS:
        return path in closure_paths(repo, ref)
    return path in OWNED_PATHS | {MANIFEST} and signature_ok(repo, ref)


def ci_owns(path, repo=None, ref=None):
    """A literal CI V5 path (the shadow workflow or a V5 tool) while this cohort is exact; never a wildcard CI admission."""
    return path in CI_PATHS and exact_blobs_ok(repo, ref)


def supersedes(path, value, repo=None, ref=None):
    if path not in SUPERSEDED:
        return False
    # The signature decides a supersession; the composite separately requires every cohort's FULL exactness (map bytes, changed set, untracked
    # files), so a signature-only verdict never makes the tree valid.
    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value


def ux_pr2a_artifact_test_pin(path, value, repo=None, ref=None):
    """Admit only the reviewed artifact fixture source, leaving the historical pins intact."""
    return path == 'tests/test_ux_pr2a_scope.py' and supersedes(path, value, repo, ref)


def mutation_inventory_handoff(value, predecessor, repo=None, ref=None):
    """Bind the Correction F inventory to its exact historical R1 source."""
    path = 'tests/model_mutation_security_successor.py'
    root = Path(repo) if repo is not None else ROOT
    return (predecessor == _blob(_base_bytes(str(root), path))
            and value == CORRECTION_F_BLOBS[path]
            and exact_blobs_ok(root, ref))


def r1_security_test_handoff(path, value, repo=None, ref=None):
    if path != R1_SECURITY_TEST or not exact_blobs_ok(repo, ref):
        return False
    pins = manifest(repo, ref).get("source_blobs", {})
    return value is not None and pins.get(path) == value


def o1_historical_test_pin(sibling, path, value, repo=None, ref=None):
    """Keep the reviewed O1 audit blob in its historical manifest after the literal source handoff."""
    if (sibling, path) != ('docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json', 'tests/test_post413_o1_scope.py'):
        return False
    root = Path(repo) if repo is not None else ROOT
    if not exact_blobs_ok(root, ref):
        return False
    historical = json.loads(_base_bytes(str(root), sibling))['source_blobs'][path]
    return value == historical == _blob(_base_bytes(str(root), path))


def nontrust_scope_authorized(changed, repo=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:
            return False
        actual = set(_git(root, "diff", "--name-only", BASE).decode().splitlines())
        return bool(actual) and actual == set(changed) and actual <= OWNED_PATHS | {MANIFEST} | C06_REVIEWED_PRODUCT_BLOBS.keys() and exact_blobs_ok(root)
    except (OSError, subprocess.CalledProcessError):
        return False


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo, ref) and composite(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get("source_blobs", {})
    if path not in pins or not valid(repo, ref):
        return False
    return source is None or _blob(source.encode() if isinstance(source, str) else source) == pins[path]


def protected_blobs(repo=None, ref=None):
    return {}

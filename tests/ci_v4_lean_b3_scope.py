"""CI V4 Lean B3: ONE finite exact-source successor after the accepted B2 cohort (GLM B3+B4 scoped implementation, 2026-11-15).

BASE is accepted main (the merged #451, ``523a9eb2``). This cohort carries the WARN-ONLY test-admission report
(``tests/ci_v4_lean_report.py``: the machine-readable test-admission JSON over the trusted-base diff, its CLI command
and its targeted tests) and a DATA-ONLY refresh of ``docs/ci_v4/module_weights.json`` (hosted per-module JUnit
weights from run 43744944268 on the merged #451, u1 measured directly at 1537.3 s). It changes NO selector, policy,
workflow, product, financial or UI source and selects, deletes, skips or moves NO test. ZERO B4 demotions are
proposed: the B4 evidence is ``B4_PROOF_BLOCKED_ZERO_DEMOTIONS`` in the private packet.

Every changed byte, Git mode and the immutable BASE tree are bound to this module's manifest. The shared governance
paths this successor really changes (the B2 forward hook, the composite registry, the U1 discovery list, the exact-tail
tests, the report machinery and the eight current maps) are SUPERSEDED paths: each carries its accepted BASE blob, the
literal one-occurrence substitutions that produce its new blob, and the exact new blob. Previous manifests are never
rewritten except the current-map keys every earlier successor moved the same way.

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls the B2 cohort,
an older cohort or the composite; the B2 cohort calls this module through one forward hook (the acyclic C06->B1->B2 pattern).
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = "523a9eb2f4efb00dac49cee070cf925232ba0698"
BASE_TREE = "d702f6c10b91af5a41afba057f83c088dff31340"
MANIFEST = "docs/ci_v4/lean_b3/SOURCE_SUCCESSOR.json"
SCHEMA = "CI_V4_LEAN_B3_EXACT_SOURCE_V1"
AUTHORIZATION = ("GLM B3+B4 scoped implementation (2026-11-15): one finite exact-source successor of the accepted B2 cohort for the "
                 "WARN-ONLY test-admission report and the data-only scheduling-weight refresh; no selector, policy, workflow, product, "
                 "financial or test-selection change; no merge or deployment authority; zero test demotions proposed.")
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v4_lean_b2_scope.py"
BASE_COHORTS = (
    'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope',
    'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope',
    'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope',
    'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope',
    'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope',
    'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope',
    'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope',
    'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope',
    'tests.ci_v4_lean_b2_scope',
)
NEW = frozenset((
    "docs/ci_v4/lean_b3/README.md",
    "tests/ci_v4_lean_b3_scope.py",
    "tests/test_ci_v4_lean_b3_scope.py",
))
# Shared governance paths whose bytes move by one reviewed literal substitution (HANDOFFS): the B2 forward hook, the registry, the
# U1 discovery list, the exact-tail tests, the report machinery and the data-only weights refresh.
HANDOFF_PATHS = frozenset((
    'tests/c06_cost_workspace_scope.py',
    'tests/ci_v4_lean_b2_scope.py',
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
    'tests/ci_v4_lean_report.py',
    'tests/test_ci_v4_lean_report.py',
    'docs/ci_v4/module_weights.json',
    'tests/test_bess02_scope.py',
    'tests/test_c06_cost_workspace_scope.py',
    'tests/test_ci_v4_lean_b1_scope.py',
    'tests/test_ci_v4_lean_b2_scope.py',
    'tests/test_ci_v4_lean_tamper_matrix.py',
    'tests/test_ci_v4_perf_scope.py',
    'tests/test_f03_financing_scope.py',
    'tests/test_f04_financing_scope.py',
    'tests/test_post432_l01_l02_scope.py',
    'tests/test_r02_ppa_ux_scope.py',
    'tests/test_r03_ppa_scope.py',
    'tests/test_r04_ppa_scope.py',
    'tests/test_t01e_remediation_scope.py',
))
# ... and the eight current maps, of which the registry, U1-discovery and weights keys move (the bounded handoff every earlier successor made).
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
MAP_KEYS = ('tests/fin_v2_cohorts.py', 'tests/u1_scope.py', 'docs/ci_v4/module_weights.json')
SUPERSEDED = HANDOFF_PATHS | CURRENT_MAPS
OWNED_PATHS = NEW | SUPERSEDED
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "migrations/", "app/", "research/", "frontend/", "static/", "main_web.py")
# Accepted CI V4 control sources that this successor must leave byte-identical to BASE; the scheduling weights move by the reviewed
# HANDOFF above instead (data-only, no selection semantics).
FROZEN = (
    ".github/workflows/ci_v4_f01_job.yml", ".github/workflows/ci_v4_full.yml", ".github/workflows/ci_v4_pr.yml",
    ".github/workflows/ci_v4_release_gate.yml", ".github/workflows/ci_v4_shadow_split.yml",
    "docs/ci_v4/ci-v4-policy.json", "docs/ci_v4/full_skip_baseline.json",
    "docs/ci_v4/node_split_policy.json", "docs/ci_v4/node_weights.json",
    "pytest.ini",
    "tools/ci_v4_activate.py", "tools/ci_v4_aggregate.py", "tools/ci_v4_full_record.py", "tools/ci_v4_governance_gate.py",
    "tools/ci_v4_nodes.py", "tools/ci_v4_release_gate.py", "tools/ci_v4_schedule.py", "tools/ci_v4_select.py", "tools/ci_v4_shard.py",
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
    """Only the finite current-source keys (MAP_KEYS: the registry and the U1 discovery guard) may move; all history stays unchanged."""
    d = json.loads(_base_bytes(str(root), path))
    pins = manifest(root).get("source_blobs", {}) if pins is None else pins
    for key in MAP_KEYS:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The accepted C06 leaf gains one forward hook
# to this cohort (the same acyclic pattern F03, T01-E, R03 and R04 used); the registry appends this cohort exactly once; the exact-tail tests
# accept one more state.
HANDOFFS = {
    'docs/ci_v4/module_weights.json': [
        ((
            '  "tests/test_ci_acceptance.py": 7.71,\n'
            '  "tests/test_ci_optimization_v2.py": 0.362,\n'),
         (
            '  "tests/test_ci_acceptance.py": 6.177,\n'
            '  "tests/test_ci_optimization_v2.py": 0.625,\n')),
        ('  "tests/test_ci_v4_aggregate.py": 4.874,\n',
         '  "tests/test_ci_v4_aggregate.py": 7.098,\n'),
        ((
            '  "tests/test_ci_v4_scope.py": 0.888,\n'
            '  "tests/test_ci_v4_select.py": 8.722,\n'),
         (
            '  "tests/test_ci_v4_scope.py": 26.4,\n'
            '  "tests/test_ci_v4_select.py": 5.142,\n')),
        ('  "tests/test_f04_signing_secret_fail_closed.py": 0.583,\n',
         '  "tests/test_f04_signing_secret_fail_closed.py": 0.494,\n'),
        ('  "tests/test_financing_f35b_csrf.py": 13.297,\n',
         '  "tests/test_financing_f35b_csrf.py": 17.299,\n'),
        ('  "tests/test_finv2_d01_routes_and_matrix.py": 62.998,\n',
         '  "tests/test_finv2_d01_routes_and_matrix.py": 52.53,\n'),
        ('  "tests/test_finval_f01_fixture_integrity.py": 300.0,\n',
         '  "tests/test_finval_f01_fixture_integrity.py": 5.044,\n'),
        ('  "tests/test_public_engine_smoke.py": 6.429,\n',
         '  "tests/test_public_engine_smoke.py": 4.8,\n'),
        ('  "tests/test_public_ui_smoke.py": 0.002,\n',
         '  "tests/test_public_ui_smoke.py": 0.001,\n'),
        ('  "tests/test_rc7b_quarterly_csrf_successor.py": 500.0,\n',
         '  "tests/test_rc7b_quarterly_csrf_successor.py": 25.908,\n'),
        ((
            '  "tests/test_rc_sec_csrf_successor.py": 600.0,\n'
            '  "tests/test_rcm_adapter_csrf_successor.py": 2.584,\n'),
         (
            '  "tests/test_rc_sec_csrf_successor.py": 29.027,\n'
            '  "tests/test_rcm_adapter_csrf_successor.py": 5.105,\n')),
        ('  "tests/test_save_all_atomic_v1.py": 13.712,\n',
         '  "tests/test_save_all_atomic_v1.py": 8.979,\n'),
        ('  "tests/test_tax_wf10_candidate.py": 0.232,\n',
         '  "tests/test_tax_wf10_candidate.py": 0.014,\n'),
        ('  "tests/test_trust_readiness_controls.py": 29.803,\n',
         '  "tests/test_trust_readiness_controls.py": 8.977,\n'),
        ('  "tests/test_u1_scope.py": 258.992,\n',
         '  "tests/test_u1_scope.py": 1537.3,\n'),
        ('  "tests/test_ux_c_strict_numbers.py": 1.054,\n',
         (
            '  "tests/test_ux_c_strict_numbers.py": 1.054,\n'
            '  "tests/test_ux_pr2c_scope.py": 1980.0,\n')),
        ('  "tests/test_wf07_revenue_csrf.py": 5.719,\n',
         '  "tests/test_wf07_revenue_csrf.py": 5.335,\n'),
        ('  "tests/test_wf09_csrf_successor.py": 73.519,\n',
         '  "tests/test_wf09_csrf_successor.py": 24.278,\n'),
        ((
            '  "tests/test_yield_y0.py": 0.024,\n'
            '  "tests/test_ux_pr2c_scope.py": 1980.0\n'),
         '  "tests/test_yield_y0.py": 0.024\n'),
        ('  "tests/test_tax_wf10_candidate.py": 97,\n',
         '  "tests/test_tax_wf10_candidate.py": 32,\n'),
        ('  "tests/test_u1_scope.py": 100,\n',
         '  "tests/test_u1_scope.py": 17,\n'),
        ((
            ' "source": "GitHub Actions run 41782498276 (head 800395fd25a9296baab6366719f09e92ea920ac1), CI V3 native.xml of all 8 workers (artifacts 13301027713,13301557025,13301809315,13302907177,13302108520,13302441866,13302584009,13302064367); JUnit testcase time summed per module (includes per-test setup/teardown; excludes runner/checkout/install overhead) | CI V4 rules v2: 167 modules replaced by measured plain-runner JUnit time of CI V4 run 41833710956 (head ad9fce94, shards 0-4,6). | Correction P (2026-11-11, CI V4 performance): 4 module weights recalibrated. tests/test_ux_pr2c_scope.py 1980 s = measured JUnit #438 run 42881247217 shard-0 (1881.013 s, 18 cases) +5% headroom; the module is NOT changed by Correction P (byte-pinned by the ux_pr2c cohort; restructure needs an owner-reviewed successor), so its measured floor is scheduled honestly instead of the old 30 s fallback. tests/test_rc_sec_csrf_successor.py 600 s, tests/test_rc7b_quarterly_csrf_successor.py 500 s, tests/test_finval_f01_fixture_integrity.py 300 s = CONSERVATIVE PREDICTIONS after the scoped-composite fix (measured baseline #438: 2603/1738/469 s; instrumented local trace: one unscoped inventory call ~8.3k git subprocesses vs ~332 inside one call_scope). PROJECTED, not hosted measurements: re-measure from the first hosted CI V4 run whose trusted base contains this file and replace the predictions; pre-Correction-P values (179.444/104.839/5.649) remain in git history at main 01a26f9a.",\n'
            ' "total_nodes": 23770\n'),
         (
            ' "source": "GitHub Actions run 43744944268 (PR #451 head 36735613, merged as main 523a9eb2): per-module sums of the hosted shard JUnit (shards 0-2; u1 completed and included). Stale CI V3 values kept for modules outside that selection. GLM B3 2026-11-15; data-only change (no selection, tier, check or policy change).",\n'
            ' "total_nodes": 23622\n')),
    ],
    'tests/c06_cost_workspace_scope.py': [
        ((
            '    try:\r\n'
            '        pins = manifest(root, ref).get("source_blobs", {})\r\n'),
         (
            '    try:\r\n'
            '        from tests.fin_v2_cohorts import COHORT_MODULES as _CM3\r\n'
            '        pins = manifest(root, ref).get("source_blobs", {})\r\n')),
        ('        nxt = N is not None and N.signature_ok(root, ref)\r\n',
         (
            '        nxt = N is not None and N.signature_ok(root, ref)\r\n'
            '        N2 = N._next() if nxt else None\r\n'
            '        n_hand = set(N.HANDOFFS) | (set(N2.HANDOFFS) if N2 is not None and N.SUCCESSOR in _CM3 and N2.signature_ok(root, ref) else set())\r\n')),
        ('            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution of this shared path\r\n',
         '            if nxt and path in n_hand:            # the reviewed successor chain owns the further substitution of this shared path\r\n'),
    ],
    'tests/ci_v4_lean_b2_scope.py': [
        ((
            '    try:\n'
            '        yield\n'),
         (
            '    try:\n'
            '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept globally.\n'
            '        N = _next()\n'
            '        if N is None:\n'
            '            yield\n'
            '        else:\n'
            '            with N.scoped():\n'
            '                yield\n')),
        ((
            '    if mode == "exact":\n'
            '        return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
            '    return _signature_ok(root, ref, mode)\n'),
         (
            '    from contextlib import nullcontext\n'
            '    N = _next()\n'
            '    with (N.scoped() if N is not None else nullcontext()):\n'
            '        if mode == "exact":\n'
            '            return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
            '        return _signature_ok(root, ref, mode)\n')),
        ((
            '\n'
            'def map_keys(repo=None, ref=None):\n'),
         (
            '\n'
            "SUCCESSOR = 'tests.ci_v4_lean_b3_scope'\n"
            '\n'
            '\n'
            'def _next():\n'
            '    """The one finite forward successor (CI V4 Lean B3). Low-level only: its signature never calls this module or the composite."""\n'
            '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '    if SUCCESSOR not in COHORT_MODULES:\n'
            '        return None\n'
            '    from tests import ci_v4_lean_b3_scope\n'
            '    return ci_v4_lean_b3_scope\n'
            '\n'
            '\n'
            'def _next_pins(root, ref):\n'
            '    N = _next()\n'
            '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n'
            '\n'
            '\n'
            'def map_keys(repo=None, ref=None):\n')),
        ('    return tuple(MAP_KEYS)\n',
         (
            '    root = Path(repo) if repo is not None else ROOT\n'
            '    with scoped():\n'
            '        N = _next()\n'
            '        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ()\n'
            '        return tuple(MAP_KEYS) + more\n')),
        ('        if COHORT_MODULES != BASE_COHORTS + (__name__,):\n',
         '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n'),
        ('        if pins.get("tests/ci_v4_lean_b2_scope.py") != _MODULE_BLOB:\n',
         (
            '        N = _next()\n'
            '        nx = _next_pins(root, ref)\n'
            '        nxt = N is not None and N.signature_ok(root, ref)\n'
            '        if nx.get("tests/ci_v4_lean_b2_scope.py", pins.get("tests/ci_v4_lean_b2_scope.py")) != _MODULE_BLOB:\n')),
        ('        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n',
         (
            '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
            '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n')),
        ('        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\n',
         '        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\n'),
        ('        if any(pins[p] != _expected_blob(key, p) for p in HANDOFFS):\n',
         (
            '        n_covered = {p for p in HANDOFFS if nxt and p in N.HANDOFFS}\n'
            '        if any(pins[p] != _expected_blob(key, p) for p in HANDOFFS if p not in n_covered):\n'
            '            return False\n'
            '        if nxt and not N.reviewed_edits_ok(root, ref):\n')),
        ('        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):\n',
         (
            '        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p)\n'
            '               for p in FROZEN if not (nxt and p in N.HANDOFFS)):\n')),
    ],
    'tests/ci_v4_lean_report.py': [
        ((
            '"""CI V4 Lean B1: opt-in measurement, worker SIMULATION and WARN-ONLY test-admission report.\n'
            '\n'
            'Nothing here selects, schedules, skips, gates or blocks anything. Every number carries an evidence label so a local measurement or a simulation can\n'
            'never be read as hosted proof:\n'
            '\n'
            '* ``MEASURED_LOCAL``  - observed on this machine, by this process (wall / CPU seconds, Git subprocess counts, collected node ids).\n'
            '* ``SIMULATION``      - computed from recorded module weights with the accepted LPT function of ``tools/ci_v4_schedule.py``; never hosted truth.\n'
            "* ``WARN_ONLY``       - a test-admission observation from Fable's PROPOSED policy; it never fails a run and the exit code stays 0.\n"
            '\n'
            'Run it explicitly (``python -m tests.ci_v4_lean_report <command>``); it is never imported by the CI V4 plan, selector, scheduler or aggregator.\n'
            'Only public-safe test file names and counters are written - no private inputs, no client material.\n'
            '"""\n'
            'from __future__ import annotations\n'
            '\n'
            'import argparse\n'
            'import ast\n'
            'import contextlib\n'
            'import hashlib\n'
            'import json\n'
            'import re\n'
            'import subprocess\n'
            'import sys\n'
            'import time\n'
            'import xml.etree.ElementTree as ET\n'
            'from pathlib import Path\n'
            '\n'
            'ROOT = Path(__file__).resolve().parents[1]\n'
            'SCHEMA = "FINCO_CI_V4_LEAN_REPORT_V1"\n'
            'LABELS = ("MEASURED_LOCAL", "SIMULATION", "WARN_ONLY")\n'
            '# Fable C3-A PROPOSED budgets (05_TEST_ADMISSION_AND_RETIREMENT_POLICY_V1): NOT owner approved, never enforced.\n'
            'PROPOSED_BUDGETS = {"enforced": False, "approved_by_owner": False,\n'
            '                    "node_seconds": {"target": 60, "warn": 120, "exception": 300},\n'
            '                    "module_minutes": {"target": 5, "warn": 10, "exception": 15},\n'
            '                    "critical_path_minutes": {"target": 35, "warn": 45, "exception": 60}}\n'
            'SIM_WORKERS = (3, 4, 5, 6, 8)\n'
            '\n'
            '\n'
            '# ----------------------------------------------------------------------------------------------------- Git subprocess counting\n'
            '@contextlib.contextmanager\n'
            'def git_subprocess_counter():\n'
            '    """Count every ``git`` child process started by this interpreter inside the block (restored on exit; no global state is kept)."""\n'
            '    counts = {"git": 0, "other": 0}\n'
            '    original = subprocess.Popen.__init__\n'
            '\n'
            '    def counted(self, args, *a, **k):\n'
            '        first = args[0] if isinstance(args, (list, tuple)) and args else str(args)\n'
            '        counts["git" if first == "git" else "other"] += 1\n'
            '        return original(self, args, *a, **k)\n'
            '\n'
            '    subprocess.Popen.__init__ = counted\n'
            '    try:\n'
            '        yield counts\n'
            '    finally:\n'
            '        subprocess.Popen.__init__ = original\n'
            '\n'
            '\n'
            'def measure_gate(root=ROOT):\n'
            '    """One central governance gate verdict, measured: wall, CPU, Git subprocesses. Runs the repository\'s own ``run()`` unchanged."""\n'
            '    root = Path(root).resolve()\n'
            '    sys.path.insert(0, str(root))\n'
            '    try:\n'
            '        from tools import ci_v4_governance_gate as G\n'
            '        with git_subprocess_counter() as counts:\n'
            '            wall, cpu = time.monotonic(), time.process_time()\n'
            '            try:\n'
            '                record = G.run()\n'
            '                error = None\n'
            '            except Exception as exc:                                   # fail closed, report the exception honestly\n'
            '                record, error = {"verdict": "FAIL"}, "%s: %s" % (type(exc).__name__, exc)\n'
            '            wall, cpu = time.monotonic() - wall, time.process_time() - cpu\n'
            '    finally:\n'
            '        sys.path.remove(str(root))\n'
            '    return {"label": "MEASURED_LOCAL", "what": "central governance gate (one pass)", "verdict": record.get("verdict"),\n'
            '            "cohorts_checked": len(record.get("cohorts", {})), "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),\n'
            '            "git_subprocesses": counts["git"], "other_subprocesses": counts["other"], "error": error}\n'
            '\n'
            '\n'
            '# ----------------------------------------------------------------------------------------------------- collection evidence\n'
            '_NODE = re.compile(r"^(?P<id>[\\w./-]+\\.py::\\S.*)$")\n'
            '\n'
            '\n'
            'def parse_collect_output(text):\n'
            '    """Node ids, errors and the summary line from ``pytest --collect-only -q`` output."""\n'
            '    nodes, errors = [], []\n'
            '    for line in text.splitlines():\n'
            '        line = line.rstrip()\n'
            '        m = _NODE.match(line)\n'
            '        if m:\n'
            '            nodes.append(m.group("id"))\n'
            '        elif line.startswith("ERROR "):\n'
            '            errors.append(line)\n'
            '    return nodes, errors\n'
            '\n'
            '\n'
            'def collection_digest(modules, root=ROOT, extra_args=()):\n'
            '    """Exact collected node ids of ``modules`` from a FRESH pytest process (the same profile the CI uses: root pytest.ini, no cache plugin)."""\n'
            '    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra_args, *modules]\n'
            '    start = time.monotonic()\n'
            '    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)\n'
            '    nodes, errors = parse_collect_output(proc.stdout)\n'
            '    digest = hashlib.sha256("\\n".join(sorted(nodes)).encode()).hexdigest()\n'
            '    return {"label": "MEASURED_LOCAL", "what": "pytest --collect-only", "modules": sorted(modules), "collected_nodes": len(nodes),\n'
            '            "node_id_sha256": digest, "collection_errors": errors, "returncode": proc.returncode,\n'
            '            "collect_wall_s": round(time.monotonic() - start, 2),\n'
            '            "note": "selected / executed / skipped / deselected are NOT derived from collection; they come only from a run\'s JUnit"}\n'
            '\n'
            '\n'
            '# ----------------------------------------------------------------------------------------------------- weights + SIMULATION\n'
            'def load_recorded_weights(path=None):\n'
            '    from tools import ci_v4_schedule as sched\n'
            '    weights = sched.load_weights(path)\n'
            '    try:\n'
            '        source = json.loads(Path(path or ROOT / "docs/ci_v4/module_weights.json").read_text()).get("source", "unknown")\n'
            '    except (OSError, ValueError):\n'
            '        source = "unknown"\n'
            '    return weights, source\n'
            '\n'
            '\n'
            'def simulate_workers(modules, weights=None, counts=SIM_WORKERS, weights_source="supplied"):\n'
            '    """LPT SIMULATION of whole-module scheduling for ``counts`` workers. A module without a recorded weight is priced at the conservative\n'
            '    default of the accepted scheduler and listed as ``unknown_modules`` (never silently zero). Result is a SIMULATION, not hosted proof."""\n'
            '    from tools import ci_v4_schedule as sched\n'
            '    mods = sorted(set(modules))\n'
            '    if weights is None:\n'
            '        weights, weights_source = load_recorded_weights()\n'
            '    unknown = [m for m in mods if m not in weights]\n'
            '    total = sum(sched.weight_of(m, weights) for m in mods)\n'
            '    rows = []\n'
            '    for k in counts:\n'
            '        _, loads = sched.lpt(mods, weights, k)\n'
            '        rows.append({"workers": k, "critical_path_s": round(max(loads), 1) if loads else 0.0, "runner_s": round(sum(loads), 1),\n'
            '                     "imbalance_ratio": round(max(loads) / (sum(loads) / k), 3) if loads and sum(loads) else None})\n'
            '    return {"label": "SIMULATION", "what": "whole-module LPT over recorded weights", "modules": len(mods), "total_weight_s": round(total, 1),\n'
            '            "weights_source": weights_source, "unknown_modules": unknown, "default_module_s_for_unknown": sched.DEFAULT_MODULE_SECONDS,\n'
            '            "rows": rows, "disclaimer": "NOT hosted evidence; weights are historical and a schedule is only a prediction until a hosted run confirms it"}\n'
            '\n'
            '\n'
            'def read_junit_module_seconds(junit_paths):\n'
            '    """module path -> summed testcase seconds, from JUnit XML (classname ``tests.test_x`` -> ``tests/test_x.py``)."""\n'
            '    seconds, nodes = {}, {}\n'
            '    for p in junit_paths:\n'
            '        for case in ET.parse(p).getroot().iter("testcase"):\n'
            '            cls = case.get("classname", "")\n'
            '            parts = cls.split(".")\n'
            '            # pytest classnames are dotted module paths, optionally followed by a test class name\n'
            '            path = None\n'
            '            for i in range(len(parts), 0, -1):\n'
            '                cand = "/".join(parts[:i]) + ".py"\n'
            '                if (ROOT / cand).is_file():\n'
            '                    path = cand\n'
            '                    break\n'
            '            if path is None:\n'
            '                continue\n'
            '            seconds[path] = seconds.get(path, 0.0) + float(case.get("time", 0) or 0)\n'
            '            nodes[path] = nodes.get(path, 0) + 1\n'
            '    return seconds, nodes\n'
            '\n'
            '\n'
            'def propose_weights(junit_paths, current_weights, provenance, run_ref=""):\n'
            '    """A weights PROPOSAL from one run\'s JUnit. It never writes ``docs/ci_v4/module_weights.json`` and is NOT active: activation needs the trusted-base\n'
            '    flow and hosted proof. A module absent from the JUnit keeps its previous weight (or stays unknown); ties sort lexically. Deterministic."""\n'
            '    seconds, nodes = read_junit_module_seconds(sorted(junit_paths))\n'
            '    modules = {m: round(seconds.get(m, current_weights.get(m, 0.0)), 3) for m in sorted(set(seconds) | set(current_weights))}\n'
            '    kept = sorted(m for m in current_weights if m not in seconds)\n'
            '    return {"label": "MEASURED_LOCAL", "status": "PROPOSAL_NOT_ACTIVE", "provenance": provenance, "run_ref": run_ref,\n'
            '            "refreshed_modules": len(seconds), "kept_previous_weight": kept[:50], "kept_previous_weight_count": len(kept),\n'
            '            "modules": modules, "nodes": {m: nodes[m] for m in sorted(nodes)},\n'
            '            "rule": "must come from the last ACCEPTED main-run JUnit; unknown stays unknown (conservative default applies); trusted-base activation required"}\n'
            '\n'
            '\n'
            '# ----------------------------------------------------------------------------------------------------- WARN-ONLY admission report\n'
            '_WARNINGS = {\n'
            '    "ADM-RISK": "module docstring does not name the protected risk (policy item 1)",\n'
            '    "ADM-SOURCE-TEXT": "a test reads another file\'s text/bytes and asserts on it; acceptable only when that text is an approved contract (policy item 8)",\n'
            '    "ADM-COPIED-MATRIX": "large parametrization over owned paths looks like a per-cohort copy of a tamper matrix; extend the central matrix instead (policy item 8)",\n'
            '    "ADM-GIT-LOOP": "subprocess / git helper called inside a loop or comprehension; measure the Git subprocess count per node (policy item 5)",\n'
            '    "ADM-SKIP": "skip/xfail present: a skipped node is never PASS (policy item 3)",\n'
            '}\n'
            '\n'
            '\n'
            'def _call_name(node):\n'
            '    f = node.func\n'
            '    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")\n'
            '\n'
            '\n'
            'def admission_report(paths, root=ROOT):\n'
            '    """WARN-ONLY observations about test files (purely static, AST). Never raises for a finding; never changes an exit code."""\n'
            '    findings = []\n'
            '    for rel in sorted(paths):\n'
            '        p = Path(root) / rel\n'
            '        try:\n'
            '            tree = ast.parse(p.read_text(encoding="utf-8"))\n'
            '        except (OSError, SyntaxError, UnicodeDecodeError) as exc:\n'
            '            findings.append({"path": rel, "code": "ADM-UNREADABLE", "line": 0, "severity": "WARN", "message": "could not parse: %s" % type(exc).__name__})\n'
            '            continue\n'
            '        doc = ast.get_docstring(tree) or ""\n'
            '        if rel.rsplit("/", 1)[-1].startswith("test_") and not re.search(r"\\brisk|protect|invariant|negative|tamper|fail[- ]closed|never\\b", doc, re.I):\n'
            '            findings.append({"path": rel, "code": "ADM-RISK", "line": 1, "severity": "WARN", "message": _WARNINGS["ADM-RISK"]})\n'
            '        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]:\n'
            '            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]\n'
            '            names = {_call_name(c) for c in calls}\n'
            '            has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(fn))\n'
            '            if has_assert and names & {"read_text", "read_bytes"} and any(isinstance(n, (ast.Compare,)) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)\n'
            '                                                                         for n in ast.walk(fn)):\n'
            '                findings.append({"path": rel, "code": "ADM-SOURCE-TEXT", "line": fn.lineno, "severity": "WARN", "message": _WARNINGS["ADM-SOURCE-TEXT"]})\n'
            '            for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp))]:\n'
            '                inner = {_call_name(c) for c in ast.walk(loop) if isinstance(c, ast.Call)}\n'
            '                if inner & {"check_output", "run", "Popen", "git", "_git"}:\n'
            '                    findings.append({"path": rel, "code": "ADM-GIT-LOOP", "line": fn.lineno, "severity": "WARN", "message": _WARNINGS["ADM-GIT-LOOP"]})\n'
            '                    break\n'
            '        for node in ast.walk(tree):\n'
            '            if isinstance(node, ast.Call) and _call_name(node) == "parametrize" and node.args:\n'
            '                values = node.args[-1]\n'
            '                n = len(values.elts) if isinstance(values, (ast.List, ast.Tuple)) else 0\n'
            '                if n >= 20 or (isinstance(values, ast.Call) and "OWNED_PATHS" in ast.unparse(values)):\n'
            '                    findings.append({"path": rel, "code": "ADM-COPIED-MATRIX", "line": node.lineno, "severity": "WARN", "message": _WARNINGS["ADM-COPIED-MATRIX"]})\n'
            '            if isinstance(node, (ast.Attribute, ast.Name)) and getattr(node, "attr", getattr(node, "id", "")) in ("skip", "xfail", "skipif"):\n'
            '                findings.append({"path": rel, "code": "ADM-SKIP", "line": getattr(node, "lineno", 0), "severity": "WARN", "message": _WARNINGS["ADM-SKIP"]})\n'
            '    return {"label": "WARN_ONLY", "what": "test-admission observations (Fable policy V1, PROPOSED)", "files": len(set(paths)), "warnings": len(findings),\n'
            '            "findings": findings, "budgets": PROPOSED_BUDGETS, "exit_code_policy": "always 0: informational, never a gate"}\n'
            '\n'
            '\n'
            'def budget_warnings(junit_paths):\n'
            '    """WARN-ONLY: compare observed node/module seconds in a run\'s JUnit with the PROPOSED (not approved) budgets."""\n'
            '    node_b, mod_b = PROPOSED_BUDGETS["node_seconds"], PROPOSED_BUDGETS["module_minutes"]\n'
            '    rows, per_module = [], {}\n'
            '    for p in junit_paths:\n'
            '        for case in ET.parse(p).getroot().iter("testcase"):\n'
            '            t = float(case.get("time", 0) or 0)\n'
            '            per_module[case.get("classname", "")] = per_module.get(case.get("classname", ""), 0.0) + t\n'
            '            for level in ("exception", "warn"):\n'
            '                if t > node_b[level]:\n'
            '                    rows.append({"kind": "node", "level": level.upper(), "id": "%s::%s" % (case.get("classname"), case.get("name")), "seconds": round(t, 1)})\n'
            '                    break\n'
            '    for cls, t in per_module.items():\n'
            '        for level in ("exception", "warn"):\n'
            '            if t / 60.0 > mod_b[level]:\n'
            '                rows.append({"kind": "module", "level": level.upper(), "id": cls, "seconds": round(t, 1)})\n'
            '                break\n'
            '    return {"label": "WARN_ONLY", "enforced": False, "budgets": PROPOSED_BUDGETS, "findings": sorted(rows, key=lambda r: (r["kind"], -r["seconds"], r["id"]))}\n'
            '\n'
            '\n'
            '# ----------------------------------------------------------------------------------------------------- CLI (explicit, opt-in)\n'
            'def _emit(obj, output):\n'
            '    obj = {"schema": SCHEMA, **obj}\n'
            '    text = json.dumps(obj, indent=2, sort_keys=True) + "\\n"\n'
            '    if output:\n'
            '        Path(output).parent.mkdir(parents=True, exist_ok=True)\n'
            '        Path(output).write_text(text)\n'
            '    else:\n'
            '        sys.stdout.write(text)\n'
            '\n'
            '\n'
            'def main(argv=None):\n'
            '    ap = argparse.ArgumentParser(description="CI V4 Lean B1 opt-in report (measurement / SIMULATION / WARN-ONLY). Never gates anything.")\n'
            '    sub = ap.add_subparsers(dest="cmd", required=True)\n'
            '    for name in ("measure-gate", "collect", "simulate", "weights-proposal", "admission", "budgets"):\n'
            '        s = sub.add_parser(name)\n'
            '        s.add_argument("--output")\n'
            '        if name in ("collect", "simulate"):\n'
            '            s.add_argument("modules", nargs="+")\n'
            '        if name == "admission":\n'
            '            s.add_argument("paths", nargs="+")\n'
            '        if name in ("weights-proposal", "budgets"):\n'
            '            s.add_argument("--junit", nargs="+", required=True)\n'
            '        if name == "weights-proposal":\n'
            '            s.add_argument("--provenance", required=True, help="run id / commit of the ACCEPTED main run the JUnit came from")\n'
            '    a = ap.parse_args(argv)\n'
            '    if a.cmd == "measure-gate":\n'
            '        _emit(measure_gate(), a.output)\n'
            '    elif a.cmd == "collect":\n'
            '        _emit(collection_digest(a.modules), a.output)\n'
            '    elif a.cmd == "simulate":\n'
            '        _emit(simulate_workers(a.modules), a.output)\n'
            '    elif a.cmd == "weights-proposal":\n'
            '        weights, _ = load_recorded_weights()\n'
            '        _emit(propose_weights(a.junit, weights, a.provenance), a.output)\n'
            '    elif a.cmd == "budgets":\n'
            '        _emit(budget_warnings(a.junit), a.output)\n'
            '    else:\n'
            '        _emit(admission_report(a.paths), a.output)\n'
            '    return 0            # informational by design; a measurement failure is reported inside the JSON, never as a gate\n'
            '\n'
            '\n'
            'if __name__ == "__main__":\n'
            '    sys.exit(main())\n'),
         (
            '"""CI V4 Lean B1: opt-in measurement, worker SIMULATION and WARN-ONLY test-admission report.\r\n'
            '\r\n'
            'Nothing here selects, schedules, skips, gates or blocks anything. Every number carries an evidence label so a local measurement or a simulation can\r\n'
            'never be read as hosted proof:\r\n'
            '\r\n'
            '* ``MEASURED_LOCAL``  - observed on this machine, by this process (wall / CPU seconds, Git subprocess counts, collected node ids).\r\n'
            '* ``SIMULATION``      - computed from recorded module weights with the accepted LPT function of ``tools/ci_v4_schedule.py``; never hosted truth.\r\n'
            "* ``WARN_ONLY``       - a test-admission observation from Fable's PROPOSED policy; it never fails a run and the exit code stays 0.\r\n"
            '\r\n'
            'Run it explicitly (``python -m tests.ci_v4_lean_report <command>``); it is never imported by the CI V4 plan, selector, scheduler or aggregator.\r\n'
            'Only public-safe test file names and counters are written - no private inputs, no client material.\r\n'
            '"""\r\n'
            'from __future__ import annotations\r\n'
            '\r\n'
            'import argparse\r\n'
            'import ast\r\n'
            'import contextlib\r\n'
            'import hashlib\r\n'
            'import json\r\n'
            'import re\r\n'
            'import subprocess\r\n'
            'import sys\r\n'
            'import time\r\n'
            'import xml.etree.ElementTree as ET\r\n'
            'from pathlib import Path\r\n'
            '\r\n'
            'ROOT = Path(__file__).resolve().parents[1]\r\n'
            'SCHEMA = "FINCO_CI_V4_LEAN_REPORT_V1"\r\n'
            'LABELS = ("MEASURED_LOCAL", "SIMULATION", "WARN_ONLY")\r\n'
            '# Fable C3-A PROPOSED budgets (05_TEST_ADMISSION_AND_RETIREMENT_POLICY_V1): NOT owner approved, never enforced.\r\n'
            'PROPOSED_BUDGETS = {"enforced": False, "approved_by_owner": False,\r\n'
            '                    "node_seconds": {"target": 60, "warn": 120, "exception": 300},\r\n'
            '                    "module_minutes": {"target": 5, "warn": 10, "exception": 15},\r\n'
            '                    "critical_path_minutes": {"target": 35, "warn": 45, "exception": 60}}\r\n'
            'SIM_WORKERS = (3, 4, 5, 6, 8)\r\n'
            '\r\n'
            '\r\n'
            '# ----------------------------------------------------------------------------------------------------- Git subprocess counting\r\n'
            '@contextlib.contextmanager\r\n'
            'def git_subprocess_counter():\r\n'
            '    """Count every ``git`` child process started by this interpreter inside the block (restored on exit; no global state is kept)."""\r\n'
            '    counts = {"git": 0, "other": 0}\r\n'
            '    original = subprocess.Popen.__init__\r\n'
            '\r\n'
            '    def counted(self, args, *a, **k):\r\n'
            '        first = args[0] if isinstance(args, (list, tuple)) and args else str(args)\r\n'
            '        counts["git" if first == "git" else "other"] += 1\r\n'
            '        return original(self, args, *a, **k)\r\n'
            '\r\n'
            '    subprocess.Popen.__init__ = counted\r\n'
            '    try:\r\n'
            '        yield counts\r\n'
            '    finally:\r\n'
            '        subprocess.Popen.__init__ = original\r\n'
            '\r\n'
            '\r\n'
            'def measure_gate(root=ROOT):\r\n'
            '    """One central governance gate verdict, measured: wall, CPU, Git subprocesses. Runs the repository\'s own ``run()`` unchanged."""\r\n'
            '    root = Path(root).resolve()\r\n'
            '    sys.path.insert(0, str(root))\r\n'
            '    try:\r\n'
            '        from tools import ci_v4_governance_gate as G\r\n'
            '        with git_subprocess_counter() as counts:\r\n'
            '            wall, cpu = time.monotonic(), time.process_time()\r\n'
            '            try:\r\n'
            '                record = G.run()\r\n'
            '                error = None\r\n'
            '            except Exception as exc:                                   # fail closed, report the exception honestly\r\n'
            '                record, error = {"verdict": "FAIL"}, "%s: %s" % (type(exc).__name__, exc)\r\n'
            '            wall, cpu = time.monotonic() - wall, time.process_time() - cpu\r\n'
            '    finally:\r\n'
            '        sys.path.remove(str(root))\r\n'
            '    return {"label": "MEASURED_LOCAL", "what": "central governance gate (one pass)", "verdict": record.get("verdict"),\r\n'
            '            "cohorts_checked": len(record.get("cohorts", {})), "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),\r\n'
            '            "git_subprocesses": counts["git"], "other_subprocesses": counts["other"], "error": error}\r\n'
            '\r\n'
            '\r\n'
            '# ----------------------------------------------------------------------------------------------------- collection evidence\r\n'
            '_NODE = re.compile(r"^(?P<id>[\\w./-]+\\.py::\\S.*)$")\r\n'
            '\r\n'
            '\r\n'
            'def parse_collect_output(text):\r\n'
            '    """Node ids, errors and the summary line from ``pytest --collect-only -q`` output."""\r\n'
            '    nodes, errors = [], []\r\n'
            '    for line in text.splitlines():\r\n'
            '        line = line.rstrip()\r\n'
            '        m = _NODE.match(line)\r\n'
            '        if m:\r\n'
            '            nodes.append(m.group("id"))\r\n'
            '        elif line.startswith("ERROR "):\r\n'
            '            errors.append(line)\r\n'
            '    return nodes, errors\r\n'
            '\r\n'
            '\r\n'
            'def collection_digest(modules, root=ROOT, extra_args=()):\r\n'
            '    """Exact collected node ids of ``modules`` from a FRESH pytest process (the same profile the CI uses: root pytest.ini, no cache plugin)."""\r\n'
            '    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra_args, *modules]\r\n'
            '    start = time.monotonic()\r\n'
            '    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)\r\n'
            '    nodes, errors = parse_collect_output(proc.stdout)\r\n'
            '    digest = hashlib.sha256("\\n".join(sorted(nodes)).encode()).hexdigest()\r\n'
            '    return {"label": "MEASURED_LOCAL", "what": "pytest --collect-only", "modules": sorted(modules), "collected_nodes": len(nodes),\r\n'
            '            "node_id_sha256": digest, "collection_errors": errors, "returncode": proc.returncode,\r\n'
            '            "collect_wall_s": round(time.monotonic() - start, 2),\r\n'
            '            "note": "selected / executed / skipped / deselected are NOT derived from collection; they come only from a run\'s JUnit"}\r\n'
            '\r\n'
            '\r\n'
            '# ----------------------------------------------------------------------------------------------------- weights + SIMULATION\r\n'
            'def load_recorded_weights(path=None):\r\n'
            '    from tools import ci_v4_schedule as sched\r\n'
            '    weights = sched.load_weights(path)\r\n'
            '    try:\r\n'
            '        source = json.loads(Path(path or ROOT / "docs/ci_v4/module_weights.json").read_text()).get("source", "unknown")\r\n'
            '    except (OSError, ValueError):\r\n'
            '        source = "unknown"\r\n'
            '    return weights, source\r\n'
            '\r\n'
            '\r\n'
            'def simulate_workers(modules, weights=None, counts=SIM_WORKERS, weights_source="supplied"):\r\n'
            '    """LPT SIMULATION of whole-module scheduling for ``counts`` workers. A module without a recorded weight is priced at the conservative\r\n'
            '    default of the accepted scheduler and listed as ``unknown_modules`` (never silently zero). Result is a SIMULATION, not hosted proof."""\r\n'
            '    from tools import ci_v4_schedule as sched\r\n'
            '    mods = sorted(set(modules))\r\n'
            '    if weights is None:\r\n'
            '        weights, weights_source = load_recorded_weights()\r\n'
            '    unknown = [m for m in mods if m not in weights]\r\n'
            '    total = sum(sched.weight_of(m, weights) for m in mods)\r\n'
            '    rows = []\r\n'
            '    for k in counts:\r\n'
            '        _, loads = sched.lpt(mods, weights, k)\r\n'
            '        rows.append({"workers": k, "critical_path_s": round(max(loads), 1) if loads else 0.0, "runner_s": round(sum(loads), 1),\r\n'
            '                     "imbalance_ratio": round(max(loads) / (sum(loads) / k), 3) if loads and sum(loads) else None})\r\n'
            '    return {"label": "SIMULATION", "what": "whole-module LPT over recorded weights", "modules": len(mods), "total_weight_s": round(total, 1),\r\n'
            '            "weights_source": weights_source, "unknown_modules": unknown, "default_module_s_for_unknown": sched.DEFAULT_MODULE_SECONDS,\r\n'
            '            "rows": rows, "disclaimer": "NOT hosted evidence; weights are historical and a schedule is only a prediction until a hosted run confirms it"}\r\n'
            '\r\n'
            '\r\n'
            'def read_junit_module_seconds(junit_paths):\r\n'
            '    """module path -> summed testcase seconds, from JUnit XML (classname ``tests.test_x`` -> ``tests/test_x.py``)."""\r\n'
            '    seconds, nodes = {}, {}\r\n'
            '    for p in junit_paths:\r\n'
            '        for case in ET.parse(p).getroot().iter("testcase"):\r\n'
            '            cls = case.get("classname", "")\r\n'
            '            parts = cls.split(".")\r\n'
            '            # pytest classnames are dotted module paths, optionally followed by a test class name\r\n'
            '            path = None\r\n'
            '            for i in range(len(parts), 0, -1):\r\n'
            '                cand = "/".join(parts[:i]) + ".py"\r\n'
            '                if (ROOT / cand).is_file():\r\n'
            '                    path = cand\r\n'
            '                    break\r\n'
            '            if path is None:\r\n'
            '                continue\r\n'
            '            seconds[path] = seconds.get(path, 0.0) + float(case.get("time", 0) or 0)\r\n'
            '            nodes[path] = nodes.get(path, 0) + 1\r\n'
            '    return seconds, nodes\r\n'
            '\r\n'
            '\r\n'
            'def propose_weights(junit_paths, current_weights, provenance, run_ref=""):\r\n'
            '    """A weights PROPOSAL from one run\'s JUnit. It never writes ``docs/ci_v4/module_weights.json`` and is NOT active: activation needs the trusted-base\r\n'
            '    flow and hosted proof. A module absent from the JUnit keeps its previous weight (or stays unknown); ties sort lexically. Deterministic."""\r\n'
            '    seconds, nodes = read_junit_module_seconds(sorted(junit_paths))\r\n'
            '    modules = {m: round(seconds.get(m, current_weights.get(m, 0.0)), 3) for m in sorted(set(seconds) | set(current_weights))}\r\n'
            '    kept = sorted(m for m in current_weights if m not in seconds)\r\n'
            '    return {"label": "MEASURED_LOCAL", "status": "PROPOSAL_NOT_ACTIVE", "provenance": provenance, "run_ref": run_ref,\r\n'
            '            "refreshed_modules": len(seconds), "kept_previous_weight": kept[:50], "kept_previous_weight_count": len(kept),\r\n'
            '            "modules": modules, "nodes": {m: nodes[m] for m in sorted(nodes)},\r\n'
            '            "rule": "must come from the last ACCEPTED main-run JUnit; unknown stays unknown (conservative default applies); trusted-base activation required"}\r\n'
            '\r\n'
            '\r\n'
            '# ----------------------------------------------------------------------------------------------------- WARN-ONLY admission report\r\n'
            '_WARNINGS = {\r\n'
            '    "ADM-RISK": "module docstring does not name the protected risk (policy item 1)",\r\n'
            '    "ADM-SOURCE-TEXT": "a test reads another file\'s text/bytes and asserts on it; acceptable only when that text is an approved contract (policy item 8)",\r\n'
            '    "ADM-COPIED-MATRIX": "large parametrization over owned paths looks like a per-cohort copy of a tamper matrix; extend the central matrix instead (policy item 8)",\r\n'
            '    "ADM-GIT-LOOP": "subprocess / git helper called inside a loop or comprehension; measure the Git subprocess count per node (policy item 5)",\r\n'
            '    "ADM-SKIP": "skip/xfail present: a skipped node is never PASS (policy item 3)",\r\n'
            '}\r\n'
            '\r\n'
            '\r\n'
            'def _call_name(node):\r\n'
            '    f = node.func\r\n'
            '    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")\r\n'
            '\r\n'
            '\r\n'
            'def admission_report(paths, root=ROOT):\r\n'
            '    """WARN-ONLY observations about test files (purely static, AST). Never raises for a finding; never changes an exit code."""\r\n'
            '    findings = []\r\n'
            '    for rel in sorted(paths):\r\n'
            '        p = Path(root) / rel\r\n'
            '        try:\r\n'
            '            tree = ast.parse(p.read_text(encoding="utf-8"))\r\n'
            '        except (OSError, SyntaxError, UnicodeDecodeError) as exc:\r\n'
            '            findings.append({"path": rel, "code": "ADM-UNREADABLE", "line": 0, "severity": "WARN", "message": "could not parse: %s" % type(exc).__name__})\r\n'
            '            continue\r\n'
            '        doc = ast.get_docstring(tree) or ""\r\n'
            '        if rel.rsplit("/", 1)[-1].startswith("test_") and not re.search(r"\\brisk|protect|invariant|negative|tamper|fail[- ]closed|never\\b", doc, re.I):\r\n'
            '            findings.append({"path": rel, "code": "ADM-RISK", "line": 1, "severity": "WARN", "message": _WARNINGS["ADM-RISK"]})\r\n'
            '        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]:\r\n'
            '            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]\r\n'
            '            names = {_call_name(c) for c in calls}\r\n'
            '            has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(fn))\r\n'
            '            if has_assert and names & {"read_text", "read_bytes"} and any(isinstance(n, (ast.Compare,)) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)\r\n'
            '                                                                         for n in ast.walk(fn)):\r\n'
            '                findings.append({"path": rel, "code": "ADM-SOURCE-TEXT", "line": fn.lineno, "severity": "WARN", "message": _WARNINGS["ADM-SOURCE-TEXT"]})\r\n'
            '            for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp))]:\r\n'
            '                inner = {_call_name(c) for c in ast.walk(loop) if isinstance(c, ast.Call)}\r\n'
            '                if inner & {"check_output", "run", "Popen", "git", "_git"}:\r\n'
            '                    findings.append({"path": rel, "code": "ADM-GIT-LOOP", "line": fn.lineno, "severity": "WARN", "message": _WARNINGS["ADM-GIT-LOOP"]})\r\n'
            '                    break\r\n'
            '        for node in ast.walk(tree):\r\n'
            '            if isinstance(node, ast.Call) and _call_name(node) == "parametrize" and node.args:\r\n'
            '                values = node.args[-1]\r\n'
            '                n = len(values.elts) if isinstance(values, (ast.List, ast.Tuple)) else 0\r\n'
            '                if n >= 20 or (isinstance(values, ast.Call) and "OWNED_PATHS" in ast.unparse(values)):\r\n'
            '                    findings.append({"path": rel, "code": "ADM-COPIED-MATRIX", "line": node.lineno, "severity": "WARN", "message": _WARNINGS["ADM-COPIED-MATRIX"]})\r\n'
            '            if isinstance(node, (ast.Attribute, ast.Name)) and getattr(node, "attr", getattr(node, "id", "")) in ("skip", "xfail", "skipif"):\r\n'
            '                findings.append({"path": rel, "code": "ADM-SKIP", "line": getattr(node, "lineno", 0), "severity": "WARN", "message": _WARNINGS["ADM-SKIP"]})\r\n'
            '    return {"label": "WARN_ONLY", "what": "test-admission observations (Fable policy V1, PROPOSED)", "files": len(set(paths)), "warnings": len(findings),\r\n'
            '            "findings": findings, "budgets": PROPOSED_BUDGETS, "exit_code_policy": "always 0: informational, never a gate"}\r\n'
            '\r\n'
            '\r\n'
            'def budget_warnings(junit_paths):\r\n'
            '    """WARN-ONLY: compare observed node/module seconds in a run\'s JUnit with the PROPOSED (not approved) budgets."""\r\n'
            '    node_b, mod_b = PROPOSED_BUDGETS["node_seconds"], PROPOSED_BUDGETS["module_minutes"]\r\n'
            '    rows, per_module = [], {}\r\n'
            '    for p in junit_paths:\r\n'
            '        for case in ET.parse(p).getroot().iter("testcase"):\r\n'
            '            t = float(case.get("time", 0) or 0)\r\n'
            '            per_module[case.get("classname", "")] = per_module.get(case.get("classname", ""), 0.0) + t\r\n'
            '            for level in ("exception", "warn"):\r\n'
            '                if t > node_b[level]:\r\n'
            '                    rows.append({"kind": "node", "level": level.upper(), "id": "%s::%s" % (case.get("classname"), case.get("name")), "seconds": round(t, 1)})\r\n'
            '                    break\r\n'
            '    for cls, t in per_module.items():\r\n'
            '        for level in ("exception", "warn"):\r\n'
            '            if t / 60.0 > mod_b[level]:\r\n'
            '                rows.append({"kind": "module", "level": level.upper(), "id": cls, "seconds": round(t, 1)})\r\n'
            '                break\r\n'
            '    return {"label": "WARN_ONLY", "enforced": False, "budgets": PROPOSED_BUDGETS, "findings": sorted(rows, key=lambda r: (r["kind"], -r["seconds"], r["id"]))}\r\n'
            '\r\n'
            '\r\n'
            '# ----------------------------------------------------------------------------------------------------- CLI (explicit, opt-in)\r\n'
            'def _emit(obj, output):\r\n'
            '    obj = {"schema": SCHEMA, **obj}\r\n'
            '    text = json.dumps(obj, indent=2, sort_keys=True) + "\\n"\r\n'
            '    if output:\r\n'
            '        Path(output).parent.mkdir(parents=True, exist_ok=True)\r\n'
            '        Path(output).write_text(text)\r\n'
            '    else:\r\n'
            '        sys.stdout.write(text)\r\n'
            '\r\n'
            '\r\n'
            'def main(argv=None):\r\n'
            '    ap = argparse.ArgumentParser(description="CI V4 Lean B1 opt-in report (measurement / SIMULATION / WARN-ONLY). Never gates anything.")\r\n'
            '    sub = ap.add_subparsers(dest="cmd", required=True)\r\n'
            '    for name in ("measure-gate", "collect", "simulate", "weights-proposal", "admission", "budgets", "test-admission"):\r\n'
            '        s = sub.add_parser(name)\r\n'
            '        s.add_argument("--output")\r\n'
            '        if name in ("collect", "simulate"):\r\n'
            '            s.add_argument("modules", nargs="+")\r\n'
            '        if name == "admission":\r\n'
            '            s.add_argument("paths", nargs="+")\r\n'
            '        if name in ("weights-proposal", "budgets"):\r\n'
            '            s.add_argument("--junit", nargs="+", required=True)\r\n'
            '        if name == "test-admission":\r\n'
            '            s.add_argument("--junit", nargs="+")\r\n'
            '        if name == "test-admission":\r\n'
            '            s.add_argument("--base", default="origin/main")\r\n'
            '            s.add_argument("--head", default="HEAD")\r\n'
            '            s.add_argument("--plan", help="trusted-base plan JSON (from the plan job artifact), optional")\r\n'
            '        if name == "weights-proposal":\r\n'
            '            s.add_argument("--provenance", required=True, help="run id / commit of the ACCEPTED main run the JUnit came from")\r\n'
            '    a = ap.parse_args(argv)\r\n'
            '    if a.cmd == "measure-gate":\r\n'
            '        _emit(measure_gate(), a.output)\r\n'
            '    elif a.cmd == "collect":\r\n'
            '        _emit(collection_digest(a.modules), a.output)\r\n'
            '    elif a.cmd == "simulate":\r\n'
            '        _emit(simulate_workers(a.modules), a.output)\r\n'
            '    elif a.cmd == "weights-proposal":\r\n'
            '        weights, _ = load_recorded_weights()\r\n'
            '        _emit(propose_weights(a.junit, weights, a.provenance), a.output)\r\n'
            '    elif a.cmd == "budgets":\r\n'
            '        _emit(budget_warnings(a.junit), a.output)\r\n'
            '    elif a.cmd == "test-admission":\r\n'
            '        _emit(test_admission_report(a.base, a.head, a.plan, a.junit or ()), a.output)\r\n'
            '    else:\r\n'
            '        _emit(admission_report(a.paths), a.output)\r\n'
            '    return 0            # informational by design; a measurement failure is reported inside the JSON, never as a gate\r\n'
            '\r\n'
            '\r\n'
            '# ----------------------------------------------------------------------------------------------- B3 test-admission report (WARN-ONLY, opt-in)\r\n'
            'ADMISSION_FIELDS = ("risk", "nearest", "witness", "tier", "owner", "retire")\r\n'
            '\r\n'
            '\r\n'
            'def _git_name_status(base, head, root):\r\n'
            '    """Added/removed/renamed/changed test-module paths vs the trusted base (rename detection ON)."""\r\n'
            '    out = subprocess.check_output(["git", "-c", "core.quotepath=false", "diff", "--name-status", "-M", base, head,\r\n'
            '                                   "--", "tests/"], cwd=root).decode("utf-8", "replace")\r\n'
            '    added, removed, renamed, changed = [], [], [], []\r\n'
            '    for line in out.splitlines():\r\n'
            '        parts = line.split("\\t")\r\n'
            '        if not parts or not parts[0]:\r\n'
            '            continue\r\n'
            '        st, p = parts[0], parts[-1]\r\n'
            '        if st.startswith("A"):\r\n'
            '            added.append(p)\r\n'
            '        elif st.startswith("D"):\r\n'
            '            removed.append(p)\r\n'
            '        elif st.startswith("R") and len(parts) >= 3:\r\n'
            '            renamed.append({"from": parts[1], "to": parts[2]})\r\n'
            '        elif st.startswith("M"):\r\n'
            '            changed.append(p)\r\n'
            '    return added, removed, renamed, changed\r\n'
            '\r\n'
            '\r\n'
            'def _test_node_names(src):\r\n'
            '    try:\r\n'
            '        tree = ast.parse(src)\r\n'
            '    except (SyntaxError, ValueError):\r\n'
            '        return None                                    # unparsable -> UNKNOWN, never an empty lie\r\n'
            '    return sorted(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"))\r\n'
            '\r\n'
            '\r\n'
            'def _body_hashes(src):\r\n'
            '    """Cheap duplicate-candidate heuristic: normalized AST-dump hash per test function (a CANDIDATE, never a finding)."""\r\n'
            '    try:\r\n'
            '        tree = ast.parse(src)\r\n'
            '    except (SyntaxError, ValueError):\r\n'
            '        return {}\r\n'
            '    out = {}\r\n'
            '    for n in ast.walk(tree):\r\n'
            '        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):\r\n'
            '            body = ast.dump(ast.Module(body=n.body, type_ignores=[]))\r\n'
            '            out[n.name] = hashlib.sha1(body.encode()).hexdigest()\r\n'
            '    return out\r\n'
            '\r\n'
            '\r\n'
            'def _admission_metadata(rel, root):\r\n'
            '    """Parse the module docstring\'s \'Admission:\' directives; every missing field is UNKNOWN, never invented."""\r\n'
            '    try:\r\n'
            '        doc = ast.get_docstring(ast.parse((Path(root) / rel).read_text(encoding="utf-8"))) or ""\r\n'
            '    except (OSError, SyntaxError, UnicodeDecodeError):\r\n'
            '        return {}\r\n'
            '    meta = {}\r\n'
            '    for line in doc.splitlines():\r\n'
            '        if line.strip().lower().startswith("admission:"):\r\n'
            '            for item in line.split(":", 1)[1].split(","):\r\n'
            '                if "=" in item:\r\n'
            '                    k, v = item.split("=", 1)\r\n'
            '                    meta[k.strip().lower()] = v.strip()\r\n'
            '    return {f: meta.get(f, "UNKNOWN") for f in ADMISSION_FIELDS}\r\n'
            '\r\n'
            '\r\n'
            'def test_admission_report(base="origin/main", head="HEAD", plan_path=None, junit_paths=(), root=ROOT):\r\n'
            '    """B3 WARN-ONLY test-admission report over the trusted-base diff. Read-only: it never gates, never writes\r\n'
            '    repo files, and every unavailable measurement is UNKNOWN with its label — never zero, never a fabricated PASS."""\r\n'
            '    root = Path(root)\r\n'
            '    added, removed, renamed, changed = _git_name_status(base, head, root)\r\n'
            '    is_test = lambda p: p.startswith("tests/") and p.rsplit("/", 1)[-1].startswith("test_") and p.endswith(".py")\r\n'
            '    added, removed, changed = sorted(filter(is_test, added)), sorted(filter(is_test, removed)), sorted(filter(is_test, changed))\r\n'
            '\r\n'
            '    node_deltas, growth = [], {"added_modules": len(added), "removed_modules": len(removed), "renamed_modules": len(renamed),\r\n'
            '                               "added_nodes": 0, "removed_nodes": 0}\r\n'
            '    plan, selected_set = None, None\r\n'
            '    if plan_path:\r\n'
            '        try:\r\n'
            '            plan = json.loads(Path(plan_path).read_text())\r\n'
            '            selected_set = set(plan.get("pytest_modules", []))\r\n'
            '        except (OSError, ValueError):\r\n'
            '            plan = None\r\n'
            '    junit_secs, _jnodes = read_junit_module_seconds(sorted(junit_paths)) if junit_paths else ({}, {})\r\n'
            '\r\n'
            '    new_skips, duplicates, meta_rows = [], [], []\r\n'
            '    existing_hashes = {}\r\n'
            '    for rel in sorted(set(added) | set(changed)):\r\n'
            '        src_now = (root / rel).read_text(encoding="utf-8", errors="replace")\r\n'
            '        now_nodes = _test_node_names(src_now)\r\n'
            '        try:\r\n'
            '            src_base = subprocess.check_output(["git", "show", "%s:%s" % (base, rel)], cwd=root).decode("utf-8", "replace")\r\n'
            '            base_nodes = _test_node_names(src_base)\r\n'
            '        except subprocess.CalledProcessError:\r\n'
            '            src_base, base_nodes = None, []\r\n'
            '        if now_nodes is None or (src_base is not None and base_nodes is None):\r\n'
            '            status, added_n, removed_n = "UNKNOWN", [], []\r\n'
            '        else:\r\n'
            '            added_n = [n for n in (now_nodes or []) if n not in (base_nodes or [])]\r\n'
            '            removed_n = [n for n in (base_nodes or []) if n not in (now_nodes or [])]\r\n'
            '            status = "MEASURED_LOCAL"\r\n'
            '        growth["added_nodes"] += len(added_n)\r\n'
            '        growth["removed_nodes"] += len(removed_n)\r\n'
            '        node_deltas.append({"module": rel, "status": status, "added_nodes": added_n, "removed_nodes": removed_n,\r\n'
            '                            "selected": ("SELECTED" if (selected_set is not None and rel in selected_set)\r\n'
            '                                         else ("NOT_SELECTED" if selected_set is not None else "UNKNOWN")),\r\n'
            '                            "wall_s": (round(junit_secs[rel], 3) if rel in junit_secs else None),\r\n'
            '                            "wall_label": ("OBSERVED_HOSTED" if rel in junit_secs else "UNKNOWN"),\r\n'
            '                            "git_process_count": "UNKNOWN"})\r\n'
            '        if rel in added:\r\n'
            '            meta_rows.append({"module": rel, **_admission_metadata(rel, root)})\r\n'
            '        marks = [ln.strip() for ln in src_now.splitlines() if re.search(r"\\b(skip|xfail|skipif)\\b", ln) and ln.strip().startswith(("@", "pytest.mark"))]\r\n'
            '        new_skips += [{"module": rel, "marker": m[:120]} for m in marks[:3]]\r\n'
            '        if rel in added:\r\n'
            '            hashes = _body_hashes(src_now)\r\n'
            '            for existing in sorted((root / "tests").glob("test_*.py")):\r\n'
            '                erel = existing.as_posix()\r\n'
            '                if erel == rel:\r\n'
            '                    continue\r\n'
            '                if erel not in existing_hashes:\r\n'
            '                    existing_hashes[erel] = _body_hashes(existing.read_text(encoding="utf-8", errors="replace"))\r\n'
            '                for name, h in sorted(hashes.items()):\r\n'
            '                    for name2, h2 in sorted(existing_hashes[erel].items()):\r\n'
            '                        if h == h2:\r\n'
            '                            duplicates.append({"candidate": "%s::%s" % (rel, name), "existing": "%s::%s" % (erel, name2),\r\n'
            '                                               "heuristic": "identical-normalized-AST-body", "severity": "WARN"})\r\n'
            '\r\n'
            '    budget = budget_warnings(sorted(junit_paths)) if junit_paths else {"label": "WARN_ONLY", "enforced": False, "findings": [],\r\n'
            '                                                                       "note": "UNKNOWN (no junit supplied)"}\r\n'
            '    crit = {"label": "UNKNOWN (no plan supplied)"}\r\n'
            '    if plan and plan.get("schedule", {}).get("predicted_critical_path_s") is not None:\r\n'
            '        crit = {"plan_predicted_critical_path_s": plan["schedule"]["predicted_critical_path_s"],\r\n'
            '                "label": "SIMULATION (weights: measured accepted)", "enforced": False}\r\n'
            '\r\n'
            '    findings = []\r\n'
            '    for row in meta_rows:\r\n'
            '        for f, v in row.items():\r\n'
            '            if f != "module" and v == "UNKNOWN":\r\n'
            '                findings.append({"path": row["module"], "code": "ADM-METADATA-UNKNOWN", "field": f, "severity": "WARN",\r\n'
            '                                 "message": "admission metadata field is UNKNOWN: " + f})\r\n'
            '    for d in duplicates:\r\n'
            '        findings.append({"path": d["candidate"], "code": "ADM-DUPLICATE-CANDIDATE", "severity": "WARN",\r\n'
            '                         "message": "duplicate CANDIDATE (heuristic only, never automatic): %s" % d["existing"]})\r\n'
            '    if new_skips:\r\n'
            '        findings.append({"code": "ADM-NEW-SKIP", "severity": "WARN",\r\n'
            '                         "message": "new skip/xfail markers present: a skipped node is never PASS (%d markers)" % len(new_skips)})\r\n'
            '\r\n'
            '    return {"label": "WARN_ONLY", "what": "B3 test-admission report over the trusted-base diff",\r\n'
            '            "base": base, "head": head, "tested_sha_from_plan": (plan or {}).get("tested_sha", "UNKNOWN"),\r\n'
            '            "modules": {"added": added, "removed": removed, "renamed": renamed, "changed": changed},\r\n'
            '            "node_deltas": node_deltas, "growth": growth,\r\n'
            '            "admission_metadata": meta_rows, "duplicate_candidates": duplicates, "new_skip_markers": new_skips,\r\n'
            '            "critical_path": crit, "budgets": budget, "findings": findings,\r\n'
            '            "labels_used": ["MEASURED_LOCAL", "OBSERVED_HOSTED", "SIMULATION", "UNKNOWN", "WARN_ONLY"],\r\n'
            '            "exit_code_policy": "always 0: informational, never a gate"}\r\n'
            '\r\n'
            '\r\n'
            'if __name__ == "__main__":\r\n'
            '    sys.exit(main())\r\n')),
    ],
    'tests/fin_v2_cohorts.py': [
        ("                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope')\n",
         "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope')\n"),
    ],
    'tests/test_bess02_scope.py': [
        ("                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
    ],
    'tests/test_c06_cost_workspace_scope.py': [
        ("    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))       # C06 is followed by at most the one reviewed B1 successor\n",
         "    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))       # C06 is followed by the reviewed B1, B2 and B3 successors\n"),
        ("            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'):         # a successor never attests an older accepted ref\n",
         "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'):         # a successor never attests an older accepted ref\n"),
    ],
    'tests/test_ci_v4_lean_b1_scope.py': [
        ('                   for p in T.OWNED_PATHS | {T.MANIFEST})\n',
         (
            '                   for p in T.OWNED_PATHS | {T.MANIFEST})\n'
            '    T2 = T._next()\n'
            '    T3 = T2._next() if T2 is not None and T2.signature_ok() else None\n')),
        ('    for path in T.FROZEN:\n',
         (
            '    for path in T.FROZEN:\n'
            "        if T3 is not None and T2 is not None and T2.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and path in T3.HANDOFFS:      # the reviewed B3 successor owns this control file's further substitution\n"
            '            assert (ROOT / path).read_bytes() == T3.expected_handoff(ROOT, path), path\n'
            '            continue\n')),
        ('    N = T._next()\n',
         (
            '    N = T._next()\n'
            '    N2 = N._next() if N is not None and N.signature_ok() else None\n')),
        ('    for p in T.HANDOFFS:\n',
         (
            '    for p in T.HANDOFFS:\n'
            '        if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n')),
        ('    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-3:] if m != "tests.ci_v4_lean_b2_scope") == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope")\n',
         '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-4:] if m != "tests.ci_v4_lean_b3_scope") == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'),
        ('    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')"\n',
         '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')"\n'),
        ('        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n',
         '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'),
        ('        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n',
         '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'),
    ],
    'tests/test_ci_v4_lean_b2_scope.py': [
        ('    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n',
         (
            '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
            '    T3 = T._next()\n')),
        ('        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n',
         (
            '        if T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p in T3.HANDOFFS:      # the reviewed B3 substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)\n'
            '        else:\n'
            '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n')),
        ((
            '    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[-3:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
            '    assert B.SUCCESSOR == T.__name__ and B._next() is T and K.SUCCESSOR == B.__name__ and K._next() is B\n'),
         (
            '    assert C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"))\n'
            '    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B\n'
            '    from tests import ci_v4_lean_b3_scope as T3\n'
            '    if T.SUCCESSOR in C.COHORT_MODULES:\n'
            '        assert C.COHORT_MODULES[-1] == T.SUCCESSOR and T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"\n')),
        ('    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n',
         '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"))\n'),
        ('    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')"\n',
         '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')"\n'),
        ('        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n',
         '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'),
    ],
    'tests/test_ci_v4_lean_report.py': [
        ((
            '"""CI V4 Lean B1 report: the measurement / SIMULATION / WARN-ONLY helpers never gate, never mutate the repository and never present a local\n'
            'measurement or a simulation as hosted evidence. Risk protected: an informational tool silently becoming a blocking gate or a fake PASS."""\n'
            'import json\n'
            'import subprocess\n'
            'import sys\n'
            'import textwrap\n'
            'from pathlib import Path\n'
            '\n'
            'import pytest\n'
            '\n'
            'from tests import ci_v4_lean_report as R\n'
            '\n'
            'ROOT = Path(__file__).resolve().parents[1]\n'
            '\n'
            '\n'
            'def _junit(tmp_path, cases, name="j.xml"):\n'
            '    rows = "".join("<testcase classname=\'%s\' name=\'%s\' time=\'%s\'/>" % c for c in cases)\n'
            '    p = tmp_path / name\n'
            '    p.write_text("<testsuites><testsuite>%s</testsuite></testsuites>" % rows)\n'
            '    return p\n'
            '\n'
            '\n'
            'def test_git_subprocess_counter_counts_only_git_and_restores_popen():\n'
            '    before = subprocess.Popen.__init__\n'
            '    with R.git_subprocess_counter() as c:\n'
            '        subprocess.run(["git", "--version"], capture_output=True)\n'
            '        subprocess.run(["git", "--version"], capture_output=True)\n'
            '        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)\n'
            '    assert c == {"git": 2, "other": 1}\n'
            '    assert subprocess.Popen.__init__ is before            # nothing stays patched\n'
            '\n'
            '\n'
            'def test_every_report_is_labelled_and_a_simulation_is_never_hosted_evidence():\n'
            '    sim = R.simulate_workers(["tests/a.py", "tests/b.py", "tests/c.py"], {"tests/a.py": 30.0, "tests/b.py": 20.0, "tests/c.py": 10.0}, weights_source="unit")\n'
            '    assert sim["label"] == "SIMULATION" and "NOT hosted evidence" in sim["disclaimer"]\n'
            '    assert [r["workers"] for r in sim["rows"]] == list(R.SIM_WORKERS) == [3, 4, 5, 6, 8]\n'
            '    assert R.admission_report([])["label"] == "WARN_ONLY" and R.budget_warnings([])["label"] == "WARN_ONLY"\n'
            '    assert set(R.LABELS) == {"MEASURED_LOCAL", "SIMULATION", "WARN_ONLY"}\n'
            '\n'
            '\n'
            'def test_simulation_is_deterministic_conserves_work_and_prices_unknown_modules_conservatively():\n'
            '    w = {"tests/a.py": 100.0, "tests/b.py": 100.0, "tests/c.py": 50.0}\n'
            '    mods = ["tests/c.py", "tests/a.py", "tests/b.py", "tests/new_unweighted.py"]\n'
            '    one = R.simulate_workers(mods, w, weights_source="unit")\n'
            '    two = R.simulate_workers(list(reversed(mods)), w, weights_source="unit")\n'
            '    assert one == two                                            # order-independent, deterministic tie-breaks\n'
            '    assert one["unknown_modules"] == ["tests/new_unweighted.py"]  # never silently zero\n'
            '    assert one["total_weight_s"] == 100 + 100 + 50 + one["default_module_s_for_unknown"]\n'
            '    for row in one["rows"]:\n'
            '        assert row["runner_s"] == one["total_weight_s"]           # LPT only moves work between workers, it never loses any\n'
            '\n'
            '\n'
            'def test_simulation_with_the_recorded_weights_names_its_provenance():\n'
            '    sim = R.simulate_workers(["tests/test_ci_v4_aggregate.py"])\n'
            '    assert sim["weights_source"] and sim["weights_source"] != "supplied" and sim["rows"]\n'
            '\n'
            '\n'
            'def test_collection_output_parser_reads_node_ids_and_errors():\n'
            '    nodes, errors = R.parse_collect_output(textwrap.dedent("""\\\n'
            '        tests/test_a.py::test_one\n'
            '        tests/test_a.py::test_two[param-1]\n'
            '        ERROR tests/test_bad.py\n'
            '        2 tests collected, 1 error in 0.1s\n'
            '        """))\n'
            '    assert nodes == ["tests/test_a.py::test_one", "tests/test_a.py::test_two[param-1]"] and errors == ["ERROR tests/test_bad.py"]\n'
            '\n'
            '\n'
            'def test_collection_digest_is_stable_and_order_independent_for_a_real_module():\n'
            '    a = R.collection_digest(["tests/test_ci_v4_lean_report.py"])\n'
            '    b = R.collection_digest(["tests/test_ci_v4_lean_report.py"])\n'
            '    assert a["label"] == "MEASURED_LOCAL" and a["collected_nodes"] >= 8 and a["collection_errors"] == []\n'
            '    assert a["node_id_sha256"] == b["node_id_sha256"] and a["collected_nodes"] == b["collected_nodes"]\n'
            '    assert "NOT derived from collection" in a["note"]            # collected is never reported as selected / executed / passed\n'
            '\n'
            '\n'
            'def test_weights_proposal_is_not_active_deterministic_and_keeps_unknown_unknown(tmp_path):\n'
            '    j = _junit(tmp_path, [("tests.test_ci_v4_aggregate", "test_one", 2.5), ("tests.test_ci_v4_aggregate", "test_two", 1.5)])\n'
            '    cur = {"tests/test_ci_v4_aggregate.py": 99.0, "tests/test_ci_v4_select.py": 7.0}\n'
            '    before = (ROOT / "docs/ci_v4/module_weights.json").read_bytes()\n'
            '    p1 = R.propose_weights([j], cur, "unit-provenance", "run-1")\n'
            '    p2 = R.propose_weights([j], cur, "unit-provenance", "run-1")\n'
            '    assert p1 == p2 and p1["status"] == "PROPOSAL_NOT_ACTIVE"\n'
            '    assert p1["modules"]["tests/test_ci_v4_aggregate.py"] == 4.0\n'
            '    assert p1["modules"]["tests/test_ci_v4_select.py"] == 7.0 and p1["kept_previous_weight"] == ["tests/test_ci_v4_select.py"]\n'
            '    assert (ROOT / "docs/ci_v4/module_weights.json").read_bytes() == before      # the active weights file is never written\n'
            '\n'
            '\n'
            'def test_admission_report_is_warn_only_and_flags_the_proposed_checklist_items(tmp_path):\n'
            '    f = tmp_path / "test_sample.py"\n'
            "    f.write_text(textwrap.dedent('''\\\n"
            '        import subprocess\n'
            '        import pytest\n'
            '\n'
            '        @pytest.mark.skip\n'
            '        def test_reads_source(tmp_path):\n'
            '            text = (tmp_path / "x.py").read_text()\n'
            '            assert "needle" in text\n'
            '\n'
            '        def test_git_in_a_loop():\n'
            '            for p in ("a", "b"):\n'
            '                subprocess.check_output(["git", "status", p])\n'
            "        '''))\n"
            '    rep = R.admission_report([str(f)])\n'
            '    codes = {x["code"] for x in rep["findings"]}\n'
            '    assert {"ADM-RISK", "ADM-SOURCE-TEXT", "ADM-GIT-LOOP", "ADM-SKIP"} <= codes\n'
            '    assert rep["label"] == "WARN_ONLY" and rep["budgets"]["enforced"] is False and rep["budgets"]["approved_by_owner"] is False\n'
            '    assert all(x["severity"] == "WARN" for x in rep["findings"])\n'
            '\n'
            '\n'
            'def test_a_documented_clean_test_has_no_admission_warning(tmp_path):\n'
            '    f = tmp_path / "test_clean.py"\n'
            '    f.write_text(\'"""Risk protected: a negative control that fails closed."""\\n\\ndef test_ok():\\n    assert 1 + 1 == 2\\n\')\n'
            '    assert R.admission_report([str(f)])["findings"] == []\n'
            '\n'
            '\n'
            'def test_budget_warnings_use_the_proposed_not_approved_thresholds(tmp_path):\n'
            '    j = _junit(tmp_path, [("tests.t", "fast", 59), ("tests.t", "slow", 130), ("tests.t", "huge", 310)])\n'
            '    rep = R.budget_warnings([j])\n'
            '    levels = {r["id"]: r["level"] for r in rep["findings"] if r["kind"] == "node"}\n'
            '    assert levels == {"tests.t::slow": "WARN", "tests.t::huge": "EXCEPTION"} and rep["enforced"] is False\n'
            '\n'
            '\n'
            'def test_the_cli_never_gates_even_when_it_finds_warnings(tmp_path):\n'
            '    f = tmp_path / "test_bad.py"\n'
            '    f.write_text("def test_x():\\n    assert True\\n")\n'
            '    out = tmp_path / "o.json"\n'
            '    assert R.main(["admission", "--output", str(out), str(f)]) == 0\n'
            '    data = json.loads(out.read_text())\n'
            '    assert data["schema"] == R.SCHEMA and data["warnings"] >= 1 and data["exit_code_policy"].startswith("always 0")\n'
            '    r = subprocess.run([sys.executable, "-m", "tests.ci_v4_lean_report", "admission", str(f)], cwd=ROOT, capture_output=True, text=True)\n'
            '    assert r.returncode == 0 and "WARN_ONLY" in r.stdout\n'
            '\n'
            '\n'
            'def test_the_report_module_is_not_wired_into_selection_scheduling_or_aggregation():\n'
            '    """It must stay opt-in: none of the CI V4 tools imports it, and it writes no tracked file by default."""\n'
            '    for tool in ("ci_v4_select", "ci_v4_schedule", "ci_v4_aggregate", "ci_v4_governance_gate", "ci_v4_activate", "ci_v4_shard", "ci_v4_nodes"):\n'
            '        assert "ci_v4_lean_report" not in (ROOT / "tools" / (tool + ".py")).read_text(), tool\n'
            '    workflows = "".join(p.read_text() for p in (ROOT / ".github/workflows").glob("ci_v4_*.yml"))\n'
            '    assert "ci_v4_lean_report" not in workflows\n'),
         (
            '"""CI V4 Lean B1 report: the measurement / SIMULATION / WARN-ONLY helpers never gate, never mutate the repository and never present a local\r\n'
            'measurement or a simulation as hosted evidence. Risk protected: an informational tool silently becoming a blocking gate or a fake PASS."""\r\n'
            'import json\r\n'
            'import subprocess\r\n'
            'import sys\r\n'
            'import textwrap\r\n'
            'from pathlib import Path\r\n'
            '\r\n'
            'import pytest\r\n'
            '\r\n'
            'from tests import ci_v4_lean_report as R\r\n'
            '\r\n'
            'ROOT = Path(__file__).resolve().parents[1]\r\n'
            '\r\n'
            '\r\n'
            'def _junit(tmp_path, cases, name="j.xml"):\r\n'
            '    rows = "".join("<testcase classname=\'%s\' name=\'%s\' time=\'%s\'/>" % c for c in cases)\r\n'
            '    p = tmp_path / name\r\n'
            '    p.write_text("<testsuites><testsuite>%s</testsuite></testsuites>" % rows)\r\n'
            '    return p\r\n'
            '\r\n'
            '\r\n'
            'def test_git_subprocess_counter_counts_only_git_and_restores_popen():\r\n'
            '    before = subprocess.Popen.__init__\r\n'
            '    with R.git_subprocess_counter() as c:\r\n'
            '        subprocess.run(["git", "--version"], capture_output=True)\r\n'
            '        subprocess.run(["git", "--version"], capture_output=True)\r\n'
            '        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)\r\n'
            '    assert c == {"git": 2, "other": 1}\r\n'
            '    assert subprocess.Popen.__init__ is before            # nothing stays patched\r\n'
            '\r\n'
            '\r\n'
            'def test_every_report_is_labelled_and_a_simulation_is_never_hosted_evidence():\r\n'
            '    sim = R.simulate_workers(["tests/a.py", "tests/b.py", "tests/c.py"], {"tests/a.py": 30.0, "tests/b.py": 20.0, "tests/c.py": 10.0}, weights_source="unit")\r\n'
            '    assert sim["label"] == "SIMULATION" and "NOT hosted evidence" in sim["disclaimer"]\r\n'
            '    assert [r["workers"] for r in sim["rows"]] == list(R.SIM_WORKERS) == [3, 4, 5, 6, 8]\r\n'
            '    assert R.admission_report([])["label"] == "WARN_ONLY" and R.budget_warnings([])["label"] == "WARN_ONLY"\r\n'
            '    assert set(R.LABELS) == {"MEASURED_LOCAL", "SIMULATION", "WARN_ONLY"}\r\n'
            '\r\n'
            '\r\n'
            'def test_simulation_is_deterministic_conserves_work_and_prices_unknown_modules_conservatively():\r\n'
            '    w = {"tests/a.py": 100.0, "tests/b.py": 100.0, "tests/c.py": 50.0}\r\n'
            '    mods = ["tests/c.py", "tests/a.py", "tests/b.py", "tests/new_unweighted.py"]\r\n'
            '    one = R.simulate_workers(mods, w, weights_source="unit")\r\n'
            '    two = R.simulate_workers(list(reversed(mods)), w, weights_source="unit")\r\n'
            '    assert one == two                                            # order-independent, deterministic tie-breaks\r\n'
            '    assert one["unknown_modules"] == ["tests/new_unweighted.py"]  # never silently zero\r\n'
            '    assert one["total_weight_s"] == 100 + 100 + 50 + one["default_module_s_for_unknown"]\r\n'
            '    for row in one["rows"]:\r\n'
            '        assert row["runner_s"] == one["total_weight_s"]           # LPT only moves work between workers, it never loses any\r\n'
            '\r\n'
            '\r\n'
            'def test_simulation_with_the_recorded_weights_names_its_provenance():\r\n'
            '    sim = R.simulate_workers(["tests/test_ci_v4_aggregate.py"])\r\n'
            '    assert sim["weights_source"] and sim["weights_source"] != "supplied" and sim["rows"]\r\n'
            '\r\n'
            '\r\n'
            'def test_collection_output_parser_reads_node_ids_and_errors():\r\n'
            '    nodes, errors = R.parse_collect_output(textwrap.dedent("""\\\r\n'
            '        tests/test_a.py::test_one\r\n'
            '        tests/test_a.py::test_two[param-1]\r\n'
            '        ERROR tests/test_bad.py\r\n'
            '        2 tests collected, 1 error in 0.1s\r\n'
            '        """))\r\n'
            '    assert nodes == ["tests/test_a.py::test_one", "tests/test_a.py::test_two[param-1]"] and errors == ["ERROR tests/test_bad.py"]\r\n'
            '\r\n'
            '\r\n'
            'def test_collection_digest_is_stable_and_order_independent_for_a_real_module():\r\n'
            '    a = R.collection_digest(["tests/test_ci_v4_lean_report.py"])\r\n'
            '    b = R.collection_digest(["tests/test_ci_v4_lean_report.py"])\r\n'
            '    assert a["label"] == "MEASURED_LOCAL" and a["collected_nodes"] >= 8 and a["collection_errors"] == []\r\n'
            '    assert a["node_id_sha256"] == b["node_id_sha256"] and a["collected_nodes"] == b["collected_nodes"]\r\n'
            '    assert "NOT derived from collection" in a["note"]            # collected is never reported as selected / executed / passed\r\n'
            '\r\n'
            '\r\n'
            'def test_weights_proposal_is_not_active_deterministic_and_keeps_unknown_unknown(tmp_path):\r\n'
            '    j = _junit(tmp_path, [("tests.test_ci_v4_aggregate", "test_one", 2.5), ("tests.test_ci_v4_aggregate", "test_two", 1.5)])\r\n'
            '    cur = {"tests/test_ci_v4_aggregate.py": 99.0, "tests/test_ci_v4_select.py": 7.0}\r\n'
            '    before = (ROOT / "docs/ci_v4/module_weights.json").read_bytes()\r\n'
            '    p1 = R.propose_weights([j], cur, "unit-provenance", "run-1")\r\n'
            '    p2 = R.propose_weights([j], cur, "unit-provenance", "run-1")\r\n'
            '    assert p1 == p2 and p1["status"] == "PROPOSAL_NOT_ACTIVE"\r\n'
            '    assert p1["modules"]["tests/test_ci_v4_aggregate.py"] == 4.0\r\n'
            '    assert p1["modules"]["tests/test_ci_v4_select.py"] == 7.0 and p1["kept_previous_weight"] == ["tests/test_ci_v4_select.py"]\r\n'
            '    assert (ROOT / "docs/ci_v4/module_weights.json").read_bytes() == before      # the active weights file is never written\r\n'
            '\r\n'
            '\r\n'
            'def test_admission_report_is_warn_only_and_flags_the_proposed_checklist_items(tmp_path):\r\n'
            '    f = tmp_path / "test_sample.py"\r\n'
            "    f.write_text(textwrap.dedent('''\\\r\n"
            '        import subprocess\r\n'
            '        import pytest\r\n'
            '\r\n'
            '        @pytest.mark.skip\r\n'
            '        def test_reads_source(tmp_path):\r\n'
            '            text = (tmp_path / "x.py").read_text()\r\n'
            '            assert "needle" in text\r\n'
            '\r\n'
            '        def test_git_in_a_loop():\r\n'
            '            for p in ("a", "b"):\r\n'
            '                subprocess.check_output(["git", "status", p])\r\n'
            "        '''))\r\n"
            '    rep = R.admission_report([str(f)])\r\n'
            '    codes = {x["code"] for x in rep["findings"]}\r\n'
            '    assert {"ADM-RISK", "ADM-SOURCE-TEXT", "ADM-GIT-LOOP", "ADM-SKIP"} <= codes\r\n'
            '    assert rep["label"] == "WARN_ONLY" and rep["budgets"]["enforced"] is False and rep["budgets"]["approved_by_owner"] is False\r\n'
            '    assert all(x["severity"] == "WARN" for x in rep["findings"])\r\n'
            '\r\n'
            '\r\n'
            'def test_a_documented_clean_test_has_no_admission_warning(tmp_path):\r\n'
            '    f = tmp_path / "test_clean.py"\r\n'
            '    f.write_text(\'"""Risk protected: a negative control that fails closed."""\\n\\ndef test_ok():\\n    assert 1 + 1 == 2\\n\')\r\n'
            '    assert R.admission_report([str(f)])["findings"] == []\r\n'
            '\r\n'
            '\r\n'
            'def test_budget_warnings_use_the_proposed_not_approved_thresholds(tmp_path):\r\n'
            '    j = _junit(tmp_path, [("tests.t", "fast", 59), ("tests.t", "slow", 130), ("tests.t", "huge", 310)])\r\n'
            '    rep = R.budget_warnings([j])\r\n'
            '    levels = {r["id"]: r["level"] for r in rep["findings"] if r["kind"] == "node"}\r\n'
            '    assert levels == {"tests.t::slow": "WARN", "tests.t::huge": "EXCEPTION"} and rep["enforced"] is False\r\n'
            '\r\n'
            '\r\n'
            'def test_the_cli_never_gates_even_when_it_finds_warnings(tmp_path):\r\n'
            '    f = tmp_path / "test_bad.py"\r\n'
            '    f.write_text("def test_x():\\n    assert True\\n")\r\n'
            '    out = tmp_path / "o.json"\r\n'
            '    assert R.main(["admission", "--output", str(out), str(f)]) == 0\r\n'
            '    data = json.loads(out.read_text())\r\n'
            '    assert data["schema"] == R.SCHEMA and data["warnings"] >= 1 and data["exit_code_policy"].startswith("always 0")\r\n'
            '    r = subprocess.run([sys.executable, "-m", "tests.ci_v4_lean_report", "admission", str(f)], cwd=ROOT, capture_output=True, text=True)\r\n'
            '    assert r.returncode == 0 and "WARN_ONLY" in r.stdout\r\n'
            '\r\n'
            '\r\n'
            'def test_the_report_module_is_not_wired_into_selection_scheduling_or_aggregation():\r\n'
            '    """It must stay opt-in: none of the CI V4 tools imports it, and it writes no tracked file by default."""\r\n'
            '    for tool in ("ci_v4_select", "ci_v4_schedule", "ci_v4_aggregate", "ci_v4_governance_gate", "ci_v4_activate", "ci_v4_shard", "ci_v4_nodes"):\r\n'
            '        assert "ci_v4_lean_report" not in (ROOT / "tools" / (tool + ".py")).read_text(), tool\r\n'
            '    workflows = "".join(p.read_text() for p in (ROOT / ".github/workflows").glob("ci_v4_*.yml"))\r\n'
            '    assert "ci_v4_lean_report" not in workflows\r\n'
            '\r\n'
            '\r\n'
            '# -------------------------------------------------------------------------------------------- B3 test-admission report (targeted cases)\r\n'
            'from tests import ci_v4_lean_report as _B3R\r\n'
            '\r\n'
            "_ADM_META = 'Admission: risk=probe-only, nearest=none, witness=red-before-green missing, tier=fast, owner=ci, retire=when-flaky'\r\n"
            '\r\n'
            '\r\n'
            '@pytest.fixture()\r\n'
            'def b3_repo(tmp_path):\r\n'
            '    root = tmp_path / "b3repo"\r\n'
            '    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])\r\n'
            '    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=root)\r\n'
            '    subprocess.check_call(["git", "config", "user.name", "t"], cwd=root)\r\n'
            '    subprocess.check_call(["git", "checkout", "-q", "-b", "b3-probe"], cwd=root)\r\n'
            '    return root\r\n'
            '\r\n'
            '\r\n'
            'def _b3_commit(root, msg="probe"):\r\n'
            '    subprocess.check_call(["git", "add", "-A"], cwd=root)\r\n'
            '    subprocess.check_call(["git", "commit", "-q", "--allow-empty", "-m", msg], cwd=root)\r\n'
            '    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_normal_addition_is_listed_with_labels(b3_repo):\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_normal.py").write_text(\r\n'
            '        "\'%s\'\\n\\ndef test_b3_probe_normal():\\n    assert True\\n" % _ADM_META)\r\n'
            '    head = _b3_commit(b3_repo)\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\r\n'
            '    assert rep["modules"]["added"] == ["tests/test_b3_probe_normal.py"]\r\n'
            '    row = rep["node_deltas"][0]\r\n'
            '    assert row["added_nodes"] == ["test_b3_probe_normal"] and row["status"] == "MEASURED_LOCAL"\r\n'
            '    assert row["selected"] == "UNKNOWN" and row["wall_label"] == "UNKNOWN" and row["git_process_count"] == "UNKNOWN"\r\n'
            '    assert all(v != "UNKNOWN" for k, v in rep["admission_metadata"][0].items() if k != "module")\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_duplicate_candidate_is_heuristic_warn_only(b3_repo):\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_dup.py").write_text(\r\n'
            '        "def test_b3_probe_dup():\\n    value = 1 + 1\\n    assert value == 2\\n")\r\n'
            '    _b3_commit(b3_repo)\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_dup2.py").write_text(\r\n'
            '        "def test_b3_probe_dup2():\\n    value = 1 + 1\\n    assert value == 2\\n")\r\n'
            '    head = _b3_commit(b3_repo)\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~2", head=head, root=b3_repo)\r\n'
            '    assert rep["duplicate_candidates"], "identical normalized bodies must surface as CANDIDATES"\r\n'
            '    assert all(d["severity"] == "WARN" for d in rep["duplicate_candidates"])\r\n'
            '    assert rep["label"] == "WARN_ONLY"\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_missing_metadata_is_unknown_never_invented(b3_repo):\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_nodoc.py").write_text("def test_b3_probe_nodoc():\\n    assert 1\\n")\r\n'
            '    head = _b3_commit(b3_repo)\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\r\n'
            '    meta = rep["admission_metadata"][0]\r\n'
            '    assert all(v == "UNKNOWN" for k, v in meta.items() if k != "module")\r\n'
            '    assert any(f["code"] == "ADM-METADATA-UNKNOWN" for f in rep["findings"])\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_new_skip_is_reported_never_pass(b3_repo):\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_skip.py").write_text(\r\n'
            '        "import pytest\\n\\n\\n@pytest.mark.skip(reason=\'probe\')\\ndef test_b3_probe_skip():\\n    assert True\\n")\r\n'
            '    head = _b3_commit(b3_repo)\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\r\n'
            '    assert rep["new_skip_markers"], "a new skip must be visible; a skipped node is never PASS"\r\n'
            '    assert any(f["code"] == "ADM-NEW-SKIP" for f in rep["findings"])\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_tool_failure_is_reported_inside_json_never_as_exit(b3_repo):\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_broken.py").write_text("def broken(:\\n")\r\n'
            '    head = _b3_commit(b3_repo)\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\r\n'
            '    assert rep["node_deltas"][0]["status"] == "UNKNOWN"      # unparsable source is UNKNOWN, never an empty lie\r\n'
            '    assert rep["exit_code_policy"].startswith("always 0")\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_unchanged_fast_path_is_empty(b3_repo):\r\n'
            '    head = _b3_commit(b3_repo, "empty")\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\r\n'
            '    assert rep["modules"]["added"] == [] and rep["modules"]["removed"] == [] and rep["modules"]["changed"] == []\r\n'
            '    assert rep["node_deltas"] == [] and rep["growth"]["added_nodes"] == 0\r\n'
            '\r\n'
            '\r\n'
            'def test_b3_admission_plan_status_selected_vs_not_selected(b3_repo):\r\n'
            '    plan = {"pytest_modules": ["tests/test_b3_probe_in_plan.py"], "schedule": {"predicted_critical_path_s": None}}\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_in_plan.py").write_text("def test_in_plan():\\n    assert True\\n")\r\n'
            '    (b3_repo / "tests" / "test_b3_probe_out_plan.py").write_text("def test_out_plan():\\n    assert True\\n")\r\n'
            '    pf = b3_repo / "plan.json"\r\n'
            '    pf.write_text(json.dumps(plan))\r\n'
            '    head = _b3_commit(b3_repo)\r\n'
            '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, plan_path=str(pf), root=b3_repo)\r\n'
            '    by_mod = {r["module"]: r for r in rep["node_deltas"]}\r\n'
            '    assert by_mod["tests/test_b3_probe_in_plan.py"]["selected"] == "SELECTED"\r\n'
            '    assert by_mod["tests/test_b3_probe_out_plan.py"]["selected"] == "NOT_SELECTED"\r\n'
            '    assert rep["critical_path"]["plan_predicted_critical_path_s"] is None\r\n')),
    ],
    'tests/test_ci_v4_lean_tamper_matrix.py': [
        ('TAIL = "\'tests.ci_v4_lean_b2_scope\')"\n',
         'TAIL = "\'tests.ci_v4_lean_b3_scope\')"\n'),
        ('    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "\'tests.ci_v4_lean_b2_scope\', " + TAIL), REG, "pinned"),\n',
         '    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "\'tests.ci_v4_lean_b3_scope\', " + TAIL), REG, "pinned"),\n'),
        ('    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v4_lean_b2_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n',
         '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v4_lean_b3_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'),
    ],
    'tests/test_ci_v4_perf_scope.py': [
        ((
            '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"),
         (
            '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n")),
        ("                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')")\n',
         '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")\n'),
    ],
    'tests/test_f03_financing_scope.py': [
        ("        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/test_f04_financing_scope.py': [
        ("        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('        authority=B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n',
         (
            '        B3=B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        authority=B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and path in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n')),
        ((
            '        _B1=C06_APPROVAL._next();_B2=_B1._next() if _B1 is not None and _B1.signature_ok() else None\n'
            "        expected=json.loads(_B2.expected_map(ROOT,path,_B2.effective_pins()) if _B2 is not None and _B2.signature_ok() else C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n"),
         (
            '        _B1=C06_APPROVAL._next();_B2=_B1._next() if _B1 is not None and _B1.signature_ok() else None;_B3=_B2._next() if _B2 is not None and _B2.signature_ok() else None\n'
            "        expected=json.loads(_B3.expected_map(ROOT,path,_B3.effective_pins()) if _B3 is not None and _B2 is not None and _B2.SUCCESSOR in C.COHORT_MODULES and _B3.signature_ok() else _B2.expected_map(ROOT,path,_B2.effective_pins()) if _B2 is not None and _B2.signature_ok() else C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n")),
    ],
    'tests/test_post432_l01_l02_scope.py': [
        ("    if 'tests.ci_v4_lean_b2_scope' in C.COHORT_MODULES and B2 is not None and B2.signature_ok():\n",
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            "    if 'tests.ci_v4_lean_b3_scope' in C.COHORT_MODULES and B3 is not None and B3.signature_ok():\n"
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'
            "    elif 'tests.ci_v4_lean_b2_scope' in C.COHORT_MODULES and B2 is not None and B2.signature_ok():\n")),
    ],
    'tests/test_r02_ppa_ux_scope.py': [
        ("                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope') if m in C.COHORT_MODULES)\n",
         "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope') if m in C.COHORT_MODULES)\n"),
        ('    if len(nxt) == 9 and B2 is not None and B2.signature_ok():\n',
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    if len(nxt) == 10 and B3 is not None and B3.signature_ok():\n'
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'
            '    elif len(nxt) == 9 and B2 is not None and B2.signature_ok():\n')),
    ],
    'tests/test_r03_ppa_scope.py': [
        ('    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n',
         (
            '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n')),
        ('        authority = B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n',
         '        authority = B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n'),
        ("        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/test_r04_ppa_scope.py': [
        ('    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\'))\n',
         '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'))\n'),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/test_t01e_remediation_scope.py': [
        ('        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n',
         (
            '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
            '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS:            # the further reviewed B3 substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == B3.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n')),
        ('                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\'))\n',
         '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'))\n'),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/u1_scope.py': [
        ("RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope')\n",
         "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope')\n"),
    ],
}


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
    return tuple(MAP_KEYS)


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
    return _blob(expected_map(Path(root), path, dict(zip(MAP_KEYS, moved))))


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
        if pins.get("tests/ci_v4_lean_b3_scope.py") != _MODULE_BLOB:
            return False
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if d.get("source_modes") != {p: "100644" for p in OWNED_PATHS} or d.get("base_modes") != {p: "100644" for p in SUPERSEDED}:
            return False
        if not NEW.isdisjoint(base) or any(p.startswith(FORBIDDEN) or p.startswith("/") or ".." in p.split("/") or "*" in p
                                           for p in OWNED_PATHS | {MANIFEST}):
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
        if any(pins[p] != _expected_blob(key, p) for p in HANDOFFS):
            return False
        if set(HANDOFFS) != HANDOFF_PATHS:
            return False
        for p in CURRENT_MAPS:
            if pins[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):
                return False
        if closure:
            for p in CURRENT_MAPS:
                if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):
                    return False
        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(Path(repo) if repo is not None else ROOT, ref, "exact")


def _diff_ok(root, ref):
    try:
        allowed = OWNED_PATHS | {MANIFEST}
        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref else []), "--").decode().splitlines())
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
    return dict(manifest(repo, ref).get("source_blobs", {}))


def closure_paths(repo=None, ref=None):
    return OWNED_PATHS | {MANIFEST} if signature_ok(repo, ref) else frozenset()


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | {MANIFEST} and signature_ok(repo, ref)


def supersedes(path, value, repo=None, ref=None):
    if path not in SUPERSEDED:
        return False
    # The signature decides a supersession; the composite separately requires every cohort's FULL exactness (map bytes, changed set, untracked
    # files), so a signature-only verdict never makes the tree valid.
    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value


def nontrust_scope_authorized(changed, repo=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:
            return False
        actual = set(_git(root, "diff", "--name-only", BASE).decode().splitlines())
        return bool(actual) and actual == set(changed) and actual <= OWNED_PATHS | {MANIFEST} and exact_blobs_ok(root)
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

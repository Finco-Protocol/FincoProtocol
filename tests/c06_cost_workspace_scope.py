"""C06: finite presentation, served bundle and provenance closure after accepted isolated R04.

No financial, security or CI authority changes. Low-level signatures never call predecessors or the composite.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'b1c08e2d00fe9933565d253d5cee6e5849b143e1'
BASE_TREE = '5b25c1f245d3d53d9bbe24060c13dc936e06b8d7'
BASE_COHORTS = ('tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope')
MANIFEST = "docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json"
SCHEMA = "C06_COST_WORKSPACE_EXACT_SOURCE_V1"
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/r04_ppa_scope.py"
SOURCE_PATHS = frozenset(('docs/react_migration/c06_cost_workspace/C06_LEDGER.md',
 'frontend/src/app/capex/ProfileDraftProvider.tsx',
 'frontend/src/app/capex/ProfileRowEditor.tsx',
 'frontend/src/app/capex/__tests__/userLineProfile.test.mjs',
 'frontend/src/app/capex/profileFocus.ts',
 'frontend/src/app/editing/CostLinesGridView.tsx',
 'static/react/finco-react.js',
 'tests/test_c06_cost_workspace_browser.py',
 'tests/test_c06_custom_capex_profile_replay.py'))
NEW = frozenset(('docs/react_migration/c06_cost_workspace/C06_LEDGER.md',
 'frontend/src/app/capex/__tests__/userLineProfile.test.mjs',
 'tests/c06_cost_workspace_scope.py',
 'tests/test_c06_cost_workspace_browser.py',
 'tests/test_c06_cost_workspace_scope.py',
 'tests/test_c06_custom_capex_profile_replay.py'))
HANDOFF_PATHS = frozenset(('tests/fin_v2_cohorts.py',
 'tests/r04_ppa_scope.py',
 'tests/test_bess02_scope.py',
 'tests/test_ci_v4_perf_scope.py',
 'tests/test_f03_financing_scope.py',
 'tests/test_f04_financing_scope.py',
 'tests/test_post432_l01_l02_scope.py',
 'tests/test_r02_ppa_ux_scope.py',
 'tests/test_r03_ppa_scope.py',
 'tests/test_r04_ppa_scope.py',
 'tests/test_t01e_remediation_scope.py'))
CURRENT_MAPS = frozenset(('docs/ci_v4/SOURCE_SUCCESSOR.json',
 'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json',
 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json',
 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json',
 'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json',
 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json',
 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json',
 'docs/tax_reference_registry/SOURCE_SUCCESSOR.json'))
MAP_KEYS = (REGISTRY, "static/react/finco-react.js")
OWNED_PATHS = SOURCE_PATHS | NEW | HANDOFF_PATHS | CURRENT_MAPS
SUPERSEDED = OWNED_PATHS - NEW
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "tools/", "migrations/", "app/", "research/", "main_web.py")
FROZEN = ('.github/workflows/ci_v4_f01_job.yml',
 '.github/workflows/finval_f01_acceptance.yml',
 'docs/bess02/SOURCE_SUCCESSOR.json',
 'docs/bess_setup/SOURCE_SUCCESSOR.json',
 'docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json',
 'docs/ci_v4/module_weights.json',
 'docs/r03_ppa_candidate/SOURCE_SUCCESSOR.json',
 'docs/r04_ppa_global_cap/SOURCE_SUCCESSOR.json',
 'docs/react_migration/f03_financing/SOURCE_SUCCESSOR.json',
 'docs/react_migration/f04_financing/SOURCE_SUCCESSOR.json',
 'docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json',
 'docs/tax_reference_registry/t01e/SOURCE_SUCCESSOR.json',
 'research/r03_ppa_candidate/core.py',
 'research/r04_ppa_global_cap/core.py',
 'static/react/finco-react.css',
 'tax_reference_registry/__init__.py',
 'tax_reference_registry/remediation.py',
 'tests/bess02_scope.py',
 'tests/ci_v4_perf_scope.py',
 'tests/ci_v4_scope.py',
 'tests/f03_financing_scope.py',
 'tests/f04_financing_scope.py',
 'tests/r03_ppa_core/oracle.py',
 'tests/r03_ppa_scope.py',
 'tests/r04_ppa_global_cap/oracle.py',
 'tests/t01e_remediation_scope.py',
 'tests/tax_reference_registry_scope.py',
 'tests/ux_pr2b_scope.py',
 'tests/ux_pr2c_scope.py')


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref=None):
    # A committed ref is read from Git (with the repository root); the working tree is read from disk.
    return (Path(root) / path).read_bytes() if ref is None else _git(root, "show", ref + ":" + path)


def _blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        raw = _read(root, MANIFEST, ref)
        d = json.loads(raw)
        if raw != (json.dumps(d, indent=2, sort_keys=True) + "\n").encode():       # canonical bytes only: no extra, reordered or hidden byte
            return {}
        return d if (isinstance(d, dict) and set(d) == {"schema_version", "authorization", "base", "base_tree", "source_blobs", "base_blobs", "source_modes", "base_modes"}
                     and d["schema_version"] == SCHEMA and d["base"] == BASE and d["base_tree"] == BASE_TREE
                     and isinstance(d["source_blobs"], dict) and isinstance(d["base_blobs"], dict)) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


def expected_map(root, path, pins=None):
    """Only the one FINITE current-source key (the registry pin) may move; all history stays unchanged."""
    d = json.loads(_base_bytes(str(root), path))
    pins = manifest(root).get("source_blobs", {}) if pins is None else pins
    for key in MAP_KEYS:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The accepted T01-E leaf gains one forward hook
# to this cohort (the same acyclic pattern F03 and T01-E used); the registry appends this cohort exactly once; the exact-tail tests accept one more state.
HANDOFFS = {'tests/fin_v2_cohorts.py': [("'tests.r04_ppa_scope')", "'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')")],
 'tests/r04_ppa_scope.py': [('    _SCOPE.append({})\n    try:\n        yield\n    finally:\n        _SCOPE.pop()\n',
                             '    _SCOPE.append({})\n'
                             '    try:\n'
                             '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept '
                             'globally.\n'
                             '        N = _next()\n'
                             '        if N is None:\n'
                             '            yield\n'
                             '        else:\n'
                             '            with N.scoped():\n'
                             '                yield\n'
                             '    finally:\n'
                             '        _SCOPE.pop()\n'),
                            ('    if mode == "exact":\n'
                             '        return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
                             '    return _signature_ok(root, ref, mode)\n',
                             '    from contextlib import nullcontext\n'
                             '    N = _next()\n'
                             '    with (N.scoped() if N is not None else nullcontext()):\n'
                             '        if mode == "exact":\n'
                             '            return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
                             '        return _signature_ok(root, ref, mode)\n'),
                            ('        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
                             '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN) | set(BASELINE))\n'
                             '        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\n',
                             '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
                             '        nx = _next_pins(root, ref)\n'
                             '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n'
                             '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN) | set(BASELINE))\n'
                             '        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\n'),
                            ('                if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):\n',
                             '                if current[p] != _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS)):\n'),
                            ('        allowed = OWNED_PATHS | {MANIFEST}\n        changed = set(',
                             '        allowed = closure_paths(root, ref)\n        changed = set('),
                            ('def map_keys(repo=None, ref=None):\n    return tuple(MAP_KEYS)\n',
                             'def _next():\n'
                             '    """The one finite forward successor (C06). Low-level only: its signature never calls this module or the '
                             'composite."""\n'
                             '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
                             "    if 'tests.c06_cost_workspace_scope' not in COHORT_MODULES:\n"
                             '        return None\n'
                             '    from tests import c06_cost_workspace_scope\n'
                             '    return c06_cost_workspace_scope\n'
                             '\n'
                             '\n'
                             'def _next_pins(root, ref):\n'
                             '    N = _next()\n'
                             '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n'
                             '\n'
                             '\n'
                             'def map_keys(repo=None, ref=None):\n'
                             '    root = Path(repo) if repo is not None else ROOT\n'
                             '    with scoped():\n'
                             '        N = _next()\n'
                             '        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_KEYS) if N is not None and '
                             'N.signature_ok(root, ref) else ()\n'
                             '        return tuple(MAP_KEYS) + more\n'),
                            ('def effective_pins(repo=None, ref=None, *, signature=False):\n'
                             '    return dict(manifest(repo, ref).get("source_blobs", {}))\n',
                             'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                             '    root = Path(repo) if repo is not None else ROOT\n'
                             '    with scoped():\n'
                             '        pins = dict(manifest(repo, ref).get("source_blobs", {}))\n'
                             '        pins.update(_next_pins(root, ref))\n'
                             '        return pins\n'),
                            ('def closure_paths(repo=None, ref=None):\n'
                             '    return OWNED_PATHS | {MANIFEST} if signature_ok(repo, ref) else frozenset()\n',
                             'def closure_paths(repo=None, ref=None):\n'
                             '    root = Path(repo) if repo is not None else ROOT\n'
                             '    with scoped():\n'
                             '        if not signature_ok(root, ref):\n'
                             '            return frozenset()\n'
                             '        N = _next()\n'
                             '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())\n'),
                            ('def supersedes(path, value, repo=None, ref=None):\n'
                             '    if path not in SUPERSEDED:\n'
                             '        return False\n'
                             '    # Like the accepted F03 / performance leaves: the signature decides a supersession; the composite '
                             "separately requires every cohort's FULL\n"
                             '    # exactness (map bytes, changed set, untracked files), so a signature-only verdict never makes the tree '
                             'valid.\n'
                             '    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value\n',
                             'def supersedes(path, value, repo=None, ref=None):\n'
                             '    with scoped():      # one shared read scope per call: the successor signature is evaluated once, then '
                             'dropped\n'
                             '        N = _next()\n'
                             '        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref):\n'
                             '            return True\n'
                             '        if path not in SUPERSEDED:\n'
                             '            return False\n'
                             '        # the CURRENT pin of this path (the successor overlay wins while its signature holds), never a raw '
                             'superseded manifest line\n'
                             '        return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\n'),
                            ('    root = Path(repo) if repo is not None else ROOT\n'
                             '    try:\n'
                             '        if _git(root, "merge-base", "origin/main", "HEAD")',
                             '    root = Path(repo) if repo is not None else ROOT\n'
                             '    try:\n'
                             '        N = _next()\n'
                             '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n'
                             '            return True\n'
                             '        if _git(root, "merge-base", "origin/main", "HEAD")'),
                            ('        pins = manifest(root, ref).get("source_blobs", {})\n'
                             '        for path in HANDOFFS:\n'
                             '            actual = _read(root, path, ref)\n'
                             '            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n'
                             '                return False\n'
                             '        return True\n',
                             '        pins = manifest(root, ref).get("source_blobs", {})\n'
                             '        N = _next()\n'
                             '        nxt = N is not None and N.signature_ok(root, ref)\n'
                             '        for path in HANDOFFS:\n'
                             '            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution '
                             'of this shared path\n'
                             '                continue\n'
                             '            actual = _read(root, path, ref)\n'
                             '            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n'
                             '                return False\n'
                             '        return N.reviewed_edits_ok(root, ref) if nxt else True\n'),
                            ('\n                if current[p] != _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS)):',
                             '\n                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS))):'),
                            ('        for p, (mode, blob) in BASELINE.items():          # literal table == immutable BASE object == '
                             'evaluated tree/ref, blob AND Git mode\n'
                             '            if _base_blob(key, p) != blob or _base_mode(key, p) != mode or current.get(p) != blob or '
                             'modes.get(p) != mode:\n'
                             '                return False',
                             '        for p, (mode, blob) in BASELINE.items():\n'
                             "            # Immutable table and BASE stay exact. Only this finite successor's signed served JS may move.\n"
                             '            expected = nx.get(p, blob) if p == "static/react/finco-react.js" else blob\n'
                             '            if _base_blob(key, p) != blob or _base_mode(key, p) != mode or current.get(p) != expected or '
                             'modes.get(p) != mode:\n'
                             '                return False')],
 'tests/test_bess02_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                ('def test_accepted_r02_product_and_historical_manifest_are_unchanged():\n'
                                 '    from tests import r02_ppa_ux_scope as R\n'
                                 "    paths = R.SOURCE_PATHS | {R.MANIFEST, 'frontend/src/app/workflow/PPAEditorView.tsx',\n"
                                 "                            'tests/onaccept01_scope.py', 'tests/tax_reference_registry_scope.py'}\n"
                                 '    from tests import f03_financing_scope as G\n'
                                 '    for path in sorted(paths):\n'
                                 '        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared '
                                 'bundle, exactly at its pinned blob\n'
                                 '            assert B._blob((B.ROOT/path).read_bytes()) == G.effective_pins()[path]\n'
                                 '            continue\n'
                                 "        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + "
                                 'path], cwd=B.ROOT)\n'
                                 "    registry = subprocess.check_output(['git', 'show', B.BASE + ':tests/fin_v2_cohorts.py'], "
                                 'cwd=B.ROOT)\n'
                                 '    accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body\n'
                                 '                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and '
                                 "n.targets[0].id == 'COHORT_MODULES')\n"
                                 '    from tests import ci_v4_perf_scope as F, f03_financing_scope as G, t01e_remediation_scope as Z, '
                                 'r03_ppa_scope as Y\n'
                                 "    own = accepted + ('tests.bess02_scope',)\n"
                                 '    # Exactly five states: the accepted BESS-only tail; one reviewed CI-performance successor; that '
                                 'successor followed by exactly one\n'
                                 '    # reviewed F03 successor; then exactly one reviewed T01-E successor; then exactly one reviewed R03 '
                                 'successor, each behind a complete signature.\n'
                                 '    assert (C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__) and F.signature_ok() and '
                                 'G.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__) and F.signature_ok() and '
                                 'G.signature_ok()\n'
                                 '                and Z.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__) and '
                                 'F.signature_ok() and G.signature_ok()\n'
                                 '                and Z.signature_ok() and Y.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, '
                                 'W.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok()))\n'
                                 "    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', "
                                 "'tests.r02_ppa_ux_scope', 'tests.bess02_scope')",
                                 'def test_accepted_r02_product_and_historical_manifest_are_unchanged():\n'
                                 '    from tests import r02_ppa_ux_scope as R\n'
                                 "    paths = R.SOURCE_PATHS | {R.MANIFEST, 'frontend/src/app/workflow/PPAEditorView.tsx',\n"
                                 "                            'tests/onaccept01_scope.py', 'tests/tax_reference_registry_scope.py'}\n"
                                 '    from tests import f03_financing_scope as G\n'
                                 '    for path in sorted(paths):\n'
                                 '        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared '
                                 'bundle, exactly at its pinned blob\n'
                                 '            assert B._blob((B.ROOT/path).read_bytes()) == G.effective_pins()[path]\n'
                                 '            continue\n'
                                 "        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + "
                                 'path], cwd=B.ROOT)\n'
                                 "    registry = subprocess.check_output(['git', 'show', B.BASE + ':tests/fin_v2_cohorts.py'], "
                                 'cwd=B.ROOT)\n'
                                 '    accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body\n'
                                 '                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and '
                                 "n.targets[0].id == 'COHORT_MODULES')\n"
                                 '    from tests import ci_v4_perf_scope as F, f03_financing_scope as G, t01e_remediation_scope as Z, '
                                 'r03_ppa_scope as Y\n'
                                 "    own = accepted + ('tests.bess02_scope',)\n"
                                 '    # Exactly five states: the accepted BESS-only tail; one reviewed CI-performance successor; that '
                                 'successor followed by exactly one\n'
                                 '    # reviewed F03 successor; then exactly one reviewed T01-E successor; then exactly one reviewed R03 '
                                 'successor, each behind a complete signature.\n'
                                 '    assert ((C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__) and F.signature_ok() and '
                                 'G.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__) and F.signature_ok() and '
                                 'G.signature_ok()\n'
                                 '                and Z.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__) and '
                                 'F.signature_ok() and G.signature_ok()\n'
                                 '                and Z.signature_ok() and Y.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, '
                                 'W.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES == V.BASE_COHORTS + (V.__name__,) and '
                                 'V.signature_ok()))\n'
                                 "    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', "
                                 "'tests.r02_ppa_ux_scope', 'tests.bess02_scope')")],
 'tests/test_ci_v4_perf_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                    ('def test_the_performance_leaf_is_exact_registered_and_the_composite_holds():\n'
                                     '    assert "tests.ci_v4_perf_scope" in C.COHORT_MODULES\n'
                                     '    # the leaf stays in its exact place; the only reviewed forward successor is F03, behind its own '
                                     'complete signature\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    with C.call_scope():\n'
                                     '        assert C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope" or (\n'
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
                                     'W.signature_ok())\n'
                                     '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.signature_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert C.valid() is True',
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
                                     'W.signature_ok())) or (C.COHORT_MODULES == V.BASE_COHORTS + (V.__name__,) and V.signature_ok())\n'
                                     '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.signature_ok() is True\n'
                                     '    with C.call_scope():\n'
                                     '        assert C.valid() is True'),
                                    ('def test_every_handoff_file_equals_its_reviewed_literal_substitution():\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'
                                     '                else Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS\n'
                                     '                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '        assert (ROOT / p).read_bytes() == want, p',
                                     'def test_every_handoff_file_equals_its_reviewed_literal_substitution():\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (V.expected_handoff(ROOT, p) if V.signature_ok() and p in V.HANDOFFS\n'
                                     '                else W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'
                                     '                else Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS\n'
                                     '                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '        assert (ROOT / p).read_bytes() == want, p'),
                                    ('def test_the_registry_appends_exactly_one_reviewed_cohort_after_the_accepted_tail():\n'
                                     '    registry = _git("show", F.BASE + ":tests/fin_v2_cohorts.py")\n'
                                     '    accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body\n'
                                     '                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)\n'
                                     '                    and n.targets[0].id == "COHORT_MODULES")\n'
                                     '    assert accepted[-1] == "tests.bess02_scope"  # the accepted BESS02 tail is intact\n'
                                     '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '    own = accepted + ("tests.ci_v4_perf_scope",)\n'
                                     '    with C.call_scope():\n'
                                     '        assert (C.COHORT_MODULES == own or (C.COHORT_MODULES == own + ("tests.f03_financing_scope",) '
                                     'and G.signature_ok())\n'
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
                                     'Q.signature_ok() and W.signature_ok()))\n'
                                     '    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1',
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
                                     'Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES == V.BASE_COHORTS + (V.__name__,) and '
                                     'V.signature_ok()))\n'
                                     '    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1'),
                                    ('def test_an_extra_or_forged_cohort_in_the_registry_fails_the_leaf_and_the_composite():\n'
                                     '    original = (ROOT / "tests/fin_v2_cohorts.py").read_bytes()\n'
                                     '    text = original.decode()\n'
                                     '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', '
                                     '\'tests.f03_financing_scope\', "\n'
                                     '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', '
                                     '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\')")\n'
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
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True and C.valid() is True',
                                     'def test_an_extra_or_forged_cohort_in_the_registry_fails_the_leaf_and_the_composite():\n'
                                     '    original = (ROOT / "tests/fin_v2_cohorts.py").read_bytes()\n'
                                     '    text = original.decode()\n'
                                     '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', '
                                     '\'tests.f03_financing_scope\', "\n'
                                     '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', '
                                     '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")\n'
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
                                     '        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)\n'
                                     '    with C.call_scope():\n'
                                     '        assert F.exact_blobs_ok() is True and C.valid() is True'),
                                    ('def '
                                     'test_the_accepted_main_version_of_every_handoff_file_is_retrievable_and_distinct_from_the_takeover():\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        base_bytes = _git("show", F.BASE + ":" + p)\n'
                                     '        now = (ROOT / p).read_bytes()\n'
                                     '        assert base_bytes != now, p                       # the takeover is real, not a no-op\n'
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'
                                     '                else Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS\n'
                                     '                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '        assert want == now                                # and equals exactly the reviewed '
                                     'substitution',
                                     'def '
                                     'test_the_accepted_main_version_of_every_handoff_file_is_retrievable_and_distinct_from_the_takeover():\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        base_bytes = _git("show", F.BASE + ":" + p)\n'
                                     '        now = (ROOT / p).read_bytes()\n'
                                     '        assert base_bytes != now, p                       # the takeover is real, not a no-op\n'
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (V.expected_handoff(ROOT, p) if V.signature_ok() and p in V.HANDOFFS\n'
                                     '                else W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'
                                     '                else Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS\n'
                                     '                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS\n'
                                     '                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS\n'
                                     '                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p))\n'
                                     '        assert want == now                                # and equals exactly the reviewed '
                                     'substitution')],
 'tests/test_f03_financing_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                       ('def test_valid_descendant_chain_is_exact_at_the_reviewed_head(clone):\n'
                                        '    ref = "HEAD"\n'
                                        '    assert F.signature_ok(clone, ref) and F.exact_blobs_ok(clone, ref)\n'
                                        '    assert B.signature_ok(clone, ref) and B.exact_blobs_ok(clone, ref) and R.signature_ok(clone, '
                                        'ref)\n'
                                        '    assert C.COHORT_MODULES[-3:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope") or (\n'
                                        '        C.COHORT_MODULES[-4:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope")) or (\n'
                                        '        C.COHORT_MODULES[-5:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope",\n'
                                        '                                  "tests.r03_ppa_scope")) or (\n'
                                        '        C.COHORT_MODULES[-6:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                        '        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok())',
                                        'def test_valid_descendant_chain_is_exact_at_the_reviewed_head(clone):\n'
                                        '    ref = "HEAD"\n'
                                        '    assert F.signature_ok(clone, ref) and F.exact_blobs_ok(clone, ref)\n'
                                        '    assert B.signature_ok(clone, ref) and B.exact_blobs_ok(clone, ref) and R.signature_ok(clone, '
                                        'ref)\n'
                                        '    assert (C.COHORT_MODULES[-3:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope") or (\n'
                                        '        C.COHORT_MODULES[-4:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope")) or (\n'
                                        '        C.COHORT_MODULES[-5:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope",\n'
                                        '                                  "tests.r03_ppa_scope")) or (\n'
                                        '        C.COHORT_MODULES[-6:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                        '        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES == V.BASE_COHORTS + '
                                        '(V.__name__,) and V.signature_ok())'),
                                       ('@pytest.mark.parametrize("name,fn", [\n'
                                        '    ("duplicate_f03", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                        '\'tests.t01e_remediation_scope\'", b"\'tests.f03_financing_scope\', '
                                        '\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                        '\'tests.fake_scope\')")),\n'
                                        '    ("swapped_perf_f03", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', '
                                        '\'tests.f03_financing_scope\'", b"\'tests.f03_financing_scope\', \'tests.ci_v4_perf_scope\'")),\n'
                                        '    ("swapped_bess_perf", lambda b: b.replace(b"\'tests.bess02_scope\', '
                                        '\'tests.ci_v4_perf_scope\'", b"\'tests.ci_v4_perf_scope\', \'tests.bess02_scope\'")),\n'
                                        '    ("perf_removed", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', ", b"")),\n'
                                        '    ("bess_removed", lambda b: b.replace(b"\'tests.bess02_scope\', ", b"")),\n'
                                        '    ("f03_missing", lambda b: b.replace(b", \'tests.f03_financing_scope\', '
                                        '\'tests.t01e_remediation_scope\'", b", \'tests.t01e_remediation_scope\'")),\n'
                                        '    ("r02_removed", lambda b: b.replace(b"\'tests.r02_ppa_ux_scope\', ", b"")),\n'
                                        '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', '
                                        '\'tests.fin_v2_ci_scope\'", b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                        '])\n'
                                        'def test_registry_mutations_are_rejected_by_f03_and_by_the_bess_chain(clone, name, fn):\n'
                                        '    ref = _variant(clone, {F.REGISTRY: fn})\n'
                                        '    assert F.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], '
                                        'cwd=clone).decode().splitlines()\n'
                                        '    assert not F.signature_ok(clone, ref), name\n'
                                        '    assert not B.exact_blobs_ok(clone, ref), name',
                                        '@pytest.mark.parametrize("name,fn", [\n'
                                        '    ("duplicate_f03", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                        '\'tests.t01e_remediation_scope\'", b"\'tests.f03_financing_scope\', '
                                        '\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.fake_scope\')")),\n'
                                        '    ("swapped_perf_f03", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', '
                                        '\'tests.f03_financing_scope\'", b"\'tests.f03_financing_scope\', \'tests.ci_v4_perf_scope\'")),\n'
                                        '    ("swapped_bess_perf", lambda b: b.replace(b"\'tests.bess02_scope\', '
                                        '\'tests.ci_v4_perf_scope\'", b"\'tests.ci_v4_perf_scope\', \'tests.bess02_scope\'")),\n'
                                        '    ("perf_removed", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', ", b"")),\n'
                                        '    ("bess_removed", lambda b: b.replace(b"\'tests.bess02_scope\', ", b"")),\n'
                                        '    ("f03_missing", lambda b: b.replace(b", \'tests.f03_financing_scope\', '
                                        '\'tests.t01e_remediation_scope\'", b", \'tests.t01e_remediation_scope\'")),\n'
                                        '    ("r02_removed", lambda b: b.replace(b"\'tests.r02_ppa_ux_scope\', ", b"")),\n'
                                        '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', '
                                        '\'tests.fin_v2_ci_scope\'", b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                        '])\n'
                                        'def test_registry_mutations_are_rejected_by_f03_and_by_the_bess_chain(clone, name, fn):\n'
                                        '    ref = _variant(clone, {F.REGISTRY: fn})\n'
                                        '    assert F.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], '
                                        'cwd=clone).decode().splitlines()\n'
                                        '    assert not F.signature_ok(clone, ref), name\n'
                                        '    assert not B.exact_blobs_ok(clone, ref), name')],
 'tests/test_f04_financing_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                       ('def test_exact_source_chain_worktree_and_committed_ref(clone):\n'
                                        "    assert F.BASE=='7584149f9334ac058cd986188b571c7dd48d538e'\n"
                                        "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
                                        "    assert C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (\n"
                                        '        '
                                        "C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') "
                                        'and W.signature_ok())\n'
                                        "    assert C.COHORT_MODULES.count('tests.f04_financing_scope')==1\n"
                                        "    for ref in (None,'HEAD'):\n"
                                        '        with C.call_scope():\n'
                                        '            assert F.signature_ok(clone,ref) and F.exact_blobs_ok(clone,ref)\n'
                                        '            assert R.exact_blobs_ok(clone,ref) and P.exact_blobs_ok(clone,ref) and '
                                        'C.valid(clone,ref)\n'
                                        '    assert not F.exact_blobs_ok(clone,F.BASE)',
                                        'def test_exact_source_chain_worktree_and_committed_ref(clone):\n'
                                        "    assert F.BASE=='7584149f9334ac058cd986188b571c7dd48d538e'\n"
                                        "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
                                        "    assert (C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (\n"
                                        '        '
                                        "C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope', "
                                        "'tests.c06_cost_workspace_scope') and W.signature_ok())) or (C.COHORT_MODULES == V.BASE_COHORTS + "
                                        '(V.__name__,) and V.signature_ok())\n'
                                        "    assert C.COHORT_MODULES.count('tests.f04_financing_scope')==1\n"
                                        "    for ref in (None,'HEAD'):\n"
                                        '        with C.call_scope():\n'
                                        '            assert F.signature_ok(clone,ref) and F.exact_blobs_ok(clone,ref)\n'
                                        '            assert R.exact_blobs_ok(clone,ref) and P.exact_blobs_ok(clone,ref) and '
                                        'C.valid(clone,ref)\n'
                                        '    assert not F.exact_blobs_ok(clone,F.BASE)'),
                                       ('def test_literal_closed_paths_and_immutable_predecessor_blobs():\n'
                                        '    data=F.manifest()\n'
                                        "    assert set(data['source_blobs'])==F.OWNED_PATHS\n"
                                        "    assert set(data['base_blobs'])==F.SUPERSEDED\n"
                                        "    assert F.MAP_KEYS==(F.REGISTRY,'static/react/finco-react.js')\n"
                                        "    assert not any('*' in p or '..' in p.split('/') or p.startswith(F.FORBIDDEN) for p in "
                                        'F.OWNED_PATHS)\n'
                                        '    for path in F.SUPERSEDED:assert '
                                        "data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
                                        '    for path in F.HANDOFFS:\n'
                                        '        authority=W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed '
                                        'substitution of this shared path\n'
                                        '        assert (ROOT/path).read_bytes()==authority.expected_handoff(ROOT,path)\n'
                                        '    for path in F.FROZEN:assert '
                                        "(ROOT/path).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT)",
                                        'def test_literal_closed_paths_and_immutable_predecessor_blobs():\n'
                                        '    data=F.manifest()\n'
                                        "    assert set(data['source_blobs'])==F.OWNED_PATHS\n"
                                        "    assert set(data['base_blobs'])==F.SUPERSEDED\n"
                                        "    assert F.MAP_KEYS==(F.REGISTRY,'static/react/finco-react.js')\n"
                                        "    assert not any('*' in p or '..' in p.split('/') or p.startswith(F.FORBIDDEN) for p in "
                                        'F.OWNED_PATHS)\n'
                                        '    for path in F.SUPERSEDED:assert '
                                        "data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
                                        '    for path in F.HANDOFFS:\n'
                                        '        authority=V if V.signature_ok() and path in V.HANDOFFS else W if W.signature_ok() and '
                                        'path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n'
                                        '        assert (ROOT/path).read_bytes()==authority.expected_handoff(ROOT,path)\n'
                                        '    for path in F.FROZEN:assert '
                                        "(ROOT/path).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT)"),
                                       ("@pytest.mark.parametrize('kind',['mode','symlink','delete','unknown','missing_registration','duplicate_registration','reordered_registration','partial_handoff'])\n"
                                        'def test_modes_registry_and_closed_diff_are_enforced(clone,kind):\n'
                                        '    with Mutation(clone):\n'
                                        "        path=clone/'static/react/finco-react.js'\n"
                                        "        if kind=='mode':path.chmod(0o755)\n"
                                        "        elif kind=='symlink':path.unlink();path.symlink_to(clone/'README.md')\n"
                                        "        elif kind=='delete':path.unlink()\n"
                                        "        elif kind=='unknown':(clone/'app/f04_unreviewed.py').write_text('unreviewed=True\\n')\n"
                                        "        elif kind=='partial_handoff':\n"
                                        '            '
                                        "path=clone/F.PREDECESSOR;path.write_bytes(subprocess.check_output(['git','show',F.BASE+':'+F.PREDECESSOR],cwd=clone))\n"
                                        '        else:\n'
                                        '            path=clone/F.REGISTRY;text=path.read_text()\n'
                                        '            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\')",", \'tests.r04_ppa_scope\')")\n'
                                        '            elif '
                                        'kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\')","\'tests.f04_financing_scope\', \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\')")\n'
                                        '            else:text=text.replace("\'tests.r03_ppa_scope\', '
                                        '\'tests.f04_financing_scope\'","\'tests.f04_financing_scope\', \'tests.r03_ppa_scope\'")\n'
                                        '            path.write_text(text)\n'
                                        '        with C.call_scope():assert not F.exact_blobs_ok(clone) and not C.valid(clone)\n'
                                        '    assert F.exact_blobs_ok(clone)',
                                        "@pytest.mark.parametrize('kind',['mode','symlink','delete','unknown','missing_registration','duplicate_registration','reordered_registration','partial_handoff'])\n"
                                        'def test_modes_registry_and_closed_diff_are_enforced(clone,kind):\n'
                                        '    with Mutation(clone):\n'
                                        "        path=clone/'static/react/finco-react.js'\n"
                                        "        if kind=='mode':path.chmod(0o755)\n"
                                        "        elif kind=='symlink':path.unlink();path.symlink_to(clone/'README.md')\n"
                                        "        elif kind=='delete':path.unlink()\n"
                                        "        elif kind=='unknown':(clone/'app/f04_unreviewed.py').write_text('unreviewed=True\\n')\n"
                                        "        elif kind=='partial_handoff':\n"
                                        '            '
                                        "path=clone/F.PREDECESSOR;path.write_bytes(subprocess.check_output(['git','show',F.BASE+':'+F.PREDECESSOR],cwd=clone))\n"
                                        '        else:\n'
                                        '            path=clone/F.REGISTRY;text=path.read_text()\n'
                                        '            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')",", \'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\')")\n'
                                        '            elif '
                                        'kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')","\'tests.f04_financing_scope\', '
                                        '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")\n'
                                        '            else:text=text.replace("\'tests.r03_ppa_scope\', '
                                        '\'tests.f04_financing_scope\'","\'tests.f04_financing_scope\', \'tests.r03_ppa_scope\'")\n'
                                        '            path.write_text(text)\n'
                                        '        with C.call_scope():assert not F.exact_blobs_ok(clone) and not C.valid(clone)\n'
                                        '    assert F.exact_blobs_ok(clone)')],
 'tests/test_post432_l01_l02_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                         ('def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():\n'
                                          "    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], "
                                          'cwd=ROOT).decode()\n'
                                          "    now = (ROOT / 'tests/fin_v2_cohorts.py').read_text()\n"
                                          '    own = base.replace(X.REGISTRY_MARKER, X.REGISTRY_NEW)\n'
                                          '    from tests import ci_v4_perf_scope as F\n'
                                          '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as '
                                          'Y\n'
                                          '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    if 'tests.r04_ppa_scope' in C.COHORT_MODULES and W.signature_ok():\n"
                                          '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.f04_financing_scope' in C.COHORT_MODULES and Q.signature_ok():\n"
                                          '        expected = Q.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.r03_ppa_scope' in C.COHORT_MODULES and Y.signature_ok():\n"
                                          '        expected = Y.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.t01e_remediation_scope' in C.COHORT_MODULES and Z.signature_ok():\n"
                                          '        expected = Z.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.f03_financing_scope' in C.COHORT_MODULES and G.signature_ok():\n"
                                          '        expected = G.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.ci_v4_perf_scope' in C.COHORT_MODULES and F.signature_ok():\n"
                                          '        expected = F.expected_handoff(ROOT, X.REGISTRY)\n'
                                          '    assert N.exact_blobs_ok() and now == expected.decode()\n'
                                          '    import ast\n'
                                          '    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, '
                                          "ast.Assign) and n.targets[0].id == 'COHORT_MODULES')\n"
                                          "    i = C.COHORT_MODULES.index('tests.post432_l01_l02_scope')\n"
                                          "    assert C.COHORT_MODULES[:i + 1] == old + ('tests.post432_l01_l02_scope',) and "
                                          'C.COHORT_MODULES[i - 3:i + 1] == ACCEPTED_ORDER_TAIL\n'
                                          '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)',
                                          'def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():\n'
                                          "    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], "
                                          'cwd=ROOT).decode()\n'
                                          "    now = (ROOT / 'tests/fin_v2_cohorts.py').read_text()\n"
                                          '    own = base.replace(X.REGISTRY_MARKER, X.REGISTRY_NEW)\n'
                                          '    from tests import ci_v4_perf_scope as F\n'
                                          '    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as '
                                          'Y\n'
                                          '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    if 'tests.c06_cost_workspace_scope' in C.COHORT_MODULES and V.signature_ok():\n"
                                          '        expected = V.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.r04_ppa_scope' in C.COHORT_MODULES and W.signature_ok():\n"
                                          '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.f04_financing_scope' in C.COHORT_MODULES and Q.signature_ok():\n"
                                          '        expected = Q.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.r03_ppa_scope' in C.COHORT_MODULES and Y.signature_ok():\n"
                                          '        expected = Y.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.t01e_remediation_scope' in C.COHORT_MODULES and Z.signature_ok():\n"
                                          '        expected = Z.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.f03_financing_scope' in C.COHORT_MODULES and G.signature_ok():\n"
                                          '        expected = G.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.ci_v4_perf_scope' in C.COHORT_MODULES and F.signature_ok():\n"
                                          '        expected = F.expected_handoff(ROOT, X.REGISTRY)\n'
                                          '    assert N.exact_blobs_ok() and now == expected.decode()\n'
                                          '    import ast\n'
                                          '    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, '
                                          "ast.Assign) and n.targets[0].id == 'COHORT_MODULES')\n"
                                          "    i = C.COHORT_MODULES.index('tests.post432_l01_l02_scope')\n"
                                          "    assert C.COHORT_MODULES[:i + 1] == old + ('tests.post432_l01_l02_scope',) and "
                                          'C.COHORT_MODULES[i - 3:i + 1] == ACCEPTED_ORDER_TAIL\n'
                                          '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)')],
 'tests/test_r02_ppa_ux_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                    ('def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():\n'
                                     '    import ast\n'
                                     "    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], "
                                     'cwd=ROOT).decode()\n'
                                     '    from tests import ci_v4_perf_scope as F\n'
                                     '    from tests import f03_financing_scope as G\n'
                                     '    from tests import t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     "    nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope', "
                                     "'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope',\n"
                                     "                            'tests.r04_ppa_scope') if m in C.COHORT_MODULES)\n"
                                     '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    if len(nxt) == 6 and W.signature_ok():\n'
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
                                     "core[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)",
                                     'def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():\n'
                                     '    import ast\n'
                                     "    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], "
                                     'cwd=ROOT).decode()\n'
                                     '    from tests import ci_v4_perf_scope as F\n'
                                     '    from tests import f03_financing_scope as G\n'
                                     '    from tests import t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     "    nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope', "
                                     "'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope',\n"
                                     "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope') if m in "
                                     'C.COHORT_MODULES)\n'
                                     '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    if len(nxt) == 7 and V.signature_ok():\n'
                                     '        expected = V.expected_handoff(ROOT, X.REGISTRY)\n'
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
                                     "core[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == "
                                     'len(C.COHORT_MODULES)')],
 'tests/test_r03_ppa_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                 ('def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '    for p in T.HANDOFFS:\n'
                                  '        authority = W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in '
                                  'Q.HANDOFFS else T\n'
                                  '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]',
                                  'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '    for p in T.HANDOFFS:\n'
                                  '        authority = V if V.signature_ok() and p in V.HANDOFFS else W if W.signature_ok() and p in '
                                  'W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n'
                                  '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]'),
                                 ('def test_registered_exactly_once_as_the_terminal_cohort_after_t01e():\n'
                                  '    assert C.COHORT_MODULES[-3:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope") or (\n'
                                  '        C.COHORT_MODULES[-4:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                  '        C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                  '        and Q.signature_ok() and W.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r03_ppa_scope") == 1',
                                  'def test_registered_exactly_once_as_the_terminal_cohort_after_t01e():\n'
                                  '    assert (C.COHORT_MODULES[-3:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope") or (\n'
                                  '        C.COHORT_MODULES[-4:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope") and Q.signature_ok()) or (\n'
                                  '        C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                  '        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES == V.BASE_COHORTS + '
                                  '(V.__name__,) and V.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r03_ppa_scope") == 1'),
                                 ('@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r03", lambda b: b.replace(b"\'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b"\'tests.r03_ppa_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                  '\'tests.fake_scope\')")),\n'
                                  '    ("swapped_t01e_r03", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                  '\'tests.r03_ppa_scope\'", b"\'tests.r03_ppa_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                  '    ("r03_missing", lambda b: b.replace(b", \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b", \'tests.f04_financing_scope\'")),\n'
                                  '    ("t01e_removed", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', ", b"")),\n'
                                  '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n'
                                  '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', \'tests.fin_v2_ci_scope\'", '
                                  'b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                  '])\n'
                                  'def test_registry_mutations_are_rejected(clone, name, fn):\n'
                                  '    ref = _variant(clone, {T.REGISTRY: fn})\n'
                                  '    assert T.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], '
                                  'cwd=clone).decode().splitlines()\n'
                                  '    with C.call_scope():\n'
                                  '        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not '
                                  'C.valid(clone, ref), name',
                                  '@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r03", lambda b: b.replace(b"\'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b"\'tests.r03_ppa_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.fake_scope\')")),\n'
                                  '    ("swapped_t01e_r03", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                  '\'tests.r03_ppa_scope\'", b"\'tests.r03_ppa_scope\', \'tests.t01e_remediation_scope\'")),\n'
                                  '    ("r03_missing", lambda b: b.replace(b", \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", '
                                  'b", \'tests.f04_financing_scope\'")),\n'
                                  '    ("t01e_removed", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', ", b"")),\n'
                                  '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n'
                                  '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', \'tests.fin_v2_ci_scope\'", '
                                  'b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                  '])\n'
                                  'def test_registry_mutations_are_rejected(clone, name, fn):\n'
                                  '    ref = _variant(clone, {T.REGISTRY: fn})\n'
                                  '    assert T.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], '
                                  'cwd=clone).decode().splitlines()\n'
                                  '    with C.call_scope():\n'
                                  '        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not '
                                  'C.valid(clone, ref), name')],
 'tests/test_r04_ppa_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                 ('def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '    for p in T.HANDOFFS:\n'
                                  '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]',
                                  'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                  '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                  '    for p in T.HANDOFFS:\n'
                                  '        authority = V if V.signature_ok() and p in V.HANDOFFS else T\n'
                                  '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]'),
                                 ('def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
                                  '    assert C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                  '    assert C.COHORT_MODULES.count("tests.r04_ppa_scope") == 1',
                                  'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
                                  '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES == '
                                  'V.BASE_COHORTS + (V.__name__,) and V.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r04_ppa_scope") == 1'),
                                 ('def test_current_maps_move_only_the_registry_key():\n'
                                  '    pins = T.manifest()["source_blobs"]\n'
                                  '    for p in T.CURRENT_MAPS:\n'
                                  '        old = json.loads(_git("show", T.BASE + ":" + p))\n'
                                  '        cur = json.loads((ROOT / p).read_text())\n'
                                  '        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")\n'
                                  '        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}\n'
                                  '        assert changed <= set(T.MAP_KEYS)\n'
                                  '        for k in changed:\n'
                                  '            assert cur["source_blobs"][k] == pins[k]',
                                  'def test_current_maps_move_only_the_registry_key():\n'
                                  '    pins = T.effective_pins()\n'
                                  '    for p in T.CURRENT_MAPS:\n'
                                  '        old = json.loads(_git("show", T.BASE + ":" + p))\n'
                                  '        cur = json.loads((ROOT / p).read_text())\n'
                                  '        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")\n'
                                  '        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}\n'
                                  '        assert changed <= set(T.map_keys())\n'
                                  '        for k in changed:\n'
                                  '            assert cur["source_blobs"][k] == pins[k]'),
                                 ('@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                  '\'tests.r04_ppa_scope\')")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                  '\'tests.fake_scope\')")),\n'
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\')")),\n'
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\')", b")")),\n'
                                  '    ("f04_removed", lambda b: b.replace(b"\'tests.f04_financing_scope\', ", b"")),\n'
                                  '    ("r03_removed", lambda b: b.replace(b"\'tests.r03_ppa_scope\', ", b"")),\n'
                                  '    ("t01e_removed", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', ", b"")),\n'
                                  '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n'
                                  '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', \'tests.fin_v2_ci_scope\'", '
                                  'b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                  '])\n'
                                  'def test_registry_mutations_are_rejected(clone, name, fn):\n'
                                  '    ref = _variant(clone, {T.REGISTRY: fn})\n'
                                  '    with C.call_scope():\n'
                                  '        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not '
                                  'C.valid(clone, ref), name',
                                  '@pytest.mark.parametrize("name,fn", [\n'
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.fake_scope\')")),\n'
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\')")),\n'
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b")")),\n'
                                  '    ("f04_removed", lambda b: b.replace(b"\'tests.f04_financing_scope\', ", b"")),\n'
                                  '    ("r03_removed", lambda b: b.replace(b"\'tests.r03_ppa_scope\', ", b"")),\n'
                                  '    ("t01e_removed", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', ", b"")),\n'
                                  '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n'
                                  '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', \'tests.fin_v2_ci_scope\'", '
                                  'b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                  '])\n'
                                  'def test_registry_mutations_are_rejected(clone, name, fn):\n'
                                  '    ref = _variant(clone, {T.REGISTRY: fn})\n'
                                  '    with C.call_scope():\n'
                                  '        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not '
                                  'C.valid(clone, ref), name'),
                                 ('def test_supersession_is_pin_exact_and_cross_path_safe():\n'
                                  '    pins = T.manifest()["source_blobs"]\n'
                                  '    reg = pins[T.REGISTRY]\n'
                                  '    assert P.supersedes(T.REGISTRY, reg) and F.supersedes(T.REGISTRY, reg) and '
                                  'F.effective_pins()[T.REGISTRY] == reg\n'
                                  '    assert not F.supersedes(T.REGISTRY, "0" * 40)\n'
                                  '    assert not F.supersedes(T.REGISTRY, pins[T.PREDECESSOR])        # a real blob pinned for another '
                                  'path\n'
                                  '    assert not F.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted R03 '
                                  'blob is no longer current\n'
                                  '    assert not P.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])\n'
                                  '    assert not T.supersedes("tests/not_superseded.py", reg)',
                                  'def test_supersession_is_pin_exact_and_cross_path_safe():\n'
                                  '    pins = T.manifest()["source_blobs"]\n'
                                  '    reg = T.effective_pins()[T.REGISTRY]\n'
                                  '    assert P.supersedes(T.REGISTRY, reg) and F.supersedes(T.REGISTRY, reg) and '
                                  'F.effective_pins()[T.REGISTRY] == reg\n'
                                  '    assert not F.supersedes(T.REGISTRY, "0" * 40)\n'
                                  '    assert not F.supersedes(T.REGISTRY, pins[T.PREDECESSOR])        # a real blob pinned for another '
                                  'path\n'
                                  '    assert not F.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted R03 '
                                  'blob is no longer current\n'
                                  '    assert not P.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])\n'
                                  '    assert not T.supersedes("tests/not_superseded.py", reg)'),
                                 ('def test_no_verdict_is_cached_across_refs_or_mutations(clone):\n'
                                  '    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\')", b")")})\n'
                                  '    with T.scoped(), F.scoped():\n'
                                  '        assert T.signature_ok(clone, "HEAD") and F.exact_blobs_ok(clone, "HEAD")\n'
                                  '        assert not T.signature_ok(clone, bad) and not F.exact_blobs_ok(clone, bad)     # same process, '
                                  'same scope, other ref\n'
                                  '    assert T.signature_ok(clone, "HEAD")                                                # and the '
                                  'positive verdict was never poisoned',
                                  'def test_no_verdict_is_cached_across_refs_or_mutations(clone):\n'
                                  '    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b")")})\n'
                                  '    with T.scoped(), F.scoped():\n'
                                  '        assert T.signature_ok(clone, "HEAD") and F.exact_blobs_ok(clone, "HEAD")\n'
                                  '        assert not T.signature_ok(clone, bad) and not F.exact_blobs_ok(clone, bad)     # same process, '
                                  'same scope, other ref\n'
                                  '    assert T.signature_ok(clone, "HEAD")                                                # and the '
                                  'positive verdict was never poisoned'),
                                 ('def test_baseline_table_is_exactly_the_accepted_base_state_and_authorizes_no_change():\n'
                                  '    assert set(KEY_PRODUCTION_PATHS) <= set(T.BASELINE)\n'
                                  '    for p, (mode, blob) in T.BASELINE.items():\n'
                                  '        line = _git("ls-tree", T.BASE, "--", p).split()\n'
                                  '        assert (line[0], line[2]) == (mode, blob) and mode == "100644", p\n'
                                  '        assert (ROOT / p).is_file() and not (ROOT / p).is_symlink()\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == blob, p\n'
                                  '        assert p not in T.OWNED_PATHS and p not in T.SUPERSEDED and p not in T.HANDOFFS and not '
                                  'T.allowed_path(p), p   # asserted, never pre-authorized\n'
                                  '        assert p not in T.manifest()["source_blobs"] and p not in T.manifest()["base_blobs"]\n'
                                  '    assert not set(T.BASELINE) & set(T.FROZEN)',
                                  'def test_baseline_table_is_exactly_the_accepted_base_state_and_authorizes_no_change():\n'
                                  '    assert set(KEY_PRODUCTION_PATHS) <= set(T.BASELINE)\n'
                                  '    for p, (mode, blob) in T.BASELINE.items():\n'
                                  '        line = _git("ls-tree", T.BASE, "--", p).split()\n'
                                  '        assert (line[0], line[2]) == (mode, blob) and mode == "100644", p\n'
                                  '        assert (ROOT / p).is_file() and not (ROOT / p).is_symlink()\n'
                                  '        expected = V.effective_pins()[p] if p == "static/react/finco-react.js" and V.signature_ok() '
                                  'else blob\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == expected, p\n'
                                  '        assert p not in T.OWNED_PATHS and p not in T.SUPERSEDED and p not in T.HANDOFFS and not '
                                  'T.allowed_path(p), p   # asserted, never pre-authorized\n'
                                  '        assert p not in T.manifest()["source_blobs"] and p not in T.manifest()["base_blobs"]\n'
                                  '    assert not set(T.BASELINE) & set(T.FROZEN)')],
 'tests/test_t01e_remediation_scope.py': [('import pytest\n', 'import pytest\nfrom tests import c06_cost_workspace_scope as V\n'),
                                          ('def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                           '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                           '    from tests import r03_ppa_scope as Y\n'
                                           '    for p in T.HANDOFFS:\n'
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
                                           '        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]',
                                           'def test_signature_exactness_and_reviewed_substitutions_hold():\n'
                                           '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
                                           '    from tests import r03_ppa_scope as Y\n'
                                           '    for p in T.HANDOFFS:\n'
                                           '        if V.signature_ok() and p in V.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == V.expected_handoff(ROOT, p)\n'
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
                                           '        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]'),
                                          ('def '
                                           'test_registered_exactly_once_directly_after_f03_with_only_the_reviewed_r03_successor_behind_it():\n'
                                           '    i = C.COHORT_MODULES.index("tests.t01e_remediation_scope")\n'
                                           '    assert C.COHORT_MODULES[i - 1] == "tests.f03_financing_scope"\n'
                                           '    assert C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", '
                                           '"tests.f04_financing_scope"),\n'
                                           '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope"))\n'
                                           '    assert C.COHORT_MODULES.count("tests.t01e_remediation_scope") == 1',
                                           'def '
                                           'test_registered_exactly_once_directly_after_f03_with_only_the_reviewed_r03_successor_behind_it():\n'
                                           '    i = C.COHORT_MODULES.index("tests.t01e_remediation_scope")\n'
                                           '    assert C.COHORT_MODULES[i - 1] == "tests.f03_financing_scope"\n'
                                           '    assert (C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", '
                                           '"tests.f04_financing_scope"),\n'
                                           '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope"))) or (C.COHORT_MODULES == V.BASE_COHORTS + (V.__name__,) and '
                                           'V.signature_ok())\n'
                                           '    assert C.COHORT_MODULES.count("tests.t01e_remediation_scope") == 1'),
                                          ('@pytest.mark.parametrize("name,fn", [\n'
                                           '    ("duplicate_t01e", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'")),\n'
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                           '\'tests.fake_scope\')")),\n'
                                           '    ("swapped_f03_t01e", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                           '\'tests.t01e_remediation_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.f03_financing_scope\'")),\n'
                                           '    ("t01e_missing", lambda b: b.replace(b", \'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b", \'tests.r03_ppa_scope\'")),\n'
                                           '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n'
                                           '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', '
                                           '\'tests.fin_v2_ci_scope\'", b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                           '])\n'
                                           'def test_registry_mutations_are_rejected(clone, name, fn):\n'
                                           '    ref = _variant(clone, {T.REGISTRY: fn})\n'
                                           '    assert T.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], '
                                           'cwd=clone).decode().splitlines()\n'
                                           '    with C.call_scope():\n'
                                           '        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not '
                                           'C.valid(clone, ref), name',
                                           '@pytest.mark.parametrize("name,fn", [\n'
                                           '    ("duplicate_t01e", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'")),\n'
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                           '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.fake_scope\')")),\n'
                                           '    ("swapped_f03_t01e", lambda b: b.replace(b"\'tests.f03_financing_scope\', '
                                           '\'tests.t01e_remediation_scope\'", b"\'tests.t01e_remediation_scope\', '
                                           '\'tests.f03_financing_scope\'")),\n'
                                           '    ("t01e_missing", lambda b: b.replace(b", \'tests.t01e_remediation_scope\', '
                                           '\'tests.r03_ppa_scope\'", b", \'tests.r03_ppa_scope\'")),\n'
                                           '    ("f03_removed", lambda b: b.replace(b"\'tests.f03_financing_scope\', ", b"")),\n'
                                           '    ("earlier_reordered", lambda b: b.replace(b"\'tests.fin_v2_3_scope\', '
                                           '\'tests.fin_v2_ci_scope\'", b"\'tests.fin_v2_ci_scope\', \'tests.fin_v2_3_scope\'")),\n'
                                           '])\n'
                                           'def test_registry_mutations_are_rejected(clone, name, fn):\n'
                                           '    ref = _variant(clone, {T.REGISTRY: fn})\n'
                                           '    assert T.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], '
                                           'cwd=clone).decode().splitlines()\n'
                                           '    with C.call_scope():\n'
                                           '        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not '
                                           'C.valid(clone, ref), name')]}

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
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if d.get("source_modes") != {p: "100644" for p in OWNED_PATHS} or d.get("base_modes") != {p: "100644" for p in SUPERSEDED}:
            return False
        if any(_base_mode(str(root), p) != d["base_modes"][p] for p in SUPERSEDED):
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
        if any(current.get(p) != _blob(_base_bytes(key, p)) for p in FROZEN):
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
    # Like the accepted F03 / performance leaves: the signature decides a supersession; the composite separately requires every cohort's FULL
    # exactness (map bytes, changed set, untracked files), so a signature-only verdict never makes the tree valid.
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

"""CI V4 Lean B2: ONE finite exact-source successor after the accepted B1 leaf (owner decision NEW_DRAFT_FROM_MAIN, 2026-11-15).

BASE is accepted main (the merged #449, ``3e859ac8``). This cohort changes exactly one thing in behaviour: the READ-ONLY provenance nodes of
``tests/test_u1_scope.py`` that re-derive the same many-cohort exact-source verdict dozens of times now share ONE outer ``call_scope`` (the
bounded, existing, per-call memo that dies with its block). The tamper nodes that mutate a worktree are not touched and no verdict is ever kept
across a mutation, a ref, a tree or a test case. It changes NO selector, policy, workflow, product, financial or UI source and selects, deletes,
skips or moves NO test: ``FROZEN`` pins every CI V4 control file to its accepted BASE blob.

Every changed byte, Git mode and the immutable BASE tree are bound to this module's manifest. The shared governance paths this successor really
changes (the composite registry, the U1 discovery entry, the U1 provenance tests, the B1 and C06 forward hooks, the exact-tail tests and the
current maps) are SUPERSEDED paths: each carries its accepted BASE blob, the literal one-occurrence substitutions that produce its new blob, and
the exact new blob. Previous manifests are never rewritten except the current-map keys that every earlier successor moved the same way.

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls the B1 leaf, the C06 leaf, an older cohort
or the composite; the B1 leaf calls this module through one forward hook (the acyclic pattern B1 used for C06).
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "3e859ac82c9510f467999a5182bd9d9a21583291"
BASE_TREE = "af0a714420ba84dcd026a04e47d0ff9e0473c6d8"
MANIFEST = "docs/ci_v4/lean_b2/SOURCE_SUCCESSOR.json"
SCHEMA = "CI_V4_LEAN_B2_EXACT_SOURCE_V1"
AUTHORIZATION = ('Owner decision NEW_DRAFT_FROM_MAIN (2026-11-15): one finite exact-source successor of the accepted CI V4 Lean B1 leaf for '
                 'a bounded, semantic-preserving U1 provenance test-runtime optimisation; no selector, policy, workflow, product, financial, UI or test-selection change; no test demotion; no merge or deployment authority.')
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v4_lean_b1_scope.py"
BASE_COHORTS = (
    'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope',
    'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope',
    'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope',
    'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope',
    'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope',
    'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope',
    'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope',
    'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope',
)
NEW = frozenset((
    "docs/ci_v4/lean_b2/README.md",
    "tests/ci_v4_lean_b2_scope.py",
    "tests/test_ci_v4_lean_b2_scope.py",
))
# Accepted governance paths whose bytes move by one reviewed literal substitution (HANDOFFS) ...
HANDOFF_PATHS = frozenset((
    'docs/react_migration/ux_pr2c/UX_PR2C_EXACT_SOURCE.json',
    'tests/c06_cost_workspace_scope.py',
    'tests/ci_v4_lean_b1_scope.py',
    'tests/fin_v2_cohorts.py',
    'tests/test_bess02_scope.py',
    'tests/test_c06_cost_workspace_scope.py',
    'tests/test_ci_v4_lean_b1_scope.py',
    'tests/test_ci_v4_lean_tamper_matrix.py',
    'tests/test_ci_v4_perf_scope.py',
    'tests/test_f03_financing_scope.py',
    'tests/test_f04_financing_scope.py',
    'tests/test_post432_l01_l02_scope.py',
    'tests/test_r02_ppa_ux_scope.py',
    'tests/test_r03_ppa_scope.py',
    'tests/test_r04_ppa_scope.py',
    'tests/test_t01e_remediation_scope.py',
    'tests/test_u1_scope.py',
    'tests/u1_scope.py',
))
# ... and the current maps, of which only the registry, U1 discovery and U1 provenance-test keys move (the bounded handoff every earlier successor made).
CURRENT_MAPS = frozenset((
    "docs/ci_v4/SOURCE_SUCCESSOR.json",
    "docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json",
    "docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json",
    "docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json",
    "docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json",
    "docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json",
    "docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json",
    "docs/tax_reference_registry/SOURCE_SUCCESSOR.json",
))
MAP_KEYS = ('tests/fin_v2_cohorts.py', 'tests/u1_scope.py', 'tests/test_u1_scope.py')
SUPERSEDED = HANDOFF_PATHS | CURRENT_MAPS
OWNED_PATHS = NEW | SUPERSEDED
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "migrations/", "app/", "research/", "frontend/", "static/", "main_web.py")
# Accepted CI V4 control sources that this successor must leave byte-identical to BASE: no selector, policy, aggregator, scheduler or workflow change.
FROZEN = (
    ".github/workflows/ci_v4_f01_job.yml", ".github/workflows/ci_v4_full.yml", ".github/workflows/ci_v4_pr.yml",
    ".github/workflows/ci_v4_release_gate.yml", ".github/workflows/ci_v4_shadow_split.yml",
    "docs/ci_v4/ci-v4-policy.json", "docs/ci_v4/full_skip_baseline.json", "docs/ci_v4/module_weights.json",
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
    'docs/react_migration/ux_pr2c/UX_PR2C_EXACT_SOURCE.json': [
        ('    "tests/test_u1_scope.py": "8f58878effa3d1d07fe630eea68b0e0c16c01d9b",\n',
         '    "tests/test_u1_scope.py": "4c1da14dfcd634614472a0dcbb4d4aee846220ba",\n'),
    ],
    'tests/fin_v2_cohorts.py': [
        ("'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope')",
         "'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope')"),
    ],
    'tests/u1_scope.py': [
        ("'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope')",
         "'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope')"),
    ],
    'tests/test_u1_scope.py': [
        ('def test_positive_cohort_is_exact_registered_and_closed():\n',
         (
                'def test_positive_cohort_is_exact_registered_and_closed():\n'
                '    with C.call_scope():       # ONE outer READ-ONLY governance call: each cohort verdict is computed once and dropped on exit (no mutation inside)\n'
                '        _positive_cohort_is_exact_registered_and_closed()\n'
                '\n'
                '\n'
                'def _positive_cohort_is_exact_registered_and_closed():\n')),
        ('def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n',
         (
                'def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n'
                '    with C.call_scope():       # ONE outer READ-ONLY governance call over the finite owned set; nothing is mutated inside the scope\n'
                '        _no_path_outside_the_superseded_set_is_ever_admitted_by_supersession()\n'
                '\n'
                '\n'
                'def _no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n')),
        ('def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n',
         (
                'def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n'
                '    with C.call_scope():       # ONE outer READ-ONLY governance call: the later-cohort enumeration shares one verdict per cohort\n'
                '        _integration_reference_is_main_after_414_and_everything_unowned_equals_it()\n'
                '\n'
                '\n'
                'def _integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n')),
    ],
    'tests/ci_v4_lean_b1_scope.py': [
        ((
                '        pins = manifest(root, ref).get("source_blobs", {})\n'
                '        for path in HANDOFFS:\n'),
         (
                '        pins = manifest(root, ref).get("source_blobs", {})\n'
                '        N = _next()\n'
                '        nxt = N is not None and N.signature_ok(root, ref)\n'
                '        for path in HANDOFFS:\n'
                '            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution of this shared path\n'
                '                continue\n')),
        ((
                '                return False\n'
                '        return True\n'
                '    except (OSError, ValueError, KeyError, TypeError, UnicodeError, subprocess.CalledProcessError):\n'),
         (
                '                return False\n'
                '        return N.reviewed_edits_ok(root, ref) if nxt else True\n'
                '    except (OSError, ValueError, KeyError, TypeError, UnicodeError, subprocess.CalledProcessError):\n')),
        ((
                '    _SCOPE.append({})\n'
                '    try:\n'
                '        yield\n'
                '    finally:\n'),
         (
                '    _SCOPE.append({})\n'
                '    try:\n'
                '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept globally.\n'
                '        N = _next()\n'
                '        if N is None:\n'
                '            yield\n'
                '        else:\n'
                '            with N.scoped():\n'
                '                yield\n'
                '    finally:\n')),
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
                'def map_keys(repo=None, ref=None):\n'
                '    return tuple(MAP_KEYS)\n'),
         (
                "SUCCESSOR = 'tests.ci_v4_lean_b2_scope'\n"
                '\n'
                '\n'
                'def _next():\n'
                '    """The one finite forward successor (CI V4 Lean B2). Low-level only: its signature never calls this module or the composite."""\n'
                '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
                '    if SUCCESSOR not in COHORT_MODULES:\n'
                '        return None\n'
                '    from tests import ci_v4_lean_b2_scope\n'
                '    return ci_v4_lean_b2_scope\n'
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
                '        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ()\n'
                '        return tuple(MAP_KEYS) + more\n')),
        ('        if COHORT_MODULES != BASE_COHORTS + (__name__,):\n',
         '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n'),
        ('        if pins.get("tests/ci_v4_lean_b1_scope.py") != _MODULE_BLOB:\n',
         (
                '        nx = _next_pins(root, ref)\n'
                '        if nx.get("tests/ci_v4_lean_b1_scope.py", pins.get("tests/ci_v4_lean_b1_scope.py")) != _MODULE_BLOB:\n')),
        ('        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n',
         (
                '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
                '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n')),
        ('        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\n',
         '        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\n'),
        ('            if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):\n',
         '            if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS))):\n'),
        ((
                '        allowed = OWNED_PATHS | {MANIFEST}\n'
                '        changed = set('),
         (
                '        allowed = closure_paths(root, ref)\n'
                '        changed = set(')),
        ((
                'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                '    return dict(manifest(repo, ref).get("source_blobs", {}))\n'),
         (
                'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                '    root = Path(repo) if repo is not None else ROOT\n'
                '    with scoped():\n'
                '        pins = dict(manifest(repo, ref).get("source_blobs", {}))\n'
                '        pins.update(_next_pins(root, ref))\n'
                '        return pins\n')),
        ((
                'def closure_paths(repo=None, ref=None):\n'
                '    return OWNED_PATHS | {MANIFEST} if signature_ok(repo, ref) else frozenset()\n'),
         (
                'def closure_paths(repo=None, ref=None):\n'
                '    root = Path(repo) if repo is not None else ROOT\n'
                '    with scoped():\n'
                '        if not signature_ok(root, ref):\n'
                '            return frozenset()\n'
                '        N = _next()\n'
                '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())\n')),
        ((
                'def supersedes(path, value, repo=None, ref=None):\n'
                '    if path not in SUPERSEDED:\n'
                '        return False\n'),
         (
                'def supersedes(path, value, repo=None, ref=None):\n'
                '    with scoped():      # one shared read scope per call: the successor signature is evaluated once, then dropped\n'
                '        N = _next()\n'
                '        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref):\n'
                '            return True\n'
                '        return _supersedes_own(path, value, repo, ref)\n'
                '\n'
                '\n'
                'def _supersedes_own(path, value, repo=None, ref=None):\n'
                '    if path not in SUPERSEDED:\n'
                '        return False\n')),
        ('    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value\n',
         (
                '    # the CURRENT pin of this path (the successor overlay wins while its signature holds), never a raw superseded manifest line\n'
                '    return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\n')),
        ((
                '    try:\n'
                '        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:\n'),
         (
                '    try:\n'
                '        N = _next()\n'
                '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n'
                '            return True\n'
                '        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:\n')),
    ],
    'tests/c06_cost_workspace_scope.py': [
        ('        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\r\n',
         (
                '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\r\n'
                "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope')):       # at most the two reviewed successors\r\n")),
    ],
    'tests/test_bess02_scope.py': [
        ('                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n',
         "                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"),
    ],
    'tests/test_f03_financing_scope.py': [
        ('        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n',
         "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')", b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/test_f04_financing_scope.py': [
        ("        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n",
         "        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"),
        ('        B1=C06_APPROVAL._next()\n',
         (
                '        B1=C06_APPROVAL._next()\n'
                '        B2=B1._next() if B1 is not None and B1.signature_ok() else None\n')),
        ('        authority=B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n',
         '        authority=B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n'),
        ("        expected=json.loads(C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n",
         (
                '        _B1=C06_APPROVAL._next();_B2=_B1._next() if _B1 is not None and _B1.signature_ok() else None\n'
                "        expected=json.loads(_B2.expected_map(ROOT,path,_B2.effective_pins()) if _B2 is not None and _B2.signature_ok() else C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n")),
    ],
    'tests/test_r03_ppa_scope.py': [
        ('        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n',
         "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')", b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n'),
        ('    B1 = C06_APPROVAL._next()\n',
         (
                '    B1 = C06_APPROVAL._next()\n'
                '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n')),
        ('        authority = B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n',
         '        authority = B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n'),
    ],
    'tests/test_r04_ppa_scope.py': [
        ('    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n',
         '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\'))\n'),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')", b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n'),
        ('        B1 = C06_APPROVAL._next()\n',
         (
                '        B1 = C06_APPROVAL._next()\n'
                '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n')),
        ('        authority = (B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the further reviewed B1 substitution of this shared path\n',
         '        authority = (B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the further reviewed B1 substitution of this shared path\n'),
    ],
    'tests/test_t01e_remediation_scope.py': [
        ('                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n',
         '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\'))\n'),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')", b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n'),
        ('        if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS:            # the further reviewed B1 substitution of this shared path\n',
         (
                '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                '        if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS:            # the further reviewed B2 substitution of this shared path\n'
                '            assert (ROOT / p).read_bytes() == B2.expected_handoff(ROOT, p)\n'
                '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                '            continue\n'
                '        if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS:            # the further reviewed B1 substitution of this shared path\n')),
    ],
    'tests/test_ci_v4_perf_scope.py': [
        ((
                '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                '            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n'),
         (
                '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n")),
        ((
                '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                '                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR))\n'),
         (
                '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                "                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n")),
        ('    return N if N is not None and N.signature_ok() else None\n',
         (
                '    return N if N is not None and N.signature_ok() else None\n'
                '\n'
                '\n'
                'def _b2():\n'
                '    """The one reviewed B2 successor of B1 while it is registered and exact, else None."""\n'
                '    N = _b1()\n'
                '    N2 = N._next() if N is not None else None\n'
                '    return N2 if N2 is not None and N2.signature_ok() else None\n')),
        ((
                '    for p in sorted(F.HANDOFFS):\n'
                '        want = (_b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n'),
         (
                '    for p in sorted(F.HANDOFFS):\n'
                '        want = (_b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
                '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n')),
        ((
                '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                '        want = (_b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n'),
         (
                '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                '        want = (_b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
                '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n')),
        ('              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')")\n',
         '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')")\n'),
    ],
    'tests/test_c06_cost_workspace_scope.py': [
        ('    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR))       # C06 is followed by at most the one reviewed B1 successor\n',
         "    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))       # C06 is followed by at most the one reviewed B1 successor\n"),
        ((
                '    N=F._next()\n'
                '    for path in F.HANDOFFS:\n'
                '        later=N if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'),
         (
                '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None\n'
                '    for path in F.HANDOFFS:\n'
                '        later=N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n')),
        ('            elif kind==\'duplicate_registration\':text=text.replace("\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')","\'tests.c06_cost_workspace_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')")\n',
         '            elif kind==\'duplicate_registration\':text=text.replace("\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\'","\'tests.c06_cost_workspace_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\'")\n'),
        ("        assert {k for k in original['source_blobs'] if original['source_blobs'][k]!=current['source_blobs'][k]}<=set(F.MAP_KEYS)\n",
         "        assert {k for k in original['source_blobs'] if original['source_blobs'][k]!=current['source_blobs'][k]}<=set(F.map_keys())\n"),
        ('            if m.__name__ not in (F.__name__, F.SUCCESSOR):         # a successor never attests an older accepted ref\n',
         "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'):         # a successor never attests an older accepted ref\n"),
        ("        expected=json.loads(F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n",
         (
                '        _N=F._next();_N2=_N._next() if _N is not None and _N.signature_ok() else None\n'
                "        expected=json.loads(_N2.expected_map(ROOT,path,_N2.effective_pins()) if _N2 is not None and _N2.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n")),
    ],
    'tests/test_post432_l01_l02_scope.py': [
        ("    if 'tests.ci_v4_lean_b1_scope' in C.COHORT_MODULES and B1 is not None and B1.signature_ok():\n",
         (
                '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
                "    if 'tests.ci_v4_lean_b2_scope' in C.COHORT_MODULES and B2 is not None and B2.signature_ok():\n"
                '        expected = B2.expected_handoff(ROOT, X.REGISTRY)\n'
                "    elif 'tests.ci_v4_lean_b1_scope' in C.COHORT_MODULES and B1 is not None and B1.signature_ok():\n")),
    ],
    'tests/test_r02_ppa_ux_scope.py': [
        ("                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope') if m in C.COHORT_MODULES)\n",
         "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope') if m in C.COHORT_MODULES)\n"),
        ('    B1 = C06_APPROVAL._next()\n',
         (
                '    B1 = C06_APPROVAL._next()\n'
                '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n')),
        ('    if len(nxt) == 8 and B1 is not None and B1.signature_ok():\n',
         (
                '    if len(nxt) == 9 and B2 is not None and B2.signature_ok():\n'
                '        expected = B2.expected_handoff(ROOT, X.REGISTRY)\n'
                '    elif len(nxt) == 8 and B1 is not None and B1.signature_ok():\n')),
    ],
    'tests/test_ci_v4_lean_b1_scope.py': [
        ((
                '    for p in T.HANDOFFS:\n'
                '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'),
         (
                '    N = T._next()\n'
                '    for p in T.HANDOFFS:\n'
                '        if N is not None and N.signature_ok() and p in N.HANDOFFS:                  # the further reviewed B2 substitution of this shared path\n'
                '            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
                '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                '            continue\n'
                '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n')),
        ((
                '    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and C.COHORT_MODULES.count(T.__name__) == 1\n'
                '    assert C.COHORT_MODULES[-2:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope")\n'),
         (
                '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR)) and C.COHORT_MODULES.count(T.__name__) == 1\n'
                '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == "tests.c06_cost_workspace_scope"\n')),
        ('        assert changed <= set(T.MAP_KEYS)\n',
         '        assert changed <= set(T.map_keys())\n'),
        ('    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope")\n',
         '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-3:] if m != "tests.ci_v4_lean_b2_scope") == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope")\n'),
        ('    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\')"\n',
         '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')"\n'),
        ('        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b1_scope\')")),\n',
         '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n'),
        ('        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\')")),\n',
         '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n'),
        ('    reg = pins[T.REGISTRY]\n',
         '    reg = T.effective_pins()[T.REGISTRY]\n'),
    ],
    'tests/test_ci_v4_lean_tamper_matrix.py': [
        ('TAIL = "\'tests.ci_v4_lean_b1_scope\')"\n',
         'TAIL = "\'tests.ci_v4_lean_b2_scope\')"\n'),
        ('    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "\'tests.ci_v4_lean_b1_scope\', " + TAIL), REG, "pinned"),\n',
         '    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "\'tests.ci_v4_lean_b2_scope\', " + TAIL), REG, "pinned"),\n'),
        ('    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v4_lean_b1_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n',
         '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v4_lean_b2_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'),
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
        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept globally.
        N = _next()
        if N is None:
            yield
        else:
            with N.scoped():
                yield
    finally:
        _SCOPE.pop()


def _compute(root, ref, mode):
    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the changed/untracked checks."""
    from contextlib import nullcontext
    N = _next()
    with (N.scoped() if N is not None else nullcontext()):
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


SUCCESSOR = 'tests.ci_v4_lean_b3_scope'


def _next():
    """The one finite forward successor (CI V4 Lean B3). Low-level only: its signature never calls this module or the composite."""
    from tests.fin_v2_cohorts import COHORT_MODULES
    if SUCCESSOR not in COHORT_MODULES:
        return None
    from tests import ci_v4_lean_b3_scope
    return ci_v4_lean_b3_scope


def _next_pins(root, ref):
    N = _next()
    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}


def map_keys(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    with scoped():
        N = _next()
        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ()
        return tuple(MAP_KEYS) + more


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
        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        N = _next()
        nx = _next_pins(root, ref)
        nxt = N is not None and N.signature_ok(root, ref)
        if nx.get("tests/ci_v4_lean_b2_scope.py", pins.get("tests/ci_v4_lean_b2_scope.py")) != _MODULE_BLOB:
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
        cur = {p: nx.get(p, b) for p, b in pins.items()}
        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))
        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:
            return False
        owned = (OWNED_PATHS - (set() if closure else CURRENT_MAPS)) | {MANIFEST}
        if any(modes.get(p) != "100644" for p in owned):
            return False
        n_covered = {p for p in HANDOFFS if nxt and p in N.HANDOFFS}
        if any(pins[p] != _expected_blob(key, p) for p in HANDOFFS if p not in n_covered):
            return False
        if nxt and not N.reviewed_edits_ok(root, ref):
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
        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p)
               for p in FROZEN if not (nxt and p in N.HANDOFFS)):
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

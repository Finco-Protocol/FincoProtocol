"""CI V4 shard-2 fix (scheduler worker-scan correction, shard stall diagnostics, u1 node split): finite exact-source successor after the accepted C06 leaf.

CI-only. No financial engine, schema, API, writer, persistence, authentication, CSRF, Run, UX or feature-flag path; no change to
``docs/ci_v4/module_weights.json``, to the CI V4 workflows or to any other CI tool. It admits exactly the reviewed CI V4 files in ``SOURCE_PATHS``
(two ``tools/`` modules, two ``docs/ci_v4/`` policy files, two tests), pinned by exact Git blob and Git mode against the immutable BASE tree (accepted
main with C06). The ``tools/`` admission is a literal two-path set (``CI_TOOL_PATHS``): the forbidden prefixes of the older cohorts are not widened and no
prefix, wildcard or dynamic allowlist exists.

The shared governance paths it really changes are SUPERSEDED paths carrying their accepted BASE blob, the literal one-occurrence substitutions that produce
the new blob (``HANDOFFS``) and the exact new blob. C06 hands its own forward hook, the registry tail and the exact-tail tests to this successor by reviewed
substitution; C06's manifest and every other historical manifest stay byte-identical. Only the current-map keys of the paths this cohort itself moves change
(the registry and the reviewed handoff paths in the current maps that pin them, the CI paths in the CI V4 map).

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls C06, an older cohort or the composite; the C06 leaf
calls this module through one forward hook (the acyclic pattern F04 and R04 used). The module does not contain its own blob: the manifest pins it from outside.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "07f558461dc13c1a8c623064360dee0b4ba42cd0"
BASE_TREE = "d3c7bcf2c24f8557b7977cb3dea85816ac15ed2a"
MANIFEST = "docs/ci_v4/shard2_fix/SOURCE_SUCCESSOR.json"
SCHEMA = "CI_V4_SHARD2_FIX_EXACT_SOURCE_V1"
AUTHORIZATION = ("Owner-directed PR #448 Correction A: finite exact-source successor of the CI V4 scheduler/shard/node-split change on the existing "
                 "Draft; CI-only; no financial policy, merge or deployment authorization.")
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/c06_cost_workspace_scope.py"
# The only tools/ paths this cohort can admit (literal; an unknown tools/ path is never admitted by any prefix or pattern).
CI_TOOL_PATHS = frozenset((
    "tools/ci_v4_activate.py",
    "tools/ci_v4_schedule.py",
    "tools/ci_v4_shard.py",
))
SOURCE_PATHS = CI_TOOL_PATHS | frozenset((
    "docs/ci_v4/node_split_policy.json",
    "docs/ci_v4/node_weights.json",
    "tests/test_ci_v4_activate.py",
    "tests/test_ci_v4_nodes.py",
    "tests/test_ci_v4_schedule.py",
))
NEW = frozenset((
    "tests/ci_v4_shard2_fix_scope.py",
    "tests/test_ci_v4_shard2_fix_scope.py",
))
# Accepted governance paths whose bytes move by one reviewed literal substitution (HANDOFFS) ...
HANDOFF_PATHS = frozenset((
    "tests/c06_cost_workspace_scope.py",
    "tests/fin_v2_cohorts.py",
    "tests/test_bess02_scope.py",
    "tests/test_c06_cost_workspace_scope.py",
    "tests/test_ci_v4_perf_scope.py",
    "tests/test_f03_financing_scope.py",
    "tests/test_f04_financing_scope.py",
    "tests/test_post413_o1_scope.py",
    "tests/test_post432_l01_l02_scope.py",
    "tests/test_r02_ppa_ux_scope.py",
    "tests/test_r03_ppa_scope.py",
    "tests/test_r04_ppa_scope.py",
    "tests/test_rcux_governance.py",
    "tests/test_t01e_remediation_scope.py",
    "tests/test_u1_scope.py",
    "tests/test_u2_scope.py",
    "tests/test_ux_pr1_scope.py",
    "tests/test_wf06b_scope.py",
    "tests/u1_scope.py",
    "tests/u2_scope.py",
    "tests/ux_pr1_scope.py",
    "tests/ux_pr2b_scope.py",
    "tests/ux_pr2c_scope.py",
    "tests/ux_pr3b1_scope.py",
))
# ... and the eight current maps, of which only the pins of the paths this cohort moves change (the bounded handoff C06 made).
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
MAP_KEYS = tuple(sorted({REGISTRY} | SOURCE_PATHS | HANDOFF_PATHS))      # a key moves only where a current map actually pins that path
OWNED_PATHS = SOURCE_PATHS | NEW | HANDOFF_PATHS | CURRENT_MAPS
SUPERSEDED = OWNED_PATHS - NEW
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "tools/", "migrations/", "app/", "research/", "main_web.py")
# Accepted historical manifests, products, CI and every other CI V4 file that must stay byte-identical to BASE (a successor never rewrites them).
FROZEN = (
    ".github/workflows/ci_v4_f01_job.yml",
    ".github/workflows/ci_v4_full.yml",
    ".github/workflows/ci_v4_pr.yml",
    ".github/workflows/ci_v4_release_gate.yml",
    ".github/workflows/ci_v4_shadow_split.yml",
    ".github/workflows/finval_f01_acceptance.yml",
    "docs/bess02/SOURCE_SUCCESSOR.json",
    "docs/bess_setup/SOURCE_SUCCESSOR.json",
    "docs/ci_v4/ci-v4-policy.json",
    "docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json",
    "docs/ci_v4/full_skip_baseline.json",
    "docs/ci_v4/module_weights.json",
    "docs/r03_ppa_candidate/SOURCE_SUCCESSOR.json",
    "docs/r04_ppa_global_cap/SOURCE_SUCCESSOR.json",
    "docs/react_migration/c06_cost_workspace/C06_LEDGER.md",
    "docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json",
    "docs/react_migration/f03_financing/SOURCE_SUCCESSOR.json",
    "docs/react_migration/f04_financing/SOURCE_SUCCESSOR.json",
    "docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json",
    "docs/tax_reference_registry/t01e/SOURCE_SUCCESSOR.json",
    "research/r03_ppa_candidate/core.py",
    "research/r04_ppa_global_cap/core.py",
    "tax_reference_registry/__init__.py",
    "tax_reference_registry/remediation.py",
    "tests/bess02_scope.py",
    "tests/ci_v4_perf_scope.py",
    "tests/ci_v4_scope.py",
    "tests/f03_financing_scope.py",
    "tests/f04_financing_scope.py",
    "tests/r03_ppa_core/oracle.py",
    "tests/r03_ppa_scope.py",
    "tests/r04_ppa_global_cap/oracle.py",
    "tests/r04_ppa_scope.py",
    "tests/t01e_remediation_scope.py",
    "tests/tax_reference_registry_scope.py",
    "tools/ci_v4_aggregate.py",
    "tools/ci_v4_full_record.py",
    "tools/ci_v4_governance_gate.py",
    "tools/ci_v4_nodes.py",
    "tools/ci_v4_release_gate.py",
    "tools/ci_v4_select.py",
)


@lru_cache(maxsize=512)
def _base_mode(root, path):
    """Git mode of an IMMUTABLE accepted-main (BASE) entry (cached: BASE never changes, so a cached value can never go stale)."""
    line = _git(Path(root), "ls-tree", BASE, "--", path).decode().strip()
    return line.split()[0] if line else None


@lru_cache(maxsize=512)
def _base_blob(root, path):
    """Blob id of an IMMUTABLE accepted-main (BASE) object, hashed once."""
    return _blob(_base_bytes(root, path))


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
        return d if (isinstance(d, dict) and set(d) == {"schema_version", "authorization", "base", "base_tree", "source_blobs", "base_blobs",
                                                         "source_modes", "base_modes"}
                     and d["schema_version"] == SCHEMA and d["authorization"] == AUTHORIZATION and d["base"] == BASE and d["base_tree"] == BASE_TREE
                     and isinstance(d["source_blobs"], dict) and isinstance(d["base_blobs"], dict)
                     and isinstance(d["source_modes"], dict) and isinstance(d["base_modes"], dict)) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


def expected_map(root, path, pins=None):
    """Only the FINITE current-source keys (the registry pin and the six CI paths) may move; all history stays unchanged."""
    d = json.loads(_base_bytes(str(root), path))
    pins = manifest(root).get("source_blobs", {}) if pins is None else pins
    for key in MAP_KEYS:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The accepted C06 leaf gains one forward hook to this
# cohort (the same acyclic pattern F04 and R04 used); the registry appends this cohort exactly once; the exact-tail tests accept one more state.
HANDOFFS = {'tests/c06_cost_workspace_scope.py': [('    _SCOPE.append({})\r\n    try:\r\n        yield\r\n    finally:\r\n        _SCOPE.pop()\r\n',
                                        '    _SCOPE.append({})\r\n'
                                        '    try:\r\n'
                                        '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept '
                                        'globally.\r\n'
                                        '        N = _next()\r\n'
                                        '        if N is None:\r\n'
                                        '            yield\r\n'
                                        '        else:\r\n'
                                        '            with N.scoped():\r\n'
                                        '                yield\r\n'
                                        '    finally:\r\n'
                                        '        _SCOPE.pop()\r\n'),
                                       ('    if mode == "exact":\r\n'
                                        '        return _signature_ok(root, ref, True) and _diff_ok(root, ref)\r\n'
                                        '    return _signature_ok(root, ref, mode)\r\n',
                                        '    from contextlib import nullcontext\r\n'
                                        '    N = _next()\r\n'
                                        '    with (N.scoped() if N is not None else nullcontext()):\r\n'
                                        '        if mode == "exact":\r\n'
                                        '            return _signature_ok(root, ref, True) and _diff_ok(root, ref)\r\n'
                                        '        return _signature_ok(root, ref, mode)\r\n'),
                                       ('        if COHORT_MODULES != BASE_COHORTS + (__name__,):\r\n            return False\r\n',
                                        '        if COHORT_MODULES != BASE_COHORTS + (__name__,) and COHORT_MODULES != BASE_COHORTS + (__name__, '
                                        "'tests.ci_v4_shard2_fix_scope'):\r\n"
                                        '            return False\r\n'),
                                       ('        if pins.get("tests/c06_cost_workspace_scope.py") != _MODULE_BLOB:\r\n            return False\r\n',
                                        '        nx = _next_pins(root, ref)\r\n'
                                        '        if pins.get("tests/c06_cost_workspace_scope.py") != _MODULE_BLOB and '
                                        'nx.get("tests/c06_cost_workspace_scope.py") != _MODULE_BLOB:\r\n'
                                        '            return False\r\n'),
                                       ('        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\r\n'
                                        '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\r\n'
                                        '        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\r\n',
                                        '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\r\n'
                                        '        cur = {p: nx.get(p, b) for p, b in pins.items()}\r\n'
                                        '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\r\n'
                                        '        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\r\n'),
                                       ('                if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):\r\n',
                                        '                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in '
                                        'MAP_KEYS))):\r\n'),
                                       ('        allowed = OWNED_PATHS | {MANIFEST}\r\n        changed = set(',
                                        '        allowed = closure_paths(root, ref)\r\n        changed = set('),
                                       ('def map_keys(repo=None, ref=None):\r\n    return tuple(MAP_KEYS)\r\n',
                                        'def _next():\r\n'
                                        '    """The one finite forward successor (CI V4 shard-2 fix). Low-level only: its signature never calls this '
                                        'module or the composite."""\r\n'
                                        '    from tests.fin_v2_cohorts import COHORT_MODULES\r\n'
                                        "    if 'tests.ci_v4_shard2_fix_scope' not in COHORT_MODULES:\r\n"
                                        '        return None\r\n'
                                        '    from tests import ci_v4_shard2_fix_scope\r\n'
                                        '    return ci_v4_shard2_fix_scope\r\n'
                                        '\r\n'
                                        '\r\n'
                                        'def _next_pins(root, ref):\r\n'
                                        '    N = _next()\r\n'
                                        '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\r\n'
                                        '\r\n'
                                        '\r\n'
                                        'def map_keys(repo=None, ref=None):\r\n'
                                        '    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    with scoped():\r\n'
                                        '        N = _next()\r\n'
                                        '        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_KEYS) if N is not None and '
                                        'N.signature_ok(root, ref) else ()\r\n'
                                        '        return tuple(MAP_KEYS) + more\r\n'),
                                       ('def effective_pins(repo=None, ref=None, *, signature=False):\r\n'
                                        '    return dict(manifest(repo, ref).get("source_blobs", {}))\r\n',
                                        'def effective_pins(repo=None, ref=None, *, signature=False):\r\n'
                                        '    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    with scoped():\r\n'
                                        '        pins = dict(manifest(repo, ref).get("source_blobs", {}))\r\n'
                                        '        pins.update(_next_pins(root, ref))\r\n'
                                        '        return pins\r\n'),
                                       ('def closure_paths(repo=None, ref=None):\r\n'
                                        '    return OWNED_PATHS | {MANIFEST} if signature_ok(repo, ref) else frozenset()\r\n',
                                        'def closure_paths(repo=None, ref=None):\r\n'
                                        '    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    with scoped():\r\n'
                                        '        if not signature_ok(root, ref):\r\n'
                                        '            return frozenset()\r\n'
                                        '        N = _next()\r\n'
                                        '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else '
                                        'frozenset())\r\n'),
                                       ('def supersedes(path, value, repo=None, ref=None):\r\n'
                                        '    if path not in SUPERSEDED:\r\n'
                                        '        return False\r\n'
                                        '    # Like the accepted F03 / performance leaves: the signature decides a supersession; the composite '
                                        "separately requires every cohort's FULL\r\n"
                                        '    # exactness (map bytes, changed set, untracked files), so a signature-only verdict never makes the tree '
                                        'valid.\r\n'
                                        '    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value\r\n',
                                        'def supersedes(path, value, repo=None, ref=None):\r\n'
                                        '    with scoped():      # one shared read scope per call: the successor signature is evaluated once, then '
                                        'dropped\r\n'
                                        '        N = _next()\r\n'
                                        '        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref):\r\n'
                                        '            return True\r\n'
                                        '        if path not in SUPERSEDED:\r\n'
                                        '            return False\r\n'
                                        '        # the CURRENT pin of this path (the successor overlay wins while its signature holds), never a raw '
                                        'superseded manifest line\r\n'
                                        '        return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\r\n'),
                                       ('    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    try:\r\n'
                                        '        if _git(root, "merge-base", "origin/main", "HEAD")',
                                        '    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    try:\r\n'
                                        '        N = _next()\r\n'
                                        '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\r\n'
                                        '            return True\r\n'
                                        '        if _git(root, "merge-base", "origin/main", "HEAD")'),
                                       ('        pins = manifest(root, ref).get("source_blobs", {})\r\n'
                                        '        for path in HANDOFFS:\r\n'
                                        '            actual = _read(root, path, ref)\r\n'
                                        '            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\r\n'
                                        '                return False\r\n'
                                        '        return True\r\n',
                                        '        pins = manifest(root, ref).get("source_blobs", {})\r\n'
                                        '        N = _next()\r\n'
                                        '        nxt = N is not None and N.signature_ok(root, ref)\r\n'
                                        '        for path in HANDOFFS:\r\n'
                                        '            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further '
                                        'substitution of this shared path\r\n'
                                        '                continue\r\n'
                                        '            actual = _read(root, path, ref)\r\n'
                                        '            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\r\n'
                                        '                return False\r\n'
                                        '        return N.reviewed_edits_ok(root, ref) if nxt else True\r\n')],
 'tests/fin_v2_cohorts.py': [("'tests.c06_cost_workspace_scope')", "'tests.c06_cost_workspace_scope', 'tests.ci_v4_shard2_fix_scope')")],
 'tests/test_bess02_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                 'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                 'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()))\n',
                                 '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) or '
                                 '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                 '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok()))\n'),
                                ('        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared bundle, '
                                 'exactly at its pinned blob\n',
                                 '        if path in S2_APPROVAL.SUPERSEDED and S2_APPROVAL.signature_ok():     # the one reviewed CI V4 shard-2 fix '
                                 'successor of the CI V4 scheduler/shard sources\n'
                                 '            assert B._blob((B.ROOT/path).read_bytes()) == S2_APPROVAL.effective_pins()[path]\n'
                                 '            continue\n'
                                 '        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared bundle, '
                                 'exactly at its pinned blob\n')],
 'tests/test_c06_cost_workspace_scope.py': [('    assert C.COHORT_MODULES == F.BASE_COHORTS + (F.__name__,)\n',
                                             '    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, '
                                             "'tests.ci_v4_shard2_fix_scope'))\n"),
                                            ('    for path in F.HANDOFFS:assert (ROOT/path).read_bytes()==F.expected_handoff(ROOT,path)\n',
                                             '    from tests import ci_v4_shard2_fix_scope as S2\n'
                                             '    for path in F.HANDOFFS:\n'
                                             '        want=S2.expected_handoff(ROOT,path) if S2.signature_ok() and path in S2.HANDOFFS else '
                                             'F.expected_handoff(ROOT,path)\n'
                                             '        assert (ROOT/path).read_bytes()==want\n'),
                                            ('            if m.__name__!=F.__name__:\n'
                                             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n',
                                             "            if m.__name__ not in (F.__name__,'tests.ci_v4_shard2_fix_scope'):      # the later "
                                             'reviewed CI V4 shard-2 fix successor does not exist at the accepted base\n'
                                             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n'),
                                            ('            if kind==\'missing_registration\':text=text.replace(", '
                                             '\'tests.c06_cost_workspace_scope\')",\')\')\n',
                                             '            if kind==\'missing_registration\':text=text.replace(", \'tests.c06_cost_workspace_scope\', '
                                             '\'tests.ci_v4_shard2_fix_scope\')", ", \'tests.ci_v4_shard2_fix_scope\')")\n'),
                                            ('            elif '
                                             'kind==\'duplicate_registration\':text=text.replace("\'tests.c06_cost_workspace_scope\')","\'tests.c06_cost_workspace_scope\', '
                                             '\'tests.c06_cost_workspace_scope\')")\n',
                                             '            elif '
                                             'kind==\'duplicate_registration\':text=text.replace("\'tests.c06_cost_workspace_scope\', '
                                             '\'tests.ci_v4_shard2_fix_scope\')","\'tests.c06_cost_workspace_scope\', '
                                             '\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_shard2_fix_scope\')")\n'),
                                            ('        expected=json.loads(F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a '
                                             "reviewed successor's registry pin wins)\n",
                                             '        from tests import ci_v4_shard2_fix_scope as S2\n'
                                             '        expected=json.loads(S2.expected_map(ROOT,path,S2.effective_pins()) if S2.signature_ok() else '
                                             "F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's pins "
                                             'win)\n'),
                                            ("        assert {k for k in original['source_blobs'] if "
                                             "original['source_blobs'][k]!=current['source_blobs'][k]}<=set(F.MAP_KEYS)\n",
                                             "        assert {k for k in original['source_blobs'] if "
                                             "original['source_blobs'][k]!=current['source_blobs'][k]}<=set(F.map_keys())\n")],
 'tests/test_ci_v4_perf_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                     'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                     'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                    ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok())\n',
                                     '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) or '
                                     '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                     '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok())\n'),
                                    ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()))\n',
                                     '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) or '
                                     '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                     '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok()))\n'),
                                    ('    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n',
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (S2_APPROVAL.expected_handoff(ROOT, p) if S2_APPROVAL.signature_ok() and p in '
                                     'S2_APPROVAL.HANDOFFS\n'
                                     '                else C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n'),
                                    ('        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n',
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (S2_APPROVAL.expected_handoff(ROOT, p) if S2_APPROVAL.signature_ok() and p in '
                                     'S2_APPROVAL.HANDOFFS\n'
                                     '                else C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n'),
                                    ('\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")\n',
                                     '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_shard2_fix_scope\')")\n'),
                                    ('    for other in ("docs/ci_v4/node_split_policy.json", "docs/ci_v4/ci-v4-policy.json", '
                                     '"docs/ci_v4/node_weights.json"):\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(other, F._blob((ROOT / other).read_bytes())) is False, other\n',
                                     '    for other in ("docs/ci_v4/ci-v4-policy.json",):\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(other, F._blob((ROOT / other).read_bytes())) is False, other\n'
                                     '    # The two policy files the reviewed CI V4 shard-2 fix successor moved are accepted at exactly its pin - '
                                     'never at the old BASE bytes or a forged value.\n'
                                     '    for moved in ("docs/ci_v4/node_split_policy.json", "docs/ci_v4/node_weights.json"):\n'
                                     '        pin = S2_APPROVAL.manifest()["source_blobs"][moved]\n'
                                     '        assert S2_APPROVAL.signature_ok() and F._blob((ROOT / moved).read_bytes()) == pin\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(moved, pin) is True, moved\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(moved, F._blob(_git("show", F.BASE + ":" + moved))) is False, moved\n'
                                     '        with C.call_scope():\n'
                                     '            assert U31.supersedes(moved, "0" * 40) is False, moved\n')],
 'tests/test_f03_financing_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                        'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                        'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                       ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                        'C06_APPROVAL.signature_ok())\n',
                                        '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) '
                                        'or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                        '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok())\n'),
                                       ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                        'b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_shard2_fix_scope\')", '
                                        'b"\'tests.ci_v4_shard2_fix_scope\', \'tests.fake_scope\')")),\n')],
 'tests/test_f04_financing_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                        'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                        'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                       ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                        'C06_APPROVAL.signature_ok())\n',
                                        '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) '
                                        'or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                        '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok())\n'),
                                       ('        authority=C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if',
                                        '        authority=S2_APPROVAL if S2_APPROVAL.signature_ok() and path in S2_APPROVAL.HANDOFFS else '
                                        'C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if'),
                                       ('        if path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                        '            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)\n'
                                        "            assert F._blob((ROOT/path).read_bytes())==C06_APPROVAL.manifest()['source_blobs'][path]\n",
                                        '        if path in S2_APPROVAL.HANDOFFS and S2_APPROVAL.signature_ok():\n'
                                        '            assert (ROOT/path).read_bytes()==S2_APPROVAL.expected_handoff(ROOT,path)\n'
                                        "            assert F._blob((ROOT/path).read_bytes())==S2_APPROVAL.manifest()['source_blobs'][path]\n"
                                        '        elif path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                        '            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)\n'
                                        "            assert F._blob((ROOT/path).read_bytes())==C06_APPROVAL.manifest()['source_blobs'][path]\n"),
                                       ('            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')",", \'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\')")\n',
                                        '            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'",", \'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\'")\n'),
                                       ('            elif kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')","\'tests.f04_financing_scope\', '
                                        '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")\n',
                                        '            elif kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'","\'tests.f04_financing_scope\', '
                                        '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")\n'),
                                       ('        expected=json.loads(C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if '
                                        'C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))',
                                        '        expected=json.loads(S2_APPROVAL.expected_map(ROOT,path,S2_APPROVAL.effective_pins()) if '
                                        'S2_APPROVAL.signature_ok() else C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if '
                                        'C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))')],
 'tests/test_post413_o1_scope.py': [('def _u2_signed_later_pins(repo=None, ref=None):\n',
                                     'def _c06_continues(path, signed_pin, root, ref):\n'
                                     '    """The accepted C06 successor (#444) moved a presentation path that U2 had signed: C06 is exact and '
                                     'registered, its recorded BASE blob is exactly\n'
                                     "    U2's signed pin and the evaluated bytes are exactly C06's own pin (the registered chain U2 -> C06; nothing "
                                     'else is admitted by this helper)."""\n'
                                     '    from tests import c06_cost_workspace_scope as K\n'
                                     '    if K.__name__ not in C.COHORT_MODULES or path not in K.SUPERSEDED or not K.exact_blobs_ok(root, ref):\n'
                                     '        return False\n'
                                     '    signed = K.manifest(root, ref)\n'
                                     "    pin = signed.get('source_blobs', {}).get(path)\n"
                                     "    return (pin is not None and signed.get('base_blobs', {}).get(path) == signed_pin and K.supersedes(path, "
                                     'pin, root, ref)\n'
                                     '            and K._blob(K._read(root, path, ref)) == pin)\n'
                                     '\n'
                                     '\n'
                                     'def _u2_signed_later_pins(repo=None, ref=None):\n'),
                                    ('            and signed[p] != historical.get(p) and U2.supersedes(p, signed[p], root, ref)\n'
                                     '            and U2._blob(U2._read(root, p, ref)) == signed[p]}\n',
                                     '            and signed[p] != historical.get(p)\n'
                                     '            and ((U2.supersedes(p, signed[p], root, ref) and U2._blob(U2._read(root, p, ref)) == signed[p])\n'
                                     '                 or _c06_continues(p, signed[p], root, ref))}\n'),
                                    ('def test_positive_cohort_is_exact_registered_and_closed():\n'
                                     '    assert O.exact_blobs_ok() and O.valid() and C.valid() and U.exact_blobs_ok()\n'
                                     '    assert O.__name__ in C.COHORT_MODULES and O in C.cohorts() and O.__name__ in U.LATER_COHORTS and '
                                     'O.protected_blobs() == {}\n'
                                     '    data = O.manifest()\n'
                                     "    assert set(data['source_blobs']) == O.OWNED_PATHS - {O.MANIFEST} and set(data['base_blobs']) == "
                                     'O.SUPERSEDED\n'
                                     "    assert all('*' not in p and not p.endswith('/') for p in O.OWNED_PATHS)\n"
                                     '    assert not any(p.startswith(O.FORBIDDEN_PREFIXES) or p in O.FORBIDDEN_PATHS for p in O.OWNED_PATHS)\n'
                                     '    assert O.SUPERSEDED <= O.OWNED_PATHS\n'
                                     "    for stranger in ('app/library/router.py', 'app/v2/react_workspace_router.py', "
                                     "'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py',\n"
                                     "                     'financial_engine/x.py', '.github/workflows/ci.yml', 'app/capex_profiles/binding.py'):\n"
                                     '        assert not O.allowed_path(stranger) and not O.matches(stranger)\n'
                                     "    for owned in (ROUTE, SERVICE, BUNDLE, EDITOR, 'app/capex_profiles/runtime.py', "
                                     "'tests/post413_o1_scope.py'):\n"
                                     '        assert O.matches(owned) and O.allowed_path(owned) and U.allowed_path(owned)\n',
                                     'def test_positive_cohort_is_exact_registered_and_closed():\n'
                                     '    with C.call_scope():\n'
                                     '        assert O.exact_blobs_ok() and O.valid() and C.valid() and U.exact_blobs_ok()\n'
                                     '        assert O.__name__ in C.COHORT_MODULES and O in C.cohorts() and O.__name__ in U.LATER_COHORTS and '
                                     'O.protected_blobs() == {}\n'
                                     '        data = O.manifest()\n'
                                     "        assert set(data['source_blobs']) == O.OWNED_PATHS - {O.MANIFEST} and set(data['base_blobs']) == "
                                     'O.SUPERSEDED\n'
                                     "        assert all('*' not in p and not p.endswith('/') for p in O.OWNED_PATHS)\n"
                                     '        assert not any(p.startswith(O.FORBIDDEN_PREFIXES) or p in O.FORBIDDEN_PATHS for p in O.OWNED_PATHS)\n'
                                     '        assert O.SUPERSEDED <= O.OWNED_PATHS\n'
                                     "        for stranger in ('app/library/router.py', 'app/v2/react_workspace_router.py', "
                                     "'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py',\n"
                                     "                         'financial_engine/x.py', '.github/workflows/ci.yml', "
                                     "'app/capex_profiles/binding.py'):\n"
                                     '            assert not O.allowed_path(stranger) and not O.matches(stranger)\n'
                                     "        for owned in (ROUTE, SERVICE, BUNDLE, EDITOR, 'app/capex_profiles/runtime.py', "
                                     "'tests/post413_o1_scope.py'):\n"
                                     '            assert O.matches(owned) and O.allowed_path(owned) and U.allowed_path(owned)\n'),
                                    ('def test_supersession_is_bounded_to_the_exact_pin_of_a_superseded_path():\n'
                                     "    pins = O.manifest()['source_blobs']\n"
                                     "    for path in (ROUTE, SERVICE, 'app/v2/router.py', 'frontend/src/app/api.ts'):\n"
                                     '        assert O.supersedes(path, pins[path]) and U.supersedes(path, pins[path])\n'
                                     "        assert not O.supersedes(path, '0' * 40) and not U.supersedes(path, '0' * 40)\n"
                                     "    assert not O.supersedes('app/v2/capex_router.py', pins['app/v2/capex_router.py'])           # no older "
                                     'cohort pins it: owned, never superseded\n'
                                     "    assert not O.supersedes('app/library/router.py', pins[ROUTE]) and not "
                                     "U.supersedes('app/library/router.py', pins[ROUTE])\n"
                                     "    assert not O.supersedes(ROUTE, pins[SERVICE])                                                # one path's "
                                     "pin is never another path's value\n",
                                     'def test_supersession_is_bounded_to_the_exact_pin_of_a_superseded_path():\n'
                                     '    with C.call_scope():\n'
                                     "        pins = O.manifest()['source_blobs']\n"
                                     "        for path in (ROUTE, SERVICE, 'app/v2/router.py', 'frontend/src/app/api.ts'):\n"
                                     '            assert O.supersedes(path, pins[path]) and U.supersedes(path, pins[path])\n'
                                     "            assert not O.supersedes(path, '0' * 40) and not U.supersedes(path, '0' * 40)\n"
                                     "        assert not O.supersedes('app/v2/capex_router.py', pins['app/v2/capex_router.py'])           # no older "
                                     'cohort pins it: owned, never superseded\n'
                                     "        assert not O.supersedes('app/library/router.py', pins[ROUTE]) and not "
                                     "U.supersedes('app/library/router.py', pins[ROUTE])\n"
                                     '        assert not O.supersedes(ROUTE, pins[SERVICE])                                                # one '
                                     "path's pin is never another path's value\n"),
                                    ('def test_shared_sibling_pins_equal_this_cohorts_pin_and_nothing_else_moved():\n'
                                     '    evidence = _audit_shared_sibling_pins()\n'
                                     "    assert set(evidence[U2_MANIFEST]['u2']) == U2_LATER_PRESENTATION\n"
                                     "    assert all(not row['u2'] for name, row in evidence.items() if name != U2_MANIFEST)\n",
                                     'def test_shared_sibling_pins_equal_this_cohorts_pin_and_nothing_else_moved():\n'
                                     '    with C.call_scope():\n'
                                     '        evidence = _audit_shared_sibling_pins()\n'
                                     "        assert set(evidence[U2_MANIFEST]['u2']) == U2_LATER_PRESENTATION\n"
                                     "        assert all(not row['u2'] for name, row in evidence.items() if name != U2_MANIFEST)\n"),
                                    ('def test_signed_u2_sibling_admission_rejects_tampering_at_the_evaluated_checkout(wt, change):\n'
                                     '    from tests import u2_scope as U2\n'
                                     '    ui = sorted(U2_LATER_PRESENTATION)[0]\n'
                                     '    target = U2_MANIFEST\n'
                                     '    data = json.loads((wt / target).read_text())\n'
                                     "    if change == 'forged_pin':\n"
                                     "        data['source_blobs'][ui] = '0' * 40\n"
                                     "    elif change == 'stale_pin':\n"
                                     "        data['source_blobs'][ui] = json.loads(_git(wt, 'show', O.BASE + ':' + target))['source_blobs'][ui]\n"
                                     "    elif change == 'foreign_path':\n"
                                     "        data['source_blobs']['frontend/src/app/ForeignSibling.tsx'] = '0' * 40\n"
                                     "    elif change == 'wrong_o1_pin':\n"
                                     "        assert 'tests/u1_scope.py' in O.OWNED_PATHS\n"
                                     "        data['source_blobs']['tests/u1_scope.py'] = '0' * 40\n"
                                     "    elif change == 'unsigned_source':\n"
                                     '        target = ui\n'
                                     '        _flip(wt / target)\n'
                                     "    elif change == 'deregistered_u2':\n"
                                     "        target = 'tests/fin_v2_cohorts.py'\n"
                                     '        registry = wt / target\n'
                                     "        registry.write_text(_without_tuple_module(registry.read_text(), 'COHORT_MODULES', U2.__name__))\n"
                                     "        assert U2.__name__ not in _tuple_assignment(registry.read_text(), 'COHORT_MODULES')[1]\n"
                                     "    elif change == 'broken_u2_scope':\n"
                                     "        target = 'tests/u2_scope.py'\n"
                                     '        _flip(wt / target)\n'
                                     '    if target == U2_MANIFEST:\n'
                                     "        (wt / target).write_text(json.dumps(data, indent=2, sort_keys=True) + '\\n')\n"
                                     '    with pytest.raises(AssertionError):\n'
                                     '        _audit_shared_sibling_pins(wt)\n'
                                     '    assert not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', target)\n"
                                     '    # A new call observes the restored bytes; no verdict is shared across the mutation boundary.\n'
                                     '    assert U2.exact_blobs_ok(wt)\n',
                                     'def test_signed_u2_sibling_admission_rejects_tampering_at_the_evaluated_checkout(wt, change):\n'
                                     '    from tests import u2_scope as U2\n'
                                     '    ui = sorted(U2_LATER_PRESENTATION)[0]\n'
                                     '    target = U2_MANIFEST\n'
                                     '    data = json.loads((wt / target).read_text())\n'
                                     "    if change == 'forged_pin':\n"
                                     "        data['source_blobs'][ui] = '0' * 40\n"
                                     "    elif change == 'stale_pin':\n"
                                     "        data['source_blobs'][ui] = json.loads(_git(wt, 'show', O.BASE + ':' + target))['source_blobs'][ui]\n"
                                     "    elif change == 'foreign_path':\n"
                                     "        data['source_blobs']['frontend/src/app/ForeignSibling.tsx'] = '0' * 40\n"
                                     "    elif change == 'wrong_o1_pin':\n"
                                     "        assert 'tests/u1_scope.py' in O.OWNED_PATHS\n"
                                     "        data['source_blobs']['tests/u1_scope.py'] = '0' * 40\n"
                                     "    elif change == 'unsigned_source':\n"
                                     '        target = ui\n'
                                     '        _flip(wt / target)\n'
                                     "    elif change == 'deregistered_u2':\n"
                                     "        target = 'tests/fin_v2_cohorts.py'\n"
                                     '        registry = wt / target\n'
                                     "        registry.write_text(_without_tuple_module(registry.read_text(), 'COHORT_MODULES', U2.__name__))\n"
                                     "        assert U2.__name__ not in _tuple_assignment(registry.read_text(), 'COHORT_MODULES')[1]\n"
                                     "    elif change == 'broken_u2_scope':\n"
                                     "        target = 'tests/u2_scope.py'\n"
                                     '        _flip(wt / target)\n'
                                     '    if target == U2_MANIFEST:\n'
                                     "        (wt / target).write_text(json.dumps(data, indent=2, sort_keys=True) + '\\n')\n"
                                     '    with pytest.raises(AssertionError):\n'
                                     '        with C.call_scope():\n'
                                     '            _audit_shared_sibling_pins(wt)\n'
                                     '    with C.call_scope():\n'
                                     '        assert not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', target)\n"
                                     '    # A new call observes the restored bytes; no verdict is shared across the mutation boundary.\n'
                                     '    with C.call_scope():\n'
                                     '        assert U2.exact_blobs_ok(wt)\n'),
                                    ('def test_signed_u2_sibling_admission_checks_the_named_commit_not_another_checkout(wt):\n'
                                     "    before = _audit_shared_sibling_pins(wt, 'HEAD')\n"
                                     '    _flip(wt / sorted(U2_LATER_PRESENTATION)[0])\n'
                                     '    with pytest.raises(AssertionError):\n'
                                     '        _audit_shared_sibling_pins(wt)\n'
                                     "    assert _audit_shared_sibling_pins(wt, 'HEAD') == before\n",
                                     'def test_signed_u2_sibling_admission_checks_the_named_commit_not_another_checkout(wt):\n'
                                     '    with C.call_scope():\n'
                                     "        before = _audit_shared_sibling_pins(wt, 'HEAD')\n"
                                     '    _flip(wt / sorted(U2_LATER_PRESENTATION)[0])\n'
                                     '    with pytest.raises(AssertionError):\n'
                                     '        with C.call_scope():\n'
                                     '            _audit_shared_sibling_pins(wt)\n'
                                     '    with C.call_scope():\n'
                                     "        assert _audit_shared_sibling_pins(wt, 'HEAD') == before\n"),
                                    ('def test_the_ci_v4_later_exception_is_literal_bounded_and_needs_an_exact_cohort(wt):\n'
                                     '    """Negatives for the bounded CI V4 exception: a shared/co-pinned path, a non-CI path, a drifted CI V4 file '
                                     'each fail closed."""\n'
                                     '    from tests import ci_v4_scope as C4\n'
                                     '    later = _ci_v4_own_later_paths()\n'
                                     '    assert later and all(p.startswith(CI_V4_OWN_PREFIXES) for p in later)\n'
                                     "    assert not later & O.OWNED_PATHS and 'tests/u1_scope.py' not in later and 'tests/fin_v2_cohorts.py' not in "
                                     'later\n'
                                     "    assert not later & {'tests/test_cost_batch_save_v1.py', 'tests/test_saas_revamp_entry.py', "
                                     "'tests/u2_scope.py'}   # product / shared files stay out\n"
                                     "    assert '.github/workflows/public_safety_and_smoke.yml' not in later and 'tools/ci_v3_production.py' not in "
                                     'later\n'
                                     "    _flip(wt / 'tools/ci_v4_shard.py')                                                          # a drifted CI "
                                     'V4 file: cohort inexact -> no exception\n'
                                     '    assert not C4.exact_blobs_ok(wt) and _ci_v4_own_later_paths(wt) == frozenset()\n'
                                     "    _git(wt, 'checkout', '--', 'tools/ci_v4_shard.py')\n"
                                     '    assert _ci_v4_own_later_paths(wt) == later\n',
                                     'def test_the_ci_v4_later_exception_is_literal_bounded_and_needs_an_exact_cohort(wt):\n'
                                     '    """Negatives for the bounded CI V4 exception: a shared/co-pinned path, a non-CI path, a drifted CI V4 file '
                                     'each fail closed."""\n'
                                     '    from tests import ci_v4_scope as C4\n'
                                     '    later = _ci_v4_own_later_paths()\n'
                                     '    assert later and all(p.startswith(CI_V4_OWN_PREFIXES) for p in later)\n'
                                     "    assert not later & O.OWNED_PATHS and 'tests/u1_scope.py' not in later and 'tests/fin_v2_cohorts.py' not in "
                                     'later\n'
                                     "    assert not later & {'tests/test_cost_batch_save_v1.py', 'tests/test_saas_revamp_entry.py', "
                                     "'tests/u2_scope.py'}   # product / shared files stay out\n"
                                     "    assert '.github/workflows/public_safety_and_smoke.yml' not in later and 'tools/ci_v3_production.py' not in "
                                     'later\n'
                                     "    _flip(wt / 'tools/ci_v4_shard.py')                                                          # a drifted CI "
                                     'V4 file: cohort inexact -> no exception\n'
                                     '    with C.call_scope():\n'
                                     '        assert not C4.exact_blobs_ok(wt) and _ci_v4_own_later_paths(wt) == frozenset()\n'
                                     "    _git(wt, 'checkout', '--', 'tools/ci_v4_shard.py')\n"
                                     '    assert _ci_v4_own_later_paths(wt) == later\n'),
                                    ('def test_one_byte_in_each_owned_source_fails_closed(wt, path):\n'
                                     '    _flip(wt / path)\n'
                                     '    assert not O.exact_blobs_ok(wt)\n'
                                     '    assert not O.matches(path, (wt / path).read_bytes(), repo=wt)\n'
                                     "    _git(wt, 'checkout', '--', path)\n"
                                     '    assert O.exact_blobs_ok(wt)                                                                  # restoring '
                                     'the bytes restores validity\n',
                                     'def test_one_byte_in_each_owned_source_fails_closed(wt, path):\n'
                                     '    _flip(wt / path)\n'
                                     '    with C.call_scope():\n'
                                     '        assert not O.exact_blobs_ok(wt)\n'
                                     '    with C.call_scope():\n'
                                     '        assert not O.matches(path, (wt / path).read_bytes(), repo=wt)\n'
                                     "    _git(wt, 'checkout', '--', path)\n"
                                     '    with C.call_scope():\n'
                                     '        assert O.exact_blobs_ok(wt)                                                                  # '
                                     'restoring the bytes restores validity\n'),
                                    ('def test_modified_manifest_missing_or_extra_pin_and_wrong_base_fail_closed(wt):\n'
                                     '    manifest = wt / O.MANIFEST\n'
                                     '    original = json.loads(manifest.read_text())\n'
                                     '\n'
                                     '    def write(data):\n'
                                     "        manifest.write_text(json.dumps(data, indent=2) + '\\n')\n"
                                     "    pinned = sorted(original['source_blobs'])[0]\n"
                                     '    changes = [\n'
                                     "        lambda d: d['source_blobs'].__setitem__(pinned, '0' * 40),\n"
                                     "        lambda d: d['source_blobs'].pop(pinned),\n"
                                     "        lambda d: d['source_blobs'].__setitem__('app/library/router.py', '1' * 40),\n"
                                     "        lambda d: d['base_blobs'].__setitem__(ROUTE, '2' * 40),\n"
                                     "        lambda d: d['base_blobs'].pop(ROUTE),\n"
                                     "        lambda d: d.__setitem__('base', '3' * 40),\n"
                                     "        lambda d: d.__setitem__('base_tree', '4' * 40),\n"
                                     "        lambda d: d.__setitem__('schema_version', 'OTHER'),\n"
                                     '    ]\n'
                                     '    for change in changes:\n'
                                     '        data = json.loads(json.dumps(original))\n'
                                     '        change(data)\n'
                                     '        write(data)\n'
                                     '        assert not O.exact_blobs_ok(wt)\n'
                                     "    manifest.write_text(json.dumps(original, indent=2) + '\\n')\n"
                                     '    assert O.exact_blobs_ok(wt)\n',
                                     'def test_modified_manifest_missing_or_extra_pin_and_wrong_base_fail_closed(wt):\n'
                                     '    manifest = wt / O.MANIFEST\n'
                                     '    original = json.loads(manifest.read_text())\n'
                                     '\n'
                                     '    def write(data):\n'
                                     "        manifest.write_text(json.dumps(data, indent=2) + '\\n')\n"
                                     "    pinned = sorted(original['source_blobs'])[0]\n"
                                     '    changes = [\n'
                                     "        lambda d: d['source_blobs'].__setitem__(pinned, '0' * 40),\n"
                                     "        lambda d: d['source_blobs'].pop(pinned),\n"
                                     "        lambda d: d['source_blobs'].__setitem__('app/library/router.py', '1' * 40),\n"
                                     "        lambda d: d['base_blobs'].__setitem__(ROUTE, '2' * 40),\n"
                                     "        lambda d: d['base_blobs'].pop(ROUTE),\n"
                                     "        lambda d: d.__setitem__('base', '3' * 40),\n"
                                     "        lambda d: d.__setitem__('base_tree', '4' * 40),\n"
                                     "        lambda d: d.__setitem__('schema_version', 'OTHER'),\n"
                                     '    ]\n'
                                     '    for change in changes:\n'
                                     '        data = json.loads(json.dumps(original))\n'
                                     '        change(data)\n'
                                     '        write(data)\n'
                                     '        with C.call_scope():\n'
                                     '            assert not O.exact_blobs_ok(wt)\n'
                                     "    manifest.write_text(json.dumps(original, indent=2) + '\\n')\n"
                                     '    with C.call_scope():\n'
                                     '        assert O.exact_blobs_ok(wt)\n'),
                                    ('def test_altered_registry_hook_or_sibling_pin_fails_closed(wt):\n'
                                     "    for path in ('tests/u1_scope.py', 'tests/fin_v2_cohorts.py'):\n"
                                     '        _flip(wt / path)\n'
                                     '        assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     "        _git(wt, 'checkout', '--', path)\n"
                                     "    registry = wt / 'tests/fin_v2_cohorts.py'\n"
                                     '    registry.write_text(registry.read_text().replace("\'tests.post413_o1_scope\'", '
                                     '"\'tests.post413_o1_scope_x\'"))\n'
                                     '    assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', 'tests/fin_v2_cohorts.py')\n"
                                     '    assert O.exact_blobs_ok(wt) and C.valid(wt)\n'
                                     '    for manifest in sorted(SIBLINGS):\n'
                                     '        data = json.loads((wt / manifest).read_text())\n'
                                     "        key = 'tests/u1_scope.py'\n"
                                     "        data['source_blobs'][key] = '0' * 40\n"
                                     "        (wt / manifest).write_text(json.dumps(data, indent=2, sort_keys=True) + '\\n')\n"
                                     '        assert not C.valid(wt), manifest                                                         # a '
                                     'stale/forged sibling pin of a shared blob fails the composite\n'
                                     "        _git(wt, 'checkout', '--', manifest)\n"
                                     '    assert C.valid(wt)\n',
                                     'def test_altered_registry_hook_or_sibling_pin_fails_closed(wt):\n'
                                     "    for path in ('tests/u1_scope.py', 'tests/fin_v2_cohorts.py'):\n"
                                     '        _flip(wt / path)\n'
                                     '        with C.call_scope():\n'
                                     '            assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     "        _git(wt, 'checkout', '--', path)\n"
                                     "    registry = wt / 'tests/fin_v2_cohorts.py'\n"
                                     '    registry.write_text(registry.read_text().replace("\'tests.post413_o1_scope\'", '
                                     '"\'tests.post413_o1_scope_x\'"))\n'
                                     '    with C.call_scope():\n'
                                     '        assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', 'tests/fin_v2_cohorts.py')\n"
                                     '    with C.call_scope():\n'
                                     '        assert O.exact_blobs_ok(wt) and C.valid(wt)\n'
                                     '    for manifest in sorted(SIBLINGS):\n'
                                     '        data = json.loads((wt / manifest).read_text())\n'
                                     "        key = 'tests/u1_scope.py'\n"
                                     "        data['source_blobs'][key] = '0' * 40\n"
                                     "        (wt / manifest).write_text(json.dumps(data, indent=2, sort_keys=True) + '\\n')\n"
                                     '        with C.call_scope():\n'
                                     '            assert not C.valid(wt), manifest                                                         # a '
                                     'stale/forged sibling pin of a shared blob fails the composite\n'
                                     "        _git(wt, 'checkout', '--', manifest)\n"
                                     '    with C.call_scope():\n'
                                     '        assert C.valid(wt)\n'),
                                    ('def test_one_byte_in_the_workstream_b_route_or_service_fails_the_composite_and_restores(wt):\n'
                                     "    for path in (ROUTE, SERVICE, 'app/v2/save_all_commands.py', 'app/capex_profiles/runtime.py'):\n"
                                     '        _flip(wt / path)\n'
                                     '        assert not C.valid(wt), path\n'
                                     "        _git(wt, 'checkout', '--', path)\n"
                                     '    assert C.valid(wt)\n',
                                     'def test_one_byte_in_the_workstream_b_route_or_service_fails_the_composite_and_restores(wt):\n'
                                     "    for path in (ROUTE, SERVICE, 'app/v2/save_all_commands.py', 'app/capex_profiles/runtime.py'):\n"
                                     '        _flip(wt / path)\n'
                                     '        with C.call_scope():\n'
                                     '            assert not C.valid(wt), path\n'
                                     "        _git(wt, 'checkout', '--', path)\n"
                                     '    with C.call_scope():\n'
                                     '        assert C.valid(wt)\n'),
                                    ('def test_unauthorised_extra_source_changed_unowned_file_and_foreign_prefix_fail_closed(wt):\n'
                                     "    (wt / 'app').mkdir(exist_ok=True)\n"
                                     "    (wt / 'app' / 'untracked_new_source.py').write_text('X = 1\\n')\n"
                                     '    assert not C.valid(wt)                                                                       # untracked '
                                     'source outside every pin\n'
                                     "    _git(wt, 'clean', '-fdxq')\n"
                                     "    _flip(wt / 'app/library/router.py')                                                          # an unowned, "
                                     'historically pinned file\n'
                                     '    assert not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', 'app/library/router.py')\n"
                                     "    (wt / 'financial_engine').mkdir(exist_ok=True)\n"
                                     "    (wt / 'financial_engine' / 'unreviewed.py').write_text('X = 1\\n')\n"
                                     "    _git(wt, 'add', 'financial_engine/unreviewed.py')\n"
                                     '    assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     "    _git(wt, 'reset', '--hard', '-q')\n"
                                     "    _git(wt, 'clean', '-fdxq')\n"
                                     '    assert C.valid(wt)\n',
                                     'def test_unauthorised_extra_source_changed_unowned_file_and_foreign_prefix_fail_closed(wt):\n'
                                     "    (wt / 'app').mkdir(exist_ok=True)\n"
                                     "    (wt / 'app' / 'untracked_new_source.py').write_text('X = 1\\n')\n"
                                     '    with C.call_scope():\n'
                                     '        assert not C.valid(wt)                                                                       # '
                                     'untracked source outside every pin\n'
                                     "    _git(wt, 'clean', '-fdxq')\n"
                                     "    _flip(wt / 'app/library/router.py')                                                          # an unowned, "
                                     'historically pinned file\n'
                                     '    with C.call_scope():\n'
                                     '        assert not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', 'app/library/router.py')\n"
                                     "    (wt / 'financial_engine').mkdir(exist_ok=True)\n"
                                     "    (wt / 'financial_engine' / 'unreviewed.py').write_text('X = 1\\n')\n"
                                     "    _git(wt, 'add', 'financial_engine/unreviewed.py')\n"
                                     '    with C.call_scope():\n'
                                     '        assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     "    _git(wt, 'reset', '--hard', '-q')\n"
                                     "    _git(wt, 'clean', '-fdxq')\n"
                                     '    with C.call_scope():\n'
                                     '        assert C.valid(wt)\n'),
                                    ('def test_altered_ci_v4_workflow_or_selector_and_a_stale_historical_pin_fail_closed(wt):\n'
                                     "    for path in ('.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_select.py'):\n"
                                     '        _flip(wt / path)\n'
                                     '        assert not C.valid(wt), path\n'
                                     "        _git(wt, 'checkout', '--', path)\n"
                                     "    historical = wt / 'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json'\n"
                                     '    data = json.loads(historical.read_text())\n'
                                     "    data['source_blobs'][ROUTE] = '0' * 40\n"
                                     "    historical.write_text(json.dumps(data, indent=2, sort_keys=True) + '\\n')\n"
                                     '    assert not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', str(historical.relative_to(wt)))\n"
                                     '    assert C.valid(wt)\n',
                                     'def test_altered_ci_v4_workflow_or_selector_and_a_stale_historical_pin_fail_closed(wt):\n'
                                     "    for path in ('.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_select.py'):\n"
                                     '        _flip(wt / path)\n'
                                     '        with C.call_scope():\n'
                                     '            assert not C.valid(wt), path\n'
                                     "        _git(wt, 'checkout', '--', path)\n"
                                     "    historical = wt / 'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json'\n"
                                     '    data = json.loads(historical.read_text())\n'
                                     "    data['source_blobs'][ROUTE] = '0' * 40\n"
                                     "    historical.write_text(json.dumps(data, indent=2, sort_keys=True) + '\\n')\n"
                                     '    with C.call_scope():\n'
                                     '        assert not C.valid(wt)\n'
                                     "    _git(wt, 'checkout', '--', str(historical.relative_to(wt)))\n"
                                     '    with C.call_scope():\n'
                                     '        assert C.valid(wt)\n'),
                                    ('def '
                                     'test_a_deregistered_cohort_or_a_hook_without_it_fails_and_an_executable_or_committed_mode_change_fails(wt):\n'
                                     "    registry = wt / 'tests/fin_v2_cohorts.py'\n"
                                     '    original = registry.read_text()\n'
                                     "    registry.write_text(_without_tuple_module(original, 'COHORT_MODULES', O.__name__))\n"
                                     '    assert registry.read_text() != original and O.__name__ not in _tuple_assignment(registry.read_text(), '
                                     "'COHORT_MODULES')[1]\n"
                                     '    assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     '    registry.write_text(original)\n'
                                     "    hook = wt / 'tests/u1_scope.py'\n"
                                     '    hook_original = hook.read_text()\n'
                                     "    hook.write_text(_without_tuple_module(hook_original, 'LATER_COHORTS', O.__name__))\n"
                                     '    assert hook.read_text() != hook_original and O.__name__ not in _tuple_assignment(hook.read_text(), '
                                     "'LATER_COHORTS')[1]\n"
                                     '    assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     '    hook.write_text(hook_original)\n'
                                     '    assert O.exact_blobs_ok(wt) and C.valid(wt)\n'
                                     '    (wt / ROUTE).chmod(0o755)\n'
                                     '    assert not O.exact_blobs_ok(wt)\n'
                                     "    _git(wt, 'checkout', '--', ROUTE)\n"
                                     "    _git(wt, 'update-index', '--chmod=+x', ROUTE)\n"
                                     "    _git(wt, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mode')\n"
                                     "    assert not O.exact_blobs_ok(wt, 'HEAD')\n",
                                     'def '
                                     'test_a_deregistered_cohort_or_a_hook_without_it_fails_and_an_executable_or_committed_mode_change_fails(wt):\n'
                                     "    registry = wt / 'tests/fin_v2_cohorts.py'\n"
                                     '    original = registry.read_text()\n'
                                     "    registry.write_text(_without_tuple_module(original, 'COHORT_MODULES', O.__name__))\n"
                                     '    assert registry.read_text() != original and O.__name__ not in _tuple_assignment(registry.read_text(), '
                                     "'COHORT_MODULES')[1]\n"
                                     '    with C.call_scope():\n'
                                     '        assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     '    registry.write_text(original)\n'
                                     "    hook = wt / 'tests/u1_scope.py'\n"
                                     '    hook_original = hook.read_text()\n'
                                     "    hook.write_text(_without_tuple_module(hook_original, 'LATER_COHORTS', O.__name__))\n"
                                     '    assert hook.read_text() != hook_original and O.__name__ not in _tuple_assignment(hook.read_text(), '
                                     "'LATER_COHORTS')[1]\n"
                                     '    with C.call_scope():\n'
                                     '        assert not O.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                     '    hook.write_text(hook_original)\n'
                                     '    with C.call_scope():\n'
                                     '        assert O.exact_blobs_ok(wt) and C.valid(wt)\n'
                                     '    (wt / ROUTE).chmod(0o755)\n'
                                     '    with C.call_scope():\n'
                                     '        assert not O.exact_blobs_ok(wt)\n'
                                     "    _git(wt, 'checkout', '--', ROUTE)\n"
                                     "    _git(wt, 'update-index', '--chmod=+x', ROUTE)\n"
                                     "    _git(wt, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mode')\n"
                                     '    with C.call_scope():\n'
                                     "        assert not O.exact_blobs_ok(wt, 'HEAD')\n"),
                                    ('def test_ux_pr1_browser_fixture_shared_pin_is_exact_at_the_evaluated_ref(wt):\n'
                                     '    from tests import ux_pr1_scope as UX\n'
                                     "    path = 'tests/test_model_workspace_consolidation_browser.py'\n"
                                     '    assert path in UX_PR1_LATER_SHARED and path in UX.OWNED_PATHS and path in UX.SUPERSEDED\n'
                                     "    before = _audit_shared_sibling_pins(wt, 'HEAD')\n"
                                     '    from tests import ux_pr2b_scope as UX3\n'
                                     '    assert _ux_pr1_signed_later_pins(wt)[path] == UX3.effective_pins(wt)[path]\n'
                                     '    original = (wt / path).read_bytes()\n'
                                     '    _flip(wt / path)\n'
                                     '    with pytest.raises(AssertionError):\n'
                                     '        _audit_shared_sibling_pins(wt)\n'
                                     "    assert _audit_shared_sibling_pins(wt, 'HEAD') == before\n"
                                     '    (wt / path).write_bytes(original)\n'
                                     "    sibling = wt / 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json'\n"
                                     '    raw = sibling.read_bytes()\n'
                                     '    data = json.loads(raw)\n'
                                     "    data['source_blobs'][path] = '0' * 40\n"
                                     "    sibling.write_text(json.dumps(data, indent=2) + '\\n')\n"
                                     '    with pytest.raises(AssertionError):\n'
                                     '        _audit_shared_sibling_pins(wt)\n'
                                     '    sibling.write_bytes(raw)\n'
                                     '    assert _audit_shared_sibling_pins(wt) == before\n',
                                     'def test_ux_pr1_browser_fixture_shared_pin_is_exact_at_the_evaluated_ref(wt):\n'
                                     '    from tests import ux_pr1_scope as UX\n'
                                     "    path = 'tests/test_model_workspace_consolidation_browser.py'\n"
                                     '    assert path in UX_PR1_LATER_SHARED and path in UX.OWNED_PATHS and path in UX.SUPERSEDED\n'
                                     '    with C.call_scope():\n'
                                     "        before = _audit_shared_sibling_pins(wt, 'HEAD')\n"
                                     '    from tests import ux_pr2b_scope as UX3\n'
                                     '    with C.call_scope():\n'
                                     '        assert _ux_pr1_signed_later_pins(wt)[path] == UX3.effective_pins(wt)[path]\n'
                                     '    original = (wt / path).read_bytes()\n'
                                     '    _flip(wt / path)\n'
                                     '    with pytest.raises(AssertionError):\n'
                                     '        with C.call_scope():\n'
                                     '            _audit_shared_sibling_pins(wt)\n'
                                     '    with C.call_scope():\n'
                                     "        assert _audit_shared_sibling_pins(wt, 'HEAD') == before\n"
                                     '    (wt / path).write_bytes(original)\n'
                                     "    sibling = wt / 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json'\n"
                                     '    raw = sibling.read_bytes()\n'
                                     '    data = json.loads(raw)\n'
                                     "    data['source_blobs'][path] = '0' * 40\n"
                                     "    sibling.write_text(json.dumps(data, indent=2) + '\\n')\n"
                                     '    with pytest.raises(AssertionError):\n'
                                     '        with C.call_scope():\n'
                                     '            _audit_shared_sibling_pins(wt)\n'
                                     '    sibling.write_bytes(raw)\n'
                                     '    with C.call_scope():\n'
                                     '        assert _audit_shared_sibling_pins(wt) == before\n')],
 'tests/test_post432_l01_l02_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                          'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                          'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                         ("    if 'tests.c06_cost_workspace_scope' in C.COHORT_MODULES and C06_APPROVAL.signature_ok():\n"
                                          '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n',
                                          "    if 'tests.ci_v4_shard2_fix_scope' in C.COHORT_MODULES and S2_APPROVAL.signature_ok():\n"
                                          '        expected = S2_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.c06_cost_workspace_scope' in C.COHORT_MODULES and C06_APPROVAL.signature_ok():\n"
                                          '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n')],
 'tests/test_r02_ppa_ux_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                     'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                     'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                    ("                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope') if m in "
                                     'C.COHORT_MODULES)\n',
                                     "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                                     "'tests.ci_v4_shard2_fix_scope') if m in C.COHORT_MODULES)\n"),
                                    ('    if len(nxt) == 7 and C06_APPROVAL.signature_ok():\n'
                                     '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n',
                                     "    if 'tests.ci_v4_shard2_fix_scope' in C.COHORT_MODULES and S2_APPROVAL.signature_ok():\n"
                                     '        expected = S2_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 7 and C06_APPROVAL.signature_ok():\n'
                                     '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'),
                                    ("    assert not [p for p in changed if p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', "
                                     "'.github/', 'tools/', 'scripts/'))\n"
                                     '                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS) and not (G.signature_ok() and p in '
                                     'G.SOURCE_PATHS)]\n',
                                     '    from tests import ci_v4_shard2_fix_scope as S2\n'
                                     "    assert not [p for p in changed if p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', "
                                     "'.github/', 'tools/', 'scripts/'))\n"
                                     '                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS) and not (G.signature_ok() and p in '
                                     'G.SOURCE_PATHS)\n'
                                     '                and not (S2.signature_ok() and p in S2.CI_TOOL_PATHS)]      # exactly the literal CI V4 tool '
                                     'paths of the reviewed shard-2 fix successor\n')],
 'tests/test_r03_ppa_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                  'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                  'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                 ('        authority = C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if',
                                  '        authority = S2_APPROVAL if S2_APPROVAL.signature_ok() and p in S2_APPROVAL.HANDOFFS else C06_APPROVAL if '
                                  'C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if'),
                                 ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok())\n',
                                  '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) or '
                                  '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                  '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok())\n'),
                                 ('        if p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n',
                                  '        if p in S2_APPROVAL.HANDOFFS and S2_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == S2_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == S2_APPROVAL.manifest()["source_blobs"][p]\n'
                                  '        elif p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n'),
                                 ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_shard2_fix_scope\')", b"\'tests.ci_v4_shard2_fix_scope\', '
                                  '\'tests.fake_scope\')")),\n')],
 'tests/test_r04_ppa_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                  'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                  'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                 ('        authority = C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T\n',
                                  '        authority = S2_APPROVAL if S2_APPROVAL.signature_ok() and p in S2_APPROVAL.HANDOFFS else C06_APPROVAL if '
                                  'C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T\n'),
                                 ('or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok())\n',
                                  'or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok()) or '
                                  '(\n'
                                  '        C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, S2_APPROVAL.__name__)\n'
                                  '        and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok())\n'),
                                 ('        if p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n',
                                  '        if p in S2_APPROVAL.HANDOFFS and S2_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == S2_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == S2_APPROVAL.manifest()["source_blobs"][p]\n'
                                  '        elif p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n'),
                                 ('    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")),\n',
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")),\n'),
                                 ('    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')")),\n',
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'),
                                 ('    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", b", '
                                  '\'tests.c06_cost_workspace_scope\')")),\n',
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b", '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'),
                                 ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_shard2_fix_scope\')", b"\'tests.ci_v4_shard2_fix_scope\', '
                                  '\'tests.fake_scope\')")),\n'),
                                 ('    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b", \'tests.c06_cost_workspace_scope\')")})\n',
                                  '    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b", \'tests.c06_cost_workspace_scope\'")})\n'),
                                 ('        expected = C06_APPROVAL.effective_pins()[p] if p == "static/react/finco-react.js" and '
                                  'C06_APPROVAL.signature_ok() else blob\n',
                                  '        expected = C06_APPROVAL.effective_pins()[p] if p == "static/react/finco-react.js" and '
                                  'C06_APPROVAL.signature_ok() else blob\n')],
 'tests/test_rcux_governance.py': [('from tests import post413_r1_scope as R1\n',
                                    'from tests import post413_r1_scope as R1\n'
                                    'from tests import fin_v2_cohorts as C      # the registry call scope of the read-only verdict phases below\n'),
                                   ('def test_layer_is_a_subset_of_the_reviewed_surfaces_and_every_current_source_is_exactly_pinned():\n'
                                    '    assert all(ALLOWED.match(path) for path in LAYER), [p for p in LAYER if not ALLOWED.match(p)]\n'
                                    '    assert "static/react/finco-react.js" in LAYER\n'
                                    '    for path, blob in LAYER.items():\n'
                                    '        assert path in S.BLOBS and len(blob) == 40 and re.fullmatch(r"[0-9a-f]{40}", blob)\n'
                                    '        assert blob not in {S.BLOBS[path], S.RC_M_SUCCESSORS.get(path)}                # a NEW reviewed state, '
                                    'never a repin\n'
                                    '        later = S.WSV2_ACCEPTANCE_SUCCESSORS.get(path, S.WSV2_PRESENTATION_SUCCESSORS.get(path, '
                                    'S.WSV2_BROWSER_SUCCESSORS.get(path, blob)))  # exact later WS1 state only\n'
                                    '        from tests import wf03_lifecycle_scope as WF03\n'
                                    '        # or the exact reviewed WS-2 state; WF-04 successor lineage: the exact later state pinned by '
                                    'tests/wf04_scope.py while that cohort is valid; or the exact WF-03 state\n'
                                    '        assert (S.git_blob(SOURCES[path]) in {later, S.WSV2_SAVE_ALL_SUCCESSORS.get(path), '
                                    'S.WSV2_EDITING_SUCCESSORS.get(path)}\n'
                                    '                or WF04.presentation_successor(path, SOURCES[path]) or WF03.matches(path,SOURCES[path])\n'
                                    '                or WF06B.matches(path, SOURCES[path])                  # PR #410: the exact WF-06B successor '
                                    'state of a superseded path\n'
                                    '                or R1.matches(path, SOURCES[path])\n'
                                    '                or _authenticated_u1_workflow_successor(path, SOURCES[path])\n'
                                    '                or _authenticated_ux1_mvp_successor(path, SOURCES[path])\n'
                                    '                or PR3.matches(path, SOURCES[path]))                    # post-#413: the exact state pinned by '
                                    'the closed R1 cohort (role file: one added wrapper)\n'
                                    '    assert S.violations(SOURCES) == [] and S.current_mutation_successor_valid()\n',
                                    'def test_layer_is_a_subset_of_the_reviewed_surfaces_and_every_current_source_is_exactly_pinned():\n'
                                    '    with C.call_scope():\n'
                                    '        assert all(ALLOWED.match(path) for path in LAYER), [p for p in LAYER if not ALLOWED.match(p)]\n'
                                    '        assert "static/react/finco-react.js" in LAYER\n'
                                    '        for path, blob in LAYER.items():\n'
                                    '            assert path in S.BLOBS and len(blob) == 40 and re.fullmatch(r"[0-9a-f]{40}", blob)\n'
                                    '            assert blob not in {S.BLOBS[path], S.RC_M_SUCCESSORS.get(path)}                # a NEW reviewed '
                                    'state, never a repin\n'
                                    '            later = S.WSV2_ACCEPTANCE_SUCCESSORS.get(path, S.WSV2_PRESENTATION_SUCCESSORS.get(path, '
                                    'S.WSV2_BROWSER_SUCCESSORS.get(path, blob)))  # exact later WS1 state only\n'
                                    '            from tests import wf03_lifecycle_scope as WF03\n'
                                    '            # or the exact reviewed WS-2 state; WF-04 successor lineage: the exact later state pinned by '
                                    'tests/wf04_scope.py while that cohort is valid; or the exact WF-03 state\n'
                                    '            assert (S.git_blob(SOURCES[path]) in {later, S.WSV2_SAVE_ALL_SUCCESSORS.get(path), '
                                    'S.WSV2_EDITING_SUCCESSORS.get(path)}\n'
                                    '                    or WF04.presentation_successor(path, SOURCES[path]) or WF03.matches(path,SOURCES[path])\n'
                                    '                    or WF06B.matches(path, SOURCES[path])                  # PR #410: the exact WF-06B '
                                    'successor state of a superseded path\n'
                                    '                    or R1.matches(path, SOURCES[path])\n'
                                    '                    or _authenticated_u1_workflow_successor(path, SOURCES[path])\n'
                                    '                    or _authenticated_ux1_mvp_successor(path, SOURCES[path])\n'
                                    '                    or PR3.matches(path, SOURCES[path]))                    # post-#413: the exact state pinned '
                                    'by the closed R1 cohort (role file: one added wrapper)\n'
                                    '        assert S.violations(SOURCES) == [] and S.current_mutation_successor_valid()\n'),
                                   ('def test_the_workspace_router_changes_only_by_the_one_rcux_include_and_reviewed_wording():\n'
                                    '    source = SOURCES["app/v2/react_workspace_router.py"]\n'
                                    '    tail = source[source.index("# ───────────────────────────── RC-UX: React adapters"):]\n'
                                    '    assert re.findall(r"^router\\.include_router\\((\\w+)\\)$", tail, flags=re.M) == ["_rcux_router"]\n'
                                    '    assert re.findall(r"^from app\\.v2\\.(\\w+) import router as (\\w+)", tail, flags=re.M) == [("react_rcux", '
                                    '"_rcux_router")]\n'
                                    '    rebuilt = _git("show", f"{BASE}:app/v2/react_workspace_router.py")\n'
                                    '    for old, new in ROUTER_WORDING:\n'
                                    '        assert rebuilt.count(old) == 1, old\n'
                                    '        rebuilt = rebuilt.replace(old, new)\n'
                                    '    expected = rebuilt.rstrip("\\n") + "\\n\\n\\n" + tail.rstrip("\\n") + "\\n"\n'
                                    '    from tests import fin_v2_wsv2_scope as WS2\n'
                                    '    assert source == expected or WS2.matches("app/v2/react_workspace_router.py", source.encode())   # or the '
                                    'Owner-approved WS-2 exact blob\n',
                                    'def test_the_workspace_router_changes_only_by_the_one_rcux_include_and_reviewed_wording():\n'
                                    '    with C.call_scope():\n'
                                    '        source = SOURCES["app/v2/react_workspace_router.py"]\n'
                                    '        tail = source[source.index("# ───────────────────────────── RC-UX: React adapters"):]\n'
                                    '        assert re.findall(r"^router\\.include_router\\((\\w+)\\)$", tail, flags=re.M) == ["_rcux_router"]\n'
                                    '        assert re.findall(r"^from app\\.v2\\.(\\w+) import router as (\\w+)", tail, flags=re.M) == '
                                    '[("react_rcux", "_rcux_router")]\n'
                                    '        rebuilt = _git("show", f"{BASE}:app/v2/react_workspace_router.py")\n'
                                    '        for old, new in ROUTER_WORDING:\n'
                                    '            assert rebuilt.count(old) == 1, old\n'
                                    '            rebuilt = rebuilt.replace(old, new)\n'
                                    '        expected = rebuilt.rstrip("\\n") + "\\n\\n\\n" + tail.rstrip("\\n") + "\\n"\n'
                                    '        from tests import fin_v2_wsv2_scope as WS2\n'
                                    '        assert source == expected or WS2.matches("app/v2/react_workspace_router.py", source.encode())   # or '
                                    'the Owner-approved WS-2 exact blob\n'),
                                   ('def test_the_rcux_changes_touch_no_protected_financial_security_or_ci_path():\n'
                                    '    try:\n'
                                    '        changed = set(_git("diff", "--name-only", MAIN, "HEAD").split())\n'
                                    '        changed |= set(_git("diff", "--name-only").split()) | set(_git("diff", "--name-only", '
                                    '"--cached").split())\n'
                                    '    except subprocess.CalledProcessError:\n'
                                    '        pytest.skip("baseline commit not available in this checkout")\n'
                                    '    forbidden = ("app/input_adapter.py", "app/api/project_runner.py", "app/runtime/model_execution.py", '
                                    '"app/v2/router.py",\n'
                                    '                 "app/v2/returns_projection.py", "app/services/run_intent_service.py", '
                                    '"app/persistence/run_intent_repository.py",\n'
                                    '                 "app/persistence/run_history_repository.py", "app/persistence/projects_repository.py", '
                                    '"app/services/run_service.py",\n'
                                    '                 "app/services/goal_seek.py", "app/services/sensitivity_matrix.py", "main_web.py",\n'
                                    '                 "app/workbook/mutation_csrf.py", "app/workbook/financing_csrf.py")\n'
                                    '    prefixes = ("financial_engine/", "finco_core/", "domain/", ".github/", "app/workbook/", '
                                    '"app/capex_profiles/", "app/export/")\n'
                                    '    hits = [p for p in changed if p in forbidden or p.startswith(prefixes)]\n'
                                    '    # The ONE later, separately governed exception: the PR #394 correction cohort pins the exact blob of '
                                    'app/services/run_intent_service.py\n'
                                    '    # (tests/fin_v2_pr394_corr_scope.py).  Only that exact path with exactly that blob is attributed to it - '
                                    'never a prefix or another forbidden path.\n'
                                    '    from tests import fin_v2_pr394_corr_scope as PR394\n'
                                    '    hits = [p for p in hits if not (p == "app/services/run_intent_service.py" and PR394.matches(p, (S.ROOT / '
                                    'p).read_bytes()))]\n'
                                    '    # Two later, separately governed exceptions: the Owner-approved WS-2 Save All cohort '
                                    '(tests/fin_v2_wsv2_scope.py) pins the exact blob of each of its own\n'
                                    '    # paths; the Owner-authorised WF-04 cohort (tests/wf04_scope.py) owns exactly the two workbook paths below '
                                    '(the registered contractual-DSCR inputs and their\n'
                                    '    # pure Run-terms module). Only that exact path with exactly that blob is attributed to it.\n'
                                    '    from tests import fin_v2_wsv2_scope as WS2\n'
                                    '    from tests import wf04_scope as WF04\n'
                                    '    hits = [p for p in hits if not (p in WS2.OWNED_PATHS and WS2.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '    hits = [p for p in hits if not (p in ("app/workbook/registry.py", "app/workbook/dscr_contract_terms.py")\n'
                                    '                                    and WF04.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '    # Third: the Owner-approved Correction C timeout hunk in exactly one workflow (tests/wf04_scope.py admits '
                                    'the path only at the exact approved-main\n'
                                    '    # bytes plus the literal hunk, while the whole cohort is valid); every other .github/ path is still a hit.\n'
                                    '    hits = [p for p in hits if not (p == WF04.WORKFLOW_PATH and WF04.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '    # Fourth: the Owner-approved WF-03 lifecycle cohort (tests/wf03_lifecycle_scope.py) owns exactly these four '
                                    'paths (archive / restore fences, request\n'
                                    '    # admission, creation completeness, demo-provisioning prefixes); only that exact path with exactly that '
                                    'pinned blob is attributed to it.\n'
                                    '    from tests import wf03_lifecycle_scope as WF03\n'
                                    '    WF03_PATHS = ("main_web.py", "app/v2/router.py", "app/persistence/projects_repository.py", '
                                    '"app/services/run_service.py")\n'
                                    '    hits = [p for p in hits if not (p in WF03_PATHS and WF03.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '    # Fifth: the three Owner-approved CI workflows the WF-03 cohort owns (Correction E budgets + the '
                                    'run-attempt artifact integrity repair): only the\n'
                                    '    # exact path set WF03.CI_TIMEOUT_WORKFLOWS, each at exactly its WF-03-pinned blob. No other .github/ path '
                                    'and no other byte is admitted.\n'
                                    '    hits = [p for p in hits if not (p in WF03.CI_TIMEOUT_WORKFLOWS and WF03.matches(p, (S.ROOT / '
                                    'p).read_bytes()))]\n'
                                    '    # Sixth: the Owner-approved CI V4 cohort (tests/ci_v4_scope.py, CI policy 2026-11-04) owns exactly its '
                                    'literal CI_PATHS (new ci_v4_* workflows and\n'
                                    "    # tools only); admitted only through U1's bounded later-CI hook while that cohort is registered and exact. "
                                    'No existing workflow or tool is admitted.\n'
                                    '    from tests import u1_scope as U1\n'
                                    '    hits = [p for p in hits if not U1._later_ci_owns(p, S.ROOT, None)]\n'
                                    '    # Seventh: the closed Workstream-B cohort (tests/post413_o1_scope.py; O1 / G7 / G-U2-1 / D7, every '
                                    'behaviour off by default or additive, no Owner decision\n'
                                    '    # approved here) owns a literal, finite path set. Only a path of that set at exactly its pinned blob, while '
                                    'the cohort and the composite are valid, is attributed to it.\n'
                                    '    from tests import post413_o1_scope as O1\n'
                                    '    hits = [p for p in hits if not (p in O1.OWNED_PATHS and O1.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '    assert hits == [], hits\n'
                                    '    assert not O1.matches("app/capex_profiles/binding.py", (S.ROOT / '
                                    '"app/capex_profiles/binding.py").read_bytes())      # a sibling file the cohort does not own\n'
                                    '    assert not O1.matches("app/v2/router.py", b"x = '
                                    '1\\n")                                                                 # an owned path at foreign bytes\n'
                                    '    for stranger in (".github/workflows/public_safety_and_smoke.yml", ".github/workflows/ci_v4_unlisted.yml", '
                                    '"tools/ci_v3_production.py"):\n'
                                    '        assert not U1._later_ci_owns(stranger, S.ROOT, None), stranger\n'
                                    '    golden = [p for p in changed if re.search(r"golden|baseline_snapshot|expected_outputs", p)]\n'
                                    '    assert golden == [], golden\n',
                                    'def test_the_rcux_changes_touch_no_protected_financial_security_or_ci_path():\n'
                                    '    with C.call_scope():\n'
                                    '        try:\n'
                                    '            changed = set(_git("diff", "--name-only", MAIN, "HEAD").split())\n'
                                    '            changed |= set(_git("diff", "--name-only").split()) | set(_git("diff", "--name-only", '
                                    '"--cached").split())\n'
                                    '        except subprocess.CalledProcessError:\n'
                                    '            pytest.skip("baseline commit not available in this checkout")\n'
                                    '        forbidden = ("app/input_adapter.py", "app/api/project_runner.py", "app/runtime/model_execution.py", '
                                    '"app/v2/router.py",\n'
                                    '                     "app/v2/returns_projection.py", "app/services/run_intent_service.py", '
                                    '"app/persistence/run_intent_repository.py",\n'
                                    '                     "app/persistence/run_history_repository.py", "app/persistence/projects_repository.py", '
                                    '"app/services/run_service.py",\n'
                                    '                     "app/services/goal_seek.py", "app/services/sensitivity_matrix.py", "main_web.py",\n'
                                    '                     "app/workbook/mutation_csrf.py", "app/workbook/financing_csrf.py")\n'
                                    '        prefixes = ("financial_engine/", "finco_core/", "domain/", ".github/", "app/workbook/", '
                                    '"app/capex_profiles/", "app/export/")\n'
                                    '        hits = [p for p in changed if p in forbidden or p.startswith(prefixes)]\n'
                                    '        # The ONE later, separately governed exception: the PR #394 correction cohort pins the exact blob of '
                                    'app/services/run_intent_service.py\n'
                                    '        # (tests/fin_v2_pr394_corr_scope.py).  Only that exact path with exactly that blob is attributed to it '
                                    '- never a prefix or another forbidden path.\n'
                                    '        from tests import fin_v2_pr394_corr_scope as PR394\n'
                                    '        hits = [p for p in hits if not (p == "app/services/run_intent_service.py" and PR394.matches(p, (S.ROOT '
                                    '/ p).read_bytes()))]\n'
                                    '        # Two later, separately governed exceptions: the Owner-approved WS-2 Save All cohort '
                                    '(tests/fin_v2_wsv2_scope.py) pins the exact blob of each of its own\n'
                                    '        # paths; the Owner-authorised WF-04 cohort (tests/wf04_scope.py) owns exactly the two workbook paths '
                                    'below (the registered contractual-DSCR inputs and their\n'
                                    '        # pure Run-terms module). Only that exact path with exactly that blob is attributed to it.\n'
                                    '        from tests import fin_v2_wsv2_scope as WS2\n'
                                    '        from tests import wf04_scope as WF04\n'
                                    '        hits = [p for p in hits if not (p in WS2.OWNED_PATHS and WS2.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '        hits = [p for p in hits if not (p in ("app/workbook/registry.py", '
                                    '"app/workbook/dscr_contract_terms.py")\n'
                                    '                                        and WF04.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '        # Third: the Owner-approved Correction C timeout hunk in exactly one workflow (tests/wf04_scope.py '
                                    'admits the path only at the exact approved-main\n'
                                    '        # bytes plus the literal hunk, while the whole cohort is valid); every other .github/ path is still a '
                                    'hit.\n'
                                    '        hits = [p for p in hits if not (p == WF04.WORKFLOW_PATH and WF04.matches(p, (S.ROOT / '
                                    'p).read_bytes()))]\n'
                                    '        # Fourth: the Owner-approved WF-03 lifecycle cohort (tests/wf03_lifecycle_scope.py) owns exactly these '
                                    'four paths (archive / restore fences, request\n'
                                    '        # admission, creation completeness, demo-provisioning prefixes); only that exact path with exactly that '
                                    'pinned blob is attributed to it.\n'
                                    '        from tests import wf03_lifecycle_scope as WF03\n'
                                    '        WF03_PATHS = ("main_web.py", "app/v2/router.py", "app/persistence/projects_repository.py", '
                                    '"app/services/run_service.py")\n'
                                    '        hits = [p for p in hits if not (p in WF03_PATHS and WF03.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '        # Fifth: the three Owner-approved CI workflows the WF-03 cohort owns (Correction E budgets + the '
                                    'run-attempt artifact integrity repair): only the\n'
                                    '        # exact path set WF03.CI_TIMEOUT_WORKFLOWS, each at exactly its WF-03-pinned blob. No other .github/ '
                                    'path and no other byte is admitted.\n'
                                    '        hits = [p for p in hits if not (p in WF03.CI_TIMEOUT_WORKFLOWS and WF03.matches(p, (S.ROOT / '
                                    'p).read_bytes()))]\n'
                                    '        # Sixth: the Owner-approved CI V4 cohort (tests/ci_v4_scope.py, CI policy 2026-11-04) owns exactly its '
                                    'literal CI_PATHS (new ci_v4_* workflows and\n'
                                    "        # tools only); admitted only through U1's bounded later-CI hook while that cohort is registered and "
                                    'exact. No existing workflow or tool is admitted.\n'
                                    '        from tests import u1_scope as U1\n'
                                    '        hits = [p for p in hits if not U1._later_ci_owns(p, S.ROOT, None)]\n'
                                    '        # Seventh: the closed Workstream-B cohort (tests/post413_o1_scope.py; O1 / G7 / G-U2-1 / D7, every '
                                    'behaviour off by default or additive, no Owner decision\n'
                                    '        # approved here) owns a literal, finite path set. Only a path of that set at exactly its pinned blob, '
                                    'while the cohort and the composite are valid, is attributed to it.\n'
                                    '        from tests import post413_o1_scope as O1\n'
                                    '        hits = [p for p in hits if not (p in O1.OWNED_PATHS and O1.matches(p, (S.ROOT / p).read_bytes()))]\n'
                                    '        assert hits == [], hits\n'
                                    '        assert not O1.matches("app/capex_profiles/binding.py", (S.ROOT / '
                                    '"app/capex_profiles/binding.py").read_bytes())      # a sibling file the cohort does not own\n'
                                    '        assert not O1.matches("app/v2/router.py", b"x = '
                                    '1\\n")                                                                 # an owned path at foreign bytes\n'
                                    '        for stranger in (".github/workflows/public_safety_and_smoke.yml", '
                                    '".github/workflows/ci_v4_unlisted.yml", "tools/ci_v3_production.py"):\n'
                                    '            assert not U1._later_ci_owns(stranger, S.ROOT, None), stranger\n'
                                    '        golden = [p for p in changed if re.search(r"golden|baseline_snapshot|expected_outputs", p)]\n'
                                    '        assert golden == [], golden\n'),
                                   ('def test_the_wf03_ci_workflow_successor_is_exact_path_and_exact_blob_only():\n'
                                    '    """Negatives for the RC-UX CI-workflow successor: exactly the three WF-03 workflows at their exact pins; no '
                                    'other .github/ path, no other byte."""\n'
                                    '    from tests import wf03_lifecycle_scope as WF03\n'
                                    '    assert WF03.CI_TIMEOUT_WORKFLOWS == {".github/workflows/ci_public_job.yml", '
                                    '".github/workflows/ci_v3_required_job.yml",\n'
                                    '                                         ".github/workflows/public_safety_and_smoke.yml"}\n'
                                    '    for path in sorted(WF03.CI_TIMEOUT_WORKFLOWS):\n'
                                    '        raw = (S.ROOT / path).read_bytes()\n'
                                    '        assert WF03.matches(path, raw) and not WF03.matches(path, raw + b"\\n") and not WF03.matches(path, '
                                    'raw.replace(b"timeout-minutes", b"timeout-minutez", 1))\n'
                                    '    for other in (".github/workflows/protocol_ui_browser.yml", ".github/workflows/finval_f01_acceptance.yml", '
                                    '".github/workflows/new_unreviewed.yml"):\n'
                                    '        assert other not in WF03.CI_TIMEOUT_WORKFLOWS and not WF03.allowed_path(other)\n',
                                    'def test_the_wf03_ci_workflow_successor_is_exact_path_and_exact_blob_only():\n'
                                    '    """Negatives for the RC-UX CI-workflow successor: exactly the three WF-03 workflows at their exact pins; no '
                                    'other .github/ path, no other byte."""\n'
                                    '    with C.call_scope():\n'
                                    '        from tests import wf03_lifecycle_scope as WF03\n'
                                    '        assert WF03.CI_TIMEOUT_WORKFLOWS == {".github/workflows/ci_public_job.yml", '
                                    '".github/workflows/ci_v3_required_job.yml",\n'
                                    '                                             ".github/workflows/public_safety_and_smoke.yml"}\n'
                                    '        for path in sorted(WF03.CI_TIMEOUT_WORKFLOWS):\n'
                                    '            raw = (S.ROOT / path).read_bytes()\n'
                                    '            assert WF03.matches(path, raw) and not WF03.matches(path, raw + b"\\n") and not WF03.matches(path, '
                                    'raw.replace(b"timeout-minutes", b"timeout-minutez", 1))\n'
                                    '        for other in (".github/workflows/protocol_ui_browser.yml", '
                                    '".github/workflows/finval_f01_acceptance.yml", ".github/workflows/new_unreviewed.yml"):\n'
                                    '            assert other not in WF03.CI_TIMEOUT_WORKFLOWS and not WF03.allowed_path(other)\n')],
 'tests/test_t01e_remediation_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                           'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                           'from tests import ci_v4_shard2_fix_scope as S2_APPROVAL\n'),
                                          ('        if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n',
                                           '        if S2_APPROVAL.signature_ok() and p in S2_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == S2_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'),
                                          ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                           'C06_APPROVAL.signature_ok())\n',
                                           '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                           'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                           'S2_APPROVAL.__name__)\n'
                                           '            and C06_APPROVAL.signature_ok() and S2_APPROVAL.signature_ok())\n'),
                                          ('        if p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n',
                                           '        if p in S2_APPROVAL.HANDOFFS and S2_APPROVAL.signature_ok():\n'
                                           '            assert (ROOT / p).read_bytes() == S2_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == S2_APPROVAL.manifest()["source_blobs"][p]\n'
                                           '        elif p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n'),
                                          ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                           'b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_shard2_fix_scope\')", '
                                           'b"\'tests.ci_v4_shard2_fix_scope\', \'tests.fake_scope\')")),\n')],
 'tests/test_u1_scope.py': [('def test_positive_cohort_is_exact_registered_and_closed():\n'
                             '    assert U.exact_blobs_ok() and U.valid() and C.valid() and W.exact_blobs_ok()\n'
                             '    assert U.__name__ in C.COHORT_MODULES and U in C.cohorts() and U.protected_blobs() == {}\n'
                             '    data = U.manifest()\n'
                             "    assert set(data['source_blobs']) == U.OWNED_PATHS - {U.MANIFEST} and set(data['base_blobs']) == U.SUPERSEDED\n"
                             "    assert all('*' not in p and not p.endswith('/') for p in U.OWNED_PATHS)\n"
                             '    assert not any(p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS for p in U.OWNED_PATHS)\n'
                             "    for stranger in ('app/library/router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py', "
                             "'financial_engine/x.py', '.github/workflows/ci.yml'):\n"
                             '        assert not U.allowed_path(stranger) and not U.matches(stranger) and not W.allowed_path(stranger)\n'
                             "    for owned in ('app/cost_line_ledger/opex_bases.py', 'static/react/finco-react.js', 'tests/u1_scope.py'):\n"
                             '        assert U.matches(owned) and U.allowed_path(owned) and W.allowed_path(owned)\n'
                             "    path = 'static/react/finco-react.js'\n"
                             "    assert U.supersedes(path, data['source_blobs'][path]) and not U.supersedes(path, '0' * 40) and W.supersedes(path, "
                             "data['source_blobs'][path])\n"
                             "    assert not U.supersedes('app/cost_line_ledger/opex_bases.py', "
                             "data['source_blobs']['app/cost_line_ledger/opex_bases.py'])   # new at U1: nothing to supersede\n",
                             'def test_positive_cohort_is_exact_registered_and_closed():\n'
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok() and U.valid() and C.valid() and W.exact_blobs_ok()\n'
                             '        assert U.__name__ in C.COHORT_MODULES and U in C.cohorts() and U.protected_blobs() == {}\n'
                             '        data = U.manifest()\n'
                             "        assert set(data['source_blobs']) == U.OWNED_PATHS - {U.MANIFEST} and set(data['base_blobs']) == U.SUPERSEDED\n"
                             "        assert all('*' not in p and not p.endswith('/') for p in U.OWNED_PATHS)\n"
                             '        assert not any(p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS for p in U.OWNED_PATHS)\n'
                             "        for stranger in ('app/library/router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py', "
                             "'financial_engine/x.py', '.github/workflows/ci.yml'):\n"
                             '            assert not U.allowed_path(stranger) and not U.matches(stranger) and not W.allowed_path(stranger)\n'
                             "        for owned in ('app/cost_line_ledger/opex_bases.py', 'static/react/finco-react.js', 'tests/u1_scope.py'):\n"
                             '            assert U.matches(owned) and U.allowed_path(owned) and W.allowed_path(owned)\n'
                             "        path = 'static/react/finco-react.js'\n"
                             "        assert U.supersedes(path, data['source_blobs'][path]) and not U.supersedes(path, '0' * 40) and "
                             "W.supersedes(path, data['source_blobs'][path])\n"
                             "        assert not U.supersedes('app/cost_line_ledger/opex_bases.py', "
                             "data['source_blobs']['app/cost_line_ledger/opex_bases.py'])   # new at U1: nothing to supersede\n"),
                            ('def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):\n'
                             '    assert U.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             '    assert not U.exact_blobs_ok(wt) and not U.matches(path, (wt / path).read_bytes(), repo=wt)\n'
                             '    assert not C.valid(wt) and not W.exact_blobs_ok(wt)\n',
                             'def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):\n'
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not U.matches(path, (wt / path).read_bytes(), repo=wt)\n'
                             '    with C.call_scope():\n'
                             '        assert not C.valid(wt) and not W.exact_blobs_ok(wt)\n'),
                            ('def test_missing_owned_path_fails_closed(path, wt):\n'
                             '    (wt / path).unlink()\n'
                             '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n',
                             'def test_missing_owned_path_fails_closed(path, wt):\n'
                             '    (wt / path).unlink()\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                            ('def test_manifest_forgery_is_refused(kind, wt):\n'
                             '    mpath = wt / U.MANIFEST\n'
                             '    d = json.loads(mpath.read_text())\n'
                             "    if kind == 'extra-path':\n"
                             "        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40\n"
                             "    elif kind == 'missing-pin':\n"
                             "        d['source_blobs'].pop('static/react/finco-react.js')\n"
                             "    elif kind == 'wrong-base':\n"
                             "        d['base'] = '0' * 40\n"
                             "    elif kind == 'wrong-tree':\n"
                             "        d['base_tree'] = '0' * 40\n"
                             "    elif kind == 'wrong-blob':\n"
                             "        d['source_blobs']['app/cost_line_ledger/opex_bases.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-pins':\n"
                             "        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'\n"
                             "        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]\n"
                             "    elif kind == 'drop-base-blobs':\n"
                             "        d['base_blobs'].pop('app/v2/react_workspace_router.py')\n"
                             "    elif kind == 'wrong-base-blob':\n"
                             "        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-schema':\n"
                             "        d['schema_version'] = 'WF06B_A_PLUS_EXACT_SOURCE_V1'\n"
                             "    elif kind == 'alias-pin':\n"
                             "        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']\n"
                             "    elif kind == 'wrong-integration':\n"
                             "        d['integration'] = '0' * 40\n"
                             "    elif kind == 'wrong-integration-tree':\n"
                             "        d['integration_tree'] = '0' * 40\n"
                             "    elif kind == 'drop-integration-blobs':\n"
                             "        d['integration_blobs'].pop('tests/wf06b_scope.py')\n"
                             "    elif kind == 'wrong-integration-blob':\n"
                             "        d['integration_blobs']['tests/wf06b_scope.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-integration-blobs':\n"
                             "        a, b = 'tests/wf06b_scope.py', 'tests/test_wf06b_scope.py'\n"
                             "        d['integration_blobs'][a], d['integration_blobs'][b] = d['integration_blobs'][b], d['integration_blobs'][a]\n"
                             "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                             '    assert not U.exact_blobs_ok(wt) and not C.valid(wt) and not W.exact_blobs_ok(wt)\n',
                             'def test_manifest_forgery_is_refused(kind, wt):\n'
                             '    mpath = wt / U.MANIFEST\n'
                             '    d = json.loads(mpath.read_text())\n'
                             "    if kind == 'extra-path':\n"
                             "        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40\n"
                             "    elif kind == 'missing-pin':\n"
                             "        d['source_blobs'].pop('static/react/finco-react.js')\n"
                             "    elif kind == 'wrong-base':\n"
                             "        d['base'] = '0' * 40\n"
                             "    elif kind == 'wrong-tree':\n"
                             "        d['base_tree'] = '0' * 40\n"
                             "    elif kind == 'wrong-blob':\n"
                             "        d['source_blobs']['app/cost_line_ledger/opex_bases.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-pins':\n"
                             "        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'\n"
                             "        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]\n"
                             "    elif kind == 'drop-base-blobs':\n"
                             "        d['base_blobs'].pop('app/v2/react_workspace_router.py')\n"
                             "    elif kind == 'wrong-base-blob':\n"
                             "        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-schema':\n"
                             "        d['schema_version'] = 'WF06B_A_PLUS_EXACT_SOURCE_V1'\n"
                             "    elif kind == 'alias-pin':\n"
                             "        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']\n"
                             "    elif kind == 'wrong-integration':\n"
                             "        d['integration'] = '0' * 40\n"
                             "    elif kind == 'wrong-integration-tree':\n"
                             "        d['integration_tree'] = '0' * 40\n"
                             "    elif kind == 'drop-integration-blobs':\n"
                             "        d['integration_blobs'].pop('tests/wf06b_scope.py')\n"
                             "    elif kind == 'wrong-integration-blob':\n"
                             "        d['integration_blobs']['tests/wf06b_scope.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-integration-blobs':\n"
                             "        a, b = 'tests/wf06b_scope.py', 'tests/test_wf06b_scope.py'\n"
                             "        d['integration_blobs'][a], d['integration_blobs'][b] = d['integration_blobs'][b], d['integration_blobs'][a]\n"
                             "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not C.valid(wt) and not W.exact_blobs_ok(wt)\n'),
                            ('def test_extra_tracked_extra_untracked_and_executable_paths_fail_closed(wt):\n'
                             "    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\\n')\n"
                             '    assert not U.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')\n"
                             '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'reset', '-q')\n"
                             "    (wt / 'frontend/src/app/Sneaky.tsx').unlink()\n"
                             '    assert U.exact_blobs_ok(wt)\n'
                             "    run = wt / 'app/cost_line_ledger/run.sh'\n"
                             "    run.write_text('#!/bin/sh\\n')\n"
                             '    run.chmod(0o755)\n'
                             '    assert not U.exact_blobs_ok(wt)\n'
                             '    run.unlink()\n'
                             "    owned = wt / 'app/cost_line_ledger/opex_bases.py'\n"
                             '    owned.chmod(0o755)\n'
                             '    assert not U.exact_blobs_ok(wt)\n'
                             '    owned.chmod(0o644)\n'
                             '    assert U.exact_blobs_ok(wt)\n',
                             'def test_extra_tracked_extra_untracked_and_executable_paths_fail_closed(wt):\n'
                             "    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')\n"
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'reset', '-q')\n"
                             "    (wt / 'frontend/src/app/Sneaky.tsx').unlink()\n"
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok(wt)\n'
                             "    run = wt / 'app/cost_line_ledger/run.sh'\n"
                             "    run.write_text('#!/bin/sh\\n')\n"
                             '    run.chmod(0o755)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt)\n'
                             '    run.unlink()\n'
                             "    owned = wt / 'app/cost_line_ledger/opex_bases.py'\n"
                             '    owned.chmod(0o755)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt)\n'
                             '    owned.chmod(0o644)\n'
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok(wt)\n'),
                            ('def test_protected_and_unowned_code_modified_after_signing_fails_closed(path, wt):\n'
                             '    assert U.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             '    assert not U.allowed_path(path)\n',
                             'def test_protected_and_unowned_code_modified_after_signing_fails_closed(path, wt):\n'
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.allowed_path(path)\n'),
                            ('def test_the_410_manifest_and_unlisted_predecessor_files_cannot_be_bypassed(path, wt):\n'
                             '    _flip(wt / path)\n'
                             '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n',
                             'def test_the_410_manifest_and_unlisted_predecessor_files_cannot_be_bypassed(path, wt):\n'
                             '    _flip(wt / path)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                            ('def test_wf06b_follows_u1_only_for_the_exact_pin_and_only_the_recorded_historical_blob(wt):\n'
                             "    path = 'frontend/src/app/workflow/CostLineManager.tsx'          # superseded by U1 and by no later cohort (a later "
                             "cohort's pin is the later cohort's own)\n"
                             '    assert W.exact_blobs_ok(wt)\n'
                             '    # forge the WF-06B pin: it no longer equals the historical blob U1 re-verified against git at its BASE -> WF-06B '
                             'must NOT follow U1\n'
                             '    mpath = wt / W.MANIFEST\n'
                             '    d = json.loads(mpath.read_text())\n'
                             "    d['source_blobs'][path] = '1' * 40\n"
                             "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                             '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'checkout', '--', W.MANIFEST)\n"
                             '    assert W.exact_blobs_ok(wt)\n'
                             '    # forge the U1 pin: U1 itself refuses, and WF-06B stops following it\n'
                             '    upath = wt / U.MANIFEST\n'
                             '    u = json.loads(upath.read_text())\n'
                             "    u['source_blobs'][path] = '2' * 40\n"
                             "    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\\n')\n"
                             '    assert not U.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not C.valid(wt)\n',
                             'def test_wf06b_follows_u1_only_for_the_exact_pin_and_only_the_recorded_historical_blob(wt):\n'
                             "    path = 'frontend/src/app/workflow/CostLineManager.tsx'          # superseded by U1 and by no later cohort (a later "
                             "cohort's pin is the later cohort's own)\n"
                             '    with C.call_scope():\n'
                             '        assert W.exact_blobs_ok(wt)\n'
                             '    # forge the WF-06B pin: it no longer equals the historical blob U1 re-verified against git at its BASE -> WF-06B '
                             'must NOT follow U1\n'
                             '    mpath = wt / W.MANIFEST\n'
                             '    d = json.loads(mpath.read_text())\n'
                             "    d['source_blobs'][path] = '1' * 40\n"
                             "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'checkout', '--', W.MANIFEST)\n"
                             '    with C.call_scope():\n'
                             '        assert W.exact_blobs_ok(wt)\n'
                             '    # forge the U1 pin: U1 itself refuses, and WF-06B stops following it\n'
                             '    upath = wt / U.MANIFEST\n'
                             '    u = json.loads(upath.read_text())\n'
                             "    u['source_blobs'][path] = '2' * 40\n"
                             "    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                            ('def test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort(wt):\n'
                             '    from tests import wsv2_core_scope as CORE\n'
                             '    assert CORE.exact_blobs_ok(wt)\n'
                             "    _flip(wt / 'static/react/finco-react.js')\n"
                             '    assert not U.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)\n',
                             'def test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort(wt):\n'
                             '    from tests import wsv2_core_scope as CORE\n'
                             '    with C.call_scope():\n'
                             '        assert CORE.exact_blobs_ok(wt)\n'
                             "    _flip(wt / 'static/react/finco-react.js')\n"
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)\n'),
                            ('def test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref(wt):\n'
                             "    head = _git(wt, 'rev-parse', 'HEAD').strip()\n"
                             '    assert U.exact_blobs_ok(wt, head)\n'
                             '    assert not U.exact_blobs_ok(wt, U.BASE)\n'
                             "    _git(wt, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-qm', 'noop')\n"
                             "    assert U.exact_blobs_ok(wt, 'HEAD')\n",
                             'def test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref(wt):\n'
                             "    head = _git(wt, 'rev-parse', 'HEAD').strip()\n"
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok(wt, head)\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt, U.BASE)\n'
                             "    _git(wt, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-qm', 'noop')\n"
                             '    with C.call_scope():\n'
                             "        assert U.exact_blobs_ok(wt, 'HEAD')\n"),
                            ('def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n'
                             '    later_superseded = set().union(*(set(m.SUPERSEDED) for m in U._later_modules()))\n'
                             '    for path in U.OWNED_PATHS - U.SUPERSEDED - {U.MANIFEST} - later_superseded:\n'
                             '        raw = (U.ROOT / path).read_bytes()\n'
                             "        assert not U.supersedes(path, U._blob(raw)) and not W.supersedes(path, U._blob(raw + b'\\n')), path\n",
                             'def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n'
                             '    with C.call_scope():\n'
                             '        later_superseded = set().union(*(set(m.SUPERSEDED) for m in U._later_modules()))\n'
                             '        for path in U.OWNED_PATHS - U.SUPERSEDED - {U.MANIFEST} - later_superseded:\n'
                             '            raw = (U.ROOT / path).read_bytes()\n'
                             "            assert not U.supersedes(path, U._blob(raw)) and not W.supersedes(path, U._blob(raw + b'\\n')), path\n"),
                            ('def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n'
                             "    assert _git(U.ROOT, 'rev-parse', U.INTEGRATION + '^{tree}').strip() == U.INTEGRATION_TREE\n"
                             "    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.BASE, U.INTEGRATION], cwd=U.ROOT)\n"
                             "    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.INTEGRATION, 'HEAD'], cwd=U.ROOT)\n"
                             '    data = U.manifest()\n'
                             "    for path, blob in data['integration_blobs'].items():\n"
                             "        assert _git(U.ROOT, 'rev-parse', f'{U.INTEGRATION}:{path}').strip() == blob\n"
                             "    changed = set(_git(U.ROOT, 'diff', '--name-only', U.INTEGRATION, '--').split())\n"
                             '    # Post-#413 successors: only the finite, closed path set of a later cohort that is REGISTERED and EXACT (each '
                             'pinned by its own manifest).\n'
                             '    later_owned = set().union(*(set(m.OWNED_PATHS) | {m.MANIFEST} for m in U._later_modules() if m.__name__ in '
                             'C.COHORT_MODULES and m.exact_blobs_ok()))\n'
                             '    assert changed <= U.OWNED_PATHS | {U.MANIFEST} | later_owned          # nothing else moved away from main at #414\n'
                             '    assert not any((p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS) and not U._later_ci_owns(p, U.ROOT, '
                             'None) for p in changed)\n',
                             'def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n'
                             '    with C.call_scope():\n'
                             "        assert _git(U.ROOT, 'rev-parse', U.INTEGRATION + '^{tree}').strip() == U.INTEGRATION_TREE\n"
                             "        subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.BASE, U.INTEGRATION], cwd=U.ROOT)\n"
                             "        subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.INTEGRATION, 'HEAD'], cwd=U.ROOT)\n"
                             '        data = U.manifest()\n'
                             "        for path, blob in data['integration_blobs'].items():\n"
                             "            assert _git(U.ROOT, 'rev-parse', f'{U.INTEGRATION}:{path}').strip() == blob\n"
                             "        changed = set(_git(U.ROOT, 'diff', '--name-only', U.INTEGRATION, '--').split())\n"
                             '        # Post-#413 successors: only the finite, closed path set of a later cohort that is REGISTERED and EXACT (each '
                             'pinned by its own manifest).\n'
                             '        later_owned = set().union(*(set(m.OWNED_PATHS) | {m.MANIFEST} for m in U._later_modules() if m.__name__ in '
                             'C.COHORT_MODULES and m.exact_blobs_ok()))\n'
                             '        assert changed <= U.OWNED_PATHS | {U.MANIFEST} | later_owned          # nothing else moved away from main at '
                             '#414\n'
                             '        assert not any((p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS) and not U._later_ci_owns(p, '
                             'U.ROOT, None) for p in changed)\n'),
                            ('def test_an_unowned_path_that_moved_away_from_main_after_414_fails_closed(wt):\n'
                             '    assert U.exact_blobs_ok(wt)\n'
                             "    _flip(wt / 'app/cost_line_ledger/ledger.py')                            # not owned by U1: it must equal main at "
                             'the integration commit\n'
                             '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n',
                             'def test_an_unowned_path_that_moved_away_from_main_after_414_fails_closed(wt):\n'
                             '    with C.call_scope():\n'
                             '        assert U.exact_blobs_ok(wt)\n'
                             "    _flip(wt / 'app/cost_line_ledger/ledger.py')                            # not owned by U1: it must equal main at "
                             'the integration commit\n'
                             '    with C.call_scope():\n'
                             '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n')],
 'tests/test_u2_scope.py': [('def test_positive_cohort_is_exact_registered_and_closed():\n'
                             '    assert U2.exact_blobs_ok() and U2.valid() and C.valid() and U1.exact_blobs_ok() and W.exact_blobs_ok()\n'
                             '    assert U2.__name__ in C.COHORT_MODULES and U2 in C.cohorts() and U2.protected_blobs() == {}\n'
                             '    data = U2.manifest()\n'
                             "    assert set(data['source_blobs']) == U2.OWNED_PATHS and set(data['base_blobs']) == U2.SUPERSEDED\n"
                             '    assert not any(p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS for p in U2.OWNED_PATHS)\n'
                             '    assert not (U2.OWNED_PATHS & U2.R1_PATHS)                                                    # addendum: no '
                             'R1-owned file\n'
                             "    for stranger in ('app/library/router.py', 'app/v2/acquisition_router.py', 'tests/test_something_new.py',\n"
                             "                     'financial_engine/x.py', '.github/workflows/ci.yml'):\n"
                             '        assert not U2.allowed_path(stranger) and not U1.allowed_path(stranger) and not W.allowed_path(stranger)\n'
                             "    # An R1 path is never U2's. It is admitted by U1 / WF-06B ONLY through the exact, registered R1 cohort that owns "
                             'it (integration branch).\n'
                             "    r1 = {m.__name__: m for m in _later()}['tests.post413_r1_scope']\n"
                             "    for r1_path in ('frontend/src/app/editing/saveAll.ts', 'frontend/src/app/editing/pendingEdits.ts', "
                             "'frontend/src/app/workflow/PPAEditorView.tsx'):\n"
                             '        assert not U2.allowed_path(r1_path) and r1_path not in U2.OWNED_PATHS and r1.allowed_path(r1_path)\n'
                             "        assert 'tests.post413_r1_scope' in C.COHORT_MODULES and r1.exact_blobs_ok() and U1.allowed_path(r1_path) and "
                             'W.allowed_path(r1_path)\n'
                             "    for owned in ('app/v2/react_opex_lines.py', 'frontend/src/app/capex/profileImport.ts', 'tests/u2_scope.py'):\n"
                             '        assert U2.matches(owned) and U2.allowed_path(owned) and U1.allowed_path(owned) and W.allowed_path(owned)\n'
                             "    path = 'static/react/finco-react.js'\n"
                             "    pin = data['source_blobs'][path]\n"
                             '    assert U2.supersedes(path, pin) and U1.supersedes(path, pin) and W.supersedes(path, pin) and not '
                             "U2.supersedes(path, '0' * 40)\n"
                             "    assert not U2.supersedes('app/v2/react_opex_lines.py', data['source_blobs']['app/v2/react_opex_lines.py'])   # new "
                             'at U2: nothing to supersede\n',
                             'def test_positive_cohort_is_exact_registered_and_closed():\n'
                             '    with C.call_scope():\n'
                             '        assert U2.exact_blobs_ok() and U2.valid() and C.valid() and U1.exact_blobs_ok() and W.exact_blobs_ok()\n'
                             '        assert U2.__name__ in C.COHORT_MODULES and U2 in C.cohorts() and U2.protected_blobs() == {}\n'
                             '        data = U2.manifest()\n'
                             "        assert set(data['source_blobs']) == U2.OWNED_PATHS and set(data['base_blobs']) == U2.SUPERSEDED\n"
                             '        assert not any(p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS for p in U2.OWNED_PATHS)\n'
                             '        assert not (U2.OWNED_PATHS & U2.R1_PATHS)                                                    # addendum: no '
                             'R1-owned file\n'
                             "        for stranger in ('app/library/router.py', 'app/v2/acquisition_router.py', 'tests/test_something_new.py',\n"
                             "                         'financial_engine/x.py', '.github/workflows/ci.yml'):\n"
                             '            assert not U2.allowed_path(stranger) and not U1.allowed_path(stranger) and not W.allowed_path(stranger)\n'
                             "        # An R1 path is never U2's. It is admitted by U1 / WF-06B ONLY through the exact, registered R1 cohort that "
                             'owns it (integration branch).\n'
                             "        r1 = {m.__name__: m for m in _later()}['tests.post413_r1_scope']\n"
                             "        for r1_path in ('frontend/src/app/editing/saveAll.ts', 'frontend/src/app/editing/pendingEdits.ts', "
                             "'frontend/src/app/workflow/PPAEditorView.tsx'):\n"
                             '            assert not U2.allowed_path(r1_path) and r1_path not in U2.OWNED_PATHS and r1.allowed_path(r1_path)\n'
                             "            assert 'tests.post413_r1_scope' in C.COHORT_MODULES and r1.exact_blobs_ok() and U1.allowed_path(r1_path) "
                             'and W.allowed_path(r1_path)\n'
                             "        for owned in ('app/v2/react_opex_lines.py', 'frontend/src/app/capex/profileImport.ts', 'tests/u2_scope.py'):\n"
                             '            assert U2.matches(owned) and U2.allowed_path(owned) and U1.allowed_path(owned) and W.allowed_path(owned)\n'
                             "        path = 'static/react/finco-react.js'\n"
                             "        pin = data['source_blobs'][path]\n"
                             '        assert U2.supersedes(path, pin) and U1.supersedes(path, pin) and W.supersedes(path, pin) and not '
                             "U2.supersedes(path, '0' * 40)\n"
                             "        assert not U2.supersedes('app/v2/react_opex_lines.py', data['source_blobs']['app/v2/react_opex_lines.py'])   # "
                             'new at U2: nothing to supersede\n'),
                            ('def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):\n'
                             '    assert U2.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             '    assert not U2.exact_blobs_ok(wt) and not U2.matches(path, (wt / path).read_bytes(), repo=wt) and not C.valid(wt)\n'
                             '    if path in U1.OWNED_PATHS:\n'
                             '        assert not U1.exact_blobs_ok(wt)                                                          # U1 stops following '
                             'a drifted U2 state\n',
                             'def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):\n'
                             '    with C.call_scope():\n'
                             '        assert U2.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt) and not U2.matches(path, (wt / path).read_bytes(), repo=wt) and not '
                             'C.valid(wt)\n'
                             '    if path in U1.OWNED_PATHS:\n'
                             '        with C.call_scope():\n'
                             '            assert not U1.exact_blobs_ok(wt)                                                          # U1 stops '
                             'following a drifted U2 state\n'),
                            ('def test_manifest_forgery_is_refused(kind, wt):\n'
                             '    mpath = wt / U2.MANIFEST\n'
                             '    d = json.loads(mpath.read_text())\n'
                             "    if kind == 'extra-path':\n"
                             "        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40\n"
                             "    elif kind == 'missing-pin':\n"
                             "        d['source_blobs'].pop('static/react/finco-react.js')\n"
                             "    elif kind == 'wrong-base':\n"
                             "        d['base'] = '0' * 40\n"
                             "    elif kind == 'wrong-tree':\n"
                             "        d['base_tree'] = '0' * 40\n"
                             "    elif kind == 'wrong-blob':\n"
                             "        d['source_blobs']['app/v2/react_opex_lines.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-pins':\n"
                             "        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'\n"
                             "        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]\n"
                             "    elif kind == 'drop-base-blob':\n"
                             "        d['base_blobs'].pop('app/v2/react_workspace_router.py')\n"
                             "    elif kind == 'wrong-base-blob':\n"
                             "        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-schema':\n"
                             "        d['schema_version'] = U1.SCHEMA\n"
                             "    elif kind == 'alias-pin':\n"
                             "        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']\n"
                             "    elif kind == 'extra-base-blob':\n"
                             "        d['base_blobs']['app/v2/save_all_commands.py'] = _git(U2.ROOT, 'rev-parse', "
                             "f'{U2.BASE}:app/v2/save_all_commands.py').strip()\n"
                             "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                             '    assert not U2.exact_blobs_ok(wt) and not C.valid(wt) and not U1.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt)\n',
                             'def test_manifest_forgery_is_refused(kind, wt):\n'
                             '    mpath = wt / U2.MANIFEST\n'
                             '    d = json.loads(mpath.read_text())\n'
                             "    if kind == 'extra-path':\n"
                             "        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40\n"
                             "    elif kind == 'missing-pin':\n"
                             "        d['source_blobs'].pop('static/react/finco-react.js')\n"
                             "    elif kind == 'wrong-base':\n"
                             "        d['base'] = '0' * 40\n"
                             "    elif kind == 'wrong-tree':\n"
                             "        d['base_tree'] = '0' * 40\n"
                             "    elif kind == 'wrong-blob':\n"
                             "        d['source_blobs']['app/v2/react_opex_lines.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-pins':\n"
                             "        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'\n"
                             "        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]\n"
                             "    elif kind == 'drop-base-blob':\n"
                             "        d['base_blobs'].pop('app/v2/react_workspace_router.py')\n"
                             "    elif kind == 'wrong-base-blob':\n"
                             "        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40\n"
                             "    elif kind == 'swapped-schema':\n"
                             "        d['schema_version'] = U1.SCHEMA\n"
                             "    elif kind == 'alias-pin':\n"
                             "        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']\n"
                             "    elif kind == 'extra-base-blob':\n"
                             "        d['base_blobs']['app/v2/save_all_commands.py'] = _git(U2.ROOT, 'rev-parse', "
                             "f'{U2.BASE}:app/v2/save_all_commands.py').strip()\n"
                             "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt) and not C.valid(wt) and not U1.exact_blobs_ok(wt) and not '
                             'W.exact_blobs_ok(wt)\n'),
                            ('def test_u1_follows_u2_only_where_u2_recorded_exactly_the_u1_pin(wt, monkeypatch):\n'
                             "    path = 'frontend/src/app/capex/CapexStudio.tsx'\n"
                             '    assert U1.exact_blobs_ok(wt)\n'
                             "    # forge the U1 pin: U2's recorded BASE blob no longer equals it -> U1 must NOT follow U2\n"
                             '    upath = wt / U1.MANIFEST\n'
                             '    u = json.loads(upath.read_text())\n'
                             "    u['source_blobs'][path] = '1' * 40\n"
                             "    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\\n')\n"
                             '    assert not U1.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'checkout', '--', U1.MANIFEST)\n"
                             '    assert U1.exact_blobs_ok(wt)\n'
                             '    # a U2 cohort that no longer supersedes the path is not followed either\n'
                             "    monkeypatch.setattr(U2, 'SUPERSEDED', frozenset(U2.SUPERSEDED - {path}))\n"
                             "    assert not U1.supersedes(path, U2.manifest(wt)['source_blobs'][path], repo=wt)\n",
                             'def test_u1_follows_u2_only_where_u2_recorded_exactly_the_u1_pin(wt, monkeypatch):\n'
                             "    path = 'frontend/src/app/capex/CapexStudio.tsx'\n"
                             '    with C.call_scope():\n'
                             '        assert U1.exact_blobs_ok(wt)\n'
                             "    # forge the U1 pin: U2's recorded BASE blob no longer equals it -> U1 must NOT follow U2\n"
                             '    upath = wt / U1.MANIFEST\n'
                             '    u = json.loads(upath.read_text())\n'
                             "    u['source_blobs'][path] = '1' * 40\n"
                             "    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not U1.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'checkout', '--', U1.MANIFEST)\n"
                             '    with C.call_scope():\n'
                             '        assert U1.exact_blobs_ok(wt)\n'
                             '    # a U2 cohort that no longer supersedes the path is not followed either\n'
                             "    monkeypatch.setattr(U2, 'SUPERSEDED', frozenset(U2.SUPERSEDED - {path}))\n"
                             '    with C.call_scope():\n'
                             "        assert not U1.supersedes(path, U2.manifest(wt)['source_blobs'][path], repo=wt)\n"),
                            ('def test_extra_tracked_extra_untracked_r1_and_executable_paths_fail_closed(wt):\n'
                             "    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\\n')\n"
                             '    assert not U2.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')\n"
                             '    assert not U2.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'reset', '-q')\n"
                             "    (wt / 'frontend/src/app/Sneaky.tsx').unlink()\n"
                             '    assert U2.exact_blobs_ok(wt)\n'
                             "    owned = wt / 'app/v2/react_opex_lines.py'\n"
                             '    owned.chmod(0o755)\n'
                             '    assert not U2.exact_blobs_ok(wt)\n'
                             '    owned.chmod(0o644)\n'
                             '    assert U2.exact_blobs_ok(wt)\n',
                             'def test_extra_tracked_extra_untracked_r1_and_executable_paths_fail_closed(wt):\n'
                             "    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')\n"
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "    _git(wt, 'reset', '-q')\n"
                             "    (wt / 'frontend/src/app/Sneaky.tsx').unlink()\n"
                             '    with C.call_scope():\n'
                             '        assert U2.exact_blobs_ok(wt)\n'
                             "    owned = wt / 'app/v2/react_opex_lines.py'\n"
                             '    owned.chmod(0o755)\n'
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt)\n'
                             '    owned.chmod(0o644)\n'
                             '    with C.call_scope():\n'
                             '        assert U2.exact_blobs_ok(wt)\n'),
                            ('def test_protected_r1_and_unowned_code_modified_after_signing_fails_closed(path, wt):\n'
                             '    assert U2.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             "    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qam', 'tamper', '--no-verify')\n"
                             '    assert not U2.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             '    assert not U2.allowed_path(path)\n'
                             "    _git(wt, 'reset', '--hard', '-q', 'HEAD~1')\n",
                             'def test_protected_r1_and_unowned_code_modified_after_signing_fails_closed(path, wt):\n'
                             '    with C.call_scope():\n'
                             '        assert U2.exact_blobs_ok(wt)\n'
                             '    _flip(wt / path)\n'
                             "    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qam', 'tamper', '--no-verify')\n"
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             '    with C.call_scope():\n'
                             '        assert not U2.allowed_path(path)\n'
                             "    _git(wt, 'reset', '--hard', '-q', 'HEAD~1')\n"),
                            ('def test_an_unreviewed_second_include_router_fails_closed(where, wt):\n'
                             '    path = wt / _ROUTER\n'
                             "    text = path.read_text(encoding='utf-8')\n"
                             '    extra = "from app.v2.react_unreviewed import router as _unreviewed_router  # noqa: '
                             'E402\\n\\nrouter.include_router(_unreviewed_router)\\n"\n'
                             "    if where == 'tail':\n"
                             "        text = text.rstrip('\\n') + '\\n\\n' + extra\n"
                             "    elif where == 'body':\n"
                             '        i = text.index(_RCUX_TAIL)                                                                 # inside the '
                             'historical RC-M interval\n'
                             "        text = text[:i] + extra + '\\n' + text[i:]\n"
                             '    else:\n'
                             '        i = text.index(_RCM_MARK)                                                                  # a second include '
                             'in the U2 section\n'
                             "        text = text[:i] + extra + '\\n' + text[i:]\n"
                             "    path.write_text(text, encoding='utf-8')\n"
                             "    if where == 'tail':\n"
                             "        assert _tail_includes(text) != ['_rcux_router']                                           # the protected "
                             'RC-UX check refuses it\n'
                             "    if where == 'body':\n"
                             '        import re\n'
                             '        rcm = text[text.index(_RCM_MARK):text.index(_RCUX_TAIL)]\n'
                             '        assert re.findall(r"^router\\.include_router\\((\\w+)\\)$", rcm, flags=re.M) != _RCM_INCLUDES   # the '
                             'protected RC-M check refuses it\n'
                             '    assert not U2.exact_blobs_ok(wt) and not U1.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             '    assert not U1.supersedes(_ROUTER, U2._blob(text.encode()), repo=wt)\n',
                             'def test_an_unreviewed_second_include_router_fails_closed(where, wt):\n'
                             '    path = wt / _ROUTER\n'
                             "    text = path.read_text(encoding='utf-8')\n"
                             '    extra = "from app.v2.react_unreviewed import router as _unreviewed_router  # noqa: '
                             'E402\\n\\nrouter.include_router(_unreviewed_router)\\n"\n'
                             "    if where == 'tail':\n"
                             "        text = text.rstrip('\\n') + '\\n\\n' + extra\n"
                             "    elif where == 'body':\n"
                             '        i = text.index(_RCUX_TAIL)                                                                 # inside the '
                             'historical RC-M interval\n'
                             "        text = text[:i] + extra + '\\n' + text[i:]\n"
                             '    else:\n'
                             '        i = text.index(_RCM_MARK)                                                                  # a second include '
                             'in the U2 section\n'
                             "        text = text[:i] + extra + '\\n' + text[i:]\n"
                             "    path.write_text(text, encoding='utf-8')\n"
                             "    if where == 'tail':\n"
                             "        assert _tail_includes(text) != ['_rcux_router']                                           # the protected "
                             'RC-UX check refuses it\n'
                             "    if where == 'body':\n"
                             '        import re\n'
                             '        rcm = text[text.index(_RCM_MARK):text.index(_RCUX_TAIL)]\n'
                             '        assert re.findall(r"^router\\.include_router\\((\\w+)\\)$", rcm, flags=re.M) != _RCM_INCLUDES   # the '
                             'protected RC-M check refuses it\n'
                             '    with C.call_scope():\n'
                             '        assert not U2.exact_blobs_ok(wt) and not U1.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not '
                             'C.valid(wt)\n'
                             '    with C.call_scope():\n'
                             '        assert not U1.supersedes(_ROUTER, U2._blob(text.encode()), repo=wt)\n'),
                            ('def test_an_unrelated_committed_extra_file_fails_closed(wt):\n'
                             "    extra = wt / 'app/v2/react_unreviewed.py'\n"
                             '    extra.write_text(\'"""unreviewed"""\\n\')\n'
                             "    _git(wt, 'add', 'app/v2/react_unreviewed.py')\n"
                             "    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qm', 'extra', '--no-verify')\n"
                             '    try:\n'
                             '        assert not U2.exact_blobs_ok(wt) and not U1.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             "        assert not U2.allowed_path('app/v2/react_unreviewed.py') and not "
                             "U1.allowed_path('app/v2/react_unreviewed.py')\n"
                             '    finally:\n'
                             "        _git(wt, 'reset', '--hard', '-q', 'HEAD~1')\n",
                             'def test_an_unrelated_committed_extra_file_fails_closed(wt):\n'
                             "    extra = wt / 'app/v2/react_unreviewed.py'\n"
                             '    extra.write_text(\'"""unreviewed"""\\n\')\n'
                             "    _git(wt, 'add', 'app/v2/react_unreviewed.py')\n"
                             "    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qm', 'extra', '--no-verify')\n"
                             '    try:\n'
                             '        with C.call_scope():\n'
                             '            assert not U2.exact_blobs_ok(wt) and not U1.exact_blobs_ok(wt) and not C.valid(wt)\n'
                             '        with C.call_scope():\n'
                             "            assert not U2.allowed_path('app/v2/react_unreviewed.py') and not "
                             "U1.allowed_path('app/v2/react_unreviewed.py')\n"
                             '    finally:\n'
                             "        _git(wt, 'reset', '--hard', '-q', 'HEAD~1')\n"),
                            ('def test_shared_reviewed_paths_are_signed_identically_and_fail_closed(wt):\n'
                             '    """#419 Correction K negatives for the shared reviewed set: one-byte drift, a forged pin in ONE owner, an extra '
                             'unowned path, same-cardinality\n'
                             '    identity swap and a historical protected path are all refused."""\n'
                             '    four = list(_later(FOUR))\n'
                             '    union_u2, union_siblings = U2.OWNED_PATHS | {U2.MANIFEST}, _signed([m for m in four if m is not U2])\n'
                             "    assert (union_u2 & union_siblings) <= SHARED_REVIEWED and 'tests/test_wf06b_scope.py' in (union_u2 & "
                             'union_siblings)\n'
                             "    path = 'tests/test_wf06b_scope.py'\n"
                             '    _flip(wt / path)                                                                                  # one byte of '
                             'drift: signatures disagree\n'
                             '    assert len(_shared_signatures(wt, four, path)) == 2 and not U2.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'checkout', '--', path)\n"
                             '    mpath = wt / U2.MANIFEST                                                                          # forged pin in '
                             'one owner only\n'
                             "    d = json.loads(mpath.read_text()); d['source_blobs'][path] = '0' * 40; mpath.write_text(json.dumps(d, indent=2) + "
                             "'\\n')\n"
                             '    assert len(_shared_signatures(wt, four, path)) == 2 and not U2.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'checkout', '--', str(mpath.relative_to(wt)))\n"
                             "    assert 'app/v2/react_unreviewed.py' not in SHARED_REVIEWED and not U2.allowed_path('app/v2/react_unreviewed.py')   "
                             '# extra unowned path\n'
                             "    swapped = (SHARED_REVIEWED - {path}) | {'tests/test_rcm_governance_x.py'}                         # same "
                             'cardinality, different identity\n'
                             '    assert len(swapped) == len(SHARED_REVIEWED) and (union_u2 & union_siblings) - swapped == {path}\n'
                             "    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')) for p in "
                             'SHARED_REVIEWED)   # no protected path\n',
                             'def test_shared_reviewed_paths_are_signed_identically_and_fail_closed(wt):\n'
                             '    """#419 Correction K negatives for the shared reviewed set: one-byte drift, a forged pin in ONE owner, an extra '
                             'unowned path, same-cardinality\n'
                             '    identity swap and a historical protected path are all refused."""\n'
                             '    four = list(_later(FOUR))\n'
                             '    union_u2, union_siblings = U2.OWNED_PATHS | {U2.MANIFEST}, _signed([m for m in four if m is not U2])\n'
                             "    assert (union_u2 & union_siblings) <= SHARED_REVIEWED and 'tests/test_wf06b_scope.py' in (union_u2 & "
                             'union_siblings)\n'
                             "    path = 'tests/test_wf06b_scope.py'\n"
                             '    _flip(wt / path)                                                                                  # one byte of '
                             'drift: signatures disagree\n'
                             '    with C.call_scope():\n'
                             '        assert len(_shared_signatures(wt, four, path)) == 2 and not U2.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'checkout', '--', path)\n"
                             '    mpath = wt / U2.MANIFEST                                                                          # forged pin in '
                             'one owner only\n'
                             "    d = json.loads(mpath.read_text()); d['source_blobs'][path] = '0' * 40; mpath.write_text(json.dumps(d, indent=2) + "
                             "'\\n')\n"
                             '    with C.call_scope():\n'
                             '        assert len(_shared_signatures(wt, four, path)) == 2 and not U2.exact_blobs_ok(wt)\n'
                             "    _git(wt, 'checkout', '--', str(mpath.relative_to(wt)))\n"
                             '    with C.call_scope():\n'
                             "        assert 'app/v2/react_unreviewed.py' not in SHARED_REVIEWED and not "
                             "U2.allowed_path('app/v2/react_unreviewed.py')   # extra unowned path\n"
                             "    swapped = (SHARED_REVIEWED - {path}) | {'tests/test_rcm_governance_x.py'}                         # same "
                             'cardinality, different identity\n'
                             '    assert len(swapped) == len(SHARED_REVIEWED) and (union_u2 & union_siblings) - swapped == {path}\n'
                             "    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')) for p in "
                             'SHARED_REVIEWED)   # no protected path\n')],
 'tests/test_ux_pr1_scope.py': [('def test_unsigned_byte_fails_closed(path,wt):\n'
                                 '    assert U.exact_blobs_ok(wt)\n'
                                 "    p=wt/path;p.write_bytes(p.read_bytes()+b'\\n')\n"
                                 '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n',
                                 'def test_unsigned_byte_fails_closed(path,wt):\n'
                                 '    # One bounded read-only registry call scope PER PHASE (each is dropped before the byte is changed, so no '
                                 'verdict is ever reused across the\n'
                                 '    # mutation): the unscoped composite recomputed the whole cohort chain at every link (about 16-21 minutes per '
                                 'parameter on a hosted runner).\n'
                                 '    with C.call_scope():\n'
                                 '        assert U.exact_blobs_ok(wt)\n'
                                 "    p=wt/path;p.write_bytes(p.read_bytes()+b'\\n')\n"
                                 '    with C.call_scope():\n'
                                 '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                                ('def test_forgery_foreign_modes_and_registration_fail_closed(change,wt):\n'
                                 '    assert U.exact_blobs_ok(wt)\n'
                                 '    path=wt/U.MANIFEST;d=json.loads(path.read_text())\n',
                                 'def test_forgery_foreign_modes_and_registration_fail_closed(change,wt):\n'
                                 '    # Read-only verdict phases run in their own bounded call scope (dropped before any byte changes): same '
                                 'assertions, no verdict reused across a mutation.\n'
                                 '    with C.call_scope():\n'
                                 '        assert U.exact_blobs_ok(wt)\n'
                                 '    path=wt/U.MANIFEST;d=json.loads(path.read_text())\n'),
                                ('    try:\n        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n    finally:\n        # core.filemode=false',
                                 '    try:\n'
                                 '        with C.call_scope():\n'
                                 '            assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                 '    finally:\n'
                                 '        # core.filemode=false'),
                                ("    d['source_blobs'][owned]='0'*40;p.write_text(json.dumps(d)+'\\n')\n"
                                 '    assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                 "    p.write_bytes(old);d=json.loads(old);d['base']='0'*40;p.write_text(json.dumps(d)+'\\n')\n"
                                 '    assert not U.exact_blobs_ok(wt)\n',
                                 "    d['source_blobs'][owned]='0'*40;p.write_text(json.dumps(d)+'\\n')\n"
                                 '    # Read-only verdict phases run in their own bounded call scope (dropped before any byte changes): same '
                                 'assertions, no verdict reused across a mutation.\n'
                                 '    with C.call_scope():\n'
                                 '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                 "    p.write_bytes(old);d=json.loads(old);d['base']='0'*40;p.write_text(json.dumps(d)+'\\n')\n"
                                 '    with C.call_scope():\n'
                                 '        assert not U.exact_blobs_ok(wt)\n'),
                                ('    assert U.matches(p,raw,repo=wt) and W.matches(p,raw,repo=wt)\n'
                                 "    (wt/p).write_bytes(raw+b'\\n')\n"
                                 '    assert not U.matches(p,raw,repo=wt) and not W.matches(p,raw,repo=wt)\n'
                                 "    assert U.exact_blobs_ok(wt,'HEAD')\n",
                                 '    # Read-only verdict phases run in their own bounded call scope (dropped before any byte changes): same '
                                 'assertions, no verdict reused across a mutation.\n'
                                 '    with C.call_scope():\n'
                                 '        assert U.matches(p,raw,repo=wt) and W.matches(p,raw,repo=wt)\n'
                                 "    (wt/p).write_bytes(raw+b'\\n')\n"
                                 '    with C.call_scope():\n'
                                 '        assert not U.matches(p,raw,repo=wt) and not W.matches(p,raw,repo=wt)\n'
                                 '    with C.call_scope():\n'
                                 "        assert U.exact_blobs_ok(wt,'HEAD')\n"),
                                ('    assert U.exact_blobs_ok(wt) and C.valid(wt)\n'
                                 "    for suffix in ('.py','.tsx','.mjs'):\n"
                                 "        source=evidence/('unsigned'+suffix);source.write_text('unsigned\\n')\n"
                                 '        assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                 '        source.unlink()\n'
                                 '    artifact.chmod(0o755);assert not U.exact_blobs_ok(wt)\n'
                                 "    artifact.chmod(0o644);artifact.unlink();artifact.symlink_to(wt/'tests/ux_pr1_scope.py')\n"
                                 '    assert not U.exact_blobs_ok(wt)\n',
                                 '    # Read-only verdict phases run in their own bounded call scope (dropped before any byte changes): same '
                                 'assertions, no verdict reused across a mutation.\n'
                                 '    with C.call_scope():\n'
                                 '        assert U.exact_blobs_ok(wt) and C.valid(wt)\n'
                                 "    for suffix in ('.py','.tsx','.mjs'):\n"
                                 "        source=evidence/('unsigned'+suffix);source.write_text('unsigned\\n')\n"
                                 '        with C.call_scope():\n'
                                 '            assert not U.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                 '        source.unlink()\n'
                                 '    artifact.chmod(0o755)\n'
                                 '    with C.call_scope():\n'
                                 '        assert not U.exact_blobs_ok(wt)\n'
                                 "    artifact.chmod(0o644);artifact.unlink();artifact.symlink_to(wt/'tests/ux_pr1_scope.py')\n"
                                 '    with C.call_scope():\n'
                                 '        assert not U.exact_blobs_ok(wt)\n'),
                                ('def test_exact_registered_and_historical_maps_immutable():\n',
                                 'def _later_authority(path):\n'
                                 '    """The LAST registered successor after UX-PR3b2 (BESS01, R02, F03, C06, the CI V4 shard-2 fix ...) that '
                                 'supersedes ``path``, or None. It is the\n'
                                 '    authority for the CURRENT blob; PR1 keeps its own authenticated lineage (``_effective_pin``) up to PR3b2."""\n'
                                 '    import importlib\n'
                                 '    from tests import ux_pr3b2_scope as F\n'
                                 '    last=None\n'
                                 '    for name in C.COHORT_MODULES[C.COHORT_MODULES.index(F.__name__)+1:]:\n'
                                 '        later=importlib.import_module(name)\n'
                                 "        if path in getattr(later,'SUPERSEDED',()):\n"
                                 '            assert later.exact_blobs_ok()\n'
                                 '            last=later\n'
                                 '    return last\n'
                                 '\n'
                                 'def test_exact_registered_and_historical_maps_immutable():\n'),
                                ('            eff=_effective_pin(p,hist)\n'
                                 "            assert U.supersedes(p,eff) and not U.supersedes(p,'0'*40)\n"
                                 '            if eff!=hist:  # a historical pin is preserved but no longer current authority\n'
                                 '                assert not U.supersedes(p,hist)\n'
                                 "            assert git(U.ROOT,'hash-object',p).strip()==eff\n",
                                 '            eff=_effective_pin(p,hist)\n'
                                 '            last=_later_authority(p)\n'
                                 "            cur=git(U.ROOT,'hash-object',p).strip()\n"
                                 '            if last is None:   # nothing moved the pin after UX-PR3b2: the PR1 lineage end is the current pin\n'
                                 "                assert U.supersedes(p,eff) and not U.supersedes(p,'0'*40) and cur==eff\n"
                                 '            else:              # the last registered successor that moved it accepts exactly the current blob and '
                                 'nothing forged\n'
                                 "                assert last.supersedes(p,cur) and not last.supersedes(p,'0'*40)\n"
                                 '            if eff!=hist:  # a historical pin is preserved but no longer current authority\n'
                                 '                assert not U.supersedes(p,hist)\n'),
                                ("    evidence=wt/'evidence'/'ux-pr1-probe';evidence.mkdir(parents=True,exist_ok=True)\n"
                                 '    artifact=evidence/\'source.json\';artifact.write_text(\'{"synthetic": true}\\n\')\n',
                                 '    # A finite generated-evidence path (the BESS01 guard accepts only those exact F01 outputs, no prefix or glob): '
                                 'the probe stays a data file, never source.\n'
                                 "    evidence=wt/'evidence'/'browser';evidence.mkdir(parents=True,exist_ok=True)\n"
                                 '    artifact=evidence/\'solar.json\';artifact.write_text(\'{"synthetic": true}\\n\')\n')],
 'tests/test_wf06b_scope.py': [('def test_positive_cohort_is_exact_registered_and_closed():\n'
                                '    assert W.exact_blobs_ok() and W.valid() and C.valid()\n'
                                '    assert W.__name__ in C.COHORT_MODULES and W in C.cohorts() and W.protected_blobs() == {}\n'
                                '    data = W.manifest()\n'
                                "    assert set(data['source_blobs']) == W.OWNED_PATHS - {W.MANIFEST} and set(data['base_blobs']) == W.SUPERSEDED\n"
                                "    assert all('*' not in p and not p.endswith('/') for p in W.OWNED_PATHS)                # a closed literal list, "
                                'never a pattern\n'
                                '    assert not any(p.startswith(W.FORBIDDEN_PREFIXES) or p in W.FORBIDDEN_PATHS for p in W.OWNED_PATHS)\n'
                                "    for stranger in ('app/library/router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py', "
                                "'financial_engine/x.py', '.github/workflows/ci.yml'):\n"
                                '        assert not W.allowed_path(stranger) and not W.matches(stranger)\n'
                                "    for owned in ('app/cost_line_ledger/ledger.py', 'static/react/finco-react.js', 'tests/wf06b_scope.py'):\n"
                                '        assert W.matches(owned) and W.allowed_path(owned)\n'
                                '    # the supersession is literal: only superseded paths, only the exact pin\n'
                                "    path = 'static/react/finco-react.js'\n"
                                "    assert W.supersedes(path, data['source_blobs'][path]) and not W.supersedes(path, '0' * 40)\n"
                                "    assert not W.supersedes('app/v2/router.py', data['source_blobs'][path]) and not "
                                "W.supersedes('app/cost_line_ledger/ledger.py', data['source_blobs']['app/cost_line_ledger/ledger.py'])\n",
                                'def test_positive_cohort_is_exact_registered_and_closed():\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok() and W.valid() and C.valid()\n'
                                '        assert W.__name__ in C.COHORT_MODULES and W in C.cohorts() and W.protected_blobs() == {}\n'
                                '        data = W.manifest()\n'
                                "        assert set(data['source_blobs']) == W.OWNED_PATHS - {W.MANIFEST} and set(data['base_blobs']) == "
                                'W.SUPERSEDED\n'
                                "        assert all('*' not in p and not p.endswith('/') for p in W.OWNED_PATHS)                # a closed literal "
                                'list, never a pattern\n'
                                '        assert not any(p.startswith(W.FORBIDDEN_PREFIXES) or p in W.FORBIDDEN_PATHS for p in W.OWNED_PATHS)\n'
                                "        for stranger in ('app/library/router.py', 'frontend/src/app/NewUnreviewed.tsx', "
                                "'tests/test_something_new.py', 'financial_engine/x.py', '.github/workflows/ci.yml'):\n"
                                '            assert not W.allowed_path(stranger) and not W.matches(stranger)\n'
                                "        for owned in ('app/cost_line_ledger/ledger.py', 'static/react/finco-react.js', 'tests/wf06b_scope.py'):\n"
                                '            assert W.matches(owned) and W.allowed_path(owned)\n'
                                '        # the supersession is literal: only superseded paths, only the exact pin\n'
                                "        path = 'static/react/finco-react.js'\n"
                                "        assert W.supersedes(path, data['source_blobs'][path]) and not W.supersedes(path, '0' * 40)\n"
                                "        assert not W.supersedes('app/v2/router.py', data['source_blobs'][path]) and not "
                                "W.supersedes('app/cost_line_ledger/ledger.py', data['source_blobs']['app/cost_line_ledger/ledger.py'])\n"),
                               ('def test_base_is_the_integrated_409_main_and_history_is_recorded_not_rewritten():\n'
                                "    assert _git(W.ROOT, 'rev-parse', W.BASE + '^{tree}').strip() == W.BASE_TREE\n"
                                "    subprocess.check_call(['git', 'merge-base', '--is-ancestor', W.BASE, 'HEAD'], cwd=W.ROOT)\n"
                                '    data = W.manifest()\n'
                                "    for path, blob in data['base_blobs'].items():                                          # each superseded path's "
                                'BASE blob is what git holds at BASE\n'
                                "        assert _git(W.ROOT, 'rev-parse', f'{W.BASE}:{path}').strip() == blob\n"
                                '    for path in W.SUPERSEDED:\n'
                                "        assert data['source_blobs'][path] != data['base_blobs'][path] or path in W.GOVERNANCE_PATHS or path\n"
                                '    # the older manifests were not edited: they are byte-identical to BASE\n'
                                "    changed = set(_git(W.ROOT, 'diff', '--name-only', W.BASE, '--').split())\n"
                                '    # later closed cohorts (registered and exact) own exactly their OWN manifest; every other manifest stays '
                                'byte-identical to BASE\n'
                                '    from tests import u1_scope as _U1\n'
                                '    later_manifests = {m.MANIFEST for m in _U1._later_modules() if m.__name__ in C.COHORT_MODULES and '
                                'm.exact_blobs_ok()}\n'
                                "    assert not any(p.startswith('docs/') and p.endswith('SOURCE_SUCCESSOR.json') and p not in (W.MANIFEST, "
                                "'docs/react_migration/u1_workbench/SOURCE_SUCCESSOR.json') and p not in later_manifests for p in changed)   # "
                                "PR-U1's own seal is the only later manifest\n",
                                'def test_base_is_the_integrated_409_main_and_history_is_recorded_not_rewritten():\n'
                                '    with C.call_scope():\n'
                                "        assert _git(W.ROOT, 'rev-parse', W.BASE + '^{tree}').strip() == W.BASE_TREE\n"
                                "        subprocess.check_call(['git', 'merge-base', '--is-ancestor', W.BASE, 'HEAD'], cwd=W.ROOT)\n"
                                '        data = W.manifest()\n'
                                "        for path, blob in data['base_blobs'].items():                                          # each superseded "
                                "path's BASE blob is what git holds at BASE\n"
                                "            assert _git(W.ROOT, 'rev-parse', f'{W.BASE}:{path}').strip() == blob\n"
                                '        for path in W.SUPERSEDED:\n'
                                "            assert data['source_blobs'][path] != data['base_blobs'][path] or path in W.GOVERNANCE_PATHS or path\n"
                                '        # the older manifests were not edited: they are byte-identical to BASE\n'
                                "        changed = set(_git(W.ROOT, 'diff', '--name-only', W.BASE, '--').split())\n"
                                '        # later closed cohorts (registered and exact) own exactly their OWN manifest; every other manifest stays '
                                'byte-identical to BASE\n'
                                '        from tests import u1_scope as _U1\n'
                                '        later_manifests = {m.MANIFEST for m in _U1._later_modules() if m.__name__ in C.COHORT_MODULES and '
                                'm.exact_blobs_ok()}\n'
                                "        assert not any(p.startswith('docs/') and p.endswith('SOURCE_SUCCESSOR.json') and p not in (W.MANIFEST, "
                                "'docs/react_migration/u1_workbench/SOURCE_SUCCESSOR.json') and p not in later_manifests for p in changed)   # "
                                "PR-U1's own seal is the only later manifest\n"),
                               ('def test_older_cohorts_and_the_409_seal_are_still_exact_on_the_real_tree():\n'
                                '    from tests import fin_v2_integration_409_scope as INT\n'
                                '    assert INT.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts())\n',
                                'def test_older_cohorts_and_the_409_seal_are_still_exact_on_the_real_tree():\n'
                                '    with C.call_scope():\n'
                                '        from tests import fin_v2_integration_409_scope as INT\n'
                                '        assert INT.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts())\n'),
                               ('def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                '    _flip(wt / path)\n'
                                '    assert not W.exact_blobs_ok(wt) and not W.matches(path, (wt / path).read_bytes(), repo=wt)\n'
                                '    assert not C.valid(wt)\n',
                                'def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                '    _flip(wt / path)\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not W.matches(path, (wt / path).read_bytes(), repo=wt)\n'
                                '    with C.call_scope():\n'
                                '        assert not C.valid(wt)\n'),
                               ('def test_missing_owned_path_fails_closed(path, wt):\n'
                                '    (wt / path).unlink()\n'
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n',
                                'def test_missing_owned_path_fails_closed(path, wt):\n'
                                '    (wt / path).unlink()\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                               ('def test_missing_owned_incident_document_fails_closed(path, wt):\n'
                                '    (wt / path).unlink()\n'
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n',
                                'def test_missing_owned_incident_document_fails_closed(path, wt):\n'
                                '    (wt / path).unlink()\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                               ('def test_manifest_forgery_is_refused(kind, wt):\n'
                                '    mpath = wt / W.MANIFEST\n'
                                '    d = json.loads(mpath.read_text())\n'
                                "    if kind == 'extra-path':\n"
                                "        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40\n"
                                "    elif kind == 'missing-pin':\n"
                                "        d['source_blobs'].pop('static/react/finco-react.js')\n"
                                "    elif kind == 'wrong-base':\n"
                                "        d['base'] = '0' * 40\n"
                                "    elif kind == 'wrong-tree':\n"
                                "        d['base_tree'] = '0' * 40\n"
                                "    elif kind == 'wrong-blob':\n"
                                "        d['source_blobs']['app/cost_line_ledger/ledger.py'] = '0' * 40\n"
                                "    elif kind == 'swapped-pins':\n"
                                "        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'\n"
                                "        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]\n"
                                "    elif kind == 'drop-base-blobs':\n"
                                "        d['base_blobs'].pop('app/v2/react_workspace_router.py')\n"
                                "    elif kind == 'wrong-base-blob':\n"
                                "        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40\n"
                                "    elif kind == 'swapped-schema':\n"
                                "        d['schema_version'] = 'WF06A_UX_EXACT_SOURCE_V1'\n"
                                "    elif kind == 'alias-pin':                                           # same value under a forged alias path\n"
                                "        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']\n"
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n',
                                'def test_manifest_forgery_is_refused(kind, wt):\n'
                                '    mpath = wt / W.MANIFEST\n'
                                '    d = json.loads(mpath.read_text())\n'
                                "    if kind == 'extra-path':\n"
                                "        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40\n"
                                "    elif kind == 'missing-pin':\n"
                                "        d['source_blobs'].pop('static/react/finco-react.js')\n"
                                "    elif kind == 'wrong-base':\n"
                                "        d['base'] = '0' * 40\n"
                                "    elif kind == 'wrong-tree':\n"
                                "        d['base_tree'] = '0' * 40\n"
                                "    elif kind == 'wrong-blob':\n"
                                "        d['source_blobs']['app/cost_line_ledger/ledger.py'] = '0' * 40\n"
                                "    elif kind == 'swapped-pins':\n"
                                "        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'\n"
                                "        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]\n"
                                "    elif kind == 'drop-base-blobs':\n"
                                "        d['base_blobs'].pop('app/v2/react_workspace_router.py')\n"
                                "    elif kind == 'wrong-base-blob':\n"
                                "        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40\n"
                                "    elif kind == 'swapped-schema':\n"
                                "        d['schema_version'] = 'WF06A_UX_EXACT_SOURCE_V1'\n"
                                "    elif kind == 'alias-pin':                                           # same value under a forged alias path\n"
                                "        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']\n"
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                               ('def test_extra_tracked_extra_untracked_and_executable_paths_fail_closed(wt):\n'
                                "    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\\n')\n"
                                '    assert not W.exact_blobs_ok(wt)                                                       # untracked, not owned\n'
                                "    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')\n"
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)                                   # staged, not owned\n'
                                "    _git(wt, 'reset', '-q')\n"
                                "    (wt / 'frontend/src/app/Sneaky.tsx').unlink()\n"
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    run = wt / 'app/cost_line_ledger/run.sh'\n"
                                "    run.write_text('#!/bin/sh\\n')\n"
                                '    run.chmod(0o755)\n'
                                '    assert not W.exact_blobs_ok(wt)                                                       # a future untracked '
                                'executable\n'
                                '    run.unlink()\n'
                                "    owned = wt / 'app/cost_line_ledger/ledger.py'\n"
                                '    owned.chmod(0o755)\n'
                                '    assert not W.exact_blobs_ok(wt)                                                       # an owned file made '
                                'executable\n'
                                '    owned.chmod(0o644)\n'
                                '    assert W.exact_blobs_ok(wt)\n',
                                'def test_extra_tracked_extra_untracked_and_executable_paths_fail_closed(wt):\n'
                                "    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                                                       # untracked, not '
                                'owned\n'
                                "    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)                                   # staged, not owned\n'
                                "    _git(wt, 'reset', '-q')\n"
                                "    (wt / 'frontend/src/app/Sneaky.tsx').unlink()\n"
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    run = wt / 'app/cost_line_ledger/run.sh'\n"
                                "    run.write_text('#!/bin/sh\\n')\n"
                                '    run.chmod(0o755)\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                                                       # a future untracked '
                                'executable\n'
                                '    run.unlink()\n'
                                "    owned = wt / 'app/cost_line_ledger/ledger.py'\n"
                                '    owned.chmod(0o755)\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                                                       # an owned file made '
                                'executable\n'
                                '    owned.chmod(0o644)\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'),
                               ('def test_protected_and_unowned_code_modified_after_signing_fails_closed(path, wt):\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                '    _flip(wt / path)\n'
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                '    assert not W.allowed_path(path)\n',
                                'def test_protected_and_unowned_code_modified_after_signing_fails_closed(path, wt):\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                '    _flip(wt / path)\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                '    with C.call_scope():\n'
                                '        assert not W.allowed_path(path)\n'),
                               ('def test_old_409_union_and_predecessor_manifests_cannot_be_bypassed(path, wt):\n'
                                '    target = wt / path\n'
                                '    if not target.exists():\n'
                                "        target.write_text('x\\n')\n"
                                '    else:\n'
                                '        _flip(target)\n'
                                '    from tests import fin_v2_integration_409_scope as INT\n'
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt) and not INT.exact_blobs_ok(wt)\n',
                                'def test_old_409_union_and_predecessor_manifests_cannot_be_bypassed(path, wt):\n'
                                '    target = wt / path\n'
                                '    if not target.exists():\n'
                                "        target.write_text('x\\n')\n"
                                '    else:\n'
                                '        _flip(target)\n'
                                '    from tests import fin_v2_integration_409_scope as INT\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt) and not INT.exact_blobs_ok(wt)\n'),
                               ('def test_removing_an_old_ledger_row_or_historical_map_is_caught_by_the_older_cohorts(wt):\n'
                                '    from tests import wf03_lifecycle_scope as WF03\n'
                                "    manifest = wt / 'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json'\n"
                                '    d = json.loads(manifest.read_text())\n'
                                "    d['path_ledger'] = d['path_ledger'][:-1]\n"
                                "    manifest.write_text(json.dumps(d, indent=2) + '\\n')\n"
                                '    assert not C.valid(wt) and not W.exact_blobs_ok(wt)\n',
                                'def test_removing_an_old_ledger_row_or_historical_map_is_caught_by_the_older_cohorts(wt):\n'
                                '    from tests import wf03_lifecycle_scope as WF03\n'
                                "    manifest = wt / 'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json'\n"
                                '    d = json.loads(manifest.read_text())\n'
                                "    d['path_ledger'] = d['path_ledger'][:-1]\n"
                                "    manifest.write_text(json.dumps(d, indent=2) + '\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert not C.valid(wt) and not W.exact_blobs_ok(wt)\n'),
                               ('def test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort(wt):\n'
                                '    from tests import wsv2_core_scope as CORE\n'
                                '    assert CORE.exact_blobs_ok(wt)\n'
                                '    mpath = wt / W.MANIFEST\n'
                                '    d = json.loads(mpath.read_text())\n'
                                "    d['source_blobs']['static/react/finco-react.js'] = '1' * 40               # forge this cohort's pin: the older "
                                'cohort must NOT follow it\n'
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    assert not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)\n'
                                "    _git(wt, 'checkout', '--', W.MANIFEST)\n"
                                "    _flip(wt / 'static/react/finco-react.js')                                  # a tampered bundle: no cohort pins "
                                'it\n'
                                '    assert not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)\n',
                                'def test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort(wt):\n'
                                '    from tests import wsv2_core_scope as CORE\n'
                                '    with C.call_scope():\n'
                                '        assert CORE.exact_blobs_ok(wt)\n'
                                '    mpath = wt / W.MANIFEST\n'
                                '    d = json.loads(mpath.read_text())\n'
                                "    d['source_blobs']['static/react/finco-react.js'] = '1' * 40               # forge this cohort's pin: the older "
                                'cohort must NOT follow it\n'
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)\n'
                                "    _git(wt, 'checkout', '--', W.MANIFEST)\n"
                                "    _flip(wt / 'static/react/finco-react.js')                                  # a tampered bundle: no cohort pins "
                                'it\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)\n'),
                               ('def test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref(wt):\n'
                                "    head = _git(wt, 'rev-parse', 'HEAD').strip()\n"
                                '    assert W.exact_blobs_ok(wt, head)\n'
                                '    assert not W.exact_blobs_ok(wt, W.BASE)                                    # BASE has no WF-06B manifest\n'
                                "    _git(wt, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-qm', 'noop')\n"
                                "    assert W.exact_blobs_ok(wt, 'HEAD')\n",
                                'def test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref(wt):\n'
                                "    head = _git(wt, 'rev-parse', 'HEAD').strip()\n"
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt, head)\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt, W.BASE)                                    # BASE has no WF-06B manifest\n'
                                "    _git(wt, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-qm', 'noop')\n"
                                '    with C.call_scope():\n'
                                "        assert W.exact_blobs_ok(wt, 'HEAD')\n"),
                               ('def test_matches_accepts_exactly_the_successor_bytes_and_the_historical_pin(modname):\n'
                                '    import importlib\n'
                                "    D = importlib.import_module(f'tests.{modname}')\n"
                                '    paths = _pinned_and_superseded(D)\n'
                                "    assert 'tests/test_rcm_governance.py' in paths and f'tests/{modname}.py' in paths\n"
                                '    with _one_outer_call():\n'
                                '        for path in paths:\n'
                                '            raw = (W.ROOT / path).read_bytes()\n'
                                '            assert D.matches(path, raw) is True, path                                   # current, authenticated '
                                'successor bytes\n'
                                "            assert D.matches(path, raw + b'\\n') is False, path                          # one byte more is "
                                "nobody's reviewed state\n"
                                "            assert D.matches(path, raw.decode()) is True and D.matches(path, raw.decode() + ' ') is False\n"
                                "            historical = W._git(W.ROOT, 'show', f'{W.BASE}:{path}')\n"
                                '            assert D.matches(path, historical) is True, path                             # the historical reviewed '
                                'pin is unchanged and still matches\n'
                                "        for stranger in ('financial_engine/native_v11/config.py', 'tests/conftest.py', "
                                "'unreviewed/new_authority.py', 'docs/react_migration/wf06b_a_plus/P00.md'):\n"
                                "            assert stranger not in D.manifest()['source_blobs'] or stranger in W.SUPERSEDED\n"
                                "            assert D.matches(stranger, (W.ROOT / stranger).read_bytes() if (W.ROOT / stranger).exists() else b'x') "
                                'is False\n',
                                'def test_matches_accepts_exactly_the_successor_bytes_and_the_historical_pin(modname):\n'
                                '    with C.call_scope():\n'
                                '        import importlib\n'
                                "        D = importlib.import_module(f'tests.{modname}')\n"
                                '        paths = _pinned_and_superseded(D)\n'
                                "        assert 'tests/test_rcm_governance.py' in paths and f'tests/{modname}.py' in paths\n"
                                '        with _one_outer_call():\n'
                                '            for path in paths:\n'
                                '                raw = (W.ROOT / path).read_bytes()\n'
                                '                assert D.matches(path, raw) is True, path                                   # current, '
                                'authenticated successor bytes\n'
                                "                assert D.matches(path, raw + b'\\n') is False, path                          # one byte more is "
                                "nobody's reviewed state\n"
                                "                assert D.matches(path, raw.decode()) is True and D.matches(path, raw.decode() + ' ') is False\n"
                                "                historical = W._git(W.ROOT, 'show', f'{W.BASE}:{path}')\n"
                                '                assert D.matches(path, historical) is True, path                             # the historical '
                                'reviewed pin is unchanged and still matches\n'
                                "            for stranger in ('financial_engine/native_v11/config.py', 'tests/conftest.py', "
                                "'unreviewed/new_authority.py', 'docs/react_migration/wf06b_a_plus/P00.md'):\n"
                                "                assert stranger not in D.manifest()['source_blobs'] or stranger in W.SUPERSEDED\n"
                                '                assert D.matches(stranger, (W.ROOT / stranger).read_bytes() if (W.ROOT / stranger).exists() else '
                                "b'x') is False\n"),
                               ('def test_matches_refuses_successor_bytes_when_the_successor_is_not_authenticated(modname, wt, monkeypatch):\n'
                                '    import importlib\n'
                                "    D = importlib.import_module(f'tests.{modname}')\n"
                                "    path = 'tests/test_rcm_governance.py'\n"
                                '    raw = (wt / path).read_bytes()\n'
                                '    assert D.matches(path, raw, repo=wt) is True\n'
                                '    # a forged / mismatched WF-06B pin\n'
                                '    mpath = wt / W.MANIFEST\n'
                                '    good = mpath.read_text()\n'
                                '    d = json.loads(good)\n'
                                "    d['source_blobs'][path] = '2' * 40\n"
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    assert D.matches(path, raw, repo=wt) is False\n'
                                '    mpath.write_text(good)\n'
                                '    assert D.matches(path, raw, repo=wt) is True\n'
                                '    # one byte in the successor manifest, in any owned file the successor depends on, or a missing manifest\n'
                                "    mpath.write_text(good + '}')                                                   # one byte that breaks the "
                                'manifest\n'
                                '    assert D.matches(path, raw, repo=wt) is False\n'
                                '    mpath.write_text(good)\n'
                                "    _flip(wt / 'tests/wf06b_scope.py')\n"
                                "    assert D.matches(path, raw, repo=wt) is False                                   # the successor's own bytes are "
                                'pinned\n'
                                "    _git(wt, 'checkout', '--', 'tests/wf06b_scope.py')\n"
                                '    mpath.unlink()\n'
                                '    assert D.matches(path, raw, repo=wt) is False\n'
                                "    _git(wt, 'checkout', '--', W.MANIFEST)\n"
                                '    # altered base identity and a forged predecessor\n'
                                "    monkeypatch.setattr(W, 'BASE_TREE', '0' * 40)\n"
                                '    assert D.matches(path, raw, repo=wt) is False\n'
                                '    monkeypatch.undo()\n'
                                '    d = json.loads(good)\n'
                                "    d['base_blobs'][path] = '3' * 40\n"
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    assert D.matches(path, raw, repo=wt) is False\n'
                                '    mpath.write_text(good)\n'
                                '    # an untracked executable anywhere\n'
                                "    exe = wt / 'app/sneaky.sh'\n"
                                "    exe.write_text('#!/bin/sh\\n')\n"
                                '    exe.chmod(0o755)\n'
                                '    assert D.matches(path, raw, repo=wt) is False\n'
                                '    exe.unlink()\n'
                                '    assert D.matches(path, raw, repo=wt) is True\n'
                                '    # deleting the owned source fails the whole composition\n'
                                '    (wt / path).unlink()\n'
                                '    assert D.matches(path, raw, repo=wt) is False\n',
                                'def test_matches_refuses_successor_bytes_when_the_successor_is_not_authenticated(modname, wt, monkeypatch):\n'
                                '    import importlib\n'
                                "    D = importlib.import_module(f'tests.{modname}')\n"
                                "    path = 'tests/test_rcm_governance.py'\n"
                                '    raw = (wt / path).read_bytes()\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is True\n'
                                '    # a forged / mismatched WF-06B pin\n'
                                '    mpath = wt / W.MANIFEST\n'
                                '    good = mpath.read_text()\n'
                                '    d = json.loads(good)\n'
                                "    d['source_blobs'][path] = '2' * 40\n"
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'
                                '    mpath.write_text(good)\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is True\n'
                                '    # one byte in the successor manifest, in any owned file the successor depends on, or a missing manifest\n'
                                "    mpath.write_text(good + '}')                                                   # one byte that breaks the "
                                'manifest\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'
                                '    mpath.write_text(good)\n'
                                "    _flip(wt / 'tests/wf06b_scope.py')\n"
                                '    with C.call_scope():\n'
                                "        assert D.matches(path, raw, repo=wt) is False                                   # the successor's own bytes "
                                'are pinned\n'
                                "    _git(wt, 'checkout', '--', 'tests/wf06b_scope.py')\n"
                                '    mpath.unlink()\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'
                                "    _git(wt, 'checkout', '--', W.MANIFEST)\n"
                                '    # altered base identity and a forged predecessor\n'
                                "    monkeypatch.setattr(W, 'BASE_TREE', '0' * 40)\n"
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'
                                '    monkeypatch.undo()\n'
                                '    d = json.loads(good)\n'
                                "    d['base_blobs'][path] = '3' * 40\n"
                                "    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'
                                '    mpath.write_text(good)\n'
                                '    # an untracked executable anywhere\n'
                                "    exe = wt / 'app/sneaky.sh'\n"
                                "    exe.write_text('#!/bin/sh\\n')\n"
                                '    exe.chmod(0o755)\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'
                                '    exe.unlink()\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is True\n'
                                '    # deleting the owned source fails the whole composition\n'
                                '    (wt / path).unlink()\n'
                                '    with C.call_scope():\n'
                                '        assert D.matches(path, raw, repo=wt) is False\n'),
                               ('def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n'
                                '    import importlib\n'
                                '    with _one_outer_call():\n'
                                "        for modname in ('fin_v2_d01_scope', 'fin_v2_3_scope', 'fin_v2_r1_scope', 'fin_v2_rcux_scope', "
                                "'fin_v2_wsv2_scope'):\n"
                                "            D = importlib.import_module(f'tests.{modname}')\n"
                                "            for path in set(D.manifest().get('source_blobs', {})) - W.SUPERSEDED:\n"
                                '                raw = (W.ROOT / path).read_bytes()\n'
                                "                assert D.matches(path, raw + b'\\n') is False, (modname, path)\n"
                                "                assert not W.supersedes(path, W._blob(raw + b'\\n')), (modname, path)\n",
                                'def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n'
                                '    with C.call_scope():\n'
                                '        import importlib\n'
                                '        with _one_outer_call():\n'
                                "            for modname in ('fin_v2_d01_scope', 'fin_v2_3_scope', 'fin_v2_r1_scope', 'fin_v2_rcux_scope', "
                                "'fin_v2_wsv2_scope'):\n"
                                "                D = importlib.import_module(f'tests.{modname}')\n"
                                "                for path in set(D.manifest().get('source_blobs', {})) - W.SUPERSEDED:\n"
                                '                    raw = (W.ROOT / path).read_bytes()\n'
                                "                    assert D.matches(path, raw + b'\\n') is False, (modname, path)\n"
                                "                    assert not W.supersedes(path, W._blob(raw + b'\\n')), (modname, path)\n"),
                               ('def test_mutation_after_a_successful_check_restoration_and_a_different_mutation(wt):\n'
                                '    """Success, real mutation, restore, then a DIFFERENT mutation: every evaluation reads the real bytes."""\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    _flip(wt / 'tests/wf06b_scope.py')\n"
                                '    assert not W.exact_blobs_ok(wt)                  # one flipped byte fails closed\n'
                                "    _git(wt, 'checkout', '--', 'tests/wf06b_scope.py')\n"
                                '    assert W.exact_blobs_ok(wt)                      # restored byte-exactly\n'
                                "    (wt / 'app/cost_line_ledger/ledger.py').write_text('x = 1\\n')       # a different file, a different mutation\n"
                                '    assert not W.exact_blobs_ok(wt)                  # still fails closed\n'
                                "    _git(wt, 'checkout', '--', 'app/cost_line_ledger/ledger.py')\n"
                                '    assert W.exact_blobs_ok(wt)\n',
                                'def test_mutation_after_a_successful_check_restoration_and_a_different_mutation(wt):\n'
                                '    """Success, real mutation, restore, then a DIFFERENT mutation: every evaluation reads the real bytes."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    _flip(wt / 'tests/wf06b_scope.py')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                  # one flipped byte fails closed\n'
                                "    _git(wt, 'checkout', '--', 'tests/wf06b_scope.py')\n"
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)                      # restored byte-exactly\n'
                                "    (wt / 'app/cost_line_ledger/ledger.py').write_text('x = 1\\n')       # a different file, a different mutation\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                  # still fails closed\n'
                                "    _git(wt, 'checkout', '--', 'app/cost_line_ledger/ledger.py')\n"
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'),
                               ('def test_staged_index_and_untracked_bytes_are_judged_fresh(wt):\n'
                                '    """Staged tamper, generated untracked CI evidence and an untracked source file are each judged from the\n'
                                '    real evaluation, never from a remembered verdict."""\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    _flip(wt / 'tests/wf06b_scope.py')\n"
                                "    _git(wt, 'add', 'tests/wf06b_scope.py')          # staged, not only in the working tree\n"
                                '    assert not W.exact_blobs_ok(wt)                  # the staged bytes do not fool the real byte read\n'
                                "    _git(wt, 'reset', '-q')\n"
                                "    _git(wt, 'checkout', '--', 'tests/wf06b_scope.py')\n"
                                "    evidence = wt / 'evidence'                       # generated CI evidence does not exist until CI creates it\n"
                                '    evidence.mkdir()\n'
                                "    (evidence / 'probe.json').write_text('{}\\n')    # untracked generated CI evidence stays admitted\n"
                                '    assert W.exact_blobs_ok(wt)\n'
                                '    (evidence / \'probe.json\').write_text(\'{"runs": 2}\\n\')\n'
                                '    assert W.exact_blobs_ok(wt)                      # evidence bytes never change the verdict\n'
                                "    (wt / 'app/sneaky.py').write_text('x = 1\\n')\n"
                                '    assert not W.exact_blobs_ok(wt)                  # an untracked source file is still refused\n'
                                "    (wt / 'app/sneaky.py').unlink()\n"
                                "    (evidence / 'probe.json').unlink()\n"
                                '    evidence.rmdir()\n'
                                '    assert W.exact_blobs_ok(wt)\n',
                                'def test_staged_index_and_untracked_bytes_are_judged_fresh(wt):\n'
                                '    """Staged tamper, generated untracked CI evidence and an untracked source file are each judged from the\n'
                                '    real evaluation, never from a remembered verdict."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    _flip(wt / 'tests/wf06b_scope.py')\n"
                                "    _git(wt, 'add', 'tests/wf06b_scope.py')          # staged, not only in the working tree\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                  # the staged bytes do not fool the real byte read\n'
                                "    _git(wt, 'reset', '-q')\n"
                                "    _git(wt, 'checkout', '--', 'tests/wf06b_scope.py')\n"
                                "    evidence = wt / 'evidence'                       # generated CI evidence does not exist until CI creates it\n"
                                '    evidence.mkdir()\n'
                                "    (evidence / 'probe.json').write_text('{}\\n')    # untracked generated CI evidence stays admitted\n"
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                '    (evidence / \'probe.json\').write_text(\'{"runs": 2}\\n\')\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)                      # evidence bytes never change the verdict\n'
                                "    (wt / 'app/sneaky.py').write_text('x = 1\\n')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                  # an untracked source file is still refused\n'
                                "    (wt / 'app/sneaky.py').unlink()\n"
                                "    (evidence / 'probe.json').unlink()\n"
                                '    evidence.rmdir()\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'),
                               ('def test_a_patched_identity_constant_is_used_by_every_evaluation(wt, monkeypatch):\n'
                                '    """A forged governance identity constant is consulted by the real evaluation each time."""\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    monkeypatch.setattr(W, 'BASE_TREE', '0' * 40)\n"
                                '    assert not W.exact_blobs_ok(wt)\n'
                                '    monkeypatch.undo()\n'
                                '    assert W.exact_blobs_ok(wt)\n',
                                'def test_a_patched_identity_constant_is_used_by_every_evaluation(wt, monkeypatch):\n'
                                '    """A forged governance identity constant is consulted by the real evaluation each time."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    monkeypatch.setattr(W, 'BASE_TREE', '0' * 40)\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)\n'
                                '    monkeypatch.undo()\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'),
                               ('def test_same_cardinality_guard_identity_changes_cannot_reuse_a_prior_verdict(wt, monkeypatch):\n'
                                '    """Same-size swaps of the guard\'s literal identity (owned set / superseded set) must be seen by a fresh\n'
                                '    evaluation; a prior True must never survive a guard-identity change."""\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    forged_owned = frozenset((W.OWNED_PATHS - {'app/cost_line_ledger/capacity.py'}) | {'app/v2/router.py'})\n"
                                '    assert len(forged_owned) == len(W.OWNED_PATHS)\n'
                                "    monkeypatch.setattr(W, 'OWNED_PATHS', forged_owned)\n"
                                '    assert not W.exact_blobs_ok(wt)                  # the manifest no longer matches the forged owned set\n'
                                '    monkeypatch.undo()\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    forged_superseded = frozenset((W.SUPERSEDED - {'static/react/finco-react.css'}) | "
                                "{'app/cost_line_ledger/capacity.py'})\n"
                                '    assert len(forged_superseded) == len(W.SUPERSEDED)\n'
                                "    monkeypatch.setattr(W, 'SUPERSEDED', forged_superseded)\n"
                                '    data = W.manifest()\n'
                                "    assert not W.supersedes('static/react/finco-react.css', data['source_blobs']['static/react/finco-react.css'], "
                                'repo=wt)\n'
                                "    assert not W.supersedes('app/cost_line_ledger/capacity.py', '0' * 40, repo=wt)\n"
                                '    monkeypatch.undo()\n'
                                "    assert W.supersedes('static/react/finco-react.css', data['source_blobs']['static/react/finco-react.css'], "
                                'repo=wt)\n',
                                'def test_same_cardinality_guard_identity_changes_cannot_reuse_a_prior_verdict(wt, monkeypatch):\n'
                                '    """Same-size swaps of the guard\'s literal identity (owned set / superseded set) must be seen by a fresh\n'
                                '    evaluation; a prior True must never survive a guard-identity change."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    forged_owned = frozenset((W.OWNED_PATHS - {'app/cost_line_ledger/capacity.py'}) | {'app/v2/router.py'})\n"
                                '    assert len(forged_owned) == len(W.OWNED_PATHS)\n'
                                "    monkeypatch.setattr(W, 'OWNED_PATHS', forged_owned)\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                  # the manifest no longer matches the forged owned set\n'
                                '    monkeypatch.undo()\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    forged_superseded = frozenset((W.SUPERSEDED - {'static/react/finco-react.css'}) | "
                                "{'app/cost_line_ledger/capacity.py'})\n"
                                '    assert len(forged_superseded) == len(W.SUPERSEDED)\n'
                                "    monkeypatch.setattr(W, 'SUPERSEDED', forged_superseded)\n"
                                '    data = W.manifest()\n'
                                '    with C.call_scope():\n'
                                "        assert not W.supersedes('static/react/finco-react.css', "
                                "data['source_blobs']['static/react/finco-react.css'], repo=wt)\n"
                                '    with C.call_scope():\n'
                                "        assert not W.supersedes('app/cost_line_ledger/capacity.py', '0' * 40, repo=wt)\n"
                                '    monkeypatch.undo()\n'
                                '    with C.call_scope():\n'
                                "        assert W.supersedes('static/react/finco-react.css', data['source_blobs']['static/react/finco-react.css'], "
                                'repo=wt)\n'),
                               ('def test_a_mutated_worktree_is_judged_independently_of_the_real_tree(wt):\n'
                                '    """Multi-repo / temp-root separation: each evaluated root gets its own real evaluation."""\n'
                                '    assert W.exact_blobs_ok() and W.exact_blobs_ok(wt)\n'
                                "    _flip(wt / 'static/react/finco-react.js')\n"
                                '    assert not W.exact_blobs_ok(wt)                  # the mutated worktree fails closed...\n'
                                '    assert W.exact_blobs_ok()                        # ...while the real tree still validates\n'
                                '    assert not W.exact_blobs_ok(wt)\n',
                                'def test_a_mutated_worktree_is_judged_independently_of_the_real_tree(wt):\n'
                                '    """Multi-repo / temp-root separation: each evaluated root gets its own real evaluation."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok() and W.exact_blobs_ok(wt)\n'
                                "    _flip(wt / 'static/react/finco-react.js')\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)                  # the mutated worktree fails closed...\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok()                        # ...while the real tree still validates\n'
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt)\n'),
                               ('def test_bytes_hidden_from_git_diff_by_assume_unchanged_are_rejected(wt):\n'
                                '    """Correction A counterexample 2: `update-index --assume-unchanged` hides a real byte mutation from\n'
                                '    `git diff`; the exact check reads the real file bytes, so the tamper must still fail closed."""\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    victim = 'tests/wf06b_scope.py'\n"
                                "    _git(wt, 'update-index', '--assume-unchanged', victim)\n"
                                "    (wt / victim).write_bytes((wt / victim).read_bytes() + b'\\n# TAMPER\\n')\n"
                                "    assert subprocess.check_output(['git', '-C', str(wt), 'diff', 'HEAD', '--no-ext-diff', '--binary', '--']) == "
                                "b''\n"
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)      # the real bytes are read directly\n'
                                "    _git(wt, 'update-index', '--no-assume-unchanged', victim)\n"
                                "    _git(wt, 'checkout', '--', victim)\n"
                                '    assert W.exact_blobs_ok(wt)\n',
                                'def test_bytes_hidden_from_git_diff_by_assume_unchanged_are_rejected(wt):\n'
                                '    """Correction A counterexample 2: `update-index --assume-unchanged` hides a real byte mutation from\n'
                                '    `git diff`; the exact check reads the real file bytes, so the tamper must still fail closed."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    victim = 'tests/wf06b_scope.py'\n"
                                "    _git(wt, 'update-index', '--assume-unchanged', victim)\n"
                                "    (wt / victim).write_bytes((wt / victim).read_bytes() + b'\\n# TAMPER\\n')\n"
                                "    assert subprocess.check_output(['git', '-C', str(wt), 'diff', 'HEAD', '--no-ext-diff', '--binary', '--']) == "
                                "b''\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)      # the real bytes are read directly\n'
                                "    _git(wt, 'update-index', '--no-assume-unchanged', victim)\n"
                                "    _git(wt, 'checkout', '--', victim)\n"
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'),
                               ('def test_executable_mode_change_hidden_from_git_diff_is_rejected(wt):\n'
                                '    """Correction A counterexample 1 (POSIX): with `core.filemode false` git hides a real mode change from\n'
                                '    `git diff`; the exact check stats the file itself, so the executable bit must fail closed. On Windows/NTFS\n'
                                '    a chmod cannot represent the POSIX executable bit — the same environmental limitation as\n'
                                '    test_extra_tracked_extra_untracked_and_executable_paths_fail_closed above — so the full sequence can only\n'
                                '    be exercised on a POSIX host (the CI runners)."""\n'
                                '    assert W.exact_blobs_ok(wt)\n'
                                "    _git(wt, 'config', 'core.filemode', 'false')\n"
                                "    victim = wt / 'app/cost_line_ledger/ledger.py'\n"
                                '    victim.chmod(0o755)\n'
                                '    if victim.stat().st_mode & 0o111 == 0:\n'
                                "        pytest.skip('POSIX-only: this host cannot represent the POSIX executable bit (NTFS)')\n"
                                "    assert subprocess.check_output(['git', '-C', str(wt), 'diff', 'HEAD', '--no-ext-diff', '--binary', '--']) == "
                                "b''\n"
                                '    assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                '    victim.chmod(0o644)\n'
                                '    assert W.exact_blobs_ok(wt)\n',
                                'def test_executable_mode_change_hidden_from_git_diff_is_rejected(wt):\n'
                                '    """Correction A counterexample 1 (POSIX): with `core.filemode false` git hides a real mode change from\n'
                                '    `git diff`; the exact check stats the file itself, so the executable bit must fail closed. On Windows/NTFS\n'
                                '    a chmod cannot represent the POSIX executable bit — the same environmental limitation as\n'
                                '    test_extra_tracked_extra_untracked_and_executable_paths_fail_closed above — so the full sequence can only\n'
                                '    be exercised on a POSIX host (the CI runners)."""\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n'
                                "    _git(wt, 'config', 'core.filemode', 'false')\n"
                                "    victim = wt / 'app/cost_line_ledger/ledger.py'\n"
                                '    victim.chmod(0o755)\n'
                                '    if victim.stat().st_mode & 0o111 == 0:\n'
                                "        pytest.skip('POSIX-only: this host cannot represent the POSIX executable bit (NTFS)')\n"
                                "    assert subprocess.check_output(['git', '-C', str(wt), 'diff', 'HEAD', '--no-ext-diff', '--binary', '--']) == "
                                "b''\n"
                                '    with C.call_scope():\n'
                                '        assert not W.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                '    victim.chmod(0o644)\n'
                                '    with C.call_scope():\n'
                                '        assert W.exact_blobs_ok(wt)\n')],
 'tests/u1_scope.py': [("'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')\n\n\nclass _Discovered:",
                        "'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_shard2_fix_scope')\n\n\nclass _Discovered:"),
                       ("    if path not in ('frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/styles/compact-inputs.css',",
                        '    from tests import ci_v4_shard2_fix_scope as S2\n'
                        '    if path in S2.SUPERSEDED:       # CI V4 shard-2 fix: the finite signed successor chain (C06 forwards to it) may move '
                        'these exact pins too\n'
                        '        from tests import c06_cost_workspace_scope as C06\n'
                        '        return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                        "    if path not in ('frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/styles/compact-inputs.css',")],
 'tests/u2_scope.py': [("    if path not in ('frontend/src/app/capex/profileFocus.ts', 'frontend/src/app/editing/CostLinesGridView.tsx',",
                        '    from tests import ci_v4_shard2_fix_scope as S2\n'
                        '    if path in S2.SUPERSEDED:       # CI V4 shard-2 fix: the finite signed successor chain (C06 forwards to it) may move '
                        'these exact pins too\n'
                        '        from tests import c06_cost_workspace_scope as C06\n'
                        '        return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                        "    if path not in ('frontend/src/app/capex/profileFocus.ts', 'frontend/src/app/editing/CostLinesGridView.tsx',"),
                       ('def supersedes(path, value, repo=None, ref=None):\n'
                        '    if path in ("frontend/src/app/editing/CostLinesGridView.tsx", "frontend/src/app/CostWorkbench.tsx",',
                        'def supersedes(path, value, repo=None, ref=None):\n'
                        '    from tests import ci_v4_shard2_fix_scope as S2\n'
                        '    if path in S2.SUPERSEDED and _c06_pin(path, value, ROOT if repo is None else Path(repo), ref):\n'
                        '        return True\n'
                        '    if path in ("frontend/src/app/editing/CostLinesGridView.tsx", "frontend/src/app/CostWorkbench.tsx",')],
 'tests/ux_pr1_scope.py': [('def supersedes(path,value,repo=None,ref=None):\n'
                            '    S=_pr2a()\n'
                            '    if path not in SUPERSEDED or not exact_blobs_ok(repo,ref):\n'
                            '        return False\n',
                            'def supersedes(path,value,repo=None,ref=None):\n'
                            '    S=_pr2a()\n'
                            '    if path not in SUPERSEDED or not exact_blobs_ok(repo,ref):\n'
                            '        return False\n'
                            '    from tests import ci_v4_shard2_fix_scope as S2\n'
                            '    if path in S2.SUPERSEDED:       # CI V4 shard-2 fix: the finite signed successor chain (C06 forwards to it) follows '
                            'this pin\n'
                            '        from tests import c06_cost_workspace_scope as C06\n'
                            '        if C06.signature_ok(repo,ref) and C06.supersedes(path,value,repo,ref):\n'
                            '            return True\n')],
 'tests/ux_pr2b_scope.py': [("    if path in ('frontend/src/app/capex/ProfileDraftProvider.tsx', 'frontend/src/app/capex/ProfileRowEditor.tsx', ",
                             '    from tests import ci_v4_shard2_fix_scope as S2\n'
                             "    if path in S2.SUPERSEDED or path in ('frontend/src/app/capex/ProfileDraftProvider.tsx', "
                             "'frontend/src/app/capex/ProfileRowEditor.tsx', ")],
 'tests/ux_pr2c_scope.py': [("    if path in ('frontend/src/app/capex/ProfileDraftProvider.tsx',):\n"
                             '        from tests import c06_cost_workspace_scope as C06\n',
                             '    from tests import ci_v4_shard2_fix_scope as S2\n'
                             "    if path in S2.SUPERSEDED or path in ('frontend/src/app/capex/ProfileDraftProvider.tsx',):\n"
                             '        from tests import c06_cost_workspace_scope as C06\n')],
 'tests/ux_pr3b1_scope.py': [('    if path in ("frontend/src/app/editing/CostLinesGridView.tsx", "tests/ux_pr3b1_scope.py", '
                              '"frontend/src/app/CostWorkbench.tsx"):\n',
                              '    from tests import ci_v4_shard2_fix_scope as S2\n'
                              '    if path in S2.SUPERSEDED or path in ("frontend/src/app/editing/CostLinesGridView.tsx", "tests/ux_pr3b1_scope.py", '
                              '"frontend/src/app/CostWorkbench.tsx"):\n')]}


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
    """Pure function of an immutable BASE map and the literal moved pins."""
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
        # Registered exactly once, as the immediate successor of C06 and the LAST entry (acyclic, strictly ordered, no duplicate, no foreign tail).
        if COHORT_MODULES.count(__name__) != 1 or COHORT_MODULES[-2:] != (PREDECESSOR.replace("/", ".")[:-3], __name__):
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if d.get("source_modes") != {p: "100644" for p in OWNED_PATHS} or d.get("base_modes") != {p: "100644" for p in SUPERSEDED}:
            return False
        if any(_base_mode(str(root), p) != d["base_modes"][p] for p in SUPERSEDED):
            return False
        if not NEW.isdisjoint(base) or any((p.startswith(FORBIDDEN) and p not in CI_TOOL_PATHS) or p.startswith("/") or ".." in p.split("/") or "*" in p
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
        if any(current.get(p) != _base_blob(key, p) or modes.get(p) != _base_mode(key, p) for p in FROZEN):
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


def write_manifest(repo=None):
    """Maintainer helper (python -m tests.ci_v4_shard2_fix_scope): derive every pin from BASE and the literals above, never from a stale manifest.
    Handoff and map pins are PURE functions of BASE + literals; source and new-file pins are the current working-tree bytes. Never called by a check."""
    root = Path(repo) if repo is not None else ROOT
    key = str(root)
    pins = {p: _blob((root / p).read_bytes()) for p in sorted(SOURCE_PATHS | NEW)}
    pins.update({p: _expected_blob(key, p) for p in sorted(HANDOFFS)})
    for p in sorted(CURRENT_MAPS):
        pins[p] = None
    for p in sorted(CURRENT_MAPS):
        pins[p] = _blob(expected_map(root, p, pins))
    data = {"schema_version": SCHEMA, "authorization": AUTHORIZATION, "base": BASE, "base_tree": BASE_TREE,
            "base_blobs": {p: _base_blob(key, p) for p in sorted(SUPERSEDED)}, "source_blobs": dict(sorted(pins.items())),
            "base_modes": {p: _base_mode(key, p) for p in sorted(SUPERSEDED)}, "source_modes": {p: "100644" for p in sorted(OWNED_PATHS)}}
    (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\n").encode())
    for p in sorted(CURRENT_MAPS):
        (root / p).write_bytes(expected_map(root, p, pins))
    return data


if __name__ == "__main__":
    write_manifest()

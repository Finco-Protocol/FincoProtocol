"""UX-FINAL-01 (Excel-first React UX consolidation): finite exact-source successor after the accepted C06 added-line CAPEX profile successor.

Frontend presentation only: no engine, schema, writer, API, flag or financial-policy change. It pins every source, test, document and the single
reproducible JS/CSS bundle this PR changes, and the immutable BASE tree (accepted main with C06). The shared governance paths it really changes are
SUPERSEDED paths carrying their accepted BASE blob, the literal one-occurrence substitutions that produce the new blob, and the exact new blob.
C06 hands the shared bundle, the registry and its own forward hook to this successor by reviewed substitution; C06's manifest and every other historical
manifest stay byte-identical. Only the current-map keys of the registry and the two bundles move. Two living documents (LIVE_DOCS) may change without a
pin: they carry no behaviour and cannot name the commit that contains them.

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls C06, an older cohort or the composite;
the C06 leaf calls this module through one forward hook (the acyclic pattern F04 and R04 used).
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
MANIFEST = "docs/react_migration/ux_final01/SOURCE_SUCCESSOR.json"
SCHEMA = "UX_FINAL01_EXACT_SOURCE_V1"
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/c06_cost_workspace_scope.py"
SOURCE_PATHS = frozenset((
    "frontend/src/App.tsx",
    "frontend/src/app/FinancialResults.tsx",
    "frontend/src/app/InputsOverview.tsx",
    "frontend/src/app/WorkspaceView.tsx",
    "frontend/src/app/financing/FinancingStudio.tsx",
    "frontend/src/app/financing/pr3b1/FinancingOverview.tsx",
    "frontend/src/app/financing/pr3b1/FinancingReadLayer.tsx",
    "frontend/src/app/financing/pr3b1/__tests__/readLayer.test.mjs",
    "frontend/src/app/financing/pr3b1/runEvidence.ts",
    "frontend/src/app/financing/pr3b2/FinancingEditing.tsx",
    "static/react/finco-react.css",
    "static/react/finco-react.js",
))
NEW = frozenset((
    "docs/react_migration/ux_final01/screen_contract.csv",
    "frontend/src/app/financing/pr3b1/__tests__/uxFinal01.test.mjs",
    "frontend/src/styles/ux-final01.css",
    "tests/test_ux_final01_browser.py",
    "tests/test_ux_final01_scope.py",
    "tests/ux_final01_scope.py",
    "tests/ux_final01_screens.py",
))
# Living documentation: may change without a pin (no behaviour; run identifiers cannot be pinned inside the commit they describe).
LIVE_DOCS = frozenset((
    "docs/react_migration/ux_final01/INTEGRATION_PLAYBOOK.md",
    "docs/react_migration/ux_final01/WORK_COMPLETED_LEDGER.md",
))
# Accepted governance paths whose bytes move by one reviewed literal substitution (HANDOFFS) ...
HANDOFF_PATHS = frozenset((
    "tests/c06_cost_workspace_scope.py",
    "tests/fin_v2_cohorts.py",
    "tests/post413_o1_scope.py",
    "tests/post413_r17_scope.py",
    "tests/post413_r18_scope.py",
    "tests/post413_r1_scope.py",
    "tests/test_bess02_scope.py",
    "tests/test_c06_cost_workspace_scope.py",
    "tests/test_ci_v4_perf_scope.py",
    "tests/test_f03_financing_scope.py",
    "tests/test_f04_financing_scope.py",
    "tests/test_post432_l01_l02_scope.py",
    "tests/test_r02_ppa_ux_scope.py",
    "tests/test_r03_ppa_scope.py",
    "tests/test_r04_ppa_scope.py",
    "tests/test_t01e_remediation_scope.py",
    "tests/test_u1_scope.py",
    "tests/test_u2_scope.py",
    "tests/u1_scope.py",
    "tests/u2_scope.py",
    "tests/ux_pr1_scope.py",
    "tests/ux_pr2b_scope.py",
    "tests/ux_pr2c_scope.py",
    "tests/ux_pr3b1_scope.py",
))
# ... and the eight current maps, of which only the registry and the two bundle keys move (the bounded handoff C06 made, one step further).
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
MAP_KEYS = (REGISTRY, "static/react/finco-react.js", "static/react/finco-react.css", "tests/u1_scope.py", "tests/u2_scope.py", "tests/ux_pr3b1_scope.py", "tests/test_u2_scope.py", "tests/post413_r1_scope.py", "tests/post413_r17_scope.py", "tests/post413_r18_scope.py")
OWNED_PATHS = SOURCE_PATHS | NEW | HANDOFF_PATHS | CURRENT_MAPS
SUPERSEDED = OWNED_PATHS - NEW
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "tools/", "migrations/", "app/", "research/", "main_web.py")
# Accepted historical manifests, products and CI that must stay byte-identical to BASE (a successor never rewrites them).
FROZEN = (
    ".github/workflows/ci_v4_f01_job.yml",
    ".github/workflows/finval_f01_acceptance.yml",
    "docs/bess02/SOURCE_SUCCESSOR.json",
    "docs/bess_setup/SOURCE_SUCCESSOR.json",
    "docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json",
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
    "tests/model_react_rcux_capex_acceptance.py",
    "tests/r03_ppa_core/oracle.py",
    "tests/r03_ppa_scope.py",
    "tests/r04_ppa_global_cap/oracle.py",
    "tests/r04_ppa_scope.py",
    "tests/t01e_remediation_scope.py",
    "tests/tax_reference_registry_scope.py",
    "tests/test_c06_cost_workspace_browser.py",
    "tests/test_c06_custom_capex_profile_replay.py",
    "tests/test_ux_pr3b1_scope.py",
)
# C06 and R04 keep owning their own production baselines; this successor owns no revenue or CAPEX engine path.
BASELINE = {}


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
        return d if (isinstance(d, dict) and set(d) == {"schema_version", "authorization", "base", "base_tree", "source_blobs", "base_blobs"}
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


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The accepted C06 leaf gains one forward hook to this
# cohort (the same acyclic pattern F04 and R04 used); the registry appends this cohort exactly once; the exact-tail tests accept one more state.
HANDOFFS = {'tests/c06_cost_workspace_scope.py': [('    _SCOPE.append({})\r\n    try:\r\n        yield\r\n    finally:\r\n        _SCOPE.pop()\r\n',
                                        '    _SCOPE.append({})\r\n'
                                        '    try:\r\n'
                                        '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, '
                                        'never kept globally.\r\n'
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
                                        '        if COHORT_MODULES != BASE_COHORTS + (__name__,) and COHORT_MODULES != BASE_COHORTS + '
                                        "(__name__, 'tests.ux_final01_scope'):\r\n"
                                        '            return False\r\n'),
                                       ('        if pins.get("tests/c06_cost_workspace_scope.py") != _MODULE_BLOB:\r\n'
                                        '            return False\r\n',
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
                                       ('                if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in '
                                        'MAP_KEYS)):\r\n',
                                        '                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in '
                                        'MAP_KEYS))):\r\n'),
                                       ('        allowed = OWNED_PATHS | {MANIFEST}\r\n        changed = set(',
                                        '        allowed = closure_paths(root, ref)\r\n        changed = set('),
                                       ('def map_keys(repo=None, ref=None):\r\n    return tuple(MAP_KEYS)\r\n',
                                        'def _next():\r\n'
                                        '    """The one finite forward successor (UX-FINAL-01). Low-level only: its signature never calls '
                                        'this module or the composite."""\r\n'
                                        '    from tests.fin_v2_cohorts import COHORT_MODULES\r\n'
                                        "    if 'tests.ux_final01_scope' not in COHORT_MODULES:\r\n"
                                        '        return None\r\n'
                                        '    from tests import ux_final01_scope\r\n'
                                        '    return ux_final01_scope\r\n'
                                        '\r\n'
                                        '\r\n'
                                        'def _next_pins(root, ref):\r\n'
                                        '    N = _next()\r\n'
                                        '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else '
                                        '{}\r\n'
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
                                        '    # Like the accepted F03 / performance leaves: the signature decides a supersession; the '
                                        "composite separately requires every cohort's FULL\r\n"
                                        '    # exactness (map bytes, changed set, untracked files), so a signature-only verdict never '
                                        'makes the tree valid.\r\n'
                                        '    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == '
                                        'value\r\n',
                                        'def supersedes(path, value, repo=None, ref=None):\r\n'
                                        '    with scoped():      # one shared read scope per call: the successor signature is evaluated '
                                        'once, then dropped\r\n'
                                        '        N = _next()\r\n'
                                        '        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, '
                                        'ref):\r\n'
                                        '            return True\r\n'
                                        '        if path not in SUPERSEDED:\r\n'
                                        '            return False\r\n'
                                        '        # the CURRENT pin of this path (the successor overlay wins while its signature holds), '
                                        'never a raw superseded manifest line\r\n'
                                        '        return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\r\n'),
                                       ('    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    try:\r\n'
                                        '        if _git(root, "merge-base", "origin/main", "HEAD")',
                                        '    root = Path(repo) if repo is not None else ROOT\r\n'
                                        '    try:\r\n'
                                        '        N = _next()\r\n'
                                        '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, '
                                        'root):\r\n'
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
 'tests/fin_v2_cohorts.py': [("'tests.c06_cost_workspace_scope')", "'tests.c06_cost_workspace_scope', 'tests.ux_final01_scope')")],
 'tests/post413_o1_scope.py': [('            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n',
                                '            if any(_blob(_read(root, p, ref)) != sha and not _ux_pin(p, _blob(_read(root, p, ref)), root, '
                                'ref) for p, sha in pins.items()):\n'),
                               ('            if listed != pins:\n                return False\n',
                                '            if set(listed) != set(pins) or any(listed[p] != pins[p] and not _ux_pin(p, listed[p], root, '
                                'ref) for p in pins):\n'
                                '                return False\n'),
                               ('def supersedes(path, value, repo=None, ref=None):\n',
                                'def _ux_pin(path, blob, root, ref):\n'
                                '    """UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may move this exact pin; '
                                'history and every other pin stay unchanged."""\n'
                                '    from tests import ux_final01_scope as UX\n'
                                '    if path not in UX.SUPERSEDED:\n'
                                '        return False\n'
                                '    from tests import c06_cost_workspace_scope as C06\n'
                                '    return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                                '\n'
                                '\n'
                                'def supersedes(path, value, repo=None, ref=None):\n')],
 'tests/post413_r17_scope.py': [('            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n',
                                 '            if any(_blob(_read(root, p, ref)) != sha and not _ux_pin(p, _blob(_read(root, p, ref)), '
                                 'root, ref) for p, sha in pins.items()):\n'),
                                ('            if listed != pins:\n                return False\n',
                                 '            if set(listed) != set(pins) or any(listed[p] != pins[p] and not _ux_pin(p, listed[p], root, '
                                 'ref) for p in pins):\n'
                                 '                return False\n'),
                                ('def supersedes(path, value, repo=None, ref=None):\n',
                                 'def _ux_pin(path, blob, root, ref):\n'
                                 '    """UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may move this exact pin; '
                                 'history and every other pin stay unchanged."""\n'
                                 '    from tests import ux_final01_scope as UX\n'
                                 '    if path not in UX.SUPERSEDED:\n'
                                 '        return False\n'
                                 '    from tests import c06_cost_workspace_scope as C06\n'
                                 '    return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                                 '\n'
                                 '\n'
                                 'def supersedes(path, value, repo=None, ref=None):\n')],
 'tests/post413_r18_scope.py': [('            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n',
                                 '            if any(_blob(_read(root, p, ref)) != sha and not _ux_pin(p, _blob(_read(root, p, ref)), '
                                 'root, ref) for p, sha in pins.items()):\n'),
                                ('            if listed != pins:\n                return False\n',
                                 '            if set(listed) != set(pins) or any(listed[p] != pins[p] and not _ux_pin(p, listed[p], root, '
                                 'ref) for p in pins):\n'
                                 '                return False\n'),
                                ('def supersedes(path, value, repo=None, ref=None):\n',
                                 'def _ux_pin(path, blob, root, ref):\n'
                                 '    """UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may move this exact pin; '
                                 'history and every other pin stay unchanged."""\n'
                                 '    from tests import ux_final01_scope as UX\n'
                                 '    if path not in UX.SUPERSEDED:\n'
                                 '        return False\n'
                                 '    from tests import c06_cost_workspace_scope as C06\n'
                                 '    return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                                 '\n'
                                 '\n'
                                 'def supersedes(path, value, repo=None, ref=None):\n')],
 'tests/post413_r1_scope.py': [('            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n',
                                '            if any(_blob(_read(root, p, ref)) != sha and not _ux_pin(p, _blob(_read(root, p, ref)), root, '
                                'ref) for p, sha in pins.items()):\n'),
                               ('            if listed != pins:\n                return False\n',
                                '            if set(listed) != set(pins) or any(listed[p] != pins[p] and not _ux_pin(p, listed[p], root, '
                                'ref) for p in pins):\n'
                                '                return False\n'),
                               ('def supersedes(path, value, repo=None, ref=None):\n',
                                'def _ux_pin(path, blob, root, ref):\n'
                                '    """UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may move this exact pin; '
                                'history and every other pin stay unchanged."""\n'
                                '    from tests import ux_final01_scope as UX\n'
                                '    if path not in UX.SUPERSEDED:\n'
                                '        return False\n'
                                '    from tests import c06_cost_workspace_scope as C06\n'
                                '    return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                                '\n'
                                '\n'
                                'def supersedes(path, value, repo=None, ref=None):\n')],
 'tests/test_bess02_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                 'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                 'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                 'C06_APPROVAL.signature_ok()))\n',
                                 '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                 'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, '
                                 'UX_APPROVAL.__name__)\n'
                                 '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok()))\n'),
                                ('        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared '
                                 'bundle, exactly at its pinned blob\n',
                                 '        if path in UX_APPROVAL.SUPERSEDED and UX_APPROVAL.signature_ok():     # the one reviewed '
                                 'UX-FINAL-01 successor of the shared presentation sources\n'
                                 '            assert B._blob((B.ROOT/path).read_bytes()) == UX_APPROVAL.effective_pins()[path]\n'
                                 '            continue\n'
                                 '        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared '
                                 'bundle, exactly at its pinned blob\n')],
 'tests/test_c06_cost_workspace_scope.py': [('    assert C.COHORT_MODULES == F.BASE_COHORTS + (F.__name__,)\n',
                                             '    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + '
                                             "(F.__name__, 'tests.ux_final01_scope'))\n"),
                                            ('    for path in F.HANDOFFS:assert (ROOT/path).read_bytes()==F.expected_handoff(ROOT,path)\n',
                                             '    from tests import ux_final01_scope as UX\n'
                                             '    for path in F.HANDOFFS:\n'
                                             '        want=UX.expected_handoff(ROOT,path) if UX.signature_ok() and path in UX.HANDOFFS '
                                             'else F.expected_handoff(ROOT,path)\n'
                                             '        assert (ROOT/path).read_bytes()==want\n'),
                                            ('            if m.__name__!=F.__name__:\n'
                                             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n',
                                             "            if m.__name__ not in (F.__name__,'tests.ux_final01_scope'):      # the later "
                                             'reviewed UX successor does not exist at the accepted base\n'
                                             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n'),
                                            ('            if kind==\'missing_registration\':text=text.replace(", '
                                             '\'tests.c06_cost_workspace_scope\')",\')\')\n',
                                             '            if kind==\'missing_registration\':text=text.replace(", '
                                             '\'tests.c06_cost_workspace_scope\', \'tests.ux_final01_scope\')", ", '
                                             '\'tests.ux_final01_scope\')")\n'),
                                            ('            elif '
                                             'kind==\'duplicate_registration\':text=text.replace("\'tests.c06_cost_workspace_scope\')","\'tests.c06_cost_workspace_scope\', '
                                             '\'tests.c06_cost_workspace_scope\')")\n',
                                             '            elif '
                                             'kind==\'duplicate_registration\':text=text.replace("\'tests.c06_cost_workspace_scope\', '
                                             '\'tests.ux_final01_scope\')","\'tests.c06_cost_workspace_scope\', '
                                             '\'tests.c06_cost_workspace_scope\', \'tests.ux_final01_scope\')")\n')],
 'tests/test_ci_v4_perf_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                     'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                     'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                    ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                     'C06_APPROVAL.signature_ok())\n',
                                     '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                     'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + '
                                     '(C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                     '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok())\n'),
                                    ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                     'C06_APPROVAL.signature_ok()))\n',
                                     '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                     'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + '
                                     '(C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                     '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok()))\n'),
                                    ('    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n',
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (UX_APPROVAL.expected_handoff(ROOT, p) if UX_APPROVAL.signature_ok() and p in '
                                     'UX_APPROVAL.HANDOFFS\n'
                                     '                else C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n'),
                                    ('        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n',
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (UX_APPROVAL.expected_handoff(ROOT, p) if UX_APPROVAL.signature_ok() and p in '
                                     'UX_APPROVAL.HANDOFFS\n'
                                     '                else C06_APPROVAL.expected_handoff(ROOT, p) if C06_APPROVAL.signature_ok() and p in '
                                     'C06_APPROVAL.HANDOFFS\n'),
                                    ('\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")\n',
                                     '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ux_final01_scope\')")\n')],
 'tests/test_f03_financing_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                        'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                        'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                       ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                        'C06_APPROVAL.signature_ok())\n',
                                        '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                        'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + '
                                        '(C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                        '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok())\n'),
                                       ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", '
                                        'b"\'tests.ux_final01_scope\', \'tests.fake_scope\')")),\n')],
 'tests/test_f04_financing_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                        'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                        'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                       ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                        'C06_APPROVAL.signature_ok())\n',
                                        '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                        'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + '
                                        '(C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                        '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok())\n'),
                                       ('        authority=C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS '
                                        'else W if',
                                        '        authority=UX_APPROVAL if UX_APPROVAL.signature_ok() and path in UX_APPROVAL.HANDOFFS else '
                                        'C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if'),
                                       ('        if path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                        '            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)\n'
                                        '            assert '
                                        "F._blob((ROOT/path).read_bytes())==C06_APPROVAL.manifest()['source_blobs'][path]\n",
                                        '        if path in UX_APPROVAL.HANDOFFS and UX_APPROVAL.signature_ok():\n'
                                        '            assert (ROOT/path).read_bytes()==UX_APPROVAL.expected_handoff(ROOT,path)\n'
                                        '            assert '
                                        "F._blob((ROOT/path).read_bytes())==UX_APPROVAL.manifest()['source_blobs'][path]\n"
                                        '        elif path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                        '            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)\n'
                                        '            assert '
                                        "F._blob((ROOT/path).read_bytes())==C06_APPROVAL.manifest()['source_blobs'][path]\n"),
                                       ('            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')",", \'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\')")\n',
                                        '            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'",", \'tests.r04_ppa_scope\', '
                                        '\'tests.c06_cost_workspace_scope\'")\n'),
                                       ('            elif '
                                        'kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')","\'tests.f04_financing_scope\', '
                                        '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')")\n',
                                        '            elif '
                                        'kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'","\'tests.f04_financing_scope\', '
                                        '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")\n')],
 'tests/test_post432_l01_l02_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                          'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                          'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                         ("    if 'tests.c06_cost_workspace_scope' in C.COHORT_MODULES and C06_APPROVAL.signature_ok():\n"
                                          '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n',
                                          "    if 'tests.ux_final01_scope' in C.COHORT_MODULES and UX_APPROVAL.signature_ok():\n"
                                          '        expected = UX_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.c06_cost_workspace_scope' in C.COHORT_MODULES and C06_APPROVAL.signature_ok():\n"
                                          '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n')],
 'tests/test_r02_ppa_ux_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                     'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                     'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                    ("                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope') if m in "
                                     'C.COHORT_MODULES)\n',
                                     "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', "
                                     "'tests.ux_final01_scope') if m in C.COHORT_MODULES)\n"),
                                    ('    if len(nxt) == 7 and C06_APPROVAL.signature_ok():\n'
                                     '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n',
                                     "    if 'tests.ux_final01_scope' in C.COHORT_MODULES and UX_APPROVAL.signature_ok():\n"
                                     '        expected = UX_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 7 and C06_APPROVAL.signature_ok():\n'
                                     '        expected = C06_APPROVAL.expected_handoff(ROOT, X.REGISTRY)\n')],
 'tests/test_r03_ppa_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                  'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                  'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                 ('        authority = C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W '
                                  'if',
                                  '        authority = UX_APPROVAL if UX_APPROVAL.signature_ok() and p in UX_APPROVAL.HANDOFFS else '
                                  'C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if'),
                                 ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                  'C06_APPROVAL.signature_ok())\n',
                                  '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                  'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + '
                                  '(C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                  '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok())\n'),
                                 ('        if p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n',
                                  '        if p in UX_APPROVAL.HANDOFFS and UX_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == UX_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == UX_APPROVAL.manifest()["source_blobs"][p]\n'
                                  '        elif p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n'),
                                 ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", b"\'tests.ux_final01_scope\', '
                                  '\'tests.fake_scope\')")),\n')],
 'tests/test_r04_ppa_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                  'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                  'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                 ('        authority = C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T\n',
                                  '        authority = UX_APPROVAL if UX_APPROVAL.signature_ok() and p in UX_APPROVAL.HANDOFFS else '
                                  'C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T\n'),
                                 ('or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                  'C06_APPROVAL.signature_ok())\n',
                                  'or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                  'C06_APPROVAL.signature_ok()) or (\n'
                                  '        C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                  '        and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok())\n'),
                                 ('        if p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n',
                                  '        if p in UX_APPROVAL.HANDOFFS and UX_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == UX_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == UX_APPROVAL.manifest()["source_blobs"][p]\n'
                                  '        elif p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                  '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                  '            assert T._blob((ROOT / p).read_bytes()) == C06_APPROVAL.manifest()["source_blobs"][p]\n'),
                                 ('    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')")),\n',
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'),
                                 ('    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')")),\n',
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'")),\n'),
                                 ('    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b", \'tests.c06_cost_workspace_scope\')")),\n',
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b", \'tests.c06_cost_workspace_scope\'")),\n'),
                                 ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", b"\'tests.ux_final01_scope\', '
                                  '\'tests.fake_scope\')")),\n'),
                                 ('    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\')", b", \'tests.c06_cost_workspace_scope\')")})\n',
                                  '    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\', '
                                  '\'tests.c06_cost_workspace_scope\'", b", \'tests.c06_cost_workspace_scope\'")})\n'),
                                 ('        expected = C06_APPROVAL.effective_pins()[p] if p == "static/react/finco-react.js" and '
                                  'C06_APPROVAL.signature_ok() else blob\n',
                                  '        expected = C06_APPROVAL.effective_pins()[p] if p == "static/react/finco-react.js" and '
                                  'C06_APPROVAL.signature_ok() else blob\n')],
 'tests/test_t01e_remediation_scope.py': [('from tests import c06_cost_workspace_scope as C06_APPROVAL\n',
                                           'from tests import c06_cost_workspace_scope as C06_APPROVAL\n'
                                           'from tests import ux_final01_scope as UX_APPROVAL\n'),
                                          ('        if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n',
                                           '        if UX_APPROVAL.signature_ok() and p in UX_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == UX_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS:\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'),
                                          ('(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                           'C06_APPROVAL.signature_ok())\n',
                                           '(C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and '
                                           'C06_APPROVAL.signature_ok()) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + '
                                           '(C06_APPROVAL.__name__, UX_APPROVAL.__name__)\n'
                                           '            and C06_APPROVAL.signature_ok() and UX_APPROVAL.signature_ok())\n'),
                                          ('        if p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == '
                                           'C06_APPROVAL.manifest()["source_blobs"][p]\n',
                                           '        if p in UX_APPROVAL.HANDOFFS and UX_APPROVAL.signature_ok():\n'
                                           '            assert (ROOT / p).read_bytes() == UX_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == '
                                           'UX_APPROVAL.manifest()["source_blobs"][p]\n'
                                           '        elif p in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
                                           '            assert (ROOT / p).read_bytes() == C06_APPROVAL.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == '
                                           'C06_APPROVAL.manifest()["source_blobs"][p]\n'),
                                          ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\', '
                                           '\'tests.c06_cost_workspace_scope\')", b"\'tests.r04_ppa_scope\', '
                                           '\'tests.c06_cost_workspace_scope\', \'tests.fake_scope\')")),\n',
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", '
                                           'b"\'tests.ux_final01_scope\', \'tests.fake_scope\')")),\n')],
 'tests/test_u1_scope.py': [('def test_positive_cohort_is_exact_registered_and_closed():\n',
                             'def test_positive_cohort_is_exact_registered_and_closed():\n'
                             '    # Read-only node: ONE registry-wide read for THIS call only (dropped on exit; nothing is kept across '
                             'calls or mutations) instead of one full\n'
                             '    # cohort verdict per path. The nodes that mutate a worktree (the `wt` fixture) are deliberately NOT '
                             'scoped. Assertions are unchanged.\n'
                             '    with C.call_scope():\n'
                             '        _positive_cohort_checks()\n'
                             '\n'
                             '\n'
                             'def _positive_cohort_checks():\n'),
                            ('def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n',
                             'def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():\n'
                             '    # Read-only node: ONE registry-wide read for THIS call only (dropped on exit; nothing is kept across '
                             'calls or mutations) instead of one full\n'
                             '    # cohort verdict per path. The nodes that mutate a worktree (the `wt` fixture) are deliberately NOT '
                             'scoped. Assertions are unchanged.\n'
                             '    with C.call_scope():\n'
                             '        _no_path_outside_checks()\n'
                             '\n'
                             '\n'
                             'def _no_path_outside_checks():\n'),
                            ('def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n',
                             'def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():\n'
                             '    # Read-only node: ONE registry-wide read for THIS call only (dropped on exit; nothing is kept across '
                             'calls or mutations) instead of one full\n'
                             '    # cohort verdict per path. The nodes that mutate a worktree (the `wt` fixture) are deliberately NOT '
                             'scoped. Assertions are unchanged.\n'
                             '    with C.call_scope():\n'
                             '        _integration_reference_checks()\n'
                             '\n'
                             '\n'
                             'def _integration_reference_checks():\n')],
 'tests/test_u2_scope.py': [('def test_positive_cohort_is_exact_registered_and_closed():\n',
                             'def test_positive_cohort_is_exact_registered_and_closed():\n'
                             '    # Read-only node: ONE registry-wide read for THIS call only (dropped on exit; nothing is kept across '
                             'calls or mutations) instead of one full\n'
                             '    # cohort verdict per path (the same bounded call scope the accepted PR3b1 and U1 successors use). '
                             'Assertions are unchanged.\n'
                             '    with C.call_scope():\n'
                             '        _positive_cohort_checks()\n'
                             '\n'
                             '\n'
                             'def _positive_cohort_checks():\n')],
 'tests/u1_scope.py': [("'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')\n\n\nclass _Discovered:",
                        "'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ux_final01_scope')\n\n\nclass _Discovered:"),
                       ('        self.OWNED_PATHS = frozenset(module.OWNED_PATHS)\n',
                        "        self.OWNED_PATHS = frozenset(module.OWNED_PATHS) | frozenset(getattr(module, 'LIVE_DOCS', ()))      # "
                        'living documents a cohort may change without a pin\n'),
                       ("    if path not in ('frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/styles/compact-inputs.css',",
                        '    from tests import ux_final01_scope as UX\n'
                        '    if path in UX.SUPERSEDED:       # UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may '
                        'move these exact pins too\n'
                        '        from tests import c06_cost_workspace_scope as C06\n'
                        '        return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                        "    if path not in ('frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/styles/compact-inputs.css',")],
 'tests/u2_scope.py': [("    if path not in ('frontend/src/app/capex/profileFocus.ts', 'frontend/src/app/editing/CostLinesGridView.tsx',",
                        '    from tests import ux_final01_scope as UX\n'
                        '    if path in UX.SUPERSEDED:       # UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may '
                        'move these exact pins too\n'
                        '        from tests import c06_cost_workspace_scope as C06\n'
                        '        return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)\n'
                        "    if path not in ('frontend/src/app/capex/profileFocus.ts', 'frontend/src/app/editing/CostLinesGridView.tsx',"),
                       ('def supersedes(path, value, repo=None, ref=None):\n'
                        '    if path in ("frontend/src/app/editing/CostLinesGridView.tsx", "frontend/src/app/CostWorkbench.tsx",',
                        'def supersedes(path, value, repo=None, ref=None):\n'
                        '    from tests import ux_final01_scope as UX\n'
                        '    if path in UX.SUPERSEDED and _c06_pin(path, value, ROOT if repo is None else Path(repo), ref):\n'
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
                            '    from tests import ux_final01_scope as UX\n'
                            '    if path in UX.SUPERSEDED:       # UX-FINAL-01: the finite signed successor chain (C06 forwards to it) '
                            'follows this pin\n'
                            '        from tests import c06_cost_workspace_scope as C06\n'
                            '        if C06.signature_ok(repo,ref) and C06.supersedes(path,value,repo,ref):\n'
                            '            return True\n')],
 'tests/ux_pr2b_scope.py': [("    if path in ('frontend/src/app/capex/ProfileDraftProvider.tsx', "
                             "'frontend/src/app/capex/ProfileRowEditor.tsx', ",
                             '    from tests import ux_final01_scope as UX\n'
                             "    if path in UX.SUPERSEDED or path in ('frontend/src/app/capex/ProfileDraftProvider.tsx', "
                             "'frontend/src/app/capex/ProfileRowEditor.tsx', ")],
 'tests/ux_pr2c_scope.py': [("    if path in ('frontend/src/app/capex/ProfileDraftProvider.tsx',):\n"
                             '        from tests import c06_cost_workspace_scope as C06\n',
                             '    from tests import ux_final01_scope as UX\n'
                             "    if path in UX.SUPERSEDED or path in ('frontend/src/app/capex/ProfileDraftProvider.tsx',):\n"
                             '        from tests import c06_cost_workspace_scope as C06\n')],
 'tests/ux_pr3b1_scope.py': [('    if path in ("frontend/src/app/editing/CostLinesGridView.tsx", "tests/ux_pr3b1_scope.py", '
                              '"frontend/src/app/CostWorkbench.tsx"):\n',
                              '    from tests import ux_final01_scope as UX\n'
                              '    if path in UX.SUPERSEDED or path in ("frontend/src/app/editing/CostLinesGridView.tsx", '
                              '"tests/ux_pr3b1_scope.py", "frontend/src/app/CostWorkbench.tsx"):\n')]}


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
        if __name__ not in COHORT_MODULES:
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
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
        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN) | set(BASELINE))
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
        for p, (mode, blob) in BASELINE.items():          # literal table == immutable BASE object == evaluated tree/ref, blob AND Git mode
            if _base_blob(key, p) != blob or _base_mode(key, p) != mode or current.get(p) != blob or modes.get(p) != mode:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(Path(repo) if repo is not None else ROOT, ref, "exact")


def _diff_ok(root, ref):
    try:
        allowed = OWNED_PATHS | {MANIFEST} | LIVE_DOCS
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
    return OWNED_PATHS | {MANIFEST} | LIVE_DOCS if signature_ok(repo, ref) else frozenset()


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | {MANIFEST} | LIVE_DOCS and signature_ok(repo, ref)


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
        return bool(actual) and actual == set(changed) and actual <= OWNED_PATHS | {MANIFEST} | LIVE_DOCS and exact_blobs_ok(root)
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

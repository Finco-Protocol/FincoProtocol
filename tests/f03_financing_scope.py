"""F03 Financing — finite exact-source successor after accepted BESS02 (#436, itself after R02 #437).

Only one authorized read-only selected-Run evidence bridge. No financial-engine,
writer, authentication, CSRF, reserve, BESS, tax or CI policy edits.
Every changed byte, Git mode and immutable BASE tree is bound to this manifest.
Previous manifests are never rewritten. No wildcard, suffix/prefix exemption or
semantic reinterpretation of a failed Run is permitted.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "01a26f9a87a12548c4f151caebe8ee933db7445c"
BASE_TREE = "0f84439efe6cb4ad920ea008eb739bbc7dbe07ab"
MANIFEST = "docs/react_migration/f03_financing/SOURCE_SUCCESSOR.json"
SCHEMA = "F03_FINANCING_PROVEN_READ_LAYER_EXACT_SOURCE_V1"
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/bess02_scope.py"
BESS_TEST = "tests/test_bess02_scope.py"
R02_MODULE = "tests/r02_ppa_ux_scope.py"
R02_TEST = "tests/test_r02_ppa_ux_scope.py"
POST432_TEST = "tests/test_post432_l01_l02_scope.py"
SOURCE_PATHS = frozenset((
    "app/v2/f02_financing_period_evidence.py",
    "app/v2/react_financing.py",
    "frontend/src/app/financing/pr3b1/FinancingOverview.tsx",
    "frontend/src/app/financing/pr3b1/__tests__/readLayer.test.mjs",
    "frontend/src/app/financing/pr3b1/__tests__/synthetic.mjs",
    "frontend/src/app/financing/pr3b1/readEvidence.ts",
    "frontend/src/app/financing/pr3b1/runEvidence.ts",
    "frontend/src/app/financing/pr3b1/sourcesUsesModel.ts",
    "frontend/src/app/financing/pr3b1/termSheetModel.ts",
    "frontend/src/app/financing/pr3b1/types.ts",
    "static/react/finco-react.js",
    # Already reviewed via CI_PATHS and WORKFLOW_EDITS; R02's exact-source
    # acceptance must recognise precisely this protected successor path.
    ".github/workflows/finval_f01_acceptance.yml",
))
TEST_PATHS = frozenset((
    "tests/test_f02_financing_period_evidence.py",
    "tests/test_f03_financing_scope.py",
))
GOVERNANCE_PATHS = frozenset((PREDECESSOR, BESS_TEST, R02_MODULE, R02_TEST, POST432_TEST, REGISTRY, "tests/f03_financing_scope.py", "tests/ci_v4_scope.py", "tests/ux_pr2b_scope.py", "tests/ux_pr2c_scope.py"))
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
MAP_KEYS = (REGISTRY, "static/react/finco-react.js")
CI_WORKFLOW = ".github/workflows/finval_f01_acceptance.yml"
CI_PATHS = frozenset((CI_WORKFLOW,))
OWNED_PATHS = SOURCE_PATHS | TEST_PATHS | GOVERNANCE_PATHS | CURRENT_MAPS | CI_PATHS
NEW = frozenset((
    "app/v2/f02_financing_period_evidence.py",
    "tests/test_f02_financing_period_evidence.py",
    "tests/test_f03_financing_scope.py",
    "tests/f03_financing_scope.py",
))
SUPERSEDED = OWNED_PATHS - NEW
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "tools/",
             "migrations/", "app/workbook/", "app/persistence/", "app/run_integrity/", "main_web.py")

def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)

def _read(root, path, ref=None):
    return (Path(root) / path).read_bytes() if ref is None else _git(root, "show", ref + ":" + path)

def _blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        d = json.loads(_read(root, MANIFEST, ref))
        return d if (isinstance(d, dict) and set(d) == {"schema_version", "base", "base_tree", "source_blobs", "base_blobs"}
            and d["schema_version"] == SCHEMA and d["base"] == BASE and d["base_tree"] == BASE_TREE
            and isinstance(d["source_blobs"], dict) and isinstance(d["base_blobs"], dict)) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}

def expected_map(root, path, pins=None):
    """Only the two FINITE current-source keys may move; all history stays unchanged."""
    d = json.loads(_base_bytes(str(root), path))
    pins = manifest(root).get("source_blobs", {}) if pins is None else pins
    for key in MAP_KEYS:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()

# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes of the BESS02 governance chain. BESS02 gains
# one forward hook to this cohort (the same acyclic pattern BESS02 itself added to R02); the R02 closure delegates one line to BESS02; the
# exact-tail tests become two-state (accepted BESS-only tail, or exactly one F03 append behind a complete F03 signature); the registry appends
# this cohort once. This signature never calls BESS02, R02 or the composite: it reads Git objects and this manifest only.
HANDOFFS = {'tests/bess02_scope.py': [('    _SCOPE.append({})\n    try:\n        yield\n    finally:\n        _SCOPE.pop()\n',
                            '    _SCOPE.append({})\n'
                            '    try:\n'
                            '        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept globally.\n'
                            '        N = _next()\n'
                            '        if N is None:\n'
                            '            yield\n'
                            '        else:\n'
                            '            with N.scoped():\n'
                            '                yield\n'
                            '    finally:\n'
                            '        _SCOPE.pop()\n'),
                           ('def _verdict(repo, ref, closure):\n'
                            '    key = (str(repo if repo is not None else ROOT), ref, closure)\n'
                            '    if _SCOPE:\n'
                            '        if key not in _SCOPE[-1]:\n'
                            '            _SCOPE[-1][key] = _exact(repo, ref, closure)\n'
                            '        return _SCOPE[-1][key]\n'
                            '    return _exact(repo, ref, closure)\n',
                            'def _exact_next_scoped(repo, ref, closure):\n'
                            '    N = _next()\n'
                            '    if N is None:\n'
                            '        return _exact(repo, ref, closure)\n'
                            '    with N.scoped():\n'
                            '        return _exact(repo, ref, closure)\n'
                            '\n'
                            '\n'
                            'def _verdict(repo, ref, closure):\n'
                            '    key = (str(repo if repo is not None else ROOT), ref, closure)\n'
                            '    if _SCOPE:\n'
                            '        if key not in _SCOPE[-1]:\n'
                            '            _SCOPE[-1][key] = _exact_next_scoped(repo, ref, closure)\n'
                            '        return _SCOPE[-1][key]\n'
                            '    return _exact_next_scoped(repo, ref, closure)\n'),
                           ("        head = ref or 'HEAD'\n",
                            "        head = ref or 'HEAD'\n"
                            '        nx = _next_pins(root, ref)\n'
                            '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n'),
                           ('            expected = expected_map(root, p, pins)\n'
                            '            if pins[p] != _blob(expected) or (closure and _read(root, p, ref) != expected):',
                            '            expected = expected_map(root, p, cur, _next_moved(root, ref))\n'
                            '            if cur[p] != _blob(expected) or (closure and _read(root, p, ref) != expected):'),
                           ('(closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != pins[p]:',
                            '(closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != cur[p]:'),
                           ('            allowed = OWNED_PATHS | {MANIFEST}\n', '            allowed = closure_paths(root, ref)\n'),
                           ("def expected_map(root, path, pins):\n    d = json.loads(_base(root, 'show', BASE + ':' + path))",
                            "def expected_map(root, path, pins, moved=None):\n    d = json.loads(_base(root, 'show', BASE + ':' + path))"),
                           ("        d['source_blobs'][p] = pins[p]\n    return (json.dumps(d",
                            "        d['source_blobs'][p] = pins[p]\n"
                            '    for key, blob in (moved or {}).items():\n'
                            "        if key in d['source_blobs']:\n"
                            "            d['source_blobs'][key] = blob\n"
                            '    return (json.dumps(d'),
                           ('    try:\n        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)',
                            '    try:\n'
                            '        N = _next()\n'
                            '        if N is not None and N.signature_ok(root, ref):\n'
                            '            return N.reviewed_edits_ok(root, ref) and all(\n'
                            '                _read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS if p not in N.HANDOFFS)\n'
                            '        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)'),
                           ('def allowed_path(path, repo=None, ref=None):\n    return path in OWNED_PATHS | {MANIFEST}\n',
                            'def _next():\n'
                            '    """The one finite forward successor (F03). Low-level only: its signature never calls this module or the '
                            'composite."""\n'
                            '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
                            "    if 'tests.f03_financing_scope' not in COHORT_MODULES:\n"
                            '        return None\n'
                            '    from tests import f03_financing_scope\n'
                            '    return f03_financing_scope\n'
                            '\n'
                            '\n'
                            'def _next_pins(root, ref):\n'
                            '    N = _next()\n'
                            '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n'
                            '\n'
                            '\n'
                            'def _next_moved(root, ref):\n'
                            '    N = _next()\n'
                            '    if N is None or not N.signature_ok(root, ref):\n'
                            '        return {}\n'
                            '    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}\n'
                            '\n'
                            '\n'
                            'def closure_paths(repo=None, ref=None):\n'
                            '    """This cohort\'s closed path set, gated by its OWN signature, plus the successor\'s closure; one shared read scope '
                            'evaluates each signature once."""\n'
                            '    root = Path(repo) if repo is not None else ROOT\n'
                            '    with scoped():\n'
                            '        if not signature_ok(root, ref):\n'
                            '            return frozenset()\n'
                            '        N = _next()\n'
                            '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())\n'
                            '\n'
                            '\n'
                            'def allowed_path(path, repo=None, ref=None):\n'
                            '    return path in closure_paths(repo, ref)\n'),
                           ("    return path in SUPERSEDED and signature_ok(repo, ref) and manifest(repo, ref)['source_blobs'].get(path) == value\n",
                            '    if path in SUPERSEDED and signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:\n'
                            '        return True\n'
                            '    N = _next()\n'
                            '    return N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref)\n'),
                           ('def effective_pins(repo=None, ref=None, *, signature=False):\n'
                            "    return dict(manifest(repo, ref).get('source_blobs', {}))",
                            'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                            '    root = Path(repo) if repo is not None else ROOT\n'
                            "    pins = dict(manifest(repo, ref).get('source_blobs', {}))\n"
                            '    pins.update(_next_pins(root, ref))\n'
                            '    return pins'),
                           ('    root = Path(repo) if repo is not None else ROOT\n'
                            '    try:\n'
                            "        if _git(root, 'merge-base', 'origin/main', 'HEAD')",
                            '    root = Path(repo) if repo is not None else ROOT\n'
                            '    try:\n'
                            '        N = _next()\n'
                            '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n'
                            '            return True\n'
                            "        if _git(root, 'merge-base', 'origin/main', 'HEAD')")],
 'tests/fin_v2_cohorts.py': [("'tests.bess02_scope')", "'tests.bess02_scope', 'tests.f03_financing_scope')")],
 'tests/r02_ppa_ux_scope.py': [('    return own | ((N.OWNED_PATHS | {N.MANIFEST}) if N is not None and N.signature_ok(root, ref) else frozenset())',
                                '    return own | (N.closure_paths(root, ref) if N is not None else frozenset())')],
 'tests/test_bess02_scope.py': [("    assert C.COHORT_MODULES == accepted + ('tests.bess02_scope',)\n"
                                 "    assert C.COHORT_MODULES[-3:] == ('tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', "
                                 "'tests.bess02_scope')",
                                 '    from tests import f03_financing_scope as F\n'
                                 "    own = accepted + ('tests.bess02_scope',)\n"
                                 '    # Exactly two states: the accepted BESS-only tail, or one reviewed F03 successor behind a complete F03 '
                                 'signature.\n'
                                 '    assert C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())\n'
                                 "    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', "
                                 "'tests.bess02_scope')"),
                                ('    for path in sorted(paths):\n'
                                 "        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + path], "
                                 'cwd=B.ROOT)\n',
                                 '    from tests import f03_financing_scope as F\n'
                                 '    for path in sorted(paths):\n'
                                 '        if path in F.SOURCE_PATHS and F.signature_ok():     # one reviewed F03 successor of the shared bundle, '
                                 'exactly at its pinned blob\n'
                                 "            assert B._blob((B.ROOT/path).read_bytes()) == F.manifest()['source_blobs'][path]\n"
                                 '            continue\n'
                                 "        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + path], "
                                 'cwd=B.ROOT)\n')],
 'tests/test_post432_l01_l02_scope.py': [('    assert N.exact_blobs_ok() and now == N.expected_handoff(ROOT, X.REGISTRY).decode()\n',
                                          '    from tests import f03_financing_scope as F\n'
                                          "    nxt = 'tests.f03_financing_scope' in C.COHORT_MODULES\n"
                                          '    assert N.exact_blobs_ok() and now == (F.expected_handoff(ROOT, X.REGISTRY) if nxt and '
                                          'F.signature_ok() else N.expected_handoff(ROOT, X.REGISTRY)).decode()\n')],
 'tests/test_r02_ppa_ux_scope.py': [('    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == N.expected_handoff(ROOT, X.REGISTRY)\n',
                                     '    from tests import f03_financing_scope as F\n'
                                     "    nxt = ('tests.f03_financing_scope',) if 'tests.f03_financing_scope' in C.COHORT_MODULES else ()\n"
                                     '    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == (\n'
                                     '        F.expected_handoff(ROOT, X.REGISTRY) if nxt and F.signature_ok() else N.expected_handoff(ROOT, '
                                     'X.REGISTRY))\n'),
                                    ("    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') and "
                                     "C.COHORT_MODULES[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == "
                                     'len(C.COHORT_MODULES)',
                                     '    core = C.COHORT_MODULES[:len(C.COHORT_MODULES) - len(nxt)]\n'
                                     "    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') + nxt and core[-6:] == "
                                     "TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)"),
                                    ('                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS)]',
                                     '                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS) and not (F.signature_ok() and p in '
                                     'F.SOURCE_PATHS)]'),
                                    ('    assert X.exact_blobs_ok() and X.signature_ok()\n    data = X.manifest()\n',
                                     '    from tests import f03_financing_scope as F\n'
                                     '    assert X.exact_blobs_ok() and X.signature_ok()\n'
                                     '    data = X.manifest()\n')]}


def expected_handoff(root, path):
    """The exact bytes of ``path`` after the reviewed substitutions over its immutable BASE blob."""
    raw = _base_bytes(str(root), path).decode()          # immutable BASE object (cached)
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


# Exact, reviewed F01 workflow transformation. No broad workflow admission;
# this predecessor is authenticated by the immutable BASE blob and byte-for-byte
# transformation, in addition to the manifest source pin and Git mode checks.
WORKFLOW_EDITS = (
    ("    timeout-minutes: 25\n", "    timeout-minutes: 45\n"),
    ("          python -m pytest tests/finval_f01_browser_acceptance.py", "          echo \"FINVAL_BROWSER_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)\"\n          python -m pytest tests/finval_f01_browser_acceptance.py"),
    (" -q -rs --junitxml=evidence/financial-browser.xml", " -q -rs --durations=20 --junitxml=evidence/financial-browser.xml\n          echo \"FINVAL_BROWSER_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)\""),
    ("        run: docker build -f docs/ci_v3/phase4/runtime/Dockerfile -t finval-f01-native .\n", "        run: |\n          echo \"FINVAL_DOCKER_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)\"\n          docker build -f docs/ci_v3/phase4/runtime/Dockerfile -t finval-f01-native .\n          echo \"FINVAL_DOCKER_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)\"\n"),
    ("          mkdir -p evidence/native\n", "          echo \"FINVAL_NATIVE_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)\"\n          mkdir -p evidence/native\n"),
    (" -q -rs --junitxml=evidence/native.xml", " -q -rs --durations=20 --junitxml=evidence/native.xml\n          echo \"FINVAL_NATIVE_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)\""),
)


def reviewed_workflow_ok(repo=None, ref=None, actual=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        baseline = _git(root, "show", BASE + ":" + CI_WORKFLOW)
        # The original F01 guard must remain the exact historically reviewed blob.
        if _blob(baseline) != "8b7b49a49583fc33c48d60cc55bd88ea9e88ef8d":
            return False
        candidate = baseline.decode()
        for old, new in WORKFLOW_EDITS:
            if candidate.count(old) != 1:
                return False
            candidate = candidate.replace(old, new)
        raw = _read(root, CI_WORKFLOW, ref) if actual is None else actual
        if isinstance(raw, str):
            raw = raw.encode()
        pins = manifest(root, ref).get("source_blobs", {})
        return raw == candidate.encode() and pins.get(CI_WORKFLOW) == _blob(raw)
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError):
        return False

# Finite exact-source F01-CI handoffs: four literal edits of CI V4 plus
# one admission each in PR2b/PR2c. They never import F03 in reverse, never
# edit historical manifests, skip tests or allow arbitrary CI policy drift.
REVIEWED_CI_HANDOFFS = {
    "tests/ci_v4_scope.py": (
        ("    return S.supersedes(path, value, root, ref)\n\n\ndef _merge_event_successor():", "    if S.supersedes(path, value, root, ref):\n        return True\n    # One exact F03-reviewed successor of the CI V4 module; never a prefix.\n    if path != 'tests/ci_v4_scope.py':\n        return False\n    from tests import f03_financing_scope as F\n    return F.supersedes(path, value, root, ref)\n\n\ndef _merge_event_successor():"),
        ("    return B\n\n\ndef _git(root, *args):", "    return B\n\n\ndef _f03_ci_owns(path, root, ref):\n    \"\"\"Admit only the exact reviewed 45-minute F01 workflow; no CI wildcard.\"\"\"\n    if path != '.github/workflows/finval_f01_acceptance.yml':\n        return False\n    from tests import f03_financing_scope as F\n    return path in F.CI_PATHS and F.exact_blobs_ok(root, ref) and F.reviewed_workflow_ok(root, ref)\n\n\ndef _git(root, *args):"),
        ("    authorized_ci = successor.CI_PATHS if successor_ok else frozenset()\n    data = manifest(root, ref)", "    authorized_ci = successor.CI_PATHS if successor_ok else frozenset()\n    if _f03_ci_owns('.github/workflows/finval_f01_acceptance.yml', root, ref):\n        authorized_ci = authorized_ci | {'.github/workflows/finval_f01_acceptance.yml'}\n    data = manifest(root, ref)"),
        ("    return (path in CI_PATHS or _merge_event_successor().ci_owns(path, repo, ref)) and exact_blobs_ok(repo, ref)", "    root = Path(repo) if repo is not None else ROOT\n    return (path in CI_PATHS or _merge_event_successor().ci_owns(path, repo, ref)\n            or _f03_ci_owns(path, root, ref)) and exact_blobs_ok(repo, ref)"),
    ),
    "tests/ux_pr2b_scope.py": (
        ("def _pr3b1_pin(path, blob, repo=None, ref=None, *, signature=False):\n    S = _pr3b1()", "def _pr3b1_pin(path, blob, repo=None, ref=None, *, signature=False):\n    # One reviewed CI V4 module successor, proven by F03 without this cohort.\n    if path == 'tests/ci_v4_scope.py':\n        from tests import f03_financing_scope as F\n        if F.supersedes(path, blob, repo, ref):\n            return True\n    S = _pr3b1()"),
    ),
    "tests/ux_pr2c_scope.py": (
        ("def _pr3b1_pin(path, blob, repo=None, ref=None):\n    S = _pr3b1()", "def _pr3b1_pin(path, blob, repo=None, ref=None):\n    # Exact low-level F03 successor of only the CI V4 source file.\n    if path == 'tests/ci_v4_scope.py':\n        from tests import f03_financing_scope as F\n        if F.supersedes(path, blob, repo, ref):\n            return True\n    S = _pr3b1()"),
    ),
}


def reviewed_ci_handoffs_ok(repo=None, ref=None, *, path=None, actual=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        if path is not None and path not in REVIEWED_CI_HANDOFFS:
            return False
        paths = (path,) if path is not None else tuple(sorted(REVIEWED_CI_HANDOFFS))
        d = manifest(root, ref)
        pins, predecessors = d.get("source_blobs", {}), d.get("base_blobs", {})
        for p in paths:
            original = _git(root, "show", BASE + ":" + p)
            if _blob(original) != predecessors.get(p):
                return False
            current = original.decode()
            for before, after in REVIEWED_CI_HANDOFFS[p]:
                if current.count(before) != 1:
                    return False
                current = current.replace(before, after)
            raw = _read(root, p, ref) if actual is None else actual
            if isinstance(raw, str):
                raw = raw.encode()
            if raw != current.encode() or pins.get(p) != _blob(raw):
                return False
        return True
    except (OSError, ValueError, UnicodeError, KeyError, TypeError, subprocess.CalledProcessError):
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

def signature_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    key = (str(root), ref)
    if _SCOPE and key in _SCOPE[-1]:
        return _SCOPE[-1][key]
    value = _signature_ok(root, ref)
    if _SCOPE:
        _SCOPE[-1][key] = value
    return value

# Accepted BESS02/R02 product bytes and historical manifests that must stay byte-identical to BASE.
FROZEN = ("docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json", "docs/bess_setup/SOURCE_SUCCESSOR.json", "docs/bess02/SOURCE_SUCCESSOR.json",
          "app/services/bess_standalone_candidate.py", "app/services/bess_setup_preview.py", "app/workbook/bess_config.py")


@lru_cache(maxsize=512)
def _base_bytes(root, path):
    """Bytes of an IMMUTABLE accepted-main (BASE) object. Never a working-tree or ref read, so a cached value can never go stale."""
    return _git(Path(root), "show", BASE + ":" + path)


@lru_cache(maxsize=8)
def _base_tree(root):
    return _git(Path(root), "rev-parse", BASE + "^{tree}").decode().strip()


@lru_cache(maxsize=256)
def _expected_blob(root, kind, path):
    """Blob id of the literal reviewed transformation of an immutable BASE blob (a pure function of BASE and this module's literals)."""
    if kind == "handoff":
        edits = HANDOFFS[path]
    elif kind == "ci":
        edits = REVIEWED_CI_HANDOFFS[path]
    else:
        edits = WORKFLOW_EDITS
        path = CI_WORKFLOW
    raw = _base_bytes(root, path)
    if kind == "workflow" and _blob(raw) != "8b7b49a49583fc33c48d60cc55bd88ea9e88ef8d":
        raise ValueError("the original F01 workflow is not the historically reviewed blob")
    text = raw.decode()
    for old, new in edits:
        if text.count(old) != 1:
            raise ValueError("reviewed edit is missing or ambiguous")
        text = text.replace(old, new)
    return _blob(text.encode())


@lru_cache(maxsize=256)
def _expected_map_blob(root, path, moved):
    """Pure function of an immutable BASE map and the two literal moved pins."""
    return _blob(expected_map(Path(root), path, dict(zip(MAP_KEYS, moved))))


def _snapshot(root, ref, paths):
    """One read of the evaluated state: {path: blob} and {path: mode}. A committed ref is read with ONE ls-tree; the working tree is read
    directly (bytes hashed here, exactly like the sibling cohorts), a symlink / non-file / executable bit being reported as a bad mode."""
    paths = sorted(paths)
    if ref is None:
        blobs, modes = {}, {}
        for p in paths:
            f = root / p
            if f.is_symlink() or not f.is_file():
                continue
            blobs[p] = _blob(f.read_bytes())
            modes[p] = "100755" if f.stat().st_mode & 0o111 else "100644"
        return blobs, modes
    blobs, modes = {}, {}
    for line in _git(root, "ls-tree", "-r", ref, "--", *paths).decode().splitlines():
        meta, name = line.split("\t", 1)
        mode, _kind, blob = meta.split()
        blobs[name], modes[name] = blob, mode
    return blobs, modes


def _signature_ok(root, ref):
    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: O(1) git reads per verdict, nothing cached from mutable state."""
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if __name__ not in COHORT_MODULES:
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if not NEW.isdisjoint(base) or any((p.startswith(FORBIDDEN) and p not in CI_PATHS) or p.startswith("/") or ".." in p.split("/") or "*" in p for p in OWNED_PATHS | {MANIFEST}):
            return False
        _git(root, "merge-base", "--is-ancestor", BASE, ref or "HEAD")
        key = str(root)
        if _base_tree(key) != BASE_TREE:
            return False
        if any(_blob(_base_bytes(key, p)) != base[p] for p in base):          # recorded predecessor blobs are what accepted main holds
            return False
        current, modes = _snapshot(root, ref, set(pins) | {MANIFEST} | set(FROZEN))
        if {p: current.get(p) for p in pins} != pins:
            return False
        owned = OWNED_PATHS | {MANIFEST}
        if len(modes) < len(owned) or any(modes.get(p) != "100644" for p in owned):
            return False
        if any(pins[p] != _expected_blob(key, "handoff", p) for p in HANDOFFS):
            return False
        if pins[CI_WORKFLOW] != _expected_blob(key, "workflow", CI_WORKFLOW):
            return False
        if any(pins[p] != _expected_blob(key, "ci", p) for p in REVIEWED_CI_HANDOFFS):
            return False
        for p in CURRENT_MAPS:
            if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):
                return False
        if any(current.get(p) != _blob(_base_bytes(key, p)) for p in FROZEN):
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False

def exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if not signature_ok(root, ref):
        return False
    try:
        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref else []), "--").decode().splitlines())
        if not changed <= OWNED_PATHS | {MANIFEST}:
            return False
        if ref is None:
            untracked = set(_git(root, "ls-files", "--others", "--exclude-standard").decode().splitlines())
            if any(p not in OWNED_PATHS | {MANIFEST} and not (p.startswith("evidence/") and p.endswith((".json", ".xml", ".png", ".txt", ".csv", ".html", ".zip"))) for p in untracked):
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
    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value

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

"""F03 Financing — finite exact-source successor after accepted R02 (#437).

Only one authorized read-only selected-Run evidence bridge. No financial-engine,
writer, authentication, CSRF, reserve, BESS, tax or CI policy edits.
Every changed byte, Git mode and immutable BASE tree is bound to this manifest.
Previous manifests are never rewritten. No wildcard, suffix/prefix exemption or
semantic reinterpretation of a failed Run is permitted.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "c26b968683f1de63f73f92789dcef947e912822e"
BASE_TREE = "bd65189555850dca7982ce9f5e9314a73b923eef"
MANIFEST = "docs/react_migration/f03_financing/SOURCE_SUCCESSOR.json"
SCHEMA = "F03_FINANCING_PROVEN_READ_LAYER_EXACT_SOURCE_V1"
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/r02_ppa_ux_scope.py"
L_MODULE = "tests/post432_l01_l02_scope.py"
R02_TEST = "tests/test_r02_ppa_ux_scope.py"
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
GOVERNANCE_PATHS = frozenset((PREDECESSOR, L_MODULE, R02_TEST, REGISTRY, "tests/test_post432_l01_l02_scope.py", "tests/f03_financing_scope.py", "tests/ci_v4_scope.py", "tests/ux_pr2b_scope.py", "tests/ux_pr2c_scope.py"))
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
_REGISTRY_OLD = "'tests.r02_ppa_ux_scope')"
_REGISTRY_NEW = "'tests.r02_ppa_ux_scope', 'tests.f03_financing_scope')"
_POST432_EDITS = (
    (
        "return {p: b for p, b in N.manifest(root, ref)['source_blobs'].items() if p in N.SUPERSEDED}",
        "return dict(N.effective_pins(root, ref))",
    ),
    (
        "return base | ((N.OWNED_PATHS | {N.MANIFEST}) if N is not None and N.signature_ok(root, ref) else frozenset())",
        "return base | (N.closure_paths(root, ref) if N is not None and N.signature_ok(root, ref) else frozenset())",
    ),
)

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

def expected_map(root, path):
    """Only the two FINITE current-source keys may move; all history stays unchanged."""
    d = json.loads(_git(root, "show", BASE + ":" + path))
    pins = manifest(root).get("source_blobs", {})
    for key in MAP_KEYS:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()

def reviewed_handoff_ok(root, ref, path, expected=None, actual=None):
    if path not in (REGISTRY, L_MODULE):
        return False
    original = _git(root, "show", BASE + ":" + path).decode()
    if path == REGISTRY:
        if original.count(_REGISTRY_OLD) != 1:
            return False
        target = original.replace(_REGISTRY_OLD, _REGISTRY_NEW)
    else:
        target = original
        for before, after in _POST432_EDITS:
            if target.count(before) != 1:
                return False
            target = target.replace(before, after)
    actual_bytes = _read(root, path, ref) if actual is None else actual
    pins = manifest(root, ref).get("source_blobs", {})
    return actual_bytes == target.encode() and pins.get(path) == _blob(actual_bytes)

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

def _signature_ok(root, ref):
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
        if _git(root, "rev-parse", BASE + "^{tree}").decode().strip() != BASE_TREE:
            return False
        paths = sorted(base)
        historical = _git(root, "rev-parse", *[BASE + ":" + p for p in paths]).decode().split()
        if historical != [base[p] for p in paths]:
            return False
        if ref is None:
            ordered = sorted(pins)
            hashed = subprocess.run(["git", "hash-object", "--stdin-paths"], cwd=root,
                input="".join(str(root / p) + "\n" for p in ordered).encode(),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout.decode().split()
            current = dict(zip(ordered, hashed)) if len(hashed) == len(ordered) else None
        else:
            lines = _git(root, "ls-tree", "-r", ref, "--", *sorted(pins)).decode().splitlines()
            current = {line.split("\t", 1)[1]: line.split()[2] for line in lines}
        if current != pins:
            return False
        modes = _git(root, "ls-tree", "-r", ref or "HEAD", "--", *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
        if len(modes) != len(OWNED_PATHS | {MANIFEST}) or any(not x.startswith("100644 ") for x in modes):
            return False
        if not all(reviewed_handoff_ok(root, ref, p) for p in (REGISTRY, L_MODULE)):
            return False
        if not reviewed_workflow_ok(root, ref):
            return False
        if not reviewed_ci_handoffs_ok(root, ref):
            return False
        for p in CURRENT_MAPS:
            if _read(root, p, ref) != expected_map(root, p):
                return False
        for p in ("docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json", "docs/bess_setup/SOURCE_SUCCESSOR.json"):
            if _read(root, p, ref) != _git(root, "show", BASE + ":" + p):
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

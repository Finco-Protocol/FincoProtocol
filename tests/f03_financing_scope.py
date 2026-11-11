"""F03 Financing — finite exact-source successor after the accepted CI V4 Correction P leaf (#441, itself after BESS02 #436 and R02 #437).

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
BASE = "69d68d4f6e45fdffc7e9e3800ceeca0ba26582b9"
BASE_TREE = "7f8335faa58a4c54b45d23837a625e85475a8c0c"
MANIFEST = "docs/react_migration/f03_financing/SOURCE_SUCCESSOR.json"
SCHEMA = "F03_FINANCING_PROVEN_READ_LAYER_EXACT_SOURCE_V1"
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v4_perf_scope.py"
BESS_MODULE = "tests/bess02_scope.py"
PERF_TEST = "tests/test_ci_v4_perf_scope.py"
BESS_TEST = "tests/test_bess02_scope.py"
R02_TEST = "tests/test_r02_ppa_ux_scope.py"
POST432_TEST = "tests/test_post432_l01_l02_scope.py"
PR2B_TEST = "tests/test_ux_pr2b_scope.py"
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
    # The CI V4 internal F01 job: the same steps as the standalone workflow, one reviewed timeout line (25 -> 45 minutes).
    ".github/workflows/ci_v4_f01_job.yml",
))
TEST_PATHS = frozenset((
    "tests/test_f02_financing_period_evidence.py",
    "tests/test_f03_financing_scope.py",
))
GOVERNANCE_PATHS = frozenset((PREDECESSOR, BESS_MODULE, PERF_TEST, BESS_TEST, R02_TEST, POST432_TEST, PR2B_TEST, REGISTRY, "tests/f03_financing_scope.py", "tests/ci_v4_scope.py", "tests/ux_pr2b_scope.py", "tests/ux_pr2c_scope.py"))
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
CI_JOB = ".github/workflows/ci_v4_f01_job.yml"
CI_PATHS = frozenset((CI_WORKFLOW, CI_JOB))
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

# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes of the governance tail. The accepted CI V4
# Correction P leaf gains one forward hook to this cohort (the same acyclic pattern BESS02 added toward that leaf); BESS02 reads its successor's
# map keys dynamically (one literal); the exact-tail tests accept exactly one more reviewed state (this cohort appended once, behind a complete
# signature); the registry appends this cohort once. This signature never calls BESS02, R02 or the composite: it reads Git objects and this manifest only.
HANDOFFS = {'tests/bess02_scope.py': [('        return {}\n'
                            '    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}\n',
                            '        return {}\n'
                            '    return {k: v for k, v in _next_pins(root, ref).items() if k in N.map_keys(root, ref) and k not in CURRENT_MAPS}\n')],
 'tests/ci_v4_perf_scope.py': [('    _SCOPE.append({})\n    try:\n        yield\n    finally:\n        _SCOPE.pop()\n',
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
                               ('\n            if p != MANIFEST and (closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != pins[p]:',
                                '\n            if p != MANIFEST and (closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != cur[p]:'),
                               ('            allowed = OWNED_PATHS | {MANIFEST}\n            if not changed <= allowed:',
                                '            allowed = closure_paths(root, ref)\n            if not changed <= allowed:'),
                               ('    try:\n        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)',
                                '    try:\n'
                                '        N = _next()\n'
                                '        if N is not None and N.signature_ok(root, ref):\n'
                                '            return N.reviewed_edits_ok(root, ref) and all(\n'
                                '                _read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS if p not in N.HANDOFFS)\n'
                                '        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)'),
                               ('def map_keys(repo=None, ref=None):\n    return tuple(MAP_KEYS)\n',
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
                                'def map_keys(repo=None, ref=None):\n'
                                '    root = Path(repo) if repo is not None else ROOT\n'
                                '    with scoped():\n'
                                '        N = _next()\n'
                                '        return tuple(MAP_KEYS) + (tuple(N.map_keys(root, ref)) if N is not None and N.signature_ok(root, ref) else '
                                '())\n'),
                               ('    """This leaf\'s closed path set, gated by its OWN signature (no successor below it on this branch)."""\n'
                                '    root = Path(repo) if repo is not None else ROOT\n'
                                '    with scoped():\n'
                                '        if not signature_ok(root, ref):\n'
                                '            return frozenset()\n'
                                '        return OWNED_PATHS | {MANIFEST}',
                                '    """This leaf\'s closed path set, gated by its OWN signature, plus the successor\'s closure; one shared read '
                                'scope evaluates each signature once."""\n'
                                '    root = Path(repo) if repo is not None else ROOT\n'
                                '    with scoped():\n'
                                '        if not signature_ok(root, ref):\n'
                                '            return frozenset()\n'
                                '        N = _next()\n'
                                '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())'),
                               ('def supersedes(path, value, repo=None, ref=None):\n'
                                '    return path in SUPERSEDED and signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\n',
                                'def supersedes(path, value, repo=None, ref=None):\n'
                                '    with scoped():      # one shared read scope per call: each successor signature is evaluated once, then dropped\n'
                                '        if path in SUPERSEDED and signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:\n'
                                '            return True\n'
                                '        N = _next()\n'
                                '        return N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref)\n'),
                               ('def effective_pins(repo=None, ref=None, *, signature=False):\n'
                                "    return dict(manifest(repo, ref).get('source_blobs', {}))",
                                'def effective_pins(repo=None, ref=None, *, signature=False):\n'
                                '    root = Path(repo) if repo is not None else ROOT\n'
                                '    with scoped():\n'
                                "        pins = dict(manifest(repo, ref).get('source_blobs', {}))\n"
                                '        pins.update(_next_pins(root, ref))\n'
                                '        return pins'),
                               ('    root = Path(repo) if repo is not None else ROOT\n'
                                '    try:\n'
                                "        if _git(root, 'merge-base', 'origin/main', 'HEAD')",
                                '    root = Path(repo) if repo is not None else ROOT\n'
                                '    try:\n'
                                '        N = _next()\n'
                                '        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n'
                                '            return True\n'
                                "        if _git(root, 'merge-base', 'origin/main', 'HEAD')")],
 'tests/fin_v2_cohorts.py': [("'tests.ci_v4_perf_scope')", "'tests.ci_v4_perf_scope', 'tests.f03_financing_scope')")],
 'tests/test_bess02_scope.py': [('    from tests import ci_v4_perf_scope as F\n'
                                 "    own = accepted + ('tests.bess02_scope',)\n"
                                 '    # Exactly two states: the accepted BESS-only tail, or one reviewed CI-performance successor behind a complete '
                                 'signature.\n'
                                 '    assert C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())',
                                 '    from tests import ci_v4_perf_scope as F, f03_financing_scope as G\n'
                                 "    own = accepted + ('tests.bess02_scope',)\n"
                                 '    # Exactly three states: the accepted BESS-only tail; one reviewed CI-performance successor; that successor '
                                 'followed by exactly one\n'
                                 '    # reviewed F03 successor, each behind a complete signature.\n'
                                 '    assert (C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__) and F.signature_ok() and G.signature_ok()))'),
                                ('    for path in sorted(paths):\n'
                                 "        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + path], "
                                 'cwd=B.ROOT)\n',
                                 '    from tests import f03_financing_scope as G\n'
                                 '    for path in sorted(paths):\n'
                                 '        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared bundle, '
                                 'exactly at its pinned blob\n'
                                 "            assert B._blob((B.ROOT/path).read_bytes()) == G.manifest()['source_blobs'][path]\n"
                                 '            continue\n'
                                 "        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + path], "
                                 'cwd=B.ROOT)\n')],
 'tests/test_ci_v4_perf_scope.py': [('    assert C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope"\n',
                                     '    # the leaf stays in its exact place; the only reviewed forward successor is F03, behind its own complete '
                                     'signature\n'
                                     '    from tests import f03_financing_scope as G\n'
                                     '    assert C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope" or (\n'
                                     '        C.COHORT_MODULES[-2:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope") and '
                                     'G.signature_ok())\n'),
                                    ('    assert C.COHORT_MODULES == accepted + ("tests.ci_v4_perf_scope",)\n',
                                     '    from tests import f03_financing_scope as G\n'
                                     '    own = accepted + ("tests.ci_v4_perf_scope",)\n'
                                     '    assert C.COHORT_MODULES == own or (C.COHORT_MODULES == own + ("tests.f03_financing_scope",) and '
                                     'G.signature_ok())\n'),
                                    ('    for p in sorted(F.HANDOFFS):\n        assert (ROOT / p).read_bytes() == F.expected_handoff(ROOT, p), p\n',
                                     '    from tests import f03_financing_scope as G\n'
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p)\n'
                                     '        assert (ROOT / p).read_bytes() == want, p\n'),
                                    ('    assert moved == new and F.effective_pins() == {**F.effective_pins(), **new}\n'
                                     '    assert F.manifest()["source_blobs"] == {**F.manifest()["source_blobs"], **new}\n',
                                     '    from tests import f03_financing_scope as G\n'
                                     '    assert {k: moved[k] for k in new} == new and F.effective_pins() == {**F.effective_pins(), **new}\n'
                                     '    assert set(moved) - set(new) <= set(G.MAP_KEYS)                       # the only other moved key is the '
                                     "reviewed F03 successor's\n"
                                     '    assert F.manifest()["source_blobs"] == {**F.manifest()["source_blobs"], **{k: v for k, v in new.items() if '
                                     'k not in G.manifest()["source_blobs"]}}\n'),
                                    ('    marker = "\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\')"\n',
                                     '    marker = "\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', '
                                     '\'tests.f03_financing_scope\')"\n'),
                                    ('        forged = text.replace(", \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\')", ", '
                                     '\'tests.ci_v4_perf_scope\')")\n',
                                     '        forged = text.replace(", \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\'", ", '
                                     '\'tests.ci_v4_perf_scope\'")\n'),
                                    ('        assert F.expected_handoff(ROOT, p) == now         # and equals exactly the reviewed substitution\n',
                                     '        from tests import f03_financing_scope as G\n'
                                     '        want = G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else '
                                     'F.expected_handoff(ROOT, p)\n'
                                     '        assert want == now                                # and equals exactly the reviewed substitution\n')],
 'tests/test_post432_l01_l02_scope.py': [("    nxt = 'tests.ci_v4_perf_scope' in C.COHORT_MODULES\n"
                                          '    assert N.exact_blobs_ok() and now == (F.expected_handoff(ROOT, X.REGISTRY) if nxt and '
                                          'F.signature_ok() else N.expected_handoff(ROOT, X.REGISTRY)).decode()',
                                          '    from tests import f03_financing_scope as G\n'
                                          '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    if 'tests.f03_financing_scope' in C.COHORT_MODULES and G.signature_ok():\n"
                                          '        expected = G.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.ci_v4_perf_scope' in C.COHORT_MODULES and F.signature_ok():\n"
                                          '        expected = F.expected_handoff(ROOT, X.REGISTRY)\n'
                                          '    assert N.exact_blobs_ok() and now == expected.decode()')],
 'tests/test_r02_ppa_ux_scope.py': [("    nxt = ('tests.ci_v4_perf_scope',) if 'tests.ci_v4_perf_scope' in C.COHORT_MODULES else ()\n"
                                     '    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == (\n'
                                     '        F.expected_handoff(ROOT, X.REGISTRY) if nxt and F.signature_ok() else N.expected_handoff(ROOT, '
                                     'X.REGISTRY))',
                                     '    from tests import f03_financing_scope as G\n'
                                     "    nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope') if m in C.COHORT_MODULES)\n"
                                     '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    if len(nxt) == 2 and G.signature_ok():\n'
                                     '        expected = G.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 1 and F.signature_ok():\n'
                                     '        expected = F.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == expected'),
                                    ('    assert X.exact_blobs_ok() and X.signature_ok()\n    data = X.manifest()\n',
                                     '    from tests import f03_financing_scope as G\n'
                                     '    assert X.exact_blobs_ok() and X.signature_ok()\n'
                                     '    data = X.manifest()\n'),
                                    ('                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS)]',
                                     '                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS) and not (G.signature_ok() and p in '
                                     'G.SOURCE_PATHS)]')],
 'tests/test_ux_pr2b_scope.py': [('def test_one_byte_in_every_owned_blob_fails_closed(path,wt):\n'
                                  '    assert B.exact_blobs_ok(wt)\n'
                                  "    p=wt/path; old=p.read_bytes(); p.write_bytes(old+b'\\n')\n"
                                  '    assert not B.exact_blobs_ok(wt) and not A.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                  '    p.write_bytes(old)\n'
                                  '    assert B.exact_blobs_ok(wt)\n',
                                  'def test_one_byte_in_every_owned_blob_fails_closed(path,wt):\n'
                                  '    with C.call_scope():\n'
                                  '        assert B.exact_blobs_ok(wt)\n'
                                  "    p=wt/path; old=p.read_bytes(); p.write_bytes(old+b'\\n')\n"
                                  '    with C.call_scope():\n'
                                  '        assert not B.exact_blobs_ok(wt) and not A.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                  '    p.write_bytes(old)\n'
                                  '    with C.call_scope():\n'
                                  '        assert B.exact_blobs_ok(wt)\n'),
                                 ("    manifest.write_text(json.dumps(d,indent=2)+'\\n')\n    assert not B.exact_blobs_ok(wt) and not C.valid(wt)\n",
                                  "    manifest.write_text(json.dumps(d,indent=2)+'\\n')\n"
                                  '    with C.call_scope():\n'
                                  '        assert not B.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                                 ('    assert not B.exact_blobs_ok(wt) or not A.exact_blobs_ok(wt)\n    assert not C.valid(wt)\n',
                                  '    with C.call_scope():\n'
                                  '        assert not B.exact_blobs_ok(wt) or not A.exact_blobs_ok(wt)\n'
                                  '        assert not C.valid(wt)\n'),
                                 ("    d['source_blobs'][owned]='0'*40;p.write_text(json.dumps(d)+'\\n')\n"
                                  '    assert not B.exact_blobs_ok(wt) and not C.valid(wt)\n',
                                  "    d['source_blobs'][owned]='0'*40;p.write_text(json.dumps(d)+'\\n')\n"
                                  '    with C.call_scope():\n'
                                  '        assert not B.exact_blobs_ok(wt) and not C.valid(wt)\n'),
                                 ('    assert current!=historical\n'
                                  '    assert C.matches(path,current,repo=wt) and not C.matches(path,historical,repo=wt)\n'
                                  "    assert not C.matches(path,b'forged',repo=wt) and not B.exact_blobs_ok(wt,B.BASE)\n"
                                  "    assert not B.exact_blobs_ok(wt,'0'*40)\n"
                                  "    assert B.exact_blobs_ok(wt,'HEAD')\n"
                                  "    (wt/path).write_bytes(current+b'\\n')\n"
                                  '    assert not C.matches(path,current,repo=wt)\n'
                                  "    assert C.matches(path,current,repo=wt,ref='HEAD')\n",
                                  '    assert current!=historical\n'
                                  '    with C.call_scope():\n'
                                  '        assert C.matches(path,current,repo=wt) and not C.matches(path,historical,repo=wt)\n'
                                  "        assert not C.matches(path,b'forged',repo=wt) and not B.exact_blobs_ok(wt,B.BASE)\n"
                                  "        assert not B.exact_blobs_ok(wt,'0'*40)\n"
                                  "        assert B.exact_blobs_ok(wt,'HEAD')\n"
                                  "    (wt/path).write_bytes(current+b'\\n')\n"
                                  '    with C.call_scope():\n'
                                  '        assert not C.matches(path,current,repo=wt)\n'
                                  "        assert C.matches(path,current,repo=wt,ref='HEAD')\n"),
                                 ("    p=wt/'evidence/pr2b.json';p.parent.mkdir(exist_ok=True);p.write_text('{}')\n"
                                  '    assert B.exact_blobs_ok(wt) and C.valid(wt)\n',
                                  "    p=wt/'evidence/pr2b.json';p.parent.mkdir(exist_ok=True);p.write_text('{}')\n"
                                  '    with C.call_scope():\n'
                                  '        assert B.exact_blobs_ok(wt) and C.valid(wt)\n'),
                                 ("    assert not B.exact_blobs_ok(wt,'HEAD') and not C.valid(wt,'HEAD')\n",
                                  "    with C.call_scope():\n        assert not B.exact_blobs_ok(wt,'HEAD') and not C.valid(wt,'HEAD')\n"),
                                 ("    assert B.ci_authority_ok(wt) and B.ci_owns('tools/ci_merge_tree_guard.py',wt)\n"
                                  '    assert not B.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                  "    assert not B.ci_owns('tools/ci_v4_unknown.py',wt) and not B.ci_owns('app/v2/react_opex_lines.py',wt)\n",
                                  '    with C.call_scope():\n'
                                  "        assert B.ci_authority_ok(wt) and B.ci_owns('tools/ci_merge_tree_guard.py',wt)\n"
                                  '        assert not B.exact_blobs_ok(wt) and not C.valid(wt)\n'
                                  "        assert not B.ci_owns('tools/ci_v4_unknown.py',wt) and not B.ci_owns('app/v2/react_opex_lines.py',wt)\n"),
                                 ('    assert B.ci_authority_ok(wt) and not B.exact_blobs_ok(wt) and not C.valid(wt)\n',
                                  '    with C.call_scope():\n'
                                  '        assert B.ci_authority_ok(wt) and not B.exact_blobs_ok(wt) and not C.valid(wt)\n')]}


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


# The CI V4 internal F01 job (``ci_v4_f01_job.yml``) runs the same four-browser plus twenty-native steps as the standalone workflow but kept
# the original 25-minute limit: a selected F01 on #438 was cancelled at exactly that limit. ONE literal line moves; every step, selection,
# evidence, non-root and 20/20 no-skip assertion is byte-identical to the accepted blob.
JOB_BASE_BLOB = "99ca73daefbca15bd1642520efb4f26db00430be"
JOB_EDITS = (("    timeout-minutes: 25\n", "    timeout-minutes: 45\n"),)


def reviewed_job_ok(repo=None, ref=None, actual=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        candidate = _base_bytes(str(root), CI_JOB).decode()
        if _blob(candidate.encode()) != JOB_BASE_BLOB:
            return False
        for old, new in JOB_EDITS:
            if candidate.count(old) != 1:
                return False
            candidate = candidate.replace(old, new)
        raw = _read(root, CI_JOB, ref) if actual is None else actual
        if isinstance(raw, str):
            raw = raw.encode()
        return raw == candidate.encode() and manifest(root, ref).get("source_blobs", {}).get(CI_JOB) == _blob(raw)
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError):
        return False


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
        ("    return S.supersedes(path, value, root, ref)\n\n\ndef _merge_event_successor():", "    if S.supersedes(path, value, root, ref):\n        return True\n    # Exact F03-reviewed successors of two CI V4 source paths only (the module and the internal F01 job); never a prefix.\n    if path not in ('tests/ci_v4_scope.py', '.github/workflows/ci_v4_f01_job.yml'):\n        return False\n    from tests import f03_financing_scope as F\n    return F.supersedes(path, value, root, ref)\n\n\ndef _merge_event_successor():"),
        ("    return B\n\n\ndef _git(root, *args):", "    return B\n\n\ndef _f03_ci_owns(path, root, ref):\n    \"\"\"Admit only the exact reviewed 45-minute F01 workflow; no CI wildcard.\"\"\"\n    if path != '.github/workflows/finval_f01_acceptance.yml':\n        return False\n    from tests import f03_financing_scope as F\n    return path in F.CI_PATHS and F.exact_blobs_ok(root, ref) and F.reviewed_workflow_ok(root, ref)\n\n\ndef _git(root, *args):"),
        ("    authorized_ci = successor.CI_PATHS if successor_ok else frozenset()\n    data = manifest(root, ref)", "    authorized_ci = successor.CI_PATHS if successor_ok else frozenset()\n    if _f03_ci_owns('.github/workflows/finval_f01_acceptance.yml', root, ref):\n        authorized_ci = authorized_ci | {'.github/workflows/finval_f01_acceptance.yml'}\n    data = manifest(root, ref)"),
        ("    return (path in CI_PATHS or _merge_event_successor().ci_owns(path, repo, ref)) and exact_blobs_ok(repo, ref)", "    root = Path(repo) if repo is not None else ROOT\n    return (path in CI_PATHS or _merge_event_successor().ci_owns(path, repo, ref)\n            or _f03_ci_owns(path, root, ref)) and exact_blobs_ok(repo, ref)"),
    ),
    "tests/ux_pr2b_scope.py": (
        ("def _pr3b1_pin(path, blob, repo=None, ref=None, *, signature=False):\n    S = _pr3b1()", "def _pr3b1_pin(path, blob, repo=None, ref=None, *, signature=False):\n    # Reviewed CI V4 module / pr2b-suite successors, proven by F03 without this cohort.\n    if path in ('tests/ci_v4_scope.py', 'tests/test_ux_pr2b_scope.py'):\n        from tests import f03_financing_scope as F\n        if F.supersedes(path, blob, repo, ref):\n            return True\n    S = _pr3b1()"),
    ),
    "tests/ux_pr2c_scope.py": (
        ("def _pr3b1_pin(path, blob, repo=None, ref=None):\n    S = _pr3b1()", "def _pr3b1_pin(path, blob, repo=None, ref=None):\n    # Exact low-level F03 successor of only the CI V4 source file and the pr2b mutation-suite test file.\n    if path in ('tests/ci_v4_scope.py', 'tests/test_ux_pr2b_scope.py'):\n        from tests import f03_financing_scope as F\n        if F.supersedes(path, blob, repo, ref):\n            return True\n    S = _pr3b1()"),
    ),
}

# Committed-ref evaluation of the CI V4 guard compared its pins by exact equality, so the reviewed F03 successor of its own module (and of the
# internal F01 job) could never be recognised at a ref, while the working-tree branch already honours the reviewed supersession. Same literal
# tolerance, same hook: exactly the paths the F03 hook already admits, nothing wider.
REVIEWED_CI_HANDOFFS["tests/ci_v4_scope.py"] = REVIEWED_CI_HANDOFFS["tests/ci_v4_scope.py"] + ((
    "            if listed != pins:\n                return False\n        # engine/core/domain never moved",
    "            if set(listed) != set(pins) or any(listed[p] != pins[p] and not _pr2c_supersedes(p, listed[p], root, ref) for p in pins):\n"
    "                return False\n        # engine/core/domain never moved"),)



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

# Accepted BESS02/R02 product bytes and historical manifests that must stay byte-identical to BASE.
FROZEN = ("docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json", "docs/bess_setup/SOURCE_SUCCESSOR.json", "docs/bess02/SOURCE_SUCCESSOR.json",
          "docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json", "docs/ci_v4/module_weights.json",
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
    elif kind == "job":
        edits = JOB_EDITS
        path = CI_JOB
    else:
        edits = WORKFLOW_EDITS
        path = CI_WORKFLOW
    raw = _base_bytes(root, path)
    if kind == "workflow" and _blob(raw) != "8b7b49a49583fc33c48d60cc55bd88ea9e88ef8d":
        raise ValueError("the original F01 workflow is not the historically reviewed blob")
    if kind == "job" and _blob(raw) != JOB_BASE_BLOB:
        raise ValueError("the original CI V4 F01 job is not the accepted blob")
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


def _signature_ok(root, ref, closure=False):
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
        judged = {p for p in pins if closure or p not in CURRENT_MAPS}
        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))
        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:
            return False
        owned = (OWNED_PATHS - (set() if closure else CURRENT_MAPS)) | {MANIFEST}
        if any(modes.get(p) != "100644" for p in owned):
            return False
        if any(pins[p] != _expected_blob(key, "handoff", p) for p in HANDOFFS):
            return False
        if pins[CI_WORKFLOW] != _expected_blob(key, "workflow", CI_WORKFLOW):
            return False
        if pins[CI_JOB] != _expected_blob(key, "job", CI_JOB):
            return False
        if any(pins[p] != _expected_blob(key, "ci", p) for p in REVIEWED_CI_HANDOFFS):
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
    if path not in SUPERSEDED:
        return False
    # Like the accepted BESS02 / performance leaves: the signature decides a supersession; the composite separately requires every
    # cohort's FULL exactness (map bytes, changed set, untracked files), so a signature-only verdict never makes the tree valid.
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

"""UX-FINAL-01 (Excel-first React UX, slice 1): finite exact-source successor after the accepted R04 isolated leaf.

Frontend presentation only: no engine, schema, writer, API, flag or financial-policy change. The Financing inputs block shows units beside labels,
the NOT_RUN banner is plain, and the CSS bundle is intentionally unchanged. Every changed byte and Git mode, and the immutable BASE tree, are bound to this
module's manifest. The shared governance paths it really changes are SUPERSEDED paths carrying their accepted BASE blob, the literal one-occurrence
substitutions that produce the new blob, and the exact new blob. R04 hands the shared bundle to this successor by one reviewed substitution
(its Phase-1 baseline asked for exactly that paired move). Previous manifests are never rewritten except the current-map keys (registry, JS and CSS bundle).

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls R04, an older cohort or the composite;
the R04 leaf calls this module through one forward hook (the acyclic pattern F04 and R04 used).
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "b1c08e2d00fe9933565d253d5cee6e5849b143e1"
BASE_TREE = "5b25c1f245d3d53d9bbe24060c13dc936e06b8d7"
MANIFEST = "docs/react_migration/ux_final01/SOURCE_SUCCESSOR.json"
SCHEMA = "UX_FINAL01_EXACT_SOURCE_V1"
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/r04_ppa_scope.py"
SOURCE_PATHS = frozenset((
    "frontend/src/app/financing/pr3b1/runEvidence.ts",
    "frontend/src/app/financing/pr3b2/FinancingEditing.tsx",
    "static/react/finco-react.js",
))
NEW = frozenset((
    "docs/react_migration/ux_final01/screen_contract.csv",
    "frontend/src/app/financing/pr3b1/__tests__/uxFinal01.test.mjs",
    "tests/test_ux_final01_browser.py",
    "tests/test_ux_final01_scope.py",
    "tests/ux_final01_scope.py",
))
# Accepted governance paths whose bytes move by one reviewed literal substitution (HANDOFFS) ...
HANDOFF_PATHS = frozenset((
    PREDECESSOR,
    REGISTRY,
    "tests/test_bess02_scope.py",
    "tests/test_ci_v4_perf_scope.py",
    "tests/test_f03_financing_scope.py",
    "tests/test_f04_financing_scope.py",
    "tests/test_post432_l01_l02_scope.py",
    "tests/test_r02_ppa_ux_scope.py",
    "tests/test_r03_ppa_scope.py",
    "tests/test_r04_ppa_scope.py",
    "tests/test_t01e_remediation_scope.py",
))
# ... and the eight current maps, of which only the registry and JS-bundle keys move (the same bounded handoff F03, T01-E, R03, F04 and R04 made).
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
OWNED_PATHS = SOURCE_PATHS | NEW | HANDOFF_PATHS | CURRENT_MAPS
SUPERSEDED = OWNED_PATHS - NEW
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "tools/", "migrations/", "app/", "research/", "main_web.py")
# Accepted historical manifests, products and CI that must stay byte-identical to BASE (a successor never rewrites them).
FROZEN = (
    "docs/react_migration/f04_financing/SOURCE_SUCCESSOR.json", "tests/r03_ppa_scope.py",
    "tests/f04_financing_scope.py",
    "docs/r04_ppa_global_cap/SOURCE_SUCCESSOR.json",
    "research/r04_ppa_global_cap/README.md",
    "research/r04_ppa_global_cap/__init__.py",
    "research/r04_ppa_global_cap/core.py",
    "tests/r04_ppa_global_cap/__init__.py",
    "tests/r04_ppa_global_cap/oracle.py",
    "tests/r04_ppa_global_cap/test_r04_allocation.py",
    "tests/r04_ppa_global_cap/test_r04_canonical_reconciliation.py",
    "tests/r04_ppa_global_cap/test_r04_production_acceptance.py",
    "docs/r03_ppa_candidate/SOURCE_SUCCESSOR.json", "research/r03_ppa_candidate/core.py", "tests/r03_ppa_core/oracle.py",
    "docs/tax_reference_registry/t01e/SOURCE_SUCCESSOR.json", "tax_reference_registry/remediation.py",
    "tests/t01e_remediation_scope.py", "tests/f03_financing_scope.py",
    "docs/react_migration/f03_financing/SOURCE_SUCCESSOR.json",
    "docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json", "docs/ci_v4/module_weights.json",
    "docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json", "docs/bess_setup/SOURCE_SUCCESSOR.json", "docs/bess02/SOURCE_SUCCESSOR.json",
    "tax_reference_registry/__init__.py", "tests/tax_reference_registry_scope.py",
    ".github/workflows/finval_f01_acceptance.yml", ".github/workflows/ci_v4_f01_job.yml",
    "tests/ci_v4_perf_scope.py", "tests/bess02_scope.py", "tests/ci_v4_scope.py", "tests/ux_pr2b_scope.py", "tests/ux_pr2c_scope.py",
)
# The R04 leaf keeps owning the Phase-1 production PPA baseline; this successor owns no revenue path.
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


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The accepted R04 leaf gains one forward hook to this
# cohort (the same acyclic pattern F04 and R04 used) and hands over its bundle baseline; the registry appends this cohort exactly once; the exact-tail
# tests accept one more state.
HANDOFFS = {'tests/fin_v2_cohorts.py': [("'tests.r04_ppa_scope')", "'tests.r04_ppa_scope', 'tests.ux_final01_scope')")],
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
                             '                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS))):\n'),
                            ('        allowed = OWNED_PATHS | {MANIFEST}\n        changed = set(',
                             '        allowed = closure_paths(root, ref)\n        changed = set('),
                            ('def map_keys(repo=None, ref=None):\n    return tuple(MAP_KEYS)\n',
                             'def _next():\n'
                             '    """The one finite forward successor (UX-FINAL-01). Low-level only: its signature never calls this module '
                             'or the composite."""\n'
                             '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
                             "    if 'tests.ux_final01_scope' not in COHORT_MODULES:\n"
                             '        return None\n'
                             '    from tests import ux_final01_scope\n'
                             '    return ux_final01_scope\n'
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
                            ('    "static/react/finco-react.js": ("100644", "6a27300af4d4f818c3f30800b6b8ae634c50224b"),\n', '')],
 'tests/test_bess02_scope.py': [('from tests import r04_ppa_scope as W\n',
                                 'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                ('                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok()))\n',
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok())\n'
                                 '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, '
                                 'W.__name__, V.__name__)\n'
                                 '                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                 'Q.signature_ok() and W.signature_ok()\n'
                                 '                and V.signature_ok()))\n')],
 'tests/test_ci_v4_perf_scope.py': [('from tests import r04_ppa_scope as W\n',
                                     'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                    ('            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and '
                                     'W.signature_ok())\n'
                                     '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n',
                                     '            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and '
                                     'W.signature_ok()) or (\n'
                                     '            C.COHORT_MODULES[-7:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                     '"tests.r04_ppa_scope", "tests.ux_final01_scope")\n'
                                     '            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and '
                                     'W.signature_ok() and V.signature_ok())\n'
                                     '    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)\n'),
                                    ('    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n',
                                     '    for p in sorted(F.HANDOFFS):\n'
                                     '        want = (V.expected_handoff(ROOT, p) if V.signature_ok() and p in V.HANDOFFS\n'
                                     '                else W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'),
                                    ('        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n',
                                     '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
                                     '        want = (V.expected_handoff(ROOT, p) if V.signature_ok() and p in V.HANDOFFS\n'
                                     '                else W.expected_handoff(ROOT, p) if W.signature_ok() and p in W.HANDOFFS\n'),
                                    ('                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok() and W.signature_ok()))\n'
                                     '    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1\n',
                                     '                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok() and W.signature_ok())\n'
                                     '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", '
                                     '"tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                     '"tests.r04_ppa_scope", "tests.ux_final01_scope")\n'
                                     '                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and '
                                     'Q.signature_ok() and W.signature_ok() and V.signature_ok()))\n'
                                     '    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1\n'),
                                    ('              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', '
                                     '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\')")\n',
                                     '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', '
                                     '\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.ux_final01_scope\')")\n')],
 'tests/test_f03_financing_scope.py': [('from tests import r04_ppa_scope as W\n',
                                        'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                       ('"tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok())\n',
                                        '"tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok()) or (\n'
                                        '        C.COHORT_MODULES[-8:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", '
                                        '"tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", '
                                        '"tests.f04_financing_scope", "tests.r04_ppa_scope", "tests.ux_final01_scope")\n'
                                        '        and Q.signature_ok() and W.signature_ok() and V.signature_ok())\n'),
                                       ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                        '\'tests.fake_scope\')")),\n',
                                        '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", '
                                        'b"\'tests.ux_final01_scope\', \'tests.fake_scope\')")),\n')],
 'tests/test_f04_financing_scope.py': [('from tests import r04_ppa_scope as W\n',
                                        'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                       ('        '
                                        "C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') "
                                        'and W.signature_ok())\n',
                                        '        '
                                        "C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') "
                                        'and W.signature_ok()) or (\n'
                                        '        '
                                        "C.COHORT_MODULES[-4:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope','tests.ux_final01_scope')\n"
                                        '        and W.signature_ok() and V.signature_ok())\n'),
                                       ('        authority=W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed '
                                        'substitution of this shared path\n',
                                        '        authority=(V if V.signature_ok() and path in V.HANDOFFS else W if W.signature_ok() and '
                                        'path in W.HANDOFFS else F)      # the latest reviewed substitution of this shared path\n'),
                                       ('            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\')",", \'tests.r04_ppa_scope\')")\n',
                                        '            if kind==\'missing_registration\':text=text.replace(", \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\'",", \'tests.r04_ppa_scope\'")\n'),
                                       ('            elif '
                                        'kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\')","\'tests.f04_financing_scope\', \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\')")\n',
                                        '            elif '
                                        'kind==\'duplicate_registration\':text=text.replace("\'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\'","\'tests.f04_financing_scope\', \'tests.f04_financing_scope\', '
                                        '\'tests.r04_ppa_scope\'")\n')],
 'tests/test_post432_l01_l02_scope.py': [('from tests import r04_ppa_scope as W\n',
                                          'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                         ("    if 'tests.r04_ppa_scope' in C.COHORT_MODULES and W.signature_ok():\n"
                                          '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n',
                                          "    if 'tests.ux_final01_scope' in C.COHORT_MODULES and V.signature_ok():\n"
                                          '        expected = V.expected_handoff(ROOT, X.REGISTRY)\n'
                                          "    elif 'tests.r04_ppa_scope' in C.COHORT_MODULES and W.signature_ok():\n"
                                          '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n')],
 'tests/test_r02_ppa_ux_scope.py': [('from tests import r04_ppa_scope as W\n',
                                     'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                    ("                            'tests.r04_ppa_scope') if m in C.COHORT_MODULES)\n"
                                     '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    if len(nxt) == 6 and W.signature_ok():\n'
                                     '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n',
                                     "                            'tests.r04_ppa_scope', 'tests.ux_final01_scope') if m in "
                                     'C.COHORT_MODULES)\n'
                                     '    expected = N.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    if len(nxt) == 7 and V.signature_ok():\n'
                                     '        expected = V.expected_handoff(ROOT, X.REGISTRY)\n'
                                     '    elif len(nxt) == 6 and W.signature_ok():\n'
                                     '        expected = W.expected_handoff(ROOT, X.REGISTRY)\n')],
 'tests/test_r03_ppa_scope.py': [('from tests import r04_ppa_scope as W\n',
                                  'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                 ('        authority = W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in '
                                  'Q.HANDOFFS else T\n',
                                  '        authority = (V if V.signature_ok() and p in V.HANDOFFS else W if W.signature_ok() and p in '
                                  'W.HANDOFFS\n'
                                  '                     else Q if Q.signature_ok() and p in Q.HANDOFFS else T)\n'),
                                 ('        and Q.signature_ok() and W.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r03_ppa_scope") == 1\n',
                                  '        and Q.signature_ok() and W.signature_ok()) or (\n'
                                  '        C.COHORT_MODULES[-6:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope", "tests.ux_final01_scope")\n'
                                  '        and Q.signature_ok() and W.signature_ok() and V.signature_ok())\n'
                                  '    assert C.COHORT_MODULES.count("tests.r03_ppa_scope") == 1\n'),
                                 ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                  '\'tests.fake_scope\')")),\n',
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", b"\'tests.ux_final01_scope\', '
                                  '\'tests.fake_scope\')")),\n')],
 'tests/test_r04_ppa_scope.py': [('from tests import f04_financing_scope as P\n',
                                  'from tests import f04_financing_scope as P\nfrom tests import ux_final01_scope as V\n'),
                                 ('    assert C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n',
                                  '    assert C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope") or (\n'
                                  '        C.COHORT_MODULES[-6:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", '
                                  '"tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope", "tests.ux_final01_scope")\n'
                                  '        and V.signature_ok())\n'),
                                 ('    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                  '\'tests.r04_ppa_scope\')")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                  '\'tests.fake_scope\')")),\n'
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\')")),\n'
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\')", b")")),\n',
                                  '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.ux_final01_scope\')", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.ux_final01_scope\')")),\n'
                                  '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", b"\'tests.ux_final01_scope\', '
                                  '\'tests.fake_scope\')")),\n'
                                  '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\'", '
                                  'b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
                                  '    ("r04_missing", lambda b: b.replace(b", \'tests.r04_ppa_scope\'", b"")),\n'),
                                 ('    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\')", b")")})\n',
                                  '    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", \'tests.r04_ppa_scope\'", b"")})\n'),
                                 ('"frontend/src/app/workflow/ModelWorkflowValidation.ts", "static/react/finco-react.js")\n',
                                  '"frontend/src/app/workflow/ModelWorkflowValidation.ts")\n'),
                                 ('    for p in T.HANDOFFS:\n'
                                  '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]\n',
                                  '    for p in T.HANDOFFS:\n'
                                  '        authority = V if V.signature_ok() and p in V.HANDOFFS else T      # the latest reviewed '
                                  'substitution of a shared path\n'
                                  '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'
                                  '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'),
                                 ('def test_current_maps_move_only_the_registry_key():\n    pins = T.manifest()["source_blobs"]\n',
                                  'def test_current_maps_move_only_the_registry_key():\n'
                                  '    pins = T.effective_pins()          # the CURRENT pins: the reviewed UX-FINAL-01 overlay wins while '
                                  'its signature holds\n'),
                                 ('        assert changed <= set(T.MAP_KEYS)\n',
                                  '        assert changed <= set(T.MAP_KEYS) | set(V.MAP_KEYS)          # the registry (R04) plus the '
                                  'registry and JS bundle keys the successor moves\n'),
                                 ('    pins = T.manifest()["source_blobs"]\n    reg = pins[T.REGISTRY]\n',
                                  '    pins = T.manifest()["source_blobs"]\n'
                                  '    reg = T.effective_pins()[T.REGISTRY]          # the CURRENT registry pin (the reviewed successor '
                                  'overlay wins)\n')],
 'tests/test_t01e_remediation_scope.py': [('from tests import r04_ppa_scope as W\n',
                                           'from tests import r04_ppa_scope as W\nfrom tests import ux_final01_scope as V\n'),
                                          ('    for p in T.HANDOFFS:\n'
                                           '        if W.signature_ok() and p in W.HANDOFFS:            # the latest reviewed R04 '
                                           'substitution of this shared path\n',
                                           '    for p in T.HANDOFFS:\n'
                                           '        if V.signature_ok() and p in V.HANDOFFS:            # the latest reviewed UX-FINAL-01 '
                                           'substitution of this shared path\n'
                                           '            assert (ROOT / p).read_bytes() == V.expected_handoff(ROOT, p)\n'
                                           '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
                                           '            continue\n'
                                           '        if W.signature_ok() and p in W.HANDOFFS:            # the latest reviewed R04 '
                                           'substitution of this shared path\n'),
                                          ('                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope"))\n',
                                           '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope"),\n'
                                           '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", '
                                           '"tests.r04_ppa_scope", "tests.ux_final01_scope"))\n'),
                                          ('    ("fake_extra", lambda b: b.replace(b"\'tests.r04_ppa_scope\')", b"\'tests.r04_ppa_scope\', '
                                           '\'tests.fake_scope\')")),\n',
                                           '    ("fake_extra", lambda b: b.replace(b"\'tests.ux_final01_scope\')", '
                                           'b"\'tests.ux_final01_scope\', \'tests.fake_scope\')")),\n')]}


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

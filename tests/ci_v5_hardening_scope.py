"""CI V5-2B exact-source successor (after the one-time V5 bootstrap cohort): ONE finite, terminal exact-source ownership successor (2026-11-16).

BASE is accepted main (``36158f91``, merged #453). V4 requires every changed path to be owned by a registered cohort; the V5-2B hardening PR rewrites eight
files that the V5 bootstrap cohort owns (the evaluator, B5, the candidate generator, the shadow orchestrator, the shadow workflow, the A/B/A harness, the
README and the explicit delta), and adds the V5-2B hardening test and this cohort. It is NOT V5 activation: it promotes no epoch (``docs/ci_v5/epoch.json``
is never owned), makes no V5 verdict authoritative or required, changes no V4 selector, scheduler, aggregator, required workflow, policy, weight, node
split, financial or UI byte, and selects, deletes, skips or moves no test.

Every changed byte, Git mode and the immutable BASE tree are bound to this module's manifest. The shared governance paths this successor really changes (the
C06, B1, B2 and B3 tail tuples, the V5 bootstrap forward hook, the composite registry, the U1 discovery list, the exact-tail tests and the current maps)
are SUPERSEDED paths: each carries its accepted BASE blob, the literal one-occurrence substitutions that produce its new blob and the exact new blob. The
eight V5 files the bootstrap cohort owned are REPLACED paths: each carries its accepted BASE blob and the exact new blob (a literal substitution of a whole
rewritten file would only duplicate it). ``.github/`` and ``tools/`` are admitted ONLY for literal paths the bootstrap already admitted (CI_PATHS); no
pattern, prefix or wildcard widens the scope.

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls the bootstrap cohort, an older cohort or the
composite; the bootstrap cohort calls this module through one forward hook (the acyclic C06->B1->B2->B3->V5_BOOTSTRAP pattern, one step further). Nothing is
cached across calls: the read scope is dropped when the OUTERMOST block exits.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = "36158f91c20c3a79073c7b7cc387f647d157ee6a"
BASE_TREE = "20e13113ae180f770ae0f2d273b8b60c8b0174fc"
MANIFEST = "docs/ci_v5/hardening_2b/SOURCE_SUCCESSOR.json"
SCHEMA = "CI_V5_2B_EXACT_SOURCE_V1"
AUTHORIZATION = ("CI V5-2B hardening (2026-11-16): one finite exact-source ownership successor of the V5 bootstrap cohort for the V5 evaluator schema V2, the split "
                 "shadow lane and their tests; no V5 activation, no epoch promotion, no required check, no selector, policy, workflow (other than the one "
                 "non-required shadow workflow), scheduling-weight, product, financial or test-selection change; no merge or deployment authority.")
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v5_bootstrap_scope.py"
BASE_COHORTS = (
    'tests.fin_v2_3_scope',
    'tests.fin_v2_ci_scope',
    'tests.fin_v2_d01_scope',
    'tests.fin_v2_r1_scope',
    'tests.fin_v2_rcux_scope',
    'tests.fin_v2_pr394_corr_scope',
    'tests.wsv2_core_scope',
    'tests.fin_v2_wsv2_scope',
    'tests.wf04_scope',
    'tests.wf03_lifecycle_scope',
    'tests.fin_v2_wf06a_scope',
    'tests.fin_v2_integration_409_scope',
    'tests.wf06b_scope',
    'tests.u1_scope',
    'tests.post413_r17_scope',
    'tests.post413_r18_scope',
    'tests.post413_r1_scope',
    'tests.u2_scope',
    'tests.ci_v4_scope',
    'tests.g10_d8_scope',
    'tests.post413_o1_scope',
    'tests.ux_pr1_scope',
    'tests.ux_pr2a_scope',
    'tests.ux_pr2b_scope',
    'tests.ux_pr2c_scope',
    'tests.ux_pr3b1_scope',
    'tests.ux_pr3b2_scope',
    'tests.tax_reference_registry_scope',
    'tests.on_bess01_scope',
    'tests.onaccept01_scope',
    'tests.post432_l01_l02_scope',
    'tests.r02_ppa_ux_scope',
    'tests.bess02_scope',
    'tests.ci_v4_perf_scope',
    'tests.f03_financing_scope',
    'tests.t01e_remediation_scope',
    'tests.r03_ppa_scope',
    'tests.f04_financing_scope',
    'tests.r04_ppa_scope',
    'tests.c06_cost_workspace_scope',
    'tests.ci_v4_lean_b1_scope',
    'tests.ci_v4_lean_b2_scope',
    'tests.ci_v4_lean_b3_scope',
    'tests.ci_v5_bootstrap_scope',
)
NEW = frozenset((
    'tests/ci_v5_hardening_scope.py',
    'tests/test_ci_v5_hardening.py',
    'tests/test_ci_v5_hardening_scope.py',
))
# The V5 files the bootstrap cohort owned, rewritten by this PR (REPLACED: accepted BASE blob + exact new blob; ``.github/`` and ``tools/`` stay literal).
REPLACED = frozenset((
    '.github/workflows/ci_v5_shadow.yml',
    'docs/ci_v5/README.md',
    'docs/ci_v5/delta.json',
    'tests/test_ci_v5_foundation.py',
    'tools/ci_v5_b5.py',
    'tools/ci_v5_candidate.py',
    'tools/ci_v5_epoch.py',
    'tools/ci_v5_shadow.py',
))
# The ONLY ``.github/`` and ``tools/`` paths this cohort owns: exactly the literal paths the bootstrap cohort already admitted. Never a prefix, never a pattern.
CI_PATHS = frozenset((
    ".github/workflows/ci_v5_shadow.yml",
    "tools/ci_v5_b5.py",
    "tools/ci_v5_candidate.py",
    "tools/ci_v5_epoch.py",
    "tools/ci_v5_shadow.py",
))
# Shared governance paths whose bytes move by one reviewed literal substitution (HANDOFFS).
HANDOFF_PATHS = frozenset((
    'tests/c06_cost_workspace_scope.py',
    'tests/ci_v4_lean_b1_scope.py',
    'tests/ci_v4_lean_b2_scope.py',
    'tests/ci_v4_lean_b3_scope.py',
    'tests/ci_v5_bootstrap_scope.py',
    'tests/fin_v2_cohorts.py',
    'tests/test_bess02_scope.py',
    'tests/test_c06_cost_workspace_scope.py',
    'tests/test_ci_v4_lean_b1_scope.py',
    'tests/test_ci_v4_lean_b2_scope.py',
    'tests/test_ci_v4_lean_b3_scope.py',
    'tests/test_ci_v4_lean_tamper_matrix.py',
    'tests/test_ci_v4_perf_scope.py',
    'tests/test_ci_v5_bootstrap_scope.py',
    'tests/test_f03_financing_scope.py',
    'tests/test_f04_financing_scope.py',
    'tests/test_post432_l01_l02_scope.py',
    'tests/test_r02_ppa_ux_scope.py',
    'tests/test_r03_ppa_scope.py',
    'tests/test_r04_ppa_scope.py',
    'tests/test_t01e_remediation_scope.py',
    'tests/u1_scope.py',
))
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
MAP_KEYS = ('tests/fin_v2_cohorts.py', 'tests/u1_scope.py')
SUPERSEDED = HANDOFF_PATHS | REPLACED | CURRENT_MAPS
OWNED_PATHS = NEW | SUPERSEDED
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", "migrations/", "app/", "research/", "frontend/", "static/", "main_web.py")
NEW_ONLY_PREFIXES = (".github/", "tools/")
# Accepted CI V4 control sources that this successor must leave byte-identical to BASE.
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


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The V5 bootstrap cohort gains one forward hook to this cohort
# (the same acyclic pattern B3 received from B2 and the bootstrap from B3); the C06, B1, B2 and B3 layers accept one more reviewed tail state; the registry
# appends this cohort exactly once; the U1 discovery list names it; the exact-tail tests accept one more state.
HANDOFFS = {
    'tests/c06_cost_workspace_scope.py': [
        ((
            '\r\n'
            'def _v5_handoffs(root, ref):\r\n'
            '    """The shared paths the one-time CI V5 bootstrap successor further substitutes (its literal HANDOFFS), only while its signature holds. It is reached through the\r\n'
            '    B1 -> B2 -> B3 reviewed-edit chain, which verifies those bytes; nothing is admitted here."""\r\n'
            '    from tests import ci_v5_bootstrap_scope as V\r\n'
            '    return frozenset(V.HANDOFFS) if V.signature_ok(root, ref) else frozenset()\r\n'
            '\r\n'
            '\r\n'
            'def reviewed_edits_ok(repo=None, ref=None):\r\n'),
         (
            '\r\n'
            'def _v5_handoffs(root, ref):\r\n'
            '    """The shared paths the one-time CI V5 bootstrap successor further substitutes (its literal HANDOFFS), only while its signature holds. It is reached through the\r\n'
            '    B1 -> B2 -> B3 reviewed-edit chain, which verifies those bytes; nothing is admitted here."""\r\n'
            '    from tests import ci_v5_bootstrap_scope as V\r\n'
            '    from tests.fin_v2_cohorts import COHORT_MODULES\r\n'
            '    out = frozenset(V.HANDOFFS) if V.signature_ok(root, ref) else frozenset()\r\n'
            "    if 'tests.ci_v5_hardening_scope' in COHORT_MODULES:      # the V5-2B hardening successor, one chain step further (literal HANDOFFS, only while its signature holds)\r\n"
            '        from tests import ci_v5_hardening_scope as H\r\n'
            '        out = out | (frozenset(H.HANDOFFS) if H.signature_ok(root, ref) else frozenset())\r\n'
            '    return out\r\n'
            '\r\n'
            '\r\n'
            'def reviewed_edits_ok(repo=None, ref=None):\r\n')),
        ((
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope'),\r\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope')):       # at most the four reviewed successors\r\n"
            '            return False\r\n'),
         (
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope'),\r\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'),\r\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope')):       # at most the five reviewed successors\r\n"
            '            return False\r\n')),
    ],
    'tests/ci_v4_lean_b1_scope.py': [
        ((
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\n'
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope'),\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope')):       # B1 -> B2 -> B3 -> V5 bootstrap, nothing else\n"
            '            return False\n'),
         (
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\n'
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope'),\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'),\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope')):       # B1 -> B2 -> B3 -> V5 bootstrap -> V5-2B, nothing else\n"
            '            return False\n')),
    ],
    'tests/ci_v4_lean_b2_scope.py': [
        ((
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\n'
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope')):       # B2 -> B3 -> V5 bootstrap, nothing else\n"
            '            return False\n'),
         (
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\n'
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope'),\n"
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope')):       # B2 -> B3 -> V5 bootstrap -> V5-2B, nothing else\n"
            '            return False\n')),
    ],
    'tests/ci_v4_lean_b3_scope.py': [
        ((
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n'
            '            return False\n'),
         (
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            "        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope')):\n"
            '            return False\n')),
    ],
    'tests/ci_v5_bootstrap_scope.py': [
        ((
            '        pins = manifest(root, ref).get("source_blobs", {})\n'
            '        for path in HANDOFFS:\n'
            '            actual = _read(root, path, ref)\n'),
         (
            '        pins = manifest(root, ref).get("source_blobs", {})\n'
            '        N = _next()\n'
            '        nxt = N is not None and N.signature_ok(root, ref)\n'
            '        for path in HANDOFFS:\n'
            '            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution of this shared path\n'
            '                continue\n'
            '            actual = _read(root, path, ref)\n')),
        ((
            '                return False\n'
            '        return True\n'
            '    except (OSError, ValueError, KeyError, TypeError, UnicodeError, subprocess.CalledProcessError):\n'),
         (
            '                return False\n'
            '        return N.reviewed_edits_ok(root, ref) if nxt else True\n'
            '    except (OSError, ValueError, KeyError, TypeError, UnicodeError, subprocess.CalledProcessError):\n')),
        ((
            '    try:\n'
            '        yield\n'
            '    finally:\n'),
         (
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
            '    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the changed/untracked checks."""\n'
            '    if mode == "exact":\n'
            '        return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
            '    return _signature_ok(root, ref, mode)\n'
            '\n'),
         (
            '    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the changed/untracked checks."""\n'
            '    from contextlib import nullcontext\n'
            '    N = _next()\n'
            '    with (N.scoped() if N is not None else nullcontext()):\n'
            '        if mode == "exact":\n'
            '            return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n'
            '        return _signature_ok(root, ref, mode)\n'
            '\n')),
        ((
            '\n'
            'def map_keys(repo=None, ref=None):\n'
            '    return tuple(MAP_KEYS)\n'
            '\n'),
         (
            '\n'
            "SUCCESSOR = 'tests.ci_v5_hardening_scope'\n"
            '\n'
            '\n'
            'def _next():\n'
            '    """The one finite forward successor (CI V5-2B hardening). Low-level only: its signature never calls this module or the composite."""\n'
            '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '    if SUCCESSOR not in COHORT_MODULES:\n'
            '        return None\n'
            '    from tests import ci_v5_hardening_scope\n'
            '    return ci_v5_hardening_scope\n'
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
            '        return tuple(MAP_KEYS) + more\n'
            '\n')),
        ((
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '        if COHORT_MODULES != BASE_COHORTS + (__name__,):\n'
            '            return False\n'),
         (
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n'
            '            return False\n')),
        ((
            '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n'
            '        if pins.get("tests/ci_v5_bootstrap_scope.py") != _MODULE_BLOB:\n'
            '            return False\n'),
         (
            '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n'
            '        nx = _next_pins(root, ref)\n'
            '        if nx.get("tests/ci_v5_bootstrap_scope.py", pins.get("tests/ci_v5_bootstrap_scope.py")) != _MODULE_BLOB:\n'
            '            return False\n')),
        ((
            '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
            '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\n'
            '        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\n'
            '            return False\n'),
         (
            '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n'
            '        cur = {p: nx.get(p, b) for p, b in pins.items()}\n'
            '        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\n'
            '        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\n'
            '            return False\n')),
        ((
            '            for p in CURRENT_MAPS:\n'
            '                if current[p] != _expected_map_blob(key, p, tuple(pins[k] for k in MAP_KEYS)):\n'
            '                    return False\n'),
         (
            '            for p in CURRENT_MAPS:\n'
            '                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS))):\n'
            '                    return False\n')),
        ((
            '    try:\n'
            '        allowed = OWNED_PATHS | {MANIFEST}\n'
            '        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref else []), "--").decode().splitlines())\n'),
         (
            '    try:\n'
            '        allowed = closure_paths(root, ref)\n'
            '        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref else []), "--").decode().splitlines())\n')),
        ((
            'def effective_pins(repo=None, ref=None, *, signature=False):\n'
            '    return dict(manifest(repo, ref).get("source_blobs", {}))\n'
            '\n'),
         (
            'def effective_pins(repo=None, ref=None, *, signature=False):\n'
            '    root = Path(repo) if repo is not None else ROOT\n'
            '    with scoped():\n'
            '        pins = dict(manifest(repo, ref).get("source_blobs", {}))\n'
            '        pins.update(_next_pins(root, ref))\n'
            '        return pins\n'
            '\n')),
        ((
            'def closure_paths(repo=None, ref=None):\n'
            '    return OWNED_PATHS | {MANIFEST} if signature_ok(repo, ref) else frozenset()\n'
            '\n'),
         (
            'def closure_paths(repo=None, ref=None):\n'
            '    root = Path(repo) if repo is not None else ROOT\n'
            '    with scoped():\n'
            '        if not signature_ok(root, ref):\n'
            '            return frozenset()\n'
            '        N = _next()\n'
            '        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())\n'
            '\n')),
        ((
            'def supersedes(path, value, repo=None, ref=None):\n'
            '    if path not in SUPERSEDED:\n'),
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
            '    if path not in SUPERSEDED:\n')),
        ((
            '    # files), so a signature-only verdict never makes the tree valid.\n'
            '    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value\n'
            '\n'),
         (
            '    # files), so a signature-only verdict never makes the tree valid.\n'
            '    # the CURRENT pin of this path (the successor overlay wins while its signature holds), never a raw superseded manifest line\n'
            '    return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\n'
            '\n')),
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
    'tests/fin_v2_cohorts.py': [
        ((
            "                  'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope',\n"
            "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope')\n"
            '# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).\n'),
         (
            "                  'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope',\n"
            "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope')\n"
            '# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).\n')),
    ],
    'tests/test_bess02_scope.py': [
        ((
            '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, W.__name__)\n'
            "                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))\n"
            '        and C06_APPROVAL.signature_ok()))\n'),
         (
            '            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__, Y.__name__, Q.__name__, W.__name__)\n'
            "                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))\n"
            '        and C06_APPROVAL.signature_ok()))\n')),
    ],
    'tests/test_c06_cost_workspace_scope.py': [
        ((
            "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
            "    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))       # C06 is followed by the reviewed B1, B2, B3 and V5 bootstrap successors\n"
            '    assert C.COHORT_MODULES.count(F.__name__)==1\n'),
         (
            "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
            "    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))       # C06 is followed by the reviewed B1, B2, B3, V5 bootstrap and V5-2B successors\n"
            '    assert C.COHORT_MODULES.count(F.__name__)==1\n')),
        ((
            "    for path in F.SUPERSEDED:assert data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
            '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None;N3=N2._next() if N2 is not None and N2.signature_ok() else None;N4=N3._next() if N3 is not None and N3.signature_ok() else None\n'
            '    for path in F.HANDOFFS:\n'
            '        later=N4 if N4 is not None and N4.signature_ok() and path in N4.HANDOFFS else N3 if N3 is not None and N3.signature_ok() and path in N3.HANDOFFS else N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'
            '        assert (ROOT/path).read_bytes()==later.expected_handoff(ROOT,path)\n'
            '    from tests import ci_v5_bootstrap_scope as V5\n'
            '    for path in F.FROZEN:\n'
            '        if V5.signature_ok() and path in V5.HANDOFFS:      # the one-time V5 bootstrap successor further substitutes this frozen CI module (literal, pin-exact)\n'
            '            assert (ROOT/path).read_bytes()==V5.expected_handoff(ROOT,path)\n'
            "            assert F._blob((ROOT/path).read_bytes())==V5.manifest()['source_blobs'][path]\n"
            '        else:\n'
            "            assert (ROOT/path).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT)\n"
            '\n'),
         (
            "    for path in F.SUPERSEDED:assert data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
            '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None;N3=N2._next() if N2 is not None and N2.signature_ok() else None;N4=N3._next() if N3 is not None and N3.signature_ok() else None;N5=N4._next() if N4 is not None and N4.signature_ok() else None\n'
            '    for path in F.HANDOFFS:\n'
            '        later=N5 if N5 is not None and N5.signature_ok() and path in N5.HANDOFFS else N4 if N4 is not None and N4.signature_ok() and path in N4.HANDOFFS else N3 if N3 is not None and N3.signature_ok() and path in N3.HANDOFFS else N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'
            '        assert (ROOT/path).read_bytes()==later.expected_handoff(ROOT,path)\n'
            '    from tests import ci_v5_bootstrap_scope as V5\n'
            '    for path in F.FROZEN:\n'
            '        if V5.signature_ok() and path in V5.HANDOFFS:      # the one-time V5 bootstrap successor further substitutes this frozen CI module (literal, pin-exact)\n'
            '            assert (ROOT/path).read_bytes()==V5.expected_handoff(ROOT,path)\n'
            "            assert F._blob((ROOT/path).read_bytes())==V5.manifest()['source_blobs'][path]\n"
            '        else:\n'
            "            assert (ROOT/path).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT)\n"
            '\n')),
        ((
            '        for m in C.cohorts():\n'
            "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'):         # a successor never attests an older accepted ref\n"
            '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n'),
         (
            '        for m in C.cohorts():\n'
            "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'):         # a successor never attests an older accepted ref\n"
            '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n')),
    ],
    'tests/test_ci_v4_lean_b1_scope.py': [
        ((
            '    N2 = N._next() if N is not None and N.signature_ok() else None\n'
            '    N3 = N2._next() if N2 is not None and N2.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        if N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the further reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n'
            '        if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this shared path\n'),
         (
            '    N2 = N._next() if N is not None and N.signature_ok() else None\n'
            '    N3 = N2._next() if N2 is not None and N2.signature_ok() else None\n'
            '    N4 = N3._next() if N3 is not None and N3.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        if N4 is not None and N4.signature_ok() and p in N4.HANDOFFS:      # the further reviewed V5-2B substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N4.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n'
            '        if N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the further reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n'
            '        if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this shared path\n')),
        ((
            '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR),\n'
            '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope"),\n'
            '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == "tests.c06_cost_workspace_scope"\n'),
         (
            '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR),\n'
            '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope"),\n'
            '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"),\n'
            '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope")) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == "tests.c06_cost_workspace_scope"\n')),
        ((
            '    from tests import u1_scope as U\n'
            '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-5:] if m not in ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")) == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1\n'),
         (
            '    from tests import u1_scope as U\n'
            '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-6:] if m not in ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope")) == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1\n')),
        ((
            'def test_registry_mutations_are_rejected(clone):\n'
            '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
            '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')")),\n'
            '        ("b1_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b1_scope\'", b"")),\n'),
         (
            'def test_registry_mutations_are_rejected(clone):\n'
            '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
            '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')")),\n'
            '        ("b1_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b1_scope\'", b"")),\n')),
    ],
    'tests/test_ci_v4_lean_b2_scope.py': [
        ((
            '    T3 = T._next()\n'
            '    T4 = T3._next() if T3 is not None and T3.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        if T4 is not None and T4.signature_ok() and p in T4.HANDOFFS:      # the reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == T4.expected_handoff(ROOT, p)\n'
            '        elif T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p in T3.HANDOFFS:      # the reviewed B3 substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)\n'),
         (
            '    T3 = T._next()\n'
            '    T4 = T3._next() if T3 is not None and T3.signature_ok() else None\n'
            '    T5 = T4._next() if T4 is not None and T4.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        if T5 is not None and T5.signature_ok() and p in T5.HANDOFFS:      # the reviewed V5-2B substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == T5.expected_handoff(ROOT, p)\n'
            '        elif T4 is not None and T4.signature_ok() and p in T4.HANDOFFS:      # the reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == T4.expected_handoff(ROOT, p)\n'
            '        elif T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p in T3.HANDOFFS:      # the reviewed B3 substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)\n')),
        ((
            '    assert C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"))\n'
            '    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B\n'),
         (
            '    assert C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"))\n'
            '    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B\n')),
        ((
            '    if T.SUCCESSOR in C.COHORT_MODULES:\n'
            '        assert C.COHORT_MODULES[-1] in (T.SUCCESSOR, "tests.ci_v5_bootstrap_scope") and T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"\n'
            '\n'),
         (
            '    if T.SUCCESSOR in C.COHORT_MODULES:\n'
            '        assert C.COHORT_MODULES[-1] in (T.SUCCESSOR, "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope") and T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"\n'
            '\n')),
        ((
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"))\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1\n'),
         (
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"))\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1\n')),
        ((
            'def test_registry_mutations_are_rejected(clone):\n'
            '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'),
         (
            'def test_registry_mutations_are_rejected(clone):\n'
            '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n')),
    ],
    'tests/test_ci_v4_lean_b3_scope.py': [
        ((
            '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
            '    N = T._next()\n'
            '    for p in T.HANDOFFS:\n'
            '        if N is not None and N.signature_ok() and p in N.HANDOFFS:      # the reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
            '        else:\n'
            '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
            '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'),
         (
            '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
            '    N = T._next()\n'
            '    N2 = N._next() if N is not None and N.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        if N2 is not None and N2.signature_ok() and p in N2.HANDOFFS:      # the reviewed V5-2B substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
            '        elif N is not None and N.signature_ok() and p in N.HANDOFFS:      # the reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)\n'
            '        else:\n'
            '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
            '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n')),
        ((
            '\n'
            'def test_registered_exactly_once_after_b2_with_only_the_reviewed_v5_bootstrap_behind_it():\n'
            '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR)) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[-3:] in (("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"),)\n'
            '    assert B.SUCCESSOR == T.__name__ and B._next() is T and B1.SUCCESSOR == B.__name__ and B1._next() is B\n'),
         (
            '\n'
            'def test_registered_exactly_once_after_b2_with_only_the_reviewed_v5_bootstrap_behind_it():\n'
            "    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, 'tests.ci_v5_hardening_scope')) and C.COHORT_MODULES.count(T.__name__) == 1\n"
            '    assert C.COHORT_MODULES[-3:] in (("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"))\n'
            '    assert B.SUCCESSOR == T.__name__ and B._next() is T and B1.SUCCESSOR == B.__name__ and B1._next() is B\n')),
        ((
            '\n'
            'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_bootstrap():\n'
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b3_scope") == 1\n'),
         (
            '\n'
            'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_bootstrap():\n'
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"))\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b3_scope") == 1\n')),
        ((
            '\n'
            'def test_the_registry_tail_is_one_finite_sequence_for_c06_b1_b2_b3_and_the_v5_bootstrap(monkeypatch):\n'
            '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP is the ONLY accepted tail: any permutation, duplicate, extra cohort or reordered truncation fails the signature of every layer."""\n'
            '    from tests import ci_v5_bootstrap_scope as V\n'
            '    exact = C.COHORT_MODULES\n'
            '    assert exact[-5:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")\n'
            '    layers = (K, B1, B, T, V)\n'
            '    with C.call_scope():\n'
            '        assert all(m.signature_ok() for m in layers)                       # state A: the pristine registry is accepted by every layer\n'
            '    c06, b1, b2, b3, v5 = exact[-5:]\n'
            '    head = exact[:-5]\n'
            '    variants = {\n'
            '        "b2_b3_swapped": head + (c06, b1, b3, b2, v5),\n'
            '        "b1_b2_swapped": head + (c06, b2, b1, b3, v5),\n'
            '        "b3_v5_swapped": head + (c06, b1, b2, v5, b3),\n'
            '        "v5_duplicated": exact + (v5,),\n'
            '        "b3_duplicated": exact + (b3,),\n'
            '        "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",),\n'
            '        "v5_before_c06": head + (v5, c06, b1, b2, b3),\n'
            '        "c06_dropped": head + (b1, b2, b3, v5),\n'
            '        "b3_dropped": head + (c06, b1, b2, v5),\n'
            '    }\n'),
         (
            '\n'
            'def test_the_registry_tail_is_one_finite_sequence_for_c06_b1_b2_b3_the_v5_bootstrap_and_v5_2b(monkeypatch):\n'
            '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B is the ONLY accepted tail: any permutation, duplicate, extra cohort or reordered truncation fails the signature of every layer."""\n'
            '    from tests import ci_v5_bootstrap_scope as V\n'
            '    from tests import ci_v5_hardening_scope as H\n'
            '    exact = C.COHORT_MODULES\n'
            '    assert exact[-6:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope")\n'
            '    layers = (K, B1, B, T, V, H)\n'
            '    with C.call_scope():\n'
            '        assert all(m.signature_ok() for m in layers)                       # state A: the pristine registry is accepted by every layer\n'
            '    c06, b1, b2, b3, v5, h5 = exact[-6:]\n'
            '    head = exact[:-6]\n'
            '    variants = {\n'
            '        "b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5),\n'
            '        "b1_b2_swapped": head + (c06, b2, b1, b3, v5, h5),\n'
            '        "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5),\n'
            '        "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5),\n'
            '        "h5_duplicated": exact + (h5,),\n'
            '        "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5),\n'
            '        "b3_duplicated": exact + (b3,),\n'
            '        "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",),\n'
            '        "h5_before_c06": head + (h5, c06, b1, b2, b3, v5),\n'
            '        "c06_dropped": head + (b1, b2, b3, v5, h5),\n'
            '        "b3_dropped": head + (c06, b1, b2, v5, h5),\n'
            '        "v5_dropped": head + (c06, b1, b2, b3, h5),\n'
            '    }\n')),
    ],
    'tests/test_ci_v4_lean_tamper_matrix.py': [
        ((
            'REG = "tests/fin_v2_cohorts.py"\n'
            'TAIL = "\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')"\n'
            '# row id, invariant class, mutation, injected path, attribution class\n'),
         (
            'REG = "tests/fin_v2_cohorts.py"\n'
            'TAIL = "\'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')"\n'
            '# row id, invariant class, mutation, injected path, attribution class\n')),
        ((
            '    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, B1.PREDECESSOR, "pinned"),\n'
            '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v5_bootstrap_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'
            '    ("current_map_key_forged", "current_map", _forge_map_key, "docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),\n'),
         (
            '    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, B1.PREDECESSOR, "pinned"),\n'
            '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v5_hardening_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'
            '    ("current_map_key_forged", "current_map", _forge_map_key, "docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),\n')),
    ],
    'tests/test_ci_v4_perf_scope.py': [
        ((
            '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))\n"
            '                and C06_APPROVAL.signature_ok())\n'),
         (
            '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))\n"
            '                and C06_APPROVAL.signature_ok())\n')),
        ((
            '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))\n"
            '                and C06_APPROVAL.signature_ok()))\n'),
         (
            '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))\n"
            '                and C06_APPROVAL.signature_ok()))\n')),
        ((
            '\n'
            '\n'
            'def _b4():\n'
            '    """The one reviewed V5 bootstrap successor of B3 while it is registered and exact, else None."""\n'
            '    N = _b3()\n'
            '    N4 = N._next() if N is not None else None\n'
            '    return N4 if N4 is not None and N4.signature_ok() else None\n'
            '\n'
            'from tests import f04_financing_scope as Q\n'),
         (
            '\n'
            '\n'
            'def _b4():\n'
            '    """The one reviewed V5 bootstrap successor of B3 while it is registered and exact, else None."""\n'
            '    N = _b3()\n'
            '    N4 = N._next() if N is not None else None\n'
            '    return N4 if N4 is not None and N4.signature_ok() else None\n'
            '\n'
            '\n'
            'def _b5():\n'
            '    """The one reviewed V5-2B successor of the V5 bootstrap while it is registered and exact, else None."""\n'
            '    N4 = _b4()\n'
            '    N5 = N4._next() if N4 is not None else None\n'
            '    return N5 if N5 is not None and N5.signature_ok() else None\n'
            '\n'
            'from tests import f04_financing_scope as Q\n')),
        ((
            '    for p in sorted(F.HANDOFFS):\n'
            '        want = (_b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n'
            '                else _b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
            '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'),
         (
            '    for p in sorted(F.HANDOFFS):\n'
            '        want = (_b5().expected_handoff(ROOT, p) if _b5() is not None and p in _b5().HANDOFFS\n'
            '                else _b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n'
            '                else _b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
            '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n')),
        ((
            '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
            '        want = (_b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n'
            '                else _b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
            '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'),
         (
            '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
            '        want = (_b5().expected_handoff(ROOT, p) if _b5() is not None and p in _b5().HANDOFFS\n'
            '                else _b4().expected_handoff(ROOT, p) if _b4() is not None and p in _b4().HANDOFFS\n'
            '                else _b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
            '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n')),
        ((
            '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', \'tests.f03_financing_scope\', "\n'
            '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')")\n'
            '    assert text.count(marker) == 1\n'),
         (
            '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', \'tests.f03_financing_scope\', "\n'
            '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')")\n'
            '    assert text.count(marker) == 1\n')),
    ],
    'tests/test_ci_v5_bootstrap_scope.py': [
        ((
            'from tests import ci_v5_bootstrap_scope as T\n'),
         (
            'from tests import ci_v5_bootstrap_scope as T\n'
            'from tests import ci_v5_hardening_scope as H5\n')),
        ((
            '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
            '    for p in T.HANDOFFS:\n'
            '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
            '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'),
         (
            '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
            '    for p in T.HANDOFFS:\n'
            '        if H5.signature_ok() and p in H5.HANDOFFS:                       # the reviewed V5-2B successor further substitutes this shared path (literal, pin-exact)\n'
            '            assert (ROOT / p).read_bytes() == H5.expected_handoff(ROOT, p)\n'
            '        else:\n'
            '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
            '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n')),
        ((
            'def test_registered_exactly_once_as_the_terminal_cohort_after_b3():\n'
            '    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 1                       # exactly ONE module gained; no hardcoded total\n'
            '    assert C.COHORT_MODULES[-2:] == ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")\n'),
         (
            'def test_registered_exactly_once_after_b3_with_only_the_reviewed_v5_2b_behind_it():\n'
            '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR)) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 2                       # exactly ONE module gained after the bootstrap; no hardcoded total\n'
            '    assert C.COHORT_MODULES[-3:] == ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope")\n'
            '    assert T._next() is H5 and T.SUCCESSOR == H5.__name__\n')),
        ((
            'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():\n'
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-1] == "tests.ci_v5_bootstrap_scope" and U.RECONCILED_SUCCESSORS.count("tests.ci_v5_bootstrap_scope") == 1\n'),
         (
            'def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_v5_2b():\n'
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope") and U.RECONCILED_SUCCESSORS.count("tests.ci_v5_bootstrap_scope") == 1\n')),
        ((
            '    tail = b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_bootstrap_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
            '        ("swapped_b3_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'),
         (
            '    tail = b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
            '        ("swapped_b3_v5", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_hardening_scope\')")),\n'
            '        ("v5_2b_missing", lambda b: b.replace(b", \'tests.ci_v5_hardening_scope\'", b"")),\n')),
        ((
            '    pins = T.manifest()["source_blobs"]\n'
            '    reg = pins[T.REGISTRY]\n'
            '    assert B3.supersedes(T.REGISTRY, reg) and B2.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)\n'),
         (
            '    pins = T.manifest()["source_blobs"]\n'
            '    reg = T.effective_pins()[T.REGISTRY]                                             # the CURRENT pin: the V5-2B overlay wins for the registry it superseded\n'
            '    assert reg != pins[T.REGISTRY] and not B3.supersedes(T.REGISTRY, pins[T.REGISTRY])   # the bootstrap-era registry pin is no longer current\n'
            '    assert B3.supersedes(T.REGISTRY, reg) and B2.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)\n')),
        ((
            'def test_the_registry_tail_is_one_finite_sequence_and_v5_is_terminal(monkeypatch):\n'
            '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP is the ONLY accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer present."""\n'
            '    exact = C.COHORT_MODULES\n'
            '    assert exact[-5:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")\n'
            '    layers = (K, B1, B2, B3, T)\n'
            '    with C.call_scope():\n'
            '        assert all(m.signature_ok() for m in layers)\n'
            '    c06, b1, b2, b3, v5 = exact[-5:]\n'
            '    head = exact[:-5]\n'
            '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5), "b1_b2_swapped": head + (c06, b2, b1, b3, v5), "b3_v5_swapped": head + (c06, b1, b2, v5, b3),\n'
            '                "v5_duplicated": exact + (v5,), "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",), "v5_before_c06": head + (v5, c06, b1, b2, b3),\n'
            '                "c06_dropped": head + (b1, b2, b3, v5), "b3_dropped": head + (c06, b1, b2, v5), "b1_dropped": head + (c06, b2, b3, v5)}\n'),
         (
            'def test_the_registry_tail_is_one_finite_sequence_and_v5_2b_is_terminal(monkeypatch):\n'
            '    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B is the ONLY accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer present."""\n'
            '    exact = C.COHORT_MODULES\n'
            '    assert exact[-6:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope")\n'
            '    layers = (K, B1, B2, B3, T, H5)\n'
            '    with C.call_scope():\n'
            '        assert all(m.signature_ok() for m in layers)\n'
            '    c06, b1, b2, b3, v5, h5 = exact[-6:]\n'
            '    head = exact[:-6]\n'
            '    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5), "b1_b2_swapped": head + (c06, b2, b1, b3, v5, h5), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5),\n'
            '                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5), "h5_duplicated": exact + (h5,), "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5),\n'
            '                "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",), "h5_before_c06": head + (h5, c06, b1, b2, b3, v5),\n'
            '                "c06_dropped": head + (b1, b2, b3, v5, h5), "b3_dropped": head + (c06, b1, b2, v5, h5), "b1_dropped": head + (c06, b2, b3, v5, h5), "v5_dropped": head + (c06, b1, b2, b3, h5)}\n')),
        ((
            '              edit(lambda d: d["source_blobs"].__setitem__(DELTA, "0" * 40)), edit(lambda d: d["source_blobs"].__setitem__(CANDIDATE, "0" * 40)),\n'
            '              edit(lambda d: d["source_blobs"].__setitem__(SHADOW, "0" * 40)), edit(lambda d: d["source_blobs"].__setitem__(T.PREDECESSOR, "0" * 40)),\n'),
         (
            '              edit(lambda d: d["source_blobs"].__setitem__(CANDIDATE, "0" * 40)),      # DELTA and SHADOW are further pinned (and judged) by the V5-2B successor: their bootstrap-era pins are shadowed\n'
            '              edit(lambda d: d["source_blobs"].__setitem__(T.PREDECESSOR, "0" * 40)),\n')),
    ],
    'tests/test_f03_financing_scope.py': [
        ((
            '        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))\n"
            '        and C06_APPROVAL.signature_ok())\n'),
         (
            '        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))\n"
            '        and C06_APPROVAL.signature_ok())\n')),
        ((
            '    ("duplicate_f03", lambda b: b.replace(b"\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'", b"\'tests.f03_financing_scope\', \'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_perf_f03", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', \'tests.f03_financing_scope\'", b"\'tests.f03_financing_scope\', \'tests.ci_v4_perf_scope\'")),\n'),
         (
            '    ("duplicate_f03", lambda b: b.replace(b"\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'", b"\'tests.f03_financing_scope\', \'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_perf_f03", lambda b: b.replace(b"\'tests.ci_v4_perf_scope\', \'tests.f03_financing_scope\'", b"\'tests.f03_financing_scope\', \'tests.ci_v4_perf_scope\'")),\n')),
    ],
    'tests/test_f04_financing_scope.py': [
        ((
            "    assert (C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (\n"
            "        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))\n"
            '        and C06_APPROVAL.signature_ok())\n'),
         (
            "    assert (C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (\n"
            "        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))\n"
            '        and C06_APPROVAL.signature_ok())\n')),
        ((
            '        B3=B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        B4=B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '        authority=B4 if B4 is not None and B4.signature_ok() and path in B4.HANDOFFS else B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and path in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n'
            '        assert (ROOT/path).read_bytes()==authority.expected_handoff(ROOT,path)\n'
            '    from tests import ci_v5_bootstrap_scope as V5\n'
            '    for path in F.FROZEN:\n'
            '        if V5.signature_ok() and path in V5.HANDOFFS:      # the one-time V5 bootstrap successor further substitutes this shared path (literal, pin-exact)\n'
            '            assert (ROOT/path).read_bytes()==V5.expected_handoff(ROOT,path)\n'
            "            assert F._blob((ROOT/path).read_bytes())==V5.manifest()['source_blobs'][path]\n"
            '        elif path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
            '            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)\n'),
         (
            '        B3=B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        B4=B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '        B5=B4._next() if B4 is not None and B4.signature_ok() else None\n'
            '        authority=B5 if B5 is not None and B5.signature_ok() and path in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and path in B4.HANDOFFS else B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and path in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n'
            '        assert (ROOT/path).read_bytes()==authority.expected_handoff(ROOT,path)\n'
            '    from tests import ci_v5_bootstrap_scope as V5\n'
            '    for path in F.FROZEN:\n'
            '        if V5.signature_ok() and path in V5.HANDOFFS:      # the one-time V5 bootstrap successor further substitutes this shared path (literal, pin-exact)\n'
            '            assert (ROOT/path).read_bytes()==V5.expected_handoff(ROOT,path)\n'
            "            assert F._blob((ROOT/path).read_bytes())==V5.manifest()['source_blobs'][path]\n"
            '        elif path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():\n'
            '            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)\n')),
    ],
    'tests/test_post432_l01_l02_scope.py': [
        ((
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            "    if 'tests.ci_v5_bootstrap_scope' in C.COHORT_MODULES and B4 is not None and B4.signature_ok():\n"
            '        expected = B4.expected_handoff(ROOT, X.REGISTRY)\n'
            "    elif 'tests.ci_v4_lean_b3_scope' in C.COHORT_MODULES and B3 is not None and B3.signature_ok():\n"
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'),
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '    B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
            "    if 'tests.ci_v5_hardening_scope' in C.COHORT_MODULES and B5 is not None and B5.signature_ok():\n"
            '        expected = B5.expected_handoff(ROOT, X.REGISTRY)\n'
            "    elif 'tests.ci_v5_bootstrap_scope' in C.COHORT_MODULES and B4 is not None and B4.signature_ok():\n"
            '        expected = B4.expected_handoff(ROOT, X.REGISTRY)\n'
            "    elif 'tests.ci_v4_lean_b3_scope' in C.COHORT_MODULES and B3 is not None and B3.signature_ok():\n"
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n')),
    ],
    'tests/test_r02_ppa_ux_scope.py': [
        ((
            "    nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope',\n"
            "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope') if m in C.COHORT_MODULES)\n"
            '    B1 = C06_APPROVAL._next()\n'),
         (
            "    nxt = tuple(m for m in ('tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope',\n"
            "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope') if m in C.COHORT_MODULES)\n"
            '    B1 = C06_APPROVAL._next()\n')),
        ((
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '    if len(nxt) == 11 and B4 is not None and B4.signature_ok():\n'
            '        expected = B4.expected_handoff(ROOT, X.REGISTRY)\n'
            '    elif len(nxt) == 10 and B3 is not None and B3.signature_ok():\n'
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'),
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '    B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
            '    if len(nxt) == 12 and B5 is not None and B5.signature_ok():\n'
            '        expected = B5.expected_handoff(ROOT, X.REGISTRY)\n'
            '    elif len(nxt) == 11 and B4 is not None and B4.signature_ok():\n'
            '        expected = B4.expected_handoff(ROOT, X.REGISTRY)\n'
            '    elif len(nxt) == 10 and B3 is not None and B3.signature_ok():\n'
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n')),
    ],
    'tests/test_r03_ppa_scope.py': [
        ((
            '        C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'))\n"
            '        and C06_APPROVAL.signature_ok())\n'),
         (
            '        C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope'))\n"
            '        and C06_APPROVAL.signature_ok())\n')),
        ((
            '    ("duplicate_r03", lambda b: b.replace(b"\'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", b"\'tests.r03_ppa_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_t01e_r03", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'", b"\'tests.r03_ppa_scope\', \'tests.t01e_remediation_scope\'")),\n'),
         (
            '    ("duplicate_r03", lambda b: b.replace(b"\'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'", b"\'tests.r03_ppa_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_t01e_r03", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'", b"\'tests.r03_ppa_scope\', \'tests.t01e_remediation_scope\'")),\n')),
        ((
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        authority = B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n'
            '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n'),
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '    B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
            '    for p in T.HANDOFFS:\n'
            '        authority = B5 if B5 is not None and B5.signature_ok() and p in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n'
            '        assert (ROOT / p).read_bytes() == authority.expected_handoff(ROOT, p)\n')),
    ],
    'tests/test_r04_ppa_scope.py': [
        ((
            'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
            '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\'))\n'
            '                                                    and C06_APPROVAL.signature_ok())\n'),
         (
            'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
            '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\'))\n'
            '                                                    and C06_APPROVAL.signature_ok())\n')),
        ((
            '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', \'tests.c06_cost_workspace_scope\'")),\n'),
         (
            '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', \'tests.c06_cost_workspace_scope\'")),\n')),
        ((
            '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '        authority = (B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 is not None and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the further reviewed B1 substitution of this shared path\n'
            '                     else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T)\n'),
         (
            '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '        B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
            '        authority = (B5 if B5 is not None and B5.signature_ok() and p in B5.HANDOFFS else B4 if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS else B3 if B3 is not None and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the further reviewed B1 substitution of this shared path\n'
            '                     else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T)\n')),
    ],
    'tests/test_t01e_remediation_scope.py': [
        ((
            '    assert (C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", "tests.f04_financing_scope"),\n'
            '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\'))\n'
            '        and C06_APPROVAL.signature_ok())\n'),
         (
            '    assert (C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", "tests.f04_financing_scope"),\n'
            '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\'), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\'))\n'
            '        and C06_APPROVAL.signature_ok())\n')),
        ((
            '    ("duplicate_t01e", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'", b"\'tests.t01e_remediation_scope\', \'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_f03_t01e", lambda b: b.replace(b"\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'", b"\'tests.t01e_remediation_scope\', \'tests.f03_financing_scope\'")),\n'),
         (
            '    ("duplicate_t01e", lambda b: b.replace(b"\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'", b"\'tests.t01e_remediation_scope\', \'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\')", b"\'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.ci_v5_bootstrap_scope\', \'tests.ci_v5_hardening_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_f03_t01e", lambda b: b.replace(b"\'tests.f03_financing_scope\', \'tests.t01e_remediation_scope\'", b"\'tests.t01e_remediation_scope\', \'tests.f03_financing_scope\'")),\n')),
        ((
            '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '        if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS:            # the further reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == B4.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n'
            '        if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS:            # the further reviewed B3 substitution of this shared path\n'),
         (
            '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        B4 = B3._next() if B3 is not None and B3.signature_ok() else None\n'
            '        B5 = B4._next() if B4 is not None and B4.signature_ok() else None\n'
            '        if B5 is not None and B5.signature_ok() and p in B5.HANDOFFS:            # the further reviewed V5-2B substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == B5.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n'
            '        if B4 is not None and B4.signature_ok() and p in B4.HANDOFFS:            # the further reviewed V5 bootstrap substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == B4.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n'
            '        if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS:            # the further reviewed B3 substitution of this shared path\n')),
    ],
    'tests/u1_scope.py': [
        ((
            '\n'
            "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope')\n"
            '\n'),
         (
            '\n'
            "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope')\n"
            '\n')),
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
        N = _next()
        nxt = N is not None and N.signature_ok(root, ref)
        for path in HANDOFFS:
            if nxt and path in N.HANDOFFS:            # the reviewed successor owns the further substitution of this shared path
                continue
            actual = _read(root, path, ref)
            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):
                return False
        return N.reviewed_edits_ok(root, ref) if nxt else True
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


SUCCESSOR = 'tests.ci_v5_gate_scope'


def _next():
    """The one finite forward successor (CI V5-3 gate). Low-level only: its signature never calls this module or the composite."""
    from tests.fin_v2_cohorts import COHORT_MODULES
    if SUCCESSOR not in COHORT_MODULES:
        return None
    from tests import ci_v5_gate_scope
    return ci_v5_gate_scope


def _next_pins(root, ref):
    N = _next()
    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}


def later_handoffs(root, ref):
    """HANDOFFS of every reviewed successor behind this cohort (only while each signature holds): a path a LATER cohort owns is not judged against this cohort's literals."""
    N = _next()
    if N is None or not N.signature_ok(root, ref):
        return frozenset()
    return frozenset(N.HANDOFFS) | (N.later_handoffs(root, ref) if hasattr(N, 'later_handoffs') else frozenset())


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
        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_full_recovery_scope')):
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        nx = _next_pins(root, ref)
        if nx.get("tests/ci_v5_hardening_scope.py", pins.get("tests/ci_v5_hardening_scope.py")) != _MODULE_BLOB:
            return False
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if d.get("source_modes") != {p: "100644" for p in OWNED_PATHS} or d.get("base_modes") != {p: "100644" for p in SUPERSEDED}:
            return False
        if not NEW.isdisjoint(base) or any(p.startswith(FORBIDDEN) or p.startswith("/") or ".." in p.split("/") or "*" in p
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
        cur = {p: nx.get(p, b) for p, b in pins.items()}
        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))
        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:
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
                if current[p] != nx.get(p, _expected_map_blob(key, p, tuple(cur[k] for k in MAP_KEYS))):
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
        allowed = closure_paths(root, ref)
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
    root = Path(repo) if repo is not None else ROOT
    with scoped():
        pins = dict(manifest(repo, ref).get("source_blobs", {}))
        pins.update(_next_pins(root, ref))
        return pins


def closure_paths(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    with scoped():
        if not signature_ok(root, ref):
            return frozenset()
        N = _next()
        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | {MANIFEST} and signature_ok(repo, ref)


def ci_owns(path, repo=None, ref=None):
    """A literal CI V5 path (the shadow workflow or a V5 tool) while this cohort is exact; never a wildcard CI admission."""
    return path in CI_PATHS and exact_blobs_ok(repo, ref)


def supersedes(path, value, repo=None, ref=None):
    with scoped():      # one shared read scope per call: the successor signature is evaluated once, then dropped
        N = _next()
        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref):
            return True
        return _supersedes_own(path, value, repo, ref)


def _supersedes_own(path, value, repo=None, ref=None):
    if path not in SUPERSEDED:
        return False
    # The signature decides a supersession; the composite separately requires every cohort's FULL exactness (map bytes, changed set, untracked
    # files), so a signature-only verdict never makes the tree valid.
    # the CURRENT pin of this path (the successor overlay wins while its signature holds), never a raw superseded manifest line
    return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value


def nontrust_scope_authorized(changed, repo=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        N = _next()
        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):
            return True
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

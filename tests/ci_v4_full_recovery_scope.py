"""CI V4 FULL-recovery exact-source successor (after the V5-3 gate cohort): ONE finite, terminal exact-source ownership successor (2026-11-16).

BASE is accepted main (``957335405828``, merged #455). V4 requires every changed path to be owned by a registered cohort. The FULL-recovery PR makes the two slowest FULL
test modules (``tests/test_ci_v3_outcome_reconciliation.py`` 16,008 s and ``tests/fin_truth_b1/test_source_successor.py`` 2,497 s of the 19,200 s FULL budget in run 43828509961)
evaluate the V4 exact-source cohort chain ONCE per test (the existing ``fin_v2_cohorts.call_scope()`` memo) instead of once per nested call, and records the forensic report.
No assertion, parameter, expected outcome, node or skip changes; nothing is cached across tests, refs or monkeypatches. It is NOT V5 activation, promotes no epoch, edits no
branch protection, changes no V4 selector, scheduler, aggregator, required workflow, policy, weight, node split, financial or UI byte.

Every changed byte, Git mode and the immutable BASE tree are bound to this module's manifest. The shared governance paths this successor really changes (the composite registry,
the U1 discovery list, the V5-3 gate module and its exact-tail tests, the earlier layers' tail tuples and exact-tail tests and the current maps) are SUPERSEDED paths: each carries
its accepted BASE blob, the literal one-occurrence substitutions that produce its new blob and the exact new blob. The three FULL-recovery files are REPLACED paths (BASE blob + exact
new blob). ``.github/`` and ``tools/`` are not touched at all (CI_PATHS is empty).

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls an older cohort or the composite; the V5-3 gate cohort calls this module
through one forward hook (the acyclic C06->B1->B2->B3->V5_BOOTSTRAP->V5_2B->V5_3->FULL_RECOVERY pattern, one step further). Nothing is cached across calls.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = "957335405828091410c2c38638ad0cf3f3732fd2"
BASE_TREE = "48f3ded78c0d1e675b4a37c075890a140a8196e3"
MANIFEST = "docs/ci_v5/full_recovery/SOURCE_SUCCESSOR.json"
SCHEMA = "CI_V4_FULL_RECOVERY_EXACT_SOURCE_V1"
AUTHORIZATION = ("CI V4 FULL recovery (2026-11-16): one finite exact-source ownership successor of the V5-3 gate cohort for the FULL-recovery test-evaluation memo, its report and the explicit delta; no V5 activation, no required check, no branch-protection change, no authoritative V5 verdict, no selector, policy, workflow, scheduling-weight, product, financial or test-selection change; no merge or deployment authority.")
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v5_gate_scope.py"
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
    'tests.ci_v5_hardening_scope',
    'tests.ci_v5_gate_scope',
)
NEW = frozenset((
    'docs/ci_v5/full_recovery/FULL_RECOVERY_REPORT.md',
    'tests/ci_v4_full_recovery_scope.py',
    'tests/test_ci_v4_full_recovery_scope.py',
))
# The files rewritten by this PR (REPLACED: accepted BASE blob + exact new blob; ``.github/`` and ``tools/`` stay literal).
REPLACED = frozenset((
    'docs/ci_v5/delta.json',
    'tests/fin_truth_b1/test_source_successor.py',
    'tests/test_ci_v3_outcome_reconciliation.py',
))
# The ONLY ``.github/`` and ``tools/`` paths this cohort owns: exactly the literal paths the bootstrap cohort already admitted. Never a prefix, never a pattern.
CI_PATHS = frozenset(())
# Shared governance paths whose bytes move by one reviewed literal substitution (HANDOFFS).
HANDOFF_PATHS = frozenset((
    'tests/ci_v5_gate_scope.py',
    'tests/fin_v2_cohorts.py',
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


# Finite, literal, one-occurrence substitutions over the IMMUTABLE accepted-main (BASE) bytes. The V5-3 gate cohort gains one forward hook to this cohort (the same acyclic pattern the
# V5-2B cohort received from the bootstrap and the gate from V5-2B); the earlier layers accept one more reviewed tail state; the registry appends this cohort exactly once;
# the U1 discovery list names it; the exact-tail tests accept one more state.
HANDOFFS = {
    'tests/ci_v5_gate_scope.py': [
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
            "SUCCESSOR = 'tests.ci_v4_full_recovery_scope'\n"
            '\n'
            '\n'
            'def _next():\n'
            '    """The one finite forward successor (CI V4 FULL recovery). Low-level only: its signature never calls this module or the composite."""\n'
            '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '    if SUCCESSOR not in COHORT_MODULES:\n'
            '        return None\n'
            '    from tests import ci_v4_full_recovery_scope\n'
            '    return ci_v4_full_recovery_scope\n'
            '\n'
            '\n'
            'def _next_pins(root, ref):\n'
            '    N = _next()\n'
            '    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n'
            '\n'
            '\n'
            'def later_handoffs(root, ref):\n'
            '    """HANDOFFS of every reviewed successor behind this cohort (only while each signature holds): a path a LATER cohort owns is not judged against this cohort\'s literals."""\n'
            '    N = _next()\n'
            '    if N is None or not N.signature_ok(root, ref):\n'
            '        return frozenset()\n'
            "    return frozenset(N.HANDOFFS) | (N.later_handoffs(root, ref) if hasattr(N, 'later_handoffs') else frozenset())\n"
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
            '        if pins.get("tests/ci_v5_gate_scope.py") != _MODULE_BLOB:\n'
            '            return False\n'),
         (
            '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n'
            '        nx = _next_pins(root, ref)\n'
            '        if nx.get("tests/ci_v5_gate_scope.py", pins.get("tests/ci_v5_gate_scope.py")) != _MODULE_BLOB:\n'
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
            "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope')\n"
            '# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).\n'),
         (
            "                  'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope',\n"
            "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')\n"
            '# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).\n')),
    ],
    'tests/u1_scope.py': [
        ((
            '\n'
            "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope')\n"
            '\n'),
         (
            '\n'
            "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')\n"
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
        if pins.get("tests/ci_v4_full_recovery_scope.py") != _MODULE_BLOB:
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


def ci_owns(path, repo=None, ref=None):
    """A literal CI V5 path (the shadow workflow or a V5 tool) while this cohort is exact; never a wildcard CI admission."""
    return path in CI_PATHS and exact_blobs_ok(repo, ref)


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

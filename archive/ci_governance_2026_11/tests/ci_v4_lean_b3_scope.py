"""CI V4 Lean B3: ONE finite exact-source successor after the accepted B2 cohort (B3+B4 scoped implementation, 2026-11-15).

BASE is accepted main (the merged #451, ``523a9eb2``). This cohort carries the WARN-ONLY test-admission report
(``tests/ci_v4_lean_report.py``: the machine-readable test-admission JSON over the trusted-base diff, its CLI command
and its targeted tests). It changes NO selector, policy, workflow, scheduling weight, product, financial or UI source and
selects, deletes, skips or moves NO test: ``docs/ci_v4/module_weights.json`` is FROZEN to its accepted-main bytes. ZERO B4
demotions are proposed: the B4 evidence is ``B4_PROOF_BLOCKED_ZERO_DEMOTIONS`` in the private packet.

Every changed byte, Git mode and the immutable BASE tree are bound to this module's manifest. The shared governance
paths this successor really changes (the C06, B1 and B2 forward hooks, the composite registry, the U1 discovery list, the
exact-tail tests, the report machinery and the eight current maps) are SUPERSEDED paths: each carries its accepted BASE blob, the
literal one-occurrence substitutions that produce its new blob, and the exact new blob. Previous manifests are never
rewritten except the current-map keys every earlier successor moved the same way.

Termination: the signature reads Git objects, this manifest and the registry tuple only. It never calls the B2 cohort,
an older cohort or the composite; the B2 cohort calls this module through one forward hook (the acyclic C06->B1->B2 pattern).
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = "523a9eb2f4efb00dac49cee070cf925232ba0698"
BASE_TREE = "d702f6c10b91af5a41afba057f83c088dff31340"
MANIFEST = "docs/ci_v4/lean_b3/SOURCE_SUCCESSOR.json"
SCHEMA = "CI_V4_LEAN_B3_EXACT_SOURCE_V1"
AUTHORIZATION = ("B3+B4 scoped implementation (2026-11-15): one finite exact-source successor of the accepted B2 cohort for the "
                 "WARN-ONLY test-admission report; no selector, policy, workflow, scheduling-weight, product, "
                 "financial or test-selection change; no merge or deployment authority; zero test demotions proposed.")
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v4_lean_b2_scope.py"
BASE_COHORTS = (
    'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope',
    'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope',
    'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope',
    'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope',
    'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope',
    'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope',
    'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope',
    'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope',
    'tests.ci_v4_lean_b2_scope',
)
NEW = frozenset((
    "docs/ci_v4/lean_b3/README.md",
    "tests/ci_v4_lean_b3_scope.py",
    "tests/test_ci_v4_lean_b3_scope.py",
))
# Shared governance paths whose bytes move by one reviewed literal substitution (HANDOFFS): the C06, B1 and B2 forward hooks, the registry,
# the U1 discovery list, the exact-tail tests and the report machinery.
HANDOFF_PATHS = frozenset((
    'tests/c06_cost_workspace_scope.py',
    'tests/ci_v4_lean_b1_scope.py',
    'tests/ci_v4_lean_b2_scope.py',
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
    'tests/ci_v4_lean_report.py',
    'tests/test_ci_v4_lean_report.py',
    'tests/test_bess02_scope.py',
    'tests/test_c06_cost_workspace_scope.py',
    'tests/test_ci_v4_lean_b1_scope.py',
    'tests/test_ci_v4_lean_b2_scope.py',
    'tests/test_ci_v4_lean_tamper_matrix.py',
    'tests/test_ci_v4_perf_scope.py',
    'tests/test_f03_financing_scope.py',
    'tests/test_f04_financing_scope.py',
    'tests/test_post432_l01_l02_scope.py',
    'tests/test_r02_ppa_ux_scope.py',
    'tests/test_r03_ppa_scope.py',
    'tests/test_r04_ppa_scope.py',
    'tests/test_t01e_remediation_scope.py',
))
# ... and the eight current maps, of which only the registry and U1-discovery keys move (the bounded handoff every earlier successor made).
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
SUPERSEDED = HANDOFF_PATHS | CURRENT_MAPS
OWNED_PATHS = NEW | SUPERSEDED
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", ".github/", "migrations/", "app/", "research/", "frontend/", "static/", "main_web.py")
# Accepted CI V4 control sources that this successor must leave byte-identical to BASE: no selector, policy, aggregator, scheduler, workflow or scheduling-weight change.
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
    'tests/c06_cost_workspace_scope.py': [
        ((
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\r\n'
            "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope')):       # at most the two reviewed successors\r\n"
            '            return False\r\n'),
         (
             '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\r\n'
             "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope'),\r\n"
             "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope')):       # at most the three reviewed successors\r\n"
             '            return False\r\n')),
    ],
    'tests/ci_v4_lean_b1_scope.py': [
        ((
            '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
            '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n'
            '            return False\n'),
         (
             '        from tests.fin_v2_cohorts import COHORT_MODULES\n'
             '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR),\n'
             "                                  BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope')):       # B1 -> B2 -> B3, nothing else\n"
             '            return False\n')),
    ],
    'tests/ci_v4_lean_b2_scope.py': [
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
             "SUCCESSOR = 'tests.ci_v4_lean_b3_scope'\n"
             '\n'
             '\n'
             'def _next():\n'
             '    """The one finite forward successor (CI V4 Lean B3). Low-level only: its signature never calls this module or the composite."""\n'
             '    from tests.fin_v2_cohorts import COHORT_MODULES\n'
             '    if SUCCESSOR not in COHORT_MODULES:\n'
             '        return None\n'
             '    from tests import ci_v4_lean_b3_scope\n'
             '    return ci_v4_lean_b3_scope\n'
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
            '        if pins.get("tests/ci_v4_lean_b2_scope.py") != _MODULE_BLOB:\n'
            '            return False\n'),
         (
             '        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n'
             '        nx = _next_pins(root, ref)\n'
             '        if nx.get("tests/ci_v4_lean_b2_scope.py", pins.get("tests/ci_v4_lean_b2_scope.py")) != _MODULE_BLOB:\n'
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
    'tests/ci_v4_lean_report.py': [
        ((
            '    sub = ap.add_subparsers(dest="cmd", required=True)\n'
            '    for name in ("measure-gate", "collect", "simulate", "weights-proposal", "admission", "budgets"):\n'
            '        s = sub.add_parser(name)\n'),
         (
             '    sub = ap.add_subparsers(dest="cmd", required=True)\n'
             '    for name in ("measure-gate", "collect", "simulate", "weights-proposal", "admission", "budgets", "test-admission"):\n'
             '        s = sub.add_parser(name)\n')),
        ((
            '            s.add_argument("--junit", nargs="+", required=True)\n'
            '        if name == "weights-proposal":\n'),
         (
             '            s.add_argument("--junit", nargs="+", required=True)\n'
             '        if name == "test-admission":\n'
             '            s.add_argument("--junit", nargs="+")\n'
             '        if name == "test-admission":\n'
             '            s.add_argument("--base", default="origin/main")\n'
             '            s.add_argument("--head", default="HEAD")\n'
             '            s.add_argument("--plan", help="trusted-base plan JSON (from the plan job artifact), optional")\n'
             '        if name == "weights-proposal":\n')),
        ((
            '        _emit(budget_warnings(a.junit), a.output)\n'
            '    else:\n'),
         (
             '        _emit(budget_warnings(a.junit), a.output)\n'
             '    elif a.cmd == "test-admission":\n'
             '        _emit(test_admission_report(a.base, a.head, a.plan, a.junit or ()), a.output)\n'
             '    else:\n')),
        ((
            '\n'
            'if __name__ == "__main__":\n'),
         (
             '\n'
             '# ----------------------------------------------------------------------------------------------- B3 test-admission report (WARN-ONLY, opt-in)\n'
             'ADMISSION_FIELDS = ("risk", "nearest", "witness", "tier", "owner", "retire")\n'
             '\n'
             '\n'
             'def _git_name_status(base, head, root):\n'
             '    """Added/removed/renamed/changed test-module paths vs the trusted base (rename detection ON)."""\n'
             '    out = subprocess.check_output(["git", "-c", "core.quotepath=false", "diff", "--name-status", "-M", base, head,\n'
             '                                   "--", "tests/"], cwd=root).decode("utf-8", "replace")\n'
             '    added, removed, renamed, changed = [], [], [], []\n'
             '    for line in out.splitlines():\n'
             '        parts = line.split("\\t")\n'
             '        if not parts or not parts[0]:\n'
             '            continue\n'
             '        st, p = parts[0], parts[-1]\n'
             '        if st.startswith("A"):\n'
             '            added.append(p)\n'
             '        elif st.startswith("D"):\n'
             '            removed.append(p)\n'
             '        elif st.startswith("R") and len(parts) >= 3:\n'
             '            renamed.append({"from": parts[1], "to": parts[2]})\n'
             '        elif st.startswith("M"):\n'
             '            changed.append(p)\n'
             '    return added, removed, renamed, changed\n'
             '\n'
             '\n'
             'def _test_node_names(src):\n'
             '    try:\n'
             '        tree = ast.parse(src)\n'
             '    except (SyntaxError, ValueError):\n'
             '        return None                                    # unparsable -> UNKNOWN, never an empty lie\n'
             '    return sorted(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"))\n'
             '\n'
             '\n'
             'def _body_hashes(src):\n'
             '    """Cheap duplicate-candidate heuristic: normalized AST-dump hash per test function (a CANDIDATE, never a finding)."""\n'
             '    try:\n'
             '        tree = ast.parse(src)\n'
             '    except (SyntaxError, ValueError):\n'
             '        return {}\n'
             '    out = {}\n'
             '    for n in ast.walk(tree):\n'
             '        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):\n'
             '            body = ast.dump(ast.Module(body=n.body, type_ignores=[]))\n'
             '            out[n.name] = hashlib.sha1(body.encode()).hexdigest()\n'
             '    return out\n'
             '\n'
             '\n'
             'def _show(ref, rel, root):\n'
             '    """The text of ``rel`` AT ``ref`` (Git object read, never the working tree), or None when the path does not exist there."""\n'
             '    try:\n'
             '        return subprocess.check_output(["git", "show", "%s:%s" % (ref, rel)], cwd=root, stderr=subprocess.DEVNULL).decode("utf-8", "replace")\n'
             '    except subprocess.CalledProcessError:\n'
             '        return None\n'
             '\n'
             '\n'
             'def _skip_markers(src):\n'
             '    return [ln.strip() for ln in src.splitlines() if re.search(r"\\b(skip|xfail|skipif)\\b", ln) and ln.strip().startswith(("@", "pytest.mark", "pytestmark"))]\n'
             '\n'
             '\n'
             'def _admission_metadata(src):\n'
             '    """Parse the module docstring\'s \'Admission:\' directives; every missing field is UNKNOWN, never invented."""\n'
             '    try:\n'
             '        doc = ast.get_docstring(ast.parse(src)) or ""\n'
             '    except (SyntaxError, ValueError):\n'
             '        return {}\n'
             '    meta = {}\n'
             '    for line in doc.splitlines():\n'
             '        if line.strip().lower().startswith("admission:"):\n'
             '            for item in line.split(":", 1)[1].split(","):\n'
             '                if "=" in item:\n'
             '                    k, v = item.split("=", 1)\n'
             '                    meta[k.strip().lower()] = v.strip()\n'
             '    return {f: meta.get(f, "UNKNOWN") for f in ADMISSION_FIELDS}\n'
             '\n'
             '\n'
             'def test_admission_report(base="origin/main", head="HEAD", plan_path=None, junit_paths=(), root=ROOT):\n'
             '    """B3 WARN-ONLY test-admission report over the trusted-base diff. Read-only: it never gates, never writes\n'
             '    repo files, and every unavailable measurement is UNKNOWN with its label — never zero, never a fabricated PASS."""\n'
             '    root = Path(root)\n'
             '    head_sha = subprocess.check_output(["git", "rev-parse", head], cwd=root).decode().strip()\n'
             '    head_tree = subprocess.check_output(["git", "rev-parse", head + "^{tree}"], cwd=root).decode().strip()\n'
             '    worktree_clean = subprocess.check_output(["git", "status", "--porcelain"], cwd=root).decode().strip() == ""\n'
             '    head_binding = ("WORKTREE_CLEAN_HEAD_MATCHES" if (worktree_clean and head in ("HEAD", head_sha)) else\n'
             '                    "COMMITTED_REF (every content read is a Git object read at the supplied head; the working tree is never read)")\n'
             '    added, removed, renamed, changed = _git_name_status(base, head, root)\n'
             '    is_test = lambda p: p.startswith("tests/") and p.rsplit("/", 1)[-1].startswith("test_") and p.endswith(".py")\n'
             '    added, removed, changed = sorted(filter(is_test, added)), sorted(filter(is_test, removed)), sorted(filter(is_test, changed))\n'
             '\n'
             '    node_deltas, growth = [], {"added_modules": len(added), "removed_modules": len(removed), "renamed_modules": len(renamed),\n'
             '                               "added_nodes": 0, "removed_nodes": 0}\n'
             '    plan, selected_set, plan_provenance = None, None, "UNKNOWN (no plan supplied)"\n'
             '    if plan_path:\n'
             '        try:\n'
             '            plan = json.loads(Path(plan_path).read_text())\n'
             '            selected_set = set(plan.get("pytest_modules", []))\n'
             '            if plan.get("tested_sha") == head_sha:\n'
             '                plan_provenance = "SHA_BOUND_INPUT (plan tested_sha == report head; that the plan came from a hosted run is attested by the caller, not by this tool)"\n'
             '            else:\n'
             '                plan_provenance = "UNVERIFIED_INPUT (plan tested_sha %s != report head %s)" % (plan.get("tested_sha", "UNKNOWN")[:12], head_sha[:12])\n'
             '        except (OSError, ValueError):\n'
             '            plan = None\n'
             '            plan_provenance = "UNKNOWN (plan unreadable)"\n'
             '    junit_secs, _jnodes = read_junit_module_seconds(sorted(junit_paths)) if junit_paths else ({}, {})\n'
             '    # A JUnit file carries no commit identity, so it is never OBSERVED_HOSTED here: the caller must attest its run and SHA separately.\n'
             '    junit_provenance = ("UNVERIFIED_INPUT (JUnit supplied; it is not bound to the report head SHA, so its seconds are not hosted proof)"\n'
             '                        if junit_paths else "UNKNOWN (no junit supplied)")\n'
             '\n'
             '    new_skips, duplicates, meta_rows = [], [], []\n'
             '    existing_hashes = {}\n'
             '    for rel in sorted(set(added) | set(changed)):\n'
             '        src_now = _show(head, rel, root)\n'
             '        now_nodes = _test_node_names(src_now) if src_now is not None else None\n'
             '        src_base = _show(base, rel, root)\n'
             '        base_nodes = _test_node_names(src_base) if src_base is not None else []\n'
             '        if now_nodes is None or base_nodes is None:\n'
             '            src_now = src_now or ""\n'
             '            status, added_n, removed_n = "UNKNOWN", [], []\n'
             '        else:\n'
             '            added_n = [n for n in now_nodes if n not in base_nodes]\n'
             '            removed_n = [n for n in base_nodes if n not in now_nodes]\n'
             '            status = "AST_FUNCTION_DELTA"          # function names only: never collected pytest node ids or a parametrize count\n'
             '        growth["added_nodes"] += len(added_n)\n'
             '        growth["removed_nodes"] += len(removed_n)\n'
             '        node_deltas.append({"module": rel, "status": status, "added_nodes": added_n, "removed_nodes": removed_n,\n'
             '                            "node_id_status": "UNKNOWN (no SHA-bound pytest --collect-only of both states; function names are not node ids)",\n'
             '                            "selected": ("SELECTED" if (selected_set is not None and rel in selected_set)\n'
             '                                         else ("NOT_SELECTED" if selected_set is not None else "UNKNOWN")),\n'
             '                            "wall_s": (round(junit_secs[rel], 3) if rel in junit_secs else None),\n'
             '                            "wall_label": ("UNVERIFIED_INPUT (JUnit not SHA-bound)" if rel in junit_secs else "UNKNOWN"),\n'
             '                            "git_process_count": "UNKNOWN"})\n'
             '        if rel in added:\n'
             '            meta_rows.append({"module": rel, **_admission_metadata(src_now)})\n'
             '        base_marks = set(_skip_markers(src_base)) if src_base is not None else set()\n'
             '        new_skips += [{"module": rel, "marker": m[:120],\n'
             '                       "newness": "PRE_EXISTING (same marker line present at base)" if m in base_marks else "NEW_VS_BASE (marker line absent at base)"}\n'
             '                      for m in _skip_markers(src_now)[:3]]\n'
             '        if rel in added:\n'
             '            hashes = _body_hashes(src_now)\n'
             '            listing = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", head, "--", "tests/"], cwd=root).decode("utf-8", "replace").splitlines()\n'
             '            for erel in sorted(p for p in listing if is_test(p) and p.count("/") == 1):\n'
             '                if erel == rel:\n'
             '                    continue\n'
             '                if erel not in existing_hashes:\n'
             '                    existing_hashes[erel] = _body_hashes(_show(head, erel, root) or "")\n'
             '                for name, h in sorted(hashes.items()):\n'
             '                    for name2, h2 in sorted(existing_hashes[erel].items()):\n'
             '                        if h == h2:\n'
             '                            duplicates.append({"candidate": "%s::%s" % (rel, name), "existing": "%s::%s" % (erel, name2),\n'
             '                                               "heuristic": "identical-normalized-AST-body", "severity": "WARN"})\n'
             '\n'
             '    budget = budget_warnings(sorted(junit_paths)) if junit_paths else {"label": "WARN_ONLY", "enforced": False, "findings": [],\n'
             '                                                                       "note": "UNKNOWN (no junit supplied)"}\n'
             '    crit = {"label": "UNKNOWN (no plan supplied)"}\n'
             '    if plan:\n'
             '        predicted = (plan.get("schedule") or {}).get("predicted_critical_path_s")\n'
             '        crit = {"plan_predicted_critical_path_s": predicted, "enforced": False,\n'
             '                "label": ("SIMULATION (the plan\'s prediction from the committed scheduling weights; not an observed hosted time)"\n'
             '                          if predicted is not None else "UNKNOWN (the supplied plan carries no predicted critical path)")}\n'
             '\n'
             '    findings = []\n'
             '    for row in meta_rows:\n'
             '        for f, v in row.items():\n'
             '            if f != "module" and v == "UNKNOWN":\n'
             '                findings.append({"path": row["module"], "code": "ADM-METADATA-UNKNOWN", "field": f, "severity": "WARN",\n'
             '                                 "message": "admission metadata field is UNKNOWN: " + f})\n'
             '    for d in duplicates:\n'
             '        findings.append({"path": d["candidate"], "code": "ADM-DUPLICATE-CANDIDATE", "severity": "WARN",\n'
             '                         "message": "duplicate CANDIDATE (heuristic only, never automatic): %s" % d["existing"]})\n'
             '    fresh = [k for k in new_skips if k["newness"].startswith("NEW_VS_BASE")]\n'
             '    if fresh:\n'
             '        findings.append({"code": "ADM-NEW-SKIP", "severity": "WARN",\n'
             '                         "message": "new skip/xfail markers: a skipped node is never PASS (%d marker lines absent at base)" % len(fresh)})\n'
             '\n'
             '    return {"label": "WARN_ONLY", "what": "B3 test-admission report over the trusted-base diff",\n'
             '            "base": base, "head": head, "head_sha": head_sha, "head_tree": head_tree, "head_binding": head_binding,\n'
             '            "plan_provenance": plan_provenance, "junit_provenance": junit_provenance,\n'
             '            "modules": {"added": added, "removed": removed, "renamed": renamed, "changed": changed},\n'
             '            "node_deltas": node_deltas, "node_delta_kind": "AST_FUNCTION_DELTA (exact collected node ids require a fresh pytest --collect-only on both exact SHA/trees; UNKNOWN when unavailable)", "growth": growth,\n'
             '            "admission_metadata": meta_rows, "duplicate_candidates": duplicates, "present_skip_markers": new_skips, "new_skip_markers": fresh,\n'
             '            "critical_path": crit, "budgets": budget, "findings": findings,\n'
             '            "labels_used": ["AST_FUNCTION_DELTA", "MEASURED_LOCAL", "SHA_BOUND_INPUT", "SIMULATION", "UNVERIFIED_INPUT", "UNKNOWN", "WARN_ONLY"],\n'
             '            "exit_code_policy": "always 0: informational, never a gate"}\n'
             '\n'
             '\n'
             'if __name__ == "__main__":\n')),
    ],
    'tests/fin_v2_cohorts.py': [
        ("                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope')\n",
         "                  'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope')\n"),
    ],
    'tests/test_bess02_scope.py': [
        ("                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "                and F.signature_ok() and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
    ],
    'tests/test_c06_cost_workspace_scope.py': [
        ((
            "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
            "    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))       # C06 is followed by at most the one reviewed B1 successor\n"
            '    assert C.COHORT_MODULES.count(F.__name__)==1\n'),
         (
             "    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE\n"
             "    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'), F.BASE_COHORTS + (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))       # C06 is followed by the reviewed B1, B2 and B3 successors\n"
             '    assert C.COHORT_MODULES.count(F.__name__)==1\n')),
        ((
            "    for path in F.SUPERSEDED:assert data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
            '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None\n'
            '    for path in F.HANDOFFS:\n'
            '        later=N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'
            '        assert (ROOT/path).read_bytes()==later.expected_handoff(ROOT,path)\n'),
         (
             "    for path in F.SUPERSEDED:assert data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)\n"
             '    N=F._next();N2=N._next() if N is not None and N.signature_ok() else None;N3=N2._next() if N2 is not None and N2.signature_ok() else None\n'
             '    for path in F.HANDOFFS:\n'
             '        later=N3 if N3 is not None and N3.signature_ok() and path in N3.HANDOFFS else N2 if N2 is not None and N2.signature_ok() and path in N2.HANDOFFS else N if N is not None and F.SUCCESSOR in C.COHORT_MODULES and N.signature_ok() and path in N.HANDOFFS else F      # the further reviewed B1 substitution of this shared path\n'
             '        assert (ROOT/path).read_bytes()==later.expected_handoff(ROOT,path)\n')),
        ((
            '        for m in C.cohorts():\n'
            "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'):         # a successor never attests an older accepted ref\n"
            '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n'),
         (
             '        for m in C.cohorts():\n'
             "            if m.__name__ not in (F.__name__, F.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'):         # a successor never attests an older accepted ref\n"
             '                assert m.exact_blobs_ok(clone,F.BASE),m.__name__\n')),
    ],
    'tests/test_ci_v4_lean_b1_scope.py': [
        ((
            'MATRIX = "tests/test_ci_v4_lean_tamper_matrix.py"\n'
            '\n'),
         (
             'MATRIX = "tests/test_ci_v4_lean_tamper_matrix.py"\n'
             'README = "docs/ci_v4/lean_b1/README.md"      # a B1-owned path no later successor hands off: its pin is still judged by B1 itself\n'
             '\n')),
        ((
            '                   for p in T.OWNED_PATHS | {T.MANIFEST})\n'
            '    for path in T.FROZEN:\n'
            '        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n'),
         (
             '                   for p in T.OWNED_PATHS | {T.MANIFEST})\n'
             '    T2 = T._next()\n'
             '    T3 = T2._next() if T2 is not None and T2.signature_ok() else None\n'
             '    for path in T.FROZEN:\n'
             "        if T3 is not None and T2 is not None and T2.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and path in T3.HANDOFFS:      # the reviewed B3 successor owns this control file's further substitution\n"
             '            assert (ROOT / path).read_bytes() == T3.expected_handoff(ROOT, path), path\n'
             '            continue\n'
             '        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path\n')),
        ((
            '    N = T._next()\n'
            '    for p in T.HANDOFFS:\n'
            '        if N is not None and N.signature_ok() and p in N.HANDOFFS:                  # the further reviewed B2 substitution of this shared path\n'),
         (
             '    N = T._next()\n'
             '    N2 = N._next() if N is not None and N.signature_ok() else None\n'
             '    for p in T.HANDOFFS:\n'
             '        if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this shared path\n'
             '            assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)\n'
             '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
             '            continue\n'
             '        if N is not None and N.signature_ok() and p in N.HANDOFFS:                  # the further reviewed B2 substitution of this shared path\n')),
        ((
            'def test_registered_exactly_once_as_the_terminal_cohort_after_c06():\n'
            '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR)) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == "tests.c06_cost_workspace_scope"\n'),
         (
             'def test_registered_exactly_once_as_the_terminal_cohort_after_c06():\n'
             '    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR),\n'
             '                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope")) and C.COHORT_MODULES.count(T.__name__) == 1\n'
             '    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == "tests.c06_cost_workspace_scope"\n')),
        ((
            '    from tests import u1_scope as U\n'
            '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-3:] if m != "tests.ci_v4_lean_b2_scope") == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope")\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1\n'),
         (
             '    from tests import u1_scope as U\n'
             '    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-4:] if m != "tests.ci_v4_lean_b3_scope") == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
             '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1\n')),
        ((
            'def test_registry_mutations_are_rejected(clone):\n'
            '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
            '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n'
            '        ("b1_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b1_scope\'", b"")),\n'),
         (
             'def test_registry_mutations_are_rejected(clone):\n'
             '    tail = b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')"\n'
             '    for name, fn in (\n'
             '        ("duplicate", lambda b: b.replace(tail, b"\'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'
             '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'
             '        ("swapped_c06_b1", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'
             '        ("b1_missing", lambda b: b.replace(b", \'tests.ci_v4_lean_b1_scope\'", b"")),\n')),
        ((
            '    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),\n'
            '              edit(lambda d: d["source_blobs"].__setitem__(REPORT, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),\n'
            '              edit(lambda d: d["source_modes"].__setitem__(REPORT, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),\n'),
         (
             '    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),\n'
             '              edit(lambda d: d["source_blobs"].__setitem__(README, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),\n'
             '              edit(lambda d: d["source_modes"].__setitem__(REPORT, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),\n')),
    ],
    'tests/test_ci_v4_lean_b2_scope.py': [
        ((
            'U1_TESTS = "tests/test_u1_scope.py"\n'
            'SCOPED_NODES = ("test_positive_cohort_is_exact_registered_and_closed",\n'),
         (
             'U1_TESTS = "tests/test_u1_scope.py"\n'
             'README = "docs/ci_v4/lean_b2/README.md"      # a B2-owned path no later successor hands off: its pin is still judged by B2 itself\n'
             'SCOPED_NODES = ("test_positive_cohort_is_exact_registered_and_closed",\n')),
        ((
            '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
            '    for p in T.HANDOFFS:\n'
            '        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
            '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'),
         (
             '    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()\n'
             '    T3 = T._next()\n'
             '    for p in T.HANDOFFS:\n'
             '        if T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p in T3.HANDOFFS:      # the reviewed B3 substitution of this shared path\n'
             '            assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)\n'
             '        else:\n'
             '            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)\n'
             '        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n')),
        ((
            'def test_registered_exactly_once_as_the_terminal_cohort_after_b1():\n'
            '    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and C.COHORT_MODULES.count(T.__name__) == 1\n'
            '    assert C.COHORT_MODULES[-3:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
            '    assert B.SUCCESSOR == T.__name__ and B._next() is T and K.SUCCESSOR == B.__name__ and K._next() is B\n'
            '\n'),
         (
             'def test_registered_exactly_once_as_the_terminal_cohort_after_b1():\n'
             '    assert C.COHORT_MODULES.count(T.__name__) == 1\n'
             '    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"))\n'
             '    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B\n'
             '    from tests import ci_v4_lean_b3_scope as T3\n'
             '    if T.SUCCESSOR in C.COHORT_MODULES:\n'
             '        assert C.COHORT_MODULES[-1] == T.SUCCESSOR and T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"\n'
             '\n')),
        ((
            '    from tests import u1_scope as U\n'
            '    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")\n'
            '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1\n'),
         (
             '    from tests import u1_scope as U\n'
             '    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"))\n'
             '    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1\n')),
        ((
            'def test_registry_mutations_are_rejected(clone):\n'
            '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')"\n'
            '    for name, fn in (\n'
            '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\')")),\n'
            '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n'),
         (
             'def test_registry_mutations_are_rejected(clone):\n'
             '    tail = b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')"\n'
             '    for name, fn in (\n'
             '        ("duplicate", lambda b: b.replace(tail, b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")),\n'
             '        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", \'tests.fake_scope\')")),\n')),
        ((
            '    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),\n'
            '              edit(lambda d: d["source_blobs"].__setitem__(MODULE, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),\n'
            '              edit(lambda d: d["source_modes"].__setitem__(MODULE, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),\n'),
         (
             '    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),\n'
             '              edit(lambda d: d["source_blobs"].__setitem__(README, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),\n'
             '              edit(lambda d: d["source_modes"].__setitem__(MODULE, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),\n')),
        ((
            '    pins = T.manifest()["source_blobs"]\n'
            '    reg = pins[T.REGISTRY]\n'
            '    assert B.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)\n'
            '    assert not B.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(U1_TESTS, "0" * 40)\n'),
         (
             '    pins = T.manifest()["source_blobs"]\n'
             '    reg = T.effective_pins()[T.REGISTRY]            # the CURRENT registry pin (the B3 successor overlay wins while its signature holds)\n'
             '    assert B.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)\n'
             "    assert not B.supersedes(T.REGISTRY, pins[T.REGISTRY])       # B2's own registry pin is superseded by B3 and no longer current\n"
             '    assert not B.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(U1_TESTS, "0" * 40)\n')),
    ],
    'tests/test_ci_v4_lean_report.py': [
        ('    assert "ci_v4_lean_report" not in workflows\n',
         (
             '    assert "ci_v4_lean_report" not in workflows\n'
             '\n'
             '\n'
             '# -------------------------------------------------------------------------------------------- B3 test-admission report (targeted cases)\n'
             'from tests import ci_v4_lean_report as _B3R\n'
             '\n'
             "_ADM_META = 'Admission: risk=probe-only, nearest=none, witness=red-before-green missing, tier=fast, owner=ci, retire=when-flaky'\n"
             '\n'
             '\n'
             '@pytest.fixture()\n'
             'def b3_repo(tmp_path):\n'
             '    root = tmp_path / "b3repo"\n'
             '    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])\n'
             '    subprocess.check_call(["git", "config", "user.name", "t"], cwd=root)\n'
             '    subprocess.check_call(["git", "config", "user.email", "t-at-test-placeholder"], cwd=root)\n'
             '    subprocess.check_call(["git", "checkout", "-q", "-b", "b3-probe"], cwd=root)\n'
             '    return root\n'
             '\n'
             '\n'
             'def _b3_commit(root, msg="probe"):\n'
             '    subprocess.check_call(["git", "add", "-A"], cwd=root)\n'
             '    subprocess.check_call(["git", "commit", "-q", "--allow-empty", "-m", msg], cwd=root)\n'
             '    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()\n'
             '\n'
             '\n'
             'def test_b3_admission_normal_addition_is_listed_with_labels(b3_repo):\n'
             '    (b3_repo / "tests" / "test_b3_probe_normal.py").write_text(\n'
             '        "\'%s\'\\n\\ndef test_b3_probe_normal():\\n    assert True\\n" % _ADM_META)\n'
             '    head = _b3_commit(b3_repo)\n'
             '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\n'
             '    assert rep["modules"]["added"] == ["tests/test_b3_probe_normal.py"]\n'
             '    row = rep["node_deltas"][0]\n'
             '    assert row["added_nodes"] == ["test_b3_probe_normal"] and row["status"] == "AST_FUNCTION_DELTA"\n'
             '    assert row["node_id_status"].startswith("UNKNOWN")      # function names are never reported as collected node ids\n'
             '    assert row["selected"] == "UNKNOWN" and row["wall_label"] == "UNKNOWN" and row["git_process_count"] == "UNKNOWN"\n'
             '    assert all(v != "UNKNOWN" for k, v in rep["admission_metadata"][0].items() if k != "module")\n'
             '\n'
             '\n'
             'def test_b3_admission_duplicate_candidate_is_heuristic_warn_only(b3_repo):\n'
             '    (b3_repo / "tests" / "test_b3_probe_dup.py").write_text(\n'
             '        "def test_b3_probe_dup():\\n    value = 1 + 1\\n    assert value == 2\\n")\n'
             '    _b3_commit(b3_repo)\n'
             '    (b3_repo / "tests" / "test_b3_probe_dup2.py").write_text(\n'
             '        "def test_b3_probe_dup2():\\n    value = 1 + 1\\n    assert value == 2\\n")\n'
             '    head = _b3_commit(b3_repo)\n'
             '    rep = _B3R.test_admission_report(base="HEAD~2", head=head, root=b3_repo)\n'
             '    assert rep["duplicate_candidates"], "identical normalized bodies must surface as CANDIDATES"\n'
             '    assert all(d["severity"] == "WARN" for d in rep["duplicate_candidates"])\n'
             '    assert rep["label"] == "WARN_ONLY"\n'
             '\n'
             '\n'
             'def test_b3_admission_missing_metadata_is_unknown_never_invented(b3_repo):\n'
             '    (b3_repo / "tests" / "test_b3_probe_nodoc.py").write_text("def test_b3_probe_nodoc():\\n    assert 1\\n")\n'
             '    head = _b3_commit(b3_repo)\n'
             '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\n'
             '    meta = rep["admission_metadata"][0]\n'
             '    assert all(v == "UNKNOWN" for k, v in meta.items() if k != "module")\n'
             '    assert any(f["code"] == "ADM-METADATA-UNKNOWN" for f in rep["findings"])\n'
             '\n'
             '\n'
             'def test_b3_admission_new_skip_is_reported_never_pass(b3_repo):\n'
             '    (b3_repo / "tests" / "test_b3_probe_skip.py").write_text(\n'
             '        "import pytest\\n\\n\\npytestmark = pytest.mark.skip(reason=\'probe\')\\ndef test_b3_probe_skip():\\n    assert True\\n")\n'
             '    head = _b3_commit(b3_repo)\n'
             '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\n'
             '    assert [k["newness"][:11] for k in rep["new_skip_markers"]] == ["NEW_VS_BASE"], "a new skip must be visible; a skipped node is never PASS"\n'
             '    assert any(f["code"] == "ADM-NEW-SKIP" for f in rep["findings"])\n'
             '\n'
             '\n'
             'def test_b3_admission_tool_failure_is_reported_inside_json_never_as_exit(b3_repo):\n'
             '    (b3_repo / "tests" / "test_b3_probe_broken.py").write_text("def broken(:\\n")\n'
             '    head = _b3_commit(b3_repo)\n'
             '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\n'
             '    assert rep["node_deltas"][0]["status"] == "UNKNOWN"      # unparsable source is UNKNOWN, never an empty lie\n'
             '    assert rep["exit_code_policy"].startswith("always 0")\n'
             '\n'
             '\n'
             'def test_b3_admission_unchanged_fast_path_is_empty(b3_repo):\n'
             '    head = _b3_commit(b3_repo, "empty")\n'
             '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)\n'
             '    assert rep["modules"]["added"] == [] and rep["modules"]["removed"] == [] and rep["modules"]["changed"] == []\n'
             '    assert rep["node_deltas"] == [] and rep["growth"]["added_nodes"] == 0\n'
             '\n'
             '\n'
             'def test_b3_admission_plan_status_selected_vs_not_selected(b3_repo):\n'
             '    plan = {"pytest_modules": ["tests/test_b3_probe_in_plan.py"], "schedule": {"predicted_critical_path_s": None}}\n'
             '    (b3_repo / "tests" / "test_b3_probe_in_plan.py").write_text("def test_in_plan():\\n    assert True\\n")\n'
             '    (b3_repo / "tests" / "test_b3_probe_out_plan.py").write_text("def test_out_plan():\\n    assert True\\n")\n'
             '    pf = b3_repo / "plan.json"\n'
             '    pf.write_text(json.dumps(plan))\n'
             '    head = _b3_commit(b3_repo)\n'
             '    rep = _B3R.test_admission_report(base="HEAD~1", head=head, plan_path=str(pf), root=b3_repo)\n'
             '    by_mod = {r["module"]: r for r in rep["node_deltas"]}\n'
             '    assert by_mod["tests/test_b3_probe_in_plan.py"]["selected"] == "SELECTED"\n'
             '    assert by_mod["tests/test_b3_probe_out_plan.py"]["selected"] == "NOT_SELECTED"\n'
             '    assert rep["critical_path"]["plan_predicted_critical_path_s"] is None\n')),
    ],
    'tests/test_ci_v4_lean_tamper_matrix.py': [
        ((
            'REG = "tests/fin_v2_cohorts.py"\n'
            'TAIL = "\'tests.ci_v4_lean_b2_scope\')"\n'
            '# row id, invariant class, mutation, injected path, attribution class\n'),
         (
             'REG = "tests/fin_v2_cohorts.py"\n'
             'TAIL = "\'tests.ci_v4_lean_b3_scope\')"\n'
             '# row id, invariant class, mutation, injected path, attribution class\n')),
        ((
            '    ("unowned_tracked_file", "unowned_tracked", _new_tracked("docs/ci_v4/lean_matrix_unowned.md"), "docs/ci_v4/lean_matrix_unowned.md", "direct"),\n'
            '    ("forged_manifest_pin", "forged_manifest", _manifest_edit(lambda d: d["source_blobs"].__setitem__("tests/ci_v4_lean_report.py", "0" * 40)),\n'
            '     B1.MANIFEST, "cohort_named"),\n'),
         (
             '    ("unowned_tracked_file", "unowned_tracked", _new_tracked("docs/ci_v4/lean_matrix_unowned.md"), "docs/ci_v4/lean_matrix_unowned.md", "direct"),\n'
             '    ("forged_manifest_pin", "forged_manifest", _manifest_edit(lambda d: d["source_blobs"].__setitem__("docs/ci_v4/lean_b1/README.md", "0" * 40)),\n'
             '     B1.MANIFEST, "cohort_named"),\n')),
        ((
            '    ("registry_cohort_removed", "registry", _text_sub(REG, "\'tests.f03_financing_scope\', ", ""), REG, "pinned"),\n'
            '    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "\'tests.ci_v4_lean_b2_scope\', " + TAIL), REG, "pinned"),\n'
            '    ("registry_b1_unregistered", "registry", _text_sub(REG, ", \'tests.ci_v4_lean_b1_scope\'", ""), REG, "pinned"),\n'),
         (
             '    ("registry_cohort_removed", "registry", _text_sub(REG, "\'tests.f03_financing_scope\', ", ""), REG, "pinned"),\n'
             '    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "\'tests.ci_v4_lean_b3_scope\', " + TAIL), REG, "pinned"),\n'
             '    ("registry_b1_unregistered", "registry", _text_sub(REG, ", \'tests.ci_v4_lean_b1_scope\'", ""), REG, "pinned"),\n')),
        ((
            '    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, B1.PREDECESSOR, "pinned"),\n'
            '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v4_lean_b2_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'
            '    ("current_map_key_forged", "current_map", _forge_map_key, "docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),\n'),
         (
             '    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, B1.PREDECESSOR, "pinned"),\n'
             '    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", \'tests.ci_v4_lean_b3_scope\')", ")"), "tests/u1_scope.py", "pinned"),\n'
             '    ("current_map_key_forged", "current_map", _forge_map_key, "docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),\n')),
    ],
    'tests/test_ci_v4_perf_scope.py': [
        ((
            '\n'
            'from tests import f04_financing_scope as Q\n'),
         (
             '\n'
             '\n'
             'def _b3():\n'
             '    """The one reviewed B3 successor of B2 while it is registered and exact, else None."""\n'
             '    N = _b2()\n'
             '    N3 = N._next() if N is not None else None\n'
             '    return N3 if N3 is not None and N3.signature_ok() else None\n'
             '\n'
             'from tests import f04_financing_scope as Q\n')),
        ((
            '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"
            '                and C06_APPROVAL.signature_ok())\n'),
         (
             '            C.COHORT_MODULES[-6:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
             "            and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"
             '                and C06_APPROVAL.signature_ok())\n')),
        ((
            '    for p in sorted(F.HANDOFFS):\n'
            '        want = (_b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
            '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n'),
         (
             '    for p in sorted(F.HANDOFFS):\n'
             '        want = (_b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
             '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
             '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n')),
        ((
            '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
            "                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n"
            '                and C06_APPROVAL.signature_ok()))\n'),
         (
             '                or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")\n'
             "                    and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"
             '                and C06_APPROVAL.signature_ok()))\n')),
        ((
            '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', \'tests.f03_financing_scope\', "\n'
            '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')")\n'
            '    assert text.count(marker) == 1\n'),
         (
             '    marker = ("\'tests.r02_ppa_ux_scope\', \'tests.bess02_scope\', \'tests.ci_v4_perf_scope\', \'tests.f03_financing_scope\', "\n'
             '              "\'tests.t01e_remediation_scope\', \'tests.r03_ppa_scope\', \'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\', \'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')")\n'
             '    assert text.count(marker) == 1\n')),
        ((
            '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
            '        want = (_b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
            '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n'),
         (
             '        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y\n'
             '        want = (_b3().expected_handoff(ROOT, p) if _b3() is not None and p in _b3().HANDOFFS\n'
             '                else _b2().expected_handoff(ROOT, p) if _b2() is not None and p in _b2().HANDOFFS\n'
             '                else _b1().expected_handoff(ROOT, p) if _b1() is not None and p in _b1().HANDOFFS\n')),
    ],
    'tests/test_f03_financing_scope.py': [
        ("        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/test_f04_financing_scope.py': [
        ("        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope') and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('        authority=B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n',
         (
            '        B3=B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        authority=B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and path in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and path in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and path in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path\n')),
        ((
            '        _B1=C06_APPROVAL._next();_B2=_B1._next() if _B1 is not None and _B1.signature_ok() else None\n'
            "        expected=json.loads(_B2.expected_map(ROOT,path,_B2.effective_pins()) if _B2 is not None and _B2.signature_ok() else C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n"),
         (
            '        _B1=C06_APPROVAL._next();_B2=_B1._next() if _B1 is not None and _B1.signature_ok() else None;_B3=_B2._next() if _B2 is not None and _B2.signature_ok() else None\n'
            "        expected=json.loads(_B3.expected_map(ROOT,path,_B3.effective_pins()) if _B3 is not None and _B2 is not None and _B2.SUCCESSOR in C.COHORT_MODULES and _B3.signature_ok() else _B2.expected_map(ROOT,path,_B2.effective_pins()) if _B2 is not None and _B2.signature_ok() else C06_APPROVAL.expected_map(ROOT,path,C06_APPROVAL.effective_pins()) if C06_APPROVAL.signature_ok() else F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)\n")),
    ],
    'tests/test_post432_l01_l02_scope.py': [
        ("    if 'tests.ci_v4_lean_b2_scope' in C.COHORT_MODULES and B2 is not None and B2.signature_ok():\n",
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            "    if 'tests.ci_v4_lean_b3_scope' in C.COHORT_MODULES and B3 is not None and B3.signature_ok():\n"
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'
            "    elif 'tests.ci_v4_lean_b2_scope' in C.COHORT_MODULES and B2 is not None and B2.signature_ok():\n")),
    ],
    'tests/test_r02_ppa_ux_scope.py': [
        ("                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope') if m in C.COHORT_MODULES)\n",
         "                            'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope') if m in C.COHORT_MODULES)\n"),
        ('    if len(nxt) == 9 and B2 is not None and B2.signature_ok():\n',
         (
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '    if len(nxt) == 10 and B3 is not None and B3.signature_ok():\n'
            '        expected = B3.expected_handoff(ROOT, X.REGISTRY)\n'
            '    elif len(nxt) == 9 and B2 is not None and B2.signature_ok():\n')),
    ],
    'tests/test_r03_ppa_scope.py': [
        ('    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n',
         (
            '    B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
            '    B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n')),
        ('        authority = B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n',
         '        authority = B3 if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and p in W.HANDOFFS else Q if Q.signature_ok() and p in Q.HANDOFFS else T\n'),
        ("        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope'))\n",
         "        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope'))\n"),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/test_r04_ppa_scope.py': [
        ((
            '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
            '        authority = (B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the further reviewed B1 substitution of this shared path\n'
            '                     else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T)\n'),
         (
             '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
             '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
             '        authority = (B3 if B3 is not None and B3.signature_ok() and p in B3.HANDOFFS else B2 if B2 is not None and B2.signature_ok() and p in B2.HANDOFFS else B1 if B1 is not None and B1.signature_ok() and p in B1.HANDOFFS             # the further reviewed B1 substitution of this shared path\n'
             '                     else C06_APPROVAL if C06_APPROVAL.signature_ok() and p in C06_APPROVAL.HANDOFFS else T)\n')),
        ((
            'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
            '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\'))\n'
            '                                                    and C06_APPROVAL.signature_ok())\n'),
         (
             'def test_registered_exactly_once_as_the_terminal_cohort_after_f04():\n'
             '    assert (C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'))\n'
             '                                                    and C06_APPROVAL.signature_ok())\n')),
        ((
            '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")),\n'
            '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n'
            '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', \'tests.c06_cost_workspace_scope\'")),\n'),
         (
             '    ("duplicate_r04", lambda b: b.replace(b"\'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'")),\n'
             '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'
             '    ("swapped_f04_r04", lambda b: b.replace(b"\'tests.f04_financing_scope\', \'tests.r04_ppa_scope\', \'tests.c06_cost_workspace_scope\'", b"\'tests.r04_ppa_scope\', \'tests.f04_financing_scope\', \'tests.c06_cost_workspace_scope\'")),\n')),
    ],
    'tests/test_t01e_remediation_scope.py': [
        ('        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n',
         (
            '        B2 = B1._next() if B1 is not None and B1.signature_ok() else None\n'
            '        B3 = B2._next() if B2 is not None and B2.signature_ok() else None\n'
            '        if B3 is not None and B2 is not None and B2.SUCCESSOR in C.COHORT_MODULES and B3.signature_ok() and p in B3.HANDOFFS:            # the further reviewed B3 substitution of this shared path\n'
            '            assert (ROOT / p).read_bytes() == B3.expected_handoff(ROOT, p)\n'
            '            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]\n'
            '            continue\n')),
        ('                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\'))\n',
         '                                        ("tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope"))) or (C.COHORT_MODULES in (C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR), C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__, C06_APPROVAL.SUCCESSOR, \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\'))\n'),
        ('    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.fake_scope\')")),\n',
         '    ("fake_extra", lambda b: b.replace(b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\')", b"\'tests.ci_v4_lean_b1_scope\', \'tests.ci_v4_lean_b2_scope\', \'tests.ci_v4_lean_b3_scope\', \'tests.fake_scope\')")),\n'),
    ],
    'tests/u1_scope.py': [
        ("RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope')\n",
         "RECONCILED_SUCCESSORS = ('tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope')\n"),
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


SUCCESSOR = 'tests.ci_v5_bootstrap_scope'


def _next():
    """The one finite forward successor (CI V5 bootstrap). Low-level only: its signature never calls this module or the composite."""
    from tests.fin_v2_cohorts import COHORT_MODULES
    if SUCCESSOR not in COHORT_MODULES:
        return None
    from tests import ci_v5_bootstrap_scope
    return ci_v5_bootstrap_scope


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


def _p0_pins_frozen_edit(path, value, root, ref):
    """P1 (post-#457): one of the two named CI V4 control blobs may differ from BASE only to the EXACT pin of the registered P0 terminal
    (its signature holds and its manifest pins exactly this blob). Any other frozen path, blob or mode stays equal to BASE."""
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if 'tests.ci_v4_p0_scope' not in COHORT_MODULES:
            return False
        from tests import ci_v4_p0_scope as P0
        return value is not None and P0.supersedes(path, value, root, ref)
    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        return False


def _signature_ok(root, ref, closure=False):
    """Pure comparison of one batched snapshot against immutable BASE-derived expectations: nothing cached from mutable state."""
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope'), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope'), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope'), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        nx = _next_pins(root, ref)
        if nx.get("tests/ci_v4_lean_b3_scope.py", pins.get("tests/ci_v4_lean_b3_scope.py")) != _MODULE_BLOB:
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
        if any((current.get(p) != _blob(_base_bytes(key, p)) and not (p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml', 'tools/ci_v4_release_gate.py')
                                                               and _p0_pins_frozen_edit(p, current.get(p), root, ref)))
               or modes.get(p) != _base_mode(key, p) for p in FROZEN):
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

"""Finite M2-B Model/Radar coexistence boundary exact-source successor (Cohort #49).

Owner-authorized (2026-11-22, Correction D): admits ONLY the 5 literal Model/Radar
coexistence files (main_web.py, main_api.py, app/protocol_ui/router.py,
app/internal_auth_introspect.py, tests/test_m2b_model_radar_boundary.py), this
scope module + its tamper tests + its manifest, and the literal tail-chain handoffs.
Never weakens historical FORBIDDEN lists, never touches financial_engine/, finco_core/,
domain/, migrations/, .github/, tools/, static/, frontend/, or parked PR #473.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = '707e68b290694c57b470f4a112c190abb3d02ac9'
BASE_TREE = '0d4e8961c33e7bab7aa94077ee4fe9b561061ba2'
MANIFEST = 'docs/radar_separation/m2b_model_boundary/SOURCE_SUCCESSOR.json'
SCHEMA = 'M2B_RADAR_BOUNDARY_EXACT_SOURCE_V1'
AUTHORIZATION = 'Owner authorization 2026-11-22 (Correction D): bounded exact-source successor for Model/Radar coexistence boundary (main_web.py, main_api.py, app/protocol_ui/router.py, app/internal_auth_introspect.py, tests/test_m2b_model_radar_boundary.py) and finite tail-chain handoffs; no merge, deploy, V5 activation, #473 edit, or financial change.'
REGISTRY = "tests/fin_v2_cohorts.py"
PREDECESSOR = "tests/ci_v4_p0_scope.py"
BASE_COHORTS = ('tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope', 'tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')
NEW = frozenset(('app/internal_auth_introspect.py', 'tests/m2b_radar_boundary_scope.py', 'tests/test_m2b_model_radar_boundary.py', 'tests/test_m2b_radar_boundary_scope.py'))
REPLACED = frozenset(('app/protocol_ui/router.py', 'main_api.py', 'main_web.py'))
BOUNDARY_PROTECTED_PATHS = frozenset(("main_web.py",))
CI_PATHS = frozenset(())
HANDOFF_PATHS = frozenset(('tests/c06_cost_workspace_scope.py', 'tests/ci_v4_full_recovery_scope.py', 'tests/ci_v4_lean_b1_scope.py', 'tests/ci_v4_lean_b2_scope.py', 'tests/ci_v4_lean_b3_scope.py', 'tests/ci_v4_p0_scope.py', 'tests/ci_v4_scope.py', 'tests/ci_v5_bootstrap_scope.py', 'tests/ci_v5_gate_scope.py', 'tests/ci_v5_hardening_scope.py', 'tests/fin_v2_cohorts.py', 'tests/post413_o1_scope.py', 'tests/post413_r17_scope.py', 'tests/post413_r18_scope.py', 'tests/post413_r1_scope.py', 'tests/u1_scope.py'))
CURRENT_MAPS = frozenset(('docs/ci_v4/SOURCE_SUCCESSOR.json', 'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json', 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json', 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json', 'docs/tax_reference_registry/SOURCE_SUCCESSOR.json'))
MAP_KEYS = ("tests/fin_v2_cohorts.py", "tests/u1_scope.py")
SUPERSEDED = HANDOFF_PATHS | REPLACED | CURRENT_MAPS
OWNED_PATHS = NEW | SUPERSEDED
FORBIDDEN = ("financial_engine/", "finco_core/", "domain/", "migrations/", "research/", "frontend/", "static/", ".github/", "tools/")
FROZEN = ('.github/workflows/ci_v4_f01_job.yml', '.github/workflows/ci_v4_pr.yml', '.github/workflows/ci_v4_release_gate.yml', '.github/workflows/ci_v4_shadow_split.yml', 'docs/ci_v4/ci-v4-policy.json', 'docs/ci_v4/full_skip_baseline.json', 'docs/ci_v4/module_weights.json', 'pytest.ini', 'tools/ci_v4_activate.py', 'tools/ci_v4_aggregate.py', 'tools/ci_v4_full_record.py', 'tools/ci_v4_governance_gate.py', 'tools/ci_v4_nodes.py', 'tools/ci_v4_schedule.py', 'tools/ci_v4_select.py', 'tools/ci_v4_shard.py')
HANDOFFS = {'tests/fin_v2_cohorts.py': [("'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')", "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')")], 'tests/u1_scope.py': [("'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')", "'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')"), ("    return path.startswith(('.github/', 'tools/')) and any(callable(getattr(m, 'ci_owns', None)) and m.ci_owns(path, repo, ref) for m in _later_modules())", "    return (path.startswith(('.github/', 'tools/')) or path == 'main_web.py') and any(callable(getattr(m, 'ci_owns', None)) and m.ci_owns(path, repo, ref) for m in _later_modules())")], 'tests/ci_v4_scope.py': [("    if 'tests.ci_v4_p0_scope' in COHORT_MODULES:      # P1 (post-#457): the P0 terminal admits ITS literal guard paths (workflow + tool) only; no wildcard\n        from tests import ci_v4_p0_scope as P0\n        out = out | (P0.CI_PATHS if P0.exact_blobs_ok(root, ref) else frozenset())\n    return out", "    if 'tests.ci_v4_p0_scope' in COHORT_MODULES:      # P1 (post-#457): the P0 terminal admits ITS literal guard paths (workflow + tool) only; no wildcard\n        from tests import ci_v4_p0_scope as P0\n        out = out | (P0.CI_PATHS if P0.exact_blobs_ok(root, ref) else frozenset())\n    if 'tests.m2b_radar_boundary_scope' in COHORT_MODULES:\n        from tests import m2b_radar_boundary_scope as M2B\n        out = out | (M2B.BOUNDARY_PROTECTED_PATHS if M2B.exact_blobs_ok(root, ref) else frozenset())\n    return out"), ("    if path in ('tests/fin_v2_integration_409_scope.py', 'tests/post413_r1_scope.py'):", "    if path in ('tests/fin_v2_integration_409_scope.py', 'tests/post413_r1_scope.py', 'tests/post413_r17_scope.py', 'tests/post413_r18_scope.py'):")], 'tests/post413_o1_scope.py': [("    if not path.startswith(('.github/', 'tools/')):\n        return False", "    if not (path.startswith(('.github/', 'tools/')) or path == 'main_web.py'):\n        return False")], 'tests/post413_r1_scope.py': [("    if not path.startswith(('.github/', 'tools/')):\n        return False", "    if not (path.startswith(('.github/', 'tools/')) or path == 'main_web.py'):\n        return False")], 'tests/post413_r17_scope.py': [("    if not path.startswith(('.github/', 'tools/')):\n        return False", "    if not (path.startswith(('.github/', 'tools/')) or path == 'main_web.py'):\n        return False"), ('def _exact_blobs_ok(repo=None, ref=None):\n', "def _m2b_self_pin(path, value, root, ref):\n    if path != 'tests/post413_r17_scope.py':\n        return False\n    from tests import ci_v4_p0_scope as P0\n    return P0.supersedes(path, value, root, ref)\n\n\ndef _exact_blobs_ok(repo=None, ref=None):\n"), ("        if ref is None:\n            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n                return False\n        else:\n            listed = {}\n            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():\n                meta, name = line.split('\\t', 1)\n                listed[name] = meta.split()[2]\n            if listed != pins:\n                return False\n", "        if ref is None:\n            if any(_blob(_read(root, p, ref)) != sha and not _m2b_self_pin(p, _blob(_read(root, p, ref)), root, ref) for p, sha in pins.items()):\n                return False\n        else:\n            listed = {}\n            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():\n                meta, name = line.split('\\t', 1)\n                listed[name] = meta.split()[2]\n            if set(listed) != set(pins) or any(listed[p] != sha and not _m2b_self_pin(p, listed[p], root, ref) for p, sha in pins.items()):\n                return False\n")], 'tests/post413_r18_scope.py': [("    if not path.startswith(('.github/', 'tools/')):\n        return False", "    if not (path.startswith(('.github/', 'tools/')) or path == 'main_web.py'):\n        return False"), ('def _exact_blobs_ok(repo=None, ref=None):\n', "def _m2b_self_pin(path, value, root, ref):\n    if path != 'tests/post413_r18_scope.py':\n        return False\n    from tests import ci_v4_p0_scope as P0\n    return P0.supersedes(path, value, root, ref)\n\n\ndef _exact_blobs_ok(repo=None, ref=None):\n"), ("        if ref is None:\n            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):\n                return False\n        else:\n            listed = {}\n            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():\n                meta, name = line.split('\\t', 1)\n                listed[name] = meta.split()[2]\n            if listed != pins:\n                return False\n", "        if ref is None:\n            if any(_blob(_read(root, p, ref)) != sha and not _m2b_self_pin(p, _blob(_read(root, p, ref)), root, ref) for p, sha in pins.items()):\n                return False\n        else:\n            listed = {}\n            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():\n                meta, name = line.split('\\t', 1)\n                listed[name] = meta.split()[2]\n            if set(listed) != set(pins) or any(listed[p] != sha and not _m2b_self_pin(p, listed[p], root, ref) for p, sha in pins.items()):\n                return False\n")], 'tests/c06_cost_workspace_scope.py': [("    if 'tests.ci_v4_p0_scope' in COHORT_MODULES:\r\n        from tests import ci_v4_p0_scope as P0\r\n        out = out | (frozenset(P0.HANDOFFS) if P0.signature_ok(root, ref) else frozenset())\r\n    return out\r\n", "    if 'tests.ci_v4_p0_scope' in COHORT_MODULES:\r\n        from tests import ci_v4_p0_scope as P0\r\n        out = out | (frozenset(P0.HANDOFFS) if P0.signature_ok(root, ref) else frozenset())\r\n    if 'tests.m2b_radar_boundary_scope' in COHORT_MODULES:\r\n        from tests import m2b_radar_boundary_scope as M2B\r\n        out = out | (frozenset(M2B.HANDOFFS) if M2B.signature_ok(root, ref) else frozenset())\r\n    return out\r\n"), ("BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v4_lean_b1_scope.py': [("BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v4_lean_b2_scope.py': [("BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v4_lean_b3_scope.py': [("BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v5_bootstrap_scope.py': [("BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v5_hardening_scope.py': [("BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.ci_v4_full_recovery_scope') + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v5_gate_scope.py': [("BASE_COHORTS + (__name__, SUCCESSOR) + ('tests.ci_v4_p0_scope',)):", "BASE_COHORTS + (__name__, SUCCESSOR) + ('tests.ci_v4_p0_scope',), BASE_COHORTS + (__name__, SUCCESSOR) + ('tests.ci_v4_p0_scope', 'tests.m2b_radar_boundary_scope')):")], 'tests/ci_v4_full_recovery_scope.py': [('        from tests.fin_v2_cohorts import COHORT_MODULES\n        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n            return False\n        d = manifest(root, ref)', "        from tests.fin_v2_cohorts import COHORT_MODULES\n        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR), BASE_COHORTS + (__name__, SUCCESSOR, 'tests.m2b_radar_boundary_scope')):\n            return False\n        d = manifest(root, ref)")], 'tests/ci_v4_p0_scope.py': [('def reviewed_edits_ok(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        pins = manifest(root, ref).get("source_blobs", {})\n        for path in HANDOFFS:\n            actual = _read(root, path, ref)\n            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n                return False\n        return True\n', 'def reviewed_edits_ok(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        pins = manifest(root, ref).get("source_blobs", {})\n        N = _next()\n        nxt = N is not None and N.signature_ok(root, ref)\n        for path in HANDOFFS:\n            if nxt and path in N.HANDOFFS:\n                continue\n            actual = _read(root, path, ref)\n            if actual != expected_handoff(root, path) or pins.get(path) != _blob(actual):\n                return False\n        return N.reviewed_edits_ok(root, ref) if nxt else True\n'), ('    _SCOPE.append({})\n    try:\n        yield\n    finally:\n        _SCOPE.pop()\n\n\ndef _compute(root, ref, mode):\n    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the changed/untracked checks."""\n    if mode == "exact":\n        return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n    return _signature_ok(root, ref, mode)\n', '    _SCOPE.append({})\n    try:\n        N = _next()\n        if N is None:\n            yield\n        else:\n            with N.scoped():\n                yield\n    finally:\n        _SCOPE.pop()\n\n\ndef _compute(root, ref, mode):\n    """mode False: signature; True: signature + map bytes; "exact": the full closure incl. the changed/untracked checks."""\n    from contextlib import nullcontext\n    N = _next()\n    with (N.scoped() if N is not None else nullcontext()):\n        if mode == "exact":\n            return _signature_ok(root, ref, True) and _diff_ok(root, ref)\n        return _signature_ok(root, ref, mode)\n'), ('def map_keys(repo=None, ref=None):\n    return MAP_PIN_KEYS\n', "SUCCESSOR = 'tests.m2b_radar_boundary_scope'\n\n\ndef _next():\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if SUCCESSOR not in COHORT_MODULES:\n        return None\n    from tests import m2b_radar_boundary_scope\n    return m2b_radar_boundary_scope\n\n\ndef _next_pins(root, ref):\n    N = _next()\n    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n\n\ndef later_handoffs(root, ref):\n    N = _next()\n    if N is None or not N.signature_ok(root, ref):\n        return frozenset()\n    return frozenset(N.HANDOFFS) | (N.later_handoffs(root, ref) if hasattr(N, 'later_handoffs') else frozenset())\n\n\ndef map_keys(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    with scoped():\n        N = _next()\n        more = tuple(k for k in N.map_keys(root, ref) if k not in MAP_PIN_KEYS) if N is not None and N.signature_ok(root, ref) else ()\n        return tuple(MAP_PIN_KEYS) + more\n"), ('        if COHORT_MODULES != BASE_COHORTS + (__name__,):\n            return False\n        d = manifest(root, ref)\n        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n        if pins.get("tests/ci_v4_p0_scope.py") != _MODULE_BLOB:\n            return False\n', '        if COHORT_MODULES not in (BASE_COHORTS + (__name__,), BASE_COHORTS + (__name__, SUCCESSOR)):\n            return False\n        d = manifest(root, ref)\n        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})\n        nx = _next_pins(root, ref)\n        if nx.get("tests/ci_v4_p0_scope.py", pins.get("tests/ci_v4_p0_scope.py")) != _MODULE_BLOB:\n            return False\n'), ('        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\n        if {p: current.get(p) for p in judged} != {p: pins[p] for p in judged}:\n            return False\n', '        judged = {p for p in pins if closure or p not in CURRENT_MAPS}\n        cur = {p: nx.get(p, b) for p, b in pins.items()}\n        current, modes = _snapshot(root, ref, judged | {MANIFEST} | set(FROZEN))\n        if {p: current.get(p) for p in judged} != {p: cur[p] for p in judged}:\n            return False\n'), ('        if closure:\n            for p in CURRENT_MAPS:\n                if current[p] != _expected_map_blob(key, p, moved):\n                    return False\n', '        if closure:\n            for p in CURRENT_MAPS:\n                if current[p] != nx.get(p, _expected_map_blob(key, p, moved)):\n                    return False\n'), ('def _diff_ok(root, ref):\n    try:\n        allowed = OWNED_PATHS | {MANIFEST} | _c06_product_paths(root, ref)\n', 'def _diff_ok(root, ref):\n    try:\n        allowed = closure_paths(root, ref)\n'), ('def effective_pins(repo=None, ref=None, *, signature=False):\n    return {**manifest(repo, ref).get("source_blobs", {}), **C06_REVIEWED_PRODUCT_BLOBS}\n\n\ndef closure_paths(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    if not signature_ok(root, ref):\n        return frozenset()\n    return OWNED_PATHS | {MANIFEST} | _c06_product_paths(root, ref)\n\n\ndef allowed_path(path, repo=None, ref=None):\n    if path in C06_REVIEWED_PRODUCT_BLOBS:\n        return path in closure_paths(repo, ref)\n    return path in OWNED_PATHS | {MANIFEST} and signature_ok(repo, ref)\n', 'def effective_pins(repo=None, ref=None, *, signature=False):\n    root = Path(repo) if repo is not None else ROOT\n    with scoped():\n        pins = {**manifest(root, ref).get("source_blobs", {}), **C06_REVIEWED_PRODUCT_BLOBS}\n        pins.update(_next_pins(root, ref))\n        return pins\n\n\ndef closure_paths(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    with scoped():\n        if not signature_ok(root, ref):\n            return frozenset()\n        N = _next()\n        return OWNED_PATHS | {MANIFEST} | _c06_product_paths(root, ref) | (N.closure_paths(root, ref) if N is not None else frozenset())\n\n\ndef allowed_path(path, repo=None, ref=None):\n    return path in closure_paths(repo, ref)\n'), ('def supersedes(path, value, repo=None, ref=None):\n    if path not in SUPERSEDED:\n        return False\n    # The signature decides a supersession; the composite separately requires every cohort\'s FULL exactness (map bytes, changed set, untracked\n    # files), so a signature-only verdict never makes the tree valid.\n    return signature_ok(repo, ref) and manifest(repo, ref).get("source_blobs", {}).get(path) == value\n', 'def supersedes(path, value, repo=None, ref=None):\n    with scoped():\n        N = _next()\n        if N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref):\n            return True\n        if path not in SUPERSEDED:\n            return False\n        return signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value\n'), ('def nontrust_scope_authorized(changed, repo=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:\n', 'def nontrust_scope_authorized(changed, repo=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        N = _next()\n        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n            return True\n        if _git(root, "merge-base", "origin/main", "HEAD").decode().strip() != BASE:\n')]}


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref=None):
    return (Path(root) / path).read_bytes() if ref is None else _git(root, "show", ref + ":" + path)


def _blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


_MODULE_BLOB = _blob(Path(__file__).read_bytes())


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        raw = _read(root, MANIFEST, ref)
        d = json.loads(raw)
        if raw != (json.dumps(d, indent=2, sort_keys=True) + "\n").encode():
            return {}
        return d if (
            isinstance(d, dict)
            and set(d) == {"schema_version", "authorization", "base", "base_tree", "source_blobs", "base_blobs", "source_modes", "base_modes"}
            and d.get("authorization") == AUTHORIZATION
            and d["schema_version"] == SCHEMA
            and d["base"] == BASE
            and d["base_tree"] == BASE_TREE
            and isinstance(d["source_blobs"], dict)
            and isinstance(d["base_blobs"], dict)
        ) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


@lru_cache(maxsize=512)
def _base_mode(root, path):
    return _git(Path(root), "ls-tree", BASE, "--", path).decode().split()[0]


@lru_cache(maxsize=512)
def _base_bytes(root, path):
    return _git(Path(root), "show", BASE + ":" + path)


@lru_cache(maxsize=8)
def _base_tree(root):
    return _git(Path(root), "rev-parse", BASE + "^{tree}").decode().strip()


def expected_handoff(root, path):
    text = _base_bytes(str(root), path).decode()
    for old, new in HANDOFFS[path]:
        if text.count(old) != 1:
            raise ValueError("reviewed handoff is missing or ambiguous")
        text = text.replace(old, new, 1)
    return text.encode()


@lru_cache(maxsize=256)
def _expected_blob(root, path):
    return _blob(expected_handoff(root, path))


def expected_map(root, path, pins=None):
    d = json.loads(_base_bytes(str(root), path))
    pins = manifest(root).get("source_blobs", {}) if pins is None else pins
    for key in MAP_KEYS:
        if key in d["source_blobs"]:
            d["source_blobs"][key] = pins[key]
    return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()


@lru_cache(maxsize=256)
def _expected_map_blob(root, path, moved):
    return _blob(expected_map(Path(root), path, dict(zip(MAP_KEYS, moved))))


def map_keys(repo=None, ref=None):
    return MAP_KEYS


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


def _snapshot(root, ref, paths):
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
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if COHORT_MODULES != BASE_COHORTS + (__name__,):
            return False
        d = manifest(root, ref)
        pins, base = d.get("source_blobs", {}), d.get("base_blobs", {})
        if pins.get("tests/m2b_radar_boundary_scope.py") != _MODULE_BLOB:
            return False
        if set(pins) != OWNED_PATHS or set(base) != SUPERSEDED:
            return False
        if d.get("source_modes") != {p: "100644" for p in OWNED_PATHS} or d.get("base_modes") != {p: "100644" for p in SUPERSEDED}:
            return False
        if not NEW.isdisjoint(base) or any(p.startswith(FORBIDDEN) or p.startswith("/") or ".." in p.split("/") or "*" in p for p in OWNED_PATHS | {MANIFEST}):
            return False
        _git(root, "merge-base", "--is-ancestor", BASE, ref or "HEAD")
        key = str(root)
        if _base_tree(key) != BASE_TREE:
            return False
        if any(_blob(_base_bytes(key, p)) != base[p] for p in base):
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
        if set(HANDOFFS) != HANDOFF_PATHS:
            return False
        if any(pins[p] != _expected_blob(key, p) for p in HANDOFFS):
            return False
        moved = tuple(pins[k] for k in MAP_KEYS)
        for p in CURRENT_MAPS:
            if pins[p] != _expected_map_blob(key, p, moved):
                return False
        if closure:
            for p in CURRENT_MAPS:
                if current[p] != _expected_map_blob(key, p, moved):
                    return False
        if any(current.get(p) != _blob(_base_bytes(key, p)) or modes.get(p) != _base_mode(key, p) for p in FROZEN):
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def _diff_ok(root, ref):
    try:
        allowed = OWNED_PATHS | {MANIFEST}
        changed = set(_git(root, "diff", "--name-only", "--no-renames", BASE, *([ref] if ref else []), "--").decode().splitlines())
        if not changed <= allowed:
            return False
        if ref is None:
            untracked = set(_git(root, "ls-files", "--others", "--exclude-standard").decode().splitlines())
            if any(p not in allowed and not (p.startswith("evidence/") and p.endswith((".json", ".xml", ".png", ".txt", ".csv", ".html", ".zip"))) for p in untracked):
                return False
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _compute(root, ref, mode):
    if mode == "exact":
        return _signature_ok(root, ref, True) and _diff_ok(root, ref)
    return _signature_ok(root, ref, mode)


def _verdict(root, ref, mode):
    if _SCOPE:
        k = (str(root), ref, mode)
        memo = _SCOPE[-1]
        if k not in memo:
            memo[k] = _compute(root, ref, mode)
        return memo[k]
    return _compute(root, ref, mode)


def signature_ok(repo=None, ref=None):
    return _verdict(Path(repo) if repo is not None else ROOT, ref, False)


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(Path(repo) if repo is not None else ROOT, ref, "exact")


def effective_pins(repo=None, ref=None, *, signature=False):
    return dict(manifest(repo, ref).get("source_blobs", {}))


def closure_paths(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if not signature_ok(root, ref):
        return frozenset()
    return OWNED_PATHS | {MANIFEST}


def allowed_path(path, repo=None, ref=None):
    return path in closure_paths(repo, ref)


def ci_owns(path, repo=None, ref=None):
    return path in BOUNDARY_PROTECTED_PATHS and exact_blobs_ok(repo, ref)


def supersedes(path, value, repo=None, ref=None):
    if path not in SUPERSEDED:
        return False
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

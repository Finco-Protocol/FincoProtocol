"""Closed ON-BESS-01 Correction A leaf; no predecessor/composite authority.

Exact current blobs and accepted main objects, immutable historical maps,
finite current-map moves, structural router review and complete path/mode
closure are separate obligations. Only valid() imports the composite; the
low-level predecessor hooks terminate here. Memos last one read-only call.
"""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = '91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
BASE_TREE = 'e9573d7802b319deb943dab60667778a431370e4'
MANIFEST = 'docs/bess_setup/SOURCE_SUCCESSOR.json'
SCHEMA = 'ON_BESS_01_PREVIEW_EXACT_SOURCE_V1'
APP_PATHS = frozenset((
    'app/services/bess_setup_preview.py',
    'app/v2/bess_setup_router.py',
    'app/v2/react_poc_router.py',
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
OWNED_PATHS = APP_PATHS | CURRENT_MAPS | frozenset((
    'frontend/src/app/newProject/NewProjectWizard.tsx',
    'frontend/src/app/newProject/bess/BessSetupPreview.tsx',
    'frontend/src/app/newProject/bess/bessSetup.css',
    'frontend/src/app/newProject/bess/types.ts',
    'static/react/finco-react.js',
    'static/react/finco-react.css',
    'tests/fin_v2_cohorts.py',
    'tests/wf03_lifecycle_scope.py',
    'tests/u1_scope.py',
    'tests/ux_pr3b2_scope.py',
    'tests/ux_pr3b1_scope.py',
    'tests/tax_reference_registry_scope.py',
    'tests/test_ux_pr3b2_scope.py',
    'tests/on_bess01_scope.py',
    'tests/on_bess01_router_review.py',
    'tests/on_bess01_correction_checks.py',
    'tests/on_bess01_contract_checks.py',
    'tests/on_bess01_browser_checks.py',
    'tests/on_bess01_governance_checks.py',
    'docs/bess_setup/IMPLEMENTATION.md',
    'docs/bess_setup/CORRECTION_A.md',
    'docs/bess_setup/CORRECTION_B.md',
    'tests/test_trust_readiness_registry.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/on_bess01_reviewed_successors.py',
    'tests/on_bess01_successor_checks.py',
))
SUPERSEDED = frozenset((
    'app/v2/react_poc_router.py',
    'frontend/src/app/newProject/NewProjectWizard.tsx',
    'static/react/finco-react.js',
    'static/react/finco-react.css',
    'tests/fin_v2_cohorts.py',
    'tests/wf03_lifecycle_scope.py',
    'tests/u1_scope.py',
    'tests/ux_pr3b2_scope.py',
    'tests/ux_pr3b1_scope.py',
    'tests/tax_reference_registry_scope.py',
    'tests/test_ux_pr3b2_scope.py',
    'tests/test_trust_readiness_registry.py',
    'tests/model_react_rcm_financing_acceptance.py',
)) | CURRENT_MAPS
FROZEN = frozenset((
    'app/v2/router.py',
    'frontend/src/app/financing/BankabilityEditor.tsx',
    'frontend/src/app/financing/FinancingStudio.tsx',
    'frontend/src/app/workflow/workflowShared.tsx',
    'app/v2/react_new_project.py',
    'frontend/src/app/newProject/types.ts',
    'app/workbook/bess_config.py',
    'app/services/project_library_service.py',
    'app/services/reference_seed_service.py',
    'app/product_capability.py',
    'tests/test_rcm_adapter_csrf_successor.py',
    'tests/test_trust_readiness_controls.py',
    'tests/test_rc_sec_csrf_successor.py',
    'tests/test_ci_v4_scope.py',
    'tests/test_finv2_d01_routes_and_matrix.py',
    'tests/test_model_workspace_productivity_v1.py',
    'tests/test_finval_f01_fixture_integrity.py',
    'tests/test_finval_f01_scope.py',
    'tests/test_finval_rate_successor.py',
    'tests/test_u1_scope.py',
    'tests/test_wf03_lifecycle_scope.py',
))
GENERATED_EVIDENCE = frozenset((
    'evidence/browser/data_center-0.056.png',
    'evidence/browser/data_center-5.60.png',
    'evidence/browser/data_center.json',
    'evidence/browser/ev_charging-0.056.png',
    'evidence/browser/ev_charging-5.60.png',
    'evidence/browser/ev_charging.json',
    'evidence/browser/solar-0.056.png',
    'evidence/browser/solar-5.60.png',
    'evidence/browser/solar.json',
    'evidence/browser/wind-0.056.png',
    'evidence/browser/wind-5.60.png',
    'evidence/browser/wind.json',
    'evidence/financial-browser.xml',
    'evidence/financial/data_center-history-False.json',
    'evidence/financial/data_center-history-True.json',
    'evidence/financial/data_center-rate-0.056.json',
    'evidence/financial/data_center-rate-0.56.json',
    'evidence/financial/data_center-rate-5.6.json',
    'evidence/financial/data_center-rate-9.0.json',
    'evidence/financial/ev_charging-history-False.json',
    'evidence/financial/ev_charging-history-True.json',
    'evidence/financial/ev_charging-rate-0.056.json',
    'evidence/financial/ev_charging-rate-0.56.json',
    'evidence/financial/ev_charging-rate-5.6.json',
    'evidence/financial/ev_charging-rate-9.0.json',
    'evidence/financial/http-data_center-0.056.json',
    'evidence/financial/http-data_center-0.56.json',
    'evidence/financial/http-data_center-5.6.json',
    'evidence/financial/http-data_center-9.0.json',
    'evidence/financial/http-ev_charging-0.056.json',
    'evidence/financial/http-ev_charging-0.56.json',
    'evidence/financial/http-ev_charging-5.6.json',
    'evidence/financial/http-ev_charging-9.0.json',
    'evidence/financial/http-solar-0.056.json',
    'evidence/financial/http-solar-0.56.json',
    'evidence/financial/http-solar-5.6.json',
    'evidence/financial/http-solar-9.0.json',
    'evidence/financial/http-wind-0.056.json',
    'evidence/financial/http-wind-0.56.json',
    'evidence/financial/http-wind-5.6.json',
    'evidence/financial/http-wind-9.0.json',
    'evidence/financial/solar-history-False.json',
    'evidence/financial/solar-history-True.json',
    'evidence/financial/solar-rate-0.056.json',
    'evidence/financial/solar-rate-0.56.json',
    'evidence/financial/solar-rate-5.6.json',
    'evidence/financial/solar-rate-9.0.json',
    'evidence/financial/wind-history-False.json',
    'evidence/financial/wind-history-True.json',
    'evidence/financial/wind-rate-0.056.json',
    'evidence/financial/wind-rate-0.56.json',
    'evidence/financial/wind-rate-5.6.json',
    'evidence/financial/wind-rate-9.0.json',
    'evidence/merge-tree.json',
    'evidence/native.xml',
    'evidence/native/native-data_center-0.056.json',
    'evidence/native/native-data_center-0.56.json',
    'evidence/native/native-data_center-5.6.json',
    'evidence/native/native-data_center-9.0.json',
    'evidence/native/native-data_center-None.json',
    'evidence/native/native-ev_charging-0.056.json',
    'evidence/native/native-ev_charging-0.56.json',
    'evidence/native/native-ev_charging-5.6.json',
    'evidence/native/native-ev_charging-9.0.json',
    'evidence/native/native-ev_charging-None.json',
    'evidence/native/native-solar-0.056.json',
    'evidence/native/native-solar-0.56.json',
    'evidence/native/native-solar-5.6.json',
    'evidence/native/native-solar-9.0.json',
    'evidence/native/native-solar-None.json',
    'evidence/native/native-wind-0.056.json',
    'evidence/native/native-wind-0.56.json',
    'evidence/native/native-wind-5.6.json',
    'evidence/native/native-wind-9.0.json',
    'evidence/native/native-wind-None.json',
    'evidence/source.json',
))
_SCOPE = []
_ENCLOSING_SCOPES = (
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
)


def _git(root, *args):
    return subprocess.check_output(['git', *map(str, args)], cwd=root, stderr=subprocess.DEVNULL)


@lru_cache(maxsize=256)
def _base_fact(root, args, reader):
    return reader(root, *args)  # only immutable BASE objects, never current bytes


def _base(root, *args):
    return _base_fact(root, args, _git)


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        if (set(data) != {'schema_version', 'base', 'base_tree', 'source_blobs', 'base_blobs'}
                or data['schema_version'] != SCHEMA or data['base'] != BASE or data['base_tree'] != BASE_TREE
                or not isinstance(data['source_blobs'], dict) or not isinstance(data['base_blobs'], dict)):
            return {}
        return data
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


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


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo, ref, True)


def signature_ok(repo=None, ref=None):
    return _verdict(repo, ref, False)


def _verdict(repo, ref, closure):
    key = (str(repo if repo is not None else ROOT), ref, closure)
    if not _SCOPE:
        # Reuse only an already-open, read-only predecessor call scope. This is
        # metadata lookup, never a predecessor verdict/import; it cannot form
        # a source-authority cycle. Drop the memo with that outermost call.
        for name in _ENCLOSING_SCOPES:
            outer = getattr(sys.modules.get(name), '_SCOPE', None)
            if outer:
                memo = outer[-1]
                shared = ('tests.on_bess01_scope.verdict',) + key
                if shared not in memo:
                    with scoped():
                        memo[shared] = _verdict(repo, ref, closure)
                return memo[shared]
        with scoped():
            return _verdict(repo, ref, closure)
    if key not in _SCOPE[-1]:
        _SCOPE[-1][key] = _exact(repo, ref, closure)
    return _SCOPE[-1][key]


def _maps_ok(root, ref, pins):
    for path in CURRENT_MAPS:
        old = json.loads(_base(root, 'show', BASE + ':' + path))
        now = json.loads(_read(root, path, ref))
        if set(now) != set(old) or any(now[k] != old[k] for k in old if k != 'source_blobs'):
            return False
        a, b = old['source_blobs'], now['source_blobs']
        if set(a) != set(b):
            return False
        if any(b[p] != a[p] and (p not in SUPERSEDED - CURRENT_MAPS or b[p] != pins[p]) for p in a):
            return False
    return True


def _foreign_bytes_and_modes_ok(root):
    # Git's index can hide drift through assume-unchanged/core.filemode. Verify
    # every non-owned accepted-main object directly as well as the git delta.
    # This grants no path permission; it strengthens the complete closure.
    for line in _base(root, 'ls-tree', '-r', BASE).decode().splitlines():
        meta, path = line.split('\t', 1)
        if path in OWNED_PATHS | {MANIFEST}:
            continue
        mode, kind, pin = meta.split()
        p = root / path
        if kind != 'blob' or mode not in ('100644', '100755') or not p.is_file() or p.is_symlink():
            return False
        if _blob(p.read_bytes()) != pin or bool(p.stat().st_mode & 0o111) != (mode == '100755'):
            return False
    return True


def _generated_evidence_ok(root, path):
    """Finite existing F01 workflow outputs only; never source ownership.

    No prefix/glob exception: unknown files and tracked evidence still fail the
    source delta closure. These regular data files are never evaluated and
    never supply pins or authority. Attestations must name the real HEAD/tree.
    """
    if path not in GENERATED_EVIDENCE:
        return False
    p = root / path
    if (not p.is_file() or p.is_symlink() or p.stat().st_mode & 0o111
            or p.stat().st_mode & 0o7777 not in (0o600, 0o644) or p.stat().st_nlink != 1
            or p.stat().st_size > 5_000_000
            or any(parent.is_symlink() for parent in p.parents if parent != root and root in parent.parents)):
        return False
    raw = p.read_bytes()
    try:
        if path.endswith('.png'):
            # Validate bounded PNG framing and CRCs; magic bytes alone are insufficient.
            import struct
            import zlib
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                return False
            offset, kinds = 8, []
            while offset + 12 <= len(raw):
                length = int.from_bytes(raw[offset:offset + 4], 'big')
                end = offset + 12 + length
                if end > len(raw):
                    return False
                kind = raw[offset + 4:offset + 8]
                chunk = raw[offset + 8:offset + 8 + length]
                crc = int.from_bytes(raw[end - 4:end], 'big')
                if zlib.crc32(kind + chunk) & 0xffffffff != crc:
                    return False
                if not kinds:
                    if kind != b'IHDR' or length != 13:
                        return False
                    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', chunk)
                    if (not 0 < width <= 10000 or not 0 < height <= 10000 or width * height > 20_000_000
                            or depth != 8 or color not in (2, 6) or compression or filtering or interlace):
                        return False
                elif kind == b'IHDR':
                    return False
                kinds.append(kind)
                offset = end
                if kind == b'IEND':
                    return length == 0 and offset == len(raw) and b'IDAT' in kinds
            return False
        if path.endswith('.xml'):
            import xml.etree.ElementTree as ET
            return b'<!DOCTYPE' not in raw.upper() and ET.fromstring(raw).tag in ('testsuite', 'testsuites')
        data = json.loads(raw)
        if path in ('evidence/source.json', 'evidence/merge-tree.json'):
            head = _git(root, 'rev-parse', 'HEAD').decode().strip()
            tree = _git(root, 'rev-parse', 'HEAD^{tree}').decode().strip()
            if not isinstance(data, dict) or data.get('head') != head or data.get('tree') != tree:
                return False
            if path == 'evidence/source.json':
                return set(data) == {'head', 'tree'}
            required = {'head', 'tree', 'mode', 'merge_sha', 'merge_tree', 'equivalent'}
            if not (required <= set(data) <= required | {'authenticated_drift'} and data['equivalent'] is True):
                return False
            if data['mode'] == 'main-head':
                return set(data) == required and data['merge_sha'] is None and data['merge_tree'] is None
            if data['mode'] != 'identical-tree' or data['merge_tree'] != tree:
                return False
            import re
            merge = data['merge_sha']
            if not isinstance(merge, str) or not re.fullmatch('[0-9a-f]{40}', merge):
                return False
            # The workflow has fetched this immutable object. Metadata is data,
            # never a source-authority shortcut; verify its actual tree/parents.
            parents = _git(root, 'rev-list', '--parents', '-n', '1', merge).decode().split()
            return (len(parents) == 3 and parents[-1] == head
                    and _git(root, 'rev-parse', merge + '^{tree}').decode().strip() == tree
                    and ('authenticated_drift' not in data or isinstance(data['authenticated_drift'], dict)))
        return isinstance(data, (dict, list))
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, subprocess.CalledProcessError):
        return False


def _exact(repo, ref, closure):
    root = Path(repo) if repo is not None else ROOT
    try:
        # Registry membership only; never evaluate its composite verdict here.
        from tests.fin_v2_cohorts import COHORT_MODULES
        if __name__ not in COHORT_MODULES:
            return False
        data = manifest(root, ref)
        pins = data.get('source_blobs', {})
        if set(pins) != OWNED_PATHS or set(data.get('base_blobs', {})) != SUPERSEDED:
            return False
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        if _base(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        old = {line.split('\t')[1]: line.split()[2] for line in _base(root, 'ls-tree', '-r', BASE, '--', *sorted(OWNED_PATHS)).decode().splitlines()}
        if old != data['base_blobs']:
            return False
        if any(_blob(_read(root, p, ref)) != pin for p, pin in pins.items()):
            return False
        if any(_read(root, p, ref) != _base(root, 'show', BASE + ':' + p) for p in FROZEN):
            return False
        if not _maps_ok(root, ref, pins):
            return False
        # Preserve ALL original assertion ASTs in the single reviewed consumer.
        import ast
        p = 'tests/test_ux_pr3b2_scope.py'
        assertions = lambda raw: [ast.dump(n) for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.Assert)]
        if assertions(_read(root, p, ref)) != assertions(_base(root, 'show', BASE + ':' + p)):
            return False
        from tests.on_bess01_reviewed_successors import reviewed_edits_ok
        if not reviewed_edits_ok(lambda p: _read(root, p, ref), lambda p: _base(root, 'show', BASE + ':' + p)):
            return False
        from tests.on_bess01_router_review import violations
        if violations(_read(root, 'app/v2/bess_setup_router.py', ref),
                      _read(root, 'app/v2/react_poc_router.py', ref),
                      _base(root, 'show', BASE + ':app/v2/react_poc_router.py')):
            return False
        old_registry = _base(root, 'show', BASE + ':tests/fin_v2_cohorts.py').decode()
        registry = _read(root, 'tests/fin_v2_cohorts.py', ref).decode()
        if registry != old_registry.replace("'tests.tax_reference_registry_scope')", "'tests.tax_reference_registry_scope', 'tests.on_bess01_scope')"):
            return False
        allowed = OWNED_PATHS | {MANIFEST}
        if closure:
            changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
            if not changed <= allowed:
                return False
            if ref is None:
                extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
                if any(p not in allowed and not _generated_evidence_ok(root, p) for p in extra):
                    return False
                if not _foreign_bytes_and_modes_ok(root):
                    return False
        if ref is None:
            if any(not (root / p).is_file() or (root / p).is_symlink() or (root / p).stat().st_mode & 0o111 for p in allowed | FROZEN):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(allowed | FROZEN)).decode().splitlines()
            if len(modes) != len(allowed | FROZEN) or any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    return path in OWNED_PATHS | {MANIFEST} or (ref is None and _generated_evidence_ok(root, path))


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref)['source_blobs'].get(path) == value


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo, ref) and composite(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    raw = source.encode() if isinstance(source, str) else source
    return path in pins and exact_blobs_ok(repo, ref) and (source is None or _blob(raw) == pins[path])


def protected_blobs(repo=None, ref=None):
    return {}

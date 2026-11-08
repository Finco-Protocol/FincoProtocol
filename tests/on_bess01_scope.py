"""Closed ON-BESS-01 source seal. No historical cohort or pin is relaxed.

This seal proves this slice only. Integration with protected predecessor
cohorts remains a separately reported dependency until their owner supplies
an exact successor. It never claims global governance acceptance.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
BASE_TREE = 'e9573d7802b319deb943dab60667778a431370e4'
MANIFEST = 'docs/bess_setup/SOURCE_SUCCESSOR.json'
SCHEMA = 'ON_BESS_01_PREVIEW_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset((
    'app/services/bess_setup_preview.py',
    'app/v2/bess_setup_router.py',
    'app/v2/react_new_project.py',
    'frontend/src/app/newProject/NewProjectWizard.tsx',
    'frontend/src/app/newProject/types.ts',
    'frontend/src/app/newProject/bess/BessSetupPreview.tsx',
    'frontend/src/app/newProject/bess/bessSetup.css',
    'frontend/src/app/newProject/bess/types.ts',
    'static/react/finco-react.js',
    'static/react/finco-react.css',
    'tests/fin_v2_cohorts.py',
    'tests/on_bess01_scope.py',
    'tests/on_bess01_contract_checks.py',
    'tests/on_bess01_browser_checks.py',
    'tests/on_bess01_governance_checks.py',
    'docs/bess_setup/IMPLEMENTATION.md',
))
SUPERSEDED = frozenset((
    'app/v2/react_new_project.py',
    'frontend/src/app/newProject/NewProjectWizard.tsx',
    'frontend/src/app/newProject/types.ts',
    'static/react/finco-react.js',
    'static/react/finco-react.css',
    'tests/fin_v2_cohorts.py',
))


def _git(root, *args):
    return subprocess.check_output(['git', *map(str, args)], cwd=root, stderr=subprocess.DEVNULL)


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
    yield  # finite seal; no mutable verdict survives a read or tamper test


def exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = manifest(root, ref)
        if set(data.get('source_blobs', {})) != OWNED_PATHS or set(data.get('base_blobs', {})) != SUPERSEDED:
            return False
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        old = {line.split('\t')[1]: line.split()[2] for line in _git(root, 'ls-tree', '-r', BASE, '--', *sorted(OWNED_PATHS)).decode().splitlines()}
        if old != data['base_blobs']:
            return False
        for path, pin in data['source_blobs'].items():
            if _blob(_read(root, path, ref)) != pin:
                return False
        allowed = OWNED_PATHS | {MANIFEST}
        changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
        if not changed <= allowed:
            return False
        if ref is None:
            extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
            if not extra <= allowed:
                return False
            if any(not (root / p).is_file() or (root / p).is_symlink() or (root / p).stat().st_mode & 0o111 for p in allowed):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(allowed)).decode().splitlines()
            if len(modes) != len(allowed) or any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | {MANIFEST}


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref)['source_blobs'].get(path) == value


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo, ref) and composite(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    raw = source.encode() if isinstance(source, str) else source
    return path in pins and valid(repo, ref) and (source is None or _blob(raw) == pins[path])


def protected_blobs(repo=None, ref=None):
    return {}  # never admits an engine, revenue, tax or financial policy change

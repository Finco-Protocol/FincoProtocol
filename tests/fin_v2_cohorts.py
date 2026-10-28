"""Registry of the reviewed FIN-V2 exact-source cohorts.

Every governance guard that recognises a cohort asks this module, so adding or composing cohorts never edits the guards again.
A cohort module offers ``BASE``, ``OWNED_PATHS``, ``manifest``, ``exact_blobs_ok``, ``allowed_path``, ``valid``, ``matches`` and ``protected_blobs``.
The composite is valid only while EVERY registered cohort has its exact blobs and EVERY changed path since the accepted parent is allowed by
at least one registered cohort. An unregistered, missing or altered cohort never widens the scope.
"""
from pathlib import Path
import importlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COHORT_MODULES = ('tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope',
                  'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.fin_v2_wsv2_scope')
# The accepted parent every cohort diff is judged against (main after merged PR #388 and #390).
PARENT = 'f79e251903621c1a5c88501d51d6971960b612d3'


def cohorts():
    loaded = []
    for name in COHORT_MODULES:
        try:
            loaded.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return loaded


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def valid(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    mods = cohorts()
    if not mods:
        return False
    try:
        if not all(m.exact_blobs_ok(root, ref) for m in mods):
            return False
        _git(root, 'merge-base', '--is-ancestor', PARENT, ref or 'HEAD')
        changed = _git(root, 'diff', '--name-only', PARENT, *([ref] if ref else []), '--').decode().splitlines()
        if any(not any(m.allowed_path(p, root, ref) for m in mods) for p in changed):
            return False
        if ref is None:
            owned = set().union(*(set(m.manifest(root, ref).get('source_blobs', {})) for m in mods))
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '--',
                             'app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py').decode().splitlines()
            if any(p not in owned for p in untracked):
                return False
        return True
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def matches(path, source=None, *, repo=None, ref=None):
    if not valid(repo, ref):
        return False
    return any(_owned_match(m, path, source, repo, ref) for m in cohorts())


def _owned_match(module, path, source, repo, ref):
    pins = module.manifest(repo, ref).get('source_blobs', {})
    if path not in pins:
        # A cohort that declares a closed ``PRESENTATION`` pattern (RC-UX) owns those paths at path level only; a byte string must still be a pin.
        pattern = getattr(module, 'PRESENTATION', None)
        return source is None and pattern is not None and bool(pattern.match(path))
    if source is None:
        return True
    raw = source.encode() if isinstance(source, str) else source
    return module._blob(raw) == pins[path]


def protected_blobs(repo=None, ref=None):
    if not valid(repo, ref):
        return {}
    merged = {}
    for m in cohorts():
        for p, b in m.manifest(repo, ref).get('source_blobs', {}).items():
            if p.startswith(('financial_engine/', 'finco_core/', 'domain/')):
                merged[p] = b
    return merged

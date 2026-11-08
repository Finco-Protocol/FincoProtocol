"""UX-PR2a closed successor over merged UX-PR1 (main 713c0daf). Read-only inline CAPEX month / OPEX year timelines; no engine, writer, flag or CI change.

Low level and one-way: this module reads git objects and its own literal manifest only. It never imports the UX-PR1 cohort or the registry (the composite
``valid`` imports the registry lazily and is never called from a low level check), so the dependency graph is acyclic:
    ux_pr1_scope --(one-way hook: supersedes / allowed_path)--> ux_pr2a_scope --> git objects + own manifest.
``BASE`` is the merged PR1 main, authenticated by commit, tree AND the recorded blob of every superseded path; PR1's own manifest, base and pins are not
edited: PR1 follows PR2a only through ``supersedes(path, blob)`` for a literal path at exactly PR2a's pin while this cohort is exact. Coordinated current
pins of sibling manifests may move only for paths this cohort owns, and only to these same bytes.
"""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import hashlib
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
BASE = '713c0daf434dd79616f5a07451de6accddde93e0'
BASE_TREE = '11e796b14b55c9039bd17ccc00f16c3929196357'
MANIFEST = 'docs/react_migration/ux_pr2a/UX_PR2A_EXACT_SOURCE.json'
SCHEMA = 'UX_PR2A_TIMELINE_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset((
    'docs/react_migration/ux_pr2a/IMPLEMENTATION.md',
    'frontend/src/app/capex/savedTimeline.ts',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/projection/OpexLineYears.tsx',
    'frontend/src/app/projection/opexLineTimeline.ts',
    'frontend/src/styles/ux-pr1-workbench.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/model_react_ux_pr2a_acceptance.py',
    'tests/test_post413_o1_scope.py',
    'tests/test_u2_scope.py',
    'tests/test_ux_pr2a_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_scope.py',
    'tests/ux_pr2a_browser_role.py',
    'tests/ux_pr2a_scope.py',
))
# Owned paths that exist at BASE (merged PR1): their BASE blobs are recorded in the manifest and re-verified against git.
SUPERSEDED = frozenset((
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/projection/OpexLineYears.tsx',
    'frontend/src/styles/ux-pr1-workbench.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_scope.py',
    'tests/test_post413_o1_scope.py',
    'tests/test_u2_scope.py',
))
# Sibling manifests whose pins of OWNED paths may move to these same bytes (nothing else in them may change).
INTEGRATION_MANIFESTS = frozenset((
 'docs/ci_v4/SOURCE_SUCCESSOR.json',
 'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json',
 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json',
 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json',
 'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json',
 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json',
 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json',
))
FORBIDDEN_PREFIXES = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'migrations/', 'schemas/')
FORBIDDEN_PATHS = frozenset(('main_web.py', 'frontend/src/app/editing/pendingEdits.ts', 'frontend/src/app/editing/saveAll.ts', 'frontend/src/app/workflow/PPAEditorView.tsx'))
def _pr2b():
    try:
        from tests import ux_pr2b_scope as S
        return S
    except ImportError:
        return None

def _pr2c():
    try:
        from tests import ux_pr2c_scope as S
        return S
    except ImportError:
        return None

def effective_pins(repo=None, ref=None):
    """Only authenticated exact successor pins supersede the immutable historical pins."""
    pins = dict(manifest(repo, ref).get('source_blobs', {}))
    S = _pr2b()
    if S is not None and S.exact_blobs_ok(repo, ref):
        pins.update({p: b for p, b in S.manifest(repo, ref)['source_blobs'].items() if p in S.SUPERSEDED})
    S4 = _pr2c()
    if S4 is not None and S4.exact_blobs_ok(repo, ref):
        pins.update({p: b for p, b in S4.manifest(repo, ref)['source_blobs'].items() if p in S4.SUPERSEDED})
    S5 = _pr3b1()
    if S5 is not None and S5.exact_blobs_ok(repo, ref):
        pins.update({p: b for p, b in S5.manifest(repo, ref)['source_blobs'].items() if p in S5.SUPERSEDED})
    return pins

def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)
# Only immutable BASE git objects are cached. Working bytes, ref ancestry, modes,
# diffs and registration are read afresh in every outer validation call.
_OBJECT_FACTS = {}
def _base_fact(root, *args):
    key = (str(root),) + args
    if key not in _OBJECT_FACTS:
        _OBJECT_FACTS[key] = _git(root, *args)
    return _OBJECT_FACTS[key]
def _read(root, path, ref):
    return (Path(root)/path).read_bytes() if ref is None else _git(root, 'show', ref+':'+path)
def _blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def manifest(repo=None, ref=None):
    try:
        d = json.loads(_read(Path(repo) if repo is not None else ROOT, MANIFEST, ref))
        return d if (set(d) == {'base', 'base_tree', 'schema_version', 'source_blobs', 'base_blobs'} and d.get('schema_version') == SCHEMA and d.get('base') == BASE and d.get('base_tree') == BASE_TREE) else {}
    except (OSError, ValueError, AttributeError, subprocess.CalledProcessError):
        return {}
# CI generates untracked evidence before F01/static attribution. Follow the same
# finite artifact types as U2; this never admits a changed tracked file or source.
_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')
def _ci_evidence_only(root, path):
    f = root/path
    return (path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)
            and f.is_file() and not f.is_symlink() and not f.stat().st_mode & 0o111)
_SCOPE=[]
@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    with ExitStack() as successors:
        S=_pr2b()
        if S is not None:
            successors.enter_context(S.scoped())
        _SCOPE.append({})
        try:
            yield
        finally:
            _SCOPE.pop()
# While an enclosing OLDER cohort module is inside its one-outer-call scope nothing is written or mutated (that scope's contract), so this verdict
# shares THAT scope's memo exactly as ``tests/u1_scope.py`` and ``tests/post413_r1_scope.py`` already do: it lives only as long as the enclosing
# outer call, is dropped with it and never outlives or crosses an outer call. Outside every scope nothing is shared.
_ENCLOSING_SCOPE_MODULES = ('tests.wf06b_scope', 'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope')
def _enclosing_call_memo():
    import sys
    for name in _ENCLOSING_SCOPE_MODULES:
        scope = getattr(sys.modules.get(name), '_SCOPE', None)
        if scope:
            return scope[-1]
    return None
def exact_blobs_ok(repo=None, ref=None):
    key=(str(repo if repo is not None else ROOT),ref)
    if not _SCOPE:
        memo=_enclosing_call_memo()
        if memo is not None:
            shared=('tests.ux_pr2a_scope.exact_blobs_ok',)+key
            if shared not in memo:
                with scoped():
                    memo[shared]=exact_blobs_ok(repo,ref)
            return memo[shared]
        with scoped():
            return exact_blobs_ok(repo,ref)
    if key not in _SCOPE[-1]:
        _SCOPE[-1][key]=_exact_blobs_ok(repo,ref)
    return _SCOPE[-1][key]
def _exact_blobs_ok(repo=None, ref=None):
    root=Path(repo) if repo is not None else ROOT
    try:
        S3=_pr2b()
        ok3=S3 is not None and S3.exact_blobs_ok(root,ref)
        pins3=S3.manifest(root,ref).get('source_blobs',{}) if ok3 else {}
        # PR2c composes into the same bounded admission: a sibling-manifest pin of a path the
        # exact ux_pr2c cohort supersedes may move to exactly that cohort's pin (its own
        # sibling-leg check proved the move), exactly as ux_pr2b's pins are admitted.
        S4=_pr2c()
        ok4=S4 is not None and S4.exact_blobs_ok(root,ref)
        pins4=S4.manifest(root,ref).get('source_blobs',{}) if ok4 else {}
        def pin_ok3(p,blob):
            if ok3 and p in S3.SUPERSEDED and pins3.get(p)==blob:
                return True
            return ok4 and p in S4.SUPERSEDED and pins4.get(p)==blob
        owns3=lambda p: ok3 and (S3.allowed_path(p,root,ref) or _pr2c_owns(p,root,ref))
        d=manifest(root,ref)
        pins=d.get('source_blobs',{})
        if set(pins)!=OWNED_PATHS or set(d.get('base_blobs',{}))!=SUPERSEDED:
            return False
        permitted=OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}
        if any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '*' in p or '..' in p.split('/') or p.startswith('/') for p in permitted):
            return False
        _git(root,'merge-base','--is-ancestor',BASE,ref or 'HEAD')
        if _base_fact(root,'rev-parse',BASE+'^{tree}').decode().strip()!=BASE_TREE:
            return False
        baseline = {}
        for line in _base_fact(root,'ls-tree','-r',BASE,'--',*sorted(OWNED_PATHS)).decode().splitlines():
            meta, path = line.split('\t',1)
            baseline[path] = meta.split()[2]
        if baseline != d['base_blobs']:
            return False
        for p,sha in pins.items():
            if _blob(_read(root,p,ref))!=sha and not pin_ok3(p,_blob(_read(root,p,ref))) and not _pr3b1_pin(p,_blob(_read(root,p,ref)),root,ref):
                return False
        for path in INTEGRATION_MANIFESTS:
            before=json.loads(_base_fact(root,'show',BASE+':'+path)); now=json.loads(_read(root,path,ref))
            if set(now)!=set(before) or any(now[k]!=before[k] for k in before if k!='source_blobs'):
                return False
            old,new=before['source_blobs'],now['source_blobs']
            if set(old)!=set(new):
                return False
            if any(not (p in pins and new[p]==pins[p]) and not pin_ok3(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref) for p in old if new[p]!=old[p]):
                return False
        changed=_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines()
        if any(p not in permitted and not owns3(p) and not _pr3b1_owns(p,root,ref) for p in changed):
            return False
        if ref is None:
            untracked = set(_git(root,'ls-files','--others','--exclude-standard').decode().splitlines())-permitted
            if any(not _ci_evidence_only(root,p) and not owns3(p) and not _pr3b1_owns(p,root,ref) for p in untracked):
                return False
            for p in permitted:
                f=root/p
                if not f.is_file() or f.is_symlink() or f.stat().st_mode & 0o111:
                    return False
        else:
            modes=_git(root,'ls-tree','-r',ref,'--',*sorted(permitted)).decode().splitlines()
            if len(modes)!=len(permitted) or any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False
def _pr2c_owns(path,root,ref):
    """Bounded UX-PR2c tip admission for THIS cohort's own whole-tree closure: the path is one of the exact UX-PR2c cohort's literal paths while that
    cohort is exact.  Never a widening of PR2a's own public ``allowed_path``."""
    try:
        from tests import ux_pr2c_scope as S
    except ImportError:
        return False
    return S.exact_blobs_ok(root,ref) and S.allowed_path(path,root,ref)


def successor_owns(path,root,ref):
    """Tip-aware closure admission for the DIRECT PREDECESSOR's whole-tree closure (UX-PR1): a changed path since the PR1 BASE is admitted only inside
    the literal path sets of the exact direct successor (PR2b) or the exact tip (PR2c) — never as a widening of PR2a's own public ``allowed_path``."""
    S=_pr2b()
    return S is not None and S.exact_blobs_ok(root,ref) and (S.allowed_path(path,root,ref) or _pr2c_owns(path,root,ref))


def allowed_path(path,repo=None,ref=None):
    """Literal scope containment (Correction E): PR2a recognises ONLY its own literal authorized paths.  Newer successors are independently registered
    and authorize their own paths; delegating ``allowed_path`` to a descendant converted this narrow historical contract into transitive ownership."""
    return path in OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}
def base_blob(path,repo=None,ref=None):
    return manifest(repo,ref).get('base_blobs',{}).get(path)
def supersedes(path,value,repo=None,ref=None):
    S=_pr2b()
    literal=path in SUPERSEDED or (S is not None and path in S.SUPERSEDED)
    return literal and exact_blobs_ok(repo,ref) and (effective_pins(repo,ref).get(path)==value
        or (S is not None and S.supersedes(path,value,repo,ref)))
def valid(repo=None,ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo,ref) and composite_valid(repo,ref)
def matches(path,source=None,*,repo=None,ref=None):
    pins=manifest(repo,ref).get('source_blobs',{})
    raw=source.encode() if isinstance(source,str) else source
    return path in pins and valid(repo,ref) and (source is None or _blob(raw)==pins[path])
def protected_blobs(repo=None,ref=None):
    return {}


def _pr3b1():
    try:
        from tests import ux_pr3b1_scope as S
        return S
    except ImportError:
        return None


def _pr3b1_pin(path, blob, repo=None, ref=None):
    S = _pr3b1()
    return S is not None and S.supersedes(path, blob, repo, ref)


def _pr3b1_owns(path, repo=None, ref=None):
    S = _pr3b1()
    return S is not None and S.allowed_path(path, repo, ref) and S.exact_blobs_ok(repo, ref)

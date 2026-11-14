"""UX-PR1 closed presentation successor over merged #423. No engine, writer, flag or CI change.

Low-level checks read git and this literal manifest only; older cohorts can follow exact
reviewed UI bytes without importing this cohort back into its own validation. Historical
manifest ancestry/maps stay unchanged. Coordinated current pins must match these same bytes.
"""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import hashlib
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
BASE = '32c7bd6b66086db7b19ec576509cb873a6d36441'
BASE_TREE = '77c195d4d2fe43fae63cbccaf217b6f2f1a7bb54'
MANIFEST = 'docs/react_migration/ux_pr1/UX_PR1_EXACT_SOURCE.json'
SCHEMA = 'UX_PR1_PRESENTATION_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset((
    'docs/react_migration/ux_pr1/IMPLEMENTATION.md',
    'frontend/src/app/CanonicalInputGrid.tsx',
    'frontend/src/app/CostWorkbench.tsx',
    'frontend/src/app/InputsCostCards.tsx',
    'frontend/src/app/InputsOverview.tsx',
    'frontend/src/app/WorkspaceNav.tsx',
    'frontend/src/app/WorkspaceSidebar.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/__tests__/uxPr1.test.mjs',
    'frontend/src/app/__tests__/wf06a.test.mjs',
    'frontend/src/app/costAmounts.ts',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/workflow/WorkflowBar.tsx',
    'frontend/src/app/workspaceNavigation.ts',
    'frontend/src/finco/_shared/FincoShell.tsx',
    'frontend/src/styles/ux-pr1-workbench.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/test_workflow_c_browser_v1.py',
    'tests/test_project_lifecycle_browser.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/model_mutation_cookie_policy_acceptance.py',
    'tests/model_react_mvp_acceptance.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_u1_helpers.py',
    'tests/model_react_ux_pr1_acceptance.py',
    'tests/model_react_wf06a_acceptance.py',
    'tests/model_react_wf06b_acceptance.py',
    'tests/model_react_wf1_browser_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/model_react_wf2_lifecycle_acceptance.py',
    'tests/test_post413_o1_scope.py',
    'tests/test_u2_scope.py',
    'tests/test_ux_pr1_presentation.py',
    'tests/test_ux_pr1_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_browser_role.py',
    'tests/ux_pr1_scope.py',
    'tests/wf06b_scope.py',
))
SUPERSEDED = frozenset((
    'frontend/src/app/CanonicalInputGrid.tsx',
    'frontend/src/app/CostWorkbench.tsx',
    'frontend/src/app/InputsCostCards.tsx',
    'frontend/src/app/InputsOverview.tsx',
    'frontend/src/app/WorkspaceNav.tsx',
    'frontend/src/app/WorkspaceSidebar.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/__tests__/wf06a.test.mjs',
    'frontend/src/app/costAmounts.ts',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/workflow/WorkflowBar.tsx',
    'frontend/src/app/workspaceNavigation.ts',
    'frontend/src/finco/_shared/FincoShell.tsx',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/test_workflow_c_browser_v1.py',
    'tests/test_project_lifecycle_browser.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/model_mutation_cookie_policy_acceptance.py',
    'tests/model_react_mvp_acceptance.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_u1_helpers.py',
    'tests/model_react_wf06a_acceptance.py',
    'tests/model_react_wf06b_acceptance.py',
    'tests/model_react_wf1_browser_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/model_react_wf2_lifecycle_acceptance.py',
    'tests/test_post413_o1_scope.py',
    'tests/test_u2_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/wf06b_scope.py',
))
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
def _pr2a():
    """One-way delegation to the low level UX-PR2a successor (git objects + its own manifest only; it never imports this module)."""
    try:
        from tests import ux_pr2a_scope as S
    except ImportError:
        return None
    return S

def _pr2a_pin_ok(root, path, blob, ref):
    """A PR1 pin may be superseded ONLY for a literal path of the PR2a cohort at exactly its pin, while that cohort is itself exact."""
    S = _pr2a()
    return S is not None and S.supersedes(path, blob, root, ref)

def _pr2a_owns(root, path, ref):
    S = _pr2a()
    return S is not None and S.allowed_path(path, root, ref) and S.exact_blobs_ok(root, ref)

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
        return d if (d.get('schema_version') == SCHEMA and d.get('base') == BASE and d.get('base_tree') == BASE_TREE) else {}
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
        S=_pr2a()
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
            shared=('tests.ux_pr1_scope.exact_blobs_ok',)+key
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
        # ONE evaluation of the PR2a successor per call (its exact proof is not repeated per path).
        S2=_pr2a()
        ok2=S2 is not None and S2.exact_blobs_ok(root,ref)
        pins2=S2.effective_pins(root,ref) if ok2 else {}
        pin_ok2=lambda p,blob: ok2 and pins2.get(p)==blob
        owns2=lambda p: ok2 and (S2.allowed_path(p,root,ref) or S2.successor_owns(p,root,ref))
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
            if _blob(_read(root,p,ref))!=sha and not pin_ok2(p,_blob(_read(root,p,ref))) and not _pr3b1_pin(p,_blob(_read(root,p,ref)),root,ref):
                return False
        for path in INTEGRATION_MANIFESTS:
            before=json.loads(_base_fact(root,'show',BASE+':'+path)); now=json.loads(_read(root,path,ref))
            if set(now)!=set(before) or any(now[k]!=before[k] for k in before if k!='source_blobs'):
                return False
            old,new=before['source_blobs'],now['source_blobs']
            if set(old)!=set(new):
                return False
            if any(not (p in pins and new[p]==pins[p]) and not pin_ok2(p,new[p]) and not _pr3b1_pin(p,new[p],root,ref) for p in old if new[p]!=old[p]):
                return False
        changed=_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines()
        if any(p not in permitted and not owns2(p) and not _pr3b1_owns(p,root,ref) for p in changed):
            return False
        if ref is None:
            untracked = set(_git(root,'ls-files','--others','--exclude-standard').decode().splitlines())-permitted
            if any(not _ci_evidence_only(root,p) and not owns2(p) and not _pr3b1_owns(p,root,ref) for p in untracked):
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
def allowed_path(path,repo=None,ref=None):
    return path in OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}
def base_blob(path,repo=None,ref=None):
    return manifest(repo,ref).get('base_blobs',{}).get(path)
def supersedes(path,value,repo=None,ref=None):
    S=_pr2a()
    if path not in SUPERSEDED or not exact_blobs_ok(repo,ref):
        return False
    from tests import ci_v4_shard2_fix_scope as S2
    if path in S2.SUPERSEDED:       # CI V4 shard-2 fix: the finite signed successor chain (C06 forwards to it) follows this pin
        from tests import c06_cost_workspace_scope as C06
        if C06.signature_ok(repo,ref) and C06.supersedes(path,value,repo,ref):
            return True
    pins=S.effective_pins(repo,ref) if S is not None and S.exact_blobs_ok(repo,ref) else {}
    return pins.get(path,manifest(repo,ref).get('source_blobs',{}).get(path))==value
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

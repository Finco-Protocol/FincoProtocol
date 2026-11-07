"""Closed PR3b-1 read-only Financing mount and bounded historical-test successor.

Literal ownership, exact source/modes/base tree/ancestry and sibling-pin moves only.
Low-level checks never evaluate predecessors/composite; registry membership is a
read-only check. One verdict per outer read-only scope, dropped after that call.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = 'd295922bfd4e39f769a3e0ed132f6a009e86cdd9'
BASE_TREE = 'af667f3bed5550c2578694038f46724a7470c54d'
MANIFEST = 'docs/react_migration/ux_pr3b1/UX_PR3B1_EXACT_SOURCE.json'
SCHEMA = 'UX_PR3B1_READ_LAYER_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset((
    'docs/react_migration/ux_pr3b1/IMPLEMENTATION.md',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/financing/FinancingStudio.tsx',
    'frontend/src/app/financing/pr3b1/FinancingOverview.tsx',
    'frontend/src/app/financing/pr3b1/FinancingReadLayer.tsx',
    'frontend/src/app/financing/pr3b1/INTEGRATION.md',
    'frontend/src/app/financing/pr3b1/__tests__/browserHarness.mjs',
    'frontend/src/app/financing/pr3b1/__tests__/readLayer.test.mjs',
    'frontend/src/app/financing/pr3b1/__tests__/synthetic.mjs',
    'frontend/src/app/financing/pr3b1/coverageModel.ts',
    'frontend/src/app/financing/pr3b1/financingOverview.css',
    'frontend/src/app/financing/pr3b1/readEvidence.ts',
    'frontend/src/app/financing/pr3b1/runEvidence.ts',
    'frontend/src/app/financing/pr3b1/sourcesUsesModel.ts',
    'frontend/src/app/financing/pr3b1/termSheetModel.ts',
    'frontend/src/app/financing/pr3b1/types.ts',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_pr3b1_acceptance.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/model_react_rcm_investors_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_wf04_debt_metrics_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_rcux_governance.py',
    'tests/test_u2_scope.py',
    'tests/test_ux_pr3b1_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_scope.py',
    'tests/ux_pr2a_scope.py',
    'tests/ux_pr2b_scope.py',
    'tests/ux_pr2c_scope.py',
    'tests/ux_pr3b1_browser_role.py',
    'tests/ux_pr3b1_scope.py',
))
SUPERSEDED = frozenset((
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/financing/FinancingStudio.tsx',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/model_react_rcm_investors_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_wf04_debt_metrics_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_rcux_governance.py',
    'tests/test_u2_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_scope.py',
    'tests/ux_pr2a_scope.py',
    'tests/ux_pr2b_scope.py',
    'tests/ux_pr2c_scope.py',
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

def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (Path(root)/path).read_bytes() if ref is None else _git(root, 'show', ref+':'+path)


def _blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def manifest(repo=None, ref=None):
    try:
        d=json.loads(_read(Path(repo) if repo is not None else ROOT, MANIFEST, ref))
        return d if (set(d)=={'schema_version','base','base_tree','source_blobs','base_blobs'}
            and d['schema_version']==SCHEMA and d['base']==BASE and d['base_tree']==BASE_TREE) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


_SCOPE=[]
_IMMUTABLE={}
@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try: yield
    finally: _SCOPE.pop()


def _base_fact(root, *args):
    key=(str(root),)+args
    if key not in _IMMUTABLE: _IMMUTABLE[key]=_git(root,*args)
    return _IMMUTABLE[key]


def exact_blobs_ok(repo=None, ref=None):
    key=(str(repo if repo is not None else ROOT),ref)
    if not _SCOPE:
        # Same existing one-outer-call contract as PR2c: no working verdict survives
        # a read-only enumeration. No per-path whole-tree scan, no process cache.
        for name in ('tests.ux_pr2c_scope','tests.ux_pr2b_scope','tests.ux_pr2a_scope','tests.ux_pr1_scope','tests.u1_scope','tests.wf06b_scope','tests.wf03_lifecycle_scope','tests.fin_v2_wf06a_scope','tests.fin_v2_integration_409_scope'):
            outer=getattr(sys.modules.get(name),'_SCOPE',None)
            if outer:
                memo=outer[-1];shared=('tests.ux_pr3b1_scope.exact',)+key
                if shared not in memo:
                    with scoped(): memo[shared]=exact_blobs_ok(repo,ref)
                return memo[shared]
        with scoped(): return exact_blobs_ok(repo,ref)
    if key not in _SCOPE[-1]: _SCOPE[-1][key]=_exact(repo,ref)
    return _SCOPE[-1][key]


def _exact(repo=None, ref=None):
    from tests.fin_v2_cohorts import COHORT_MODULES
    if __name__ not in COHORT_MODULES: return False
    root=Path(repo) if repo is not None else ROOT
    try:
        d=manifest(root,ref);pins=d.get('source_blobs',{})
        if set(pins)!=OWNED_PATHS or set(d.get('base_blobs',{}))!=SUPERSEDED: return False
        _git(root,'merge-base','--is-ancestor',BASE,ref or 'HEAD')
        if _base_fact(root,'rev-parse',BASE+'^{tree}').decode().strip()!=BASE_TREE: return False
        baseline={line.split('\t',1)[1]:line.split()[2] for line in _base_fact(root,'ls-tree','-r',BASE,'--',*sorted(OWNED_PATHS)).decode().splitlines()}
        if baseline!=d['base_blobs']: return False
        for p,b in pins.items():
            if _blob(_read(root,p,ref))!=b: return False
        for p in INTEGRATION_MANIFESTS:
            before=json.loads(_base_fact(root,'show',BASE+':'+p));now=json.loads(_read(root,p,ref))
            if set(now)!=set(before) or any(now[k]!=before[k] for k in before if k!='source_blobs'): return False
            a,b=before['source_blobs'],now['source_blobs']
            if set(a)!=set(b) or any(b[k]!=a[k] and (k not in SUPERSEDED or b[k]!=pins[k]) for k in a): return False
        permitted=OWNED_PATHS|INTEGRATION_MANIFESTS|{MANIFEST}
        changed=set(_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines())
        if changed-permitted: return False
        if ref is None:
            for p in permitted:
                f=root/p
                if not f.is_file() or f.is_symlink() or f.stat().st_mode&0o111: return False
            extra=set(_git(root,'ls-files','--others','--exclude-standard').decode().splitlines())-permitted
            if any(not (p.startswith('evidence/') and p.endswith(('.json','.xml','.png','.txt','.csv','.html','.zip')) and (root/p).is_file() and not (root/p).is_symlink() and not (root/p).stat().st_mode&0o111) for p in extra): return False
        else:
            modes=_git(root,'ls-tree','-r',ref,'--',*sorted(permitted)).decode().splitlines()
            if len(modes)!=len(permitted) or any(not l.startswith('100644 ') for l in modes): return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS|INTEGRATION_MANIFESTS|{MANIFEST}


def base_blob(path, repo=None, ref=None):
    return manifest(repo,ref).get('base_blobs',{}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and exact_blobs_ok(repo,ref) and manifest(repo,ref).get('source_blobs',{}).get(path)==value


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo,ref) and composite(repo,ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins=manifest(repo,ref).get('source_blobs',{});raw=source.encode() if isinstance(source,str) else source
    return path in pins and valid(repo,ref) and (source is None or _blob(raw)==pins[path])


def protected_blobs(repo=None, ref=None):
    return {}

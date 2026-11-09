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
    'tests/finval_f01_browser_acceptance.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_pr3b1_acceptance.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/model_react_rcm_investors_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_wf04_debt_metrics_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_rcux_governance.py',
    'tests/test_u2_scope.py',
    'tests/test_ux_pr1_scope.py',
    'tests/test_ux_pr3b1_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_scope.py',
    'tests/ux_pr2a_scope.py',
    'tests/ux_pr2b_scope.py',
    'tests/ux_pr2c_scope.py',
    'tests/ux_pr3b1_browser_role.py',
    'tests/ux_pr3b1_scope.py',
    'tests/test_post413_o1_scope.py',
))
SUPERSEDED = frozenset((
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/financing/FinancingStudio.tsx',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/finval_f01_browser_acceptance.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/model_react_rcm_investors_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_wf04_debt_metrics_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_rcux_governance.py',
    'tests/test_u2_scope.py',
    'tests/test_ux_pr1_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr1_scope.py',
    'tests/ux_pr2a_scope.py',
    'tests/ux_pr2b_scope.py',
    'tests/ux_pr2c_scope.py',
    'tests/test_post413_o1_scope.py',
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
    from contextlib import ExitStack
    with ExitStack() as successors:
        S=_successor()
        if S is not None: successors.enter_context(S.scoped())
        _SCOPE.append({})
        try: yield
        finally: _SCOPE.pop()


def _base_fact(root, *args):
    key=(str(root),)+args
    if key not in _IMMUTABLE: _IMMUTABLE[key]=_git(root,*args)
    return _IMMUTABLE[key]


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo, ref, True)


def signature_ok(repo=None, ref=None):
    """Source/base/mode authority only, for the predecessor's literal CI_PATHS.

    Does not admit any path or satisfy global governance; full exactness still
    checks sibling manifests and the complete changed/untracked closure. The
    independent signature does not read foreign manifests. Mutable results never escape
    the enclosing read-only call, and signature/full memo entries are distinct.
    """
    return _verdict(repo, ref, False)


def _verdict(repo, ref, closure):
    key=(str(repo if repo is not None else ROOT),ref,closure)
    if not _SCOPE:
        for name in ('tests.ux_pr2c_scope','tests.ux_pr2b_scope','tests.ux_pr2a_scope','tests.ux_pr1_scope','tests.u1_scope','tests.wf06b_scope','tests.wf03_lifecycle_scope','tests.fin_v2_wf06a_scope','tests.fin_v2_integration_409_scope'):
            outer=getattr(sys.modules.get(name),'_SCOPE',None)
            if outer:
                memo=outer[-1];shared=('tests.ux_pr3b1_scope.verdict',)+key
                if shared not in memo:
                    with scoped(): memo[shared]=_verdict(repo,ref,closure)
                return memo[shared]
        with scoped(): return _verdict(repo,ref,closure)
    if key not in _SCOPE[-1]: _SCOPE[-1][key]=_exact(repo,ref,closure)
    return _SCOPE[-1][key]


def _exact(repo=None, ref=None, closure=True):
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
        S=_successor()
        next_ok=S is not None and (S.exact_blobs_ok(root,ref) if closure else S.signature_ok(root,ref))
        # Effective pins include the exact terminal successor; historical sets stay unchanged.
        next_pins=S.effective_pins(root,ref,signature=not closure) if next_ok else {}
        next_owns=lambda p: next_ok and S.allowed_path(p,root,ref)
        for p,b in pins.items():
            if _blob(_read(root,p,ref))!=b and next_pins.get(p)!=_blob(_read(root,p,ref)): return False
        permitted=OWNED_PATHS|{MANIFEST}
        if closure:
            for p in INTEGRATION_MANIFESTS:
                before=json.loads(_base_fact(root,'show',BASE+':'+p));now=json.loads(_read(root,p,ref))
                if set(now)!=set(before) or any(now[k]!=before[k] for k in before if k!='source_blobs'): return False
                a,b=before['source_blobs'],now['source_blobs']
                if set(a)!=set(b) or any(b[k]!=a[k] and (k not in SUPERSEDED or b[k]!=pins[k]) and next_pins.get(k)!=b[k] for k in a): return False
            permitted=permitted|INTEGRATION_MANIFESTS
            changed=set(_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines())
            if any(not next_owns(p) for p in changed-permitted): return False
        if ref is None:
            for p in permitted:
                f=root/p
                if not f.is_file() or f.is_symlink() or f.stat().st_mode&0o111: return False
            extra=set(_git(root,'ls-files','--others','--exclude-standard').decode().splitlines())-permitted
            if closure and any(not next_owns(p) and not (p.startswith('evidence/') and p.endswith(('.json','.xml','.png','.txt','.csv','.html','.zip')) and (root/p).is_file() and not (root/p).is_symlink() and not (root/p).stat().st_mode&0o111) for p in extra): return False
        else:
            modes=_git(root,'ls-tree','-r',ref,'--',*sorted(permitted)).decode().splitlines()
            if len(modes)!=len(permitted) or any(not l.startswith('100644 ') for l in modes): return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    S=_successor()
    return path in OWNED_PATHS|INTEGRATION_MANIFESTS|{MANIFEST} or (S is not None and S.allowed_path(path,repo,ref) and S.exact_blobs_ok(repo,ref))


def base_blob(path, repo=None, ref=None):
    return manifest(repo,ref).get('base_blobs',{}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and exact_blobs_ok(repo,ref) and effective_pins(repo,ref).get(path)==value


def _successor():
    try:
        from tests import ux_pr3b2_scope as S
        return S
    except ImportError:
        return None


def effective_pins(repo=None, ref=None, *, signature=False):
    pins=dict(manifest(repo,ref).get('source_blobs',{}))
    S=_successor()
    if S is not None and (S.signature_ok(repo,ref) if signature else S.exact_blobs_ok(repo,ref)):
        pins.update(S.effective_pins(repo,ref,signature=signature))
    return pins


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo,ref) and composite(repo,ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins=manifest(repo,ref).get('source_blobs',{});raw=source.encode() if isinstance(source,str) else source
    return path in pins and valid(repo,ref) and (source is None or _blob(raw)==pins[path])


def protected_blobs(repo=None, ref=None):
    return {}

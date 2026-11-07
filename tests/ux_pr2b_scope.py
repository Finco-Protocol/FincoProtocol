"""UX-PR2b low-level closed successor: verified unmerged PR2a parent, exact blobs/modes/ancestry. No predecessor or registry evaluation below valid()."""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import hashlib
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
BASE = '4d661e5a6e06e3a41a31b8c1ddd1896dd835e760'
BASE_TREE = 'e6453b1828c39a7698c5cddbcfa0f9aab9a631a9'
MANIFEST = 'docs/react_migration/ux_pr2b/UX_PR2B_EXACT_SOURCE.json'
SCHEMA = 'UX_PR2B_PROFILE_DRAFT_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset(('docs/react_migration/ux_pr2b/IMPLEMENTATION.md', 'frontend/src/app/WorkspaceView.tsx', 'frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/app/capex/ProfileDraftProvider.tsx', 'frontend/src/app/capex/ProfileRowEditor.tsx', 'frontend/src/app/capex/__tests__/profileDraft.test.mjs', 'frontend/src/app/capex/profileDraft.ts', 'frontend/src/app/editing/CostLinesGridView.tsx', 'frontend/src/styles/ux-pr1-workbench.css', 'static/react/finco-react.css', 'static/react/finco-react.js', 'tests/ci_v4_scope.py', 'tests/fin_v2_cohorts.py', 'tests/model_react_ux_pr2b_acceptance.py', 'tests/test_ci_merge_event_identity.py', 'tests/test_model_workspace_consolidation_browser.py', 'tests/test_post413_o1_scope.py', 'tests/test_u2_scope.py', 'tests/test_ux_pr1_scope.py', 'tests/test_ux_pr2a_scope.py', 'tests/test_ux_pr2b_scope.py', 'tests/u1_scope.py', 'tests/u2_scope.py', 'tests/ux_pr1_scope.py', 'tests/ux_pr2a_scope.py', 'tests/ux_pr2b_browser_role.py', 'tests/ux_pr2b_scope.py', 'tools/ci_merge_tree_guard.py'))
SUPERSEDED = frozenset(('frontend/src/app/WorkspaceView.tsx', 'frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/app/editing/CostLinesGridView.tsx', 'frontend/src/styles/ux-pr1-workbench.css', 'static/react/finco-react.css', 'static/react/finco-react.js', 'tests/ci_v4_scope.py', 'tests/fin_v2_cohorts.py', 'tests/test_model_workspace_consolidation_browser.py', 'tests/test_post413_o1_scope.py', 'tests/test_u2_scope.py', 'tests/test_ux_pr1_scope.py', 'tests/test_ux_pr2a_scope.py', 'tests/u1_scope.py', 'tests/u2_scope.py', 'tests/ux_pr1_scope.py', 'tests/ux_pr2a_scope.py', 'tools/ci_merge_tree_guard.py'))
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
# Owner-directed Correction B: this one existing CI guard, never a wildcard tools admission.
CI_PATHS = frozenset(('tools/ci_merge_tree_guard.py',))
FORBIDDEN_PREFIXES = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'migrations/', 'schemas/')
FORBIDDEN_PATHS = frozenset(('main_web.py', 'frontend/src/app/editing/pendingEdits.ts', 'frontend/src/app/editing/saveAll.ts', 'frontend/src/app/workflow/PPAEditorView.tsx'))
def _pr2c():
    try:
        from tests import ux_pr2c_scope as S
        return S
    except ImportError:
        return None


def effective_pins(repo=None, ref=None):
    """Only authenticated exact successor pins supersede the immutable historical pins."""
    pins = dict(manifest(repo, ref).get('source_blobs', {}))
    S = _pr2c()
    if S is not None and S.exact_blobs_ok(repo, ref):
        pins.update({p: b for p, b in S.manifest(repo, ref)['source_blobs'].items() if p in S.SUPERSEDED})
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
        S=_pr2c()
        if S is not None:
            successors.enter_context(S.scoped())
        _SCOPE.append({})
        try:
            yield
        finally:
            _SCOPE.pop()
def exact_blobs_ok(repo=None, ref=None):
    key=(str(repo if repo is not None else ROOT),ref)
    if not _SCOPE:
        with scoped():
            return exact_blobs_ok(repo,ref)
    if key not in _SCOPE[-1]:
        _SCOPE[-1][key]=_exact_blobs_ok(repo,ref)
    return _SCOPE[-1][key]
def ci_authority_ok(repo=None, ref=None):
    """Signature-level authority for the literal CI_PATHS only: same manifest/BASE/ancestry/pin/mode proof as exact_blobs_ok, WITHOUT the whole-tree changed-path closure (that closure stays in exact_blobs_ok and composite_valid, so an unrelated drift is still refused globally)."""
    key=(str(repo if repo is not None else ROOT),ref,'ci-authority')
    if not _SCOPE:
        with scoped():
            return ci_authority_ok(repo,ref)
    if key not in _SCOPE[-1]:
        _SCOPE[-1][key]=_exact_blobs_ok(repo,ref,closure=False)
    return _SCOPE[-1][key]
def _exact_blobs_ok(repo=None, ref=None, closure=True):
    root=Path(repo) if repo is not None else ROOT
    try:
        S4=_pr2c()
        ok4=S4 is not None and S4.exact_blobs_ok(root,ref)
        pins4=S4.manifest(root,ref).get('source_blobs',{}) if ok4 else {}
        pin_ok4=lambda p,blob: ok4 and p in S4.SUPERSEDED and pins4.get(p)==blob
        owns4=lambda p: ok4 and S4.allowed_path(p,root,ref)
        d=manifest(root,ref)
        pins=d.get('source_blobs',{})
        if set(pins)!=OWNED_PATHS or set(d.get('base_blobs',{}))!=SUPERSEDED:
            return False
        permitted=OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}
        if any((p.startswith(FORBIDDEN_PREFIXES) and p not in CI_PATHS) or p in FORBIDDEN_PATHS or '*' in p or '..' in p.split('/') or p.startswith('/') for p in permitted):
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
            if _blob(_read(root,p,ref))!=sha and not pin_ok4(p,_blob(_read(root,p,ref))):
                return False
        for path in (INTEGRATION_MANIFESTS if closure else ()):  # sibling manifests are another cohort's signature; global closure/composite check them
            before=json.loads(_base_fact(root,'show',BASE+':'+path)); now=json.loads(_read(root,path,ref))
            if set(now)!=set(before) or any(now[k]!=before[k] for k in before if k!='source_blobs'):
                return False
            old,new=before['source_blobs'],now['source_blobs']
            if set(old)!=set(new):
                return False
            if any(not (p in pins and new[p]==pins[p]) and not pin_ok4(p,new[p]) for p in old if new[p]!=old[p]):
                return False
        changed=_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines()
        if closure and any(p not in permitted and not owns4(p) for p in changed):
            return False
        if ref is None:
            untracked = set(_git(root,'ls-files','--others','--exclude-standard').decode().splitlines())-permitted
            if closure and any(not _ci_evidence_only(root,p) and not owns4(p) for p in untracked):
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
    """Literal scope containment (Correction E): PR2b recognises ONLY its own literal authorized paths; PR2c is independently registered and
    authorizes its own paths at the composite level."""
    return path in OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}
def base_blob(path,repo=None,ref=None):
    return manifest(repo,ref).get('base_blobs',{}).get(path)
def supersedes(path,value,repo=None,ref=None):
    return path in SUPERSEDED and exact_blobs_ok(repo,ref) and manifest(repo,ref).get('source_blobs',{}).get(path)==value
def valid(repo=None,ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo,ref) and composite_valid(repo,ref)
def matches(path,source=None,*,repo=None,ref=None):
    pins=manifest(repo,ref).get('source_blobs',{})
    raw=source.encode() if isinstance(source,str) else source
    return path in pins and valid(repo,ref) and (source is None or _blob(raw)==pins[path])
def protected_blobs(repo=None,ref=None):
    return {}

def ci_owns(path,repo=None,ref=None):
    return path in CI_PATHS and ci_authority_ok(repo,ref)

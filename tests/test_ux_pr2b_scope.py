"""Literal successor proof and independent tamper controls on actual disposable git worktrees."""
import json
import subprocess
import pytest
from tests import ux_pr2b_scope as B
from tests import ux_pr2a_scope as A
from tests import ux_pr1_scope as P
from tests import fin_v2_cohorts as C


def immutable_check(fn):
    """Share proofs only during this immutable positive check; negative mutations never use this decorator."""
    from functools import wraps
    from contextlib import ExitStack
    @wraps(fn)
    def wrapped(*args,**kwargs):
        with ExitStack() as scopes:
            for m in C.cohorts():
                if callable(getattr(m,'scoped',None)):
                    scopes.enter_context(m.scoped())
            return fn(*args,**kwargs)
    return wrapped


def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.STDOUT).strip()


@pytest.fixture(scope='module')
def tree(tmp_path_factory):
    path=tmp_path_factory.mktemp('pr2b-scope')/'tree'
    git(B.ROOT,'worktree','add','--detach',str(path),'HEAD')
    yield path
    git(B.ROOT,'worktree','remove','--force',str(path))


@pytest.fixture
def wt(tree):
    original=git(tree,'rev-parse','HEAD')
    yield tree
    git(tree,'reset','--hard',original)
    git(tree,'clean','-fdxq')
    # Explicit mode restoration also works with core.filemode=false.
    for p in B.OWNED_PATHS | B.INTEGRATION_MANIFESTS | {B.MANIFEST}:
        (tree/p).chmod(0o644)
    assert git(tree,'rev-parse','HEAD')==original


@immutable_check
def test_exact_root_closed_registration_and_immutable_predecessors():
    assert B.BASE=='4d661e5a6e06e3a41a31b8c1ddd1896dd835e760'
    assert git(B.ROOT,'rev-parse',B.BASE+'^{tree}')==B.BASE_TREE
    assert B.exact_blobs_ok() and B.valid() and A.exact_blobs_ok() and P.exact_blobs_ok()
    assert C.COHORT_MODULES.count(B.__name__)==1 and B.protected_blobs()=={}
    assert all(m.exact_blobs_ok() for m in C.cohorts())
    for manifest in (A.MANIFEST,P.MANIFEST):
        assert git(B.ROOT,'diff',B.BASE,'--',manifest)==''
    source=(B.ROOT/'tests/ux_pr2b_scope.py').read_text().split('def valid(',1)[0]
    import ast
    imports=[n for n in ast.walk(ast.parse(source)) if isinstance(n,(ast.Import,ast.ImportFrom))]
    names=[ast.unparse(n) for n in imports]
    assert not any(any(x in name for x in ('ux_pr1_scope','ux_pr2a_scope','fin_v2_cohorts')) for name in names), names
    assert set(B.manifest()['source_blobs'])==B.OWNED_PATHS
    for p in B.SUPERSEDED:
        pin=B.manifest()['source_blobs'][p]
        assert B.base_blob(p)==git(B.ROOT,'rev-parse',B.BASE+':'+p)
        assert B.supersedes(p,pin) and A.supersedes(p,pin)
        assert not B.supersedes(p,'0'*40)
    for p in ['app/v2/react_capex.py','frontend/src/app/editing/pendingEdits.ts','frontend/src/app/editing/saveAll.ts','.github/workflows/ci_v4_pr.yml','frontend/src/app/capex/Unsigned.tsx']:
        assert not B.allowed_path(p) and not B.matches(p)


@pytest.mark.parametrize('path',sorted(B.OWNED_PATHS))
def test_one_byte_in_every_owned_blob_fails_closed(path,wt):
    with C.call_scope():
        assert B.exact_blobs_ok(wt)
    p=wt/path; old=p.read_bytes(); p.write_bytes(old+b'\n')
    with C.call_scope():
        assert not B.exact_blobs_ok(wt) and not A.exact_blobs_ok(wt) and not C.valid(wt)
    p.write_bytes(old)
    with C.call_scope():
        assert B.exact_blobs_ok(wt)


@pytest.mark.parametrize('case',['blob','missing','extra','base','tree','history','schema','key','foreign','executable','symlink','deregister','evidence-executable','evidence-source','evidence-symlink'])
def test_forgery_modes_unknown_paths_and_untrusted_evidence(case,wt):
    d=B.manifest(wt); manifest=wt/B.MANIFEST
    target=wt/'frontend/src/app/capex/profileDraft.ts'
    if case=='blob': d['source_blobs']['frontend/src/app/capex/profileDraft.ts']='0'*40
    elif case=='missing': d['source_blobs'].pop('frontend/src/app/capex/profileDraft.ts')
    elif case=='extra': d['source_blobs']['financial_engine/unsigned.py']='0'*40
    elif case=='base': d['base']='0'*40
    elif case=='tree': d['base_tree']='0'*40
    elif case=='history': d['base_blobs']['tests/ux_pr2a_scope.py']='0'*40
    elif case=='schema': d['schema_version']='FORGED'
    elif case=='key': d['unexpected']=True
    elif case=='foreign': (wt/'frontend/src/app/Unsigned.tsx').write_text('export {}\n')
    elif case=='executable': target.chmod(0o755)
    elif case=='symlink': target.unlink(); target.symlink_to(wt/'tests/ux_pr2b_scope.py')
    elif case=='deregister':
        p=wt/'tests/fin_v2_cohorts.py'; p.write_text(p.read_text().replace(", 'tests.ux_pr2b_scope'",''))
    elif case.startswith('evidence-'):
        folder=wt/'evidence';folder.mkdir(exist_ok=True)
        f=folder/('unsafe.json' if case=='evidence-executable' else 'unsigned.py'); f.write_text('{}')
        if case=='evidence-executable':f.chmod(0o755)
        if case=='evidence-symlink':f.unlink();f.symlink_to(target)
    manifest.write_text(json.dumps(d,indent=2)+'\n')
    with C.call_scope():
        assert not B.exact_blobs_ok(wt) and not C.valid(wt)


@pytest.mark.parametrize('path',[A.MANIFEST,P.MANIFEST,'tests/ux_pr2a_scope.py','tests/ux_pr1_scope.py'])
def test_altered_predecessor_is_not_authority(path,wt):
    p=wt/path;p.write_bytes(p.read_bytes()+b'\n')
    with C.call_scope():
        assert not B.exact_blobs_ok(wt) or not A.exact_blobs_ok(wt)
        assert not C.valid(wt)


@pytest.mark.parametrize('path',sorted(B.INTEGRATION_MANIFESTS))
def test_sibling_only_current_owned_pins_may_move(path,wt):
    p=wt/path;d=json.loads(p.read_text())
    owned=next(k for k in d['source_blobs'] if k in B.OWNED_PATHS)
    d['source_blobs'][owned]='0'*40;p.write_text(json.dumps(d)+'\n')
    with C.call_scope():
        assert not B.exact_blobs_ok(wt) and not C.valid(wt)


def test_wrong_sha_ref_and_old_source_cannot_bypass_guard(wt):
    path='frontend/src/app/capex/CapexStudio.tsx'
    current=(wt/path).read_bytes()
    historical=subprocess.check_output(['git','show',B.BASE+':'+path],cwd=wt)
    assert current!=historical
    with C.call_scope():
        assert C.matches(path,current,repo=wt) and not C.matches(path,historical,repo=wt)
        assert not C.matches(path,b'forged',repo=wt) and not B.exact_blobs_ok(wt,B.BASE)
        assert not B.exact_blobs_ok(wt,'0'*40)
        assert B.exact_blobs_ok(wt,'HEAD')
    (wt/path).write_bytes(current+b'\n')
    with C.call_scope():
        assert not C.matches(path,current,repo=wt)
        assert C.matches(path,current,repo=wt,ref='HEAD')


def test_allowed_ci_artifact_is_not_source_and_verdict_does_not_survive_call(wt):
    p=wt/'evidence/pr2b.json';p.parent.mkdir(exist_ok=True);p.write_text('{}')
    with C.call_scope():
        assert B.exact_blobs_ok(wt) and C.valid(wt)
    q=wt/'frontend/src/app/capex/profileDraft.ts';raw=q.read_bytes();q.write_bytes(raw+b'\n')
    assert not B.exact_blobs_ok(wt)
    q.write_bytes(raw);assert B.exact_blobs_ok(wt)
    assert B._SCOPE==[] and A._SCOPE==[] and P._SCOPE==[]


def test_committed_executable_is_ref_rejected_and_fixture_restores_original_head(wt):
    path='frontend/src/app/capex/profileDraft.ts'
    git(wt,'update-index','--chmod=+x',path)
    git(wt,'-c','user.name=FINCO synthetic validation','-c','user.email=noreply@users.noreply.github.com','commit','-m','Synthetic invalid mode negative')
    with C.call_scope():
        assert not B.exact_blobs_ok(wt,'HEAD') and not C.valid(wt,'HEAD')


# Correction E: CI authority (signature level) is isolated from the whole-tree closure; the closure and composite stay global fail-closed.
def test_unrelated_cohort_drift_keeps_ci_authority_but_fails_closure_and_composite(wt):
    path=wt/'app/v2/react_opex_lines.py'
    path.write_bytes(path.read_bytes()+b'\n')
    with C.call_scope():
        assert B.ci_authority_ok(wt) and B.ci_owns('tools/ci_merge_tree_guard.py',wt)
        assert not B.exact_blobs_ok(wt) and not C.valid(wt)
        assert not B.ci_owns('tools/ci_v4_unknown.py',wt) and not B.ci_owns('app/v2/react_opex_lines.py',wt)

@pytest.mark.parametrize('path',sorted(B.OWNED_PATHS))
def test_one_byte_in_any_owned_blob_removes_ci_authority(path,wt):
    assert B.ci_authority_ok(wt)
    p=wt/path;p.write_bytes(p.read_bytes()+b'\n')
    assert not B.ci_authority_ok(wt) and not B.ci_owns('tools/ci_merge_tree_guard.py',wt)

@pytest.mark.parametrize('case',['base','tree','guard-pin','mode','extra-pin','base-blob'])
def test_forged_manifest_or_mode_removes_ci_authority(case,wt):
    assert B.ci_authority_ok(wt)
    mp=wt/B.MANIFEST;d=json.loads(mp.read_text())
    if case=='base':d['base']='0'*40
    elif case=='tree':d['base_tree']='0'*40
    elif case=='guard-pin':d['source_blobs']['tools/ci_merge_tree_guard.py']='0'*40
    elif case=='extra-pin':d['source_blobs']['financial_engine/x.py']='0'*40
    elif case=='base-blob':d['base_blobs'][next(iter(d['base_blobs']))]='0'*40
    if case=='mode':(wt/'tools/ci_merge_tree_guard.py').chmod(0o755)
    else:mp.write_text(json.dumps(d,indent=2)+'\n')
    assert not B.ci_authority_ok(wt) and not B.ci_owns('tools/ci_merge_tree_guard.py',wt)

def test_forged_sibling_manifest_keeps_pr2b_ci_authority_but_fails_closure_and_composite(wt):
    mp=wt/'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json';d=json.loads(mp.read_text())
    d['source_blobs']['static/react/finco-react.js']='0'*40
    mp.write_text(json.dumps(d,indent=2)+'\n')
    with C.call_scope():
        assert B.ci_authority_ok(wt) and not B.exact_blobs_ok(wt) and not C.valid(wt)

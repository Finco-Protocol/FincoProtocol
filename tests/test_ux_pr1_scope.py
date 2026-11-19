"""Closed successor positives and tamper controls on actual git worktrees."""
import json
from contextlib import ExitStack
import subprocess
import pytest
from tests import ux_pr1_scope as U
from tests import fin_v2_cohorts as C
from tests import ci_immutable_git_reads as immutable_git

def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.STDOUT)

@pytest.fixture(scope='module')
def tree(tmp_path_factory):
    path=tmp_path_factory.mktemp('ux-pr1-scope')/'tree'
    git(U.ROOT,'worktree','add','--detach',str(path),'HEAD')
    yield path
    git(U.ROOT,'worktree','remove','--force',str(path))

@pytest.fixture
def wt(tree):
    # Cache only immutable Git objects across the mutations of this case.
    with immutable_git.scope():
        yield tree
    git(tree,'reset','--hard','-q')
    git(tree,'clean','-fdxq')

def _effective_pin(path,historical):
    """Follow only registered literal moves, authenticating every base-to-source link."""
    from tests import ux_pr2a_scope as A, ux_pr2b_scope as B, ux_pr2c_scope as D, ux_pr3b1_scope as E, ux_pr3b2_scope as F
    pin=historical
    # PR2c legitimately moved some PR2b sibling pins. Read each predecessor at
    # the next signed BASE so those current-pin moves cannot erase a lineage link.
    chain=((A,B.BASE),(B,D.BASE),(D,E.BASE),(E,F.BASE),(F,None))
    for successor,ref in chain:  # PR1 -> PR2a -> PR2b -> PR2c -> PR3b1
        if path in successor.SUPERSEDED:
            assert successor.__name__ in C.COHORT_MODULES
            assert successor.exact_blobs_ok()
            assert successor.exact_blobs_ok(ref=ref)
            signed=successor.manifest(ref=ref)
            assert signed['base_blobs'][path]==pin
            pin=signed['source_blobs'][path]
    return pin

# The closed PR2a -> PR3b2 chain above describes the original UX handoff.
# Nine paths moved again in the accepted registry after PR3b2. Review the
# current assertion against the accepted Git checkpoint and composite.
PR3B2_MERGE = '785024c752bbd1700d6051cf15115d9980d0b4a1'
RECONCILIATION_HEAD = '411106af20d5b82cf474b8f80f4515740884a6b6'
RECONCILIATION_TREE = 'c523a71441f3f3dc2f6489e2cc9ad9a00a8c633d'
LATER_UX_PR1_PATHS = frozenset((
    'frontend/src/app/CostWorkbench.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/test_u2_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
))


def _later_ux_pr1_pins(root):
    git(root, 'merge-base', '--is-ancestor', PR3B2_MERGE, RECONCILIATION_HEAD)
    git(root, 'merge-base', '--is-ancestor', RECONCILIATION_HEAD, 'HEAD')
    assert git(root, 'rev-parse', RECONCILIATION_HEAD + '^{tree}').strip() == RECONCILIATION_TREE
    paths = set(git(root, 'diff', '--name-only', '--no-renames', PR3B2_MERGE,
                    RECONCILIATION_HEAD, '--', *sorted(U.SUPERSEDED)).splitlines())
    assert paths == LATER_UX_PR1_PATHS
    entries = {}
    for line in git(root, 'ls-tree', '-r', RECONCILIATION_HEAD, '--', *sorted(paths)).splitlines():
        entry, path = line.split('\t', 1)
        mode, kind, blob = entry.split()
        assert (mode, kind) == ('100644', 'blob')
        entries[path] = blob
    assert set(entries) == paths
    return entries


def test_exact_registered_and_historical_maps_immutable():
    # One immutable outer call; drop every memo before the tamper tests mutate bytes.
    with ExitStack() as scopes:
        for m in C.cohorts():
            if hasattr(m, 'scoped'):
                scopes.enter_context(m.scoped())
        assert U.exact_blobs_ok() and U.valid() and U.__name__ in C.COHORT_MODULES
        assert all(m.exact_blobs_ok() for m in C.cohorts())
        d=U.manifest()
        assert set(d['source_blobs'])==U.OWNED_PATHS and set(d['base_blobs'])==U.SUPERSEDED
        later_pins = _later_ux_pr1_pins(U.ROOT)
        for p in U.SUPERSEDED:
            assert d['base_blobs'][p]==git(U.ROOT,'rev-parse',U.BASE+':'+p).strip()
            hist=d['source_blobs'][p]
            eff=_effective_pin(p,hist)
            lineage_ref = PR3B2_MERGE if p in later_pins else None
            assert U.supersedes(p,eff,ref=lineage_ref) and not U.supersedes(p,'0'*40,ref=lineage_ref)
            if eff!=hist:  # a historical pin cannot supersede an accepted later pin
                assert not U.supersedes(p,hist,ref=lineage_ref)
            if p in later_pins:
                assert git(U.ROOT, 'rev-parse', PR3B2_MERGE + ':' + p).strip() == eff
                assert not U.supersedes(p,'0'*40)
            assert git(U.ROOT,'hash-object',p).strip()==later_pins.get(p, eff)
        for p in U.INTEGRATION_MANIFESTS:
            old=json.loads(git(U.ROOT,'show',U.BASE+':'+p));now=json.loads((U.ROOT/p).read_text())
            assert {k:v for k,v in old.items() if k!='source_blobs'}=={k:v for k,v in now.items() if k!='source_blobs'}
        for p in ('app/v2/save_all_commands.py','financial_engine/x.py','.github/workflows/ci_v4_pr.yml','frontend/src/app/editing/pendingEdits.ts'):
            assert not U.allowed_path(p) and not U.matches(p)

@pytest.mark.parametrize('path',sorted(U.OWNED_PATHS))
def test_unsigned_byte_fails_closed(path,wt):
    # Each tree state gets a fresh verdict, even within the same test.
    with C.call_scope():
        assert U.exact_blobs_ok(wt)
    p=wt/path;p.write_bytes(p.read_bytes()+b'\n')
    with C.call_scope():
        assert not U.exact_blobs_ok(wt) and not C.valid(wt)

@pytest.mark.parametrize('change',['missing','extra','base','tree','history','mode','foreign','deregister'])
def test_forgery_foreign_modes_and_registration_fail_closed(change,wt):
    with C.call_scope():
        assert U.exact_blobs_ok(wt)
    path=wt/U.MANIFEST;d=json.loads(path.read_text())
    if change=='missing':d['source_blobs'].pop(next(iter(d['source_blobs'])))
    elif change=='extra':d['source_blobs']['financial_engine/new.py']='0'*40
    elif change=='base':d['base']='0'*40
    elif change=='tree':d['base_tree']='0'*40
    elif change=='history':d['base_blobs'][next(iter(d['base_blobs']))]='0'*40
    elif change=='mode':(wt/'frontend/src/app/WorkspaceView.tsx').chmod(0o755)
    elif change=='foreign':(wt/'frontend/src/app/Unsigned.tsx').write_text('export {}\n')
    elif change=='deregister':
        p=wt/'tests/fin_v2_cohorts.py';p.write_text(p.read_text().replace(", 'tests.ux_pr1_scope'",''))
    path.write_text(json.dumps(d,indent=2)+'\n')
    try:
        with C.call_scope():
            assert not U.exact_blobs_ok(wt) and not C.valid(wt)
    finally:
        # core.filemode=false makes reset preserve a pure executable-mode mutation.
        (wt/'frontend/src/app/WorkspaceView.tsx').chmod(0o644)

@pytest.mark.parametrize('path',sorted(U.INTEGRATION_MANIFESTS))
def test_shared_pin_and_historical_map_tamper_fail_closed(path,wt):
    p=wt/path;d=json.loads(p.read_text());old=p.read_bytes()
    owned=next(k for k in d['source_blobs'] if k in U.OWNED_PATHS)
    d['source_blobs'][owned]='0'*40;p.write_text(json.dumps(d)+'\n')
    with C.call_scope():
        assert not U.exact_blobs_ok(wt) and not C.valid(wt)
    p.write_bytes(old);d=json.loads(old);d['base']='0'*40;p.write_text(json.dumps(d)+'\n')
    with C.call_scope():
        assert not U.exact_blobs_ok(wt)

def test_match_requires_exact_registered_source_and_named_ref(wt):
    from tests import wf06b_scope as W
    p='frontend/src/app/workflow/WorkflowBar.tsx';raw=(wt/p).read_bytes()
    with C.call_scope():
        assert U.matches(p,raw,repo=wt) and W.matches(p,raw,repo=wt)
    (wt/p).write_bytes(raw+b'\n')
    with C.call_scope():
        assert not U.matches(p,raw,repo=wt) and not W.matches(p,raw,repo=wt)
    with C.call_scope():
        assert U.exact_blobs_ok(wt,'HEAD')


def test_ci_artifacts_are_not_source_exemptions(wt):
    # The accepted BESS/ON closure recognizes a finite set of F01 outputs.
    evidence=wt/'evidence'/'browser';evidence.mkdir(parents=True,exist_ok=True)
    artifact=evidence/'solar.json';artifact.write_text('{"synthetic": true}\n')
    with C.call_scope():
        assert U.exact_blobs_ok(wt) and C.valid(wt)
    for suffix in ('.json','.py','.tsx','.mjs'):
        source=evidence/('unsigned'+suffix);source.write_text('unsigned\n')
        with C.call_scope():
            assert not U.exact_blobs_ok(wt) and not C.valid(wt)
        source.unlink()
    artifact.chmod(0o755)
    with C.call_scope():
        assert not U.exact_blobs_ok(wt)
    artifact.chmod(0o644);artifact.unlink();artifact.symlink_to(wt/'tests/ux_pr1_scope.py')
    with C.call_scope():
        assert not U.exact_blobs_ok(wt)

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
ACCEPTED_RUNTIME_HEAD = '305b3553536680e567c608e4ebd3b166ef3d32a7'
REVIEWED_RUNTIME_HEAD = '0d648a03915f2f42959082610281b9617484550e'
REVIEWED_O1_PHASE = (
    '85fa95c569728a7bbcbf57ccad122a4af4febf63',
    'f709969121e26c55332aef262ae50c673a616844',
)
CURRENT_O1_PHASE_BLOB = '9d02e58a2c6c0b6f76c4c6ec8994ec1b02cfff00'
RUNTIME_HANDOFF_PINS = {
    'tests/u1_scope.py': (
        '77707d87ec3aee5d919f9a5f0468983286280ab1',
        'b52633f205db995a14e20bb96acc2a925f3604f1',
        'e1cb7445168cd8e71151e0222f202b50d4a5036a',
    ),
    'tests/fin_v2_cohorts.py': (
        'f39ca2c065216672288e840889fd8e6be9399f50',
        'f39ca2c065216672288e840889fd8e6be9399f50',
        'c80dd99eb29c860cd16a957d30f79888488bfe6a',
    ),
    'tests/test_post413_o1_scope.py': (
        '40b935e1cdd342452a60f0d5e1ebf6865be95041',
        '40b935e1cdd342452a60f0d5e1ebf6865be95041',
        '50ae69884bc625d3317a89eaed207735d46f277b',
    ),
}
CURRENT_RUNTIME_PINS = {
    'tests/test_post413_o1_scope.py': CURRENT_O1_PHASE_BLOB,
    'tests/fin_v2_cohorts.py': '5c5cf444551aa9d853771005bba954b6bf5edb13',
    'tests/u1_scope.py': 'a4b7f3e728dae845ac9c51cdfa90408a4b8e1608',
}


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


def _runtime_handoff_pin(root, path, historical):
    if path not in RUNTIME_HANDOFF_PINS:
        return historical
    from tests import ci_v4_p0_scope as P0

    original, accepted, reviewed = RUNTIME_HANDOFF_PINS[path]
    assert historical == original
    lineage = [(RECONCILIATION_HEAD, original), (ACCEPTED_RUNTIME_HEAD, accepted), (REVIEWED_RUNTIME_HEAD, reviewed)]
    o1_manifest = 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json'
    if path == 'tests/test_post413_o1_scope.py':
        assert P0.o1_historical_test_pin(o1_manifest, path, accepted, root)
        lineage.append(REVIEWED_O1_PHASE)
    else:
        approved = json.loads(git(root, 'show', ACCEPTED_RUNTIME_HEAD + ':' + P0.MANIFEST))
        assert approved['source_blobs'][path] == accepted and approved['source_modes'][path] == '100644'
    latest_ref, reviewed = lineage[-1]
    current = CURRENT_RUNTIME_PINS.get(path, reviewed)
    lineage.append(('HEAD', current))
    for (predecessor, _), (successor, _) in zip(lineage, lineage[1:]):
        git(root, 'merge-base', '--is-ancestor', predecessor, successor)
    for ref, blob in lineage:
        assert git(root, 'ls-tree', ref, '--', path).strip() == f'100644 blob {blob}\t{path}'
    successor = json.loads(git(root, 'show', latest_ref + ':' + P0.MANIFEST))
    assert successor['source_blobs'][path] == reviewed and successor['source_modes'][path] == '100644'
    assert path in P0.HANDOFFS and P0.exact_blobs_ok(root) and P0.supersedes(path, current, root)
    return current


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
            lineage_ref = PR3B2_MERGE if p in later_pins or p in RUNTIME_HANDOFF_PINS else None
            assert U.supersedes(p,eff,ref=lineage_ref) and not U.supersedes(p,'0'*40,ref=lineage_ref)
            if eff!=hist:  # a historical pin cannot supersede an accepted later pin
                assert not U.supersedes(p,hist,ref=lineage_ref)
            if p in later_pins:
                assert git(U.ROOT, 'rev-parse', PR3B2_MERGE + ':' + p).strip() == eff
                assert not U.supersedes(p,'0'*40)
            current_pin = _runtime_handoff_pin(U.ROOT, p, later_pins.get(p, eff))
            assert git(U.ROOT, 'hash-object', '--no-filters', p).strip() == current_pin
        for p in U.INTEGRATION_MANIFESTS:
            old=json.loads(git(U.ROOT,'show',U.BASE+':'+p));now=json.loads((U.ROOT/p).read_text())
            assert {k:v for k,v in old.items() if k!='source_blobs'}=={k:v for k,v in now.items() if k!='source_blobs'}
        for p in ('app/v2/save_all_commands.py','financial_engine/x.py','.github/workflows/ci_v4_pr.yml','frontend/src/app/editing/pendingEdits.ts'):
            assert not U.allowed_path(p) and not U.matches(p)


def test_runtime_handoff_rejects_physical_and_committed_changes(wt):
    path = 'tests/u1_scope.py'
    historical = RUNTIME_HANDOFF_PINS[path][0]
    with C.call_scope():
        assert _runtime_handoff_pin(wt, path, historical) == CURRENT_RUNTIME_PINS[path]
    source = wt / path
    source.write_bytes(source.read_bytes() + b'\n')
    with C.call_scope(), pytest.raises(AssertionError):
        _runtime_handoff_pin(wt, path, historical)
    original_head = git(wt, 'rev-parse', 'HEAD').strip()
    try:
        git(wt, 'add', '--', path)
        git(wt, '-c', 'user.name=UX scope test', '-c', 'user.email=noreply@users.noreply.github.com',
            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Alter the live runtime handoff')
        with C.call_scope(), pytest.raises(AssertionError):
            _runtime_handoff_pin(wt, path, historical)
    finally:
        git(wt, 'reset', '--hard', '-q', original_head)


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


@pytest.fixture
def f01_evidence_file(wt):
    # The accepted BESS/ON closure recognizes a finite set of F01 outputs.
    artifact = wt / 'evidence/browser/solar.json'
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"synthetic": true}\n')
    return artifact


def test_ci_artifacts_are_not_source_exemptions(wt, f01_evidence_file):
    with C.call_scope():
        assert U.exact_blobs_ok(wt) and C.valid(wt)


@pytest.mark.parametrize('suffix', ['.json', '.py', '.tsx', '.mjs'])
def test_unreviewed_file_in_evidence_directory_fails_closed(wt, f01_evidence_file, suffix):
    source = f01_evidence_file.with_name('unsigned' + suffix)
    source.write_text('{}\n' if suffix == '.json' else 'unsigned\n')
    with C.call_scope():
        assert not U.exact_blobs_ok(wt) and not C.valid(wt)


@pytest.mark.parametrize('kind', ['executable', 'symlink'])
def test_invalid_evidence_file_mode_fails_closed(wt, f01_evidence_file, kind):
    if kind == 'executable':
        f01_evidence_file.chmod(0o755)
    else:
        f01_evidence_file.unlink()
        f01_evidence_file.symlink_to(wt / 'tests/ux_pr1_scope.py')
    with C.call_scope():
        assert not U.exact_blobs_ok(wt)

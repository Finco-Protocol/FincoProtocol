"""H-1/H-2 deliberately tighten source state; accepted historical pins remain unchanged."""
from contextlib import ExitStack, nullcontext
from pathlib import Path
import json
import os
import stat
import subprocess
import time
import pytest
from tests import fin_v2_integration_409_scope as I
from tests import fin_v2_wf06a_scope as W6
from tests import wf03_lifecycle_scope as W3
from tests import wsv2_core_scope as WS
from tests import fin_v2_cohorts as C
from tests import on09c_source_state as S
from tests import wf06b_scope as W

GATES = [('INT.exact', I.exact_blobs_ok), ('WF06A.exact', W6.exact_blobs_ok),
         ('WF03.valid', W3.valid), ('WSV2.exact', WS.exact_blobs_ok), ('composite.valid', C.valid)]
VICTIM = 'tests/fin_v2_integration_409_scope.py'


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


@pytest.fixture(scope='module')
def wt(tmp_path_factory):
    root = tmp_path_factory.mktemp('on09c') / 'wt'
    git(I.ROOT, 'worktree', 'add', '--detach', str(root), 'HEAD')
    yield root
    git(I.ROOT, 'worktree', 'remove', '--force', str(root))


def reset(root):
    # Only the module-owned disposable worktree is reset, never the live branch.
    git(root, 'reset', '--hard', 'HEAD')
    git(root, 'clean', '-fdxq')


def check(root, name, expected, rows):
    values = {}
    for label, fn in GATES:
        with ExitStack() as scopes:
            for cohort in C.cohorts():
                if callable(getattr(cohort, 'scoped', None)):
                    scopes.enter_context(cohort.scoped())
            values[label] = fn(root)
        assert values[label] is expected, (name, label, values)
    rows.append({'case': name, 'expected': expected, 'results': values,
                 'context': 'fresh registered call scopes per gate; identity rechecked across mutations'})


def flip(root, path=VICTIM, suffix=b'\n'):
    target = root / path
    target.write_bytes(target.read_bytes() + suffix)


def test_full_real_source_state_matrix(wt):
    rows = []
    try:
        reset(wt); check(wt, 'clean', True, rows)
        flip(wt); check(wt, 'tracked-byte-flip', False, rows)
        flip(wt, suffix=b'# second same-path state\n'); check(wt, 'same-path-second-byte-state', False, rows)
        reset(wt); flip(wt); git(wt, 'add', VICTIM); check(wt, 'staged-edit', False, rows)
        reset(wt); flip(wt, 'app/services/sensitivity_service.py'); check(wt, 'unstaged-edit', False, rows)
        reset(wt); path = wt/'app/on09c_untracked.py'; path.write_text('x=1\n'); check(wt, 'untracked-executable-source', False, rows)
        path.write_text('x=2\n'); check(wt, 'untracked-source-second-byte-state', False, rows)
        reset(wt); (wt/VICTIM).unlink(); check(wt, 'deleted-file', False, rows)
        reset(wt); (wt/VICTIM).rename(wt/'tests/on09c_renamed.py'); check(wt, 'renamed-file', False, rows)
        reset(wt); path = wt/VICTIM; path.chmod(path.stat().st_mode | 0o111); check(wt, 'tracked-file-mode-change', False, rows)
        for name, edit in [
            ('missing-manifest-entry', lambda j: j['source_blobs'].pop('tests/wf03_lifecycle_scope.py')),
            ('extra-manifest-entry', lambda j: j['source_blobs'].__setitem__('app/unreviewed.py', '0'*40)),
            ('forged-blob', lambda j: j['source_blobs'].__setitem__('tests/wf03_lifecycle_scope.py', '0'*40)),
            ('forged-ancestor-sha', lambda j: j['sources']['PR407'].__setitem__('head', '1'*40)),
            ('forged-ancestor-tree', lambda j: j['sources']['PR407'].__setitem__('tree', '2'*40)),
        ]:
            reset(wt); path = wt/I.MANIFEST; data = json.loads(path.read_text()); edit(data); path.write_text(json.dumps(data)); check(wt, name, False, rows)
        reset(wt); path = wt/'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json'; data = json.loads(path.read_text()); data['historical_source_blobs'][next(iter(data['historical_source_blobs']))] = {}; path.write_text(json.dumps(data)); check(wt, 'mutated-historical-source-map', False, rows)
        reset(wt); path = wt/W3.MANIFEST; data = json.loads(path.read_text()); data['path_ledger'].pop(); path.write_text(json.dumps(data)); check(wt, 'truncated-path-ledger', False, rows)
        reset(wt); flip(wt, 'financial_engine/orchestrator.py'); check(wt, 'unexpected-financial-engine-source', False, rows)
        reset(wt); path = wt/VICTIM; original = path.read_bytes(); flip(wt); git(wt, 'add', VICTIM); path.write_bytes(original); check(wt, 'staged-index-edit-with-worktree-restored', False, rows)
        reset(wt); check(wt, 'restored-clean', True, rows)
        out = os.environ.get('ON09C_EVIDENCE_DIR')
        if out:
            folder = Path(out); folder.mkdir(parents=True, exist_ok=True)
            (folder/'HARDENED_NEGATIVE_MATRIX.json').write_text(json.dumps(rows, indent=2)+'\n')
    finally:
        reset(wt)


@pytest.mark.parametrize('label,gate,scope', [
    ('INT', I.exact_blobs_ok, I.scoped),
    ('WF06A', W6.exact_blobs_ok, W6.scoped),
    ('WF03', W3.valid, W3.scoped),
    ('WF06B', W.exact_blobs_ok, W.scoped),
    ('WSV2', WS.exact_blobs_ok, nullcontext),
    ('composite', C.valid, nullcontext),
])
def test_mutations_between_calls_inside_the_same_outer_scope(wt, label, gate, scope):
    reset(wt)
    try:
        with ExitStack() as scopes:
            for cohort in C.cohorts():
                if callable(getattr(cohort, 'scoped', None)):
                    scopes.enter_context(cohort.scoped())
            scopes.enter_context(scope())
            assert gate(wt)
            original = (wt/VICTIM).read_bytes()
            flip(wt); assert not gate(wt)
            flip(wt, suffix=b'# another state\n'); assert not gate(wt)
            reset(wt); assert gate(wt)
            (wt/VICTIM).chmod((wt/VICTIM).stat().st_mode | 0o111); assert not gate(wt)
            reset(wt); assert gate(wt)
            flip(wt); git(wt, 'add', VICTIM); (wt/VICTIM).write_bytes(original)
            assert not gate(wt)
            reset(wt); assert gate(wt)
    finally:
        reset(wt)


def test_type_and_index_flags_are_not_hidden_by_equal_content(wt):
    reset(wt)
    try:
        original = (wt/VICTIM).read_bytes()
        outside = wt.parent/'same-bytes.py'; outside.write_bytes(original)
        (wt/VICTIM).unlink(); (wt/VICTIM).symlink_to(outside)
        assert not I.exact_blobs_ok(wt)
        reset(wt); git(wt, 'update-index', '--assume-unchanged', VICTIM)
        assert not I.exact_blobs_ok(wt)
        git(wt, 'update-index', '--no-assume-unchanged', VICTIM)
        git(wt, 'update-index', '--skip-worktree', VICTIM)
        assert not I.exact_blobs_ok(wt)
        git(wt, 'update-index', '--no-skip-worktree', VICTIM)
        reset(wt); git(wt, '-c', 'core.filemode=false', 'status', '--porcelain')
        (wt/VICTIM).chmod((wt/VICTIM).stat().st_mode | 0o111)
        # The identity's lstat signature is independent of core.filemode config.
        def ignoring_filemode(root, *args):
            return git(root, '-c', 'core.filemode=false', *args)
        assert not S.authenticated_state_ok(wt, None, ignoring_filemode)
    finally:
        git(wt, 'update-index', '--no-assume-unchanged', '--no-skip-worktree', VICTIM)
        reset(wt)


def test_allowed_evidence_and_outside_staging_keep_their_policy(wt):
    reset(wt)
    try:
        (wt/'evidence').mkdir(exist_ok=True)
        (wt/'evidence/on09c.json').write_text('{}')
        assert I.exact_blobs_ok(wt)
        (wt/'evidence/on09c.json').unlink()
        (wt/'evidence/on09c.json').symlink_to('missing-on09c-evidence-target')
        assert I.exact_blobs_ok(wt)
        reset(wt)
        mode_paths = dict(S.canonical_modes(str(wt), I._git))
        outside = next(p for p in ('README.md', 'README') if (wt/p).is_file() and p not in mode_paths)
        path = wt/outside; original = path.read_bytes(); path.write_bytes(original+b'\n'); git(wt, 'add', outside); path.write_bytes(original)
        assert S.authenticated_state_ok(wt, None, I._git)
        assert I.exact_blobs_ok(wt)
        reset(wt)
        assert I.exact_blobs_ok(wt)
    finally:
        reset(wt)


def test_same_size_past_mtime_cannot_hide_index_only_drift(wt):
    reset(wt)
    try:
        path = wt/VICTIM
        original = path.read_bytes()
        changed = original.replace(b'Exact-source', b'Xxact-source', 1)
        assert changed != original and len(changed) == len(original)
        past = int(time.time()) - 86400
        path.write_bytes(changed); os.utime(path, (past, past)); git(wt, 'add', VICTIM)
        path.write_bytes(original); os.utime(path, (past, past))
        def distrust_ctime(root, *args):
            return git(root, '-c', 'core.trustctime=false', *args)
        assert distrust_ctime(wt, 'diff', '--raw', '--no-ext-diff', '--no-renames', '-z', '--') == b''
        assert not S.authenticated_state_ok(wt, None, distrust_ctime)
        key = S.state_key(wt, None, distrust_ctime)
        reset(wt)
        assert S.state_key(wt, None, distrust_ctime) != key
    finally:
        reset(wt)


def test_fresh_byte_identity_cannot_be_hidden_by_git_stat_cache(wt):
    reset(wt)
    try:
        path = wt/VICTIM; original = path.read_bytes()
        past = int(time.time()) - 86400
        os.utime(path, (past, past)); git(wt, 'update-index', '--refresh')
        def distrust_ctime(root, *args):
            return git(root, '-c', 'core.trustctime=false', *args)
        before = S.state_key(wt, None, distrust_ctime)
        changed = original.replace(b'Exact-source', b'Xxact-source', 1)
        path.write_bytes(changed); os.utime(path, (past, past))
        assert distrust_ctime(wt, 'diff', 'HEAD', '--no-ext-diff', '--binary', '--') == b''
        assert S.state_key(wt, None, distrust_ctime) != before
        assert not S.authenticated_state_ok(wt, None, distrust_ctime)
    finally:
        reset(wt)


def test_accepted_history_and_finite_successor_modes_are_closed(wt):
    reset(wt)
    data = W.manifest(wt)
    old = json.loads(W._read(wt, W.MANIFEST, S.ACCEPTED))
    assert data['on09c_history'] == {S.ACCEPTED: old}
    assert set(data['source_blobs']) == set(old['source_blobs']) | set(S.ADDED_MODES)
    assert not I.allowed_path('tests/on09c_unreviewed.py', wt)
    for field in ('on09c_history', 'on09c_path_ledger'):
        path = wt/W.MANIFEST; changed = json.loads(path.read_text()); changed[field] = {}; path.write_text(json.dumps(changed))
        assert not I.exact_blobs_ok(wt)
        reset(wt)


@pytest.mark.parametrize('initial_bad', [True, False])
def test_cache_miss_proof_is_bound_to_its_start_state(wt, monkeypatch, initial_bad):
    reset(wt)
    try:
        original = (wt/VICTIM).read_bytes()
        bad = original+b'\n# proof-state tamper\n'
        def set_state(broken):
            (wt/VICTIM).write_bytes(bad if broken else original)
            git(wt, 'add', VICTIM)
        set_state(initial_bad)
        reader = I._read
        armed = [True]
        def transition(root, path, ref):
            if Path(root) == wt and ref is None and armed[0]:
                armed[0] = False
                set_state(not initial_bad)
            return reader(root, path, ref)
        monkeypatch.setattr(I, '_read', transition)
        I._RESULTS.clear()
        assert not I.exact_blobs_ok(wt)
        set_state(initial_bad)
        assert I.exact_blobs_ok(wt) is (not initial_bad)
        reset(wt)
        assert I.exact_blobs_ok(wt)
    finally:
        reset(wt)


def test_missing_mandatory_helper_denies_on_cold_import(wt):
    reset(wt)
    try:
        (wt/'tests/on09c_source_state.py').unlink()
        code = '''import json
from tests import fin_v2_integration_409_scope as I, fin_v2_wf06a_scope as W6, wf03_lifecycle_scope as W3, wsv2_core_scope as WS, fin_v2_cohorts as C
with I.scoped(), W6.scoped(), W3.scoped():
 print(json.dumps([I.exact_blobs_ok(),W6.exact_blobs_ok(),W3.valid(),WS.exact_blobs_ok(),C.valid()]))
'''
        import sys
        output = subprocess.check_output([sys.executable, '-c', code], cwd=wt,
                                         env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=60)
        assert json.loads(output) == [False]*5
    finally:
        reset(wt)


def test_fifo_type_is_denied_before_git_diff_can_read_it(wt):
    reset(wt)
    try:
        (wt/VICTIM).unlink(); os.mkfifo(wt/VICTIM)
        def no_diff(root, *args):
            assert not args or args[0] != 'diff', 'unsupported source type must stop before diff'
            return I._git(root, *args)
        assert S.state_key(wt, None, no_diff) is None
        assert not S.authenticated_state_ok(wt, None, no_diff)
        assert not I.exact_blobs_ok(wt)
    finally:
        (wt/VICTIM).unlink(missing_ok=True)
        reset(wt)


def test_explicit_immutable_ref_is_independent_of_working_index(wt):
    reset(wt)
    try:
        head = git(wt, 'rev-parse', 'HEAD').decode().strip()
        original = (wt/VICTIM).read_bytes(); flip(wt); git(wt, 'add', VICTIM); (wt/VICTIM).write_bytes(original)
        assert not I.exact_blobs_ok(wt)
        assert I.exact_blobs_ok(wt, head)
    finally:
        reset(wt)


def test_staged_successor_provenance_forgery_is_not_just_index_drift(wt):
    reset(wt)
    try:
        path = wt/W.MANIFEST; data = json.loads(path.read_text())
        data['on09c_path_ledger'][0]['unreviewed'] = 'ignored field is forbidden'
        path.write_text(json.dumps(data)); git(wt, 'add', W.MANIFEST)
        assert S.authenticated_state_ok(wt, None, I._git)
        assert not I.exact_blobs_ok(wt)
    finally:
        reset(wt)


@pytest.mark.parametrize('initial_bad', [True, False])
def test_leaf_cache_miss_is_bound_to_its_start_state(wt, monkeypatch, initial_bad):
    reset(wt)
    try:
        original = (wt/VICTIM).read_bytes()
        def set_state(broken):
            (wt/VICTIM).write_bytes(original+b'\n# leaf transition\n' if broken else original)
            git(wt, 'add', VICTIM)
        set_state(initial_bad)
        reader = W._read
        armed = [True]
        def transition(root, path, ref):
            if Path(root) == wt and ref is None and armed[0]:
                armed[0] = False
                set_state(not initial_bad)
            return reader(root, path, ref)
        monkeypatch.setattr(W, '_read', transition)
        with W.scoped():
            assert not W.exact_blobs_ok(wt)
            set_state(initial_bad)
            assert W.exact_blobs_ok(wt) is (not initial_bad)
            reset(wt)
            assert W.exact_blobs_ok(wt)
    finally:
        reset(wt)


def test_accepted_predecessor_ref_remains_positive_with_a_bad_current_index(wt):
    reset(wt)
    try:
        original = (wt/VICTIM).read_bytes()
        flip(wt); git(wt, 'add', VICTIM); (wt/VICTIM).write_bytes(original)
        assert not W.exact_blobs_ok(wt)
        for label, gate in GATES:
            with ExitStack() as scopes:
                for cohort in C.cohorts():
                    if callable(getattr(cohort, 'scoped', None)):
                        scopes.enter_context(cohort.scoped())
                assert gate(wt, S.ACCEPTED), label
        assert W.exact_blobs_ok(wt, S.ACCEPTED)
        # No mutable-working-state fallback to the historical lane.
        assert not I.exact_blobs_ok(wt)
    finally:
        reset(wt)


def test_canonical_closure_covers_all_accepted_registered_cohorts(wt):
    manifests = {m.MANIFEST for m in C.cohorts()}
    assert set(S.MANIFESTS) == manifests
    modes = dict(S.canonical_modes(str(wt), I._git))
    for path in manifests:
        data = json.loads(git(wt, 'show', S.ACCEPTED+':'+path))
        assert set(data['source_blobs']) | {path} <= modes.keys()
    assert set(S.ADDED_MODES) == W.ON09C_ADDED
    assert not any(p.startswith(W.FORBIDDEN_PREFIXES) for p in W.ON09C_CHANGED)


@pytest.mark.parametrize('dependency', ['reader', 'base_tree'])
def test_nested_leaf_proof_changes_invalidate_warm_outer_approvals(wt, monkeypatch, dependency):
    reset(wt)
    try:
        with ExitStack() as scopes:
            for cohort in C.cohorts():
                if callable(getattr(cohort, 'scoped', None)):
                    scopes.enter_context(cohort.scoped())
            for label, gate in GATES:
                assert gate(wt), label
            if dependency == 'reader':
                reader = W._read
                def forged(root, path, ref):
                    raw = reader(root, path, ref)
                    if path == W.MANIFEST and ref is None:
                        data = json.loads(raw)
                        data['base_tree'] = '0'*40
                        return json.dumps(data).encode()
                    return raw
                monkeypatch.setattr(W, '_read', forged)
            else:
                monkeypatch.setattr(W, 'BASE_TREE', '0'*40)
            for label, gate in GATES:
                assert not gate(wt), (dependency, label)
            monkeypatch.undo()
            for label, gate in GATES:
                assert gate(wt), label
    finally:
        reset(wt)

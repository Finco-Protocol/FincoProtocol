"""PR-U2 exact-source cohort: positives and tamper negatives on REAL git worktrees (2026-11-03 brief + mandatory addendum).

Every negative mutates a real checkout of the committed HEAD (shared object database, private working tree) and asks the real cohort functions.
"""
import json
from pathlib import Path
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import u1_scope as U1
from tests import u2_scope as U2
from tests import wf06b_scope as W


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    head = _git(U2.ROOT, 'rev-parse', 'HEAD').strip()
    path = tmp_path_factory.mktemp('u2-wt') / 'wt'
    _git(U2.ROOT, 'worktree', 'add', '--detach', str(path), head)
    yield path
    _git(U2.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def _flip(path):
    path.write_bytes(path.read_bytes() + b'\n')


# ── Integrated four-cohort contract (R17 / R18 / R1 / U2 registered together on the integration branch) ──────────────────────────────────────
FOUR = ('tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope')


def _later(names=None):
    """The registered later-cohort modules (read through U1's own closed list), optionally restricted to ``names``."""
    return [m for m in U1._later_modules() if names is None or m.__name__ in names]


def _signed(modules):
    """Finite closed union of the owned paths plus the manifest of each given cohort module."""
    return set().union(*(set(m.OWNED_PATHS) | {m.MANIFEST} for m in modules)) if modules else set()


def _unexplained(changed, registered_exact):
    """Changed paths neither owned by U2 nor by a REGISTERED and EXACT sibling cohort; any historical SOURCE_SUCCESSOR.json that is not a registered
    sibling's own manifest is always unexplained, and so is every forbidden path."""
    owned = U2.OWNED_PATHS | {U2.MANIFEST} | _signed(registered_exact)
    return sorted(p for p in changed
                  if p not in owned or p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS)




def test_positive_cohort_is_exact_registered_and_closed():
    assert U2.exact_blobs_ok() and U2.valid() and C.valid() and U1.exact_blobs_ok() and W.exact_blobs_ok()
    assert U2.__name__ in C.COHORT_MODULES and U2 in C.cohorts() and U2.protected_blobs() == {}
    data = U2.manifest()
    assert set(data['source_blobs']) == U2.OWNED_PATHS and set(data['base_blobs']) == U2.SUPERSEDED
    assert not any(p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS for p in U2.OWNED_PATHS)
    assert not (U2.OWNED_PATHS & U2.R1_PATHS)                                                    # addendum: no R1-owned file
    for stranger in ('app/v2/router.py', 'app/v2/save_all_commands.py', 'tests/test_something_new.py',
                     'financial_engine/x.py', '.github/workflows/ci.yml'):
        assert not U2.allowed_path(stranger) and not U1.allowed_path(stranger) and not W.allowed_path(stranger)
    # An R1 path is never U2's. It is admitted by U1 / WF-06B ONLY through the exact, registered R1 cohort that owns it (integration branch).
    r1 = {m.__name__: m for m in _later()}['tests.post413_r1_scope']
    for r1_path in ('frontend/src/app/editing/saveAll.ts', 'frontend/src/app/editing/pendingEdits.ts', 'frontend/src/app/workflow/PPAEditorView.tsx'):
        assert not U2.allowed_path(r1_path) and r1_path not in U2.OWNED_PATHS and r1.allowed_path(r1_path)
        assert 'tests.post413_r1_scope' in C.COHORT_MODULES and r1.exact_blobs_ok() and U1.allowed_path(r1_path) and W.allowed_path(r1_path)
    for owned in ('app/v2/react_opex_lines.py', 'frontend/src/app/capex/profileImport.ts', 'tests/u2_scope.py'):
        assert U2.matches(owned) and U2.allowed_path(owned) and U1.allowed_path(owned) and W.allowed_path(owned)
    path = 'static/react/finco-react.js'
    pin = data['source_blobs'][path]
    assert U2.supersedes(path, pin) and U1.supersedes(path, pin) and W.supersedes(path, pin) and not U2.supersedes(path, '0' * 40)
    assert not U2.supersedes('app/v2/react_opex_lines.py', data['source_blobs']['app/v2/react_opex_lines.py'])   # new at U2: nothing to supersede


def test_base_is_main_after_413_and_u1_is_superseded_only_at_its_own_pins():
    assert _git(U2.ROOT, 'rev-parse', U2.BASE + '^{tree}').strip() == U2.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U2.BASE, 'HEAD'], cwd=U2.ROOT)
    u1_pins = U1.manifest()['source_blobs']
    for path, blob in U2.manifest()['base_blobs'].items():
        assert _git(U2.ROOT, 'rev-parse', f'{U2.BASE}:{path}').strip() == blob
        assert u1_pins.get(path) == blob, path                                                    # U2 supersedes exactly what U1 signed
    changed = set(_git(U2.ROOT, 'diff', '--name-only', U2.BASE, '--').split())
    registered_exact = [m for m in _later() if m.__name__ in C.COHORT_MODULES and m.exact_blobs_ok()]
    assert {m.__name__ for m in registered_exact} <= set(FOUR) and 'tests.u2_scope' in {m.__name__ for m in registered_exact}
    own_manifests = {m.MANIFEST for m in registered_exact}
    # no OLDER manifest edited: the only SOURCE_SUCCESSOR.json files in the diff are the registered exact sibling cohorts' OWN manifests
    assert not any(p.endswith('SOURCE_SUCCESSOR.json') and p not in own_manifests for p in changed)
    assert not any(p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS for p in changed)
    # an R1 file may be in the diff only because the exact registered R1 cohort owns it (never U2)
    r1_owned = _signed([m for m in registered_exact if m.__name__ == 'tests.post413_r1_scope'])
    assert all(p in r1_owned for p in changed & U2.R1_PATHS)
    assert _unexplained(changed, registered_exact) == []                                          # U2's own paths + exact registered siblings only


def test_unexplained_changed_paths_are_refused_for_the_four_cohort_contract():
    """Negatives of the F2 contract on synthetic change sets: every path outside U2 and the exact registered siblings stays unexplained."""
    registered = _later(FOUR)
    r1 = [m for m in registered if m.__name__ == 'tests.post413_r1_scope']
    base = {'app/v2/react_opex_lines.py', U2.MANIFEST}
    assert _unexplained(base, registered) == []
    assert _unexplained(base | {'frontend/src/app/editing/saveAll.ts'}, registered) == []                       # exact registered R1 owns it
    assert _unexplained(base | {'frontend/src/app/editing/saveAll.ts'}, [m for m in registered if m not in r1]) == ['frontend/src/app/editing/saveAll.ts']
    assert _unexplained({'app/v2/router.py'}, registered) == ['app/v2/router.py']                                # foreign changed byte
    assert _unexplained({'tests/test_something_new.py'}, registered) == ['tests/test_something_new.py']          # unregistered new path
    old_manifest = 'docs/react_migration/u1_workbench/SOURCE_SUCCESSOR.json'
    assert _unexplained({old_manifest}, registered) == [old_manifest]                                            # altered historical manifest
    assert _unexplained({'docs/react_migration/post413_rX/SOURCE_SUCCESSOR.json'}, registered) == ['docs/react_migration/post413_rX/SOURCE_SUCCESSOR.json']   # unowned manifest
    for forbidden in ('financial_engine/x.py', 'finco_core/x.py', 'domain/x.py', '.github/workflows/x.yml', 'tools/x.py', 'main_web.py'):
        assert _unexplained({forbidden}, registered) == [forbidden]


def test_older_cohorts_still_exact_through_the_bounded_hooks():
    assert all(m.exact_blobs_ok() for m in C.cohorts())


@pytest.mark.parametrize('path', sorted(U2.OWNED_PATHS))
def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):
    assert U2.exact_blobs_ok(wt)
    _flip(wt / path)
    assert not U2.exact_blobs_ok(wt) and not U2.matches(path, (wt / path).read_bytes(), repo=wt) and not C.valid(wt)
    if path in U1.OWNED_PATHS:
        assert not U1.exact_blobs_ok(wt)                                                          # U1 stops following a drifted U2 state


@pytest.mark.parametrize('kind', ['extra-path', 'missing-pin', 'wrong-base', 'wrong-tree', 'wrong-blob', 'swapped-pins', 'drop-base-blob',
                                  'wrong-base-blob', 'swapped-schema', 'alias-pin', 'extra-base-blob'])
def test_manifest_forgery_is_refused(kind, wt):
    mpath = wt / U2.MANIFEST
    d = json.loads(mpath.read_text())
    if kind == 'extra-path':
        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40
    elif kind == 'missing-pin':
        d['source_blobs'].pop('static/react/finco-react.js')
    elif kind == 'wrong-base':
        d['base'] = '0' * 40
    elif kind == 'wrong-tree':
        d['base_tree'] = '0' * 40
    elif kind == 'wrong-blob':
        d['source_blobs']['app/v2/react_opex_lines.py'] = '0' * 40
    elif kind == 'swapped-pins':
        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'
        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]
    elif kind == 'drop-base-blob':
        d['base_blobs'].pop('app/v2/react_workspace_router.py')
    elif kind == 'wrong-base-blob':
        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40
    elif kind == 'swapped-schema':
        d['schema_version'] = U1.SCHEMA
    elif kind == 'alias-pin':
        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']
    elif kind == 'extra-base-blob':
        d['base_blobs']['app/v2/save_all_commands.py'] = _git(U2.ROOT, 'rev-parse', f'{U2.BASE}:app/v2/save_all_commands.py').strip()
    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')
    assert not U2.exact_blobs_ok(wt) and not C.valid(wt) and not U1.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt)


def test_u1_follows_u2_only_where_u2_recorded_exactly_the_u1_pin(wt, monkeypatch):
    path = 'frontend/src/app/capex/CapexStudio.tsx'
    assert U1.exact_blobs_ok(wt)
    # forge the U1 pin: U2's recorded BASE blob no longer equals it -> U1 must NOT follow U2
    upath = wt / U1.MANIFEST
    u = json.loads(upath.read_text())
    u['source_blobs'][path] = '1' * 40
    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\n')
    assert not U1.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'checkout', '--', U1.MANIFEST)
    assert U1.exact_blobs_ok(wt)
    # a U2 cohort that no longer supersedes the path is not followed either
    monkeypatch.setattr(U2, 'SUPERSEDED', frozenset(U2.SUPERSEDED - {path}))
    assert not U1.supersedes(path, U2.manifest(wt)['source_blobs'][path], repo=wt)


def test_extra_tracked_extra_untracked_r1_and_executable_paths_fail_closed(wt):
    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\n')
    assert not U2.exact_blobs_ok(wt)
    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')
    assert not U2.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'reset', '-q')
    (wt / 'frontend/src/app/Sneaky.tsx').unlink()
    assert U2.exact_blobs_ok(wt)
    owned = wt / 'app/v2/react_opex_lines.py'
    owned.chmod(0o755)
    assert not U2.exact_blobs_ok(wt)
    owned.chmod(0o644)
    assert U2.exact_blobs_ok(wt)


@pytest.mark.parametrize('path', ['financial_engine/__init__.py', 'finco_core/__init__.py', 'domain/__init__.py', 'main_web.py', 'tools/ci_v3_schema.py',
                                  '.github/workflows/ci_v3_required_job.yml', 'app/v2/router.py', 'tests/conftest.py',
                                  'app/v2/save_all_commands.py', 'frontend/src/app/editing/saveAll.ts', 'frontend/src/app/editing/pendingEdits.ts',
                                  'frontend/src/app/editing/wsv2Extensions.tsx', 'frontend/src/app/workflow/PPAEditorView.tsx',
                                  'frontend/src/app/WorkspaceView.tsx', 'frontend/src/app/editing/ChangesProvider.tsx',
                                  'app/capex_profiles/config.py', 'app/v2/capex_router.py', 'app/v2/opex_router.py'])
def test_protected_r1_and_unowned_code_modified_after_signing_fails_closed(path, wt):
    assert U2.exact_blobs_ok(wt)
    _flip(wt / path)
    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qam', 'tamper', '--no-verify')
    assert not U2.exact_blobs_ok(wt) and not C.valid(wt)
    assert not U2.allowed_path(path)
    _git(wt, 'reset', '--hard', '-q', 'HEAD~1')


_RCUX_TAIL = "# ───────────────────────────── RC-UX: React adapters"
_ROUTER = 'app/v2/react_workspace_router.py'
_RCM_MARK = "# ───────────────────────────── RC-M: React adapters"
_U2_MARK = "# ───────────────────────────── PR-U2b: OPEX lines by year"
_RCM_INCLUDES = ['_new_project_router', '_analysis_router', '_goal_seek_router', '_financing_router', '_investors_router']


def _tail_includes(text):
    import re
    return re.findall(r"^router\.include_router\((\w+)\)$", text[text.index(_RCUX_TAIL):], flags=re.M)


def test_the_u2_mount_is_in_the_body_and_the_rcux_tail_keeps_exactly_its_one_include():
    import re
    inc = r"^router\.include_router\((\w+)\)$"
    text = (U2.ROOT / _ROUTER).read_text(encoding='utf-8')
    base = _git(U2.ROOT, 'show', f'{U2.BASE}:{_ROUTER}')
    # (a) the U2 include appears exactly once in the whole file
    assert re.findall(inc, text, flags=re.M).count('_u2_opex_lines_router') == 1
    # (b) it lives in its own marked U2 section, before (outside) both historical sentinel intervals
    u2_at, rcm_at, rcux_at = text.index(_U2_MARK), text.index(_RCM_MARK), text.index(_RCUX_TAIL)
    assert u2_at < rcm_at < rcux_at and text.index('router.include_router(_u2_opex_lines_router)') < rcm_at
    assert re.findall(inc, text[u2_at:rcm_at], flags=re.M) == ['_u2_opex_lines_router']
    # (c) RC-M keeps exactly its five includes in order, RC-UX exactly its one; everything from RC-M on is byte-identical to BASE
    assert re.findall(inc, text[rcm_at:rcux_at], flags=re.M) == _RCM_INCLUDES
    assert _tail_includes(text) == ['_rcux_router']
    assert text[rcm_at:] == base[base.index(_RCM_MARK):]
    # the only change against BASE is the U2 section inserted right before the RC-M marker
    assert text[:u2_at] == base[:base.index(_RCM_MARK)]
    added = sorted(set(re.findall(inc, text, flags=re.M)) - set(re.findall(inc, base, flags=re.M)))
    assert added == ['_u2_opex_lines_router']


@pytest.mark.parametrize('where', ['tail', 'body', 'u2-section'])
def test_an_unreviewed_second_include_router_fails_closed(where, wt):
    path = wt / _ROUTER
    text = path.read_text(encoding='utf-8')
    extra = "from app.v2.react_unreviewed import router as _unreviewed_router  # noqa: E402\n\nrouter.include_router(_unreviewed_router)\n"
    if where == 'tail':
        text = text.rstrip('\n') + '\n\n' + extra
    elif where == 'body':
        i = text.index(_RCUX_TAIL)                                                                 # inside the historical RC-M interval
        text = text[:i] + extra + '\n' + text[i:]
    else:
        i = text.index(_RCM_MARK)                                                                  # a second include in the U2 section
        text = text[:i] + extra + '\n' + text[i:]
    path.write_text(text, encoding='utf-8')
    if where == 'tail':
        assert _tail_includes(text) != ['_rcux_router']                                           # the protected RC-UX check refuses it
    if where == 'body':
        import re
        rcm = text[text.index(_RCM_MARK):text.index(_RCUX_TAIL)]
        assert re.findall(r"^router\.include_router\((\w+)\)$", rcm, flags=re.M) != _RCM_INCLUDES   # the protected RC-M check refuses it
    assert not U2.exact_blobs_ok(wt) and not U1.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not C.valid(wt)
    assert not U1.supersedes(_ROUTER, U2._blob(text.encode()), repo=wt)


def test_an_unrelated_committed_extra_file_fails_closed(wt):
    extra = wt / 'app/v2/react_unreviewed.py'
    extra.write_text('"""unreviewed"""\n')
    _git(wt, 'add', 'app/v2/react_unreviewed.py')
    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qm', 'extra', '--no-verify')
    try:
        assert not U2.exact_blobs_ok(wt) and not U1.exact_blobs_ok(wt) and not C.valid(wt)
        assert not U2.allowed_path('app/v2/react_unreviewed.py') and not U1.allowed_path('app/v2/react_unreviewed.py')
    finally:
        _git(wt, 'reset', '--hard', '-q', 'HEAD~1')


def _u1_test_later_owned(repo, modules):
    # The four post-#413 data-integrity cohorts only; the CI V4 cohort (also a registered later cohort) is proven by tests/test_ci_v4_scope.py.
    return set().union(*(set(m.OWNED_PATHS) | {m.MANIFEST} for m in U1._later_modules()
                         if m.__name__ in modules and m.__name__ in FOUR and m.exact_blobs_ok(repo)))


# Reviewed governance/bundle paths that more than one of the four cohorts owns. Closed, literal; Correction J changed tests/test_wf06b_scope.py
# on every branch with identical text, so all four sign the same blob (proven by ``_shared_signatures``).
SHARED_REVIEWED = frozenset(('tests/fin_v2_cohorts.py', 'tests/u1_scope.py', 'tests/test_u1_scope.py', 'tests/test_wf06b_scope.py',
                             'static/react/finco-react.js'))


def _shared_signatures(repo, modules, path):
    """The set of blobs the owning cohorts pin for ``path`` plus the blob the evaluated tree holds (one element when all agree)."""
    pins = {m.manifest(repo).get('source_blobs', {}).get(path) for m in modules if path in m.OWNED_PATHS}
    return pins | {U1._blob((Path(repo) / path).read_bytes())}


def test_the_u1_successor_assertion_admits_only_a_registered_exact_u2(wt, monkeypatch):
    four = {m.__name__: m for m in _later(FOUR)}
    assert set(four) == set(FOUR) and set(FOUR) <= set(C.COHORT_MODULES)                            # all four are registered on the integration branch
    siblings = [m for n, m in four.items() if n != U2.__name__]
    union_all, union_siblings, union_u2 = _signed(list(four.values())), _signed(siblings), U2.OWNED_PATHS | {U2.MANIFEST}
    assert _u1_test_later_owned(wt, C.COHORT_MODULES) == union_all                                   # the exact union of the four signed, finite sets
    shared = (union_u2 & union_siblings) - SHARED_REVIEWED
    assert union_u2 <= union_all and shared == set(), shared                                         # U2 and siblings share only the reviewed governance/bundle paths
    for path in sorted(union_u2 & union_siblings):                                                   # every owner signs the SAME exact blob, = the tree
        assert len(_shared_signatures(wt, list(four.values()), path)) == 1, path
    # U2 unregistered: its U2-only permissions disappear, the sibling cohorts' stay (they are independently registered and exact)
    without_u2 = _u1_test_later_owned(wt, tuple(m for m in C.COHORT_MODULES if m != U2.__name__))
    assert without_u2 == union_siblings and 'app/v2/react_opex_lines.py' not in without_u2
    # each sibling unregistered independently removes only its own permissions
    for name, module in four.items():
        rest = _signed([m for n, m in four.items() if n != name])
        assert _u1_test_later_owned(wt, tuple(n for n in C.COHORT_MODULES if n != name)) == rest, name
    # U2 source drifted: U2 stops being exact -> only the siblings remain
    _flip(wt / 'app/v2/react_opex_lines.py')
    assert _u1_test_later_owned(wt, C.COHORT_MODULES) == union_siblings
    _git(wt, 'checkout', '--', 'app/v2/react_opex_lines.py')
    # each sibling drifted independently: that sibling stops being exact AND U2 stops being exact (a changed path of a drifted sibling is no longer
    # explained for U2); the other two siblings are unaffected
    drift = {'tests.post413_r17_scope': 'tests/test_r17_base_case_scope.py', 'tests.post413_r18_scope': 'tests/test_r18_atomic_reference_clone.py',
             'tests.post413_r1_scope': 'tests/test_r1_ppa_stale_document_replay.py'}
    for name, path in drift.items():
        _flip(wt / path)
        got = _u1_test_later_owned(wt, C.COHORT_MODULES)
        _git(wt, 'checkout', '--', path)
        assert got == _signed([m for n, m in four.items() if n not in (name, U2.__name__)]), name
    # a forged manifest of one sibling is refused independently
    mpath = wt / four['tests.post413_r1_scope'].MANIFEST
    d = json.loads(mpath.read_text())
    d['source_blobs']['static/react/finco-react.js'] = '0' * 40
    mpath.write_text(json.dumps(d, indent=2) + '\n')
    assert _u1_test_later_owned(wt, C.COHORT_MODULES) == _signed([m for n, m in four.items() if n not in ('tests.post413_r1_scope', U2.__name__)])
    _git(wt, 'checkout', '--', str(mpath.relative_to(wt)))
    # no later cohort at all: nothing is admitted and the hooks fail closed (no recursion, no residual state)
    monkeypatch.setattr(U1, 'LATER_COHORTS', ())
    assert U1._later_modules() == [] and not U1.allowed_path('app/v2/react_opex_lines.py') and not U1.allowed_path('frontend/src/app/editing/saveAll.ts')
    assert not W.allowed_path('frontend/src/app/editing/saveAll.ts')


def test_shared_reviewed_paths_are_signed_identically_and_fail_closed(wt):
    """#419 Correction K negatives for the shared reviewed set: one-byte drift, a forged pin in ONE owner, an extra unowned path, same-cardinality
    identity swap and a historical protected path are all refused."""
    four = list(_later(FOUR))
    union_u2, union_siblings = U2.OWNED_PATHS | {U2.MANIFEST}, _signed([m for m in four if m is not U2])
    assert (union_u2 & union_siblings) <= SHARED_REVIEWED and 'tests/test_wf06b_scope.py' in (union_u2 & union_siblings)
    path = 'tests/test_wf06b_scope.py'
    _flip(wt / path)                                                                                  # one byte of drift: signatures disagree
    assert len(_shared_signatures(wt, four, path)) == 2 and not U2.exact_blobs_ok(wt)
    _git(wt, 'checkout', '--', path)
    mpath = wt / U2.MANIFEST                                                                          # forged pin in one owner only
    d = json.loads(mpath.read_text()); d['source_blobs'][path] = '0' * 40; mpath.write_text(json.dumps(d, indent=2) + '\n')
    assert len(_shared_signatures(wt, four, path)) == 2 and not U2.exact_blobs_ok(wt)
    _git(wt, 'checkout', '--', str(mpath.relative_to(wt)))
    assert 'app/v2/react_unreviewed.py' not in SHARED_REVIEWED and not U2.allowed_path('app/v2/react_unreviewed.py')   # extra unowned path
    swapped = (SHARED_REVIEWED - {path}) | {'tests/test_rcm_governance_x.py'}                         # same cardinality, different identity
    assert len(swapped) == len(SHARED_REVIEWED) and (union_u2 & union_siblings) - swapped == {path}
    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')) for p in SHARED_REVIEWED)   # no protected path

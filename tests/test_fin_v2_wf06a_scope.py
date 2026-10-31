"""WF-06A exact-source cohort: positives and independently injected closed-world negatives (PR #406, Owner Correction B)."""
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import fin_v2_wf06a_scope as F


def test_complete_closed_cohort_and_registry():
    assert F.exact_blobs_ok() and F.valid() and C.valid()
    assert F.__name__ in C.COHORT_MODULES and F in C.cohorts()
    assert F.protected_blobs() == {}
    data = F.manifest()
    assert set(data['source_blobs']) == F.OWNED_PATHS - {F.MANIFEST}
    assert not any(p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/')) or p == 'main_web.py' for p in F.OWNED_PATHS)
    assert all('*' not in p and not p.endswith('/') for p in F.OWNED_PATHS)          # a closed literal list, never a pattern
    for stranger in ('frontend/src/app/NewUnreviewed.tsx', 'frontend/src/app/WorkspaceView.tsx', 'app/v2/router.py',
                     'tests/test_something_new.py', 'docs/react_migration/wf06a_ux/other.md', 'static/react/other.js'):
        assert not F.allowed_path(stranger) and not F.matches(stranger)
    for owned in ('frontend/src/app/InputsGuide.tsx', 'frontend/src/app/RunFailureNotice.tsx', 'static/react/finco-react.js'):
        assert F.matches(owned) and F.allowed_path(owned)


def test_predecessor_lineage_is_recorded_and_exact():
    data = F.manifest()
    assert set(data['predecessor_pins']) == F.FOLLOWED_MANIFESTS
    for path in F.FOLLOWED_MANIFESTS:
        old = json.loads(F._read(F.ROOT, path, F.BASE))['source_blobs']
        now = json.loads((F.ROOT / path).read_text())['source_blobs']
        moved = {p for p in old if old[p] != now[p]}
        assert moved <= F.FOLLOWED_MOVES[path]
        assert data['predecessor_pins'][path] == {p: old[p] for p in sorted(moved)}
        assert all(now[p] == data['source_blobs'][p] for p in moved)               # follows only this cohort's own exact pin
    # the two re-pinned historical pins of a predecessor map are exactly the delegated pair
    assert F.PREDECESSOR_REPINS == {F.WSV2_CORE_MANIFEST: frozenset(('frontend/src/app/RunFailureNotice.tsx',))}


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS - {F.MANIFEST}))
def test_every_owned_byte_and_missing_path_fail_closed(path, monkeypatch):
    source = (F.ROOT / path).read_bytes()
    assert not F.matches(path, source + b'\n')                                       # one malicious byte
    reader = F._read

    def missing(root, p, ref):
        if p == path and ref is None:
            raise FileNotFoundError(path)
        return reader(root, p, ref)
    monkeypatch.setattr(F, '_read', missing)
    assert not F.exact_blobs_ok()


@pytest.mark.parametrize('kind', ['extra-path', 'missing-pin', 'wrong-base', 'wrong-tree', 'wrong-blob', 'wrong-predecessor', 'drop-predecessor',
                                  'swapped-schema'])
def test_manifest_forgery_and_incomplete_successor_refused(kind, monkeypatch):
    reader = F._read

    def forged(root, path, ref):
        raw = reader(root, path, ref)
        if path == F.MANIFEST and ref is None:
            d = json.loads(raw)
            if kind == 'extra-path':
                d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40
            elif kind == 'missing-pin':
                d['source_blobs'].pop('frontend/src/app/InputsGuide.tsx')
            elif kind == 'wrong-base':
                d['base'] = '0' * 40
            elif kind == 'wrong-tree':
                d['base_tree'] = '0' * 40
            elif kind == 'wrong-blob':
                d['source_blobs']['static/react/finco-react.js'] = '0' * 40
            elif kind == 'wrong-predecessor':
                d['predecessor_pins'][F.WSV2_CORE_MANIFEST]['frontend/src/app/RunFailureNotice.tsx'] = '0' * 40
            elif kind == 'drop-predecessor':
                d['predecessor_pins'].pop(F.WF04_MANIFEST)
            else:
                d['schema_version'] = 'OTHER'
            return json.dumps(d).encode()
        return raw
    monkeypatch.setattr(F, '_read', forged)
    assert not F.exact_blobs_ok()


def test_wrong_ancestor_swapped_parent_and_unreviewed_paths_are_refused(monkeypatch):
    git = F._git

    def not_ancestor(root, *args):
        if args[:2] == ('merge-base', '--is-ancestor'):
            raise subprocess.CalledProcessError(1, args)
        return git(root, *args)
    monkeypatch.setattr(F, '_git', not_ancestor)
    assert not F.exact_blobs_ok()

    def swapped_tree(root, *args):
        if args[:1] == ('rev-parse',) and args[1].endswith('^{tree}'):
            return b'0' * 40 + b'\n'
        return git(root, *args)
    monkeypatch.setattr(F, '_git', swapped_tree)
    assert not F.exact_blobs_ok()

    def extra_changed(root, *args):
        raw = git(root, *args)
        return raw + b'app/unreviewed_writer.py\n' if args[:2] == ('diff', '--name-only') else raw
    monkeypatch.setattr(F, '_git', extra_changed)
    assert not F.exact_blobs_ok()

    def untracked_executable(root, *args):
        raw = git(root, *args)
        return raw + b'frontend/src/app/evil.tsx\ntools/run_me.sh\n' if args[:2] == ('ls-files', '--others') else raw
    monkeypatch.setattr(F, '_git', untracked_executable)
    assert not F.exact_blobs_ok()


@pytest.mark.parametrize('kind', ['unowned-pin-moved', 'moved-pin-not-ours', 'history-changed', 'extra-key', 'pin-removed'])
def test_followed_manifest_tampering_is_refused(kind, monkeypatch):
    reader = F._read
    target = F.WSV2_CORE_MANIFEST

    def tampered(root, path, ref):
        raw = reader(root, path, ref)
        if path == target and ref is None:
            d = json.loads(raw)
            if kind == 'unowned-pin-moved':
                d['source_blobs']['frontend/src/app/WorkspaceView.tsx'] = '1' * 40          # a pin the cohort never delegated
            elif kind == 'moved-pin-not-ours':
                d['source_blobs']['frontend/src/app/RunFailureNotice.tsx'] = '2' * 40       # delegated path, but not this cohort's exact pin
            elif kind == 'history-changed':
                d['historical_source_blobs']['8a74fcb5cd57e470cf83a458bd165ea14ad394fb']['static/react/finco-react.js'] = '3' * 40
            elif kind == 'extra-key':
                d['unreviewed_authority'] = True
            else:
                d['source_blobs'].pop('frontend/src/app/WorkspaceView.tsx')
            return json.dumps(d).encode()
        return raw
    monkeypatch.setattr(F, '_read', tampered)
    assert not F.exact_blobs_ok()


def test_unrelated_predecessor_manifest_repin_is_refused(monkeypatch):
    unrelated = 'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json'
    assert unrelated not in F.OWNED_PATHS and not F.allowed_path(unrelated)
    git = F._git

    def changed(root, *args):
        raw = git(root, *args)
        return raw + (unrelated + '\n').encode() if args[:2] == ('diff', '--name-only') else raw
    monkeypatch.setattr(F, '_git', changed)
    assert not F.exact_blobs_ok()


def test_delegation_is_one_literal_pair_to_the_exact_pin_only():
    path = 'frontend/src/app/RunFailureNotice.tsx'
    pin = F.manifest()['source_blobs'][path]
    assert F.predecessor_repin(F.WSV2_CORE_MANIFEST, path, pin)
    assert not F.predecessor_repin(F.WSV2_CORE_MANIFEST, path, '0' * 40)                       # forged pin
    assert not F.predecessor_repin(F.WF04_MANIFEST, path, pin)                                  # other manifest
    assert not F.predecessor_repin(F.WSV2_CORE_MANIFEST, 'frontend/src/app/WorkspaceView.tsx', '0' * 40)
    assert not F.predecessor_repin(F.WSV2_CORE_MANIFEST, 'frontend/src/app/NewUnreviewed.tsx', pin)


def test_unregistered_or_broken_cohort_widens_nothing(monkeypatch, tmp_path):
    assert not F.exact_blobs_ok(tmp_path) and not F.valid(tmp_path)                            # no repository: fail closed
    monkeypatch.setattr(C, 'COHORT_MODULES', tuple(n for n in C.COHORT_MODULES if n != F.__name__))
    assert not C.valid()                                                                         # its owned paths are then unreviewed
    monkeypatch.setattr(C, 'COHORT_MODULES', C.COHORT_MODULES + (F.__name__,))
    reader = F._read

    def broken(root, path, ref):
        if path == F.MANIFEST:
            raise FileNotFoundError(path)
        return reader(root, path, ref)
    monkeypatch.setattr(F, '_read', broken)
    assert not F.exact_blobs_ok() and F.manifest() == {}


def test_older_guards_refuse_when_the_wf06a_cohort_is_missing_or_forged(monkeypatch):
    from tests import wf03_lifecycle_scope as W3, wf04_scope as W4, wsv2_core_scope as W2
    assert W3.exact_blobs_ok() and W4.exact_blobs_ok() and W2.exact_blobs_ok()
    path = 'frontend/src/app/InputsGuide.tsx'
    for guard in (lambda: W2._wf06a_allows(path, W2.ROOT, None), lambda: W3._wf06a_allows(path, W3.ROOT, None),
                  lambda: W4._downstream_allows(path, W4.ROOT, None)):
        assert guard()
    monkeypatch.setattr(F, 'exact_blobs_ok', lambda *a, **k: False)
    assert not W2._wf06a_allows(path, W2.ROOT, None) and not W3._wf06a_allows(path, W3.ROOT, None)
    assert not W4._downstream_allows(path, W4.ROOT, None) and not W3._wf06a_repin(F.WSV2_CORE_MANIFEST, 'frontend/src/app/RunFailureNotice.tsx', '0' * 40, W3.ROOT, None)

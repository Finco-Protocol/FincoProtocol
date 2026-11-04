"""CI V4 exact-source cohort: positive state and tamper negatives on a REAL private git worktree (no mocks)."""
import json
import os
import subprocess

import pytest

from tests import ci_v4_scope as V


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    path = tmp_path_factory.mktemp('ci-v4-wt') / 'wt'
    _git(V.ROOT, 'worktree', 'add', '--detach', str(path), 'HEAD')
    # The worktree starts from the committed HEAD; carry the evaluated working-tree state of the owned files into it.
    for p in sorted(V.OWNED_PATHS | {V.MANIFEST}):
        src = V.ROOT / p
        if src.exists():
            (path / p).parent.mkdir(parents=True, exist_ok=True)
            (path / p).write_bytes(src.read_bytes())
    _git(path, 'add', '-A')
    _git(path, '-c', 'user.name=ci', '-c', 'user.email=ci-test-identity', 'commit', '-q', '--allow-empty', '-m', 'snapshot')
    yield path
    _git(V.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def test_positive_literal_closed_set(wt):
    assert V.exact_blobs_ok(wt)
    assert V._owned_ok() and all('*' not in p for p in V.OWNED_PATHS)
    assert all(p.startswith(('.github/workflows/ci_v4_', 'tools/ci_v4_')) for p in V.CI_PATHS)
    assert not any(p.startswith(V.FORBIDDEN_PREFIXES) for p in V.OWNED_PATHS)
    assert V.protected_blobs() == {}
    for stranger in ('.github/workflows/public_safety_and_smoke.yml', 'tools/ci_v3_production.py', 'financial_engine/cfads.py', 'app/auth.py'):
        assert not V.allowed_path(stranger) and not V.ci_owns(stranger, wt)
    assert V.ci_owns('.github/workflows/ci_v4_pr.yml', wt)


def test_existing_workflow_or_v3_tool_edit_is_refused(wt):
    for p in ('.github/workflows/public_safety_and_smoke.yml', 'tools/ci_v3_production.py'):
        (wt / p).write_bytes((wt / p).read_bytes() + b'\n')
        assert not V.exact_blobs_ok(wt), p
        _git(wt, 'checkout', '-q', '--', p)


@pytest.mark.parametrize('path', ['.github/workflows/ci_v4_extra.yml', 'tools/ci_v4_extra.py', 'tools/bypass.py'])
def test_untracked_unknown_ci_path_is_refused(wt, path):
    (wt / path).write_text('x\n')
    assert not V.exact_blobs_ok(wt)


def test_engine_change_is_refused(wt):
    p = wt / 'financial_engine' / 'cfads.py'
    p.write_bytes(p.read_bytes() + b'\n')
    assert not V.exact_blobs_ok(wt)


def test_owned_file_drift_is_refused(wt):
    p = wt / 'docs/ci_v4/ci-v4-policy.json'
    p.write_text(p.read_text().replace('"risk"', '"fast"', 1))
    assert not V.exact_blobs_ok(wt)


def test_forged_manifest_is_refused(wt):
    m = wt / V.MANIFEST
    data = json.loads(m.read_text())
    data['source_blobs']['tools/ci_v4_select.py'] = '0' * 40
    m.write_text(json.dumps(data))
    assert not V.exact_blobs_ok(wt)
    data = json.loads((V.ROOT / V.MANIFEST).read_text()); data['base'] = '1' * 40
    m.write_text(json.dumps(data))
    assert not V.exact_blobs_ok(wt)
    data = json.loads((V.ROOT / V.MANIFEST).read_text()); data['source_blobs']['tools/stranger.py'] = '0' * 40
    m.write_text(json.dumps(data))
    assert not V.exact_blobs_ok(wt)


def test_executable_owned_file_is_refused(wt):
    p = wt / 'tools/ci_v4_select.py'
    os.chmod(p, 0o755)
    try:
        assert not V.exact_blobs_ok(wt)
    finally:
        os.chmod(p, 0o644)


def test_supersession_is_bounded_to_the_exact_pin(wt):
    pin = V.manifest(wt)['source_blobs']['tests/u1_scope.py']
    assert V.supersedes('tests/u1_scope.py', pin, wt)
    assert not V.supersedes('tests/u1_scope.py', '0' * 40, wt)
    assert not V.supersedes('tools/ci_v4_select.py', V.manifest(wt)['source_blobs']['tools/ci_v4_select.py'], wt)

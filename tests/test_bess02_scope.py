"""BESS02 closed-source admission and deliberate negative controls."""
from pathlib import Path
import ast
import json
import subprocess
import shutil

import pytest
from tests import bess02_scope as B, fin_v2_cohorts as C


@pytest.fixture(scope='module')
def candidate_tree(tmp_path_factory):
    root = tmp_path_factory.mktemp('bess02-governance')/'repo'
    subprocess.check_call(['git', 'clone', '-q', '--no-hardlinks', str(B.ROOT), str(root)])
    for path in B.OWNED_PATHS | {B.MANIFEST}:
        target = root/path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(B.ROOT/path, target)
    return root


def test_registered_candidate_and_full_predecessor_chain():
    from tests import post432_l01_l02_scope as L, onaccept01_scope as A, on_bess01_scope as P
    assert B.__name__ in C.COHORT_MODULES
    with C.call_scope():
        assert B.signature_ok() and B.exact_blobs_ok()
        assert L.exact_blobs_ok() and A.exact_blobs_ok() and P.exact_blobs_ok()
        assert C.valid()


def test_existing_assertions_and_default_off_product_boundaries_remain_exact():
    path = 'tests/test_ux_pr3b2_scope.py'
    original = subprocess.check_output(['git', 'show', B.BASE + ':' + path], cwd=B.ROOT)
    assertions = lambda raw: [ast.dump(n) for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.Assert)]
    assert assertions((B.ROOT/path).read_bytes()) == assertions(original)
    for path in ('app/workbook/bess_config.py', 'app/product_capability.py',
                 'app/services/project_library_service.py', 'app/services/reference_seed_service.py',
                 'docs/bess_setup/SOURCE_SUCCESSOR.json', 'docs/onaccept01/SOURCE_SUCCESSOR.json',
                 'docs/react_migration/post432_l01_l02/SOURCE_SUCCESSOR.json'):
        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + path], cwd=B.ROOT)
    from app.workbook import bess_config
    assert bess_config.ACTIVATION_ENABLED is False
    assert not B.protected_blobs()


@pytest.mark.parametrize('kind', ['source_byte', 'source_mode', 'symlink', 'wrong_pin', 'wrong_base',
                                  'wrong_tree', 'wrong_base_blob', 'unknown_path', 'foreign_history'])
def test_tamper_is_refused_without_widening_authority(kind, candidate_tree):
    root = candidate_tree
    source = root/'app/services/bess_standalone_candidate.py'
    manifest = root/B.MANIFEST
    history = root/'docs/bess_setup/SOURCE_SUCCESSOR.json'
    path = manifest if kind in ('wrong_pin', 'wrong_base', 'wrong_tree', 'wrong_base_blob') else history if kind == 'foreign_history' else source
    raw, mode = path.read_bytes(), path.stat().st_mode
    extra = root/'app/bess02_unreviewed.py'
    try:
        if kind in ('source_byte', 'foreign_history'):
            path.write_bytes(raw + b'\n')
        elif kind == 'source_mode':
            path.chmod(mode | 0o111)
        elif kind == 'symlink':
            path.unlink()
            path.symlink_to(root/'app/workbook/bess_config.py')
        elif kind == 'unknown_path':
            extra.write_text('unreviewed = True\n')
        else:
            data = json.loads(raw)
            if kind == 'wrong_pin':
                data['source_blobs']['app/services/bess_standalone_candidate.py'] = '0'*40
            elif kind == 'wrong_base':
                data['base'] = '0'*40
            elif kind == 'wrong_tree':
                data['base_tree'] = '0'*40
            else:
                data['base_blobs']['tests/fin_v2_cohorts.py'] = '0'*40
            path.write_text(json.dumps(data) + '\n')
        assert not B.exact_blobs_ok(root)
    finally:
        if path.is_symlink():
            path.unlink()
        path.write_bytes(raw)
        path.chmod(mode)
        if extra.exists():
            extra.unlink()
    assert B.exact_blobs_ok(root)


def test_missing_registration_old_ref_and_dropped_pin_refuse(monkeypatch, candidate_tree):
    root = candidate_tree
    monkeypatch.setattr(C, 'COHORT_MODULES', tuple(n for n in C.COHORT_MODULES if n != B.__name__))
    assert not B.signature_ok(root)
    monkeypatch.undo()
    assert not B.exact_blobs_ok(root, ref=B.BASE)
    path = root/B.MANIFEST
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
        data['source_blobs'].pop('tests/test_bess_standalone_candidate.py')
        path.write_text(json.dumps(data) + '\n')
        assert not B.signature_ok(root)
    finally:
        path.write_bytes(raw)
    assert B.exact_blobs_ok(root)

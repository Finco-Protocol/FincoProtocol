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
    from tests import post432_l01_l02_scope as L, onaccept01_scope as A, on_bess01_scope as P, r02_ppa_ux_scope as R
    assert B.__name__ in C.COHORT_MODULES
    with C.call_scope():
        assert B.signature_ok() and B.exact_blobs_ok()
        assert L.exact_blobs_ok() and A.exact_blobs_ok() and P.exact_blobs_ok() and R.exact_blobs_ok()
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


def test_f01_generated_artifacts_are_inert_and_never_source_authority(candidate_tree, tmp_path):
    """The existing finite F01 data validator admits outputs, never code or drift."""
    root = candidate_tree
    evidence = root/'evidence'
    assert not evidence.exists()
    financial = evidence/'financial'
    financial.mkdir(parents=True)
    attestation = evidence/'source.json'
    data = financial/'solar-rate-5.6.json'
    source = root/'app/services/bess_standalone_candidate.py'
    source_bytes = source.read_bytes()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    correct = json.dumps({'head': head, 'tree': tree}) + '\n'
    try:
        attestation.write_text(correct)
        data.write_text('{"synthetic":true}\n')
        assert B.exact_blobs_ok(root)
        assert not B.allowed_path('evidence/source.json', root)
        assert 'evidence/source.json' not in B.manifest(root)['source_blobs']
        attestation.write_text(json.dumps({'head': '0'*40, 'tree': tree}) + '\n')
        assert not B.exact_blobs_ok(root)
        attestation.write_text(correct)
        source.write_bytes(source_bytes + b'\n')
        assert not B.exact_blobs_ok(root)
        source.write_bytes(source_bytes)
        for name in ('unreviewed.py', 'unreviewed.json'):
            unknown = financial/name
            unknown.write_text('{}\n')
            assert not B.exact_blobs_ok(root)
            unknown.unlink()
        mode = data.stat().st_mode
        data.chmod(mode | 0o111)
        assert not B.exact_blobs_ok(root)
        data.chmod(mode)
        data.unlink()
        data.symlink_to(source)
        assert not B.exact_blobs_ok(root)
        data.unlink()
        data.write_text('{}\n')
        # Even a finite artifact name may not escape through a directory link.
        data.unlink()
        financial.rmdir()
        target = tmp_path/'outside'
        target.mkdir()
        (target/'solar-rate-5.6.json').write_text('{}\n')
        financial.symlink_to(target, target_is_directory=True)
        assert not B.exact_blobs_ok(root)
        financial.unlink()
        financial.mkdir()
        data.write_text('{}\n')
        assert B.exact_blobs_ok(root)
    finally:
        source.write_bytes(source_bytes)
        shutil.rmtree(evidence)
    assert B.exact_blobs_ok(root)


def test_accepted_r02_product_and_historical_manifest_are_unchanged():
    from tests import r02_ppa_ux_scope as R
    paths = R.SOURCE_PATHS | {R.MANIFEST, 'frontend/src/app/workflow/PPAEditorView.tsx',
                            'tests/onaccept01_scope.py', 'tests/tax_reference_registry_scope.py'}
    from tests import f03_financing_scope as G
    for path in sorted(paths):
        if path in G.SOURCE_PATHS and G.signature_ok():     # one reviewed F03 successor of the shared bundle, exactly at its pinned blob
            assert B._blob((B.ROOT/path).read_bytes()) == G.manifest()['source_blobs'][path]
            continue
        assert (B.ROOT/path).read_bytes() == subprocess.check_output(['git', 'show', B.BASE + ':' + path], cwd=B.ROOT)
    registry = subprocess.check_output(['git', 'show', B.BASE + ':tests/fin_v2_cohorts.py'], cwd=B.ROOT)
    accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body
                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'COHORT_MODULES')
    from tests import ci_v4_perf_scope as F, f03_financing_scope as G, t01e_remediation_scope as Z
    own = accepted + ('tests.bess02_scope',)
    # Exactly four states: the accepted BESS-only tail; one reviewed CI-performance successor; that successor followed by exactly one
    # reviewed F03 successor; that followed by exactly one reviewed T01-E successor, each behind a complete signature.
    assert (C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())
            or (C.COHORT_MODULES == own + (F.__name__, G.__name__) and F.signature_ok() and G.signature_ok())
            or (C.COHORT_MODULES == own + (F.__name__, G.__name__, Z.__name__) and F.signature_ok() and G.signature_ok()
                and Z.signature_ok()))
    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope')


def test_r02_outer_read_scope_shares_successor_memo_and_drops_it_before_mutation(candidate_tree, monkeypatch):
    """Identical checks run once per outer read; later reads see every mutation."""
    from tests import r02_ppa_ux_scope as R, post432_l01_l02_scope as L
    root = candidate_tree
    real = B._exact
    evaluations = []
    def counted(*args, **kwargs):
        evaluations.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(B, '_exact', counted)
    with R.scoped():
        for _ in range(3):
            assert L.signature_ok(root) and R.signature_ok(root) and B.signature_ok(root)
    assert len(evaluations) == 1
    with R.scoped():
        assert B.signature_ok(root)
    assert len(evaluations) == 2  # a closed scope never attests a later read
    path = root/'app/services/bess_standalone_candidate.py'
    raw, mode = path.read_bytes(), path.stat().st_mode
    evidence = root/'evidence'
    try:
        path.write_bytes(raw + b'\n')
        with R.scoped():
            assert not B.signature_ok(root) and not L.signature_ok(root)
        path.write_bytes(raw)
        path.chmod(mode | 0o111)
        with R.scoped():
            assert not B.signature_ok(root)
        path.chmod(mode)
        evidence.mkdir()
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
        attestation = evidence/'source.json'
        attestation.write_text(json.dumps({'head': head, 'tree': tree}) + '\n')
        with R.scoped():
            assert B.exact_blobs_ok(root)
        attestation.write_text(json.dumps({'head': '0'*40, 'tree': tree}) + '\n')
        with R.scoped():
            assert not B.exact_blobs_ok(root)
        attestation.unlink()
        foreign = evidence/'unreviewed.py'
        foreign.write_text('x=1\n')
        with R.scoped():
            assert not B.exact_blobs_ok(root)
    finally:
        path.write_bytes(raw)
        path.chmod(mode)
        if evidence.exists():
            shutil.rmtree(evidence)
    with R.scoped():
        assert B.exact_blobs_ok(root)


def test_one_preview_service_successor_is_exact_and_all_routes_and_activation_stay_frozen():
    from tests import on_bess01_scope as P
    path = 'app/services/bess_setup_preview.py'
    assert B.SUPERSEDED_SOURCE_PATHS == {path}
    assert path in B.SOURCE_PATHS and path in B.SUPERSEDED
    recorded = B.manifest()
    assert recorded['base_blobs'][path] == subprocess.check_output(
        ['git', 'rev-parse', B.BASE + ':' + path], cwd=B.ROOT, text=True).strip()
    with C.call_scope():
        assert P.exact_blobs_ok() and B.exact_blobs_ok() and C.valid()
        assert P.supersedes(path, recorded['source_blobs'][path])
        assert not P.supersedes(path, '0'*40)
        assert C.matches(path, (B.ROOT/path).read_bytes())
    for protected in ('app/v2/bess_setup_router.py', 'app/v2/react_poc_router.py',
                      'app/workbook/bess_config.py', 'app/services/project_library_service.py',
                      'app/services/reference_seed_service.py', 'app/product_capability.py'):
        assert protected not in B.SOURCE_PATHS
        assert (B.ROOT/protected).read_bytes() == subprocess.check_output(
            ['git', 'show', B.BASE + ':' + protected], cwd=B.ROOT)

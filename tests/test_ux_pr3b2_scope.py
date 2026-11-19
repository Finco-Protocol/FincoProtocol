"""Exact current source, forbidden mutations, registry and immutable historical lineage."""
import json
import os
import subprocess
import pytest
from tests import ux_pr3b2_scope as F, ux_pr3b1_scope as E, fin_v2_cohorts as C

_LATER_SOURCES = {
    'tests.ci_v4_p0_scope': (
        '.github/workflows/ci_perf_guard.yml', '.github/workflows/ci_v4_full.yml',
        'tools/ci_full_parallel.py', 'tools/ci_perf_guard.py',
    ),
    'tests.f03_financing_scope': (
        '.github/workflows/ci_v4_f01_job.yml', '.github/workflows/finval_f01_acceptance.yml',
        'app/v2/f02_financing_period_evidence.py', 'app/v2/react_financing.py',
    ),
    'tests.ci_v5_gate_scope': (
        '.github/workflows/ci_v5_gate.yml', 'tools/ci_v5_candidate.py',
        'tools/ci_v5_epoch.py', 'tools/ci_v5_shadow.py',
    ),
    'tests.ci_v5_hardening_scope': ('.github/workflows/ci_v5_shadow.yml', 'tools/ci_v5_b5.py'),
    'tests.t01e_remediation_scope': ('tax_reference_registry/remediation.py',),
}


def _later_pins(root, ref=None):
    from pathlib import Path
    root = Path(root)
    recognized = set()
    for cohort in C.cohorts():
        paths = _LATER_SOURCES.get(cohort.__name__, ())
        if not paths or not cohort.exact_blobs_ok(root, ref):
            continue
        pins = cohort.manifest(root, ref).get('source_blobs', {})
        subject = ref or 'HEAD'
        rows = subprocess.check_output(['git', 'ls-tree', subject, '--', *paths], cwd=root, text=True)
        entries = dict(row.split('\t', 1)[::-1] for row in rows.splitlines())
        for path in paths:
            blob = pins.get(path)
            file = root / path
            if not blob or entries.get(path) != f'100644 blob {blob}':
                continue
            if ref is None and (not file.is_file() or file.is_symlink() or file.stat().st_mode & 0o111
                                or cohort._blob(file.read_bytes()) != blob):
                continue
            recognized.add(path)
    return recognized


def test_current_registered_cohort_and_unchanged_financial_sources():
    with C.call_scope():
        assert F.exact_blobs_ok() and E.exact_blobs_ok() and C.valid()
    assert F.__name__ in C.COHORT_MODULES
    assert os.environ.get('FINCO_SAVE_ALL_PROFILE_ENABLED','0')=='0'
    changed=subprocess.check_output(['git','diff','--name-only',F.BASE],cwd=F.ROOT,text=True).splitlines()
    try:
        from tests import tax_reference_registry_scope as T
        t01d=T.SOURCE_PATHS if T.exact_blobs_ok() else frozenset()   # the one bounded successor: its exact, literal, pinned package files only
    except ImportError:
        t01d=frozenset()
    from tests import on_bess01_scope as B
    t01d = t01d | (B.APP_PATHS if B.exact_blobs_ok() else frozenset())
    from tests import post432_l01_l02_scope as L
    t01d = t01d | (L.SOURCE_PATHS if L.exact_blobs_ok() else frozenset())      # post-#434 L01/L02: exactly its two pinned presentation sources, only while that cohort is exact
    from tests import bess02_scope as N
    t01d = t01d | (N.SOURCE_PATHS if N.exact_blobs_ok() else frozenset())
    with C.call_scope():
        t01d |= _later_pins(F.ROOT)
    assert not any(p.startswith(('app/','financial_engine/','finco_core/','domain/','.github/','tools/','revenue_reference_core/','tax_reference_registry/')) and p not in t01d for p in changed)
    old=subprocess.check_output(['git','show',F.BASE+':'+E.MANIFEST],cwd=F.ROOT)
    assert (F.ROOT/E.MANIFEST).read_bytes()==old
    for p in ('frontend/src/app/editing/wsv2Extensions.tsx', 'frontend/src/app/editing/saveAll.ts', 'frontend/src/app/editing/pendingEdits.ts'):
        assert (F.ROOT/p).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+p],cwd=F.ROOT)


@pytest.mark.parametrize('path', [
    '.github/workflows/unsigned.yml', 'tools/unsigned.py', 'financial_engine/unsigned.py',
])
def test_unreviewed_financial_and_ci_paths_have_no_successor_pin(path):
    with C.call_scope():
        if path in _later_pins(F.ROOT):
            pytest.fail(f'unreviewed path has a successor pin: {path}')

@pytest.mark.parametrize('kind',['byte','foreign_discard_bridge','mode','symlink','manifest','base','tree','base_blob','unrelated','protected','registration'])
def test_source_and_scope_tamper_fail_closed(kind):
    source=F.ROOT/'frontend/src/app/financing/pr3b2/blockContract.ts'
    p=F.ROOT/F.MANIFEST if kind in ('manifest','base','tree','base_blob') else F.ROOT/'tests/fin_v2_cohorts.py' if kind=='registration' else F.ROOT/'frontend/src/app/editing/wsv2Extensions.tsx' if kind=='foreign_discard_bridge' else source
    raw=p.read_bytes();mode=p.stat().st_mode
    extra=F.ROOT/('app/pr3b2_unreviewed.py' if kind=='protected' else 'frontend/src/app/financing/pr3b2/unreviewed.ts')
    try:
        if kind in ('byte','foreign_discard_bridge','registration'):p.write_bytes(raw+b'\n')
        elif kind=='mode':p.chmod(mode|0o111)
        elif kind=='symlink':p.unlink();p.symlink_to(F.ROOT/'tests/ux_pr3b2_scope.py')
        elif kind in ('unrelated','protected'):extra.write_text('unsigned\n')
        else:
            d=json.loads(raw)
            if kind=='manifest':d['source_blobs']['frontend/src/app/financing/pr3b2/blockContract.ts']='0'*40
            elif kind=='base':d['base']='0'*40
            elif kind=='tree':d['base_tree']='0'*40
            else:d['base_blobs']['static/react/finco-react.js']='0'*40
            p.write_text(json.dumps(d)+'\n')
        assert not F.exact_blobs_ok() and not E.exact_blobs_ok() and not C.valid()
    finally:
        if p.is_symlink():p.unlink()
        p.write_bytes(raw);p.chmod(mode)
        if extra.exists():extra.unlink()
    assert F.exact_blobs_ok()

def test_dropped_registry_wrong_ref_and_forged_committed_ancestry(monkeypatch):
    monkeypatch.setattr(C,'COHORT_MODULES',tuple(n for n in C.COHORT_MODULES if n!=F.__name__))
    assert not F.exact_blobs_ok() and not E.exact_blobs_ok()
    monkeypatch.undo()
    assert not F.exact_blobs_ok(ref=F.BASE)
    tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=F.ROOT,text=True).strip()
    identity = dict(os.environ, GIT_AUTHOR_NAME='FINCO synthetic control', GIT_AUTHOR_EMAIL='synthetic.invalid', GIT_COMMITTER_NAME='FINCO synthetic control', GIT_COMMITTER_EMAIL='synthetic.invalid')
    orphan=subprocess.check_output(['git','commit-tree',tree],input='Synthetic ancestry control\n',text=True,cwd=F.ROOT,env=identity).strip()
    assert not F.exact_blobs_ok(ref=orphan)
    assert F.exact_blobs_ok()

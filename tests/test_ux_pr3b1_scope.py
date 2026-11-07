"""Closed PR3b-1 source authority and inherited RC-UX false-negative controls."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from tests import ux_pr3b1_scope as C, fin_v2_cohorts as registry
from tests.test_rcux_governance import _authenticated_u1_workflow_successor as successor

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = 'frontend/src/app/workflow/workflowShared.tsx'

def test_exact_registered_current_cohort_and_immutable_base():
    assert C.__name__ in registry.COHORT_MODULES
    assert C.exact_blobs_ok()
    assert C.valid()
    assert subprocess.check_output(['git','rev-parse',C.BASE+'^{tree}'],cwd=ROOT,text=True).strip() == C.BASE_TREE
    assert C.SUPERSEDED <= C.OWNED_PATHS
    assert not C.allowed_path('app/v2/unreviewed.py')
    assert not C.supersedes(WORKFLOW, '0'*40)

@pytest.mark.parametrize('kind', ['byte','manifest','mode','unrelated','base_tree','base_blob'])
def test_source_signature_and_closure_fail_closed(kind):
    p = ROOT / ('docs/react_migration/ux_pr2c/UX_PR2C_EXACT_SOURCE.json' if kind=='manifest' else C.MANIFEST if kind in ('base_tree','base_blob') else 'frontend/src/app/financing/pr3b1/runEvidence.ts')
    extra = ROOT / 'frontend/src/app/financing/pr3b1/unreviewed.ts'
    raw = p.read_bytes(); mode=p.stat().st_mode
    try:
        if kind=='byte': p.write_bytes(raw+b'\n')
        elif kind=='mode': p.chmod(mode | 0o111)
        elif kind=='unrelated': extra.write_text('export const unreviewed = true;\n')
        else:
            d=json.loads(raw)
            if kind=='manifest': d['source_blobs']['frontend/src/app/editing/saveAll.ts']='0'*40
            elif kind=='base_tree': d['base_tree']='0'*40
            else: d['base_blobs']['frontend/src/app/WorkspaceView.tsx']='0'*40
            p.write_text(json.dumps(d,indent=2)+'\n')
        assert not C.exact_blobs_ok()
        assert not C.supersedes('static/react/finco-react.js', C.manifest().get('source_blobs',{}).get('static/react/finco-react.js'))
    finally:
        p.write_bytes(raw);p.chmod(mode)
        if extra.exists():extra.unlink()
    assert C.exact_blobs_ok()

def test_deregistered_current_successor_and_wrong_ref_fail_closed(monkeypatch):
    monkeypatch.setattr(registry,'COHORT_MODULES',tuple(n for n in registry.COHORT_MODULES if n!=C.__name__))
    assert not C.exact_blobs_ok()
    assert not C.valid()
    monkeypatch.undo()
    assert not C.exact_blobs_ok(ref=C.BASE)
    assert not C.exact_blobs_ok(ref='HEAD~1000')

def test_historical_rcux_u1_recognition_requires_exact_registered_authority(monkeypatch):
    raw=(ROOT/WORKFLOW).read_text()
    assert successor(WORKFLOW,raw)
    assert not successor(WORKFLOW,raw+'\n')
    assert not successor('frontend/src/app/WorkspaceView.tsx',raw)
    assert not successor(WORKFLOW,raw,ref='3e00acab71ea4c2bd9e7396e5bee609225212623')
    monkeypatch.setattr(registry,'COHORT_MODULES',tuple(n for n in registry.COHORT_MODULES if n!='tests.u1_scope'))
    assert not successor(WORKFLOW,raw)

def test_historical_successor_rejects_forged_manifest_and_altered_working_copy():
    p=ROOT/'docs/react_migration/u1_workbench/SOURCE_SUCCESSOR.json';raw=p.read_bytes();source=(ROOT/WORKFLOW).read_bytes()
    try:
        d=json.loads(raw);d['source_blobs'][WORKFLOW]='0'*40;p.write_text(json.dumps(d)+'\n')
        assert not successor(WORKFLOW,source.decode())
    finally:p.write_bytes(raw)
    try:
        (ROOT/WORKFLOW).write_bytes(source+b'\n')
        assert not successor(WORKFLOW,source.decode())
    finally:(ROOT/WORKFLOW).write_bytes(source)
    assert successor(WORKFLOW,source.decode())

def test_original_rcux_predecessor_state_is_still_admitted():
    from tests import model_mutation_security_successor as S
    sources={p:(ROOT/p).read_text() for p in S.BLOBS}
    sources[WORKFLOW]=subprocess.check_output(['git','cat-file','blob',S.RC_UX_SUCCESSORS[WORKFLOW]],cwd=ROOT,text=True)
    assert not [v for v in S.violations(sources) if v.startswith(WORKFLOW+': unreviewed')]

def test_profile_flag_and_accepted_pr429_sources_unchanged():
    assert os.environ.get('FINCO_SAVE_ALL_PROFILE_ENABLED','0')=='0'
    from app.v2.save_all_commands import profile_enabled
    assert profile_enabled() is False
    for p in ['app/v2/react_capex.py','frontend/src/app/capex/ProfileDraftProvider.tsx','frontend/src/app/editing/pendingEdits.ts','frontend/src/app/editing/saveAll.ts']:
        assert (ROOT/p).read_bytes()==subprocess.check_output(['git','show',C.BASE+':'+p],cwd=ROOT)


def test_ux1_mvp_historical_recognition_is_also_exact_and_registered(monkeypatch):
    from tests.test_rcux_governance import _authenticated_ux1_mvp_successor as accept
    path='tests/model_react_mvp_acceptance.py';raw=(ROOT/path).read_text()
    assert accept(path,raw)
    assert not accept(path,raw+'\n')
    assert not accept(WORKFLOW,raw)
    assert not accept(path,raw,ref=C.BASE+'~1000')
    monkeypatch.setattr(registry,'COHORT_MODULES',tuple(n for n in registry.COHORT_MODULES if n!='tests.ux_pr1_scope'))
    assert not accept(path,raw)


def test_forged_ancestry_and_committed_mode_are_rejected_with_exact_source(tmp_path):
    # Detached Git objects only: no branch/ref/index/history rewrite or trigger commit.
    env={**os.environ,'GIT_AUTHOR_NAME':'Synthetic fixture','GIT_AUTHOR_EMAIL':'synthetic.invalid','GIT_COMMITTER_NAME':'Synthetic fixture','GIT_COMMITTER_EMAIL':'synthetic.invalid'}
    tree=subprocess.check_output(['git','write-tree'],cwd=ROOT,text=True).strip()
    orphan=subprocess.check_output(['git','commit-tree',tree],input='Synthetic ancestry refusal\n',cwd=ROOT,text=True,env=env).strip()
    assert not C.exact_blobs_ok(ref=orphan)  # every signed byte is present; accepted main is not an ancestor
    index=tmp_path/'private-index';env['GIT_INDEX_FILE']=str(index)
    subprocess.check_call(['git','read-tree',tree],cwd=ROOT,env=env)
    subprocess.check_call(['git','update-index','--chmod=+x','frontend/src/app/financing/pr3b1/runEvidence.ts'],cwd=ROOT,env=env)
    mode_tree=subprocess.check_output(['git','write-tree'],cwd=ROOT,text=True,env=env).strip()
    mode_commit=subprocess.check_output(['git','commit-tree',mode_tree,'-p','HEAD'],input='Synthetic mode refusal\n',cwd=ROOT,text=True,env=env).strip()
    assert not C.exact_blobs_ok(ref=mode_commit)  # correct ancestry and source, forged committed executable mode
    assert C.exact_blobs_ok()


def test_signature_only_ci_authority_never_admits_global_drift_or_unknown_ci():
    from tests import ux_pr2b_scope as B
    unrelated=ROOT/'app/v2/react_opex_lines.py';raw=unrelated.read_bytes()
    guard=ROOT/'tools/ci_merge_tree_guard.py';guard_raw=guard.read_bytes()
    try:
        unrelated.write_bytes(raw+b'\n')
        assert C.signature_ok() and not C.exact_blobs_ok() and not C.valid()
        assert B.ci_authority_ok() and B.ci_owns('tools/ci_merge_tree_guard.py')
        assert not B.exact_blobs_ok() and not B.ci_owns('tools/ci_v4_unknown.py')
        guard.write_bytes(guard_raw+b'\n')
        assert not B.ci_authority_ok() and not B.ci_owns('tools/ci_merge_tree_guard.py')
    finally:
        unrelated.write_bytes(raw);guard.write_bytes(guard_raw)
    assert C.exact_blobs_ok()


def test_signature_only_ci_authority_ignores_foreign_manifest_forgery_but_full_proof_rejects_it():
    from tests import ux_pr2b_scope as B
    foreign=ROOT/'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json'
    raw=foreign.read_bytes()
    try:
        d=json.loads(raw);d['source_blobs']['static/react/finco-react.js']='0'*40
        foreign.write_text(json.dumps(d,indent=2)+'\n')
        assert C.signature_ok() and B.ci_authority_ok()
        assert not C.exact_blobs_ok() and not C.valid() and not B.exact_blobs_ok()
        assert not C.supersedes('static/react/finco-react.js',C.manifest()['source_blobs']['static/react/finco-react.js'])
    finally:foreign.write_bytes(raw)
    assert C.exact_blobs_ok()

"""C06 exact-source closure: real Git objects and adversarial source/map/mode controls."""
from pathlib import Path
import json
import os
import subprocess
import pytest
from tests import c06_cost_workspace_scope as F, fin_v2_cohorts as C
from tests import r04_ppa_scope as R, f03_financing_scope as P

ROOT=Path(__file__).resolve().parents[1]
def git(root,*args):
    return subprocess.check_output(['git','-c','user.name=test','-c','user.email=noreply@users.noreply.github.com','-c','commit.gpgsign=false',*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()

@pytest.fixture(scope='module')
def clone(tmp_path_factory):
    root=tmp_path_factory.mktemp('c06-governance')/'repo'
    git(ROOT,'clone','-q','--no-hardlinks',str(ROOT),str(root))
    return root

class Mutation:
    def __init__(self,root):self.root=root
    def __enter__(self):return self.root
    def __exit__(self,*args):
        git(self.root,'reset','--hard','HEAD');git(self.root,'clean','-fdxq')

def test_exact_source_chain_worktree_and_committed_ref(clone):
    assert F.BASE=='b1c08e2d00fe9933565d253d5cee6e5849b143e1'
    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE
    assert C.COHORT_MODULES in (F.BASE_COHORTS + (F.__name__,), F.BASE_COHORTS + (F.__name__, 'tests.ux_final01_scope'))
    assert C.COHORT_MODULES.count(F.__name__)==1
    for ref in (None,'HEAD'):
        with C.call_scope():
            assert F.signature_ok(clone,ref) and F.exact_blobs_ok(clone,ref)
            assert R.exact_blobs_ok(clone,ref) and P.exact_blobs_ok(clone,ref) and C.valid(clone,ref)
    assert not F.exact_blobs_ok(clone,F.BASE)

def test_literal_closed_paths_and_immutable_predecessor_blobs():
    data=F.manifest()
    assert set(data['source_blobs'])==F.OWNED_PATHS
    assert set(data['base_blobs'])==F.SUPERSEDED
    assert F.MAP_KEYS==(F.REGISTRY,'static/react/finco-react.js','static/react/finco-react.css','tests/u1_scope.py','tests/u2_scope.py','tests/ux_pr3b1_scope.py','tests/test_u2_scope.py','tests/test_ux_pr3b1_scope.py')
    assert not any('*' in p or '..' in p.split('/') or p.startswith(F.FORBIDDEN) for p in F.OWNED_PATHS)
    for path in F.SUPERSEDED:assert data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)
    from tests import ux_final01_scope as UX
    for path in F.HANDOFFS:
        want=UX.expected_handoff(ROOT,path) if UX.signature_ok() and path in UX.HANDOFFS else F.expected_handoff(ROOT,path)
        assert (ROOT/path).read_bytes()==want
    for path in F.FROZEN:assert (ROOT/path).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT)

def test_current_maps_change_only_their_existing_registry_and_js_keys():
    for path in F.CURRENT_MAPS:
        original=json.loads(subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT))
        current=json.loads((ROOT/path).read_text())
        expected=json.loads(F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)
        assert current==expected and set(original)==set(current)
        assert set(original['source_blobs'])==set(current['source_blobs'])
        assert all(original[k]==current[k] for k in original if k!='source_blobs')
        assert {k for k in original['source_blobs'] if original['source_blobs'][k]!=current['source_blobs'][k]}<=set(F.MAP_KEYS)

@pytest.mark.parametrize('path',sorted(F.OWNED_PATHS|{F.MANIFEST}))
def test_worktree_byte_tamper_fails_without_changing_head(clone,path):
    with Mutation(clone):
        before=git(clone,'rev-parse','HEAD')
        f=clone/path;f.write_bytes(f.read_bytes()+b'\n')
        assert git(clone,'rev-parse','HEAD')==before
        with C.call_scope():assert not F.exact_blobs_ok(clone) and not C.valid(clone)
        assert F.exact_blobs_ok(clone,'HEAD')
    assert F.exact_blobs_ok(clone)

@pytest.mark.parametrize('kind',['mode','symlink','delete','unknown','missing_registration','duplicate_registration','reordered_registration','partial_handoff'])
def test_modes_registry_and_closed_diff_are_enforced(clone,kind):
    with Mutation(clone):
        path=clone/'static/react/finco-react.js'
        if kind=='mode':path.chmod(0o755)
        elif kind=='symlink':path.unlink();path.symlink_to(clone/'README.md')
        elif kind=='delete':path.unlink()
        elif kind=='unknown':(clone/'app/f04_unreviewed.py').write_text('unreviewed=True\n')
        elif kind=='partial_handoff':
            path=clone/F.PREDECESSOR;path.write_bytes(subprocess.check_output(['git','show',F.BASE+':'+F.PREDECESSOR],cwd=clone))
        else:
            path=clone/F.REGISTRY;text=path.read_text()
            if kind=='missing_registration':text=text.replace(", 'tests.c06_cost_workspace_scope', 'tests.ux_final01_scope')", ", 'tests.ux_final01_scope')")
            elif kind=='duplicate_registration':text=text.replace("'tests.c06_cost_workspace_scope', 'tests.ux_final01_scope')","'tests.c06_cost_workspace_scope', 'tests.c06_cost_workspace_scope', 'tests.ux_final01_scope')")
            else:text=text.replace("'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope'","'tests.c06_cost_workspace_scope', 'tests.r04_ppa_scope'")
            path.write_text(text)
        with C.call_scope():assert not F.exact_blobs_ok(clone) and not C.valid(clone)
    assert F.exact_blobs_ok(clone)

@pytest.mark.parametrize('kind',['base','tree','source_pin','base_pin','source_mode','base_mode','drop_pin','forged_map_and_pin'])
def test_manifest_and_map_forgery_are_rejected(clone,kind):
    with Mutation(clone):
        path=clone/F.MANIFEST;data=json.loads(path.read_text())
        if kind=='base':data['base']='0'*40
        elif kind=='tree':data['base_tree']='0'*40
        elif kind=='source_pin':data['source_blobs']['static/react/finco-react.js']='0'*40
        elif kind=='base_pin':data['base_blobs'][F.REGISTRY]='0'*40
        elif kind=='source_mode':data['source_modes'][F.REGISTRY]='100755'
        elif kind=='base_mode':data['base_modes'][F.REGISTRY]='100755'
        elif kind=='drop_pin':data['source_blobs'].pop(F.REGISTRY)
        else:
            mp=sorted(F.CURRENT_MAPS)[0];f=clone/mp;f.write_bytes(f.read_bytes()+b'\n')
            data['source_blobs'][mp]=F._blob(f.read_bytes())
        path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
        with C.call_scope():assert not F.signature_ok(clone) and not C.valid(clone)

@pytest.mark.parametrize('path',['static/react/finco-react.js','frontend/src/app/capex/ProfileDraftProvider.tsx',F.REGISTRY,F.MANIFEST])
def test_committed_tamper_is_rejected_in_separate_ref(clone,path):
    with Mutation(clone):
        good=git(clone,'rev-parse','HEAD');f=clone/path;f.write_bytes(f.read_bytes()+b'\n')
        git(clone,'add',path);git(clone,'commit','-qm','adversarial variant');bad=git(clone,'rev-parse','HEAD')
        git(clone,'checkout','-q',good)
        with C.call_scope():
            assert F.exact_blobs_ok(clone,'HEAD')
            assert not F.exact_blobs_ok(clone,bad) and not C.valid(clone,bad)
            assert F.exact_blobs_ok(clone,'HEAD')

@pytest.mark.parametrize('path', sorted(F.APPROVED_SOURCE_BLOBS))
def test_paired_source_and_manifest_pin_forgery_is_not_authorization(clone, path):
    with Mutation(clone):
        f=clone/path;f.write_bytes(f.read_bytes()+b'\n')
        mp=clone/F.MANIFEST;data=json.loads(mp.read_text())
        data['source_blobs'][path]=F._blob(f.read_bytes())
        # Even recomputing every dependent current map and its pin cannot authorize new product bytes.
        for p in F.CURRENT_MAPS:
            raw=F.expected_map(clone,p,data['source_blobs'])
            (clone/p).write_bytes(raw);data['source_blobs'][p]=F._blob(raw)
        mp.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
        with C.call_scope():
            assert not F.signature_ok(clone) and not C.valid(clone)

@pytest.mark.parametrize('path', sorted(F.HANDOFF_PATHS))
def test_one_sided_current_guard_handoff_fails_closed(clone,path):
    with Mutation(clone):
        (clone/path).write_bytes(subprocess.check_output(['git','show',F.BASE+':'+path],cwd=clone))
        with C.call_scope():
            assert not F.signature_ok(clone) and not C.valid(clone)


def test_accepted_ref_preserves_all_preexisting_exact_guards_and_original_code(clone):
    from tests import ux_pr2b_scope as B, ux_pr2c_scope as D, ux_pr3b1_scope as U
    provider='frontend/src/app/capex/ProfileDraftProvider.tsx'
    editor='frontend/src/app/capex/ProfileRowEditor.tsx'
    with C.call_scope():
        assert not F.signature_ok(clone,F.BASE)
        for m in C.cohorts():
            if m.__name__ not in (F.__name__,'tests.ux_final01_scope'):      # the later reviewed UX successor does not exist at the accepted base
                assert m.exact_blobs_ok(clone,F.BASE),m.__name__
        assert B.ci_authority_ok(clone,F.BASE)
        for path in (provider,editor):
            old=git(clone,'rev-parse',F.BASE+':'+path)
            # Original accepted source remains accepted, new source cannot attest the old ref.
            assert B._pr3b1_pin(path,old,clone,F.BASE) or D.manifest(clone,F.BASE)['source_blobs'].get(path)==old or B.manifest(clone,F.BASE)['source_blobs'][path]==old
            assert not B._pr3b1_pin(path,F.manifest()['source_blobs'][path],clone,F.BASE,signature=True)
        assert not U.supersedes('tests/ux_pr3b1_scope.py', F.manifest()['source_blobs']['tests/ux_pr3b1_scope.py'],clone,F.BASE)
    # Execute the historical registry and code too: the new current-head registry must not stand in for old code.
    original=git(clone,'rev-parse','HEAD')
    try:
        git(clone,'checkout','-q','--detach',F.BASE)
        script='from tests import fin_v2_cohorts as C\nwith C.call_scope():\n assert C.valid()\n assert all(m.exact_blobs_ok() for m in C.cohorts())\nprint("ACCEPTED_HISTORICAL_COMPOSITE_PASS")'
        import sys
        result=subprocess.run([sys.executable,'-c',script],cwd=clone,capture_output=True,text=True,check=True)
        assert 'ACCEPTED_HISTORICAL_COMPOSITE_PASS' in result.stdout
    finally:
        git(clone,'checkout','-q',original)


def test_altered_accepted_history_is_rejected_by_old_and_current_guards(clone):
    original=git(clone,'rev-parse','HEAD')
    try:
        git(clone,'checkout','-q','--detach',F.BASE)
        path=clone/'tests/ux_pr2b_scope.py';path.write_bytes(path.read_bytes()+b'\n')
        git(clone,'add','tests/ux_pr2b_scope.py');git(clone,'commit','-qm','altered accepted history')
        bad=git(clone,'rev-parse','HEAD')
        import sys
        script='from tests import fin_v2_cohorts as C, r04_ppa_scope as W\nwith C.call_scope():\n assert not W.signature_ok()\n assert not C.valid()\nprint("ALTERED_HISTORY_REJECTED")'
        result=subprocess.run([sys.executable,'-c',script],cwd=clone,capture_output=True,text=True,check=True)
        assert 'ALTERED_HISTORY_REJECTED' in result.stdout
        git(clone,'checkout','-q',original)
        with C.call_scope():
            assert not R.signature_ok(clone,bad) and not C.valid(clone,bad)
    finally:
        git(clone,'reset','--hard','HEAD');git(clone,'checkout','-q',original)


def test_direct_reviewed_edits_rejects_a_forged_historical_manifest(clone):
    from tests import f03_financing_scope as P
    with Mutation(clone):
        p=clone/P.MANIFEST;d=json.loads(p.read_text());d['source_blobs'][P.REGISTRY]='0'*40
        p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
        with C.call_scope():
            assert not P.reviewed_edits_ok(clone) and not F.signature_ok(clone) and not C.valid(clone)


def test_paired_scope_module_and_pin_forgery_is_rejected(clone):
    with Mutation(clone):
        p=clone/'tests/c06_cost_workspace_scope.py';p.write_bytes(p.read_bytes()+b'\n')
        f=clone/F.MANIFEST;d=json.loads(f.read_text());d['source_blobs']['tests/c06_cost_workspace_scope.py']=F._blob(p.read_bytes())
        f.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
        assert not F.signature_ok(clone) and not F.exact_blobs_ok(clone)

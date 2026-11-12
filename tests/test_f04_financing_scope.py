"""F04 exact-source closure: real Git objects and adversarial source/map/mode controls."""
from pathlib import Path
import json
import os
import subprocess
import pytest
from tests import c06_cost_workspace_scope as C06_APPROVAL
from tests import f04_financing_scope as F, fin_v2_cohorts as C
from tests import r03_ppa_scope as R, f03_financing_scope as P
from tests import r04_ppa_scope as W

ROOT=Path(__file__).resolve().parents[1]
def git(root,*args):
    return subprocess.check_output(['git','-c','user.name=test','-c','user.email=noreply@users.noreply.github.com','-c','commit.gpgsign=false',*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()

@pytest.fixture(scope='module')
def clone(tmp_path_factory):
    root=tmp_path_factory.mktemp('f04-governance')/'repo'
    git(ROOT,'clone','-q','--no-hardlinks',str(ROOT),str(root))
    return root

class Mutation:
    def __init__(self,root):self.root=root
    def __enter__(self):return self.root
    def __exit__(self,*args):
        git(self.root,'reset','--hard','HEAD');git(self.root,'clean','-fdxq')

def test_exact_source_chain_worktree_and_committed_ref(clone):
    assert F.BASE=='7584149f9334ac058cd986188b571c7dd48d538e'
    assert git(ROOT,'rev-parse',F.BASE+'^{tree}')==F.BASE_TREE
    assert (C.COHORT_MODULES[-2:]==('tests.r03_ppa_scope','tests.f04_financing_scope') or (
        C.COHORT_MODULES[-3:]==('tests.r03_ppa_scope','tests.f04_financing_scope','tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope') and W.signature_ok())) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok())
    assert C.COHORT_MODULES.count('tests.f04_financing_scope')==1
    for ref in (None,'HEAD'):
        with C.call_scope():
            assert F.signature_ok(clone,ref) and F.exact_blobs_ok(clone,ref)
            assert R.exact_blobs_ok(clone,ref) and P.exact_blobs_ok(clone,ref) and C.valid(clone,ref)
    assert not F.exact_blobs_ok(clone,F.BASE)

def test_literal_closed_paths_and_immutable_predecessor_blobs():
    data=F.manifest()
    assert set(data['source_blobs'])==F.OWNED_PATHS
    assert set(data['base_blobs'])==F.SUPERSEDED
    assert F.MAP_KEYS==(F.REGISTRY,'static/react/finco-react.js')
    assert not any('*' in p or '..' in p.split('/') or p.startswith(F.FORBIDDEN) for p in F.OWNED_PATHS)
    for path in F.SUPERSEDED:assert data['base_blobs'][path]==git(ROOT,'rev-parse',F.BASE+':'+path)
    for path in F.HANDOFFS:
        authority=V if C06_APPROVAL.signature_ok() and path in C06_APPROVAL.HANDOFFS else W if W.signature_ok() and path in W.HANDOFFS else F      # the latest reviewed substitution of this shared path
        assert (ROOT/path).read_bytes()==authority.expected_handoff(ROOT,path)
    for path in F.FROZEN:
        if path in C06_APPROVAL.HANDOFFS and C06_APPROVAL.signature_ok():
            assert (ROOT/path).read_bytes()==C06_APPROVAL.expected_handoff(ROOT,path)
            assert F._blob((ROOT/path).read_bytes())==C06_APPROVAL.manifest()['source_blobs'][path]
        else:
            assert (ROOT/path).read_bytes()==subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT)

def test_current_maps_change_only_their_existing_registry_and_js_keys():
    for path in F.CURRENT_MAPS:
        original=json.loads(subprocess.check_output(['git','show',F.BASE+':'+path],cwd=ROOT))
        current=json.loads((ROOT/path).read_text())
        expected=json.loads(F.expected_map(ROOT,path,F.effective_pins()))      # the CURRENT pins (a reviewed successor's registry pin wins)
        assert current==expected and set(original)==set(current)
        assert set(original['source_blobs'])==set(current['source_blobs'])
        assert all(original[k]==current[k] for k in original if k!='source_blobs')
        assert {k for k in original['source_blobs'] if original['source_blobs'][k]!=current['source_blobs'][k]}<=set(F.map_keys())

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
            if kind=='missing_registration':text=text.replace(", 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')",", 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')")
            elif kind=='duplicate_registration':text=text.replace("'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')","'tests.f04_financing_scope', 'tests.f04_financing_scope', 'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')")
            else:text=text.replace("'tests.r03_ppa_scope', 'tests.f04_financing_scope'","'tests.f04_financing_scope', 'tests.r03_ppa_scope'")
            path.write_text(text)
        with C.call_scope():assert not F.exact_blobs_ok(clone) and not C.valid(clone)
    assert F.exact_blobs_ok(clone)

@pytest.mark.parametrize('kind',['base','tree','source_pin','base_pin','drop_pin','forged_map_and_pin'])
def test_manifest_and_map_forgery_are_rejected(clone,kind):
    with Mutation(clone):
        path=clone/F.MANIFEST;data=json.loads(path.read_text())
        if kind=='base':data['base']='0'*40
        elif kind=='tree':data['base_tree']='0'*40
        elif kind=='source_pin':data['source_blobs']['static/react/finco-react.js']='0'*40
        elif kind=='base_pin':data['base_blobs'][F.REGISTRY]='0'*40
        elif kind=='drop_pin':data['source_blobs'].pop(F.REGISTRY)
        else:
            mp=sorted(F.CURRENT_MAPS)[0];f=clone/mp;f.write_bytes(f.read_bytes()+b'\n')
            data['source_blobs'][mp]=F._blob(f.read_bytes())
        path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
        with C.call_scope():assert not F.signature_ok(clone) and not C.valid(clone)

@pytest.mark.parametrize('path',['static/react/finco-react.js','frontend/src/app/financing/pr3b1/debtProvenanceModel.ts',F.REGISTRY,F.MANIFEST])
def test_committed_tamper_is_rejected_in_separate_ref(clone,path):
    with Mutation(clone):
        good=git(clone,'rev-parse','HEAD');f=clone/path;f.write_bytes(f.read_bytes()+b'\n')
        git(clone,'add',path);git(clone,'commit','-qm','adversarial variant');bad=git(clone,'rev-parse','HEAD')
        git(clone,'checkout','-q',good)
        with C.call_scope():
            assert F.exact_blobs_ok(clone,'HEAD')
            assert not F.exact_blobs_ok(clone,bad) and not C.valid(clone,bad)
            assert F.exact_blobs_ok(clone,'HEAD')

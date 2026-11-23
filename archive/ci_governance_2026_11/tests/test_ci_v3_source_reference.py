"""Source/reference boundaries; all invented service responses are SYNTHETIC."""
import json
from pathlib import Path
import pytest
from tools import ci_v3_source_reference as ref
from tools.ci_v3_schema import ContractError,read_json,seal,write_json
from tools.ci_v3_production import inventory


def snapshot():
 report={'selected':['tests/test_original.py::test_kept'],'collection':{'skips':[]}}
 return seal({'schema':1,'kind':'ci-v3-source-reference','report':report})


def test_new_nodes_are_explicit_and_no_existing_node_disappears():
 old=snapshot();ids=['tests/test_original.py::test_kept','tests/test_added.py::test_new']
 inv=inventory({'collection':{'source':{'head':'a'*40,'tree':'b'*40},'nodes':sorted(ids),'skips':[]}})
 changes=ref.reconciliation(old,inv)
 assert changes['added']==['tests/test_added.py::test_new'] and changes['removed']==[]
 assert changes['reference_digest']==old['digest'] and changes['new_nonpass_policy']=='reject'
 inv=inventory({'collection':{'source':{'head':'a'*40,'tree':'b'*40},'nodes':[ids[1]],'skips':[]}})
 with pytest.raises(ContractError,match='original nodes removed'):ref.reconciliation(old,inv)


def test_changed_collection_skip_requires_authority():
 old=snapshot();inv={'nodes':[{'nodeid':old['report']['selected'][0]}],'collection_skips':[{'nodeid':'tests/test_lost.py','reason':'missing dependency'}]}
 with pytest.raises(ContractError,match='collection skip change'):ref.reconciliation(old,inv)


@pytest.mark.parametrize('path',['requirements.txt','constraints.txt','docs/ci_v3/phase4/runtime/python.lock'])
def test_changed_dependency_inputs_require_matching_reviewed_runtime_contract(tmp_path,path):
 root=Path(__file__).resolve().parents[1];pins=read_json(root/'docs/ci_v3/phase4/runtime/inputs.json')
 for name in pins:
  p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/name).read_bytes())
 p=tmp_path/'docs/ci_v3/phase4/runtime/inputs.json';write_json(p,pins)
 assert ref.runtime_inputs_match(tmp_path)
 f=tmp_path/path;f.write_bytes(f.read_bytes()+b'\n# changed source dependency input\n')
 assert not ref.runtime_inputs_match(tmp_path)


def test_source_base_cannot_be_replaced_by_an_older_event_source(tmp_path,monkeypatch):
 event=tmp_path/'event.json';write_json(event,{'pull_request':{'base':{'sha':'b'*40}}})
 monkeypatch.setenv('GITHUB_EVENT_PATH',str(event));monkeypatch.setenv('FINCO_PRODUCTION_BASE','a'*40)
 with pytest.raises(ContractError,match='authenticated event'):ref.source_base()


@pytest.mark.parametrize('attack',['missing','failed','foreign','wrong-workflow'])
def test_reference_requires_successful_accepted_source_run(tmp_path,monkeypatch,attack):
 base={'head':'a'*40,'tree':'b'*40}
 monkeypatch.setattr(ref,'git',lambda *args:'')
 run={'id':1,'head_sha':base['head'],'run_attempt':1,'path':'.github/workflows/public_safety_and_smoke.yml','conclusion':'success','head_repository':{'full_name':ref.REPO}}
 if attack=='failed':run['conclusion']='failure'
 elif attack=='foreign':run['head_repository']['full_name']='SYNTHETIC/fork'
 elif attack=='wrong-workflow':run['path']='other.yml'
 class Service:
  def listing(self,*args):return [] if attack=='missing' else [run]
 with pytest.raises(ContractError,match='no successful accepted-source'):ref.authenticate_reference(Service(),base,tmp_path)

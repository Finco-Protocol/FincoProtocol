"""Independent exact-content negatives; synthetic fixture pins are never owner approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
import r_live_lifecycle_content_authority as authority

REPO=Path(__file__).resolve().parents[1]


def git(repo,*args):
    return subprocess.check_output(['git',*args],cwd=repo,text=True).strip()


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    repo=tmp_path/'fixture';repo.mkdir()
    git(repo,'init','-b','main');git(repo,'config','user.name','Synthetic Governance Fixture')
    git(repo,'config','user.email','noreply@users.noreply.github.com')
    (repo/'README').write_text('SYNTHETIC fixture; not owner authority')
    git(repo,'add','.');git(repo,'commit','-m','synthetic original review')
    original={'head':git(repo,'rev-parse','HEAD'),'tree':git(repo,'rev-parse','HEAD^{tree}')}
    git(repo,'update-ref','refs/remotes/origin/main','HEAD')
    for name in authority.APPROVED_LIFECYCLE_BLOBS:
        dest=repo/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((REPO/name).read_bytes())
    git(repo,'add','.');git(repo,'commit','-m','synthetic corrected source')
    corrected={'head':git(repo,'rev-parse','HEAD'),'tree':git(repo,'rev-parse','HEAD^{tree}')}
    monkeypatch.setattr(authority,'ORIGINAL_REVIEWED_SOURCE',original)
    monkeypatch.setattr(authority,'CORRECTED_PROTECTED_SOURCE',corrected)
    monkeypatch.setattr(authority,'OWNER_APPROVAL_REFERENCE','SYNTHETIC-ISOLATED-TEST-ONLY')
    monkeypatch.setattr(authority,'APPROVAL_ORIGIN',{'kind':'SYNTHETIC-TEST-ONLY','github_signed_attestation':False})
    record=deepcopy(authority.expected_approval());raw=(json.dumps(record,sort_keys=True)+'\n').encode()
    path=repo/authority.APPROVAL_PATH;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    git(repo,'add','.');git(repo,'commit','-m','synthetic governance record')
    monkeypatch.setattr(authority,'OWNER_APPROVAL_SHA256',hashlib.sha256(raw).hexdigest())
    return repo,path,record


def test_committed_exact_approved_pair_and_reference():
    assert authority.OWNER_APPROVAL_REFERENCE=='conversation:2026-10-22:PR346:Correction-D:section-1'
    assert authority.APPROVED_LIFECYCLE_BLOBS=={
        'app/radar_rwa/r_live_snapshot_store.py':'4179c296c803f42040b2811dc70ef55a1cdfa1d0',
        'app/radar_rwa/r_live_warming.py':'563c1a256886f7b26af21ac63e121216f908c840'}
    for name,pin in authority.APPROVED_LIFECYCLE_BLOBS.items():
        assert git(REPO,'rev-parse','HEAD:'+name)==pin
        assert authority.reviewed_lifecycle_content_matches(name,repo=REPO)
    assert authority.ORIGINAL_REVIEWED_SOURCE['head']!=authority.CORRECTED_PROTECTED_SOURCE['head']
    assert git(REPO,'rev-parse',authority.CORRECTED_PROTECTED_SOURCE['head']+'^{tree}')==authority.CORRECTED_PROTECTED_SOURCE['tree']
    assert not authority.APPROVAL_ORIGIN['github_signed_attestation']


def test_fixture_exact_content_passes(fixture):
    repo,_,_=fixture
    assert all(authority.reviewed_lifecycle_content_matches(name,repo=repo) for name in authority.APPROVED_LIFECYCLE_BLOBS)


@pytest.mark.parametrize('name',sorted(authority.APPROVED_LIFECYCLE_BLOBS))
@pytest.mark.parametrize('attack',['byte-committed','byte-working','missing-committed','missing-working','symlink'])
def test_either_source_mutation_revokes_entire_pair(fixture,name,attack,tmp_path):
    repo,_,_=fixture;path=repo/name
    if attack.startswith('byte'):path.write_bytes(path.read_bytes()+b'\n')
    elif attack.startswith('missing'):path.unlink()
    else:
        target=tmp_path/'same-bytes';target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
    if attack.endswith('committed'):git(repo,'add','-A');git(repo,'commit','-m','unapproved source')
    assert all(not authority.reviewed_lifecycle_content_matches(p,repo=repo) for p in authority.APPROVED_LIFECYCLE_BLOBS)


def test_superseded_warming_blob_not_recognized(fixture):
    repo,_,_=fixture;name='app/radar_rwa/r_live_warming.py'
    old=subprocess.check_output(['git','show','a0d243c7d9c88d16990da9115e00ed00e3ad8160:'+name],cwd=REPO)
    assert authority._blob(old)=='9635b99e1d06f91b701dc8c4b2ffda97be839fea'
    (repo/name).write_bytes(old);git(repo,'add','.');git(repo,'commit','-m','superseded blob')
    assert not authority.reviewed_lifecycle_content_matches(name,repo=repo)


@pytest.mark.parametrize('attack',['missing','working-byte','committed-byte','reference','stale-source','blob-map',
    'unapproved','runtime_activation_authorized','workflow_deployment_authorized','hosted_shadow_authorized',
    'image_publication_authorized','phase4_activation_authorized','merge_authorized','duplicate-key','wrong-scope'])
def test_approval_mutations_rejected_even_if_document_hash_is_substituted_in_fixture(fixture,monkeypatch,attack):
    repo,path,record=fixture;name=next(iter(authority.APPROVED_LIFECYCLE_BLOBS))
    if attack=='missing':path.unlink()
    elif attack in ['working-byte','committed-byte']:path.write_bytes(path.read_bytes()+b' ')
    else:
        if attack=='reference':record['Financial']['reference']='forged-or-stale-reference'
        elif attack=='stale-source':record['corrected_protected_source']={'head':'f'*40,'tree':'e'*40}
        elif attack=='blob-map':record['blobs'][name]='f'*40
        elif attack=='unapproved':record['Financial']['approved']=False
        elif attack=='wrong-scope':record['scope']='app/radar_rwa/**'
        elif attack!='duplicate-key':record[attack]=True
        raw=json.dumps(record,sort_keys=True).encode()
        if attack=='duplicate-key':raw=raw[:-1]+b',"schema":1}'
        path.write_bytes(raw)
        # This override is SYNTHETIC and forces semantic checks to run after
        # integrity, proving a document hash alone cannot change its authority.
        monkeypatch.setattr(authority,'OWNER_APPROVAL_SHA256',hashlib.sha256(raw).hexdigest())
    if attack!='working-byte':git(repo,'add','-A');git(repo,'commit','-m','unapproved decision mutation')
    assert not authority.reviewed_lifecycle_content_matches(name,repo=repo)


@pytest.mark.parametrize('attack',['missing-anchor','wrong-anchor-tree','unrelated-target','bad-ref','invalid-repo'])
def test_source_provenance_uncertainty_fails_closed(fixture,monkeypatch,attack,tmp_path):
    repo,path,_=fixture;name=next(iter(authority.APPROVED_LIFECYCLE_BLOBS));ref='HEAD'
    if attack=='missing-anchor':monkeypatch.setattr(authority,'CORRECTED_PROTECTED_SOURCE',{'head':'f'*40,'tree':'e'*40})
    elif attack=='wrong-anchor-tree':monkeypatch.setattr(authority,'CORRECTED_PROTECTED_SOURCE',{**authority.CORRECTED_PROTECTED_SOURCE,'tree':'f'*40})
    elif attack=='unrelated-target':
        tree=git(repo,'rev-parse','HEAD^{tree}')
        ref=git(repo,'commit-tree',tree,'-m','unrelated same-content tree')
    elif attack=='bad-ref':ref='no-such-ref'
    else:repo=tmp_path/'not-a-repo'
    assert not authority.reviewed_lifecycle_content_matches(name,repo=repo,ref=ref)


@pytest.mark.parametrize('name',['app/radar_rwa/new_sibling.py','app/radar_rwa/r_live_warming.py/child',
    'app/radar_rwa/r_live_snapshot_store.py.old','finco_radar/unapproved.py','financial_engine/unapproved.py'])
def test_no_namespace_or_filename_prefix_authority(fixture,name):
    assert not authority.reviewed_lifecycle_content_matches(name,repo=fixture[0])


@pytest.fixture
def three_guards(fixture,monkeypatch):
    import radar_authority_governance as radar
    import r_live_lifecycle_governance as adapter
    import model_v2_governance as model
    import tests.test_ci_acceptance as ci
    repo=fixture[0]
    monkeypatch.setattr(radar,'REPO',repo)
    monkeypatch.setattr(model,'REPO',repo)
    monkeypatch.setattr(adapter,'REPO',repo)
    return repo,adapter,adapter,ci


def test_all_three_original_guard_call_paths_accept_exact_fixture(three_guards):
    repo,finance,model,ci=three_guards
    for name in authority.APPROVED_LIFECYCLE_BLOBS:assert finance.approved_frozen_path(name)
    assert model.model_v2_frozen_violations(list(authority.APPROVED_LIFECYCLE_BLOBS))==[]
    ci._assert_frozen_financial_namespace_authority(repo)


@pytest.mark.parametrize('attack',['one-byte','missing-blob','stale-reference','unexpected-path'])
def test_all_three_original_guard_call_paths_reject_each_attack(three_guards,attack):
    repo,finance,model,ci=three_guards;name=next(iter(authority.APPROVED_LIFECYCLE_BLOBS))
    if attack=='one-byte':(repo/name).write_bytes((repo/name).read_bytes()+b'\n')
    elif attack=='missing-blob':git(repo,'rm',name)
    elif attack=='unexpected-path':
        name='app/radar_rwa/unapproved_sibling.py';(repo/name).write_text('unapproved')
    else:
        path=repo/authority.APPROVAL_PATH;record=json.loads(path.read_text());record['Financial']['reference']='stale'
        path.write_text(json.dumps(record))
    git(repo,'add','-A');git(repo,'commit','-m','unapproved '+attack)
    assert not finance.approved_frozen_path(name)
    assert name in model.model_v2_frozen_violations([name])
    with pytest.raises(AssertionError,match='Permanent hard-deny'):
        ci._assert_frozen_financial_namespace_authority(repo)


def test_historical_authorities_and_original_assertions_preserved():
    import ast
    from v9p2a_odr_successor import HISTORICAL_AUTHORITY_MODULES, WIRING_BLOBS, RC7C_MAIN
    from v10_native_shadow_successor import historical_subject
    # HEAD itself, or - only while HEAD is the recognised V10 successor - its immutable OD-R checkpoint (never relabelled)
    subject=historical_subject()
    for name in HISTORICAL_AUTHORITY_MODULES:
        assert git(REPO,'rev-parse',subject+':'+name)==git(REPO,'rev-parse',RC7C_MAIN+':'+name)
    for name,(_,pin) in WIRING_BLOBS.items():
        assert git(REPO,'rev-parse',subject+':'+name)==pin
    functions={
        'tests/test_ci_acceptance.py':'test_frozen_financial_namespaces_unmodified',
        'tests/test_multi_source_evidence_v2.py':'test_existing_authorities_are_not_modified',
        'tests/test_parallel_stream_frozen_diff.py':'test_ce_no_frozen_production_namespace_modified_by_this_fix'}
    for name,function in functions.items():
        original=ast.parse(subprocess.check_output(['git','show','a0d243c7d9c88d16990da9115e00ed00e3ad8160:'+name],cwd=REPO))
        current=ast.parse((REPO/name).read_bytes())
        old=next(n for n in ast.walk(original) if isinstance(n,ast.FunctionDef) and n.name==function)
        new=next(n for n in ast.walk(current) if isinstance(n,ast.FunctionDef) and n.name==function)
        # Only an explicit authority-import source may change; every other
        # statement, predicate, assertion and test identity remains identical.
        for node in ast.walk(new):
            if isinstance(node,ast.ImportFrom) and node.module=='r_live_lifecycle_governance':
                node.module='finance_integrity_governance'
        assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)


def test_committed_odr_and_financial_engine_decisions_preserved():
    import finance_integrity_governance as historical
    import model_v2_governance as model
    import r_live_lifecycle_governance as adapter
    from v9p2a_odr_successor import odr_violations
    from v10_native_shadow_successor import historical_subject
    assert odr_violations(ref=historical_subject())==[]
    paths=set(historical.APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS)
    for value in vars(model).values():
        if isinstance(value,dict):paths.update(p for p in value if isinstance(p,str) and p.startswith('financial_engine/'))
    paths.add('financial_engine/unapproved.py')
    for name in paths:
        assert adapter.approved_frozen_path(name)==historical.approved_frozen_path(name)

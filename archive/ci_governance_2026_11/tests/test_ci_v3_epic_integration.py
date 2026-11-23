"""Epic integration keeps source authentication and nonpass authority closed."""
import hashlib,json
from pathlib import Path
import pytest,yaml
from tools import ci_v3_production as prod
from tools.ci_v3_frontend import prepare_frontend,frontend_record
from tools.ci_v3_schema import ContractError
ROOT=Path(__file__).resolve().parents[1]
EPIC='epic/model-react-frontend-v1'


def test_main_and_epic_pushes_and_prs_keep_public_contract():
 for name in ['public_safety_and_smoke.yml','dependency_security_audit.yml','protocol_verification.yml']:
  flow=yaml.load((ROOT/'.github/workflows'/name).read_text(),Loader=yaml.BaseLoader)
  assert {'main',EPIC}<=set(flow['on']['push']['branches'])
  assert 'pull_request' in flow['on']
 browser=yaml.load((ROOT/'.github/workflows/protocol_ui_browser.yml').read_text(),Loader=yaml.BaseLoader)
 assert EPIC in browser['on']['push']['branches'] and 'pull_request' in browser['on']
 flow=yaml.load((ROOT/'.github/workflows/public_safety_and_smoke.yml').read_text(),Loader=yaml.BaseLoader)
 assert set(flow['jobs'])=={'source-safety','safety-and-smoke','mandatory-evidence'}
 assert 'source-base' in flow['jobs']['safety-and-smoke']['with']
 assert prod.routing()['worker_count']==8


def report(status='passed'):
 phases=[{'nodeid':'tests/test_synthetic.py::test_original','when':w,'outcome':'passed','reason':'','wasxfail':None} for w in ['setup','call','teardown']]
 if status!='passed':phases[1].update(outcome='skipped',reason='frontend toolchain missing')
 return {'selected':['tests/test_synthetic.py::test_original'],'phases':phases}


def test_legacy_reference_does_not_authorize_new_frontend_skip():
 historical=report();accepted=report()
 accepted['selected'].append('tests/test_synthetic.py::test_graph')
 accepted['phases'] += [{**p,'nodeid':'tests/test_synthetic.py::test_graph'} for p in report('skipped')['phases']]
 with pytest.raises(ContractError,match='nonhistorical nonpass'):
  prod.validate_reference_policy({'report':accepted},historical)
 assert prod.route_mode(prod.routing(),True,'',True,False)=='sequential'
 # Once the toolchain exists, a future genuinely accepted checkpoint can pass.
 accepted['phases']=[{**p,'outcome':'passed','reason':''} for p in accepted['phases']]
 prod.validate_reference_policy({'report':accepted},historical)


def test_reference_cannot_drop_or_change_historical_phase():
 historical=report()
 with pytest.raises(ContractError):prod.validate_reference_policy({'report':{'selected':[],'phases':[]}},historical)
 with pytest.raises(ContractError):prod.validate_reference_policy({'report':report('skipped')},historical)


def bundle(tmp_path):
 source=tmp_path/'source';target=tmp_path/'immutable'
 (source/'frontend').mkdir(parents=True);(target/'node_modules/typescript/bin').mkdir(parents=True)
 for name,data in [('package.json','{}'),('package-lock.json','{}')]:
  (source/'frontend'/name).write_text(data);(target/name).write_text(data)
 (target/'node_modules/.package-lock.json').write_text('{}')
 (target/'node_modules/typescript/bin/tsc').write_text('// SYNTHETIC compiler\n')
 (target/'node_modules/typescript/package.json').write_text('{"version":"5.5.4"}')
 sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
 data={n:sha(source/'frontend'/n) for n in ['package.json','package-lock.json']}
 data.update(installed_lock_sha256=sha(target/'node_modules/.package-lock.json'),typescript_entry_sha256=sha(target/'node_modules/typescript/bin/tsc'))
 (target/'identity.json').write_text(json.dumps(data))
 return source,target


def test_private_subject_uses_immutable_locked_frontend(tmp_path):
 source,target=bundle(tmp_path);prepare_frontend(source,target)
 assert (source/'frontend/node_modules').is_symlink()
 assert (source/'frontend/node_modules').resolve()==target/'node_modules'
 record=frontend_record(source)
 assert record['typescript_version']=='5.5.4' and record['typescript_entry_sha256']


@pytest.mark.parametrize('attack',['missing-runtime','source-lock','compiler','installed-lock','unexpected-subject-deps'])
def test_frontend_mismatch_fails_instead_of_skipping(tmp_path,attack):
 source,target=bundle(tmp_path)
 if attack=='missing-runtime':(target/'identity.json').unlink()
 elif attack=='source-lock':(source/'frontend/package-lock.json').write_text('{"changed":true}')
 elif attack=='compiler':(target/'node_modules/typescript/bin/tsc').write_text('// altered compiler\n')
 elif attack=='installed-lock':(target/'node_modules/.package-lock.json').write_text('{"changed":true}')
 else:(source/'frontend/node_modules').mkdir()
 with pytest.raises(ValueError):prepare_frontend(source,target)


def test_runtime_transition_requires_sequential_checkpoint(monkeypatch):
 reference={'source':{'head':'synthetic'}}
 current=(ROOT/'docs/ci_v3/phase4/runtime/inputs.json').read_bytes()
 monkeypatch.setattr(prod.subprocess,'check_output',lambda *args,**kwargs:current)
 prod.require_reference_runtime(reference)
 monkeypatch.setattr(prod.subprocess,'check_output',lambda *args,**kwargs:b'{}')
 with pytest.raises(ContractError,match='runtime inputs changed'):
  prod.require_reference_runtime(reference)

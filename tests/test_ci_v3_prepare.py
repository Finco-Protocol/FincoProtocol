"""Current inventory preparation collects real tests without executing or admitting them."""
import pytest
import os
from pathlib import Path
import shutil
import subprocess
import sys

from tools.ci_v3_prepare import prepare
from tools.ci_v3_schema import ContractError, read_json, seal, write_json
from tools.ci_v3_real_contract import git_source
from tools.ci_v3_synthetic_project import create_project


def test_failing_test_is_only_collected_and_every_isolation_decision_stays_blocked(tmp_path):
    project=tmp_path/'project';create_project(project,'failure')
    output=tmp_path/'proposal'
    assert prepare(project,output)==6
    status=read_json(output/'proposal-status.json')
    assert status['executed_test_phases']==0 and not status['admitted'] and not status['authoritative_acceptance']
    assert status['process']['normal_successful_exit']
    assert read_json(output/'policy.json')['allowed_nonpass']=={}
    assert all(m['mode']=='blocked' and not m['reviewed'] for m in read_json(output/'isolation.json')['modules'].values())


def test_uncommitted_source_cannot_be_labeled_as_current_committed_inventory(tmp_path):
    project=tmp_path/'project';create_project(project)
    (project/'tests/test_new.py').write_text('def test_new(): pass\n')
    with pytest.raises(ContractError,match='clean committed'):prepare(project,tmp_path/'proposal')
    assert not (tmp_path/'proposal').exists()


def test_real_minimal_bootstrap_keeps_trusted_adapter_and_subject_legacy_tool_roots(tmp_path):
    project=tmp_path/'project';inventory,_,_=create_project(project)
    bootstrap=tmp_path/'bootstrap'
    shutil.copytree(Path(__file__).resolve().parents[1]/'tools',bootstrap/'tools',ignore=shutil.ignore_patterns('__pycache__'))
    (project/'tools').mkdir()
    (project/'tools/ci_single_gate.py').write_text('SUBJECT_LEGACY_MARKER=True\n')
    (project/'pytest.ini').write_text('[pytest]\ntestpaths=tests\npythonpath=.\n')
    gamma=project/'tests/test_gamma.py'
    gamma.write_text(gamma.read_text()+f'''
    from tools import ci_single_gate, ci_v3_pytest_adapter
    assert ci_single_gate.SUBJECT_LEGACY_MARKER is True
    assert Path(ci_v3_pytest_adapter.__file__).resolve().parents[1] == Path({str(bootstrap)!r}).resolve()
''')
    subprocess.run(['git','-C',str(project),'add','.'],check=True,capture_output=True)
    subprocess.run(['git','-C',str(project),'-c','user.name=CI V3 Synthetic','-c','user.email=fixture.invalid',
                    'commit','-qm','Hosted bootstrap fixture'],check=True,capture_output=True)
    source=git_source(project);inventory=seal({**{k:v for k,v in inventory.items() if k!='digest'},'source':source})
    evidence=tmp_path/'evidence';(evidence/'tmp').mkdir(parents=True)
    write_json(evidence/'request.json',{'mode':'worker','hosted':True,'project':str(project),'context':{'source':source},
        'worker':'worker-2','inventory':inventory,'owned_modules':['tests/test_gamma.py']})
    (evidence/'release').write_text('fixture parent ready\n')
    env=dict(os.environ,HOME=str(tmp_path/'home'),PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',
        CI_V3_WORKER_TMPDIR=str(evidence/'tmp'),CI_V3_WORKER_ID='worker-2')
    run=subprocess.run([sys.executable,'-I',str(bootstrap/'tools/ci_v3_real_child.py'),str(evidence/'request.json')],
        cwd=project,env=env,capture_output=True,timeout=30)
    assert run.returncode==0,run.stdout.decode(errors='replace')+run.stderr.decode(errors='replace')
    assert read_json(evidence/'interpreter-exit.json')['finalizing']
    assert len(read_json(evidence/'adapter.json')['phases'])==3

"""Fallback occurs only at admission; selected parallel rejection remains failure."""
import json
from tools.ci_v3_hosted_transport import sha
from tools.ci_v3_mandatory import main


def invoke(tmp_path,monkeypatch,stage,root):
    path=tmp_path/'root.json';path.write_text(json.dumps(root))
    output=tmp_path/'selection.json';github_output=tmp_path/'github-output'
    monkeypatch.setenv('GITHUB_OUTPUT',str(github_output))
    code=main([stage,'--root',str(path),'--root-sha256',sha(path.read_bytes()),
               '--project',str(tmp_path),'--output',str(output)])
    return code,output,github_output


def test_closed_authority_defaults_to_original_sequential_before_execution(tmp_path,monkeypatch):
    code,output,host=invoke(tmp_path,monkeypatch,'route',{'enabled':False})
    assert code==0 and json.loads(output.read_text())['execution_mode']=='sequential'
    assert host.read_text()=='execution_mode=sequential\n'


def test_stale_or_malformed_enabled_authority_falls_back_before_work(tmp_path,monkeypatch):
    code,output,host=invoke(tmp_path,monkeypatch,'route',{'enabled':True})
    assert code==0 and json.loads(output.read_text())['execution_mode']=='sequential'
    assert 'admission rejected' in json.loads(output.read_text())['reason']


def test_parallel_verification_rejection_never_starts_a_second_full_suite(tmp_path,monkeypatch):
    code,output,host=invoke(tmp_path,monkeypatch,'verify',{'enabled':False})
    assert code==1 and not host.exists()
    assert json.loads((tmp_path/'mandatory-rejection.json').read_text())['mandatory_execution_valid'] is False

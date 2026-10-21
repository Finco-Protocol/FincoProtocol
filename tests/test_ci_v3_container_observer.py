"""Mocked Docker lifecycle contract; does not report a real container run."""
from types import SimpleNamespace
import subprocess

import pytest

from tools import ci_v3_container as module
from tools.ci_v3_schema import read_json, write_json
from tools.ci_v3_synthetic_project import create_project


@pytest.mark.parametrize('fault',['normal','nonzero','timeout','missing-finalizer','live-thread','cleanup-unproven','cancel','rm-timeout','source-mutation','head-mutation'])
def test_mock_docker_host_observation_and_cleanup(tmp_path,monkeypatch,fault):
    project=tmp_path/'project';inventory,_,_=create_project(project)
    output=tmp_path/'observation';calls=[]
    child=output/'child'
    class Process:
        pid=987654
        returncode=None
        waits=0
        def wait(self,timeout):
            self.waits+=1
            if self.waits==1:
                if fault=='timeout':raise subprocess.TimeoutExpired('fixture-docker',timeout)
                if fault=='cancel':raise KeyboardInterrupt('fixture cancellation')
                self.returncode=1 if fault=='nonzero' else 0
                write_json(child/'pytest-return.json',{'code':self.returncode,'pytest_started_ms':1,'pytest_returned_ms':2,
                    'leaks':{'threads':['leaked'] if fault=='live-thread' else [],'children':[]}})
                if fault!='missing-finalizer':write_json(child/'interpreter-exit.json',{'finalizing':True,'at_ms':3})
                if fault=='source-mutation':(output/'source/tests/test_gamma.py').write_text('changed source')
                if fault=='head-mutation':(output/'source/.git/HEAD').write_text('f'*40+'\n')
            elif self.returncode is None:self.returncode=-9
            return self.returncode
    def launch(command,**kwargs):
        calls.append(command)
        kwargs['stdout'].write(b'forged success marker rc=0\n')
        return Process()
    def run(command,**kwargs):
        calls.append(command)
        if command[:3]==['docker','rm','-f'] and fault=='rm-timeout':raise subprocess.TimeoutExpired('fixture-rm',30)
        if command[:3]==['docker','container','inspect']:
            return SimpleNamespace(returncode=1,stderr=b'daemon unavailable' if fault=='cleanup-unproven' else b'Error: No such container',stdout=b'')
        return SimpleNamespace(returncode=0,stderr=b'',stdout=b'')
    # Patch this module's dependency object, leaving real Git fixture preparation
    # and unrelated subprocess callers intact.
    monkeypatch.setattr(module,'subprocess',SimpleNamespace(check_output=subprocess.check_output,Popen=launch,run=run,
        TimeoutExpired=subprocess.TimeoutExpired,SubprocessError=subprocess.SubprocessError,STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.setattr(module.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(module.os,'getgid',lambda:1001,raising=False)
    monkeypatch.setattr(module.os,'killpg',lambda pid,sig:calls.append(['owned-group-kill',pid]),raising=False)
    monkeypatch.setattr(module.signal,'SIGKILL',9,raising=False)
    request={'mode':'discover','worker':None,'context':{'source':inventory['source'],'run_id':'123','attempt':2,'repository':'local/fixture'}}
    if fault=='cancel':
        with pytest.raises(KeyboardInterrupt):module.observe_container(request,output,project,'example.invalid/image@sha256:'+'a'*64,10)
    else:
        _,result=module.observe_container(request,output,project,'example.invalid/image@sha256:'+'a'*64,10)
        assert result['normal_successful_exit'] is (fault in ['normal','rm-timeout'])
        assert result['timed_out'] is (fault=='timeout')
    assert any(c[:3]==['docker','rm','-f'] for c in calls)
    assert any(c[:3]==['docker','container','inspect'] for c in calls)
    assert any(c[0]=='owned-group-kill' for c in calls)
    assert read_json(output/'host-finalization.json')['cancelled'] is (fault=='cancel')
    config=(output/'source/.git/config').read_text()
    assert 'extraheader' not in config and 'credential' not in config and 'url =' not in config

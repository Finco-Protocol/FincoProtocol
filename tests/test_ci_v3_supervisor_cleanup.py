"""Real independent parent cleanup; escaped orphan never becomes green."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]


def run_supervisor(tmp_path,body):
    (tmp_path/'test_case.py').write_text(body)
    env={**os.environ,'PYTHONPATH':str(ROOT),'FINCO_CI_PYTEST_BUDGET_S':'25',
         'FINCO_CI_EXIT_GRACE_S':'5','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
    return subprocess.run([sys.executable,str(ROOT/'tools/ci_pytest_runner.py'),'-q','test_case.py'],
                          cwd=tmp_path,env=env,capture_output=True,text=True,timeout=40)


def test_real_supervisor_records_clean_normal_completion(tmp_path):
    result=run_supervisor(tmp_path,'def test_ok(): assert True\n')
    assert result.returncode==0,result.stdout+result.stderr
    cleanup=json.loads(next(s.removeprefix('FINCO_CI_CLEANUP ') for s in result.stdout.splitlines()
                            if s.startswith('FINCO_CI_CLEANUP ')))
    assert cleanup['mechanism']=='linux-subreaper-proc-waitpid-v1'
    assert cleanup['cleanup_verified'] and cleanup['survivors_observed']==cleanup['survivors_remaining']==[]


def test_orphan_in_new_session_fails_after_pytest_pass_and_is_cleaned(tmp_path):
    result=run_supervisor(tmp_path,'''import os,time

def test_orphan():
    first=os.fork()
    if first==0:
        os.setsid()
        for fd in (0,1,2):
            os.close(fd)
        time.sleep(20)
        os._exit(0)
    assert first>0
''')
    assert '1 passed' in result.stdout
    assert result.returncode==125,result.stdout+result.stderr
    cleanup=json.loads(next(s.removeprefix('FINCO_CI_CLEANUP ') for s in result.stdout.splitlines()
                            if s.startswith('FINCO_CI_CLEANUP ')))
    assert not cleanup['cleanup_verified'] and cleanup['survivors_observed']
    assert cleanup['survivors_remaining']==[]


def test_failed_test_exit_is_preserved_even_when_cleanup_is_successful(tmp_path):
    result=run_supervisor(tmp_path,'def test_fails(): assert False\n')
    assert result.returncode==1 and '1 failed' in result.stdout
    assert '"cleanup_verified": true' in result.stdout

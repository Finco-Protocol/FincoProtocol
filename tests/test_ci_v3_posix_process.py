"""Real Linux process groups; skipped honestly when the local host is Windows."""
import sys

import pytest

from tools.ci_v3_process_observer import observe
from tools.ci_v3_synthetic_project import create_project

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Real Linux/POSIX process handling requires Linux; not simulated')


@pytest.mark.parametrize('variant',['positive','failure','abrupt','forged_success','timeout','shutdown_hang','missing_exit','grandchild_timeout'])
def test_actual_posix_process_results_and_descendant_cleanup(tmp_path,variant):
    project=tmp_path/'project';inventory,policy,weights=create_project(project,variant)
    request={'mode':'worker','project':str(project),'context':{'source':inventory['source']},'worker':'worker-2',
             'inventory':inventory,'owned_modules':['tests/test_gamma.py']}
    # All process-fault variants and the failing assertion live in gamma.
    result=observe(request,tmp_path/'execution',6 if variant in ['timeout','shutdown_hang','grandchild_timeout'] else 20)
    assert result['containment']=='posix-process-group' and result['descendant_cleanup_complete']
    if variant=='positive':assert result['normal_successful_exit'] and result['os_exit_code']==0
    else:assert result['normal_successful_exit'] is False
    if variant in ['timeout','shutdown_hang','grandchild_timeout']:assert result['timed_out']
    if variant=='missing_exit':assert result['interpreter_exit'] is None
    if variant=='forged_success':assert result['os_exit_code']==1


def test_running_unregistered_child_prevents_normal_success(tmp_path):
    project=tmp_path/'project';inventory,_,_=create_project(project)
    conftest=project/'conftest.py'
    conftest.write_text(conftest.read_text()+'''\n\ndef pytest_sessionfinish(session, exitstatus):
    import subprocess, sys
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
''')
    request={'mode':'worker','project':str(project),'context':{'source':inventory['source']},'worker':'worker-2',
             'inventory':inventory,'owned_modules':['tests/test_gamma.py']}
    result=observe(request,tmp_path/'execution',20)
    assert result['os_exit_code']==0 and result['pytest_return']['code']==0
    assert result['surviving_descendants_at_parent_exit']
    assert result['descendant_cleanup_complete'] and not result['normal_successful_exit']

"""Exact phase/outcome/native-JUnit checks with explicit synthetic process fixtures."""
from copy import deepcopy
import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

from tools.ci_v3_phase_compare import compare, control_report, main, phase_map
from tools.ci_v3_schema import ContractError

SOURCE = {'head': 'a' * 40, 'tree': 'b' * 40}
IDS = [f'tests/test_{i}.py::test_case[asyncio]' for i in range(3)]
SKIP = {'nodeid': 'tests/test_optional.py', 'reason': 'missing optional runtime'}


def xml(report):
    suite = ET.Element('testsuite', tests=str(len(report['selected']) + 1), failures='0', errors='0', skipped='1')
    for ident in report['selected']:
        module, name = ident.split('::', 1)
        ET.SubElement(suite, 'testcase', classname=module[:-3].replace('/', '.'), name=name)
    case = ET.SubElement(suite, 'testcase', classname='', name='tests.test_optional')
    ET.SubElement(case, 'skipped', message='collection skipped')
    return ET.tostring(suite)


def world():
    collection = {'source': SOURCE, 'complete': True, 'errors': [], 'nodes': IDS, 'skips': [SKIP]}
    phases = [{'nodeid': n, 'when': when, 'outcome': 'passed', 'reason': '', 'wasxfail': None}
              for n in IDS for when in ('setup', 'call', 'teardown')]
    control = {'source': SOURCE, 'collection': collection, 'selected': IDS, 'deselected': [],
               'phases': phases, 'pytest_exitstatus': 0, 'environment': {'fixture': 'same'},
               'pytest_plugins': ['pytest_asyncio.plugin', 'anyio.pytest_plugin']}
    workers = [{**deepcopy(control), 'selected': [n], 'deselected': [x for x in IDS if x != n],
                'phases': deepcopy([p for p in phases if p['nodeid'] == n])} for n in IDS]
    native = [xml(r) for r in [control, *workers]]
    processes = [dict(source=SOURCE, normal_exit=True, exit_code=0, cleanup_verified=True) for _ in range(4)]
    return deepcopy((control, workers, native, processes))


def test_exact_phases_and_native_original_ids_match_without_granting_authority():
    result = compare(*world())
    assert result['phase_equivalent'] and result['original_nodes'] == 3
    assert result['native_junit_valid'] and result['process_cleanup_valid']
    assert not result['admission_ready'] and not result['provenance_authenticated']


@pytest.mark.parametrize('attack', ['parameter', 'missing', 'duplicate', 'phase-missing', 'phase-duplicate',
    'setup', 'teardown', 'reason', 'xfail', 'collection-reason', 'source', 'cleanup', 'timeout', 'native-missing', 'native-duplicate', 'native-failure', 'native-count'])
def test_mismatches_never_pass(attack):
    c, w, native, processes = world()
    if attack == 'parameter': w[0]['selected'][0] = IDS[0].replace('[asyncio]', '')
    elif attack == 'missing': w[0]['phases'] = []
    elif attack == 'duplicate': w[1] = deepcopy(w[0])
    elif attack == 'phase-missing': w[0]['phases'].pop()
    elif attack == 'phase-duplicate': w[0]['phases'].append(deepcopy(w[0]['phases'][0]))
    elif attack in ('setup', 'teardown'): next(p for p in w[0]['phases'] if p['when'] == attack)['outcome'] = 'failed'
    elif attack == 'reason': w[0]['phases'][1]['reason'] = 'different exact reason'
    elif attack == 'xfail': w[0]['phases'][1]['wasxfail'] = 'new policy'
    elif attack == 'collection-reason': w[0]['collection']['skips'][0]['reason'] = 'new skip'
    elif attack == 'source': w[0]['source'] = {'head': 'c' * 40, 'tree': SOURCE['tree']}
    elif attack == 'cleanup': processes[1].pop('cleanup_verified')
    elif attack == 'timeout': processes[1]['timed_out'] = True
    else:
        root = ET.fromstring(native[1]); case = root.find('testcase')
        if attack == 'native-missing': root.remove(case)
        elif attack == 'native-duplicate': root.append(deepcopy(case))
        elif attack == 'native-failure': ET.SubElement(case, 'failure', message='new failure'); root.set('failures', '1')
        else: root.set('tests', '100')
        native[1] = ET.tostring(root)
    with pytest.raises(ContractError): compare(c, w, native, processes)


@pytest.mark.parametrize('status', ['skipped', 'xfail', 'xpass'])
def test_runtime_nonpass_status_reason_and_native_junit_are_compared(status):
    c, w, native, processes = world()
    for report in (c, w[0]):
        call = next(p for p in report['phases'] if p['nodeid'] == IDS[0] and p['when'] == 'call')
        call.update(outcome='passed' if status == 'xpass' else 'skipped', reason='' if status == 'xpass' else 'exact reason',
                    wasxfail=None if status == 'skipped' else 'exact reason')
    for index in (0, 1):
        if status != 'xpass':
            root = ET.fromstring(native[index]); root.set('skipped', '2')
            ET.SubElement(root.find('testcase'), 'skipped', type='pytest.xfail' if status == 'xfail' else 'pytest.skip', message='exact reason')
            native[index] = ET.tostring(root)
    assert compare(c, w, native, processes)['phase_equivalent']
    w[0]['phases'][1]['reason'] = 'changed'
    with pytest.raises(ContractError): compare(c, w, native, processes)


def test_old_control_or_progress_duration_data_cannot_manufacture_phases():
    with pytest.raises(ContractError, match='control phase evidence missing'):
        control_report({'durations': {'s': 1, 'c': 2, 't': 3}})


def test_same_source_control_observer_captures_real_phase_and_collection_records(tmp_path):
    import os
    import subprocess
    import sys
    project = tmp_path / 'project'; project.mkdir()
    (project / 'test_case.py').write_text('def test_ok(): assert True\n')
    (project / 'test_optional.py').write_text('import pytest\npytest.skip("optional fixture", allow_module_level=True)\n')
    output = tmp_path / 'control.json'; junit = tmp_path / 'native.xml'
    # Explicit PYTHONPATH only locates the trusted observer; subject collection is unchanged.
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', FINCO_CI_TESTED_SHA=SOURCE['head'], FINCO_CI_TESTED_TREE=SOURCE['tree'],
               PYTHONPATH=str(__import__('pathlib').Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'tools.ci_pytest_inventory',
        '--ci-inventory=' + str(output), '--junitxml=' + str(junit)], cwd=project, env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
    observed = control_report(json.loads(output.read_text()))
    assert observed['source'] == SOURCE
    assert observed['collection']['skips'] == [{'nodeid': 'test_optional.py', 'reason': 'Skipped: optional fixture'}]
    assert [p['when'] for p in phase_map(observed)['test_case.py::test_ok']] == ['setup', 'call', 'teardown']


def test_input_tamper_is_rejected_against_external_pin(tmp_path):
    path = tmp_path / 'artifact.json'; path.write_text('{}')
    item = {name: {'path': str(path), 'sha256': 'f' * 64} for name in ('report', 'junit', 'process')}
    inputs = tmp_path / 'inputs.json'; inputs.write_text(json.dumps([item] * 4))
    output = tmp_path / 'proof.json'
    assert main(['--inputs', str(inputs), '--output', str(output)]) == 1
    assert not json.loads(output.read_text())['admission_ready']

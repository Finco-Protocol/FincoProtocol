"""Real collection/execution and missing-plugin controls for original async IDs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.ci_v3_process_observer import observe
from tools.ci_v3_pytest_config import PLUGINS, plugin_args
from tools.ci_v3_schema import ContractError, read_json, reconcile_collection


def test_actual_anyio_original_ids_and_all_execution_phases(tmp_path):
    project = tmp_path / 'project'; (project / 'tests').mkdir(parents=True)
    (project / 'pytest.ini').write_text('[pytest]\nasyncio_mode=auto\n')
    (project / 'tests/test_async.py').write_text('''import pytest
@pytest.mark.anyio
async def test_async():
    assert True
@pytest.mark.parametrize("value", ["opaque::id"])
def test_literal(value):
    assert value == "opaque::id"
''')
    source = {'head': 'a' * 40, 'tree': 'b' * 40}
    request = {'mode': 'discover', 'project': str(project), 'worker': None, 'context': {'source': source}}
    observed = observe(request, tmp_path / 'discover', 30)
    assert observed['normal_successful_exit']
    report = read_json(tmp_path / 'discover/adapter.json')
    from anyio import get_available_backends
    expected = sorted(['tests/test_async.py::test_async[' + b + ']' for b in get_available_backends()]
                      + ['tests/test_async.py::test_literal[opaque::id]'])
    assert report['collection']['nodes'] == expected and report['phases'] == []
    inventory = {'source': source, 'nodes': [{'nodeid': n} for n in expected], 'collection_skips': []}
    request.update(mode='worker', worker='worker-0', inventory=inventory, owned_modules=['tests/test_async.py'])
    assert observe(request, tmp_path / 'worker', 30)['normal_successful_exit']
    actual = read_json(tmp_path / 'worker/adapter.json')
    assert sorted(actual['selected']) == expected and not actual['deselected']
    for node in expected:
        assert [(p['when'], p['outcome']) for p in actual['phases'] if p['nodeid'] == node] == [
            ('setup', 'passed'), ('call', 'passed'), ('teardown', 'passed')]


@pytest.mark.parametrize('plugin', PLUGINS)
def test_missing_required_plugin_fails_before_collection(tmp_path, plugin):
    target = tmp_path / 'test_never.py'; target.write_text('def test_never(): assert False\n')
    code = '''import builtins, sys
original = builtins.__import__
missing = sys.argv[1]
def guarded(name, *args, **kwargs):
 if name == missing: raise ImportError("missing required plugin fixture")
 return original(name, *args, **kwargs)
builtins.__import__ = guarded
import pytest
from tools.ci_v3_pytest_config import plugin_args
raise SystemExit(pytest.main([*plugin_args(), sys.argv[2]]))
'''
    result = subprocess.run([sys.executable, '-c', code, plugin, str(target)],
        env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'), capture_output=True, timeout=30)
    assert result.returncode != 0 and b'missing required plugin fixture' in result.stderr
    assert b'test_never FAILED' not in result.stdout


@pytest.mark.parametrize('attack', ['missing', 'changed', 'duplicate'])
def test_parameterized_identity_mutations_are_not_aliased(attack):
    ident = 'tests/test_async.py::test_async[asyncio]'
    inventory = {'source': {}, 'nodes': [{'nodeid': ident}], 'collection_skips': []}
    nodes = [] if attack == 'missing' else ([ident, ident] if attack == 'duplicate' else [ident[:-9]])
    with pytest.raises(ContractError):
        reconcile_collection(inventory, {'source': {}, 'complete': True, 'errors': [], 'nodes': nodes, 'skips': []})

"""Fail-closed readiness and an actual cancellation-regression mutation control."""
import asyncio
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

import p0_exec_helpers as helpers


def test_missing_start_acknowledgement_fails_instead_of_skipping():
    reader, writer = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        with pytest.raises(AssertionError, match="did not acknowledge"):
            asyncio.run(helpers.wait_for_worker_start(reader, timeout=0.01))
    finally:
        reader.close(); writer.close()


@pytest.mark.parametrize('message', [0, -1, 'ready', True, os.getpid()],
                         ids=['zero', 'negative', 'text', 'bool', 'parent'])
def test_invalid_or_parent_start_acknowledgement_is_rejected(message):
    reader, writer = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        writer.send(message)
        with pytest.raises(AssertionError, match="invalid spawned-worker"):
            asyncio.run(helpers.wait_for_worker_start(reader))
    finally:
        reader.close(); writer.close()


def test_closed_readiness_channel_is_failure():
    reader, writer = multiprocessing.get_context("spawn").Pipe(duplex=False)
    writer.close()
    try:
        with pytest.raises(EOFError):
            asyncio.run(helpers.wait_for_worker_start(reader))
    finally:
        reader.close()


@pytest.mark.parametrize('defect', ['early-release', 'never-release'])
def test_original_cancellation_assertions_reject_capacity_defects(tmp_path, defect):
    """Both premature release and a retained slot must fail the real test."""
    xml = tmp_path / 'mutant.xml'
    code = '''import asyncio, sys
from app.runtime.model_execution import ModelExecutor
original = ModelExecutor._await
async def broken(self, future):
    try:
        return await original(self, future)
    except asyncio.CancelledError:
        # Deliberate test-only defect: the worker is still calculating.
        with self._lock:
            self._active -= 1
        self._gate.release()
        raise
if sys.argv[2] == 'early-release':
    ModelExecutor._await = broken
else:
    ModelExecutor._finish = lambda *args: None  # deliberate retained-slot defect
import pytest
from tools.ci_v3_pytest_config import plugin_args
raise SystemExit(pytest.main(['-q', '--tb=short', '-p', 'no:cacheprovider', *plugin_args(),
    '--junitxml='+sys.argv[1],
    'tests/test_p0a_model_execution.py::test_client_disconnect_never_leaks_capacity_and_discards_the_result']))
'''
    result = subprocess.run([sys.executable, '-c', code, str(xml), defect],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'),
        capture_output=True, timeout=45)
    assert result.returncode == 1, (result.stdout, result.stderr)
    cases = list(ET.parse(xml).getroot().iter('testcase'))
    assert len(cases) == 1 and cases[0].find('failure') is not None
    expected = 'assert 0 == 1' if defect == 'early-release' else 'assert 1 == 0'
    assert expected in cases[0].find('failure').text
    assert cases[0].get('name') == 'test_client_disconnect_never_leaks_capacity_and_discards_the_result'

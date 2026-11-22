"""Production routing and adversarial coverage checks; service fixtures are SYNTHETIC."""
from copy import deepcopy
import json,os,shutil,subprocess
from pathlib import Path
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]


def test_browser_diagnostic_failure_preserves_original_exception(tmp_path):
 from tests.model_statements_tree_acceptance import browser_failure_guard
 class ClosedDuringFailure:
  def is_closed(self):return False
  def evaluate(self,*args):raise RuntimeError('page lost')
  def screenshot(self,**kwargs):raise RuntimeError('screenshot lost')
 results=[]
 with pytest.raises(AssertionError,match='wrong keyboard focus'):
  with browser_failure_guard(tmp_path,results,{'name':'Tab'},[ClosedDuringFailure()]):
   raise AssertionError('wrong keyboard focus')
 assert results[-1]['status']=='FAIL' and results[-1]['exception_type']=='AssertionError'
 assert results[-1]['diagnostic_error']=='page lost' and results[-1]['screenshot_error']=='screenshot lost'


def test_fixture_owned_acquisition_pool_is_closed_and_joined():
 from app.radar_runtime.service import AcquisitionService
 from app.radar_runtime.snapshot_store import SnapshotStore
 from tests.conftest import _close_owned_acquisition_services
 service=AcquisitionService(SnapshotStore(':memory:'))
 pool=service._provider_pool
 assert pool.submit(lambda: 1).result(timeout=2)==1
 _close_owned_acquisition_services([(service,pool)])
 assert service._closed and not any(t.is_alive() for t in pool._threads)


# ── Run-attempt artifact identity: replay of PR #400 run 41099667692 (SYNTHETIC service, real ZIP round trips) ───────
RUNTIME_BYTES=b'SYNTHETIC runtime-image.tar.gz bytes'

def _zip(folder):
 import io,zipfile
 buffer=io.BytesIO()
 with zipfile.ZipFile(buffer,'w') as archive:
  for file in sorted(folder.rglob('*')):
   if file.is_file():archive.writestr(str(file.relative_to(folder)),file.read_bytes())
 return buffer.getvalue()


def toolkit_by_name(listing,name):
 # actions/download-artifact (pinned d3f86a10 / @actions/artifact getArtifact): newest = highest numeric ID for that name.
 return max((a for a in listing if a['name']==name),key=lambda a:a['id'])

def stale_attempt_1_baseline_only(tmp_path):
 folder=tmp_path/'attempt-1-plan';(folder/'baseline/public-verification-results').mkdir(parents=True)
 (folder/'baseline/public-verification-results/inventory.json').write_text('{}')
 return folder


def _plain(step_run):return step_run if isinstance(step_run,str) else ''



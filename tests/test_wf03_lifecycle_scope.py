"""WF03 exact-source positives and independently injected closed-world negatives."""
import copy
import difflib
import json
import subprocess

import pytest
from tests import wf03_lifecycle_scope as F


def test_complete_closed_successor_and_unchanged_historical_maps(tmp_path):
    assert F.valid() and F.exact_blobs_ok()
    assert not F.valid(tmp_path) and F.protected_blobs()=={}
    assert F.D029_APPROVED_PATHS=={'app/persistence/workspace_repository.py'}
    assert not F.matches('financial_engine/native_v11/config.py')
    assert not F.allowed_path('app/unreviewed_writer.py')
    assert all(not p.startswith(('financial_engine/','finco_core/','domain/')) for p in F.OWNED_PATHS)
    # Finite successor of the former 'no .github/ path' rule: exactly the three Owner-directed CI-timeout workflows, nothing else under .github/.
    assert {p for p in F.OWNED_PATHS if p.startswith('.github/')}==F.CI_TIMEOUT_WORKFLOWS
    assert not F.allowed_path('.github/workflows/protocol_ui_browser.yml') and not F.allowed_path('.github/workflows/new_unreviewed.yml')
    data=F.manifest()
    for path in F.PREDECESSOR_MANIFESTS:
        old=json.loads(F._read(F.ROOT,path,F.BASE))
        current=json.loads(F._read(F.ROOT,path,None))
        assert current['historical_source_blobs'][F.BASE]==old['source_blobs']
        for key,value in old.get('historical_source_blobs',{}).items():
            assert current['historical_source_blobs'][key]==value
    assert set(data['source_blobs'])==F.OWNED_PATHS


@pytest.mark.parametrize('path',sorted(F.OWNED_PATHS))
def test_every_owned_byte_and_missing_path_fail_closed(path,monkeypatch):
    source=(F.ROOT/path).read_bytes()
    assert not F.matches(path,source+b'\n')
    reader=F._read
    def missing(root,p,ref):
        if p==path and ref is None: raise FileNotFoundError(path)
        return reader(root,p,ref)
    monkeypatch.setattr(F,'_read',missing)
    assert not F.exact_blobs_ok() and not F.valid()


@pytest.mark.parametrize('kind',['extra-path','missing-pin','wrong-base','wrong-blob','removed-history'])
def test_manifest_forgery_and_incomplete_successor_refused(kind,monkeypatch):
    reader=F._read
    def changed(root,path,ref):
        raw=reader(root,path,ref)
        if path==F.MANIFEST and ref is None:
            d=json.loads(raw)
            if kind=='extra-path': d['source_blobs']['financial_engine/unreviewed.py']='0'*40
            elif kind=='missing-pin': d['source_blobs'].pop('app/persistence/db.py')
            elif kind=='wrong-base': d['base']='0'*40
            elif kind=='wrong-blob': d['source_blobs']['app/persistence/db.py']='0'*40
            else: d['predecessor_manifests'].pop(F.PREDECESSOR_MANIFESTS[0])
            return json.dumps(d).encode()
        return raw
    monkeypatch.setattr(F,'_read',changed)
    assert not F.exact_blobs_ok() and not F.valid()


def test_wrong_ancestor_and_unreviewed_changed_path_are_refused(monkeypatch):
    git=F._git
    def wrong(root,*args):
        if args[:2]==('merge-base','--is-ancestor'): raise subprocess.CalledProcessError(1,args)
        return git(root,*args)
    monkeypatch.setattr(F,'_git',wrong)
    assert not F.exact_blobs_ok()
    def extra(root,*args):
        raw=git(root,*args)
        if args[:2]==('diff','--name-only'): return raw+b'app/unreviewed_writer.py\n'
        return raw
    monkeypatch.setattr(F,'_git',extra)
    assert not F.valid()


def test_trust_successor_preserves_the_actual_ws2_parent_byte_content():
    parent=F._read(F.ROOT,'app/trust_readiness/registry.py',F.BASE).decode()
    current=(F.ROOT/'app/trust_readiness/registry.py').read_text(encoding='utf-8')
    assert F.trust_registry_successor(parent,current)
    assert not [line for line in difflib.unified_diff(parent.splitlines(),current.splitlines())
                if line.startswith('-') and not line.startswith('---')]
    for text in (current+'\n# unreviewed',current.replace('data.backups','data.backups_removed',1),
                 current.replace('No TTL or cascading project deletion','Automatically deleted after 24 hours',1)):
        assert not F.trust_registry_successor(parent,text)

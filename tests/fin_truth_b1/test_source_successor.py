"""B1 finite successor: byte, predecessor and undeclared-path negatives."""
import json

import pytest
from tests import wf03_lifecycle_scope as F


def test_b1_source_complete_and_predecessor_history_unchanged():
    assert F.exact_blobs_ok() and F.valid()
    seal=json.loads((F.ROOT/F.B1_MANIFEST).read_text())
    old=json.loads(F._read(F.ROOT,F.MANIFEST,F.B1_BASE))
    assert seal['historical_source_blobs']=={F.B1_BASE:old['source_blobs']}
    reviewed=json.loads(F._read(F.ROOT,F.MANIFEST,F.B1_CORRECTION_B_BASE))
    assert seal['correction_b_history']=={F.B1_CORRECTION_B_BASE:reviewed['source_blobs']}
    assert F.manifest()['path_ledger'][:len(reviewed['path_ledger'])]==reviewed['path_ledger']
    current=F.manifest()['source_blobs']
    assert set(current)==set(old['source_blobs'])|F.B1_PATHS
    assert not any(p.startswith(('financial_engine/','finco_core/','domain/')) for p in F.B1_PATHS|F.B1_REPINS)
    for path in ('app/unreviewed.py','tests/fin_truth_b1/new.py','docs/financial_validation/fin_truth_b1/unreviewed.md'):
        assert not F.allowed_path(path)


@pytest.mark.parametrize('kind',['byte','missing','history','correction-history','extra-path','unrelated-pin','ledger-history','correction-ledger'])
def test_b1_undeclared_or_corrupt_layer_is_not_admitted(monkeypatch,kind):
    read=F._read
    def changed(root,path,ref):
        raw=read(root,path,ref)
        if ref is None and kind=='byte' and path=='main_web.py':return raw+b'\n'
        if ref is None and path==F.B1_MANIFEST:
            seal=json.loads(raw)
            if kind=='missing':seal['source_blobs'].pop('main_web.py')
            elif kind=='history':seal['historical_source_blobs'][F.B1_BASE]['main_web.py']='0'*40
            elif kind=='correction-history':seal['correction_b_history'][F.B1_CORRECTION_B_BASE]['main_web.py']='0'*40
            elif kind=='extra-path':seal['source_blobs']['app/unreviewed.py']='0'*40
            return json.dumps(seal).encode()
        if ref is None and kind=='ledger-history' and path==F.MANIFEST:
            data=json.loads(raw);data['path_ledger'][0]['invariant']='deleted historical meaning'
            return json.dumps(data).encode()
        if ref is None and kind=='correction-ledger' and path==F.MANIFEST:
            data=json.loads(raw);data['path_ledger'][-1]['before_blob']='0'*40
            return json.dumps(data).encode()
        if ref is None and kind=='unrelated-pin' and path==F.MANIFEST:
            data=json.loads(raw);data['source_blobs']['app/persistence/db.py']='0'*40
            return json.dumps(data).encode()
        return raw
    monkeypatch.setattr(F,'_read',changed)
    assert not F.exact_blobs_ok() and not F.valid()

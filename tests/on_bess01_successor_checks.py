"""Opt-in Correction B V1 negative proof; adds no mandatory selected identities."""
import ast
import copy
import json
import subprocess

import pytest
from tests import on_bess01_scope as B
from tests import on_bess01_reviewed_successors as S
from tests.on_bess01_correction_checks import evidence_file, real_attestation


def accepted():
    return subprocess.check_output(['git', 'show', B.BASE + ':app/v2/router.py'], cwd=B.ROOT).decode()


@pytest.mark.parametrize('old,new', [
    ('if not validate_csrf_token(form.get("csrf_token")):', 'if False:'),
    ('if not user:', 'if False:'),
    ('if is_protected_reference(record):', 'if False:'),
    ('base_token=(str(form.get("contracts_base_token")) if form.get("contracts_base_token") is not None else None)', 'base_token=None'),
    ('except ContractsTokenError as exc:', 'except RuntimeError as exc:'),
    ('"reload": True', '"reload": False'),
    ('"code": exc.code', '"code": "OK"'),
    ('raw=form.get("contracts", "")', 'raw=""'),
    ('expected_hash=str(form.get("content_hash") or "")', 'expected_hash=""'),
    ('status_code=401', 'status_code=200'),
    ('save_contracts(owner=owner,', 'save_unchecked(owner=owner,'),
])
def test_pin_independent_revenue_ast_rejects_weakened_security(old, new):
    source = accepted()
    assert old in source
    altered = source.replace(old, new)
    assert not S.revenue_structure_ok(altered, source)
    assert not S.o1_revenue_authorized('', altered)


def test_current_revenue_requires_real_history_identity_and_provenance(monkeypatch):
    from tests import post413_o1_scope as O1
    source = accepted()
    old = subprocess.check_output(['git', 'show', S.F35B_BASE + ':app/v2/router.py'], cwd=B.ROOT).decode().strip()
    assert S.o1_revenue_authorized(old, source)
    assert not S.o1_revenue_authorized(old + 'x', source)
    assert not S.o1_revenue_authorized(old, source + '\n')
    assert not S.revenue_structure_ok(source + '\ndef v2_revenue_contracts(): pass\n', source)
    monkeypatch.setattr(O1, 'exact_blobs_ok', lambda *a: False)
    assert not S.o1_revenue_authorized(old, source)


def bank_facts():
    state = ({'bankability_config_json': json.dumps({'version': 1, 'day_count': 'act_360'})}, None)
    return dict(status=200, event={'workbook-field-error': {'field_id': 'debt.bankability.configuration',
        'message': 'Draft changed since page loaded, so your edit was not saved. Reload the page to see the current value, then enter it again.',
        'error_class': None, 'conflict': True}}, tone='conflict', warning=next(iter(S.APPROVED_WARNINGS)),
        before=state, after=copy.deepcopy(state), posts=[], local_day_count='act_365')


@pytest.mark.parametrize('fault', ['status', 'type', 'field', 'class', 'warning', 'tone', 'overwrite', 'run', 'post', 'draft', 'extra-event'])
def test_browser_oracle_rejects_false_green(fault):
    f = bank_facts()
    assert S.bankability_refusal_valid(**f)
    if fault == 'status': f['status'] = 303
    if fault == 'type': f['event']['workbook-field-error']['conflict'] = False
    if fault == 'field': f['event']['workbook-field-error']['field_id'] = 'other'
    if fault == 'class': f['event']['workbook-field-error']['error_class'] = 'STALE'
    if fault == 'warning': f['warning'] = ''
    if fault == 'tone': f['tone'] = 'ok'
    if fault == 'overwrite': f['after'][0]['bankability_config_json'] = '{"version":1,"day_count":"act_365"}'
    if fault == 'run': f['after'] = (f['after'][0], 'unexpected-run')
    if fault == 'post': f['posts'] = ['/v2/workbook/update']
    if fault == 'draft': f['local_day_count'] = 'act_360'
    if fault == 'extra-event': f['event']['success'] = True
    assert not S.bankability_refusal_valid(**f)


def test_successor_contract_admits_only_the_two_reviewed_edits():
    read = lambda p: (B.ROOT / p).read_bytes()
    base = lambda p: subprocess.check_output(['git', 'show', B.BASE + ':' + p], cwd=B.ROOT)
    assert S.reviewed_edits_ok(read, base)
    for path in (S.TRUST_PATH, S.BANK_PATH):
        assert not S.reviewed_edits_ok(lambda p: read(p) + (b'\n' if p == path else b''), base)


@pytest.mark.parametrize('fault', ['missing-owned', 'mode-world-write', 'hardlink', 'oversize', 'truncated-png', 'wrong-merge-mode', 'forged-merge'])
def test_generated_output_add_missing_modified_controls(fault):
    path = 'evidence/source.json'
    raw = json.dumps(real_attestation()).encode()
    if fault == 'missing-owned':
        p = B.ROOT / S.TRUST_PATH
        original = p.read_bytes()
        try:
            p.unlink()
            assert not B.exact_blobs_ok()
        finally: p.write_bytes(original)
        return
    if fault == 'oversize': raw = b' ' * 5_000_001
    if fault == 'truncated-png': path, raw = 'evidence/browser/solar-0.056.png', b'\x89PNG\r\n\x1a\n'
    if fault in ('wrong-merge-mode', 'forged-merge'):
        from tools.ci_merge_tree_guard import prove_merge_tree
        head = real_attestation()['head']
        d = prove_merge_tree(head)
        d['merge_sha'] = '0' * 40
        if fault == 'forged-merge': d.update(mode='identical-tree', merge_tree=d['tree'])
        path, raw = 'evidence/merge-tree.json', json.dumps(d).encode()
    with evidence_file(path, raw) as p:
        link = p.with_name('hardlink-control')
        try:
            if fault == 'mode-world-write': p.chmod(0o666)
            if fault == 'hardlink': link.hardlink_to(p)
            assert not B._generated_evidence_ok(B.ROOT, path)
            assert not B.exact_blobs_ok()
        finally: link.unlink(missing_ok=True)
    # Optional generated outputs never constitute authority: absence is safe.
    assert B.exact_blobs_ok()

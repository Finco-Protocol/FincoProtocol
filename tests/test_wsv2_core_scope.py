"""Strict WS1 source admission and mandatory-browser negative controls."""
import ast
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import model_mutation_security_successor as S
from tests import wsv2_core_scope as F
from tests import wf04_scope as WF04

PRESENTATION = frozenset((
    'frontend/src/app/FinancialResults.tsx', 'frontend/src/app/WorkspaceView.tsx',
    'static/react/finco-react.js', 'static/react/finco-react.css',
))
OWNER_APPROVED_ACCEPTANCE = frozenset((
    'tests/model_react_mvp_acceptance.py',
    'tests/model_react_rcm_new_project_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_rcux_product_acceptance.py',
    'tests/test_model_react_poc_browser_acceptance.py',
    'tests/model_react_wf1_browser_acceptance.py',
    'tests/model_react_rcm_investors_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
))
ROLE = 'tests/test_model_workspace_consolidation_browser.py'
ACCEPTANCE = 'tests/model_react_wsv2_acceptance.py'
TESTS = (
    'test_wsv2_real_run_reads_exact_snapshot_without_document_reload',
    'test_wsv2_wizard_three_steps_library_and_safe_exception',
    'test_wsv2_refuses_same_run_with_split_freshness',
    'test_wsv2_before_visuals_use_exact_main_assets',
)


def test_closed_cohort_is_registered_exact_and_excludes_financial_authorities():
    assert F.__name__ in C.COHORT_MODULES and F in C.cohorts()
    assert F.exact_blobs_ok() and F.valid() and C.valid()
    assert F.protected_blobs() == {}
    assert {p for p in F.OWNED_PATHS if p.startswith('app/')} == {
        'app/templates/v2/react_poc.html', 'app/v2/react_overview.py', 'app/v2/react_rcux.py',
    }
    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/',
                                 'frontend/src/app/editing/')) for p in F.OWNED_PATHS)
    assert 'frontend/src/app/ppa/PPAEditorView.tsx' not in F.OWNED_PATHS


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS))
@pytest.mark.parametrize('operation', ('drift', 'delete'))
def test_every_owned_byte_and_deletion_fails_closed(path, operation, monkeypatch):
    original = F._read

    def altered(root, p, ref):
        if p == path and ref is None:
            if operation == 'delete':
                raise FileNotFoundError(path)
            return original(root, p, ref) + b'\n'
        return original(root, p, ref)

    monkeypatch.setattr(F, '_read', altered)
    assert not F.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('drop', (False, True))
def test_manifest_cannot_add_or_drop_any_pin(drop, monkeypatch):
    original = F._read

    def altered(root, path, ref):
        raw = original(root, path, ref)
        if path == F.MANIFEST and ref is None:
            data = json.loads(raw)
            if drop:
                data['source_blobs'].pop('app/v2/react_overview.py')
            else:
                data['source_blobs']['app/v2/router.py'] = '0' * 40
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(F, '_read', altered)
    assert not F.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('payload', ([], None, {'source_blobs': None}, {'source_blobs': []}))
def test_malformed_manifest_shapes_return_false(payload, monkeypatch):
    original = F._read

    def altered(root, path, ref):
        if path == F.MANIFEST and ref is None:
            malformed = payload
            if isinstance(payload, dict):
                malformed = {**json.loads(original(root, path, ref)), **payload}
            return json.dumps(malformed).encode()
        return original(root, path, ref)

    monkeypatch.setattr(F, '_read', altered)
    assert not F.manifest() and not F.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('path', (
    'app/v2/router.py', 'app/services/run_intent_service.py', 'app/workbook/mutation_csrf.py',
    'app/persistence/projects_repository.py', 'app/v2/save_all_commands.py',
    'financial_engine/native_v11/new.cpp', 'finco_core/inputs/valuation.py',
    '.github/workflows/unreviewed.yml', 'frontend/src/app/editing/store.ts',
    'tests/model_react_wsv2_future_acceptance.py', 'docs/react_migration/wsv2_core/unreviewed.md',
))
def test_unapproved_changed_or_untracked_path_is_refused(path, monkeypatch):
    assert not F.allowed_path(path)
    original = F._git

    def extra(root, *args):
        result = original(root, *args)
        if args[:2] == ('diff', '--name-only'):
            return result + b'\n' + path.encode()
        return result

    monkeypatch.setattr(F, '_git', extra)
    assert not F.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('attribute', ('BASE', 'AUTHORIZATION_HEAD'))
def test_wrong_or_missing_ancestry_fails_closed(attribute, monkeypatch):
    monkeypatch.setattr(F, attribute, '0' * 40)
    assert not F.exact_blobs_ok() and not C.valid()


def test_absent_or_unregistered_cohort_cannot_be_silently_omitted(monkeypatch):
    original = C.importlib.import_module

    def missing(name):
        if name == F.__name__:
            raise ModuleNotFoundError(name=name)
        return original(name)

    with monkeypatch.context() as patch:
        patch.setattr(C.importlib, 'import_module', missing)
        assert not C.valid()
    monkeypatch.setattr(C, 'COHORT_MODULES', tuple(n for n in C.COHORT_MODULES if n != F.__name__))
    assert not C.valid()


def test_correction_e_d029_role_pin_is_additive_and_preserves_negative_controls():
    path = 'tests/test_model_mutation_security_successor.py'
    assert path in F.OWNED_PATHS
    source = (F.ROOT / path).read_text()
    assert F.manifest()['source_blobs'][path] == F._blob(source.encode())
    assert S.RC_UX_SUCCESSORS[ROLE] != S.WSV2_BROWSER_SUCCESSORS[ROLE]
    role_source = (F.ROOT / ROLE).read_text()
    # WF-04 successor lineage: the WS1 role state, or - only while the whole WF-04 cohort is valid - exactly the WF-04 pinned later state.
    assert S.git_blob(role_source) == S.WSV2_BROWSER_SUCCESSORS[ROLE] or WF04.presentation_successor(ROLE, role_source)
    assert 'test_d029_browser_wrappers_are_exactly_the_seven_reviewed_cases_and_extras_are_refused' in source
    assert "assert S.git_blob(source) == S.WSV2_BROWSER_SUCCESSORS[path]" in source
    assert 'assert skipped[path]!=source and S.violations(skipped)' in source
    assert 'assert S.violations(extra)' in source


def test_original_presentation_and_security_dictionaries_are_immutable_and_individually_admitted():
    old = ast.parse(F._read(F.ROOT, 'tests/model_mutation_security_successor.py', F.AUTHORIZATION_HEAD))
    sources = {p: (S.ROOT / p).read_text() for p in S.BLOBS}
    assert set(S.WSV2_PRESENTATION_SUCCESSORS) == PRESENTATION
    assert set(S.WSV2_BROWSER_SUCCESSORS) == {ROLE}
    for node in old.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in ('SOURCE_HEAD', 'BLOBS') or name.endswith('_SUCCESSORS'):
            assert getattr(S, name) == ast.literal_eval(node.value), name
    for path in PRESENTATION | {ROLE}:
        # WF-04 successor lineage: for the three presentation paths only, the exact later state pinned by tests/wf04_scope.py is also the current state.
        assert (S.git_blob(sources[path]) == {**S.WSV2_PRESENTATION_SUCCESSORS, **S.WSV2_BROWSER_SUCCESSORS}[path]
                or WF04.presentation_successor(path, sources[path]))
        changed = dict(sources)
        changed[path] += '\n'
        assert S.violations(changed)
        changed[path] = F._read(F.ROOT, path, F.AUTHORIZATION_HEAD).decode()
        assert not [e for e in S.violations(changed) if e.startswith(path + ': unreviewed')]
    assert S.violations(sources) == [] and S.current_mutation_successor_valid()


def test_predecessor_manifest_pins_and_metadata_remain_verbatim():
    assert F._historical_manifests_ok(F.ROOT, None)
    for path in F.PREDECESSOR_MANIFESTS:
        old = json.loads(F._read(F.ROOT, path, F.AUTHORIZATION_HEAD))
        now = json.loads(F._read(F.ROOT, path, None))
        assert now['historical_source_blobs'][F.AUTHORIZATION_HEAD] == old['source_blobs']
        for p, value in old['source_blobs'].items():
            # WF-04 successor lineage: only the named, owner-authorised re-pins may move (tests/test_wf04_scope.py proves each equals the WF-04 pin).
            if path != F.PREDECESSOR_MANIFESTS[-1] and p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/')) \
                    and p not in F.WF04_SUCCESSOR_REPIN.get(path, ()):
                assert now['source_blobs'][p] == value


@pytest.mark.parametrize('tamper', ('history', 'financial_pin', 'metadata'))
def test_historical_record_or_unapproved_repin_cannot_be_resealed(tamper, monkeypatch):
    original = F._read

    def altered(root, path, ref):
        raw = original(root, path, ref)
        if path == F.PREDECESSOR_MANIFESTS[0] and ref is None:
            data = json.loads(raw)
            if tamper == 'history':
                data['historical_source_blobs'][F.AUTHORIZATION_HEAD]['app/v2/router.py'] = '0' * 40
            elif tamper == 'financial_pin':
                data['source_blobs']['app/v2/router.py'] = '0' * 40
            else:
                data['authorization'] = 'unreviewed'
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(F, '_read', altered)
    assert not F._historical_manifests_ok(F.ROOT, None)


def browser_contract_ok(role, acceptance):
    marker = '# WS1 Workspace V2'
    expected = 'from tests.model_react_wsv2_acceptance import *  # noqa: E402,F401,F403'
    # WF-04 successor lineage: the one later, separately governed block that may follow the WS1 import (tests/test_wf04_scope.py proves it exactly).
    tail = role[role.index(marker):].splitlines()[1:] if role.count(marker) == 1 else None
    if tail is None or tail[:1] != [expected] or tail[1:] not in ([], WF04.ROLE_IMPORT_BLOCK):
        return False
    prior = F._read(F.ROOT, ROLE, F.AUTHORIZATION_HEAD).decode()
    if role[:role.index(marker)].rstrip() != prior.rstrip():
        return False
    tree = ast.parse(acceptance)
    functions = tuple(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))
    exported = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and isinstance(n.targets[0], ast.Name) and n.targets[0].id == '__all__')
    return functions == TESTS and exported == list(TESTS) and not any(
        token in acceptance for token in ('importorskip', 'pytest.skip', 'mark.skip', 'skipif', 'xfail', 'autouse'))


def test_browser_registration_preserves_original_role_and_exact_new_exports():
    role = (F.ROOT / ROLE).read_text()
    acceptance = (F.ROOT / ACCEPTANCE).read_text()
    assert browser_contract_ok(role, acceptance)
    line = 'from tests.model_react_wsv2_acceptance import *  # noqa: E402,F401,F403'
    assert not browser_contract_ok(role.replace(line, ''), acceptance)
    assert not browser_contract_ok(role + line + '\n', acceptance)
    assert not browser_contract_ok(role, acceptance.replace('def ' + TESTS[1], 'def missing_test'))
    assert not browser_contract_ok(role, acceptance.replace('def ' + TESTS[1], '@pytest.mark.skip\ndef ' + TESTS[1]))


# The accepted WS1 integration (merged PR 398). Later, separately owned cohorts (WF-04, tests/wf04_scope.py) are judged by their own manifest and
# negative controls; this test keeps judging exactly the WS1 diff.
WS1_ACCEPTED_MERGE = 'b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3'


def test_ws1_diff_has_no_financial_run_integrity_or_ws2_source_change():
    changed = F._git(F.ROOT, 'diff', '--name-only', F.BASE, WS1_ACCEPTED_MERGE, '--').decode().splitlines()
    authorities = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'app/persistence/',
                   'app/workbook/', 'app/services/', 'frontend/src/app/editing/')
    assert not [p for p in changed if p.startswith(authorities)]
    assert 'app/v2/router.py' not in changed and 'app/v2/post_run_context.py' not in changed


def test_owner_approved_acceptance_exact_pins_identity_and_rejection():
    assert set(S.WSV2_ACCEPTANCE_SUCCESSORS) == OWNER_APPROVED_ACCEPTANCE
    assert OWNER_APPROVED_ACCEPTANCE <= F.OWNED_PATHS
    pins = F.manifest()['source_blobs']
    for path in OWNER_APPROVED_ACCEPTANCE:
        assert pins[path] == S.WSV2_ACCEPTANCE_SUCCESSORS[path]
        original = F._read(F.ROOT, path, F.AUTHORIZATION_HEAD).decode()
        current = F._read(F.ROOT, path, None).decode()
        assert S.git_blob(current) == pins[path]
        def tests(text):
            return [(n.name, [ast.dump(d, include_attributes=False) for d in n.decorator_list])
                    for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')]
        assert tests(original) == tests(current), path
        assert 'pytest.mark.skip' not in current and 'pytest.mark.xfail' not in current
        if path in S.BLOBS:
            sources = {p: (S.ROOT / p).read_text() for p in S.BLOBS}
            assert S.violations(sources) == []
            mutated = dict(sources)
            mutated[path] = current + '\n'
            assert S.violations(mutated)


@pytest.mark.parametrize('artifact', ('evidence/source.json', 'evidence/merge-tree.json',
                                      'evidence/browser/solar.png', 'evidence/financial-browser.xml'))
def test_generated_ci_evidence_does_not_turn_valid_financial_sources_into_unreviewed(artifact, monkeypatch):
    original = F._git
    def with_generated_evidence(root, *args):
        found = original(root, *args)
        if args[:3] == ('ls-files', '--others', '--exclude-standard'):
            return found + artifact.encode() + b'\n'
        return found
    monkeypatch.setattr(F, '_git', with_generated_evidence)
    assert F.exact_blobs_ok() and C.valid()


@pytest.mark.parametrize('unreviewed', ('evidence/rogue.py', 'evidence/rogue.ts',
                                      'app/v2/new_writer.py', 'tests/new_financial_test.py'))
def test_untracked_source_is_still_strictly_rejected(unreviewed, monkeypatch):
    original = F._git
    def with_unreviewed_source(root, *args):
        found = original(root, *args)
        if args[:3] == ('ls-files', '--others', '--exclude-standard'):
            return found + unreviewed.encode() + b'\n'
        return found
    monkeypatch.setattr(F, '_git', with_unreviewed_source)
    assert not F.exact_blobs_ok() and not C.valid()

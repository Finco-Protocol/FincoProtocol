"""Negative controls for the finite RC-UX Completion V1 exact-source cohort and its place in the FIN-V2 cohort registry."""
import json

import pytest

from tests import fin_v2_cohorts as C
from tests import fin_v2_rcux_scope as F


def test_the_cohort_is_registered_valid_and_owns_no_financial_namespace(tmp_path):
    assert F.__name__ in C.COHORT_MODULES and F in C.cohorts()
    assert F.valid() and C.valid()
    assert not F.valid(tmp_path)
    assert F.protected_blobs() == {} and not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/')) for p in F.OWNED_PATHS)
    assert not F.matches('financial_engine/dsra/target.py') and not C.matches('unreviewed/new_financial_authority.py')


def test_the_owned_protected_sources_are_exactly_the_read_only_react_adapters_and_the_cohort_itself():
    assert {p for p in F.OWNED_PATHS if p.startswith('app/')} == {
        'app/v2/react_capex.py', 'app/v2/react_compare.py', 'app/v2/react_goal_seek_targets.py', 'app/v2/react_import.py', 'app/v2/react_opex_projection.py', 'app/v2/react_projects.py', 'app/v2/react_rcux.py',
        'app/v2/react_trust.py', 'app/v2/react_whatif.py', 'app/v2/react_workspace_router.py'}
    assert {p for p in F.OWNED_PATHS if not p.startswith('app/')} == {'tests/fin_v2_rcux_scope.py', 'tests/rcux_navigation_contract.py', 'tests/test_fin_v2_rcux_scope.py'}


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS - {'tests/test_fin_v2_rcux_scope.py'}))
def test_one_byte_or_deletion_in_each_owned_source_fails_closed(path, monkeypatch):
    raw = (F.ROOT / path).read_bytes()
    assert F.matches(path, raw)
    assert not F.matches(path, raw + b'\n')
    original = F._read

    def missing(root, p, ref):
        if p == path:
            raise FileNotFoundError(path)
        return original(root, p, ref)
    monkeypatch.setattr(F, '_read', missing)
    assert not F.valid() and not F.exact_blobs_ok()
    assert not C.valid()


def test_manifest_cannot_add_or_drop_a_source_path(monkeypatch):
    original = F._read

    def altered(drop):
        def read(root, p, ref):
            raw = original(root, p, ref)
            if p == F.MANIFEST:
                data = json.loads(raw)
                if drop:
                    data['source_blobs'].pop('app/v2/react_capex.py')
                else:
                    data['source_blobs']['app/v2/router.py'] = '0' * 40
                return json.dumps(data).encode()
            return raw
        return read
    for drop in (False, True):
        monkeypatch.setattr(F, '_read', altered(drop))
        assert not F.valid() and not C.valid()


@pytest.mark.parametrize('path', ['app/v2/router.py', 'app/input_adapter.py', 'app/api/project_runner.py', 'app/v2/react_new_project.py',
                                  'app/v2/react_goal_seek.py', 'app/workbook/registry.py', 'financial_engine/dsra/target.py',
                                  'finco_core/inputs/shl_timing.py', '.github/workflows/ci_public_job.yml', 'main_web.py',
                                  'tests/test_fin_v2_r1_scope.py', 'static/react/other.js', 'frontend/package.json',
                                  # a future / unreviewed module is NOT admitted by name pattern: it must be added to PRESENTATION_FILES explicitly
                                  'tests/rcux_other_helper.py', 'tests/test_rcux_unreviewed.py', 'tests/model_react_future_acceptance.py',
                                  'tests/test_model_react_rcux_future_v1.py', 'tests/test_model_react_new_unreviewed_v1.py', 'tests/react_other.py',
                                  'docs/react_migration/rc_ux_completion/handover/tools/evil.py', 'docs/react_migration/rc_ux_completion/x.py',
                                  'frontend/src/evil.py'])
def test_the_presentation_set_never_admits_a_protected_unreviewed_or_future_python_module(path):
    assert not F.PRESENTATION.match(path) and path not in F.OWNED_PATHS


def test_every_exactly_admitted_file_exists_and_none_is_a_protected_namespace():
    for path in F.PRESENTATION_FILES:
        assert (F.ROOT / path).is_file(), path
        assert not path.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/')) and path != 'main_web.py', path
    assert 'tests/rcux_navigation_contract.py' in F.OWNED_PATHS and 'tests/test_rcux_navigation_source.py' in F.PRESENTATION_FILES
    assert F.matches('tests/rcux_navigation_contract.py', (F.ROOT / 'tests/rcux_navigation_contract.py').read_bytes())
    assert not F.matches('tests/rcux_navigation_contract.py', (F.ROOT / 'tests/rcux_navigation_contract.py').read_bytes() + b'\n')


@pytest.mark.parametrize('path', ['frontend/src/app/WorkspaceView.tsx', 'static/react/finco-react.js', 'tests/model_react_rcux_runs_acceptance.py',
                                  'tests/test_model_react_rcux_compare_v1.py', 'tests/test_model_react_poc_browser_acceptance.py',
                                  'tests/react_run_identity.py', 'docs/react_migration/rc_ux_completion/README.md'])
def test_the_presentation_set_admits_the_reviewed_react_surfaces(path):
    assert F.PRESENTATION.match(path)


def test_presentation_paths_are_owned_at_path_level_only_never_as_a_byte_match():
    assert F.matches('frontend/src/app/WorkspaceView.tsx') and C.matches('static/react/finco-react.js')
    assert not F.matches('frontend/src/app/WorkspaceView.tsx', b'anything') and not F.matches('static/react/other.js')
    assert not F.matches('app/v2/router.py') and not F.matches('financial_engine/dsra/target.py')


def test_extra_path_outside_every_registered_cohort_is_rejected(monkeypatch):
    assert F.valid()
    for extra_path in ('financial_engine/dsra/unreviewed_reserve_waterfall.py', 'app/v2/router_unreviewed.py'):
        original = F._git

        def extra(root, *args, _p=extra_path, _o=original):
            out = _o(root, *args)
            return out + b'\n' + _p.encode() if args[:2] == ('diff', '--name-only') else out
        monkeypatch.setattr(F, '_git', extra)
        assert not F.valid()
        monkeypatch.setattr(F, '_git', original)


def test_a_non_ancestor_base_is_rejected(monkeypatch):
    monkeypatch.setattr(F, 'BASE', '0' * 40)
    assert not F.valid() and not F.exact_blobs_ok()


def test_every_new_react_or_rcux_module_in_the_tree_is_explicitly_admitted_tracked_or_not():
    """Catches the 'new module not yet admitted' mistake BEFORE it is committed (an untracked file is invisible to the git-diff based composite).

    A module that did not exist at the accepted parent and that sits where RC-UX work lives must be named in OWNED_PATHS / PRESENTATION_FILES, or be
    admitted by another registered cohort.  Pre-existing modules (the RC-M / WF adapters) are not RC-UX's to claim and are skipped.
    """
    import re
    import subprocess
    names = re.compile(r'^(tests/(test_model_react_.+|model_react_.+|test_rcux_.+|rcux_.+|test_fin_v2_rcux_.+|fin_v2_rcux_.+|react_.+)\.py|app/v2/react_.+\.py)$')
    admitted = F.PRESENTATION_FILES | F.OWNED_PATHS

    def existed_at_parent(path):
        return subprocess.run(['git', 'cat-file', '-e', F.BASE + ':' + path], cwd=F.ROOT, capture_output=True).returncode == 0

    present = {p.relative_to(F.ROOT).as_posix() for p in list((F.ROOT / 'tests').glob('*.py')) + list((F.ROOT / 'app/v2').glob('react_*.py'))}
    others = [m for m in C.cohorts() if m is not F]
    unadmitted = sorted(p for p in present if names.match(p) and p not in admitted and not existed_at_parent(p)
                        and not any(m.allowed_path(p, F.ROOT, None) for m in others))
    assert unadmitted == [], unadmitted

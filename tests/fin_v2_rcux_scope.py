"""Additive exact-blob RC-UX Completion V1 cohort (React presentation + read-only adapters).

Recognition authorizes only the recorded RC-UX successor: the read-only ``app/v2/react_*`` adapters and their one aggregator mount, the React
frontend sources, the rebuilt committed bundle, the RC-UX tests and the RC-UX documents.  It touches no financial engine, persistence, CSRF,
workbook, export or CI path, merges no PR and activates nothing.  Pins are exact Git blobs for every owned protected source; the presentation
surfaces (``frontend/src``, the bundle, browser acceptance modules, documents) are admitted by a closed path pattern and are additionally
pinned file-by-file in ``RC_UX_SUCCESSORS`` (``tests/model_mutation_security_successor.py``).  Any other changed path, byte, deletion or
untracked protected source fails closed.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Same accepted parent as every other FIN-V2 cohort: main after merged PR #388 (RC-M) and #390.
BASE = 'f79e251903621c1a5c88501d51d6971960b612d3'
MANIFEST = 'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json'
SCHEMA = 'RC_UX_EXACT_SOURCE_V1'
PROTECTED = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py')

OWNED_PATHS = frozenset((
    'app/v2/react_capex.py',
    'app/v2/react_compare.py',
    'app/v2/react_compare_projects.py',
    'app/v2/react_goal_seek_targets.py',
    'app/v2/react_import.py',
    'app/v2/react_opex_projection.py',
    'app/v2/react_projects.py',
    'app/v2/react_rcux.py',
    'app/v2/react_trust.py',
    'app/v2/react_whatif.py',
    'app/v2/react_workspace_router.py',
    'tests/fin_v2_rcux_scope.py',
    'tests/rcux_navigation_contract.py',        # the pure navigation classifier: byte-pinned, so the React-only rule cannot be loosened unreviewed
    'tests/test_fin_v2_rcux_scope.py',
))

#: Reviewed test / bundle files, admitted by EXACT path (no pattern): a new RC-UX test, acceptance or helper module is not admitted until its path is
#: added here, in the same reviewed change as the module itself.  Their bytes are additionally pinned file-by-file in ``RC_UX_SUCCESSORS``
#: (``tests/model_mutation_security_successor.py``) wherever the original protected layers covered them.
PRESENTATION_FILES = frozenset((
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/model_react_rcm_analysis_acceptance.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/model_react_rcm_new_project_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_rcux_capex_acceptance.py',
    'tests/model_react_rcux_import_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_rcux_product_acceptance.py',
    'tests/model_react_rcux_runs_acceptance.py',
    'tests/model_react_rcux_whatif_acceptance.py',
    'tests/model_react_wf1_browser_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/model_react_wf2_lifecycle_acceptance.py',
    'tests/react_run_identity.py',
    'tests/test_model_react_overnight_b_v1.py',
    'tests/test_model_react_poc_browser_acceptance.py',
    'tests/test_model_react_rcux_capex_v1.py',
    'tests/test_model_react_rcux_compare_projects_v1.py',
    'tests/test_model_react_rcux_compare_v1.py',
    'tests/test_model_react_rcux_goal_seek_targets_v1.py',
    'tests/test_model_react_rcux_import_v1.py',
    'tests/test_model_react_rcux_opex_projection_v1.py',
    'tests/test_model_react_rcux_projects_v1.py',
    'tests/test_model_react_rcux_trust_v1.py',
    'tests/test_model_react_rcux_whatif_v1.py',
    'tests/test_model_react_ux040506_v1.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_rcux_governance.py',
    'tests/test_rcux_navigation_source.py',
    'docs/react_migration/rc_ux_completion/handover/tools/build_register.py',
    'docs/react_migration/rc_ux_completion/handover/tools/refresh_pins.py',
))
#: The only patterns: the React frontend source tree and the RC-UX documents (never a Python file).
_PATTERN = re.compile(r'^(frontend/src/.+\.(ts|tsx|css|mjs)|docs/react_migration/rc_ux_completion/.+\.(md|csv|txt|json))$')


class _Presentation:
    """``PRESENTATION.match(path)``: an exact reviewed file, or the frontend source tree / RC-UX documents by pattern."""

    @staticmethod
    def match(path):
        return path in PRESENTATION_FILES or bool(_PATTERN.match(path))


PRESENTATION = _Presentation()


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if data.get('schema_version') == SCHEMA and data.get('base') == BASE else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def exact_blobs_ok(repo=None, ref=None):
    """History and every owned byte: the pin set equals the owned set and each pin is the exact Git blob."""
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if set(pins) != OWNED_PATHS:
        return False
    try:
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        return all(_blob(_read(root, p, ref)) == expected for p, expected in pins.items())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    return path in pins or path == MANIFEST or bool(PRESENTATION.match(path))


def _other_cohort_allows(path, root, ref):
    """A path owned by ANOTHER registered reviewed cohort (tests/fin_v2_cohorts.py) is that cohort's exact-blob responsibility."""
    try:
        from tests.fin_v2_cohorts import cohorts
    except ImportError:
        return False
    return any(m.__name__ != __name__ and m.allowed_path(path, root, ref) for m in cohorts())


def valid(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if not exact_blobs_ok(root, ref):
        return False
    try:
        changed = _git(root, 'diff', '--name-only', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any(not allowed_path(p, root, ref) and not _other_cohort_allows(p, root, ref) for p in changed):
            return False
        if ref is None:
            pins = manifest(root, ref).get('source_blobs', {})
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '--', *PROTECTED).decode().splitlines()
            if any(p not in pins and not _other_cohort_allows(p, root, ref) for p in untracked):
                return False
        return True
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def matches(path, source=None, *, repo=None, ref=None):
    """Path-level ownership (``source is None``) covers the closed presentation pattern; a given byte string must be an exact pinned blob."""
    pins = manifest(repo, ref).get('source_blobs', {})
    if source is None and PRESENTATION.match(path):
        return valid(repo, ref)
    if path not in pins or not valid(repo, ref):
        return False
    if source is None:
        return True
    raw = source.encode() if isinstance(source, str) else source
    return _blob(raw) == pins[path]


def protected_blobs(repo=None, ref=None):
    """RC-UX owns no financial_engine/finco_core/domain source; this cohort can never widen the frozen financial namespace."""
    return {}

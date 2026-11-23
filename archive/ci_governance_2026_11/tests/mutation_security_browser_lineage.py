"""Proposed security review of the mandatory browser role's accepted UX lineage."""
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ROLE = "tests/test_model_workspace_consolidation_browser.py"
R1_WRAPPER = (
    b"def test_r1_stale_ppa_document_is_never_replayed_by_a_second_tab(browser, react_enabled):\n"
    b"    from tests.model_react_r1_ppa_two_tab_acceptance import check_r1_stale_ppa_document_is_never_replayed_by_a_second_tab\n"
    b"    check_r1_stale_ppa_document_is_never_replayed_by_a_second_tab(browser, react_enabled)\n\n\n"
)
# First-parent merges containing the reviewed role. Only the last role state is
# proposed as current. Earlier states remain evidence of the historical checks.
HISTORY = (
    ("36edeeb5d9a14749fdfafcd3b60a0d384cac73ba", "76692a9edc8da4418e29c2d8dc52d3847f4eac34"),  # #383
    ("6c642adcd193691818f1413bf5273885470c8ef9", "f1a762a4f7bbfca34e8e93c74fbba3042d970665"),  # #384 D029
    ("cf7056de4078ca66afcf52265a9bacafe35586f7", "6f91b8c9376ba65c27aab34ea39651cef351b2e9"),  # #386 Overnight B
    ("b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3", "7c6478289c029f8b53e16103fa22b22123cbd19a"),  # #398 WS1
    ("db504f6408cb456c617c9342a1ffa202ee455283", "e5f3ace7a7406fc2b487ef90eab369e4ed51955b"),  # #399 WF04
    ("33ca245b533116825685c77b26b8bc87705813e7", "bf53a54e3d0abb9ce2b66a34f175834296e0ada2"),  # #400 WF03
    ("cd125b5e08302ea1db7169e172fec288aa7acea5", "2d0b5c1abc6c64a47ec925244f0b098cca67fb39"),  # #419 R1
    ("713c0daf434dd79616f5a07451de6accddde93e0", "f3d6bac063ac94ac33d4dd18e970f9c515935929"),  # #426 UX-PR1
    ("f0ead1687bafd41db7472e4009234d0410451210", "d883b8d54353a9c86dc3c0d1b14b5adab57c2957"),  # #428 UX-PR2b
    ("4e22f330d97eec66befcbb5df6dc4e1529ae6835", "ff1137eb91ad5bc08f1c9f79375fae0b132a4862"),  # #430 UX-PR3b1
    ("785024c752bbd1700d6051cf15115d9980d0b4a1", "423ec822d396a2e83ea58525222de70828909858"),  # #431 UX-PR3b2
)
IMPORTS = (
    ("model_react_ux_pr2b_acceptance", "a38c85456ba8d2ddf2783a70183f76d6939297d7"),
    ("model_react_pr3b1_acceptance", "6fc916b9963d5c6d982015cd31b5696284af0a37"),
    ("model_react_pr3b2_acceptance", "820ce2ef0c771266493724c46d12e1bdac9b11df"),
)
WF03_REF, WF03_BLOB = HISTORY[5]
WF03_IMPORT = b"from tests.test_project_lifecycle_browser import wf03_servers, wf03_browser  # noqa: F401\n"
WF03_ADAPTER = (
    b"from tests.test_project_lifecycle_browser import wf03_servers, wf03_browser as _wf03_browser  # noqa: F401\n"
    b"\n\n"
    b"@pytest.fixture\n"
    b"def wf03_browser(request):\n"
    b"    # Keep the helper module unchanged and the selected cases individually attributable.\n"
    b'    pytest.importorskip("playwright.sync_api", reason="playwright not installed in this workflow")\n'
    b'    return request.getfixturevalue("_wf03_browser")\n'
)


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _entry(root, ref, path, blob):
    return _git(root, "ls-tree", "-r", "-z", ref, "--", path) == f"100644 blob {blob}\t{path}\0".encode()


def _blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _current_entry(root, ref, path, blob):
    if ref is not None:
        return _entry(root, ref, path, blob)
    file = root / path
    return (file.is_file() and not file.is_symlink() and not file.stat().st_mode & 0o111
            and _blob(file.read_bytes()) == blob)


def role_violations(*, repo=None, ref=None):
    """Check the candidate role against literal Git sources and predecessor semantics."""
    root = Path(repo) if repo is not None else ROOT
    try:
        head = ref if ref is not None else "HEAD"
        snapshots = []
        for revision, blob in HISTORY:
            if not _entry(root, revision, ROLE, blob):
                return ["SECURITY_ROLE_HISTORY"]
            snapshots.append(_git(root, "show", f"{revision}:{ROLE}"))
        revisions = [revision for revision, _ in HISTORY] + [head]
        for before, after in zip(revisions, revisions[1:]):
            _git(root, "merge-base", "--is-ancestor", before, after)
        if not _current_entry(root, ref, ROLE, HISTORY[-1][1]):
            return ["SECURITY_ROLE_CURRENT"]
        wf03, r1, pr1 = snapshots[5:8]
        if r1.count(R1_WRAPPER) != 1 or r1.replace(R1_WRAPPER, b"", 1) != wf03:
            return ["SECURITY_R1_WRAPPER"]
        if r1.count(WF03_IMPORT) != 1 or r1.replace(WF03_IMPORT, WF03_ADAPTER, 1) != pr1:
            return ["SECURITY_WF03_FIXTURE"]
        for index, (module, blob) in enumerate(IMPORTS, start=8):
            import_line = f"from tests.{module} import *  # noqa: E402,F401,F403\n".encode()
            preceding = snapshots[index - 1]
            current = snapshots[index]
            added = current[len(preceding):].strip().splitlines()
            added_imports = [line for line in added if not line.startswith(b"#")]
            if not current.startswith(preceding) or added_imports != [import_line.strip()]:
                return ["SECURITY_ROLE_IMPORT"]
            path = f"tests/{module}.py"
            if not _entry(root, HISTORY[index][0], path, blob) or not _current_entry(root, ref, path, blob):
                return ["SECURITY_ROLE_IMPORT_SOURCE"]
        return []
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return ["SECURITY_ROLE_FACTS_UNAVAILABLE"]

def verified_pre_r1_source(source, *, repo=None):
    """Project only the authenticated current role to the exact historical WF03 source."""
    root = Path(repo) if repo is not None else ROOT
    if _blob(source.encode()) != HISTORY[-1][1] or role_violations(repo=root):
        return None
    return _git(root, "show", f"{WF03_REF}:{ROLE}").decode()

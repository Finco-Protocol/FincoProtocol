"""Exact-source tests for the proposed security browser role successor."""
import pytest

from tests import mutation_security_browser_lineage as lineage
from test_v11_stage3_successor import head, mutate, repo, show  # noqa: F401


def test_browser_role_candidate_matches_merged_sources():
    assert lineage.role_violations() == []
    assert lineage.role_violations(ref="HEAD") == []
    current = (lineage.ROOT / lineage.ROLE).read_text()
    previous = lineage.verified_pre_r1_source(current)
    assert previous is not None and lineage._blob(previous.encode()) == lineage.WF03_BLOB
    assert lineage.verified_pre_r1_source(current + "\n") is None


@pytest.mark.parametrize("change", ["one-byte", "missing", "foreign", "renamed", "semantics", "stale", "import-drift"])
def test_candidate_role_rejects_unreviewed_changes(repo, tmp_path, head, change):  # noqa: F811
    role = lineage.ROLE
    original = show(repo, head, role)
    changes = {role: original + b"\n"}
    error = "SECURITY_ROLE_CURRENT"
    if change == "missing":
        changes = {role: None}
    elif change == "foreign":
        changes = {role: b"# unrelated file\n"}
    elif change == "renamed":
        changes = {role: None, "tests/test_renamed_browser_role.py": original}
    elif change == "semantics":
        changes = {role: original.replace(lineage.WF03_ADAPTER, lineage.WF03_IMPORT, 1)}
        assert changes[role] != original
    elif change == "stale":
        changes = {role: show(repo, lineage.HISTORY[-2][0], role)}
    elif change == "import-drift":
        path = "tests/model_react_pr3b2_acceptance.py"
        changes = {path: show(repo, head, path) + b"\n"}
        error = "SECURITY_ROLE_IMPORT_SOURCE"
    ref = mutate(repo, tmp_path, head, changes)
    assert lineage.role_violations(repo=repo, ref=ref) == [error]


def test_candidate_rejects_executable_browser_role_in_worktree(tmp_path):
    # Copy the exact role and make it executable. The validator reads Git history
    # from the real repository and rejects the evaluated file before any import.
    import subprocess

    subprocess.run(["git", "worktree", "add", "--detach", str(tmp_path / "tree"), "HEAD"],
                   cwd=lineage.ROOT, check=True, capture_output=True)
    tree = tmp_path / "tree"
    try:
        role = tree / lineage.ROLE
        assert lineage.role_violations(repo=tree) == []
        role.chmod(0o755)
        assert lineage.role_violations(repo=tree) == ["SECURITY_ROLE_CURRENT"]
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)],
                       cwd=lineage.ROOT, check=True, capture_output=True)

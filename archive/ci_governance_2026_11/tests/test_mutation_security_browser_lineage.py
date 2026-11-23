"""Exact-source tests for the proposed security browser role successor."""
import subprocess

import pytest

from tests import mutation_security_browser_lineage as lineage


@pytest.fixture(scope="module")
def role_tree(tmp_path_factory):
    tree = tmp_path_factory.mktemp("security-browser-lineage") / "tree"
    subprocess.run(["git", "worktree", "add", "--detach", str(tree), "HEAD"],
                   cwd=lineage.ROOT, check=True, capture_output=True)
    try:
        yield tree
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)],
                       cwd=lineage.ROOT, check=True, capture_output=True)


def test_browser_role_candidate_matches_merged_sources():
    assert lineage.role_violations() == []
    assert lineage.role_violations(ref="HEAD") == []
    current = (lineage.ROOT / lineage.ROLE).read_text()
    previous = lineage.verified_pre_r1_source(current)
    assert previous is not None and lineage._blob(previous.encode()) == lineage.WF03_BLOB
    assert lineage.verified_pre_r1_source(current + "\n") is None


@pytest.mark.parametrize("change", ["one-byte", "missing", "foreign", "renamed", "semantics", "stale", "import-drift", "mode"])
def test_candidate_role_rejects_unreviewed_changes(role_tree, change):
    role = role_tree / lineage.ROLE
    imported = role_tree / "tests/model_react_pr3b2_acceptance.py"
    renamed = role.with_name("test_renamed_browser_role.py")
    original = role.read_bytes()
    expected = "SECURITY_ROLE_CURRENT"
    assert lineage.role_violations(repo=role_tree) == []
    try:
        if change == "one-byte":
            role.write_bytes(original + b"\n")
        elif change == "missing":
            role.unlink()
        elif change == "foreign":
            role.write_bytes(b"# unrelated file\n")
        elif change == "renamed":
            role.rename(renamed)
        elif change == "semantics":
            modified = original.replace(lineage.WF03_ADAPTER, lineage.WF03_IMPORT, 1)
            assert modified != original
            role.write_bytes(modified)
        elif change == "stale":
            role.write_bytes(lineage._git(role_tree, "show", f"{lineage.HISTORY[-2][0]}:{lineage.ROLE}"))
        elif change == "import-drift":
            imported.write_bytes(imported.read_bytes() + b"\n")
            expected = "SECURITY_ROLE_IMPORT_SOURCE"
        elif change == "mode":
            role.chmod(0o755)
        assert lineage.role_violations(repo=role_tree) == [expected]
    finally:
        if role.exists():
            role.chmod(0o644)
        renamed.unlink(missing_ok=True)
        subprocess.run(["git", "restore", "--", lineage.ROLE, str(imported.relative_to(role_tree))],
                       cwd=role_tree, check=True, capture_output=True)

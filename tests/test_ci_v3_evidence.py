"""Evidence is bound to the exact executed source/image and rejects substitution, drift and stray source changes."""
import io
import json
import subprocess
import tarfile

import pytest

from tools import ci_v3_evidence as ev
from tools.ci_v3_schema import ContractError, write_json

IMAGE = {"image_id": "sha256:img", "registry_digest": None}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def make_run(path, label, kind="target", tree=None, image="sha256:img", historical=False, module="tests/test_a.py"):
    path.mkdir(parents=True); (path / "lane-0").mkdir()
    meta = {"kind": kind, "label": label, "image_id": image, "tree": tree, "concurrency": 3}
    if historical:
        meta["historical"] = True
    write_json(path / "meta.json", meta)
    xml = b"<testsuite tests='1'><testcase classname='tests.test_a' name='t'/></testsuite>"
    (path / "lane-0" / "tests__test_a.xml").write_bytes(xml)
    row = {"module": module, "tag": None, "exit_code": 0, "timed_out": False, "failures": 0, "errors": 0, "skipped": 0, "tests": 1,
           "seconds": 1, "tail": "", "junit_sha256": ev.sha(xml)}
    (path / "lane-0" / "results.jsonl").write_text(json.dumps(row) + "\n")


def write_nodes(path, ids):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as tar:
        data = "\n".join(ids).encode(); info = tarfile.TarInfo("node-ids.txt"); info.size = len(data); tar.addfile(info, io.BytesIO(data))
    path.write_bytes(buffer.getvalue())


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"; (repo / "tools").mkdir(parents=True); (repo / ev.EVIDENCE_DIR).mkdir(parents=True)
    (repo / "tools/ci_v3_x.py").write_text("X = 1\n"); (repo / "app.py").write_text("A = 1\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "source")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    evidence = repo / ev.EVIDENCE_DIR
    make_run(tmp_path / "run", "exact", tree=tree)
    ev.pack_attempt(tmp_path / "run", evidence / "attempts/exact")
    image_dir = tmp_path / "image"; image_dir.mkdir(); write_json(image_dir / "image.json", IMAGE)
    ids = ["tests/test_a.py::t"]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as tar:
        data = "\n".join(ids).encode(); info = tarfile.TarInfo("node-ids.txt"); info.size = len(data); tar.addfile(info, io.BytesIO(data))
    archive = tmp_path / "nodes.tar.xz"; archive.write_bytes(buffer.getvalue())
    inventory = tmp_path / "inventory.json"; write_json(inventory, {"nodes": [{"nodeid": i} for i in ids], "source": {"head": head, "tree": tree}, "digest": "d"})
    write_json(evidence / "collection-skips.json", [])
    return dict(repo=repo, evidence=evidence, image_dir=image_dir, inventory=inventory, archive=archive, head=head, tree=tree, tmp=tmp_path)


def build(w, extra=("collection-skips.json",)):
    manifest = ev.build(w["repo"], w["evidence"], w["image_dir"], w["inventory"], w["archive"], list(extra))
    write_json(w["evidence"] / "manifest.json", manifest)
    return manifest


def commit_evidence(w):
    git(w["repo"], "add", "-A"); git(w["repo"], "commit", "-qm", "evidence")


def test_round_trip_and_followup_limited_to_evidence_paths(world):
    build(world)
    commit_evidence(world)     # evidence/manifest added after the executed source
    result = ev.verify(world["repo"], world["evidence"])
    assert result["verified"] and all(p.startswith(ev.ALLOWED_FOLLOWUP) for p in result["published_head_differs_from_source_by"])


def test_dirty_or_wrong_source_is_rejected(world):
    (world["repo"] / "app.py").write_text("A = 2\n")
    with pytest.raises(ContractError, match="clean committed"):
        build(world)


def test_attempt_from_other_tree_or_image_is_rejected_unless_marked_historical(world):
    make_run(world["tmp"] / "other", "other", tree=world["tree"], image="sha256:other"); ev.pack_attempt(world["tmp"] / "other", world["evidence"] / "attempts/other")
    with pytest.raises(ContractError, match="evidence image"):
        build(world)
    for p in (world["evidence"] / "attempts/other").iterdir():
        p.unlink()
    (world["evidence"] / "attempts/other").rmdir()
    make_run(world["tmp"] / "old", "old", tree="f" * 40, image="sha256:old", historical=True)
    ev.pack_attempt(world["tmp"] / "old", world["evidence"] / "attempts/old")
    assert any(a["historical"] for a in build(world)["attempts"])


def test_source_change_outside_evidence_after_execution_is_rejected(world):
    build(world); commit_evidence(world)
    (world["repo"] / "app.py").write_text("A = 3\n"); git(world["repo"], "add", "-A"); git(world["repo"], "commit", "-qm", "sneaky")
    with pytest.raises(ContractError, match="outside evidence paths"):
        ev.verify(world["repo"], world["evidence"])


@pytest.mark.parametrize("tamper", ["results", "junit", "extra-file", "manifest"])
def test_tampered_evidence_is_detected(world, tamper):
    build(world); commit_evidence(world)
    attempt = world["evidence"] / "attempts/exact"
    if tamper == "results":
        (attempt / "results.jsonl").write_text((attempt / "results.jsonl").read_text().replace('"tests": 1', '"tests": 2'))
    elif tamper == "junit":
        (attempt / "junit.tar.xz").write_bytes((attempt / "junit.tar.xz").read_bytes() + b"x")
    elif tamper == "extra-file":
        (world["evidence"] / "collection-skips.json").write_text("[1]\n")
    else:
        m = json.loads((world["evidence"] / "manifest.json").read_text()); m["source"]["head"] = "0" * 40
        (world["evidence"] / "manifest.json").write_text(json.dumps(m))
    with pytest.raises((ContractError, OSError, subprocess.CalledProcessError, tarfile.TarError)):
        ev.verify(world["repo"], world["evidence"])


def test_tool_file_changed_after_execution_is_detected(world):
    build(world)
    (world["repo"] / "tools/ci_v3_x.py").write_text("X = 2\n"); git(world["repo"], "add", "-A"); git(world["repo"], "commit", "-qm", "tool")
    with pytest.raises(ContractError):
        ev.verify(world["repo"], world["evidence"])


def test_inventory_from_another_tree_is_rejected(world):
    inv = json.loads(world["inventory"].read_text()); inv["source"]["tree"] = "e" * 40; world["inventory"].write_text(json.dumps(inv))
    with pytest.raises(ContractError, match="different source tree"):
        build(world)


def commit_file(w, path, text, message="change"):
    target = w["repo"] / path
    target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
    git(w["repo"], "add", path); git(w["repo"], "commit", "-qm", message)   # evidence files stay untracked, as in production
    return subprocess.check_output(["git", "-C", str(w["repo"]), "rev-parse", "HEAD^{tree}"], text=True).strip()


@pytest.mark.parametrize("path,text,ok", [("tools/ci_v3_newtool.py", "N = 1\n", True), ("tests/test_ci_v3_new.py", "def test_x(): pass\n", True),
    ("docs/ci_v3/phase3c/README.md", "doc\n", True), ("tools/ci_v3_probe_run.py", "changed\n", False), ("app.py", "A = 9\n", False),
    ("tests/test_other.py", "def test_y(): pass\n", False)])
def test_carry_forward_allows_only_ci_v3_internal_additions_and_docs(world, path, text, ok):
    (world["repo"] / "tools/ci_v3_probe_run.py").write_text("base\n"); git(world["repo"], "add", "tools/ci_v3_probe_run.py"); git(world["repo"], "commit", "-qm", "base")
    base_tree = subprocess.check_output(["git", "-C", str(world["repo"]), "rev-parse", "HEAD^{tree}"], text=True).strip()
    new_tree = commit_file(world, path, text)
    if ok:
        assert ev.carry_forward_changes(world["repo"], base_tree, new_tree)[0][1] == path
    else:
        with pytest.raises(ContractError, match="invalidates evidence"):
            ev.carry_forward_changes(world["repo"], base_tree, new_tree)


def test_manifest_records_and_reverifies_carried_forward_attempts(world):
    base_tree = world["tree"]
    make_run(world["tmp"] / "baseline", "baseline", tree=base_tree)
    ev.pack_attempt(world["tmp"] / "baseline", world["evidence"] / "attempts/baseline")
    for p in (world["evidence"] / "attempts/exact").iterdir():
        p.unlink()
    (world["evidence"] / "attempts/exact").rmdir()
    commit_file(world, "tools/ci_v3_newtool.py", "N = 1\n")        # later tree: a CI-V3-internal addition
    world["head"] = subprocess.check_output(["git", "-C", str(world["repo"]), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(world["repo"]), "rev-parse", "HEAD^{tree}"], text=True).strip()
    inv = json.loads(world["inventory"].read_text()); inv["source"] = {"head": world["head"], "tree": tree}; world["inventory"].write_text(json.dumps(inv))
    manifest = build(world)
    assert manifest["carried_forward_from"][base_tree] == [["A", "tools/ci_v3_newtool.py"]]
    commit_evidence(world)
    assert ev.verify(world["repo"], world["evidence"])["verified"]


def test_changed_ci_v3_tool_requires_all_ci_v3_self_tests_at_the_final_tree(world):
    base_tree = world["tree"]
    make_run(world["tmp"] / "baseline", "baseline", tree=base_tree, module="tests/test_ci_v3_x.py")
    ev.pack_attempt(world["tmp"] / "baseline", world["evidence"] / "attempts/baseline")
    for p in (world["evidence"] / "attempts/exact").iterdir():
        p.unlink()
    (world["evidence"] / "attempts/exact").rmdir()
    commit_file(world, "tools/ci_v3_real_child.py", "X = 1\n")        # an allowed CI-V3 addition that the self-tests exercise
    head = subprocess.check_output(["git", "-C", str(world["repo"]), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(world["repo"]), "rev-parse", "HEAD^{tree}"], text=True).strip()
    inv = json.loads(world["inventory"].read_text())
    inv["source"] = {"head": head, "tree": tree}; inv["nodes"] = [{"nodeid": "tests/test_ci_v3_x.py::t", "module": "tests/test_ci_v3_x.py"}]
    world["inventory"].write_text(json.dumps(inv)); write_nodes(world["archive"], ["tests/test_ci_v3_x.py::t"])
    with pytest.raises(ContractError, match="must run at the final tree"):
        build(world)
    make_run(world["tmp"] / "final", "final", tree=tree, module="tests/test_ci_v3_x.py")
    ev.pack_attempt(world["tmp"] / "final", world["evidence"] / "attempts/final")
    manifest = build(world)
    assert manifest["ci_v3_modules_required_at_final_tree"] == ["tests/test_ci_v3_x.py"]
    commit_evidence(world)
    assert ev.verify(world["repo"], world["evidence"])["verified"]


def test_no_product_test_imports_ci_v3_tools_which_is_the_premise_of_carry_forward():
    import re
    from pathlib import Path
    offenders = [p.name for p in Path(__file__).parent.glob("*.py")
                 if not p.name.startswith(("test_ci_v3_", "ci_v3_")) and re.search(r"(?:from|import)\s+tools\.ci_v3_", p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == []

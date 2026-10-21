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


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"; (repo / "tools").mkdir(parents=True); (repo / "docs/ci_v3/phase3b/evidence").mkdir(parents=True)
    (repo / "tools/ci_v3_x.py").write_text("X = 1\n"); (repo / "app.py").write_text("A = 1\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "source")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    evidence = repo / "docs/ci_v3/phase3b/evidence"
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
    make_run(world["tmp"] / "other", "other", tree="f" * 40); ev.pack_attempt(world["tmp"] / "other", world["evidence"] / "attempts/other")
    with pytest.raises(ContractError, match="exact source and image"):
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

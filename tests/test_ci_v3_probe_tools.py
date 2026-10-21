"""Probe orchestration and bounded-validation subsets stay deterministic, bounded and file-preserving."""
import subprocess

import pytest

from tools.ci_v3_container_validate import NEGATIVE, make_subset
from tools.ci_v3_probe_run import lanes
from tools.ci_v3_schema import ContractError


def entries(*names):
    return [{"module": n, "tag": None} for n in names]


def test_lanes_cover_every_entry_exactly_once_and_are_deterministic():
    items = entries("a", "b", "c", "d", "e")
    weights = {"a": 50, "b": 40, "c": 30, "d": 20, "e": 10}
    one = lanes(items, 3, weights)
    assert one == lanes(list(reversed(items)), 3, weights)
    assert sorted(e["module"] for lane in one for e in lane) == ["a", "b", "c", "d", "e"] and all(one)


def test_lane_balance_puts_the_heaviest_alone():
    result = lanes(entries("big", "x", "y"), 3, {"big": 1000, "x": 10, "y": 10})
    assert [len(lane) for lane in result] == [1, 1, 1]


def repo_with_tests(tmp_path):
    repo = tmp_path / "src"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests/conftest.py").write_text("# base\n")
    for name in ("test_keep.py", "test_other.py"):
        (repo / "tests" / name).write_text("def test_x():\n    pass\n")
    (repo / "tests/helper.py").write_text("H = 1\n")
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    run("add", "-A")
    run("commit", "-qm", "base")
    return repo


def test_subset_keeps_every_file_and_ignores_the_rest_at_collection(tmp_path):
    out = make_subset(repo_with_tests(tmp_path), ["tests/test_keep.py"], tmp_path / "dst")
    assert (out / "tests/test_other.py").exists() and (out / "tests/helper.py").exists()   # nothing deleted
    conftest = (out / "tests/conftest.py").read_text()
    assert "collect_ignore" in conftest and "test_other.py" in conftest and "test_keep.py" not in conftest
    assert subprocess.check_output(["git", "-C", str(out), "status", "--porcelain"], text=True) == ""


def test_negative_injection_is_confined_to_the_derived_subset(tmp_path):
    source = repo_with_tests(tmp_path)
    out = make_subset(source, ["tests/test_keep.py"], tmp_path / "dst", NEGATIVE["failure"])
    name = NEGATIVE["failure"][0]
    assert (out / name).exists() and not (source / name).exists()
    assert name.split("/", 1)[1] not in (out / "tests/conftest.py").read_text()   # the injected test is collected


def test_subset_rejects_unknown_module(tmp_path):
    with pytest.raises(ContractError, match="subset module missing"):
        make_subset(repo_with_tests(tmp_path), ["tests/test_nope.py"], tmp_path / "dst")


def sealed_world():
    from tools.ci_v3_schema import seal
    nodes = [{"nodeid": f"tests/test_m.py::t{i}", "module": "tests/test_m.py"} for i in range(3)]
    inventory = seal({"nodes": nodes})
    return inventory, seal({"inventory_digest": inventory["digest"]}), seal({"inventory_digest": inventory["digest"], "modules_ms": {"tests/test_m.py": 3}})


@pytest.mark.parametrize("kind,count", [("unauthorized-node", 2), ("missing-node", 4)])
def test_inventory_mutations_change_only_the_node_set_and_reseal_consistently(kind, count):
    from tools.ci_v3_container_validate import mutate_inventory
    from tools.ci_v3_schema import digest
    inventory, policy, weights = sealed_world()
    new_inventory, new_policy, new_weights = mutate_inventory(inventory, policy, weights, kind)
    assert len(new_inventory["nodes"]) == count and new_inventory["digest"] != inventory["digest"]
    assert new_inventory["digest"] == digest({k: v for k, v in new_inventory.items() if k != "digest"})
    assert new_policy["inventory_digest"] == new_weights["inventory_digest"] == new_inventory["digest"]
    if kind == "missing-node":
        assert new_inventory["nodes"][-1]["nodeid"].endswith("test_phantom_required_node")


@pytest.mark.parametrize("kind,expected", [("duplicate-junit-node", 3), ("missing-junit-node", 1)])
def test_junit_tamper_duplicates_or_removes_exactly_one_case(tmp_path, kind, expected):
    from tools.ci_v3_container_validate import tamper_worker_junit
    path = tmp_path / "worker-0/child"; path.mkdir(parents=True)
    (path / "native.xml").write_text('<testsuite><testcase classname="a" name="x"/><testcase classname="a" name="y"/></testsuite>')
    tamper_worker_junit(tmp_path, kind)
    text = (path / "native.xml").read_text()
    assert text.count("<testcase") == expected


def test_resource_sampler_parses_docker_memory_units():
    from tools.ci_v3_container_validate import ResourceSampler
    assert ResourceSampler.mib("512MiB") == 512 and ResourceSampler.mib("1.5GiB") == 1536 and round(ResourceSampler.mib("2048KiB"), 3) == 2


def test_passwd_file_gives_the_numeric_host_user_an_entry_without_secrets(tmp_path):
    from tools.ci_v3_container import docker_command, passwd_file
    path = passwd_file(tmp_path / "passwd", 1001, 118)
    assert path.read_text().splitlines() == ["root:x:0:0:root:/root:/usr/sbin/nologin", "ci:x:1001:118:ci:/tmp/home:/usr/sbin/nologin"]
    assert passwd_file(tmp_path / "root", 0, 0).read_text().count("\n") == 1          # no duplicate uid 0
    args = docker_command("example.invalid/image@sha256:" + "a" * 64, "ci-v3-" + "b" * 32, tmp_path / "p", tmp_path / "b", tmp_path / "e", "worker-0", passwd=path)
    assert any(a.endswith("target=/etc/passwd,readonly") for a in args)
    assert not any("/etc/passwd" in a for a in docker_command("example.invalid/image@sha256:" + "a" * 64, "ci-v3-" + "b" * 32, tmp_path / "p", tmp_path / "b", tmp_path / "e", "worker-0"))

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

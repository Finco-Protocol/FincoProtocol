"""Explicit tiny Git-backed pytest demonstrations; never touches a product project."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import subprocess
import sys

from tools.ci_v3_real_contract import git_source
from tools.ci_v3_schema import require, seal, write_json

EXPECTED_NODES = sorted([
    "tests/test_alpha.py::test_numbers[literal::id]",
    "tests/test_alpha.py::test_numbers[second[id]]",
    "tests/test_beta.py::test_owner",
    "tests/test_beta.py::test_expected",
    "tests/test_beta.py::test_runtime_skip",
    "tests/test_gamma.py::test_temp_isolation",
])

CONFTEST = '''import json, os, sqlite3
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def db():
    root = Path(os.environ["CI_V3_WORKER_TMPDIR"])
    owner = os.environ["CI_V3_WORKER_ID"]
    path = root / "session.sqlite"
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("create table if not exists owners (owner text)")
    connection.execute("insert into owners values (?)", (owner,))
    connection.commit()
    yield connection
    connection.close()
    (root / "fixture-proof.json").write_text(json.dumps({"owner":owner, "database":str(path), "closed":True}))
'''
ALPHA = '''import os, pytest
CALLS = []

@pytest.mark.parametrize("value", [1, 2], ids=["literal::id", "second[id]"])
def test_numbers(value, db):
    CALLS.append(value)
    assert CALLS == list(range(1, value+1))
    assert db.execute("select owner from owners").fetchall() == [(os.environ["CI_V3_WORKER_ID"],)]
'''
BETA = '''import os, pytest

def test_owner(db):
    assert db.execute("select owner from owners").fetchall() == [(os.environ["CI_V3_WORKER_ID"],)]

@pytest.mark.xfail(reason="expected demonstration", strict=True)
def test_expected(db):
    assert False

def test_runtime_skip(db):
    pytest.skip("approved runtime condition")
'''
GAMMA = '''import os
from pathlib import Path

def test_temp_isolation(tmp_path, db):
    assert tmp_path.resolve().is_relative_to(Path(os.environ["CI_V3_WORKER_TMPDIR"]).resolve())
    assert db.execute("select owner from owners").fetchall() == [(os.environ["CI_V3_WORKER_ID"],)]
'''


def create_project(root, variant="positive"):
    root = Path(root).resolve()
    require(not root.exists(), "preserve existing synthetic project")
    (root / "tests").mkdir(parents=True)
    conftest, alpha, beta, gamma = CONFTEST, ALPHA, BETA, GAMMA
    if variant == "failure":
        gamma = gamma.replace("    assert tmp_path", "    assert False\n    assert tmp_path")
    elif variant in ("abrupt", "forged_success", "silent_zero", "timeout", "shutdown_hang", "missing_exit", "grandchild_timeout"):
        body = {"abrupt": "os._exit(7)", "forged_success": "print('PYTEST_MAIN_RETURNED rc=0', flush=True); os._exit(1)",
                "silent_zero": "os._exit(0)", "timeout": "__import__('time').sleep(30)",
                "shutdown_hang": "__import__('threading').Thread(target=lambda: __import__('time').sleep(30), daemon=False).start()",
                "missing_exit": "__import__('atexit').register(lambda: os._exit(0))",
                "grandchild_timeout": "__import__('subprocess').Popen([__import__('sys').executable, '-c', \"import os,time; from pathlib import Path; Path(os.environ['CI_V3_WORKER_TMPDIR'], 'grandchild.pid').write_text(str(os.getpid())); time.sleep(30)\"]); __import__('time').sleep(30)"}[variant]
        gamma = "import os\ndef test_temp_isolation():\n    " + body + "\n"
    elif variant == "collection_only":
        conftest += '\ndef pytest_sessionstart(session):\n    if os.environ.get("CI_V3_WORKER_ID") != "discover":\n        session.config.option.collectonly = True\n'
    elif variant == "deselection":
        conftest += '\ndef pytest_collection_modifyitems(items):\n    items.pop()\n'
    elif variant == "wrong_xfail":
        beta = beta.replace("expected demonstration", "unapproved reason")
    elif variant == "wrong_skip":
        beta = beta.replace("approved runtime condition", "unapproved runtime condition")
    elif variant == "xpass":
        beta = beta.replace("    assert False", "    assert True")
    elif variant == "contamination":
        conftest = conftest.replace('path = root / "session.sqlite"', 'path = Path(__file__).parent.parent / "shared.sqlite"')
    elif variant == "teardown_failure":
        conftest = conftest.replace('    connection.close()', '    connection.close()\n    if owner == "worker-2":\n        raise RuntimeError("real teardown failure")')
    elif variant == "duplicate_execution":
        conftest += '\ndef pytest_runtest_protocol(item, nextitem):\n    from _pytest.runner import runtestprotocol\n    runtestprotocol(item, nextitem=nextitem)\n    runtestprotocol(item, nextitem=nextitem)\n    return True\n'
    elif variant not in ("positive", "new_node", "collection_error", "wrong_collection_skip"):
        raise ValueError("unknown synthetic variant")
    files = {"conftest.py": conftest, "tests/test_alpha.py": alpha, "tests/test_beta.py": beta,
        "tests/test_gamma.py": gamma, "tests/test_optional.py": 'import pytest\npytest.skip("optional collector", allow_module_level=True)\n',
        ".gitignore": "__pycache__/\n.pytest_cache/\n", "pytest.ini": "[pytest]\ntestpaths = tests\n",
        "ci_v3_synthetic_project.json": json.dumps({"synthetic_only": True}) + "\n"}
    if variant == "collection_error":
        files["tests/test_broken.py"] = "def broken syntax\n"
    if variant == "new_node":
        files["tests/test_new.py"] = "def test_unreviewed():\n    assert True\n"
    if variant == "wrong_collection_skip":
        files["tests/test_optional.py"] = 'import pytest\npytest.skip("changed collector condition", allow_module_level=True)\n'
    for name, data in files.items():
        (root / name).write_bytes(data.encode("utf-8"))
    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    git("init", "-q"); git("config", "core.autocrlf", "false")
    git("add", ".")
    git("-c", "user.name=CI V3 Synthetic", "-c", "user.email=fixture.invalid", "commit", "-qm", "Synthetic execution fixture")
    source = git_source(root)
    modules = sorted({n.split("::", 1)[0] for n in EXPECTED_NODES})
    inventory = seal({"schema": 1, "kind": "ci-v3-inventory", "authority": "offline-prototype",
        "source": source, "repository": "local/ci-v3-synthetic", "nodes": [
            {"nodeid": n, "module": n.split("::", 1)[0], "fixture_unit": n.split("::", 1)[0],
             "execution_owner": "plan.module_workers", "optional_overlap_ownership": "policy.module_overlaps",
             "domain": "F", "confidence": "unresolved", "mandatory": True,
             "obligations": ["full-regression"], "dependency_evidence": "hand-authored synthetic expected identities"} for n in EXPECTED_NODES],
        "modules": {m: {"isolation_review": "unproven", "dependency_evidence": {}} for m in modules},
        "collection_skips": [{"nodeid": "tests/test_optional.py", "reason": "Skipped: optional collector"}]})
    policy = seal({"schema": 1, "kind": "ci-v3-policy", "authority": "offline-prototype",
        "inventory_digest": inventory["digest"], "new_nodes": "fail-closed", "selective_execution": False,
        "module_overlaps": {}, "allowed_nonpass": {
            "tests/test_beta.py::test_expected": {"status": "xfail", "reason": "expected demonstration"},
            "tests/test_beta.py::test_runtime_skip": {"status": "skipped", "reason": "Skipped: approved runtime condition"}}})
    weights = seal({"schema": 1, "kind": "ci-v3-weights", "source": source,
        "inventory_digest": inventory["digest"], "measurement": "synthetic fixed workload inputs, not a FINCO runtime estimate",
        "modules_ms": {"tests/test_alpha.py": 3000, "tests/test_beta.py": 2000, "tests/test_gamma.py": 1000}})
    return inventory, policy, weights


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--variant", default="positive")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    require(not output.exists(), "preserve existing demonstration")
    output.mkdir(parents=True)
    inventory, policy, weights = create_project(output / "project", args.variant)
    from tools.ci_v3_shadow_local import run_shadow
    result = run_shadow(output / "project", inventory, policy, weights, output / "execution", args.timeout)
    write_json(output / "demo-result.json", result)
    print(json.dumps(result))
    return 0 if result["proof"]["coverage_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())

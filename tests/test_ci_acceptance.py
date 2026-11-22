"""CI partition/aggregate adversarial tests; no financial runtime changes."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest


HEAD = "a" * 40
TREE = "b" * 40
NODES = ["tests/test_one.py::test_a", "tests/test_one.py::test_b", "tests/test_two.py::test_c"]


def proof():
    control = {"schema": 1, "head": HEAD, "tree": TREE, "pytest_exit": 0,
               "collected": NODES, "selected": NODES, "deselected": [],
               "collection_skips": [["tests/test_browser.py", "Playwright not installed"]],
               "collection_errors": [], "shard": None,
               "outcomes": {node: {"status": "passed", "reason": ""} for node in NODES}}
    shards = []
    for slot, selected in enumerate((NODES[:2], NODES[2:])):
        shard = deepcopy(control)
        shard.update(shard=slot, selected=selected, deselected=sorted(set(NODES) - set(selected)),
                     outcomes={node: control["outcomes"][node] for node in selected})
        shards.append(shard)
    processes = [{"head": HEAD, "tree": TREE, "exit_code": 0, "normal_exit": True,
                  "junit_sha256": "digest", "junit_failures": 0, "environment_sha256": "environment",
                  "elapsed_seconds": 10.0} for _ in range(3)]
    return control, shards, processes


def test_plugin_real_collection_outcomes_and_module_partition(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"test_synthetic_{index}.py"
        path.write_text("import pytest\ndef test_pass(): assert True\n"
                        "@pytest.mark.skip(reason='synthetic reason')\ndef test_skip(): pass\n", encoding="utf-8")
        paths.append(str(path))
    weights = tmp_path / "weights.json"
    weights.write_text('{"modules": {}}', encoding="utf-8")
    records = []
    for slot in (None, 0, 1):
        output = tmp_path / f"inventory-{slot}.json"
        command = [sys.executable, "-m", "pytest", "-q", "--confcutdir", str(tmp_path),
                   "-p", "tools.ci_pytest_inventory", f"--ci-inventory={output}",
                   f"--ci-weights={weights}", *paths]
        if slot is not None:
            command.append(f"--ci-shard={slot}")
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        records.append(json.loads(output.read_text(encoding="utf-8")))
    assert len(records[0]["selected"]) == 4
    assert {v["status"] for v in records[0]["outcomes"].values()} == {"passed", "skipped"}
    assert set(records[1]["selected"]).isdisjoint(records[2]["selected"])
    assert set(records[1]["selected"] + records[2]["selected"]) == set(records[0]["selected"])


_F3_5_REVIEWED_PROTECTED_PATHS = frozenset({
    "financial_engine/book_basis.py",
    "financial_engine/financial_statements/assembly.py",
    "financial_engine/financial_statements/contracts.py",
    "financial_engine/financing/generic_product_policy.py",
    "financial_engine/financing/junior_debt.py",
    "financial_engine/financing/project.py",
    "financial_engine/financing/project_uses.py",
    "financial_engine/project_returns/contracts.py",
    "financial_engine/project_returns/model.py",
    "financial_engine/senior_debt/project_adapter.py",
    "financial_engine/shareholder_waterfall/contracts.py",
    "financial_engine/shareholder_waterfall/model.py",
    "finco_core/inputs/_models.py",
    "finco_core/inputs/junior_debt.py",
    "finco_core/inputs/serialization.py",
})


def test_required_gate_triggers_do_not_depend_on_changed_paths():
    root = Path(__file__).resolve().parents[1]
    for name in ("public_safety_and_smoke", "protocol_ui_browser", "pr_compile_and_safety", "governance_history", "dependency_security_audit"):
        text = (root / ".github" / "workflows" / (name + ".yml")).read_text(encoding="utf-8")
        assert "pull_request:" in text
        assert "paths:" not in text
        assert "head.sha" in text



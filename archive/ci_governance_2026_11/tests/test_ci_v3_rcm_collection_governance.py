"""RC-M — the CI V3 collection-skip inventory stays immutable: RC-M adds no collection skip, and unauthorized drift still fails.

``tools.ci_v3_source_reference.reconciliation`` compares the accepted base's collection-skip inventory with the PR's.  The RC-M
browser acceptance runs inside the existing mandatory consolidation role through non-collected modules, so the plan environment (no
Chromium driver) collects exactly the base's skips.  These tests prove the gate itself is not weakened and that no RC-M test module
can re-introduce an import-time skip.
"""
import ast
from pathlib import Path

import pytest

from tools.ci_v3_schema import ContractError
from tools.ci_v3_source_reference import reconciliation

ROOT = Path(__file__).resolve().parent.parent
BASE_SKIPS = [{"nodeid": "tests/test_yield_browser.py", "reason": "could not import 'playwright'"},
              {"nodeid": "tests/test_cost_workspace_browser_v1.py", "reason": "playwright not installed in this workflow"}]
NODES = ["tests/test_a.py::test_one", "tests/test_b.py::test_two"]


def _snapshot(skips=BASE_SKIPS):
    return {"digest": "d", "report": {"selected": list(NODES), "collection": {"skips": list(skips)}}}


def _inventory(skips=BASE_SKIPS, nodes=NODES):
    return {"nodes": [{"nodeid": n} for n in nodes], "collection_skips": list(skips)}


def test_equal_skip_inventories_and_added_nodes_are_accepted():
    result = reconciliation(_snapshot(), _inventory(nodes=[*NODES, "tests/test_model_workspace_consolidation_browser.py::test_new"]))
    assert result["collection_skips_equal"] is True and result["removed"] == [] and len(result["added"]) == 1


def test_an_added_collection_skip_is_refused_without_reconciliation_authority():
    extra = {"nodeid": "tests/test_model_react_rcm_new_project_browser.py", "reason": "could not import 'playwright'"}
    with pytest.raises(ContractError, match="collection skip change"):
        reconciliation(_snapshot(), _inventory(skips=[*BASE_SKIPS, extra]))


def test_a_removed_collection_skip_is_refused_too():
    with pytest.raises(ContractError, match="collection skip change"):
        reconciliation(_snapshot(), _inventory(skips=BASE_SKIPS[:1]))


def test_a_changed_skip_reason_is_refused():
    changed = [{**BASE_SKIPS[0], "reason": "another reason"}, BASE_SKIPS[1]]
    with pytest.raises(ContractError, match="collection skip change"):
        reconciliation(_snapshot(), _inventory(skips=changed))


def test_a_removed_original_node_is_refused():
    with pytest.raises(ContractError, match="original nodes removed"):
        reconciliation(_snapshot(), _inventory(nodes=NODES[:1]))


def _module_level_skips(path: Path) -> list[str]:
    """Collection-time skips only: ``importorskip`` / ``pytestmark`` / skip decorators outside any function body."""
    hits = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        nodes = [node] if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else [*node.decorator_list]
        for top in nodes:
            for sub in ast.walk(top):
                text = ast.unparse(sub) if isinstance(sub, (ast.Call, ast.Attribute, ast.Name)) else ""
                if any(word in text for word in ("importorskip", "mark.skip", "pytest.skip", "pytestmark")):
                    hits.append(f"{path.name}:{getattr(sub, 'lineno', 0)} {text[:60]}")
                    break
    return hits


def test_no_rcm_test_module_can_introduce_a_collection_skip():
    modules = sorted({*ROOT.glob("tests/test_*rcm*.py"), *ROOT.glob("tests/model_react_rcm_*.py"), ROOT / "tests/rcm_adapter_csrf_successor.py",
                      ROOT / "tests/rcm_multiproc_app.py"})
    assert len(modules) >= 12
    assert [hit for module in modules for hit in _module_level_skips(module) if module.name != Path(__file__).name] == []

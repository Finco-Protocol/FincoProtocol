"""Disclosure guard for the explicit precondition added to tests/test_golden_flow_correction_b.py.

The only permitted differences from the version on main (before CI V3 Phase 3B) are: ``import pytest``, the isolated
``reference_runs_seeded`` fixture, and that fixture being requested by the one test. Every assertion, golden
expectation and Run counter is pinned by the AST hash of the original module with those three pieces removed.
"""
import ast
import hashlib
import json
from pathlib import Path

ORIGINAL_AST_SHA256 = "ed5810a4daa25f8714b8e19bae725ba723131e43efd1a442f3639095d77fdc8b"   # module as on main d6270d58
TEST = "test_active_scenario_override_stays_stale_on_reopen_and_first_run_succeeds"
FIXTURE = "reference_runs_seeded"
SOURCE = Path(__file__).with_name("test_golden_flow_correction_b.py")


def canon(node):
    """Python-version independent serialization: node type plus non-empty fields (no positions)."""
    if isinstance(node, ast.AST):
        fields = {name: canon(value) for name, value in ast.iter_fields(node) if value not in (None, [], ())}
        return {"_": type(node).__name__, **fields}
    if isinstance(node, list):
        return [canon(item) for item in node]
    return repr(node)


def digest(tree):
    return hashlib.sha256(json.dumps(canon(tree), sort_keys=True).encode()).hexdigest()


def normalized():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    kept, removed = [], {"import_pytest": 0, "fixture": 0, "param": 0}
    for node in tree.body:
        if isinstance(node, ast.Import) and [a.name for a in node.names] == ["pytest"]:
            removed["import_pytest"] += 1
            continue
        if isinstance(node, ast.FunctionDef) and node.name == FIXTURE:
            removed["fixture"] += 1
            continue
        if isinstance(node, ast.FunctionDef) and node.name == TEST:
            assert [a.arg for a in node.args.args] == [FIXTURE], "the test must request exactly the isolated precondition"
            node.args.args = []
            removed["param"] += 1
        kept.append(node)
    tree.body = kept
    return tree, removed


def test_only_the_disclosed_precondition_differs_from_the_original_module():
    tree, removed = normalized()
    assert removed == {"import_pytest": 1, "fixture": 1, "param": 1}
    assert digest(tree) == ORIGINAL_AST_SHA256


def test_run_counter_assertion_and_seeding_order_are_intact():
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count("assert calls == 1") == 1                      # exactly one user Run is counted
    fixture = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == FIXTURE)
    body = ast.unparse(fixture)
    assert "monkeypatch.setattr(db, 'DB_PATH'" in body and "tmp_path" in body        # private database, never the shared one
    assert body.index("DB_PATH") < body.index("ensure_reference_canonical_last_runs()")   # redirected before seeding

"""Disclosure guard for the explicit precondition added to tests/test_golden_flow_correction_b.py.

The only permitted differences from the version on main (before CI V3 Phase 3B) are: ``import pytest``, the isolated
``reference_runs_seeded`` fixture, and that fixture being requested by the one test. Every assertion, golden
expectation and Run counter is pinned by the AST hash of the original module with those three pieces removed.

Released Run CSRF transports and SEC-02's three explicit scenario transports are
also normalized at their exact assignment/route sites; the original digest stays
unchanged. Any argument, value, assertion or extra helper still changes/fails it.
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


def normalized(text=None):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8") if text is None else text)
    kept, removed = [], {"import_pytest": 0, "fixture": 0, "param": 0,
                         "csrf_helper_import": 0, "csrf_run_calls": 0,
                         "mutation_helper_import": 0, "mutation_calls": 0}
    for node in tree.body:
        if isinstance(node, ast.Import) and [a.name for a in node.names] == ["pytest"]:
            removed["import_pytest"] += 1
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "tests.run_clone_csrf":
            assert len(node.names) == 1 and node.names[0].name == "post_valid_csrf" and not node.names[0].asname, (
                "only the reviewed CSRF transport helper may be imported")
            removed["csrf_helper_import"] += 1
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "tests.model_mutation_csrf":
            assert len(node.names) == 1 and node.names[0].name == "post_valid_mutation" and not node.names[0].asname
            removed["mutation_helper_import"] += 1
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

    # Restore ONLY the two approved positive transport call ASTs to their
    # original client.post form before applying the unchanged original digest.
    # No assertion, financial value, CAS condition or Run counter is masked.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in ("first_run", "rerun"):
            continue
        call = node.value
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "post_valid_csrf", (
            "approved Run assignment must use only the explicit CSRF helper")
        assert len(call.args) >= 2 and isinstance(call.args[0], ast.Name) and call.args[0].id == "client", (
            "the CSRF helper must receive the existing client")
        assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "/v2/workbook/run", (
            "the existing canonical Run route must remain unchanged")
        node.value = ast.Call(
            func=ast.Attribute(value=ast.Name(id="client", ctx=ast.Load()), attr="post", ctx=ast.Load()),
            args=call.args[1:], keywords=call.keywords)
        removed["csrf_run_calls"] += 1
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "post_valid_csrf"
                   for n in ast.walk(tree)), "unexpected extra CSRF helper call"
    # SEC-02 changed exactly these three positive transports; retain the original
    # route, data, assertions, values and Run counters in the historical digest.
    expected = {"created": "/v2/workbook/scenarios/create",
                "rejected": "/v2/workbook/scenarios/update-overrides",
                "mutated": "/v2/workbook/scenarios/update-overrides"}
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, call = node.targets[0], node.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "post_valid_mutation"):
            continue
        assert isinstance(target, ast.Name) and target.id in expected and target.id not in seen
        assert len(call.args) == 2 and isinstance(call.args[0], ast.Name) and call.args[0].id == "client"
        assert isinstance(call.args[1], ast.Constant) and call.args[1].value == expected[target.id]
        seen.add(target.id)
        node.value = ast.Call(func=ast.Attribute(value=call.args[0], attr="post", ctx=ast.Load()),
                              args=call.args[1:], keywords=call.keywords)
        removed["mutation_calls"] += 1
    assert seen == set(expected)
    assert not any(isinstance(n, ast.Name) and n.id == "post_valid_mutation" for n in ast.walk(tree))
    return tree, removed


def test_only_the_disclosed_precondition_differs_from_the_original_module():
    tree, removed = normalized()
    assert removed == {"import_pytest": 1, "fixture": 1, "param": 1,
                       "csrf_helper_import": 1, "csrf_run_calls": 2,
                       "mutation_helper_import": 1, "mutation_calls": 3}
    assert digest(tree) == ORIGINAL_AST_SHA256


def test_financial_assertion_drift_is_not_masked_by_transport_normalization():
    text = SOURCE.read_text(encoding="utf-8")
    assert "assert calls == 1" in text
    tree, _ = normalized(text.replace("assert calls == 1", "assert calls == 2", 1))
    assert digest(tree) != ORIGINAL_AST_SHA256


def test_mutation_route_drift_is_not_admitted_as_transport_only():
    text = SOURCE.read_text(encoding="utf-8")
    changed = text.replace('post_valid_mutation(client, "/v2/workbook/scenarios/create"',
                           'post_valid_mutation(client, "/v2/workbook/scenarios/select"', 1)
    assert changed != text
    import pytest
    with pytest.raises(AssertionError):
        normalized(changed)


def test_run_counter_assertion_and_seeding_order_are_intact():
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count("assert calls == 1") == 1                      # exactly one user Run is counted
    fixture = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == FIXTURE)
    body = ast.unparse(fixture)
    assert "monkeypatch.setattr(db, 'DB_PATH'" in body and "tmp_path" in body        # private database, never the shared one
    assert body.index("DB_PATH") < body.index("ensure_reference_canonical_last_runs()")   # redirected before seeding

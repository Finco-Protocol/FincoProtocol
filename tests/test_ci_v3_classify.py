"""Standalone-evidence classification never approves, drops or relaxes a module."""
import pytest

from tools.ci_v3_classify import classify, load_probe
from tools.ci_v3_schema import ContractError


def prepared():
    nodes = [{"module": "tests/test_a.py"}] * 2 + [{"module": "tests/test_b.py"}]
    mods = {m: {"sha256": "0" * 64, "findings": []} for m in ("tests/test_a.py", "tests/test_b.py", "tests/helper.py")}
    return {"inventory": {"nodes": nodes}, "isolation": {"schema": 3, "kind": "ci-v3-isolation-policy", "modules": mods}}


def result(module, **kw):
    return {"module": module, "exit_code": 0, "timed_out": False, "failures": 0, "errors": 0, "skipped": 0, "tests": 2, "seconds": 1.0, **kw}


def test_pass_is_proposal_only_and_helpers_are_explicit():
    proposal, summary = classify(prepared(), {"tests/test_a.py": result("tests/test_a.py"), "tests/test_b.py": result("tests/test_b.py", tests=1)})
    mods = proposal["modules"]
    assert mods["tests/test_a.py"]["mode"] == "runner-private" and not any(m["reviewed"] for m in mods.values())
    assert mods["tests/helper.py"]["category"] == "not-collected-helper" and summary["unresolved_blocking_admission"] == 0


@pytest.mark.parametrize("change,category", [({"exit_code": 1, "failures": 1}, "standalone-failure"), ({"timed_out": True, "exit_code": None}, "standalone-failure"),
    ({"skipped": 1}, "coverage-mismatch"), ({"tests": 1}, "coverage-mismatch")])
def test_non_clean_standalone_blocks(change, category):
    proposal, summary = classify(prepared(), {"tests/test_a.py": result("tests/test_a.py", **change), "tests/test_b.py": result("tests/test_b.py", tests=1)})
    assert proposal["modules"]["tests/test_a.py"]["category"] == category and summary["unresolved_blocking_admission"] == 1


def test_missing_evidence_blocks_and_duplicates_reject(tmp_path):
    proposal, summary = classify(prepared(), {})
    assert summary["unresolved_blocking_admission"] == 2 and proposal["modules"]["tests/test_b.py"]["mode"] == "blocked"
    (tmp_path / "results.jsonl").write_text('{"module": "m"}\n{"module": "m"}\n')
    with pytest.raises(ContractError):
        load_probe(tmp_path)

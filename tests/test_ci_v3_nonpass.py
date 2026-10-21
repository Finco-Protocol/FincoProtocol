"""The proposed nonpass policy contains only control-identical records; losses, changes and unknowns are never blessed."""
import pytest

from tools.ci_v3_nonpass import compare, node_id, read_control
from tools.ci_v3_schema import ContractError

SK = lambda reason: {"status": "skipped", "reason": reason}
A, B, C, D = (f"tests/test_m.py::test_{x}" for x in "abcd")


def run(observed, control_runtime, executed=None, collected=None):
    return compare(observed, control_runtime, executed or {A, B, C, D}, collected or {A, B, C, D})


def test_only_exact_control_identical_records_are_proposed():
    proposed, rejected, owner, missing = run({A: SK("x")}, {A: SK("x")})
    assert set(proposed) == {A} and not rejected and not owner and not missing


@pytest.mark.parametrize("observed,control", [({A: SK("other")}, {A: SK("x")}),
    ({A: {"status": "xfail", "reason": "x"}}, {A: SK("x")})])
def test_changed_status_or_reason_is_rejected(observed, control):
    proposed, rejected, _, _ = run(observed, control)
    assert not proposed and rejected[A]["why"] == "changed"


def test_node_the_control_executes_but_shadow_skips_is_a_coverage_loss():
    proposed, rejected, _, _ = run({B: SK("node is not available")}, {A: SK("x")})
    assert not proposed and rejected[B]["why"].startswith("environment-coverage-loss") and rejected[B]["environment_dependent"]


def test_unknown_to_control_needs_owner_decision_and_missing_is_reported():
    proposed, rejected, owner, missing = compare({"tests/new.py::test_n": SK("new")}, {A: SK("x")}, {A}, {A, "tests/new.py::test_n"})
    assert not proposed and "tests/new.py::test_n" in owner and set(missing) == {A}


def test_malformed_record_is_rejected():
    with pytest.raises(ContractError):
        run({A: {"status": "skipped"}}, {})


def control_xml(tmp_path, body):
    path = tmp_path / "r.xml"; path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>"); return path


def test_control_reader_exact_ids_collection_skips_and_duplicates(tmp_path):
    ok = control_xml(tmp_path, '<testcase classname="tests.test_m.TestK" name="test_a[p.q]"><skipped message="why"/></testcase>'
                               '<testcase classname="" name="tests.test_x"><skipped message="no playwright"/></testcase>'
                               '<testcase classname="tests.test_m" name="test_b"/>')
    runtime, collection, executed, _ = read_control(ok, {"tests/test_m.py"})
    assert runtime == {"tests/test_m.py::TestK::test_a[p.q]": SK("why")} and collection[0]["nodeid"] == "tests/test_x.py"
    assert executed == {"tests/test_m.py::TestK::test_a[p.q]", "tests/test_m.py::test_b"}
    dup = control_xml(tmp_path, '<testcase classname="tests.test_m" name="t"/><testcase classname="tests.test_m" name="t"/>')
    with pytest.raises(ContractError, match="duplicate"):
        read_control(dup, {"tests/test_m.py"})
    with pytest.raises(ContractError, match="DTD"):
        read_control(control_xml(tmp_path, '<!DOCTYPE x>'), {"tests/test_m.py"})


def test_node_id_prefers_longest_module_prefix():
    assert node_id("tests.test_m.TestK", "t", {"tests/test_m.py"}) == "tests/test_m.py::TestK::t"
    assert node_id("other.x", "t", {"tests/test_m.py"}) is None

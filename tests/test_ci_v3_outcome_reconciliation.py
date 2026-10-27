"""D-029 CI V3: the single Financial-Owner-authorized historical outcome reconciliation.

Synthetic baseline/current evidence proves the exception is exact (one node, SKIPPED -> PASSED, exact reviewed
sources, successor tests passed in the same run) and that everything else keeps hard equality / fails closed."""
from __future__ import annotations

import ast
import copy
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from tools import ci_v3_production as prod
from tools.ci_v3_schema import read_json

ROOT = Path(__file__).resolve().parents[1]
NODE = prod.D029_NODE


def ph(call="passed", reason="", wasxfail=None, setup="passed", teardown="passed", setup_reason=""):
    return [{"when": "setup", "outcome": setup, "reason": setup_reason, "wasxfail": None},
            {"when": "call", "outcome": call, "reason": reason, "wasxfail": wasxfail},
            {"when": "teardown", "outcome": teardown, "reason": "", "wasxfail": None}]


OLD = ph("skipped", "Skipped: " + prod.D029_SKIP_REASON)
OLD_NATIVE = ("skipped", "tests/test_trust_readiness_registry.py:913: " + prod.D029_SKIP_REASON)
NEW = ph()
NEW_NATIVE = ("passed", "")


def run_evidence(**changes):
    phases = {n: ph() for n in prod.D029_EVIDENCE_NODES}
    native = {n: ("passed", "") for n in prod.D029_EVIDENCE_NODES}
    phases[NODE], native[NODE] = NEW, NEW_NATIVE
    return changes.get("phases", phases), changes.get("native", native)


def real_facts():
    return prod.d029_source_facts()


def problems(facts=None, node=NODE, old=OLD, old_native=OLD_NATIVE, new=NEW, new_native=NEW_NATIVE, run=None):
    run_phases, run_native = run or run_evidence()
    return prod.d029_transition_problems(node, old, old_native, new, new_native, facts or real_facts(), run_phases, run_native)


def test_the_authorized_transition_holds_on_the_real_reviewed_sources():
    assert problems() == []
    receipts = []
    run_phases, run_native = run_evidence()
    assert prod.d029_authorized(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, run_phases, run_native, receipts)
    assert receipts == [{"node": NODE, "from": "SKIPPED", "to": "PASSED"}]


def test_reconciliation_record_is_exact_content_and_binds_the_reviewed_constants():
    record = read_json(ROOT / prod.D029_RECORD)
    assert record == prod.d029_expected_record()
    assert record["node"] == NODE and record["transition"] == {"from": "SKIPPED", "reason": prod.D029_SKIP_REASON, "to": "PASSED"}
    assert len(record["required_passing_nodes"]) == len(set(record["required_passing_nodes"])) == 15
    # the pinned Trust blobs are the committed ones
    for path, blob in prod.D029_BLOBS.items():
        assert subprocess.check_output(["git", "rev-parse", "HEAD:" + path], cwd=ROOT, text=True).strip() == blob


@pytest.mark.parametrize("name, kwargs", (
    ("SKIPPED -> FAILED", dict(new=ph("failed", "boom"), new_native=("failed", "boom"))),
    ("SKIPPED -> XFAIL", dict(new=ph("skipped", "x", wasxfail="expected"), new_native=("xfail", "x"))),
    ("SKIPPED -> still skipped", dict(new=ph("skipped", "again"), new_native=("skipped", "again"))),
    ("SKIPPED -> missing execution", dict(new=[ph()[0], ph()[2]])),
    ("SKIPPED -> setup error", dict(new=ph("passed", setup="failed"))),
    ("SKIPPED -> teardown error", dict(new=ph("passed", teardown="failed"))),
    ("baseline skip reason changed", dict(old=ph("skipped", "Skipped: some other reason"))),
    ("baseline native reason changed", dict(old_native=("skipped", "some other reason"))),
    ("baseline was not skipped", dict(old=ph("passed"), old_native=("passed", ""))),
    ("baseline xfail", dict(old=ph("skipped", "Skipped: " + prod.D029_SKIP_REASON, wasxfail="x"))),
    ("setup phase changed", dict(new=ph(setup_reason="different setup"))),
    ("native proof missing", dict(new_native=())),
    ("native proof failed", dict(new_native=("failed", "x"))),
    ("native proof skipped", dict(new_native=("skipped", "x"))),
    ("native evidence malformed", dict(new_native=None)),
    ("corrupted phase record", dict(new=[{"when": "call"}])),
))
def test_transition_rejects_every_other_outcome_and_malformed_evidence(name, kwargs):
    assert problems(**kwargs), name


def test_only_the_one_node_is_ever_reconciled():
    others = ("tests/test_trust_readiness_registry.py::test_keys_are_unique_and_prefixed",
              "tests/test_trust_readiness_controls.py::" + NODE.split("::")[1],
              NODE + "[param]", NODE.replace("registry", "claims"), "tests/test_other.py::test_x")
    for node in others:
        assert problems(node=node) == ["not the authorized node"]
        assert not prod.d029_authorized(node, OLD, OLD_NATIVE, NEW, NEW_NATIVE, *run_evidence(), [])


@pytest.mark.parametrize("mutate", (
    lambda f: {**f, "blobs": {**f["blobs"], "app/trust_readiness/registry.py": "0" * 40}},                  # unreviewed registry blob
    lambda f: {**f, "blobs": {**f["blobs"], "docs/readiness/02_data_handling.md": "0" * 40}},              # unreviewed generated document
    lambda f: {**f, "blobs": {**f["blobs"], "tests/test_trust_readiness_controls.py": "0" * 40}},          # RC-M controls test edited beyond its reviewed blob
    lambda f: {**f, "blobs": {k: v for k, v in f["blobs"].items() if k != "tests/test_trust_readiness_controls.py"}},   # reviewed blob missing
    lambda f: {**f, "changed": f["changed"] - {"tests/test_trust_readiness_controls.py"}},                 # RC-M path dropped from the reviewed set
    lambda f: {**f, "main_blobs": {"app/trust_readiness/registry.py": "0" * 40}},                           # wrong pinned baseline
    lambda f: {**f, "changed": f["changed"] | {"app/trust_readiness/projection.py"}},                       # unrelated Trust change
    lambda f: {**f, "changed": f["changed"] | {"docs/readiness/07_authentication_and_tenant_audit.md"}},    # unrelated security/retention doc
    lambda f: {**f, "changed": f["changed"] - {"docs/readiness/06_retention_and_deletion.md"}},             # incomplete reviewed set
    lambda f: {**f, "record": {**f["record"], "node": "tests/other.py::t"}},                                # wrong receipt
    lambda f: {**f, "record": {**f["record"], "authorization": "someone else"}},
    lambda f: {**f, "record": {}},
))
def test_unreviewed_sources_scope_or_receipt_fail_closed(mutate):
    assert problems(facts=mutate(copy.deepcopy(real_facts())))


def test_successor_tests_must_have_passed_in_the_same_run():
    for missing in prod.D029_EVIDENCE_NODES:
        phases, native = run_evidence()
        del phases[missing]
        assert problems(run=(phases, native)), missing
        phases, native = run_evidence()
        del native[missing]
        assert problems(run=(phases, native)), missing
        phases, native = run_evidence()
        phases[missing] = ph("skipped", "skipped")
        native[missing] = ("skipped", "")
        assert problems(run=(phases, native)), missing
        phases, native = run_evidence()
        native[missing] = ("failed", "x")
        assert problems(run=(phases, native)), missing


def test_git_failure_wrong_ancestry_or_missing_record_is_not_an_authorization(monkeypatch):
    run_phases, run_native = run_evidence()

    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(prod, "git", unavailable)
    assert not prod.d029_authorized(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, run_phases, run_native, [])
    monkeypatch.undo()
    monkeypatch.setattr(prod, "D029_MAIN", "0" * 40)                      # not an ancestor / not the reviewed main
    assert not prod.d029_authorized(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, run_phases, run_native, [])
    monkeypatch.undo()
    monkeypatch.setattr(prod, "D029_RECORD", "docs/model_v2/d029/evidence/missing.json")
    assert not prod.d029_authorized(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, run_phases, run_native, [])


def test_authority_is_not_inferred_from_branch_pr_or_environment(monkeypatch):
    for key, value in (("GITHUB_HEAD_REF", "codex/d029-run-idempotency-v1"), ("GITHUB_REF", "refs/pull/384/merge"),
                       ("D029_AUTHORIZED", "1"), ("FINCO_ALLOW_OUTCOME_RECONCILIATION", "true")):
        monkeypatch.setenv(key, value)
    facts = copy.deepcopy(real_facts())
    facts["blobs"]["app/trust_readiness/registry.py"] = "0" * 40
    assert problems(facts=facts)
    assert "environ" not in inspect.getsource(prod.d029_transition_problems) + inspect.getsource(prod.d029_authorized)


def test_verify_data_keeps_hard_equality_and_reconciles_only_through_the_one_function():
    source = inspect.getsource(prod.verify_data)
    tree = ast.parse("def wrapper():\n" + "\n".join(" " + l for l in source.splitlines()))
    requires = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "require"
                and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "phase/native outcome regression" in a.value
                        for a in ast.walk(n))]
    assert len(requires) == 1 or len(requires) == 2
    texts = [ast.unparse(r) for r in requires]
    assert any("v == bp[n] and native[n] == bn[n]" in t and "d029_authorized(" in t for t in texts)
    assert any("v == rp[n] and list(native[n]) == rn[n]" in t and "d029_authorized(" in t for t in texts)
    assert source.count("d029_authorized(") == 2
    # no other verifier site (or file) knows the exception
    for path in ROOT.joinpath("tools").glob("*.py"):
        if path.name != "ci_v3_production.py":
            assert "d029_authorized" not in path.read_text(encoding="utf-8")
    assert sum(1 for line in source.splitlines() if "nonhistorical nonpass requires explicit reviewed authority" in line) == 1
    assert prod.D029_NODE not in inspect.getsource(prod.validate_reference_policy)


def test_exception_does_not_extend_to_other_test_families():
    # the allow-list is one literal node; there is no pattern, prefix, family or regex
    assert isinstance(prod.D029_NODE, str) and "*" not in prod.D029_NODE and prod.D029_NODE.count("::") == 1
    assert [n for n in dir(prod) if n.startswith("D029_") and isinstance(getattr(prod, n), (list, set, frozenset))
            and n not in ("D029_TRUST_CHANGED",)] == []

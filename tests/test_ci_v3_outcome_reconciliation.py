"""D-029 CI V3: the single Financial-Owner-authorized historical outcome reconciliation.

Synthetic baseline/current evidence proves the exception is exact (one node, SKIPPED -> PASSED, exact reviewed
sources, successor tests passed in the same run) and that everything else keeps hard equality / fails closed."""
from __future__ import annotations

import ast
import copy
import functools
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from tests import fin_v2_cohorts as COHORTS
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
    # the 15 original D-029 evidence nodes, plus the WS-2 same-run evidence node(s) the current (WS-2) Trust state also requires
    from tests import wf03_lifecycle_scope as WF03
    nodes = prod.D029_EVIDENCE_NODES + prod.WS2_EXTRA_NODES + WF03.CI_EVIDENCE_NODES
    phases = {n: ph() for n in nodes}
    native = {n: ("passed", "") for n in nodes}
    phases[NODE], native[NODE] = NEW, NEW_NATIVE
    return changes.get("phases", phases), changes.get("native", native)


@pytest.fixture(autouse=True)
def one_governance_call_per_test():
    """Each test is ONE outer governance call: every exact-source cohort verdict is computed once per test (not once per nested call) and dropped when the
    test ends. Nothing is cached across tests, refs, monkeypatches or mutations; the assertions and their inputs are unchanged."""
    with COHORTS.call_scope():
        yield


@functools.lru_cache(maxsize=1)
def _head_facts():
    # the facts of the checked-out HEAD are immutable for the whole session; every consumer receives its OWN deep copy (a test may mutate it)
    return prod.d029_source_facts()


def real_facts():
    return copy.deepcopy(_head_facts())


def test_the_session_cached_head_facts_equal_freshly_read_facts():
    """Negative control for the one cached read: a fresh read of the real sources is identical, and a caller's mutation never reaches the cache."""
    fresh = prod.d029_source_facts()
    assert real_facts() == fresh and real_facts() is not real_facts()
    mutated = real_facts()
    mutated["blobs"]["app/trust_readiness/registry.py"] = "0" * 40
    mutated["changed"] = frozenset()
    assert real_facts() == fresh and real_facts()["blobs"] != mutated["blobs"]


def problems(facts=None, node=NODE, old=OLD, old_native=OLD_NATIVE, new=NEW, new_native=NEW_NATIVE, run=None):
    run_phases, run_native = run or run_evidence()
    return prod.d029_transition_problems(node, old, old_native, new, new_native, facts or real_facts(), run_phases, run_native)


def test_the_authorized_transition_holds_on_the_real_reviewed_sources():
    assert problems() == []
    receipts = []
    run_phases, run_native = run_evidence()
    assert prod.d029_authorized(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, run_phases, run_native, receipts)
    assert receipts == [{"node": NODE, "from": "SKIPPED", "to": "PASSED"}]


def test_wf03_ci_state_rejects_mixed_blobs_and_missing_same_run_evidence():
    from tests import wf03_lifecycle_scope as F
    facts=real_facts()
    assert facts.get('wf03_state') is not None
    phases,native=run_evidence()
    assert F.accepts_ci_trust_state(facts,phases,native)
    for path in F.CI_TRUST_PATHS:
        altered=copy.deepcopy(facts)
        altered['wf03_state']['current_blobs'][path]='0'*40
        assert not F.accepts_ci_trust_state(altered,phases,native)
    altered=copy.deepcopy(facts);altered['wf03_state']['base']='0'*40
    assert not F.accepts_ci_trust_state(altered,phases,native)
    altered=copy.deepcopy(facts);altered['blobs']['app/trust_readiness/registry.py']=prod.WS2_TRUST_BLOBS['app/trust_readiness/registry.py']
    assert not F.accepts_ci_trust_state(altered,phases,native)
    for node in F.CI_EVIDENCE_NODES:
        incomplete=dict(phases);incomplete.pop(node)
        assert not F.accepts_ci_trust_state(facts,incomplete,native)


def test_reconciliation_record_is_exact_content_and_binds_the_reviewed_constants():
    record = read_json(ROOT / prod.D029_RECORD)
    assert record == prod.d029_expected_record()
    assert record["node"] == NODE and record["transition"] == {"from": "SKIPPED", "reason": prod.D029_SKIP_REASON, "to": "PASSED"}
    assert len(record["required_passing_nodes"]) == len(set(record["required_passing_nodes"])) == 15
    # the historical D-029 Trust blobs are immutable history: each one was committed in this branch's ancestry (the current HEAD holds the
    # later WS-2 state of the same three sources, pinned separately below)
    for path, blob in prod.D029_BLOBS.items():
        assert subprocess.check_output(["git", "cat-file", "-t", blob], cwd=ROOT, text=True).strip() == "blob"
        found = subprocess.check_output(["git", "log", "-1", "--format=%H", "--find-object=" + blob, "HEAD", "--", path], cwd=ROOT, text=True).strip()
        assert found, (path, blob)
        subprocess.run(["git", "merge-base", "--is-ancestor", found, "HEAD"], cwd=ROOT, check=True)


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


# ───────────── WS-2 Gate C (Option 1): the closed successor state of the Trust sources (PR #397, Correction M) ─────────────
WS2_PATHS = {**prod.WS2_TRUST_BLOBS, **prod.WS2_TRUST_EXTRA_BLOBS, **prod.D029_TRUST_CHANGED_BLOBS}


def git_blob(path):
    return subprocess.check_output(["git", "rev-parse", "HEAD:" + path], cwd=ROOT, text=True).strip()


def ws2_run_evidence():
    phases = {n: ph() for n in prod.D029_EVIDENCE_NODES + prod.WS2_EXTRA_NODES}
    native = {n: ("passed", "") for n in phases}
    phases[NODE], native[NODE] = NEW, NEW_NATIVE
    return phases, native


def test_the_historical_d029_receipt_and_constants_are_unchanged():
    assert prod.D029_MAIN == "36edeeb5d9a14749fdfafcd3b60a0d384cac73ba"
    assert prod.D029_MAIN_BLOBS == {"app/trust_readiness/registry.py": "32a6bcb86516ff4d1ee8b1dc90191fdb57c5dc2d"}
    assert prod.D029_BLOBS == {"app/trust_readiness/registry.py": "99ff83825e6bef013be9411235d2d77345f78b02",
                               "docs/readiness/02_data_handling.md": "330db9c4ae6cd6c8349aad4a1d0c632010e6c1e4",
                               "docs/readiness/06_retention_and_deletion.md": "a155b44b47ce3cbe22239e6a65635d666e0f3dac"}
    assert prod.D029_TRUST_CHANGED_BLOBS == {"tests/test_trust_readiness_controls.py": "cd5b3114d9a11ca4507667a099bb853573d056d3"}
    assert len(prod.D029_EVIDENCE_NODES) == 15 and prod.D029_SKIP_REASON == "trust pack not part of this diff"
    assert git_blob(prod.D029_RECORD) == prod.WS2_RECORD_BLOB          # the historical receipt itself is byte-identical


def ws2_parent_facts():
    # Preserve the historical STATE B tests against actual immutable merged
    # WS2 sources. Current WF03 STATE C is separately tested above, including
    # its required same-run nodes; these negatives must not pass merely because
    # STATE C evidence is absent.
    from tests import wf03_lifecycle_scope as F
    facts = copy.deepcopy(real_facts())
    for path, blob in WS2_PATHS.items():
        actual = subprocess.check_output(["git", "rev-parse", F.BASE + ":" + path], cwd=ROOT, text=True).strip()
        assert actual == blob, path
    facts["blobs"] = {**prod.WS2_TRUST_BLOBS, **prod.D029_TRUST_CHANGED_BLOBS}
    facts["ws2_extra_blobs"] = dict(prod.WS2_TRUST_EXTRA_BLOBS)
    facts["ws2_manifest_pins"] = {**prod.WS2_TRUST_BLOBS, **prod.WS2_TRUST_EXTRA_BLOBS}
    facts["wf03_state"] = None
    return facts


def test_the_real_head_is_exactly_the_ws2_state_and_the_receipt_binds_it():
    from tests import wf03_lifecycle_scope as F
    current = real_facts()
    assert current["wf03_state"] == F.ci_source_facts() and current["wf03_state"] is not None
    assert F.accepts_ci_trust_state(current, *run_evidence())
    facts = ws2_parent_facts()
    assert facts["blobs"] == {**prod.WS2_TRUST_BLOBS, **prod.D029_TRUST_CHANGED_BLOBS}
    assert facts["ws2_receipt"] == prod.ws2_expected_receipt() == read_json(ROOT / prod.WS2_RECEIPT)
    assert facts["ws2_manifest_pins"] == {**prod.WS2_TRUST_BLOBS, **prod.WS2_TRUST_EXTRA_BLOBS}
    assert facts["changed"] == prod.D029_TRUST_CHANGED
    assert problems(facts=facts, run=ws2_run_evidence()) == []
    receipts = []
    run_phases, run_native = ws2_run_evidence()
    assert prod.d029_transition_problems(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, facts, run_phases, run_native) == []
    assert prod.d029_authorized(NODE, OLD, OLD_NATIVE, NEW, NEW_NATIVE, *run_evidence(), receipts)
    assert receipts == [{"node": NODE, "from": "SKIPPED", "to": "PASSED"}]


def test_the_ws2_receipt_is_a_state_attestation_not_a_second_transition():
    receipt = prod.ws2_expected_receipt()
    assert receipt["schema"] == "WS2_CI_V3_TRUST_SUCCESSOR_V1" and "node" not in receipt and "transition" not in receipt
    assert receipt["predecessor_record"] == prod.D029_RECORD and receipt["d029_main"] == prod.D029_MAIN
    assert "signature" not in json.dumps(receipt).lower()                 # no claimed approval artefact that does not exist


@pytest.mark.parametrize("path", sorted(WS2_PATHS))
def test_ws2_one_byte_drift_of_any_trust_source_fails_closed(path):
    facts = copy.deepcopy(ws2_parent_facts())
    if path in facts["blobs"]:
        facts["blobs"][path] = "0" * 40
    else:
        facts["ws2_extra_blobs"][path] = "0" * 40
    assert problems(facts=facts, run=ws2_run_evidence())


@pytest.mark.parametrize("name, mutate", (
    ("hybrid: D-029 registry with WS-2 documents", lambda f: f["blobs"].update({"app/trust_readiness/registry.py": prod.D029_BLOBS["app/trust_readiness/registry.py"]})),
    ("hybrid: WS-2 registry with a D-029 document", lambda f: f["blobs"].update({"docs/readiness/02_data_handling.md": prod.D029_BLOBS["docs/readiness/02_data_handling.md"]})),
    ("hybrid: WS-2 registry with the other D-029 document", lambda f: f["blobs"].update({"docs/readiness/06_retention_and_deletion.md": prod.D029_BLOBS["docs/readiness/06_retention_and_deletion.md"]})),
    ("incomplete tuple", lambda f: f["blobs"].pop("docs/readiness/06_retention_and_deletion.md")),
    ("unknown third blob", lambda f: f["blobs"].update({"app/trust_readiness/registry.py": "1" * 40})),
    ("extra path in the blob map", lambda f: f["blobs"].update({"app/trust_readiness/projection.py": "2" * 40})),
    ("Trust registry test blob changed", lambda f: f["ws2_extra_blobs"].update({"tests/test_trust_readiness_registry.py": "3" * 40})),
    ("Trust registry test blob missing", lambda f: f["ws2_extra_blobs"].clear()),
    ("receipt missing", lambda f: f.update({"ws2_receipt": None})),
    ("receipt modified", lambda f: f["ws2_receipt"].update({"scope": "anything"})),
    ("receipt claims a second transition", lambda f: f["ws2_receipt"].update({"node": NODE})),
    ("receipt blobs altered", lambda f: f["ws2_receipt"]["current_blobs"].update({"app/trust_readiness/registry.py": "4" * 40})),
    ("D-029 record blob changed", lambda f: f.update({"record_blob": "5" * 40})),
    ("D-029 record content changed", lambda f: f["record"].update({"authorization": "someone else"})),
    ("WS-2 manifest pin missing", lambda f: f.update({"ws2_manifest_pins": None})),
    ("WS-2 manifest pin differs", lambda f: f["ws2_manifest_pins"].update({"app/trust_readiness/registry.py": "6" * 40})),
    ("changed-path set gained an unrelated Trust path", lambda f: f.update({"changed": f["changed"] | {"app/trust_readiness/projection.py"}})),
    ("changed-path set lost a reviewed path", lambda f: f.update({"changed": f["changed"] - {"tests/test_trust_readiness_registry.py"}})),
    ("D-029 baseline main changed", lambda f: f.update({"main_blobs": {"app/trust_readiness/registry.py": "7" * 40}})),
))
def test_ws2_state_rejects_hybrids_incomplete_tuples_and_tampered_receipts(name, mutate):
    facts = copy.deepcopy(ws2_parent_facts())
    mutate(facts)
    assert problems(facts=facts, run=ws2_run_evidence()), name


def test_ws2_state_requires_all_fifteen_same_run_evidence_nodes():
    assert prod.WS2_EXTRA_NODES == () and len(prod.D029_EVIDENCE_NODES) == 15
    for missing in prod.D029_EVIDENCE_NODES:
        phases, native = ws2_run_evidence()
        del phases[missing]
        assert problems(facts=ws2_parent_facts(), run=(phases, native)), missing
        phases, native = ws2_run_evidence()
        native[missing] = ("failed", "x")
        assert problems(facts=ws2_parent_facts(), run=(phases, native)), missing
        phases, native = ws2_run_evidence()
        phases[missing] = ph("skipped", "skipped")
        native[missing] = ("skipped", "")
        assert problems(facts=ws2_parent_facts(), run=(phases, native)), missing


def test_ws2_state_does_not_loosen_any_outcome_rule():
    run = ws2_run_evidence()
    for kwargs in (dict(new=ph("failed", "boom"), new_native=("failed", "boom")), dict(new=ph("skipped", "x", wasxfail="e"), new_native=("xfail", "x")),
                   dict(old=ph("passed"), old_native=("passed", "")), dict(new=ph(setup_reason="different setup")), dict(new_native=())):
        assert problems(facts=ws2_parent_facts(), run=run, **kwargs), kwargs
    assert problems(run=run, node="tests/test_trust_readiness_registry.py::test_keys_are_unique_and_prefixed") == ["not the authorized node"]


def test_the_exception_is_not_selected_by_environment_branch_or_a_monkeypatched_policy(monkeypatch):
    facts = copy.deepcopy(ws2_parent_facts())
    facts["blobs"]["app/trust_readiness/registry.py"] = "0" * 40
    for key, value in (("GITHUB_HEAD_REF", "claude/new-session-85uo4c"), ("WS2_TRUST_SUCCESSOR", "1"), ("FINCO_ALLOW_OUTCOME_RECONCILIATION", "true")):
        monkeypatch.setenv(key, value)
    assert problems(facts=facts, run=ws2_run_evidence())
    source = inspect.getsource(prod.d029_transition_problems) + inspect.getsource(prod.ws2_expected_receipt) + inspect.getsource(prod.d029_source_facts)
    assert "environ" not in source and "getenv" not in source


def test_only_the_d029_and_ws2_tuples_exist_as_accepted_states():
    # the two tuples differ in exactly the three Trust sources; nothing else is a state
    assert set(prod.D029_BLOBS) == set(prod.WS2_TRUST_BLOBS) and all(prod.D029_BLOBS[k] != prod.WS2_TRUST_BLOBS[k] for k in prod.D029_BLOBS)
    assert not any(k in prod.WS2_TRUST_BLOBS for k in prod.D029_TRUST_CHANGED_BLOBS)



# --------------------------------------------------------------------------------------------------------------------------------------
# Correction C (2026-11-17): STATE C compares the historical WS-2 manifest pins with AUTHENTICATED HISTORICAL evidence (the reviewed pins the closed WF-03
# cohort records for the same paths), never with a later blob; the current Trust state is proven through the closed exact-source chain. Nothing below
# repins the WS-2 manifest, changes a D-029 constant, or admits an unreviewed value.
# --------------------------------------------------------------------------------------------------------------------------------------
WS2_MANIFEST_BLOB = "70ba41995ee7744fca9f3e86a63f5921a3b5da66"
TRUST_TEST = "tests/test_trust_readiness_registry.py"
HISTORICAL_TRUST_TEST_PIN = "eeb8302dce96e535e1ad9aa2a93b5a684197fdec"
CURRENT_TRUST_TEST_BLOB = "cb8a6c12551600f55b6a9c8c75b1cef2f5f1c519"


def _head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _state_c_inputs():
    from tests import wf03_lifecycle_scope as F
    facts = real_facts()
    return F, facts, *run_evidence()


def test_state_c_historical_pins_are_the_reviewed_cohort_pins_and_the_current_blob_is_the_later_pin():
    F, facts, phases, native = _state_c_inputs()
    reviewed = F.manifest(ROOT, _head())["source_blobs"]
    keys = (*prod.WS2_TRUST_BLOBS, *prod.WS2_TRUST_EXTRA_BLOBS)
    assert facts["ws2_manifest_pins"] == {p: reviewed[p] for p in keys}
    # the WS-2 manifest was NOT repinned: its historical pin of the Trust registry test is still the one the WF-03 cohort reviewed
    assert facts["ws2_manifest_pins"][TRUST_TEST] == HISTORICAL_TRUST_TEST_PIN and reviewed[TRUST_TEST] == HISTORICAL_TRUST_TEST_PIN
    assert git_blob(prod.WS2_MANIFEST) == WS2_MANIFEST_BLOB == reviewed[prod.WS2_MANIFEST]
    assert facts["wf03_state"]["current_blobs"][TRUST_TEST] == CURRENT_TRUST_TEST_BLOB == git_blob(TRUST_TEST)
    assert F.accepts_ci_trust_state(facts, phases, native)
    assert problems(facts=facts) == []


def _historical_only(F, facts, monkeypatch):
    """The WF-03-era state: every current Trust blob IS the reviewed pin (no later cohort involved). Accepted by the same predicate."""
    reviewed = F.manifest(ROOT, _head())["source_blobs"]
    actual = copy.deepcopy(facts["wf03_state"])
    actual["current_blobs"] = {p: reviewed[p] for p in F.CI_TRUST_PATHS}
    altered = copy.deepcopy(facts)
    altered["wf03_state"] = actual
    altered["blobs"] = {p: actual["current_blobs"][p] for p in altered["blobs"]}
    altered["ws2_extra_blobs"] = {p: actual["current_blobs"][p] for p in altered["ws2_extra_blobs"]}
    monkeypatch.setattr(F, "ci_source_facts", lambda: copy.deepcopy(actual))
    return altered


def test_state_c_accepts_the_historical_only_state_without_any_later_cohort(monkeypatch):
    F, facts, phases, native = _state_c_inputs()
    altered = _historical_only(F, facts, monkeypatch)
    monkeypatch.setattr(F, "_wf06b_supersedes", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a later cohort must not be consulted")))
    assert F.accepts_ci_trust_state(altered, phases, native)


def _one_byte(sha):
    return sha[:-1] + ("0" if sha[-1] != "0" else "1")


@pytest.mark.parametrize("path", sorted((*prod.WS2_TRUST_BLOBS, *prod.WS2_TRUST_EXTRA_BLOBS)))
@pytest.mark.parametrize("how", ("one_byte", "wrong_sha", "later_blob", "missing_path", "none_value"))
def test_state_c_rejects_every_mutation_of_a_historical_ws2_pin(path, how, monkeypatch):
    F, facts, phases, native = _state_c_inputs()
    pins = dict(facts["ws2_manifest_pins"])
    if how == "one_byte":
        pins[path] = _one_byte(pins[path])
    elif how == "wrong_sha":
        pins[path] = "0" * 40
    elif how == "later_blob":
        pins[path] = facts["wf03_state"]["current_blobs"][path]        # repinning to the later blob is exactly what is NOT acceptable when it differs
        if pins[path] == facts["ws2_manifest_pins"][path]:
            pytest.skip("this path has no later blob: the pin already equals the current blob")
    elif how == "missing_path":
        pins.pop(path)
    else:
        pins[path] = None
    facts["ws2_manifest_pins"] = pins
    assert not F.accepts_ci_trust_state(facts, phases, native)
    assert problems(facts=facts)           # and the whole transition is therefore refused


@pytest.mark.parametrize("name, mutate", (
    ("extra path", lambda p: p.update({"app/trust_readiness/projection.py": "1" * 40})),
    ("empty", lambda p: p.clear()),
))
def test_state_c_rejects_an_extra_or_empty_historical_pin_map(name, mutate):
    F, facts, phases, native = _state_c_inputs()
    mutate(facts["ws2_manifest_pins"])
    assert not F.accepts_ci_trust_state(facts, phases, native), name
    for bad in (None, [], "x"):
        facts["ws2_manifest_pins"] = bad
        assert not F.accepts_ci_trust_state(facts, phases, native)


@pytest.mark.parametrize("name", ("pin_changed", "pin_removed", "ws2_manifest_pin_changed", "ws2_manifest_pin_removed", "pins_absent"))
def test_state_c_rejects_an_altered_reviewed_cohort_record(name, monkeypatch):
    F, facts, phases, native = _state_c_inputs()
    real = F.manifest

    def forged(repo=None, ref=None):
        data = copy.deepcopy(real(repo, ref))
        pins = data["source_blobs"]
        if name == "pin_changed":
            pins[TRUST_TEST] = CURRENT_TRUST_TEST_BLOB              # "the reviewed record says cb8a…" while the WS-2 manifest still holds eeb8…
        elif name == "pin_removed":
            pins.pop(TRUST_TEST)
        elif name == "ws2_manifest_pin_changed":
            pins[prod.WS2_MANIFEST] = "2" * 40
        elif name == "ws2_manifest_pin_removed":
            pins.pop(prod.WS2_MANIFEST)
        else:
            data = {}
        return data
    monkeypatch.setattr(F, "manifest", forged)
    assert not F.accepts_ci_trust_state(facts, phases, native)


@pytest.mark.parametrize("which", ("head", "worktree"))
def test_state_c_rejects_ws2_manifest_bytes_that_are_not_the_reviewed_blob(which, monkeypatch):
    F, facts, phases, native = _state_c_inputs()
    real = F._read
    head = _head()

    def read(root, path, ref):
        data = real(root, path, ref)
        if path == prod.WS2_MANIFEST and (ref == head if which == "head" else ref is None):
            return data + b" "
        return data
    monkeypatch.setattr(F, "_read", read)
    assert not F.accepts_ci_trust_state(facts, phases, native)


@pytest.mark.parametrize("path", sorted(WF03_TRUST_PATHS := ("app/trust_readiness/registry.py", "docs/readiness/02_data_handling.md",
                                                             "docs/readiness/06_retention_and_deletion.md", "tests/test_trust_readiness_controls.py", TRUST_TEST)))
def test_state_c_current_blob_must_be_the_reviewed_pin_or_the_exact_pin_of_a_later_cohort(path, monkeypatch):
    F, facts, phases, native = _state_c_inputs()
    assert path in F.CI_TRUST_PATHS
    asked = []
    real = F._wf06b_supersedes

    def spy(p, value, root, ref):
        asked.append((p, value))
        return real(p, value, root, ref)

    def with_current(value):
        actual = copy.deepcopy(facts["wf03_state"])
        actual["current_blobs"][path] = value
        altered = copy.deepcopy(facts)
        altered["wf03_state"] = actual
        if path in altered["blobs"]:
            altered["blobs"][path] = value
        if path in altered["ws2_extra_blobs"]:
            altered["ws2_extra_blobs"][path] = value
        monkeypatch.setattr(F, "ci_source_facts", lambda: copy.deepcopy(actual))
        return altered
    monkeypatch.setattr(F, "_wf06b_supersedes", spy)
    real_value = facts["wf03_state"]["current_blobs"][path]
    assert F.accepts_ci_trust_state(with_current(real_value), phases, native)                    # control: the real current blob is accepted
    for forged in ("0" * 40, _one_byte(real_value)):
        asked.clear()
        assert not F.accepts_ci_trust_state(with_current(forged), phases, native)
        assert (path, forged) in asked, "rejected for the wrong reason: the later-cohort pin was never consulted"


@pytest.mark.parametrize("how", ("failed", "skipped", "xfail", "native_failed", "native_missing", "missing", "setup_failed"))
@pytest.mark.parametrize("index", range(3))
def test_state_c_requires_each_same_run_evidence_node_to_have_really_passed(how, index):
    from tests import wf03_lifecycle_scope as F
    facts = real_facts()
    phases, native = run_evidence()
    node = F.CI_EVIDENCE_NODES[index]
    if how == "failed":
        phases[node] = ph(call="failed")
    elif how == "skipped":
        phases[node] = ph(call="skipped", reason="x")
    elif how == "xfail":
        phases[node] = ph(call="skipped", wasxfail="x")
    elif how == "native_failed":
        native[node] = ("failed", "")
    elif how == "native_missing":
        native.pop(node)
    elif how == "setup_failed":
        phases[node] = ph(setup="failed")
    else:
        phases.pop(node)
    assert not F.accepts_ci_trust_state(facts, phases, native)


def test_state_c_still_rejects_the_original_d029_and_ws2_tuples_as_state_c():
    from tests import wf03_lifecycle_scope as F
    facts = ws2_parent_facts()
    assert facts["wf03_state"] is None and not F.accepts_ci_trust_state(facts, *ws2_run_evidence())      # A/B are accepted by their own predicates only
    assert problems(facts=facts, run=ws2_run_evidence()) == []                                          # ... which are untouched
    assert prod.WS2_TRUST_EXTRA_BLOBS == {TRUST_TEST: "69e0b15e0c4cfd36102d1442e577f7cc6d9b6516"}
    assert prod.D029_TRUST_CHANGED_BLOBS == {"tests/test_trust_readiness_controls.py": "cd5b3114d9a11ca4507667a099bb853573d056d3"}


# --- the closed exact-source chain itself (real Git objects, immutable refs; nothing is checked out or written to a ref) ---------------------
def _mutated_ref(tmp_path, changes):
    """A commit on top of HEAD whose tree differs only by ``changes`` ({path: bytes}); loose objects only, no ref, no worktree."""
    env = {**__import__("os").environ, "GIT_INDEX_FILE": str(tmp_path / "index"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}

    def run(*args, **kw):
        return subprocess.run(["git", *args], cwd=ROOT, env=env, check=True, capture_output=True, **kw).stdout.decode().strip()
    run("read-tree", "HEAD")
    for path, data in changes.items():
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=ROOT, env=env, input=data, check=True, capture_output=True).stdout.decode().strip()
        run("update-index", "--add", "--cacheinfo", "100644," + blob + "," + path)
    tree = run("write-tree")
    return run("commit-tree", tree, "-p", "HEAD", "-m", "synthetic")


def _head_bytes(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=ROOT)


def test_the_real_chain_accepts_head_and_rejects_every_arbitrary_trust_blob_and_extra_path(tmp_path):
    from tests import wf03_lifecycle_scope as F
    assert F.exact_blobs_ok(ROOT, _head())
    for path in F.CI_TRUST_PATHS:
        ref = _mutated_ref(tmp_path, {path: _head_bytes(path) + b"\n# unreviewed\n"})
        assert not F.exact_blobs_ok(ROOT, ref), path
    extra = _mutated_ref(tmp_path, {"app/trust_readiness/unreviewed_extra.py": b"x = 1\n"})
    assert not F.valid(ROOT, extra)


def test_the_real_chain_rejects_repinning_the_ws2_manifest_or_the_bess_predecessor(tmp_path):
    from tests import wf03_lifecycle_scope as F
    manifest = json.loads(_head_bytes(prod.WS2_MANIFEST))
    manifest["source_blobs"][TRUST_TEST] = CURRENT_TRUST_TEST_BLOB            # the rejected "repin eeb8… -> cb8a…" shortcut
    repin = _mutated_ref(tmp_path, {prod.WS2_MANIFEST: (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()})
    assert not F.exact_blobs_ok(ROOT, repin) and not COHORTS.valid(ROOT, repin)
    bess_path = "docs/bess_setup/SOURCE_SUCCESSOR.json"
    bess = json.loads(_head_bytes(bess_path))
    assert bess["base_blobs"][TRUST_TEST] == HISTORICAL_TRUST_TEST_PIN and bess["source_blobs"][TRUST_TEST] == CURRENT_TRUST_TEST_BLOB
    for section in ("base_blobs", "source_blobs"):
        forged = json.loads(_head_bytes(bess_path))
        forged[section][TRUST_TEST] = "0" * 40
        ref = _mutated_ref(tmp_path, {bess_path: (json.dumps(forged, indent=2, sort_keys=True) + "\n").encode()})
        assert not COHORTS.valid(ROOT, ref), section

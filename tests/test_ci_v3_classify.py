"""Standalone-attempt classification never approves, drops or relaxes a module, and never trusts a later PASS."""
import json

import pytest

from tools.ci_v3_classify import MIN_TARGET_PASSES, classify, collect, decide, nonpass_proposal
from tools.ci_v3_schema import ContractError

EXPECTED = 2
SHA = "0" * 64


def attempt(kind="first", label="a", **kw):
    base = {"module": "tests/test_a.py", "module_sha256": SHA, "historical": False, "tag": None, "exit_code": 0, "timed_out": False, "failures": 0, "errors": 0,
            "skipped": 0, "tests": EXPECTED, "seconds": 1.0, "tail": "", "kind": kind, "label": label, "concurrency": 3 if kind == "target" else 4, "cpus": 1.33, "tree": "T"}
    return {**base, **kw}


def target_passes(count):
    return [attempt("target", f"t{i}") for i in range(count)]


FAIL = dict(exit_code=1, failures=1)


def prepared():
    nodes = [{"module": "tests/test_a.py"}] * 2 + [{"module": "tests/test_b.py"}]
    mods = {m: {"sha256": "0" * 64, "findings": []} for m in ("tests/test_a.py", "tests/test_b.py", "tests/helper.py")}
    return {"inventory": {"nodes": nodes}, "isolation": {"schema": 3, "kind": "ci-v3-isolation-policy", "modules": mods}}


def test_stable_pass_is_proposal_only_and_helpers_are_explicit():
    attempts = {"tests/test_a.py": [attempt()], "tests/test_b.py": [attempt(tests=1, module="tests/test_b.py")]}
    proposal, summary = classify(prepared(), attempts)
    mods = proposal["modules"]
    assert mods["tests/test_a.py"]["category"] == "stable-pass" and mods["tests/test_a.py"]["mode"] == "runner-private"
    assert not any(m["reviewed"] for m in mods.values())
    assert mods["tests/helper.py"]["category"] == "not-collected-helper"
    assert summary["unresolved_blocking_admission"] == 0 and summary["unresolved_modules"] == []


@pytest.mark.parametrize("history,category", [
    ([attempt(**FAIL)], "standalone-failure"),
    ([attempt(timed_out=True, exit_code=None)], "timeout"),
    ([attempt(), attempt("uncontended", timed_out=True, exit_code=None)], "timeout"),
    ([attempt(exit_code=137)], "capacity-exhaustion"),
    ([attempt(exit_code=-9)], "capacity-exhaustion"),
    ([attempt(), attempt("uncontended", tail="E MemoryError")], "capacity-exhaustion"),
    ([attempt(tests=1)], "coverage-mismatch"),
    ([attempt(skipped=1)], "nonpass-approval-required"),
    ([attempt(skipped=1), attempt("uncontended", skipped=2)], "inconsistent-verdicts"),
])
def test_unclean_attempts_block(history, category):
    mode, got, _ = decide(history, EXPECTED, current_sha=SHA)
    assert (mode, got) == ("blocked", category)


def test_reproduced_flaw_failed_under_load_then_one_uncontended_pass_stays_blocked():
    """Before the correction this exact history was 'load-sensitive-pass' / runner-private."""
    mode, category, _ = decide([attempt(**FAIL), attempt("uncontended", label="rerun")], EXPECTED, current_sha=SHA)
    assert (mode, category) == ("blocked", "load-sensitive-unproven")


@pytest.mark.parametrize("reruns", [1, 2, 10, 100])
def test_repeated_uncontended_reruns_never_unlock(reruns):
    history = [attempt(**FAIL)] + [attempt("uncontended", f"u{i}") for i in range(reruns)]
    assert decide(history, EXPECTED, current_sha=SHA)[:2] == ("blocked", "load-sensitive-unproven")


def test_only_equivalent_target_concurrency_unlocks_and_keeps_the_failure():
    history = [attempt(**FAIL)] + target_passes(MIN_TARGET_PASSES)
    assert decide(history, EXPECTED, current_sha=SHA)[:2] == ("runner-private", "target-concurrency-stability-validated")
    assert decide([attempt(**FAIL)] + target_passes(MIN_TARGET_PASSES - 1), EXPECTED, current_sha=SHA)[:2] == ("blocked", "load-sensitive-unproven")
    wrong = [{**a, "concurrency": 1} for a in target_passes(MIN_TARGET_PASSES)]   # not three-way concurrency
    assert decide([attempt(**FAIL)] + wrong, EXPECTED, current_sha=SHA)[:2] == ("blocked", "load-sensitive-unproven")
    proposal, _ = classify(prepared(), {"tests/test_a.py": history})
    record = proposal["modules"]["tests/test_a.py"]
    assert record["reviewed"] is False and any(a["exit_code"] == 1 for a in record["attempts"])


@pytest.mark.parametrize("bad", [dict(FAIL), dict(timed_out=True, exit_code=None), dict(exit_code=137)])
def test_any_target_failure_blocks_even_after_many_passes(bad):
    history = [attempt(**FAIL)] + target_passes(20) + [attempt("target", "tx", **bad)]
    assert decide(history, EXPECTED, current_sha=SHA)[0] == "blocked"


def test_failure_after_an_initial_pass_is_inconsistent_not_approved():
    assert decide([attempt(), attempt("target", **FAIL)], EXPECTED, current_sha=SHA)[:2] == ("blocked", "inconsistent-verdicts")


def test_missing_evidence_blocks_and_collection_skips_are_explicit():
    proposal, summary = classify(prepared(), {}, skipped_modules={"tests/test_b.py"})
    assert proposal["modules"]["tests/test_a.py"]["category"] == "no-standalone-evidence"
    assert proposal["modules"]["tests/test_b.py"]["category"] == "collection-skipped"
    assert summary["unresolved_blocking_admission"] == 1


def write_run(path, kind, label, module="tests/test_a.py", image_id="img", tree="tree", **kw):
    path.mkdir(parents=True)
    (path / "meta.json").write_text(json.dumps({"kind": kind, "label": label, "image_id": image_id, "tree": tree, "concurrency": 4}))
    (path / "lane-0").mkdir()
    record = {"module": module, "tag": None, "exit_code": 0, "timed_out": False, "failures": 0, "errors": 0, "skipped": 0, "tests": 2, "seconds": 1, "tail": ""}
    (path / "lane-0/results.jsonl").write_text(json.dumps({**record, **kw}) + "\n")


def test_attempt_loader_preserves_every_attempt_and_binds_identity(tmp_path):
    write_run(tmp_path / "one", "first", "one", **FAIL)
    write_run(tmp_path / "two", "uncontended", "two")
    loaded = collect([tmp_path / "one", tmp_path / "two"], {"image_id": "img", "trees": ["tree"]})
    assert [a["label"] for a in loaded["tests/test_a.py"]] == ["one", "two"] and loaded["tests/test_a.py"][0]["exit_code"] == 1
    with pytest.raises(ContractError, match="not executed on the evidence"):
        collect([tmp_path / "one"], {"image_id": "other", "trees": ["tree"]})
    write_run(tmp_path / "dup", "first", "one")
    with pytest.raises(ContractError, match="duplicate attempt"):
        collect([tmp_path / "one", tmp_path / "dup"])


def junit(path, cases):
    body = "".join(f'<testcase classname="{c}" name="{n}"><skipped type="{t}" message="{m}"/></testcase>' for c, n, t, m in cases)
    path.write_text(f'<testsuites><testsuite tests="{len(cases)}">{body}</testsuite></testsuites>')
    return path


def test_nonpass_proposal_uses_exact_original_identity_and_rejects_conflicts(tmp_path):
    ids = ["tests/test_a.py::test_x", "tests/test_a.py::TestK::test_y[p]"]
    one = junit(tmp_path / "one.xml", [("tests.test_a", "test_x", "pytest.skip", "node is not available"),
                                       ("tests.test_a.TestK", "test_y[p]", "pytest.xfail", "known")])
    proposal, unmatched = nonpass_proposal([one.read_bytes()], ids)
    assert proposal == {ids[0]: {"status": "skipped", "reason": "node is not available"}, ids[1]: {"status": "xfail", "reason": "known"}} and not unmatched
    changed = junit(tmp_path / "two.xml", [("tests.test_a", "test_x", "pytest.skip", "different reason")])
    with pytest.raises(ContractError, match="inconsistent nonpass"):
        nonpass_proposal([one.read_bytes(), changed.read_bytes()], ids)
    foreign = junit(tmp_path / "three.xml", [("tests.test_a", "test_unknown", "pytest.skip", "x")])
    assert nonpass_proposal([foreign.read_bytes()], ids)[1][0]["name"] == "test_unknown"


def historical(**kw):
    return attempt(historical=True, label="old", image_id="old", tree="old", **kw)


def test_historical_failure_on_unchanged_module_still_counts_and_needs_target_stability():
    old = historical(**FAIL)
    assert decide([old, attempt("target", "t0")], EXPECTED, current_sha=SHA)[:2] == ("blocked", "load-sensitive-unproven")
    assert decide([old] + target_passes(MIN_TARGET_PASSES), EXPECTED, current_sha=SHA)[:2] == ("runner-private", "target-concurrency-stability-validated")


def test_source_change_supersedes_a_historical_failure_but_it_stays_recorded():
    old = historical(**FAIL, module_sha256="1" * 64)
    assert decide([old, attempt("target", "t0")], EXPECTED, current_sha=SHA)[:2] == ("runner-private", "stable-pass")
    proposal, _ = classify({**prepared(), "isolation": {**prepared()["isolation"], "modules": {"tests/test_a.py": {"sha256": SHA}}}},
                           {"tests/test_a.py": [old, attempt("target", "t0")]})
    assert [a["historical"] for a in proposal["modules"]["tests/test_a.py"]["attempts"]] == [True, False]


def test_historical_pass_never_supplies_positive_evidence():
    assert decide([historical()], EXPECTED, current_sha=SHA)[:2] == ("blocked", "historical-only-needs-current-execution")
    assert decide([historical(), historical(skipped=0)], EXPECTED, current_sha=SHA)[0] == "blocked"


def test_target_attempts_below_the_cpu_budget_do_not_count_and_the_constraint_is_reported():
    starved = [{**a, "cpus": 1.0} for a in target_passes(MIN_TARGET_PASSES)]
    assert decide([attempt(**FAIL)] + starved, EXPECTED, current_sha=SHA)[:2] == ("blocked", "load-sensitive-unproven")
    mode, category, reason = decide([attempt(**FAIL, cpus=1.0)] + target_passes(MIN_TARGET_PASSES), EXPECTED, current_sha=SHA)
    assert (mode, category) == ("runner-private", "target-concurrency-stability-validated") and "failed at [1.0] CPU" in reason


def test_exact_source_attempt_on_a_changed_module_blob_is_stale_and_never_counts():
    old = attempt("target", "t0", module_sha256="1" * 64)
    assert decide([old], EXPECTED, current_sha=SHA)[:2] == ("blocked", "no-standalone-evidence")
    assert decide([old, attempt("target", "t1")], EXPECTED, current_sha=SHA)[:2] == ("runner-private", "stable-pass")


def test_baseline_and_targeted_trees_are_both_accepted_by_the_loader(tmp_path):
    write_run(tmp_path / "base", "first", "base", tree="B"); write_run(tmp_path / "target", "target", "target", tree="T")
    loaded = collect([tmp_path / "base", tmp_path / "target"], {"image_id": "img", "trees": ["B", "T"]})
    assert {a["tree"] for a in loaded["tests/test_a.py"]} == {"B", "T"}
    with pytest.raises(ContractError, match="not executed on the evidence"):
        collect([tmp_path / "base"], {"image_id": "img", "trees": ["T"]})


OTHER_MODULE_SHA = "a" * 64


@pytest.mark.parametrize("override,reason", [
    ({"module_sha256": None}, "missing-module-sha256"),
    ({"module_sha256": "1" * 64}, "stale-or-mismatched-module-sha256"),            # an older blob of the same module
    ({"module_sha256": OTHER_MODULE_SHA}, "stale-or-mismatched-module-sha256"),    # another module's blob
    ({"module_sha256": "A" * 64}, "malformed-module-sha256"),                       # not lower-case hex
    ({"module_sha256": "abc"}, "malformed-module-sha256"),
    ({"module_sha256": 12345}, "malformed-module-sha256"),
])
def test_exact_source_attempt_without_the_current_module_identity_never_supplies_positive_evidence(override, reason):
    bad = attempt("target", "t0", **override)
    assert decide([bad], EXPECTED, current_sha=SHA)[:2] == ("blocked", "no-standalone-evidence")
    assert reason in decide([bad], EXPECTED, current_sha=SHA)[2]
    assert decide([bad for _ in range(MIN_TARGET_PASSES + 3)], EXPECTED, current_sha=SHA)[0] == "blocked"      # volume does not help
    # stability after a real failure cannot be assembled from unidentified or stale passes either
    unproven = [attempt(**FAIL)] + [attempt("target", f"t{i}", **override) for i in range(MIN_TARGET_PASSES)]
    assert decide(unproven, EXPECTED, current_sha=SHA)[0] == "blocked"


def test_missing_key_entirely_is_treated_like_none():
    bare = {k: v for k, v in attempt("target", "t0").items() if k != "module_sha256"}
    assert decide([bare], EXPECTED, current_sha=SHA)[:2] == ("blocked", "no-standalone-evidence")


@pytest.mark.parametrize("current", [None, "", "short", "G" * 64])
def test_unavailable_or_malformed_current_identity_blocks_every_attempt(current):
    assert decide([attempt("target", "t0")], EXPECTED, current_sha=current)[:2] == ("blocked", "no-standalone-evidence")


def test_one_identified_attempt_still_counts_next_to_unidentified_ones():
    mixed = [attempt("target", "t0", module_sha256=None), attempt("target", "t1")]
    assert decide(mixed, EXPECTED, current_sha=SHA)[:2] == ("runner-private", "stable-pass")


def test_every_attempt_is_preserved_with_an_exclusion_reason():
    attempts = [attempt("target", "ok"), attempt("target", "none", module_sha256=None), attempt("target", "old", module_sha256="1" * 64),
                historical(**FAIL, module_sha256="2" * 64)]
    proposal, _ = classify({**prepared(), "isolation": {**prepared()["isolation"], "modules": {"tests/test_a.py": {"sha256": SHA}}}}, {"tests/test_a.py": attempts})
    assert len(proposal["modules"]["tests/test_a.py"]["attempts"]) == 4
    rows = proposal["modules"]["tests/test_a.py"]["attempts"]
    assert [(r["counts"], r["exclusion"]) for r in rows] == [(True, None), (False, "missing-module-sha256"),
                                                              (False, "stale-or-mismatched-module-sha256"), (False, "historical-evidence")]


def test_ci_v3_self_tests_count_only_evidence_from_the_final_tree():
    old = attempt("target", "old", tree="B")
    new = attempt("target", "new", tree="T")
    module = "tests/test_ci_v3_something.py"
    assert decide([old], EXPECTED, current_sha=SHA, module=module, final_tree="T")[:2] == ("blocked", "no-standalone-evidence")
    assert "ci-v3-self-test-needs-final-tree-evidence" in decide([old], EXPECTED, current_sha=SHA, module=module, final_tree="T")[2]
    assert decide([old, new], EXPECTED, current_sha=SHA, module=module, final_tree="T")[:2] == ("runner-private", "stable-pass")
    # a product test module may still carry evidence from the baseline tree
    assert decide([old], EXPECTED, current_sha=SHA, module="tests/test_product.py", final_tree="T")[:2] == ("runner-private", "stable-pass")


def historical_run(path, label="old-study", **kw):
    write_run(path, "first", label, tree="OLD", image_id="old-image", module="tests/test_a.py", **kw)
    meta = json.loads((path / "meta.json").read_text()); meta["historical"] = False      # even if mislabelled, the loader forces it
    (path / "meta.json").write_text(json.dumps(meta))


def test_earlier_source_pass_is_never_current_evidence_even_when_the_test_file_is_unchanged(tmp_path):
    for i in range(10):                                                                  # ten earlier-source passes do not matter
        historical_run(tmp_path / f"h{i}", f"old-{i}", module_sha256=SHA)
    history = collect([], {"image_id": "img", "trees": ["NEW"]}, [tmp_path / f"h{i}" for i in range(10)])["tests/test_a.py"]
    assert all(a["historical"] for a in history)
    mode, category, reason = decide(history, EXPECTED, current_sha=SHA)
    assert (mode, category) == ("blocked", "historical-only-needs-current-execution") and "must be executed on the current source" in reason


def test_a_fresh_current_source_attempt_resolves_what_history_cannot(tmp_path):
    historical_run(tmp_path / "h", module_sha256=SHA)
    history = collect([], None, [tmp_path / "h"])["tests/test_a.py"] + [attempt("target", "fresh")]
    assert decide(history, EXPECTED, current_sha=SHA)[:2] == ("runner-private", "stable-pass")


def test_earlier_source_failure_on_an_unchanged_module_still_counts_against_it(tmp_path):
    historical_run(tmp_path / "h", module_sha256=SHA, **FAIL)
    history = collect([], None, [tmp_path / "h"])["tests/test_a.py"]
    assert decide(history + [attempt("target", "fresh")], EXPECTED, current_sha=SHA)[:2] == ("blocked", "load-sensitive-unproven")


def test_historical_directories_are_not_bound_to_the_current_identity_but_current_ones_are(tmp_path):
    historical_run(tmp_path / "h", module_sha256=SHA)
    write_run(tmp_path / "cur", "target", "cur", tree="OLD", image_id="img")
    with pytest.raises(ContractError, match="not executed on the evidence"):
        collect([tmp_path / "cur"], {"image_id": "img", "trees": ["NEW"]}, [tmp_path / "h"])
    assert collect([], {"image_id": "img", "trees": ["NEW"]}, [tmp_path / "h"])

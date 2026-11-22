"""The proposal approves nothing, covers exactly the collected modules/nodes and lists every owner decision."""
import pytest

from tools.ci_v3_proposal import build, owner_decisions, reassess
from tools.ci_v3_schema import ContractError, seal


def world():
    nodes = [{"nodeid": "tests/test_a.py::t1", "module": "tests/test_a.py"}, {"nodeid": "tests/test_a.py::t2", "module": "tests/test_a.py"}]
    inventory = seal({"nodes": nodes, "modules": {"tests/test_a.py": {}}, "source": {"head": "h", "tree": "t"}})
    policy = seal({"inventory_digest": inventory["digest"], "allowed_nonpass": {}})
    weights = seal({"modules_ms": {"tests/test_a.py": 2}})
    iso = {"modules": {"tests/test_a.py": {"category": "stable-pass", "mode": "runner-private", "reason": "ok", "reviewed": False}}}
    prepared = {"inventory": inventory, "policy": policy, "weights": weights, "isolation": {"modules": dict(iso["modules"])},
                "collection": {"skips": [{"nodeid": "tests/test_b.py", "reason": "x"}]}, "environment": {"python": "3.12"}}
    summary = {"categories": {"stable-pass": 1}, "unresolved_blocking_admission": 0, "unresolved_modules": []}
    nonpass = seal({"allowed_nonpass": {"tests/test_a.py::t1": {"status": "skipped", "reason": "r", "environment_dependent": False}},
                    "rejected": {}, "needs_owner_decision": {}, "control_nonpass_not_reproduced": {}, "control": {"reference": "run"}, "coverage_equivalence": {}})
    equivalence = seal({"fully_equivalent": True, "unaccepted_differences": []})
    return prepared, {"proposal": iso, "summary": summary}, nonpass, {"image_id": "sha256:x", "registry_digest": None}, equivalence


def test_clean_evidence_still_is_not_admission_ready_and_names_the_remaining_blockers():
    bundle, proposal = build(*world(), None, None, {})
    assert proposal["admission_ready"] is False and proposal["authority"] == "proposal-not-approved"
    assert {"image not published", "nonpass policy not approved", "no owner has reviewed isolation", "hosted-runner calibration absent or failing"} <= set(proposal["admission_blockers"])
    assert set(bundle) == {"inventory", "policy", "weights", "isolation", "environment"} and not any(m["reviewed"] for m in bundle["isolation"]["modules"].values())
    assert proposal["inventory"]["nodes"] == 2 and proposal["inventory"]["collection_skips"] == 1 and len(proposal["inventory"]["node_ids_sha256"]) == 64


def test_proposal_is_reproducible_byte_for_byte():
    one = build(*world(), None, None, {})[1]
    two = build(*world(), None, None, {})[1]
    assert one == two


def test_policy_carries_only_the_proposed_exact_records():
    bundle, _ = build(*world(), None, None, {})
    assert list(bundle["policy"]["allowed_nonpass"]) == ["tests/test_a.py::t1"]


def test_classification_must_cover_exactly_the_collected_modules():
    prepared, classification, nonpass, image, equivalence = world()
    classification["proposal"]["modules"]["tests/extra.py"] = {}
    with pytest.raises(ContractError, match="does not cover"):
        build(prepared, classification, nonpass, image, equivalence, None, None, {})


def test_reassessment_maps_every_previously_unresolved_module_and_ignores_resolved_ones():
    previous = {"tests/test_a.py": {"category": "standalone-failure"}, "tests/test_b.py": {"category": "standalone-pass"}, "tests/gone.py": {"category": "nonpass-approval-required"}}
    now = {"tests/test_a.py": {"category": "stable-pass", "mode": "runner-private", "reason": "ok"}}
    rows = {r["module"]: r for r in reassess(previous, now)}
    assert set(rows) == {"tests/test_a.py", "tests/gone.py"} and rows["tests/test_a.py"]["resolved"] and not rows["tests/gone.py"]["resolved"]


def test_owner_decisions_include_calibration_and_publication_until_provided():
    prepared, classification, nonpass, image, equivalence = world()
    texts = " ".join(d["decision"] for d in owner_decisions(classification["summary"], nonpass, equivalence, None, image))
    assert "calibrate" in texts and "publication" in texts and "golden_flow" in texts


def test_observed_daemon_threads_become_a_blocking_owner_decision_and_stay_unapproved():
    threads = [{"name": "demo-cleanup", "daemon": True}, {"name": "finco-r-live-snapshot-warmer", "daemon": True}]
    bundle, proposal = build(*world(), None, None, {}, threads)
    assert "daemon thread policy not approved" in proposal["admission_blockers"]
    assert proposal["daemon_thread_proposal"]["observed_after_pytest_returned"] == threads
    assert "allowed_daemon_threads" not in bundle["isolation"]                 # nothing is enabled by the proposal
    decision = next(d for d in proposal["owner_decisions"] if "daemon threads" in d["decision"])
    assert decision["blocking"] and "demo-cleanup" in decision["decision"]


def test_proposal_separates_historical_execution_from_evidence_for_the_current_source():
    prepared, classification, nonpass, image, equivalence = world()
    classification["summary"] = {"categories": {"historical-only-needs-current-execution": 480, "stable-pass": 1}, "unresolved_blocking_admission": 480,
                                 "unresolved_modules": ["tests/test_a.py"]}
    historical = [{"manifest_digest": "d" * 64, "source": {"head": "old", "tree": "oldtree"}, "applies_to_this_source": False,
                   "unreviewed_change_classes": {"financial-source": 7}, "unreviewed_changed_paths": 40}]
    _, proposal = build(prepared, classification, nonpass, image, equivalence, None, None, {}, (), historical)
    scope = proposal["evidence_scope"]
    assert scope["current_source"] == {"head": "h", "tree": "t"} and scope["historical"] == historical
    assert "not equivalence evidence" in scope["statement"] and proposal["admission_ready"] is False
    assert "480 modules have only earlier-source (historical) evidence" in proposal["admission_blockers"]
    assert "earlier execution evidence does not apply to the current source" in proposal["admission_blockers"]


def test_missing_full_control_phase_evidence_is_an_explicit_blocker():
    _, proposal = build(*world(), None, None, {})
    assert 'same-source original-node/phase comparison absent' in proposal['admission_blockers']
    assert proposal['admission_ready'] is False

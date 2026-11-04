"""CI V4 selector: risk routing, fail-closed behaviour and self-weakening refusal (synthetic paths only)."""
import copy
import json
from pathlib import Path

import pytest

from tools import ci_v4_select as S

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())


def plan(paths, policy=None, **kw):
    return S.select(paths, copy.deepcopy(policy or POLICY), root=ROOT, head_sha="a" * 40, tree_sha="b" * 40, base_sha="c" * 40, **kw)


def test_policy_valid_and_every_declared_suite_module_exists():
    S.validate_policy(copy.deepcopy(POLICY))
    for name, suite in POLICY["suites"].items():
        for m in suite["modules"]:
            assert (ROOT / m).is_file(), (name, m)


def test_ordinary_docs_pr_is_fast_baseline_only():
    p = plan(["README.md", "docs/engine/notes.md"])
    assert p["tier"] == "fast" and p["suites"] == ["fast_baseline"]
    assert set(p["pytest_modules"]) == set(POLICY["suites"]["fast_baseline"]["modules"])
    assert p["not_selected"]["label"] == "NOT SELECTED (not PASS)" and p["not_selected"]["count"] > 500
    assert not p["needs_browser"] and not p["needs_native_docker"]
    assert p["schedule"]["workers"] <= POLICY["workers"]["fast"]["max"]


def test_changed_test_module_selects_itself_only_in_fast():
    p = plan(["tests/test_goal_seek_v1.py"])
    assert p["tier"] == "fast" and "tests/test_goal_seek_v1.py" in p["pytest_modules"]


def test_react_ux_pr_is_risk_with_bundle_identity_and_browser():
    p = plan(["frontend/src/app/CostWorkbench.tsx", "static/react/finco-react.js"])
    assert p["tier"] == "risk" and p["needs_frontend_build"] and p["needs_browser"]
    assert {"risk_ui_build", "risk_f01", "risk_security"} <= set(p["suites"])


def test_non_financial_frontend_is_risk_but_without_f01_matrix():
    p = plan(["frontend/src/nonmodel/Landing.tsx"])
    assert p["tier"] == "risk" and "risk_ui_build" in p["suites"] and "risk_f01" not in p["suites"]


def test_financing_capex_pr_runs_finance_oracle_native_and_f01():
    p = plan(["app/capex_engine.py", "financial_engine/financing/__init__.py"])
    assert p["tier"] == "risk" and p["needs_native_docker"] and p["needs_browser"]
    assert {"risk_finance", "risk_f01", "risk_f01_native", "risk_save_integrity"} <= set(p["suites"])
    assert "tests/test_goal_seek_v1.py" in p["pytest_modules"]


def test_security_auth_pr_runs_security_negatives_and_dependents():
    p = plan(["app/auth.py"])
    assert p["tier"] == "risk" and "risk_security" in p["suites"]
    assert p["dependents"]["total"] >= 1          # real importers of app.auth are selected
    for m in POLICY["suites"]["risk_security"]["modules"]:
        assert m in p["pytest_modules"]


def test_engine_dscr_pr_cannot_pass_with_docs_or_fast_only():
    p = plan(["financial_engine/senior_debt/__init__.py", "docs/engine/x.md"])
    assert p["tier"] == "risk"
    for m in ("tests/test_h2_dscr_sculpting_feasibility.py", "tests/test_model_financing_bankability.py", "tests/test_wf04_dscr_contract_terms.py"):
        assert m in p["pytest_modules"]


def test_github_policy_pr_is_a_control_change():
    p = plan([".github/workflows/ci_v4_pr.yml"])
    assert p["tier"] == "risk" and p["control_changed"] and "risk_governance" in p["suites"]
    q = plan(["docs/ci_v4/ci-v4-policy.json"])
    assert q["control_changed"] and q["tier"] == "risk"


def test_unknown_path_fails_closed_to_extended_risk():
    p = plan(["brand_new_dir/thing.bin"])
    assert p["tier"] == "risk" and p["unknown_paths"] == ["brand_new_dir/thing.bin"]
    assert any(t.get("fail_closed") for t in p["triggers"])
    assert {"risk_finance", "risk_security", "risk_save_integrity", "risk_governance"} <= set(p["suites"])


def test_mixed_docs_and_finance_takes_the_max_tier():
    assert plan(["README.md", "domain/__init__.py"])["tier"] == "risk"


@pytest.mark.parametrize("bad", ["../etc/passwd", "/abs/path.py", "tests/../app/auth.py"])
def test_path_traversal_is_refused(bad):
    with pytest.raises(S.PolicyError):
        plan([bad])


def test_force_tier_can_only_raise():
    assert plan(["README.md"], force_tier="full")["tier"] == "full"
    with pytest.raises(S.PolicyError):
        plan(["app/auth.py"], force_tier="fast")


def test_full_selects_every_test_module():
    p = plan([], force_tier="full")
    every = sorted(x.relative_to(ROOT).as_posix() for x in (ROOT / "tests").glob("test_*.py"))
    assert set(every) <= set(p["pytest_modules"]) and p["not_selected"]["count"] == 0 and p["tier"] == "full"


def test_policy_rule_routing_finance_to_fast_is_rejected():
    bad = copy.deepcopy(POLICY)
    bad["rules"].insert(0, {"id": "sneaky", "tier": "fast", "patterns": ["financial_engine/**"], "suites": []})
    with pytest.raises(S.PolicyError):
        S.validate_policy(bad)


def test_policy_unknown_default_fast_is_rejected():
    bad = copy.deepcopy(POLICY); bad["default_tier_for_unknown_path"] = "fast"
    with pytest.raises(S.PolicyError):
        S.validate_policy(bad)


def test_policy_missing_suite_reference_is_rejected():
    bad = copy.deepcopy(POLICY); bad["rules"][0]["suites"] = ["does_not_exist"]
    with pytest.raises(S.PolicyError):
        S.validate_policy(bad)


def test_missing_declared_test_module_fails_closed():
    bad = copy.deepcopy(POLICY); bad["suites"]["fast_baseline"]["modules"].append("tests/test_vanished_v0.py")
    with pytest.raises(S.PolicyError):
        plan(["README.md"], policy=bad)


def test_malicious_selector_change_that_shrinks_selection_is_refused():
    """A PR edits the policy to drop risk_finance from engine changes; judged against the trusted BASE policy it is refused."""
    changed = ["financial_engine/senior_debt/__init__.py", "docs/ci_v4/ci-v4-policy.json"]
    base = plan(changed)
    weakened = copy.deepcopy(POLICY)
    for r in weakened["rules"]:
        if r["id"] == "financial_core":
            r["suites"] = ["risk_security"]
    with pytest.raises(S.PolicyError):
        S.compare_with_head_policy(base, weakened, changed, root=ROOT, head_sha="a" * 40, tree_sha="b" * 40, base_sha="c" * 40)


def test_selector_change_that_only_adds_coverage_is_accepted():
    changed = ["app/auth.py", "tools/ci_v4_select.py"]
    base = plan(changed)
    stronger = copy.deepcopy(POLICY)
    stronger["suites"]["fast_baseline"]["modules"].append("tests/test_goal_seek_v1.py")
    head = S.compare_with_head_policy(base, stronger, changed, root=ROOT, head_sha="a" * 40, tree_sha="b" * 40, base_sha="c" * 40)
    assert S.covers(head, base)


def test_synthetic_regression_edits_in_critical_files_trigger_their_suites():
    """Owner-style synthetic regressions: each critical edit must pull in the suite that would catch it."""
    expect = {
        "financial_engine/cfads.py": "risk_finance",
        "app/input_adapter.py": "risk_save_integrity",
        "app/auth.py": "risk_security",
        "frontend/src/app/InputsOverview.tsx": "risk_f01",
        "tests/conftest.py": "risk_governance",
        "requirements.txt": "risk_finance",
    }
    for path, suite in expect.items():
        assert suite in plan([path])["suites"], path


def test_plan_is_deterministic_and_digest_bound():
    a, b = plan(["app/auth.py"]), plan(["app/auth.py"])
    assert a == b and len(a["digest"]) == 64

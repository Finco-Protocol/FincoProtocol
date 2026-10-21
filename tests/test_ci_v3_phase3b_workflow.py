"""The deployable shadow workflow bytes stay inactive, additive, bounded and advisory-only."""
from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "docs/ci_v3/phase3b/ci_v3_shadow.yml"


@pytest.fixture(scope="module")
def flow():
    return yaml.load(CANDIDATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_not_active_and_existing_public_workflow_untouched():
    assert not (ROOT / ".github/workflows/ci_v3_shadow.yml").exists()
    public = (ROOT / ".github/workflows/public_safety_and_smoke.yml").read_text(encoding="utf-8")
    assert "ci_v3" not in public and "tools.ci_v3" not in public


def test_manual_dispatch_only_protected_admission_three_parallel_workers(flow):
    assert list(flow["on"]) == ["workflow_dispatch"]
    jobs = flow["jobs"]
    assert set(jobs) == {"admission", "plan", "worker-0", "worker-1", "worker-2", "aggregate"}
    assert jobs["admission"]["environment"] == "ci-v3-shadow-admission" and "needs" not in jobs["admission"]
    for i in range(3):
        assert jobs[f"worker-{i}"]["needs"] == ["admission", "plan"]   # siblings never depend on each other
    assert jobs["aggregate"]["if"] == "always()" and set(jobs["aggregate"]["needs"]) == set(jobs) - {"aggregate"}


def test_budget_ceiling_and_least_privilege(flow):
    assert sum(int(j["timeout-minutes"]) for j in flow["jobs"].values()) == 350   # owner-proposed ceiling
    assert all(j["permissions"] == {"contents": "read", "actions": "read"} for j in flow["jobs"].values())
    assert flow["concurrency"]["cancel-in-progress"] == "false"


def test_no_retry_selection_or_secret_use():
    text = CANDIDATE.read_text(encoding="utf-8")
    assert not re.search(r"retry|rerun|continue-on-error|secrets\.|pull_request|schedule:|--deselect|-k |--lf|\bmaxfail", text, re.I)
    assert "@sha256" not in text and re.findall(r"uses: \S+@([0-9a-f]{40})", text)   # actions pinned by commit
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in re.findall(r"uses: \S+@(\S+)", text))

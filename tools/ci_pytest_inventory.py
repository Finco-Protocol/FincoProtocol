"""Opt-in pytest evidence plugin; only shadow jobs partition collected modules."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.ci_acceptance import partition_modules
from tools.ci_v3_real_contract import environment_record, phase_record, report_reason


def pytest_addoption(parser):
    group = parser.getgroup("finco-ci-evidence")
    group.addoption("--ci-inventory", default=None)
    group.addoption("--ci-shard", type=int, default=None)
    group.addoption("--ci-weights", default="tools/ci_module_weights.json")


def pytest_configure(config):
    if config.getoption("ci_shard") not in (None, 0, 1):
        raise pytest.UsageError("CI shadow shard must be 0 or 1")
    config._finco_evidence = {
        "schema": 1, "head": os.environ.get("FINCO_CI_TESTED_SHA"),
        "tree": os.environ.get("FINCO_CI_TESTED_TREE"),
        "collected": [], "selected": [], "deselected": [],
        "collection_skips": [], "collection_errors": [], "outcomes": {},
        "shard": config.getoption("ci_shard"),
        "phase_schema": 1, "phases": [], "environment": environment_record(), "collection_skip_records": [],
    }


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    evidence = config._finco_evidence
    evidence["collected"] = sorted(item.nodeid for item in items)
    shard = config.getoption("ci_shard")
    if shard is not None:
        weights = json.loads(Path(config.getoption("ci_weights")).read_text(encoding="utf-8"))
        assigned = partition_modules(evidence["collected"], weights["modules"])
        retained, removed = [], []
        for item in items:
            (retained if assigned[item.nodeid.split("::", 1)[0]] == shard else removed).append(item)
        items[:] = retained
        config.hook.pytest_deselected(items=removed)
    evidence["selected"] = sorted(item.nodeid for item in items)


def pytest_deselected(items):
    if items:
        items[0].config._finco_evidence["deselected"].extend(item.nodeid for item in items)


class Reports:
    def __init__(self, evidence):
        self.evidence = evidence

    def pytest_collectreport(self, report):
        if report.skipped:
            self.evidence["collection_skips"].append([report.nodeid, str(report.longrepr)])
            self.evidence["collection_skip_records"].append({"nodeid": report.nodeid, "reason": report_reason(report)})
        elif report.failed:
            self.evidence["collection_errors"].append([report.nodeid, str(report.longrepr)])

    def pytest_runtest_logreport(self, report):
        # Observation only: retain every phase, including passing setup/teardown.
        # Never infer phases later from duration/progress summaries.
        self.evidence["phases"].append(phase_record(report))
        if report.when == "call" or report.failed or report.skipped:
            status = report.outcome
            reason = ""
            if hasattr(report, "wasxfail"):
                status = "xpass" if report.passed else "xfail"
                reason = str(report.wasxfail)
            elif report.skipped:
                reason = str(report.longrepr)
            previous = self.evidence["outcomes"].get(report.nodeid)
            if previous is None or previous["status"] != "failed":
                self.evidence["outcomes"][report.nodeid] = {"status": status, "reason": reason}


def pytest_sessionstart(session):
    from tools.ci_v3_pytest_config import loaded_plugins
    session.config._finco_evidence["pytest_plugins"] = loaded_plugins(session.config)
    session.config.pluginmanager.register(Reports(session.config._finco_evidence), "finco-ci-reports")


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    output = session.config.getoption("ci_inventory")
    if output:
        evidence = session.config._finco_evidence
        evidence["pytest_exit"] = int(session.exitstatus)
        evidence["collection_skips"].sort()
        evidence["deselected"].sort()
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

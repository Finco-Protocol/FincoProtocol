"""Opt-in real pytest report producer. No hook changes an outcome or tolerance."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import time

import pytest

from tools.ci_v3_real_contract import environment_record, envelope, outcome
from tools.ci_v3_schema import digest, read_json, reconcile_collection, write_json


def reason(report):
    value = report.longrepr
    return str(value[2]) if isinstance(value, tuple) and len(value) == 3 else str(value or "")


class Adapter:
    """Instantiated by the trusted bootstrap; nothing is enabled on ordinary imports."""
    def __init__(self, request, destination):
        self.request, self.destination = request, Path(destination)
        self.started = time.perf_counter()
        self.full, self.selected, self.deselected = [], [], []
        self.skips, self.errors, self.phases = [], [], []
        self.raw_collection = []
        self.authorized_selection = False
        self.selection_errors = []
        self.environment = environment_record()
        self.collection_finished_ms = None
        self.collection_started_at = None
        self.collection_duration_ms = None

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionstart(self, session):
        self.collection_started_at = time.perf_counter()

    def pytest_collectreport(self, report):
        if report.skipped or report.failed:
            rec = {"nodeid": report.nodeid, "reason": reason(report)}
            (self.skips if report.skipped else self.errors).append(rec)
            self.raw_collection.append({**rec, "longrepr": str(report.longrepr), "outcome": report.outcome})

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        initial = [item.nodeid for item in items]
        yield
        self.full = sorted(initial)
        if Counter(item.nodeid for item in items) != Counter(initial) or self.selection_errors:
            self.selection_errors.append("unexpected external pytest deselection")
            raise pytest.UsageError("CI V3 rejects unexpected deselection")
        if len(set(initial)) != len(initial):
            raise pytest.UsageError("CI V3 rejects duplicate collected identities")
        if self.request["mode"] == "worker":
            collection = self.collection()
            reconcile_collection(self.request["inventory"], collection)
            modules = self.request["owned_modules"]
            kept, removed = [], []
            for item in items:
                (kept if item.nodeid.split("::", 1)[0] in modules else removed).append(item)
            items[:] = kept
            self.authorized_selection = True
            config.hook.pytest_deselected(items=removed)
            self.authorized_selection = False
        self.selected = [item.nodeid for item in items]
        self.collection_finished_ms = round((time.perf_counter() - self.started) * 1000)
        self.collection_duration_ms = round((time.perf_counter() - self.collection_started_at) * 1000)

    def pytest_deselected(self, items):
        if self.authorized_selection:
            self.deselected.extend(item.nodeid for item in items)
        elif items:
            self.selection_errors.extend(item.nodeid for item in items)

    def collection(self):
        return {"source": self.request["context"]["source"], "complete": not self.errors,
                "errors": sorted(self.errors, key=lambda x: x["nodeid"]), "nodes": self.full,
                "skips": sorted(self.skips, key=lambda x: (x["nodeid"], x["reason"]))}

    def phase(self, report):
        return {"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
                "reason": reason(report) if not report.passed else "",
                "wasxfail": str(report.wasxfail) if hasattr(report, "wasxfail") else None,
                "duration_ms": round(report.duration * 1000), "longrepr": str(report.longrepr or "")}

    @pytest.hookimpl(hookwrapper=True, trylast=True)
    def pytest_runtest_makereport(self, item, call):
        result = yield
        report = result.get_result()
        current = [p for p in self.phases if p["nodeid"] == item.nodeid] + [self.phase(report)]
        status = outcome(current, complete=False)
        properties = [(k, v) for k, v in report.user_properties if not k.startswith("ci_v3_")]
        properties.append(("ci_v3_identity", json.dumps(["node", item.nodeid], ensure_ascii=True)))
        if status["status"] in ("skipped", "xfail", "xpass"):
            properties.append(("ci_v3_reason", json.dumps(status["reason"], ensure_ascii=True)))
        report.user_properties = properties

    def pytest_runtest_logreport(self, report):
        self.phases.append(self.phase(report))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        value = envelope("ci-v3-pytest-report", mode=self.request["mode"],
            worker=self.request.get("worker"), context=self.request["context"], collection=self.collection(),
            selected=self.selected, deselected=sorted(self.deselected), phases=self.phases,
            unauthorized_deselection=self.selection_errors, raw_collection=self.raw_collection,
            pytest_exitstatus=int(session.exitstatus), environment=self.environment,
            environment_digest=digest(self.environment),
            telemetry={"collection_finished_ms": self.collection_finished_ms,
                       "collection_duration_ms": self.collection_duration_ms,
                       "session_finish_ms": round((time.perf_counter() - self.started) * 1000)})
        write_json(self.destination, value)

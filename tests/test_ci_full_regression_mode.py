"""FINCO 34 owner policy: one exact long node DEFERRED_TO_FULL, explicit STANDARD/FULL Model CI modes, exact accounting,
and a cached-but-verified F01 native image. Positive and negative controls for every piece of the mechanism."""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import check_groups  # noqa: E402
import ci_mode  # noqa: E402
import native_image_identity  # noqa: E402
import required_jobs  # noqa: E402

NPV = ("tests/test_model_react_rcux_goal_seek_targets_v1.py::"
       "test_npv_with_a_saved_valuation_policy_is_solved_in_keur_and_equals_the_legacy_route")


def _wf(name):
    data = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
    data["on"] = data.get("on", data.get(True))  # PyYAML parses the bare key `on` as True
    return data


# ── the deferred list is exactly one real node, not a known defect ────────────────────────────────────────────────────

def test_exactly_one_deferred_node_and_it_is_the_npv_parity_test():
    nodes = check_groups.known(ROOT / "tests/full_regression_nodes.txt")
    assert nodes == {NPV}
    assert NPV not in check_groups.known(ROOT / "tests/known_defects.txt")
    module = ast.parse((ROOT / NPV.split("::")[0]).read_text(encoding="utf-8"))
    names = [n.name for n in module.body if isinstance(n, ast.FunctionDef)]
    assert names.count(NPV.split("::")[1]) == 1


def test_known_defects_list_is_unchanged_at_65():
    assert len(check_groups.known(ROOT / "tests/known_defects.txt")) == 65


# ── mode decision ────────────────────────────────────────────────────────────────────────────────────────────────────

PREFIXES = ci_mode.relevant_prefixes(ROOT / "scripts/ci/full_regression_paths.txt")


@pytest.mark.parametrize("event,full_input,files,expected", [
    ("schedule", "", None, True),
    ("workflow_dispatch", "true", None, True),
    ("workflow_dispatch", "false", None, False),
    ("workflow_dispatch", "", None, False),
    ("push", "", None, False),
    ("pull_request", "", ["app/services/financial_goal_seek.py"], True),
    ("pull_request", "", ["financial_engine/valuation/model.py"], True),
    ("pull_request", "", ["tests/full_regression_nodes.txt"], True),
    ("pull_request", "", [".github/workflows/model_ci.yml"], True),
    ("pull_request", "", ["frontend/src/App.tsx", "docs/readme.md"], False),
    ("merge_group", "", ["finco_core/x.py"], True),
    ("merge_group", "", ["static/app.js"], False),
])
def test_mode_decision(event, full_input, files, expected):
    full, reason = ci_mode.decide(event, full_input, "b", "h", diff=lambda b, h: files or [], prefixes=PREFIXES)
    assert full is expected, reason


def test_unreadable_diff_or_missing_shas_fail_closed_to_full():
    def boom(b, h):
        raise RuntimeError("bad object")
    assert ci_mode.decide("pull_request", "", "b", "h", diff=boom, prefixes=PREFIXES)[0] is True
    assert ci_mode.decide("pull_request", "", None, "h", prefixes=PREFIXES)[0] is True
    assert ci_mode.decide("merge_group", "", "b", None, prefixes=PREFIXES)[0] is True


def test_prefix_matching_is_exact_for_files_and_prefix_only_for_directories():
    assert ci_mode.touched(["app/v2/router.py"], ["app/v2/router.py"]) == ["app/v2/router.py"]
    assert ci_mode.touched(["app/v2/router_extra.py"], ["app/v2/router.py"]) == []
    assert ci_mode.touched(["finco_core/a/b.py"], ["finco_core/"]) == ["finco_core/a/b.py"]


def test_the_deferred_test_and_its_production_path_are_relevant():
    for path in (NPV.split("::")[0], "app/services/financial_goal_seek.py", "app/v2/react_goal_seek_targets.py",
                 "financial_engine/valuation/model.py", "scripts/ci/check_groups.py"):
        assert ci_mode.touched([path], PREFIXES), path


# ── required aggregate ───────────────────────────────────────────────────────────────────────────────────────────────

def _needs(full, overrides=None):
    needs = {name: {"result": "success", "outputs": {}} for name in required_jobs.EXPECTED}
    needs["mode"]["outputs"] = {"full": "true" if full else "false"}
    if not full:
        needs["full-regression"]["result"] = "skipped"
    for name, result in (overrides or {}).items():
        if result is None:
            needs.pop(name)
        else:
            needs[name]["result"] = result
    return needs


def test_required_positive_standard_and_full():
    assert required_jobs.evaluate(_needs(False)) == []
    assert required_jobs.evaluate(_needs(True)) == []


@pytest.mark.parametrize("full,overrides", [
    (True, {"full-regression": "skipped"}),
    (True, {"full-regression": "cancelled"}),
    (True, {"full-regression": "failure"}),
    (True, {"full-regression": None}),
    (False, {"full-regression": "success"}),
    (False, {"finance": "cancelled"}),
    (False, {"tests": "failure"}),
    (False, {"mode": "failure"}),
    (False, {"static": None}),
])
def test_required_negatives(full, overrides):
    assert required_jobs.evaluate(_needs(full, overrides))


def test_required_rejects_missing_or_bogus_mode_output():
    needs = _needs(False)
    needs["mode"]["outputs"] = {}
    assert required_jobs.evaluate(needs)
    needs["mode"]["outputs"] = {"full": "maybe"}
    assert required_jobs.evaluate(needs)


# ── accounting (check_groups) ────────────────────────────────────────────────────────────────────────────────────────

KNOWN = "tests/test_k.py::test_known"
DEF = "tests/test_d.py::test_deferred"
NODES = ["tests/test_a.py::test_1", "tests/test_a.py::test_2", "tests/test_b.py::test_3", KNOWN, DEF]


def _digest(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def _junit(path, ids, outcome=None):
    cases = []
    for n in ids:
        cls, name = check_groups.as_junit(n)
        inner = "<%s/>" % outcome if outcome else ""
        cases.append('<testcase classname="%s" name="%s">%s</testcase>' % (cls, name, inner))
    path.write_text("<testsuites><testsuite>%s</testsuite></testsuites>" % "".join(cases))


def _fixture(tmp_path, groups=(("tests/test_a.py::test_1", "tests/test_a.py::test_2"), ("tests/test_b.py::test_3",)),
             full=None, full_outcome=None, collected=NODES, listed=(KNOWN, DEF)):
    root = tmp_path / "groups"
    for i, sel in enumerate(groups, 1):
        d = root / ("tests-%d" % i)
        d.mkdir(parents=True)
        (d / ("counts-%d.json" % i)).write_text(json.dumps(dict(
            collected=len(collected), collected_digest=_digest(collected), selected=list(sel), listed_present=list(listed))))
        _junit(d / ("junit-%d.xml" % i), sel)
    if full is not None:
        d = root / "full-regression"
        d.mkdir(parents=True)
        (d / "counts-full.json").write_text(json.dumps(dict(
            collected=len(collected), collected_digest=_digest(collected), selected=list(full), listed_present=list(listed))))
        _junit(d / "junit-full.xml", full, full_outcome)
    return root


def _check(root, groups=2, full=False):
    return check_groups.check(str(root), groups, {KNOWN}, frozenset({DEF}), full)


def test_accounting_positive_standard(tmp_path, capsys):
    assert _check(_fixture(tmp_path)) == []
    out = capsys.readouterr().out
    assert "5 collected = 3 executed + 1 deferred to FULL + 1 known defects" in out
    assert "DEFERRED_TO_FULL (not run in this mode): " + DEF in out


def test_accounting_positive_full(tmp_path, capsys):
    assert _check(_fixture(tmp_path, full=[DEF]), full=True) == []
    out = capsys.readouterr().out
    assert "5 collected = 4 executed + 0 deferred to FULL + 1 known defects" in out
    assert "FULL executed and passed: " + DEF in out


@pytest.mark.parametrize("kwargs,full", [
    (dict(listed=(KNOWN,)), False),                                                     # deferred node not in collection
    (dict(listed=(DEF,)), False),                                                       # known defect not in collection
    (dict(groups=(("tests/test_a.py::test_1", "tests/test_a.py::test_2", DEF), ("tests/test_b.py::test_3",))), False),
    (dict(groups=(("tests/test_a.py::test_1",), ("tests/test_b.py::test_3",))), False),  # extra exclusion: a node lost
    (dict(groups=(("tests/test_a.py::test_1", "tests/test_a.py::test_2"), ("tests/test_a.py::test_2", "tests/test_b.py::test_3"))), False),
    (dict(), True),                                                                     # FULL mode, full job absent
    (dict(full=["tests/test_a.py::test_1"]), True),                                     # full job ran the wrong node
    (dict(full=[DEF], full_outcome="failure"), True),
    (dict(full=[DEF], full_outcome="skipped"), True),
    (dict(full=[DEF], full_outcome="error"), True),
    (dict(full=[DEF]), False),                                                          # STANDARD but FULL evidence present
])
def test_accounting_negatives(tmp_path, kwargs, full):
    assert _check(_fixture(tmp_path, **kwargs), full=full)


def test_accounting_rejects_a_node_listed_as_both_known_and_deferred(tmp_path):
    root = _fixture(tmp_path)
    assert check_groups.check(str(root), 2, {KNOWN, DEF}, frozenset({DEF}), False)


# ── workflow wiring ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_model_ci_modes_and_jobs_are_wired():
    wf = _wf("model_ci.yml")
    on = wf["on"]
    assert on["schedule"], "the nightly schedule must exist (FULL)"
    for trigger in ("workflow_dispatch", "workflow_call"):
        spec = on[trigger]["inputs"]["full_regression"]
        assert spec["type"] == "boolean" and spec["default"] is False
    jobs = wf["jobs"]
    assert set(jobs) == {"mode", "static", "boot-smoke", "finance", "tests", "acceptance", "full-regression", "required"}
    full_job = jobs["full-regression"]
    assert full_job["needs"] == "mode" and full_job["if"] == "needs.mode.outputs.full == 'true'"
    run = "\n".join(s.get("run", "") for s in full_job["steps"])
    assert "--file tests/full_regression_nodes.txt" in run and "junit_check.py" in run and "--exact" in run
    assert any(s.get("env", {}).get("FINCO_CI_STRICT_SKIPS") == "1" for s in full_job["steps"])
    tests_run = "\n".join(s.get("run", "") for s in jobs["tests"]["steps"])
    assert "known_defects.py --deselect --file tests/full_regression_nodes.txt" in tests_run
    required = jobs["required"]
    assert set(required["needs"]) == required_jobs.EXPECTED
    req_run = "\n".join(s.get("run", "") for s in required["steps"])
    assert "required_jobs.py" in req_run and "--deferred tests/full_regression_nodes.txt" in req_run
    assert "set -o pipefail" in req_run
    mode_run = "\n".join(s.get("run", "") for s in jobs["mode"]["steps"])
    assert "ci_mode.py" in mode_run and "set -o pipefail" in mode_run


def test_pip_network_resilience_is_bounded_and_global():
    env = _wf("model_ci.yml")["env"]
    assert env["PIP_DEFAULT_TIMEOUT"] == "60" and env["PIP_RETRIES"] == "10"


def test_no_continue_on_error_and_unchanged_timeouts():
    wf = _wf("model_ci.yml")
    text = (ROOT / ".github/workflows/model_ci.yml").read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    jobs = wf["jobs"]
    assert jobs["finance"]["timeout-minutes"] == 45 and jobs["tests"]["timeout-minutes"] == 40
    assert jobs["static"]["timeout-minutes"] == 20 and jobs["acceptance"]["timeout-minutes"] == 40
    assert jobs["full-regression"]["timeout-minutes"] == 60


def _release_gate_problems(wf):
    jobs = wf.get("jobs", {})
    out = []
    model = jobs.get("model-ci", {})
    if model.get("uses") != "./.github/workflows/model_ci.yml":
        out.append("model-ci does not call Model CI")
    if (model.get("with") or {}).get("full_regression") is not True:
        out.append("model-ci is not called in FULL mode")
    approve = jobs.get("approve", {})
    needs = approve.get("needs")
    if needs != "model-ci" and needs != ["model-ci"]:
        out.append("approve does not depend on model-ci")
    if approve.get("environment") != "production":
        out.append("approve is not behind the production environment")
    if any("continue-on-error" in j or j.get("if") for j in jobs.values()):
        out.append("a release job can be bypassed (continue-on-error / if)")
    return out


def test_release_gate_runs_full_and_approval_depends_on_it():
    assert _release_gate_problems(_wf("release_gate.yml")) == []


@pytest.mark.parametrize("mutate", [
    lambda wf: wf["jobs"]["model-ci"]["with"].update(full_regression=False),
    lambda wf: wf["jobs"]["model-ci"].pop("with"),
    lambda wf: wf["jobs"]["approve"].update(needs=[]),
    lambda wf: wf["jobs"]["approve"].update({"if": "always()"}),
    lambda wf: wf["jobs"]["model-ci"].update({"continue-on-error": True}),
])
def test_release_gate_negatives_are_rejected(mutate):
    wf = _wf("release_gate.yml")
    mutate(wf)
    assert _release_gate_problems(wf)


def test_finance_keeps_its_acceptance_and_builds_the_unchanged_image_with_a_verified_cache():
    steps = _wf("model_ci.yml")["jobs"]["finance"]["steps"]
    names = [s.get("name", s.get("uses", "")) for s in steps]
    build = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("docker/build-push-action@"))
    ident = next(i for i, n in enumerate(names) if n.startswith("Native image identity"))
    native = next(i for i, n in enumerate(names) if n.startswith("F01 twenty native"))
    assert build < ident < native
    w = steps[build]["with"]
    assert w["file"] == "docs/ci_v3/phase4/runtime/Dockerfile" and w["tags"] == "finval-f01-native" and w["load"] is True
    assert w["cache-from"] == "type=gha,scope=finval-f01-native" and w["cache-to"].startswith("type=gha,scope=finval-f01-native")
    for s in steps:
        if "uses" in s:
            assert "@" in s["uses"] and len(s["uses"].split("@")[1]) == 40, s["uses"]   # every action pinned by commit SHA
    text = "\n".join(s.get("run", "") for s in steps)
    assert "--exact 4" in text and "--exact 20" in text and "--network none" in text
    assert "native_image_identity.py" in text and "fin_v2_3_oracle_workbook.py" in text
    assert "docker build " not in text   # one build path only (the cached, identity-checked one)


# requirements-ci-tests.txt was changed on main by the CI normalization (#476, 0788da50) without updating this historical
# manifest; that pre-existing staleness is recorded, not repinned here. Every other approved native input, the Dockerfile
# and python.lock above all, must be byte-identical to the approved record (this PR changes none of them).
_STALE_ON_MAIN = {"requirements-ci-tests.txt"}


def test_the_native_dockerfile_and_its_approved_inputs_are_unchanged():
    recorded = json.loads((ROOT / "docs/ci_v3/phase4/runtime/inputs.json").read_text(encoding="utf-8"))
    assert {"docs/ci_v3/phase4/runtime/Dockerfile", "docs/ci_v3/phase4/runtime/python.lock"} <= set(recorded)
    for path, digest in recorded.items():
        if path in _STALE_ON_MAIN:
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


# ── native image identity ────────────────────────────────────────────────────────────────────────────────────────────

def _image(tmp_path, **override):
    img = tmp_path / "img"
    (img / "frontend").mkdir(parents=True)
    pkg = {n: hashlib.sha256((ROOT / "frontend" / n).read_bytes()).hexdigest() for n in ("package.json", "package-lock.json")}
    pkg.update(override.get("identity", {}))
    (img / "frontend/identity.json").write_text(json.dumps(pkg))
    (img / "resolved-system.txt").write_text(override.get("system", native_image_identity.GCC13 + "\npython3.12=3.12.3-1\n"))
    (img / "os-release.txt").write_text(override.get("os", 'PRETTY_NAME="Ubuntu 24.04.3 LTS"\n'))
    (img / "python-version.txt").write_text(override.get("py", "Python 3.12.3 (main)\n"))
    lock = (ROOT / "docs/ci_v3/phase4/runtime/python.lock").read_text().splitlines()
    frozen = [l.split("#")[0].split(";")[0].strip().replace("-", "_") for l in lock if "==" in l]   # pip freeze spelling may differ
    frozen = override.get("frozen", frozen)
    (img / "resolved-python.txt").write_text("\n".join(frozen + ["pip==24.0"]) + "\n")
    return img


def test_native_identity_positive(tmp_path):
    assert native_image_identity.problems(_image(tmp_path), ROOT) == []


@pytest.mark.parametrize("override", [
    dict(identity={"package-lock.json": "0" * 64}),
    dict(system="gcc-13=13.2.0-1\n"),
    dict(os='PRETTY_NAME="Ubuntu 22.04"\n'),
    dict(py="Python 3.11.9\n"),
    dict(frozen=["anyio==0.0.1"]),
])
def test_native_identity_negatives(tmp_path, override):
    assert native_image_identity.problems(_image(tmp_path, **override), ROOT)

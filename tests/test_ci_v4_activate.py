"""CI V4 PR-B: trusted-base activation of exact-node sharding in the required PR gate.

Real pytest processes on a synthetic subject repository; the controller is THIS repository's tools (the trusted tree). Proves: the trusted
base alone decides (a PR head that enables splitting does not split its own gate), the selection is never changed, the plan is re-sealed with
provenance, shards and the gate use the materialized TRUSTED plugin, and every tamper fails closed.
"""
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tools import ci_v4_activate as AC
from tools import ci_v4_aggregate as AG
from tools import ci_v4_nodes as N
from tools import ci_v4_schedule as S
from tools.ci_v4_select import policy_digest

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
WORKERS = {**POLICY, "workers": {**POLICY["workers"], "risk": {"max": 3, "min_module_seconds_per_extra_worker": 1, "fixed_overhead_seconds_per_worker": 10}}}
MODULE, PLAIN = "tests/test_synth.py", "tests/test_plain.py"
TRUSTED = "a" * 40
SYNTH = '''
import pytest

@pytest.mark.parametrize("p", ["a", "b/c.py", "x::y", "f[g]"])
def test_param(p):
    assert p

class TestKlass:
    def test_method(self):
        assert True

def test_one():
    assert True
'''


def _policy(enabled):
    return {"schema": S.NODE_SPLIT_POLICY_SCHEMA, "enabled_in_required_pr_gate": enabled, "target_unit_seconds": 60, "max_parts_per_module": 3,
            "modules": {MODULE: {"verdict": "SPLIT_SAFE", "isolation_proof": "synthetic, no shared state", "granularity": "node"}}}


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


@pytest.fixture()
def subject(tmp_path, monkeypatch):
    root = tmp_path / "subject"
    (root / "tests").mkdir(parents=True)
    (root / MODULE).write_text(SYNTH)
    (root / PLAIN).write_text("def test_plain():\n    assert True\n")
    (root / "tests/__init__.py").write_text("")
    (root / "pytest.ini").write_text("[pytest]\n")
    # The PR head's OWN policy says "enabled": it must never be read for its own gate.
    (root / "docs/ci_v4").mkdir(parents=True)
    (root / "docs/ci_v4/node_split_policy.json").write_text(json.dumps(_policy(True)))
    _git(root, "init", "-q")
    for args in (("add", "-A"), ("commit", "-qm", "subject")):
        _git(root, "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", *args)
    for k in list(os.environ):
        if k.startswith("FINCO_CI_V4_NODE_"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return root


def _sealed(subject, modules=(MODULE, PLAIN), policy=WORKERS):
    mods = sorted(modules)
    plan = {"schema": "FINCO_CI_V4_PLAN_V1", "tier": "risk", "tested_sha": _git(subject, "rev-parse", "HEAD"),
            "tested_tree": _git(subject, "rev-parse", "HEAD^{tree}"), "policy_digest": policy_digest(policy), "pytest_modules": mods,
            "no_skip_modules": mods, "suites": ["risk_security"], "rule_ids": ["application_surface"], "needs_browser": True,
            "needs_native_docker": False, "triggers": [], "not_selected": {"count": 7, "label": "NOT SELECTED (not PASS)"}}
    plan["schedule"] = S.plan_shards(mods, {MODULE: 120.0, PLAIN: 1.0}, "risk", policy)
    plan["digest"] = S.plan_digest(plan)
    return plan


def _apply(subject, tmp_path, plan, enabled=True, weights=None):
    planfile = tmp_path / "ci-v4-plan.json"
    planfile.write_text(json.dumps(plan))
    ev = tmp_path / "evidence"; ev.mkdir(exist_ok=True)
    pol = _policy(enabled)
    orig_w, orig_nw = S.load_weights, S.load_node_weights
    ids_w = weights or {}
    S.load_weights, S.load_node_weights = (lambda path=None: {MODULE: 120.0, PLAIN: 1.0}), (lambda path=None: ids_w)
    try:
        rec = AC.apply(planfile, subject, tmp_path / "plugin", ev, split_policy=pol, policy=WORKERS, trusted_sha=TRUSTED)
    finally:
        S.load_weights, S.load_node_weights = orig_w, orig_nw
    return rec, json.loads(planfile.read_text()), ev


@pytest.fixture()
def activated(subject, tmp_path):
    plan = _sealed(subject)
    ids = [MODULE + "::test_param[" + p + "]" for p in ("a", "b/c.py", "x::y", "f[g]")] + [MODULE + "::TestKlass::test_method", MODULE + "::test_one"]
    rec, node_plan, ev = _apply(subject, tmp_path, plan, weights={n: 30.0 for n in ids})
    return {"subject": subject, "tmp": tmp_path, "original": plan, "plan": node_plan, "record": rec, "evidence": ev}


def _run_all(a, plan=None):
    plan = plan or a["plan"]
    pf = a["tmp"] / "plan-run.json"; pf.write_text(json.dumps(plan))
    out = a["tmp"] / "shards"
    rcs = [AC.shard(pf, i, a["subject"], a["tmp"] / "w", out / ("s%d" % i), TRUSTED) for i in range(len(plan["schedule"]["shards"]))]
    return pf, out, rcs


# ── bootstrap: the trusted base alone decides ───────────────────────────────────────────────────────────────────────────────────────────

def test_base_false_head_true_keeps_the_sealed_module_plan_byte_for_byte(subject, tmp_path):
    """PR-B on itself: its base says false, its head says true -> the required gate keeps the module plan."""
    plan = _sealed(subject)
    before = json.dumps(plan)
    rec, after, ev = _apply(subject, tmp_path, plan, enabled=False)
    assert rec["decision"] == "module_plan" and "disabled" in rec["reason"]
    assert json.dumps(after) == before and "node_split" not in after
    assert json.loads((subject / "docs/ci_v4/node_split_policy.json").read_text())["enabled_in_required_pr_gate"] is True  # ignored
    assert not (ev / "node-inventory.json").exists()                                                              # no collection overhead


def test_trusted_true_without_an_eligible_selected_module_keeps_the_plan(subject, tmp_path):
    plan = _sealed(subject, modules=(PLAIN,))
    before = json.dumps(plan)
    rec, after, _ = _apply(subject, tmp_path, plan)
    assert rec["decision"] == "module_plan" and json.dumps(after) == before


def test_trusted_true_splits_only_the_allowlisted_selected_module_and_keeps_the_selection(activated):
    orig, plan, rec = activated["original"], activated["plan"], activated["record"]
    assert rec["decision"] == "node_plan" and set(plan["node_split"]["modules"]) == {MODULE}
    for key in orig:
        if key not in ("schedule", "digest"):
            assert plan[key] == orig[key], key                                                       # selection, suites, F01, NOT SELECTED intact
    act = plan["node_split"]["activation"]
    assert act["trusted_base_sha"] == TRUSTED and act["original_plan_digest"] == orig["digest"] and act["plugin"] == AC.TRUSTED_PLUGIN
    assert plan["digest"] == S.plan_digest(plan)
    AC.check_invariants(orig, plan)
    assert (activated["evidence"] / "ci-v4-module-plan.json").is_file() and (activated["evidence"] / "node-inventory.json").is_file()


def test_decide_reads_nothing_but_the_trusted_policy():
    plan = {"pytest_modules": ["tests/test_rcux_governance.py", "tests/test_x.py"]}
    assert AC.decide(plan, _policy(False))["decision"] == "module_plan"
    real = S.load_node_split_policy()
    got = AC.decide(plan, real)
    assert got["decision"] == "collect" and got["eligible"] == ["tests/test_rcux_governance.py"]
    # tests/test_u1_scope.py joined the reviewed split-safe allowlist (CI V4 shard-2 fix); u2 (still NOT_BENEFICIAL) and the finance modules do not.
    got = AC.decide({"pytest_modules": ["tests/test_u1_scope.py", "tests/test_goal_seek_v1.py"]}, real)
    assert got["decision"] == "collect" and got["eligible"] == ["tests/test_u1_scope.py"]
    assert AC.decide({"pytest_modules": ["tests/test_u2_scope.py", "tests/test_goal_seek_v1.py"]}, real)["decision"] == "module_plan"


# ── sealing / invariants ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tamper", ["digest", "policy", "sha", "already_node"])
def test_activation_refuses_an_unsealed_foreign_or_mismatched_plan(subject, tmp_path, tamper):
    plan = _sealed(subject)
    if tamper == "digest":
        plan["pytest_modules"] = [PLAIN]                                                              # selection altered after sealing
    elif tamper == "policy":
        plan["policy_digest"] = "0" * 64; plan["digest"] = S.plan_digest(plan)                         # selected under another policy
    elif tamper == "sha":
        plan["tested_sha"] = "b" * 40; plan["digest"] = S.plan_digest(plan)                            # not the checked-out head
    else:
        plan["node_split"] = {}; plan["digest"] = S.plan_digest(plan)
    with pytest.raises(AC.ActivationError):
        _apply(subject, tmp_path, plan)


@pytest.mark.parametrize("tamper", ["drop_module", "drop_node", "dup_node", "change_suite", "shards_mismatch"])
def test_invariants_refuse_any_selection_or_partition_change(activated, tamper):
    plan = copy.deepcopy(activated["plan"])
    units = plan["schedule"]["units"]
    if tamper == "drop_module":
        plan["pytest_modules"] = [MODULE]
    elif tamper == "drop_node":
        next(u for s in units for u in s if u["kind"] == "nodes")["node_ids"].pop()
    elif tamper == "dup_node":
        us = [u for s in units for u in s if u["kind"] == "nodes"]
        us[1]["node_ids"].append(us[0]["node_ids"][0])
    elif tamper == "change_suite":
        plan["needs_browser"] = False                                                                 # F01 silently dropped
    else:
        plan["schedule"]["shards"][0] = [PLAIN] if MODULE in plan["schedule"]["shards"][0] else [MODULE]
    plan["digest"] = S.plan_digest(plan)
    with pytest.raises(AC.ActivationError):
        AC.check_invariants(activated["original"], plan)


# ── trusted execution and independent verification ─────────────────────────────────────────────────────────────────────────────────────

def test_end_to_end_trusted_shards_and_independent_gate_verification_pass(activated):
    pf, out, rcs = _run_all(activated)
    assert rcs and all(rc == 0 for rc in rcs)
    for rec in (json.loads(p.read_text()) for p in out.glob("**/shard-*.json")):
        assert rec["executor"]["plugin"] == AC.TRUSTED_PLUGIN and rec["executor"]["trusted_base_sha"] == TRUSTED
    res = AC.verify(pf, activated["subject"], out, activated["tmp"] / "v", activated["tmp"] / "result", TRUSTED)
    assert res["verdict"] == "PASS", res["problems"]
    assert res["executed_nodes"] == 7 and res["verifier"]["trusted_base_sha"] == TRUSTED


def test_the_subjects_own_plugin_is_never_used(activated):
    """A PR head that ships a lying tools/ci_v4_nodes.py does not measure itself: the trusted copy runs under a unique module name."""
    (activated["subject"] / "tools").mkdir()
    (activated["subject"] / "tools/__init__.py").write_text("")
    (activated["subject"] / "tools/ci_v4_nodes.py").write_text("raise SystemExit('head plugin imported')\n")
    _git(activated["subject"], "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", "add", "-A")
    _git(activated["subject"], "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", "commit", "-qm", "lying plugin")
    plan = _sealed(activated["subject"])
    ids = [MODULE + "::test_param[" + p + "]" for p in ("a", "b/c.py", "x::y", "f[g]")] + [MODULE + "::TestKlass::test_method", MODULE + "::test_one"]
    tmp = activated["tmp"] / "lying"; tmp.mkdir()
    _, node_plan, _ = _apply(activated["subject"], tmp, plan, weights={n: 30.0 for n in ids})
    a = dict(activated, plan=node_plan, tmp=tmp)
    pf, out, rcs = _run_all(a)
    assert all(rc == 0 for rc in rcs)
    assert AC.verify(pf, a["subject"], out, tmp / "v", tmp / "r", TRUSTED)["verdict"] == "PASS"


@pytest.mark.parametrize("tamper", ["drop_evidence_node", "drop_shard", "foreign_trusted", "plugin_bytes"])
def test_gate_verification_fails_closed(activated, tamper):
    pf, out, rcs = _run_all(activated)
    trusted_sha = TRUSTED
    if tamper == "drop_evidence_node":
        f = next(out.glob("**/nodes-shard-0.json")); ev = json.loads(f.read_text())
        ev["nodes"].pop(next(n for n in ev["nodes"] if n.startswith(MODULE))); f.write_text(json.dumps(ev))
    elif tamper == "drop_shard":
        for p in next(out.glob("s0")).iterdir():
            p.unlink()
    elif tamper == "foreign_trusted":
        trusted_sha = "c" * 40                                                                        # a different base than the activator
    if tamper == "plugin_bytes":
        fake = activated["tmp"] / "fake-trusted"
        (fake / "tools").mkdir(parents=True)
        for name in ("ci_v4_nodes.py", "ci_v3_pytest_config.py"):
            (fake / "tools" / name).write_text((ROOT / "tools" / name).read_text() + ("\n# drift\n" if name == "ci_v4_nodes.py" else ""))
        with pytest.raises(AC.ActivationError):
            AC.verify(pf, activated["subject"], out, activated["tmp"] / "v", activated["tmp"] / "r", TRUSTED, trusted=fake)
        return
    if tamper == "foreign_trusted":
        with pytest.raises(AC.ActivationError):
            AC.verify(pf, activated["subject"], out, activated["tmp"] / "v", activated["tmp"] / "r", trusted_sha)
        return
    res = AC.verify(pf, activated["subject"], out, activated["tmp"] / "v", activated["tmp"] / "r", trusted_sha)
    assert res["verdict"] == "FAIL" and res["problems"]


def test_shard_refuses_spoofed_index_module_plan_or_moved_head(activated, tmp_path):
    pf = tmp_path / "p.json"; pf.write_text(json.dumps(activated["plan"]))
    with pytest.raises(AC.ActivationError):
        AC.shard(pf, 99, activated["subject"], tmp_path / "w", tmp_path / "o", TRUSTED)
    mp = tmp_path / "m.json"; mp.write_text(json.dumps(activated["original"]))
    with pytest.raises(AC.ActivationError):
        AC.shard(mp, 0, activated["subject"], tmp_path / "w", tmp_path / "o", TRUSTED)
    with pytest.raises(AC.ActivationError):
        AC.verify(mp, activated["subject"], tmp_path, tmp_path / "w", tmp_path / "o", TRUSTED)
    (activated["subject"] / PLAIN).write_text("def test_plain():\n    assert True\n\ndef test_new():\n    pass\n")
    _git(activated["subject"], "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", "commit", "-qam", "moved")
    with pytest.raises(AC.ActivationError):
        AC.shard(pf, 0, activated["subject"], tmp_path / "w", tmp_path / "o", TRUSTED)


def test_node_plan_without_independent_inventory_is_refused_by_the_aggregator(activated):
    pf, out, _ = _run_all(activated)
    records = [json.loads(p.read_text()) for p in sorted(out.glob("**/shard-*.json"))]
    evidence = {int(p.name[12:-5]): json.loads(p.read_text()) for p in out.glob("**/nodes-shard-*.json")}
    res = AG.aggregate(activated["plan"], records, sorted(out.glob("**/*.xml")), node_evidence=evidence, inventory=None)
    assert res["verdict"] == "FAIL" and any("independent re-collection" in p for p in res["problems"])


# ── the required workflow wiring ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _wf():
    return yaml.safe_load((ROOT / ".github/workflows/ci_v4_pr.yml").read_text())


def _run_text(job):
    return "\n".join(s.get("run", "") for s in job["steps"])


def test_required_workflow_keeps_its_check_name_and_trusted_selection():
    wf = _wf()
    assert wf["jobs"]["gate"]["name"] == "CI V4 gate"
    plan = _run_text(wf["jobs"]["plan"])
    assert "(cd \"$SEL\" && python -m tools.ci_v4_select" in plan and "SEL=trusted" in plan
    assert "(cd trusted && python -m tools.ci_v4_activate decide" in plan and "(cd trusted && python -m tools.ci_v4_activate apply" in plan
    assert "subject/docs/ci_v4/node_split_policy.json" not in plan                                      # the head's split policy is never read


def test_required_workflow_runs_node_plans_only_with_trusted_tools_and_independent_verification():
    wf = _wf()
    shards, gate = _run_text(wf["jobs"]["shards"]), _run_text(wf["jobs"]["gate"])
    assert 'git archive --format=tar "$BASE_SHA" tools docs/ci_v4' in shards and "python -m tools.ci_v4_activate shard" in shards
    assert "python -m tools.ci_v4_shard --plan" in shards                                                # module plans: unchanged path
    assert "(cd trusted && python -m tools.ci_v4_activate verify" in gate
    assert 'test "$IS_NODE" = "$NODE_SPLIT"' in gate and "FAIL CLOSED" in gate                          # spoofed output / missing verifier
    for job in ("plan", "shards", "gate"):
        versions = [s["with"]["python-version"] for s in wf["jobs"][job]["steps"] if "setup-python" in s.get("uses", "")]
        assert versions == ["3.12.16"], (job, versions)                                                 # one interpreter for the profile


def test_shadow_workflow_is_labelled_not_required_and_cannot_be_the_gate():
    wf = yaml.safe_load((ROOT / ".github/workflows/ci_v4_shadow_split.yml").read_text())
    assert "not required" in wf["name"] and wf["permissions"] == {"contents": "read"}
    assert all(j.get("name", "") != "CI V4 gate" for j in wf["jobs"].values())
    assert "NOT REQUIRED" in wf["jobs"]["shadow-verify"]["name"]


# ── stall forensics on the TRUSTED node-plan executor (the module-plan shard has its own, tools/ci_v4_shard.py) ───────────────────────────────

def test_node_plan_shard_names_the_running_node_dumps_its_stack_and_keeps_failures_failing(subject, tmp_path, capfd):
    """A hung node of a NODE plan is attributable from the job log: its id is printed when it STARTS, the faulthandler dump (written to a pre-capture
    duplicate of stderr) shows the concrete frame, a failing node is named FAILED, and the shard exit code and JUnit remain pytest's own."""
    (subject / MODULE).write_text(SYNTH + "\nimport time\n\n\ndef _stuck_here(seconds):\n    time.sleep(seconds)\n\n\ndef test_slow():\n    _stuck_here(5)\n\n\n"
                                  "def test_boom():\n    assert 1 == 2\n")
    for args in (("add", "-A"), ("commit", "-qm", "slow and failing nodes")):
        _git(subject, "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", *args)
    plan = _sealed(subject)
    ids = [MODULE + "::test_param[" + p + "]" for p in ("a", "b/c.py", "x::y", "f[g]")] + [MODULE + "::TestKlass::test_method", MODULE + "::test_one",
                                                                                           MODULE + "::test_slow", MODULE + "::test_boom"]
    rec, node_plan, ev = _apply(subject, tmp_path, plan, weights={n: 30.0 for n in ids})
    assert rec["decision"] == "node_plan"
    pf = tmp_path / "plan-run.json"
    pf.write_text(json.dumps(node_plan))
    out = tmp_path / "shards"
    rcs = {}
    for i in range(len(node_plan["schedule"]["shards"])):
        rcs[i] = AC.shard(pf, i, subject, tmp_path / "w", out / ("s%d" % i), TRUSTED, dump_after_s=2)
    log = capfd.readouterr()
    text = log.out + log.err
    owner = [i for i, units in enumerate(node_plan["schedule"]["units"]) for u in units if u["kind"] == "nodes" and MODULE + "::test_slow" in u["node_ids"]]
    assert owner and len(owner) == 1
    assert MODULE + "::test_slow" in text and "stall dump" in text and "in _stuck_here" in text
    assert text.index(MODULE + "::test_slow") < text.index("stall dump")                 # the node id is already in the log when the stack is dumped
    assert MODULE + "::test_boom FAILED" in text
    boom_owner = [i for i, units in enumerate(node_plan["schedule"]["units"]) for u in units if u["kind"] == "nodes" and MODULE + "::test_boom" in u["node_ids"]]
    assert all(rcs[i] == 1 for i in boom_owner) and any(rc == 1 for rc in rcs.values())               # a failure is never turned into success
    rec0 = json.loads((out / ("s%d" % boom_owner[0]) / ("shard-%d.json" % boom_owner[0])).read_text())
    assert rec0["pytest_exit"] == 1 and rec0["executor"]["trusted_base_sha"] == TRUSTED


def test_node_plan_shard_runs_pytest_through_the_diagnostic_wrapper_without_q():
    """Static contract of the executor argv: the stdlib wrapper (never a pytest option, see hosted run 43590299354), -v and no -q."""
    import inspect
    src = inspect.getsource(AC.shard)
    assert "pytest_command(" in src and "DIAGNOSTIC_ARGS" in src and '"-q"' not in src and '"-m", "pytest"' not in src

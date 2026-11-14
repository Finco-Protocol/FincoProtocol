"""CI V4 node splitting: exact pytest node identity, deterministic partition, shard execution and independent aggregation.

Everything below runs REAL pytest processes (collection, assigned execution, JUnit) on a synthetic module in a private git repository and the
real ``tools.ci_v4_shard`` / ``tools.ci_v4_aggregate`` code; the negatives tamper with real artifacts. Nothing mocks git or pytest.
"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import ci_v4_aggregate as A
from tools import ci_v4_nodes as N
from tools import ci_v4_schedule as S
from tools import ci_v4_shard as SH

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
MODULE = "tests/test_synth.py"
SYNTH = r'''
import os
import pytest

@pytest.fixture(scope="module")
def res():
    d = os.environ["SYNTH_MARKERS"]
    open(os.path.join(d, "setup-%d" % os.getpid()), "w").close()
    yield
    open(os.path.join(d, "teardown-%d" % os.getpid()), "w").close()

@pytest.mark.parametrize("p", ["a", "b/c.py", "d e", "x::y", "f[g]"])
def test_param(res, p):
    assert p

class TestKlass:
    def test_method(self, res):
        assert True

def test_plain():
    assert True
'''
SPLIT_POLICY = {"schema": S.NODE_SPLIT_POLICY_SCHEMA, "enabled_in_required_pr_gate": False, "target_unit_seconds": 60, "max_parts_per_module": 3,
                "modules": {MODULE: {"verdict": "SPLIT_SAFE", "isolation_proof": "synthetic: module fixture per process, no shared state", "granularity": "node"}}}
WORKERS = {**POLICY, "workers": {**POLICY["workers"], "risk": {"max": 3, "min_module_seconds_per_extra_worker": 1, "fixed_overhead_seconds_per_worker": 10}}}


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def _env(markers):
    env = dict(os.environ, PYTHONPATH=str(ROOT), SYNTH_MARKERS=str(markers), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for k in (N.ENV_COLLECT, N.ENV_ASSIGN, N.ENV_EVIDENCE):
        env.pop(k, None)
    return env


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / MODULE).write_text(SYNTH)
    (root / "tests/__init__.py").write_text("")
    (root / "pytest.ini").write_text("[pytest]\n")
    _git(root, "init", "-q")
    _git(root, "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", "add", "-A")
    _git(root, "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", "commit", "-qm", "synthetic")
    markers = tmp_path / "markers"; markers.mkdir()
    for k, v in _env(markers).items():
        monkeypatch.setenv(k, v)
    for k in (N.ENV_COLLECT, N.ENV_ASSIGN, N.ENV_EVIDENCE):
        monkeypatch.delenv(k, raising=False)
    return root, markers


def _plan(root, inventory, node_weights=None):
    ids = inventory["modules"][MODULE]["node_ids"]
    base = {"schema": "FINCO_CI_V4_PLAN_V1", "tier": "risk", "tested_sha": inventory["tested_sha"], "tested_tree": inventory["tested_tree"],
            "pytest_modules": [MODULE], "no_skip_modules": [MODULE], "rule_ids": ["test"], "triggers": [],
            "not_selected": {"count": 0, "label": "NOT SELECTED (not PASS)"}}
    base["schedule"] = S.plan_shards([MODULE], {MODULE: 30.0}, "risk", WORKERS)
    base["digest"] = S.plan_digest(base)
    weights = node_weights or {n: 30.0 for n in ids}
    return S.apply_node_split(base, inventory, SPLIT_POLICY, {MODULE: 30.0}, weights, WORKERS, shadow=True)


def _run_shards(root, plan, out):
    planfile = out / "plan.json"
    planfile.write_text(json.dumps(plan))
    rcs = []
    for i in range(len(plan["schedule"]["shards"])):
        rcs.append(subprocess.call([sys.executable, "-m", "tools.ci_v4_shard", "--plan", str(planfile), "--index", str(i),
                                    "--output", str(out / ("s%d" % i))], cwd=root, stdout=subprocess.DEVNULL))
    return rcs


def _load(out, n):
    records = [json.loads((out / ("s%d" % i) / ("shard-%d.json" % i)).read_text()) for i in range(n)]
    evidence = {i: json.loads((out / ("s%d" % i) / ("nodes-shard-%d.json" % i)).read_text()) for i in range(n)}
    junit = [out / ("s%d" % i) / ("junit-shard-%d.xml" % i) for i in range(n)]
    return records, evidence, junit


@pytest.fixture()
def run(repo, tmp_path):
    root, markers = repo
    inv = N.collect([MODULE], tmp_path / "inv.json", root=root)
    plan = _plan(root, inv)
    out = tmp_path / "out"; out.mkdir()
    rcs = _run_shards(root, plan, out)
    independent = N.collect([MODULE], tmp_path / "inv2.json", root=root)          # a second, independent collection (the verify job)
    records, evidence, junit = _load(out, len(plan["schedule"]["shards"]))
    return {"root": root, "markers": markers, "inv": inv, "independent": independent, "plan": plan, "rcs": rcs,
            "records": records, "evidence": evidence, "junit": junit, "out": out}


def _agg(r, plan=None, records=None, evidence=None, junit=None, inventory="independent"):
    return A.aggregate(plan or r["plan"], records if records is not None else r["records"], junit if junit is not None else r["junit"],
                       node_evidence=evidence if evidence is not None else r["evidence"],
                       inventory=r["independent"] if inventory == "independent" else inventory)


# ── identity and collection ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_inventory_is_the_exact_ordered_pytest_node_ids_and_is_deterministic(repo, tmp_path):
    root, _ = repo
    a = N.collect([MODULE], tmp_path / "a.json", root=root)
    b = N.collect([MODULE], tmp_path / "b.json", root=root)
    ids = a["modules"][MODULE]["node_ids"]
    assert ids == b["modules"][MODULE]["node_ids"] and a["digest"] == b["digest"] and a["profile_digest"] == b["profile_digest"]
    assert ids == [MODULE + "::test_param[" + p + "]" for p in ("a", "b/c.py", "d e", "x::y", "f[g]")] + [
        MODULE + "::TestKlass::test_method", MODULE + "::test_plain"]                                   # original parametrized ids, unchanged
    assert a["modules"][MODULE]["digest"] == N.ids_digest(ids) and a["tested_sha"] == _git(root, "rev-parse", "HEAD")
    N.verify_inventory(a)
    forged = copy.deepcopy(a); forged["modules"][MODULE]["node_ids"].pop()
    with pytest.raises(N.NodeError):
        N.verify_inventory(forged)


def test_collection_refuses_a_dirty_tracked_tree(repo, tmp_path):
    root, _ = repo
    (root / MODULE).write_text(SYNTH + "\ndef test_extra():\n    pass\n")
    with pytest.raises(N.NodeError):
        N.collect([MODULE], tmp_path / "x.json", root=root)


def test_junit_address_is_pytests_own_derivation(run):
    from tools.ci_v4_aggregate import read_junit
    junit = {(c["classname"], c["name"]) for p in run["junit"] for c in read_junit(p)}
    assert junit == {N.junit_address(n) for n in run["inv"]["modules"][MODULE]["node_ids"]}


# ── partition ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_partition_is_exact_deterministic_order_preserving_and_never_empty(run):
    plan, inv = run["plan"], run["inv"]
    ids = inv["modules"][MODULE]["node_ids"]
    units = [u for s in plan["schedule"]["units"] for u in s]
    assert all(u["kind"] == "nodes" and u["node_ids"] for u in units) and len(units) == 3
    flat = [n for u in units for n in u["node_ids"]]
    assert sorted(flat) == sorted(ids) and len(flat) == len(set(flat))                     # disjoint union == collection
    for u in units:
        assert u["node_ids"] == [n for n in ids if n in set(u["node_ids"])]                 # collection order inside a part
    assert plan["pytest_modules"] == [MODULE] and plan == _plan(run["root"], inv)            # selection untouched, deterministic


def test_a_floor_node_gets_its_own_part_and_disabled_policy_is_a_no_op(run):
    inv = run["inv"]; ids = inv["modules"][MODULE]["node_ids"]
    heavy = {n: (500.0 if n.endswith("test_plain") else 10.0) for n in ids}
    plan = _plan(run["root"], inv, heavy)
    parts = [u["node_ids"] for s in plan["schedule"]["units"] for u in s]
    assert [MODULE + "::test_plain"] in parts
    base = {k: v for k, v in plan.items() if k not in ("node_split",)}
    base["schedule"] = plan["schedule"]["module_plan_superseded"]; base.pop("digest"); base["digest"] = S.plan_digest(base)
    off = dict(SPLIT_POLICY)
    assert S.apply_node_split(base, inv, off, {MODULE: 30.0}, heavy, WORKERS) is base       # required gate: OFF -> unchanged plan object
    other = copy.deepcopy(inv); other["tested_sha"] = "0" * 40
    with pytest.raises(ValueError):
        S.apply_node_split(base, other, off, {MODULE: 30.0}, heavy, WORKERS, shadow=True)


@pytest.mark.parametrize("mutate", [
    lambda p: p["modules"].update({"tests/test_*.py": p["modules"][MODULE]}),
    lambda p: p["modules"][MODULE].pop("isolation_proof"),
    lambda p: p["modules"][MODULE].update(verdict="NOT_SAFE_TO_SPLIT"),
    lambda p: p.update(max_parts_per_module=64),
    lambda p: p.update(enabled_in_required_pr_gate="yes"),
])
def test_split_policy_is_a_closed_literal_allowlist(mutate):
    p = copy.deepcopy(SPLIT_POLICY)
    mutate(p)
    with pytest.raises((ValueError, KeyError)):
        S.validate_node_split_policy(p)


def test_repository_policy_is_the_closed_reviewed_allowlist():
    """PR-B enables the required-gate use (authority only from the TRUSTED base, see tests/test_ci_v4_activate.py); the allowlist stays the three
    proven modules - nothing else (U2/O1, finance, Goal Seek) is split without separate isolation evidence. tests/test_u1_scope.py joined
    2026-11-14 with its own isolation proof (the same per-test worktree/reset fixtures as the proven WF-06B module) after its measured size
    grew 15.9x over the stale weight (4113.3 s across 100 nodes, heaviest node 1990.5 s, run 43569255310 shard-1 at the exact PR head)."""
    pol = S.load_node_split_policy()
    assert pol["enabled_in_required_pr_gate"] is True
    assert set(pol["modules"]) == {"tests/test_rcux_governance.py", "tests/test_wf06b_scope.py", "tests/test_u1_scope.py"}
    for m in pol["modules"]:
        assert (ROOT / m).is_file()
        assert pol["modules"][m]["isolation_proof"]
    weights = json.loads((ROOT / "docs/ci_v4/node_weights.json").read_text())
    assert weights["sources"] and all(len(s["sha"]) == 40 and len(s["artifact_sha256"]) == 64 for s in weights["sources"])
    assert all("NOT a completed sample" in c["reason"] for c in weights["censored"])


# ── shard execution ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_shards_execute_exactly_their_nodes_with_per_process_fixtures(run):
    assert run["rcs"] == [0, 0, 0]
    names = sorted(p.name.split("-")[0] for p in run["markers"].iterdir())
    assert names.count("setup") == 3 and names.count("teardown") == 3                     # module fixture once per isolated process, torn down
    for i, (rec, ev) in enumerate(zip(run["records"], [run["evidence"][k] for k in sorted(run["evidence"])])):
        planned = [n for u in run["plan"]["schedule"]["units"][i] for n in u["node_ids"]]
        assert sorted(ev["nodes"]) == sorted(planned) == sorted(ev["kept"])
        assert ev["complete"] is True and ev["exitstatus"] == rec["pytest_exit"] == 0 and rec["tmp"]["mode"] == "disk"


@pytest.mark.parametrize("tamper", ["digest", "missing_id", "foreign_module"])
def test_shard_aborts_before_running_on_a_collection_or_assignment_mismatch(run, tamper):
    plan = copy.deepcopy(run["plan"])
    if tamper == "digest":
        plan["node_split"]["modules"][MODULE]["digest"] = "0" * 64
    elif tamper == "missing_id":
        plan["schedule"]["units"][0][0]["node_ids"].append(MODULE + "::test_not_there")
    else:
        (run["root"] / "tests/test_other.py").write_text("def test_o():\n    pass\n")
        plan["schedule"]["units"][0].append({"kind": "module", "module": "tests/test_nope.py"})
    if tamper != "foreign_module":
        plan["digest"] = S.plan_digest(plan)
        out = run["out"] / ("t-" + tamper); out.mkdir()
        assert _run_shards(run["root"], plan, out)[0] == 1
        ev = json.loads((out / "s0/nodes-shard-0.json").read_text())
        assert ev["exitstatus"] == 4 and ev["nodes"] == {}                                    # usage error before any test ran
    else:
        assign = SH.assignment(plan, 0)
        env_assign = run["out"] / "assign.json"; env_assign.write_text(json.dumps(assign))
        evf = run["out"] / "ev.json"
        env = dict(os.environ, **{N.ENV_ASSIGN: str(env_assign), N.ENV_EVIDENCE: str(evf)})
        rc = subprocess.call(N._pytest_argv([MODULE, "tests/test_other.py"]), cwd=run["root"], env=env, stdout=subprocess.DEVNULL)
        assert rc == 4 and json.loads(evf.read_text())["nodes"] == {}


def test_tmp_choice_is_recorded_and_falls_back_safely(tmp_path):
    assert SH.choose_tmp("disk", 0) == (None, {"mode": "disk", "reason": "default"})
    path, rec = SH.choose_tmp("auto", 1, tmpfs=tmp_path, min_free=0, disk_base=tmp_path)
    assert rec["mode"] == "tmpfs" and path.is_dir() and (path.stat().st_mode & 0o777) == 0o700
    path, rec = SH.choose_tmp("auto", 2, tmpfs=tmp_path, min_free=1 << 62, disk_base=tmp_path)
    assert rec["mode"] == "disk_fallback" and path.is_dir()
    path, rec = SH.choose_tmp("auto", 3, tmpfs=tmp_path / "missing", min_free=0, disk_base=tmp_path)
    assert rec["mode"] == "disk_fallback"
    with pytest.raises(SystemExit):
        SH.choose_tmp("tmpfs", 4, tmpfs=tmp_path / "missing", min_free=0)


# ── independent aggregation ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_exact_disjoint_union_passes(run):
    res = _agg(run)
    assert res["verdict"] == "PASS", res["problems"]
    assert res["executed_nodes"] == len(run["inv"]["modules"][MODULE]["node_ids"])


def _drop_node(r, nodeid):
    """Remove one node from BOTH the evidence and the JUnit of its shard (a consistent but incomplete execution)."""
    ev = copy.deepcopy(r["evidence"])
    junit = []
    cls, name = N.junit_address(nodeid)
    for i, p in enumerate(r["junit"]):
        ev[i]["nodes"].pop(nodeid, None)
        text = p.read_text()
        import xml.etree.ElementTree as ET
        tree = ET.parse(p)
        for suite in tree.getroot().iter("testsuite"):
            for tc in list(suite):
                if tc.tag == "testcase" and (tc.get("classname"), tc.get("name")) == (cls, name):
                    suite.remove(tc)
        q = p.parent / ("junit-shard-%d.xml" % i)
        q2 = r["out"] / ("drop-%d" % i); q2.mkdir(exist_ok=True)
        tree.write(q2 / q.name)
        junit.append(q2 / q.name)
        assert text
    return ev, junit


def test_a_missing_node_fails_closed(run):
    victim = run["inv"]["modules"][MODULE]["node_ids"][2]
    ev, junit = _drop_node(run, victim)
    res = _agg(run, evidence=ev, junit=junit)
    assert res["verdict"] == "FAIL" and any("never executed" in p for p in res["problems"])


def test_a_duplicated_node_across_shards_fails_closed(run):
    ev = copy.deepcopy(run["evidence"])
    node = next(iter(ev[0]["nodes"]))
    ev[1]["nodes"][node] = ev[0]["nodes"][node]
    res = _agg(run, evidence=ev)
    assert res["verdict"] == "FAIL" and any("more than once" in p for p in res["problems"])


def test_a_foreign_or_misassigned_node_fails_closed(run):
    ev = copy.deepcopy(run["evidence"])
    ev[0]["nodes"][MODULE + "::test_invented"] = {"outcome": "passed", "phases": {"call": "passed"}, "duration": 0}
    res = _agg(run, evidence=ev)
    assert res["verdict"] == "FAIL" and any("outside the collection" in p for p in res["problems"])
    ev = copy.deepcopy(run["evidence"])
    node = next(iter(ev[1]["nodes"]))
    ev[0]["nodes"][node] = ev[1]["nodes"].pop(node)                                         # ran, but in the wrong shard
    res = _agg(run, evidence=ev)
    assert res["verdict"] == "FAIL" and any("assigned to shard" in p for p in res["problems"])


@pytest.mark.parametrize("forge", ["incomplete", "binding", "profile", "exit", "kept_dup", "outcome", "absent"])
def test_forged_or_truncated_evidence_fails_closed(run, forge):
    ev = copy.deepcopy(run["evidence"])
    if forge == "incomplete":
        ev[0]["complete"] = False
    elif forge == "binding":
        ev[0]["binding"]["plan_digest"] = "0" * 64
    elif forge == "profile":
        ev[0]["profile_digest"] = "0" * 64
    elif forge == "exit":
        ev[0]["exitstatus"] = 1
    elif forge == "kept_dup":
        ev[0]["kept"] = ev[0]["kept"] + ev[0]["kept"][:1]
    elif forge == "outcome":
        n = next(iter(ev[0]["nodes"])); ev[0]["nodes"][n]["outcome"] = "incomplete"
    else:
        del ev[0]
    assert _agg(run, evidence=ev)["verdict"] == "FAIL"


def test_junit_that_does_not_reconcile_with_the_evidence_fails_closed(run):
    victim = next(iter(run["evidence"][0]["nodes"]))
    _, junit = _drop_node(run, victim)                                                       # JUnit lost a case the evidence reports
    res = _agg(run, junit=junit)
    assert res["verdict"] == "FAIL" and any("does not reconcile" in p for p in res["problems"])


def test_plan_and_inventory_forgery_or_downgrade_fails_closed(run):
    with pytest.raises(A.AggregateError):
        forged = copy.deepcopy(run["plan"]); forged["node_split"]["modules"][MODULE]["node_ids"].pop()
        _agg(run, plan=forged)                                                               # altered after signing -> digest
    res = _agg(run, inventory=None)
    assert res["verdict"] == "FAIL" and any("independent re-collection" in p for p in res["problems"])
    other = copy.deepcopy(run["independent"]); other["modules"][MODULE]["node_ids"] = other["modules"][MODULE]["node_ids"][:-1]
    other["modules"][MODULE]["count"] -= 1; other["modules"][MODULE]["digest"] = N.ids_digest(other["modules"][MODULE]["node_ids"])
    other["digest"] = __import__("hashlib").sha256(json.dumps({k: v for k, v in other.items() if k != "digest"}, sort_keys=True,
                                                               separators=(",", ":")).encode()).hexdigest()
    res = _agg(run, inventory=other)
    assert res["verdict"] == "FAIL" and any("differs from the planned inventory" in p for p in res["problems"])
    recs = copy.deepcopy(run["records"]); recs[0].pop("units")
    assert _agg(run, records=recs)["verdict"] == "FAIL"                                      # a shard that ignored its units
    recs = copy.deepcopy(run["records"])[:-1]
    assert _agg(run, records=recs)["verdict"] == "FAIL"                                      # a whole shard missing


def test_a_failing_node_fails_the_split_module(repo, tmp_path):
    root, _ = repo
    (root / MODULE).write_text(SYNTH.replace("assert p\n", "assert p != 'd e'\n"))
    _git(root, "-c", "user.name=ci-test-identity", "-c", "user.email=ci-test-identity", "commit", "-qam", "red")
    inv = N.collect([MODULE], tmp_path / "inv.json", root=root)
    plan = _plan(root, inv)
    out = tmp_path / "o"; out.mkdir()
    assert 1 in _run_shards(root, plan, out)
    records, evidence, junit = _load(out, len(plan["schedule"]["shards"]))
    res = A.aggregate(plan, records, junit, node_evidence=evidence, inventory=N.collect([MODULE], tmp_path / "i2.json", root=root))
    assert res["verdict"] == "FAIL" and res["counts"]["failed"] == 1


def test_real_allowlisted_modules_collect_exact_lossless_ids(tmp_path):
    """The real split candidates at this commit: unique ids, lossless JUnit identity, stable across two collections (count NOT hardcoded)."""
    mods = sorted(S.load_node_split_policy()["modules"])
    got = []
    for k in range(2):
        f = tmp_path / ("c%d.json" % k)
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", **{N.ENV_COLLECT: str(f)})
        env.pop(N.ENV_ASSIGN, None); env.pop(N.ENV_EVIDENCE, None)
        assert subprocess.call(N._pytest_argv(["--collect-only", "--junitxml", str(tmp_path / "j.xml"), *mods]), cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL) == 0
        got.append(json.loads(f.read_text()))
    assert got[0]["modules"] == got[1]["modules"] and set(got[0]["modules"]) == set(mods)
    for m in mods:
        ids = got[0]["modules"][m]["node_ids"]
        assert ids and len(ids) == len(set(ids)) and len({N.junit_address(i) for i in ids}) == len(ids)


# ---- stall forensics: the in-process stdlib faulthandler watchdog (2026-11-14) -----------------------------------------------------------------
WRAP = r'''
import time


def _hang_here(seconds):
    time.sleep(seconds)


def test_fast():
    assert True


def test_slow_node():
    _hang_here(6)


def test_after():
    assert True
'''
WRAP_FAIL = "def test_boom():\n    assert 1 == 2\n"


def _run_wrapped(tmp_path, body, name, dump_after_s=2, **extra_env):
    f = tmp_path / name
    f.write_text(body)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", **extra_env)
    argv = SH.pytest_command(["-rs", *SH.DIAGNOSTIC_ARGS, "-p", "no:cacheprovider", "--rootdir", str(tmp_path), str(f)], dump_after_s=dump_after_s)
    proc = subprocess.run(argv, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    return proc.returncode, proc.stdout.decode(errors="replace")


def test_watchdog_names_the_running_node_and_dumps_the_stack_repeatedly_without_stopping_the_run(tmp_path):
    """Real pytest under PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 (the hosted shard environment): a node that outlives the interval is named in the log
    BEFORE it finishes, every dump shows the concrete frame it is stuck in, the dump repeats, and the run still completes (a watchdog never kills)."""
    secret = "SYNTH-SECRET-VALUE-448"
    rc, out = _run_wrapped(tmp_path, WRAP, "test_wrap.py", FINCO_SYNTH_TOKEN=secret)
    assert rc == 0, out
    first_dump = out.index("most recent call first")
    running = out.index("test_wrap.py::test_slow_node")
    assert running < first_dump                                              # the stuck node id is already in the log when the first dump is written
    assert "PASSED" not in out[running:first_dump].split("\\n", 1)[0]          # ... and it had not completed yet
    assert out.count("most recent call first") >= 2                          # repeat=True: a longer stall dumps again
    assert "in _hang_here" in out and "test_wrap.py" in out[first_dump:]     # the concrete currently-running frame
    assert out.count("Timeout (0:00:02)!") >= 2
    assert "test_wrap.py::test_after" in out and "3 passed" in out
    assert secret not in out and "FINCO_SYNTH_TOKEN" not in out              # a dump shows frames only, never the environment


def test_watchdog_keeps_a_failing_run_failing_and_adds_no_dump_to_a_fast_run(tmp_path):
    rc, out = _run_wrapped(tmp_path, WRAP_FAIL, "test_fail.py", dump_after_s=30)
    assert rc == 1 and "1 failed" in out and "most recent call first" not in out      # failure stays failure; nothing is dumped before the interval
    rc, out = _run_wrapped(tmp_path, "def test_ok():\n    assert True\n", "test_ok.py", dump_after_s=30)
    assert rc == 0 and "1 passed" in out and "most recent call first" not in out


def test_watchdog_is_an_in_process_stdlib_wrapper_not_a_pytest_option():
    """Hosted run 43590299354: with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 the pytest option form (-p faulthandler / --faulthandler-timeout) was rejected. The
    shard command must stay the stdlib wrapper, with the unchanged default interval above the heaviest measured legitimate node."""
    argv = SH.pytest_command(["-rs", "x"])
    assert argv[:2] == [sys.executable, "-c"] and argv[3:] == ["-rs", "x"] and "dump_traceback_later(2400, repeat=True, file=_real_stderr)" in argv[2]
    assert "os.dup(2)" in argv[2] and "cancel_dump_traceback_later" in argv[2]            # the dump survives pytest's fd capture and never fires after the run
    assert not any(a == "faulthandler" or a.startswith("--faulthandler") for a in argv)
    assert SH.DIAGNOSTIC_DUMP_AFTER_S == 2400 and SH.DIAGNOSTIC_ARGS == ("-v",)
    weights = json.loads((ROOT / "docs/ci_v4/node_weights.json").read_text())["nodes"]
    assert SH.DIAGNOSTIC_DUMP_AFTER_S > max(weights.values())            # a healthy measured node never triggers a dump

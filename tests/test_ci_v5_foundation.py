"""CI V5 shadow foundation: one bounded A/B/A harness over a SYNTHETIC repository, plus B5 provenance and comparison rules.

Protects: the epoch evaluator must FAIL CLOSED (or stay explicitly NON-AUTHORITATIVE in bootstrap) on every representative tamper class, pass on the
pristine state ``A`` and again on the restored state ``A'`` (no verdict cache can leak), never accept a PR-head self-authorised epoch, and the B5
report must never turn missing / unverified / skipped / not-selected evidence into a PASS. Everything is hermetic (temporary Git repositories); a
synthetic pass is MEASURED_LOCAL evidence, never hosted acceptance. Set FINCO_V5_AB_OUT=<csv path> to record the matrix.
"""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ci_v5_b5 as B5            # noqa: E402
import ci_v5_epoch as E          # noqa: E402
import ci_v5_shadow as SH        # noqa: E402

PREFIXES = ["app/", "financial_engine/", "tools/ci_", "docs/ci_v4/", ".github/"]
B3_REPORT = str(ROOT / "tests" / "ci_v4_lean_report.py")
ROWS = []


class Repo:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *a, input=None):
        p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *a], cwd=self.path,
                           input=input, capture_output=True, text=True)
        assert p.returncode == 0, (a, p.stderr)
        return p.stdout.strip()

    def write(self, rel, text):
        f = self.path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.is_symlink() or f.exists():
            f.unlink()
        f.write_text(text)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def checkout(self, sha):
        self.git("checkout", "-q", "--detach", sha)
        self.git("reset", "-q", "--hard", sha)
        self.git("clean", "-fdxq")

    def inv(self, sha):
        return E.read_inventory(E.Git(self.path), sha)


def _seed(r):
    for rel, text in {"app/main.py": "MAIN = 1\n", "app/util.py": "UTIL = 1\n", "financial_engine/calc.py": "CALC = 1\n", "tools/ci_gate.py": "GATE = 1\n",
                      "docs/ci_v4/policy.json": "{}\n", ".github/workflows/req.yml": "name: req\n", "tests/test_calc.py": "def test_calc():\n    assert True\n",
                      "README.md": "x\n", "scripts/run.sh": "echo hi\n"}.items():
        r.write(rel, text)
    return r.commit("accepted main E")


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    """TRUSTED world: epoch.json committed at the trusted base M, head A_t declares its guarded change. BOOT world: base E has NO epoch; head carries a candidate."""
    r = Repo(tmp_path_factory.mktemp("v5"))
    e_sha = _seed(r)
    atlas = [{"id": "V4-INV-MUTATION-SEMANTICS", "kind": "INVARIANT", "status": "GAP", "semantic_paths": ["app/util.py"], "note": "synthetic"}]
    epoch = E.make_epoch(E.Git(r.path), e_sha, PREFIXES, epoch_id="synthetic", atlas=atlas)
    epoch_bytes = E.canonical(epoch)

    def legit_change(repo):                       # one declared guarded modify + one declared guarded add + one ORDINARY unguarded change
        repo.write("app/main.py", "MAIN = 2\n")
        repo.write("app/new.py", "NEW = 1\n")
        repo.write("tests/test_new.py", "def test_new():\n    assert True\n")

    def with_delta(repo, base_epoch, extra=None):
        pre = repo.commit("guarded change")
        delta = E.make_delta(base_epoch, repo.inv(pre))
        repo.write("docs/ci_v5/delta.json", E.canonical(delta).decode())
        return repo.commit("delta"), delta

    # trusted: M = E + epoch.json
    r.write(E.TRUSTED_EPOCH_PATH, epoch_bytes.decode())
    m_sha = r.commit("promote epoch (owner reviewed)")
    legit_change(r)
    a_t, delta_t = with_delta(r, epoch)
    # bootstrap: E + candidate + delta
    r.checkout(e_sha)
    legit_change(r)
    r.write(E.CANDIDATE_EPOCH_PATH, epoch_bytes.decode())
    a_b, delta_b = with_delta(r, epoch)
    r.checkout(a_t)
    return {"r": r, "E": e_sha, "M": m_sha, "A_t": a_t, "A_b": a_b, "epoch": epoch, "epoch_bytes": epoch_bytes, "delta": delta_t}


def _codes(rec):
    return {f["code"] for f in rec["failures"]} | {u["code"] for u in rec["unknowns"]}


# ------------------------------------------------------------------------------------------------------------- mutations (each returns kwargs)
def _commit_edit(fn):
    def mutate(w):
        fn(w["r"], w)
        return {"head": w["r"].commit("tamper B")}
    return mutate


def _exec_bit(r, w):
    os.chmod(r.path / "financial_engine/calc.py", 0o755)


def _symlink(r, w):
    (r.path / "app/util.py").unlink()
    os.symlink("/etc/passwd", r.path / "app/util.py")


def _rename(r, w):
    r.git("mv", "app/util.py", "app/util_renamed.py")


def _delta_edit(edit):
    def mutate(w):
        d = json.loads((w["r"].path / "docs/ci_v5/delta.json").read_text())
        edit(d)
        w["r"].write("docs/ci_v5/delta.json", E.canonical(d).decode() if d is not None else "")
        return {"head": w["r"].commit("tamper delta")}
    return mutate


def _epoch_edit(edit, path, resign=False):
    def mutate(w):
        raw = (w["r"].path / path).read_bytes()
        d = json.loads(raw)
        edit(d)
        if resign:
            d["entries_sha256"] = E.entries_digest(d["entries"])
        w["r"].write(path, E.canonical(d).decode())
        return {"head": w["r"].commit("forge epoch")}
    return mutate


def _forge_blob(d):
    e = d["entries"][0]
    d["entries"][0] = e[:7] + "0" * 40 + e[47:]


def _pin_foreign_commit(w):                        # same tree, but a commit that is NOT in the trusted base's history
    r = w["r"]
    foreign = r.git("commit-tree", r.git("rev-parse", w["E"] + "^{tree}"), "-m", "foreign")
    d = json.loads((r.path / E.CANDIDATE_EPOCH_PATH).read_text())
    d["base_commit"] = foreign
    r.write(E.CANDIDATE_EPOCH_PATH, E.canonical(d).decode())
    return {"head": r.commit("pin to a foreign commit")}


def _selfauth(w):                                  # PR head tampers a guarded file AND rewrites the trust anchor to bless it
    r = w["r"]
    r.write("app/util.py", "UTIL = 666\n")
    pre = r.commit("tamper")
    d = json.loads((r.path / E.TRUSTED_EPOCH_PATH).read_text())
    d["entries"] = sorted(E.entry_str(p, o, m) for p, (m, o) in {p: v for p, v in r.inv(pre).items() if p.startswith(tuple(PREFIXES))}.items())
    d["entries_sha256"] = E.entries_digest(d["entries"])
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(d).decode())
    return {"head": r.commit("self-authorise")}


def _selfauth_candidate(w):                        # bootstrap: the head regenerates ITS OWN candidate + delta over the tampered tree
    r = w["r"]
    r.write("financial_engine/calc.py", "CALC = 666\n")
    pre = r.commit("tamper")
    cand = E.make_epoch(E.Git(r.path), w["E"], PREFIXES, epoch_id="synthetic", atlas=w["epoch"]["atlas"])
    delta = E.make_delta(cand, r.inv(pre))
    r.write("docs/ci_v5/delta.json", E.canonical(delta).decode())
    return {"head": r.commit("self-authorised delta")}


def _declared_semantic_change(w):                  # fully DECLARED, but the path's V4 invariant is semantic: V5 must not claim PASS
    r = w["r"]
    r.write("app/util.py", "UTIL = 7\n")
    pre = r.commit("semantic path change")
    r.write("docs/ci_v5/delta.json", E.canonical(E.make_delta(w["epoch"], r.inv(pre))).decode())
    return {"head": r.commit("declare it")}


def _untracked(w):
    w["r"].write("app/evil.py", "EVIL = 1\n")
    return {"head": w["A_t"], "check_worktree": True}


def _dirty(w):
    w["r"].write("app/main.py", "MAIN = 3\n")
    return {"head": w["A_t"], "check_worktree": True}


def _wrong_worktree(w):
    w["r"].git("checkout", "-q", "--detach", w["M"])
    return {"head": w["A_t"], "check_worktree": True}


def _space_path(r, w):
    r.write("app/a b.py", "X = 1\n")


def _stale_base(w):                                 # trusted base moved on with an UNPROMOTED guarded change; the head declares it, so ONLY staleness remains
    r = w["r"]
    r.checkout(w["M"])
    r.write("app/util.py", "UTIL = 2\n")
    new_base = r.commit("accepted guarded change after the epoch")
    r.write("docs/ci_v5/delta.json", E.canonical(E.make_delta(w["epoch"], r.inv(new_base))).decode())
    return {"head": r.commit("declare it"), "base": new_base}


def _mutated(w):
    return {"head": w["r"].commit("noop")}


CASES = [
    # name, world, mutation, expected codes (subset of the observed codes), expected B verdict
    ("modified_guarded_byte", "t", _commit_edit(lambda r, w: r.write("app/util.py", "UTIL = 2\n")), {"UNDECLARED_CHANGE"}, "FAIL"),
    ("executable_bit", "t", _commit_edit(_exec_bit), {"UNDECLARED_MODE_CHANGE"}, "FAIL"),
    ("symlink_replaces_guarded_file", "t", _commit_edit(_symlink), {"NON_REGULAR_MODE"}, "FAIL"),
    ("deleted_guarded_file", "t", _commit_edit(lambda r, w: r.git("rm", "-q", "app/util.py")), {"UNDECLARED_DELETE_OR_RENAME"}, "FAIL"),
    ("renamed_guarded_file", "t", _commit_edit(_rename), {"UNDECLARED_DELETE_OR_RENAME", "UNDECLARED_ADD"}, "FAIL"),
    ("guarded_path_with_unsafe_chars", "t", _commit_edit(_space_path), {"UNSAFE_PATH"}, "FAIL"),
    ("untracked_guarded_file", "t", _untracked, {"UNTRACKED_GUARDED_PATH"}, "FAIL"),
    ("dirty_guarded_file", "t", _dirty, {"DIRTY_GUARDED_PATH"}, "FAIL"),
    ("worktree_head_is_not_the_evaluated_sha", "t", _wrong_worktree, {"WORKTREE_HEAD_MISMATCH"}, "FAIL"),
    ("changed_governance_selector_policy", "t", _commit_edit(lambda r, w: (r.write("tools/ci_gate.py", "GATE = 0\n"), r.write("docs/ci_v4/policy.json", '{"x":1}\n'))), {"UNDECLARED_CHANGE"}, "FAIL"),
    ("workflow_added_without_declaration", "t", _commit_edit(lambda r, w: r.write(".github/workflows/evil.yml", "name: evil\n")), {"UNDECLARED_ADD"}, "FAIL"),
    ("delta_missing_one_protected_file", "t", _delta_edit(lambda d: d["changes"].pop(0)), {"UNDECLARED_CHANGE"}, "FAIL"),
    ("delta_declares_wrong_blob", "t", _delta_edit(lambda d: d["changes"][0].update(blob="0" * 40)), {"DELTA_BLOB_MISMATCH"}, "FAIL"),
    ("delta_duplicate_path", "t", _delta_edit(lambda d: d["changes"].append(dict(d["changes"][0]))), {"DELTA_DUPLICATE_PATH"}, "FAIL"),
    ("delta_case_collision", "t", _delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/NEW.py", "blob": "1" * 40, "mode": "100644"})), {"DELTA_DUPLICATE_PATH"}, "FAIL"),
    ("delta_wildcard_path", "t", _delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/*", "blob": "1" * 40, "mode": "100644"})), {"DELTA_BAD_PATH"}, "FAIL"),
    ("delta_path_traversal", "t", _delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/../x.py", "blob": "1" * 40, "mode": "100644"})), {"DELTA_BAD_PATH"}, "FAIL"),
    ("delta_widens_guard", "t", _delta_edit(lambda d: d["changes"].append({"op": "add", "path": "scripts/new.sh", "blob": "1" * 40, "mode": "100644"})), {"DELTA_OUTSIDE_GUARD"}, "FAIL"),
    ("delta_modify_of_unknown_path", "t", _delta_edit(lambda d: d["changes"].append({"op": "modify", "path": "app/ghost.py", "blob": "1" * 40, "mode": "100644"})), {"DELTA_BAD_OP"}, "FAIL"),
    ("delta_declares_unrealised_add", "t", _delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/promised.py", "blob": "1" * 40, "mode": "100644"})), {"DELTA_NOT_REALISED"}, "FAIL"),
    ("delta_bound_to_other_epoch", "t", _delta_edit(lambda d: d.update(epoch_entries_sha256="2" * 64)), {"DELTA_EPOCH_MISMATCH"}, "FAIL"),
    ("delta_unknown_schema", "t", _delta_edit(lambda d: d.update(schema="FINCO_CI_V5_DELTA_V9")), {"DELTA_UNKNOWN_SCHEMA"}, "FAIL"),
    ("self_authorised_head_epoch_json", "t", _selfauth, {"TRUST_ANCHOR_MODIFIED"}, "FAIL"),
    ("candidate_unknown_schema", "b", _epoch_edit(lambda d: d.update(schema="FINCO_CI_V5_EPOCH_V9"), E.CANDIDATE_EPOCH_PATH), {"EPOCH_UNKNOWN_SCHEMA"}, "FAIL"),
    ("candidate_forged_digest", "b", _epoch_edit(_forge_blob, E.CANDIDATE_EPOCH_PATH), {"EPOCH_DIGEST_MISMATCH"}, "FAIL"),
    ("candidate_forged_blob_resigned", "b", _epoch_edit(_forge_blob, E.CANDIDATE_EPOCH_PATH, True), {"EPOCH_SNAPSHOT_MISMATCH"}, "FAIL"),
    ("candidate_pinned_sha_does_not_own_tree", "b", _epoch_edit(lambda d: d.update(base_tree="3" * 40), E.CANDIDATE_EPOCH_PATH), {"EPOCH_TREE_NOT_OWNED"}, "FAIL"),
    ("candidate_pinned_to_non_history_commit", "b", _pin_foreign_commit, {"EPOCH_NOT_ACCEPTED_HISTORY"}, "FAIL"),
    ("candidate_self_authorising_tampered_tree", "b", _selfauth_candidate, None, "PASS"),    # PASSes ONLY as NON-AUTHORITATIVE (asserted below)
    ("declared_change_on_semantic_v4_invariant", "t", _declared_semantic_change, {"SEMANTIC_INVARIANT_NOT_EVALUATED"}, "UNKNOWN"),
    ("epoch_stale_at_trusted_base", "t", _stale_base, {"EPOCH_STALE_AT_BASE"}, "UNKNOWN"),
]


def _run(w, world, mutation):
    r = w["r"]
    base = w["M"] if world == "t" else w["E"]
    a = w["A_t"] if world == "t" else w["A_b"]
    r.checkout(a)
    rec_a = E.verify(r.path, a, base, check_worktree=True)
    kw = mutation(w)
    head, base = kw.get("head", a), kw.get("base", base)
    rec_b = E.verify(r.path, head, base, check_worktree=kw.get("check_worktree", False))
    r.checkout(a)
    rec_a2 = E.verify(r.path, a, w["M"] if world == "t" else w["E"], check_worktree=True)
    return rec_a, rec_b, rec_a2


@pytest.mark.parametrize("name,world,mutation,expected,verdict", CASES, ids=[c[0] for c in CASES])
def test_a_b_a_tamper_matrix(worlds, name, world, mutation, expected, verdict):
    rec_a, rec_b, rec_a2 = _run(worlds, world, mutation)
    trust = "TRUSTED_BASE" if world == "t" else "CANDIDATE_UNTRUSTED"
    assert rec_a["verdict"] == "PASS" and rec_a["trust_state"] == trust and rec_a["authoritative"] == (world == "t"), rec_a["failures"]   # pristine A
    assert rec_b["verdict"] == verdict, (name, rec_b["failures"], rec_b["unknowns"])
    if expected is not None:
        assert expected <= _codes(rec_b), (name, _codes(rec_b))                    # attributed to the SPECIFIC guard, not any exception
        assert "EVALUATOR_ERROR" not in _codes(rec_b)
        assert not rec_b["authoritative"] or rec_b["verdict"] == "FAIL"
    else:                                                                            # self-authorised: never authoritative, never an effective PASS
        assert rec_b["authoritative"] is False and rec_b["effective"] == "NON_AUTHORITATIVE_PASS"
    assert rec_a2["verdict"] == "PASS" and rec_a2["failures"] == [] and rec_a2["effective"] == rec_a["effective"]                       # restored A'
    assert rec_a2["metrics"]["memo_or_cache"] == "none" and rec_a2["epoch"] == rec_a["epoch"]
    ROWS.append({"case": name, "world": "TRUSTED_BASE" if world == "t" else "BOOTSTRAP_CANDIDATE", "A": rec_a["effective"], "B": rec_b["effective"],
                 "B_codes": ";".join(sorted(_codes(rec_b))), "expected_code": ";".join(sorted(expected or ["NON_AUTHORITATIVE_ONLY"])), "A_prime": rec_a2["effective"],
                 "git_children_A": rec_a["metrics"]["git_children"]})


def test_ref_and_object_validation_and_no_shell_interpolation(worlds, tmp_path):
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    marker = tmp_path / "pwned"
    bad = ["HEAD", "main", w["A_t"][:12], "$(touch %s)" % marker, "; touch %s" % marker, "--output=%s" % marker, w["A_t"].upper(), ""]
    for ref in bad:
        rec = E.verify(r.path, ref, w["M"])
        assert rec["verdict"] == "FAIL" and "BAD_REF" in _codes(rec) and rec["authoritative"] is False, ref
    assert not marker.exists()
    rec = E.verify(r.path, "f" * 40, w["M"])                                          # well-formed but absent: UNKNOWN, never PASS
    assert rec["verdict"] == "UNKNOWN" and "OBJECT_UNAVAILABLE" in _codes(rec)
    tree = r.git("rev-parse", w["A_t"] + "^{tree}")
    assert E.verify(r.path, w["A_t"], w["M"], expect_head_tree="0" * 40)["verdict"] == "FAIL"
    assert E.verify(r.path, w["A_t"], w["M"], expect_head_tree=tree)["verdict"] == "PASS"
    assert "BASE_NOT_ANCESTOR" in _codes(E.verify(r.path, w["M"], w["A_t"]))             # base newer than head: wrong base
    assert E.verify(r.path, tree, w["M"])["verdict"] == "UNKNOWN"                       # a tree id is not a commit


def test_ordinary_unguarded_change_and_declared_production_delta_need_no_cohort(worlds):
    """V5-3 property: an unguarded change needs nothing; a guarded production change needs exactly its declared delta. No legacy cohort is created."""
    w, r = worlds, worlds["r"]
    r.checkout(w["M"])
    r.write("tests/test_ordinary.py", "def test_ordinary():\n    assert True\n")
    r.write("README.md", "changed\n")
    head = r.commit("ordinary only")
    assert E.verify(r.path, head, w["M"])["verdict"] == "PASS"
    assert json.loads(json.dumps(w["delta"]))["changes"] and {c["op"] for c in w["delta"]["changes"]} == {"add", "modify"}
    assert E.verify(r.path, w["A_t"], w["M"])["delta_changes"] == 2


def test_no_verdict_is_cached_across_mutation_between_evaluations(worlds):
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    seen = []
    for step in range(3):
        seen.append(E.verify(r.path, r.git("rev-parse", "HEAD"), w["M"], check_worktree=True)["verdict"])
        r.write("app/main.py", "MAIN = %d\n" % (100 + step))                          # dirty the guarded worktree between evaluations
        seen.append(E.verify(r.path, r.git("rev-parse", "HEAD"), w["M"], check_worktree=True)["verdict"])
        r.checkout(w["A_t"])
    assert seen == ["PASS", "FAIL"] * 3


def test_trusted_epoch_is_read_from_the_base_only_and_head_candidate_is_never_authoritative(worlds):
    w, r = worlds, worlds["r"]
    trusted = E.verify(r.path, w["A_t"], w["M"])
    boot = E.verify(r.path, w["A_b"], w["E"])
    assert trusted["epoch"]["source"] == "base:" + E.TRUSTED_EPOCH_PATH and trusted["authoritative"] and trusted["effective"] == "PASS"
    assert boot["epoch"]["source"] == "head:" + E.CANDIDATE_EPOCH_PATH and not boot["authoritative"] and boot["effective"] == "NON_AUTHORITATIVE_PASS"
    assert E.verify(r.path, w["M"], w["M"], epoch_bytes=w["epoch_bytes"])["trust_state"] == "EXPLICIT_UNTRUSTED"
    none = E.verify(r.path, w["E"], w["E"])
    assert none["verdict"] == "UNKNOWN" and none["trust_state"] == "NO_EPOCH" and not none["authoritative"]


def test_epoch_document_validation_is_strict(worlds):
    ep = worlds["epoch"]
    assert E.load_epoch(worlds["epoch_bytes"])[0] is not None
    for mutated in ({**ep, "extra": 1}, {**ep, "entries": ep["entries"] + [ep["entries"][0]]}, {**ep, "entries": ["120000 %s\tapp/x.py" % ("a" * 40)] + ep["entries"]},
                    {**ep, "entries": ["100644 %s\t../x" % ("a" * 40)] + ep["entries"]}, {**ep, "base_commit": "short"}):
        assert E.load_epoch(E.canonical(mutated))[0] is None
    assert E.load_epoch(worlds["epoch_bytes"] + b" ")[0] is None and E.load_epoch(b"{")[0] is None
    entries = sorted(set(ep["entries"]))
    assert E.entries_digest(entries) == ep["entries_sha256"]


def test_candidate_artifact_in_repository_is_well_formed_and_makes_no_authority_claim():
    path = ROOT / E.CANDIDATE_EPOCH_PATH
    epoch, problems = E.load_epoch(path.read_bytes())
    assert epoch is not None, problems
    assert not (ROOT / E.TRUSTED_EPOCH_PATH).exists(), "a trusted epoch needs a separate owner-reviewed promotion PR"
    modes = {e.split(" ", 1)[0] for e in epoch["entries"]}
    assert modes <= set(E.MODES) and epoch["atlas"], "every row must carry an explicit COVERED / GAP / UNKNOWN status"
    assert {r["status"] for r in epoch["atlas"]} <= {"COVERED", "GAP", "UNKNOWN"}
    assert any(r["status"] != "COVERED" for r in epoch["atlas"]), "V4-only invariants must be listed as gaps, never hidden"


# ------------------------------------------------------------------------------------------------------------------------------ B5 provenance
def _junit(tmp_path, cases):
    body = "".join('<testcase classname="%s" name="%s" time="1.5">%s</testcase>' % (c, n, extra) for c, n, extra in cases)
    p = tmp_path / "j.xml"
    p.write_text('<testsuite>%s</testsuite>' % body)
    return str(p)


def test_b5_status_vocabulary_never_promotes_unverified_skipped_or_unselected_to_pass(worlds, tmp_path):
    w, r = worlds, worlds["r"]
    sha = w["A_t"]
    junit = _junit(tmp_path, [("tests.test_new", "test_a", ""), ("tests.test_new", "test_b", "<skipped/>")])
    known = {"tests/test_new.py"}
    label, _why, st = B5.junit_evidence([junit], None, sha, known)
    assert (label, st) == ("UNVERIFIED_INPUT", {})                                        # no attestation: no status, no seconds, not OBSERVED_HOSTED
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"kind": "hosted_run", "sha": "0" * 40, "run_id": "1", "junit_sha256": [B5._sha256(junit)]}))
    assert B5.junit_evidence([junit], str(wrong), sha, known)[0] == "UNVERIFIED_INPUT"    # attestation for ANOTHER sha
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"kind": "hosted_run", "sha": sha, "run_id": "1", "junit_sha256": ["f" * 64]}))
    assert B5.junit_evidence([junit], str(stale), sha, known)[0] == "UNVERIFIED_INPUT"    # digest of other bytes
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"kind": "hosted_run", "sha": sha, "run_id": "9", "junit_sha256": [B5._sha256(junit)]}))
    label, _why, st = B5.junit_evidence([junit], str(good), sha, known)
    assert label == "OBSERVED_HOSTED" and st == {"tests/test_new.py": "SKIPPED"}          # one skipped node: the module is never plain PASS
    good.write_text(json.dumps({"kind": "hosted_run", "sha": sha, "run_id": "9", "conclusion": "cancelled", "junit_sha256": [B5._sha256(junit)]}))
    assert B5.junit_evidence([junit], str(good), sha, known)[2] == {"tests/test_new.py": "CANCELLED"}
    assert B5.junit_evidence([], None, sha)[0] == "UNKNOWN"


def test_b5_report_on_synthetic_pr_is_honest_about_missing_plan_and_junit(worlds, tmp_path):
    w = worlds
    rep = B5.build(w["r"].path, w["M"], w["A_t"], B3_REPORT)
    assert rep["status"] == "OK" and rep["head_sha"] == w["A_t"] and rep["node_delta_kind"].startswith("AST_FUNCTION_DELTA")
    mod = {m["path"]: m for m in rep["modules"]}["tests/test_new.py"]
    assert mod["change"] == "added" and mod["selection"] == "UNKNOWN" and mod["status"] == "UNKNOWN" and mod["seconds"] is None
    assert any(u.startswith("plan:") for u in rep["unavailable"]) and any(u.startswith("junit:") for u in rep["unavailable"])
    assert rep["junit"]["label"] == "UNKNOWN" and rep["simulation"]["label"] == "UNKNOWN" and rep["exit_code_policy"].startswith("always 0")
    text = B5.summary_markdown(rep)
    assert "WARN-ONLY" in text and "| `tests/test_new.py` | added | UNKNOWN | UNKNOWN |" in text
    # a plan whose tested_sha is NOT the head stays UNVERIFIED: NOT_SELECTED must not be claimed from it
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"tested_sha": "e" * 40, "pytest_modules": ["tests/test_calc.py"]}))
    rep = B5.build(w["r"].path, w["M"], w["A_t"], B3_REPORT, str(plan))
    row = {m["path"]: m for m in rep["modules"]}["tests/test_new.py"]
    assert rep["plan_provenance"].startswith("UNVERIFIED_INPUT") and row["selection"] == "UNKNOWN" and row["status"] == "UNKNOWN"
    plan.write_text(json.dumps({"tested_sha": w["A_t"], "pytest_modules": ["tests/test_calc.py"]}))
    row = {m["path"]: m for m in B5.build(w["r"].path, w["M"], w["A_t"], B3_REPORT, str(plan))["modules"]}["tests/test_new.py"]
    assert row["selection"] == "NOT_SELECTED" and row["status"] == "NOT_SELECTED" and row["status"] != "PASS"
    plan.write_text("{not json")
    assert B5.build(w["r"].path, w["M"], w["A_t"], B3_REPORT, str(plan))["plan_provenance"].startswith("UNKNOWN")


def test_b5_failure_is_visible_unavailable_never_a_pass(worlds, tmp_path):
    rep = B5.build(worlds["r"].path, "0" * 40, worlds["A_t"], B3_REPORT)
    assert rep["status"] == "UNAVAILABLE" and "UNAVAILABLE" in B5.summary_markdown(rep) and "NOT a pass" in B5.summary_markdown(rep)


# ----------------------------------------------------------------------------------------------------------------------- V4 / V5 comparison
@pytest.mark.parametrize("v4,v5,auth,relation", [
    ("PASS", "PASS", True, "MATCH_PASS"), ("FAIL", "FAIL", True, "MATCH_FAIL"), ("FAIL", "PASS", False, "MISMATCH_V5_WOULD_ADMIT_V4_FAIL"),
    ("PASS", "FAIL", True, "MISMATCH_V5_STRICTER_THAN_V4"), ("UNAVAILABLE", "PASS", True, "INCOMPARABLE"), ("PASS", "UNKNOWN", False, "INCOMPARABLE")])
def test_comparison_never_lets_v5_suppress_a_v4_failure_and_never_claims_parity(v4, v5, auth, relation):
    out = SH.compare({"verdict": v4, "non_exact_cohorts": ["x"]}, {"verdict": v5, "authoritative": auth})
    assert out["relation"] == relation and out["parity"] == "PARITY_NOT_ESTABLISHED" and out["v4_remains_authoritative"] is True
    assert (out["v4_failure_attribution"] is not None) == (v4 == "FAIL")


def test_v4_gate_runner_never_reports_pass_for_a_missing_or_failed_gate(tmp_path):
    rec = SH.run_v4_gate(str(tmp_path), str(tmp_path / "o.json"), 30)                       # a directory without the gate: UNAVAILABLE, not PASS
    assert rec["verdict"] == "UNAVAILABLE"


def test_shadow_workflow_is_observational_and_least_privilege():
    import yaml
    text = (ROOT / ".github/workflows/ci_v5_shadow.yml").read_text()
    wf = yaml.safe_load(text)
    assert wf["permissions"] == {"contents": "read"} and list(wf["jobs"]) == ["shadow"]
    assert "pull_request_target" not in text and "secrets." not in text and "continue-on-error" not in text and "workflow_run" not in text
    assert not any("${{" in step.get("run", "") for step in wf["jobs"]["shadow"]["steps"]), "event/context values reach scripts only through env:"
    assert all(len(u.split("@")[1]) == 40 for u in (s["uses"] for s in wf["jobs"]["shadow"]["steps"] if "uses" in s))     # actions pinned by full SHA


def teardown_module(module):
    out = os.environ.get("FINCO_V5_AB_OUT")
    if out and ROWS:
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
            w.writeheader()
            w.writerows(sorted(ROWS, key=lambda r: r["case"]))

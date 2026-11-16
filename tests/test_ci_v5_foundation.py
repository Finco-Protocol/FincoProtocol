"""CI V5-2B: the A/B/A hostile regression matrix over a SYNTHETIC repository (schema V2: ALL_TRACKED, base-relative delta, trusted-code semantic registry).

Specification: the V5-2A audit counterexample matrix (G1-G24, GA3, T1, T2a, T3c, T3e, T5b, W3-W7, S1b and the previously rejected R1-R8, T4a-T4k, plus A1-A4).
Every row is a three-state experiment: A (pristine, must be the expected verdict), B (the tamper, must be rejected for the SPECIFIC reason) and A'
(restored, must equal A: no cache can leak). The evaluator runs exactly as the lane runs it (``tool_source=TRUSTED_BASE``, base == protected tip).
Everything is hermetic (temporary Git repositories, synthetic content only); a pass here is MEASURED_LOCAL evidence, never hosted acceptance.
Set FINCO_V5_AB_OUT=<csv path> to record the matrix (with the exact head/tree/base SHAs of every row).
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
import ci_v5_epoch as E          # noqa: E402

POLICY = E.POLICY
ROWS = []
SEMANTIC_LITERAL = "app/library/router.py"          # a real member of the V4 mutation-security inventory (and of the trusted registry)


class Repo:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *a, input=None):
        p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t\x40test.invalid", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", *a],
                           cwd=self.path, input=input, capture_output=True, text=True)
        assert p.returncode == 0, (a, p.stderr)
        return p.stdout.strip()

    def write(self, rel, text, mode=None):
        f = self.path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.is_symlink() or f.exists():
            f.unlink()
        f.write_text(text)
        if mode:
            os.chmod(f, mode)

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

    def tree(self, sha):
        return self.git("rev-parse", sha + "^{tree}")


SEED = {
    "app/main.py": "MAIN = 1\n", "app/util.py": "UTIL = 1\n", "app/radar_rwa.py": "RWA = 1\n", SEMANTIC_LITERAL: "ROUTER = 1\n",
    "financial_engine/calc.py": "CALC = 1\n", "finco_core/core.py": "CORE = 1\n", "finco_radar/mod.py": "RADAR = 1\n",
    "tools/ci_gate.py": "GATE = 1\n", "tools/governance_history_gate.py": "GOV = 1\n", "main_api.py": "API = 1\n", "utils/financial.py": "FIN = 1\n",
    "utils/cache.py": "CACHE = 1\n", "static/app.js": "var a = 1;\n", "deploy/scripts/start_prod.sh": "echo start\n", "deploy/nginx/app.conf": "server {}\n",
    "frontend/package.json": "{}\n", "frontend/vite.config.ts": "export default {}\n", "docs/ci_v4/policy.json": "{}\n", "docs/ci_v5/README.md": "readme\n",
    "docs/ci_v5/bootstrap/SOURCE_SUCCESSOR.json": "{}\n", ".github/workflows/req.yml": "name: req\n", "tests/test_calc.py": "def test_calc():\n    assert True\n",
    "tests/conftest.py": "# conftest\n", "tests/test_wf07_revenue_csrf.py": "def test_csrf():\n    assert True\n",
    "tests/test_f04_signing_secret_fail_closed.py": "def test_sign():\n    assert True\n", "tests/test_finval_f01_native_identity.py": "def test_f01():\n    assert True\n",
    "tests/browser_model_mutation.py": "BROWSER = 1\n", "README.md": "x\n", "scripts/run.sh": "echo hi\n", ".gitignore": "app/data/*\n__pycache__/\n*.pyc\n",
}


def _seed(r):
    for rel, text in SEED.items():
        r.write(rel, text)
    return r.commit("accepted main E")


def with_delta(repo, base_sha, msg="delta"):
    """Commit the guarded change currently in the worktree, then the delta that declares it (base-relative, bound to the base tip)."""
    pre = repo.commit("guarded change")
    delta = E.make_delta(repo.inv(base_sha), repo.inv(pre), base_sha, repo.tree(base_sha))
    repo.write(E.DELTA_PATH, E.canonical(delta).decode())
    return repo.commit(msg), delta


def legit_change(repo):                       # one P modify + one P add + one X add + one ORDINARY prose change: all non-semantic
    repo.write("app/main.py", "MAIN = 2\n")
    repo.write("app/new.py", "NEW = 1\n")
    repo.write("tests/test_new.py", "def test_new():\n    assert True\n")
    repo.write("README.md", "changed\n")


def promote(repo, snapshot_sha):
    epoch = E.make_epoch(E.Git(repo.path), snapshot_sha, epoch_id="synthetic", full_run={"status": "ATTESTED_BY_OWNER", "run_id": "1", "sha": snapshot_sha})
    repo.write(E.TRUSTED_EPOCH_PATH, E.canonical(epoch).decode())
    return epoch


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    """TRUSTED world: epoch.json committed at the trusted base M (promotion accepted), head A_t declares its change. BOOT world: base E has NO epoch;
    the head carries a candidate. SECOND: R = A_t merged (base moved on); the epoch is NOT re-promoted."""
    r = Repo(tmp_path_factory.mktemp("v5"))
    e_sha = _seed(r)
    epoch = promote(r, e_sha)
    m_sha = r.commit("promote epoch (owner reviewed)")
    legit_change(r)
    a_t, delta_t = with_delta(r, m_sha)
    r.checkout(e_sha)                            # bootstrap world: no trusted epoch at the base, a candidate at the head
    legit_change(r)
    r.write(E.CANDIDATE_EPOCH_PATH, E.canonical(epoch).decode())
    a_b, _ = with_delta(r, e_sha)
    r.checkout(a_t)                              # SECOND world: A_t is accepted and merged; R (the new tip) = A_t; the epoch is NOT re-promoted
    r_sha = a_t
    return {"r": r, "E": e_sha, "M": m_sha, "A_t": a_t, "A_b": a_b, "R": r_sha, "epoch": epoch, "epoch_bytes": E.canonical(epoch), "delta": delta_t}


def ver(w, head, base, **kw):
    kw.setdefault("tool_source", "TRUSTED_BASE")
    kw.setdefault("trusted_ref_tip", base)
    return E.verify(w["r"].path, head, base, **kw)


def codes(rec):
    return {f["code"] for f in rec["failures"]} | {u["code"] for u in rec["unknowns"]}


def _bare_pass_absent(rec):
    """No bare ``PASS`` / ``FAIL`` string value anywhere in the verdict JSON: integrity and authorization are never conflated."""
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
        else:
            yield o
    return not any(v in ("PASS", "FAIL") for v in walk(rec))


# ---------------------------------------------------------------------------------------------------------------------------------- mutations
def edit(fn):
    def mutate(w):
        fn(w["r"], w)
        return {"head": w["r"].commit("tamper B")}
    return mutate


def write_file(rel, text="EVIL = 1\n", mode=None):
    return lambda r, w: r.write(rel, text, mode)


def _symlink(rel, target="/etc/passwd"):
    def go(r, w):
        p = r.path / rel
        if p.exists() or p.is_symlink():
            p.unlink()
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, p)
    return go


def _gitlink(r, w):
    (r.path / "utils" / "lab_vendor").mkdir(parents=True, exist_ok=True)
    r.git("update-index", "--add", "--cacheinfo", "160000,%s,utils/lab_vendor" % r.git("rev-parse", "HEAD"))
    r.write(".gitmodules", '[submodule "x"]\n\tpath = utils/lab_vendor\n\turl = ./x\n')


def _delete(rel):
    return lambda r, w: r.git("rm", "-q", rel)


def _rename(src, dst):
    return lambda r, w: (r.path / dst).parent.mkdir(parents=True, exist_ok=True) or r.git("mv", src, dst)


def _chmod(rel):
    return lambda r, w: os.chmod(r.path / rel, 0o755)


def declared(fn):
    """The SAME tamper, but fully declared by an exact base-relative delta (integrity holds; the class decides the verdict)."""
    def mutate(w):
        r = w["r"]
        fn(r, w)
        head, _ = with_delta(r, w["M"], "declare tamper")
        return {"head": head}
    return mutate


def delta_edit(edit_fn):
    def mutate(w):
        d = json.loads((w["r"].path / E.DELTA_PATH).read_text())
        edit_fn(d)
        w["r"].write(E.DELTA_PATH, E.canonical(d).decode() if d is not None else "")
        return {"head": w["r"].commit("tamper delta")}
    return mutate


def raw_delta(raw_fn):
    def mutate(w):
        w["r"].write(E.DELTA_PATH, raw_fn((w["r"].path / E.DELTA_PATH).read_text()))
        return {"head": w["r"].commit("tamper delta bytes")}
    return mutate


# ---------------------------------------------------------------------------------------------------------------------------------- the matrix
# name, world, mutation, expected codes (subset), expected integrity of B
FAIL, UNK, PASS = "INTEGRITY_FAIL", "UNKNOWN", "INTEGRITY_PASS"
G_UNDECLARED = [   # (id, rel path, op) - the audit's G1-G24 as synthetic equivalents, undeclared
    ("G1", write_file("conftest.py", "import os\n"), {"UNDECLARED_ADD"}),
    ("G2", write_file("sitecustomize.py", "import os\n"), {"UNDECLARED_ADD"}),
    ("G3", write_file("tools/governance_history_gate.py", "GOV = 0\n"), {"UNDECLARED_CHANGE"}),
    ("G4", write_file("deploy/scripts/start_prod.sh", "echo evil\n"), {"UNDECLARED_CHANGE"}),
    ("G5", write_file("deploy/nginx/app.conf", "server { evil }\n"), {"UNDECLARED_CHANGE"}),
    ("G6", write_file("main_api.py", "API = 0\n"), {"UNDECLARED_CHANGE"}),
    ("G7", write_file("utils/financial.py", "FIN = 0\n"), {"UNDECLARED_CHANGE"}),
    ("G8", write_file("finco_radar/mod.py", "RADAR = 0\n"), {"UNDECLARED_CHANGE"}),
    ("G9", write_file("static/app.js", "var evil;\n"), {"UNDECLARED_CHANGE"}),
    ("G10", _delete("tests/test_wf07_revenue_csrf.py"), {"UNDECLARED_DELETE_OR_RENAME"}),
    ("G11", write_file("tests/test_f04_signing_secret_fail_closed.py", "def test_sign():\n    pass\n"), {"UNDECLARED_CHANGE"}),
    ("G12", write_file("tests/test_finval_f01_native_identity.py", "def test_f01():\n    pass\n"), {"UNDECLARED_CHANGE"}),
    ("G13", write_file("secrets.py", "SECRET = 1\n"), {"UNDECLARED_ADD"}),
    ("G14", _symlink("static/lab_link", "../.env"), {"NON_REGULAR_MODE"}),
    ("G15", _gitlink, {"NON_REGULAR_MODE"}),
    ("G16", write_file("App/lab.py", "LAB = 1\n"), {"UNDECLARED_ADD", "CASEFOLD_COLLISION"}),
    ("G17", write_file(".gitignore", "app/data/*\napp/lab_hidden.py\n"), {"UNDECLARED_CHANGE"}),
    ("G18", write_file("frontend/package.json", '{"evil":1}\n'), {"UNDECLARED_CHANGE"}),
    ("G19", write_file("frontend/vite.config.ts", "export default {evil: 1}\n"), {"UNDECLARED_CHANGE"}),
    ("G20", write_file("lab_pkg/__init__.py", "LAB = 1\n"), {"UNDECLARED_ADD"}),
    ("G21", _chmod("utils/cache.py"), {"UNDECLARED_MODE_CHANGE"}),
    ("G22", write_file("docs/ci_v5/README.md", "edited\n"), {"UNDECLARED_CHANGE"}),
    ("G23", write_file("docs/ci_v5/bootstrap/SOURCE_SUCCESSOR.json", '{"x":1}\n'), {"UNDECLARED_CHANGE"}),
    ("G24", write_file("tests/browser_model_mutation.py", "BROWSER = 0\n"), {"UNDECLARED_CHANGE"}),
    ("GA3", lambda r, w: (r.write("brand_new_top/x.py", "X = 1\n"), r.write("sitecustomize.py", "X = 1\n"), r.write("docs/NEW.md", "n\n")), {"UNDECLARED_ADD"}),
]
G_DECLARED_VERDICT = {   # the same tamper once DECLARED: the approval class decides - S / unclassified are never better than UNKNOWN
    "G1": UNK, "G2": UNK, "G3": UNK, "G4": PASS, "G5": PASS, "G6": PASS, "G7": PASS, "G8": PASS, "G9": PASS, "G10": UNK, "G11": UNK, "G12": UNK, "G13": UNK,
    "G14": FAIL, "G15": FAIL, "G16": FAIL, "G17": PASS, "G18": PASS, "G19": PASS, "G20": UNK, "G21": PASS, "G22": PASS, "G23": UNK, "G24": UNK, "GA3": UNK,
}
CASES = [
    ("R1_modified_guarded_byte", "t", edit(write_file("app/util.py", "UTIL = 2\n")), {"UNDECLARED_CHANGE"}, FAIL),
    ("R2_added_guarded_file", "t", edit(write_file("app/evil.py")), {"UNDECLARED_ADD"}, FAIL),
    ("R3_deleted_guarded_file", "t", edit(_delete("financial_engine/calc.py")), {"UNDECLARED_DELETE_OR_RENAME"}, FAIL),
    ("R4_executable_bit", "t", edit(_chmod("finco_core/core.py")), {"UNDECLARED_MODE_CHANGE"}, FAIL),
    ("R5_symlink_replaces_file", "t", edit(_symlink("app/util.py")), {"NON_REGULAR_MODE"}, FAIL),
    ("R7_workflow_added", "t", edit(write_file(".github/workflows/evil.yml", "name: evil\n")), {"UNDECLARED_ADD"}, FAIL),
    ("R8_rename_guarded_to_unguarded_dir", "t", edit(_rename("app/util.py", "utils/util.py")), {"UNDECLARED_DELETE_OR_RENAME", "UNDECLARED_ADD"}, FAIL),
    ("unsafe_path_space", "t", edit(write_file("app/a b.py", "X = 1\n")), {"UNSAFE_PATH"}, FAIL),
    ("unsafe_path_non_ascii", "t", edit(write_file("app/café.py", "X = 1\n")), {"UNSAFE_PATH"}, FAIL),
    ("casefold_collision_declared", "t", declared(lambda r, w: (r.write("app/Util.py", "UTIL = 1\n"))), {"CASEFOLD_COLLISION"}, FAIL),
    ("casefold_directory_collision_declared", "t", declared(lambda r, w: r.write("App/lab.py", "LAB = 1\n")), {"CASEFOLD_COLLISION"}, FAIL),
    ("A1_declared_nonsemantic", "t", declared(lambda r, w: r.write("app/util.py", "UTIL = 2\n")), set(), PASS),
    ("A2_declared_new_route_file", "t", declared(write_file("app/new_router.py", "from fastapi import APIRouter\n")), {"SEMANTIC_INVARIANT_NOT_EVALUATED"}, UNK),
    ("A3_declared_semantic_inventory_path", "t", declared(write_file(SEMANTIC_LITERAL, "ROUTER = 2\n")), {"SEMANTIC_INVARIANT_NOT_EVALUATED"}, UNK),
    ("A4_declared_delete_of_test_infrastructure", "t", declared(_delete("tests/conftest.py")), {"SEMANTIC_INVARIANT_NOT_EVALUATED"}, UNK),
    ("test_retirement_declared", "t", declared(_delete("tests/test_calc.py")), {"SEMANTIC_INVARIANT_NOT_EVALUATED"}, UNK),
    ("T3c_silent_revert_with_empty_delta", "n", edit(write_file("app/main.py", "MAIN = 1\n")), {"UNDECLARED_CHANGE"}, FAIL),
    ("T3d_new_change_inheriting_previous_delta", "n", edit(write_file("app/other.py", "OTHER = 1\n")), {"UNDECLARED_ADD"}, FAIL),
    ("T4b_delta_path_traversal", "t", delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/../x.py", "blob": "1" * 40, "mode": "100644", "class": "P"})), {"DELTA_BAD_PATH"}, FAIL),
    ("T4c_delta_noncanonical_bytes", "t", raw_delta(lambda t: json.dumps(json.loads(t), separators=(",", ":")) + "\n"), {"DELTA_NONCANONICAL"}, FAIL),
    ("T4d_delta_bound_to_other_base", "t", delta_edit(lambda d: d.update(base_sha="2" * 40)), {"DELTA_BASE_MISMATCH"}, FAIL),
    ("T4d2_delta_bound_to_other_tree", "t", delta_edit(lambda d: d.update(base_tree="3" * 40)), {"DELTA_BASE_TREE_MISMATCH"}, FAIL),
    ("T4d3_delta_result_digest_forged", "t", delta_edit(lambda d: d.update(result_inventory_sha256="4" * 64)), {"DELTA_RESULT_MISMATCH"}, FAIL),
    ("T4e_delta_extra_wildcard_key", "t", delta_edit(lambda d: d.update(wildcard="*")), {"DELTA_MALFORMED"}, FAIL),
    ("T4f_delta_declares_symlink_mode", "t", delta_edit(lambda d: d["changes"][0].update(mode="120000")), {"DELTA_BAD_MODE"}, FAIL),
    ("T4g_delta_case_collision_add", "t", delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/NEW.py", "blob": "1" * 40, "mode": "100644", "class": "P"})), {"DELTA_DUPLICATE_PATH"}, FAIL),
    ("T4h_delta_declared_not_realised", "t", delta_edit(lambda d: d["changes"].append({"op": "add", "path": "app/promised.py", "blob": "1" * 40, "mode": "100644", "class": "P"})), {"DELTA_NOT_REALISED"}, FAIL),
    ("T4i_delta_is_a_symlink", "t", edit(lambda r, w: (r.write("app/util.py", "UTIL = 2\n"), _symlink(E.DELTA_PATH, "x")(r, w))), {"NON_REGULAR_MODE"}, FAIL),
    ("T4j_delta_over_max", "t", delta_edit(lambda d: d["changes"].extend({"op": "add", "path": "app/g%d.py" % i, "blob": "1" * 40, "mode": "100644", "class": "P"} for i in range(E.MAX_DELTA + 1))), {"DELTA_TOO_LARGE"}, FAIL),
    ("T4k_delta_duplicate_key", "t", raw_delta(lambda t: t.replace('"changes"', '"changes": [], "changes"', 1)), {"DELTA_NONCANONICAL"}, FAIL),
    ("delta_missing_one_change", "t", delta_edit(lambda d: d["changes"].pop(0)), {"UNDECLARED_CHANGE"}, FAIL),
    ("delta_wrong_blob", "t", delta_edit(lambda d: d["changes"][0].update(blob="0" * 40)), {"DELTA_BLOB_MISMATCH"}, FAIL),
    ("delta_wrong_class", "t", delta_edit(lambda d: d["changes"][0].update(**{"class": "S"})), {"DELTA_CLASS_MISMATCH"}, FAIL),
    ("delta_same_value_noop_modify", "t", lambda w: delta_edit(lambda d: d["changes"].append({"op": "modify", "path": "app/util.py", "blob": w["r"].inv(w["M"])["app/util.py"][1],
                                                                                         "mode": "100644", "class": "P"}))(w), {"DELTA_NOOP"}, FAIL),
    ("delta_declares_exempt_path", "t", delta_edit(lambda d: d["changes"].append({"op": "add", "path": E.DELTA_PATH, "blob": "1" * 40, "mode": "100644", "class": "D"})), {"DELTA_EXEMPT_PATH"}, FAIL),
    ("delta_unknown_schema_v1", "t", delta_edit(lambda d: d.update(schema="FINCO_CI_V5_DELTA_V1")), {"DELTA_UNKNOWN_SCHEMA"}, FAIL),
    ("V4_bound_exempt_manifest_change", "t", edit(write_file("docs/ci_v5/hardening_2b/SOURCE_SUCCESSOR.json", "{}\n")), {"SEMANTIC_INVARIANT_NOT_EVALUATED"}, UNK),
]
G_CASES = [("G_undeclared_" + g[0], "t", edit(g[1]), g[2], FAIL) for g in G_UNDECLARED] + \
          [("G_declared_" + g[0], "t", declared(g[1]), set(), G_DECLARED_VERDICT[g[0]]) for g in G_UNDECLARED]
ALL_CASES = CASES + G_CASES


def _pair(w, world):
    """(pristine A head, trusted base, trusted ref tip) per world; world 'n' = the NEXT PR after A_t merged (tip R, epoch not re-promoted)."""
    if world == "t":
        return w["A_t"], w["M"]
    if world == "n":
        return w["A_t"], w["R"]
    return w["A_b"], w["E"]


def _setup(w, world):
    r = w["r"]
    head, base = _pair(w, world)
    if world == "n":                                        # a fresh PR on top of the accepted A_t: starts from the merged state (inherits its delta.json)
        r.checkout(w["R"])
        return w["R"], w["R"]
    r.checkout(head)
    return head, base


@pytest.mark.parametrize("name,world,mutation,expected,verdict", ALL_CASES, ids=[c[0] for c in ALL_CASES])
def test_a_b_a_tamper_matrix(worlds, name, world, mutation, expected, verdict):
    w, r = worlds, worlds["r"]
    a, base = _setup(w, world)
    rec_a = ver(w, a, base, check_worktree=True)
    if world == "n":                                       # A for the next PR: the merged tip evaluated against itself (no-op PR, inherited delta ignored)
        assert rec_a["integrity"] == PASS and rec_a["notes"].get("delta_inherited_from_base") is True, rec_a["failures"] + rec_a["unknowns"]
    else:
        assert rec_a["integrity"] == PASS, (rec_a["failures"], rec_a["unknowns"])
    kw = mutation(w)
    head = kw.get("head", a)
    rec_b = ver(w, head, base, check_worktree=False)
    assert rec_b["integrity"] == verdict, (name, rec_b["failures"], rec_b["unknowns"])
    assert expected <= codes(rec_b), (name, expected, codes(rec_b))                  # attributed to the SPECIFIC guard, never to a generic exception
    assert "EVALUATOR_ERROR" not in codes(rec_b)
    assert rec_b["authorization"] == "NOT_EVALUATED" and rec_b["enforcement"] == "SHADOW" and _bare_pass_absent(rec_b)
    if verdict == PASS:
        assert rec_b["trust"]["authoritative"] is True and rec_b["full_guard_count"] > 0
    r.checkout(a)
    rec_a2 = ver(w, a, base, check_worktree=True)
    assert rec_a2["integrity"] == rec_a["integrity"] and rec_a2["failures"] == rec_a["failures"] and rec_a2["metrics"]["memo_or_cache"] == "none"
    ROWS.append({"case": name, "world": world, "A": rec_a["integrity"], "B": rec_b["integrity"], "B_codes": ";".join(sorted(codes(rec_b))),
                 "expected": ";".join(sorted(expected)) or "-", "A_prime": rec_a2["integrity"], "head_sha": head, "head_tree": rec_b["source_tree"],
                 "base_sha": base, "git_children_A": rec_a["metrics"]["git_children"]})


# ---------------------------------------------------------------------------------------------------------------------------------- trust (T1, T2a, T3, T5)
def test_T1_non_main_base_with_forged_epoch_is_never_authoritative(worlds):
    """A PR targeting a non-protected base that carries a forged epoch.json: the base is not the trusted tip -> UNKNOWN, never authoritative."""
    w, r = worlds, worlds["r"]
    r.checkout(w["E"])
    forged = json.loads(w["epoch_bytes"])
    forged["epoch_id"] = "forged"
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(forged).decode())
    fork_tip = r.commit("attacker branch carrying its own epoch")
    r.write("app/util.py", "UTIL = 66\n")
    head, _ = with_delta(r, fork_tip)
    rec = E.verify(r.path, head, fork_tip, trusted_ref_tip=w["M"], tool_source="TRUSTED_BASE")
    assert rec["integrity"] == UNK and "BASE_NOT_TRUSTED_REF_TIP" in codes(rec) and rec["trust"]["authoritative"] is False
    rec = E.verify(r.path, head, fork_tip, tool_source="TRUSTED_BASE")                 # no tip supplied at all: also UNKNOWN
    assert rec["integrity"] == UNK and "TRUSTED_REF_TIP_NOT_PROVIDED" in codes(rec) and rec["trust"]["base_state"] != "VERIFIED_TIP"


def test_T2a_stale_fork_is_not_judged_at_an_older_base(worlds):
    """The head does not contain the protected tip (a stale fork): UNKNOWN, never a pass at the author's chosen merge-base."""
    w, r = worlds, worlds["r"]
    r.checkout(w["E"])
    r.write("utils/util2.py", "X = 1\n")
    head = r.commit("stale fork edit")
    rec = ver(w, head, w["M"])
    assert rec["integrity"] == UNK and "HEAD_NOT_UP_TO_DATE" in codes(rec) and rec["failures"] == [] and not rec["trust"]["authoritative"]


def test_T3_cadence_second_pr_after_one_merge_with_epoch_unchanged(worlds):
    """T3a/T3b: PR1 (declared change) passes; after it merges the SAME epoch still anchors PR2 (no promotion after every PR); a no-op / prose PR passes."""
    w, r = worlds, worlds["r"]
    assert ver(w, w["A_t"], w["M"])["integrity"] == PASS                                  # PR1
    r.checkout(w["R"])
    r.write("README.md", "second pr\n")
    head2, _ = with_delta(r, w["R"], "pr2")
    rec = ver(w, head2, w["R"])
    assert rec["integrity"] == PASS and rec["epoch"]["commit"] == w["E"] and "epoch_drift_paths" in rec["notes"]      # epoch unchanged, drift is informational
    r.checkout(w["R"])
    rec = ver(w, w["R"], w["R"])                                                           # PR3: nothing changed at all; inherited delta is ignored
    assert rec["integrity"] == PASS and rec["delta_changes"] == 0 and rec["notes"]["delta_inherited_from_base"] is True
    r.checkout(w["R"])
    r.write("docs/ci_v5/README.md", "docs only\n")                                         # PR with ONLY a prose change and NO delta: still undeclared
    rec = ver(w, r.commit("undeclared docs"), w["R"])
    assert rec["integrity"] == FAIL and "UNDECLARED_CHANGE" in codes(rec)


def test_T3e_replay_of_a_previously_approved_delta_is_rejected(worlds):
    """A delta approved for an earlier base cannot be replayed against a later tip to roll back a fix: it is bound to base sha, base tree and result."""
    w, r = worlds, worlds["r"]
    r.checkout(w["R"])
    r.write("app/main.py", "MAIN = 1\n")                                                   # roll the approved change back ...
    r.write(E.DELTA_PATH, E.canonical(w["delta"]).decode())                                # ... replaying the OLD approved delta verbatim (identical to the merged one)
    rec = ver(w, r.commit("replay"), w["R"])
    assert rec["integrity"] == FAIL and "UNDECLARED_CHANGE" in codes(rec)                  # an inherited delta declares nothing for THIS pull request
    r.checkout(w["R"])
    older = json.loads(E.canonical(w["delta"]))
    older["base_sha"] = w["E"]                                                             # replay bound to an even older base: explicit mismatch
    r.write("app/main.py", "MAIN = 1\n")
    r.write(E.DELTA_PATH, E.canonical(older).decode())
    rec = ver(w, r.commit("replay old base"), w["R"])
    assert rec["integrity"] == FAIL and "DELTA_BASE_MISMATCH" in codes(rec)
    r.checkout(w["R"])
    forward = json.loads(E.canonical(w["delta"]))                                          # a delta that was approved for the SAME base but another result
    r.write("app/main.py", "MAIN = 1\n")
    r.write(E.DELTA_PATH, E.canonical({**forward, "base_sha": w["R"], "base_tree": r.tree(w["R"])}).decode())
    rec = ver(w, r.commit("replay rebased"), w["R"])
    assert rec["integrity"] == FAIL and {"DELTA_RESULT_MISMATCH"} <= codes(rec)


def test_T5b_replace_refs_cannot_redirect_object_identity(worlds):
    """`git replace <bad> <good>` in the evaluating clone: the tampered head is still judged by its REAL objects, and the replace ref itself is a failure."""
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    r.write("app/util.py", "UTIL = 666\n")
    bad = r.commit("tampered head")
    good = w["A_t"]
    plain = ver(w, bad, w["M"])
    assert plain["integrity"] == FAIL and "UNDECLARED_CHANGE" in codes(plain)
    r.git("replace", bad, good)
    try:
        rec = ver(w, bad, w["M"])
        assert rec["integrity"] == FAIL and {"REPLACE_REFS_PRESENT", "UNDECLARED_CHANGE"} <= codes(rec)
        raw = subprocess.run(["git", "ls-tree", "-r", bad], cwd=r.path, capture_output=True, text=True).stdout
        assert raw != subprocess.run(["git", "--no-replace-objects", "ls-tree", "-r", bad], cwd=r.path, capture_output=True, text=True).stdout   # the replacement IS active for plain git
    finally:
        r.git("replace", "-d", bad)
    assert "REPLACE_REFS_PRESENT" not in codes(ver(w, bad, w["M"]))


def test_inherited_git_environment_cannot_redirect_the_evaluation(worlds, monkeypatch, tmp_path):
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    other = Repo(tmp_path / "other")
    other.write("x.py", "x\n")
    other.commit("other")
    for k, v in {"GIT_DIR": str(other.path / ".git"), "GIT_WORK_TREE": str(other.path), "GIT_INDEX_FILE": str(tmp_path / "idx"),
                 "GIT_OBJECT_DIRECTORY": str(tmp_path / "objs"), "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(tmp_path / "alt"), "GIT_NAMESPACE": "evil",
                 "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree", "GIT_CONFIG_VALUE_0": str(tmp_path), "GIT_NO_REPLACE_OBJECTS": "0"}.items():
        monkeypatch.setenv(k, v)
    env = E.sanitized_env()
    assert not [k for k in env if k.startswith("GIT_") and k not in ("GIT_NO_REPLACE_OBJECTS", "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_CONFIG_NOSYSTEM",
                                                                  "GIT_CONFIG_GLOBAL", "GIT_ATTR_NOSYSTEM", "GIT_CONFIG_COUNT", "GIT_PAGER", "GIT_ASKPASS")]
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1" and env["GIT_CONFIG_COUNT"] == "0"
    rec = ver(w, w["A_t"], w["M"], check_worktree=True)
    assert rec["integrity"] == PASS, (rec["failures"], rec["unknowns"])


def test_ref_and_object_validation_and_no_shell_interpolation(worlds, tmp_path):
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    marker = tmp_path / "pwned"
    bad = ["HEAD", "main", w["A_t"][:12], "$(touch %s)" % marker, "; touch %s" % marker, "--output=%s" % marker, w["A_t"].upper(), ""]
    for ref in bad:
        rec = E.verify(r.path, ref, w["M"], tool_source="TRUSTED_BASE")
        assert rec["integrity"] == FAIL and "BAD_REF" in codes(rec) and rec["trust"]["authoritative"] is False, ref
        rec = E.verify(r.path, w["A_t"], w["M"], trusted_ref_tip=ref, tool_source="TRUSTED_BASE")
        assert rec["integrity"] == FAIL and "BAD_REF" in codes(rec), ref
    assert not marker.exists()
    rec = E.verify(r.path, "f" * 40, w["M"], trusted_ref_tip=w["M"], tool_source="TRUSTED_BASE")      # well-formed but absent: UNKNOWN, never a pass
    assert rec["integrity"] == UNK and "OBJECT_UNAVAILABLE" in codes(rec)
    tree = r.tree(w["A_t"])
    assert ver(w, w["A_t"], w["M"], expect_head_tree="0" * 40)["integrity"] == FAIL
    assert ver(w, w["A_t"], w["M"], expect_head_tree=tree)["integrity"] == PASS
    assert "HEAD_NOT_UP_TO_DATE" in codes(ver(w, w["M"], w["A_t"]))                                    # base newer than head: wrong base
    assert ver(w, tree, w["M"])["integrity"] == UNK                                                    # a tree id is not a commit


def test_untrusted_tool_source_can_fail_but_never_pass(worlds):
    w = worlds
    ok = E.verify(w["r"].path, w["A_t"], w["M"], trusted_ref_tip=w["M"], tool_source="UNTRUSTED_TOOL_SOURCE")
    assert ok["integrity"] == UNK and "UNTRUSTED_TOOL_SOURCE" in codes(ok) and ok["trust"]["authoritative"] is False and ok["effective"] == "NON_AUTHORITATIVE_UNKNOWN"
    w["r"].checkout(w["A_t"])
    w["r"].write("app/util.py", "UTIL = 9\n")
    bad = E.verify(w["r"].path, w["r"].commit("x"), w["M"], trusted_ref_tip=w["M"])
    assert bad["integrity"] == FAIL                                                                     # a failure under an untrusted tool is still a failure


def test_empty_or_unavailable_semantic_registry_is_unknown_never_none(worlds, monkeypatch):
    w = worlds
    assert ver(w, w["A_t"], w["M"])["integrity"] == PASS
    monkeypatch.setattr(E, "POLICY", None)
    rec = ver(w, w["A_t"], w["M"])
    assert rec["integrity"] == UNK and "SEMANTIC_REGISTRY_UNAVAILABLE" in codes(rec), (rec["failures"], rec["unknowns"])
    monkeypatch.setattr(E, "POLICY", POLICY)
    monkeypatch.setattr(POLICY, "SEMANTIC_LITERALS", ())
    assert POLICY.registry_ok() is False and POLICY.classify("app/main.py") == ("S", "SEMANTIC_REGISTRY_UNAVAILABLE")
    assert ver(w, w["A_t"], w["M"])["integrity"] == UNK


def test_S1b_semantic_authority_is_trusted_code_not_epoch_atlas(worlds):
    """The epoch's atlas is descriptive: removing every atlas row (or lying in it) cannot make a semantic edit a pass."""
    w, r = worlds, worlds["r"]
    assert w["epoch"]["atlas"] == []                                                       # S1b: a trusted epoch with atlas=[]
    r.checkout(w["M"])
    r.write(SEMANTIC_LITERAL, "ROUTER = 3\n")
    head, _ = with_delta(r, w["M"])
    rec = ver(w, head, w["M"])
    assert rec["integrity"] == UNK and "SEMANTIC_INVARIANT_NOT_EVALUATED" in codes(rec) and any(SEMANTIC_LITERAL in g for g in rec["semantic_gaps"])
    forged = dict(w["epoch"], atlas=[{"id": "x", "status": "COVERED", "semantic_paths": []}])
    assert E.load_epoch(E.canonical(forged))[0] is not None
    assert ver(w, head, w["M"], epoch_bytes=E.canonical(forged))["integrity"] == UNK


# ---------------------------------------------------------------------------------------------------------------------------------- worktree W1-W7
def _w_untracked(w):
    w["r"].write("app/evil.py", "EVIL = 1\n")


def _w_dirty(rel, text):
    return lambda w: w["r"].write(rel, text)


def _w_ignored(rel):
    return lambda w: w["r"].write(rel, "EVIL = 1\n")


def _w_skip(w):
    w["r"].write("app/main.py", "MAIN = 99\n")
    w["r"].git("update-index", "--skip-worktree", "app/main.py")


def _w_assume(w):
    w["r"].write("app/util.py", "UTIL = 99\n")
    w["r"].git("update-index", "--assume-unchanged", "app/util.py")


WORKTREE = [
    ("W1_dirty_tracked", _w_dirty("app/main.py", "MAIN = 3\n"), {"DIRTY_PATH", "WORKTREE_CONTENT_MISMATCH"}),
    ("W2_untracked_under_app", _w_untracked, {"UNTRACKED_PATH"}),
    ("W3_ignored_importable_app_data", _w_ignored("app/data/lab_hook.py"), {"IGNORED_IMPORTABLE_FILE"}),
    ("W4_ignored_pyc", _w_ignored("app/__pycache__/main.cpython-312.pyc"), {"IGNORED_IMPORTABLE_FILE"}),
    ("W5_skip_worktree_hides_dirty_file", _w_skip, {"INDEX_FLAG_HIDES_PATH", "WORKTREE_CONTENT_MISMATCH"}),
    ("W5b_assume_unchanged_hides_dirty_file", _w_assume, {"INDEX_FLAG_HIDES_PATH", "WORKTREE_CONTENT_MISMATCH"}),
    ("W6_untracked_root_conftest", _w_dirty("conftest.py", "import os\n"), {"UNTRACKED_PATH"}),
    ("W7_dirty_unguarded_tracked_file", _w_dirty("utils/financial.py", "FIN = 0\n"), {"DIRTY_PATH", "WORKTREE_CONTENT_MISMATCH"}),
    ("W8_untracked_root_sitecustomize", _w_ignored("sitecustomize.py"), {"UNTRACKED_PATH"}),
    ("W9_tracked_file_replaced_by_symlink", lambda w: (os.unlink(w["r"].path / "app/util.py"), os.symlink("/etc/hostname", w["r"].path / "app/util.py")), {"WORKTREE_PATH_MISSING_OR_NOT_REGULAR"}),
    ("W10_tracked_file_deleted_on_disk", lambda w: os.unlink(w["r"].path / "app/util.py"), {"WORKTREE_PATH_MISSING_OR_NOT_REGULAR"}),
    ("W11_mode_flipped_on_disk", lambda w: os.chmod(w["r"].path / "app/util.py", 0o755), {"WORKTREE_MODE_MISMATCH"}),
]


@pytest.mark.parametrize("name,mutate,expected", WORKTREE, ids=[c[0] for c in WORKTREE])
def test_worktree_attestation_catches_hidden_and_ignored_material(worlds, name, mutate, expected):
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    pristine = ver(w, w["A_t"], w["M"], check_worktree=True)
    assert pristine["integrity"] == PASS, (pristine["failures"], pristine["unknowns"])
    mutate(w)
    rec = ver(w, w["A_t"], w["M"], check_worktree=True)
    assert rec["integrity"] == FAIL and expected <= codes(rec), (name, codes(rec))
    r.git("update-index", "--no-skip-worktree", "app/main.py")
    r.git("update-index", "--no-assume-unchanged", "app/util.py")
    r.checkout(w["A_t"])
    again = ver(w, w["A_t"], w["M"], check_worktree=True)
    assert again["integrity"] == PASS and again["failures"] == []
    ROWS.append({"case": name, "world": "t", "A": pristine["integrity"], "B": rec["integrity"], "B_codes": ";".join(sorted(codes(rec))), "expected": ";".join(sorted(expected)),
                 "A_prime": again["integrity"], "head_sha": w["A_t"], "head_tree": rec["source_tree"], "base_sha": w["M"], "git_children_A": pristine["metrics"]["git_children"]})


def test_ignored_but_harmless_files_do_not_false_fail(worlds):
    """Disposable generated artifacts that are neither importable nor served (a log) are reported, never a false red."""
    w, r = worlds, worlds["r"]
    r.checkout(w["A_t"])
    r.write(".gitignore", (r.path / ".gitignore").read_text())            # unchanged content
    (r.path / "scratch.log").write_text("x")                              # not ignored by the synthetic .gitignore -> untracked: must FAIL
    assert "UNTRACKED_PATH" in codes(ver(w, w["A_t"], w["M"], check_worktree=True))
    (r.path / "scratch.log").unlink()
    (r.path / ".git" / "info" / "exclude").write_text("*.log\n")
    (r.path / "scratch.log").write_text("x")
    rec = ver(w, w["A_t"], w["M"], check_worktree=True)
    assert rec["integrity"] == PASS and rec["notes"]["ignored_files_not_importable"] == 1
    (r.path / ".git" / "info" / "exclude").write_text("")
    (r.path / "scratch.log").unlink()


def test_worktree_head_is_not_the_evaluated_sha(worlds):
    w, r = worlds, worlds["r"]
    r.git("checkout", "-q", "--detach", w["M"])
    assert "WORKTREE_HEAD_MISMATCH" in codes(ver(w, w["A_t"], w["M"], check_worktree=True))
    r.checkout(w["A_t"])


# ---------------------------------------------------------------------------------------------------------------------------------- promotion (2C contract)
def _promotion_world(w):
    r = w["r"]
    r.checkout(w["E"])                                         # accepted main WITHOUT an epoch is the base; the promotion PR changes only the anchor
    return w["E"]


def test_promotion_pr_is_promotion_requires_owner_never_a_pass(worlds):
    w, r = worlds, worlds["r"]
    base = _promotion_world(w)
    epoch = E.make_epoch(E.Git(r.path), base, epoch_id="promotion", full_run={"status": "ATTESTED_BY_OWNER", "run_id": "7", "sha": base})
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(epoch).decode())
    head = r.commit("promote")
    rec = ver(w, head, base)
    assert rec["transition"] == "PROMOTION_REQUIRES_OWNER" and rec["integrity"] == UNK and rec["failures"] == [] and "PROMOTION_REQUIRES_OWNER" in codes(rec)
    assert rec["authorization"] == "NOT_EVALUATED" and rec["trust"]["authoritative"] is False and rec["effective"] != PASS


def test_promotion_attacks_are_rejected(worlds):
    w, r = worlds, worlds["r"]
    base = _promotion_world(w)
    good = E.make_epoch(E.Git(r.path), base, epoch_id="p")

    def try_head(mutate_doc=None, extra=None, remove=False):
        r.checkout(base)
        doc = json.loads(E.canonical(good))
        if mutate_doc:
            mutate_doc(doc)
        if not remove:
            r.write(E.TRUSTED_EPOCH_PATH, E.canonical(doc).decode())
        if extra:
            extra()
        return ver(w, r.commit("promotion attempt"), base)

    assert try_head(lambda d: d["entries"].reverse())["integrity"] == FAIL                                               # unsorted / forged document
    rec = try_head(lambda d: d.update(entries=d["entries"][1:], entries_sha256=E.entries_digest(d["entries"][1:])))     # re-signed but untruthful snapshot
    assert rec["integrity"] == FAIL and "PROMOTION_SNAPSHOT_MISMATCH" in codes(rec)
    rec = try_head(lambda d: d.update(base_commit=w["M"], base_tree=r.tree(w["M"])))                                    # epoch of a commit that is not the accepted base
    assert rec["integrity"] == FAIL and "PROMOTION_EPOCH_NOT_BASE" in codes(rec)
    rec = try_head(extra=lambda: r.write("app/util.py", "UTIL = 666\n"))                                                 # promotion smuggling a source change
    assert rec["integrity"] == FAIL and "PROMOTION_NOT_ISOLATED" in codes(rec) and rec["transition"] == "PROMOTION_REQUIRES_OWNER"
    rec = try_head(lambda d: (d.update(schema=E.EPOCH_SCHEMA_V1)))                                                       # downgrade to the legacy schema
    assert rec["integrity"] == FAIL
    # the owner-approved anchor REMOVED again = an intentional rollback: still owner-gated, never a pass
    r.checkout(w["M"])
    r.git("rm", "-q", E.TRUSTED_EPOCH_PATH)
    rec = ver(w, r.commit("rollback"), w["M"])
    assert rec["transition"] == "PROMOTION_REQUIRES_OWNER" and rec["integrity"] == UNK
    # a tampered anchor at the BASE (forged, resigned with the wrong snapshot) can never yield a pass
    r.checkout(w["E"])
    doc = json.loads(E.canonical(good))
    doc["entries"] = doc["entries"][1:]
    doc["entries_sha256"] = E.entries_digest(doc["entries"])
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(doc).decode())
    forged_base = r.commit("forged anchor accepted by mistake")
    r.write("README.md", "after\n")
    head, _ = with_delta(r, forged_base)
    rec = ver(w, head, forged_base)
    assert rec["integrity"] == FAIL and "EPOCH_SNAPSHOT_MISMATCH" in codes(rec)
    r.checkout(w["A_t"])


def test_legacy_v1_epoch_is_readable_but_never_a_full_guard(worlds):
    w, r = worlds, worlds["r"]
    legacy = {"schema": E.EPOCH_SCHEMA_V1, "epoch_id": "legacy", "base_commit": w["E"], "base_tree": r.tree(w["E"]), "guard_prefixes": ["app/"],
              "entries": [], "entries_sha256": E.entries_digest([]), "atlas": []}
    got, problems = E.load_epoch(E.canonical(legacy))
    assert got is not None and got["legacy"] is True, problems
    rec = ver(w, w["A_t"], w["M"], epoch_bytes=E.canonical(legacy))
    assert rec["integrity"] == UNK and "LEGACY_NARROW_GUARD" in codes(rec) and rec["trust"]["guard_mode"] == "LEGACY_NARROW_GUARD"
    assert rec["trust"]["authoritative"] is False


def test_no_trusted_epoch_computes_integrity_but_can_never_pass(worlds):
    w, r = worlds, worlds["r"]
    rec = ver(w, w["A_b"], w["E"])                                       # BOOT: base has no epoch, the head only a candidate
    assert rec["integrity"] == UNK and rec["trust"]["epoch_state"] == "CANDIDATE_UNTRUSTED" and "NO_TRUSTED_EPOCH" in codes(rec) and rec["failures"] == []
    assert rec["trust"]["authoritative"] is False and rec["effective"] == "NON_AUTHORITATIVE_UNKNOWN"
    r.checkout(w["E"])
    r.write("app/util.py", "UTIL = 5\n")
    tamper = r.commit("tamper without delta in bootstrap")
    assert ver(w, tamper, w["E"])["integrity"] == FAIL                    # a tamper is still a failure without any epoch
    r.checkout(w["A_t"])


# ---------------------------------------------------------------------------------------------------------------------------------- documents / vocabulary
def test_epoch_document_validation_is_strict(worlds):
    ep = worlds["epoch"]
    assert E.load_epoch(worlds["epoch_bytes"])[0] is not None
    for mutated in ({**ep, "extra": 1}, {**ep, "entries": ep["entries"] + [ep["entries"][0]]}, {**ep, "entries": ["120000 %s\tapp/x.py" % ("a" * 40)] + ep["entries"]},
                    {**ep, "entries": ["100644 %s\t../x" % ("a" * 40)] + ep["entries"]}, {**ep, "base_commit": "short"}, {**ep, "guard": {"mode": "PREFIXES", "exempt": []}},
                    {**ep, "guard": {"mode": "ALL_TRACKED", "exempt": [], "extra": 1}}, {**ep, "policy_version": 3}):
        assert E.load_epoch(E.canonical(mutated))[0] is None
    assert E.load_epoch(worlds["epoch_bytes"] + b" ")[0] is None and E.load_epoch(b"{")[0] is None
    assert E.entries_digest(sorted(set(ep["entries"]))) == ep["entries_sha256"] and ep["guard"]["mode"] == "ALL_TRACKED"
    assert not any(e.endswith("\t" + E.DELTA_PATH) or e.endswith("\t" + E.TRUSTED_EPOCH_PATH) for e in ep["entries"])


def test_verdict_vocabulary_is_complete_and_never_bare():
    w_fields = {"integrity", "authorization", "enforcement", "source_head_sha", "source_tree", "base_sha", "epoch_sha", "delta_digest", "full_guard_count", "semantic_gaps"}
    rec = E.verify(".", "x", "y")
    assert w_fields <= set(rec) and rec["integrity"] == FAIL and rec["authorization"] == "NOT_EVALUATED" and rec["enforcement"] == "SHADOW"
    assert _bare_pass_absent(rec) and rec["schema"] == "FINCO_CI_V5_VERDICT_V2"
    assert {"INTEGRITY_PASS", "INTEGRITY_FAIL", "UNKNOWN"} >= {rec["integrity"]}


def test_all_tracked_means_every_path_is_evaluated_and_no_prefix_shortcut():
    """Every class is only a REVIEW label: ``is_guarded`` is True for every path except the delta, the V4-bound manifest and the anchor."""
    for p in ("a.py", "zzz/new/deep/file.txt", ".github/workflows/x.yml", "tools/x.py", "tests/x.py", "static/x.js", "deploy/x", "finco_radar/x.py", "frontend/x.ts", "README.md", ".gitignore"):
        assert E.is_guarded(p) and POLICY.classify(p)[0] in POLICY.CLASSES
    assert not E.is_guarded(E.DELTA_PATH) and not E.is_guarded(E.TRUSTED_EPOCH_PATH) and not E.is_guarded("docs/ci_v5/hardening_2b/SOURCE_SUCCESSOR.json")
    assert POLICY.classify("brand_new_root_file.py") == ("S", "UNCLASSIFIED") and POLICY.classify("new_top_level/x.py") == ("S", "UNCLASSIFIED")
    assert POLICY.classify("app/main.py")[0] == "P" and POLICY.classify("README.md")[0] == "D" and POLICY.classify("static/app.js")[0] == "X"


def test_inherited_semantic_registry_covers_the_current_v4_mutation_inventory():
    """Drift guard: the trusted registry must still cover every path of the V4 mutation-security inventory at THIS checkout."""
    sys.path.insert(0, str(ROOT))
    try:
        from tests import model_mutation_security_successor as S
        missing = sorted(set(S.BLOBS) - set(POLICY.SEMANTIC_LITERALS))
    finally:
        sys.path.remove(str(ROOT))
    assert not missing, "V4 mutation inventory paths missing from the trusted semantic registry: %s" % missing[:10]
    assert POLICY.registry_ok() and all(POLICY.classify(p)[0] == "S" for p in POLICY.SEMANTIC_LITERALS)


def teardown_module(module):
    out = os.environ.get("FINCO_V5_AB_OUT")
    if out and ROWS:
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
            w.writeheader()
            w.writerows(sorted(ROWS, key=lambda r: r["case"]))

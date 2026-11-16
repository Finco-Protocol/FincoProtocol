"""CI V5 epoch evaluator - SHADOW FOUNDATION (never a required check; V4 stays authoritative).

Model: a reviewed EPOCH snapshot of the protected source inventory ``(path, Git blob SHA, mode)`` bound to a commit SHA + tree SHA, plus a
finite, explicit per-PR DELTA of protected paths. ``verify`` proves, from Git OBJECTS only (never the working tree), that

    guarded inventory(HEAD) == epoch inventory (+) delta        and        guarded inventory(trusted BASE) == epoch inventory

Trust: the epoch is TRUSTED only when read from the trusted BASE commit (``docs/ci_v5/epoch.json``). An epoch read from the PR head
(``docs/ci_v5/epoch.candidate.json``) is ``CANDIDATE_UNTRUSTED``: it is evaluated for comparison but can never authorise the PR that carries
it. The trust anchor is never read from, nor modified by, the PR head. No wildcard approval: every guarded add / delete / modify / mode change
must be named in the delta with its exact new blob and mode. Nothing is cached: one ``ls-tree`` per evaluated commit, no memo across calls.

Stdlib only. Every Git call is an argv list (no shell); every ref is a validated 40-hex SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

EPOCH_SCHEMA = "FINCO_CI_V5_EPOCH_V1"
DELTA_SCHEMA = "FINCO_CI_V5_DELTA_V1"
VERDICT_SCHEMA = "FINCO_CI_V5_VERDICT_V1"
TRUSTED_EPOCH_PATH = "docs/ci_v5/epoch.json"          # trust anchor: read from the trusted BASE only
CANDIDATE_EPOCH_PATH = "docs/ci_v5/epoch.candidate.json"
DELTA_PATH = "docs/ci_v5/delta.json"
MAX_DELTA = 500
MODES = ("100644", "100755")                            # 120000 (symlink) and 160000 (gitlink) are never reviewable in schema V1
OPS = ("add", "modify", "delete")
SHA40 = re.compile(r"[0-9a-f]{40}")
SAFE_PATH = re.compile(r"[A-Za-z0-9_@+.\-]+(?:/[A-Za-z0-9_@+.\-]+)*")
EPOCH_KEYS = {"schema", "epoch_id", "base_commit", "base_tree", "guard_prefixes", "entries", "entries_sha256", "atlas"}
DELTA_KEYS = {"schema", "epoch_entries_sha256", "changes"}
CHANGE_KEYS = {"op", "path", "blob", "mode"}


class GitError(RuntimeError):
    pass


class Git:
    """Argv-only Git runner that counts its child processes (reported, never hidden)."""

    def __init__(self, root):
        self.root = str(root)
        self.children = 0

    def run(self, *args, input=None):
        self.children += 1
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        p = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=self.root, input=input, capture_output=True, env=env, timeout=180)
        if p.returncode != 0:
            raise GitError("git %s failed (%d)" % (args[0], p.returncode))
        return p.stdout


def canonical(obj):
    """The ONLY accepted serialisation: no reordered, extra or hidden byte survives a load."""
    return (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode()


def blob_id(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def entries_digest(entries):
    return hashlib.sha256("".join(e + "\n" for e in entries).encode()).hexdigest()


def entry_str(path, blob, mode):
    return "%s %s\t%s" % (mode, blob, path)


def parse_entry(text):
    meta, sep, path = text.partition("\t")
    parts = meta.split(" ")
    if not sep or len(parts) != 2 or parts[0] not in MODES or not SHA40.fullmatch(parts[1]) or not _path_ok(path):
        raise ValueError("bad entry")
    return path, parts[1], parts[0]


def _path_ok(path):
    return isinstance(path, str) and SAFE_PATH.fullmatch(path) is not None and not any(s in (".", "..") for s in path.split("/"))


def read_inventory(git, sha):
    """{path: (mode, blob-or-commit oid)} of a whole commit tree, ONE batched ``ls-tree`` (no per-file process)."""
    inventory = {}
    for rec in git.run("ls-tree", "-r", "-z", "--full-tree", sha).split(b"\0"):
        if rec:
            meta, _, name = rec.partition(b"\t")
            mode, _kind, oid = meta.decode().split()
            inventory[name.decode("utf-8", "surrogateescape")] = (mode, oid)
    return inventory


# ------------------------------------------------------------------------------------------------------------- epoch / delta documents
def make_epoch(git, commit, prefixes, extra_paths=(), epoch_id="", atlas=()):
    """CANDIDATE epoch of ``commit``: every tracked path under ``prefixes`` plus ``extra_paths`` (the V4 pinned scope). Pure function of Git objects."""
    inv = read_inventory(git, commit)
    tree = git.run("rev-parse", commit + "^{tree}").decode().strip()
    chosen = {p for p in inv if p.startswith(tuple(prefixes))} | (set(extra_paths) & set(inv))
    chosen.discard(TRUSTED_EPOCH_PATH)
    entries = sorted(entry_str(p, inv[p][1], inv[p][0]) for p in chosen)
    for e in entries:
        parse_entry(e)                                          # a guarded symlink / gitlink / unsafe path must stop generation, not be recorded
    return {"schema": EPOCH_SCHEMA, "epoch_id": epoch_id, "base_commit": commit, "base_tree": tree, "guard_prefixes": sorted(prefixes),
            "entries": entries, "entries_sha256": entries_digest(entries), "atlas": list(atlas)}


def make_delta(epoch, head_inv):
    """The finite delta that turns the epoch into the guarded inventory of ``head_inv`` (a generator for REVIEW; the verifier never trusts it)."""
    base = dict((p, (m, b)) for p, b, m in map(parse_entry, epoch["entries"]))
    guarded = lambda p: p in base or p.startswith(tuple(epoch["guard_prefixes"]))
    now = {p: (m, o) for p, (m, o) in head_inv.items() if guarded(p) and p != TRUSTED_EPOCH_PATH}
    changes = []
    for p in sorted(set(base) | set(now)):
        if p not in now:
            changes.append({"op": "delete", "path": p, "blob": None, "mode": None})
        elif p not in base:
            changes.append({"op": "add", "path": p, "blob": now[p][1], "mode": now[p][0]})
        elif base[p] != now[p]:
            changes.append({"op": "modify", "path": p, "blob": now[p][1], "mode": now[p][0]})
    return {"schema": DELTA_SCHEMA, "epoch_entries_sha256": epoch["entries_sha256"], "changes": changes}


def load_epoch(raw):
    """(epoch, problems). Rejects non-canonical bytes, unknown schema, wrong keys, bad/duplicate/unsorted entries and a forged digest."""
    problems = []
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, [("EPOCH_MALFORMED", "not JSON")]
    if not isinstance(d, dict) or d.get("schema") != EPOCH_SCHEMA:
        return None, [("EPOCH_UNKNOWN_SCHEMA", str(d.get("schema")) if isinstance(d, dict) else "not an object")]
    if raw != canonical(d):
        return None, [("EPOCH_NONCANONICAL", "bytes differ from the canonical serialisation")]
    if set(d) != EPOCH_KEYS or not isinstance(d["entries"], list) or not isinstance(d["guard_prefixes"], list) or not isinstance(d["atlas"], list):
        return None, [("EPOCH_MALFORMED", "unexpected key set or types")]
    if not (isinstance(d["base_commit"], str) and SHA40.fullmatch(d["base_commit"]) and isinstance(d["base_tree"], str) and SHA40.fullmatch(d["base_tree"])):
        return None, [("EPOCH_MALFORMED", "base_commit/base_tree must be 40-hex")]
    if not all(isinstance(p, str) and p and p == p.lstrip("/") and ".." not in p.split("/") and "\\" not in p for p in d["guard_prefixes"]):
        return None, [("EPOCH_MALFORMED", "bad guard prefix")]
    seen = set()
    for e in d["entries"]:
        try:
            path, _b, _m = parse_entry(e)
        except (ValueError, AttributeError, TypeError):
            problems.append(("EPOCH_BAD_ENTRY", str(e)[:80]))
            continue
        if path in seen:
            problems.append(("EPOCH_DUPLICATE_PATH", path))
        seen.add(path)
    if d["entries"] != sorted(d["entries"]) and not problems:
        problems.append(("EPOCH_MALFORMED", "entries are not sorted"))
    if not problems and d["entries_sha256"] != entries_digest(d["entries"]):
        problems.append(("EPOCH_DIGEST_MISMATCH", "entries_sha256 does not match the entries"))
    return (None if problems else d), problems


def epoch_map(epoch):
    return {p: (m, b) for p, b, m in map(parse_entry, epoch["entries"])}


def load_delta(raw, epoch):
    """(changes {path: change}, problems). ``changes`` is only returned when the whole delta is acceptable."""
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, [("DELTA_MALFORMED", "not JSON")]
    if not isinstance(d, dict) or d.get("schema") != DELTA_SCHEMA:
        return None, [("DELTA_UNKNOWN_SCHEMA", str(d.get("schema")) if isinstance(d, dict) else "not an object")]
    if raw != canonical(d):
        return None, [("DELTA_NONCANONICAL", "bytes differ from the canonical serialisation")]
    if set(d) != DELTA_KEYS or not isinstance(d["changes"], list):
        return None, [("DELTA_MALFORMED", "unexpected key set or types")]
    if d["epoch_entries_sha256"] != epoch["entries_sha256"]:
        return None, [("DELTA_EPOCH_MISMATCH", "delta is bound to a different epoch")]
    if len(d["changes"]) > MAX_DELTA:
        return None, [("DELTA_TOO_LARGE", "%d changes > %d: split the change or promote a new epoch" % (len(d["changes"]), MAX_DELTA))]
    base, prefixes, problems, out, folded = epoch_map(epoch), tuple(epoch["guard_prefixes"]), [], {}, {}
    base_fold = {q.casefold() for q in base}
    for c in d["changes"]:
        if not isinstance(c, dict) or set(c) != CHANGE_KEYS:
            problems.append(("DELTA_MALFORMED", "change keys"))
            continue
        p, op = c["path"], c["op"]
        if not _path_ok(p):
            problems.append(("DELTA_BAD_PATH", str(p)[:80]))
            continue
        if p in out or p.casefold() in folded:
            problems.append(("DELTA_DUPLICATE_PATH", p))
            continue
        folded[p.casefold()] = p
        if op not in OPS:
            problems.append(("DELTA_BAD_OP", "%s: %s" % (p, op)))
        elif op == "delete" and (c["blob"] is not None or c["mode"] is not None):
            problems.append(("DELTA_MALFORMED", p + ": delete carries a blob/mode"))
        elif op != "delete" and not (isinstance(c["blob"], str) and SHA40.fullmatch(c["blob"])):
            problems.append(("DELTA_MALFORMED", p + ": blob must be 40-hex"))
        elif op != "delete" and c["mode"] not in MODES:
            problems.append(("DELTA_BAD_MODE", "%s: %s" % (p, c["mode"])))
        elif op == "add" and (p in base):
            problems.append(("DELTA_BAD_OP", p + ": add of an existing epoch path"))
        elif op in ("modify", "delete") and p not in base:
            problems.append(("DELTA_BAD_OP", p + ": " + op + " of a path that is not in the epoch"))
        elif op == "modify" and base[p] == (c["mode"], c["blob"]):
            problems.append(("DELTA_NOOP", p + ": modify equals the epoch entry"))
        elif op == "add" and not p.startswith(prefixes):
            problems.append(("DELTA_OUTSIDE_GUARD", p + ": a delta cannot widen the guard"))
        elif op == "add" and p.casefold() in base_fold:
            problems.append(("DELTA_PATH_COLLISION", p + ": case-insensitive collision with an epoch path"))
        out[p] = c
    allp = set(out) | set(base)
    for p in out:                                               # a file may not collide with a directory of another guarded path
        if any(q.startswith(p + "/") for q in allp) and out[p]["op"] == "add":
            problems.append(("DELTA_PATH_COLLISION", p))
    return (None if problems else out), problems


# --------------------------------------------------------------------------------------------------------------------------- verification
def _tidy(items):
    return [{"code": c, "detail": d} for c, d in items]


def _worktree(git, head_sha, guarded, failures):
    if git.run("rev-parse", "HEAD").decode().strip() != head_sha:
        failures.append(("WORKTREE_HEAD_MISMATCH", "the checked-out HEAD is not the evaluated SHA"))
    out = git.run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames").split(b"\0")
    for rec in out:
        if len(rec) > 3:
            xy, path = rec[:2].decode(), rec[3:].decode("utf-8", "surrogateescape")
            if guarded(path):
                failures.append(("UNTRACKED_GUARDED_PATH" if xy == "??" else "DIRTY_GUARDED_PATH", path))


def verify(root, head_sha, base_sha, *, epoch_bytes=None, delta_bytes=None, expect_head_tree=None, check_worktree=False):
    """The V5 verdict. ``epoch_bytes`` given explicitly => ``EXPLICIT_UNTRUSTED`` (tests / tooling); otherwise the epoch is discovered:
    trusted BASE ``docs/ci_v5/epoch.json`` (TRUSTED_BASE), else the PR-head candidate (CANDIDATE_UNTRUSTED), else NO_EPOCH."""
    wall0, cpu0 = time.monotonic(), time.process_time()
    git = Git(root)
    failures, unknowns = [], []
    rec = {"schema": VERDICT_SCHEMA, "head_sha": head_sha, "base_sha": base_sha, "head_tree": None, "base_tree": None,
           "trust_state": "NO_EPOCH", "authoritative": False, "epoch": None, "delta_changes": 0, "coverage": {}}

    def finish(verdict=None):
        rec["verdict"] = verdict or ("FAIL" if failures else ("UNKNOWN" if unknowns else "PASS"))
        rec["authoritative"] = rec["trust_state"] == "TRUSTED_BASE" and rec["verdict"] in ("PASS", "FAIL")
        rec["effective"] = rec["verdict"] if rec["authoritative"] else ("NON_AUTHORITATIVE_" + rec["verdict"])
        rec["failures"], rec["unknowns"] = _tidy(failures), _tidy(unknowns)
        rec["metrics"] = {"wall_s": round(time.monotonic() - wall0, 3), "cpu_s": round(time.process_time() - cpu0, 3), "git_children": git.children,
                          "memo_or_cache": "none"}
        return rec

    if not (isinstance(head_sha, str) and SHA40.fullmatch(head_sha) and isinstance(base_sha, str) and SHA40.fullmatch(base_sha)):
        failures.append(("BAD_REF", "head and base must be full 40-hex commit SHAs (symbolic refs are rejected)"))
        return finish()
    try:
        names = [head_sha, head_sha + "^{tree}", base_sha, base_sha + "^{tree}"]
        out = git.run("cat-file", "--batch-check=%(objectname) %(objecttype)", input=("\n".join(names) + "\n").encode()).decode().splitlines()
        types = [ln.split(" ")[1] if ln.count(" ") == 1 else "missing" for ln in out]
        if types != ["commit", "tree", "commit", "tree"]:
            unknowns.append(("OBJECT_UNAVAILABLE", "head/base are not both present commits in this repository"))
            return finish()
        rec["head_tree"], rec["base_tree"] = out[1].split(" ")[0], out[3].split(" ")[0]
        if expect_head_tree is not None and expect_head_tree != rec["head_tree"]:
            failures.append(("HEAD_TREE_MISMATCH", "expected %s, found %s" % (expect_head_tree, rec["head_tree"])))
        try:
            git.run("merge-base", "--is-ancestor", base_sha, head_sha)
        except GitError:
            failures.append(("BASE_NOT_ANCESTOR", "the trusted base is not an ancestor of the evaluated head"))
            return finish()
        head_inv, base_inv = read_inventory(git, head_sha), read_inventory(git, base_sha)

        raw_epoch, source = epoch_bytes, "explicit"
        if raw_epoch is not None:
            rec["trust_state"] = "EXPLICIT_UNTRUSTED"
        else:
            if TRUSTED_EPOCH_PATH in base_inv and base_inv[TRUSTED_EPOCH_PATH][0] in MODES:
                raw_epoch, rec["trust_state"], source = git.run("cat-file", "blob", base_inv[TRUSTED_EPOCH_PATH][1]), "TRUSTED_BASE", "base:" + TRUSTED_EPOCH_PATH
            elif CANDIDATE_EPOCH_PATH in head_inv and head_inv[CANDIDATE_EPOCH_PATH][0] in MODES:
                raw_epoch, rec["trust_state"], source = git.run("cat-file", "blob", head_inv[CANDIDATE_EPOCH_PATH][1]), "CANDIDATE_UNTRUSTED", "head:" + CANDIDATE_EPOCH_PATH
        if TRUSTED_EPOCH_PATH in head_inv or TRUSTED_EPOCH_PATH in base_inv:        # the PR must never edit its own trust anchor
            if head_inv.get(TRUSTED_EPOCH_PATH) != base_inv.get(TRUSTED_EPOCH_PATH):
                failures.append(("TRUST_ANCHOR_MODIFIED", TRUSTED_EPOCH_PATH + " differs between the trusted base and the PR head: promotion needs owner review"))
        if raw_epoch is None:
            unknowns.append(("NO_EPOCH", "no trusted epoch at the base and no candidate at the head: V4 stays authoritative"))
            return finish()
        epoch, problems = load_epoch(raw_epoch)
        if epoch is None:
            failures.extend(problems)
            return finish()
        rec["epoch"] = {"source": source, "id": epoch["epoch_id"], "commit": epoch["base_commit"], "tree": epoch["base_tree"],
                        "entries": len(epoch["entries"]), "entries_sha256": epoch["entries_sha256"]}
        rec["coverage"] = _coverage(epoch)
        emap, prefixes = epoch_map(epoch), tuple(epoch["guard_prefixes"])
        guarded = lambda p: p in emap or (p.startswith(prefixes) and p != TRUSTED_EPOCH_PATH)

        # the epoch must be a truthful snapshot of the commit it names, and that commit must be accepted history of the trusted base
        etypes = git.run("cat-file", "--batch-check=%(objectname) %(objecttype)", input=("%s\n%s^{tree}\n" % (epoch["base_commit"], epoch["base_commit"])).encode()).decode().splitlines()
        if [ln.split(" ")[-1] for ln in etypes] != ["commit", "tree"]:
            unknowns.append(("EPOCH_COMMIT_UNAVAILABLE", "the epoch's pinned commit is not present in this repository"))
        else:
            if etypes[1].split(" ")[0] != epoch["base_tree"]:
                failures.append(("EPOCH_TREE_NOT_OWNED", "the pinned SHA does not own the declared tree"))
            else:
                einv = base_inv if epoch["base_commit"] == base_sha else read_inventory(git, epoch["base_commit"])
                snap = {p: v for p, v in einv.items() if guarded(p)}
                if snap != emap:
                    failures.append(("EPOCH_SNAPSHOT_MISMATCH", "epoch entries differ from the pinned commit's guarded inventory (%d paths)" % len(set(snap) ^ set(emap) | {p for p in emap if snap.get(p) != emap[p]})))
            try:
                git.run("merge-base", "--is-ancestor", epoch["base_commit"], base_sha)
            except GitError:
                failures.append(("EPOCH_NOT_ACCEPTED_HISTORY", "the epoch's pinned commit is not an ancestor of the trusted base"))

        base_g = {p: v for p, v in base_inv.items() if guarded(p)}
        if base_g != emap:
            drift = sorted({p for p in set(base_g) | set(emap) if base_g.get(p) != emap.get(p)})
            unknowns.append(("EPOCH_STALE_AT_BASE", "%d guarded paths at the trusted base differ from the epoch (re-promote the epoch): %s" % (len(drift), ", ".join(drift[:5]))))

        if delta_bytes is None and DELTA_PATH in head_inv and head_inv[DELTA_PATH][0] in MODES:
            delta_bytes = git.run("cat-file", "blob", head_inv[DELTA_PATH][1])
        if delta_bytes is None:
            changes = {}                                                          # no delta file == nothing declared: any guarded change fails below
        else:
            changes, problems = load_delta(delta_bytes, epoch)
            if changes is None:
                failures.extend(problems)
                changes = {}
        rec["delta_changes"] = len(changes)

        expected = dict(emap)
        for p, c in changes.items():
            if c["op"] == "delete":
                expected.pop(p, None)
            else:
                expected[p] = (c["mode"], c["blob"])
        head_g = {p: v for p, v in head_inv.items() if guarded(p) or p in changes}
        for p, (mode, oid) in sorted(head_g.items()):
            if p == TRUSTED_EPOCH_PATH:
                continue
            if mode not in MODES:
                failures.append(("NON_REGULAR_MODE", "%s: mode %s (symlink/gitlink are never reviewable)" % (p, mode)))
            elif not SAFE_PATH.fullmatch(p) or any(s in (".", "..") for s in p.split("/")):
                failures.append(("UNSAFE_PATH", p))
            elif p not in expected:
                failures.append(("UNDECLARED_ADD" if p not in changes else "DELTA_NOT_REALISED", p))
            elif expected[p] != (mode, oid):
                kind = "UNDECLARED_MODE_CHANGE" if expected[p][1] == oid else ("UNDECLARED_CHANGE" if p not in changes else "DELTA_BLOB_MISMATCH")
                failures.append((kind, "%s: expected %s %s, found %s %s" % (p, expected[p][0], expected[p][1][:12], mode, oid[:12])))
        for p in sorted(set(expected) - set(head_g)):
            failures.append(("UNDECLARED_DELETE_OR_RENAME" if p not in changes else "DELTA_NOT_REALISED", p))
        rec["semantic_gaps_touched"] = sorted(p for p in changes if p in _semantic_paths(epoch))
        if rec["semantic_gaps_touched"]:                                         # V4 judges these by AST / chain semantics V5 does not evaluate: never a V5 PASS
            unknowns.append(("SEMANTIC_INVARIANT_NOT_EVALUATED", "delta touches %d path(s) whose V4 invariant is semantic, not byte identity: %s" % (
                len(rec["semantic_gaps_touched"]), ", ".join(rec["semantic_gaps_touched"][:5]))))
        if check_worktree:
            _worktree(git, head_sha, guarded, failures)
        return finish()
    except (GitError, OSError, ValueError, subprocess.TimeoutExpired) as exc:       # fail closed: an evaluator error is never a PASS
        failures.append(("EVALUATOR_ERROR", "%s: %s" % (type(exc).__name__, exc)))
        return finish()


def _coverage(epoch):
    rows = [r for r in epoch["atlas"] if isinstance(r, dict)]
    counts = {}
    for r in rows:
        counts[r.get("status", "UNKNOWN")] = counts.get(r.get("status", "UNKNOWN"), 0) + 1
    gaps = sorted(r["id"] for r in rows if r.get("status") != "COVERED" and "id" in r)
    return {"atlas_rows": len(rows), "by_status": counts, "not_covered": gaps,
            "v4_remains_authoritative": True, "note": "V5 proves byte/mode identity of the guarded inventory only; every non-COVERED row is still judged by V4"}


def _semantic_paths(epoch):
    out = set()
    for r in epoch["atlas"]:
        if isinstance(r, dict) and r.get("semantic_paths"):
            out |= set(r["semantic_paths"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 epoch verifier (shadow; exit 0 PASS, 1 FAIL, 2 UNKNOWN).")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--epoch-file")
    ap.add_argument("--delta-file")
    ap.add_argument("--expect-head-tree")
    ap.add_argument("--check-worktree", action="store_true")
    ap.add_argument("--output")
    a = ap.parse_args(argv)
    read = lambda f: open(f, "rb").read() if f else None
    rec = verify(a.repo, a.head_sha, a.base_sha, epoch_bytes=read(a.epoch_file), delta_bytes=read(a.delta_file), expect_head_tree=a.expect_head_tree,
                 check_worktree=a.check_worktree)
    text = json.dumps(rec, indent=2, sort_keys=True) + "\n"
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        with open(a.output, "w") as fh:
            fh.write(text)
    print("CI V5 %s (%s, authoritative=%s): %d failures, %d unknowns" % (rec["verdict"], rec["trust_state"], rec["authoritative"], len(rec["failures"]), len(rec["unknowns"])))
    return {"PASS": 0, "FAIL": 1}.get(rec["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())

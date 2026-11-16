"""CI V5 CANDIDATE generator: epoch candidate + source atlas from the REAL V4 guard scope, and the explicit per-PR delta.

Generation only: it writes ``CANDIDATE_UNTRUSTED`` artifacts for human review and never promotes anything (no commit, no push). Promotion to
``docs/ci_v5/epoch.json`` is a separate owner-reviewed PR. Run it in a clean checkout of the accepted commit it snapshots (it imports that
checkout's own V4 cohort registry to learn the guard scope, exactly as the V4 central gate does).
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_v5_epoch as E  # noqa: E402

V4_UNTRACKED_PREFIXES = ("app/", "financial_engine/", "finco_core/", "domain/", ".github/")   # tests/fin_v2_cohorts.valid(): the untracked-file scope
V4_UNTRACKED_EXACT = ("main_web.py",)
POLICY = "docs/ci_v4/ci-v4-policy.json"


def _tracked(git):
    return [p.decode() for p in git.run("ls-files", "-z").split(b"\0") if p]


def control_scope(policy_patterns, tracked):
    """(prefixes, exact paths) of the V4 ``control_paths``. A pattern ``dir/**`` or ``dir/name_*`` becomes a plain prefix (over-approximating the
    guard is the safe direction); a wildcard directly under a directory (``tests/*_scope.py``) would guard every test, so it is expanded to the
    concrete tracked paths instead."""
    prefixes, exact = set(), set()
    for pat in policy_patterns:
        if pat.endswith("/**"):
            prefixes.add(pat[:-2])
        elif "*" in pat and pat.rsplit("/", 1)[-1].partition("*")[0]:
            prefixes.add(pat.partition("*")[0])
        elif "*" in pat:
            exact |= {p for p in tracked if fnmatch.fnmatch(p, pat)}
        elif pat in tracked:
            exact.add(pat)
    return prefixes, exact


def v4_scope(root):
    """{source id: set(paths)} from the checked-out accepted tree's own V4 modules."""
    sys.path.insert(0, str(root))
    try:
        from tests import fin_v2_cohorts as C
        from tests import model_mutation_security_successor as S
        git = E.Git(root)
        tracked = _tracked(git)
        pins, presentation = set(), set()
        for m in C.cohorts():
            pins |= set(m.manifest().get("source_blobs", {}))
            pat = getattr(m, "PRESENTATION", None)
            if pat is not None:
                presentation |= {p for p in tracked if pat.match(p)}
        policy = json.loads(open(os.path.join(root, POLICY)).read())
        prefixes, exact = control_scope(policy["control_paths"], tracked)
        untracked_scope = {p for p in tracked if p.startswith(V4_UNTRACKED_PREFIXES) or p in V4_UNTRACKED_EXACT}
        return {"tracked": set(tracked), "V4-COHORT-PINS": pins, "V4-RCUX-PRESENTATION": presentation, "V4-MUTATION-BLOBS": set(S.BLOBS),
                "V4-COMPOSITE-UNTRACKED-SCOPE": untracked_scope, "V4-CI-CONTROL-PATHS": {p for p in tracked if p.startswith(tuple(prefixes))} | exact,
                "control_prefixes": prefixes, "control_exact": exact, "registry": set(C.COHORT_MODULES), "cohort_count": len(list(C.cohorts()))}
    finally:
        sys.path.remove(str(root))


def build_atlas(scope, entry_paths):
    rows = []
    notes = {"V4-COHORT-PINS": "union of every registered cohort manifest's pinned source paths",
             "V4-RCUX-PRESENTATION": "paths owned by the RC-UX presentation pattern",
             "V4-MUTATION-BLOBS": "mutation-security inventory (model_mutation_security_successor.BLOBS)",
             "V4-COMPOSITE-UNTRACKED-SCOPE": "tests/fin_v2_cohorts.valid(): tracked files under app/ financial_engine/ finco_core/ domain/ .github/ + main_web.py",
             "V4-CI-CONTROL-PATHS": "docs/ci_v4/ci-v4-policy.json control_paths"}
    for sid in ("V4-COHORT-PINS", "V4-RCUX-PRESENTATION", "V4-MUTATION-BLOBS", "V4-COMPOSITE-UNTRACKED-SCOPE", "V4-CI-CONTROL-PATHS"):
        paths = scope[sid]
        missing = sorted(paths - entry_paths)
        rows.append({"id": sid, "kind": "PATH_SCOPE", "in_scope": len(paths), "covered": len(paths) - len(missing), "missing_from_epoch": missing[:20],
                     "status": "COVERED" if paths and not missing else "GAP", "note": notes[sid]})
    unguarded = len(scope["tracked"] - entry_paths)
    mut = sorted(scope["V4-MUTATION-BLOBS"])
    chain = sorted({p for p in scope["V4-COHORT-PINS"] if p.endswith("_scope.py") and p.startswith("tests/")} | {"tests/fin_v2_cohorts.py"})
    rows += [
        {"id": "V4-INV-CHANGED-PATH-OWNERSHIP", "kind": "INVARIANT", "status": "GAP", "unguarded_tracked_paths": unguarded,
         "note": "V4 requires EVERY changed path to be owned by a registered cohort; V5 evaluates only guarded paths, so %d tracked paths are not byte-evaluated (deliberate narrowing: owner decision)" % unguarded},
        {"id": "V4-INV-MUTATION-SEMANTICS", "kind": "INVARIANT", "status": "GAP", "semantic_paths": mut,
         "note": "V4 re-runs the mutation-security AST rules (S.violations); V5 proves bytes only. Unchanged bytes inherit the accepted verdict; any delta touching these paths needs V4"},
        {"id": "V4-INV-SUCCESSOR-CHAIN", "kind": "INVARIANT", "status": "GAP", "semantic_paths": chain,
         "note": "cohort registry order / forward-hook acyclicity / current_mutation_successor_valid are V4 semantics V5 does not re-evaluate"},
        {"id": "V4-INV-IGNORED-UNTRACKED-FILES", "kind": "INVARIANT", "status": "UNKNOWN",
         "note": "gitignored untracked files are invisible to git status and to V4's own ls-files --others --exclude-standard (same blind spot, not closed here)"},
        {"id": "V4-INV-TEST-EXECUTION", "kind": "INVARIANT", "status": "GAP",
         "note": "F01 / native / browser / security / tenancy / Save-CAS test EXECUTION stays in V4 and FULL; the epoch attests source bytes, never test results"},
    ]
    return rows


def candidate(root, commit):
    git = E.Git(root)
    if git.run("rev-parse", "HEAD").decode().strip() != commit or git.run("status", "--porcelain", "--untracked-files=all").strip():
        raise SystemExit("candidate generation needs a CLEAN checkout of exactly %s" % commit)
    scope = v4_scope(root)
    prefixes = sorted(set(V4_UNTRACKED_PREFIXES) | scope["control_prefixes"])
    extra = scope["V4-COHORT-PINS"] | scope["V4-RCUX-PRESENTATION"] | scope["V4-MUTATION-BLOBS"] | scope["control_exact"] | set(V4_UNTRACKED_EXACT)
    base = E.make_epoch(git, commit, prefixes, extra, epoch_id="candidate-" + commit[:12])
    paths = {E.parse_entry(e)[0] for e in base["entries"]}
    base["atlas"] = build_atlas(scope, paths)
    return base, scope


def write(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(E.canonical(obj))


def atlas_csv(epoch, scope, path):
    """One row per guarded path: which V4 scope sources named it (the source-to-epoch atlas)."""
    sources = ["V4-COHORT-PINS", "V4-RCUX-PRESENTATION", "V4-MUTATION-BLOBS", "V4-COMPOSITE-UNTRACKED-SCOPE", "V4-CI-CONTROL-PATHS"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "mode", "blob", "in_epoch", *sources, "coverage"])
        entries = {p: (m, b) for p, b, m in map(E.parse_entry, epoch["entries"])}
        for p in sorted(scope["tracked"]):
            flags = [int(p in scope[s]) for s in sources]
            if p in entries or any(flags):
                w.writerow([p, entries.get(p, ("", ""))[0], entries.get(p, ("", ""))[1], int(p in entries), *flags, "COVERED" if p in entries else "GAP"])
        w.writerow([])
        w.writerow(["# tracked paths NOT in the epoch (unguarded; V4 owns them, V5 does not evaluate)", len(scope["tracked"] - set(entries))])


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 candidate / delta generator (CANDIDATE_UNTRUSTED output; never promotes).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidate")
    c.add_argument("--repo", default=".")
    c.add_argument("--commit", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--atlas-csv")
    d = sub.add_parser("delta")
    d.add_argument("--repo", default=".")
    d.add_argument("--epoch", required=True)
    d.add_argument("--head-sha", required=True)
    d.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "candidate":
        epoch, scope = candidate(a.repo, a.commit)
        write(a.output, epoch)
        if a.atlas_csv:
            atlas_csv(epoch, scope, a.atlas_csv)
        print("candidate %s: %d guarded entries, %d atlas rows, digest %s" % (a.commit[:12], len(epoch["entries"]), len(epoch["atlas"]), epoch["entries_sha256"][:16]))
    else:
        epoch, problems = E.load_epoch(open(a.epoch, "rb").read())
        if epoch is None:
            raise SystemExit("epoch rejected: %s" % problems)
        git = E.Git(a.repo)
        delta = E.make_delta(epoch, E.read_inventory(git, a.head_sha))
        write(a.output, delta)
        print("delta: %d explicit changes bound to epoch %s" % (len(delta["changes"]), epoch["entries_sha256"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

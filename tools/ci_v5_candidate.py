"""CI V5 CANDIDATE generator, schema V2: ALL_TRACKED epoch candidate + the base-relative delta of a pull request.

Generation only: it writes ``CANDIDATE_UNTRUSTED`` artifacts for human review and never promotes anything (no commit, no push). Promotion to
``docs/ci_v5/epoch.json`` is a separate, owner-reviewed PR. Both generators are pure functions of Git OBJECTS (no import of the checkout's code).

  candidate  epoch candidate of an ACCEPTED commit (every tracked path except the exempt files and the anchor), with the FULL-run witness the owner supplies
  delta      the finite base-relative delta of a head against the trusted base tip, bound to base sha / base tree / result inventory digest

Run ``delta`` LAST: any later change to a guarded byte of the pull request invalidates the delta (``DELTA_RESULT_MISMATCH``). The delta file itself is exempt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_v5_epoch as E  # noqa: E402


def write(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(E.canonical(obj))


def candidate(root, commit, full_run=None):
    git = E.Git(root)
    if not E.SHA40.fullmatch(commit) or git.run("rev-parse", "--verify", commit + "^{commit}").decode().strip() != commit:
        raise SystemExit("--commit must be a full 40-hex commit SHA")
    return E.make_epoch(git, commit, epoch_id="candidate-" + commit[:12], full_run=full_run)


def delta(root, base_sha, head_sha):
    git = E.Git(root)
    for sha in (base_sha, head_sha):
        if not E.SHA40.fullmatch(sha):
            raise SystemExit("base and head must be full 40-hex commit SHAs")
    tree = git.run("rev-parse", base_sha + "^{tree}").decode().strip()
    return E.make_delta(E.read_inventory(git, base_sha), E.read_inventory(git, head_sha), base_sha, tree)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 candidate / delta generator (CANDIDATE_UNTRUSTED output; never promotes).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidate")
    c.add_argument("--repo", default=".")
    c.add_argument("--commit", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--full-run-id", help="hosted FULL run id that witnesses the snapshot (owner supplied; otherwise recorded as UNVERIFIED)")
    d = sub.add_parser("delta")
    d.add_argument("--repo", default=".")
    d.add_argument("--base-sha", required=True)
    d.add_argument("--head-sha", required=True)
    d.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "candidate":
        run = {"status": "ATTESTED_BY_OWNER", "run_id": a.full_run_id, "sha": a.commit} if a.full_run_id else None
        epoch = candidate(a.repo, a.commit, run)
        write(a.output, epoch)
        print("candidate %s: %d guarded entries, digest %s" % (a.commit[:12], len(epoch["entries"]), epoch["entries_sha256"][:16]))
    else:
        out = delta(a.repo, a.base_sha, a.head_sha)
        write(a.output, out)
        print("delta: %d explicit changes bound to base %s, result digest %s" % (len(out["changes"]), a.base_sha[:12], out["result_inventory_sha256"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

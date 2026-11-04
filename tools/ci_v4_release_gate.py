"""Release / deploy gate: a FULL regression PASS bound to the IDENTICAL immutable source SHA and tree.

No "latest green": the record must name exactly the release SHA and its git tree; its junit digests and counts are re-derived from
the supplied files; and the record itself is never trusted alone - the GitHub Actions run it names must be an ``ci_v4_full.yml`` run
of this repository on this exact head SHA that concluded ``success``. Any gap fails closed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GateError(ValueError):
    pass


def _need(cond, msg):
    if not cond:
        raise GateError(msg)


def verify_record(record, release_sha, release_tree, junit_files, release_gate_cfg, now=None, skip_baseline=None):
    _need(isinstance(record, dict) and record.get("schema") == "FINCO_CI_V4_FULL_RECORD_V1", "not a CI V4 FULL record")
    _need(SHA_RE.match(release_sha or "") is not None, "release sha must be a full 40-hex commit id")
    _need(record.get("tier") == "full", "record is not a FULL regression")
    _need(record.get("tested_sha") == release_sha, "FULL record is for a different sha (%s != %s)" % (record.get("tested_sha"), release_sha))
    _need(record.get("tested_tree") == release_tree, "FULL record tree differs from the release tree")
    _need(record.get("conclusion") == "pass", "FULL regression did not pass")
    c = record.get("counts") or {}
    _need(c.get("failed") == 0 and c.get("error") == 0, "FULL record reports failures/errors")
    _need(len(record.get("skipped_ids", [])) == int(c.get("skipped", 0)), "skipped nodes are not fully listed")
    # Only reviewed natural skips (node id -> count) may appear; any new or extra skip blocks the release (a skip is never a pass).
    import collections
    allowed = collections.Counter(skip_baseline or {})
    extra = collections.Counter(record.get("skipped_ids", [])) - allowed
    _need(not extra, "FULL record has skips outside the reviewed baseline: %s" % sorted(extra)[:5])
    _need(int(record.get("collected_nodes", 0)) >= int(release_gate_cfg["full_min_collected_nodes"]), "FULL collected fewer nodes than the policy floor (partial run)")
    _need(int(record.get("executed_nodes", 0)) == int(record.get("collected_nodes", -1)), "FULL executed != collected")
    _need(int(c.get("passed", 0)) + int(c.get("skipped", 0)) == int(record["executed_nodes"]), "counts do not add up")
    digests = sorted(hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in junit_files)
    _need(digests and digests == sorted(record.get("junit_sha256", [])), "junit files do not match the recorded digests")
    # Counts re-derived from the actual junit (never from the record alone).
    import xml.etree.ElementTree as ET
    total = bad = skip = 0
    for f in junit_files:
        for t in ET.parse(f).getroot().iter("testcase"):
            total += 1
            bad += t.find("failure") is not None or t.find("error") is not None
            skip += t.find("skipped") is not None
    _need(total == record["executed_nodes"] and bad == 0 and skip == int(c.get("skipped", 0)), "junit contents contradict the record")
    if record.get("finished_at"):
        age = (now or dt.datetime.now(dt.timezone.utc)) - dt.datetime.fromisoformat(record["finished_at"].replace("Z", "+00:00"))
        _need(age.days <= int(release_gate_cfg["max_age_days"]), "FULL record is older than the allowed age")
    return True


def verify_run(run, record, repo_slug, release_sha, cfg):
    """``run``: the GitHub Actions run JSON for record['run_id']. This is the authority the artifact record cannot forge."""
    _need(isinstance(run, dict) and run.get("id") == record.get("run_id"), "GitHub run id differs from the record")
    _need(run.get("head_sha") == release_sha, "GitHub run is for a different head sha")
    _need(run.get("conclusion") == "success" and run.get("status") == "completed", "GitHub run did not conclude success")
    _need(str(run.get("path", "")).startswith(cfg["full_workflow_path"]), "run is not the FULL workflow")
    _need(run.get("event") in cfg["allowed_events"], "run event %r is not an allowed FULL trigger" % run.get("event"))
    _need((run.get("repository") or {}).get("full_name") == repo_slug, "run belongs to another repository")
    _need((run.get("head_repository") or {}).get("full_name") == repo_slug, "run was built from a fork")
    _need(int(run.get("run_attempt", 1)) == int(record.get("run_attempt", 1)), "run attempt differs from the record")
    return True


def gate(record, run, junit_files, release_sha, release_tree, repo_slug, policy, skip_baseline=None):
    cfg = policy["release_gate"]
    verify_record(record, release_sha, release_tree, junit_files, cfg, skip_baseline=skip_baseline)
    verify_run(run, record, repo_slug, release_sha, cfg)
    return {"verdict": "RELEASE_ALLOWED", "sha": release_sha, "tree": release_tree, "run_id": record["run_id"],
            "skipped_ids": record["skipped_ids"], "collected_nodes": record["collected_nodes"]}


def _api(url, token):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:        # nosec: fixed api.github.com host
        return json.load(r)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Block a release unless FULL passed on this exact sha")
    ap.add_argument("--sha", required=True); ap.add_argument("--repo-slug", required=True)
    ap.add_argument("--policy", required=True); ap.add_argument("--record", required=True)
    ap.add_argument("--junit-dir", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--git-dir", default=".")
    ap.add_argument("--run-json", help="test/offline: run JSON file; the workflow queries the API instead")
    a = ap.parse_args(argv)
    try:
        policy = json.loads(Path(a.policy).read_text())
        record = json.loads(Path(a.record).read_text())
        tree = subprocess.check_output(["git", "rev-parse", a.sha + "^{tree}"], cwd=a.git_dir, stderr=subprocess.DEVNULL).decode().strip()
        if a.run_json:
            run = json.loads(Path(a.run_json).read_text())
        else:
            token = os.environ.get("GH_TOKEN", "")
            _need(token, "GH_TOKEN required to verify the FULL run with GitHub")
            run = _api("https://api.github.com/repos/%s/actions/runs/%s" % (a.repo_slug, int(record["run_id"])), token)
        baseline = json.loads((Path(a.git_dir) / policy["release_gate"]["skip_baseline"]).read_text())["skipped_nodes"]
        out = gate(record, run, sorted(Path(a.junit_dir).glob("**/*.xml")), a.sha, tree, a.repo_slug, policy, baseline)
    except (GateError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print("RELEASE BLOCKED (fail closed): %s" % exc, file=sys.stderr)
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(json.dumps({"verdict": "RELEASE_BLOCKED", "reason": str(exc), "sha": a.sha}, indent=2))
        return 1
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(out, indent=2, sort_keys=True))
    print("RELEASE ALLOWED sha=%s run=%s" % (a.sha, out["run_id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

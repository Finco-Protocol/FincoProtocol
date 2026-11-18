"""CI Performance Budget guard: one terminal, evidence-bound verdict per pull-request head SHA.

Runs ONLY from the trusted default branch (.github/workflows/ci_perf_guard.yml: ``workflow_run`` + ``schedule``). It never checks out,
imports or executes pull-request code: pull-request artifacts are DATA (size-capped zip members, parsed as XML/JSON). Stdlib only.

Verdict for one head SHA, written as the commit status ``CI Performance Budget`` on that SHA:

* every required workflow (trusted policy: exact name AND workflow path) has a ``pull_request`` run for exactly this head SHA;
* the end-to-end time = last completed required job - first required run ``created_at`` (queue included, every attempt included:
  a re-run never resets the clock) is <= ``limits.end_to_end_seconds``;
* every shard job of the CI V4 PR run lasts <= ``limits.shard_job_seconds`` (GitHub timestamps);
* the shard JUnit artifacts are the run's own, of the run's latest attempt, their zip SHA-256 equals GitHub's artifact digest, their
  metadata names this head SHA, no node appears twice, and their summed times agree with GitHub's own test-step durations;
* no node exceeds ``node_fail_seconds`` unless an exact, unexpired trusted exception caps it; no node regresses beyond the trusted
  ``performance_baseline.json`` by > 20 % AND > 120 s; no node without a baseline exceeds ``new_node_without_baseline_seconds``.

Terminal conditions (no waiting, no polling, no dependency on this guard's own completion):
* PENDING only while some required run is missing or unfinished AND the budget since the first ``created_at`` has not elapsed;
* FAILURE as soon as the budget has elapsed with anything missing/unfinished, or any rule above fails, or evidence is missing;
* SUCCESS only when every rule holds on complete, authenticated evidence.
The scheduled sweep re-judges every open pull request head that is not already FAILURE (SUCCESS is re-verified, so a status posted by
anything else is overwritten), so a stuck or never-created run turns PENDING into FAILURE. An old ``workflow_run`` event for a head that
is no longer an open pull request's current head writes nothing. A transient API failure (429, 5xx, rate-limited 403, network) writes
nothing: the existing absent/pending status keeps blocking, and the next event or sweep judges again; it is never SUCCESS.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SCHEMA = "FINCO_CI_PERFORMANCE_BUDGET_POLICY_V1"
ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "ci_v4" / "performance_budget_policy.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_DESCRIPTION = 140


class GuardError(Exception):
    """Evidence is missing, malformed or not authentic: the verdict is FAILURE (PERFORMANCE_UNVERIFIED), never PASS."""


class TransientError(Exception):
    """The GitHub API is temporarily unavailable (429, 5xx, rate-limited 403, network). No status is written: the existing status (absent
    or pending, both of which block a required check) stays, and the next event or sweep judges again. Never turned into SUCCESS."""


CLOCK_SKEW_SECONDS = 300


# ── policy ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def load_policy(path=POLICY_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_policy(data)
    return data


def validate_policy(p):
    if p.get("schema") != SCHEMA:
        raise GuardError("policy: unknown schema")
    lim = p["limits"]
    for k in ("end_to_end_seconds", "shard_job_seconds", "node_warn_seconds", "node_fail_seconds", "node_regression_min_seconds",
              "new_node_without_baseline_seconds"):
        if not isinstance(lim.get(k), (int, float)) or lim[k] <= 0:
            raise GuardError("policy: bad limit " + k)
    if not 0 < float(lim["node_regression_fraction"]) < 10:
        raise GuardError("policy: bad regression fraction")
    if lim["end_to_end_seconds"] > 2400 or lim["shard_job_seconds"] > lim["end_to_end_seconds"]:
        raise GuardError("policy: the end-to-end budget may never exceed 40 minutes")
    names = [w["name"] for w in p["required_workflows"]]
    if not names or len(names) != len(set(names)) or not all(w["path"].startswith(".github/workflows/") for w in p["required_workflows"]):
        raise GuardError("policy: required workflows must be unique, named and literal")
    if p["junit"]["workflow"] not in names:
        raise GuardError("policy: the JUnit workflow must be a required workflow")
    for e in p.get("exceptions", []):
        if not (e.get("node") and "::" in e["node"] and isinstance(e.get("max_seconds"), (int, float)) and e.get("expires")
                and e.get("reason") and e.get("evidence")):
            raise GuardError("policy: an exception must name an exact node, a cap, a reason, evidence and an expiry")
        _date(e["expires"])
    return p


def _date(s):
    return _dt.date.fromisoformat(s)


def _ts(s):
    if not s:
        raise GuardError("missing timestamp")
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# ── evidence model (plain dicts, as returned by the GitHub REST API) ─────────────────────────────────────────────────────────────────
def select_runs(policy, head_sha, runs):
    """{workflow name: [runs]} for this head SHA, pull_request event, exact name AND exact trusted workflow path (a renamed copy is ignored)."""
    want = {w["name"]: w["path"] for w in policy["required_workflows"]}
    out = {name: [] for name in want}
    for r in runs:
        if r.get("head_sha") != head_sha or r.get("event") != "pull_request":
            continue
        name = r.get("name")
        if name in want and r.get("path") == want[name]:
            out[name].append(r)
    return out


def evaluate(policy, head_sha, runs, jobs, artifacts, now, baseline, fetch_artifact):
    """Pure verdict. ``jobs``: {run_id: [jobs of the run's LATEST attempt]}; ``artifacts``: {run_id: [artifacts]};
    ``fetch_artifact(artifact) -> bytes``; ``baseline``: {node_id: seconds}. Returns {"state", "description", "details"}."""
    if not SHA40.match(head_sha or ""):
        return _verdict("failure", "PERFORMANCE_UNVERIFIED: head SHA is not a full object id", {})
    lim = policy["limits"]
    budget = float(lim["end_to_end_seconds"])
    by_name = select_runs(policy, head_sha, runs)
    every = [r for rs in by_name.values() for r in rs]
    details = {"head_sha": head_sha, "budget_s": budget, "runs": {}}
    if not every:
        return _verdict("pending", "waiting: no required run exists yet for this head", details)
    start = min(_ts(r["created_at"]) for r in every)
    if (start - now).total_seconds() > CLOCK_SKEW_SECONDS:
        return _verdict("failure", "PERFORMANCE_UNVERIFIED: a required run is created in the future (clock skew)", details)
    elapsed_now = (now - start).total_seconds()
    details["first_created_at"] = start.isoformat()
    missing, unfinished, latest = [], [], {}
    for name, rs in sorted(by_name.items()):
        if not rs:
            missing.append(name)
            continue
        r = max(rs, key=lambda r: (_ts(r["created_at"]), r["id"]))           # the newest run of this workflow for this head
        latest[name] = r
        details["runs"][name] = {"id": r["id"], "attempt": r.get("run_attempt"), "status": r.get("status"), "conclusion": r.get("conclusion")}
        if r.get("status") != "completed":
            unfinished.append(name)
    if missing or unfinished:
        waiting = ", ".join(missing + unfinished)
        if elapsed_now > budget:
            return _verdict("failure", "OVER_BUDGET: %ds elapsed, still missing/unfinished: %s" % (elapsed_now, waiting), details)
        return _verdict("pending", "waiting %ds/%ds for: %s" % (elapsed_now, budget, waiting), details)
    bad = sorted(n for n, r in latest.items() if r.get("conclusion") != "success")
    if bad:
        return _verdict("failure", "REQUIRED_WORKFLOW_NOT_SUCCESS: " + ", ".join(bad), details)
    try:
        end = None
        for name, r in latest.items():
            js = jobs.get(r["id"])
            if not js:
                raise GuardError("no jobs recorded for " + name)
            for j in js:
                if j.get("run_id") != r["id"] or j.get("head_sha") != head_sha or j.get("run_attempt") != r.get("run_attempt"):
                    raise GuardError("job %s does not belong to run %s attempt %s at this head" % (j.get("id"), r["id"], r.get("run_attempt")))
                if j.get("status") != "completed":
                    raise GuardError("job %s is not completed" % j.get("id"))
                if j.get("conclusion") == "skipped":
                    continue
                done = _ts(j["completed_at"])
                begun = _ts(j["started_at"])
                if done < begun or begun < start - _dt.timedelta(seconds=CLOCK_SKEW_SECONDS) \
                        or (done - now).total_seconds() > CLOCK_SKEW_SECONDS:
                    raise GuardError("job %s has inconsistent timestamps (clock skew or forged order)" % j.get("id"))
                end = done if end is None or done > end else end
        if end is None:
            raise GuardError("no completed job")
        e2e = (end - start).total_seconds()
        details["end_to_end_s"] = round(e2e, 1)
        if e2e > budget:
            return _verdict("failure", "OVER_BUDGET: end-to-end %ds > %ds" % (e2e, budget), details)
        verdict = _judge_tests(policy, head_sha, latest[policy["junit"]["workflow"]], jobs, artifacts, now, baseline, fetch_artifact, details)
        if verdict:
            return verdict
    except (GuardError, KeyError, ValueError, TypeError, zipfile.BadZipFile, ET.ParseError) as exc:
        return _verdict("failure", "PERFORMANCE_UNVERIFIED: %s" % exc, details)
    return _verdict("success", "within budget: end-to-end %ds <= %ds; slowest node %ds" % (
        details["end_to_end_s"], budget, details.get("slowest_node_s", 0)), details)


def _judge_tests(policy, head_sha, run, jobs, artifacts, now, baseline, fetch_artifact, details):
    cfg, lim = policy["junit"], policy["limits"]
    shard_jobs = {}
    for j in jobs[run["id"]]:
        m = re.match(cfg["shard_job_name_pattern"], j.get("name", ""))
        if m and j.get("conclusion") != "skipped":
            shard_jobs[int(m.group(1))] = j
    if not shard_jobs:
        raise GuardError("the CI V4 PR run has no shard job")
    over = {i: round((_ts(j["completed_at"]) - _ts(j["started_at"])).total_seconds()) for i, j in shard_jobs.items()}
    details["shard_job_s"] = over
    slow = {i: s for i, s in over.items() if s > lim["shard_job_seconds"]}
    if slow:
        return _verdict("failure", "SHARD_OVER_BUDGET: %s > %ds" % (slow, lim["shard_job_seconds"]), details)
    arts = {}
    for a in artifacts.get(run["id"], []):
        m = re.match(cfg["artifact_name_pattern"], a.get("name", ""))
        if not m:
            continue
        wr = a.get("workflow_run") or {}
        if wr.get("id") != run["id"] or wr.get("head_sha") != head_sha or a.get("expired"):
            raise GuardError("artifact %s is not this run's / this head's" % a.get("name"))
        i = int(m.group(1))
        if i in arts:
            raise GuardError("two artifacts for shard %d" % i)
        arts[i] = a
    if set(arts) != set(shard_jobs):
        raise GuardError("shard artifacts %s do not match shard jobs %s" % (sorted(arts), sorted(shard_jobs)))
    times, seen = {}, set()
    for i, a in sorted(arts.items()):
        if a.get("size_in_bytes", 0) > cfg["max_artifact_bytes"]:
            raise GuardError("artifact too large")
        blob = fetch_artifact(a)
        digest = "sha256:" + hashlib.sha256(blob).hexdigest()
        if a.get("digest") != digest:
            raise GuardError("artifact %s bytes do not match GitHub's digest" % a["name"])
        meta, cases = _read_shard(blob, i, cfg)
        if meta.get("sha") != head_sha or int(meta.get("shard", -1)) != i:
            raise GuardError("shard %d metadata names another head/shard" % i)
        if meta.get("pytest_exit") != 0:
            raise GuardError("shard %d pytest exit %r" % (i, meta.get("pytest_exit")))
        step = _test_step_seconds(shard_jobs[i], cfg["test_step_name_prefix"])
        total = sum(t for _, t in cases)
        ratio = total / step if step > 0 else 0.0
        tc = cfg["time_consistency"]
        if not tc["min_ratio"] <= ratio <= tc["max_ratio"]:
            raise GuardError("shard %d JUnit time %.0fs disagrees with GitHub's test step %.0fs (ratio %.2f)" % (i, total, step, ratio))
        for node, t in cases:
            if node in seen:
                raise GuardError("node appears twice: " + node)
            seen.add(node)
            times[node] = t
    details["nodes"] = len(times)
    top = sorted(times.items(), key=lambda kv: -kv[1])[:20]
    details["top20"] = [[n, round(t, 1)] for n, t in top]
    details["slowest_node_s"] = round(top[0][1], 1) if top else 0
    today = now.date()
    exc = {e["node"]: e for e in policy.get("exceptions", []) if _date(e["expires"]) >= today}
    problems = []
    for node, t in times.items():
        cap = exc[node]["max_seconds"] if node in exc else lim["node_fail_seconds"]
        if t > cap:
            problems.append("NODE_OVER_LIMIT %s %.0fs>%ds" % (node, t, cap))
        base = baseline.get(node)
        if base is None:
            if t > lim["new_node_without_baseline_seconds"]:
                problems.append("NODE_WITHOUT_BASELINE %s %.0fs" % (node, t))
        elif t > base * (1 + float(lim["node_regression_fraction"])) and t - base > lim["node_regression_min_seconds"]:
            problems.append("NODE_REGRESSION %s %.0fs vs baseline %.0fs" % (node, t, base))
    details["warnings"] = sorted("%s %.0fs" % (n, t) for n, t in times.items() if t > lim["node_warn_seconds"])
    if problems:
        details["problems"] = sorted(problems)
        return _verdict("failure", "%s (+%d more)" % (sorted(problems)[0], len(problems) - 1), details)
    return None


def _test_step_seconds(job, prefix):
    steps = [s for s in job.get("steps", []) if str(s.get("name", "")).startswith(prefix)]
    if len(steps) != 1:
        raise GuardError("shard job %s: expected exactly one test step" % job.get("name"))
    s = steps[0]
    return (_ts(s["completed_at"]) - _ts(s["started_at"])).total_seconds()


def _read_shard(blob, index, cfg):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        want = {cfg["junit_member"].format(index=index), cfg["meta_member"].format(index=index)}
        names = [i.filename for i in z.infolist()]
        if len(names) != len(set(names)):
            raise GuardError("shard %d artifact has duplicate member names" % index)
        infos = {i.filename: i for i in z.infolist()}
        if any(i.flag_bits & 0x1 for i in infos.values()):
            raise GuardError("shard %d artifact has an encrypted member" % index)
        if any((i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos.values()):
            raise GuardError("shard %d artifact has a symlink member" % index)
        if not want <= set(infos):
            raise GuardError("shard %d artifact lacks %s" % (index, sorted(want - set(infos))))
        for name in want:
            if infos[name].file_size > cfg["max_member_bytes"]:
                raise GuardError("artifact member too large")
        meta = json.loads(z.read(cfg["meta_member"].format(index=index)))
        xml = z.read(cfg["junit_member"].format(index=index))
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise GuardError("JUnit with DTD/entities is refused")
    root = ET.fromstring(xml)
    cases = []
    for tc in root.iter("testcase"):
        name, cls = tc.get("name"), tc.get("classname")
        if not name or not cls:
            raise GuardError("testcase without identity")
        t = float(tc.get("time", "nan"))
        if not t >= 0:
            raise GuardError("testcase with an invalid time")
        cases.append((_node_id(cls, name, meta.get("modules", [])), t))
    if not cases:
        raise GuardError("shard %d JUnit has no testcase" % index)
    return meta, cases


def _node_id(classname, name, modules):
    """pytest node id from JUnit classname (module dotted path, optionally followed by test class names)."""
    parts = classname.split(".")
    mods = set(modules)
    for j in range(len(parts), 0, -1):
        mod = "/".join(parts[:j]) + ".py"
        if mod in mods:
            return "::".join([mod] + parts[j:] + [name])
    return "/".join(parts) + ".py::" + name


def _verdict(state, description, details):
    if state not in ("pending", "success", "failure"):
        raise ValueError(state)
    return {"state": state, "description": description[:MAX_DESCRIPTION], "details": details}


# ── GitHub client (read: runs, jobs, artifacts; write: one commit status) ──────────────────────────────────────────────────────────
class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect (the artifact download goes to signed blob storage) WITHOUT the job token on any other host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            for h in [k for k in new.headers if k.lower() == "authorization"]:
                del new.headers[h]
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def classify_http_error(exc):
    """TransientError for retryable API failures (429, 5xx, rate-limited 403, network); GuardError (fail closed) for everything else."""
    if isinstance(exc, urllib.error.HTTPError):
        hdrs = exc.headers or {}
        if exc.code == 429 or exc.code >= 500 or (exc.code == 403 and (hdrs.get("Retry-After") or hdrs.get("X-RateLimit-Remaining") == "0")):
            return TransientError("GitHub API %d (retry later)" % exc.code)
        return GuardError("GitHub API %d" % exc.code)
    return TransientError("network: %s" % getattr(exc, "reason", exc))


class GitHub:
    MAX_RESPONSE_BYTES = 64 * 1024 * 1024

    def __init__(self, repo, token, api="https://api.github.com", opener=None):
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo or ""):
            raise GuardError("bad repository")
        self.repo, self.token, self.api = repo, token, api
        self.opener = opener or urllib.request.build_opener(_NoCredentialRedirect())

    def _req(self, method, path, body=None, raw=False, limit=None):
        if not path.startswith("/"):
            raise GuardError("only API paths are requested")
        url = self.api + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "finco-ci-perf-guard"})
        cap = limit or self.MAX_RESPONSE_BYTES
        try:
            with self.opener.open(req, timeout=60) as resp:
                payload = resp.read(cap + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise classify_http_error(exc) from None
        if len(payload) > cap:
            raise GuardError("API response larger than %d bytes" % cap)
        return payload if raw else json.loads(payload or b"null")

    MAX_PAGES = 20

    def _pages(self, path, key):
        """Every item of a paginated list, or GuardError: a truncated list (page cap reached, or fewer items than GitHub's ``total_count``)
        could hide a run, a late job or an artifact, so it is never judged (fail closed, never a shorter clock)."""
        out, page, total = [], 1, None
        while True:
            sep = "&" if "?" in path else "?"
            body = self._req("GET", "%s%sper_page=100&page=%d" % (path, sep, page))
            got = body[key]
            if not isinstance(got, list):
                raise GuardError("API list %s is malformed" % key)
            if isinstance(body.get("total_count"), int):
                total = body["total_count"] if total is None else total
            out += got
            if len(got) < 100:
                break
            if page >= self.MAX_PAGES:
                raise GuardError("API list %s truncated at %d pages" % (key, page))
            page += 1
        if total is not None and len(out) != total:
            raise GuardError("API list %s incomplete: %d of total_count %d" % (key, len(out), total))
        return out

    def runs_for(self, head_sha):
        return self._pages("/repos/%s/actions/runs?head_sha=%s&event=pull_request" % (self.repo, head_sha), "workflow_runs")

    def jobs_for(self, run):
        return self._pages("/repos/%s/actions/runs/%d/attempts/%d/jobs" % (self.repo, run["id"], run["run_attempt"]), "jobs")

    def artifacts_for(self, run):
        return self._pages("/repos/%s/actions/runs/%d/artifacts" % (self.repo, run["id"]), "artifacts")

    def download(self, artifact, limit=None):
        return self._req("GET", "/repos/%s/actions/artifacts/%d/zip" % (self.repo, artifact["id"]), raw=True, limit=limit)

    def open_pull_heads(self):
        return sorted({p["head"]["sha"] for p in self._pulls()})

    def _pulls(self):
        out, page = [], 1
        while True:
            got = self._req("GET", "/repos/%s/pulls?state=open&per_page=100&page=%d" % (self.repo, page))
            out += got
            if len(got) < 100:
                return out
            if page >= 10:
                raise GuardError("open pull request list truncated at %d pages" % page)
            page += 1

    def status(self, head_sha, context):
        got = self._req("GET", "/repos/%s/commits/%s/status" % (self.repo, head_sha))
        return next((s for s in got.get("statuses", []) if s.get("context") == context), None)

    def set_status(self, head_sha, state, description, context, target_url):
        return self._req("POST", "/repos/%s/statuses/%s" % (self.repo, head_sha),
                         {"state": state, "description": description[:MAX_DESCRIPTION], "context": context, "target_url": target_url})


def judge(gh, policy, head_sha, now, baseline):
    runs = gh.runs_for(head_sha)
    latest = {name: max(rs, key=lambda r: (_ts(r["created_at"]), r["id"]))
              for name, rs in select_runs(policy, head_sha, runs).items() if rs}
    done = [r for r in latest.values() if r.get("status") == "completed"]
    jobs = {r["id"]: gh.jobs_for(r) for r in done}
    junit_run = latest.get(policy["junit"]["workflow"])
    artifacts = {junit_run["id"]: gh.artifacts_for(junit_run)} if junit_run and junit_run.get("status") == "completed" else {}
    cap = int(policy["junit"]["max_artifact_bytes"])
    return evaluate(policy, head_sha, runs, jobs, artifacts, now, baseline, lambda a: gh.download(a, limit=cap))


def _fence_safe(text):
    return text.replace("`", "'")


def load_baseline(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != "FINCO_CI_PERFORMANCE_BASELINE_V1":
            raise GuardError("baseline: unknown schema")
        return {k: float(v) for k, v in data["nodes"].items()}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GuardError("baseline unreadable: %s" % exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("event", "sweep"))
    ap.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    a = ap.parse_args(argv)
    policy = load_policy()
    baseline = load_baseline(ROOT / policy["baseline"]["file"])
    gh = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    target = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"), gh.repo, os.environ.get("GITHUB_RUN_ID", ""))
    now = _dt.datetime.now(_dt.timezone.utc)
    if a.mode == "event":
        event = json.loads(Path(a.event_path).read_text(encoding="utf-8"))
        wr = event["workflow_run"]
        if wr.get("event") != "pull_request":
            print("not a pull_request run: nothing to judge")
            return 0
        try:
            open_heads = set(gh.open_pull_heads())
        except TransientError as exc:
            print("transient: %s; the next event or sweep judges again" % exc)
            return 1
        if wr.get("head_sha") not in open_heads:
            print("not the current head of an open pull request: nothing to judge")
            return 0                                   # a superseded/closed head never receives a status from an old event
        heads = [wr["head_sha"]]
    else:
        try:
            heads = gh.open_pull_heads()
        except TransientError as exc:
            print("transient: %s; the next sweep judges again" % exc)
            return 1
    rc = 0
    lines = []
    for sha in heads:
        if not SHA40.match(sha):
            continue
        try:
            if a.mode == "sweep":
                cur = gh.status(sha, policy["status_context"])
                if cur is not None and cur.get("state") == "failure":
                    continue                               # FAILURE is terminal; pending/absent are resolved and SUCCESS is re-verified
            v = judge(gh, policy, sha, now, baseline)
        except TransientError as exc:
            rc = 1
            lines.append("%s TRANSIENT (no status written): %s" % (sha, exc))
            continue
        except (GuardError, KeyError, ValueError, TypeError) as exc:
            v = _verdict("failure", "PERFORMANCE_UNVERIFIED: %s" % exc, {})
        if a.mode == "sweep" and v["state"] == "pending" and "first_created_at" not in v["details"]:
            continue                                       # no required run exists for this head yet: nothing to measure, no status written
        try:
            gh.set_status(sha, v["state"], v["description"], policy["status_context"], target)
        except TransientError as exc:
            rc = 1
            lines.append("%s TRANSIENT (status not written): %s" % (sha, exc))
            continue
        lines.append("%s %s: %s" % (sha, v["state"].upper(), _fence_safe(v["description"])))
        lines.append("```json\n%s\n```" % _fence_safe(json.dumps(v["details"], indent=1, sort_keys=True)[:60000]))
    text = "\n".join(lines) or "nothing to judge"
    print(text)
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as s:
            s.write("## CI Performance Budget\n" + text + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())

"""Read-only Actions transport. Service digests authenticate transfer, not test truth."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from tools.ci_v3_schema import _pairs, _invalid_constant, require

MAX_ARCHIVE = 512 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Only fixed-origin GET requests; never forward credentials to archive storage."""
    authenticated_service = True

    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get("GH_TOKEN", "")
        self.opener = urllib.request.build_opener(NoRedirect)

    def raw(self, path, archive=False):
        require(path.startswith("/repos/") and ".." not in path and "\\" not in path, "unsafe API route")
        headers = {"Accept": "application/vnd.github.object+json" if "/contents/" in path else "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request("https://api.github.com" + path, headers=headers)
        try:
            response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as exc:
            require(archive and exc.code == 302, "GitHub GET failed: " + str(exc.code))
            url = exc.headers["Location"]
            parsed = urllib.parse.urlparse(url)
            require(parsed.scheme == "https" and not parsed.username and not parsed.password
                    and parsed.hostname and any(parsed.hostname.endswith(s) for s in
                        (".blob.core.windows.net", ".actions.githubusercontent.com", ".githubusercontent.com")),
                    "untrusted artifact redirect")
            # Deliberately no API authorization header on storage requests.
            response = self.opener.open(urllib.request.Request(url), timeout=60)
        with response:
            self.last_response_date = getattr(response,"headers",{}).get("Date")
            data = response.read(MAX_ARCHIVE + 1)
        require(len(data) <= MAX_ARCHIVE, "API/archive response too large")
        return data

    def get(self, path):
        return json.loads(self.raw(path), object_pairs_hook=_pairs, parse_constant=_invalid_constant)

    def observation_time(self, path):
        from email.utils import parsedate_to_datetime
        from datetime import timezone
        import time
        self.get(path + ("&" if "?" in path else "?") + "ci_v3_clock=" + str(time.time_ns()))
        require(self.last_response_date, "authenticated service clock missing")
        observed = parsedate_to_datetime(self.last_response_date)
        require(abs((datetime.now(timezone.utc)-observed).total_seconds()) <= 30, "service/observer clock skew")
        return observed.isoformat()

    def listing(self, path, key):
        values = []
        for page in range(1, 101):
            result = self.get(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            values.extend(result[key])
            if len(result[key]) < 100:
                require(len(values) == result["total_count"], "incomplete paginated service metadata")
                return values
        raise ValueError("service pagination limit exceeded")

    def content(self, repo, revision, path):
        require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "content revision must be immutable")
        require(not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts, "unsafe content path")
        value = self.get(f"/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}?ref={revision}")
        require(value["type"] == "file", "non-file approval content")
        content = value
        if value.get("encoding") == "none":
            # The complete FINCO inventory exceeds the Contents API's 1 MB
            # inline limit. Resolve its immutable Git blob, not a mutable URL.
            require(re.fullmatch(r"[0-9a-f]{40}", value["sha"]), "invalid large-file Git blob identity")
            content = self.get(f"/repos/{repo}/git/blobs/{value['sha']}")
            require(content["sha"] == value["sha"], "large approval blob substituted")
        require(content["encoding"] == "base64", "unsupported approval content encoding")
        data = base64.b64decode(content["content"], validate=False)
        require(len(data) <= MAX_ARCHIVE and ("size" not in content or len(data) == content["size"]), "incomplete approval content")
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == value["sha"], "Git content blob substitution")
        return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_run(api, root, run_id, attempt):
    require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt > 0, "run/attempt identity")
    require(root.get("run_id") == run_id and root.get("run_attempt") == attempt,
            "run/attempt lacks independent single-experiment admission")
    repo = root["repository"]
    latest = api.get(f"/repos/{repo}/actions/runs/{run_id}")
    require(latest["run_attempt"] == attempt, "stale workflow attempt")
    run = api.get(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}")
    require(run["id"] == run_id and run["run_attempt"] == attempt
            and run["repository"]["full_name"] == repo
            and run["head_sha"] == root["workflow_head"]
            and run["event"] in (("pull_request", "push") if root.get("execution_authority") == "mandatory" else ("workflow_dispatch",))
            and run["conclusion"] not in
                ("cancelled", "failure", "timed_out", "action_required", "stale"), "wrong/cancelled workflow run")
    workflow = api.get(f"/repos/{repo}/actions/workflows/{run['workflow_id']}")
    require(workflow["path"] == root["workflow_path"], "wrong workflow identity")
    require(sha(api.content(repo, root["workflow_head"], root["workflow_path"])) == root["workflow_sha256"],
            "workflow revision/content mismatch")
    if root.get("execution_authority") == "mandatory":
        for path, expected in root["workflow_files_sha256"].items():
            require(sha(api.content(repo,root["workflow_head"],path))==expected, "mandatory reusable workflow bytes changed")
    source = api.get(f"/repos/{repo}/git/commits/{root['source']['head']}")
    require(source["sha"] == root["source"]["head"] and source["tree"]["sha"] == root["source"]["tree"],
            "service source/tree mismatch")
    controller = api.get(f"/repos/{repo}/git/commits/{root['controller_head']}")
    require(controller["tree"]["sha"] == root["controller_tree"], "controller revision/tree mismatch")
    return run


def extract_archive(data, destination):
    """Reject traversal, symlinks, duplicate paths and zip bombs before writing anything."""
    destination = Path(destination)
    require(not destination.exists(), "artifact destination already exists")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        require(len(infos) <= 50000 and sum(x.file_size for x in infos) <= MAX_ARCHIVE, "expanded artifact limit")
        seen = set()
        for member in infos:
            path = PurePosixPath(member.filename)
            require(member.orig_filename == member.filename and member.filename
                    and str(path) == member.filename.rstrip('/')
                    and not path.is_absolute() and "\\" not in member.filename
                    and ":" not in member.filename and all(p not in ("", ".", "..") for p in path.parts), "unsafe archive path")
            require(member.filename not in seen and not stat.S_ISLNK(member.external_attr >> 16), "duplicate/symlink artifact member")
            seen.add(member.filename)
        require(archive.testzip() is None, "incomplete artifact CRC")
        destination.mkdir(parents=True)
        archive.extractall(destination)


def receive(api, root, run_id, attempt, anchors, destination, expected_names):
    """Anchors arrive via protected host-job outputs (needs), never downloaded evidence."""
    run = validate_run(api, root, run_id, attempt)
    require(set(anchors) == set(expected_names), "missing/foreign independently retained anchors")
    require(len({a["artifact_id"] for a in anchors.values()}) == len(anchors), "duplicate artifact anchors")
    jobs = api.listing(f"/repos/{root['repository']}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    artifacts = api.listing(f"/repos/{root['repository']}/actions/runs/{run_id}/artifacts", "artifacts")
    wanted = {f"ci-v3-{name}-{run_id}-{attempt}" for name in anchors}
    # Other attempts can remain in the run, but cannot substitute current artifacts.
    current = [a for a in artifacts if a["name"].startswith("ci-v3-") and a["name"].endswith(f"-{run_id}-{attempt}")]
    require({a["name"] for a in current} == wanted, "unexpected/missing current-attempt artifacts")
    require(len(current) == len(anchors) and len({a["name"] for a in current}) == len(current), "missing/duplicate artifacts")
    receipts = {}
    for name, anchor in anchors.items():
        require(set(anchor) == {"artifact_id", "artifact_digest", "receipt_sha256", "job_id"}, "anchor shape")
        matching = [j for j in jobs if j["name"] == expected_names[name] and j["id"] == anchor["job_id"]]
        require(len(matching) == 1, "wrong job identity")
        job = matching[0]
        require(job["run_id"] == run_id and job["run_attempt"] == attempt and job["head_sha"] == root["workflow_head"]
                and job["status"] == "completed" and job["conclusion"] == "success", "failed/cancelled/wrong-attempt job")
        candidates = [a for a in current if a["id"] == anchor["artifact_id"] and a["name"] == f"ci-v3-{name}-{run_id}-{attempt}"]
        require(len(candidates) == 1, "artifact replacement")
        artifact = candidates[0]
        require(not artifact["expired"] and artifact["workflow_run"]["id"] == run_id
                and artifact["workflow_run"]["head_sha"] == root["workflow_head"]
                and artifact["workflow_run"]["repository_id"] == run["repository"]["id"], "artifact source/run mismatch")
        require(timestamp(job["started_at"]) <= timestamp(artifact["created_at"]) <= timestamp(artifact["updated_at"])
                <= timestamp(job["completed_at"]), "artifact outside expected job/attempt interval")
        require(artifact["digest"] == "sha256:" + anchor["artifact_digest"], "service artifact digest/anchor mismatch")
        data = api.raw(f"/repos/{root['repository']}/actions/artifacts/{artifact['id']}/zip", archive=True)
        require(sha(data) == anchor["artifact_digest"], "downloaded archive digest mismatch")
        directory = Path(destination) / name
        extract_archive(data, directory)
        receipt = directory / "receipt.json"
        require(receipt.is_file() and sha(receipt.read_bytes()) == anchor["receipt_sha256"], "missing independent host receipt anchor")
        receipts[name] = {"artifact": artifact, "job": job, "receipt_sha256": anchor["receipt_sha256"]}
    return {"provenance_authenticated": api.authenticated_service,
            "provenance_mode": "github-service-and-isolated-host-outputs" if api.authenticated_service else "mock-service",
            "receipts": receipts, "authoritative_acceptance": False}


def receive_mandatory_control(api, repository, source, binding, destination):
    """Authenticate the existing unmodified Public Safety control and proof."""
    run_id, attempt = binding['run_id'], binding['attempt']
    prefix=f'/repos/{repository}'
    latest=api.get(f'{prefix}/actions/runs/{run_id}')
    run=api.get(f'{prefix}/actions/runs/{run_id}/attempts/{attempt}')
    require(latest['run_attempt']==attempt and run['id']==run_id and run['run_attempt']==attempt
            and run['repository']['full_name']==repository and run['head_sha']==source['head']
            and run['status']=='completed' and run['conclusion']=='success', 'mandatory control run not exact/current/successful')
    workflow=api.get(f'{prefix}/actions/workflows/{run["workflow_id"]}')
    require(workflow['path']=='.github/workflows/public_safety_and_smoke.yml'
            and sha(api.content(repository,source['head'],workflow['path']))==binding['workflow_sha256'],
            'mandatory control workflow identity/bytes mismatch')
    jobs=api.listing(f'{prefix}/actions/runs/{run_id}/attempts/{attempt}/jobs','jobs')
    wrappers=[j for j in jobs if j['name']=='safety-and-smoke / tests']
    require(len(wrappers)==1 and wrappers[0]['status']=='completed' and wrappers[0]['conclusion']=='success'
            and wrappers[0]['run_id']==run_id and wrappers[0]['run_attempt']==attempt
            and wrappers[0]['head_sha']==source['head'],'stable mandatory tests context failed/missing')
    artifacts=api.listing(f'{prefix}/actions/runs/{run_id}/artifacts','artifacts')
    expected={'public-source-safety':'source-safety','public-verification-results':('safety-and-smoke / tests','safety-and-smoke / sequential / tests'),
              'public-shadow-proof':'mandatory-evidence'}
    require(set(binding['anchors'])==set(expected), 'full mandatory source/control/proof anchors required')
    for name,context_name in expected.items():
        anchor=binding['anchors'][name]
        allowed_names=context_name if isinstance(context_name,tuple) else (context_name,)
        matches=[j for j in jobs if j['id']==anchor['job_id'] and j['name'] in allowed_names]
        require(len(matches)==1,'missing exact mandatory check context')
        job=matches[0]
        require(job['status']=='completed' and job['conclusion']=='success' and job['run_id']==run_id
                and job['run_attempt']==attempt and job['head_sha']==source['head'],'mandatory job failed/stale')
        found=[a for a in artifacts if a['id']==anchor['artifact_id'] and a['name']==name]
        require(len(found)==1,'mandatory artifact missing/substituted')
        artifact=found[0]
        require(not artifact['expired'] and artifact['workflow_run']['id']==run_id
                and artifact['workflow_run']['head_sha']==source['head']
                and artifact['workflow_run']['repository_id']==run['repository']['id']
                and artifact['digest']=='sha256:'+anchor['artifact_digest'],'mandatory artifact provenance mismatch')
        require(timestamp(job['started_at']) <= timestamp(artifact['created_at'])
                <= timestamp(artifact['updated_at']) <= timestamp(job['completed_at']), 'mandatory artifact outside job interval')
        data=api.raw(f'{prefix}/actions/artifacts/{artifact["id"]}/zip',archive=True)
        require(sha(data)==anchor['artifact_digest'],'mandatory archive bytes changed')
        extract_archive(data,Path(destination)/name)
    return {'run':run,'jobs':jobs,'proof_completed_at':next(j['completed_at'] for j in jobs if j['name']=='mandatory-evidence'),
            'provenance_authenticated':api.authenticated_service}


def receive_browser_proof(api,repository,source,binding,destination):
    """Retain the separately mandatory six-role browser proof; no browser run."""
    prefix=f'/repos/{repository}';run_id=binding['run_id'];attempt=binding['attempt']
    latest=api.get(f'{prefix}/actions/runs/{run_id}')
    run=api.get(f'{prefix}/actions/runs/{run_id}/attempts/{attempt}')
    require(latest['run_attempt']==attempt and run['status']=='completed' and run['conclusion']=='success'
            and run['head_sha']==source['head'] and run['repository']['full_name']==repository,'browser run mismatch')
    workflow=api.get(f'{prefix}/actions/workflows/{run["workflow_id"]}')
    require(workflow['path']=='.github/workflows/protocol_ui_browser.yml'
            and sha(api.content(repository,source['head'],workflow['path']))==binding['workflow_sha256'],'browser workflow mismatch')
    anchor=binding['proof_anchor']
    jobs=api.listing(f'{prefix}/actions/runs/{run_id}/attempts/{attempt}/jobs','jobs')
    matching=[j for j in jobs if j['id']==anchor['job_id'] and j['name']=='mandatory-browser-evidence']
    require(len(matching)==1,'browser required context missing')
    job=matching[0]
    require(job['status']=='completed' and job['conclusion']=='success' and job['run_id']==run_id
            and job['run_attempt']==attempt and job['head_sha']==source['head'],'browser required context failed/stale')
    artifacts=api.listing(f'{prefix}/actions/runs/{run_id}/artifacts','artifacts')
    matches=[a for a in artifacts if a['id']==anchor['artifact_id'] and a['name']=='browser-mandatory-proof']
    require(len(matches)==1,'original browser proof artifact missing')
    artifact=matches[0]
    require(not artifact['expired'] and artifact['workflow_run']['id']==run_id
            and artifact['workflow_run']['head_sha']==source['head']
            and artifact['workflow_run']['repository_id']==run['repository']['id']
            and artifact['digest']=='sha256:'+anchor['artifact_digest'],'browser artifact provenance mismatch')
    require(timestamp(job['started_at'])<=timestamp(artifact['created_at'])<=timestamp(artifact['updated_at'])<=timestamp(job['completed_at']),
            'browser proof outside job interval')
    data=api.raw(f'{prefix}/actions/artifacts/{artifact["id"]}/zip',archive=True)
    require(sha(data)==anchor['artifact_digest'],'browser archive changed')
    extract_archive(data,destination)
    from tools.ci_v3_schema import read_json
    proof=read_json(Path(destination)/'browser-proof.json')
    require(proof.get('head')==source['head'] and proof.get('tree')==source['tree']
            and set(proof.get('mandatory_roles',{}))=={'protocol','import','grid','q4','outputs','consolidation'},
            'six-role browser source/coverage proof incomplete')
    require(all(p.get('exit_code')==0 and p.get('normal_exit') is True for p in proof['mandatory_roles'].values()),
            'browser role failure or abnormal exit')
    return {'proof':proof,'artifact':artifact,'job':job,'provenance_authenticated':api.authenticated_service}

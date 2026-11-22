"""CI Performance Budget guard (tools/ci_perf_guard.py, .github/workflows/ci_perf_guard.yml, docs/ci_v4/performance_budget_policy.json).

Every attack is its own test: a verdict may be SUCCESS only on complete, authentic evidence within budget; missing or forged evidence is
FAILURE (PERFORMANCE_UNVERIFIED), never PASS; PENDING exists only inside the budget window.
"""
import ast
import copy
import datetime as dt
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
T0 = dt.datetime(2026, 11, 18, 10, 0, 0, tzinfo=dt.timezone.utc)


def iso(minutes):
    return (T0 + dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def shard_zip(index, cases, sha=SHA, modules=("tests/test_x.py",), exit_code=0, extra_xml=b""):
    xml = b'<?xml version="1.0"?>' + extra_xml + b"<testsuites><testsuite>" + b"".join(
        ('<testcase classname="%s" name="%s" time="%s"/>' % (c.rsplit("::", 1)[0][:-3].replace("/", "."), c.rsplit("::", 1)[1], t)).encode()
        for c, t in cases) + b"</testsuite></testsuites>"
    meta = {"sha": sha, "shard": index, "pytest_exit": exit_code, "modules": list(modules), "tree": "b" * 40}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("junit-shard-%d.xml" % index, xml)
        z.writestr("shard-%d.json" % index, json.dumps(meta))
    return buf.getvalue()


# ── terminal conditions: pending only inside the budget ─────────────────────────────────────────────────────────────────────────────


# ── end-to-end clock: GitHub timestamps, queue and every attempt included ──────────────────────────────────────────────────────────


# ── JUnit evidence is authenticated against GitHub, never trusted on its own ───────────────────────────────────────────────────────


# ── per-node protection against slow tests ─────────────────────────────────────────────────────────────────────────────────────────


# ── policy and workflow invariants ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_guard_never_waits_polls_or_imports_repository_code():
    tree = ast.parse((ROOT / "tools/ci_perf_guard.py").read_text())
    names = {n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", None) for n in ast.walk(tree)}
    assert "sleep" not in names and "subprocess" not in names and "exec" not in names and "eval" not in names
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
    assert imported <= {"__future__", "argparse", "datetime", "hashlib", "io", "json", "os", "re", "sys", "urllib", "xml", "zipfile", "pathlib"}


# ── Correction A: public-safety reconciliation of the measured node ids ────────────────────────────────────────────────────────────
AT = chr(64)
DECORATOR_IDS = (
    'tests/test_rc7b_quarterly_csrf_successor.py::test_no_extra_content_route_writer_or_run[\\n' + AT + 'router.post("/extra")\\n'
    'async def extra():\\n    return None\\n]',
    'tests/test_rc7b_quarterly_csrf_successor.py::test_security_and_route_mutations_fail_with_or_without_byte_check['
    + AT + 'router.post("/workbook/calendar/operating-frequency")-' + AT + 'router.get("/workbook/calendar/operating-frequency")]',
)


def test_a_real_email_like_identifier_still_fails_the_unchanged_scanner(tmp_path):
    from tools import public_safety_scan as P
    assert P.EMAIL_RE.pattern == rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    leak = ("someone.private" + AT + "finco-internal.org").encode()
    (tmp_path / "x.json").write_bytes(b'{"owner": "' + leak + b'"}')
    assert P.scan_file("x.json", tmp_path) != []
    # escaping is NOT a bypass for a real address in a JSON string value of these files: the guarded tests above pin the exact count
    escaped = leak.replace(AT.encode(), b"\\u0040")
    assert json.loads(b'{"owner": "' + escaped + b'"}')["owner"].encode() == leak


# ── Correction A: guard security review (each finding is one attack) ──────────────────────────────────────────────────────────────


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, body=b"{}", exc=None):
        self.body, self.exc, self.seen = body, exc, []

    def open(self, req, timeout=None):
        self.seen.append(req)
        if self.exc:
            raise self.exc
        return _Resp(self.body)


def _http_error(code, headers=None):
    import email.message
    import urllib.error
    m = email.message.Message()
    for k, v in (headers or {}).items():
        m[k] = v
    return urllib.error.HTTPError("https://api.github.com/x", code, "x", m, None)


# ── Correction B: pagination truncation and symlink members ────────────────────────────────────────────────────────────────────────
class _PagedOpener:
    """Serves list pages: ``pages`` is a list of item lists; ``total`` is GitHub's total_count (None: omitted)."""

    def __init__(self, key, pages, total=None):
        self.key, self.pages, self.total, self.seen = key, pages, total, []

    def open(self, req, timeout=None):
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        page = int(q["page"][0])
        self.seen.append(page)
        items = self.pages[page - 1] if page <= len(self.pages) else []
        body = {self.key: items}
        if self.total is not None:
            body["total_count"] = self.total
        return _Resp(json.dumps(body).encode())


def full_run_timestamps():
    return {"run_attempt": 1, "created_at": iso(0), "run_started_at": iso(1), "updated_at": iso(45)}


def full_jobs_fixture(run, seconds=2399):
    def stamp(s):
        return iso(s / 60)

    phases = [("plan", 70, 120), ("recollect", 130, 200), ("f01 / f01", 65, 2050)]
    phases += [("shard-%d" % i, 125, 2180) for i in range(8)]
    phases += [("record", 2200, seconds)]
    return [{"id": i, "name": name, "run_id": run["id"], "run_attempt": 1, "head_sha": run["head_sha"],
             "head_branch": "main", "workflow_name": "CI V4 FULL", "status": "completed", "conclusion": "success",
             "started_at": stamp(start), "completed_at": stamp(end)}
            for i, (name, start, end) in enumerate(phases, 1)]



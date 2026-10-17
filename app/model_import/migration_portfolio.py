"""Bounded portfolio migration manifest.

A manifest is a small, SIGNED, user-carried ledger of what this server observed while assessing several
workbooks.  It is deliberately not a persistence authority:

  * nothing is stored on the server (no table, no file, no background job, no queue);
  * no workbook content, assumption value or formula text is in it - only identity hashes, counts, scenario
    labels and status codes;
  * no route grants authority from it (Apply still needs its own signed C0 review ticket, CSRF, CAS and owner);
  * it never starts a Run and never overwrites a project.

At most ``MAX_ENTRIES`` workbooks.  Entries are keyed by workbook SHA-256, so re-assessing the same file updates
its entry instead of duplicating it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth import SECRET_KEY
from app.model_import.migration_plan import CLASSES, OUTPUT
from app.model_import.workbook_inspect import clean_text

MAX_ENTRIES = 12
_TTL_SECONDS = 6 * 3600
_MAX_TOKEN_CHARS = 120_000
REVIEW_STATUSES = ("ASSESSED", "REVIEW_IN_PROGRESS", "SCALARS_APPLIED", "BLOCKED")
RECON_STATUSES = ("NOT_STARTED", "NOT_COMPARABLE", "COMPARED")


class ManifestError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SECRET_KEY, salt="finco-model-import-v1-manifest")


def empty_manifest(owner: str) -> dict:
    return {"version": 1, "owner": owner, "entries": []}


def seal_manifest(manifest: dict) -> str:
    if len(manifest["entries"]) > MAX_ENTRIES:
        raise ManifestError("MANIFEST_ENTRY_LIMIT_EXCEEDED")
    token = _serializer().dumps(manifest)
    if len(token) > _MAX_TOKEN_CHARS:
        raise ManifestError("MANIFEST_TOO_LARGE")
    return token


def unseal_manifest(token: str | None, *, owner: str) -> dict:
    if not token:
        return empty_manifest(owner)
    if not isinstance(token, str) or len(token) > _MAX_TOKEN_CHARS:
        raise ManifestError("MANIFEST_INVALID")
    try:
        body = _serializer().loads(token, max_age=_TTL_SECONDS)
    except (BadSignature, SignatureExpired) as exc:
        raise ManifestError("MANIFEST_EXPIRED_OR_TAMPERED") from exc
    if (not isinstance(body, dict) or body.get("version") != 1 or body.get("owner") != owner
            or not isinstance(body.get("entries"), list) or len(body["entries"]) > MAX_ENTRIES):
        raise ManifestError("MANIFEST_OWNER_MISMATCH")
    return body


def entry_from_plan(plan: dict, report: dict, *, candidate_project_code: str) -> dict:
    """Compact, value-free summary of one assessed workbook."""
    blockers = list(plan["macro_assessment"]["prevents_accurate_migration"])
    unsupported = sorted({w for w in report["warnings"]} | {b.split(":", 1)[0] for b in blockers})
    eligible = [s["key"] for s in plan["slices"] if s["apply_eligible"]]
    return {
        "workbook_sha256": plan["workbook"]["sha256"],
        "filename_hint": clean_text(report["filename"], 60),
        "format": report["format"], "size_bytes": report["size_bytes"], "macro_bearing": report["macro_bearing"],
        "candidate_project": clean_text(candidate_project_code, 60),
        "scenario_overall": plan["scenarios"]["overall"],
        "scenarios": [{"key": s["key"], "label": clean_text(s["label"], 40), "resolution": s["resolution"]}
                      for st in plan["scenarios"]["structures"] for s in st["scenarios"]][:8],
        "sheet_provenance": [{"sheet": clean_text(s["name"], 60), "hidden": s["hidden"], "used_rows": s["used_rows"],
                              "used_columns": s["used_columns"]} for s in report["sheets"]][:12],
        "mapping": {"direct_mapped": plan["mapping"]["direct_mapped"], "input_candidates": plan["mapping"]["input_candidates"],
                    "completeness": plan["mapping"]["input_mapping_completeness"]},
        "class_counts": {c: plan["class_counts"].get(c, 0) for c in CLASSES},
        "unsupported_features": unsupported[:16],
        "apply_eligible": bool(eligible), "apply_eligible_slices": eligible[:6],
        "review_status": "ASSESSED" if eligible else "BLOCKED",
        "reconciliation": {"status": "NOT_STARTED", "outputs_available": sum(1 for i in plan["items"] if i["class"] == OUTPUT),
                           "comparable": 0, "note": "Reconciliation is separate from input mapping completeness."},
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def upsert(manifest: dict, entry: dict) -> dict:
    entries = [e for e in manifest["entries"] if e["workbook_sha256"] != entry["workbook_sha256"]]
    if len(entries) >= MAX_ENTRIES:
        raise ManifestError("MANIFEST_ENTRY_LIMIT_EXCEEDED")
    entries.append(entry)
    return {**manifest, "entries": entries}


def mark(manifest: dict, workbook_sha256: str, *, review_status: str | None = None,
         reconciliation: dict | None = None) -> dict:
    """Record a server-observed step.  Unknown workbooks are ignored (never auto-created)."""
    out = []
    for e in manifest["entries"]:
        if e["workbook_sha256"] == workbook_sha256:
            e = dict(e)
            if review_status:
                if review_status not in REVIEW_STATUSES:
                    raise ManifestError("MANIFEST_STATUS_INVALID")
                e["review_status"] = review_status
            if reconciliation:
                if reconciliation.get("status") not in RECON_STATUSES:
                    raise ManifestError("MANIFEST_STATUS_INVALID")
                e["reconciliation"] = {**e["reconciliation"], **reconciliation}
            e["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(e)
    return {**manifest, "entries": out}


def manifest_json(manifest: dict) -> bytes:
    return json.dumps({"schema": "finco.model_import.migration_manifest.v1", "generated_at":
                       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "entries": manifest["entries"],
                       "retention": "Not stored by the server. Contains no workbook content, values or formulas."},
                      sort_keys=True, indent=2).encode("utf-8")

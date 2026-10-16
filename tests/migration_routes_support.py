"""Shared route helpers for the Excel migration tests (HTTP level; no private state)."""
from __future__ import annotations

import html
import re

from openpyxl import Workbook

from app.auth import generate_csrf_token
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from tests import migration_fixtures as F
from tests.test_model_decision_workspace_v2 import tokens

OWNER = "decision-user"

FIELDS = {"Insurance (annual)": "opex.lines.insurance", "Grid interconnection cost": "capex.C.grid_connection",
          "Cost of debt": "debt.senior.interest_rate_pct", "Audit and legal": "capex.D.audit_legal"}


def journey_workbook(*, summary_ref: str = "Inputs!B3") -> bytes:
    """Synthetic model: Base/Upside input columns, common inputs, structured/unsupported rows and outputs."""
    book = Workbook()
    inputs = book.active
    inputs.title = "Inputs"
    inputs.append(["Assumption", "Base Case", "Upside", "Unit"])
    inputs.append(["Insurance (annual)", 40, 38, "kEUR/yr"])
    inputs.append(["Grid interconnection cost", 1200000, 1100000, "EUR"])
    common = book.create_sheet("Common")
    common.append(["Assumption", "Value", "Unit"])
    common.append(["Cost of debt", "5,25 %", ""])
    common.append(["Audit and legal", 45.5, "kEUR"])
    common.append(["Transformer", 120, "kEUR"])
    common.append(["Target leverage", "=B2*2", ""])
    summary = book.create_sheet("Summary")
    summary.append(["Metric", "Value", "Unit"])
    summary.append(["Total CAPEX", f"={summary_ref}/1000+Common!B3", "kEUR"])
    summary.append(["Equity IRR", "=Common!B2*3", ""])
    summary["B3"].number_format = "0.0%"
    return F.add_cached_values(F.save(book), {("Summary", "B2"): 1245.5, ("Summary", "B3"): 0.1575, ("Common", "B5"): 10.5})


def ws_of(project):
    return get_workspace_state(OWNER, project.project_id)


def evidence(project):
    ws = ws_of(project)
    return (ws.draft_snapshot, ws.saved_snapshot, ws.dirty, ws.last_runtime_snapshot_id, ws.active_scenario_id,
            assemble_consistent_for_get(OWNER, project.project_id, WORKBOOK.version).composite_hash,
            tuple(h.history_id for h in get_run_history(OWNER, project.project_id)))


def assess(env, project, data, name="model.xlsx", manifest="", csrf=None):
    return env.client.post("/v2/workbook/import/assess", data={
        "project": project.project_code, "csrf_token": csrf or generate_csrf_token(), "manifest_token": manifest},
        files={"upload": (name, data, "application/octet-stream")})


def err(response):
    found = re.findall(r"(?:File or request rejected|Request rejected|rejected): ([A-Z0-9_]+)", response.text)
    return found or response.text[:200]


def slice_ticket(response, key):
    block = re.search(r'data-slice="%s".*?name="slice_ticket" value="([^"]+)"' % re.escape(key), response.text, re.S)
    assert block, f"no eligible slice {key}"
    return html.unescape(block.group(1))


def hidden(response, name):
    m = re.search(r'name="%s" value="([^"]*)"' % name, response.text)
    return html.unescape(m.group(1)) if m else ""


def review_slice(env, project, ticket, manifest=""):
    return env.client.post("/v2/workbook/import/review-slice", data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "slice_ticket": ticket, "manifest_token": manifest})


def ids_for(reviewed, label):
    """Every review-row id whose label is ``label`` (rows are split on the row marker, never matched across rows)."""
    ids = []
    for block in reviewed.text.split('<tr class="review-row"')[1:]:
        m = re.search(r'name="keep_(\d+)"', block)
        if m and re.search(r"<div>%s</div>" % re.escape(label), block):
            ids.append(m.group(1))
    return ids


def row_ids(reviewed):
    return {m[1].strip(): m[0] for m in re.findall(r'name="keep_(\d+)".*?<div>([^<]+)</div>', reviewed.text, re.S)}


def selection(reviewed, labels=tuple(FIELDS)):
    rows = row_ids(reviewed)
    out = {}
    for label in labels:
        out[f"keep_{rows[label]}"] = "on"
        out[f"field_{rows[label]}"] = FIELDS[label]
    return out


def confirm(env, project, preview_ticket, manifest="", scenario_confirmed=True, **selected):
    data = {"project": project.project_code, "csrf_token": generate_csrf_token(), "preview_ticket": preview_ticket,
            "manifest_token": manifest, **selected}
    if scenario_confirmed:
        data["scenario_confirmed"] = "on"
    return env.client.post("/v2/workbook/import/confirm", data=data)


def apply(env, project, approved, manifest=""):
    return env.client.post("/v2/workbook/import/apply", data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "approved_ticket": approved,
        "manifest_token": manifest})


def run_model(env, project):
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    response = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={"project": project.project_code, **tokens(page.text)})
    assert response.status_code == 200
    return response


def reconcile(env, project, applied_ticket, *, attested=True, history_id="", abs_tol="0", rel_tol="0", manifest=""):
    data = {"project": project.project_code, "csrf_token": generate_csrf_token(), "applied_ticket": applied_ticket,
            "history_id": history_id, "abs_tolerance": abs_tol, "rel_tolerance": rel_tol, "manifest_token": manifest}
    if attested:
        data["conventions_attested"] = "on"
    return env.client.post("/v2/workbook/import/reconcile", data=data)


def full_apply(env, project, key="upside", labels=tuple(FIELDS), data=None, manifest=""):
    """assess -> review slice -> confirm -> apply; returns (assess_response, apply_response)."""
    assessed = assess(env, project, data or journey_workbook(), manifest=manifest)
    reviewed = review_slice(env, project, slice_ticket(assessed, key), hidden(assessed, "manifest_token"))
    confirmed = confirm(env, project, hidden(reviewed, "preview_ticket"), hidden(reviewed, "manifest_token"), **selection(reviewed, labels))
    assert confirmed.status_code == 200, err(confirmed)
    applied = apply(env, project, hidden(confirmed, "approved_ticket"), hidden(confirmed, "manifest_token"))
    assert applied.status_code == 200, err(applied)
    return assessed, applied


def recon_rows(response):
    """{source cell: (status, [reason codes])} parsed from the reconcile page."""
    return {k: (v["status"], v["reasons"]) for k, v in recon_detail(response).items()}


def recon_detail(response):
    out = {}
    for status, body in re.findall(r'<tr data-status="([A-Z_]+)">(.*?)</tr>', response.text, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)
        text = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip() for t in tds]
        out[re.search(r"<strong>([^<]+)</strong>", body).group(1)] = {
            "status": status, "reasons": re.findall(r"<code>([A-Z_]{8,})</code>", body), "cells": text}
    return out

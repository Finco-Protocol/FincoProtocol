"""Shared canonical React JSON token and workspace helpers for FINCO48 test migration."""
from __future__ import annotations

from typing import Any


def react_workspace_payload(client, project_code: str) -> dict[str, Any]:
    """Fetch GET /v2/model-react/workspace and fail descriptively on non-200 or malformed JSON."""
    resp = client.get("/v2/model-react/workspace", params={"project": project_code})
    assert resp.status_code == 200, f"/v2/model-react/workspace returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "workbook" in payload, f"workspace missing 'workbook': {resp.text[:300]}"
    return payload


def react_workbook_tokens(client, project_code: str) -> dict[str, str]:
    """Return canonical {'content_hash', 'workbook_version'} from React workspace JSON."""
    wb = react_workspace_payload(client, project_code)["workbook"]
    return {"content_hash": wb["composite_hash"], "workbook_version": str(wb["version"])}


def react_run_contract(client, project_code: str) -> dict[str, Any]:
    """Fetch GET /v2/model-react/runs and return the run_contract payload."""
    resp = client.get("/v2/model-react/runs", params={"project": project_code})
    assert resp.status_code == 200, f"/v2/model-react/runs returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "run_contract" in payload, f"runs missing 'run_contract': {resp.text[:300]}"
    return payload["run_contract"]


def react_inputs_save_contract(client, project_code: str) -> dict[str, Any]:
    """Fetch GET /v2/model-react/inputs and return the 'save' CAS/CSRF contract (including 409 recovery)."""
    resp = client.get("/v2/model-react/inputs", params={"project": project_code})
    assert resp.status_code in (200, 409), f"/v2/model-react/inputs returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"inputs missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_fields_save_contract(client, project_code: str, sheet_id: str = "debt") -> dict[str, Any]:
    """Fetch GET /v2/model-react/fields/{sheet_id} and return the 'save' contract."""
    resp = client.get(f"/v2/model-react/fields/{sheet_id}", params={"project": project_code})
    assert resp.status_code == 200, f"/v2/model-react/fields/{sheet_id} returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"fields/{sheet_id} missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_revenue_save_contract(client, project_code: str) -> dict[str, Any]:
    """Fetch GET /v2/model-react/revenue and return the 'save' CAS/CSRF contract."""
    resp = client.get("/v2/model-react/revenue", params={"project": project_code})
    assert resp.status_code == 200, f"/v2/model-react/revenue returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"revenue missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_grid_and_update_tokens(client, project_code: str) -> dict[str, str]:
    """Return combined grid-save, single-update, and run tokens from canonical React JSON endpoints."""
    inputs_save = react_inputs_save_contract(client, project_code)
    wb = react_workbook_tokens(client, project_code)
    # Try fields/inputs first; fallback to fields/debt when inputs/fields not applicable
    fields_resp = client.get("/v2/model-react/fields/project_setup", params={"project": project_code})
    update_csrf = fields_resp.json()["save"]["csrf_token"] if fields_resp.status_code == 200 else ""
    runs_resp = client.get("/v2/model-react/runs", params={"project": project_code})
    run_csrf = ""
    if runs_resp.status_code == 200:
        run_csrf = (runs_resp.json().get("run_contract") or {}).get("csrf_token", "")
    return {
        "content_hash": wb["content_hash"],
        "workbook_version": wb["workbook_version"],
        "grid_csrf": str(inputs_save["csrf_token"]),
        "grid_hash": str(inputs_save["content_hash"]),
        "update_csrf": str(update_csrf),
        "run_csrf": str(run_csrf),
    }

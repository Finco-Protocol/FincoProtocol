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
    """Fetch GET /v2/model-react/inputs and return the 'save' CAS/CSRF contract."""
    resp = client.get("/v2/model-react/inputs", params={"project": project_code})
    assert resp.status_code == 200, f"/v2/model-react/inputs returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"inputs missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_revenue_save_contract(client, project_code: str) -> dict[str, Any]:
    """Fetch GET /v2/model-react/revenue and return the 'save' CAS/CSRF contract."""
    resp = client.get("/v2/model-react/revenue", params={"project": project_code})
    assert resp.status_code == 200, f"/v2/model-react/revenue returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"revenue missing 'save': {resp.text[:300]}"
    return payload["save"]

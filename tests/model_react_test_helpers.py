"""Shared canonical React JSON token and workspace helpers for FINCO48 test migration."""
from __future__ import annotations

from typing import Any


def _request_kwargs(cookies: Any = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if cookies is not None:
        kwargs["cookies"] = cookies
    if headers is not None:
        kwargs["headers"] = headers
    return kwargs


def react_workspace_payload(
    client,
    project_code: str,
    *,
    cookies: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch GET /v2/model-react/workspace and fail descriptively on non-200 or malformed JSON."""
    resp = client.get(
        "/v2/model-react/workspace",
        params={"project": project_code},
        **_request_kwargs(cookies, headers),
    )
    assert resp.status_code == 200, f"/v2/model-react/workspace returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "workbook" in payload, f"workspace missing 'workbook': {resp.text[:300]}"
    return payload


def react_workbook_tokens(
    client,
    project_code: str,
    *,
    cookies: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return canonical {'content_hash', 'workbook_version'} from React workspace JSON."""
    wb = react_workspace_payload(client, project_code, cookies=cookies, headers=headers)["workbook"]
    return {"content_hash": wb["composite_hash"], "workbook_version": str(wb["version"])}


def react_run_contract(
    client,
    project_code: str,
    *,
    cookies: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch GET /v2/model-react/runs and return the run_contract payload."""
    resp = client.get(
        "/v2/model-react/runs",
        params={"project": project_code},
        **_request_kwargs(cookies, headers),
    )
    assert resp.status_code == 200, f"/v2/model-react/runs returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "run_contract" in payload, f"runs missing 'run_contract': {resp.text[:300]}"
    return payload["run_contract"]


def react_inputs_save_contract(
    client,
    project_code: str,
    *,
    cookies: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch GET /v2/model-react/inputs and return the 'save' CAS/CSRF contract (including 409 recovery)."""
    resp = client.get(
        "/v2/model-react/inputs",
        params={"project": project_code},
        **_request_kwargs(cookies, headers),
    )
    assert resp.status_code in (200, 409), f"/v2/model-react/inputs returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"inputs missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_fields_save_contract(
    client,
    project_code: str,
    sheet_id: str = "debt",
    *,
    cookies: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch GET /v2/model-react/fields/{sheet_id} and return the 'save' contract."""
    resp = client.get(
        f"/v2/model-react/fields/{sheet_id}",
        params={"project": project_code},
        **_request_kwargs(cookies, headers),
    )
    assert resp.status_code == 200, f"/v2/model-react/fields/{sheet_id} returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"fields/{sheet_id} missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_revenue_save_contract(
    client,
    project_code: str,
    *,
    cookies: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch GET /v2/model-react/revenue and return the 'save' CAS/CSRF contract."""
    resp = client.get(
        "/v2/model-react/revenue",
        params={"project": project_code},
        **_request_kwargs(cookies, headers),
    )
    assert resp.status_code == 200, f"/v2/model-react/revenue returned HTTP {resp.status_code}: {resp.text[:300]}"
    payload = resp.json()
    assert isinstance(payload, dict) and "save" in payload, f"revenue missing 'save': {resp.text[:300]}"
    return payload["save"]


def react_grid_and_update_tokens(
    client,
    project_code: str,
    *,
    sheet_id: str = "project_setup",
    cookies: Any = None,
    headers: dict[str, str] | None = None,
    require_update: bool = True,
    require_run: bool = True,
) -> dict[str, str]:
    """Return combined grid-save, single-update, and run tokens from canonical React JSON endpoints."""
    kw = _request_kwargs(cookies, headers)
    inputs_save = react_inputs_save_contract(client, project_code, **kw)
    assert inputs_save.get("csrf_token"), f"/v2/model-react/inputs missing save.csrf_token: {inputs_save}"
    assert inputs_save.get("content_hash"), f"/v2/model-react/inputs missing save.content_hash: {inputs_save}"
    wb = react_workbook_tokens(client, project_code, **kw)
    update_csrf = ""
    if require_update:
        fields_save = react_fields_save_contract(client, project_code, sheet_id, **kw)
        update_csrf = str(fields_save.get("csrf_token") or "")
        assert update_csrf, f"/v2/model-react/fields/{sheet_id} missing save.csrf_token: {fields_save}"
    run_csrf = ""
    if require_run:
        run_contract = react_run_contract(client, project_code, **kw)
        run_csrf = str(run_contract.get("csrf_token") or "")
        assert run_csrf, f"/v2/model-react/runs missing run_contract.csrf_token: {run_contract}"
    return {
        "content_hash": wb["content_hash"],
        "workbook_version": wb["workbook_version"],
        "grid_csrf": str(inputs_save["csrf_token"]),
        "grid_hash": str(inputs_save["content_hash"]),
        "update_csrf": update_csrf,
        "run_csrf": run_csrf,
    }

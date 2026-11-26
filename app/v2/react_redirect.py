"""Canonical React URL builders and legacy GET compatibility redirect mapping."""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote, urlencode

_SHEET_TO_HASH: dict[str, str] = {
    "overview": "overview",
    "inputs": "inputs",
    "project_setup": "inputs/project",
    "project": "inputs/project",
    "technical": "inputs/technical",
    "capex": "inputs/capex",
    "opex": "inputs/opex",
    "revenue": "inputs/revenue",
    "tax": "inputs/tax",
    "financing": "financing",
    "debt": "financing",
    "debt-metrics": "debt-metrics",
    "statements": "statements",
    "fs": "statements",
    "results": "results",
    "outputs": "results",
    "returns": "results",
    "scenarios": "scenarios",
    "analysis": "analysis",
    "sensitivity": "analysis",
    "goal-seek": "analysis",
    "diagnostics": "diagnostics",
    "trust": "trust",
    "run-history": "results",
}


ALLOWED_LIBRARY_NOTICES = frozenset({"project-unavailable"})


def react_library_url(
    *,
    hash_fragment: Optional[str] = None,
    notice: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Build a safe same-origin React Library URL."""
    params: dict[str, str] = {}
    if notice in ALLOWED_LIBRARY_NOTICES:
        params["notice"] = notice
    if search:
        params["search"] = search
    url = "/v2/model-react/"
    if params:
        url += f"?{urlencode(params)}"
    if hash_fragment:
        url += f"#{hash_fragment.lstrip('#')}"
    return url


def react_project_url(
    project_code: str,
    *,
    sheet: Optional[str] = None,
    v2_err: Optional[str] = None,
    analysis: Optional[str] = None,
) -> str:
    """Build a safe same-origin React Project Workspace URL."""
    code = (project_code or "").strip()
    if not code:
        return react_library_url()
    url = f"/v2/model-react/{quote(code, safe='')}"
    params: dict[str, str] = {}
    if v2_err is not None and v2_err != "":
        params["v2_err"] = v2_err
    if analysis:
        params["analysis"] = analysis
    if params:
        url += f"?{urlencode(params)}"
    if sheet:
        mapped = _SHEET_TO_HASH.get(sheet.strip().lower())
        if mapped:
            url += f"#{mapped}"
    return url

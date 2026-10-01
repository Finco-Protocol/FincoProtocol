"""Manual-QA first-Run timing measurement (bounded, no secrets).

Drives the real POST /run pipeline through the real ASGI app for the four
reference technologies and prints the stage-timing breakdown emitted by
``app.services.run_stage_timing``:

    T0 submit          -> request_received + form_parsed (server entry)
    workspace done     -> project_workspace_resolved (+ guard/snapshot)
    model entered      -> model_entered
    run_project done   -> model_completed
    persistence done   -> persistence_completed
    response generated -> response_generated

Measured scenarios:
  1. NEWLY-CREATED project, FIRST /run click (the QA defect scenario).
  2. Same project, SECOND /run (warm path).
  3. Working copy of a protected reference, first /run (QA comparison).

Usage: python tools/qa_run_timing.py [--solar|--wind|--dc|--ev|--all]
No secrets or user inputs are logged; only stage timings.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


class StageCollector(logging.Handler):
    PATTERN = re.compile(r"run_stages outcome=(\S+) project_type=(.+?) origin=(\S+) scoped_by_user=\S+ (.*)")

    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[str, str, str, dict]] = []

    def emit(self, record: logging.LogRecord) -> None:
        match = self.PATTERN.search(record.getMessage())
        if not match:
            return
        outcome, project_type, origin, pairs = match.groups()
        stages = {}
        for token in pairs.split():
            if "=" in token:
                key, value = token.rsplit("=", 1)
                if key in ("request_received", "form_parsed", "project_workspace_resolved",
                           "runtime_guard", "runtime_snapshot_resolved", "model_entered",
                           "model_completed", "persistence_completed", "response_generated",
                           "total") and value.endswith("ms"):
                    stages[key] = int(value[:-2])
        self.records.append((outcome, project_type, origin, stages))


TECHNOLOGIES = {
    "solar": ("generic_solar_reference", "Solar"),
    "wind": ("generic_wind_reference", "Wind"),
    "dc": ("generic_data_center_reference", "Data Center"),
    "ev": ("generic_ev_charging_reference", "EV Charging"),
}

# Baseline capacity of each protected reference (factory defaults) — used
# so the working copy stays within the calibrated SHL/DSCR envelope.
REFERENCE_CAPACITY = {
    "solar": "64",
    "wind": "48",
    "dc": "20",
    "ev": "5",
}


def _csrf(client, path: str) -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else ""


def run_scenario(client, collector: StageCollector, label: str, tech_key: str,
                 new_project: bool) -> dict:
    template_source, display = TECHNOLOGIES[tech_key]
    collector.records.clear()

    project_name = f"QA Timing {display} {label} {int(time.time())}"
    response = client.post(
        "/projects/create",
        data={
            "project_name": project_name,
            "project_type": display,
            "template_source": template_source,
            "country_market": "Generic Market A",
            "capacity_mw": REFERENCE_CAPACITY[tech_key],
        },
        follow_redirects=False,
    )
    if response.status_code not in (200, 302, 303):
        return {"label": label, "tech": tech_key, "error": f"create failed {response.status_code}"}

    # First click after Create New Project lands on /v2/workbook; the Run
    # Model button posts /v2/workbook/run with project + version + hash.
    target = response.headers.get("hx-redirect") or response.headers.get("location") or "/"
    workbook = client.get(target)
    if workbook.status_code != 200:
        return {"label": label, "tech": tech_key,
                "error": f"workbook load failed {workbook.status_code}"}
    version = _extract(workbook.text, r'data-workbook-version="([^"]+)"')
    content_hash = _extract(workbook.text, r'data-content-hash="([^"]+)"')
    project_code = _extract(target, r"project=([^&]+)")
    if not (version and content_hash and project_code):
        return {"label": label, "tech": tech_key,
                "error": "run controls not found on workbook page"}

    run_response = client.post("/v2/workbook/run", data={
        "project": project_code,
        "workbook_version": version,
        "content_hash": content_hash,
    }, headers={"HX-Request": "true"})
    status = run_response.status_code
    if not collector.records:
        banner = re.findall(r"(Workbook changed[^<]*|could not be completed[^<]*|"
                            r"Engine run failed[^<]*|not yet supported[^<]*|"
                            r"Please run again[^<]*)", run_response.text)
        tail = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", run_response.text))[:300]
        return {"label": label, "tech": tech_key,
                "error": f"no stage log; run status={status}; banner={banner[:1]}; text={tail!r}"}
    outcome, project_type, origin, stages = collector.records[-1]
    return {"label": label, "tech": tech_key, "run_status": status,
            "outcome": outcome, "stages": stages}


def _extract(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def print_table(results: list[dict]) -> None:
    stages = ["form_parsed", "project_workspace_resolved", "runtime_guard",
              "runtime_snapshot_resolved", "model_entered", "model_completed",
              "persistence_completed", "response_generated", "total"]
    header = f"{'scenario':44s}" + "".join(f"{s[:14]:>16s}" for s in stages)
    print(header)
    print("-" * len(header))
    for r in results:
        if "error" in r:
            print(f"{r['tech'] + ' ' + r['label']:44s} ERROR: {r['error']}")
            continue
        row = f"{r['tech'] + ' ' + r['label']:44s}"
        for s in stages:
            ms = r["stages"].get(s)
            row += f"{(str(ms) + 'ms') if ms is not None else '—':>16s}"
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--techs", default="all",
                        help="comma list: solar,wind,dc,ev or 'all'")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "FINCO_DB_PATH": str(tmp / "qa_timing.db"),
        "FINCO_APP_MODE": "development",
        "FINCO_MODEL_EXECUTION_MODE": "thread",
        "FINCO_MODEL_EXECUTION_CONCURRENCY": "2",
        "FINCO_YIELD_ENABLED": "0",
    })

    import app.persistence.db as _db
    _db.DB_PATH = str(tmp / "qa_timing.db")

    logging.getLogger().setLevel(logging.INFO)
    collector = StageCollector()
    logging.getLogger("finco.run_stages").addHandler(collector)
    logging.getLogger("finco.run_stages").propagate = False

    from starlette.testclient import TestClient
    import main_web

    results: list[dict] = []
    # HTTPS base url: session/demo cookies are marked Secure; httpx must
    # send them back, matching real browser behaviour over TLS.
    with TestClient(main_web.app, base_url="https://qa-timing.local",
                    raise_server_exceptions=False) as client:
        # Login as the configured admin (local synthetic credentials only).
        login_page = client.get("/login")
        match = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
        login = client.post("/login", data={
            "username": os.environ.get("FINCO_ADMIN_USER", "admin"),
            "password": os.environ.get("FINCO_ADMIN_PASSWORD", "admin"),
            "csrf_token": match.group(1) if match else "",
        })
        if login.status_code not in (200, 302, 303):
            print("LOGIN FAILED:", login.status_code)
            return

        techs = list(TECHNOLOGIES) if args.techs == "all" else args.techs.split(",")
        for tech in techs:
            results.append(run_scenario(
                client, collector, "new-project first run", tech, new_project=True))
            results.append(run_scenario(
                client, collector, "same project second run", tech, new_project=False))

    print_table(results)


if __name__ == "__main__":
    main()

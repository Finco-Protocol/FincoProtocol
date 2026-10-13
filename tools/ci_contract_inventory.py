"""Generate source-bound workflow contracts locally; PyYAML is a tooling input."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess

from tools.ci_acceptance import write_json
from tools.ci_browser_job import REQUIRED, SELECTIONS


def main():
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", args.ref, ".github/workflows"], text=True).splitlines()
    entries = []
    for path in paths:
        if path.endswith((".yml", ".yaml")):
            content = subprocess.check_output(["git", "show", f"{args.ref}:{path}"])
            config = yaml.load(content, Loader=yaml.BaseLoader)
            entries.append({"path": path, "sha256": hashlib.sha256(content).hexdigest(),
                            "workflow": config["name"], "triggers": config.get("on"),
                            "permissions": config.get("permissions"), "jobs": config.get("jobs")})
    write_json(args.output, {
        "source_ref": args.ref, "workflows": entries,
        "process_required": ["Public Safety and Model Smoke", "Governance Full History", "Dependency Security Audit",
                             "Protocol UI Browser Acceptance", "PR Compile and Safety Gate"],
        "browser_commands": SELECTIONS,
        "explicit_scripts": ["tests.model_outputs_workspace_acceptance", "tools.model_financing_f3_evidence_bundle"],
        "required_browser_files": REQUIRED, "optional_evidence": ["F3 evidence"],
        "known_browser_selection_gaps": ["tests/test_model_golden_flows_browser.py", "tests/test_wf07_revenue_browser.py",
                                         "tests/test_model_trust_pack_browser.py", "tests/test_model_insight_q3_browser.py",
                                         "tests/test_model_smart_panel_q2_navigation_browser.py", "tests/test_workflow_c_browser_v1.py"],
        "existing_exclusions": ["test_data_center_browser_acceptance.py is not selected by the browser workflow",
                                "Protocol selection deselects test_api_b04_placeholders_not_links"],
        "pytest_node_authority": "Execution inventory.json; JUnit alone does not reconstruct all exact collected node IDs",
    })


if __name__ == "__main__":
    main()

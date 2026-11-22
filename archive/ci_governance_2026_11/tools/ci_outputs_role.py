"""The existing `outputs` browser role: both Chromium acceptance modules, each in its own process, both always executed.

Every module runs against the real ``main_web`` registration and writes its own artifact folder (never shared).  This runner
records each module's exit status in ``artifacts/outputs-role.json`` and exits non-zero if ANY module failed, so a failing or
missing Statements V2 acceptance fails the same mandatory gate as the original Outputs acceptance.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MODULES = (
    ("tests.model_outputs_workspace_acceptance", "artifacts/outputs-workspace"),
    ("tests.model_statements_tree_acceptance", "artifacts/statements-tree"),
)


def main() -> int:
    Path("artifacts").mkdir(exist_ok=True)
    record: dict[str, dict] = {}
    worst = 0
    for module, out in MODULES:
        code = subprocess.run([sys.executable, "-m", module, "--out", out]).returncode
        record[module] = {"exit_code": code, "normal_exit": code >= 0, "out": out}
        worst = worst or code
    Path("artifacts/outputs-role.json").write_text(json.dumps({"modules": record}, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())

"""Generate an UNAPPROVED V9 proposal-byte manifest, never a release authority."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

BASE = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"
PATHS = ("financial_engine/financing/project.py", "financial_engine/financing/v9_candidate.py",
         "financial_engine/financing/v9_numerics.py", "financial_engine/shareholder_waterfall/model.py",
         "app/services/production_financial_authority.py")


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = {"base": BASE, "review_status": "UNREVIEWED_PROPOSAL_BYTES_ONLY",
                "financial_owner_approved": False, "precision_approved": False,
                "failure_equivalence_proved": False, "release_approved": False,
                "production_activation": False, "files": {}}
    for path in PATHS:
        predecessor = subprocess.run(["git", "rev-parse", "--verify", BASE + ":" + path],
                                     cwd=root, text=True, capture_output=True)
        candidate = subprocess.check_output(["git", "hash-object", "--no-filters", path], cwd=root).decode().strip()
        manifest["files"][path] = {"predecessor": predecessor.stdout.strip() if predecessor.returncode == 0 else None,
                                   "candidate": candidate}
    out = root / "docs/model_v2/V9_CANDIDATE_BLOB_MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

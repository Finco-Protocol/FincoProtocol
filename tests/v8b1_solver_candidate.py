"""Performance V8-B1: exact-content RECOGNITION of the single reviewed solver change. This grants no approval and no guard consumes it.

It exists so an independent reviewer can bind a decision to one predecessor blob and one successor blob, and so any further byte (or any
other path) demonstrably loses recognition. ``APPROVED`` is a literal False: approval is an external, recorded human decision.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = "financial_engine/senior_debt/solver.py"
PREDECESSOR_BLOB = "6cf4a6cd9f149f271d4b61a60bb6b0aa70e4c9e0"      # blob on origin/main 5be8c4b1
CANDIDATE_BLOB = "a3939cee010b799479d5f489c5a5ddfa60f0405a"        # O8: diagnostic-only metric computed on the returning iteration
PREDECESSOR_COMMIT = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"
APPROVED = False                                                      # literal; never derived


def blob_at(ref: str, path: str = PATH, repo: Path = ROOT) -> str | None:
    out = subprocess.run(["git", "rev-parse", "--verify", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def recognises(path: str, blob: str | None) -> bool:
    """True only for the one path at the one candidate blob."""
    return path == PATH and blob == CANDIDATE_BLOB


def predecessor_is_the_main_blob(repo: Path = ROOT) -> bool:
    return blob_at(PREDECESSOR_COMMIT, repo=repo) == PREDECESSOR_BLOB

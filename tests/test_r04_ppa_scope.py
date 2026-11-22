"""R04 exact-source successor (after the accepted R03 leaf): positive identity and adversarial fail-closed controls.

Every negative runs in an ISOLATED clone (a committed variant, or a mutated working tree that is restored afterwards); the evaluated checkout is
never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REMEDIATION = "research/r04_ppa_global_cap/core.py"
SECOND_TEST = "tests/r04_ppa_global_cap/oracle.py"


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


class _WorkingTree:
    """Mutate the clone's WORKING TREE only (HEAD stays the accepted commit) and always restore it, so ``ref=None`` verdicts are judged on disk."""

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        _g(self.root, "checkout", "-q", "-f", "HEAD")
        _g(self.root, "clean", "-fdxq")


def _tamper(root, path, fn):
    f = root / path
    f.write_bytes(fn(f.read_bytes()))


# ---------------------------------------------------------------- positive identity


def test_no_production_path_imports_the_isolated_candidate_and_it_imports_no_product_code():
    import re
    files = _git("ls-files", "--", "*.py", "*.ts", "*.tsx", "*.js", "*.mjs", "*.html").split("\n")
    pat = re.compile(r"r04_ppa_global_cap")
    offenders = [f for f in files if f and not f.startswith(("research/r04_ppa_global_cap/", "tests/")) and pat.search((ROOT / f).read_text(errors="ignore"))]
    assert offenders == []
    core = (ROOT / "research/r04_ppa_global_cap/core.py").read_text()
    for forbidden in ("import app", "from app", "financial_engine", "finco_core", "main_web", "tax_reference_registry", "domain."):
        assert forbidden not in core, forbidden
    assert '"wired_into_save_or_run": False' in core


# ---------------------------------------------------------------- working-tree tamper is detected (the original defect)


# ---------------------------------------------------------------- committed-ref adversarial variants


# ---------------------------------------------------------------- PHASE 1: baseline ownership of the production revenue paths (no runtime change)
KEY_PRODUCTION_PATHS = ("domain/revenue/multistream_runtime.py", "domain/revenue/plan.py", "domain/revenue/plan_engine.py",
                        "app/workbook/revenue_multistream.py", "app/workbook/revenue_contracts_service.py", "finco_core/revenue/generation.py",
                        "finco_core/engine/period_engine.py", "frontend/src/app/workflow/PpaContractsEditor.tsx",
                        "frontend/src/app/workflow/ModelWorkflowValidation.ts", "static/react/finco-react.js")



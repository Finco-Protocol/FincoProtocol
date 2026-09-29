"""Opus Correction Stream C1 — product truth + H-4A validation terminology.

Proves the truth-correction contract without changing any behavior:

  1. No generic misleading "MODEL VALIDATION" user-facing label remains where
     it refers to the reference regression capability (H-4A rename to
     "Reference Regression Check").
  2. The check is described as pinned-reference regression protection — never
     as independent validation of a user's model or Last Run.
  3. Signed Run / Verify / token distinctions remain explicit.
  4. Unsupported/live claims match the actual implementation (Signed Run
     public verifier, B2.3 metering wiring, Run Integrity Checks planned).
  5. Zero behavior/math change: frozen namespaces have no diff against main
     and the machine authority key stays ``MODEL_VALIDATION``.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (REPO / rel_path).read_text(encoding="utf-8")


def _main_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=REPO,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


# ── 1. H-4A rename ───────────────────────────────────────────────────────────

class TestReferenceRegressionCheckNaming:
    def test_trust_pack_uses_reference_regression_check_label(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "c1-truth.db"))
        from app.persistence import db
        db.DB_PATH = os.environ["FINCO_DB_PATH"]
        db.init_db()

        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project
        from fastapi.testclient import TestClient
        import main_web

        record = create_reference_seeded_project(
            user_id="c1-truth-user",
            template_source="generic_solar_reference",
            requested_name="C1 Truth",
            capacity_mw=64.0,
        )
        cookies = {COOKIE_NAME: create_session_token(user_id="c1-truth-user", username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)

        # Never-run page: fail-closed UNAVAILABLE branch still carries the scope.
        pre = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert pre.status_code == 200
        assert "does <strong>not</strong> independently validate" in pre.text

        import re as _re

        m = _re.search(r'name="content_hash" value="([^"]+)"', pre.text)
        mv = _re.search(r'name="workbook_version" value="([^"]+)"', pre.text)
        run = client.post(
            "/v2/workbook/run",
            data={"project": record.project_code, "content_hash": m.group(1),
                  "workbook_version": mv.group(1)},
            cookies=cookies, headers={"HX-Request": "true"},
        )
        assert run.status_code == 200

        page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert page.status_code == 200

        assert "REFERENCE REGRESSION CHECK" in page.text
        # The generic misleading label is gone from the user-facing surface.
        assert "MODEL VALIDATION" not in page.text
        # The scope statement is explicit and user-visible.
        assert "independently validate your project's Last Run" in page.text
        assert "regression protection" in page.text
        # The authority separation keeps the invariant with the new term.
        assert "REFERENCE REGRESSION CHECK and FINCO VERIFY are separate authorities" in page.text
        assert "never implies Verified status" in page.text
        # Run Integrity Checks: planned, never shipped.
        assert "Run Integrity Checks" in page.text
        assert "planned (P0) and not yet shipped" in page.text

    def test_validation_fragment_carries_scope_statement(self):
        body = _read("app/templates/v2/partials/_trust_validation_body.html")
        assert "independently validate" in body
        assert "regression protection" in body
        assert "regression protection" in body

    def test_no_generic_model_validation_label_in_trust_surfaces(self):
        for rel in (
            "app/templates/v2/partials/sheet_trust.html",
            "app/templates/v2/partials/_trust_validation_body.html",
            "app/ui/trust_pack.py",
        ):
            src = _read(rel)
            # Only allowed as an explicit historical reference or machine key.
            cleaned = src.replace(
                '(formerly generic "MODEL VALIDATION")', ""
            ).replace("MODEL_VALIDATION", "")
            assert "MODEL VALIDATION" not in cleaned, rel

    def test_machine_authority_key_unchanged_for_api_stability(self):
        from app.api.v1_1 import schemas

        src = _read("app/api/v1_1/schemas.py")
        assert '"authority": "MODEL_VALIDATION"' in src
        # and the docstring documents the H-4A distinction
        inst = _read("app/api/v1_1/institutional.py")
        assert "Reference Regression Check" in inst
        assert "does not independently validate" in inst


# ── 2. Truth corrections in published docs ──────────────────────────────────

class TestPublishedTruthCorrections:
    def test_readme_signed_run_public_verifier_honesty(self):
        readme = _read("README.md")
        # The absolute third-party claim is gone.
        assert "Third-party verifiable\n  with the FINCO public key" not in readme
        assert "public trust-key distribution and a public verifier are not yet complete" in readme
        # Distinctions retained.
        assert "Not FINCO Verify. Not economic truth." in readme
        assert "No blockchain anchoring or smart-contract deployment is claimed" in readme

    def test_readme_metering_wiring_honesty(self):
        readme = _read("README.md")
        assert "not yet wired into all production resource-usage paths" in readme
        assert "production metering coverage is not LIVE" in readme
        # No blanket "usage metering are implemented" claim remains.
        assert "usage metering are implemented" not in readme

    def test_readme_equity_return_terminology(self):
        readme = _read("README.md")
        assert "pure share-capital return" in readme
        assert "EQUITY_ONLY" in readme
        assert "Total Sponsor XIRR" in readme

    def test_readme_financing_costs_qualification(self):
        readme = _read("README.md")
        assert "not yet fully wired through" in readme
        assert "IDC, lender commitment/structuring fees, and DSRA" in readme

    def test_roadmap_run_integrity_checks_planned_not_shipped(self):
        roadmap = _read("docs/ROADMAP.md")
        assert "Run Integrity Checks (planned — P0, not shipped)" in roadmap
        assert "Not implemented in V1" in roadmap
        # Reference Regression Check naming present; generic label gone.
        assert "Reference Regression Check (P1.3)" in roadmap
        assert "MODEL VALIDATION (P1.3)" not in roadmap
        # Last Run wording: replaced-only-by-next-run semantics, no forever claim.
        assert "replaced only by a subsequent committed run" in roadmap
        assert "committed, immutable snapshot" not in roadmap

    def test_capability_matrix_uses_new_name(self):
        matrix = _read("OPUS_V1_REVIEW/02_CAPABILITY_MATRIX.md")
        assert "Reference Regression Check (P1.3)" in matrix
        assert "MODEL VALIDATION (P1.3)" not in matrix
        assert "Run Integrity" not in matrix  # not present as a shipped capability

    def test_known_limitations_carry_h2_and_key_distribution(self):
        limits = _read("OPUS_V1_REVIEW/05_KNOWN_LIMITATIONS.md")
        assert "H-2" in limits
        assert "Do NOT claim unconditional institutional-grade DSCR sculpting convergence" in limits
        assert "public verifier are NOT yet" in limits or "public verifier" in limits

    def test_authority_boundaries_use_accurate_scope(self):
        bounds = _read("OPUS_V1_REVIEW/03_AUTHORITY_BOUNDARIES.md")
        assert "Reference Regression Check != FINCO VERIFY" in bounds
        # The factually wrong "checks ... against the committed Last Run outputs"
        # description is corrected.
        assert "checks model structure and numeric tolerances against the\n  committed Last Run outputs" not in bounds
        assert "NOT the user's committed Last Run" in bounds

    def test_product_invariants_preserved_in_docs(self):
        bounds = _read("OPUS_V1_REVIEW/03_AUTHORITY_BOUNDARIES.md")
        readme = _read("README.md")
        assert "SIGNED RUN" in bounds.upper() or "Signed Run" in bounds
        assert "Not economic truth" in readme or "not economic truth" in readme
        # Verify count invariant documented on the API/MCP surfaces
        inst = _read("app/api/v1_1/institutional.py")
        assert "PRODUCTION_VERIFIED_ASSET_COUNT must not increase" in inst


# ── 3. Behavior unchanged ────────────────────────────────────────────────────

class TestBehaviorUnchanged:
    @pytest.mark.parametrize(
        "frozen_path",
        [
            "financial_engine",
            "finco_core",
            "app/model_validation",
            "app/verified",
            "finco_radar",
        ],
    )
    def test_frozen_namespaces_zero_diff_against_main(self, frozen_path):
        sha = _main_sha()
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{sha}..HEAD", "--", frozen_path],
            cwd=REPO, capture_output=True, text=True, check=True,
        )
        assert out.stdout.strip() == "", out.stdout

    def test_validation_runner_behavior_untouched(self):
        # The runner module source is identical to main (no algorithm change).
        sha = _main_sha()
        out = subprocess.run(
            ["git", "diff", f"{sha}..HEAD", "--", "app/model_validation/"],
            cwd=REPO, capture_output=True, text=True, check=True,
        )
        assert out.stdout.strip() == ""

    def test_equity_kpi_labels_distinct_in_trust_pack(self):
        from app.ui.trust_pack import _CORE_KPI_ROWS

        labels = {key: label for key, label, _ in _CORE_KPI_ROWS}
        # The share-capital return must not be presented as the total sponsor return.
        assert "Sponsor" not in labels["equity_irr"]
        assert labels["total_sponsor_xirr"] == "Total Sponsor XIRR"

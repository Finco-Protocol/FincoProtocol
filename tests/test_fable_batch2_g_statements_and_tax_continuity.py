"""FINCO 35 Batch 2 — Slice G: Construction BS (E2E-05) & DC/EV tax-loss continuity.

Covers:
- E2E-05 (OD-CONSTR-01): construction balance sheet columns use staged construction_funding
  evidence (assets = staged uses, senior/SHL/equity = staged draws) with independent
  accounting identity |A - (L + E)| <= 0.01 kEUR (no full asset at month 1, no plugs);
  columns without complete balanced staged evidence are marked unavailable.
- DC & EV tax_provenance_v1 loss-schedule continuity: annual tax-loss stock balances
  carry continuously across intra-year periods (H1 -> H2 -> next H1) so
  loss_schedule_closing_equals_next_opening is True on DC and EV without changing tax math;
  genuine NOL expiry (C12) still truthfully reports discontinuity with first_discontinuity_period_index.
"""
from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, getcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.persistence.run_history_repository import get_run_history
from app.run_integrity.checks import run_integrity_checks
from app.run_integrity.contracts import CheckStatus, OverallStatus
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from tests.model_mutation_csrf import post_valid_mutation


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

getcontext().prec = 50


def _d(x) -> Decimal:
    return Decimal(repr(float(x)))


def _run_case(tmp_path, name: str, kind: str, edits: list[tuple[str, str]] | None = None):
    user = "test-sliceg-user"
    db.DB_PATH = str(tmp_path / f"{name}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name=f"SliceG {name}",
            template_source=f"generic_{kind}_reference",
            capacity_mw=16,
        )
        for field_id, value in (edits or []):
            html = client.get("/v2/workbook", params={"project": rec.project_code}).text
            tokens = {
                k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
                for k in ("content_hash", "workbook_version")
            }
            r = post_valid_mutation(
                client,
                "/v2/workbook/update",
                headers={"HX-Request": "true"},
                data={"project": rec.project_code, "field_id": field_id, "value": str(value), **tokens},
            )
            assert r.status_code == 200
        html = client.get("/v2/workbook", params={"project": rec.project_code}).text
        tokens = {
            k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
            for k in ("content_hash", "workbook_version")
        }
        req = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())
        resp = client.post(
            "/v2/workbook/run",
            headers={"Accept": "application/json"},
            data={
                "project": rec.project_code,
                **tokens,
                "csrf_token": issue_token(req, rec.project_code, purpose="workbook-run-v1"),
                "run_intent_id": str(uuid.uuid4()),
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "COMMITTED", body
        hist = get_run_history(user, rec.project_id)
        h = next(x for x in hist if x.history_id == body["history_id"]).to_dict()
        for k, v in list(h.items()):
            if isinstance(v, str) and v[:1] in "[{":
                try:
                    h[k] = json.loads(v)
                except Exception:
                    pass
        return h


def test_c01_solar_construction_bs_uses_staged_funding_and_balances_independently(tmp_path):
    h = _run_case(tmp_path, "c01_bs", "solar")
    ev = h["integrity_evidence"]
    rep = run_integrity_checks(ev)
    assert rep.overall is OverallStatus.PASS
    bs_chk = next(c for c in rep.checks if c.check_id == "BALANCE_SHEET_BALANCES")
    assert bs_chk.status is CheckStatus.PASS

    bs_rows = ev["balance_sheet"]
    # First construction column (period 0): staged uses (~5,103 kEUR), NOT full completed asset (~8,511 kEUR)!
    p0 = bs_rows[0]
    assert p0["gross_fixed_assets"] is not None
    assert p0["gross_fixed_assets"] < 6000.0
    assert p0["senior_debt"] > 2000.0
    assert p0["shl"] > 1000.0
    assert p0["share_capital"] == pytest.approx(500.0, abs=0.01)

    # Every published BS row (construction AND operating) satisfies independent Decimal identity <= 0.01 kEUR
    published_count = 0
    for row in bs_rows:
        if row["gross_fixed_assets"] is None:
            continue
        assets = (
            _d(row["gross_fixed_assets"])
            - _d(row["accumulated_depreciation"] or 0.0)
            + _d(row["unrestricted_cash"] or 0.0)
            + _d(row["dsra_balance"] or 0.0)
            + _d(row["distribution_account"] or 0.0)
        )
        le = (
            _d(row["senior_debt"] or 0.0)
            + _d(row["shl"] or 0.0)
            + _d(row["share_capital"] or 0.0)
            + _d(row["share_premium"] or 0.0)
            + _d(row["legal_reserve"] or 0.0)
            + _d(row["retained_earnings"] or 0.0)
            + _d(row["net_cit_payable"] or 0.0)
        )
        assert abs(assets - le) <= Decimal("0.01"), f"BS imbalance at period {row['period_index']}: {assets} vs {le}"
        published_count += 1
    assert published_count >= 40


def test_dc_and_ev_tax_provenance_loss_schedule_is_continuous(tmp_path):
    for kind in ("data_center", "ev_charging"):
        h = _run_case(tmp_path, f"tax_{kind}", kind)
        tp = h["runtime_summary"]["financing_evidence"]["financial_core_v1"]["tax_provenance_v1"]
        assert tp["status"] == "CALCULATED_FROM_EXISTING_SCHEDULES"
        rec = tp["reconciliation"]
        assert rec["loss_schedule_closing_equals_next_opening"] is True, (kind, rec)
        assert rec["first_discontinuity_period_index"] is None
        # Verify independently across all periods
        periods = tp["periods"]
        for i in range(1, len(periods)):
            assert periods[i]["tax_loss_opening_audit_keur"] == periods[i - 1]["tax_loss_closing_audit_keur"]

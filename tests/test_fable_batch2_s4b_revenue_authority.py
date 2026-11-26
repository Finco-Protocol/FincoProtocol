"""FINCO 35 Batch 2 — Slice D (S4b): Revenue input authority (P1-REV-01 / F2-NEW-01).

Covers OD-REV-01:
- C09 (missing merchant price 2031-2033 with positive merchant volume): Run fails closed
  with MERCHANT_PRICE_COVERAGE_MISSING naming [2031, 2032, 2033], no history committed,
  prior last-run preserved.
- C10 (explicit zero 2031-2033): Run commits cleanly (explicit zero != missing).
- C10B (covered curve from 2031): Run commits cleanly (~1,994.5 kEUR higher revenue).
- Pure 100% PPA before curve start (0 merchant MWh): Run commits cleanly (no false refusal).
- Wind C19 (explicit balancing=0 EUR/MWh): overrides factory 8 EUR/MWh default (~10,098 kEUR
  higher lifetime revenue than C02); C18 (5 EUR/MWh) replaces default without double-charge;
  C02 (absent) retains factory 8 EUR/MWh visibly.
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
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from tests.model_mutation_csrf import post_valid_mutation


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

getcontext().prec = 50


def _curve(start: int, prices: list[float]) -> str:
    return json.dumps([{"year": start + i, "price_eur_mwh": p} for i, p in enumerate(prices)])


def _run_case(tmp_path, name: str, kind: str, edits: list[tuple[str, str]], *, pre_run: bool = False):
    user = "test-s4b-user"
    db.DB_PATH = str(tmp_path / f"{name}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name=f"S4b {name}",
            template_source=f"generic_{kind}_reference",
            capacity_mw=16,
        )

        def _do_run():
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
            return resp.status_code, resp.json()

        prior_id = None
        if pre_run:
            st0, b0 = _do_run()
            assert st0 == 200 and b0["outcome"] == "COMMITTED"
            prior_id = b0["history_id"]

        for field_id, value in edits:
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
            assert r.status_code == 200, r.text[:400]

        st, body = _do_run()
        hist = get_run_history(user, rec.project_id)
        committed = None
        if body.get("outcome") == "COMMITTED":
            committed = next(x for x in hist if x.history_id == body["history_id"]).to_dict()
            for k, v in list(committed.items()):
                if isinstance(v, str) and v[:1] in "[{":
                    try:
                        committed[k] = json.loads(v)
                    except Exception:
                        pass
        return st, body, len(hist), prior_id, committed


def test_c09_missing_merchant_price_refused_preserving_prior_run_and_c10_zero_allowed(tmp_path):
    flat60 = [60.0] * 30
    # C09: 50% PPA + merchant curve starts 2034 -> positive merchant volume in 2031-2033 uncovered
    _, body_c09, hcount, prior_id, _ = _run_case(
        tmp_path,
        "c09",
        "solar",
        [
            ("revenue.ppa.production_share", "50"),
            ("revenue.merchant.price_curve_json", _curve(2034, flat60)),
        ],
        pre_run=True,
    )
    assert body_c09["outcome"] == "FAILED"
    assert "MERCHANT_PRICE_COVERAGE_MISSING" in body_c09["message"]
    assert "[2031, 2032, 2033]" in body_c09["message"]
    assert hcount == 1  # no new history committed; prior run preserved!
    assert prior_id is not None

    # C10: explicit zero 2031-2033 -> legitimate, commits cleanly
    st10, body_c10, hcount10, _, h10 = _run_case(
        tmp_path,
        "c10",
        "solar",
        [
            ("revenue.ppa.production_share", "50"),
            ("revenue.merchant.price_curve_json", _curve(2031, [0.0, 0.0, 0.0] + flat60)),
        ],
    )
    assert st10 == 200 and body_c10["outcome"] == "COMMITTED" and hcount10 == 1

    # C10B: covered curve from 2031 -> commits cleanly with ~1,994.5 kEUR higher revenue
    st10b, body_c10b, _, _, h10b = _run_case(
        tmp_path,
        "c10b",
        "solar",
        [
            ("revenue.ppa.production_share", "50"),
            ("revenue.merchant.price_curve_json", _curve(2031, flat60 + [60.0] * 3)),
        ],
    )
    assert st10b == 200 and body_c10b["outcome"] == "COMMITTED"
    rev_diff = h10b["runtime_summary"]["total_revenue_keur"] - h10["runtime_summary"]["total_revenue_keur"]
    assert rev_diff > 1900.0


def test_pure_contracted_ppa_before_merchant_curve_start_is_not_refused(tmp_path):
    # 100% PPA for 15 years (through 2046), merchant curve starts 2034 -> 0 merchant MWh in 2031-2033 -> allowed!
    flat60 = [60.0] * 30
    st, body, _, _, _ = _run_case(
        tmp_path,
        "pure_ppa",
        "solar",
        [
            ("revenue.ppa.production_share", "100"),
            ("revenue.merchant.price_curve_json", _curve(2034, flat60)),
        ],
    )
    assert st == 200 and body["outcome"] == "COMMITTED"


def test_wind_explicit_zero_balancing_overrides_default_8_and_c18_replaces_default(tmp_path):
    _, b02, _, _, h02 = _run_case(tmp_path, "c02", "wind", [])
    _, b18, _, _, h18 = _run_case(tmp_path, "c18", "wind", [("revenue.balancing.cost_eur_per_mwh", "5")])
    _, b19, _, _, h19 = _run_case(tmp_path, "c19", "wind", [("revenue.balancing.cost_eur_per_mwh", "0")])

    assert b02["outcome"] == b18["outcome"] == b19["outcome"] == "COMMITTED"
    rev02 = Decimal(repr(h02["runtime_summary"]["total_revenue_keur"]))
    rev18 = Decimal(repr(h18["runtime_summary"]["total_revenue_keur"]))
    rev19 = Decimal(repr(h19["runtime_summary"]["total_revenue_keur"]))

    # Independent proportionality check:
    # C02 uses default 8 EUR/MWh, C18 uses 5 EUR/MWh (delta = 3 EUR/MWh), C19 uses 0 EUR/MWh (delta = 8 EUR/MWh).
    # Therefore (rev19 - rev02) / (rev18 - rev02) MUST equal 8 / 3 to high precision!
    delta_0_vs_8 = rev19 - rev02
    delta_5_vs_8 = rev18 - rev02
    assert delta_0_vs_8 > Decimal("9500")   # ~10,098 kEUR lifetime
    assert delta_5_vs_8 > Decimal("3500")   # ~3,786.6 kEUR lifetime
    ratio = delta_0_vs_8 / delta_5_vs_8
    assert abs(ratio - (Decimal("8") / Decimal("3"))) < Decimal("1e-6")

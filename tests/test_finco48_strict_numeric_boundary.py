"""Strict numeric boundary witness restored in FINCO48 reconciliation.

Preserves the backend numeric-input parsing and API save boundary coverage from
retired ``tests/test_ux_c_strict_numbers.py`` without any legacy HTML/JS surface:
malformed, padded, separator-ambiguous, non-ASCII, and non-finite amounts must
be rejected before persistence without mutating cost lines or workspace CAS state.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.persistence import db


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "strict_numeric.db"))
    db.init_db()
    import main_web
    from app.auth import COOKIE_NAME, create_session_token

    owner = "finco48-strict-num-owner"
    client = TestClient(
        main_web.app,
        cookies={COOKIE_NAME: create_session_token(user_id=owner, username="admin")},
    )
    return client, owner


@pytest.mark.parametrize(
    "raw",
    ["410 420 430", "1_000", "１２３", " 5 ", "1,234", "nan", "inf", "0x10", "5\n", "", "1e400"],
)
def test_server_boundary_refuses_non_ascii_or_padded_amounts(raw):
    from app.v2.capex_commands import CapexInvalidAmountError, _parse_finite_amount_keur
    from app.v2.opex_commands import OpexInvalidAmountError, _parse_finite_opex_numerics

    with pytest.raises(CapexInvalidAmountError):
        _parse_finite_amount_keur(raw)
    with pytest.raises(OpexInvalidAmountError):
        _parse_finite_opex_numerics(raw, "2")
    with pytest.raises(OpexInvalidAmountError):
        _parse_finite_opex_numerics("2", raw)


@pytest.mark.parametrize(
    "raw,want",
    [("410", 410.0), ("-12.5", -12.5), ("1e-05", 1e-05), (".5", 0.5), (7, 7.0), (2.5, 2.5)],
)
def test_server_boundary_accepts_canonical_numeric_literals(raw, want):
    from app.v2.capex_commands import _parse_finite_amount_keur

    assert _parse_finite_amount_keur(raw) == want


@pytest.mark.parametrize("bad_amount", ["410 420 430", "1_000", "1,234", "nan"])
def test_cost_batch_save_api_refuses_malformed_numeric_without_writing(world, bad_amount):
    from app.services.reference_seed_service import create_reference_seeded_project

    client, owner = world
    rec = create_reference_seeded_project(
        user_id=owner,
        template_source="generic_solar_reference",
        requested_name="Strict Num API",
        capacity_mw=20.0,
    )
    cl_before = client.get(
        "/v2/model-react/costlines",
        params={"project": rec.project_code, "sheet": "capex"},
    )
    assert cl_before.status_code == 200, cl_before.text[:300]
    body_before = cl_before.json()
    line0 = next(ln for ln in body_before["lines"] if ln["active"])
    save_meta = body_before["save"]

    payload = [
        {
            "kind": "capex",
            "sub_line_id": line0["sub_line_id"],
            "label": line0["label"],
            "amount_keur": bad_amount,
            "row_version": line0["row_version"],
        }
    ]
    res = client.post(
        "/v2/workbook/grid/cost-lines/save",
        data={
            "project": rec.project_code,
            "csrf_token": save_meta["csrf_token"],
            "workbook_version": save_meta["workbook_version"],
            "content_hash": save_meta["content_hash"],
            "sheet": "capex",
            "payload": json.dumps(payload),
        },
        headers={"HX-Request": "true"},
    )
    assert res.status_code in (400, 422), (res.status_code, res.text[:200])

    cl_after = client.get(
        "/v2/model-react/costlines",
        params={"project": rec.project_code, "sheet": "capex"},
    ).json()
    line0_after = next(ln for ln in cl_after["lines"] if ln["sub_line_id"] == line0["sub_line_id"])
    assert line0_after["amount_keur"] == line0["amount_keur"]
    assert line0_after["row_version"] == line0["row_version"]
    assert cl_after["save"]["content_hash"] == save_meta["content_hash"]

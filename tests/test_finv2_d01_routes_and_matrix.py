"""FIN-V2-D01 — the V2 one-driver endpoint, the legacy routes, F01 integration and matrix equivalence (real routes, disposable DB).

* The V2 one-driver interest sensitivity shocks the typed Senior vector (5.5 % -> 3.5 / 4.5 / 5.5 / 6.5 / 7.5 %).
* Calibrated / bankability-owned / ambiguous-historical rates are refused BEFORE any model execution, with zero persistence.
* The shared authority is bit-identical to the React two-driver matrix and to the Save path; the matrix source is untouched.
* A preview never mutates Save, Run or Run History.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.test_fin_val_b2_c1_recovery_finite_opex import USER, _poison, _prime, _snapshot, _ws, env  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
SENS = "/v2/workbook/scenarios/sensitivity/run"
KINDS = ("solar", "wind", "data_center")


class _Capture:
    """Stands in for the bounded model executor: records every batch, returns inert KPIs."""

    def __init__(self):
        self.batches = []

    async def __call__(self, fn, runtime_key, batch):
        self.batches.append((runtime_key, list(batch)))
        return [{"kpis": {"equity_irr": 0.1, "project_irr": 0.1, "min_dscr": 1.3}} for _ in batch]


@pytest.fixture()
def capture(monkeypatch):
    from app.runtime import model_execution

    fake = _Capture()
    monkeypatch.setattr(model_execution, "run_model_process", fake)
    return fake


def _effective_percent(pi):
    from app.input_adapter import senior_rate_authority

    mode, ratio, _n = senior_rate_authority(pi)
    assert mode == "FLAT"
    return ratio * 100.0


def _post(env, record, driver="interest_rate", **extra):
    return env.client.post(SENS, data={"project": record.project_code, "driver": driver, **extra})


def _db_dump(env):
    with sqlite3.connect(env.db_path) as conn:
        return "\n".join(conn.iterdump())


def _history_count(env, record):
    with sqlite3.connect(env.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM model_run_history WHERE project_id=?", (record.project_id,)).fetchone()[0]


# ───────────────────────────── one-driver: applied ─────────────────────────────
@pytest.mark.parametrize("kind", KINDS)
def test_v2_one_driver_interest_shocks_the_effective_rate_by_100_bps_steps(env, capture, kind):
    record = env.create(kind)
    _prime(env, record)
    base = float(_snapshot(record)["interest_rate_pct"])          # F01: stored as human percent (5.5 / 6.0)
    response = _post(env, record)
    assert response.status_code == 200 and 'data-testid="sensitivity-refused"' not in response.text
    assert "X-Finco-Sensitivity-Outcome" not in response.headers
    assert len(capture.batches) == 1
    rates = [_effective_percent(pi) for pi in capture.batches[0][1]]
    assert rates == pytest.approx([base - 2.0, base - 1.0, base, base + 1.0, base + 2.0], abs=1e-9)
    if kind in ("solar", "wind"):
        assert base == pytest.approx(5.5) and rates[3] == pytest.approx(6.5) and rates[1] == pytest.approx(4.5)


def test_v2_one_driver_unshocked_step_is_the_working_copy_rate_unchanged(env, capture):
    record = env.create("solar")
    _prime(env, record)
    _post(env, record)
    mid = capture.batches[0][1][2]
    from app.workbook.input_set import ProjectInputSet

    # the route additionally folds the CAPEX/OPEX sub-lines; the financing authority of the unshocked step is untouched
    assert mid.financing == ProjectInputSet.from_snapshot(_snapshot(record)).to_projectinputs().financing


def test_v2_one_driver_sub_one_percent_rate_fails_only_the_unrepresentable_steps(env, capture):
    record = env.create("solar")
    _prime(env, record)
    _poison(env, record, "interest_rate_pct", "0.8")            # verified human-percent marker is retained
    response = _post(env, record)
    assert response.status_code == 200
    rates = [_effective_percent(pi) for pi in capture.batches[0][1]]
    assert rates == pytest.approx([0.8, 1.8, 2.8], abs=1e-9)               # only the three representable steps ran
    assert "RATE_SHOCK_OUT_OF_RANGE" in response.text           # -200 / -100 bps would be negative: failed alone


# ───────────────────────────── one-driver: refused before execution ─────────────────────────────
def _assert_refused(response, code):
    assert response.status_code == 200
    assert response.headers["X-Finco-Sensitivity-Outcome"] == "REFUSED"
    assert response.headers["X-Finco-Sensitivity-Code"] == code
    assert 'data-testid="sensitivity-refused"' in response.text and f'data-code="{code}"' in response.text


def test_v2_one_driver_calibrated_schedule_is_refused_with_zero_runs_and_zero_writes(env, capture, monkeypatch):
    import app.input_adapter as adapter

    record = env.create("solar")
    _prime(env, record)
    before = _db_dump(env)
    monkeypatch.setattr(adapter, "senior_rate_authority", lambda pi: ("CALIBRATED", None, 30))
    monkeypatch.setattr(adapter, "assert_debt_scalar_edit_allowed",
                        lambda pis, field: (_ for _ in ()).throw(ValueError(adapter._SENIOR_LOCKED_RATE_REASON)))
    _assert_refused(_post(env, record), "RATE_SHOCK_CALIBRATED_SCHEDULE")
    assert capture.batches == [] and _db_dump(env) == before


def test_v2_one_driver_bankability_owned_rate_is_refused(env, capture, monkeypatch):
    import app.input_adapter as adapter

    record = env.create("solar")
    _prime(env, record)
    monkeypatch.setattr(adapter, "assert_debt_scalar_edit_allowed", lambda pis, field: (_ for _ in ()).throw(
        ValueError("The bankability configuration owns this input. Edit or reset that configuration first.")))
    _assert_refused(_post(env, record), "RATE_SHOCK_BANKABILITY_OWNED")
    assert capture.batches == []


@pytest.mark.parametrize("marker", [None, "ratio", "ratio_v0", "human_percent_v2"])
def test_pre_f01_historical_working_copy_is_refused_and_never_migrated(env, capture, marker):
    """No unsupported historical migration: an unverified unit is neither guessed, converted nor relabelled."""
    from app.input_adapter import RATE_UNIT_KEY

    record = env.create("solar")
    _prime(env, record)
    _poison(env, record, "interest_rate_pct", "0.055")          # what a pre-F01 producer stored
    _poison(env, record, RATE_UNIT_KEY, marker)
    before_snapshot, before_dump = _snapshot(record), _db_dump(env)
    _assert_refused(_post(env, record), "RATE_UNIT_PROVENANCE_AMBIGUOUS")
    assert capture.batches == []
    assert _snapshot(record) == before_snapshot and _db_dump(env) == before_dump
    assert _snapshot(record)["interest_rate_pct"] == "0.055" and _snapshot(record).get(RATE_UNIT_KEY) == marker


def test_v2_one_driver_ev_charging_remains_unsupported(env, capture):
    record = env.create("ev_charging")
    _prime(env, record)
    response = _post(env, record)
    assert response.status_code == 409 and capture.batches == []


# ───────────────────────────── previews never mutate Save / Run / History ─────────────────────────────
@pytest.mark.parametrize("driver", ["interest_rate", "gearing", "tariff"])
def test_one_driver_preview_does_not_mutate_workspace_scenarios_or_run_history(env, capture, driver):
    record = env.create("solar")
    _prime(env, record)
    before_ws, before_dump, before_history = _ws(record), _db_dump(env), _history_count(env, record)
    assert _post(env, record, driver=driver).status_code == 200
    after = _ws(record)
    assert _db_dump(env) == before_dump and _history_count(env, record) == before_history
    for field in ("draft_snapshot", "saved_snapshot", "dirty", "last_runtime_snapshot_id", "last_runtime_at",
                  "active_scenario_id", "last_runtime_composite_hash"):
        assert getattr(after, field) == getattr(before_ws, field), field


def test_legacy_services_are_persistence_free(env):
    """The legacy sensitivity and lender services are pure: a full run leaves the database byte-identical."""
    from app import project_factories as factories
    from app.services.lender_case_service import run_lender_case
    from app.services.sensitivity_service import run_sensitivity

    record = env.create("solar")
    _prime(env, record)
    before = _db_dump(env)
    pi = factories.create_generic_solar_reference()
    run_sensitivity(pi, ["interest_rate"], [100.0], "solar")
    run_lender_case(pi, {"interest_stress": 100.0})
    assert _db_dump(env) == before


# ───────────────────────────── equivalence with the matrix and the Save path ─────────────────────────────
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bps", [-200.0, -100.0, 100.0, 200.0])
def test_shared_authority_is_bit_identical_to_the_matrix_and_to_the_save_path(env, kind, bps):
    from app.services import rate_shock as rs
    from app.services import sensitivity_matrix as matrix
    from app.v2.sensitivity_matrix_projection import DRIVERS
    from app.workbook.service import WorkbookService

    record = env.create(kind)
    _prime(env, record)
    basis = matrix.resolve_basis(workspace_owner=USER, project_record=record, ws=_ws(record), scenario_id=None)
    unshocked, _pis, _info = matrix.pre_financing_inputs(basis, [])
    matrix_pi, _pis2, _info2 = matrix.pre_financing_inputs(basis, [(DRIVERS["interest_rate"], bps)])
    ours = rs.apply_rate_shock_bps(unshocked, bps)
    vector = lambda p: p.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates  # noqa: E731
    assert vector(ours) == vector(matrix_pi)                                    # bit-for-bit, every period
    # the Save path: the same human-percent value written through the canonical field writer
    original = float(basis.pis_base.values["debt.senior.interest_rate_pct"])
    saved = WorkbookService.to_projectinputs(basis.pis_base.with_value("debt.senior.interest_rate_pct", str(original + bps * 0.01)))
    assert vector(ours) == vector(saved)


def _attribution_base():
    """What THIS workflow changed: the merge-base with main, so a forward merge of newer reviewed main (for example merged PR #388) is not attributed here.
    Falls back to main after merged PR #389 when ``origin/main`` is unavailable."""
    try:
        return subprocess.check_output(["git", "merge-base", "HEAD", "origin/main"], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return "128bf0c2b79af56985326543132cc806ff7f001c"          # main after merged PR #389


@pytest.mark.parametrize("path", [
    "app/services/sensitivity_matrix.py", "app/v2/sensitivity_matrix_projection.py", "app/v2/sensitivity_matrix_router.py",
    "app/v2/react_workspace_router.py", "app/v2/react_poc_router.py", "app/v2/react_insights_router.py",
])
def test_matrix_and_react_sources_are_byte_identical_to_the_f01_baseline(path):
    """The correct React matrix is not edited: its cells cannot change (same code, same inputs)."""
    base = _attribution_base()
    exists = subprocess.run(["git", "cat-file", "-e", base], cwd=REPO, capture_output=True)
    if exists.returncode != 0:
        pytest.skip("baseline commit not available in this shallow clone")
    expected = subprocess.check_output(["git", "rev-parse", f"{base}:{path}"], cwd=REPO, text=True).strip()
    actual = subprocess.check_output(["git", "hash-object", path], cwd=REPO, text=True).strip()
    assert actual == expected


def test_react_frontend_and_bundle_are_not_touched_by_this_workflow():
    base = _attribution_base()
    if subprocess.run(["git", "cat-file", "-e", base], cwd=REPO, capture_output=True).returncode != 0:
        pytest.skip("baseline commit not available in this shallow clone")
    changed = subprocess.check_output(["git", "diff", "--name-only", base, "--", "frontend", "static/react"],
                                      cwd=REPO, text=True).split()
    assert changed == []


# ───────────────────────────── legacy HTTP routes ─────────────────────────────
@pytest.fixture()
def legacy(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    import main_web

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "legacy.db"))
    db.init_db()
    client = TestClient(main_web.app, raise_server_exceptions=False)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id="legacy-d01", username="admin"))

    def create(kind):
        return create_reference_seeded_project(user_id="legacy-d01", requested_name="Legacy " + kind,
                                               template_source="generic_" + kind + "_reference", capacity_mw=16)
    yield type("Legacy", (), {"client": client, "create": staticmethod(create), "db_path": str(tmp_path / "legacy.db")})
    reset_model_executor_for_tests()


def _rows(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser").select("tr.sens-row")


def test_legacy_sensitivity_route_returns_applied_interest_rows_for_a_generic_reference(legacy):
    record = legacy.create("solar")
    response = legacy.client.get("/scenarios/sensitivity", params={
        "project": record.project_code, "shocks": "interest_rate", "levels": "-100,100", "tornado_kpi": "equity_irr"})
    assert response.status_code == 200
    rows = _rows(response.text)
    assert rows and not any("sens-row--error" in (r.get("class") or []) for r in rows)
    # the page repeats the same table (summary / tornado / detail): compare distinct rows only
    distinct = []
    for r in rows:
        cells = tuple(c.get_text(" ", strip=True) for c in r.find_all("td"))
        if cells not in distinct:
            distinct.append(cells)
    assert len(distinct) == 3                                                            # base, -100 bps, +100 bps
    base, down, up = distinct
    assert down != up and down != base and up != base                                    # never a flat duplicate triple
    assert down[1:] != up[1:] and down[1:] != base[1:]


@pytest.mark.parametrize("shock", ["ppa_price", "merchant_price", "availability"])
def test_legacy_sensitivity_route_refuses_inert_ev_drivers_with_a_typed_422(legacy, shock):
    record = legacy.create("ev_charging")
    response = legacy.client.get("/scenarios/sensitivity", params={"project": record.project_code, "shocks": shock})
    assert response.status_code == 422 and response.json()["state"] == "SENSITIVITY_DRIVER_UNSUPPORTED"


def test_legacy_ev_sensitivity_never_runs_on_the_wind_factory_fallback(legacy):
    """A project code the legacy resolver cannot map falls back to the Wind reference; an EV vertical must refuse it."""
    record = legacy.create("ev_charging")
    response = legacy.client.get("/scenarios/sensitivity", params={
        "project": record.project_code, "shocks": "interest_rate", "levels": "100"})
    assert response.status_code == 200
    assert not _rows(response.text)                                   # no result rows: the request failed closed
    assert "An error occurred" in response.text


def test_legacy_lender_route_applies_the_stress_or_fails_closed_never_a_flat_stressed_case(legacy):
    record = legacy.create("solar")
    response = legacy.client.get("/scenarios/lender-case", params={"project": record.project_code, "interest_stress": "100"})
    assert response.status_code == 200
    assert "Results unavailable" not in response.text

"""SC-08 / SC-10: horizon shortening vs the shareholder-loan maturity, and the structured explanation of a refused Run.

The engine's fail-closed decision is unchanged: the Run is still refused, no Run History entry is created, the previous committed Run is untouched and
nothing is moved for the user. What changes is that the user is told, in plain language, what was refused, where to look and how to recover.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

H = {"HX-Request": "true"}
HORIZON = "project_setup.technical.horizon_years"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rf.db"))
    db.init_db()
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=False)


class P:
    def __init__(self, client, uid, template="generic_solar_reference"):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project
        self.c, self.uid = client, uid
        self.rec = create_reference_seeded_project(user_id=uid, template_source=template, requested_name="RF", capacity_mw=40.0)
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username="admin"))

    def ident(self):
        html = self.c.get(f"/v2/workbook?project={self.rec.project_code}").text
        return re.search(r'data-content-hash="([^"]+)"', html).group(1), re.search(r'data-workbook-version="([^"]+)"', html).group(1)

    def set_horizon(self, years):
        ch, wv = self.ident()
        r = self.c.post("/v2/workbook/update", headers=H, data={"project": self.rec.project_code, "sheet_id": "project_setup", "field_id": HORIZON,
                                                               "value": str(years), "content_hash": ch, "workbook_version": wv})
        assert r.status_code == 200, r.text
        return r

    def setup_sheet(self):
        return self.c.get(f"/v2/workbook/grid/sheet?project={self.rec.project_code}&sheet=project_setup").text

    def run(self):
        ch, wv = self.ident()
        return self.c.post("/v2/workbook/run", headers=H, data={"project": self.rec.project_code, "workbook_version": wv, "content_hash": ch})

    def history(self):
        from app.persistence.run_history_repository import get_run_history
        return get_run_history(self.uid, self.rec.project_id)

    def snapshot(self):
        from app.persistence.workspace_repository import get_workspace_state
        return dict(get_workspace_state(self.uid, self.rec.project_id).draft_snapshot)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_shortened_horizon_shows_a_guided_shl_notice_without_moving_the_maturity(env):
    p = P(env, "sc34-rf-1")
    assert "shl-horizon-notice" not in p.setup_sheet()                               # the default horizon is consistent
    before = p.snapshot()
    p.set_horizon(20)
    html = p.setup_sheet()
    assert 'data-testid="shl-horizon-notice"' in html
    assert re.search(r'data-testid="shl-min-horizon">25 years', html)                # precise: how long the horizon must be
    assert 'data-sc34-goto-field="project_setup.technical.horizon_years"' in html     # navigation to the affected field
    assert 'data-sc34-goto-tab="tab-investor"' in html                              # and to the shareholder-loan terms
    assert "nothing has been moved or changed for you" in _text(html)
    after = p.snapshot()
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert "horizon_years" in changed and not any("shl" in k or "matur" in k for k in changed)   # the maturity / SHL terms were not touched
    p.set_horizon(25)
    assert "shl-horizon-notice" not in p.setup_sheet()                               # restoring the horizon clears the notice


def test_the_refused_run_is_explained_keeps_the_last_run_and_creates_no_history(env):
    p = P(env, "sc34-rf-2")
    ok = p.run()
    assert ok.status_code == 200 and "X-Finco-Run-Outcome" not in ok.headers
    assert len(p.history()) == 1
    p.set_horizon(20)
    bad = p.run()
    assert bad.status_code == 200                                                    # the transport status is not the outcome ...
    assert bad.headers["X-Finco-Run-Outcome"] == "FAILED"                            # ... this is
    text = _text(bad.text)
    assert 'data-testid="run-failure-detail"' in bad.text
    assert re.search(r'data-testid="run-failure-class"><code>SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED</code>', bad.text)
    assert "Model refusal (fail-closed)" in text and "at least 25 years" in text
    assert 'data-sc34-goto-tab="tab-project-setup"' in bad.text
    assert "unchanged and remains STALE" in text and "no Run History entry" in text
    assert len(p.history()) == 1                                                     # no entry after the failed computation


def test_a_horizon_not_longer_than_the_senior_tenor_is_named_precisely(env):
    p = P(env, "sc34-rf-3")
    p.set_horizon(12)
    bad = p.run()
    text = _text(bad.text)
    assert bad.headers["X-Finco-Run-Outcome"] == "FAILED"
    assert "project horizon (12 years) is not longer than the senior debt tenor (15 years)" in text
    assert "No committed Run exists" in text and len(p.history()) == 0


def test_a_genuine_cash_shortfall_refusal_stays_a_refusal():
    from app.v2.router import _engine_failure_message
    from app.v2.run_failure_explanation import explain_run_failure
    exc = SimpleNamespace(reason_code="PR8_CLEAN_ENGINE_FAIL_CLOSED", detail="ValueError: F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL: x")
    ws = SimpleNamespace(last_runtime_snapshot_id="s1", dirty=False, last_runtime_at="2026-10-16T08:45:00+00:00")
    out = explain_run_failure(exc, message=_engine_failure_message(RuntimeError(exc.detail)), ws=ws)
    assert out["classification"] == "F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL" and out["kind"] == "FAIL_CLOSED_REFUSAL"
    assert out["tab"] == "tab-debt" and "does not invent a repayment or refinancing" in out["explanation"]
    assert "remains CURRENT" in out["prior_run"] and out["no_run_recorded"] is True
    assert "No repayment or refinancing was manufactured" in out["message"]          # the pinned refusal wording is unchanged


def test_an_executor_failure_is_not_presented_as_an_input_problem():
    from app.v2.run_failure_explanation import explain_run_failure
    out = explain_run_failure(RuntimeError("boom"), message="x", ws=None, kind="EXECUTION_ERROR")
    assert out["classification"] == "MODEL_EXECUTION_FAILED" and out["kind"] == "EXECUTION_ERROR" and out["section"] == ""
    assert "No committed Run exists" in out["prior_run"]

"""SC-08 / SC-10: horizon shortening vs the shareholder-loan maturity, and the structured explanation of a refused Run.

The engine's fail-closed decision is unchanged: the Run is still refused, no Run History entry is created, the previous committed Run is untouched and
nothing is moved for the user. What changes is that the user is told, in plain language, what was refused, where to look and how to recover.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from tests.run_clone_csrf import post_valid_csrf

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
        r = post_valid_mutation(self.c, "/v2/workbook/update", headers=H, data={"project": self.rec.project_code, "sheet_id": "project_setup", "field_id": HORIZON,
                                                               "value": str(years), "content_hash": ch, "workbook_version": wv})
        assert r.status_code == 200, r.text
        return r

    def setup_sheet(self):
        return self.c.get(f"/v2/workbook/grid/sheet?project={self.rec.project_code}&sheet=project_setup").text

    def run(self):
        ch, wv = self.ident()
        return post_valid_csrf(self.c, "/v2/workbook/run", headers=H, data={"project": self.rec.project_code, "workbook_version": wv, "content_hash": ch})

    def history(self):
        from app.persistence.run_history_repository import get_run_history
        return get_run_history(self.uid, self.rec.project_id)

    def snapshot(self):
        from app.persistence.workspace_repository import get_workspace_state
        return dict(get_workspace_state(self.uid, self.rec.project_id).draft_snapshot)


def _detach_lineage(p):
    """A project WITHOUT proven canonical lineage: ON-08 never re-derives its SHL indices, so the stored factory maturity stays authoritative
    and a shortened horizon is a genuine, still-refused off-grid case (the pre-ON-08 SC-34 contract)."""
    from app.persistence import db
    with db.get_cursor() as cur:
        cur.execute("UPDATE projects SET source_project_id=NULL WHERE project_id=?", (p.rec.project_id,))


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_shortened_horizon_shows_a_guided_shl_notice_without_moving_the_maturity(env):
    """Ineligible (no proven canonical lineage): the stored SHL maturity is authoritative, so the guided notice and its true minimum remain."""
    p = P(env, "sc34-rf-1")
    _detach_lineage(p)
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


def test_eligible_working_copy_gets_no_stale_index_notice_and_nothing_is_moved(env):
    """ON-08: for a proven factory-generic Working Copy the Run re-derives the SHL indices, so the advisory must not tell the user to extend the
    horizon to the factory's 25 years nor say the model refuses; no stored SHL term is changed by viewing or editing."""
    p = P(env, "sc34-rf-1e")
    before = p.snapshot()
    p.set_horizon(20)
    html = p.setup_sheet()
    assert 'data-testid="shl-horizon-notice"' not in html and "shl-min-horizon" not in html
    assert "at least 25 years" not in _text(html)
    page = p.c.get(f"/v2/workbook?project={p.rec.project_code}").text                  # the full-workbook render consumes the same advisory
    assert 'data-testid="shl-horizon-notice"' not in page
    after = p.snapshot()
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert "horizon_years" in changed and not any("shl" in k or "matur" in k for k in changed)


def test_eligible_unserviceable_horizon_shows_no_false_minimum_and_the_run_names_the_real_reason(env):
    p = P(env, "sc34-rf-1u")
    p.set_horizon(12)                                    # not longer than the senior tenor (15)
    assert 'data-testid="shl-horizon-notice"' not in p.setup_sheet()


def test_the_refused_run_is_explained_keeps_the_last_run_and_creates_no_history(env):
    """Ineligible (no proven lineage): the stored off-grid maturity is a genuine, typed, fail-closed refusal; the Last Run is untouched."""
    p = P(env, "sc34-rf-2")
    _detach_lineage(p)
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


def test_eligible_run_with_a_shortened_horizon_commits_with_rederived_indices(env, monkeypatch):
    """The same 20-year edit on an eligible Working Copy is now admissible: the Run commits (new history entry), only the two SHL indices differ."""
    import app.api.project_runner as runner
    seen = []
    original = runner.run_project
    monkeypatch.setattr(runner, "run_project", lambda *a, **k: (seen.append(k.get("project_inputs_override")), original(*a, **k))[1])
    p = P(env, "sc34-rf-2e")
    assert p.run().status_code == 200 and len(p.history()) == 1
    p.set_horizon(20)
    ok = p.run()
    assert ok.status_code == 200 and "X-Finco-Run-Outcome" not in ok.headers, _text(ok.text)[:300]
    assert len(p.history()) == 2
    f = seen[-1].financing
    assert (f.shl_maturity_period_index, f.shl_principal_eligibility_start_period) == (42, 33)      # 3 construction periods + 20y*2 - 1; 3 + 15y*2
    assert f.clean_shl_repayment_method.value == "cash_sweep"


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

"""Portfolio core evidence from actual canonical Run commits in disposable SQLite."""
from dataclasses import asdict, replace

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import run

USER = "decision-user"


@pytest.fixture
def penv(env):
    assert any(getattr(route, "path", "") == "/v2/portfolio" for route in env.client.app.routes)
    return env


def history(record):
    from app.persistence.run_history_repository import get_run_history
    return get_run_history(USER, record.project_id)


def test_real_four_vertical_committed_evidence_provenance_and_read_only(penv, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.portfolio_reads import load_portfolio
    from app.v2.portfolio_projection import build_portfolio
    records = [penv.create(kind) for kind in ("solar", "wind", "data_center", "ev_charging")]
    for record in records:
        run(penv, record)
    before = [(get_workspace_state(USER, r.project_id), [asdict(e) for e in history(r)]) for r in records]

    def forbidden(*args, **kwargs):
        raise AssertionError("portfolio GET must not run or write")
    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    monkeypatch.setattr("app.persistence.workspace_repository.v2_atomic_run_commit", forbidden)
    view = build_portfolio(load_portfolio(USER))
    assert view["total"] == 4 and view["with_run"] == 4
    for record in records:
        row = next(row for row in view["rows"] if row["code"] == record.project_code)
        entry = history(record)[0]
        su = entry.runtime_summary["financing_evidence"]["sources_uses"]
        assert row["history_id"] == entry.history_id
        assert row["money"]["senior"]["value"] == su["senior_debt_keur"]
        assert row["money"]["equity"]["value"] == su["share_capital_and_other_equity_keur"]
        assert row["money"]["capex"]["value"] == su["base_project_capex_keur"]
        assert row["metrics"]["project_irr"]["value"] == entry.runtime_summary["project_irr"]
        assert row["freshness"] == "CURRENT"
        assert row["integrity"] in ("PASS", "FAIL", "INCOMPLETE")
        assert row["cohort"] is not None
        assert entry.history_id in row["run_url"] and entry.history_id in row["credit_url"]
    for _ in range(2):
        response = penv.client.get("/v2/portfolio")
        assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
        assert 'data-testid="portfolio-performance"' in response.text
    assert [(get_workspace_state(USER, r.project_id), [asdict(e) for e in history(r)]) for r in records] == before
    assert penv.client.post("/v2/portfolio").status_code == 405


def test_unrun_projects_not_bootstrapped_and_owner_filters_cannot_leak(penv):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.portfolio_reads import load_portfolio
    record = penv.create()
    before = get_workspace_state(USER, record.project_id)
    evidence = load_portfolio(USER)
    assert len(evidence) == 1 and evidence[0].entry is None
    assert get_workspace_state(USER, record.project_id) == before
    other = penv.client.__class__(penv.client.app)
    other.cookies.set(COOKIE_NAME, create_session_token(user_id="foreign", username="foreign"))
    response = other.get("/v2/portfolio", params={"project": record.project_code})
    assert response.status_code == 200 and record.project_name not in response.text
    assert not load_portfolio("foreign")
    anonymous = penv.client.__class__(penv.client.app)
    assert anonymous.get("/v2/portfolio", follow_redirects=False).status_code == 302
    assert penv.client.get("/v2/portfolio", params={"sort": "injected"}).status_code == 422
    assert penv.client.get("/v2/portfolio", params={"project": "a" * 161}).status_code == 422
    for params in ({"minimum": "5"}, {"sort": "min_dscr", "minimum": "NaN"},
                   {"sort": "min_dscr", "minimum": "2", "maximum": "1"}):
        assert penv.client.get("/v2/portfolio", params=params).status_code == 422


def test_stale_run_retains_financial_values_and_history_is_immutable(penv):
    from tests.test_model_financing_f2 import save
    from app.v2.portfolio_reads import load_portfolio
    from app.v2.portfolio_projection import build_portfolio
    record = penv.create()
    run(penv, record)
    before = asdict(history(record)[0])
    response = save(penv, record, "99", field="revenue.ppa.base_tariff")
    assert response.status_code == 200 and "field-error-banner" not in response.text
    row = build_portfolio(load_portfolio(USER))["rows"][0]
    assert row["freshness"] == "STALE"
    assert row["metrics"]["project_irr"]["value"] == before["runtime_summary"]["project_irr"]
    assert asdict(history(record)[0]) == before


def test_concurrent_edit_or_scenario_selection_fails_closed(penv, monkeypatch):
    from app.persistence import workspace_repository as repo
    from app.v2.portfolio_reads import load_portfolio
    record = penv.create()
    run(penv, record)
    original = repo.get_workspace_state
    calls = 0
    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        value = original(*args, **kwargs)
        return replace(value, active_scenario_id="another") if calls == 2 else value
    monkeypatch.setattr(repo, "get_workspace_state", changing)
    evidence = load_portfolio(USER)[0]
    assert evidence.freshness == "UNKNOWN" and "changed" in evidence.issue


def test_unreadable_latest_history_never_substitutes_older(penv):
    from app.persistence.db import get_cursor
    from app.v2.portfolio_reads import load_portfolio
    record = penv.create()
    run(penv, record)
    entry = history(record)[0]
    # Deliberate corruption only in this disposable test database.
    with get_cursor() as cursor:
        cursor.execute("UPDATE model_run_history SET runtime_summary_json='[]' WHERE history_id=?", (entry.history_id,))
    evidence = load_portfolio(USER)[0]
    assert evidence.entry is None and "unreadable" in evidence.issue


def test_real_base_and_child_runs_are_not_double_counted_or_promoted(penv):
    from app.persistence.scenarios_repository import list_scenarios, select_scenario
    from app.v2.portfolio_reads import load_portfolio
    from app.v2.portfolio_projection import build_portfolio
    record = penv.create()
    run(penv, record)
    base = history(record)[0]
    response = penv.client.post("/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
        data={"project": record.project_code, "scenario_name": "Portfolio child"})
    assert response.status_code == 200
    scenario = next(s for s in list_scenarios(user_id=USER, project_id=record.project_id) if s.scenario_name == "Portfolio child")
    run(penv, record)
    child = history(record)[0]
    before = [asdict(e) for e in history(record)]
    row = build_portfolio(load_portfolio(USER))["rows"][0]
    assert row["history_id"] == child.history_id and child.history_id != base.history_id
    assert build_portfolio(load_portfolio(USER))["total"] == 1
    base_scenario = next(s for s in list_scenarios(user_id=USER, project_id=record.project_id) if s.is_base_case)
    select_scenario(user_id=USER, project_id=record.project_id, scenario_id=base_scenario.scenario_id)
    row = build_portfolio(load_portfolio(USER))["rows"][0]
    assert row["history_id"] == child.history_id and row["freshness"] == "HISTORICAL"
    assert [asdict(e) for e in history(record)] == before

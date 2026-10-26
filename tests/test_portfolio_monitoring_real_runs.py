"""Portfolio core evidence from actual canonical Run commits in disposable SQLite."""
from tests.model_mutation_csrf import post_valid_mutation

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
    from decimal import Decimal
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
    assert Decimal(view["capital_groups"][0]["totals"]["senior"]["value"]) == sum(
        Decimal(str(history(record)[0].runtime_summary["financing_evidence"]["sources_uses"]["senior_debt_keur"]))
        for record in records)
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


@pytest.mark.parametrize("operation", ["draft", "scenario", "capex", "run"])
def test_concurrent_edit_or_scenario_selection_fails_closed(penv, monkeypatch, operation):
    import json
    from datetime import datetime, timezone
    from copy import deepcopy
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import get_workspace_state, v2_atomic_run_commit
    from app.workbook import workbook_identity
    from app.v2.portfolio_reads import load_portfolio
    record = penv.create()
    run(penv, record)
    ws = get_workspace_state(USER, record.project_id)
    entry = history(record)[0]
    original = workbook_identity.assemble_transactional
    changed = False
    def changing(**kwargs):
        nonlocal changed
        value = original(**kwargs)
        if not changed:
            changed = True
            if operation == "run":
                summary = deepcopy(entry.runtime_summary)
                summary["financing_evidence"]["run_binding"]["snapshot_id"] = "concurrent-run"
                v2_atomic_run_commit(user_id=USER, project_id=record.project_id, project_code=record.project_code,
                    expected_composite_hash=value.composite_hash, runtime_snapshot_id="concurrent-run", runtime_origin="test",
                    runtime_summary=summary, financial_statements=entry.financial_statements, debt_schedule=entry.debt_schedule,
                    tax_schedule=entry.tax_schedule, distribution_schedule=entry.distribution_schedule, sponsor_schedule=entry.sponsor_schedule,
                    active_scenario_id=ws.active_scenario_id, active_scenario_name=ws.active_scenario_name,
                    last_runtime_scenario_id=ws.last_runtime_scenario_id, ran_at=datetime.now(timezone.utc),
                    integrity_evidence=entry.integrity_evidence)
            else:
                with get_cursor() as cursor:
                    if operation == "draft":
                        draft = dict(ws.draft_snapshot, rev_ppa_base_tariff="99")
                        cursor.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(draft), record.project_id))
                    elif operation == "scenario":
                        cursor.execute("UPDATE workspace_states SET active_scenario_id='foreign' WHERE project_id=?", (record.project_id,))
                    else:
                        cursor.execute("UPDATE capex_sub_lines SET amount_keur=amount_keur+1 WHERE project_id=?", (record.project_id,))
        return value
    monkeypatch.setattr(workbook_identity, "assemble_transactional", changing)
    evidence = load_portfolio(USER)[0]
    assert evidence.freshness == "UNKNOWN" and "changed" in evidence.issue
    assert evidence.entry.history_id == entry.history_id


def test_repository_reads_recheck_ownership_and_exclude_archived(penv, monkeypatch):
    from app.persistence.db import get_cursor
    from app.v2 import portfolio_reads as reads
    owned, foreign, archived = [penv.create(kind) for kind in ("solar", "wind", "ev_charging")]
    with get_cursor() as cursor:
        cursor.execute("UPDATE projects SET user_id='foreign' WHERE project_id=?", (foreign.project_id,))
        cursor.execute("UPDATE projects SET archived=1 WHERE project_id=?", (archived.project_id,))
    assert [row.record.project_id for row in reads.load_portfolio(USER)] == [owned.project_id]
    original, calls = reads._projects, 0
    def transfer(connection, owner):
        nonlocal calls
        calls += 1
        if calls == 2:
            with get_cursor() as cursor:
                cursor.execute("UPDATE projects SET user_id='foreign' WHERE project_id=?", (owned.project_id,))
        return original(connection, owner)
    monkeypatch.setattr(reads, "_projects", transfer)
    assert reads.load_portfolio(USER) == []


def test_snapshot_is_read_only_and_failure_returns_unavailable_not_zero(penv, monkeypatch):
    from app.workbook import workbook_identity
    from app.persistence.workspace_repository import get_workspace_state
    record = penv.create()
    run(penv, record)
    before = get_workspace_state(USER, record.project_id)
    def write_attempt(**kwargs):
        kwargs["cursor"].execute("UPDATE projects SET project_name='unauthorized' WHERE project_id=?", (record.project_id,))
        raise AssertionError("query_only must have refused the write")
    monkeypatch.setattr(workbook_identity, "assemble_transactional", write_attempt)
    from app.v2 import portfolio_reads
    assert portfolio_reads.load_portfolio(USER)[0].freshness == "UNKNOWN"
    assert get_workspace_state(USER, record.project_id) == before
    monkeypatch.setattr(portfolio_reads, "_version", lambda *a: (_ for _ in ()).throw(RuntimeError("missing coherence evidence")))
    response = penv.client.get("/v2/portfolio")
    assert response.status_code == 503 and "temporarily unavailable" in response.text


def test_unreadable_latest_history_never_substitutes_older(penv):
    from app.persistence.db import get_cursor
    from app.v2.portfolio_reads import load_portfolio
    record = penv.create()
    run(penv, record)
    run(penv, record)
    assert len(history(record)) == 2
    entry = history(record)[0]
    # Deliberate corruption only in this disposable test database.
    with get_cursor() as cursor:
        cursor.execute("UPDATE model_run_history SET runtime_summary_json='[]' WHERE history_id=?", (entry.history_id,))
    evidence = load_portfolio(USER)[0]
    assert evidence.entry is None and "unreadable" in evidence.issue


def test_other_tenant_write_is_reconciled_without_losing_currentness(penv, monkeypatch):
    from app.persistence.db import get_cursor
    from app.workbook import workbook_identity
    from app.v2.portfolio_reads import load_portfolio
    owned, foreign = penv.create(), penv.create("wind")
    with get_cursor() as cursor:
        cursor.execute("UPDATE projects SET user_id='foreign' WHERE project_id=?", (foreign.project_id,))
    run(penv, owned)
    original, mutated = workbook_identity.assemble_transactional, False
    def changing(**kwargs):
        nonlocal mutated
        result = original(**kwargs)
        if not mutated:
            mutated = True
            with get_cursor() as cursor:
                cursor.execute("UPDATE projects SET project_name='Changed' WHERE project_id=?", (foreign.project_id,))
        return result
    monkeypatch.setattr(workbook_identity, "assemble_transactional", changing)
    evidence = load_portfolio(USER)
    assert len(evidence) == 1 and evidence[0].record.project_id == owned.project_id
    assert evidence[0].freshness == "CURRENT"


def test_idle_request_uses_one_connection_and_one_canonical_identity_per_run(penv, monkeypatch):
    from app.persistence import db
    from app.workbook import workbook_identity
    from app.v2.portfolio_reads import load_portfolio
    record = penv.create()
    run(penv, record)
    connection_count, identity_count, statements = 0, 0, []
    original_connection, original_identity = db.get_connection, workbook_identity.assemble_transactional
    def connection():
        nonlocal connection_count
        connection_count += 1
        result = original_connection()
        result.set_trace_callback(statements.append)
        return result
    def identity(**kwargs):
        nonlocal identity_count
        identity_count += 1
        return original_identity(**kwargs)
    monkeypatch.setattr(db, "get_connection", connection)
    monkeypatch.setattr(workbook_identity, "assemble_transactional", identity)
    assert load_portfolio(USER)[0].freshness == "CURRENT"
    assert connection_count == 1 and identity_count == 1
    assert sum("ROW_NUMBER()" in sql for sql in statements) == 1


def test_real_base_and_child_runs_are_not_double_counted_or_promoted(penv):
    from app.persistence.scenarios_repository import list_scenarios, select_scenario
    from app.v2.portfolio_reads import load_portfolio
    from app.v2.portfolio_projection import build_portfolio
    record = penv.create()
    run(penv, record)
    base = history(record)[0]
    response = post_valid_mutation(penv.client, "/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
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

"""V9-P2a / OD-R - production Run-to-commit safety (real V2 Run route, persistence and worker).

Path under test: Workbook V2 Run -> run_project -> run_clean_production -> generic financing
policy (DSRA owner, OD-R final authority) -> G2C -> result validation -> v2_atomic_run_commit
-> Run History. OD-R is release-closed; the only way a product Run reaches it here is the
test replacing the module default policy object, i.e. simulating a future controlled
activation inside this test process only.

Proves: the OD-R final checks run before commitment; a final-state maturity rejection never
saves a successful Run, never changes the preceding Last Run and never appends Run History;
the deployed default (canonical) behaviour is unchanged for the same project.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from tests.run_clone_csrf import post_valid_csrf

import dataclasses as dc
from contextlib import closing

import pytest

from app import project_factories as factories
from app.services import production_financial_authority as authority
from financial_engine.financing import generic_product_policy as gpp
from financial_engine.shl import maturity_authority as ma

OWNER = "odr-owner"


def _provisional_only_solar():
    """Synthetic 16 MW solar at DSCR 1.9: once materialised by the workbook, canonical rejects on a
    provisional SHL maturity breach only, while the OD-R final state is feasible."""
    pi = factories.create_default_solar_project(capacity_mw=16.)
    fields = {name: dc.replace(getattr(pi.capex, name), amount_keur=getattr(pi.capex, name).amount_keur * .26)
              for name in pi.capex._CAPEX_ITEM_FIELDS if getattr(getattr(pi.capex, name), "amount_keur", 0)}
    pi = dc.replace(pi, capex=dc.replace(pi.capex, **fields))
    return dc.replace(pi, financing=dc.replace(pi.financing, target_dscr=1.9))


@pytest.fixture(autouse=True)
def executor_cleanup():
    from app.runtime.model_execution import reset_model_executor_for_tests
    authority._POLICY_RUN_CACHE.clear()
    yield
    authority._POLICY_RUN_CACHE.clear()
    assert reset_model_executor_for_tests(None) == []
    assert ma.current_attempt() is None


@pytest.fixture
def workbook(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig, reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from main_web import app

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "odr.db"))
    db.init_db()
    seed = _provisional_only_solar()
    monkeypatch.setattr(factories, "create_generic_solar_reference", lambda: seed)
    record = create_reference_seeded_project(user_id=OWNER, requested_name="OD-R safety",
        template_source="generic_solar_reference", capacity_mw=float(seed.technical.capacity_mw))
    reset_model_executor_for_tests(ModelExecutor(ModelExecutionConfig(mode="thread")))

    class Book:
        def tokens(self):
            ws = get_workspace_state(OWNER, record.project_id)
            pis = WorkbookService.build_draft_input_set_from_workspace(ws)
            identity = assemble_consistent_for_get(user_id=OWNER, project_id=record.project_id,
                                                  workbook_version=pis.workbook_version)
            return ws, {"project": record.project_code, "workbook_version": pis.workbook_version,
                        "content_hash": identity.composite_hash}

        def run(self):
            _, data = self.tokens()
            return post_valid_csrf(self.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=data)

        def update(self, field, value):
            _, data = self.tokens()
            response = post_valid_mutation(self.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                data=data | {"sheet_id": "debt", "field_id": field, "value": value})
            assert '"workbook-field-saved"' in response.headers.get("HX-Trigger", ""), response.text[:600]

    book = Book()
    book.record = record
    with closing(TestClient(app)) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        assert client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
        book.client = client
        yield book


def _activate_odr_in_this_test(monkeypatch):
    odr = dc.replace(gpp.DEFAULT_GENERIC_FINANCING_POLICY, shl_maturity_authority=ma.SHL_MATURITY_POLICY_OD_R)
    monkeypatch.setattr(gpp, "DEFAULT_GENERIC_FINANCING_POLICY", odr)


def _failures(caplog):
    return [r.exc_info[1] for r in caplog.records if r.exc_info]


def test_canonical_default_rejects_and_commits_nothing(workbook, caplog):
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.service import WorkbookService
    response = workbook.run()
    assert response.status_code == 200 and 'data-testid="banner-error"' in response.text
    assert any("SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in str(e) for e in _failures(caplog))
    ws, _ = workbook.tokens()
    assert WorkbookService.get_runtime_result(ws) is None
    assert get_run_history(OWNER, workbook.record.project_id) == []


def test_odr_commits_admitted_run_then_final_failure_changes_nothing(workbook, monkeypatch, caplog):
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.service import WorkbookService
    _activate_odr_in_this_test(monkeypatch)

    response = workbook.run()
    assert response.status_code == 200
    valid, _ = workbook.tokens()
    assert WorkbookService.get_runtime_result(valid) is not None, response.text[:1000]
    history = get_run_history(OWNER, workbook.record.project_id)
    assert len(history) == 1

    # Final-state economically infeasible edit (DSCR 2.1): OD-R final checks fail before commit.
    workbook.update("debt.senior.target_dscr", "2.1")
    stale, _ = workbook.tokens()
    assert stale.dirty
    caplog.clear()
    response = workbook.run()
    assert response.status_code == 200 and 'data-testid="banner-error"' in response.text
    failures = [str(e) for e in _failures(caplog)]
    assert any("SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in f and "od_r_final_check=" in f for f in failures), failures
    after, _ = workbook.tokens()
    assert after == stale
    assert after.last_runtime_snapshot_id == valid.last_runtime_snapshot_id
    assert after.last_runtime_summary == valid.last_runtime_summary
    assert after.last_runtime_snapshot == valid.last_runtime_snapshot
    assert get_run_history(OWNER, workbook.record.project_id) == history
    assert WorkbookService.get_runtime_result(after) == WorkbookService.get_runtime_result(valid)


def test_odr_injected_final_failure_before_commit_appends_nothing(workbook, monkeypatch, caplog):
    """A final-check failure on an otherwise admissible Run: no Run, no history, no cache entry."""
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.service import WorkbookService
    _activate_odr_in_this_test(monkeypatch)
    original = ma.OdrAttempt.final_failure_error
    shortfall = ma.ShlMaturityShortfall(77.5, 41, 1e-7)

    def failing(self):
        if not any(c.name == "INJECTED.FINAL_CONTROL" for c in self.final_checks):
            self.final_checks.append(ma.OdrFinalCheck("INJECTED.FINAL_CONTROL", shortfall))
        return original(self)

    monkeypatch.setattr(ma.OdrAttempt, "final_failure_error", failing)
    response = workbook.run()
    assert response.status_code == 200 and 'data-testid="banner-error"' in response.text
    assert any("od_r_final_check=INJECTED.FINAL_CONTROL" in str(e) for e in _failures(caplog))
    ws, _ = workbook.tokens()
    assert WorkbookService.get_runtime_result(ws) is None
    assert get_run_history(OWNER, workbook.record.project_id) == []
    assert not authority._POLICY_RUN_CACHE


def test_odr_failed_idempotence_with_final_breach_commits_nothing(workbook, monkeypatch, caplog):
    """Combined control 8: candidate final breach + failed construction idempotence.

    The Run keeps the original idempotence rejection (final authority was never established),
    and nothing is committed: no Last Run, no Run History row, no memoised result.
    """
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.service import WorkbookService
    from finco_core.construction import stage_b2
    _activate_odr_in_this_test(monkeypatch)
    injected = ma.ShlMaturityShortfall(77.5, 41, 1e-7)
    original_record = ma.G2aShlMaturityEvidence.record_iteration

    def record(self, iteration, passes, *, final):
        if final:
            for site, ctx in passes:
                if site == "CAPACITY":
                    ctx.ledger.record(injected)
        return original_record(self, iteration, passes, final=final)

    original_b2 = stage_b2.run_stage_b2

    def perturbed(config):
        result = original_b2(config)
        costs = dc.replace(result.capitalized_financing_costs,
                           senior_idc_keur=result.capitalized_financing_costs.senior_idc_keur + 1.0)
        return dc.replace(result, capitalized_financing_costs=costs)

    monkeypatch.setattr(ma.G2aShlMaturityEvidence, "record_iteration", record)
    monkeypatch.setattr(stage_b2, "run_stage_b2", perturbed)
    response = workbook.run()
    assert response.status_code == 200 and 'data-testid="banner-error"' in response.text
    failures = [str(e) for e in _failures(caplog)]
    assert any("PR9_OUTER_G2A_IDEMPOTENCE_FAILED" in f for f in failures), failures
    assert not any("SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in f for f in failures), failures
    ws, _ = workbook.tokens()
    assert WorkbookService.get_runtime_result(ws) is None
    assert get_run_history(OWNER, workbook.record.project_id) == []
    assert not authority._POLICY_RUN_CACHE

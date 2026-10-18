"""RC-7B combined acceptance: a REAL committed 3/3 project-finance Run on the app.

Working Copy -> select 3/3 -> Save -> Run -> CURRENT -> inspect committed
quarterly schedules -> Run History -> Export, then an assumption change and a
frequency change each go CURRENT -> STALE -> Run -> CURRENT. Historical 6/6
Runs are never relabelled or recalculated.

The admission gate is opened ONLY inside these tests with monkeypatch, as
acceptance evidence. The committed ``ACTIVATION_ENABLED`` stays False; this is
not product admission and not owner approval. No mocked engine or persistence.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal, localcontext

import openpyxl
import pytest

from app.workbook import quarterly_frequency_config as cfg
from app.workbook.runtime_authority import RuntimeAuthorityState, resolve_runtime_freshness
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_rc7_capex_profile_run import (  # noqa: F401
    OWNER, _base_leaves, _hash, _latest, _planner_routes, _row, _run, _save, _ws,
)

# Quarter-end COD keeps the legacy PPA expiry on a quarter boundary (D-05).
TIMELINE = {"solar": ("2031-03-31", 14), "wind": ("2031-09-30", 20)}


def _set(env, project, field_id, value, sheet="project_setup"):
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    response = env.client.post("/v2/workbook/update", data={
        "project": project.project_code, "sheet_id": sheet, "field_id": field_id, "value": value, **tokens(page.text)})
    assert response.status_code in (200, 303), response.text[:400]


def _frequency(env, project, frequency):
    from app.auth import generate_csrf_token
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    response = env.client.post("/v2/workbook/calendar/operating-frequency", data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "frequency": frequency,
        "financing_structure": "EQUITY_ONLY_NO_RESERVE" if frequency == "3/3" else "",
        **tokens(page.text)}, follow_redirects=False)
    assert response.status_code == 303, response.text[:400]


def _state(project):
    return resolve_runtime_freshness(_ws(project), current_composite_hash=_hash(project)).state


def _export(project, history_id=None):
    from app.persistence.projects_repository import get_project
    from app.services import v2_export_service as exports
    record = get_project(project.project_id, OWNER)
    if history_id is None:
        response = exports.build_canonical_last_run_institutional_workbook_export(
            record.template_source, safe_project=record.project_code, project_record=record, user_id=OWNER)
    else:
        response = exports.build_historical_run_workbook_export(project_record=record, user_id=OWNER, history_id=history_id)
    assert response.status_code == 200, response.error_content
    return openpyxl.load_workbook(io.BytesIO(response.bytes_data))


def _frequency_label(workbook):
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            if row and row[0] in ("Frequency", "Period frequency") and len(row) > 1:
                return row[1]
    raise AssertionError("no persisted frequency row in export")


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_quarterly_project_finance_run_lifecycle(env, monkeypatch, kind):
    from app.services import production_financial_authority as authority
    from app.persistence.run_history_repository import get_run_history

    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)  # acceptance evidence only
    project = env.create(kind)
    cod, months = TIMELINE[kind]
    _set(env, project, "project_setup.technical.construction_months", str(months))
    _set(env, project, "project_setup.technical.cod_date", cod)

    # 1. Released 6/6 Run first: historical evidence that must never change.
    assert _run(env, project).status_code == 200
    assert _state(project) is RuntimeAuthorityState.CURRENT
    semi_entry = _latest(project)
    semi_before = semi_entry.to_dict()
    assert "operating_frequency" not in semi_entry.runtime_summary["financing_evidence"]

    # 2. Select 3/3 and Save -> the Last Run is STALE, numbers untouched.
    _frequency(env, project, "3/3")
    assert _state(project) is RuntimeAuthorityState.STALE
    assert cfg.frequency_label(_ws(project).draft_snapshot.get(cfg.SNAPSHOT_KEY)) == "3/3"

    # 3. Real Run (observe the single canonical calculation) -> CURRENT.
    captured = []
    real = authority.run_clean_production

    def observe(*args, **kwargs):
        result = real(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(authority, "run_clean_production", observe)
    assert _run(env, project).status_code == 200
    assert len(captured) == 1
    assert _state(project) is RuntimeAuthorityState.CURRENT
    clean = captured[0]
    pi = clean.project_inputs
    assert pi.info.operating_calendar_policy is not None
    finance = clean.g2c_result.financing_result
    model = finance.project_model_result
    ops = [p for p in model.periods if p.is_operation]
    assert len(ops) == 4 * pi.info.horizon_years
    assert ops[0].period_start == date.fromisoformat(cod)
    assert all(p.period_end.month in (3, 6, 9, 12) for p in ops)

    # 4. Committed quarterly schedules and funding authority.
    entry = _latest(project)
    evidence = entry.runtime_summary["financing_evidence"]
    assert evidence["operating_frequency"] == "3/3" and evidence["period_months"] == 3
    assert evidence["sponsor_returns_status"] == "PENDING_D08_DISTRIBUTION_ELIGIBILITY"
    debt_rows = [r for r in (entry.debt_schedule or {}).get("periods", []) if r.get("date")]
    assert debt_rows, "committed quarterly debt schedule is persisted"
    dates = sorted({r["date"] for r in debt_rows})
    assert any(d.endswith("-03-31") for d in dates) and any(d.endswith("-09-30") for d in dates)
    with localcontext() as ctx:
        ctx.prec = 50
        funding = finance.construction_funding
        draws = sum(Decimal(repr(p.senior_draw_keur)) for p in funding.periods)
        if funding.non_construction_fc_use is not None:
            draws += Decimal(repr(funding.non_construction_fc_use.senior_draw_keur))
        opening = Decimal(repr(model.senior_debt.senior_debt_opening_keur[0]))
        assert opening > 0 and abs(opening - draws) < Decimal("1e-6")
        assert abs(Decimal(repr(funding.total_audit_sources_keur)) - Decimal(repr(funding.total_audit_uses_keur))) < Decimal("1e-6")
    assert abs(model.senior_debt.senior_debt_closing_keur[-1]) < 1e-6

    # 5. History: both Runs present; the 6/6 Run is byte-identical and still 6/6.
    history = get_run_history(OWNER, project.project_id)
    assert {h.history_id for h in history} >= {semi_entry.history_id, entry.history_id}
    stored_semi = next(h for h in history if h.history_id == semi_entry.history_id)
    assert stored_semi.to_dict() == semi_before

    # 6. Export of the committed Run declares quarterly from persisted metadata;
    #    the historical 6/6 export still declares half-years (never relabelled).
    assert _frequency_label(_export(project)) == "Quarterly"
    assert _frequency_label(_export(project, semi_entry.history_id)) != "Quarterly"

    # 7. An assumption change: CURRENT -> STALE -> Run -> CURRENT.
    _set(env, project, "debt.senior.target_dscr", "1.25", sheet="debt")
    assert _state(project) is RuntimeAuthorityState.STALE
    assert _run(env, project).status_code == 200
    assert _state(project) is RuntimeAuthorityState.CURRENT
    assert _latest(project).runtime_summary["financing_evidence"]["operating_frequency"] == "3/3"

    # 8. A frequency change back to 6/6: CURRENT -> STALE -> Run -> CURRENT.
    _frequency(env, project, "6/6")
    assert _state(project) is RuntimeAuthorityState.STALE
    assert _run(env, project).status_code == 200
    assert _state(project) is RuntimeAuthorityState.CURRENT
    back = _latest(project)
    assert "operating_frequency" not in back.runtime_summary["financing_evidence"]
    assert next(h for h in get_run_history(OWNER, project.project_id)
                if h.history_id == semi_entry.history_id).to_dict() == semi_before


def _released_six_month_run(quarterly_inputs):
    """The SAME effective inputs (monthly construction input included) on the released 6/6 axis."""
    import dataclasses
    from finco_core.inputs import PeriodFrequency, ProjectInfo
    from financial_engine.financial_statements import assemble_decision_complete_financial_statements
    from financial_engine.financing.generic_product_policy import (
        DEFAULT_GENERIC_FINANCING_POLICY, run_with_generic_financing_policy,
    )
    from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
    info = quarterly_inputs.info
    plain = ProjectInfo(**{f.name: getattr(info, f.name) for f in dataclasses.fields(ProjectInfo)}
                        | {"period_frequency": PeriodFrequency.SEMESTRIAL})
    semi_inputs = dataclasses.replace(quarterly_inputs, info=plain)
    g2c, applied, _ = run_with_generic_financing_policy(
        semi_inputs, lambda a: run_project_shareholder_waterfall_model(a, source_id="rc7b_like_for_like"),
        DEFAULT_GENERIC_FINANCING_POLICY)
    return g2c, applied, assemble_decision_complete_financial_statements(g2c, applied)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_monthly_construction_idc_survives_quarterly_operation(env, monkeypatch, kind):
    """Monthly CAPEX profile + 3/3 committed Run: monthly draws, IDC, fees and COD funding equal
    the released 6/6 calculation of the same inputs, and reconcile in Decimal."""
    from app.services import production_financial_authority as authority

    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    project = env.create(kind)
    cod, months = TIMELINE[kind]
    _set(env, project, "project_setup.technical.construction_months", str(months))
    _set(env, project, "project_setup.technical.cod_date", cod)
    _save(project, [_row(leaf.item_key, "FRONT_LOADED") for leaf in _base_leaves(project)])
    _frequency(env, project, "3/3")
    captured = []
    real = authority.run_clean_production
    monkeypatch.setattr(authority, "run_clean_production",
                        lambda *a, **k: captured.append(real(*a, **k)) or captured[-1])
    assert _run(env, project).status_code == 200
    assert len(captured) == 1
    quarter = captured[0]
    assert quarter.project_inputs.info.operating_calendar_policy is not None
    typed = quarter.project_inputs.financing.construction_financing
    assert typed is not None and len(typed.periods) == months  # monthly construction axis
    b = quarter.g2c_result.financing_result
    semi_g2c, _, semi_statements = _released_six_month_run(quarter.project_inputs)
    a = semi_g2c.financing_result
    # Frequency never changes construction dates, draws, IDC, fees or Uses.
    assert a.construction_financing == b.construction_financing
    assert a.construction_funding == b.construction_funding
    assert a.project_uses == b.project_uses
    assert a.final_senior_commitment_keur == b.final_senior_commitment_keur
    assert semi_statements.construction_funding_rows == quarter.financial_statements_result.construction_funding_rows
    rate = Decimal(str(typed.senior_pricing.flat_all_in_rate))
    denominator = {"ACT_360": Decimal(360), "ACT_365": Decimal(365)}[typed.senior_pricing.day_count.value.upper()]
    c = b.construction_financing
    with localcontext() as ctx:
        ctx.prec = 50
        opening = Decimal(0)
        for start, end, draw, idc in zip(c.period_start_dates, c.period_end_dates, c.senior_draws_keur, c.senior_idc_accrual_keur):
            expected = opening * rate * Decimal((end - start).days + 1) / denominator
            assert abs(Decimal(str(idc)) - expected) < Decimal("1e-6")
            opening += Decimal(str(draw))
        outside = b.construction_funding.non_construction_fc_use
        funded = opening + (Decimal(str(outside.senior_draw_keur)) if outside else Decimal(0))
        first = Decimal(str(b.project_model_result.senior_debt.senior_debt_opening_keur[0]))
        assert abs(first - funded) < Decimal("1e-6")
    assert c.period_end_dates[-1] + timedelta(days=1) == quarter.project_inputs.info.cod_date
    evidence = _latest(project).runtime_summary["financing_evidence"]
    binding = evidence["financing_structure_binding"]
    assert binding["binding"] == "EXACT_RECORDED_STRUCTURE_VERIFIED"
    assert binding["automatic_dsra"] == "EXCLUDED_BY_RECORDED_3_3_SELECTION"
    # The excluded structure is recorded in the persisted, versioned selection itself - not inferred.
    recorded = cfg.parse_config(_ws(project).draft_snapshot.get(cfg.SNAPSHOT_KEY))["excluded_structure"]
    assert recorded["shl_amount_keur"] > 0 and recorded["dsra_months"] == 6


def test_closed_gate_blocks_the_real_run_of_a_saved_selection_and_reset_recovers(env, monkeypatch):
    """A selection saved while open is refused by the Run once the gate is closed; 6/6 reset recovers."""
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    project = env.create("solar")
    cod, months = TIMELINE["solar"]
    _set(env, project, "project_setup.technical.construction_months", str(months))
    _set(env, project, "project_setup.technical.cod_date", cod)
    _frequency(env, project, "3/3")
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", False)
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    assert page.status_code == 200  # the Working Copy still renders
    response = _run(env, project)
    assert "QUARTERLY_ADMISSION_CLOSED" in response.text
    assert not _ws(project).last_runtime_snapshot_id
    _frequency(env, project, "6/6")  # the only write accepted while closed
    assert _run(env, project).status_code == 200
    assert _state(project) is RuntimeAuthorityState.CURRENT
    assert "operating_frequency" not in _latest(project).runtime_summary["financing_evidence"]


@pytest.mark.parametrize("recorded", [
    {"sponsor_funding_mode": "EQUITY_ONLY", "shl_amount_keur": 0.0, "clean_shl_principal_keur": 0.0, "dsra_months": 0},
    {"sponsor_funding_mode": "SHARE_CAPITAL_THEN_SHL", "shl_amount_keur": 1.0, "clean_shl_principal_keur": 1.0, "dsra_months": 3},
])
def test_a_selection_written_by_another_writer_cannot_make_the_real_run_discard_shl_or_dsra(env, monkeypatch, recorded):
    """The canonical field pipeline (batch/import writers) accepts any WELL-FORMED selection. One that names a structure the
    Working Copy does not carry must be refused by the real Run: no calculation, no committed Run, typed reason, page still renders."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    project = env.create("solar")
    cod, months = TIMELINE["solar"]
    _set(env, project, "project_setup.technical.construction_months", str(months))
    _set(env, project, "project_setup.technical.cod_date", cod)
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    WorkbookUpdateService.apply_draft_update(
        ws=get_workspace_state(OWNER, project.project_id), field_id=cfg.FIELD_ID,
        raw_value=cfg.candidate_config_json(recorded), content_hash=tokens(page.text)["content_hash"],
        workbook_version=WORKBOOK.version, project_record=project)
    assert cfg.frequency_label(_ws(project).draft_snapshot.get(cfg.SNAPSHOT_KEY)) == "3/3"   # accepted as a well-formed selection
    assert env.client.get("/v2/workbook", params={"project": project.project_code}).status_code == 200
    response = _run(env, project)
    assert "QUARTERLY_FINANCING_STRUCTURE_MISMATCH" in response.text
    assert "UNCLASSIFIED_ENGINE_FAILURE" not in response.text
    assert not _ws(project).last_runtime_snapshot_id
    from app.persistence.run_history_repository import get_run_history
    assert get_run_history(OWNER, project.project_id) == []


def test_every_workbook_sheet_stays_renderable_with_an_unbound_3_3_selection_and_the_run_commits_nothing(env, monkeypatch):
    """Correction B: the typed refusal belongs to the Run. A saved 3/3 selection whose recorded structure the Working Copy does not carry
    must not break ANY page render (the throwing call sites were the full-page CAPEX/OPEX/Tax view-model materialisations), the Run
    refuses with the typed code before any calculation, and neither the Last Run nor the Run history changes."""
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.presentation_views import PRESENTATION_SHEETS
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    project = env.create("solar")
    cod, months = TIMELINE["solar"]
    _set(env, project, "project_setup.technical.construction_months", str(months))
    _set(env, project, "project_setup.technical.cod_date", cod)
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    recorded = {"sponsor_funding_mode": "EQUITY_ONLY", "shl_amount_keur": 0.0, "clean_shl_principal_keur": 0.0, "dsra_months": 0}
    WorkbookUpdateService.apply_draft_update(
        ws=get_workspace_state(OWNER, project.project_id), field_id=cfg.FIELD_ID, raw_value=cfg.candidate_config_json(recorded),
        content_hash=tokens(page.text)["content_hash"], workbook_version=WORKBOOK.version, project_record=project)
    before = _ws(project)
    draft_before = dict(before.draft_snapshot)
    for sheet in sorted(PRESENTATION_SHEETS) + ["overview", "outputs"]:
        response = env.client.get("/v2/workbook", params={"project": project.project_code, "sheet": sheet})
        assert response.status_code == 200, sheet
    response = _run(env, project)
    assert "QUARTERLY_FINANCING_STRUCTURE_MISMATCH" in response.text
    assert "Could not build project inputs" not in response.text
    after = _ws(project)
    assert not after.last_runtime_snapshot_id and get_run_history(OWNER, project.project_id) == []
    assert dict(after.draft_snapshot) == draft_before                        # the saved selection and the Working Copy are untouched

"""Workflow E — Developer Economics & Investment Decision workspace (presentation only).

Proves: the workspace is a projection of the canonical Developer Economics V1 calculator
(no second calculator), disabled is a neutral state, fee modes/percent display, typed MOIC/IRR
availability, Expected NPV / margin stay unavailable with the exact missing authority, stage and
perspective are non-economic, compare-projects additions (stable sort, availability, freshness),
and the GET surfaces are read-only and owner-isolated.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from unittest import mock

import pytest

from app.project_factories import create_generic_solar_reference
from app.v2.decision_support_projection import (
    CrossProjectRow,
    build_cross_project_rows,
    sort_cross_project_rows,
)
from app.v2.developer_decision_projection import (
    EXPECTED_NPV_CONDITIONS,
    build_decision_panel,
    build_project_meta,
)
from app.v2.developer_economics_projection import (
    STATE_ACTIVE,
    STATE_DISABLED,
    STATE_INVALID,
    build_developer_workspace,
)
from finco_core.inputs import (
    DeveloperFeeMode,
    DevelopmentEconomicsInput,
    DevelopmentOutcome,
    DevelopmentSpendEntry,
)
from financial_engine.developer_economics import compute_developer_economics


@pytest.fixture(scope="module")
def solar():
    return create_generic_solar_reference()


def _cfg(solar, **kw):
    fc = solar.info.financial_close
    base = dict(
        enabled=True,
        spend_schedule=(DevelopmentSpendEntry(date(fc.year - 1, 3, 31), 1000.0),
                        DevelopmentSpendEntry(date(fc.year - 1, 9, 30), 500.0)),
        reimbursed_development_cost_keur=1200.0,
        developer_fee_value=300.0,
    )
    base.update(kw)
    return replace(solar, development_economics=DevelopmentEconomicsInput(**base))


# ---------------------------------------------------------------- workspace projection

class TestWorkspaceProjection:
    def test_disabled_and_absent_are_the_same_neutral_state(self, solar):
        absent = build_developer_workspace(solar)
        off = build_developer_workspace(
            replace(solar, development_economics=DevelopmentEconomicsInput()))
        assert absent.state == off.state == STATE_DISABLED
        assert absent.metrics == () and absent.vector == () and absent.total_spend == "—"

    def test_active_figures_equal_the_canonical_calculator(self, solar):
        pi = _cfg(solar)
        ws = build_developer_workspace(pi)
        res = compute_developer_economics(pi)
        assert ws.state == STATE_ACTIVE
        assert ws.total_spend == f"{res.total_development_spend_keur:,.1f}"
        assert ws.reimbursement == f"{res.reimbursed_development_cost_keur:,.1f}"
        assert ws.fee_amount == f"{res.developer_fee_keur:,.1f}"
        assert ws.total_receipts == f"{res.total_developer_receipts_keur:,.1f}"
        moic = next(m for m in ws.metrics if m.key == "developer_moic")
        assert moic.display == f"{res.developer_moic:.2f}x" and moic.available
        xirr = next(m for m in ws.metrics if m.key == "developer_xirr")
        assert xirr.display == f"{res.developer_xirr * 100:.2f}%"
        assert len(ws.vector) == len(res.cashflows)

    def test_reimbursement_and_fee_are_separate_project_uses(self, solar):
        ws = build_developer_workspace(_cfg(solar))
        labels = [l for l, _ in ws.uses_lines]
        assert labels == ["Development cost reimbursement", "Developer fee"]
        assert ws.project_uses_total == "1,500.0"

    def test_percentage_fee_displays_5_percent_and_uses_hard_capex(self, solar):
        pi = _cfg(solar, developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                  developer_fee_value=0.05)
        ws = build_developer_workspace(pi)
        assert ws.fee_input_display == "5.00% of hard CAPEX"
        assert "0.05%" not in ws.fee_input_display
        assert ws.fee_amount == f"{0.05 * pi.capex.hard_capex_keur:,.1f}"
        assert "hard_capex_keur" in ws.fee_basis_authority

    def test_fixed_fee_display(self, solar):
        ws = build_developer_workspace(_cfg(solar))
        assert ws.fee_input_display == "300.0 kEUR fixed"

    def test_abandoned_has_no_receipts_and_irr_unavailable_with_reason(self, solar):
        pi = _cfg(solar, outcome=DevelopmentOutcome.ABANDONED,
                  reimbursed_development_cost_keur=0.0, developer_fee_value=0.0)
        ws = build_developer_workspace(pi)
        xirr = next(m for m in ws.metrics if m.key == "developer_xirr")
        assert not xirr.available and xirr.display == "—" and xirr.reason
        assert ws.total_receipts == "0.0"      # genuine zero receipts, not "unavailable"

    def test_no_spend_makes_moic_unavailable_not_zero(self, solar):
        pi = _cfg(solar, spend_schedule=(), reimbursed_development_cost_keur=0.0,
                  developer_fee_value=250.0)
        ws = build_developer_workspace(pi)
        moic = next(m for m in ws.metrics if m.key == "developer_moic")
        assert not moic.available and moic.display == "—" and "denominator" in moic.reason

    def test_spend_after_financial_close_is_a_typed_invalid_state(self, solar):
        fc = solar.info.financial_close
        pi = _cfg(solar, spend_schedule=(DevelopmentSpendEntry(date(fc.year + 1, 1, 1), 10.0),),
                  reimbursed_development_cost_keur=0.0)
        ws = build_developer_workspace(pi)
        assert ws.state == STATE_INVALID
        assert ws.error_code == "DEV_ECON_SPEND_AFTER_FINANCIAL_CLOSE"
        assert ws.metrics == ()

    def test_reimbursement_above_spend_is_rejected_by_the_typed_contract(self):
        with pytest.raises(ValueError, match="REIMBURSEMENT_EXCEEDS_ELIGIBLE"):
            DevelopmentEconomicsInput(
                enabled=True,
                spend_schedule=(DevelopmentSpendEntry(date(2029, 1, 1), 100.0),),
                reimbursed_development_cost_keur=101.0)


# ---------------------------------------------------------------- investment decision

class TestDecisionPanel:
    def test_expected_npv_is_unavailable_with_all_eight_conditions_listed(self):
        panel = build_decision_panel({"project_npv_keur": 5000.0}, run_state="CURRENT")
        assert not panel.expected_npv.available and panel.expected_npv.display == "—"
        assert len(EXPECTED_NPV_CONDITIONS) == 8
        assert not any(c.satisfied for c in panel.conditions)
        assert "8 of 8" in panel.expected_npv.reason

    def test_project_npv_and_expected_npv_never_share_label_or_value(self):
        panel = build_decision_panel({"project_npv_keur": 5000.0}, run_state="CURRENT")
        assert panel.project_npv.label != panel.expected_npv.label
        assert panel.project_npv.available and "5,000" in panel.project_npv.display
        assert not panel.expected_npv.available

    def test_project_npv_unavailable_when_not_persisted_or_no_run(self):
        assert not build_decision_panel({"project_npv_keur": None}, run_state="CURRENT").project_npv.available
        assert not build_decision_panel({"project_npv_keur": 5.0}, run_state="NOT_RUN").project_npv.available
        assert not build_decision_panel({"project_npv_keur": True}, run_state="CURRENT").project_npv.available

    def test_persisted_zero_npv_is_a_value(self):
        panel = build_decision_panel({"project_npv_keur": 0.0}, run_state="CURRENT")
        assert panel.project_npv.available and panel.project_npv.display.startswith("0 ")

    def test_margin_is_unavailable_and_no_recommendation_language(self):
        panel = build_decision_panel({}, run_state="CURRENT")
        assert not panel.development_margin.available
        text = repr(panel).lower()
        for word in ("buy", "sell", "recommend"):
            assert word not in text.replace("no buy/sell", "")


class TestProjectMeta:
    def test_unset_is_not_inferred(self):
        m = build_project_meta(type("R", (), {"project_stage": None, "model_perspective": None})())
        assert m.stage == "Not set" and m.perspective == "Not set"
        assert not m.developer_emphasis

    def test_developer_perspective_is_emphasis_only(self):
        m = build_project_meta(type("R", (), {"project_stage": "development",
                                              "model_perspective": "developer"})())
        assert m.developer_emphasis and m.stage == "development"
        ws = build_developer_workspace(create_generic_solar_reference())
        assert ws.state == STATE_DISABLED     # perspective never enables the capability


# ---------------------------------------------------------------- comparison additions

def _row(code, **metrics):
    return CrossProjectRow(project_code=code, project_name=code, technology="t", country="c",
                           capacity_display="1 MW", runnable=True, ran_at_display="x",
                           metrics=metrics, ebitda_margin="—")


class TestStableSort:
    def test_negative_zero_positive_and_unavailable_last_descending(self):
        rows = [_row("a", project_irr="—"), _row("b", project_irr="-2.00%"),
                _row("c", project_irr="0.00%"), _row("d", project_irr="7.50%")]
        out = [r.project_code for r in sort_cross_project_rows(rows, "project_irr", descending=True)]
        assert out == ["d", "c", "b", "a"]

    def test_unavailable_is_last_ascending_too(self):
        rows = [_row("a", total_capex_keur="—"), _row("b", total_capex_keur="1,200"),
                _row("c", total_capex_keur="900")]
        out = [r.project_code for r in sort_cross_project_rows(rows, "total_capex_keur", descending=False)]
        assert out == ["c", "b", "a"]

    def test_ties_keep_selection_order(self):
        rows = [_row("a", min_dscr="1.30x"), _row("b", min_dscr="1.30x"), _row("c", min_dscr="1.30x")]
        for desc in (True, False):
            assert [r.project_code for r in sort_cross_project_rows(rows, "min_dscr", descending=desc)] == ["a", "b", "c"]

    def test_additions_flow_through_rows(self):
        rows = build_cross_project_rows([{
            "project_code": "p", "project_name": "P", "runnable": True,
            "runtime_summary": {"project_npv_keur": -12.0}, "stage": "development",
            "perspective": "developer", "run_state": "STALE", "run_identity": "abcd1234"}])
        r = rows[0]
        assert (r.stage, r.perspective, r.run_state, r.run_identity) == (
            "development", "developer", "STALE", "abcd1234")
        assert r.metrics["project_npv_keur"] == "-12"
        none = build_cross_project_rows([{"project_code": "q", "project_name": "Q", "runnable": False}])[0]
        assert none.run_state == "NOT_RUN" and none.metrics == {}


# ---------------------------------------------------------------- routes

@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "dd.db"))
    db.init_db()
    yield


def _client(user_id, template="generic_solar_reference", name="DD Project"):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web
    record = create_reference_seeded_project(
        user_id=user_id, template_source=template, requested_name=name, capacity_mw=64.0)
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
    return TestClient(main_web.app, raise_server_exceptions=True), cookies, record


def _run(client, cookies, code):
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies)
    h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
    v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
    r = client.post("/v2/workbook/run", data={"project": code, "content_hash": h, "workbook_version": v},
                    cookies=cookies, headers={"HX-Request": "true"})
    assert r.status_code == 200


def _set_meta(project_id, stage, perspective):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        cur.execute("UPDATE projects SET project_stage=?, model_perspective=? WHERE project_id=?",
                    (stage, perspective, project_id))


class TestDeveloperDecisionPage:
    def test_unknown_project_without_credentials_never_renders(self, seeded_db):
        from fastapi.testclient import TestClient
        import main_web
        r = TestClient(main_web.app).get("/v2/developer-decision?project=nope", follow_redirects=False)
        assert r.status_code in (302, 404) and "dd-page" not in r.text

    def test_disabled_page_shows_neutral_state_and_bridge_gap(self, seeded_db):
        client, cookies, rec = _client("dd-u1")
        html = client.get(f"/v2/developer-decision?project={rec.project_code}", cookies=cookies).text
        assert 'data-testid="dd-bridge-gap"' in html
        assert "Developer Economics: DISABLED" in html
        assert 'data-testid="dd-a-spend"' not in html          # no fabricated sections
        assert 'data-testid="dd-expected_npv"' in html and 'data-available="false"' in html
        assert "Stage: Not set" in html and "Perspective: Not set" in html
        assert "recommend" not in html.lower().replace("no buy/sell recommendation", "")

    def test_other_users_project_is_not_found(self, seeded_db):
        _, _, rec = _client("dd-owner", name="Owner Only Project")
        client, cookies, _ = _client("dd-intruder")
        assert client.get(f"/v2/developer-decision?project={rec.project_code}", cookies=cookies).status_code == 404

    def test_stage_and_perspective_shown_and_do_not_change_freshness_or_enable(self, seeded_db):
        client, cookies, rec = _client("dd-u2")
        _run(client, cookies, rec.project_code)
        before = client.get(f"/v2/developer-decision?project={rec.project_code}", cookies=cookies).text
        assert "Last Run: CURRENT" in before
        _set_meta(rec.project_id, "development", "developer")
        after = client.get(f"/v2/developer-decision?project={rec.project_code}", cookies=cookies).text
        assert "Stage: development" in after and "Perspective: developer" in after
        assert "Last Run: CURRENT" in after                    # metadata never causes STALE
        assert "Developer Economics: DISABLED" in after        # perspective never enables
        assert "changes presentation emphasis only" in after

    def test_get_is_read_only_and_runs_no_engine(self, seeded_db):
        client, cookies, rec = _client("dd-u3")
        _run(client, cookies, rec.project_code)
        from app.persistence.workspace_repository import get_workspace_state
        ws0 = get_workspace_state(rec.user_id if hasattr(rec, "user_id") else "dd-u3", rec.project_id)
        with mock.patch("app.services.production_financial_authority.run_clean_production",
                        side_effect=AssertionError("engine must not run")):
            r = client.get(f"/v2/developer-decision?project={rec.project_code}", cookies=cookies)
        assert r.status_code == 200
        ws1 = get_workspace_state(rec.user_id if hasattr(rec, "user_id") else "dd-u3", rec.project_id)
        assert ws0.updated_at == ws1.updated_at
        assert ws0.last_runtime_composite_hash == ws1.last_runtime_composite_hash


class TestCompareProjectsAdditions:
    def test_stage_perspective_identity_and_freshness(self, seeded_db):
        client, cookies, rec = _client("dd-c1")
        _set_meta(rec.project_id, "financing", "ipp")
        _run(client, cookies, rec.project_code)
        html = client.get(f"/v2/compare-projects?projects={rec.project_code}", cookies=cookies).text
        assert f'data-testid="ds-stage-{rec.project_code}">Financing' in html
        assert f'data-testid="ds-perspective-{rec.project_code}">IPP' in html
        assert re.search(rf'ds-identity-{rec.project_code}">[0-9a-f]{{8}}', html)
        assert f'ds-freshness-{rec.project_code}">CURRENT' in html
        assert 'data-ds-metric="developer_returns"' in html

    def test_no_run_project_is_not_run_and_unavailable(self, seeded_db):
        client, cookies, rec = _client("dd-c2")
        html = client.get(f"/v2/compare-projects?projects={rec.project_code}", cookies=cookies).text
        assert f'ds-freshness-{rec.project_code}">NOT RUN' in html
        assert "NO CANONICAL RUN" in html

    def test_five_project_cap_preserved(self, seeded_db):
        client, cookies, first = _client("dd-c3", name="C0")
        codes = [first.project_code]
        for i in range(1, 7):
            _, _, r = _client("dd-c3", name=f"C{i}")
            codes.append(r.project_code)
        html = client.get(f"/v2/compare-projects?projects={','.join(codes)}", cookies=cookies).text
        assert len(re.findall(r'data-testid="ds-col-', html)) == 5

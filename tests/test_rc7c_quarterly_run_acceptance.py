"""RC-7C: a REAL committed 6/6 Run and a REAL committed 3/3 Run of the SAME saved project share the economic calendar.

Working Copy -> Run (6/6) -> select 3/3 -> Run: the committed Run history, statements and export declare the same operating start/end date, the same
operating days, the same production, OPEX and depreciation, and the v2 (date-authoritative) policy version as evidence. Only the financing
cash-flow timing (Senior interest/principal dates, DSCR) is allowed to differ. The admission gate is opened ONLY by monkeypatch (acceptance
evidence); ``ACTIVATION_ENABLED`` stays False. Historical Runs are never touched.
"""
from __future__ import annotations

import pytest

from app.workbook import quarterly_frequency_config as cfg
from finco_core.engine.calendar_policy import QUARTERLY_CANDIDATE_POLICY_VERSION_V2
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_rc7_capex_profile_run import OWNER, _latest, _run, _ws  # noqa: F401
from tests.test_rc7b_quarterly_production_acceptance import TIMELINE, _frequency, _set, eligible_references, _state


def _capture(env, project, monkeypatch):
    from app.services import production_financial_authority as authority
    captured = []
    real = authority.run_clean_production

    def observe(*args, **kwargs):
        result = real(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(authority, "run_clean_production", observe)
    assert _run(env, project).status_code == 200
    monkeypatch.setattr(authority, "run_clean_production", real)
    assert len(captured) == 1
    return captured[0]


def _operating(clean):
    model = clean.g2c_result.financing_result.project_model_result
    return [p for p in model.periods if p.is_operation], model


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_committed_6_6_and_3_3_runs_share_the_economic_calendar(env, monkeypatch, kind):
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)          # acceptance evidence only
    eligible_references(monkeypatch)
    project = env.create(kind)
    cod, months = TIMELINE[kind]
    _set(env, project, "project_setup.technical.construction_months", str(months))
    _set(env, project, "project_setup.technical.cod_date", cod)

    semi = _capture(env, project, monkeypatch)
    semi_entry = _latest(project)
    semi_before = semi_entry.to_dict()
    _frequency(env, project, "3/3")
    quarterly = _capture(env, project, monkeypatch)
    entry = _latest(project)

    s_ops, s_model = _operating(semi)
    q_ops, q_model = _operating(quarterly)
    # D-03 / D-04: same operating start, same operating end, same operating days; each model year spans the same dates
    assert s_ops[0].period_start == q_ops[0].period_start and s_ops[-1].period_end == q_ops[-1].period_end
    # each six-month row is subdivided into two quarters (one when the opening stub is already a single quarter)
    for row in s_ops:
        inside = [p for p in q_ops if row.period_start <= p.period_start and p.period_end <= row.period_end]
        assert len(inside) in (1, 2) and inside[0].period_start == row.period_start and inside[-1].period_end == row.period_end
    assert len(q_ops) in (2 * len(s_ops), 2 * len(s_ops) - 1)
    assert sum((p.period_end - p.period_start).days for p in s_ops) == sum((p.period_end - p.period_start).days for p in q_ops)
    for year in {p.year_index for p in s_ops}:
        s_year = [p for p in s_ops if p.year_index == year]
        q_year = [p for p in q_ops if p.year_index == year]
        assert (s_year[0].period_start, s_year[-1].period_end) == (q_year[0].period_start, q_year[-1].period_end)
    assert {p.year_index for p in s_ops} == {p.year_index for p in q_ops}
    # no invented revenue and no unexplained increase in cost: quarter-end COD and a quarter-end PPA expiry keep the exact same economics
    for attribute in ("production_mwh", "opex_keur", "book_depreciation_keur"):
        s_total, q_total = sum(getattr(p, attribute) for p in s_ops), sum(getattr(p, attribute) for p in q_ops)
        assert q_total == pytest.approx(s_total, rel=1e-9), attribute
    # revenue: identical in every model year except the one in which the PPA expires inside a six-month row (D-05: the released row keeps the PPA
    # tariff to its end, the 3/3 axis switches on the quarter boundary where the PPA actually expires; no intra-quarter split is invented)
    from dateutil.relativedelta import relativedelta
    pi = semi.project_inputs
    cod_date = s_ops[0].period_start
    ppa_end = cod_date + relativedelta(years=int(pi.revenue.ppa_term_years))
    expiry_years = {p.year_index for p in s_ops if p.period_start < ppa_end < p.period_end}

    def by_year(ops):
        out = {}
        for p in ops:
            out[p.year_index] = out.get(p.year_index, 0.0) + p.revenue_keur
        return out
    s_rev, q_rev = by_year(s_ops), by_year(q_ops)
    for year in s_rev:
        if year not in expiry_years:
            assert q_rev[year] == pytest.approx(s_rev[year], rel=1e-9), year
    assert sum(q_rev.values()) == pytest.approx(sum(s_rev.values()), rel=2e-3)
    # the committed Run declares the date-authoritative policy version; the earlier 6/6 Run is byte-identical
    evidence = entry.runtime_summary["financing_evidence"]
    assert evidence["operating_frequency"] == "3/3"
    assert evidence["operating_calendar_policy"]["version"] == QUARTERLY_CANDIDATE_POLICY_VERSION_V2
    assert evidence["classification"] == "RC7B_QUARTERLY_CANDIDATE_RELEASE_CLOSED"
    from app.persistence.run_history_repository import get_run_history
    assert next(h for h in get_run_history(OWNER, project.project_id) if h.history_id == semi_entry.history_id).to_dict() == semi_before
    # financing may differ: Senior service is quarterly, and the final Senior payment falls on the same maturity date
    assert len(q_model.senior_debt.period_indices) in (2 * len(s_model.senior_debt.period_indices), 2 * len(s_model.senior_debt.period_indices) - 1)
    assert s_model.periods[s_model.senior_debt.period_indices[-1]].period_end == q_model.periods[q_model.senior_debt.period_indices[-1]].period_end
    assert abs(q_model.senior_debt.senior_debt_closing_keur[-1]) < 1e-6
    assert cfg.ACTIVATION_ENABLED is True                          # only by the monkeypatch above; the committed constant is asserted below


def test_the_committed_activation_constant_stays_off():
    import importlib
    import inspect
    source = inspect.getsource(importlib.import_module("app.workbook.quarterly_frequency_config"))
    assert "ACTIVATION_ENABLED = False" in source

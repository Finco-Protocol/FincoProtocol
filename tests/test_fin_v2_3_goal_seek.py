import asyncio
from dataclasses import replace

import pytest

from app.services.goal_seek import solve_tariff_for_metric


@pytest.mark.parametrize('metric,target', [('min_dscr',1.2),('project_npv',1000.),('sponsor_npv',500.)])
def test_financial_units_solve_and_rerun_with_bounded_budget(metric,target):
    seen=[]
    async def evaluate(tariffs):
        seen.extend(tariffs)
        return [t/50 if metric=='min_dscr' else t*20 for t in tariffs]
    r=asyncio.run(solve_tariff_for_metric(project_type='solar',current_tariff=50.,target_value=target,
                                         metric_key=metric,evaluate_batch=evaluate,tolerance=1e-6))
    assert r.solved and abs(r.achieved_metric_value-target)<=1e-6
    assert r.model_evaluations==len(seen)<=40
    assert seen[-2]==r.solved_input_value


def test_financing_regime_switch_near_proposed_root_is_refused():
    async def evaluate(tariffs):return [t/50 for t in tariffs]
    evaluate.regime_at=lambda t:'GEARING_PEAK_A' if t<50 else 'DSCR_PEAK_B'
    r=asyncio.run(solve_tariff_for_metric(project_type='solar',current_tariff=50,target_value=1.,
        metric_key='min_dscr',evaluate_batch=evaluate))
    assert r.status=='NON_MONOTONIC_TARGET' and r.solved_input_value is None


@pytest.mark.parametrize('key',['min_dscr','project_npv','sponsor_npv'])
def test_unavailable_targets_are_never_substituted_with_zero(key):
    async def evaluate(tariffs):return [None for t in tariffs]
    r=asyncio.run(solve_tariff_for_metric(project_type='solar',current_tariff=50,target_value=0,
        metric_key=key,evaluate_batch=evaluate))
    assert r.status=='TARGET_METRIC_UNAVAILABLE' and not r.solved


def test_real_canonical_sponsor_goal_seek_is_read_only_and_reverified(monkeypatch):
    from app.project_factories import create_generic_solar_reference
    from app.services.goal_seek import make_canonical_evaluator,resolve_metric
    from app.services.sensitivity_execution import run_sensitivity_points
    from app.runtime import model_execution
    pi=create_generic_solar_reference()
    before=repr(pi)
    # Execute the same canonical worker inline to observe all calls, without a
    # process scheduler or any persistence substitute in the financial path.
    async def inline(fn,*args,**kwargs):return fn(*args,**kwargs)
    monkeypatch.setattr(model_execution,'run_model_process',inline)
    evaluate=make_canonical_evaluator('Solar',pi,resolve_metric('total_sponsor_irr'))
    target=asyncio.run(evaluate([pi.revenue.ppa_base_tariff]))[0]+.001
    r=asyncio.run(solve_tariff_for_metric(project_type='solar',current_tariff=pi.revenue.ppa_base_tariff,
        target_value=target,metric_key='total_sponsor_irr',evaluate_batch=evaluate))
    assert r.solved,r
    verification=run_sensitivity_points('Solar',[replace(pi,revenue=replace(pi.revenue,ppa_base_tariff=r.solved_input_value))])[0]
    assert verification['kpis']['total_sponsor_xirr'].hex()==r.achieved_metric_value.hex()
    assert abs(r.achieved_metric_value-target)<=1e-4
    assert repr(pi)==before and r.model_evaluations<=40

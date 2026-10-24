"""Synthetic supplied-input arithmetic, not Financial Owner policy approval."""
from decimal import Decimal as D
from dataclasses import replace
import pytest
from research.wf09a.costing import Basis, Row, calculate

def row(tag='y1', energy='100', costs=('1','2','3','4','5'), factor='1'):
    return Row(tag,D(factor),D(energy),tuple(map(D,costs)),tuple((tag+':'+str(i),) for i in range(5)))
def basis(metric='levered_after_tax',charging='not_applicable'):
    return Basis(metric,'synthetic end-period disjoint costs; no debt principal','synthetic supplied factors','EUR','net exported AC MWh',charging)

def test_units_and_five_component_reconciliation():
    r=calculate((row(),),basis())
    assert r.status=='CANDIDATE' and r.numerator_keur==D(15)
    assert r.total_eur_mwh==D(150)==sum(r.components_eur_mwh)

def test_discount_axis_and_negative_cost_credit():
    r=calculate((row('y0','0',('0','10','0','0','0')),row('y1','100',('0','0','-2','0','0'),'.5')),basis())
    assert r.numerator_keur==9 and r.pv_energy_mwh==50 and r.total_eur_mwh==180

@pytest.mark.parametrize('periods',[1,4,12])
def test_equal_time_axis_aggregation(periods):
    # Split equal-factor cashflows only; different dated factors cannot be averaged.
    rows=tuple(row(str(i),str(120//periods),tuple(str(D(x)/periods) for x in ('12','24','36','48','60')),'.8') for i in range(periods))
    assert calculate(rows,basis()).total_eur_mwh==1500

@pytest.mark.parametrize('missing',['convention','rate_source'])
def test_missing_conventions_unavailable(missing):
    assert calculate((row(),),replace(basis(),**{missing:None})).status=='UNAVAILABLE'

@pytest.mark.parametrize('rows',[(),(row(energy='0'),)])
def test_zero_or_absent_energy_is_not_fabricated_zero(rows):
    assert calculate(rows,basis()).total_eur_mwh is None

@pytest.mark.parametrize('charging',['net_spread','not_applicable'])
def test_lcos_does_not_add_buy_leg_to_net_spread(charging):
    assert calculate((row(),),basis('lcos',charging)).status=='UNAVAILABLE'

def test_lcos_explicit_buy_leg_is_supplied_in_opex():
    assert calculate((row(costs=('0','10','2','0','0')),),basis('lcos','explicit_buy')).total_eur_mwh==120

def test_unlevered_excludes_finance_tax():
    with pytest.raises(ValueError):calculate((row(),),basis('unlevered_pre_financing'))
    assert calculate((row(costs=('1','2','3','0','0')),),basis('unlevered_pre_financing')).total_eur_mwh==60

def test_duplicate_source_amount_rejected_across_components_and_periods():
    r=row(); bad=replace(r,origins=(r.origins[0],)*5)
    with pytest.raises(ValueError):calculate((bad,),basis())
    with pytest.raises(ValueError):calculate((r,replace(r,period='y2')),basis())

@pytest.mark.parametrize('change',[{'discount_factor':D('NaN')},{'energy_mwh':D('-1')},{'discount_factor':D(0)},{'costs_keur':(D(1),)}])
def test_invalid_inputs_rejected(change):
    with pytest.raises(ValueError):calculate((replace(row(),**change),),basis())

def test_evidenced_zero_cost_and_empty_provenance_are_distinct():
    assert calculate((row(costs=('0',)*5),),basis()).total_eur_mwh==0
    with pytest.raises(ValueError):calculate((replace(row(),origins=((),)*5),),basis())

def test_duplicate_periods_and_mutable_records_rejected():
    with pytest.raises(ValueError):calculate((row(),row()),basis())
    with pytest.raises(ValueError):replace(row(),costs_keur=[D(0)]*5)
    with pytest.raises(ValueError):calculate([row()],basis())

@pytest.mark.parametrize('change',[{'currency':'USD'},{'metric':'unknown'},{'energy_boundary':''},{'charging':'unknown'}])
def test_unknown_or_incomparable_basis_rejected(change):
    with pytest.raises(ValueError):calculate((row(),),replace(basis(),**change))

def test_precision_does_not_depend_on_callers_decimal_context():
    from decimal import localcontext
    with localcontext() as ctx:
        ctx.prec=3
        low=calculate((row(energy='7'),),basis())
    with localcontext() as ctx:
        ctx.prec=60
        high=calculate((row(energy='7'),),basis())
    assert low==high

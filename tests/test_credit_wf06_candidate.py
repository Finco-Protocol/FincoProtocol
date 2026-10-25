"""Independent synthetic supplied-evidence oracles; no Financial Owner approval."""
from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction
import ast
from pathlib import Path
import pytest
from app.model_v2.credit_wf06_candidate import ACTIVATION_ENABLED, NON_AUTHORITATIVE
from app.model_v2.credit_wf06_candidate.pure import (
    Period,Row,Facility,Metric,dscr_capacity,size,sculpt,assess,propose_sweep,
)

PRIORITY=('DSCR','GEARING','EXPLICIT')

def periods(cash=('100','100','100'), rate='0', target='1.25', start=1):
    return tuple(Period(i,None if c is None else D(c),D(rate),D(target),D(1),'synthetic canonical cash + explicit period rates/DF') for i,c in enumerate(cash,start))


def fixed(name='a', debt='90', n=3, bullet=False, start=1):
    balance=D(debt);rows=[]
    for i in range(1,n+1):
        principal=(balance if i==n else D(0)) if bullet else D(debt)/n
        rows.append(Row(i,balance,D(0),principal,balance-principal));balance-=principal
    return Facility(name,D(debt),start,n,tuple(rows),'synthetic contractual ledger')


def credit(ps,fs,shares=None,covenant=None):
    return assess(ps,fs,aggregate_loan_end=max(f.maturity for f in fs),shares=shares,allocation_basis='synthetic explicit attribution' if shares is not None else None,
                  covenant_dscr=covenant,discount_convention='synthetic end-period supplied DF, t0 debt',
                  max_maturity_principal=tuple((f.identifier,f.commitment) for f in fs))


def sizing(mode,ps,explicit=None,uses=None,gearing=None):
    return size(mode,explicit=explicit,eligible_uses=uses,gearing=gearing,
                capacity=dscr_capacity(ps,ps[0].index,ps[-1].index,debt_independent=True),priority=PRIORITY)


def test_closed_form_capacity_independent_fraction_oracle():
    ps=periods(rate='.1');oracle=sum((Fraction(80,1)/Fraction(11,10)**i for i in range(1,4)),Fraction())
    got=dscr_capacity(ps,1,3,debt_independent=True)
    assert float(got.value)==pytest.approx(float(oracle),abs=1e-12)


@pytest.mark.parametrize('rate',['0','.05'])
def test_single_matches_released_backward_capacity_when_semantics_match(rate):
    from datetime import date
    from types import SimpleNamespace
    from financial_engine.senior_debt.solver import _backward_dscr_capacity
    from financial_engine.senior_debt.policy import DayCountConvention
    ps=periods(rate='.05');dates={i:(date(2024+i,1,1),date(2024+i,1,1).replace(year=2025+i)) for i in (1,2,3)}
    # Use zero interest to remove actual-day convention differences from this seam.
    ps=periods(rate=rate)
    policy=SimpleNamespace(repayment_start_period_index=1,maturity_period_index=3,target_dscr=1.25,day_count_convention=DayCountConvention.ACT_365)
    actual=_backward_dscr_capacity({i:100. for i in (1,2,3)},{i:float(rate) for i in (1,2,3)},dates,(1,2,3),policy)
    assert float(dscr_capacity(ps,1,3,debt_independent=True).value)==pytest.approx(actual,abs=1e-12)


@pytest.mark.parametrize('uses,gearing,expected,binding',[('1000','.5','240','DSCR'),('100','.5','50','GEARING'),('480','.5','240','DSCR')])
def test_minimum_constraint_and_explicit_priority(uses,gearing,expected,binding):
    r=sizing('MINIMUM',periods(),D(300),D(uses),D(gearing))
    assert r.amount==D(expected) and r.binding[0]==binding
    assert r.numerical=='CLOSED_FORM_NOT_ITERATIVE' and r.lender_acceptance=='NOT_ASSESSED'


def test_fixed_commitment_below_one_is_not_resized_or_approved():
    ps=periods(('10','10','10'));s=sizing('EXPLICIT',ps,D(90),D(100),D('.5'))
    assert s.amount==90 and s.breaches==('DSCR','GEARING')
    r=credit(ps,(fixed(),),covenant=D('1.2'))
    assert r.accounting=='RECONCILED' and r.cash_feasibility==r.covenant_feasibility=='BREACH'
    with localcontext() as ctx:
        ctx.prec=50
        assert r.aggregate_dscr[0][1].value==D(10)/30


def test_fixed_gearing_does_not_change_to_dscr_or_repayment_mode():
    r=sizing('GEARING',periods(('1','1','1')),uses=D(100),gearing=D('.8'))
    assert r.amount==80 and r.breaches==('DSCR',)


def test_three_staggered_mixed_contracts_sum_once():
    ps=periods(('300',)*4)
    fs=(fixed('a','60',2),fixed('b','90',3,True),fixed('c','120',4))
    r=credit(ps,fs)
    assert [m.value for _,m in r.aggregate_dscr]==[D(5),D(5),D('2.5'),D(10)]
    assert r.cash_feasibility=='FEASIBLE' and r.covenant_feasibility=='NOT_ASSESSED'
    assert all(m.status=='UNAVAILABLE' for _,rows in r.facility_dscr for _,m in rows)
    assert fs[1].rows[-1].principal==90


def test_aggregate_shortfall_cannot_pass_individual_full_cfads():
    ps=periods(('100',));fs=tuple(fixed(x,'40',1) for x in ('a','b','c'))
    assert credit(ps,fs).cash_feasibility=='BREACH'
    with pytest.raises(ValueError,match='more than once'):
        credit(ps,fs,shares=tuple((x,(D(1),)) for x in ('a','b','c')))


def test_allocated_ratios_and_loan_project_life_hand_calculation():
    ps=tuple(replace(p,discount_factor=df) for p,df in zip(periods(('120','120','120')),map(D,('.9','.8','.7'))))
    fs=(fixed('a','60',2),fixed('b','60',3))
    r=credit(ps,fs,shares=(('a',(D('.5'),)*3),('b',(D('.5'),)*3)))
    assert r.llcr.value==D('2.4') and r.plcr.value==D('2.4')
    assert r.facility_coverage[0][1].value==D('1.7')
    assert r.facility_coverage[0][2].value==D('2.4')
    assert r.facility_dscr[0][1][0][1].value==2


@pytest.mark.parametrize('cash,expected',[(('0','0','0'),'CANDIDATE'),((None,'2','3'),'UNAVAILABLE'),(('-1','2','3'),'UNAVAILABLE')])
def test_zero_missing_negative_sizing(cash,expected):
    r=dscr_capacity(periods(cash),1,3,debt_independent=True)
    assert r.status==expected
    if expected=='UNAVAILABLE':assert r.value is None
    else:assert r.value==0


def test_nonmonotone_endogenous_solver_is_not_fabricated():
    cap=dscr_capacity(periods(),1,3,debt_independent=False)
    r=size('MINIMUM',explicit=None,eligible_uses=D(100),gearing=D('.5'),capacity=cap,priority=PRIORITY)
    assert r.status=='UNAVAILABLE' and r.amount is None


def test_missing_coverage_discount_and_zero_debt_undefined():
    ps=periods((None,'100','100'));fs=(fixed(),)
    r=credit(ps,fs,covenant=D('1.2'));assert r.cash_feasibility=='UNAVAILABLE' and r.llcr.value is None
    zero=credit(periods(),(fixed(debt='0'),))
    assert zero.llcr.status=='UNDEFINED' and all(x.status=='UNDEFINED' for _,x in zero.aggregate_dscr)
    r=assess(periods(),fs,aggregate_loan_end=3,covenant_dscr=None,discount_convention=None,max_maturity_principal=(('a',D(90)),))
    assert r.llcr.status=='UNAVAILABLE'


def test_sculpt_interest_balance_grace_and_terminal_shortfall():
    ps=periods(('100',)*3,rate='.1')
    f=sculpt('a',D(100),ps,2,3,max_maturity_principal=D(100),source='synthetic fixed commitment')
    assert f.rows[0].principal==0 and f.rows[0].interest==10
    assert all(r.opening-r.principal==r.closing for r in f.rows)
    assert f.rows[-1].closing==0 and f.commitment==100
    bad=sculpt('a',D(1000),ps,1,3,max_maturity_principal=D(1000),source='synthetic')
    assert bad.commitment==1000 and bad.rows[-1].closing>0
    assert credit(ps,(bad,)).contractual_feasibility=='BREACH'


def test_interest_starvation_caps_capacity_no_capitalization():
    ps=periods(('1','100','100'),rate='.1',target='1')
    assert dscr_capacity(ps,1,3,debt_independent=True).value==10
    f=sculpt('a',D(10),ps,1,3,max_maturity_principal=D(10),source='synthetic')
    assert f.rows[0].principal==0 and f.rows[0].closing==10


@pytest.mark.parametrize('start,maturity',[(0,3),(4,3),(1,4)])
def test_invalid_window(start,maturity):
    with pytest.raises(ValueError):dscr_capacity(periods(),start,maturity,debt_independent=True)


def test_balloon_limit_enforced_without_debt_resize():
    with pytest.raises(ValueError,match='maturity principal cap'):
        sculpt('a',D(90),periods(('0','0','100'),target='1'),1,3,max_maturity_principal=D(20),source='synthetic')


def test_sweep_residual_once_no_waterfall_mutation():
    ps=periods();fs=(fixed('a'),fixed('b'))
    proposal=propose_sweep(ps,fs,period_index=1,available_after_reserves=D(40),shares=(('a',D('.5')),('b',D('.5'))),policy_source='hypothetical owner proposal')
    assert proposal==( ('a',D(20)),('b',D(20)) )
    assert fs[0].rows[0].closing==60
    with pytest.raises(ValueError):propose_sweep(ps,fs,period_index=1,available_after_reserves=D(41),shares=(('a',D('.5')),('b',D('.5'))),policy_source='synthetic')


def test_canonical_period_ids_not_renumbered():
    ps=periods(start=7)
    f=sculpt('a',D(90),ps,7,9,max_maturity_principal=D(90),source='synthetic')
    assert tuple(r.index for r in f.rows)==(7,8,9)
    assert credit(ps,(f,)).cash_feasibility=='FEASIBLE'


def test_corrupt_ledger_and_missing_axis_rejected():
    f=fixed();ps=periods()
    for bad in (replace(f,rows=f.rows[:-1]),replace(f,rows=(replace(f.rows[0],closing=D(999)),)+f.rows[1:])):
        with pytest.raises(ValueError):credit(ps,(bad,))
    with pytest.raises(ValueError):credit(ps,(f,f))
    with pytest.raises(ValueError):credit(ps,(replace(f,rows=list(f.rows)),))


def test_release_and_import_boundaries():
    assert NON_AUTHORITATIVE and not ACTIVATION_ENABLED
    root=Path(__file__).resolve().parents[1]/'app/model_v2/credit_wf06_candidate'
    for f in root.glob('*.py'):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node,ast.Import):names=[x.name for x in node.names]
            elif isinstance(node,ast.ImportFrom):names=[node.module or '']
            else:continue
            assert all(n.split('.')[0] in {'dataclasses','decimal','functools','typing'} for n in names)


def test_sizing_target_is_not_a_covenant_or_cash_feasibility():
    ps=periods(('100','2000'),rate='.1')
    f=sculpt('a',D(900),ps,2,2,max_maturity_principal=D(900),source='synthetic')
    assert f.target_feasibility=='BREACH'
    r=credit(ps,(f,))
    assert r.cash_feasibility=='FEASIBLE' and r.covenant_feasibility=='NOT_ASSESSED'
    assert r.lender_acceptance=='NOT_ASSESSED'


@pytest.mark.parametrize('bad',[D('NaN'),D('Infinity'),D('-1')])
def test_invalid_discount_factors_fail_closed(bad):
    ps=periods();ps=(replace(ps[0],discount_factor=bad),)+ps[1:]
    with pytest.raises(ValueError):credit(ps,(fixed(),))


def test_allocation_partial_cash_is_not_implicitly_duplicated():
    ps=periods();fs=(fixed('a'),fixed('b'))
    r=credit(ps,fs,shares=(('a',(D('.25'),)*3),('b',(D('.25'),)*3)))
    with localcontext() as ctx:
        ctx.prec=50
        assert r.facility_dscr[0][1][0][1].value==D(25)/30
        assert r.aggregate_dscr[0][1].value==D(100)/60


def test_monotonic_supplied_cash_capacity_does_not_invent_endogenous_guarantee():
    ps=periods()
    assert dscr_capacity(periods(('200',)*3),1,3,debt_independent=True).value>=dscr_capacity(ps,1,3,debt_independent=True).value
    assert sizing('MINIMUM',ps,uses=D(100),gearing=D('.5')).amount<=sizing('MINIMUM',ps,uses=D(200),gearing=D('.5')).amount


def test_ambient_rounding_does_not_change_candidate():
    from decimal import ROUND_UP,ROUND_DOWN
    with localcontext() as ctx:
        ctx.prec=3;ctx.rounding=ROUND_UP
        low=dscr_capacity(periods(rate='.1'),1,3,debt_independent=True)
    with localcontext() as ctx:
        ctx.prec=60;ctx.rounding=ROUND_DOWN
        high=dscr_capacity(periods(rate='.1'),1,3,debt_independent=True)
    assert low==high


def test_borrower_gearing_cap_applies_to_sum_of_fixed_facilities_once():
    from app.model_v2.credit_wf06_candidate.pure import check_committed_limits
    fs=(fixed('a','60'),fixed('b','60'))
    r=check_committed_limits(periods(),fs,eligible_uses=D(100),gearing=D('.8'),aggregate_capacity=None,priority=PRIORITY)
    assert r.amount==120 and r.breaches==('GEARING',)
    assert fs[0].commitment==60 and fs[1].commitment==60


def test_cash_coverage_and_contractual_balloon_limit_are_distinct():
    ps=periods(('100',));f=fixed(debt='90',n=1,bullet=True)
    r=assess(ps,(f,),aggregate_loan_end=1,covenant_dscr=None,discount_convention='synthetic',max_maturity_principal=(('a',D(20)),))
    assert r.cash_feasibility=='FEASIBLE' and r.contractual_feasibility=='BREACH'


def test_fixed_debt_retains_unknown_capacity_as_unknown_not_waived():
    r=sizing('EXPLICIT',periods((None,'100','100')),explicit=D(90))
    assert r.amount==90 and r.unavailable_constraints==('DSCR',)
    assert r.lender_acceptance=='NOT_ASSESSED'

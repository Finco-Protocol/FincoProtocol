"""Immutable, supplied-CFADS credit proposals. Monetary units are kEUR.

No endogenous tax/CFADS solve, approval, funding, or production waterfall.
"""
from dataclasses import dataclass
from decimal import Decimal as D, Context, ROUND_HALF_EVEN, localcontext
from functools import wraps
from typing import Literal


def arithmetic(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            return fn(*args, **kwargs)
    return call


def amount(x, *, positive=False):
    if not isinstance(x,D) or not x.is_finite() or (positive and x<=0):
        raise ValueError('finite Decimal required; positive where declared')
    return x


@dataclass(frozen=True)
class Period:
    index: int
    cfads: D | None
    interest_factor: D
    sizing_target: D
    discount_factor: D
    source: str


@dataclass(frozen=True)
class Row:
    index: int
    opening: D
    interest: D
    principal: D
    closing: D

    @property
    @arithmetic
    def service(self):
        return self.interest+self.principal


@dataclass(frozen=True)
class Facility:
    identifier: str
    commitment: D
    repayment_start: int
    maturity: int
    rows: tuple[Row, ...]
    source: str
    target_feasibility: str = 'NOT_ASSESSED'

    def __post_init__(self):
        if not isinstance(self.rows,tuple):raise ValueError('immutable rows required')


@dataclass(frozen=True)
class Metric:
    status: str
    value: D | None
    reason: str


@dataclass(frozen=True)
class Applicability:
    name: str
    state: Literal['REQUIRED', 'INAPPLICABLE']
    reason: str


@dataclass(frozen=True)
class ConstraintEvidence:
    name: str
    applicability: str
    state: str
    value: D | None
    reason: str


@dataclass(frozen=True)
class AccrualPeriod:
    index: int
    annual_rate: D
    year_fraction: D


@dataclass(frozen=True)
class InterestEvidence:
    facility_id: str
    periods: tuple[AccrualPeriod, ...]
    source: str
    convention: str

    def __post_init__(self):
        if not isinstance(self.periods, tuple):
            raise ValueError('immutable independent accrual periods required')


@dataclass(frozen=True)
class Sizing:
    status: str
    amount: D | None
    constraints: tuple[tuple[str,D], ...]
    binding: tuple[str, ...]
    breaches: tuple[str, ...]
    numerical: str
    lender_acceptance: str = 'NOT_ASSESSED'
    unavailable_constraints: tuple[str,...] = ()
    evidence: tuple[ConstraintEvidence,...] = ()
    complete: bool = False


@dataclass(frozen=True)
class Credit:
    aggregate_dscr: tuple[tuple[int,Metric], ...]
    facility_dscr: tuple[tuple[str,tuple[tuple[int,Metric], ...]], ...]
    llcr: Metric
    plcr: Metric
    facility_coverage: tuple[tuple[str,Metric,Metric], ...]
    principal_reconciliation: str
    interest_reconciliation: tuple[tuple[str,str], ...]
    accounting: str
    cash_feasibility: str
    contractual_feasibility: str
    covenant_feasibility: str
    lender_acceptance: str = 'NOT_ASSESSED'


def axis(periods):
    if not isinstance(periods,tuple) or not periods:raise ValueError('immutable nonempty canonical axis required')
    if tuple(p.index for p in periods)!=tuple(range(periods[0].index,periods[0].index+len(periods))):
        raise ValueError('contiguous canonical operating axis required')
    for p in periods:
        if type(p.index) is not int or p.index<0:raise ValueError('canonical integer indices required')
        if not isinstance(p.source,str) or not p.source:raise ValueError('CFADS/rate/discount provenance required')
        for x in (p.interest_factor,p.sizing_target,p.discount_factor):amount(x)
        if p.interest_factor<0 or p.sizing_target<=0 or p.discount_factor<=0:
            raise ValueError('unsupported rate, target or discount factor')
        if p.cfads is not None:amount(p.cfads)


def window(periods,start,maturity):
    axis(periods)
    if type(start) is not int or type(maturity) is not int or not periods[0].index<=start<=maturity<=periods[-1].index:
        raise ValueError('invalid grace/repayment/maturity window')


def missing(reason):return Metric('UNAVAILABLE',None,reason)


@arithmetic
def ratio(numerator,denominator):
    if numerator is None:return missing('missing canonical CFADS')
    if denominator<=0:return Metric('UNDEFINED',None,'no positive debt/service denominator')
    return Metric('CANDIDATE',numerator/denominator,'supplied evidence only')


@arithmetic
def dscr_capacity(periods: tuple[Period,...], start: int, maturity: int, *, debt_independent: bool) -> Metric:
    window(periods,start,maturity)
    if debt_independent is not True:return Metric('UNSUPPORTED',None,'endogenous or non-monotone CFADS requires canonical solver; not implemented')
    relevant=tuple(p for p in periods if p.index<=maturity)
    if any(p.cfads is None for p in relevant):return missing('missing CFADS')
    if any(p.cfads<0 for p in relevant):return Metric('UNSUPPORTED',None,'negative CFADS sizing unsupported')
    closing=D(0)
    for p in reversed(relevant):
        budget=p.cfads/p.sizing_target
        if p.index<start:
            if p.interest_factor:closing=min(closing,budget/p.interest_factor)
        else:
            # Released no-capitalization constraint, on explicitly fixed CFADS.
            if p.interest_factor:closing=min(closing,budget/p.interest_factor)
            closing=(closing+budget)/(1+p.interest_factor)
    return Metric('CANDIDATE',closing,'closed-form supplied-CFADS capacity, not endogenous solve')


@arithmetic
def size(mode: Literal['EXPLICIT','GEARING','DSCR','MINIMUM'], *, explicit: D | None,
         eligible_uses: D | None, gearing: D | None, capacity: Metric | None,
         priority: tuple[str,...], applicability: tuple[Applicability,...]) -> Sizing:
    names={'EXPLICIT','GEARING','DSCR'}
    if mode not in (*names,'MINIMUM'):
        raise ValueError('unknown sizing mode')
    if not isinstance(priority,tuple) or set(priority)!=names or len(priority)!=3:
        raise ValueError('explicit complete tie-break priority required')
    if not isinstance(applicability,tuple) or len(applicability)!=3 or any(not isinstance(a,Applicability) for a in applicability):
        raise ValueError('explicit immutable applicability for all constraints required')
    specs={a.name:a for a in applicability}
    if set(specs)!=names:
        raise ValueError('duplicate, missing or unknown applicability identity')
    for a in applicability:
        if a.state not in ('REQUIRED','INAPPLICABLE') or not isinstance(a.reason,str) or not a.reason.strip():
            raise ValueError('invalid applicability state or missing declaration reason')
    if all(a.state=='INAPPLICABLE' for a in applicability):
        raise ValueError('at least one constraint must apply')
    if mode!='MINIMUM' and specs[mode].state!='REQUIRED':
        raise ValueError('selected sizing constraint must apply')
    values={};states={};reasons={}
    if explicit is not None:
        if amount(explicit)<0:raise ValueError('negative debt')
        values['EXPLICIT']=explicit
    if gearing is not None or eligible_uses is not None:
        if gearing is None or eligible_uses is None:
            states['GEARING']='MISSING';reasons['GEARING']='incomplete gearing evidence'
            if gearing is not None and not 0<=amount(gearing)<=1:raise ValueError('invalid gearing')
            if eligible_uses is not None and amount(eligible_uses)<0:raise ValueError('negative eligible uses')
        else:
            if amount(eligible_uses)<0 or not 0<=amount(gearing)<=1:raise ValueError('invalid gearing')
            values['GEARING']=eligible_uses*gearing
    if capacity is not None:
        if not isinstance(capacity,Metric):raise ValueError('typed capacity required')
        if capacity.status=='CANDIDATE':
            if capacity.value is None or amount(capacity.value)<0:raise ValueError('invalid capacity')
            values['DSCR']=capacity.value
        elif capacity.status in ('UNAVAILABLE','UNSUPPORTED') and capacity.value is None:
            states['DSCR']='MISSING' if capacity.status=='UNAVAILABLE' else 'UNSUPPORTED'
            reasons['DSCR']=capacity.reason
        else:raise ValueError('invalid capacity status/value combination')
    supplied={'EXPLICIT':explicit is not None,'GEARING':eligible_uses is not None or gearing is not None,'DSCR':capacity is not None}
    evidence=[]
    for name in priority:
        a=specs[name]
        if a.state=='INAPPLICABLE':
            if supplied[name]:raise ValueError('inapplicable constraint has supplied evidence')
            evidence.append(ConstraintEvidence(name,a.state,'INAPPLICABLE',None,a.reason))
        else:
            state='AVAILABLE' if name in values else states.get(name,'MISSING')
            evidence.append(ConstraintEvidence(name,a.state,state,values.get(name),reasons.get(name,a.reason)))
    unavailable=tuple(e.name for e in evidence if e.state in ('MISSING','UNSUPPORTED'))
    complete=not unavailable
    caps=tuple((name,values[name]) for name in priority if name in values)
    # Incomplete MINIMUM has no proposed amount. Fixed modes retain their amount
    # and known breaches but explicitly remain incomplete when another required cap is unknown.
    chosen=None if (mode=='MINIMUM' and not complete) else (min(values.values()) if mode=='MINIMUM' else values.get(mode))
    binding=tuple(name for name,value in caps if chosen is not None and value==chosen)
    breaches=tuple(name for name,value in caps if chosen is not None and chosen>value)
    return Sizing('CANDIDATE' if complete else 'UNAVAILABLE',chosen,caps,binding,breaches,
                  'CLOSED_FORM_NOT_ITERATIVE',unavailable_constraints=unavailable,
                  evidence=tuple(evidence),complete=complete)


@arithmetic
def sculpt(identifier: str, debt: D, periods: tuple[Period,...], start: int, maturity: int,
           *, max_maturity_principal: D, source: str) -> Facility:
    window(periods,start,maturity)
    if not isinstance(identifier,str) or not identifier or not isinstance(source,str) or not source or amount(debt)<0 or amount(max_maturity_principal)<0:raise ValueError('invalid proposal')
    if any(p.cfads is None or p.cfads<0 for p in tuple(p for p in periods if p.index<=maturity)):raise ValueError('missing/negative CFADS cannot sculpt')
    balance=debt;rows=[];target_status='FEASIBLE'
    for p in tuple(p for p in periods if p.index<=maturity):
        interest=balance*p.interest_factor
        budget=p.cfads/p.sizing_target
        principal=min(balance,max(D(0),budget-interest)) if p.index>=start else D(0)
        if interest+principal>budget:target_status='BREACH'
        closing=balance-principal
        rows.append(Row(p.index,balance,interest,principal,closing));balance=closing
    if rows[-1].principal>max_maturity_principal:
        raise ValueError('maturity principal cap exceeded; fixed debt not resized')
    # Fixed debt is never reduced to its capacity. Unpaid terminal balance remains visible.
    return Facility(identifier,debt,start,maturity,tuple(rows),source+'; maturity principal cap='+str(max_maturity_principal), 'BREACH' if balance else target_status)


def validate_facilities(periods,facilities):
    axis(periods)
    if not isinstance(facilities,tuple) or not facilities:raise ValueError('immutable facilities required')
    if len({f.identifier for f in facilities})!=len(facilities):raise ValueError('duplicate facility')
    for f in facilities:
        window(periods,f.repayment_start,f.maturity)
        if not isinstance(f.identifier,str) or not f.identifier or not isinstance(f.source,str) or not f.source or amount(f.commitment)<0:raise ValueError('invalid facility')
        if tuple(r.index for r in f.rows)!=tuple(p.index for p in periods if p.index<=f.maturity):raise ValueError('incomplete facility axis')
        previous=f.commitment
        for r in f.rows:
            for v in (r.opening,r.interest,r.principal,r.closing):
                if amount(v)<0:raise ValueError('negative contractual ledger')
            if r.opening!=previous or r.opening-r.principal!=r.closing:
                raise ValueError('debt conservation failed')
            if r.index<f.repayment_start and r.principal:raise ValueError('principal during grace')
            previous=r.closing


def allocations(periods,facilities,shares):
    if shares is None:return None
    if not isinstance(shares,tuple):raise ValueError('immutable shares required')
    result=dict(shares)
    if len(result)!=len(shares) or set(result)!={f.identifier for f in facilities}:raise ValueError('allocation identity mismatch')
    for values in result.values():
        if not isinstance(values,tuple) or len(values)!=len(periods):raise ValueError('allocation axis mismatch')
        if any(not 0<=amount(v)<=1 for v in values):raise ValueError('invalid allocation')
    if any(sum((v[i] for v in result.values()),D(0))>1 for i in range(len(periods))):
        raise ValueError('CFADS allocated more than once')
    return result


@arithmetic
def verify_interest(facilities, evidence):
    if evidence is None:evidence=()
    if not isinstance(evidence,tuple) or any(not isinstance(e,InterestEvidence) for e in evidence):
        raise ValueError('immutable typed interest evidence required')
    supplied={e.facility_id:e for e in evidence}
    if len(supplied)!=len(evidence) or not set(supplied)<={f.identifier for f in facilities}:
        raise ValueError('duplicate or foreign interest evidence')
    results=[]
    for f in facilities:
        e=supplied.get(f.identifier)
        if e is None:
            results.append((f.identifier,'UNVERIFIED'))
            continue
        if not isinstance(e.source,str) or not e.source.strip() or not isinstance(e.convention,str) or not e.convention.strip():
            raise ValueError('independent accrual source and convention required')
        if any(not isinstance(p,AccrualPeriod) or type(p.index) is not int for p in e.periods):
            raise ValueError('typed canonical accrual periods required')
        if tuple(p.index for p in e.periods)!=tuple(r.index for r in f.rows):
            raise ValueError('interest evidence axis mismatch')
        status='RECONCILED'
        for r,p in zip(f.rows,e.periods):
            if amount(p.annual_rate)<0 or amount(p.year_fraction,positive=True)<=0:
                raise ValueError('unsupported independent rate or accrual fraction')
            if r.interest!=r.opening*p.annual_rate*p.year_fraction:
                status='MISMATCH'
        results.append((f.identifier,status))
    return tuple(results)


@arithmetic
def assess(periods: tuple[Period,...], facilities: tuple[Facility,...], *, aggregate_loan_end: int,
           interest_evidence: tuple[InterestEvidence,...] | None = None, shares=None, allocation_basis: str | None = None, covenant_dscr: D | None, discount_convention: str | None, max_maturity_principal: tuple[tuple[str,D],...]) -> Credit:
    validate_facilities(periods,facilities)
    if type(aggregate_loan_end) is not int or aggregate_loan_end!=max(f.maturity for f in facilities):
        raise ValueError('aggregate loan life must end at last supplied maturity')
    if shares is not None and (not isinstance(allocation_basis,str) or not allocation_basis):
        raise ValueError('explicit CFADS allocation basis required')
    alloc=allocations(periods,facilities,shares)
    if not isinstance(max_maturity_principal,tuple):raise ValueError('immutable maturity limits required')
    if discount_convention is not None and not isinstance(discount_convention,str):raise ValueError('invalid discount convention')
    caps=dict(max_maturity_principal)
    if len(caps)!=len(max_maturity_principal) or set(caps)!={f.identifier for f in facilities}:raise ValueError('explicit maturity limits required')
    if any(amount(x)<0 for x in caps.values()):raise ValueError('invalid maturity limit')
    if covenant_dscr is not None:amount(covenant_dscr,positive=True)
    aggregate=[];cash='FEASIBLE';cov='NOT_ASSESSED' if covenant_dscr is None else 'FEASIBLE'
    for p in periods:
        service=sum((r.service for f in facilities for r in f.rows if r.index==p.index),D(0))
        metric=ratio(p.cfads,service);aggregate.append((p.index,metric))
        if service and p.cfads is None:
            if cash!='BREACH':cash='UNAVAILABLE'
            if covenant_dscr is not None and cov!='BREACH':cov='UNAVAILABLE'
        elif service and p.cfads<service:cash='BREACH'
        if covenant_dscr is not None and metric.value is not None and metric.value<covenant_dscr:cov='BREACH'
    contractual='FEASIBLE'
    for f in facilities:
        if f.rows[-1].closing or f.rows[-1].principal>caps[f.identifier]:contractual='BREACH'
    total=sum((f.commitment for f in facilities),D(0))
    def coverage(end,debt,weights):
        rows=tuple(p for p in periods if p.index<=end)
        if not discount_convention:return missing('explicit dated discount convention missing')
        if any(p.cfads is None for p in rows):return missing('incomplete coverage CFADS')
        return ratio(sum((p.cfads*p.discount_factor*weights[next(i for i,x in enumerate(periods) if x.index==p.index)] for p in rows),D(0)),debt)
    per=[];fcov=[]
    for f in facilities:
        if alloc is None:
            per.append((f.identifier,tuple((r.index,missing('no defensible CFADS allocation')) for r in f.rows)))
            fcov.append((f.identifier,missing('no CFADS allocation'),missing('no CFADS allocation')))
        else:
            weights=alloc[f.identifier]
            per.append((f.identifier,tuple((r.index,ratio(None if next(p for p in periods if p.index==r.index).cfads is None else next(p for p in periods if p.index==r.index).cfads*weights[next(i for i,p in enumerate(periods) if p.index==r.index)],r.service)) for r in f.rows)))
            fcov.append((f.identifier,coverage(f.maturity,f.commitment,weights),coverage(periods[-1].index,f.commitment,weights)))
    ones=(D(1),)*len(periods)
    interest=verify_interest(facilities,interest_evidence)
    accounting=('NOT_RECONCILED' if any(status=='MISMATCH' for _,status in interest) else
                'UNVERIFIED' if any(status=='UNVERIFIED' for _,status in interest) else 'RECONCILED')
    return Credit(tuple(aggregate),tuple(per),coverage(aggregate_loan_end,total,ones),coverage(periods[-1].index,total,ones),tuple(fcov),'RECONCILED',interest,accounting,cash,contractual,cov)


@arithmetic
def propose_sweep(periods,facilities,*,period_index: int, available_after_reserves: D,
                  shares: tuple[tuple[str,D],...], policy_source: str):
    """One-period proposal only; never claims a recomputed future interest schedule."""
    validate_facilities(periods,facilities)
    if type(period_index) is not int or not periods[0].index<=period_index<=periods[-1].index or not policy_source:raise ValueError('explicit sweep period/policy required')
    p=next(p for p in periods if p.index==period_index)
    if p.cfads is None:raise ValueError('missing sweep cash')
    service=sum((r.service for f in facilities for r in f.rows if r.index==period_index),D(0))
    if not 0<=amount(available_after_reserves)<=max(D(0),p.cfads-service):raise ValueError('sweep exceeds residual cash')
    if not isinstance(shares,tuple):raise ValueError('immutable sweep shares required')
    weights=dict(shares)
    if len(weights)!=len(shares) or set(weights)!={f.identifier for f in facilities}:raise ValueError('sweep allocation identities')
    if any(not 0<=amount(w)<=1 for w in weights.values()) or sum(weights.values(),D(0))>1:raise ValueError('sweep double-counting')
    return tuple((f.identifier,min(available_after_reserves*weights[f.identifier],next((r.closing for r in f.rows if r.index==period_index),D(0)))) for f in facilities)


@arithmetic
def check_committed_limits(periods,facilities,*,eligible_uses: D | None,gearing: D | None,
                           aggregate_capacity: Metric | None,priority: tuple[str,...], applicability: tuple[Applicability,...]):
    """One borrower gearing test, never the full uses cap independently per tranche."""
    validate_facilities(periods,facilities)
    return size('EXPLICIT',explicit=sum((f.commitment for f in facilities),D(0)),
                eligible_uses=eligible_uses,gearing=gearing,capacity=aggregate_capacity,priority=priority,applicability=applicability)

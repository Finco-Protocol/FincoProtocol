"""Standalone numerical and authority checks for additive WF-11 candidates."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[1] / 'app/model_opex/profiles_candidate.py'
SPEC = importlib.util.spec_from_file_location('wf11candidate', FILE)
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def item(**changes):
    return replace(MODULE.MaintenanceCandidate('e1', 'B.03', 4, Decimal('250.0')), **changes)


def test_one_off_does_not_increase_future_base():
    totals = MODULE.maintenance_preview([item()], horizon_years=7, eligible_lines=['B.03'])
    assert totals[4] == Decimal('250')
    assert all(totals[y] == 0 for y in (1, 2, 3, 5, 6, 7))
    assert MODULE.AUTHORITY == 'CANDIDATE_ONLY_NOT_SAVED_NOT_RUN'


def test_recurrence_explicit_no_silent_forward_fill():
    p = item(recurrence='EVERY_N_YEARS', interval_years=3)
    totals = MODULE.maintenance_preview([p], horizon_years=10, eligible_lines=['B.03'])
    assert [y for y, v in totals.items() if v] == [4, 7, 10]

@pytest.mark.parametrize('updates,code',[
    ({'amount_keur': Decimal('-1')},'AMOUNT_INVALID'),
    ({'amount_keur': Decimal('NaN')},'AMOUNT_INVALID'),
    ({'amount_keur': Decimal('Infinity')},'AMOUNT_INVALID'),
    ({'start_year': 9},'YEAR_OUT_OF_HORIZON'),
    ({'owner_line': 'B.13'},'UNKNOWN_OR_DERIVED_OWNER'),
    ({'owner_line': 'B.99'},'UNKNOWN_OR_DERIVED_OWNER'),
    ({'classification': 'APPROVED'},'CLASSIFICATION_INVALID'),
    ({'recurrence': 'EVERY_N_YEARS','interval_years':None},'RECURRENCE_INVALID'),
    ({'recurrence': 'ONE_OFF','interval_years':2},'RECURRENCE_INVALID'),
])
def test_invalid_candidate_is_fail_closed(updates,code):
    with pytest.raises(MODULE.OpexProfileError,match=code):
        MODULE.validate_maintenance([item(**updates)], horizon_years=7, eligible_lines=['B.03'])


def test_duplicate_identity_and_same_owner_year_rejected():
    with pytest.raises(MODULE.OpexProfileError,match='EVENT_ID_DUPLICATE_OR_INVALID'):
        MODULE.validate_maintenance([item(),item()], horizon_years=7, eligible_lines=['B.03'])
    with pytest.raises(MODULE.OpexProfileError,match='DOUBLE_COUNTING_RISK'):
        MODULE.validate_maintenance([item(),item(event_id='e2')], horizon_years=7, eligible_lines=['B.03'])


def test_full_year_weights_conserve_exact_amount():
    parts = MODULE.seasonal_candidate('170.01', ['33.3','66.7'])
    assert parts == (Decimal('56.61333'),Decimal('113.39667'))
    assert sum(parts) == Decimal('170.01')
    quarters = MODULE.seasonal_candidate('100.01', [10,20,30,40],frequency='QUARTERLY_CANDIDATE')
    assert sum(quarters) == Decimal('100.01') and len(quarters)==4

@pytest.mark.parametrize('annual,weights,freq',[('NaN',[50,50],'SEMIANNUAL'),('100',[20,30],'SEMIANNUAL'),('100',[25]*4,'ANNUAL'),('100',[50,50],'QUARTERLY_CANDIDATE'),('-1',[50,50],'SEMIANNUAL')])
def test_invalid_seasonal_candidate(annual,weights,freq):
    with pytest.raises(MODULE.OpexProfileError):
        MODULE.seasonal_candidate(annual,weights,frequency=freq)


def test_no_engine_or_persistence_imports():
    source = FILE.read_text()
    for name in ('finco_core', 'app.persistence', 'WorkbookUpdateService', 'v2_atomic_draft_update','get_cursor','sessionStorage'):
        assert name not in source

"""Strict syntax, exact declared-period arithmetic and unchanged production gate."""
from dataclasses import replace
from datetime import date
from fractions import Fraction as F
import json
import pytest

from research.r04_phase2_candidate.contracts import SCHEMA, CandidateError, parse_annual_document, require_production_contract
from research.r04_phase2_candidate.period_review import (
    DeclaredDelivery as D, GenerationPeriod as P, TechnicalSource as S,
    PeriodCapExceeded, review_declared_deliveries, source_from_inputs,
)


def document(amounts=("80", "20")):
    return {"schema": SCHEMA, "version": 1, "technology": "solar", "contracts": [
        {"id": f"ppa-{i}", "start_date": "2028-01-01", "end_date": "2029-01-01",
         "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": amount, "unit": "GWh"},
         "pricing_reference": f"explicit-existing-price-contract-{i}"} for i, amount in enumerate(amounts)]}


def source(available=100_000):
    # Explicit synthetic period proof, not a claim that the released engine
    # supports an annual frequency or this is an approved annual obligation.
    return S("solar", "P_50", "0" * 64, "1" * 64,
             (P(2, date(2028, 1, 1), date(2029, 1, 1), F(available)),))


def review(amounts=("80", "20"), available=100_000):
    book = parse_annual_document(json.dumps(document(amounts)))
    s = source(available)
    deliveries = tuple(D(f"ppa-{i}", 2, F(a) * 1000) for i, a in enumerate(amounts))
    return review_declared_deliveries(book, s, deliveries, expected_source_sha256=s.identity_sha256, requested_contract_id=f"ppa-{len(amounts)-1}")


def rational(value):
    return F(int(value["numerator"]), int(value["denominator"]))


def test_80_plus_20_period_proof_never_becomes_annual_or_production_acceptance():
    result = review()
    assert rational(result["periods"][0]["committed_mwh"]) == 100_000
    assert rational(result["periods"][0]["uncontracted_mwh"]) == 0
    assert not any(result[k] for k in ("annual_semantics_verified", "pricing_verified", "production_supported", "persisted", "run_executed"))
    with pytest.raises(CandidateError, match="POLICY_AND_PRODUCTION_ADMISSION_REQUIRED"):
        require_production_contract(parse_annual_document(json.dumps(document())))


@pytest.mark.parametrize("amounts,available,excess", [(("80", "21"),100_000,1000),(("80", "20"),98_000,2000),(("80", "20"),95_000,5000),(("60", "20", "21"),100_000,1000),(("80", "20.0000001"),100_000,F("0.0001"))])
def test_exact_excess_is_never_clipped_or_hidden_by_display_precision(amounts, available, excess):
    with pytest.raises(PeriodCapExceeded) as caught:
        review(amounts, available)
    error = caught.value
    assert error.code == "GLOBAL_PPA_CAP_EXCEEDED"
    assert rational(error.report["violations"][0]["excess_gwh"]) * 1000 == excess
    assert not error.report["annual_semantics_verified"] and not error.report["production_supported"]


def test_three_contracts_and_mixed_units_preserve_exact_declared_values():
    obj = document(("60", "20", "20"))
    obj["contracts"][1]["annual_quantity"].update(amount="20000", unit="MWh")
    book = parse_annual_document(json.dumps(obj))
    assert [c.annual_quantity_mwh for c in book.contracts] == [60000,20000,20000]
    assert review(("60", "20", "20"))["violations"] == []
    assert [c.pricing_reference for c in book.contracts] == [f"explicit-existing-price-contract-{i}" for i in range(3)]


@pytest.mark.parametrize("bad", ["0", "-1", "NaN", "Infinity", "1e3", " 80", True, 80, "01", "1.", ".1"])
def test_annual_quantity_has_no_implicit_unit_coercion_or_zero_default(bad):
    obj = document(); obj["contracts"][0]["annual_quantity"]["amount"] = bad
    with pytest.raises(CandidateError): parse_annual_document(json.dumps(obj))


@pytest.mark.parametrize("mutation", ["unit", "mixed_share", "unknown", "duplicate", "bool_version", "duplicate_key", "approval", "nonfinite", "legacy"])
def test_unknown_mixed_or_forged_policy_shapes_refuse(mutation):
    obj = document()
    if mutation == "unit": obj["contracts"][0]["annual_quantity"]["unit"] = "kWh"
    elif mutation == "mixed_share": obj["contracts"][0]["volume_share"] = .8
    elif mutation == "unknown": obj["contracts"][0]["annual_quantity"]["basis"] = "approved"
    elif mutation == "duplicate": obj["contracts"][1]["id"] = obj["contracts"][0]["id"]
    elif mutation == "bool_version": obj["version"] = True
    elif mutation == "approval": obj["approved"] = True
    elif mutation == "nonfinite": obj["contracts"][0]["annual_quantity"]["amount"] = float("nan")
    elif mutation == "legacy": obj = {"version":1,"technology":"solar","indexation_basis":"OPERATING_YEAR","streams":[]}
    raw = json.dumps(obj)
    if mutation == "duplicate_key": raw = raw.replace('"version": 1', '"version": 1, "version": 1')
    with pytest.raises(CandidateError): parse_annual_document(raw)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "negative", "bool", "float", "unknown_contract", "wrong_period", "off_axis", "stale_source", "mutated_source", "tampered_book"])
def test_declared_period_review_refuses_missing_or_tampered_facts(kind):
    book = parse_annual_document(json.dumps(document())); s = source()
    expected = s.identity_sha256
    deliveries = [D("ppa-0",2,F(80000)),D("ppa-1",2,F(20000))]
    if kind == "missing": deliveries.pop()
    elif kind == "duplicate": deliveries.append(deliveries[0])
    elif kind == "negative": deliveries[0] = replace(deliveries[0],mwh=F(-1))
    elif kind == "bool": deliveries[0] = replace(deliveries[0],mwh=True)
    elif kind == "float": deliveries[0] = replace(deliveries[0],mwh=80000.0)
    elif kind == "unknown_contract": deliveries[0] = replace(deliveries[0],contract_id="unknown")
    elif kind == "wrong_period": deliveries[0] = replace(deliveries[0],period_index=3)
    elif kind == "off_axis":
        obj=document();obj["contracts"][0]["start_date"]="2028-02-29";book=parse_annual_document(json.dumps(obj))
    elif kind == "stale_source": expected="f"*64
    elif kind == "mutated_source": s=replace(s,periods=(replace(s.periods[0],mwh=F(200000)),))
    elif kind == "tampered_book": book=replace(book,contracts=(replace(book.contracts[0],annual_quantity_mwh=F(1)),book.contracts[1]))
    with pytest.raises(CandidateError):
        review_declared_deliveries(book,s,deliveries,expected_source_sha256=expected)


def explicit_inputs(case="P_50"):
    from app.project_factories import create_generic_solar_reference
    p=create_generic_solar_reference()
    return replace(p,info=replace(p.info,financial_close=date(2027,1,1),cod_date=date(2028,1,1),construction_months=12,horizon_years=3),
                   technical=replace(p.technical,capacity_mw=100,yield_scenario=case,operating_hours_p50=1000,operating_hours_p90_10y=900,
                                     plant_availability=1,grid_availability=1,pv_degradation=.02))


def test_source_adapter_uses_selected_case_axis_and_content_identity_without_run_or_write(monkeypatch):
    def never(*a,**k): raise AssertionError("financial Run or write")
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production",never)
    monkeypatch.setattr("app.persistence.projects_repository.save_project",never)
    args=dict(technology="solar",project_id="synthetic-project",scenario_id="synthetic-scenario",input_revision="explicit-v1")
    p50=source_from_inputs(explicit_inputs(),**args)
    p90=source_from_inputs(explicit_inputs("P90-10y"),**args)
    assert len(p50.periods)==6 and p50.identity_sha256!=p90.identity_sha256
    for a,b in zip(p50.periods,p90.periods):
        assert (a.index,a.start,a.end)==(b.index,b.start,b.end)
        assert float(b.mwh/a.mwh)==pytest.approx(.9)
    assert source_from_inputs(explicit_inputs(),**{**args,"input_revision":"v2"}).identity_sha256!=p50.identity_sha256


@pytest.mark.parametrize("case", ["P99-1y","P90","UNKNOWN",True])
def test_unknown_case_never_becomes_p50(case):
    with pytest.raises(CandidateError,match="SELECTED_CASE_UNSUPPORTED"):
        source_from_inputs(explicit_inputs(case),technology="solar",project_id="p",scenario_id="s",input_revision="v")


@pytest.mark.parametrize("requested", [[], {}, False, 123, ""])
def test_malformed_requested_identity_is_a_typed_refusal(requested):
    book=parse_annual_document(json.dumps(document()));s=source()
    with pytest.raises(CandidateError):
        review_declared_deliveries(book,s,[D("ppa-0",2,F(80000)),D("ppa-1",2,F(20000))],
                                  expected_source_sha256=s.identity_sha256,requested_contract_id=requested)


@pytest.mark.parametrize("field", ["capacity_mw","operating_hours_p50","operating_hours_p90_10y","plant_availability","grid_availability","pv_degradation"])
def test_bool_is_not_a_technical_number_even_in_a_manually_constructed_dataclass(field):
    p=explicit_inputs();p=replace(p,technical=replace(p.technical,**{field:True}))
    with pytest.raises(CandidateError,match="GENERATION_INVALID"):
        source_from_inputs(p,technology="solar",project_id="p",scenario_id="s",input_revision="v")

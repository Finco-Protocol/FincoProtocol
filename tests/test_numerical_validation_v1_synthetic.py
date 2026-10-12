"""Synthetic Revenue V2 numerical contract - prepared for a REAL FINCO checkout.

No external source records. An independent Decimal oracle validates engine
period outputs. Production volume and OPEX are separate, declared boundaries.
"""
from __future__ import annotations
import json
import math
import time
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

PUBLIC_FIXTURE = {
    "price_a": "43.20", "price_b": "61.70", "price_m": "69.90",
    "share_a": "0.28", "share_b": "0.32", "share_m": "0.40",
    "merchant_capture": "0.82", "balancing": "0.017",
}
FLOAT_ABS_KEUR = 1e-9
FLOAT_REL = 1e-12


def _d(value):
    return Decimal(str(value))


def independent_revenue_oracle(production_mwh, *, year=1, index_a="0", index_b="0",
                               index_m="0", fixture=None):
    """Independent expected values; NEVER calls a FINCO revenue function.

    The delivered operating-period MWh is held fixed. This function therefore
    tests price/volume arithmetic, not production model correctness.
    """
    f = PUBLIC_FIXTURE if fixture is None else fixture
    g = _d(production_mwh)
    assert float(year).is_integer(), "The fixture requires whole operating-year indices"
    y = int(year)
    assert y >= 1 and g >= 0
    sa, sb, sm = (_d(f[k]) for k in ("share_a", "share_b", "share_m"))
    assert sa + sb + sm == Decimal("1")
    qa, qb, qm = (g * s for s in (sa, sb, sm))
    pa = _d(f["price_a"]) * (Decimal("1") + _d(index_a)) ** (y - 1)
    pb = _d(f["price_b"]) * (Decimal("1") + _d(index_b)) ** (y - 1)
    pm = _d(f["price_m"]) * (Decimal("1") + _d(index_m)) ** (y - 1)
    a, b = qa * pa / 1000, qb * pb / 1000
    merchant = qm * pm * _d(f["merchant_capture"]) / 1000
    balancing = merchant * _d(f["balancing"])
    return {
        "allocated_a_mwh": qa, "allocated_b_mwh": qb, "allocated_m_mwh": qm,
        "ppa_a_keur": a, "ppa_b_keur": b, "merchant_keur": merchant,
        "balancing_keur": balancing, "total_gross_keur": a+b+merchant,
        "total_net_keur": a+b+merchant-balancing,
        "unallocated_mwh": Decimal("0"),
        "price_a": pa, "price_b": pb, "price_m": pm,
    }


def _close(actual, expected, *, label):
    a=float(actual)
    b=float(expected)
    assert math.isfinite(a), label
    assert a == pytest.approx(b, abs=FLOAT_ABS_KEUR, rel=FLOAT_REL), (
        f"{label}: actual={a} expected={b} residual={a-b}"
    )


def _payload(operating_periods, *, index_a="0", index_b="0", index_m="0",
             fixture=None):
    f = PUBLIC_FIXTURE if fixture is None else fixture
    common = {
        "start_date":operating_periods[0].start_date.isoformat(),
        "end_date":operating_periods[-1].end_date.isoformat(),
        "settlement":"SAME_PERIOD", "source_ref":"synthetic-only",
    }
    def row(identity,kind,share,price,index,**kw):
        return {**common,"id":identity,"type":kind,"volume_share":float(f[share]),
                "price_eur_mwh":float(f[price]),"indexation_rate":float(index),**kw}
    streams=[
        row("synthetic-ppa-alpha","ppa","share_a","price_a",index_a),
        row("synthetic-ppa-beta","ppa","share_b","price_b",index_b),
        row("synthetic-merchant","merchant","share_m","price_m",index_m,
            capture_rate=float(f["merchant_capture"])),
    ]
    return {"version":1, "technology":"solar",
            "indexation_basis":"OPERATING_YEAR","streams":streams}


def _run_three_stream_synthetic(*, index_a="0", index_b="0", index_m="0",
                                fixture=None):
    # Imports occur at execution, never substitute a financial model mock.
    from app.project_factories import create_generic_solar_reference
    from app.workbook.revenue_multistream import apply_config
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import (
        _build_period_engine, run_operating_model,
    )
    from finco_core.revenue.generation import revenue_decomposition_schedule

    pi=create_generic_solar_reference()
    f = PUBLIC_FIXTURE if fixture is None else fixture
    # Explicit synthetic revenue-cost context, retaining generic factory's
    # fully defined CAPEX/OPEX/period-generation authorities.
    pi=replace(pi,revenue=replace(
        pi.revenue, balancing_cost_pv=float(f["balancing"]),
        balancing_cost_wind_eur_mwh=0.0,
        balancing_cost_eur_per_mwh=0.0,
        co2_enabled=False, co2_price_eur=0.0,
        co2_certificate_price_eur_per_mwh=0.0,
    ))
    prior=from_project_inputs(pi)
    operating=tuple(p for p in _build_period_engine(prior).periods() if p.is_operation)
    assert len(operating)>=4, "Need at least four actual operating periods"
    config=_payload(operating,index_a=index_a,index_b=index_b,index_m=index_m,fixture=f)
    active=apply_config(pi,json.dumps(config),project_type="solar")
    clean=from_project_inputs(active)
    start=time.perf_counter()
    result=run_operating_model(clean)  # THE canonical financial execution
    elapsed=time.perf_counter()-start
    axis=_build_period_engine(clean)
    evidence=revenue_decomposition_schedule(active,axis)
    return result, evidence, elapsed, active


def _assert_oracle(result,evidence, *, index_a="0",index_b="0",index_m="0",
                   fixture=None):
    active_periods=0
    max_residual=Decimal("0")
    for period in result.periods:
        if not period.is_operation:
            continue
        active_periods+=1
        raw=evidence[period.period_index]
        stream_rows=raw["multistream_evidence"]["streams"]
        actual_streams={s["id"]:s for s in stream_rows}
        assert len(stream_rows)==len(actual_streams)==3
        assert set(actual_streams)=={"synthetic-ppa-alpha", "synthetic-ppa-beta", "synthetic-merchant"}
        expected=independent_revenue_oracle(period.production_mwh,
                      year=period.year_index,index_a=index_a,index_b=index_b,
                      index_m=index_m,fixture=fixture)
        _close(sum(s["quantity_mwh"] for s in stream_rows),period.production_mwh,label="volume conservation")
        f=PUBLIC_FIXTURE if fixture is None else fixture
        _close(actual_streams["synthetic-merchant"]["capture_rate"],_d(f["merchant_capture"]),label="merchant capture")
        for name,identity in [("allocated_a_mwh","synthetic-ppa-alpha"),
                              ("allocated_b_mwh","synthetic-ppa-beta"),
                              ("allocated_m_mwh","synthetic-merchant")]:
            _close(actual_streams[identity]["quantity_mwh"],expected[name],label=name)
        for name,identity in [("ppa_a_keur","synthetic-ppa-alpha"),
                              ("ppa_b_keur","synthetic-ppa-beta"),
                              ("merchant_keur","synthetic-merchant")]:
            _close(actual_streams[identity]["revenue_keur"],expected[name],label=name)
        _close(raw["gross_electricity_revenue_keur"],expected["total_gross_keur"],label="gross")
        _close(raw["balancing_cost_keur"],expected["balancing_keur"],label="balancing")
        _close(raw["revenue_keur"],expected["total_net_keur"],label="net")
        _close(raw["multistream_evidence"]["unallocated_generation_mwh"],0,label="unallocated")
        _close(period.revenue_keur,expected["total_net_keur"],label="canonical operating revenue")
        _close(period.ebitda_keur,_d(expected["total_net_keur"])-_d(period.opex_keur),
               label="canonical EBITDA")
        for name,identity in [("price_a","synthetic-ppa-alpha"),
                              ("price_b","synthetic-ppa-beta"),
                              ("price_m","synthetic-merchant")]:
            _close(actual_streams[identity]["price_eur_mwh"],expected[name],label=name)
        residual=abs(_d(period.revenue_keur)-expected["total_net_keur"])
        max_residual=max(max_residual,residual)
    assert active_periods>=4
    assert result.provenance.run_path_id=="financial_engine.orchestrator.run_operating_model"
    assert result.provenance.input_fingerprint
    derived={e.output_path:e for e in result.provenance.derivation_evidence}
    for required in ("operating_schedules.production_mwh",
                     "operating_schedules.revenue_keur",
                     "operating_schedules.opex_keur",
                     "operating_schedules.ebitda_keur"):
        assert required in derived
    assert derived["operating_schedules.revenue_keur"].notes
    return max_residual,active_periods


def test_oracle_arithmetic_only():
    # This unit-level smoke test can execute without a FINCO checkout.
    data=independent_revenue_oracle(Decimal("100000"),year=1)
    assert data["allocated_a_mwh"]==Decimal("28000.00")
    assert data["allocated_b_mwh"]==Decimal("32000.00")
    assert data["allocated_m_mwh"]==Decimal("40000.00")
    assert data["ppa_a_keur"]==Decimal("1209.600000")
    assert data["ppa_b_keur"]==Decimal("1974.400000")
    assert data["merchant_keur"]==Decimal("2292.720000")
    assert data["balancing_keur"]==Decimal("38.976240000")
    assert data["total_net_keur"]==Decimal("5437.743760000")



def test_oracle_indexation_zero_price_and_no_double_count():
    zero={**PUBLIC_FIXTURE,"price_b":"0"}
    y2=independent_revenue_oracle(Decimal("25000"),year=2,
                                  index_a="0.013",index_b="0.021",index_m="0.034",
                                  fixture=zero)
    assert y2["ppa_b_keur"]==0
    assert y2["allocated_a_mwh"]+y2["allocated_b_mwh"]+y2["allocated_m_mwh"]==Decimal("25000")
    assert y2["total_gross_keur"]-y2["balancing_keur"]==y2["total_net_keur"]
    assert y2["unallocated_mwh"]==0
    assert y2["price_a"]==Decimal("43.20")*Decimal("1.013")


def test_canonical_three_stream_period_oracle():
    result,rows,elapsed,_=_run_three_stream_synthetic()
    max_resid,n=_assert_oracle(result,rows)
    print(f"synthetic canonical periods={n}; elapsed_seconds={elapsed:.6f}; "
          f"max_residual_keur={max_resid}")


def test_canonical_three_stream_indexation_oracle():
    result,rows,elapsed,_=_run_three_stream_synthetic(
        index_a="0.013",index_b="0.021",index_m="0.034")
    max_resid,n=_assert_oracle(result,rows,index_a="0.013",
                                index_b="0.021",index_m="0.034")
    print(f"indexed synthetic periods={n}; elapsed_seconds={elapsed:.6f}; "
          f"max_residual_keur={max_resid}")


def test_canonical_synthetic_zero_price_and_immutable_evidence():
    zero={**PUBLIC_FIXTURE,"price_b":"0.0"}
    base,rows,elapsed,inputs=_run_three_stream_synthetic(fixture=zero)
    _assert_oracle(base,rows,fixture=zero)
    original=base.operating_schedules.revenue_keur
    historical=asdict(base)
    assert original
    # Changing the input must produce a new input fingerprint but may never
    # mutate the historical immutable result.
    alt={**zero,"price_b":"22.00"}
    newer,rows2,elapsed2,_=_run_three_stream_synthetic(fixture=alt)
    _assert_oracle(newer,rows2,fixture=alt)
    assert base.provenance.input_fingerprint!=newer.provenance.input_fingerprint
    assert base.operating_schedules.revenue_keur==original
    assert asdict(base)==historical
    assert base.operating_schedules.revenue_keur!=newer.operating_schedules.revenue_keur

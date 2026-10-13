"""Neutral contractual inputs; no provider identifiers or calibration targets."""
from copy import deepcopy

from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from tests.test_wf07_revenue_multistream import contracts


def book(pi, kind="solar", families=("capacity_market", "ancillary", "rec")):
    payload = contracts(pi, kind, price=95, merchant_price=90, strike=100)
    payload["version"] = 3
    payload["products"] = []
    payload["environmental_rights"] = [
        {"energy_stream_id": row["id"], "status": "RETAINED_UNBUNDLED", "source_ref": "synthetic-unbundled-rights"}
        for row in payload["streams"] if row["type"] in ("ppa", "merchant")]
    periods = tuple(p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation)
    points = [{"period_start": p.start_date.isoformat(), "period_end": p.end_date.isoformat(),
               "settlement_date": p.end_date.isoformat()} for p in periods]
    for kind in families:
        row = dict(id=kind + "-one", type=kind, entitlement_id=kind + "-entitlement",
            source_ref="synthetic-signed-" + kind, eligibility_ref="synthetic-explicit-" + kind,
            start_date=periods[0].start_date.isoformat(), end_date=periods[-1].end_date.isoformat(),
            classification="CONTRACTED", settlement="SAME_PERIOD", indexation_rate=.01,
            periods=deepcopy(points))
        if kind == "rec":
            row.update(price_eur=3, price_unit="EUR_CERTIFICATE", energy_stream_id="market-1",
                certification_ref="synthetic-declared-certification", certificate_basis="ONE_PER_MWH",
                ownership="PROJECT_RETAINED_UNBUNDLED")
            for p in row["periods"]:
                p["certified_mwh"] = 100
        else:
            row.update(pool_id=kind + "-pool", pool_source_ref="synthetic-explicit-pool",
                pool_capacity_mw=4, eligible_mw=2, capacity_basis="CONTRACTED_ELIGIBLE_MW",
                derating_factor=.8, availability_factor=.9, performance_factor=.95)
            if kind == "capacity_market":
                row.update(price_eur=20, price_unit="EUR_KW_YEAR", day_count="ACT_365_FIXED")
            else:
                row.update(price_eur=800, price_unit="EUR_MW_PERIOD", service="contracted-response-availability",
                           obligation="AVAILABILITY_ONLY")
        payload["products"].append(row)
    return payload, periods

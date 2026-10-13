"""Independent dated common-equity numerical and unsupported-policy acceptance."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from io import BytesIO
import json

import pytest
from openpyxl import load_workbook

from app.model_v2.investor_f4 import allocate_run, parse_terms, validate_evidence, extract_equity_receipts
from app.export.investor_f4 import export_investor_evidence

BINDING = dict(owner_id="f4-owner", project_id="f4-project", scenario_id=None,
               snapshot_id="f4-run", composite_hash="f4-hash")
DATES = ("2026-01-15", "2026-06-27", "2027-01-15", "2028-04-30")


def document(three=False):
    shares = (("alpha", .7, 80), ("beta", .3, 70)) if not three else (
        ("alpha", .5, 80), ("beta", .3, 70), ("gamma", .2, 50))
    contributions = [("alpha", DATES[0], 60), ("beta", DATES[1], 40)]
    if three:
        contributions = [("alpha", DATES[0], 40), ("beta", DATES[1], 35), ("gamma", DATES[1], 25)]
    return dict(schema_version=1, agreement_id="synthetic-common-agreement", version=1,
        currency="EUR", unit="kEUR", policy="RESIDUAL_ONLY",
        investors=[dict(investor_id=i, investment_class="COMMON_EQUITY", ownership_fraction=s, commitment_keur=c)
                   for i, s, c in shares],
        contributions=[dict(investor_id=i, cash_date=d, amount_keur=a) for i, d, a in contributions])


def receipts(doc, cash=(0, 0, 30, 150), status="OK"):
    return dict(schema_version=1, source="CovenantGatedWaterfallResult.net_dividend_received_keur",
        return_status=status, periods=[dict(date=d,
            paid_in_keur=sum(c["amount_keur"] for c in doc["contributions"] if c["cash_date"] == d),
            net_equity_receipt_keur=v, gross_dividend_keur=v * 1.1, dividend_wht_keur=v * .1)
            for d, v in zip(DATES, cash)])


def decimal_xirr(events):
    """Independent bisection, ACT/365 actual dates, no production utility reuse."""
    with localcontext() as ctx:
        ctx.prec = 50
        dates = [date.fromisoformat(e["date"]) for e in events]
        amounts = [Decimal(str(e["net_cashflow_keur"])) for e in events]
        years = [Decimal((d - dates[0]).days) / Decimal(365) for d in dates]
        def npv(rate):
            return sum(a / ((1 + rate) ** t) for a, t in zip(amounts, years))
        lo, hi = Decimal("-0.999"), Decimal(100)
        assert npv(lo) > 0 > npv(hi)
        for _ in range(250):
            mid = (lo + hi) / 2
            if npv(mid) > 0:
                lo = mid
            else:
                hi = mid
        return float((lo + hi) / 2)


@pytest.mark.parametrize("three", [False, True])
@pytest.mark.parametrize("cash", [(0, 0, 30, 150), (0, 0, 150, 30), (0, 0, 10, 40)])
def test_dated_decimal_allocation_accounts_and_xirr(three, cash):
    doc = document(three)
    out = allocate_run(parse_terms(doc), receipts(doc, cash), binding=BINDING)
    for index, amount in enumerate(cash):
        distributions = [i["cash_events"][index]["residual_distribution_keur"] for i in out["investors"]]
        assert sum(distributions) == pytest.approx(amount, abs=1e-6)
        for investor, actual in zip(out["investors"], distributions):
            expected = Decimal(str(amount)) * Decimal(str(investor["ownership_fraction"]))
            assert abs(Decimal(str(actual)) - expected) < Decimal("0.000001")
    for investor in out["investors"]:
        assert investor["xirr"] == pytest.approx(decimal_xirr(investor["cash_events"]), abs=1e-8)
        assert investor["returned_capital_keur"] == 0
        assert investor["unreturned_paid_in_keur"] == investor["total_paid_in_keur"]
        assert investor["uncalled_capital_keur"] + investor["total_paid_in_keur"] == investor["commitment_keur"]
        assert investor["dpi"] == investor["realized_moic"] == pytest.approx(
            investor["cumulative_distributions_keur"] / investor["total_paid_in_keur"])
    assert out["retained_cash_keur"] == 0
    validate_evidence(out, **BINDING)


def test_changed_final_timing_changes_investor_return_not_allocation():
    doc = document()
    receipt = receipts(doc)
    old = allocate_run(parse_terms(doc), receipt, binding=BINDING)
    receipt["periods"][-1]["date"] = "2029-04-30"
    new = allocate_run(parse_terms(doc), receipt, binding=BINDING)
    for a, b in zip(old["investors"], new["investors"]):
        assert b["xirr"] < a["xirr"]
        assert b["cumulative_distributions_keur"] == a["cumulative_distributions_keur"]


def test_zero_cash_and_unpaid_maturity_return_metrics_fail_closed():
    doc = document()
    out = allocate_run(parse_terms(doc), receipts(doc, (0, 0, 0, 0)), binding=BINDING)
    assert all(i["xirr"] is None and i["xirr_status"] == "NO_POSITIVE_CASHFLOW" and i["dpi"] == 0 for i in out["investors"])
    blocked = allocate_run(parse_terms(doc), receipts(doc, status="UNPAID_SHL_AT_CONTRACTUAL_MATURITY"), binding=BINDING)
    assert all(i["xirr"] is None and i["xirr_status"] == "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"
               and i["dpi"] is None and i["realized_moic"] is None for i in blocked["investors"])


@pytest.mark.parametrize("policy", ["ROC_FIRST", "PREFERRED_RETURN", "PROMOTE", "GP_CATCH_UP", "SHL", "NAV"])
def test_unsupported_legal_economics_rejected(policy):
    doc = document()
    doc["policy"] = policy
    with pytest.raises(ValueError, match="Only EUR/kEUR"):
        parse_terms(doc)


@pytest.mark.parametrize("field,value", [("investment_class", "SHAREHOLDER_LOAN"), ("investment_class", "PREFERRED_EQUITY"),
    ("commitment_keur", -1), ("commitment_keur", float("nan")), ("ownership_fraction", True), ("ownership_fraction", .1)])
def test_invalid_investor_rejected(field, value):
    doc = document()
    doc["investors"][0][field] = value
    with pytest.raises(ValueError):
        parse_terms(doc)


@pytest.mark.parametrize("change", ["unknown", "duplicate", "overcall", "unknown_investor", "invalid_date"])
def test_invalid_agreement_rejected(change):
    doc = document()
    if change == "unknown":
        doc["shl_receipts"] = 100
    elif change == "duplicate":
        doc["investors"][1]["investor_id"] = "alpha"
    elif change == "overcall":
        doc["contributions"][0]["amount_keur"] = 81
    elif change == "unknown_investor":
        doc["contributions"][0]["investor_id"] = "unknown"
    else:
        doc["contributions"][0]["cash_date"] = "2026-02-30"
    with pytest.raises(ValueError):
        parse_terms(doc)


def test_deterministic_terms_roundtrip_and_duplicate_json_rejection():
    doc = document()
    original = parse_terms(doc)
    doc["investors"].reverse()
    doc["contributions"].reverse()
    assert parse_terms(json.dumps(doc)).to_json() == original.to_json()
    assert parse_terms(original.to_json()) == original
    with pytest.raises(ValueError, match="duplicate JSON"):
        parse_terms('{"version":1,"version":2}')


@pytest.mark.parametrize("fault", ["paid_in", "wrong_date", "gross", "source", "negative_cash"])
def test_receipt_and_contribution_mismatches_fail_closed(fault):
    doc = document()
    receipt = receipts(doc)
    if fault == "paid_in":
        receipt["periods"][0]["paid_in_keur"] += 1
    elif fault == "wrong_date":
        receipt["periods"][0]["date"] = "2026-01-16"
    elif fault == "gross":
        receipt["periods"][-1]["gross_dividend_keur"] += 1
    elif fault == "source":
        receipt["source"] = "CFADS"
    else:
        receipt["periods"][-1]["net_equity_receipt_keur"] = -1
    with pytest.raises(ValueError):
        allocate_run(parse_terms(doc), receipt, binding=BINDING)


@pytest.mark.parametrize("axis", ["owner_id", "project_id", "scenario_id", "snapshot_id", "composite_hash"])
def test_each_identity_axis_and_digest_rejected(axis):
    doc = document()
    out = allocate_run(parse_terms(doc), receipts(doc), binding=BINDING)
    changed = {**BINDING, axis: "other"}
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_evidence(out, **changed)
    mutated = deepcopy(out)
    mutated["investors"][0]["xirr"] = 9
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_evidence(mutated, **BINDING)


def test_export_is_literal_run_bound_evidence_without_recalculation(monkeypatch):
    doc = document()
    doc["investors"][0]["investor_id"] = "=SUM(A1)"
    doc["contributions"][0]["investor_id"] = "=SUM(A1)"
    out = allocate_run(parse_terms(doc), receipts(doc), binding=BINDING)
    import app.model_v2.investor_f4 as f4
    monkeypatch.setattr(f4, "run_waterfall", lambda *_: pytest.fail("export allocation"))
    monkeypatch.setattr(f4, "robust_xirr", lambda *_: pytest.fail("export XIRR"))
    wb = load_workbook(BytesIO(export_investor_evidence(out, project_name="=1+1", historical=True)))
    assert wb["Run Authority"]["B1"].data_type == "s"
    assert wb["Investor Accounts"]["A2"].value == "=SUM(A1)"
    assert wb["Investor Accounts"]["A2"].data_type == "s"
    assert wb["Canonical Equity Receipts"]["E5"].value == 150


@pytest.mark.parametrize("template", ["solar", "wind"])
@pytest.mark.parametrize("two_senior", [False, True])
def test_real_canonical_net_wht_and_shl_boundaries_without_mutation(template, two_senior):
    from dataclasses import asdict
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
    from app.services.production_financial_authority import run_clean_production
    pi = (create_generic_solar_reference if template == "solar" else create_generic_wind_reference)()
    if two_senior:
        from tests.test_financing_f3_multisenior import case
        pi, _ = case(template)
    run = run_clean_production(pi)
    frozen = asdict(run)
    receipt = extract_equity_receipts(run.g2c_result)
    doc = document()
    doc["contributions"] = [dict(investor_id="alpha", cash_date=p["date"], amount_keur=p["paid_in_keur"])
                            for p in receipt["periods"] if p["paid_in_keur"] > 0]
    doc["investors"][0]["commitment_keur"] = run.g2c_result.total_legal_equity_contributed_keur
    out = allocate_run(parse_terms(doc), receipt, binding=BINDING)
    assert sum(i["cumulative_distributions_keur"] for i in out["investors"]) == pytest.approx(
        run.g2c_result.total_net_dividend_received_keur, abs=1e-6)
    assert sum(p["dividend_wht_keur"] for p in receipt["periods"]) == pytest.approx(
        sum(p.dividend_wht_keur for p in run.g2c_result.waterfall_periods))
    assert asdict(run) == frozen

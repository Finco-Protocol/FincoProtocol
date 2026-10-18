"""RC-7 Revenue/PPA V3: independent Decimal reconciliation of multi-contract economics through the real canonical Run.

Every expected value is computed here from the contract terms and the engine's own period axis / production; nothing is derived by calling the
code under test.  Synthetic, transparent contracts only.  Existing released Revenue V2 authority is exercised unchanged.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from app import project_factories as factories
from app.workbook.revenue_multistream import apply_config
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from finco_core.revenue.generation import revenue_decomposition_schedule

ABS = 1e-8
D = Decimal


def _pi(kind):
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    return replace(pi, revenue=replace(pi.revenue, co2_enabled=False))


def _operating(pi):
    return tuple(p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation)


def _row(op, id, type, *, share, price, start=0, end=None, rate=0, **extra):
    end_date = (op[-1] if end is None else op[end - 1]).end_date.isoformat()
    row = dict(id=id, type=type, volume_share=share, price_eur_mwh=price, indexation_rate=rate, settlement="SAME_PERIOD",
               source_ref="synthetic-independent-contract", start_date=op[start].start_date.isoformat(), end_date=end_date)
    row.update(extra)
    return row


def _merchant(op, price=80.0, capture=.8, **extra):
    return _row(op, "market", "merchant", share=None, price=price, capture_rate=capture, **extra)


def _payload(kind, rows):
    return {"version": 2, "technology": kind, "indexation_basis": "OPERATING_YEAR", "streams": rows}


def _decompose(pi, payload, kind):
    active = apply_config(pi, json.dumps(payload), project_type=kind)
    return active, revenue_decomposition_schedule(active, _build_period_engine(from_project_inputs(active)))


def _streams(row):
    return {s["id"]: s for s in row["multistream_evidence"]["streams"]}


def _net(pi, gross):
    """Merchant-balancing adjustments applied by the released composition: pv-rate share of merchant revenue plus per-MWh cost."""
    return gross


KINDS = ["solar", "wind"]


@pytest.mark.parametrize("kind", KINDS)
def test_overlapping_and_sequential_contracts_conserve_physical_mwh_and_expire_on_exact_dates(kind):
    pi = _pi(kind); op = _operating(pi)
    cut = 6                                           # ppa-a ends / ppa-b starts exactly at the period boundary op[cut]
    rows = [_row(op, "ppa-a", "ppa", share=.30, price=55, end=cut),
            _row(op, "ppa-b", "ppa", share=.30, price=63, start=cut),
            _row(op, "ppa-c", "ppa", share=.25, price=48, end=cut + 4),     # overlaps both a (until cut) and b (from cut)
            _merchant(op)]
    _, out = _decompose(pi, _payload(kind, rows), kind)
    for i, period in enumerate(op):
        row = out[period.index]; s = _streams(row); gen = D(str(row["generation_mwh"]))
        shares = {"ppa-a": D("0.30") if i < cut else D(0), "ppa-b": D("0.30") if i >= cut else D(0), "ppa-c": D("0.25") if i < cut + 4 else D(0)}
        for sid, share in shares.items():
            assert D(str(s[sid]["quantity_mwh"])) == pytest.approx(gen * share, abs=D("1e-8")), (sid, i)
            if share == 0:
                assert s[sid]["revenue_keur"] == 0 and s[sid]["status"] in ("not_started", "expired"), (sid, i, s[sid]["status"])
        merchant_share = 1 - sum(shares.values())
        assert D(str(s["market"]["quantity_mwh"])) == pytest.approx(gen * merchant_share, abs=D("1e-8"))
        assert sum(D(str(x["quantity_mwh"])) for x in s.values()) == pytest.approx(gen, abs=D("1e-8")), f"MWh not conserved in period {i}"


@pytest.mark.parametrize("kind", KINDS)
def test_over_allocated_volume_shares_are_rejected_not_scaled(kind):
    pi = _pi(kind); op = _operating(pi)
    rows = [_row(op, "a", "ppa", share=.6, price=50), _row(op, "b", "ppa", share=.5, price=51), _merchant(op)]
    with pytest.raises(ValueError):
        _decompose(pi, _payload(kind, rows), kind)


@pytest.mark.parametrize("kind", KINDS)
def test_fixed_indexed_and_scheduled_prices_reconcile_independently(kind):
    pi = _pi(kind); op = _operating(pi)
    scheduled = [{"period_start": p.start_date.isoformat(), "price_eur_mwh": 40 + 2 * i} for i, p in enumerate(op)]
    rows = [_row(op, "fixed", "ppa", share=.2, price=50),
            _row(op, "indexed", "ppa", share=.2, price=50, rate=.02),
            _row(op, "sched", "ppa", share=.2, price=1, price_curve=scheduled),
            _merchant(op)]
    _, out = _decompose(pi, _payload(kind, rows), kind)
    for i, p in enumerate(op):
        s = _streams(out[p.index]); gen = D(str(out[p.index]["generation_mwh"]))
        assert s["fixed"]["price_eur_mwh"] == pytest.approx(50, abs=1e-12)
        assert s["indexed"]["price_eur_mwh"] == pytest.approx(float(D(50) * D("1.02") ** (p.year_index - 1)), abs=1e-9)
        assert s["sched"]["price_eur_mwh"] == pytest.approx(40 + 2 * i, abs=1e-12)
        for sid in ("fixed", "indexed", "sched"):
            assert s[sid]["revenue_keur"] == pytest.approx(float(gen * D("0.2") * D(str(s[sid]["price_eur_mwh"])) / 1000), abs=ABS)


@pytest.mark.parametrize("kind", KINDS)
def test_explicit_zero_price_is_valid_and_missing_price_is_rejected(kind):
    pi = _pi(kind); op = _operating(pi)
    _, out = _decompose(pi, _payload(kind, [_row(op, "zero", "ppa", share=.4, price=0), _merchant(op)]), kind)
    s = _streams(out[op[0].index])
    assert s["zero"]["price_eur_mwh"] == 0 and s["zero"]["revenue_keur"] == 0 and s["zero"]["quantity_mwh"] > 0
    missing = _row(op, "m", "ppa", share=.4, price=10); del missing["price_eur_mwh"]
    with pytest.raises(ValueError):
        _decompose(pi, _payload(kind, [missing, _merchant(op)]), kind)


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "50", None, True])
@pytest.mark.parametrize("field", ["price_eur_mwh", "volume_share", "indexation_rate"])
def test_negative_nonfinite_and_mistyped_numeric_inputs_are_rejected(field, bad):
    pi = _pi("solar"); op = _operating(pi)
    row = _row(op, "a", "ppa", share=.4, price=50)
    row[field] = bad
    if field == "volume_share" and bad is None:
        pytest.skip("None share is the merchant-residual spelling, not valid for a PPA (covered by schema tests)")
    with pytest.raises(ValueError):
        raw = json.dumps(_payload("solar", [row, _merchant(op)]), allow_nan=True)
        apply_config(pi, raw, project_type="solar")


@pytest.mark.parametrize("kind", KINDS)
def test_duplicate_contract_identity_is_rejected(kind):
    pi = _pi(kind); op = _operating(pi)
    rows = [_row(op, "dup", "ppa", share=.2, price=50), _row(op, "dup", "ppa", share=.2, price=51), _merchant(op)]
    with pytest.raises(ValueError):
        _decompose(pi, _payload(kind, rows), kind)


@pytest.mark.parametrize("kind", KINDS)
def test_signed_cfd_settlement_is_a_financial_overlay_that_never_consumes_physical_mwh(kind):
    pi = _pi(kind); op = _operating(pi)
    curve = [{"period_start": p.start_date.isoformat(), "price_eur_mwh": 40 if i % 2 == 0 else 110} for i, p in enumerate(op)]
    rows = [_row(op, "ppa", "ppa", share=.3, price=60),
            _row(op, "market", "merchant", share=None, price=1, price_curve=curve, capture_rate=1.0),
            _row(op, "cfd", "cfd", share=.2, price=75, reference_stream_id="market")]
    _, out = _decompose(pi, _payload(kind, rows), kind)
    seen = set()
    for i, p in enumerate(op):
        row = out[p.index]; s = _streams(row); gen = D(str(row["generation_mwh"]))
        ref = D(40 if i % 2 == 0 else 110)
        expect = gen * D("0.2") * (D(75) - ref) / 1000
        assert s["cfd"]["settlement_keur"] == pytest.approx(float(expect), abs=ABS)
        seen.add(expect > 0)
        physical = sum(D(str(x["quantity_mwh"])) for x in s.values() if x["type"] != "cfd")
        assert physical == pytest.approx(gen, abs=D("1e-8"))                    # the overlay did not remove or add physical energy
    assert seen == {True, False}                                                # both settlement signs exercised


@pytest.mark.parametrize("kind", KINDS)
def test_p50_and_p90_differ_by_production_basis_and_contract_revenue_scales_with_production(kind):
    pi = _pi(kind); op = _operating(pi)
    rows = [_row(op, "ppa", "ppa", share=.5, price=60), _merchant(op)]
    results = {}
    for name, scenario in (("p50", "P_50"), ("p90", "P90-10y")):
        variant = replace(pi, technical=replace(pi.technical, yield_scenario=scenario))
        _, out = _decompose(variant, _payload(kind, copy.deepcopy(rows)), kind)
        results[name] = out
    p50_hours, p90_hours = pi.technical.operating_hours_p50, pi.technical.operating_hours_p90_10y
    assert p50_hours != p90_hours
    for p in op:
        g50, g90 = D(str(results["p50"][p.index]["generation_mwh"])), D(str(results["p90"][p.index]["generation_mwh"]))
        assert (g90 < g50) == (p90_hours < p50_hours)
        for name, g in (("p50", g50), ("p90", g90)):
            assert _streams(results[name][p.index])["ppa"]["revenue_keur"] == pytest.approx(float(g * D("0.5") * 60 / 1000), abs=ABS)
    assert sum(r["revenue_keur"] for r in results["p50"].values()) != sum(r["revenue_keur"] for r in results["p90"].values())


@pytest.mark.parametrize("kind", KINDS)
def test_contract_price_flows_through_ebitda_tax_cfads_senior_and_returns_in_the_committed_run(kind):
    from app.services.production_financial_authority import run_clean_production
    pi = _pi(kind); op = _operating(pi)

    def run(price):
        rows = [_row(op, "ppa", "ppa", share=.6, price=price), _merchant(op)]
        active = apply_config(pi, json.dumps(_payload(kind, rows)), project_type=kind)
        return run_clean_production(active, "Base", project_type=kind)

    low, high = run(50), run(70)
    lo, hi = low.g2c_result.financing_result.project_model_result, high.g2c_result.financing_result.project_model_result
    d_rev = sum(hi.operating_schedules.revenue_keur) - sum(lo.operating_schedules.revenue_keur)
    assert d_rev > 0
    # EBITDA moves one-for-one with revenue (opex is price independent) ...
    assert sum(hi.operating_schedules.ebitda_keur) - sum(lo.operating_schedules.ebitda_keur) == pytest.approx(d_rev, abs=1e-6)
    # ... and the independent revenue oracle: sum(generation x share x delta price)
    _, out_lo = _decompose(pi, _payload(kind, [_row(op, "ppa", "ppa", share=.6, price=50), _merchant(op)]), kind)
    gen_total = sum(D(str(out_lo[p.index]["generation_mwh"])) for p in op)
    assert d_rev == pytest.approx(float(gen_total * D("0.6") * 20 / 1000), abs=1e-6)
    assert hi.tax_and_cfads.corporate_tax_cash_keur != lo.tax_and_cfads.corporate_tax_cash_keur
    assert hi.tax_and_cfads.cfads_keur != lo.tax_and_cfads.cfads_keur
    assert hi.senior_debt.debt_size_keur != lo.senior_debt.debt_size_keur
    assert high.g2c_result.total_sponsor_xirr != low.g2c_result.total_sponsor_xirr
    assert high.g2c_result.return_summary.project.project_xirr != low.g2c_result.return_summary.project.project_xirr


# ---- C1: physical energy ledger over committed contract evidence ------------------------------------------------------------------------
def _audit(out, op):
    """The per-period shape the Run persists as runtime_summary['revenue_multistream_audit'] (period_index + the evidence block)."""
    return [{"period_index": p.index, **out[p.index]["multistream_evidence"]} for p in op]


@pytest.mark.parametrize("kind", KINDS)
def test_energy_ledger_separates_physical_overlay_and_unallocated_and_cross_checks_production(kind):
    from domain.revenue.contract_energy_ledger import build_contract_energy_ledger, CONSERVED, UNALLOCATED, NOT_CONSERVED
    pi = _pi(kind); op = _operating(pi)
    rows = [_row(op, "ppa", "ppa", share=.3, price=60), _merchant(op), _row(op, "cfd", "cfd", share=.2, price=75, reference_stream_id="market")]
    _, out = _decompose(pi, _payload(kind, rows), kind)
    production = {p.index: out[p.index]["generation_mwh"] for p in op}
    ledger = build_contract_energy_ledger(_audit(out, op), production)
    assert ledger["status"] == CONSERVED and ledger["basis"] == "run_production" and ledger["max_abs_residual_mwh"] < 1e-6
    total_gen = sum(D(str(g)) for g in production.values())
    assert D(str(ledger["totals"]["contracted_mwh"])) == pytest.approx(total_gen * D("0.3"), abs=D("1e-6"))
    assert D(str(ledger["totals"]["merchant_mwh"])) == pytest.approx(total_gen * D("0.7"), abs=D("1e-6"))
    assert D(str(ledger["totals"]["cfd_overlay_mwh"])) == pytest.approx(total_gen * D("0.2"), abs=D("1e-6"))
    assert D(str(ledger["totals"]["physical_mwh"])) == pytest.approx(total_gen, abs=D("1e-6"))      # overlay not added
    # A production figure that disagrees with the committed allocation is NOT_CONSERVED, never silently accepted.
    wrong = {k: v * 1.01 for k, v in production.items()}
    assert build_contract_energy_ledger(_audit(out, op), wrong)["status"] == NOT_CONSERVED
    # Energy no contract took is reported, not hidden: one PPA at 30% and no merchant stream leaves 70% unallocated.
    _, partial = _decompose(pi, _payload(kind, [_row(op, "ppa", "ppa", share=.3, price=60)]), kind)
    unallocated = build_contract_energy_ledger(_audit(partial, op), {p.index: partial[p.index]["generation_mwh"] for p in op})
    assert unallocated["status"] == UNALLOCATED
    total = sum(D(str(partial[p.index]["generation_mwh"])) for p in op)
    assert D(str(unallocated["totals"]["unallocated_mwh"])) == pytest.approx(total * D("0.7"), abs=D("1e-6"))


def test_energy_ledger_fails_closed_on_missing_or_invalid_evidence():
    from domain.revenue.contract_energy_ledger import build_contract_energy_ledger, UNAVAILABLE
    for bad in (None, [], [{"streams": "x"}], [{"streams": [{"type": "ppa", "quantity_mwh": float("nan")}], "unallocated_generation_mwh": 0}],
                [{"streams": [{"type": "ppa", "quantity_mwh": -1}], "unallocated_generation_mwh": 0}],
                [{"streams": [], "unallocated_generation_mwh": None}]):
        assert build_contract_energy_ledger(bad)["status"] == UNAVAILABLE


# ---- lender (P90) vs sponsor (P50) basis under explicit contracts -------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
def test_lender_case_sizes_debt_on_p90_contract_volumes_while_the_base_revenue_schedule_stays_p50(kind):
    from finco_core.inputs._models import YieldScenario
    from app.services.production_financial_authority import run_clean_production
    pi = _pi(kind); op = _operating(pi)
    active = apply_config(pi, json.dumps(_payload(kind, [_row(op, "ppa", "ppa", share=.6, price=60), _merchant(op)])), project_type=kind)

    def run(sizing):
        variant = replace(active, financing=replace(active.financing, debt_sizing_case=replace(
            active.financing.debt_sizing_case, production_yield_scenario=sizing)))
        return run_clean_production(variant, "Base", project_type=kind).g2c_result.financing_result.project_model_result

    p90, p50 = run(YieldScenario.P90_10Y), run(YieldScenario.P50)
    assert p90.senior_debt.debt_size_keur < p50.senior_debt.debt_size_keur          # lender case is the more conservative basis
    # the sponsor/Base operating revenue is the same Base schedule in both: only the sizing basis changed
    assert sum(p90.operating_schedules.revenue_keur) == pytest.approx(sum(p50.operating_schedules.revenue_keur), rel=0, abs=1e-6)

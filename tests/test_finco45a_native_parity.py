"""FINCO45A Linux Native V10/V11 Parity Suite across OFF, S1, S1+2, S3, S1+S3, S1+2+S3.

Reuses ``tools/finco43b_native_parity.py::_run_arm`` and ``_digest`` (no cache hits) on
approved Linux kernels via ``stage3_artifacts``. Skips cleanly on Windows hosts where
``gcc``/Linux ELF kernels are unavailable, and executes mandatory on ``ubuntu-24.04`` CI.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from app import project_factories as pf
from finco_core.inputs import RevenueAdjustmentSchedule
from tests.test_fable_batch3_date_authority_generation import _with_r04
from tools.finco43b_native_parity import ARMS, _run_arm

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sealed_native_sources_and_manifests_unmodified():
    manifests = (
        REPO_ROOT / "financial_engine/native_v10/fk_v10_manifest.json",
        REPO_ROOT / "financial_engine/native_v10/fk_v10_stage2_manifest.json",
        REPO_ROOT / "financial_engine/native_v11/fk_v11_stage3_manifest.json",
    )
    for mpath in manifests:
        data = json.loads(mpath.read_text(encoding="utf-8"))
        assert "build_id" in data and "source_sha256" in data and "approved_blobs_sha256" in data


def _solar_with_zero_schedule_and_shadowed_scalars():
    solar = pf.create_generic_solar_reference()
    return replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_production_share=0.5,
            balancing_cost_pv=0.025,
            balancing_cost_schedule=RevenueAdjustmentSchedule(constant_value=0.0),
            balancing_cost_eur_per_mwh=8.0,
            balancing_cost_wind_eur_mwh=8.0,
        ),
    )


def _solar_with_dual_nonzero():
    solar = pf.create_generic_solar_reference()
    return replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_production_share=0.5,
            balancing_cost_pv=0.025,
            balancing_cost_schedule=RevenueAdjustmentSchedule(constant_value=2.0),
            balancing_cost_eur_per_mwh=0.0,
            balancing_cost_wind_eur_mwh=0.0,
        ),
    )


def _solar_unknown_yield():
    solar = pf.create_generic_solar_reference()
    return replace(
        solar,
        technical=replace(solar.technical, yield_scenario="P99_UNKNOWN"),
    )


def _r04_dated_70gwh():
    base = _with_r04(pf.create_generic_solar_reference(), "solar")
    cfg = json.loads(base.revenue.multistream_config_json)
    for st in cfg["streams"]:
        if st.get("type") == "ppa":
            st["annual_quantity"] = {"mode": "ABSOLUTE_ANNUAL", "amount": "70", "unit": "GWh"}
    return replace(base, revenue=replace(base.revenue, multistream_config_json=json.dumps(cfg, separators=(",", ":"))))


def _r04_dated_100gwh_shortfall():
    base = _with_r04(pf.create_generic_solar_reference(), "solar")
    base = replace(
        base,
        technical=replace(base.technical, capacity_mw=80.0, operating_hours_p50=1500.0, operating_hours_p90_10y=1250.0),
    )
    cfg = json.loads(base.revenue.multistream_config_json)
    for st in cfg["streams"]:
        if st.get("type") == "ppa":
            st["annual_quantity"] = {"mode": "ABSOLUTE_ANNUAL", "amount": "100", "unit": "GWh"}
    return replace(base, revenue=replace(base.revenue, multistream_config_json=json.dumps(cfg, separators=(",", ":"))))


@pytest.mark.usefixtures("stage3_artifacts")
@pytest.mark.parametrize(
    "case_id,builder,project_type,expect_digest,expect_positive_native",
    [
        ("dcorr01_zero_schedule_solar", _solar_with_zero_schedule_and_shadowed_scalars, "Solar", True, True),
        ("dcorr01_dual_nonzero_refused", _solar_with_dual_nonzero, "Solar", False, False),
        ("p1b_tech_02_unknown_yield", _solar_unknown_yield, "Solar", False, False),
        ("r04_dated_70gwh_solar", _r04_dated_70gwh, "Solar", True, True),
        ("r04_dated_100gwh_shortfall", _r04_dated_100gwh_shortfall, "Solar", False, False),
        ("ev_default_12m", pf.create_generic_ev_charging_reference, "Generic EV Charging Hub Reference", True, True),
        ("solar_ref_unchanged", pf.create_generic_solar_reference, "Solar", True, True),
        ("wind_ref_unchanged", pf.create_generic_wind_reference, "Wind", True, True),
        ("dc_ref_unchanged", pf.create_generic_data_center_reference, "Generic Data Center Reference", True, False),
    ],
)
def test_finco45a_six_arm_native_parity(case_id, builder, project_type, expect_digest, expect_positive_native):
    results = {arm: _run_arm(arm, builder, project_type) for arm in ARMS}
    ref = results["OFF"]
    key = ("sha256", "leaves") if expect_digest else ("error_type", "reason_code", "message")
    assert ref["kind"] == ("digest" if expect_digest else "rejected"), (case_id, ref)

    for arm, out in results.items():
        assert out["kind"] == ref["kind"], (case_id, arm, out)
        for field in key:
            assert out.get(field) == ref.get(field), (case_id, arm, field, out, ref)

    if expect_positive_native:
        assert results["S1"]["v10"]["native_solves"] > 0, results["S1"]
        assert results["S1+2"]["v10"]["native_solves"] > 0 and results["S1+2"]["v10"]["stage2_native_calls"] > 0, results["S1+2"]
        assert results["S3"]["v11"]["native_models"] > 0, results["S3"]
        assert results["S1+S3"]["v11"]["native_models"] > 0, results["S1+S3"]
        assert results["S1+2+S3"]["v11"]["native_models"] > 0 and results["S1+2+S3"]["v10"]["stage2_native_calls"] > 0, results["S1+2+S3"]


@pytest.mark.usefixtures("stage3_artifacts")
def test_finco43b_baseline_scenarios_and_declines_six_arms():
    from tools.finco43b_native_parity import _scenarios

    scens = _scenarios()
    for name in (
        "dated:solar_r04",
        "dated:wind_r04",
        "u2s2b:wind_ref_cash_reserve_interest",
        "admission:dated_renamed_type_dc",
        "admission:dated_untyped",
    ):
        build, ptype = scens[name]
        results = {arm: _run_arm(arm, build, ptype) for arm in ARMS}
        ref = results["OFF"]
        key = ("sha256", "leaves") if ref["kind"] == "digest" else ("error_type", "reason_code", "message")
        for arm, out in results.items():
            assert out["kind"] == ref["kind"] and all(out.get(k) == ref.get(k) for k in key), (name, arm, out, ref)
        if name.startswith("admission:"):
            for arm in ("S1", "S1+2", "S3", "S1+S3", "S1+2+S3"):
                assert results[arm]["v10"]["native_solves"] == 0 and results[arm]["v11"]["native_models"] == 0
        else:
            assert results["S1+2+S3"]["v11"]["native_models"] > 0

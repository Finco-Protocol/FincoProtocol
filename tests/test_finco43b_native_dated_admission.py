"""FINCO43B — dated-grid NATIVE admission is decided by the typed, server-owned project type, never by name/code.

Before FINCO43B the dated admission helper excluded DC/EV only by substrings of the user-editable project name/code, so a
renamed DC/EV project on a semi-annual dated grid would have been admitted to the native kernels outside the proved
Solar/Wind scope. Admission now requires ``project_type`` (``projects.project_type`` -> route runtime key ->
``run_project`` -> ``run_clean_production``) to be Solar or Wind; a present multistream configuration must name the same
technology. Every negative is a NATIVE decline only: the Run is served by canonical Python and its financial result is
bit-identical to native OFF (checked end-to-end below with the repository's own verified kernels).
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app import project_factories as pf
from app.services import production_financial_authority as pfa
from financial_engine.native_v10.config import NativeConfig, native_run
from financial_engine.native_v11.config import Stage3Config, stage3_run
from tests.test_fable_batch3_date_authority_generation import _with_r04


def _dated_solar():
    return _with_r04(pf.create_generic_solar_reference(), "solar")


def _renamed(pi, name, code):
    return replace(pi, info=replace(pi.info, name=name, code=code))


def _with_multistream_technology(pi, technology):
    """The R04 fixture's own valid multistream book with only its declared technology changed."""
    cfg = json.loads(pi.revenue.multistream_config_json)
    assert cfg["technology"] == "solar"
    cfg["technology"] = technology
    return replace(pi, revenue=replace(pi.revenue, multistream_config_json=json.dumps(cfg, separators=(",", ":"))))


@pytest.mark.parametrize("project_type", ["Solar", "solar", " SOLAR ", "Generic Solar Reference"])
def test_typed_solar_is_admitted(project_type):
    assert pfa._is_dated_native_proved(_dated_solar(), project_type) is True


@pytest.mark.parametrize("project_type", [
    "", None, "Generic Data Center Reference", "Generic EV Charging Hub Reference", "Generic EV Charging Reference",
    "data center", "ev_charging", "Storage", "Portfolio", "Test 1", "Solar Park", "solar ", 1, b"Solar",
])
def test_untyped_unknown_or_non_solar_wind_type_is_declined(project_type):
    if project_type == "solar ":          # whitespace is normalised; keep one positive control inside the matrix
        assert pfa._is_dated_native_proved(_dated_solar(), project_type) is True
        return
    assert pfa._is_dated_native_proved(_dated_solar(), project_type) is False


def test_name_and_code_never_admit():
    """The pre-FINCO43B false admission: DC/EV renamed to an innocent name used to pass; now the typed type decides."""
    innocent = _renamed(_dated_solar(), "Sunny Valley", "SV-01")
    assert pfa._is_dated_native_proved(innocent, "Generic Data Center Reference") is False
    assert pfa._is_dated_native_proved(innocent, "Generic EV Charging Hub Reference") is False
    # a misleading name on a typed Solar project: still Solar by type -> admitted
    assert pfa._is_dated_native_proved(_renamed(_dated_solar(), "Wind & Sun", "WS-7"), "Solar") is True


def test_legacy_name_tokens_can_only_decline():
    misleading = _renamed(_dated_solar(), "Solar for a Data Center", "SOL-DC")
    assert pfa._is_dated_native_proved(misleading, "Solar") is False          # safe native decline (canonical Python)


def test_multistream_technology_must_match_the_typed_vertical():
    assert pfa._is_dated_native_proved(_with_multistream_technology(_dated_solar(), "solar"), "Solar") is True
    assert pfa._is_dated_native_proved(_with_multistream_technology(_dated_solar(), "wind"), "Solar") is False
    assert pfa._is_dated_native_proved(_with_multistream_technology(_dated_solar(), "solar"), "Wind") is False


def test_malformed_multistream_cannot_reach_admission_and_parse_order_is_unchanged(monkeypatch):
    """A malformed book is refused when the typed Revenue is built, before any Run; and the admission helper still
    parses a present book for EVERY project type (accepted order), so exception precedence cannot change."""
    with pytest.raises(ValueError, match="REVENUE_V2_SCHEMA"):
        replace(_dated_solar().revenue, multistream_config_json="{not json")
    pi = _dated_solar()                    # built first: Revenue construction itself parses the book
    import domain.revenue.multistream_runtime as msr
    calls = []
    real = msr.parse_config
    monkeypatch.setattr(msr, "parse_config", lambda raw: calls.append(1) or real(raw))
    for project_type in ("Solar", "", "Generic Data Center Reference", "Storage"):
        pfa._is_dated_native_proved(pi, project_type)
    assert len(calls) == 4


def test_non_semestrial_and_bess_still_declined_for_typed_solar():
    from finco_core.engine.period_engine import PeriodFrequency
    annual = replace(_dated_solar(), info=replace(_dated_solar().info, period_frequency=PeriodFrequency.ANNUAL))
    assert pfa._is_dated_native_proved(annual, "Solar") is False
    # BESS markers decline even for a typed Solar project (the helper reads only these two typed attributes)
    from types import SimpleNamespace
    for technical in (SimpleNamespace(bess_enabled=True, bess_native_config_json=""),
                      SimpleNamespace(bess_enabled=False, bess_native_config_json='{"x":1}')):
        bess = SimpleNamespace(info=_dated_solar().info, technical=technical, revenue=_dated_solar().revenue)
        assert pfa._is_dated_native_proved(bess, "Solar") is False
    plain = SimpleNamespace(info=_dated_solar().info, technical=SimpleNamespace(bess_enabled=False, bess_native_config_json=""),
                            revenue=_dated_solar().revenue)
    assert pfa._is_dated_native_proved(plain, "Solar") is True          # control: only the BESS marker differs


# ── end-to-end: real verified kernels; declines are canonical and financially identical ─────────────────────────────
from tests.native_v10_support import evidence_of  # noqa: E402


def _run(inputs, project_type, v10, v11):
    pfa._POLICY_RUN_CACHE.clear()
    with native_run(v10) as s10, stage3_run(v11) as s11:
        result = pfa.run_clean_production(inputs, project_type=project_type)
    pfa._POLICY_RUN_CACHE.clear()
    return result, s10.as_dict(), s11.as_dict()


@pytest.mark.usefixtures("stage3_artifacts")
def test_end_to_end_typed_admission_and_canonical_declines():
    off = (NativeConfig(mode="off"), Stage3Config(mode="off"))
    on = (NativeConfig(mode="candidate", stage2_experimental=True), Stage3Config(mode="candidate"))
    pi = _dated_solar()
    base, b10, b11 = _run(pi, "Solar", *off)
    assert b10["native_solves"] == 0 and b11["native_models"] == 0
    reference = evidence_of(base)

    admitted, a10, a11 = _run(pi, "Solar", *on)
    assert a11["native_models"] > 0 and a10["stage2_native_calls"] > 0, (a10, a11)
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in a10["declines"]
    assert evidence_of(admitted) == reference

    # same dated inputs, renamed innocently, but the typed type is not Solar/Wind (or absent): native declines
    renamed = _renamed(pi, "Sunny Valley", "SV-01")
    for project_type in ("", "Generic Data Center Reference"):
        declined, d10, d11 = _run(renamed, project_type, *on)
        assert d10["declines"].get("DATE_AUTHORITY_NATIVE_UNSUPPORTED") == 1, d10
        assert d11["declines"].get("DATE_AUTHORITY_NATIVE_UNSUPPORTED") == 1, d11
        assert d10["native_solves"] == 0 and d10["stage2_native_calls"] == 0 and d11["native_models"] == 0
        assert evidence_of(declined) == evidence_of(_run(renamed, project_type, *off)[0])

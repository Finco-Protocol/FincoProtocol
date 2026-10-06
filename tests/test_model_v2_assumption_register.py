"""Workflow 04 - Assumption Register acceptance matrix.

Acceptance markers:

  ASSUMPTION_REGISTER_DETERMINISTIC          (A) identical input -> byte-identical
  ASSUMPTION_REGISTER_STABLE_IDS             (B) ids independent of display labels
  ASSUMPTION_REGISTER_MISSING_NOT_ZERO       (C) MISSING distinct from ZERO
  ASSUMPTION_REGISTER_NAN_FAIL_CLOSED        (D) NaN/Inf never enter
  ASSUMPTION_REGISTER_WORKING_COPY_MARKED    (E) context recorded verbatim
  ASSUMPTION_REGISTER_RUN_BOUND_STRICT       (F) Last Run never faked
  ASSUMPTION_REGISTER_REVENUE_PLAN_LINEAGE   (G) typed RevenuePlan lineage
  ASSUMPTION_REGISTER_CAPEX_UNITS            (H) canonical CAPEX units preserved
  ASSUMPTION_REGISTER_OPEX_SEMANTICS         (I) inflation + step changes preserved
  ASSUMPTION_REGISTER_CONTINGENCY_UNITS      (J) percentage authority stays a fraction
  ASSUMPTION_REGISTER_INPUTS_NOT_OUTPUTS     (K) sizing inputs, not engine outputs
  ASSUMPTION_REGISTER_TAX_AUTHORITY          (L) typed tax authority preserved
  ASSUMPTION_REGISTER_OVERRIDE_PROVENANCE    (M) overrides marked only when proven
  ASSUMPTION_REGISTER_NO_DATACLASS_DUMP      (N) curated semantic surface only
  ASSUMPTION_REGISTER_SERIALIZATION_GUARD    (O) roundtrip + schema fail-closed
"""
from __future__ import annotations

import pytest

from app.model_v2.assumption_register import (
    ASSUMPTION_REGISTER_SCHEMA_ID,
    ASSUMPTION_REGISTER_SCHEMA_VERSION,
    AssumptionContextKind,
    AssumptionEntry,
    AssumptionRegister,
    AssumptionSourceKind,
    ContingencyAuthorityRef,
    RegisterContext,
    RunIdentity,
    ValuePresence,
    build_assumption_register,
)
from dataclasses import replace as dc_replace

from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from domain.revenue.plan import (
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
)
from domain.revenue.revenue_config import MerchantParams, PPAParams

TOL = 1e-12


def _context(**kw):
    return RegisterContext.for_working_copy(
        state_provenance=AssumptionSourceKind.FACTORY_DEFAULT, **kw
    )


def _register(inputs=None, **kw):
    return build_assumption_register(
        create_generic_solar_reference() if inputs is None else inputs,
        _context(**kw),
    )


@pytest.fixture(scope="module")
def solar_register():
    return _register()


def test_a_identical_input_is_byte_identical(solar_register):
    """ASSUMPTION_REGISTER_DETERMINISTIC = PASS"""
    assert _register().to_json() == solar_register.to_json()


def test_b_ids_survive_display_relabel():
    """ASSUMPTION_REGISTER_STABLE_IDS = PASS - labels never become identity."""
    base = create_generic_solar_reference()
    relabelled = dc_replace(
        base,
        capex=dc_replace(
            base.capex,
            epc_contract=dc_replace(
                base.capex.epc_contract, name="Relabelled EPC"
            ),
        ),
    )
    a = {e.assumption_id for e in _register(base).entries}
    b = {e.assumption_id for e in _register(relabelled).entries}
    assert a == b
    # Labels are slot-canonical, not item names: relabelling a CapexItem
    # moves neither the entry id nor the stable label.
    assert _register(relabelled).entry(
        "capex.epc_contract.amount_keur"
    ).label == _register(base).entry(
        "capex.epc_contract.amount_keur"
    ).label


def test_c_missing_is_distinct_from_zero(solar_register):
    """ASSUMPTION_REGISTER_MISSING_NOT_ZERO = PASS."""
    bess_flag = solar_register.entry("technical.bess_enabled")
    assert bess_flag.value is False
    assert bess_flag.value_presence is ValuePresence.PRESENT
    p99 = solar_register.entry("technical.operating_hours_p99_1y")
    assert p99.value is None
    assert p99.value_presence is ValuePresence.MISSING
    # A zero CAPEX line is a PRESENT ZERO, never a MISSING.
    taxes = solar_register.entry("capex.taxes.amount_keur")
    if taxes.value == 0:
        assert taxes.value_presence is ValuePresence.PRESENT
        assert taxes.value_type == "float"


def test_d_nan_and_inf_fail_closed():
    """ASSUMPTION_REGISTER_NAN_FAIL_CLOSED = PASS."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="NOT_FINITE"):
            AssumptionEntry(
                assumption_id="x", section="T", canonical_path="t.x",
                label="X", value=bad, value_presence=ValuePresence.PRESENT,
                value_type="float", unit="1",
                source_kind=AssumptionSourceKind.UNKNOWN,
            )
    with pytest.raises(ValueError, match="NOT_FINITE"):
        AssumptionEntry(
            assumption_id="x", section="T", canonical_path="t.x",
            label="X", value=[1.0, float("nan")],
            value_presence=ValuePresence.PRESENT, value_type="array",
            unit="1", source_kind=AssumptionSourceKind.UNKNOWN,
        )


def test_e_working_copy_is_explicitly_marked(solar_register):
    """ASSUMPTION_REGISTER_WORKING_COPY_MARKED = PASS."""
    assert solar_register.context.context_kind is AssumptionContextKind.WORKING_COPY
    payload = solar_register.to_dict()
    assert payload["context"]["context_kind"] == "WORKING_COPY"
    assert payload["context"]["run_identity"] is None


def test_f_run_bound_never_fakes_last_run():
    """ASSUMPTION_REGISTER_RUN_BOUND_STRICT = PASS."""
    with pytest.raises(TypeError):
        RegisterContext.for_run_bound()
    identity = RunIdentity(
        snapshot_id="20261006T000000Z",
        composite_hash="deadbeef",
        workbook_version="2.3.0",
        engine_version="clean_senior_debt_v0",
    )
    run_bound = build_assumption_register(
        create_generic_solar_reference(),
        RegisterContext.for_run_bound(
            run_identity=identity,
            state_provenance=AssumptionSourceKind.USER_INPUT,
        ),
    )
    payload = run_bound.to_dict()
    assert payload["context"]["context_kind"] == "RUN_BOUND"
    assert payload["context"]["run_identity"]["snapshot_id"] == (
        "20261006T000000Z"
    )
    assert AssumptionRegister.from_json(run_bound.to_json()).fingerprint == (
        run_bound.fingerprint
    )
    with pytest.raises(ValueError, match="WORKING_COPY register must not"):
        RegisterContext(
            context_kind=AssumptionContextKind.WORKING_COPY,
            run_identity=identity,
        )
    incomplete = RunIdentity(
        snapshot_id="", composite_hash="deadbeef",
        workbook_version="2.3.0", engine_version="clean_senior_debt_v0",
    )
    with pytest.raises(ValueError, match="RUN_IDENTITY_INCOMPLETE"):
        RegisterContext.for_run_bound(run_identity=incomplete)


def _plan_from_authority():
    """Build a RevenuePlan through the public Workflow 02 authority."""
    ppa = PPAParams(
        ppa_base_price_eur_mwh=57.0,
        ppa_price_index=0.02,
        ppa_start_year=1,
        ppa_term_years=15.0,
        ppa_volume_share=0.7,
    )
    merchant = MerchantParams(
        merchant_enabled=True, base_price_eur_mwh=65.0,
        price_scenario="base",
    )
    streams = (
        RevenueStream(
            stream_id="ppa", stream_type=RevenueStreamType.PPA,
            volume_share=0.7, ppa=ppa,
        ),
        RevenueStream(
            stream_id="merchant", stream_type=RevenueStreamType.MERCHANT,
            volume_share=None, merchant=merchant,
        ),
    )
    return RevenuePlan.create(streams)


def test_g_revenue_plan_lineage_is_typed(solar_register):
    """ASSUMPTION_REGISTER_REVENUE_PLAN_LINEAGE = PASS."""
    plan = _plan_from_authority()
    register = _register(revenue_plan=plan)
    stream = register.entry("revenue.plan.stream.ppa.stream_type")
    assert stream.value == "ppa"
    assert stream.lineage_ref is not None and "RevenuePlan" in stream.lineage_ref
    assert register.entry(
        "revenue.plan.stream.ppa.contract_role"
    ).value == "primary_allocation"
    assert register.entry(
        "revenue.plan.stream.merchant.volume_share"
    ).value is None
    # payloads without a plan carry no plan entries at all
    assert not any(
        e.assumption_id.startswith("revenue.plan.") for e in solar_register.entries
    )


def test_h_capex_units_are_canonical(solar_register):
    """ASSUMPTION_REGISTER_CAPEX_UNITS = PASS."""
    epc = solar_register.entry("capex.epc_contract.amount_keur")
    assert epc.value == pytest.approx(
        create_generic_solar_reference().capex.epc_contract.amount_keur,
        abs=TOL,
    )
    assert epc.unit == "kEUR"
    profile = solar_register.entry("capex.epc_contract.spending_profile")
    assert profile.unit == "fraction"
    assert abs(sum(profile.value) + solar_register.entry(
        "capex.epc_contract.y0_share"
    ).value - 1.0) < 1e-9
    assert solar_register.entry(
        "capex.epc_contract.asset_class"
    ).value == "solar_panels"
    # derived construction-layer financing values are never assumptions
    all_ids = {e.assumption_id for e in solar_register.entries}
    for derived in (
        "capex.idc_keur",
        "capex.commitment_fees_keur",
        "capex.bank_fees_keur",
        "capex.reserve_accounts_keur",
    ):
        assert derived not in all_ids


def test_i_opex_semantics_preserved(solar_register):
    """ASSUMPTION_REGISTER_OPEX_SEMANTICS = PASS."""
    inputs = create_generic_solar_reference()
    first = inputs.opex[0]
    y1 = solar_register.entry("opex.items[0].y1_amount_keur")
    assert y1.value == pytest.approx(first.y1_amount_keur, abs=TOL)
    assert y1.unit == "kEUR"
    infl = solar_register.entry("opex.items[0].annual_inflation")
    assert infl.value == pytest.approx(first.annual_inflation, abs=TOL)
    assert infl.unit == "fraction_per_year"
    any_steps = [
        e for e in solar_register.entries if e.assumption_id.endswith(
            ".step_changes"
        ) and e.value is not None
    ]
    for entry in any_steps:
        index = int(entry.assumption_id.split("[")[1].split("]")[0])
        assert entry.value == [list(p) for p in inputs.opex[index].step_changes]


def test_j_contingency_units_stay_fractions(solar_register):
    """ASSUMPTION_REGISTER_CONTINGENCY_UNITS = PASS."""
    authority = ContingencyAuthorityRef(
        capex_pct=0.03, opex_pct=0.02,
        source_ref="test: proven replay-metadata authority",
    )
    register = _register(contingency_authority=authority)
    capex_pct = register.entry("capex.contingency.pct")
    assert capex_pct.value == pytest.approx(0.03, abs=TOL)
    assert capex_pct.unit == "fraction_of_capex"
    opex_pct = register.entry("opex.contingency.pct")
    assert opex_pct.value == pytest.approx(0.02, abs=TOL)
    assert opex_pct.unit == "fraction_of_opex"
    assert not any(
        e.assumption_id.startswith("capex.contingency")
        for e in solar_register.entries
    )


def test_k_inputs_not_outputs(solar_register):
    """ASSUMPTION_REGISTER_INPUTS_NOT_OUTPUTS = PASS."""
    sizing = solar_register.entry("financing.senior_debt_amount_keur")
    assert sizing.value == create_generic_solar_reference().financing.senior_debt_amount_keur
    all_ids = {e.assumption_id for e in solar_register.entries}
    for engine_output in (
        "financing.final_senior_commitment_keur",
        "financing.dscr_debt_capacity_keur",
        "financing.derived_shl_cash_principal_keur",
        "financing.shl_idc_keur",
        "returns.project_xirr",
        "returns.min_dscr",
    ):
        assert engine_output not in all_ids


def test_l_tax_authority_typed(solar_register):
    """ASSUMPTION_REGISTER_TAX_AUTHORITY = PASS."""
    inputs = create_generic_solar_reference()
    mode = solar_register.entry("tax.shl_interest_deductibility")
    assert mode.value == inputs.tax.shl_interest_deductibility.value
    assert solar_register.entry(
        "tax.corporate_rate"
    ).value == pytest.approx(inputs.tax.corporate_rate, abs=TOL)
    assert solar_register.entry(
        "tax.clean_cash_tax_timing_enabled"
    ).value is True


def test_m_overrides_marked_only_when_proven(solar_register):
    """ASSUMPTION_REGISTER_OVERRIDE_PROVENANCE = PASS."""
    # No proof supplied: override_proven must be UNKNOWN (None) everywhere.
    assert all(e.override_proven is None for e in solar_register.entries)
    ids = {"revenue.ppa_base_tariff", "revenue.ppa_index"}
    proven = _register(scenario_override_ids=ids)
    assert proven.entry("revenue.ppa_base_tariff").override_proven is True
    assert proven.entry("revenue.ppa_base_tariff").source_kind is (
        AssumptionSourceKind.SCENARIO_OVERRIDE
    )
    assert proven.entry("revenue.market_scenario").override_proven is False
    assert proven.entry("technical.capacity_mw").override_proven is False
    payload = proven.to_dict()
    assert payload["context"]["scenario_override_proof_supplied"] is True
    assert solar_register.to_dict()[
        "context"
    ]["scenario_override_proof_supplied"] is False


def test_n_no_dataclass_dump(solar_register):
    """ASSUMPTION_REGISTER_NO_DATACLASS_DUMP = PASS."""
    entries = solar_register.entries
    ids = [e.assumption_id for e in entries]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)
    assert 150 < len(ids) < 400
    for capability_flag in ("info.use_shl_canonical_engine",
                            "info.use_tax_bridge_engine",
                            "info.use_senior_rate_schedule_engine"):
        assert capability_flag not in ids
    assert not any(i.startswith("info.use_") for i in ids)
    known_sections = {
        "PROJECT", "TECHNICAL", "REVENUE", "CAPEX", "OPEX",
        "FINANCING", "TAX", "VALUATION",
    }
    assert {e.section for e in entries} == known_sections


def test_o_serialization_guard(solar_register):
    """ASSUMPTION_REGISTER_SERIALIZATION_GUARD = PASS."""
    payload = solar_register.to_dict()
    assert payload["schema_id"] == ASSUMPTION_REGISTER_SCHEMA_ID
    assert payload["schema_version"] == ASSUMPTION_REGISTER_SCHEMA_VERSION
    assert payload["entry_count"] == len(payload["entries"])
    back = AssumptionRegister.from_dict(payload)
    assert back.to_json() == solar_register.to_json()
    with pytest.raises(ValueError, match="SCHEMA_ID_MISMATCH"):
        AssumptionRegister.from_dict({**payload, "schema_id": "other"})
    with pytest.raises(ValueError, match="SCHEMA_VERSION_UNSUPPORTED"):
        AssumptionRegister.from_dict({**payload, "schema_version": 99})
    with pytest.raises(ValueError, match="field mismatch"):
        broken = dict(payload)
        broken["entries"] = [dict(payload["entries"][0], extra="x")]
        AssumptionRegister.from_dict(broken)
    with pytest.raises(ValueError, match="NOT_FINITE"):
        AssumptionRegister.from_json(
            '{"schema_id": "' + ASSUMPTION_REGISTER_SCHEMA_ID + '", '
            '"schema_version": 1, "context": {}, '
            '"entries": [{"assumption_id": "x", "value": NaN}]}'
        )


def test_p_wind_register_is_distinct_and_deterministic():
    """Companion proof: wind builds independently, differs from solar."""
    wind = build_assumption_register(
        create_generic_wind_reference(),
        _context(),
    )
    assert wind.to_json() == build_assumption_register(
        create_generic_wind_reference(), _context()
    ).to_json()
    assert wind.fingerprint != _register().fingerprint
    assert len(wind.entries) == len(_register().entries)

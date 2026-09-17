"""Focused, fully offline R10 model-radar tests.

Deterministic synthetic fixtures only.  R10 binds frozen model authority to
the R9 asset graph and compares ONLY when every comparability dimension is
source-proven; missing model authority is an honest typed PARTIAL state.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import AssetKey
from finco_radar.execution_simulator.contracts import (
    CostTreatmentState,
    ExecutionMode,
    ExecutionScenario,
    SimulationTimingPolicy,
    ScenarioQuoteEvidence,
    verify_serialized_evidence as verify_r8,
)
from finco_radar.execution_simulator.engine import build_execution_simulation
from finco_radar.model_radar.bridge import (
    MODEL_AUTHORITY_INVENTORY,
    build_model_radar_snapshot,
    discover_model_binding,
    resolve_model_binding,
    verify_r9_lineage,
)
from finco_radar.model_radar.comparisons import (
    MarketComparabilityContext,
    compute_execution_comparison,
    compute_reference_comparison,
    model_value_per_unit,
    resolve_comparability,
)
from finco_radar.model_radar.contracts import (
    PHASE,
    decimal_from_authority,
    SCHEMA_VERSION,
    ComparabilityDimension,
    ComparabilityState,
    ModelBinding,
    ModelEvidence,
    ModelRadarError,
    ModelRadarGapKind,
    ModelRadarStatus,
    ModelRadarTimingPolicy,
    ModelUnitBasis,
    ModelValueKind,
    digest_payload,
    verify_serialized_r10_evidence,
    verify_r10_snapshot_digest,
)
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.r9.live_proof import (
    build_graph_from_upstream as build_r9_evidence,
)

T = timezone.utc
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=T)
UID = "AAPL"
KEY = AssetKey(4663, "0x" + "aa" * 20)
VENUE = "LIFI_V1_QUOTE"
R7_LABELS = [
    "ORACLE_REFERENCE→VENUE[DEX:BUY:100]",
    "ORACLE_REFERENCE→VENUE[DEX:BUY:1000]",
    "ORACLE_REFERENCE→VENUE[DEX:SELL:100]",
    "ORACLE_REFERENCE→VENUE[DEX:SELL:1000]",
]
REFERENCE_PRICE = Decimal("105")
EXEC_PRICES = {
    (QuoteSide.BUY, "100"): "108",
    (QuoteSide.BUY, "1000"): "112",
    (QuoteSide.SELL, "100"): "102",
    (QuoteSide.SELL, "1000"): "98",
}
POLICY = ModelRadarTimingPolicy(
    max_model_age_seconds=Decimal("900"),
    max_model_market_skew_seconds=Decimal("300"),
)
R8_POLICY = SimulationTimingPolicy(
    max_cost_evidence_age_seconds=Decimal("600"),
    max_settlement_evidence_age_seconds=Decimal("600"),
)


def _digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------------------------------
# R9 evidence chain fixture (same shape as the frozen R9 live derivation)
# --------------------------------------------------------------------------

def _rich_r7(uid=UID, key=KEY, oracle_price="105"):
    evidence = {
        "schemaVersion": "radar-r7-cross-market-v1",
        "phase": "R7",
        "status": "CROSS_MARKET_OK",
        "economicAssetUid": uid,
        "canonicalAssetKey": {"chainId": key.chain_id,
                              "contractAddress": key.contract_address},
        "identityBinding": {
            "economicAssetUid": uid,
            "canonicalKeys": [
                {"chainId": key.chain_id, "contractAddress": key.contract_address}],
            "referenceIdentifiers": [uid],
            "source": "SYNTHETIC_TEST_REGISTRY",
        },
        "layers": {
            "underlying": None,
            "fx": {"present": False, "sourceCurrency": None,
                   "targetCurrency": None, "rate": None, "source": None,
                   "observedAt": None},
            "oracleReference": {
                "status": "AVAILABLE", "source": "ROBINHOOD_RHJ",
                "price": str(oracle_price), "currency": "USD",
                "observedAt": NOW.isoformat(), "instrument": uid,
                "multiplier": "1", "usable": True, "assetUid": uid,
                "assetKey": f"{key.chain_id}:{key.contract_address}",
            },
            "externalOracle": None,
            "token": {
                "economicAssetUid": uid, "chainId": key.chain_id,
                "contractAddress": key.contract_address, "symbol": uid,
                "multiplier": "1", "representationStatus": "ACTIVE",
                "referenceUsable": True, "observedPrice": None,
                "currency": "USD", "observedAt": None,
            },
            "venues": [{
                "venue": VENUE, "side": "BUY", "notionalUsd": "100",
                "price": "101", "currency": "USD",
                "observedAt": NOW.isoformat(),
                "source": "R0_EXECUTION_QUOTE_VIA_R3_LIQUIDITY",
                "chainId": key.chain_id,
                "contractAddress": key.contract_address,
                "gapBps": "100", "routeSignature": "SYNTH:ROUTE",
                "rawEvidence": {},
            }],
            "settlement": {
                "settlementAssetSymbol": "USDG", "chainId": 4663,
                "contractAddress": "0x" + "cc" * 20,
                "settlementCurrency": "USD", "transferRequired": None,
                "authorityStatus": "CONTEXT_ONLY", "resolved": True,
            },
        },
        "dislocationComponents": [
            {"label": label, "fromLayer": "ORACLE_REFERENCE",
             "toLayer": "VENUE", "deltaBps": "-16.20"}
            for label in R7_LABELS
        ],
        "attributionState": "MULTI_LAYER_DISLOCATION",
        "boundaries": {"crossMarketAuthority": "R7_APPLIED"},
    }
    evidence["r7SnapshotDigest"] = _digest(
        {k: v for k, v in evidence.items() if k != "r7SnapshotDigest"})
    return evidence


def _r8_row(side, notional, exec_price=None):
    base = dict(
        side=side,
        requested_notional_usd=Decimal(notional),
        token_amount=Decimal("10") if notional == "1000" else Decimal("1"),
        reference_price_usd_per_token=Decimal("100"),
        quote_observed_at=NOW,
        reference_generated_at=NOW,
        settlement_observed_at=NOW,
        canonical_asset_key=KEY,
        venue=VENUE,
        route_signature="SYNTH:ROUTE",
        route_changed=False,
        provider_fee_usd=Decimal("0.10"),
        provider_gas_usd=None,
        provider_cost_treatment=CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED,
        r0_quote_evidence={"synthetic": True},
        r2_gap_evidence={"synthetic": True},
    )
    if side is QuoteSide.BUY:
        base["r2_gap_bps"] = Decimal("200") if notional == "1000" else Decimal("100")
        base["settlement_amount_usd"] = (
            Decimal("1020") if notional == "1000" else Decimal("101"))
    else:
        base["r2_gap_bps"] = Decimal("-200") if notional == "1000" else Decimal("-100")
        base["settlement_amount_usd"] = (
            Decimal("980") if notional == "1000" else Decimal("99"))
    if exec_price is not None:
        base["r2_gap_evidence"] = {
            "referencePriceUsdPerToken": "100",
            "executionPriceUsdPerToken": exec_price,
            "gapBps": str(base["r2_gap_bps"]),
        }
    return ScenarioQuoteEvidence(**base)


def _r8_evidence(uid=UID, key=KEY, exec_prices=None, oracle_price="105"):
    r7 = _rich_r7(uid=uid, key=key, oracle_price=oracle_price)
    combos = (
        (QuoteSide.BUY, "100"), (QuoteSide.BUY, "1000"),
        (QuoteSide.SELL, "100"), (QuoteSide.SELL, "1000"),
    )
    r3_evidence = {
        "status": "PASS",
        "asset": {"assetUid": uid,
                  "canonicalKey": f"{key.chain_id}:{key.contract_address}",
                  "symbol": uid, "chainId": key.chain_id,
                  "contractAddress": key.contract_address},
    }
    scenarios, rows = [], []
    for side, notional in combos:
        price = (exec_prices or {}).get((side, notional))
        scenarios.append(ExecutionScenario(
            economic_asset_uid=uid, canonical_asset_key=key, side=side,
            requested_notional_usd=Decimal(notional), quote_source=VENUE,
            execution_mode=ExecutionMode.REFERENCE_RELATIVE,
            r7_component_label=f"ORACLE_REFERENCE→VENUE[DEX:{side.value}:{notional}]",
            as_of=NOW,
        ))
        rows.append(_r8_row(side, notional, price))
    snapshot = build_execution_simulation(
        economic_asset_uid=uid, canonical_asset_key=key,
        scenarios=scenarios, quote_evidence=rows, policy=R8_POLICY,
        upstream_evidence={
            "r7CrossMarketEvidence": r7, "r3LiquidityEvidence": r3_evidence,
        },
        source_digests={
            "r7CrossMarketDigest": _digest(r7),
            "r3LiquidityDigest": _digest(r3_evidence),
        },
        synthetic=True, generated_at=NOW,
    )
    return snapshot.to_evidence_dict()


def _r9_evidence(uid=UID, key=KEY, oracle_price="105", exec_prices=None):
    r8 = _r8_evidence(uid=uid, key=key, exec_prices=exec_prices,
                      oracle_price=oracle_price)
    return build_r9_evidence(
        r8_evidence=r8, git_head="test-head",
        generated_at=datetime(2026, 9, 17, 11, 0, tzinfo=T),
    )


def _reseal_r9(r9: dict) -> dict:
    r9["r9SnapshotDigest"] = _digest(
        {k: v for k, v in r9.items() if k != "r9SnapshotDigest"})
    return r9


def _reseal_r8(r8: dict) -> dict:
    r8["r8SnapshotDigest"] = _digest(
        {k: v for k, v in r8.items() if k != "r8SnapshotDigest"})
    return r8


# --------------------------------------------------------------------------
# Model evidence fixture
# --------------------------------------------------------------------------

def _model(**over):
    uid = over.pop("uid", UID)
    input_evidence = over.pop("input_evidence", {
        "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
        "cashFlows": ["-100", "110"], "dates": ["2026-01-01", "2027-01-01"],
        "currency": "USD", "economicScope": f"unit:{uid}",
    })
    value = over.pop("value", Decimal("100"))
    kind = over.pop("value_kind", ModelValueKind.VALUE_PER_ECONOMIC_UNIT)
    output_evidence = over.pop("output_evidence", {
        "valueKind": kind.value, "value": str(value),
    })
    return ModelEvidence(
        model_id=over.pop("model_id", "FINCO-SYNTH-PROJECT-MODEL"),
        model_version=over.pop("model_version", "1.0.0"),
        engine_authority=over.pop("engine_authority", "financial_engine"),
        economic_asset_uid=uid,
        economic_node_id=over.pop("economic_node_id", f"economic:{uid}"),
        valuation_as_of=over.pop("valuation_as_of", NOW),
        value_kind=kind,
        value=value,
        currency=over.pop("currency", "USD"),
        unit_basis=over.pop("unit_basis", ModelUnitBasis.PER_ECONOMIC_UNIT),
        input_digest=digest_payload(input_evidence),
        output_digest=digest_payload(output_evidence),
        input_evidence=input_evidence,
        output_evidence=output_evidence,
        unit_multiplier=over.pop("unit_multiplier", None),
        synthetic=True,
    )


def _bridge(r9, model=None, r8=None, *, now=NOW, synthetic=True):
    return build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8, model_evidence=model,
        timing_policy=POLICY, now=now, git_head="test-head",
        synthetic=synthetic,
    )


FULL = dict(oracle_price="105", exec_prices=EXEC_PRICES)


# --------------------------------------------------------------------------
# 66.1-66.4: deterministic model binding
# --------------------------------------------------------------------------

def test_01_binding_id_deterministic():
    a = ModelBinding(economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
                     model_id="M", model_version="1")
    b = ModelBinding(economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
                     model_id="M", model_version="1")
    assert a.binding_id == b.binding_id
    assert a.binding_id.startswith("model-binding:")


def test_02_binding_uses_economic_uid_not_ticker():
    with pytest.raises(ModelRadarError):
        ModelBinding(economic_asset_uid=UID, economic_node_id="AAPL",
                     model_id="M", model_version="1")


def test_03_ticker_alone_cannot_bind():
    # Identical display symbol, different economic UID: ticker similarity
    # carries zero binding authority.
    with pytest.raises(ModelRadarError) as excinfo:
        resolve_model_binding(
            model_evidence=_model(uid="EVIL",
                                  output_evidence={"symbol": UID, "value": "1"}),
            r9_lineage={"economic_asset_uid": UID,
                        "economic_node_id": f"economic:{UID}"},
        )
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_04_canonical_economic_node_id_exact():
    binding = ModelBinding(economic_asset_uid=UID,
                           economic_node_id=f"economic:{UID}",
                           model_id="M", model_version="1")
    assert binding.economic_node_id == "economic:AAPL"


def test_03b_cross_uid_binding_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        resolve_model_binding(
            model_evidence=_model(uid="EVIL"),
            r9_lineage={"economic_asset_uid": UID,
                        "economic_node_id": f"economic:{UID}"},
        )
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


# --------------------------------------------------------------------------
# 66.5-66.13: R9 lineage
# --------------------------------------------------------------------------

def test_05_r9_internal_digest_valid_passes():
    r9 = _r9_evidence()
    lineage = verify_r9_lineage(r9)
    assert lineage["economic_asset_uid"] == UID


def test_06_r9_internal_digest_invalid_fails():
    r9 = _r9_evidence()
    r9["economicAssetUid"] = "TAMPERED"  # bytes change, digest stale
    with pytest.raises(ModelRadarError) as excinfo:
        verify_r9_lineage(r9)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_07_full_r9_source_digest_reconstructed():
    r9 = _r9_evidence()
    lineage = verify_r9_lineage(r9)
    assert lineage["r9_source_digest"] == _digest(r9)
    snapshot = _bridge(r9, model=_model())
    assert (snapshot.source_digests["r9AssetGraphDigest"] == _digest(r9))


def test_08_r9_source_and_internal_digest_semantics_distinct():
    r9 = _r9_evidence()
    lineage = verify_r9_lineage(r9)
    assert lineage["r9_source_digest"] != lineage["r9_snapshot_digest"]
    snapshot = _bridge(r9, model=_model())
    assert (snapshot.source_digests["r9AssetGraphDigest"]
            != snapshot.source_digests["r9SnapshotDigest"])


def test_09_missing_economic_node_fails():
    r9 = _r9_evidence()
    r9["nodes"] = [n for n in r9["nodes"]
                   if n["nodeType"] != "ECONOMIC_ASSET"]
    _reseal_r9(r9)
    with pytest.raises(ModelRadarError) as excinfo:
        verify_r9_lineage(r9)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_10_duplicate_economic_node_fails():
    r9 = _r9_evidence()
    econ = next(n for n in r9["nodes"]
                if n["nodeType"] == "ECONOMIC_ASSET")
    r9["nodes"].append(copy.deepcopy(econ))
    _reseal_r9(r9)
    with pytest.raises(ModelRadarError) as excinfo:
        verify_r9_lineage(r9)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_11_model_uid_mismatch_fails():
    r9 = _r9_evidence()
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(uid="MSFT"))
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_12_model_economic_node_mismatch_fails():
    r9 = _r9_evidence()
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(economic_node_id="economic:WRONG"))
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_13_independently_valid_cross_asset_model_evidence_fails():
    """Spec 61 critical: BOTH sides are individually verifier-valid with
    freshly recomputed digests; only the semantic identity differs."""
    r9 = _r9_evidence()  # valid R9 for AAPL
    assert verify_r9_lineage(r9) is not None
    evil = _model(uid="EVIL")  # internally consistent model evidence
    assert evil.model_run_digest
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=evil)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


# --------------------------------------------------------------------------
# 66.14-66.16 + 67: model run digest semantics
# --------------------------------------------------------------------------

def test_14_model_run_digest_reconstructs():
    model = _model()
    assert model.model_run_digest == model._compute_run_digest()
    assert len(model.model_run_digest) == 64


def test_15_model_input_mutation_changes_digest():
    a = _model()
    b = _model(input_evidence={
        "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
        "cashFlows": ["-100", "120"], "dates": ["2026-01-01", "2027-01-01"],
        "currency": "USD", "economicScope": "unit:AAPL",
    })
    assert a.input_digest != b.input_digest
    assert a.model_run_digest != b.model_run_digest


def test_16_model_output_mutation_changes_digest():
    a = _model()
    b = _model(value=Decimal("110"))
    assert a.output_digest != b.output_digest
    assert a.model_run_digest != b.model_run_digest


def test_67_model_output_mutation_moves_digests_not_identity():
    r9_a, r9_b = _r9_evidence(**FULL), _r9_evidence(**FULL)
    snap_a = _bridge(r9_a, model=_model(value=Decimal("100")),
                     r8=_r8_evidence(exec_prices=EXEC_PRICES))
    snap_b = _bridge(r9_b, model=_model(value=Decimal("110")),
                     r8=_r8_evidence(exec_prices=EXEC_PRICES))
    # Economic binding identity unchanged ...
    assert snap_a.model_binding.binding_id == snap_b.model_binding.binding_id
    assert snap_a.economic_asset_uid == snap_b.economic_asset_uid
    assert snap_a.economic_node_id == snap_b.economic_node_id
    # ... model observation lineage moved.
    assert (snap_a.model_evidence.output_digest
            != snap_b.model_evidence.output_digest)
    assert (snap_a.model_evidence.model_run_digest
            != snap_b.model_evidence.model_run_digest)
    assert (snap_a.reference_comparison.reference_vs_model_bps
            != snap_b.reference_comparison.reference_vs_model_bps)
    assert snap_a.r10_snapshot_digest != snap_b.r10_snapshot_digest


# --------------------------------------------------------------------------
# 66.17-66.22 + 57: value kinds
# --------------------------------------------------------------------------

def test_17_value_kind_preserved():
    model = _model(value_kind=ModelValueKind.PROJECT_NPV_TOTAL,
                   unit_basis=ModelUnitBasis.TOTAL_PROJECT)
    snapshot = _bridge(_r9_evidence(), model=model)
    assert snapshot.model_evidence.value_kind is ModelValueKind.PROJECT_NPV_TOTAL
    assert snapshot.to_evidence_dict()["modelEvidence"]["valueKind"] == (
        "PROJECT_NPV_TOTAL")


def _not_comparable_gaps(snapshot):
    return {g.gap_kind for g in snapshot.gaps}


def test_18_xirr_non_price_comparable():
    snapshot = _bridge(_r9_evidence(), model=_model(
        value=Decimal("0.095"),
        value_kind=ModelValueKind.NON_PRICE_METRIC))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.VALUE_KIND_MISMATCH in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


def test_19_dscr_non_price_comparable():
    snapshot = _bridge(_r9_evidence(), model=_model(
        value=Decimal("1.4"), value_kind=ModelValueKind.NON_PRICE_METRIC,
        output_evidence={"metric": "DSCR", "value": "1.4"}))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert snapshot.reference_comparison is None
    assert snapshot.execution_comparisons == ()


def test_20_total_npv_not_automatically_per_unit():
    snapshot = _bridge(_r9_evidence(), model=_model(
        value=Decimal("1000000"),
        value_kind=ModelValueKind.PROJECT_NPV_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_PROJECT))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.MULTIPLIER_UNAVAILABLE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


def test_21_total_equity_vs_per_unit_blocked():
    snapshot = _bridge(_r9_evidence(), model=_model(
        value=Decimal("10000000"),
        value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_EQUITY))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert snapshot.reference_comparison is None


def test_22_enterprise_value_vs_per_unit_blocked():
    """Spec 57 critical: EV 10,000,000,000 USD vs 105 USD/share."""
    snapshot = _bridge(_r9_evidence(), model=_model(
        value=Decimal("10000000000"),
        value_kind=ModelValueKind.ENTERPRISE_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_ENTERPRISE))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.VALUE_KIND_MISMATCH in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


# --------------------------------------------------------------------------
# 66.23: the fully comparable synthetic path
# --------------------------------------------------------------------------

def test_23_same_unit_same_currency_comparable():
    r9 = _r9_evidence(**FULL)
    r8 = _r8_evidence(exec_prices=EXEC_PRICES)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_OK
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    assert snapshot.reference_comparison is not None
    assert len(snapshot.execution_comparisons) == 4
    assert snapshot.gaps == ()


# --------------------------------------------------------------------------
# 66.24-66.27 + 58: unit basis and multiplier
# --------------------------------------------------------------------------

def test_24_missing_unit_basis_unavailable_kind_exists():
    # The unit-basis vocabulary is a closed enum: a missing basis cannot be
    # constructed; the typed gap exists for upstream-absent authorities.
    assert ModelRadarGapKind.UNIT_BASIS_UNAVAILABLE.value == (
        "UNIT_BASIS_UNAVAILABLE")
    with pytest.raises(ModelRadarError):
        ModelEvidence(
            model_id="M", model_version="1", engine_authority="e",
            economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
            valuation_as_of=NOW, value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
            value=Decimal("1"), currency="USD", unit_basis=None,
            input_digest="i", output_digest="o",
        )


def test_58_total_project_vs_token_price_blocked():
    """Spec 58 critical: 1,000,000 USD TOTAL_PROJECT vs 1 USD/token world."""
    r9 = _r9_evidence(**FULL)
    snapshot = _bridge(r9, model=_model(
        value=Decimal("1000000"),
        value_kind=ModelValueKind.PROJECT_NPV_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_PROJECT))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert snapshot.reference_comparison is None
    # Never an assumed 1,000,000-token divisor anywhere in the evidence.
    assert "1000000" not in json.dumps(
        snapshot.to_evidence_dict()["referenceComparison"] or {})


def test_26_missing_multiplier_blocked_when_required():
    snapshot = _bridge(_r9_evidence(), model=_model(
        value=Decimal("1000000"),
        value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_EQUITY))
    assert ModelRadarGapKind.MULTIPLIER_UNAVAILABLE in _not_comparable_gaps(snapshot)


def test_27_exact_multiplier_applied_only_when_source_proven():
    r9 = _r9_evidence(**FULL)
    snapshot = _bridge(r9, model=_model(
        value=Decimal("1000000"),
        value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_EQUITY,
        unit_multiplier=Decimal("10000")))
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    per_unit = model_value_per_unit(snapshot.model_evidence)
    assert per_unit == Decimal("100")
    assert snapshot.reference_comparison.reference_vs_model_bps == Decimal("500")


# --------------------------------------------------------------------------
# 66.28-66.32 + 59: currency semantics
# --------------------------------------------------------------------------

def test_28_missing_currency_blocked():
    snapshot = _bridge(_r9_evidence(), model=_model(currency=""))
    assert ModelRadarGapKind.CURRENCY_UNAVAILABLE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


def test_29_currency_mismatch_blocked():
    snapshot = _bridge(_r9_evidence(), model=_model(currency="EUR"))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.CURRENCY_MISMATCH in _not_comparable_gaps(snapshot)


def test_30_no_implicit_fx():
    snapshot = _bridge(_r9_evidence(), model=_model(currency="EUR"))
    assert snapshot.reference_comparison is None
    blob = json.dumps(snapshot.to_evidence_dict())
    assert "fxRate" not in blob and "converted" not in blob.lower()


def test_31_no_stablecoin_usd_assumption():
    snapshot = _bridge(_r9_evidence(), model=_model(currency="USDC"))
    assert ModelRadarGapKind.CURRENCY_MISMATCH in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


def test_32_fx_authority_unavailable_typed():
    snapshot = _bridge(_r9_evidence(), model=_model(currency="EUR"))
    assert ModelRadarGapKind.FX_AUTHORITY_UNAVAILABLE in _not_comparable_gaps(snapshot)


# --------------------------------------------------------------------------
# 66.33-66.38 + 62: timing
# --------------------------------------------------------------------------

def test_33_valuation_timestamp_required():
    with pytest.raises(TypeError):
        ModelEvidence(
            model_id="M", model_version="1", engine_authority="e",
            economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
            value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
            value=Decimal("1"), currency="USD",
            unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            input_digest="i", output_digest="o",
        )


def test_34_naive_valuation_timestamp_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(valuation_as_of=datetime(2026, 9, 17, 12, 0))
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_TIMING_INVALID


def test_35_future_model_timestamp_fails():
    r9 = _r9_evidence()
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(
            valuation_as_of=NOW + timedelta(seconds=1)), now=NOW)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_TIMING_INVALID


def test_36_stale_model_unavailable_not_relabelled():
    r9 = _r9_evidence()
    snapshot = _bridge(r9, model=_model(
        value=Decimal("100"),
        valuation_as_of=NOW - timedelta(seconds=901)))
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL
    assert ModelRadarGapKind.MODEL_STALE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None
    # The stale value is preserved verbatim as evidence, never relabeled.
    assert snapshot.model_evidence.value == Decimal("100")


def _skewed_model(seconds: int):
    return _model(valuation_as_of=NOW - timedelta(seconds=seconds))


def test_37_skew_boundary_exact_passes():
    comparability = resolve_comparability(
        model_evidence=_skewed_model(300),
        market_context=MarketComparabilityContext(
            reference_price=Decimal("105"), reference_currency="USD",
            reference_source="R7", reference_observed_at=NOW),
        timing_policy=POLICY, now=NOW)
    timing = next(d for d in comparability.dimensions
                  if d.dimension is ComparabilityDimension.TIMING)
    assert timing.ok is True


def test_38_skew_boundary_plus_one_fails():
    comparability = resolve_comparability(
        model_evidence=_skewed_model(301),
        market_context=MarketComparabilityContext(
            reference_price=Decimal("105"), reference_currency="USD",
            reference_source="R7", reference_observed_at=NOW),
        timing_policy=POLICY, now=NOW)
    timing = next(d for d in comparability.dimensions
                  if d.dimension is ComparabilityDimension.TIMING)
    assert timing.ok is False
    assert timing.gap_kind is ModelRadarGapKind.TIMING_SKEW_INVALID


def test_62_timing_skew_not_comparable_end_to_end():
    r9 = _r9_evidence()
    snapshot = _bridge(r9, model=_skewed_model(301))
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.TIMING_SKEW_INVALID in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


# --------------------------------------------------------------------------
# 66.39-66.41 + 63: nonpositive model value
# --------------------------------------------------------------------------

def test_40_zero_model_value_no_division():
    r9 = _r9_evidence(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("0")))
    assert ModelRadarGapKind.MODEL_VALUE_NONPOSITIVE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None
    assert snapshot.execution_comparisons == ()


def test_41_negative_model_value_no_division():
    r9 = _r9_evidence(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("-5")))
    assert ModelRadarGapKind.MODEL_VALUE_NONPOSITIVE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


def test_39_positive_model_value_required_for_bps():
    with pytest.raises(ModelRadarError):
        compute_reference_comparison(
            model_value_per_unit=Decimal("0"),
            reference_price=Decimal("105"), reference_source="R7",
            model_observed_at=NOW, reference_observed_at=NOW)


# --------------------------------------------------------------------------
# 66.42-66.50: formulas and BUY/SELL semantics
# --------------------------------------------------------------------------

def test_42_reference_minus_model_formula_exact():
    comparison = compute_reference_comparison(
        model_value_per_unit=Decimal("100"),
        reference_price=Decimal("105"), reference_source="R7",
        model_observed_at=NOW, reference_observed_at=NOW)
    assert comparison.reference_minus_model_value == Decimal("5")


def test_43_reference_vs_model_bps_exact_decimal():
    comparison = compute_reference_comparison(
        model_value_per_unit=Decimal("100"),
        reference_price=Decimal("105"), reference_source="R7",
        model_observed_at=NOW, reference_observed_at=NOW)
    assert comparison.reference_vs_model_bps == Decimal("500")


def test_44_execution_minus_model_formula_exact():
    comparison = compute_execution_comparison(
        model_value_per_unit=Decimal("100"), execution_price=Decimal("108"),
        side="BUY", requested_notional_usd="100", quote_source=VENUE,
        r8_net_edge_state="COMPLETE", r8_scenario_index=0)
    assert comparison.execution_minus_model_value == Decimal("8")


def test_45_execution_vs_model_bps_exact_decimal():
    comparison = compute_execution_comparison(
        model_value_per_unit=Decimal("100"), execution_price=Decimal("108"),
        side="BUY", requested_notional_usd="100", quote_source=VENUE,
        r8_net_edge_state="COMPLETE", r8_scenario_index=0)
    assert comparison.execution_vs_model_bps == Decimal("800")


def _full_snapshot():
    return _bridge(
        _r9_evidence(**FULL), model=_model(value=Decimal("100")),
        r8=_r8_evidence(exec_prices=EXEC_PRICES))


def _exec(snapshot, side, notional):
    return next(c for c in snapshot.execution_comparisons
                if c.side == side and c.requested_notional_usd == notional)


def test_46_buy_sign_semantics_unchanged():
    snapshot = _full_snapshot()
    assert _exec(snapshot, "BUY", "100").execution_vs_model_bps == Decimal("800")
    assert _exec(snapshot, "BUY", "1000").execution_vs_model_bps == Decimal("1200")


def test_47_sell_sign_semantics_unchanged():
    snapshot = _full_snapshot()
    # SELL below model keeps the same negative deviation semantics.
    assert _exec(snapshot, "SELL", "1000").execution_vs_model_bps == Decimal("-200")
    assert _exec(snapshot, "SELL", "100").execution_vs_model_bps == Decimal("200")


def test_48_side_retained():
    snapshot = _full_snapshot()
    assert {c.side for c in snapshot.execution_comparisons} == {"BUY", "SELL"}


def test_49_requested_notional_retained():
    snapshot = _full_snapshot()
    assert {c.requested_notional_usd for c in snapshot.execution_comparisons} == {
        "100", "1000"}


def test_50_venue_retained():
    snapshot = _full_snapshot()
    assert {c.quote_source for c in snapshot.execution_comparisons} == {VENUE}


# --------------------------------------------------------------------------
# 66.51-66.54 + 64/65: R8 no-double-count and PARTIAL preservation
# --------------------------------------------------------------------------

def _mutated_r8(mutate):
    r8 = _r8_evidence(exec_prices=EXEC_PRICES)
    mutate(r8)
    _reseal_r8(r8)
    return r8


def test_51_r8_costs_not_deducted_again():
    base = _full_snapshot()
    r8 = _mutated_r8(lambda e: e["scenarios"][0]["providerCost"].__setitem__(
        "feeUsd", "999.00"))
    mutated = _bridge(_r9_evidence(**FULL), model=_model(value=Decimal("100")),
                      r8=r8)
    assert (_exec(base, "BUY", "100").execution_vs_model_bps
            == _exec(mutated, "BUY", "100").execution_vs_model_bps
            == Decimal("800"))
    blob = json.dumps(mutated.to_evidence_dict()["executionComparisons"])
    assert "providerCost" not in blob and "deduction" not in blob.lower()


def test_52_r8_settlement_not_deducted_again():
    base = _full_snapshot()
    r8 = _mutated_r8(lambda e: e["scenarios"][0]["settlementAdjustment"].__setitem__(
        "incrementalCostUsd", "50.00"))
    mutated = _bridge(_r9_evidence(**FULL), model=_model(value=Decimal("100")),
                      r8=r8)
    assert (_exec(base, "SELL", "100").execution_vs_model_bps
            == _exec(mutated, "SELL", "100").execution_vs_model_bps)


def test_53_r8_size_impact_not_deducted_again():
    base = _full_snapshot()
    r8 = _mutated_r8(lambda e: e["sizeSensitivity"][0].__setitem__(
        "grossEdgeChangeBps", "9999"))
    mutated = _bridge(_r9_evidence(**FULL), model=_model(value=Decimal("100")),
                      r8=r8)
    assert (_exec(base, "BUY", "1000").execution_vs_model_bps
            == _exec(mutated, "BUY", "1000").execution_vs_model_bps
            == Decimal("1200"))
    assert all("sizeImpact" not in c.to_evidence_dict()
               for c in mutated.execution_comparisons)


def test_54_r8_partial_stays_partial():
    r8 = _r8_evidence(exec_prices=EXEC_PRICES)
    r8["scenarios"][0]["netEdgeState"] = "PARTIAL"
    r8["scenarios"][0]["netEdgeBlockers"] = ["COST_TREATMENT_UNRESOLVED"]
    r8["scenarios"][0]["netExecutableEdgeBps"] = None
    _reseal_r8(r8)
    snapshot = _bridge(_r9_evidence(**FULL), model=_model(value=Decimal("100")),
                       r8=r8)
    comparison = next(c for c in snapshot.execution_comparisons
                      if c.r8_scenario_index == 0)
    assert comparison.r8_net_edge_state == "PARTIAL"
    assert comparison.execution_vs_model_bps == Decimal("800")


# --------------------------------------------------------------------------
# 66.55-66.57 + 39: model never replaces reference/zero/last-known
# --------------------------------------------------------------------------

def test_55_model_does_not_replace_missing_reference():
    r7 = _rich_r7()
    r7["layers"]["oracleReference"] = None
    r7["r7SnapshotDigest"] = _digest(
        {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
    r8 = _r8_evidence()
    r8["upstreamEvidence"]["r7CrossMarketEvidence"] = r7
    r8["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    _reseal_r8(r8)
    r9 = build_r9_evidence(r8_evidence=r8, git_head="t",
                           generated_at=datetime(2026, 9, 17, 11, 0, tzinfo=T))
    snapshot = _bridge(r9, model=_model(value=Decimal("100")),
                       r8=_r8_evidence(exec_prices=EXEC_PRICES))
    assert ModelRadarGapKind.REFERENCE_UNAVAILABLE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


def test_56_model_unavailable_does_not_become_zero():
    snapshot = _bridge(_r9_evidence())
    assert snapshot.model_evidence is None
    assert snapshot.to_evidence_dict()["modelEvidence"] is None
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


def test_57_model_unavailable_not_last_known_current():
    snapshot = _bridge(_r9_evidence())
    blob = json.dumps(snapshot.to_evidence_dict()).lower()
    assert "lastknown" not in blob and "last_known" not in blob
    assert snapshot.to_evidence_dict()["referenceComparison"] is None


def test_58b_live_no_binding_path_becomes_partial():
    snapshot = _bridge(_r9_evidence())
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL
    assert ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE in _not_comparable_gaps(snapshot)
    assert snapshot.execution_comparisons == ()


def test_59_synthetic_fully_comparable_path_works():
    snapshot = _full_snapshot()
    assert snapshot.synthetic is True
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_OK
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    assert snapshot.reference_comparison.reference_vs_model_bps == Decimal("500")
    assert len(snapshot.execution_comparisons) == 4


def test_binding_unavailable_discovery_typed():
    evidence, gap = discover_model_binding(UID)
    assert evidence is None
    assert gap.gap_kind is ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE


def test_model_authority_inventory_declared():
    assert "xnpv" in MODEL_AUTHORITY_INVENTORY
    assert "xirr" in MODEL_AUTHORITY_INVENTORY
    assert all(v.startswith(("finco_core.", "financial_engine."))
               for v in MODEL_AUTHORITY_INVENTORY.values())


# --------------------------------------------------------------------------
# 66.60-66.62: immutability
# --------------------------------------------------------------------------

def test_60_caller_mutation_isolation():
    r9 = _r9_evidence(**FULL)
    model = _model()
    snapshot = _bridge(r9, model=model, r8=_r8_evidence(exec_prices=EXEC_PRICES))
    expected = snapshot.to_evidence_dict()
    r9["economicAssetUid"] = "MUTATED"
    model_input = dict(model.input_evidence)
    model_input["cashFlows"] = ["hacked"]
    snapshot.model_evidence.input_evidence["cashFlows"]
    assert snapshot.to_evidence_dict() == expected


def test_61_nested_immutability():
    snapshot = _full_snapshot()
    with pytest.raises(TypeError):
        snapshot.upstream_evidence["r9AssetGraphEvidence"]["economicAssetUid"] = "X"
    with pytest.raises(TypeError):
        snapshot.boundaries["modelAuthority"] = "R99_APPLIED"


def test_62b_serialized_copy_mutation_isolation():
    snapshot = _full_snapshot()
    first = snapshot.to_evidence_dict()
    first["gaps"].append({"hacked": True})
    first["economicAssetUid"] = "MUT"
    second = snapshot.to_evidence_dict()
    assert second["gaps"] == []
    assert second["economicAssetUid"] == UID
    assert verify_r10_snapshot_digest(snapshot) is True


# --------------------------------------------------------------------------
# 66.63-66.65: determinism
# --------------------------------------------------------------------------

def test_63_execution_ordering_deterministic():
    r8 = _r8_evidence(exec_prices=EXEC_PRICES)
    r8["scenarios"] = list(reversed(r8["scenarios"]))
    _reseal_r8(r8)
    r9 = build_r9_evidence(r8_evidence=r8, git_head="t",
                           generated_at=datetime(2026, 9, 17, 11, 0, tzinfo=T))
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    keys = [(c.side, Decimal(c.requested_notional_usd), c.quote_source)
            for c in snapshot.execution_comparisons]
    assert keys == sorted(keys)
    assert len(keys) == 4


def test_64_reordered_equivalent_inputs_same_digest():
    a = _model(input_evidence={"a": "1", "b": "2"})
    b = _model(input_evidence={"b": "2", "a": "1"})
    assert a.model_run_digest == b.model_run_digest
    snap_a = _bridge(_r9_evidence(**FULL), model=a,
                     r8=_r8_evidence(exec_prices=EXEC_PRICES))
    snap_b = _bridge(_r9_evidence(**FULL), model=b,
                     r8=_r8_evidence(exec_prices=EXEC_PRICES))
    assert snap_a.r10_snapshot_digest == snap_b.r10_snapshot_digest


def test_65_semantic_mutation_breaks_r10_digest():
    snap_a = _full_snapshot()
    r9_b = _r9_evidence(oracle_price="106", exec_prices=EXEC_PRICES)
    snap_b = _bridge(r9_b, model=_model(value=Decimal("100")),
                     r8=_r8_evidence(exec_prices=EXEC_PRICES))
    assert snap_a.r10_snapshot_digest != snap_b.r10_snapshot_digest


# --------------------------------------------------------------------------
# 66.66-66.69 + 45/74/75/76: digests, boundaries, phase claims
# --------------------------------------------------------------------------

def test_66_source_digests_present_and_distinct():
    snapshot = _full_snapshot()
    digests = snapshot.source_digests
    for name in ("r9AssetGraphDigest", "r9SnapshotDigest",
                 "r8ExecutionSimulatorDigest", "r8SnapshotDigest",
                 "modelInputDigest", "modelOutputDigest",
                 "modelRunDigest"):
        assert digests.get(name), name
    assert digests["r9AssetGraphDigest"] != digests["r9SnapshotDigest"]
    assert digests["r8ExecutionSimulatorDigest"] != digests["r8SnapshotDigest"]


def test_66b_r10_digest_reconstructs_serialized():
    snapshot = _full_snapshot()
    evidence = snapshot.to_evidence_dict()
    assert verify_serialized_r10_evidence(evidence) is True
    material = {k: v for k, v in evidence.items() if k != "r10SnapshotDigest"}
    assert snapshot.r10_snapshot_digest == _digest(material)
    evidence["status"] = "TAMPERED"
    assert verify_serialized_r10_evidence(evidence) is False


def test_67b_boundaries_correct():
    snapshot = _full_snapshot()
    b = snapshot.boundaries
    assert b["modelAuthority"] == "R10_APPLIED"
    assert b["verificationAuthority"] == "R11_NOT_YET_APPLIED"
    assert b["digitalTwinAuthority"] == "R12_NOT_YET_APPLIED"
    assert b["assetGraphAuthority"] == "R9_APPLIED"


def test_68_no_r11_attestation_claims():
    blob = json.dumps(_full_snapshot().to_evidence_dict()).lower()
    for phrase in ("attestation", "notarization", "on-chain proof",
                   "proof of truth", "verification protocol"):
        assert phrase not in blob, phrase


def test_69_no_r12_digital_twin_claims():
    blob = json.dumps(_full_snapshot().to_evidence_dict()).lower()
    for phrase in ("event bus", "autonomous refresh", "streaming updates",
                   "agent subscription", "digital twin state"):
        assert phrase not in blob, phrase


# --------------------------------------------------------------------------
# 66.70-66.71 + 55/56: no recommendation/score language
# --------------------------------------------------------------------------

FORBIDDEN_VALUES = (
    "undervalued", "overvalued", "price target", "target price", "upside",
    "downside", "expected return", "alpha", "guaranteed profit",
    "risk-free", "certain arbitrage", "conviction",
)


def test_70_no_recommendation_fields():
    snapshot = _full_snapshot()
    evidence = snapshot.to_evidence_dict()
    blob = json.dumps(evidence).lower()
    for phrase in FORBIDDEN_VALUES:
        assert phrase not in blob, phrase
    assert snapshot.reference_comparison.to_evidence_dict()[
        "semantics"].startswith("descriptive deviation")


def test_71_no_score_or_rank_fields():
    evidence = _full_snapshot().to_evidence_dict()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = key.lower()
                assert "score" not in lowered, key
                assert "rank" not in lowered, key
                assert "rating" not in lowered, key
                assert "stars" not in lowered, key
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(evidence)


def test_70b_neutral_comparison_field_names():
    evidence = _full_snapshot().to_evidence_dict()
    assert "referenceVsModelBps" in evidence["referenceComparison"]
    assert "referenceMinusModelValue" in evidence["referenceComparison"]
    for key in ("upside", "downside", "profit", "mispricingScore"):
        assert key not in json.dumps(evidence)


# --------------------------------------------------------------------------
# 15: float-boundary conversion
# --------------------------------------------------------------------------

def test_decimal_from_authority_float_uses_text_representation():
    assert decimal_from_authority(0.1) == Decimal("0.1")
    assert decimal_from_authority(0.1) == Decimal(repr(0.1))
    assert decimal_from_authority(5) == Decimal("5")
    assert decimal_from_authority("12.34") == Decimal("12.34")
    with pytest.raises(ModelRadarError):
        decimal_from_authority(float("inf"))
    with pytest.raises(ModelRadarError):
        decimal_from_authority(float("nan"))
    with pytest.raises(ModelRadarError):
        decimal_from_authority(True)
    with pytest.raises(ModelRadarError):
        decimal_from_authority(None)


def test_float_authority_recorded_verbatim():
    model = _model()
    model_dict = _bridge(_r9_evidence(), model=model).to_evidence_dict()
    assert model_dict["modelEvidence"][
        "valueOriginalRepresentation"] == str(Decimal("100"))


# --------------------------------------------------------------------------
# 43/44/46: schema, phase, schema version, verify helper
# --------------------------------------------------------------------------

def test_schema_version_and_phase():
    snapshot = _full_snapshot()
    evidence = snapshot.to_evidence_dict()
    assert evidence["schemaVersion"] == SCHEMA_VERSION == (
        "radar-r10-model-radar-v1")
    assert evidence["phase"] == PHASE == "R10"


def test_no_binding_snapshot_shape():
    evidence = _bridge(_r9_evidence()).to_evidence_dict()
    for key in ("schemaVersion", "phase", "status", "generatedAt", "gitHead",
                "economicAssetUid", "economicNodeId", "canonicalAssetKey",
                "modelBinding", "modelEvidence", "comparability",
                "referenceComparison", "executionComparisons", "gaps",
                "sourceDigests", "upstreamEvidence", "boundaries",
                "timingPolicy", "r10SnapshotDigest"):
        assert key in evidence, key
    assert evidence["modelBinding"] is None
    assert evidence["modelEvidence"] is None
    assert evidence["referenceComparison"] is None
    assert evidence["executionComparisons"] == []


def test_economic_node_and_key_in_snapshot():
    snapshot = _full_snapshot()
    assert snapshot.economic_node_id == "economic:AAPL"
    assert snapshot.canonical_asset_key["chainId"] == 4663


def test_live_chain_embeds_r9_evidence_verbatim():
    r9 = _r9_evidence(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")),
                       r8=_r8_evidence(exec_prices=EXEC_PRICES))
    embedded = snapshot.to_evidence_dict()["upstreamEvidence"][
        "r9AssetGraphEvidence"]
    assert embedded == json.loads(json.dumps(r9))

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
    discover_model_evidence,
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
    datetime_from_evidence,
    decimal_from_authority,
    SCHEMA_VERSION,
    ComparabilityDimension,
    ComparabilityDimensionResult,
    ComparabilityState,
    ModelBinding,
    ModelComparability,
    ModelEvidence,
    ModelRadarError,
    ModelRadarGap,
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

def _rich_r7(uid=UID, key=KEY, oracle_price="105",
             oracle_multiplier="1", token_multiplier="1",
             oracle_currency="USD"):
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
                "price": str(oracle_price), "currency": oracle_currency,
                "observedAt": NOW.isoformat(), "instrument": uid,
                "multiplier": oracle_multiplier, "usable": True,
                "assetUid": uid,
                "assetKey": f"{key.chain_id}:{key.contract_address}",
            },
            "externalOracle": None,
            "token": {
                "economicAssetUid": uid, "chainId": key.chain_id,
                "contractAddress": key.contract_address, "symbol": uid,
                "multiplier": token_multiplier,
                "representationStatus": "ACTIVE",
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
        "synthetic": True,
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


def _r8_scenario(side, notional, uid=UID, key=KEY):
    return ExecutionScenario(
        economic_asset_uid=uid, canonical_asset_key=key, side=side,
        requested_notional_usd=Decimal(notional), quote_source=VENUE,
        execution_mode=ExecutionMode.REFERENCE_RELATIVE,
        r7_component_label=f"ORACLE_REFERENCE→VENUE[DEX:{side.value}:{notional}]",
        as_of=NOW,
    )


def _r8_evidence(uid=UID, key=KEY, exec_prices=None, oracle_price="105",
                 oracle_multiplier="1", token_multiplier="1",
                 oracle_currency="USD"):
    r7 = _rich_r7(uid=uid, key=key, oracle_price=oracle_price,
                  oracle_multiplier=oracle_multiplier,
                  token_multiplier=token_multiplier,
                  oracle_currency=oracle_currency)
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
        scenarios.append(_r8_scenario(side, notional, uid, key))
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


def _chain(uid=UID, key=KEY, oracle_price="105", exec_prices=None,
           mutate_r8=None, oracle_multiplier="1", token_multiplier="1",
           oracle_currency="USD"):
    """Build ONE deterministic R8 evidence, optionally mutate it (resealing
    required), then derive the R9 evidence from exactly that R8 — so the F3
    canonical binding between supplied and embedded R8 always holds."""
    r8 = _r8_evidence(uid=uid, key=key, exec_prices=exec_prices,
                      oracle_price=oracle_price,
                      oracle_multiplier=oracle_multiplier,
                      token_multiplier=token_multiplier,
                      oracle_currency=oracle_currency)
    if mutate_r8 is not None:
        mutate_r8(r8)
        _reseal_r8(r8)
    r9 = build_r9_evidence(r8_evidence=r8, git_head="test-head",
                           generated_at=datetime(2026, 9, 17, 11, 0, tzinfo=T))
    return r9, r8


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
    """Synthetic fixture builder.  The fixture models a WELL-FORMED source:
    the output observation carries the authoritative valuationAsOf and the
    input (policy) record carries unitMultiplier/unitMultiplierBasis
    whenever a multiplier is declared.  Production validation is NOT
    weakened - adversarial tests construct ModelEvidence directly."""
    uid = over.pop("uid", UID)
    value = over.pop("value", Decimal("100"))
    kind = over.pop("value_kind", ModelValueKind.VALUE_PER_ECONOMIC_UNIT)
    currency = over.pop("currency", "USD")
    basis = over.pop("unit_basis", ModelUnitBasis.PER_ECONOMIC_UNIT)
    multiplier = over.pop("unit_multiplier", None)
    multiplier_basis = over.pop("unit_multiplier_basis", None)
    valuation_as_of = over.pop("valuation_as_of", NOW)
    input_evidence = over.pop("input_evidence", {
        "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
        "cashFlows": ["-100", "110"], "dates": ["2026-01-01", "2027-01-01"],
        "currency": "USD", "economicScope": f"unit:{uid}",
    })
    if multiplier is not None and multiplier_basis is not None:
        input_evidence = dict(input_evidence)
        input_evidence.setdefault("unitMultiplier", str(multiplier))
        input_evidence.setdefault(
            "unitMultiplierBasis", multiplier_basis.value)
    output_evidence = over.pop("output_evidence", {
        "valueKind": kind.value, "value": str(value),
        "currency": currency, "unitBasis": basis.value,
        "valuationAsOf": valuation_as_of.isoformat(),
    })
    return ModelEvidence(
        model_id=over.pop("model_id", "FINCO-SYNTH-PROJECT-MODEL"),
        model_version=over.pop("model_version", "1.0.0"),
        engine_authority=over.pop(
            "engine_authority", "financial_engine.orchestrator"),
        economic_asset_uid=uid,
        economic_node_id=over.pop("economic_node_id", f"economic:{uid}"),
        valuation_as_of=valuation_as_of,
        value_kind=kind,
        value=value,
        currency=currency,
        unit_basis=basis,
        input_digest=digest_payload(input_evidence),
        output_digest=digest_payload(output_evidence),
        input_evidence=input_evidence,
        output_evidence=output_evidence,
        unit_multiplier=multiplier,
        unit_multiplier_basis=multiplier_basis,
        synthetic=over.pop("synthetic", True),
    )


def _bridge(r9, model=None, r8=None, *, now=NOW, synthetic=True):
    return build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8, model_evidence=model,
        timing_policy=POLICY, now=now, git_head="test-head",
        synthetic=synthetic,
    )


FULL = dict(oracle_price="105", exec_prices=EXEC_PRICES)


def _live_chain(**over):
    """A fully NON-synthetic-marked causal chain: the R8 engine output and
    its embedded R7 lineage are flipped to synthetic=False with all internal
    digests resealed, then R9 is derived from exactly that chain."""
    def _non_synth(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["synthetic"] = False
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
        e["synthetic"] = False
    return _chain(mutate_r8=_non_synth, **over)


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
                                  output_evidence={"symbol": UID,
                                                   "value": "100",
                                                   "valueKind": "VALUE_PER_ECONOMIC_UNIT",
                                                   "currency": "USD",
                                                   "unitBasis": "PER_ECONOMIC_UNIT",
                                                   "valuationAsOf": NOW.isoformat()}),
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
        currency="USD", unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
        output_evidence={"metric": "DSCR", "value": "1.4",
                         "valueKind": "NON_PRICE_METRIC", "currency": "USD",
                         "unitBasis": "PER_ECONOMIC_UNIT",
                         "valuationAsOf": NOW.isoformat()}))
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
    r9, r8 = _chain(**FULL)
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
        unit_multiplier=Decimal("10000"),
        unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT))
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
    r9, r8 = _chain(**FULL)
    return _bridge(r9, model=_model(value=Decimal("100")), r8=r8)


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

def test_51_r8_costs_not_deducted_again():
    base = _full_snapshot()
    r9_m, r8_m = _chain(**FULL, mutate_r8=lambda e: e["scenarios"][0][
        "providerCost"].__setitem__("feeUsd", "999.00"))
    mutated = _bridge(r9_m, model=_model(value=Decimal("100")), r8=r8_m)
    assert (_exec(base, "BUY", "100").execution_vs_model_bps
            == _exec(mutated, "BUY", "100").execution_vs_model_bps
            == Decimal("800"))
    blob = json.dumps(mutated.to_evidence_dict()["executionComparisons"])
    assert "providerCost" not in blob and "deduction" not in blob.lower()


def test_52_r8_settlement_not_deducted_again():
    base = _full_snapshot()
    r9_m, r8_m = _chain(**FULL, mutate_r8=lambda e: e["scenarios"][0][
        "settlementAdjustment"].__setitem__("incrementalCostUsd", "50.00"))
    mutated = _bridge(r9_m, model=_model(value=Decimal("100")), r8=r8_m)
    assert (_exec(base, "SELL", "100").execution_vs_model_bps
            == _exec(mutated, "SELL", "100").execution_vs_model_bps)


def test_53_r8_size_impact_not_deducted_again():
    base = _full_snapshot()
    def _size(e):
        e["sizeSensitivity"][0]["grossEdgeChangeBps"] = "9999"
    r9_m, r8_m = _chain(**FULL, mutate_r8=_size)
    mutated = _bridge(r9_m, model=_model(value=Decimal("100")), r8=r8_m)
    assert (_exec(base, "BUY", "1000").execution_vs_model_bps
            == _exec(mutated, "BUY", "1000").execution_vs_model_bps
            == Decimal("1200"))
    assert all("sizeImpact" not in c.to_evidence_dict()
               for c in mutated.execution_comparisons)


def test_54_r8_partial_stays_partial():
    def _partial(e):
        e["scenarios"][0]["netEdgeState"] = "PARTIAL"
        e["scenarios"][0]["netEdgeBlockers"] = ["COST_TREATMENT_UNRESOLVED"]
        e["scenarios"][0]["netExecutableEdgeBps"] = None
    r9, r8 = _chain(**FULL, mutate_r8=_partial)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    comparison = next(c for c in snapshot.execution_comparisons
                      if c.r8_scenario_index == 0)
    assert comparison.r8_net_edge_state == "PARTIAL"
    assert comparison.execution_vs_model_bps == Decimal("800")


# --------------------------------------------------------------------------
# 66.55-66.57 + 39: model never replaces reference/zero/last-known
# --------------------------------------------------------------------------

def test_55_model_does_not_replace_missing_reference():
    def _no_oracle(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"] = None
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    r9, r8 = _chain(mutate_r8=_no_oracle)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
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


def test_f7a_discovery_returns_evidence_not_binding():
    # F7a: discovery yields MODEL EVIDENCE (or a typed gap); the binding is
    # resolved separately through resolve_model_binding.
    evidence, gap = discover_model_evidence(UID)
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
    r9, r8 = _chain(**FULL, mutate_r8=lambda e: e.__setitem__(
        "scenarios", list(reversed(e["scenarios"]))))
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    keys = [(c.side, Decimal(c.requested_notional_usd), c.quote_source)
            for c in snapshot.execution_comparisons]
    assert keys == sorted(keys)
    assert len(keys) == 4


def test_64_reordered_equivalent_inputs_same_digest():
    a = _model(input_evidence={"a": "1", "b": "2"})
    b = _model(input_evidence={"b": "2", "a": "1"})
    assert a.model_run_digest == b.model_run_digest
    r9, r8 = _chain(**FULL)
    snap_a = _bridge(r9, model=a, r8=r8)
    snap_b = _bridge(r9, model=b, r8=r8)
    assert snap_a.r10_snapshot_digest == snap_b.r10_snapshot_digest


def test_65_semantic_mutation_breaks_r10_digest():
    snap_a = _full_snapshot()
    r9_b, r8_b = _chain(oracle_price="106", exec_prices=EXEC_PRICES)
    snap_b = _bridge(r9_b, model=_model(value=Decimal("100")), r8=r8_b)
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


# --------------------------------------------------------------------------
# Correction A - F1: no total-value -> market-price bridge
# --------------------------------------------------------------------------

def _no_reference_comparison(snapshot):
    return snapshot.reference_comparison is None


def test_ca_f1_01_enterprise_value_never_comparable_even_with_multiplier():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(
        value=Decimal("10000000000"),
        value_kind=ModelValueKind.ENTERPRISE_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_ENTERPRISE,
        unit_multiplier=Decimal("100000000"),
        unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.VALUE_KIND_MISMATCH in _not_comparable_gaps(snapshot)


def test_ca_f1_02_project_npv_never_comparable_even_with_multiplier():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(
        value=Decimal("1000000"),
        value_kind=ModelValueKind.PROJECT_NPV_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_PROJECT,
        unit_multiplier=Decimal("1000000"),
        unit_multiplier_basis=ModelUnitBasis.PER_TOKEN_CLAIM), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.VALUE_KIND_MISMATCH in _not_comparable_gaps(snapshot)


def test_ca_f1_03_and_04_no_comparisons_from_total_bridges():
    r9, r8 = _chain(**FULL)
    for kind, basis in (
        (ModelValueKind.ENTERPRISE_VALUE_TOTAL, ModelUnitBasis.TOTAL_ENTERPRISE),
        (ModelValueKind.PROJECT_NPV_TOTAL, ModelUnitBasis.TOTAL_PROJECT),
    ):
        snapshot = _bridge(r9, model=_model(
            value=Decimal("7777"), value_kind=kind, unit_basis=basis,
            unit_multiplier=Decimal("7"),
            unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT), r8=r8)
        assert snapshot.reference_comparison is None
        assert snapshot.execution_comparisons == ()


def test_ca_f1_05_no_ev_npv_transformation_anywhere_in_evidence():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(
        value=Decimal("10000000000"),
        value_kind=ModelValueKind.ENTERPRISE_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_ENTERPRISE,
        unit_multiplier=Decimal("100000000"),
        unit_multiplier_basis=ModelUnitBasis.PER_SHARE), r8=r8)
    blob = json.dumps(snapshot.to_evidence_dict()).lower()
    for phrase in ("pershareequivalent", "per_share_equivalent",
                   "normalizedvalue", "equitybridge", "netdebt", "sharecount",
                   "tokensupply"):
        assert phrase not in blob, phrase


def test_ca_f1_06_nav_fails_closed_even_with_multiplier():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(
        value=Decimal("500000"),
        value_kind=ModelValueKind.NAV_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_EQUITY,
        unit_multiplier=Decimal("5000"),
        unit_multiplier_basis=ModelUnitBasis.PER_SHARE), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert snapshot.reference_comparison is None


def test_ca_f1_07_equity_without_declared_basis_fails():
    r9, r8 = _chain(**FULL)
    with pytest.raises(ModelRadarError):
        _model(value=Decimal("1000000"),
               value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               unit_multiplier=Decimal("10000"))


# --------------------------------------------------------------------------
# Correction A - F2: explicit market-unit / token-claim authority
# --------------------------------------------------------------------------

def test_ca_f2_01_conversion_multiplier_applied_exactly_once():
    r9, r8 = _chain(**FULL, oracle_multiplier="2", token_multiplier="2")
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    # per-unit 100 x frozen multiplier 2 = 200 per token claim, once.
    assert snapshot.reference_comparison.model_value == Decimal("200")
    assert snapshot.reference_comparison.reference_vs_model_bps == (
        (Decimal("105") / Decimal("200") - 1) * 10000)
    buy100 = _exec(snapshot, "BUY", "100")
    assert buy100.model_value == Decimal("200")
    assert buy100.execution_vs_model_bps == (
        (Decimal("108") / Decimal("200") - 1) * 10000)


def test_ca_f2_02_raw_per_unit_value_never_directly_compared():
    r9, r8 = _chain(**FULL, oracle_multiplier=None, token_multiplier=None)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.MULTIPLIER_UNAVAILABLE in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None
    assert snapshot.execution_comparisons == ()


def test_ca_f2_03_missing_market_multiplier_fails_closed():
    snapshot = _bridge(_r9_evidence(), model=_model(value=Decimal("100")))
    # default fixture has multipliers; force-missing via no-oracle chain is
    # covered by test_55; here assert the default context DOES carry them.
    assert snapshot.comparability is not None


def test_ca_f2_04_disagreeing_oracle_token_multipliers_fail_closed():
    r9, r8 = _chain(**FULL, oracle_multiplier="2", token_multiplier="3")
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.NOT_COMPARABLE
    assert ModelRadarGapKind.UNIT_BASIS_MISMATCH in _not_comparable_gaps(snapshot)
    assert snapshot.reference_comparison is None


def test_ca_f2_05_multiplier_mutation_moves_digest():
    r9_a, r8_a = _chain(**FULL, oracle_multiplier="1", token_multiplier="1")
    r9_b, r8_b = _chain(**FULL, oracle_multiplier="2", token_multiplier="2")
    snap_a = _bridge(r9_a, model=_model(value=Decimal("100")), r8=r8_a)
    snap_b = _bridge(r9_b, model=_model(value=Decimal("100")), r8=r8_b)
    assert (snap_a.reference_comparison.reference_vs_model_bps
            != snap_b.reference_comparison.reference_vs_model_bps)
    assert snap_a.r10_snapshot_digest != snap_b.r10_snapshot_digest


def test_ca_f2_06_no_implicit_one_multiplier_path():
    from finco_radar.model_radar.comparisons import MarketComparabilityContext
    context = MarketComparabilityContext(
        reference_price=Decimal("105"), reference_currency="USD",
        reference_source="R7", reference_observed_at=NOW)
    assert context.conversion_multiplier is None
    assert context.token_multiplier is None
    model = _model(value=Decimal("100"))
    comparability = resolve_comparability(
        model_evidence=model, market_context=context,
        timing_policy=POLICY, now=NOW)
    assert comparability.state is ComparabilityState.NOT_COMPARABLE
    multiplier = next(d for d in comparability.dimensions
                      if d.dimension is ComparabilityDimension.MULTIPLIER)
    assert multiplier.ok is False


def test_ca_f2_07_token_claim_model_compares_directly():
    r9, r8 = _chain(**FULL, oracle_multiplier="2", token_multiplier="2")
    snapshot = _bridge(r9, model=_model(
        value=Decimal("105"),
        unit_basis=ModelUnitBasis.PER_TOKEN_CLAIM), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    # Direct same-basis comparison: NO multiplier application (105 not 210).
    assert snapshot.reference_comparison.model_value == Decimal("105")
    assert snapshot.reference_comparison.reference_vs_model_bps == Decimal("0")


# --------------------------------------------------------------------------
# Correction A - F3: causal R8<->R9 binding
# --------------------------------------------------------------------------

def test_ca_f3_01_independent_valid_r8_rejected():
    r9_a, _ = _chain(**FULL)
    r8_other, _ = _chain(oracle_price="106", exec_prices=EXEC_PRICES)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9_a, model=_model(value=Decimal("100")), r8=r8_other)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_ca_f3_02_same_uid_different_execution_state_rejected():
    r9_a, _ = _chain(**FULL)

    def _flip(e):
        e["scenarios"][0]["netEdgeState"] = "PARTIAL"
        e["scenarios"][0]["netEdgeBlockers"] = ["COST_TREATMENT_UNRESOLVED"]
        e["scenarios"][0]["netExecutableEdgeBps"] = None
    r8_mutated, _ = _chain(**FULL, mutate_r8=_flip)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9_a, model=_model(value=Decimal("100")), r8=r8_mutated)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_ca_f3_03_same_uid_different_deployment_rejected():
    r9, _ = _chain(**FULL)

    def _other_key(e):
        e["canonicalAssetKey"] = {"chainId": 137,
                                  "contractAddress": "0x" + "bb" * 20}
        for scenario in e["scenarios"]:
            scenario["scenario"]["contractAddress"] = "0x" + "bb" * 20
    r8_other = _r8_evidence(exec_prices=EXEC_PRICES)
    _other_key(r8_other)
    _reseal_r8(r8_other)
    # Swap the embedded R8 inside the derived R9 (resealed): the R8 is
    # internally digest-valid but points at another deployment while the R9
    # graph still records the original one - semantic rejection.
    r9_bad = copy.deepcopy(r9)
    r9_bad["upstreamEvidence"]["r8ExecutionEvidence"] = r8_other
    _reseal_r9(r9_bad)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9_bad, model=_model(value=Decimal("100")))
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


def test_ca_f3_04_exact_embedded_r8_passes_without_explicit_argument():
    r9, _ = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")))
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_OK
    assert len(snapshot.execution_comparisons) == 4


def test_ca_f3_05_reordered_supplied_r8_cannot_bypass_binding():
    r9_a, _ = _chain(**FULL)

    def _reverse(e):
        e["scenarios"] = list(reversed(e["scenarios"]))
    _, r8_reordered = _chain(**FULL, mutate_r8=_reverse)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9_a, model=_model(value=Decimal("100")), r8=r8_reordered)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH


# --------------------------------------------------------------------------
# Correction A - F4: self-verifying model digests
# --------------------------------------------------------------------------

def _stale_input_model():
    input_evidence = {"cashFlows": ["-100", "110"]}
    return ModelEvidence(
        model_id="M", model_version="1",
        engine_authority="financial_engine.orchestrator",
        economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
        valuation_as_of=NOW,
        value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
        value=Decimal("100"), currency="USD",
        unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
        input_digest=digest_payload(input_evidence),
        output_digest=digest_payload({
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat()}),
        input_evidence=input_evidence,
        output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat()},
        synthetic=True,
    )


def test_ca_f4_01_mutated_input_evidence_stale_digest_rejected():
    model = _stale_input_model()
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(
            **{**model.__dict__, "input_evidence": {"cashFlows": ["hacked"]}})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_f4_02_mutated_output_evidence_stale_digest_rejected():
    model = _stale_input_model()
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(
            **{**model.__dict__, "output_evidence": {
                "value": "999", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
                "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
                "valuationAsOf": NOW.isoformat()}})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_f4_03_forged_input_digest_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(
            model_id="M", model_version="1", engine_authority="e",
            economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
            valuation_as_of=NOW,
            value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
            value=Decimal("100"), currency="USD",
            unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            input_digest="f" * 64, output_digest=digest_payload({"v": "1"}),
            input_evidence={"a": "1"}, output_evidence={"v": "1"},
            synthetic=True)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_f4_04_forged_output_digest_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(
            model_id="M", model_version="1", engine_authority="e",
            economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
            valuation_as_of=NOW,
            value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
            value=Decimal("100"), currency="USD",
            unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            input_digest=digest_payload({"a": "1"}),
            output_digest="0" * 64,
            input_evidence={"a": "1"}, output_evidence={"v": "1"},
            synthetic=True)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_f4_05_forged_run_digest_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(
            model_id="M", model_version="1", engine_authority="e",
            economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
            valuation_as_of=NOW,
            value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
            value=Decimal("100"), currency="USD",
            unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            input_digest=digest_payload({"a": "1"}),
            output_digest=digest_payload({"v": "1"}),
            model_run_digest="e" * 64,
            input_evidence={"a": "1"}, output_evidence={"v": "1"},
            synthetic=True)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_f4_06_malformed_digest_strings_rejected():
    base = dict(
        model_id="M", model_version="1", engine_authority="e",
        economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
        valuation_as_of=NOW,
        value_kind=ModelValueKind.VALUE_PER_ECONOMIC_UNIT,
        value=Decimal("100"), currency="USD",
        unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
        input_evidence={"a": "1"}, output_evidence={"v": "1"},
        synthetic=True)
    for field, bad in (("input_digest", "short"), ("output_digest", "z" * 64)):
        kwargs = dict(base)
        kwargs["input_digest"] = digest_payload({"a": "1"})
        kwargs["output_digest"] = digest_payload({"v": "1"})
        kwargs[field] = bad
        with pytest.raises(ModelRadarError) as excinfo:
            ModelEvidence(**kwargs)
        assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


# --------------------------------------------------------------------------
# Correction A - F5: exactly seven comparability dimensions
# --------------------------------------------------------------------------

SEVEN = {d for d in ComparabilityDimension}


def _dims(snapshot):
    return snapshot.comparability.dimensions


def test_ca_f5_01_comparable_state_exact_seven_unique():
    dims = _dims(_full_snapshot())
    assert len(dims) == 7
    assert {d.dimension for d in dims} == SEVEN


def test_ca_f5_02_not_comparable_state_exact_seven_unique():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(currency="EUR"), r8=r8)
    dims = _dims(snapshot)
    assert len(dims) == 7
    assert {d.dimension for d in dims} == SEVEN
    currency = [d for d in dims
                if d.dimension is ComparabilityDimension.CURRENCY]
    assert len(currency) == 1
    assert currency[0].gap_kind is ModelRadarGapKind.CURRENCY_MISMATCH


def test_ca_f5_03_fx_absence_is_snapshot_gap_not_dimension():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(currency="EUR"), r8=r8)
    dims = _dims(snapshot)
    assert not any(
        d.gap_kind is ModelRadarGapKind.FX_AUTHORITY_UNAVAILABLE
        for d in dims)
    assert ModelRadarGapKind.FX_AUTHORITY_UNAVAILABLE in _not_comparable_gaps(
        snapshot)


def test_ca_f5_04_missing_or_duplicate_dimensions_fail_closed():
    from finco_radar.model_radar.contracts import ModelComparability
    dims = [ComparabilityDimensionResult(
        dimension=ComparabilityDimension.ECONOMIC_IDENTITY, ok=True)]
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.COMPARABLE, dimensions=dims)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID
    duplicated = [
        ComparabilityDimensionResult(
            dimension=d, ok=True) for d in ComparabilityDimension
    ] + [ComparabilityDimensionResult(
        dimension=ComparabilityDimension.CURRENCY, ok=True)]
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.COMPARABLE,
                           dimensions=duplicated)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


# --------------------------------------------------------------------------
# Correction A - F6: canonicalize before digest + stable scenario identity
# --------------------------------------------------------------------------

def test_ca_f6_01_engine_level_scenario_reorder_identical_digests():
    combos = (
        (QuoteSide.BUY, "100"), (QuoteSide.BUY, "1000"),
        (QuoteSide.SELL, "100"), (QuoteSide.SELL, "1000"),
    )
    r7 = _rich_r7()
    r3_evidence = {
        "status": "PASS",
        "asset": {"assetUid": UID,
                  "canonicalKey": f"{KEY.chain_id}:{KEY.contract_address}",
                  "symbol": UID, "chainId": KEY.chain_id,
                  "contractAddress": KEY.contract_address},
    }
    kwargs = dict(
        economic_asset_uid=UID, canonical_asset_key=KEY,
        policy=R8_POLICY,
        upstream_evidence={
            "r7CrossMarketEvidence": r7,
            "r3LiquidityEvidence": r3_evidence,
        },
        source_digests={
            "r7CrossMarketDigest": _digest(r7),
            "r3LiquidityDigest": _digest(r3_evidence),
        },
        synthetic=True, generated_at=NOW,
    )
    a = build_execution_simulation(
        scenarios=[_r8_scenario(s, n) for s, n in combos],
        quote_evidence=[_r8_row(s, n, EXEC_PRICES[(s, n)]) for s, n in combos],
        **kwargs)
    b = build_execution_simulation(
        scenarios=[_r8_scenario(s, n) for s, n in reversed(combos)],
        quote_evidence=[_r8_row(s, n, EXEC_PRICES[(s, n)])
                        for s, n in reversed(combos)],
        **kwargs)
    ev_a, ev_b = a.to_evidence_dict(), b.to_evidence_dict()
    assert ev_a == ev_b  # engine canonicalizes: bytes identical
    r9_a = build_r9_evidence(r8_evidence=ev_a, git_head="t",
                             generated_at=datetime(2026, 9, 17, 11, 0, tzinfo=T))
    r9_b = build_r9_evidence(r8_evidence=ev_b, git_head="t",
                             generated_at=datetime(2026, 9, 17, 11, 0, tzinfo=T))
    snap_a = _bridge(r9_a, model=_model(value=Decimal("100")))
    snap_b = _bridge(r9_b, model=_model(value=Decimal("100")))
    assert snap_a.r10_snapshot_digest == snap_b.r10_snapshot_digest
    assert verify_r10_snapshot_digest(snap_a) is True
    assert verify_serialized_r10_evidence(snap_a.to_evidence_dict()) is True


def test_ca_f6_02_stable_scenario_identity_after_canonical_ordering():
    r9, r8 = _chain(**FULL, mutate_r8=lambda e: e.__setitem__(
        "scenarios", list(reversed(e["scenarios"]))))
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    by_key = {(c.side, c.requested_notional_usd): c.r8_scenario_index
              for c in snapshot.execution_comparisons}
    canonical = sorted(by_key)
    assert [by_key[k] for k in canonical] == [0, 1, 2, 3]
    assert _exec(snapshot, "BUY", "100").r8_scenario_index == 0


# --------------------------------------------------------------------------
# Correction A - F7: contract hygiene
# --------------------------------------------------------------------------

def test_ca_f7_discovery_returns_evidence_type_not_binding():
    import inspect
    from finco_radar.model_radar import bridge
    source = inspect.getsource(bridge.discover_model_evidence)
    assert "-> tuple[ModelEvidence | None, ModelRadarGap | None]" in source
    result = bridge.discover_model_evidence(UID)
    assert isinstance(result, tuple) and len(result) == 2
    assert result[0] is None
    assert isinstance(result[1], ModelRadarGap)


def test_ca_f7b_decimal_timing_no_float_conversion():
    from finco_radar.model_radar.comparisons import decimal_seconds
    from datetime import timedelta
    assert decimal_seconds(timedelta(seconds=0.3)) == Decimal("0.3")
    assert decimal_seconds(timedelta(days=1, microseconds=1)) == Decimal(
        "86400.000001")


# --------------------------------------------------------------------------
# Correction B - G1: caller-supplied evidence is not live model authority
# --------------------------------------------------------------------------

def test_ca_g1_01_digest_valid_non_synthetic_caller_evidence_rejected():
    """Digest-valid, UID-matching, plausible-authority, non-synthetic
    caller-built evidence must NOT become live model authority."""
    r9, r8 = _live_chain(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("100"),
                                        synthetic=False),
                       r8=r8, synthetic=False)
    assert snapshot.status is not ModelRadarStatus.MODEL_RADAR_OK
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL
    kinds = {g.gap_kind for g in snapshot.gaps}
    assert ModelRadarGapKind.MODEL_SOURCE_AUTHORITY_UNAVAILABLE in kinds
    assert ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE in kinds
    assert snapshot.model_evidence is None
    assert snapshot.model_binding is None
    assert snapshot.reference_comparison is None
    assert snapshot.execution_comparisons == ()
    assert snapshot.to_evidence_dict()["modelEvidence"] is None


def test_ca_g1_02_arbitrary_engine_authority_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(engine_authority="e")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g1_03_plausible_but_nonspecific_authority_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(engine_authority="financial_engine")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g1_04_exact_typed_authority_accepted():
    model = _model(engine_authority="finco_core.sponsor.xnpv")
    assert model.engine_authority == "finco_core.sponsor.xnpv"


def test_ca_g1_05_never_discovered_model_identity_not_authority():
    """A caller-created model id/version was never discovered by model
    authority; non-synthetic it cannot produce a comparable snapshot."""
    r9, r8 = _live_chain(**FULL)
    snapshot = _bridge(r9, model=_model(
        model_id="NEVER-DISCOVERED-MODEL", model_version="9.9",
        synthetic=False), r8=r8, synthetic=False)
    assert snapshot.status is not ModelRadarStatus.MODEL_RADAR_OK
    assert snapshot.reference_comparison is None


def test_ca_g1_06_rejection_is_typed_gap_not_raw_crash():
    r9, r8 = _live_chain(**FULL)
    snapshot = _bridge(r9, model=_model(synthetic=False), r8=r8,
                       synthetic=False)
    evidence = snapshot.to_evidence_dict()
    assert evidence["status"] == "MODEL_RADAR_PARTIAL"
    assert any(g["gapKind"] == "MODEL_SOURCE_AUTHORITY_UNAVAILABLE"
               for g in evidence["gaps"])


# --------------------------------------------------------------------------
# Correction B - G2: synthetic provenance cannot be laundered
# --------------------------------------------------------------------------

def test_ca_g2_01_synthetic_model_cannot_publish_non_synthetic():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(synthetic=True), r8=r8,
                       synthetic=False)
    assert snapshot.synthetic is True
    assert snapshot.to_evidence_dict()["synthetic"] is True


def test_ca_g2_02_synthetic_r9_lineage_cannot_be_laundered():
    r9, r8 = _chain(**FULL)
    r9["synthetic"] = True
    _reseal_r9(r9)
    snapshot = _bridge(r9, model=None, r8=r8, synthetic=False)
    assert snapshot.synthetic is True


def test_ca_g2_03_synthetic_r8_lineage_cannot_be_laundered():
    r9, r8 = _chain(**FULL)
    assert r8["synthetic"] is True  # fixture R8 is engine-synthetic
    snapshot = _bridge(r9, model=None, r8=r8, synthetic=False)
    assert snapshot.synthetic is True


def test_ca_g2_04_synthetic_r7_lineage_cannot_be_laundered():
    r9, r8 = _chain(**FULL)
    assert (r8["upstreamEvidence"]["r7CrossMarketEvidence"]["synthetic"]
            is True)
    snapshot = _bridge(r9, model=None, r8=r8, synthetic=False)
    assert snapshot.synthetic is True


def test_ca_g2_05_non_synthetic_chain_stays_non_synthetic():
    r9, r8 = _live_chain(**FULL)
    snapshot = _bridge(r9, model=None, r8=r8, synthetic=False)
    assert snapshot.synthetic is False
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


def test_ca_g2_06_synthetic_comparable_proof_remains_synthetic():
    assert _full_snapshot().synthetic is True


# --------------------------------------------------------------------------
# Correction B - G3: output observation binds comparison-critical fields
# --------------------------------------------------------------------------

def test_ca_g3_01_output_value_mismatch_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(value=Decimal("101"), output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_02_output_value_kind_mismatch_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               output_evidence={
                   "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
                   "currency": "USD", "unitBasis": "TOTAL_EQUITY",
                   "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_03_output_currency_mismatch_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(currency="EUR", output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_04_output_unit_basis_mismatch_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(unit_basis=ModelUnitBasis.PER_SHARE, output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_05_output_multiplier_disagreement_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               unit_multiplier=Decimal("10000"),
               unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
               output_evidence={
                   "value": "1000000",
                   "valueKind": "EQUITY_VALUE_TOTAL", "currency": "USD",
                   "unitBasis": "TOTAL_EQUITY", "unitMultiplier": "5",
                   "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_06_input_multiplier_disagreement_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               unit_multiplier=Decimal("10000"),
               unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
               input_evidence={"unitMultiplier": "7"},
               output_evidence={
                   "value": "1000000",
                   "valueKind": "EQUITY_VALUE_TOTAL", "currency": "USD",
                   "unitBasis": "TOTAL_EQUITY", "unitMultiplier": "10000",
                   "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_07_valuation_timestamp_disagreement_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": "2020-01-01T00:00:00+00:00"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_g3_08_missing_observation_keys_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={"value": "100"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


# --------------------------------------------------------------------------
# Correction B - G4: comparability state consistency
# --------------------------------------------------------------------------

def _all_ok_dimensions():
    return [ComparabilityDimensionResult(dimension=d, ok=True)
            for d in ComparabilityDimension]


def test_ca_g4_01_comparable_with_failed_dimension_rejected():
    dims = _all_ok_dimensions()
    dims[1] = ComparabilityDimensionResult(
        dimension=ComparabilityDimension.VALUE_KIND, ok=False,
        gap_kind=ModelRadarGapKind.VALUE_KIND_MISMATCH, detail="x")
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.COMPARABLE,
                           dimensions=dims)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g4_02_failed_dimension_without_gap_rejected():
    dims = _all_ok_dimensions()
    dims[1] = ComparabilityDimensionResult(
        dimension=ComparabilityDimension.VALUE_KIND, ok=False, detail="x")
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.NOT_COMPARABLE,
                           dimensions=dims)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g4_03_ok_dimension_with_gap_rejected():
    dims = _all_ok_dimensions()
    dims[0] = ComparabilityDimensionResult(
        dimension=ComparabilityDimension.ECONOMIC_IDENTITY, ok=True,
        gap_kind=ModelRadarGapKind.CURRENCY_MISMATCH)
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.COMPARABLE,
                           dimensions=dims)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g4_04_not_comparable_with_all_ok_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.NOT_COMPARABLE,
                           dimensions=_all_ok_dimensions())
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g4_05_partial_with_unauthorized_failure_rejected():
    dims = _all_ok_dimensions()
    dims[1] = ComparabilityDimensionResult(
        dimension=ComparabilityDimension.VALUE_KIND, ok=False,
        gap_kind=ModelRadarGapKind.VALUE_KIND_MISMATCH, detail="x")
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.PARTIALLY_COMPARABLE,
                           dimensions=dims)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g4_06_partial_reserved_for_reference_only_failure():
    dims = _all_ok_dimensions()
    dims[6] = ComparabilityDimensionResult(
        dimension=ComparabilityDimension.REFERENCE_AVAILABILITY, ok=False,
        gap_kind=ModelRadarGapKind.REFERENCE_UNAVAILABLE, detail="no ref")
    comparability = ModelComparability(
        state=ComparabilityState.PARTIALLY_COMPARABLE, dimensions=dims)
    assert comparability.state is ComparabilityState.PARTIALLY_COMPARABLE


# --------------------------------------------------------------------------
# Correction B - G5: finite Decimal boundaries
# --------------------------------------------------------------------------

def test_ca_g5_01_decimal_authority_nonfinite_strings_rejected():
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ModelRadarError):
            decimal_from_authority(bad)
        with pytest.raises(ModelRadarError):
            decimal_from_authority(Decimal(bad))


def test_ca_g5_02_decimal_authority_malformed_string_typed():
    with pytest.raises(ModelRadarError) as excinfo:
        decimal_from_authority("abc")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g5_03_model_value_nan_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(value=Decimal("NaN"))
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g5_04_unit_multiplier_infinity_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               unit_multiplier=Decimal("Infinity"),
               unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g5_05_timing_policy_nan_rejected():
    with pytest.raises(ModelRadarError):
        ModelRadarTimingPolicy(max_model_age_seconds=Decimal("NaN"),
                               max_model_market_skew_seconds=Decimal("1"))


def test_ca_g5_06_market_multiplier_nan_rejected():
    with pytest.raises(ModelRadarError):
        MarketComparabilityContext(
            reference_price=Decimal("105"), reference_currency="USD",
            reference_source="R7", reference_observed_at=NOW,
            market_unit_basis=ModelUnitBasis.PER_TOKEN_CLAIM,
            conversion_multiplier=Decimal("NaN"),
            token_multiplier=Decimal("2"))


def test_ca_g5_07_execution_price_nonfinite_typed_error():
    def _nan_price(e):
        row = e["scenarios"][0]["upstreamEvidence"]["r2GapEvidence"]
        row["executionPriceUsdPerToken"] = "NaN"
    r9, r8 = _chain(**FULL, mutate_r8=_nan_price)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_g5_08_reference_price_infinity_typed_error():
    def _inf_oracle(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"]["price"] = "Infinity"
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    r9, r8 = _chain(mutate_r8=_inf_oracle)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=None, r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


# --------------------------------------------------------------------------
# Correction B - G6: complete kind x basis matrix
# --------------------------------------------------------------------------

def test_ca_g6_01_value_per_unit_with_total_equity_rejected():
    with pytest.raises(ModelRadarError):
        _model(unit_basis=ModelUnitBasis.TOTAL_EQUITY)


def test_ca_g6_02_value_per_unit_with_total_enterprise_rejected():
    with pytest.raises(ModelRadarError):
        _model(unit_basis=ModelUnitBasis.TOTAL_ENTERPRISE)


def test_ca_g6_03_value_per_unit_with_total_project_rejected():
    with pytest.raises(ModelRadarError):
        _model(unit_basis=ModelUnitBasis.TOTAL_PROJECT)


def test_ca_g6_04_equity_total_with_per_unit_basis_rejected():
    with pytest.raises(ModelRadarError):
        _model(value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.PER_ECONOMIC_UNIT)


def test_ca_g6_05_equity_total_with_token_claim_multiplier_basis_rejected():
    with pytest.raises(ModelRadarError):
        _model(value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               unit_multiplier=Decimal("10"),
               unit_multiplier_basis=ModelUnitBasis.PER_TOKEN_CLAIM)


def test_ca_g6_06_no_comparable_then_crash_path():
    """Every constructible COMPARABLE pair must survive model_value_per_unit
    without a later normalization error."""
    for model in (
        _model(value=Decimal("100")),
        _model(unit_basis=ModelUnitBasis.PER_SHARE),
        _model(unit_basis=ModelUnitBasis.PER_TOKEN_CLAIM),
        _model(value=Decimal("1000000"),
               value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
               unit_basis=ModelUnitBasis.TOTAL_EQUITY,
               unit_multiplier=Decimal("10000"),
               unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT),
    ):
        r9, r8 = _chain(**FULL)
        snapshot = _bridge(r9, model=model, r8=r8)
        if snapshot.comparability.state is ComparabilityState.COMPARABLE:
            model_value_per_unit(snapshot.model_evidence)  # must not raise


# --------------------------------------------------------------------------
# Correction C - H1: every comparison-critical field is source-bound
# --------------------------------------------------------------------------

def _bound_equity_model():
    """A fully source-bound synthetic equity-total model: the input (policy)
    record carries the authoritative unitMultiplier/unitMultiplierBasis and
    the output observation carries the authoritative valuationAsOf."""
    return _model(
        value=Decimal("1000000"),
        value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
        unit_basis=ModelUnitBasis.TOTAL_EQUITY,
        unit_multiplier=Decimal("10000"),
        unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
        output_evidence={
            "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
            "currency": "USD", "unitBasis": "TOTAL_EQUITY",
            "valuationAsOf": NOW.isoformat()},
    )


def test_ca_h1_01_missing_valuation_as_of_authority_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_02_valuation_as_of_disagreement_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": "2020-01-01T00:00:00+00:00"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def _equity_with_input(multiplier=None, basis=None):
    """Direct construction (no fixture auto-injection): the declared
    authority is always 10000/PER_ECONOMIC_UNIT; the optional params control
    only what the INPUT record proves."""
    input_evidence = {
        "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
        "cashFlows": ["-100", "110"], "dates": ["2026-01-01", "2027-01-01"],
        "currency": "USD", "economicScope": "unit:AAPL",
    }
    if multiplier is not None:
        input_evidence["unitMultiplier"] = multiplier
    if basis is not None:
        input_evidence["unitMultiplierBasis"] = basis
    output_evidence = {
        "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
        "currency": "USD", "unitBasis": "TOTAL_EQUITY",
        "valuationAsOf": NOW.isoformat()}
    return ModelEvidence(
        model_id="FINCO-SYNTH-PROJECT-MODEL", model_version="1.0.0",
        engine_authority="financial_engine.orchestrator",
        economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
        valuation_as_of=NOW,
        value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
        value=Decimal("1000000"), currency="USD",
        unit_basis=ModelUnitBasis.TOTAL_EQUITY,
        input_digest=digest_payload(input_evidence),
        output_digest=digest_payload(output_evidence),
        input_evidence=input_evidence,
        output_evidence=output_evidence,
        unit_multiplier=Decimal("10000"),
        unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
        synthetic=True)


def test_ca_h1_03_multiplier_without_input_authority_fails():
    model = _equity_with_input(multiplier="10000", basis="PER_ECONOMIC_UNIT")
    kwargs = dict(model.__dict__)
    kwargs["input_evidence"] = {
        k: v for k, v in kwargs["input_evidence"].items()
        if k != "unitMultiplier"}
    kwargs["input_digest"] = digest_payload(kwargs["input_evidence"])
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(**kwargs)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_04_multiplier_value_disagreement_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _equity_with_input(multiplier="7")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_05_multiplier_basis_without_input_authority_fails():
    input_evidence = {
        "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
        "unitMultiplier": "10000",
    }
    with pytest.raises(ModelRadarError) as excinfo:
        ModelEvidence(
            model_id="M", model_version="1",
            engine_authority="financial_engine.orchestrator",
            economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
            valuation_as_of=NOW,
            value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
            value=Decimal("1000000"), currency="USD",
            unit_basis=ModelUnitBasis.TOTAL_EQUITY,
            input_digest=digest_payload(input_evidence),
            output_digest=digest_payload({
                "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
                "currency": "USD", "unitBasis": "TOTAL_EQUITY",
                "valuationAsOf": NOW.isoformat()}),
            input_evidence=input_evidence,
            output_evidence={
                "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
                "currency": "USD", "unitBasis": "TOTAL_EQUITY",
                "valuationAsOf": NOW.isoformat()},
            unit_multiplier=Decimal("10000"),
            unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            synthetic=True)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_06_multiplier_basis_disagreement_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _equity_with_input(multiplier="10000", basis="PER_SHARE")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_07_input_output_multiplier_conflict_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(
            value=Decimal("1000000"),
            value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
            unit_basis=ModelUnitBasis.TOTAL_EQUITY,
            unit_multiplier=Decimal("10000"),
            unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            input_evidence={
                "unitMultiplier": "10000",
                "unitMultiplierBasis": "PER_ECONOMIC_UNIT"},
            output_evidence={
                "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
                "currency": "USD", "unitBasis": "TOTAL_EQUITY",
                "unitMultiplier": "999",
                "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_08_input_output_multiplier_basis_conflict_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(
            value=Decimal("1000000"),
            value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
            unit_basis=ModelUnitBasis.TOTAL_EQUITY,
            unit_multiplier=Decimal("10000"),
            unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
            input_evidence={
                "unitMultiplier": "10000",
                "unitMultiplierBasis": "PER_ECONOMIC_UNIT"},
            output_evidence={
                "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
                "currency": "USD", "unitBasis": "TOTAL_EQUITY",
                "unitMultiplierBasis": "PER_SHARE",
                "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_09_input_output_timestamp_conflict_fails():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(
            input_evidence={
                "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
                "valuationAsOf": "2020-01-01T00:00:00+00:00"},
            output_evidence={
                "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
                "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
                "valuationAsOf": NOW.isoformat()})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_h1_10_fully_source_bound_comparable_model_passes():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_bound_equity_model(), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    per_unit = model_value_per_unit(snapshot.model_evidence)
    assert per_unit == Decimal("100")
    assert snapshot.reference_comparison.reference_vs_model_bps == Decimal("500")


def test_ca_h1_11_dropped_input_multiplier_authority_fails():
    input_evidence = {"unitMultiplier": "10000",
                      "unitMultiplierBasis": "PER_ECONOMIC_UNIT"}
    with pytest.raises(ModelRadarError) as excinfo:
        _model(input_evidence=input_evidence)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


# --------------------------------------------------------------------------
# Correction C - H2: exact-boolean synthetic provenance
# --------------------------------------------------------------------------

def _provenance_chain(strip_layer):
    """Build a valid chain, then REMOVE/mangle the synthetic provenance flag
    on one causal layer, resealing every upstream digest correctly."""
    def mutate(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        if strip_layer == "r7":
            r7.pop("synthetic", None)
            r7["r7SnapshotDigest"] = _digest(
                {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
            e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
        if strip_layer in ("r7", "r8"):
            e.pop("synthetic", None)
    r9, _ = _chain(**FULL, mutate_r8=mutate)
    if strip_layer == "r9":
        r9.pop("synthetic", None)
        _reseal_r9(r9)
    return r9


# CI-facing alias for the Correction C negative gate
_chain_provenance_strip = _provenance_chain


def _unbound_basis_model():
    """Direct construction: multiplier value proven by input authority but
    the multiplier BASIS left unbound (H1 negative)."""
    input_evidence = {
        "discountRateAuthority": "EXPLICIT_SYNTHETIC_POLICY",
        "unitMultiplier": "10000",
    }
    output_evidence = {
        "value": "1000000", "valueKind": "EQUITY_VALUE_TOTAL",
        "currency": "USD", "unitBasis": "TOTAL_EQUITY",
        "valuationAsOf": NOW.isoformat()}
    return ModelEvidence(
        model_id="M", model_version="1",
        engine_authority="financial_engine.orchestrator",
        economic_asset_uid=UID, economic_node_id=f"economic:{UID}",
        valuation_as_of=NOW,
        value_kind=ModelValueKind.EQUITY_VALUE_TOTAL,
        value=Decimal("1000000"), currency="USD",
        unit_basis=ModelUnitBasis.TOTAL_EQUITY,
        input_digest=digest_payload(input_evidence),
        output_digest=digest_payload(output_evidence),
        input_evidence=input_evidence,
        output_evidence=output_evidence,
        unit_multiplier=Decimal("10000"),
        unit_multiplier_basis=ModelUnitBasis.PER_ECONOMIC_UNIT,
        synthetic=True)


def test_ca_h2_01_missing_r9_synthetic_fails_closed():
    r9 = _provenance_chain("r9")
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h2_02_missing_r8_synthetic_fails_closed():
    r9 = _provenance_chain("r8")
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h2_03_missing_r7_synthetic_fails_closed():
    r9 = _provenance_chain("r7")
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h2_04_null_synthetic_fails_closed():
    r9, _ = _chain(**FULL)
    r9["synthetic"] = None
    _reseal_r9(r9)
    with pytest.raises(ModelRadarError):
        _bridge(r9)


def test_ca_h2_05_string_false_synthetic_fails_closed():
    r9, _ = _chain(**FULL)
    r9["synthetic"] = "false"
    _reseal_r9(r9)
    with pytest.raises(ModelRadarError):
        _bridge(r9)


def test_ca_h2_06_integer_zero_synthetic_fails_closed():
    r9, _ = _chain(**FULL)
    r9["synthetic"] = 0
    _reseal_r9(r9)
    with pytest.raises(ModelRadarError):
        _bridge(r9)


def test_ca_h2_07_exact_false_chain_remains_valid():
    r9, r8 = _live_chain(**FULL)
    assert r9["synthetic"] is False
    assert r8["synthetic"] is False
    assert (r8["upstreamEvidence"]["r7CrossMarketEvidence"]["synthetic"]
            is False)
    snapshot = _bridge(r9, model=None, r8=r8, synthetic=False)
    assert snapshot.synthetic is False


# --------------------------------------------------------------------------
# Correction C - H3: canonical typed numeric boundaries
# --------------------------------------------------------------------------

def _malformed_chain(mutate):
    r9, r8 = _chain(**FULL, mutate_r8=mutate)
    return r9, r8


def test_ca_h3_01_oracle_price_abc_typed():
    def m(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"]["price"] = "abc"
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    r9, r8 = _malformed_chain(m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=None, r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h3_02_oracle_multiplier_abc_typed():
    def m(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"]["multiplier"] = "abc"
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    r9, r8 = _malformed_chain(m)
    with pytest.raises(ModelRadarError):
        _bridge(r9, model=None, r8=r8)


def test_ca_h3_03_token_multiplier_abc_typed():
    def m(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["token"]["multiplier"] = "abc"
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    r9, r8 = _malformed_chain(m)
    with pytest.raises(ModelRadarError):
        _bridge(r9, model=None, r8=r8)


def test_ca_h3_04_execution_price_abc_typed():
    def m(e):
        e["scenarios"][0]["upstreamEvidence"]["r2GapEvidence"][
            "executionPriceUsdPerToken"] = "abc"
    r9, r8 = _malformed_chain(m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h3_05_notional_abc_typed():
    def m(e):
        e["scenarios"][0]["scenario"]["requestedNotionalUsd"] = "abc"
    r9, r8 = _malformed_chain(m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h3_06_and_07_zero_negative_conversion_multiplier_typed():
    for bad in ("0", "-2"):
        with pytest.raises(ModelRadarError):
            MarketComparabilityContext(
                reference_price=Decimal("105"), reference_currency="USD",
                reference_source="R7", reference_observed_at=NOW,
                market_unit_basis=ModelUnitBasis.PER_TOKEN_CLAIM,
                conversion_multiplier=Decimal(bad),
                token_multiplier=Decimal("2"))


def test_ca_h3_08_and_09_zero_negative_available_reference_price_typed():
    for bad in ("0", "-5"):
        def m(e, bad=bad):
            r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
            r7["layers"]["oracleReference"]["price"] = bad
            r7["r7SnapshotDigest"] = _digest(
                {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
            e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
        r9, r8 = _malformed_chain(m)
        with pytest.raises(ModelRadarError) as excinfo:
            _bridge(r9, model=None, r8=r8)
        assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h3_10_and_11_zero_negative_execution_price_typed():
    for bad in ("0", "-3"):
        def m(e, bad=bad):
            e["scenarios"][0]["upstreamEvidence"]["r2GapEvidence"][
                "executionPriceUsdPerToken"] = bad
        r9, r8 = _malformed_chain(m)
        with pytest.raises(ModelRadarError):
            _bridge(r9, model=_model(value=Decimal("100")), r8=r8)


# --------------------------------------------------------------------------
# Correction C - H4: exact PARTIALLY_COMPARABLE contract
# --------------------------------------------------------------------------

def _dims_with(failed):
    dims = []
    for d in ComparabilityDimension:
        if d in failed:
            dims.append(ComparabilityDimensionResult(
                dimension=d, ok=False, gap_kind=failed[d], detail="x"))
        else:
            dims.append(ComparabilityDimensionResult(dimension=d, ok=True))
    return dims


def test_ca_h4_01_partial_with_currency_gap_on_reference_rejected():
    with pytest.raises(ModelRadarError):
        ModelComparability(state=ComparabilityState.PARTIALLY_COMPARABLE,
                           dimensions=_dims_with({
                               ComparabilityDimension.REFERENCE_AVAILABILITY:
                                   ModelRadarGapKind.CURRENCY_MISMATCH}))


def test_ca_h4_02_partial_with_value_kind_gap_on_reference_rejected():
    with pytest.raises(ModelRadarError):
        ModelComparability(state=ComparabilityState.PARTIALLY_COMPARABLE,
                           dimensions=_dims_with({
                               ComparabilityDimension.REFERENCE_AVAILABILITY:
                                   ModelRadarGapKind.VALUE_KIND_MISMATCH}))


def test_ca_h4_03_partial_with_two_failed_dimensions_rejected():
    dims = _dims_with({
        ComparabilityDimension.REFERENCE_AVAILABILITY:
            ModelRadarGapKind.REFERENCE_UNAVAILABLE,
        ComparabilityDimension.TIMING:
            ModelRadarGapKind.TIMING_SKEW_INVALID,
    })
    with pytest.raises(ModelRadarError):
        ModelComparability(state=ComparabilityState.PARTIALLY_COMPARABLE,
                           dimensions=dims)


def test_ca_h4_04_string_state_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state="PARTIALLY_COMPARABLE",
                           dimensions=_all_ok_dimensions())
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h4_05_non_enum_gap_object_rejected():
    dims = _all_ok_dimensions()
    dims[1] = ComparabilityDimensionResult(
        dimension=ComparabilityDimension.VALUE_KIND, ok=False,
        gap_kind="VALUE_KIND_MISMATCH", detail="x")
    with pytest.raises(ModelRadarError) as excinfo:
        ModelComparability(state=ComparabilityState.NOT_COMPARABLE,
                           dimensions=dims)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_h4_06_positive_reference_only_partial_still_passes():
    comparability = ModelComparability(
        state=ComparabilityState.PARTIALLY_COMPARABLE,
        dimensions=_dims_with({
            ComparabilityDimension.REFERENCE_AVAILABILITY:
                ModelRadarGapKind.REFERENCE_UNAVAILABLE}))
    assert comparability.state is ComparabilityState.PARTIALLY_COMPARABLE


# --------------------------------------------------------------------------
# Correction D - I1: independent execution currency authority
# --------------------------------------------------------------------------

def test_ca_i1_01_usd_usd_usd_passes_with_currency_authority():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_OK
    assert snapshot.reference_comparison is not None
    assert len(snapshot.execution_comparisons) == 4
    for row in snapshot.execution_comparisons:
        evidence = row.to_evidence_dict()
        assert evidence["executionCurrency"] == "USD"
        assert evidence["executionObservedAt"] is not None


def test_ca_i1_02_eur_model_eur_reference_usd_execution_split():
    """Model EUR + reference EUR stays reference-comparable; the USD
    execution comparison is suppressed with typed currency incompatibility
    and the snapshot remains PARTIAL."""
    r9, r8 = _chain(**FULL, oracle_currency="EUR")
    snapshot = _bridge(r9, model=_model(value=Decimal("100"),
                                        currency="EUR"), r8=r8)
    assert snapshot.comparability.state is ComparabilityState.COMPARABLE
    assert snapshot.reference_comparison is not None
    assert snapshot.execution_comparisons == ()
    kinds = {g.gap_kind for g in snapshot.gaps}
    assert ModelRadarGapKind.CURRENCY_MISMATCH in kinds
    assert ModelRadarGapKind.FX_AUTHORITY_UNAVAILABLE in kinds
    sources = {g.source for g in snapshot.gaps}
    assert "R8_EXECUTION_SIMULATOR_AUTHORITY" in sources
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


def test_ca_i1_03_eur_model_usd_reference_blocked():
    r9, r8 = _chain(**FULL)  # reference is USD
    snapshot = _bridge(r9, model=_model(value=Decimal("100"),
                                        currency="EUR"), r8=r8)
    assert snapshot.reference_comparison is None
    assert snapshot.execution_comparisons == ()
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


def test_ca_i1_04_usd_model_eur_reference_blocked_conservatively():
    """v1 requires reference authority before any execution comparison; a
    failed reference comparison is never bypassed via execution evidence."""
    r9, r8 = _chain(**FULL, oracle_currency="EUR")
    snapshot = _bridge(r9, model=_model(value=Decimal("100"),
                                        currency="USD"), r8=r8)
    assert snapshot.reference_comparison is None
    assert snapshot.execution_comparisons == ()
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


def test_ca_i1_05_stablecoin_is_not_implicit_usd():
    r9, r8 = _chain(**FULL)
    snapshot = _bridge(r9, model=_model(value=Decimal("100"),
                                        currency="USDC"), r8=r8)
    kinds = {g.gap_kind for g in snapshot.gaps}
    assert ModelRadarGapKind.CURRENCY_MISMATCH in kinds
    assert snapshot.execution_comparisons == ()
    assert snapshot.reference_comparison is None


def test_ca_i1_06_no_execution_row_omits_currency_authority():
    snapshot = _full_snapshot()
    for row in snapshot.to_evidence_dict()["executionComparisons"]:
        assert row["executionCurrency"] == "USD"
        assert row["executionObservedAt"]


# --------------------------------------------------------------------------
# Correction D - I2: execution timing authority
# --------------------------------------------------------------------------

def test_ca_i2_01_execution_skew_exact_boundary_passes():
    def m(e):
        for scenario in e["scenarios"]:
            scenario["quoteObservedAt"] = (
                (NOW - timedelta(seconds=300)).isoformat())
    r9, r8 = _chain(**FULL, mutate_r8=m)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert len(snapshot.execution_comparisons) == 4


def test_ca_i2_02_execution_skew_plus_one_microsecond_blocked():
    skewed = (NOW - timedelta(seconds=300, microseconds=1)).isoformat()

    def m(e):
        e["scenarios"][0]["quoteObservedAt"] = skewed
    r9, r8 = _chain(**FULL, mutate_r8=m)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert len(snapshot.execution_comparisons) == 3
    assert any(g.gap_kind is ModelRadarGapKind.TIMING_SKEW_INVALID
               for g in snapshot.gaps)


def test_ca_i2_03_missing_quote_observed_at_typed_gap():
    def m(e):
        for scenario in e["scenarios"]:
            scenario.pop("quoteObservedAt", None)
    r9, r8 = _chain(**FULL, mutate_r8=m)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.execution_comparisons == ()
    assert any(g.gap_kind is ModelRadarGapKind.EXECUTION_EVIDENCE_UNAVAILABLE
               for g in snapshot.gaps)


def test_ca_i2_04_malformed_quote_observed_at_typed_error():
    def m(e):
        e["scenarios"][0]["quoteObservedAt"] = "abc"
    r9, r8 = _chain(**FULL, mutate_r8=m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i2_05_naive_quote_timestamp_typed_timing_error():
    def m(e):
        e["scenarios"][0]["quoteObservedAt"] = (
            (NOW - timedelta(seconds=10)).replace(tzinfo=None).isoformat())
    r9, r8 = _chain(**FULL, mutate_r8=m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_TIMING_INVALID


def test_ca_i2_06_future_quote_timestamp_typed_timing_error():
    def m(e):
        e["scenarios"][0]["quoteObservedAt"] = (
            (NOW + timedelta(seconds=10)).isoformat())
    r9, r8 = _chain(**FULL, mutate_r8=m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_TIMING_INVALID


def test_ca_i2_07_one_stale_scenario_does_not_suppress_three_valid():
    def m(e):
        e["scenarios"][0]["quoteObservedAt"] = (
            (NOW - timedelta(seconds=301)).isoformat())
    r9, r8 = _chain(**FULL, mutate_r8=m)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert len(snapshot.execution_comparisons) == 3
    assert snapshot.reference_comparison is not None


def test_ca_i2_08_reference_survives_execution_only_timing_failure():
    def m(e):
        e["scenarios"][0]["quoteObservedAt"] = (
            (NOW - timedelta(seconds=301)).isoformat())
    r9, r8 = _chain(**FULL, mutate_r8=m)
    snapshot = _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert snapshot.reference_comparison is not None
    assert snapshot.reference_comparison.reference_vs_model_bps == Decimal("500")
    assert snapshot.status is ModelRadarStatus.MODEL_RADAR_PARTIAL


# --------------------------------------------------------------------------
# Correction D - I3: canonical typed datetime boundary
# --------------------------------------------------------------------------

def test_ca_i3_01_abc_timestamp_typed():
    with pytest.raises(ModelRadarError) as excinfo:
        datetime_from_evidence("abc", "field")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i3_02_missing_timestamp_typed():
    with pytest.raises(ModelRadarError) as excinfo:
        datetime_from_evidence(None, "field")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i3_03_naive_iso_timestamp_timing_invalid():
    with pytest.raises(ModelRadarError) as excinfo:
        datetime_from_evidence("2026-09-17T12:00:00", "field")
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_TIMING_INVALID


def test_ca_i3_04_valid_utc_accepted():
    parsed = datetime_from_evidence("2026-09-17T12:00:00+00:00", "field")
    assert parsed.utcoffset().total_seconds() == 0


def test_ca_i3_05_valid_non_utc_offset_accepted():
    parsed = datetime_from_evidence("2026-09-17T14:00:00+02:00", "field")
    assert parsed.utcoffset().total_seconds() == 7200


def test_ca_i3_06_r7_observed_at_malformed_typed_via_chain():
    def m(e):
        r7 = e["upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"]["observedAt"] = "abc"
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    r9, r8 = _chain(**FULL, mutate_r8=m)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=_model(value=Decimal("100")), r8=r8)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


# --------------------------------------------------------------------------
# Correction D - I4: exact boolean synthetic contract
# --------------------------------------------------------------------------

def test_ca_i4_01_model_synthetic_non_boolean_rejected():
    for bad in (0, 1, "false", "true", None):
        with pytest.raises(ModelRadarError) as excinfo:
            _model(synthetic=bad)
        assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i4_02_builder_synthetic_argument_exact_boolean():
    r9, r8 = _chain(**FULL)
    with pytest.raises(ModelRadarError) as excinfo:
        _bridge(r9, model=None, r8=r8, synthetic=1)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i4_03_integer_synthetic_model_cannot_become_live_snapshot():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(synthetic=1)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


# --------------------------------------------------------------------------
# Correction D - I5: context positive reference price
# --------------------------------------------------------------------------

def test_ca_i5_01_zero_reference_price_rejected_at_context():
    with pytest.raises(ModelRadarError) as excinfo:
        MarketComparabilityContext(
            reference_price=Decimal("0"), reference_currency="USD",
            reference_source="R7", reference_observed_at=NOW)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i5_02_negative_reference_price_rejected_at_context():
    with pytest.raises(ModelRadarError) as excinfo:
        MarketComparabilityContext(
            reference_price=Decimal("-1"), reference_currency="USD",
            reference_source="R7", reference_observed_at=NOW)
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_INPUT_INVALID


def test_ca_i5_03_positive_finite_reference_price_valid():
    context = MarketComparabilityContext(
        reference_price=Decimal("105"), reference_currency="USD",
        reference_source="R7", reference_observed_at=NOW)
    assert context.reference_price == Decimal("105")


# --------------------------------------------------------------------------
# Correction D - I6: output-only multiplier claims fail closed
# --------------------------------------------------------------------------

def test_ca_i6_01_output_only_multiplier_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat(), "unitMultiplier": "5"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_i6_02_output_only_multiplier_basis_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat(),
            "unitMultiplierBasis": "PER_SHARE"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH


def test_ca_i6_03_output_only_both_multiplier_fields_rejected():
    with pytest.raises(ModelRadarError) as excinfo:
        _model(output_evidence={
            "value": "100", "valueKind": "VALUE_PER_ECONOMIC_UNIT",
            "currency": "USD", "unitBasis": "PER_ECONOMIC_UNIT",
            "valuationAsOf": NOW.isoformat(), "unitMultiplier": "5",
            "unitMultiplierBasis": "PER_SHARE"})
    assert excinfo.value.status is ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH

"""Build FINCO's sanitized deterministic public verification corpus.

The corpus uses only fictional Model projects and a fully synthetic Radar R3
asset/quote matrix. It is intentionally network-free and contains no client,
workbook, wallet, company or jurisdiction-specific source data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from app.api.project_runner import run_project
from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    RegistryAssetStatus,
)
from finco_radar.gap.contracts import GapComparisonPolicy
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.liquidity.contracts import LiquidityComparisonPolicy
from finco_radar.liquidity.engine import build_liquidity_snapshot
from finco_radar.quotes.contracts import (
    AssetRef,
    ExecutionQuote,
    QuoteEvidence,
    QuoteSide,
    QuoteStatus,
    RouteLeg,
    SettlementReference,
    SettlementReferenceState,
)

from .envelope import (
    build_evidence_envelope,
    canonical_sha256,
    verify_evidence_envelope,
)
from .model import build_model_validation_claim, validate_model_run
from .radar_r3 import build_radar_r3_validation_claim, validate_radar_r3_evidence


PUBLIC_CORPUS_SCHEMA = "finco.public-validation-corpus.v1"
_EXPECTED_V1_CASES: tuple[tuple[str, str, str], ...] = (
    ("model-solar-base", "FINCO_MODEL", "MODEL_PUBLIC_VALIDATION"),
    ("model-wind-base", "FINCO_MODEL", "MODEL_PUBLIC_VALIDATION"),
    ("radar-r3-synthetic-liquidity", "FINCO_RADAR_R3", "RADAR_R3_PUBLIC_VALIDATION"),
)

# Deliberately synthetic local-chain-style identity; not a real listed asset.
_SYNTH_CHAIN = 31337
_SYNTH_UID = "0x" + "11" * 32
_SYNTH_TOKEN = "0x" + "aa" * 20
_SYNTH_SETTLEMENT = "0x" + "cc" * 20
_SYNTH_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
_SMALL = Decimal("100")
_LARGE = Decimal("1000")


def _model_case(case_id: str, project_type: str, factory) -> dict[str, Any]:
    payload = run_project(
        project_type,
        "Base",
        project_inputs_override=factory(),
    )
    report = validate_model_run(payload)
    if not report.passed:
        raise RuntimeError(
            f"public Model validation failed for {case_id}: "
            f"{[failure.invariant_id for failure in report.failures]}"
        )
    claim = build_model_validation_claim(payload, report)
    envelope = build_evidence_envelope(
        surface="FINCO_MODEL",
        evidence_type="MODEL_PUBLIC_VALIDATION",
        payload=claim,
        authority_refs=(
            "app.services.production_financial_authority.run_clean_production",
            "financial_engine.shareholder_waterfall.run_project_shareholder_waterfall_model",
            "finco_protocol.verification.model.validate_model_run",
        ),
    )
    return {
        "caseId": case_id,
        "surface": "FINCO_MODEL",
        "synthetic": True,
        "envelope": envelope.as_dict(),
    }


def _synthetic_asset() -> CanonicalAssetRecord:
    return CanonicalAssetRecord(
        asset_uid=_SYNTH_UID,
        token_symbol="SYN",
        token_name="Synthetic Verification Asset",
        deployments=(AssetKey(_SYNTH_CHAIN, _SYNTH_TOKEN),),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )


def _synthetic_binding() -> ReferenceBinding:
    return ReferenceBinding(
        asset_uid=_SYNTH_UID,
        asset_key=AssetKey(_SYNTH_CHAIN, _SYNTH_TOKEN),
        reference_symbol="SYN",
    )


def _synthetic_reference():
    row = {
        "tokenSymbol": "SYN",
        "deployments": [
            {"chainId": _SYNTH_CHAIN, "contractAddress": _SYNTH_TOKEN}
        ],
        "bid": "95",
        "ask": "105",
        "currency": "USD",
        "generatedAt": "2026-01-01T12:00:00Z",
        "isTradingHalt": False,
    }
    return build_bound_reference_price(_synthetic_asset(), _synthetic_binding(), row)


def _settlement_reference() -> SettlementReference:
    return SettlementReference(
        asset=AssetRef(
            _SYNTH_CHAIN,
            _SYNTH_SETTLEMENT,
            symbol="SUSD",
            decimals=18,
        ),
        state=SettlementReferenceState.REFERENCE_CURRENT,
        usd_per_asset=Decimal("1"),
        source="PUBLIC_SYNTHETIC_SETTLEMENT",
        observed_at=_SYNTH_NOW,
        raw_evidence={},
    )


def _quote(
    side: QuoteSide,
    notional: Decimal,
    *,
    token_amount: str,
    settlement_amount: str,
) -> ExecutionQuote:
    settlement = _settlement_reference()
    token = AssetRef(
        _SYNTH_CHAIN,
        _SYNTH_TOKEN,
        symbol="SYN",
        decimals=18,
    )
    if side is QuoteSide.BUY:
        input_asset = settlement.asset
        output_asset = token
        normalized_in = Decimal(settlement_amount)
        normalized_out = Decimal(token_amount)
        route_from, route_to = _SYNTH_SETTLEMENT, _SYNTH_TOKEN
    else:
        input_asset = token
        output_asset = settlement.asset
        normalized_in = Decimal(token_amount)
        normalized_out = Decimal(settlement_amount)
        route_from, route_to = _SYNTH_TOKEN, _SYNTH_SETTLEMENT

    return ExecutionQuote(
        chain_id=_SYNTH_CHAIN,
        token_address=_SYNTH_TOKEN,
        side=side,
        input_asset=input_asset,
        output_asset=output_asset,
        requested_notional_usd=notional,
        raw_amount_in=1,
        raw_amount_out=1,
        normalized_amount_in=normalized_in,
        normalized_amount_out=normalized_out,
        input_decimals=18,
        output_decimals=18,
        source="PUBLIC_SYNTHETIC_ROUTER",
        quoted_at=_SYNTH_NOW,
        settlement_reference=settlement,
        status=QuoteStatus.QUOTE_OK,
        fee_cost_usd=Decimal("0.05"),
        gas_cost_usd=Decimal("0.02"),
        evidence=QuoteEvidence(
            request_params={},
            response_fields={},
            route=(
                RouteLeg(
                    tool="synthetic-router",
                    from_asset=route_from,
                    to_asset=route_to,
                ),
            ),
        ),
    )


def _radar_r3_case() -> dict[str, Any]:
    quotes = [
        _quote(QuoteSide.BUY, _SMALL, token_amount="0.8", settlement_amount="100"),
        _quote(QuoteSide.BUY, _LARGE, token_amount="7", settlement_amount="1000"),
        _quote(QuoteSide.SELL, _SMALL, token_amount="0.8", settlement_amount="90"),
        _quote(QuoteSide.SELL, _LARGE, token_amount="7", settlement_amount="880"),
    ]
    reference = _synthetic_reference()
    r2_policy = GapComparisonPolicy(max_evidence_skew_seconds=300)
    observations = [
        compute_directional_gap(reference, quote, policy=r2_policy)
        for quote in quotes
    ]
    snapshot = build_liquidity_snapshot(
        asset=_synthetic_asset(),
        asset_key=AssetKey(_SYNTH_CHAIN, _SYNTH_TOKEN),
        quotes=quotes,
        gap_observations=observations,
        policy=LiquidityComparisonPolicy(max_quote_pair_skew_seconds=120),
        git_head="PUBLIC_SYNTHETIC_CORPUS_V1",
        produced_at=_SYNTH_NOW,
    )
    evidence = snapshot.to_evidence_dict()
    report = validate_radar_r3_evidence(evidence)
    if not report.passed:
        raise RuntimeError(
            "public Radar R3 validation failed: "
            f"{[failure.invariant_id for failure in report.failures]}"
        )
    claim = build_radar_r3_validation_claim(evidence, report)
    lineage = evidence["lineage"]
    envelope = build_evidence_envelope(
        surface="FINCO_RADAR_R3",
        evidence_type="RADAR_R3_PUBLIC_VALIDATION",
        payload=claim,
        authority_refs=(
            str(lineage["r1CanonicalIdentity"]),
            str(lineage["r0FormulaAuthority"]),
            str(lineage["r2ObservationAuthority"]),
            "finco_radar.liquidity.engine.build_liquidity_snapshot",
            "finco_protocol.verification.radar_r3.validate_radar_r3_evidence",
        ),
    )
    return {
        "caseId": "radar-r3-synthetic-liquidity",
        "surface": "FINCO_RADAR_R3",
        "synthetic": True,
        "envelope": envelope.as_dict(),
    }


def build_public_validation_corpus() -> dict[str, Any]:
    """Build the complete deterministic cross-surface public corpus."""

    body = {
        "schema": PUBLIC_CORPUS_SCHEMA,
        "sanitization": (
            "Synthetic-only corpus: no client, workbook, wallet, company, "
            "person or jurisdiction-specific calibration data."
        ),
        "cases": [
            _model_case("model-solar-base", "Solar", create_generic_solar_reference),
            _model_case("model-wind-base", "Wind", create_generic_wind_reference),
            _radar_r3_case(),
        ],
    }
    return {
        **body,
        "corpusSha256": canonical_sha256(body),
    }


def verify_public_validation_corpus(corpus: Mapping[str, Any]) -> bool:
    """Verify exact v1 case contract, nested envelopes and corpus digest."""

    if corpus.get("schema") != PUBLIC_CORPUS_SCHEMA:
        return False
    cases = corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != len(_EXPECTED_V1_CASES):
        return False

    for case, (expected_id, expected_surface, expected_evidence_type) in zip(
        cases, _EXPECTED_V1_CASES
    ):
        if not isinstance(case, Mapping):
            return False
        if case.get("caseId") != expected_id:
            return False
        if case.get("surface") != expected_surface:
            return False
        if case.get("synthetic") is not True:
            return False
        envelope = case.get("envelope")
        if not isinstance(envelope, Mapping):
            return False
        if envelope.get("surface") != expected_surface:
            return False
        if envelope.get("evidenceType") != expected_evidence_type:
            return False
        if not verify_evidence_envelope(envelope):
            return False

    body = {
        "schema": corpus.get("schema"),
        "sanitization": corpus.get("sanitization"),
        "cases": cases,
    }
    return corpus.get("corpusSha256") == canonical_sha256(body)

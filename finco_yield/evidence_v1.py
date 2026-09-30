from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Any

from .freshness import evaluate_freshness
from .registry import CanonicalOpportunity
from .underwriting import decompose, run_scenario


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite Decimal is not canonical")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime is not canonical")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _primitive(value: Any) -> Any:
    if is_dataclass(value):
        return _primitive(asdict(value))
    if isinstance(value, dict):
        return {str(k): _primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(v) for v in value]
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime):
        return _datetime(value)
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class YieldEvidenceV1:
    identity: dict[str, Any]
    observation: dict[str, Any]
    normalized_inputs: dict[str, Any]
    assumptions: dict[str, Any]
    outputs: dict[str, Any]
    schema_version: str = "YIELD_EVIDENCE_V1"
    calculation_version: str = "yield-calc-1.0"

    @property
    def canonical_input_hash(self) -> str:
        return canonical_hash({
            "schema_version": self.schema_version,
            "calculation_version": self.calculation_version,
            "identity": self.identity,
            "observation": self.observation,
            "normalized_inputs": self.normalized_inputs,
            "assumptions": self.assumptions,
        })

    @property
    def canonical_output_hash(self) -> str:
        return canonical_hash({
            "schema_version": self.schema_version,
            "calculation_version": self.calculation_version,
            "canonical_input_hash": self.canonical_input_hash,
            "outputs": self.outputs,
        })


def build_evidence(opportunity: CanonicalOpportunity, *, assumptions: dict[str, Any] | None = None) -> YieldEvidenceV1:
    assumptions = assumptions or {}
    decomposition = decompose(opportunity.observation)
    freshness = evaluate_freshness(
        __import__("finco_yield.schema", fromlist=["SourceReference"]).SourceReference(
            source_type=opportunity.source_type,
            uri=opportunity.source_uri,
            observed_at=opportunity.observed_at,
            block_number=opportunity.block_number,
            adapter=opportunity.adapter,
            adapter_version=opportunity.adapter_version,
        )
    )
    scenarios = []
    for name in ("REWARDS_OFF", "REWARDS_MINUS_50", "EXIT_STRESS", "GAS_SHOCK"):
        result = run_scenario(name, opportunity.observation)
        scenarios.append({"name": result.name, "state": result.state.value, "apy": result.apy, "note": result.note})
    obs = opportunity.observation
    return YieldEvidenceV1(
        identity={
            "opportunity_uid": opportunity.uid,
            "snapshot_version": opportunity.snapshot_version,
            "chain_id": opportunity.chain_id,
            "protocol": opportunity.protocol,
            "product_type": opportunity.product_type,
            "contract_address": opportunity.contract_address,
            "underlying_assets": [opportunity.underlying_address],
            "share_token": opportunity.share_token,
        },
        observation={
            "source_authority": opportunity.source_type.value,
            "source_uri": opportunity.source_uri,
            "observed_at": opportunity.observed_at,
            "block_number": opportunity.block_number,
            "adapter": opportunity.adapter,
            "adapter_version": opportunity.adapter_version,
            "freshness_state": freshness.state,
        },
        normalized_inputs={
            "tvl_usd": obs.tvl_usd,
            "gross_apy": obs.apy_total,
            "base_apy": obs.apy_base,
            "rewards_apy": obs.apy_rewards,
            "intrinsic_apy": obs.apy_intrinsic,
            "annualized_costs": obs.annualized_costs,
            "withdrawal_type": obs.withdrawal_type,
            "capacity_usd": obs.capacity_usd,
            "fee_bps": obs.fee_bps,
            "slippage_bps": obs.slippage_bps,
            "queue_seconds": obs.queue_seconds,
        },
        assumptions=assumptions,
        outputs={
            "gross_apy": decomposition.gross_apy,
            "component_state": decomposition.state.value,
            "organic_share": decomposition.organic_share,
            "reward_dependency": decomposition.reward_dependency,
            "reward_off_apy": decomposition.reward_off_apy,
            "scenario_outputs": scenarios,
        },
    )


@dataclass(frozen=True)
class YieldPreTradeEvidenceV1:
    opportunity_uid: str
    opportunity_snapshot_version: str
    underwriting_input_hash: str
    underwriting_output_hash: str
    quote_id: str
    created_at: datetime
    expires_at: datetime
    chain_id: int
    input_token: str
    amount: int
    receiver: str
    destination: str
    expected_output: int | None
    provider: str
    route_hash: str
    approval_hash: str
    fee_slippage_hash: str
    schema_version: str = "YIELD_PRE_TRADE_EVIDENCE_V1"

    @property
    def record_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class YieldPostTradeReceiptV1:
    tx_hash: str
    block_number: int
    opportunity_uid: str
    opportunity_snapshot_version: str
    input_amount: int
    actual_received_shares: int
    quoted_expected_shares: int | None
    effective_slippage_bps: Decimal | None
    timestamp: datetime
    schema_version: str = "YIELD_POST_TRADE_RECEIPT_V1"

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self)

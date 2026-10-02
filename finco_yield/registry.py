from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
import json

from .identity import YieldIdentity, canonical_address
from .schema import EvidenceConfidence, YieldObservation


class RegistryError(ValueError):
    pass


class YieldSupportState(str, Enum):
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    READ_ONLY_RESEARCH = "READ_ONLY_RESEARCH"
    EXECUTION_CANDIDATE = "EXECUTION_CANDIDATE"
    DIRECT_SUPPORTED = "DIRECT_SUPPORTED"


@dataclass(frozen=True)
class CanonicalOpportunity:
    uid: str
    name: str
    chain_id: int
    protocol: str
    product_type: str
    contract_address: str
    underlying_symbol: str
    underlying_address: str
    share_token: str
    observation: YieldObservation
    source_type: EvidenceConfidence
    source_uri: str
    observed_at: datetime
    block_number: int | None
    adapter: str
    adapter_version: str
    support_state: YieldSupportState
    snapshot_version: str = "research-y0"
    # Provenance of the observation values: SOURCE_OBSERVED (collected from a
    # live provider), REFERENCE_FIXTURE (bundled research sample), or
    # UNSPECIFIED (constructed directly, e.g. tests).  reference != live.
    data_origin: str = "UNSPECIFIED"
    provider: str | None = None
    fetched_at: datetime | None = None
    observation_hash: str | None = None

    @property
    def allowed_execution_methods(self) -> tuple[str, ...]:
        if self.product_type == "morpho_vault":
            return ("DIRECT_ERC4626", "ZERO_X_THEN_DIRECT", "ENSO")
        return ()


@dataclass(frozen=True)
class CanonicalExecutionBinding:
    opportunity_uid: str
    snapshot_version: str
    chain_id: int
    protocol: str
    product_type: str
    contract_address: str
    underlying_asset: str
    share_token: str
    allowed_execution_methods: tuple[str, ...]


def _dec(value) -> Decimal | None:
    return None if value is None or value == "" else Decimal(str(value))


def _dt(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise RegistryError("malformed registry timestamp") from exc
    if parsed.tzinfo is None:
        raise RegistryError("registry timestamp must be timezone-aware")
    return parsed


def _support_state(source_type: EvidenceConfidence) -> YieldSupportState:
    if source_type == EvidenceConfidence.DIRECT_ONCHAIN:
        return YieldSupportState.EXECUTION_CANDIDATE
    if source_type == EvidenceConfidence.NATIVE_ENRICHED:
        return YieldSupportState.READ_ONLY_RESEARCH
    return YieldSupportState.DISCOVERY_ONLY


def _from_row(row: dict, *, default_origin: str = "UNSPECIFIED") -> CanonicalOpportunity:
    identity = YieldIdentity(
        chain_id=int(row["chain_id"]),
        protocol=str(row["protocol"]),
        product_type=str(row["product_type"]),
        contract_address=canonical_address(str(row["contract_address"])),
        underlying_assets=(canonical_address(str(row["underlying_address"])),),
        share_token=canonical_address(str(row["share_token"])),
    )
    from .identity import yield_opportunity_uid
    canonical = identity.canonical()
    uid = yield_opportunity_uid(identity)
    source_type = EvidenceConfidence(str(row["source_type"]))
    return CanonicalOpportunity(
        uid=uid,
        name=str(row["name"]),
        chain_id=identity.chain_id,
        protocol=canonical["protocol"],
        product_type=canonical["product_type"],
        contract_address=canonical["contract_address"],
        underlying_symbol=str(row["underlying_symbol"]),
        underlying_address=canonical["underlying_assets"][0],
        share_token=canonical["share_token"],
        observation=YieldObservation(
            tvl_usd=_dec(row.get("tvl_usd")),
            apy_total=_dec(row.get("apy_total")),
            apy_base=_dec(row.get("apy_base")),
            apy_rewards=_dec(row.get("apy_rewards")),
            apy_intrinsic=_dec(row.get("apy_intrinsic")),
            withdrawal_type=row.get("withdrawal_type"),
        ),
        source_type=source_type,
        source_uri=str(row["source_uri"]),
        observed_at=_dt(row["observed_at"]),
        block_number=int(row["block_number"]) if row.get("block_number") is not None else None,
        adapter=str(row.get("adapter") or "unknown"),
        adapter_version=str(row.get("adapter_version") or "unknown"),
        support_state=_support_state(source_type),
        data_origin=str(row.get("data_origin") or default_origin),
        provider=(str(row["provider"]) if row.get("provider") else None),
        fetched_at=(_dt(row["fetched_at"]) if row.get("fetched_at") else None),
        observation_hash=(str(row["history_observation_hash"]) if row.get("history_observation_hash") else None),
    )


class YieldRegistry:
    """Exact UID registry. Names, tickers and URL slugs are display-only."""

    def __init__(self, opportunities: list[CanonicalOpportunity]):
        self._by_uid: dict[str, CanonicalOpportunity] = {}
        for opportunity in opportunities:
            if opportunity.uid in self._by_uid:
                raise RegistryError(f"duplicate yield opportunity uid: {opportunity.uid}")
            self._by_uid[opportunity.uid] = opportunity

    def all(self) -> tuple[CanonicalOpportunity, ...]:
        return tuple(self._by_uid.values())

    def resolve(self, opportunity_uid: str) -> CanonicalOpportunity:
        try:
            return self._by_uid[opportunity_uid]
        except KeyError as exc:
            raise RegistryError("unknown yield opportunity uid") from exc

    @staticmethod
    def _binding(opportunity: CanonicalOpportunity) -> CanonicalExecutionBinding:
        return CanonicalExecutionBinding(
            opportunity_uid=opportunity.uid,
            snapshot_version=opportunity.snapshot_version,
            chain_id=opportunity.chain_id,
            protocol=opportunity.protocol,
            product_type=opportunity.product_type,
            contract_address=opportunity.contract_address,
            underlying_asset=opportunity.underlying_address,
            share_token=opportunity.share_token,
            allowed_execution_methods=opportunity.allowed_execution_methods,
        )

    def canonical_binding(self, opportunity_uid: str) -> CanonicalExecutionBinding:
        """Resolve canonical identity for a direct block-bound revalidation attempt.

        READ_ONLY_RESEARCH may resolve here because this method authorizes no
        execution by itself. A direct execution plan must additionally pass a
        fresh explicit block-bound ERC-4626 observation in execution.py.
        """
        opportunity = self.resolve(opportunity_uid)
        if opportunity.support_state == YieldSupportState.DISCOVERY_ONLY:
            raise RegistryError("opportunity is discovery-only")
        return self._binding(opportunity)

    def execution_binding(self, opportunity_uid: str) -> CanonicalExecutionBinding:
        """Resolve a binding already eligible for routed execution planning.

        NATIVE_ENRICHED / READ_ONLY_RESEARCH is intentionally rejected here.
        """
        opportunity = self.resolve(opportunity_uid)
        if opportunity.support_state not in {
            YieldSupportState.EXECUTION_CANDIDATE,
            YieldSupportState.DIRECT_SUPPORTED,
        }:
            raise RegistryError("opportunity is not an execution candidate")
        return self._binding(opportunity)


def bundled_reference_rows() -> list[dict]:
    """Raw rows of the bundled research sample (a REFERENCE fixture)."""
    path = Path(__file__).resolve().parent / "data" / "live_opportunities.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundled_registry() -> YieldRegistry:
    """The bundled sample.  Rows are marked REFERENCE_FIXTURE: loadable does
    not mean live."""
    return YieldRegistry([
        _from_row(row, default_origin="REFERENCE_FIXTURE")
        for row in bundled_reference_rows()
    ])

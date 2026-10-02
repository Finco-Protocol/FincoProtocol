"""Explicit, source-specific live-data adapters for FINCO Yield.

No generic web scraping.  Each adapter documents its endpoint, its identity
keys and exactly which source fields map to which FINCO fields.

Failure semantics (never silent zero substitution):

* transport / HTTP / JSON problems -> typed ``SourceProviderError`` code for
  that target; the target simply has NO new observation (UNAVAILABLE), it is
  never recorded as APY 0 / TVL 0 / an empty universe;
* a response that arrives but violates the contract (identity mismatch,
  wrong shape, non-finite number, empty record) -> REJECTED, counted
  separately from transport failures;
* one failing target never suppresses the others.

Provider text is never surfaced: only fixed public codes leave this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
from typing import Any, Callable, Protocol

import httpx

from .identity import canonical_address
from .observation import (
    OBSERVED_AT_FETCHED_AT,
    ObservationRejected,
    SourceObservation,
)
from .registry import CanonicalOpportunity
from .schema import EvidenceConfidence

DEFAULT_MORPHO_API_URL = "https://api.morpho.org/graphql"
DEFAULT_TIMEOUT_SECONDS = 8.0
_MAX_TIMEOUT_SECONDS = 60.0


class SourceProviderError(RuntimeError):
    """Typed, sanitized provider failure.  ``code`` is the only public detail."""

    def __init__(self, code: str, rejected: bool = False):
        super().__init__(code)
        self.code = code
        # rejected=True: a response ARRIVED but violated the contract.
        self.rejected = rejected


@dataclass(frozen=True)
class SourceTarget:
    """One FINCO-known opportunity a provider is asked to observe."""

    uid: str
    chain_id: int
    protocol: str
    product_type: str
    contract_address: str
    underlying_address: str
    share_token: str
    underlying_symbol: str
    name: str
    source_uri: str

    @classmethod
    def from_opportunity(cls, o: CanonicalOpportunity) -> "SourceTarget":
        return cls(o.uid, o.chain_id, o.protocol, o.product_type, o.contract_address,
                   o.underlying_address, o.share_token, o.underlying_symbol, o.name,
                   o.source_uri)


@dataclass(frozen=True)
class TargetFailure:
    uid: str
    code: str
    rejected: bool


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    targets_attempted: int
    observations: tuple[SourceObservation, ...]
    failures: tuple[TargetFailure, ...]

    @property
    def status(self) -> str:
        if not self.observations:
            return "FAILED"
        return "PARTIAL" if self.failures else "SUCCEEDED"


class SourceAdapter(Protocol):
    provider_id: str

    def supports(self, target: SourceTarget) -> bool: ...

    def fetch(self, targets: list[SourceTarget]) -> ProviderResult: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def source_timeout_seconds(env: dict[str, str] | None = None) -> float:
    raw = (env if env is not None else os.environ).get("FINCO_YIELD_SOURCE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    if not (0 < value <= _MAX_TIMEOUT_SECONDS):
        return DEFAULT_TIMEOUT_SECONDS
    return value


def _http_failure(status: int) -> SourceProviderError:
    if status == 429:
        return SourceProviderError("SOURCE_RATE_LIMITED")
    if status in (401, 403):
        return SourceProviderError("SOURCE_ACCESS_DENIED")
    if status >= 500:
        return SourceProviderError("SOURCE_UPSTREAM_UNAVAILABLE")
    return SourceProviderError("SOURCE_HTTP_ERROR")


def _post_json(client: Any, url: str, body: dict, timeout: float) -> dict:
    """One bounded POST; only typed, sanitized failures escape."""
    try:
        response = client.post(
            url, json=body, timeout=timeout,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
    except httpx.TimeoutException:
        raise SourceProviderError("SOURCE_TIMEOUT") from None
    except Exception:  # transport errors; text may embed URLs/credentials
        raise SourceProviderError("SOURCE_NETWORK_ERROR") from None
    status = getattr(response, "status_code", None)
    if not isinstance(status, int) or status >= 400:
        raise _http_failure(status if isinstance(status, int) else 500)
    try:
        payload = response.json()
    except Exception:
        raise SourceProviderError("SOURCE_MALFORMED_JSON") from None
    if not isinstance(payload, dict):
        raise SourceProviderError("SOURCE_MALFORMED_JSON")
    return payload


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    """None -> None (UNAVAILABLE).  Booleans/strings/non-finite are rejected."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SourceProviderError("SOURCE_SCHEMA_REJECTED", rejected=True)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise SourceProviderError("SOURCE_SCHEMA_REJECTED", rejected=True) from None
    if not number.is_finite():
        raise SourceProviderError("SOURCE_SCHEMA_REJECTED", rejected=True)
    return number


# ---------------------------------------------------------------------------
# Morpho (Morpho Blue GraphQL API)
# ---------------------------------------------------------------------------

MORPHO_QUERY = (
    "query VaultState($address: String!, $chainId: Int!) {"
    " vaultByAddress(address: $address, chainId: $chainId) {"
    " address name symbol asset { address symbol } chain { id }"
    " state { apy netApy totalAssetsUsd } } }"
)


class MorphoGraphQLAdapter:
    """Observes known Morpho vaults one exact (chain, address) at a time.

    Endpoint: ``POST https://api.morpho.org/graphql`` (public, no credential).
    Identity keys: vault ``address`` + ``chain.id`` + ``asset.address`` -- all
    three must equal the FINCO reference identity or the response is rejected.

    Field mapping (APY values are fractions, 0.04 == 4%):

    * ``state.netApy``         -> ``apy_total``  (depositor-facing net APY)
    * ``state.totalAssetsUsd`` -> ``tvl_usd``
    * ``state.apy``            -> kept ONLY in ``source_native`` (gross native
      APY); never mapped onto ``apy_base``.
    * ``apy_base`` / ``apy_rewards`` stay ``None`` (UNAVAILABLE): the queried
      fields do not prove a base/rewards split and FINCO never derives one by
      subtraction.

    The query requests no source timestamp, so ``observed_at`` follows the
    documented ``FETCHED_AT`` policy (recorded on every observation).
    """

    provider_id = "morpho_graphql"
    adapter_name = "morpho-graphql"
    adapter_version = "morpho-graphql-v1"

    def __init__(
        self,
        *,
        url: str | None = None,
        client: Any = None,
        timeout: float | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.url = (url or os.getenv("FINCO_YIELD_MORPHO_API_URL", "").strip()
                    or DEFAULT_MORPHO_API_URL)
        if not self.url.lower().startswith("https://"):
            # Provider traffic is always TLS; a misconfigured URL is a config
            # error, not something to send to the network.
            raise ValueError("FINCO_YIELD_MORPHO_API_URL must be an https:// URL")
        self.timeout = timeout if timeout is not None else source_timeout_seconds()
        self.client = client or httpx.Client(timeout=self.timeout)
        self.clock = clock

    def supports(self, target: SourceTarget) -> bool:
        return target.protocol == "morpho" and target.product_type == "morpho_vault"

    # -- one target -------------------------------------------------------
    def _observe(self, target: SourceTarget) -> SourceObservation:
        payload = _post_json(
            self.client, self.url,
            {"query": MORPHO_QUERY,
             "variables": {"address": target.contract_address, "chainId": target.chain_id}},
            self.timeout,
        )
        fetched_at = self.clock()
        if payload.get("errors"):
            raise SourceProviderError("SOURCE_GRAPHQL_ERROR")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SourceProviderError("SOURCE_SCHEMA_REJECTED", rejected=True)
        vault = data.get("vaultByAddress")
        if vault is None:
            raise SourceProviderError("SOURCE_RECORD_NOT_FOUND")
        if not isinstance(vault, dict):
            raise SourceProviderError("SOURCE_SCHEMA_REJECTED", rejected=True)

        # -- identity collision protection: exact keys, never names/symbols
        asset = vault.get("asset")
        chain = vault.get("chain")
        state = vault.get("state")
        if not isinstance(asset, dict) or not isinstance(chain, dict) or not isinstance(state, dict):
            raise SourceProviderError("SOURCE_SCHEMA_REJECTED", rejected=True)
        try:
            same_vault = canonical_address(str(vault.get("address"))) == target.contract_address
            same_asset = canonical_address(str(asset.get("address"))) == target.underlying_address
        except ValueError:
            raise SourceProviderError("SOURCE_IDENTITY_MISMATCH", rejected=True) from None
        chain_id = chain.get("id")
        if (not same_vault or not same_asset or isinstance(chain_id, bool)
                or chain_id != target.chain_id):
            raise SourceProviderError("SOURCE_IDENTITY_MISMATCH", rejected=True)

        net_apy = _optional_decimal(state.get("netApy"), "netApy")
        tvl = _optional_decimal(state.get("totalAssetsUsd"), "totalAssetsUsd")
        native = {
            "endpoint": "morpho_graphql.vaultByAddress",
            "vault_address": target.contract_address,
            "chain_id": target.chain_id,
            "state.netApy": state.get("netApy"),
            "state.apy": state.get("apy"),
            "state.totalAssetsUsd": state.get("totalAssetsUsd"),
        }
        observation = SourceObservation(
            provider=self.provider_id,
            source_record_id=f"{target.chain_id}:{target.contract_address}",
            chain_id=target.chain_id,
            protocol=target.protocol,
            product_type=target.product_type,
            contract_address=target.contract_address,
            underlying_address=target.underlying_address,
            share_token=target.share_token,
            underlying_symbol=target.underlying_symbol,
            name=target.name,
            fetched_at=fetched_at,
            observed_at=fetched_at,
            observed_at_policy=OBSERVED_AT_FETCHED_AT,
            source_uri=target.source_uri,
            adapter=self.adapter_name,
            adapter_version=self.adapter_version,
            source_type=EvidenceConfidence.NATIVE_ENRICHED,
            tvl_usd=tvl,
            apy_total=net_apy,
            apy_base=None,
            apy_rewards=None,
            source_native=native,
            derived={
                "apy_total": "passthrough of state.netApy (fraction)",
                "tvl_usd": "passthrough of state.totalAssetsUsd (USD)",
                "apy_base": "UNAVAILABLE: not proven by queried fields",
                "apy_rewards": "UNAVAILABLE: not proven by queried fields",
                "observed_at": "FETCHED_AT policy: no source timestamp requested",
            },
        )
        try:
            return observation.validate()
        except ObservationRejected as exc:
            raise SourceProviderError(exc.code, rejected=True) from None

    # -- all targets -------------------------------------------------------
    def fetch(self, targets: list[SourceTarget]) -> ProviderResult:
        observations: list[SourceObservation] = []
        failures: list[TargetFailure] = []
        attempted = 0
        for target in targets:
            if not self.supports(target):
                continue
            attempted += 1
            try:
                observations.append(self._observe(target))
            except SourceProviderError as exc:
                failures.append(TargetFailure(target.uid, exc.code, exc.rejected))
            except Exception:  # an adapter bug must not take down the run
                failures.append(TargetFailure(target.uid, "SOURCE_ADAPTER_ERROR", False))
        return ProviderResult(self.provider_id, attempted, tuple(observations), tuple(failures))

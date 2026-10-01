"""Canonical $FINCO balance observation.

    verified wallet -> exact canonical deployment -> balanceOf(wallet) -> normalise with the deployment's
    decimals -> BalanceObservation

An observation is either OBSERVED (a real non-negative balance, which may legitimately be ZERO) or one of
several explicit non-observed statuses. A missing, unavailable, failed or unconfigured balance is NEVER
converted into numeric zero: ``balance_raw`` / ``normalized_balance`` stay ``None`` unless the chain really
answered. All RPC access is read-only (eth_chainId, eth_call). No key, signing or transaction is involved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Mapping, Protocol

from app.protocol.token_balance import _decode_uint, _encode_balanceof, _rpc_call
from app.protocol.token_config import _validate_hex_address
from app.protocol.token_deployments import DeploymentRegistry, ResolutionStatus, TokenDeployment

logger = logging.getLogger(__name__)

SOURCE_JSON_RPC = "ERC20_JSON_RPC_READ_ONLY"


class ObservationStatus(str, Enum):
    OBSERVED = "OBSERVED"
    DEPLOYMENT_NOT_CONFIGURED = "DEPLOYMENT_NOT_CONFIGURED"
    DEPLOYMENT_MALFORMED = "DEPLOYMENT_MALFORMED"
    CONFLICTING_DEPLOYMENTS = "CONFLICTING_DEPLOYMENTS"
    AMBIGUOUS_DEPLOYMENT = "AMBIGUOUS_DEPLOYMENT"
    UNSUPPORTED_CHAIN = "UNSUPPORTED_CHAIN"          # no provider for that chain / deployment not on chain
    RPC_UNAVAILABLE = "RPC_UNAVAILABLE"
    CHAIN_ID_MISMATCH = "CHAIN_ID_MISMATCH"
    BALANCE_UNAVAILABLE = "BALANCE_UNAVAILABLE"
    WALLET_MALFORMED = "WALLET_MALFORMED"


@dataclass(frozen=True)
class RawBalance:
    """What a TokenBalanceReader returns: a raw base-unit balance or an explicit failure status."""
    status: ObservationStatus
    balance_raw: int | None = None
    block_number: int | None = None
    observed_at: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BalanceObservation:
    status: ObservationStatus
    wallet_address: str | None
    chain_id: int | None
    contract_address: str | None
    decimals: int | None
    balance_raw: int | None
    normalized_balance: Decimal | None
    block_number: int | None
    observed_at: datetime | None
    source: str
    reason: str | None = None

    @property
    def observed(self) -> bool:
        return self.status is ObservationStatus.OBSERVED and self.balance_raw is not None

    @property
    def observed_zero(self) -> bool:
        return self.observed and self.balance_raw == 0


class TokenBalanceReader(Protocol):
    async def get_balance(self, chain_id: int, contract_address: str, wallet_address: str) -> RawBalance: ...


class JsonRpcTokenBalanceReader:
    """Read-only ERC-20 ``balanceOf`` over server-side JSON-RPC, one provider URL per chain id.

    Provider URLs are server-side configuration only and are never returned in any result.
    """

    def __init__(self, rpc_urls: Mapping[int, str]) -> None:
        self._rpc_urls = {int(k): v for k, v in rpc_urls.items() if isinstance(v, str) and v.strip()}

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "JsonRpcTokenBalanceReader":
        import os
        env = os.environ if environ is None else environ
        urls: dict[int, str] = {}
        prefix = "FINCO_TOKEN_RPC_URL_"
        for key, value in env.items():
            if key.startswith(prefix) and key[len(prefix):].isdigit() and value.strip():
                urls[int(key[len(prefix):])] = value.strip()
        return cls(urls)

    async def get_balance(self, chain_id: int, contract_address: str, wallet_address: str) -> RawBalance:
        rpc_url = self._rpc_urls.get(chain_id)
        if rpc_url is None:
            return RawBalance(ObservationStatus.UNSUPPORTED_CHAIN, reason="NO_PROVIDER_FOR_CHAIN")
        observed_at = datetime.now(timezone.utc)
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                try:
                    actual = int(await _rpc_call(client, rpc_url, "eth_chainId", []), 16)
                except Exception:
                    return RawBalance(ObservationStatus.RPC_UNAVAILABLE, reason="eth_chainId_failed")
                if actual != chain_id:
                    return RawBalance(ObservationStatus.CHAIN_ID_MISMATCH, reason="PROVIDER_CHAIN_DIFFERS")
                try:
                    result = await _rpc_call(client, rpc_url, "eth_call", [
                        {"to": contract_address, "data": _encode_balanceof(wallet_address)}, "latest"])
                except Exception:
                    return RawBalance(ObservationStatus.BALANCE_UNAVAILABLE, reason="balanceOf_failed")
                # A well-formed answer is exactly one 32-byte word; "0x" (no contract code) is NOT zero.
                if not isinstance(result, str) or len(result) != 66 or not result.startswith("0x"):
                    return RawBalance(ObservationStatus.BALANCE_UNAVAILABLE, reason="balanceOf_malformed")
                balance = _decode_uint(result)
                if balance is None:
                    return RawBalance(ObservationStatus.BALANCE_UNAVAILABLE, reason="balanceOf_malformed")
                block: int | None = None
                try:
                    block = int(await _rpc_call(client, rpc_url, "eth_blockNumber", []), 16)
                except Exception:
                    pass
                return RawBalance(ObservationStatus.OBSERVED, balance, block, observed_at)
        except Exception:
            logger.warning("token balance read failed")
            return RawBalance(ObservationStatus.RPC_UNAVAILABLE, reason="unexpected_error")


_RESOLUTION_TO_STATUS = {
    ResolutionStatus.NOT_CONFIGURED: ObservationStatus.DEPLOYMENT_NOT_CONFIGURED,
    ResolutionStatus.MALFORMED: ObservationStatus.DEPLOYMENT_MALFORMED,
    ResolutionStatus.CONFLICT: ObservationStatus.CONFLICTING_DEPLOYMENTS,
    ResolutionStatus.AMBIGUOUS: ObservationStatus.AMBIGUOUS_DEPLOYMENT,
    ResolutionStatus.NOT_FOUND: ObservationStatus.DEPLOYMENT_NOT_CONFIGURED,
}


def _not_observed(status: ObservationStatus, *, wallet: str | None, deployment: TokenDeployment | None,
                  reason: str | None, source: str = SOURCE_JSON_RPC) -> BalanceObservation:
    return BalanceObservation(
        status=status, wallet_address=wallet,
        chain_id=deployment.chain_id if deployment else None,
        contract_address=deployment.contract_address if deployment else None,
        decimals=deployment.decimals if deployment else None,
        balance_raw=None, normalized_balance=None, block_number=None, observed_at=None,
        source=source, reason=reason)


async def observe_finco_balance(
    wallet_address: str | None,
    registry: DeploymentRegistry,
    reader: TokenBalanceReader,
    *,
    chain_id: int | None = None,
) -> BalanceObservation:
    """Observe the wallet's balance on the exact canonical $FINCO deployment (never a guess)."""
    wallet = _validate_hex_address(wallet_address or "")
    resolution = registry.resolve(chain_id)
    if not resolution.resolved:
        return _not_observed(_RESOLUTION_TO_STATUS[resolution.status], wallet=wallet, deployment=None,
                             reason=resolution.reason)
    deployment = resolution.deployment
    assert deployment is not None
    if wallet is None:
        return _not_observed(ObservationStatus.WALLET_MALFORMED, wallet=None, deployment=deployment,
                             reason="WALLET_ADDRESS_INVALID")
    try:
        raw = await reader.get_balance(deployment.chain_id, deployment.contract_address, wallet)
    except Exception:
        return _not_observed(ObservationStatus.RPC_UNAVAILABLE, wallet=wallet, deployment=deployment,
                             reason="READER_RAISED")
    if (raw.status is not ObservationStatus.OBSERVED or raw.balance_raw is None
            or isinstance(raw.balance_raw, bool) or not isinstance(raw.balance_raw, int)
            or raw.balance_raw < 0 or raw.observed_at is None
            or raw.observed_at.tzinfo is None or raw.observed_at.utcoffset() is None):
        status = raw.status if raw.status is not ObservationStatus.OBSERVED else ObservationStatus.BALANCE_UNAVAILABLE
        return _not_observed(status, wallet=wallet, deployment=deployment, reason=raw.reason or "BALANCE_NOT_PROVEN")
    return BalanceObservation(
        status=ObservationStatus.OBSERVED, wallet_address=wallet, chain_id=deployment.chain_id,
        contract_address=deployment.contract_address, decimals=deployment.decimals,
        balance_raw=raw.balance_raw,
        normalized_balance=Decimal(raw.balance_raw).scaleb(-deployment.decimals),
        block_number=raw.block_number, observed_at=raw.observed_at, source=SOURCE_JSON_RPC)

"""FINCO token deployment registry — chain-agnostic canonical identity for $FINCO.

Economic identity is the stable uid ``FINCO``. A *deployment* is an exact (chain_id, contract_address)
pair with ERC-20 decimals. Symbol / name are display-only and never take part in identity, equality or
resolution. Production ships with ZERO configured deployments; nothing here invents a contract, a chain
or a launch decision.

Deployments come from operator configuration (``FINCO_TOKEN_DEPLOYMENTS_JSON``) and must carry explicit
provenance, in the same spirit as ``app.verified.token_entitlement.ApprovedFincoDeployment``: a bare
environment value without provenance is rejected as malformed, so it can never silently activate access.

Resolution is fail-safe: zero deployments, any malformed entry, two conflicting entries for one chain, or
several active chains with no explicit selection all resolve to a non-RESOLVED status, never to a guess.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from app.protocol.token_config import _validate_hex_address

ECONOMIC_TOKEN_UID = "FINCO"
TOKEN_STANDARD_ERC20 = "ERC-20"
DEPLOYMENTS_ENV = "FINCO_TOKEN_DEPLOYMENTS_JSON"


class DeploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NOT_CONFIGURED = "NOT_CONFIGURED"          # zero active deployments
    MALFORMED = "MALFORMED"                    # any malformed entry poisons the registry (fail closed)
    CONFLICT = "CONFLICT"                      # same chain, different contract or decimals
    AMBIGUOUS = "AMBIGUOUS"                    # several active chains and no explicit selection
    NOT_FOUND = "NOT_FOUND"                    # explicit chain selected but not deployed


@dataclass(frozen=True)
class TokenDeployment:
    """One exact canonical deployment of the economic token. Display fields never affect identity."""
    chain_id: int
    contract_address: str
    decimals: int
    provenance: str
    token_standard: str = TOKEN_STANDARD_ERC20
    status: DeploymentStatus = DeploymentStatus.ACTIVE
    observed_at: datetime | None = None
    display_symbol: str | None = field(default=None, compare=False)
    display_name: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        address = _validate_hex_address(self.contract_address) if isinstance(self.contract_address, str) else None
        if (isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0
                or address is None
                or self.token_standard != TOKEN_STANDARD_ERC20
                or isinstance(self.decimals, bool) or not isinstance(self.decimals, int)
                or not 0 <= self.decimals <= 77
                or not isinstance(self.provenance, str) or not self.provenance.strip()
                or not isinstance(self.status, DeploymentStatus)):
            raise ValueError("exact ERC-20 deployment identity, decimals and provenance required")
        if self.observed_at is not None and (self.observed_at.tzinfo is None
                                             or self.observed_at.utcoffset() is None):
            raise ValueError("aware observed_at required")
        object.__setattr__(self, "contract_address", address)

    @property
    def identity(self) -> tuple[int, str]:
        return (self.chain_id, self.contract_address)


@dataclass(frozen=True)
class DeploymentResolution:
    status: ResolutionStatus
    deployment: TokenDeployment | None = None
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED and self.deployment is not None


def _parse_entry(raw: Any) -> TokenDeployment:
    if isinstance(raw, TokenDeployment):
        return raw
    if not isinstance(raw, Mapping):
        raise ValueError("deployment entry must be an object")
    try:
        status = DeploymentStatus(str(raw.get("status", DeploymentStatus.ACTIVE.value)).upper())
    except ValueError:
        raise ValueError("unknown deployment status") from None
    observed = raw.get("observed_at")
    return TokenDeployment(
        chain_id=raw.get("chain_id"),                      # type: ignore[arg-type]
        contract_address=raw.get("contract_address"),      # type: ignore[arg-type]
        decimals=raw.get("decimals"),                      # type: ignore[arg-type]
        provenance=raw.get("provenance"),                  # type: ignore[arg-type]
        token_standard=raw.get("token_standard", TOKEN_STANDARD_ERC20),
        status=status,
        observed_at=datetime.fromisoformat(observed) if isinstance(observed, str) else None,
        display_symbol=raw.get("display_symbol"),
        display_name=raw.get("display_name"),
    )


class DeploymentRegistry:
    """Immutable set of configured deployments of the economic token ``FINCO``."""

    economic_token_uid = ECONOMIC_TOKEN_UID

    def __init__(self, entries: Iterable[Any] = ()) -> None:
        parsed: list[TokenDeployment] = []
        errors = 0
        for raw in entries:
            try:
                parsed.append(_parse_entry(raw))
            except (ValueError, TypeError):
                errors += 1                                 # never echo the offending value
        self._malformed_entries = errors
        self._deployments = tuple(parsed)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "DeploymentRegistry":
        env = os.environ if environ is None else environ
        raw = (env.get(DEPLOYMENTS_ENV) or "").strip()
        if not raw:
            return cls(())                                  # production default: zero deployments
        try:
            data = json.loads(raw)
        except ValueError:
            return cls((object(),))                         # unparseable config = one malformed entry
        if not isinstance(data, list):
            return cls((object(),))
        return cls(data)

    @property
    def deployments(self) -> tuple[TokenDeployment, ...]:
        return self._deployments

    @property
    def malformed_entry_count(self) -> int:
        return self._malformed_entries

    def resolve(self, chain_id: int | None = None) -> DeploymentResolution:
        """Resolve the single canonical deployment, or say exactly why it cannot be resolved."""
        if self._malformed_entries:
            return DeploymentResolution(ResolutionStatus.MALFORMED, None, "DEPLOYMENT_CONFIG_MALFORMED")
        active = [d for d in self._deployments if d.status is DeploymentStatus.ACTIVE]
        if not active:
            return DeploymentResolution(ResolutionStatus.NOT_CONFIGURED, None, "NO_ACTIVE_DEPLOYMENT")
        by_chain: dict[int, set[tuple[str, int]]] = {}
        for d in active:
            by_chain.setdefault(d.chain_id, set()).add((d.contract_address, d.decimals))
        conflicted = {c for c, variants in by_chain.items() if len(variants) > 1}
        if chain_id is not None:
            if chain_id in conflicted:
                return DeploymentResolution(ResolutionStatus.CONFLICT, None, "CONFLICTING_DEPLOYMENTS")
            match = next((d for d in active if d.chain_id == chain_id), None)
            if match is None:
                return DeploymentResolution(ResolutionStatus.NOT_FOUND, None, "NO_DEPLOYMENT_ON_CHAIN")
            return DeploymentResolution(ResolutionStatus.RESOLVED, match)
        if conflicted:
            return DeploymentResolution(ResolutionStatus.CONFLICT, None, "CONFLICTING_DEPLOYMENTS")
        if len(by_chain) > 1:
            return DeploymentResolution(ResolutionStatus.AMBIGUOUS, None, "MULTIPLE_ACTIVE_CHAINS")
        return DeploymentResolution(ResolutionStatus.RESOLVED, active[0])

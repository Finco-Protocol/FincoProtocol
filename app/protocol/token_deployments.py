"""Deployment SELECTION over the canonical approved $FINCO deployments (no second registry).

The only authority for "which contract is $FINCO" is
``app.verified.token_entitlement.APPROVED_FINCO_DEPLOYMENTS`` — an independently approved, provenance-carrying
tuple that is empty in production today. This module adds nothing to that authority: it only SELECTS from it
(zero, one or several approved deployments; explicit chain selection; conflict / ambiguity detection) so the
resource policy layer can be multi-chain. Environment values can never create or extend a deployment: there is
no environment parsing here, and an RPC URL or a threshold is not identity.

Economic identity is the stable uid ``FINCO``. Symbol and name are never read.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

ECONOMIC_TOKEN_UID = "FINCO"


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NOT_CONFIGURED = "NOT_CONFIGURED"   # zero approved deployments (the production default)
    CONFLICT = "CONFLICT"               # same chain approved with different contract or decimals
    AMBIGUOUS = "AMBIGUOUS"             # several approved chains and no explicit selection
    NOT_FOUND = "NOT_FOUND"             # explicit chain selected but not approved


@dataclass(frozen=True)
class DeploymentResolution:
    status: ResolutionStatus
    deployment: "object | None" = None     # an ApprovedFincoDeployment when RESOLVED
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED and self.deployment is not None


def approved_deployments() -> tuple:
    """The live canonical approved set (read at call time so the single source stays authoritative)."""
    from app.verified import token_entitlement
    return tuple(token_entitlement.APPROVED_FINCO_DEPLOYMENTS)


def resolve_approved_deployment(chain_id: int | None = None,
                                approved: Iterable | None = None) -> DeploymentResolution:
    """Select the single canonical deployment, or say exactly why none can be selected."""
    entries = tuple(approved_deployments() if approved is None else approved)
    if not entries:
        return DeploymentResolution(ResolutionStatus.NOT_CONFIGURED, None, "NO_APPROVED_DEPLOYMENT")
    by_chain: dict[int, set[tuple[str, int]]] = {}
    for entry in entries:
        by_chain.setdefault(entry.chain_id, set()).add((entry.token_address, entry.decimals))
    conflicted = {chain for chain, variants in by_chain.items() if len(variants) > 1}
    if chain_id is not None:
        if chain_id in conflicted:
            return DeploymentResolution(ResolutionStatus.CONFLICT, None, "CONFLICTING_DEPLOYMENTS")
        match = next((e for e in entries if e.chain_id == chain_id), None)
        if match is None:
            return DeploymentResolution(ResolutionStatus.NOT_FOUND, None, "NO_APPROVED_DEPLOYMENT_ON_CHAIN")
        return DeploymentResolution(ResolutionStatus.RESOLVED, match)
    if conflicted:
        return DeploymentResolution(ResolutionStatus.CONFLICT, None, "CONFLICTING_DEPLOYMENTS")
    if len(by_chain) > 1:
        return DeploymentResolution(ResolutionStatus.AMBIGUOUS, None, "MULTIPLE_APPROVED_CHAINS")
    return DeploymentResolution(ResolutionStatus.RESOLVED, entries[0])

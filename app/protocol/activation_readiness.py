"""$FINCO activation readiness — a read-only checklist, never an activation.

Question answered: "if FINCO later approves a real deployment, is everything in place to turn gating on
intentionally?". The sequence it supports (see docs/FINCO_TOKEN_ACTIVATION_RUNBOOK.md):

    approve provenance -> commit approved identity -> configure RPC -> independently verify chain + contract +
    decimals -> configure resource threshold -> activate gating explicitly -> verify fail-closed behaviour

Authority rules (unchanged by this module)
  * The ONLY authority for "which contract is $FINCO" is ``app.verified.token_entitlement.
    APPROVED_FINCO_DEPLOYMENTS`` (empty in production today). A *candidate* proposed here can be validated and
    probed, but it is never authoritative and can never produce READY_FOR_ACTIVATION until it is committed to
    that tuple. Environment values alone never establish production token provenance.
  * ``READY_FOR_ACTIVATION`` means every prerequisite is satisfied and ONLY the final explicit gating switch is
    missing; it activates NOTHING. This module only reads configuration and makes read-only ``eth_chainId`` /
    ``eth_call decimals()`` probes. Prerequisites: approved + valid deployment, RPC, chain and decimals verified,
    at least one holder resource enabled WITH a threshold, a valid ``FINCO_ENTITLEMENT_MAX_AGE_SECONDS`` (the
    canonical runtime freshness window, no default invented), and the fail-closed self-check. ``ACTIVE`` is the same
    plus an explicit ``FINCO_TOKEN_GATING_ENABLED``, so the runtime evaluator can actually operate.
  * Missing is not malformed: an incomplete product policy is ACTIVATION_INCOMPLETE, never CONFIG_INVALID.
  * Identity is exact chain + contract. Symbol / name are display-only and never read.
  * No chain, contract, supply, price, threshold, staking, burn, spend, revenue share or vesting is defined here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol

from app.protocol.entitlement_policy import AccessMode, PolicySet, load_policy_set
from app.protocol.entitlement_evaluator import FRESHNESS_ENV, _freshness_seconds
from app.protocol.token_config import _validate_hex_address
from app.protocol.token_deployments import ECONOMIC_TOKEN_UID, approved_deployments

ACTIVATION_STEPS = (
    "approve canonical deployment provenance",
    "commit approved deployment identity",
    "configure RPC",
    "independently verify chain + contract + decimals",
    "configure resource policy threshold",
    "activate gating explicitly",
    "verify fail-closed behavior",
)
RPC_ENV_PREFIX = "FINCO_TOKEN_RPC_URL_"


class ActivationStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"               # zero approved deployments (production today)
    CONFIG_INVALID = "CONFIG_INVALID"               # structural problem in deployments or policy config
    DEPLOYMENT_UNAPPROVED = "DEPLOYMENT_UNAPPROVED"  # a candidate exists that is not in the approved tuple
    ACTIVATION_INCOMPLETE = "ACTIVATION_INCOMPLETE"  # deployment verified, product prerequisites still missing
    RPC_UNAVAILABLE = "RPC_UNAVAILABLE"             # no RPC configured for the chain, or the probe failed
    CHAIN_MISMATCH = "CHAIN_MISMATCH"               # provider chain id differs from the approved chain id
    DECIMALS_MISMATCH = "DECIMALS_MISMATCH"         # on-chain decimals() differs from the approved decimals
    READY_FOR_ACTIVATION = "READY_FOR_ACTIVATION"   # every prerequisite met; ONLY the gating switch is missing
    ACTIVE = "ACTIVE"                               # same + gating explicitly ON for >= 1 enabled holder resource


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"


class Issue(str, Enum):
    MISSING_DEPLOYMENT = "MISSING_DEPLOYMENT"
    MALFORMED_ADDRESS = "MALFORMED_ADDRESS"
    UNSUPPORTED_CHAIN = "UNSUPPORTED_CHAIN"          # not a positive integer EVM chain id / not ERC-20
    DUPLICATE_DEPLOYMENT = "DUPLICATE_DEPLOYMENT"
    CONFLICTING_DEPLOYMENT = "CONFLICTING_DEPLOYMENT"
    AMBIGUOUS_ACTIVE_DEPLOYMENT = "AMBIGUOUS_ACTIVE_DEPLOYMENT"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    INVALID_APPROVAL_STATUS = "INVALID_APPROVAL_STATUS"
    DECIMALS_OUT_OF_RANGE = "DECIMALS_OUT_OF_RANGE"
    WRONG_ECONOMIC_TOKEN = "WRONG_ECONOMIC_TOKEN"
    POLICY_CONFIG_INVALID = "POLICY_CONFIG_INVALID"


@dataclass(frozen=True)
class ActivationDeployment:
    """The activation contract for a future approved deployment. Exact chain + contract identity only."""
    economic_token_uid: str
    chain_id: int
    contract_address: str
    decimals: int
    provenance: str
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    token_standard: str = "ERC-20"
    display_symbol: str | None = field(default=None, compare=False)   # display only
    display_name: str | None = field(default=None, compare=False)     # display only

    @property
    def identity(self) -> tuple[int, str]:
        return (self.chain_id, self.contract_address)


def validate_candidate(raw: Any) -> tuple[ActivationDeployment | None, tuple[Issue, ...]]:
    """Deterministic structural validation of ONE proposed deployment (dict or ActivationDeployment)."""
    if raw is None:
        return None, (Issue.MISSING_DEPLOYMENT,)
    get = (lambda k: getattr(raw, k, None)) if not isinstance(raw, Mapping) else raw.get
    issues: list[Issue] = []
    if get("economic_token_uid") != ECONOMIC_TOKEN_UID:
        issues.append(Issue.WRONG_ECONOMIC_TOKEN)
    chain = get("chain_id")
    if isinstance(chain, bool) or not isinstance(chain, int) or chain <= 0 or (get("token_standard") or "ERC-20") != "ERC-20":
        issues.append(Issue.UNSUPPORTED_CHAIN)
    address = _validate_hex_address(get("contract_address")) if isinstance(get("contract_address"), str) else None
    if address is None:
        issues.append(Issue.MALFORMED_ADDRESS)
    decimals = get("decimals")
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 77:
        issues.append(Issue.DECIMALS_OUT_OF_RANGE)
    provenance = get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        issues.append(Issue.MISSING_PROVENANCE)
    if issues:
        return None, tuple(dict.fromkeys(issues))
    status = get("approval_status") or ApprovalStatus.PENDING
    try:
        status = ApprovalStatus(getattr(status, "value", status))
    except ValueError:
        return None, (Issue.INVALID_APPROVAL_STATUS,)     # a malformed approval label is not an approval
    return ActivationDeployment(ECONOMIC_TOKEN_UID, chain, address, decimals, provenance.strip(), status,
                                get("token_standard") or "ERC-20"), ()


def validate_deployment_set(entries: Iterable[Any]) -> tuple[Issue, ...]:
    """Structural validation of the committed approved set: zero, one or many; fail closed on any defect."""
    items = tuple(entries)
    if not items:
        return (Issue.MISSING_DEPLOYMENT,)
    issues: list[Issue] = []
    seen: dict[tuple[int, str, int], int] = {}
    by_chain: dict[int, set[tuple[str, int]]] = {}
    for entry in items:
        raw = {"economic_token_uid": ECONOMIC_TOKEN_UID, "chain_id": getattr(entry, "chain_id", None),
               "contract_address": getattr(entry, "token_address", None), "decimals": getattr(entry, "decimals", None),
               "provenance": getattr(entry, "provenance", None), "token_standard": getattr(entry, "standard", "ERC-20")}
        parsed, problems = validate_candidate(raw)
        issues.extend(problems)
        if parsed is None:
            continue
        key = (parsed.chain_id, parsed.contract_address, parsed.decimals)
        seen[key] = seen.get(key, 0) + 1
        by_chain.setdefault(parsed.chain_id, set()).add((parsed.contract_address, parsed.decimals))
    if any(count > 1 for count in seen.values()):
        issues.append(Issue.DUPLICATE_DEPLOYMENT)
    if any(len(variants) > 1 for variants in by_chain.values()):
        issues.append(Issue.CONFLICTING_DEPLOYMENT)
    return tuple(dict.fromkeys(issues))


# ── read-only chain probe ───────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ChainProbeResult:
    reachable: bool
    chain_id: int | None = None
    decimals: int | None = None
    reason: str | None = None


class ChainProbe(Protocol):
    async def probe(self, rpc_url: str, contract_address: str) -> ChainProbeResult: ...


class JsonRpcChainProbe:
    """Read-only ``eth_chainId`` + ``decimals()`` via the existing P4 JSON-RPC helpers. Never writes."""

    async def probe(self, rpc_url: str, contract_address: str) -> ChainProbeResult:
        from app.protocol.token_balance import _decode_uint, _encode_decimals, _rpc_call
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                try:
                    chain_id = int(await _rpc_call(client, rpc_url, "eth_chainId", []), 16)
                except Exception:
                    return ChainProbeResult(False, reason="eth_chainId_failed")
                try:
                    result = await _rpc_call(client, rpc_url, "eth_call",
                                             [{"to": contract_address, "data": _encode_decimals()}, "latest"])
                    decimals = _decode_uint(result) if isinstance(result, str) and len(result) == 66 else None
                except Exception:
                    decimals = None
                return ChainProbeResult(True, chain_id, decimals, None if decimals is not None else "decimals_unavailable")
        except Exception:
            return ChainProbeResult(False, reason="unexpected_error")


# ── report ─────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ActivationCheck:
    name: str
    passed: bool | None          # None = not evaluated (an earlier check failed)
    detail: str = ""


@dataclass(frozen=True)
class ActivationReport:
    status: ActivationStatus
    checks: tuple[ActivationCheck, ...]
    issues: tuple[Issue, ...] = ()
    chain_id: int | None = None
    contract_address: str | None = None
    active_resources: tuple[str, ...] = ()
    reason: str = ""

    @property
    def ready_or_active(self) -> bool:
        return self.status in (ActivationStatus.READY_FOR_ACTIVATION, ActivationStatus.ACTIVE)

    def public_view(self) -> dict:
        """Safe to log or print: no RPC URL, no secret."""
        return {"status": self.status.value, "reason": self.reason, "chain_id": self.chain_id,
                "contract_address": self.contract_address, "issues": [i.value for i in self.issues],
                "active_resources": list(self.active_resources),
                "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks]}


_CHECK_NAMES = ("deployment_approved", "deployment_valid", "rpc_configured", "chain_verified",
                "decimals_verified", "resource_threshold_configured", "freshness_window_configured",
                "gating_explicitly_enabled", "fail_closed_behavior")


def _checks(**done: tuple[bool | None, str]) -> tuple[ActivationCheck, ...]:
    return tuple(ActivationCheck(n, *done.get(n, (None, "not evaluated"))) for n in _CHECK_NAMES)


def _fail_closed_self_check(policy_set: PolicySet, deployments: tuple) -> bool:
    """Gated resources must DENY a missing wallet and the public resource must stay public (pure, offline)."""
    from datetime import datetime, timezone
    from app.protocol.entitlement_evaluator import NO_WALLET, Decision, decide_resource_access
    from app.protocol.token_deployments import resolve_approved_deployment
    resolution = resolve_approved_deployment(approved=deployments)
    now = datetime.now(timezone.utc)
    for key, policy in policy_set.policies.items():
        verdict = decide_resource_access(key, NO_WALLET, policy_set, resolution, None,
                                         freshness_seconds=60, now=now).decision
        if policy.access_mode is AccessMode.PUBLIC and verdict is not Decision.ALLOW:
            return False
        if policy.access_mode is AccessMode.FINCO_HOLDER and verdict is Decision.ALLOW:
            return False
    return True


async def _verify_deployment(deployment, env: Mapping[str, str], probe: ChainProbe | None,
                             base: dict) -> ActivationReport | None:
    """RPC configured -> chain id matches -> decimals match. Returns a failing report, or None when verified."""
    ident = dict(chain_id=deployment.chain_id, contract_address=deployment.token_address)
    rpc_url = (env.get(f"{RPC_ENV_PREFIX}{deployment.chain_id}") or "").strip()
    if not rpc_url:
        return ActivationReport(ActivationStatus.RPC_UNAVAILABLE,
                                _checks(**base, rpc_configured=(False, "no RPC configured for the chain")),
                                reason="NO_RPC_FOR_CHAIN", **ident)
    base["rpc_configured"] = (True, "configured")
    result = await (probe or JsonRpcChainProbe()).probe(rpc_url, deployment.token_address)
    if not result.reachable or result.chain_id is None:
        return ActivationReport(ActivationStatus.RPC_UNAVAILABLE, _checks(**base, chain_verified=(False, "probe failed")),
                                reason=result.reason or "RPC_PROBE_FAILED", **ident)
    if result.chain_id != deployment.chain_id:
        return ActivationReport(ActivationStatus.CHAIN_MISMATCH,
                                _checks(**base, chain_verified=(False, "provider chain differs from approved chain")),
                                reason="PROVIDER_CHAIN_DIFFERS", **ident)
    base["chain_verified"] = (True, "provider chain matches")
    if result.decimals is None:
        return ActivationReport(ActivationStatus.RPC_UNAVAILABLE,
                                _checks(**base, decimals_verified=(False, "decimals() not provable")),
                                reason="DECIMALS_UNAVAILABLE", **ident)
    if result.decimals != deployment.decimals:
        return ActivationReport(ActivationStatus.DECIMALS_MISMATCH,
                                _checks(**base, decimals_verified=(False, "on-chain decimals differ from approved")),
                                reason="ONCHAIN_DECIMALS_DIFFER", **ident)
    return None


async def assess_activation(
    *,
    environ: Mapping[str, str] | None = None,
    approved: Iterable | None = None,
    candidate: Any = None,
    probe: ChainProbe | None = None,
    policy_set: PolicySet | None = None,
) -> ActivationReport:
    """Deterministic, read-only readiness assessment. Fails closed at the first unmet requirement."""
    env = os.environ if environ is None else environ
    committed = tuple(approved_deployments() if approved is None else approved)
    policy_set = policy_set or load_policy_set(env)

    if candidate is not None:
        parsed, problems = validate_candidate(candidate)
        if problems:
            return ActivationReport(ActivationStatus.CONFIG_INVALID, _checks(deployment_valid=(False, "candidate invalid")),
                                    problems, reason="CANDIDATE_INVALID")
        # Every approval-relevant field must equal the committed record, provenance included. A candidate
        # that only shares chain + contract + decimals is NOT the approved record. Display fields never count.
        in_committed = any(
            (e.chain_id, e.token_address, getattr(e, "standard", "ERC-20"), e.decimals, e.provenance.strip())
            == (parsed.chain_id, parsed.contract_address, parsed.token_standard, parsed.decimals, parsed.provenance)
            for e in committed)
        if not in_committed or parsed.approval_status is not ApprovalStatus.APPROVED:
            return ActivationReport(
                ActivationStatus.DEPLOYMENT_UNAPPROVED,
                _checks(deployment_approved=(False, "candidate is not in the committed approved set")),
                chain_id=parsed.chain_id, contract_address=parsed.contract_address, reason="CANDIDATE_NOT_COMMITTED")

    if not committed:
        return ActivationReport(ActivationStatus.NOT_CONFIGURED,
                                _checks(deployment_approved=(False, "zero approved deployments")),
                                (Issue.MISSING_DEPLOYMENT,), reason="NO_APPROVED_DEPLOYMENT")

    issues = list(validate_deployment_set(committed))
    if policy_set.config_error:
        issues.append(Issue.POLICY_CONFIG_INVALID)
    holder_policies = [p for p in policy_set.policies.values() if p.access_mode is AccessMode.FINCO_HOLDER]
    chains = {e.chain_id for e in committed}
    if len(chains) > 1 and any(p.chain_id is None for p in holder_policies):
        issues.append(Issue.AMBIGUOUS_ACTIVE_DEPLOYMENT)
    if issues:
        return ActivationReport(ActivationStatus.CONFIG_INVALID,
                                _checks(deployment_approved=(True, "approved set present"),
                                        deployment_valid=(False, "structural validation failed")),
                                tuple(dict.fromkeys(issues)), reason="CONFIG_INVALID")

    chosen = validate_candidate(candidate)[0] if candidate is not None else None
    targets = [e for e in committed if chosen is None or e.chain_id == chosen.chain_id]
    base = {"deployment_approved": (True, "approved set present"), "deployment_valid": (True, "valid")}
    for deployment in sorted(targets, key=lambda e: (e.chain_id, e.token_address)):
        failure = await _verify_deployment(deployment, env, probe, dict(base))
        if failure is not None:
            return failure
    deployment = sorted(targets, key=lambda e: (e.chain_id, e.token_address))[0]
    base.update({"rpc_configured": (True, "configured on every approved chain"),
                 "chain_verified": (True, "provider chain matches"),
                 "decimals_verified": (True, "on-chain decimals match")})
    active = tuple(p.resource_key for p in holder_policies if p.enabled and p.minimum_balance is not None)
    freshness_ok = _freshness_seconds(env) is not None          # the SAME canonical parser the runtime uses
    gating = policy_set.gating_enabled
    fail_closed = _fail_closed_self_check(policy_set, committed)
    base["resource_threshold_configured"] = (bool(active), f"{len(active)} holder resource(s) enabled with a threshold")
    base["freshness_window_configured"] = (freshness_ok, f"{FRESHNESS_ENV} " + ("valid" if freshness_ok else
                                                                              "missing or not a positive integer"))
    base["gating_explicitly_enabled"] = (gating, "explicit operator opt-in" if gating else "gating OFF")
    base["fail_closed_behavior"] = (fail_closed, "no-wallet denied; public stays public")
    ident = dict(chain_id=deployment.chain_id, contract_address=deployment.token_address)
    if not fail_closed:
        return ActivationReport(ActivationStatus.CONFIG_INVALID, _checks(**base), reason="FAIL_CLOSED_CHECK_FAILED", **ident)
    missing = tuple(name for name, ok in (("resource_threshold_configured", bool(active)),
                                          ("freshness_window_configured", freshness_ok)) if not ok)
    if missing:       # missing, not malformed: the product policy / runtime config is simply not finished
        return ActivationReport(ActivationStatus.ACTIVATION_INCOMPLETE, _checks(**base),
                                reason="MISSING_" + "_AND_".join(m.upper() for m in missing), **ident)
    if gating:
        return ActivationReport(ActivationStatus.ACTIVE, _checks(**base), active_resources=active,
                                reason="GATING_EXPLICITLY_ENABLED", **ident)
    return ActivationReport(ActivationStatus.READY_FOR_ACTIVATION, _checks(**base),
                            reason="READY_GATING_NOT_ACTIVE", **ident)

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
  * Only resources actually intended for activation (enabled AND a threshold) are activation targets. Each target
    must resolve to exactly one approved deployment through the SAME ``resolve_approved_deployment`` call the
    runtime uses, and its threshold must be exactly representable in that deployment's decimals (the runtime's own
    ``_token_policy`` rule, no rounding). ``active_resources`` lists only such validated, runtime-operable targets.
    Disabled / unthresholded resources never create deployment ambiguity. RPC verification covers the deployments
    the targets select (every approved deployment when there is no target yet); an approved but unused deployment
    does not block activation of a valid resource on another approved chain. Identity validation is unchanged.
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
from app.protocol.entitlement_evaluator import FRESHNESS_ENV, _freshness_seconds, _token_policy
from app.protocol.token_config import _validate_hex_address
from app.protocol.token_deployments import (
    ECONOMIC_TOKEN_UID, ResolutionStatus, approved_deployments, resolve_approved_deployment,
)

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
    RESOURCE_CHAIN_NOT_APPROVED = "RESOURCE_CHAIN_NOT_APPROVED"      # an activation-target resource names an unapproved chain
    THRESHOLD_EXCEEDS_TOKEN_DECIMALS = "THRESHOLD_EXCEEDS_TOKEN_DECIMALS"   # same rule as the runtime evaluator


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
class BalanceProbeCheck:
    """OPTIONAL read-only balance-authority diagnostic result.

    Proves ONLY that the configured read-only balance authority can execute
    ``balanceOf`` against the exact approved deployment over the SAME
    chain-scoped RPC the runtime evaluator consumes.  It never asserts
    wallet ownership and never affects the activation status.

    MISSING ≠ ZERO: ``balance_raw_present`` is True only when a successful
    chain read returned a raw balance (an explicit zero included);
    ``factual_zero`` is True only for such an observed zero.  Any RPC /
    contract / identity failure is a typed unavailable state with no number.
    """

    requested: bool
    executed: bool
    available: bool
    balance_raw_present: bool
    factual_zero: bool
    observation_status: str
    detail: str = ""


@dataclass(frozen=True)
class ActivationReport:
    status: ActivationStatus
    checks: tuple[ActivationCheck, ...]
    issues: tuple[Issue, ...] = ()
    chain_id: int | None = None
    contract_address: str | None = None
    active_resources: tuple[str, ...] = ()       # ONLY when ACTIVE: resources that are on and runtime-operable
    activation_targets: tuple[str, ...] = ()     # validated resources that WOULD be active once gating is on
    reason: str = ""
    balance_probe: BalanceProbeCheck | None = None   # additive; None = not requested

    @property
    def ready_or_active(self) -> bool:
        return self.status in (ActivationStatus.READY_FOR_ACTIVATION, ActivationStatus.ACTIVE)

    def public_view(self) -> dict:
        """Safe to log or print: no RPC URL, no secret, no probe wallet."""
        view = {"status": self.status.value, "reason": self.reason, "chain_id": self.chain_id,
                "contract_address": self.contract_address, "issues": [i.value for i in self.issues],
                "active_resources": list(self.active_resources),
                "activation_targets": list(self.activation_targets),
                "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks]}
        if self.balance_probe is not None:
            from dataclasses import asdict
            probe = asdict(self.balance_probe)
            probe.pop("wallet_address", None)    # never printed
            view["balance_probe"] = probe
        return view


_CHECK_NAMES = ("deployment_approved", "deployment_valid", "rpc_configured", "chain_verified",
                "decimals_verified", "resource_threshold_configured", "resource_deployment_resolved",
                "threshold_representable", "freshness_window_configured",
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
    balance_probe_wallet: str | None = None,
    balance_provider: Any = None,
) -> ActivationReport:
    """Deterministic, read-only readiness assessment. Fails closed at the first unmet requirement.

    ``balance_probe_wallet`` (optional): when supplied with an exact EVM
    address, ONE additional read-only ``balanceOf`` diagnostic runs against
    the exact approved deployment over the SAME chain-scoped RPC the runtime
    evaluator consumes — using the existing
    ``app.verified.token_entitlement.P4ReadOnlyBalanceProvider``.  It is
    additive evidence only: it never changes the ActivationStatus, never
    asserts wallet ownership, and MISSING/UNAVAILABLE is never a zero.
    """
    report = await _assess_activation_inner(
        environ=environ, approved=approved, candidate=candidate, probe=probe,
        policy_set=policy_set)
    if balance_probe_wallet is None:
        return report
    return await _attach_balance_probe(
        report, balance_probe_wallet,
        os.environ if environ is None else environ,
        approved=None if approved is None else tuple(approved),
        provider=balance_provider)


async def _attach_balance_probe(
    report: ActivationReport, wallet: str, env: Mapping[str, str],
    approved: tuple | None, provider: Any,
) -> ActivationReport:
    """Attach the optional balance diagnostic WITHOUT changing the status."""
    from dataclasses import replace
    from app.protocol.token_config import _validate_hex_address

    def _check(executed: bool, available: bool, raw_present: bool,
               factual_zero: bool, status: str, detail: str = ""):
        return replace(report, balance_probe=BalanceProbeCheck(
            requested=True, executed=executed, available=available,
            balance_raw_present=raw_present, factual_zero=factual_zero,
            observation_status=status, detail=detail))

    address = _validate_hex_address(wallet)
    if address is None:
        return _check(False, False, False, False, "MALFORMED_PROBE_WALLET",
                      "probe wallet must be an exact 0x + 40-hex address")
    if report.status not in (ActivationStatus.READY_FOR_ACTIVATION,
                             ActivationStatus.ACTIVE,
                             ActivationStatus.ACTIVATION_INCOMPLETE):
        return _check(False, False, False, False, "DEPLOYMENT_NOT_VERIFIED",
                      "deployment verification did not complete")

    deployment = None
    for entry in (approved if approved is not None else approved_deployments()):
        if (entry.chain_id, entry.token_address) == (report.chain_id,
                                                     report.contract_address):
            deployment = entry
            break
    if deployment is None:
        return _check(False, False, False, False, "DEPLOYMENT_NOT_VERIFIED",
                      "approved deployment for the verified identity not found")
    rpc_url = (env.get(f"{RPC_ENV_PREFIX}{deployment.chain_id}") or "").strip()
    if not rpc_url:
        return _check(False, False, False, False, "NO_RPC_FOR_CHAIN",
                      "chain-scoped RPC not configured")

    from decimal import Decimal
    from app.protocol.token_config import TokenConfig
    from app.verified.token_entitlement import P4ReadOnlyBalanceProvider
    # Runtime parity: the SAME chain-scoped rpc_url, contract, decimals and
    # P4 read-only provider the entitlement evaluator's default provider
    # uses (mirror of entitlement_evaluator._default_provider).
    config = TokenConfig(rpc_url=rpc_url, chain_id=deployment.chain_id,
                         token_address=deployment.token_address,
                         min_balance=Decimal(1),
                         decimals_override=deployment.decimals)
    from app.verified.token_entitlement import FincoEntitlementPolicy
    token_policy = FincoEntitlementPolicy(
        chain_id=deployment.chain_id, token_address=deployment.token_address,
        token_decimals=deployment.decimals, minimum_balance_raw=1,
        freshness_seconds=1, provenance=deployment.provenance)
    try:
        active_provider = provider or P4ReadOnlyBalanceProvider(config)
        evidence = await active_provider.balance_of(token_policy, address)
    except Exception:
        return _check(True, False, False, False, "BALANCE_UNAVAILABLE",
                      "balance observation raised")
    # Identity fail-closed: evidence from another chain/contract/wallet is a
    # typed mismatch, never a balance (same rule as the canonical evaluator).
    if (getattr(evidence, "chain_id", None) != deployment.chain_id
            or getattr(evidence, "token_address", None) != deployment.token_address
            or getattr(evidence, "wallet_address", None) != address):
        return _check(True, False, False, False, "BALANCE_IDENTITY_MISMATCH",
                      "evidence identity differs from the approved deployment")
    if evidence.state.value == "AVAILABLE" and evidence.balance_raw is not None:
        return _check(True, True, True, evidence.balance_raw == 0,
                      "BALANCE_OBSERVED",
                      f"raw balance observed on chain {deployment.chain_id}")
    return _check(True, False, False, False,
                  evidence.reason or evidence.state.value)


async def _assess_activation_inner(
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

    # Activation targets: ONLY resources intended for activation take part in deployment selection.
    targets: list[tuple] = []                                   # (policy, resolved approved deployment)
    if not issues:
        for policy in holder_policies:
            if not (policy.enabled and policy.minimum_balance is not None):
                continue
            resolution = resolve_approved_deployment(policy.chain_id, committed)   # exactly what the runtime calls
            if not resolution.resolved:
                issues.append({ResolutionStatus.NOT_FOUND: Issue.RESOURCE_CHAIN_NOT_APPROVED,
                               ResolutionStatus.AMBIGUOUS: Issue.AMBIGUOUS_ACTIVE_DEPLOYMENT,
                               ResolutionStatus.CONFLICT: Issue.CONFLICTING_DEPLOYMENT}
                              .get(resolution.status, Issue.MISSING_DEPLOYMENT))
            elif _token_policy(resolution.deployment, policy, 1) is None:          # runtime's exact-integer rule
                issues.append(Issue.THRESHOLD_EXCEEDS_TOKEN_DECIMALS)
            else:
                targets.append((policy, resolution.deployment))
    if issues:
        return ActivationReport(ActivationStatus.CONFIG_INVALID,
                                _checks(deployment_approved=(True, "approved set present"),
                                        deployment_valid=(False, "structural / resource validation failed")),
                                tuple(dict.fromkeys(issues)), reason="CONFIG_INVALID")

    chosen = validate_candidate(candidate)[0] if candidate is not None else None
    selected = {(d.chain_id, d.token_address): d for _, d in targets}
    if chosen is not None:                                      # a pre-commit candidate is verified as well
        for entry in committed:
            if entry.chain_id == chosen.chain_id and entry.token_address == chosen.contract_address:
                selected[(entry.chain_id, entry.token_address)] = entry
    verify_set = sorted(selected.values() if selected else committed, key=lambda e: (e.chain_id, e.token_address))
    base = {"deployment_approved": (True, "approved set present"), "deployment_valid": (True, "valid")}
    for deployment in verify_set:
        failure = await _verify_deployment(deployment, env, probe, dict(base))
        if failure is not None:
            return failure
    deployment = verify_set[0]
    base.update({"rpc_configured": (True, "configured on every verified chain"),
                 "chain_verified": (True, "provider chain matches"),
                 "decimals_verified": (True, "on-chain decimals match")})
    active = tuple(policy.resource_key for policy, _ in targets)      # validated, runtime-operable resources only
    freshness_ok = _freshness_seconds(env) is not None                # the SAME canonical parser the runtime uses
    gating = policy_set.gating_enabled
    fail_closed = _fail_closed_self_check(policy_set, committed)
    base["resource_threshold_configured"] = (bool(active), f"{len(active)} holder resource(s) enabled with a threshold")
    base["resource_deployment_resolved"] = (bool(active), "every active resource resolves to one approved deployment"
                                            if active else "no activation-target resource")
    base["threshold_representable"] = (bool(active), "every threshold is exact in the deployment decimals"
                                       if active else "no activation-target resource")
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
                                activation_targets=active, reason="MISSING_" + "_AND_".join(m.upper() for m in missing), **ident)
    if gating:
        return ActivationReport(ActivationStatus.ACTIVE, _checks(**base), active_resources=active,
                                activation_targets=active, reason="GATING_EXPLICITLY_ENABLED", **ident)
    return ActivationReport(ActivationStatus.READY_FOR_ACTIVATION, _checks(**base), activation_targets=active,
                            reason="READY_GATING_NOT_ACTIVE", **ident)

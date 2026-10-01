"""$FINCO token-gate ACTIVATION READINESS diagnostics (V1).

Operator-safe readiness layer BETWEEN an authenticated FINCO wallet and the
existing entitlement evaluator.  This module OWNS NO authority: it composes
the already-canonical pieces and reports whether a future real $FINCO
configuration is activation-ready.

Authority chain (all read through their existing modules — nothing here
decides access, evaluates balances itself, or stores state):

    gate flag                app.protocol.entitlement_policy.load_policy_set
                             (FINCO_TOKEN_GATING_ENABLED, default OFF)
    resource policies        same PolicySet (per-resource enabled/threshold)
    P4 token configuration   app.protocol.token_config.get_token_config
                             (FINCO_TOKEN_RPC_URL / _CHAIN_ID / _ADDRESS /
                              FINCO_ACCESS_MIN_BALANCE / FINCO_TOKEN_DECIMALS)
    approved deployments     app.protocol.token_deployments
                             .resolve_approved_deployment (over the canonical
                             APPROVED_FINCO_DEPLOYMENTS — empty today)
    provider binding         chain-scoped env FINCO_TOKEN_RPC_URL_<chain_id>
                             consumed by entitlement_evaluator._default_provider
    read-only observation    app.protocol.token_balance.read_token_balance
                             (eth_call balanceOf / decimals — NEVER a write)
    wallet identity          wallet_context_for_session / _for_user
    canonical entitlement    evaluate_token_entitlement /
                             decide_resource_access (untouched)

Typed readiness states (distinct, never collapsed):

    GATE_OFF               gating flag OFF — product behaviour unchanged
    NOT_CONFIGURED         required configuration absent (deployment and/or
                           P4 token config) — a first-class state
    PARTIALLY_CONFIGURED   some required values present, not all
    PROVIDER_UNAVAILABLE   configuration present but the RPC provider could
                           not be reached / is not bound
    TOKEN_CONTRACT_UNAVAILABLE
                           provider reachable but the token contract could
                           not be queried
    READY                  everything configured and the observation
                           authority is functional (activation-ready; the
                           gate itself still decides whether gating applies)

MISSING ≠ ZERO: probe/observation failures are typed states with reasons —
an RPC timeout, an RPC error or a contract error NEVER produce a balance of
zero.  A factual zero is only ever the result of a successful chain read
returning exactly zero.

Operator safety: the report contains NO secrets — the RPC URL is represented
only as a boolean presence flag and a host hint; no keys, seeds, session
data or credentials ever appear.  Read-only only: no eth_sendTransaction,
approve, transfer, signing, custody or private keys exist anywhere in this
path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Optional

READINESS_SCHEMA_VERSION = "finco-token-gate-readiness-v1"

# Typed readiness states.
STATE_GATE_OFF = "GATE_OFF"
STATE_NOT_CONFIGURED = "NOT_CONFIGURED"
STATE_PARTIALLY_CONFIGURED = "PARTIALLY_CONFIGURED"
STATE_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
STATE_TOKEN_CONTRACT_UNAVAILABLE = "TOKEN_CONTRACT_UNAVAILABLE"
STATE_READY = "READY"

PROBE_WALLET_ADDRESS = "0x" + "00" * 20  # deterministic read-only probe target


def _chain_scoped_provider_env(chain_id: int | None,
                               environ: Mapping[str, str]) -> str | None:
    """The provider binding the evaluator's default provider actually reads:
    FINCO_TOKEN_RPC_URL_<chain_id>."""
    if chain_id is None:
        return None
    value = (environ.get(f"FINCO_TOKEN_RPC_URL_{chain_id}") or "").strip()
    return value or None


def _host_hint(url: str) -> str | None:
    """Coarse host hint for diagnostics — never the full URL (no credentials,
    no query string)."""
    from urllib.parse import urlsplit
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host or None


@dataclass(frozen=True)
class ProviderProbeResult:
    """Typed result of ONE read-only provider probe."""

    reachable: bool
    status: str                     # canonical TokenObservation status code
    detail: str | None = None
    observed_balance_raw: Optional[int] = None   # None unless a real read happened
    factual_zero: bool = False      # True ONLY for a successful explicit-zero read


@dataclass(frozen=True)
class TokenGateReadinessReport:
    """Operator-safe activation readiness report (JSON-serialisable)."""

    schema_version: str
    state: str                      # one of the STATE_* constants
    gate_enabled: bool
    next_action: str | None
    checks: dict = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "gate_enabled": self.gate_enabled,
            "next_action": self.next_action,
            "checks": self.checks,
        }


def _gate_view(environ: Mapping[str, str]) -> dict:
    from app.protocol.entitlement_policy import load_policy_set
    policy_set = load_policy_set(environ)
    resources = {}
    for key, policy in policy_set.policies.items():
        resources[key] = {
            "access_mode": policy.access_mode.value,
            "enabled": policy.enabled,
            "threshold_set": policy.minimum_balance is not None,
            "wallet_verified_required": policy.wallet_verified_required,
        }
    return {
        "gating_enabled": policy_set.gating_enabled,
        "config_error": policy_set.config_error,
        "resources": resources,
    }


def _config_view(environ: Mapping[str, str]) -> dict:
    from app.protocol.token_config import get_token_config
    config = get_token_config()
    if config is None:
        return {"configured": False, "reason": "NOT_CONFIGURED"}
    return {
        "configured": True,
        "chain_id": config.chain_id,
        "token_address_present": bool(config.token_address),
        "threshold_set": config.min_balance is not None,
        "decimals_override": config.decimals_override,
        "provider_env_present": bool(config.rpc_url),
        "provider_env_chain_scoped": False,   # P4 config uses the flat URL
    }


def _deployment_view(environ: Mapping[str, str]) -> dict:
    from app.protocol.entitlement_policy import load_policy_set
    from app.protocol.token_deployments import resolve_approved_deployment
    policy_set = load_policy_set(environ)
    selector = None
    for policy in policy_set.policies.values():
        if policy.chain_id is not None:
            selector = policy.chain_id
            break
    resolution = resolve_approved_deployment(selector)
    return {
        "status": resolution.status.value,
        "reason": resolution.reason or None,
        "resolved": resolution.resolved,
        "chain_id": getattr(resolution.deployment, "chain_id", None),
        "decimals": getattr(resolution.deployment, "decimals", None),
    }


def probe_provider(config, *, provider=None,
                   probe_address: str = PROBE_WALLET_ADDRESS) -> ProviderProbeResult:
    """ONE read-only probe through the canonical balance authority.

    ``provider`` is an injectable canonical ``TokenBalanceProvider`` for
    deterministic tests; production uses the existing P4 read-only provider.
    Read-only only: balanceOf/decimals style eth_call — never a write.
    """
    from app.protocol.token_balance import (
        STATUS_CHAIN_ID_MISMATCH,
        STATUS_ENTITLED,
        STATUS_INSUFFICIENT,
        STATUS_RPC_UNAVAILABLE,
        STATUS_TOKEN_CONTRACT_UNAVAILABLE,
        read_token_balance,
    )

    async def _run() -> ProviderProbeResult:
        observation = await read_token_balance(probe_address, config)
        if observation.status in (STATUS_ENTITLED, STATUS_INSUFFICIENT):
            raw = observation.balance_raw
            return ProviderProbeResult(
                reachable=True,
                status=observation.status,
                detail=None,
                observed_balance_raw=raw,
                factual_zero=(raw == 0),
            )
        if observation.status in (STATUS_RPC_UNAVAILABLE,
                                  STATUS_CHAIN_ID_MISMATCH):
            return ProviderProbeResult(reachable=False,
                                       status=observation.status,
                                       detail=observation.status)
        if observation.status == STATUS_TOKEN_CONTRACT_UNAVAILABLE:
            return ProviderProbeResult(reachable=True,
                                       status=observation.status,
                                       detail=observation.status)
        return ProviderProbeResult(reachable=False, status=observation.status,
                                   detail=observation.status)

    import asyncio
    if provider is not None:
        # Injected provider path (deterministic tests): same evidence shape.
        from app.verified.token_entitlement import P4ReadOnlyBalanceProvider

        async def _via_provider() -> ProviderProbeResult:
            evidence = await provider.balance_of(
                _probe_token_policy(config), probe_address)
            if evidence.state.value == "AVAILABLE" and evidence.balance_raw is not None:
                return ProviderProbeResult(
                    reachable=True, status="ENTITLED",
                    observed_balance_raw=evidence.balance_raw,
                    factual_zero=(evidence.balance_raw == 0))
            return ProviderProbeResult(reachable=False,
                                       status=evidence.reason or "BALANCE_UNAVAILABLE",
                                       detail=evidence.reason)
        return asyncio.run(_via_provider())
    return asyncio.run(_run())


def _probe_token_policy(config):
    """Canonical FincoEntitlementPolicy for the probe (threshold from P4
    config; a probe only needs identity fields to be well-formed)."""
    from app.verified.token_entitlement import FincoEntitlementPolicy
    decimals = config.decimals_override if config.decimals_override is not None else 18
    minimum_raw = (config.min_balance * (Decimal(10) ** decimals))
    if minimum_raw != minimum_raw.to_integral_value():
        minimum_raw = Decimal(int(minimum_raw))
    return FincoEntitlementPolicy(
        chain_id=config.chain_id, token_address=config.token_address,
        token_decimals=decimals, minimum_balance_raw=int(minimum_raw),
        freshness_seconds=300, provenance="READINESS_PROBE",
    )


def build_readiness_report(
    *, environ: Mapping[str, str] | None = None,
    provider=None,
    probe: bool = False,
) -> TokenGateReadinessReport:
    """Compose the operator-safe readiness report from existing authorities.

    ``environ`` is injectable for deterministic tests; ``provider`` is an
    injectable canonical balance provider; ``probe`` enables the (read-only)
    provider reachability check — OFF by default so the diagnostic never
    makes network calls unless an operator explicitly asks for it.
    """
    env = os.environ if environ is None else environ
    from app.protocol.entitlement_policy import load_policy_set

    gate = _gate_view(env)
    gate_enabled = bool(gate["gating_enabled"]) and not bool(gate["config_error"])
    config = _config_view(env)
    deployment = _deployment_view(env)

    provider_check: dict = {"probed": False, "reachable": None,
                            "status": None, "factual_zero": False,
                            "chain_scoped_env_present": None}
    chain_id = config.get("chain_id") if config.get("configured") else None
    provider_env = _chain_scoped_provider_env(chain_id, env)
    provider_check["chain_scoped_env_present"] = provider_env is not None

    state = None
    next_action = None

    if not gate_enabled:
        state = STATE_GATE_OFF
        next_action = ("Token gating is OFF — product behaviour is unchanged. "
                       "To prepare activation, configure the deployment, "
                       "threshold and provider, then set "
                       "FINCO_TOKEN_GATING_ENABLED=1.")
        if not config.get("configured") and not deployment.get("resolved"):
            next_action = ("Token gating is OFF and no $FINCO deployment is "
                           "configured (production default). Configure the "
                           "approved deployment, P4 token config, threshold "
                           "and provider before enabling the gate.")

    if state is None:
        missing = []
        if not deployment.get("resolved"):
            missing.append(f"approved deployment ({deployment['status']})")
        if not config.get("configured"):
            missing.append("P4 token configuration")
        if missing:
            # Both absent = the production default NOT_CONFIGURED; exactly
            # one present = part-way through activation.
            state = (STATE_NOT_CONFIGURED if len(missing) == 2
                     else STATE_PARTIALLY_CONFIGURED)
            next_action = "Configure: " + "; ".join(missing)

    if state is None and not config.get("decimals_override"):
        # Decimals authority must be explicit for deterministic conversion.
        state = STATE_PARTIALLY_CONFIGURED
        next_action = "Set FINCO_TOKEN_DECIMALS (explicit decimals authority)."

    if state is None and provider_env is None:
        # The evaluator's default provider consumes ONLY the chain-scoped
        # env; a flat P4 RPC URL does not feed gated resource decisions.
        state = STATE_PROVIDER_UNAVAILABLE
        next_action = (f"Set FINCO_TOKEN_RPC_URL_{chain_id} (the chain-scoped "
                       "provider binding consumed by the evaluator).")

    probe_result: Optional[ProviderProbeResult] = None
    if state is None and probe:
        from app.protocol.token_config import get_token_config
        probe_result = probe_provider(get_token_config(), provider=provider)
        provider_check.update({
            "probed": True,
            "reachable": probe_result.reachable,
            "status": probe_result.status,
            "factual_zero": probe_result.factual_zero,
        })
        if probe_result.status == "TOKEN_CONTRACT_UNAVAILABLE":
            state = STATE_TOKEN_CONTRACT_UNAVAILABLE
            next_action = (f"Provider probe failed: {probe_result.status}.")
        elif not probe_result.reachable:
            state = (STATE_PROVIDER_UNAVAILABLE
                     if probe_result.status in ("RPC_UNAVAILABLE",
                                                "CHAIN_ID_MISMATCH")
                     else STATE_TOKEN_CONTRACT_UNAVAILABLE)
            next_action = f"Provider probe failed: {probe_result.status}."

    if state is None:
        state = STATE_READY
        next_action = ("Activation-ready: configuration, deployment and "
                       "observation authority are functional. Enabling "
                       "FINCO_TOKEN_GATING_ENABLED=1 activates gating; "
                       "existing ungated product behaviour changes only for "
                       "gated resources.")

    report = TokenGateReadinessReport(
        schema_version=READINESS_SCHEMA_VERSION,
        state=state,
        gate_enabled=gate_enabled,
        next_action=next_action,
        checks={
            "gate": gate,
            "token_config": config,
            "deployment": deployment,
            "provider": provider_check,
            "wallet_observation_authority": {
                "module": "app.protocol.token_balance.read_token_balance",
                "read_only": True,
                "present": True,
            },
        },
    )
    return report


def main(argv: list[str] | None = None) -> int:
    """Operator CLI: print the readiness report as JSON. Never raises; never
    prints secrets (RPC URL is represented by presence + host hint only)."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="$FINCO token-gate activation readiness diagnostic. "
                    "Read-only; makes no network calls unless --probe is set.")
    parser.add_argument("--probe", action="store_true",
                        help="also probe the configured RPC provider with one "
                             "read-only balanceOf call against a deterministic "
                             "probe address")
    args = parser.parse_args(argv)

    try:
        report = build_readiness_report(probe=args.probe)
        payload = report.public_dict()
    except Exception as exc:  # diagnostic must never crash the operator shell
        payload = {"schema_version": READINESS_SCHEMA_VERSION,
                   "state": "NOT_CONFIGURED",
                   "error": f"{type(exc).__name__}"}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

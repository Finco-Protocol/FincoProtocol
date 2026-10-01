# $FINCO token activation runbook (readiness only)

**Current production truth — unchanged by this document:**
`APPROVED_FINCO_DEPLOYMENTS = ()` (zero approved deployments), token gating **OFF**, resource thresholds **UNSET**.
Nothing described below has been done. This is the sequence to follow *after* FINCO decides, outside this
repository, on a real deployment. No chain, contract, supply, price, holder threshold, staking, burn, token spend,
revenue share or vesting is defined here or anywhere in the entitlement code.

Architecture (no rewrite is needed to activate):

```
verified wallet -> approved deployment (app.verified.token_entitlement.APPROVED_FINCO_DEPLOYMENTS)
  -> read-only balance evidence -> canonical token entitlement -> resource policy -> ALLOW / DENY / INACTIVE
```

Identity is the exact chain id + contract address. Symbol and name are display-only. **Environment variables never
establish token provenance**: only an entry committed to `APPROVED_FINCO_DEPLOYMENTS` (with provenance) is an
authority. RPC URLs, thresholds and the gating flag are operator configuration, not identity.

## Sequence

1. **Approve canonical deployment provenance.** FINCO records, outside the code, which chain and contract are the
   canonical `$FINCO`, and the evidence (e.g. a signed announcement, deployer address, explorer verification).
2. **Commit approved deployment identity.** Add one `ApprovedFincoDeployment(chain_id, token_address, "ERC-20",
   decimals, provenance)` to `APPROVED_FINCO_DEPLOYMENTS` in a reviewed change. Several chains may be listed; a
   resource policy then selects one with `chain_id`. Duplicate or conflicting entries fail validation.
3. **Configure RPC.** Set the server-side `FINCO_TOKEN_RPC_URL_<chain_id>`. It is never sent to a browser or printed.
4. **Independently verify chain + contract + decimals.** Run the read-only check (see below): the provider's
   `eth_chainId` must equal the approved chain and `decimals()` must equal the approved decimals. Do not rely on a
   single operator's say-so; have a second person verify against the provenance.
5. **Configure resource policy threshold.** Via `FINCO_ENTITLEMENT_POLICIES_JSON`, set `enabled` and
   `minimum_balance` per gated resource (and `chain_id` if several chains are approved), and set the runtime
   freshness window `FINCO_ENTITLEMENT_MAX_AGE_SECONDS` to a positive integer (the same variable the runtime
   evaluator requires; no default is assumed — without it every gated decision is `TOKEN_CONFIGURATION_UNAVAILABLE`).
   The amounts are product decisions made elsewhere; nothing in this repository proposes one.
6. **Activate gating explicitly.** Set `FINCO_TOKEN_GATING_ENABLED=1` (and `FINCO_ENTITLEMENT_MAX_AGE_SECONDS`).
   Nothing activates automatically: `READY_FOR_ACTIVATION` is a report, not a switch.
7. **Verify fail-closed behavior.** Confirm that a missing or unverified wallet, an unreachable RPC, a wrong
   chain or contract, a stale balance and a below-threshold balance are all denied, while `yield.basic` stays public.

## Read-only readiness check

```
python tools/finco_token_activation_check.py            # current committed state
python tools/finco_token_activation_check.py --candidate proposal.json   # validate a proposal; never authoritative
```

### Statuses (exactly as implemented)

| Status | Meaning |
|---|---|
| `NOT_CONFIGURED` | Zero approved deployments (production today). |
| `CONFIG_INVALID` | Something present is malformed: invalid, duplicate, conflicting or ambiguous deployments, an invalid candidate or approval status, invalid operator policy config, or a failed fail-closed self-check. |
| `DEPLOYMENT_UNAPPROVED` | A candidate was given that is not identical to the committed approved record (chain, contract, standard, decimals **and provenance**). A candidate is never authority. |
| `RPC_UNAVAILABLE` | No RPC configured for an approved chain, or the read-only probe failed or could not prove `decimals()`. |
| `CHAIN_MISMATCH` | The provider's `eth_chainId` differs from the approved chain. |
| `DECIMALS_MISMATCH` | On-chain `decimals()` differs from the approved decimals. |
| `ACTIVATION_INCOMPLETE` | The deployment is verified but a prerequisite is **missing** (not malformed): no enabled holder resource with a `minimum_balance`, and/or no valid `FINCO_ENTITLEMENT_MAX_AGE_SECONDS`. Gating being ON does not change this. |
| `READY_FOR_ACTIVATION` | Every prerequisite is satisfied — approved + valid deployment, RPC, chain, decimals, at least one enabled holder resource with a threshold, a valid freshness window, fail-closed self-check — and **only** the gating switch is missing. Gating is still OFF. |
| `ACTIVE` | The same prerequisites **and** `FINCO_TOKEN_GATING_ENABLED` is explicitly on. The report lists exactly which holder resources are active (not necessarily all of them). The runtime evaluator can then operate. |

`READY_FOR_ACTIVATION` is a report, not a switch: the tool only makes read-only `eth_chainId` and `decimals()` calls,
never changes configuration, and prints no RPC URL or secret. It exits non-zero unless the status is
`READY_FOR_ACTIVATION` or `ACTIVE`.

# $FINCO Token-Gate Activation Runbook (V1 readiness)

Status: **readiness procedure only.** Nothing here deploys a token, moves
funds, signs transactions, enables execution or activates production
gating.  Gating is OFF by default (`FINCO_TOKEN_GATING_ENABLED` unset).

The gate composes EXISTING authorities only — no parallel entitlement
system exists:

- gate flag + resource policies: `app.protocol.entitlement_policy`
  (`FINCO_TOKEN_GATING_ENABLED`, `FINCO_ENTITLEMENT_POLICIES_JSON`)
- approved deployment selection: `app.protocol.token_deployments`
  (over `app.verified.token_entitlement.APPROVED_FINCO_DEPLOYMENTS` —
  empty in production today)
- P4 token configuration: `app.protocol.token_config`
- read-only balance observation: `app.protocol.token_balance`
  (eth_call `balanceOf`/`decimals` — read-only, 10 s timeout, raw integer
  balances preserved, failures are typed and NEVER zero)
- canonical entitlement: `app.protocol.entitlement_evaluator` /
  `app.verified.token_entitlement.evaluate_token_entitlement`

## Activation procedure

1. **Configure network** — approve the deployment in
   `app.verified.token_entitlement.APPROVED_FINCO_DEPLOYMENTS`
   (chain id + exact ERC-20 contract + decimals + provenance) via a
   reviewed PR.  Environment values can never create a deployment.
2. **Configure token contract** — set the P4 configuration:

   ```text
   FINCO_TOKEN_CHAIN_ID=<chain id>
   FINCO_TOKEN_ADDRESS=<0x… exact deployed contract>
   FINCO_TOKEN_DECIMALS=<explicit decimals authority>
   FINCO_ACCESS_MIN_BALANCE=<threshold in token units — product decision>
   ```

3. **Configure threshold** — the threshold comes from
   `FINCO_ACCESS_MIN_BALANCE` (P4) and/or the per-resource policy override
   `FINCO_ENTITLEMENT_POLICIES_JSON`
   (e.g. `{"yield.history": {"enabled": true, "minimum_balance": "100"}}`).
   Thresholds are a product decision — nothing in the code sets one.
4. **Configure provider** — set the chain-scoped provider the evaluator
   consumes: `FINCO_TOKEN_RPC_URL_<chain_id>=https://…` (server-side only,
   never exposed to the browser; no credentials in the URL).
5. **Verify diagnostics** — run the operator diagnostic:

   ```text
   python -m app.protocol.token_gate_readiness          # configuration only
   python -m app.protocol.token_gate_readiness --probe  # + one read-only
                                                        # balanceOf probe
   ```

   Acceptance: state `READY` with `--probe` reporting `reachable: true`.
   `RPC_UNAVAILABLE` / `TOKEN_CONTRACT_UNAVAILABLE` are typed failures —
   they are never balances, never zero.
6. **Enable gate** — set `FINCO_TOKEN_GATING_ENABLED=1` and (optionally)
   enable individual resources through
   `FINCO_ENTITLEMENT_POLICIES_JSON`.  With the gate OFF, product behaviour
   is byte-for-byte unchanged.
7. **Run acceptance** — `tests/test_token_gate_readiness.py` plus the
   existing entitlement/gating suites.  Confirm: missing evidence is
   denied (fail closed), unavailable evidence is never zero, factual zero
   renders exactly `0`, gating-off behaviour unchanged.

## Invariants

- `$FINCO` never touches the math (assumptions, CAPEX, OPEX, tax, debt,
  DSCR, XIRR, statements, valuation, market observations are unaffected by
  token balance).
- missing ≠ zero · unavailable ≠ zero · RPC failure ≠ zero balance.
- ownership ≠ entitlement; entitlement ≠ execution/metering/staking/burn.
- read-only only: no `eth_sendTransaction`, approve, transfer, signing,
  custody or private keys anywhere in this path.

"""app.protocol — FINCO Token Utility V1 package.

Provides the holder-entitlement rail:
  utility_registry  — stable identifiers and metadata for FINCO capabilities
  token_config      — chain-agnostic token configuration from environment
  token_balance     — read-only ERC-20 balance reader via JSON-RPC
  wallet_auth       — EIP-191 wallet ownership challenge / verify flow
  access_decision   — typed access-decision authority
  router            — FastAPI router mounted at /protocol
"""

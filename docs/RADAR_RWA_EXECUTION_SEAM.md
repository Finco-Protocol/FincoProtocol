# RWA / R-LIVE Execution Seam — Future Design Boundary (NOT SHIPPED)

Status: **DOCUMENTED SEAM ONLY.** No buy/execution code exists in this PR.
No server private key, no custody, no automatic broadcast — ever.

## Current boundary (this PR)

R-LIVE reference observations and RWA market rows are read-only market
intelligence:

- R-LIVE reference ≠ executable quote.
- Reference premium ≠ trading signal.
- RWA observed-market data ≠ underlying asset spot authority.
- BNB deployment ≠ Robinhood deployment.
- Robinhood binding ≠ FINCO Verify.

The BNB capability model makes execution explicit:
`EXECUTION = AVAILABLE / NOT SUPPORTED / UNAVAILABLE`. `NOT SUPPORTED`
means no execution-route authority exists for the row — a BNB contract
alone never implies execution capability, and `ACTIONABLE` filtering
requires `EXECUTION = AVAILABLE`, never mere contract existence.

## Future execution seam (design only)

A future execution layer would reuse FINCO's non-custodial execution
philosophy end to end:

```
R-LIVE / RWA asset (exact canonical identity)
  → exact execution venue / route (typed route authority, no inference)
  → executable quote (venue-quoted, time-bounded, explicitly labelled)
  → fees / slippage disclosure (itemised before signing)
  → execution gap (quote vs reference; already modelled in B1.x authority)
  → connected-wallet signing (user's wallet; server NEVER holds keys)
  → user-broadcast settlement (no automatic broadcast; no custody)
```

Hard invariants for any future implementation:

1. Server-side private keys are prohibited; signing happens in the user's
   connected wallet only.
2. No custody: funds move only through user-signed transactions.
3. No automatic broadcast: the user reviews and submits.
4. Execution capability is a separately defined authority — never inferred
   from market observation, deployment existence, or identity binding.
5. Reference data stays labelled as reference: quotes must carry their own
   venue/timestamp authority and expiry.
6. Token authority, Signed Run authority, Verify authority and Yield
   authority remain unchanged by the execution layer.

# FINCO V1 — Independent Opus Review Prompt

You are performing a clean-room security and authority review of FINCO V1.
You have no prior context from the development history. Use only the files
in this OPUS_V1_REVIEW/ package and the repository at the SHA below.

## Entry Point

Repository: `Finco-Protocol/FincoProtocol`
Main SHA at handoff: `5b6abf71c7286db5e8fd172983f4505f7e3b18ce`

## Review Scope

1. **Authority firewall integrity** — verify that the nine invariants in
   `03_AUTHORITY_BOUNDARIES.md` hold in the code. Pay particular attention to:
   - B2.3: `app/usage/ledger.py`, `app/usage/query.py` — can a caller supply
     `subject_id`, `wallet_address`, or bypass session identity?
   - B2.2: `app/verified/token_entitlement.py` — is there any fallback that
     grants access when the token check fails?
   - Run Certificate: `app/verify/run_certificate.py` — does it ever call
     the financial engine? Does it accept Working Copy inputs?

2. **Frozen namespace integrity** — verify that `financial_engine/**`,
   `finco_core/**`, `app/verified/**`, `finco_radar/**` contain no
   unexpected side effects (network calls, state mutation, secret exposure).

3. **Identity spoofing** — can any API endpoint in `app/api/v1_1/`,
   `app/api/v1/`, or `main_web.py` be called to obtain another user's
   usage data, Verified dossier, or run certificate?

4. **Missing != Zero** — in `app/usage/query.py` and `finco_radar/gap/`,
   verify that storage failures and observation gaps are structurally
   distinct from empty/zero results.

5. **Capability contract consistency** — run
   `pytest tests/test_p0_4_capability_contract.py tests/test_product_capability_consistency.py -v`
   and verify all pass. Any failure means a surface disagrees with
   `app/product_capability.py`.

6. **B2.3 full test suite** — run
   `pytest tests/test_b2_3_usage_metering.py -v`
   and verify all 29 tests pass.

7. **Known limitations** — verify that the limitations in
   `05_KNOWN_LIMITATIONS.md` are accurately described (no under-stating,
   no over-stating).

## What NOT to Review

- Jev / Reflex (issue #119) — experimental, not V1 scope.
- `domain/` — internal domain models, not a V1 authority surface.
- Browser UI templates — not in scope for this authority review.
- Financial model correctness (IRR, DSCR arithmetic) — not in scope.

## Format

Return findings as:

```
FINDING [n]: <module:line> — <one sentence>
SEVERITY: CRITICAL | MAJOR | MINOR | INFORMATIONAL
EVIDENCE: <specific code path or test that demonstrates the issue>
RECOMMENDATION: <specific fix>
```

If no findings: `NO FINDINGS — invariants hold as described.`

Do NOT assign a score. Do NOT fabricate findings. Do NOT infer from
intent; verify from code.

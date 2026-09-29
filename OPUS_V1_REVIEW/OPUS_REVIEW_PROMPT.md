# FINCO V1 — Independent Opus Review Prompt

You are performing a clean-room independent review of FINCO V1.
You have no prior context from the development history.

Use only the files in this `OPUS_V1_REVIEW/` package and the repository at
the SHA below. Do not assume anything about the system from any other source.

This package describes the implemented repository state. It is not a marketing
document. Do not treat this as an invitation to confirm its claims — your job
is to independently verify or challenge them.

---

## Entry Point

Repository: `Finco-Protocol/FincoProtocol`
**Main SHA at handoff: `8cd58ad8f50108bbe9931751a4ef8d5b3feef797`**

Clone and review at this exact SHA.

---

## What You Are Reviewing

FINCO V1 — an off-chain deterministic project-finance modelling and verification
platform. The product narrative is:

> **Model + Radar + Verify + Signed Run + API/MCP + $FINCO**

Your job is to determine whether this narrative is internally coherent, whether
each component does what it claims, and whether any component contaminates
another in a way that breaks authority boundaries or makes a misleading claim.

---

## Review Dimensions

### A. Enterprise SaaS Readiness

- Is the codebase structured for multi-tenant use, or is it single-tenant/pilot stage?
- Are sessions, identity, and data isolation sufficient for multiple institutional users?
- Are there missing controls (rate limiting, audit logging, access revocation)?
- What is missing before a controlled institutional pilot launch?

### B. Financial-Model / Authority Integrity

- Does the CALCULATE layer (`financial_engine/`, `finco_core/`) stay frozen and
  side-effect-free? No network calls, no state mutation, no secret exposure?
- Is the Working Copy / Last Run separation correctly enforced everywhere?
  Can any surface return Working Copy values labeled as Last Run?
- Is `PRODUCTION_VERIFIED_ASSET_COUNT` accurate? Are any MODEL_ONLY records
  presented as VERIFIED?

### C. RWA / Crypto Product Coherence

- Is the product narrative (Model + Radar + Verify + Signed Run) internally
  coherent?
- Does Radar data flow into the financial engine in any code path?
- Is R-LIVE correctly separated from execution price? Does any surface imply
  a reference observation is tradeable?
- Is the BNB Tokenized Assets / Radar capability correctly kept separate from
  the Model verticals?

### D. Security / Identity / Provenance Architecture

- Can any API endpoint in `app/api/v1_1/`, `app/api/v1/`, or `main_web.py`
  be called to obtain another user's usage data, Verified dossier, or run
  certificate?
- Can a caller supply `subject_id`, `wallet_address`, or bypass session identity
  in B2.2 or B2.3?
- Does B2.2 (`app/verified/token_entitlement.py`) have any fallback that grants
  access when the token check fails?
- Does the Signed Run Certificate ever call the financial engine or accept
  Working Copy inputs? (`app/services/run_certificate_service.py`)
- Does the Trust Pack rendering (`app/ui/trust_pack.py`) ever issue a certificate
  or run the model at page render time?
- Is the Ed25519 signing in the Signed Run Certificate correctly implemented?
  Can a caller with no configured key obtain a certificate?

### E. API + MCP Agent Readiness

- Are the 9 MCP tools (`finco_supported_today`, `finco_projects`, `finco_last_run`,
  `finco_run_identity`, `finco_kpis`, `finco_validation`, `finco_verify`,
  `finco_r_live`, `finco_export_metadata`) truly read-only?
- Does any MCP tool perform state mutation, trigger model runs, or expose
  internal exceptions?
- Is MCP session identity correctly derived from `FINCO_SESSION_TOKEN` and not
  from caller-supplied arguments?
- Are the MCP tool responses stable (versioned, typed) or fragile?

### F. UX / Institutional Usability

- Does the Model Trust Pack UX V1 (`app/ui/trust_pack.py`,
  `app/templates/v2/partials/sheet_trust.html`) correctly distinguish its
  7 sections (A–G)?
- Does it correctly present MODEL VALIDATION ≠ FINCO VERIFY?
- Does it correctly present Signed Run Certificate ≠ FINCO VERIFY?
- Are DEFERRED sections (C: Validation, G: Certificate) correctly guarded —
  no actionable load URL without a committed Last Run?
- Does the CSS presentation correctly restrict green status to VERIFIED only?

### G. Public-Launch Blockers

- What would prevent a controlled institutional public launch today?
- Identify any capability described as LIVE that is not reliably deployable.
- Identify any authority boundary that is asserted in docs but not enforced in code.
- Identify any known limitation in `05_KNOWN_LIMITATIONS.md` that is understated.

### H. Product Narrative Coherence

Does the narrative **Model + Radar + Verify + Signed Run + API/MCP + $FINCO**
hold together without token contaminating math/truth?

Specifically verify:
- `$FINCO NEVER TOUCHES THE MATH` — no token balance/entitlement affects any
  financial calculation.
- `$FINCO NEVER DETERMINES WHETHER EVIDENCE IS TRUE` — no token state affects
  Verify outcomes.
- `SIGNED RUN ≠ FINCO VERIFY` — no code path converts a signed certificate into
  a VERIFIED status.
- `MODEL VALIDATION ≠ FINCO VERIFY` — no code path converts a validation pass
  into VERIFIED.
- `MARKET REFERENCE ≠ EXECUTABLE PRICE` — no Radar reference leaks into engine
  inputs.

---

## Specific Historical Problem Areas — Verify These

1. **Working Copy vs Last Run** — confirm that no API endpoint or export surface
   returns Working Copy values labeled as Last Run outputs.

2. **Export-time rerun** — confirm that institutional XLSX export reads persisted
   outputs and never re-runs the financial engine.

3. **Last Run identity completeness** — confirm that `app/services/run_certificate_service.py`
   fails closed for incomplete identity and refuses to substitute current values.

4. **Validation vs Verify** — confirm that no code path in `app/model_validation/`
   sets a VERIFIED status or updates `app/verified/`.

5. **Verify fail-closed behavior** — confirm that `app/verified/token_entitlement.py`
   has no access-granting fallback on exception.

6. **Market identity authority** — confirm that `finco_radar/authority/cross_chain.py`
   requires source-attested evidence and cannot be satisfied by name/symbol alone.

7. **Independent reference provenance** — confirm that R-LIVE reference prices
   never flow into `financial_engine/` as inputs.

8. **Reference vs executable price** — confirm that no R-LIVE observation is
   presented as a tradeable or executable price in any API response.

9. **R-LIVE writer/read boundary** — confirm that read paths in
   `app/radar_rwa/r_live_service.py` perform zero history writes. External
   collector is sole history writer.

10. **Signed Run vs Verify separation** — confirm that issuing a Signed Run
    Certificate does not create or update any record in `app/verified/`.

11. **Token/access vs truth/math separation** — confirm that B2.2 entitlement
    decisions and B2.3 usage recording have no effect on any financial calculation
    or verification outcome.

12. **Missing != zero** — confirm `app/usage/query.py` and `finco_radar/gap/`
    structurally distinguish storage failures from empty/zero results.

13. **Supported Today consistency** — run
    `pytest tests/test_p0_4_capability_contract.py tests/test_product_capability_consistency.py -v`
    and verify all pass.

14. **Trust Pack render guard** — confirm `app/ui/trust_pack.py:build_trust_pack()`
    never calls `issue_run_certificate()`. Certificate issuance must only occur
    via `build_certificate_fragment()` from an explicit user-triggered endpoint.

---

## What NOT to Review

- `domain/` — internal domain models, not a V1 authority surface.
- `tests/test_b2_2_token_entitlement.py` — has a pre-existing `eth_account`
  module missing error in CI (infrastructure issue, not in scope).
- Financial model arithmetic correctness (IRR, DSCR values) — not in scope for
  this authority review.
- Jev / Reflex (issue #119) — experimental shadow, explicitly not V1 scope.

---

## Format for Findings

```
FINDING [n]: <file:line or surface> — <one sentence>
SEVERITY: BLOCKER | HIGH | MEDIUM | LOW | INFORMATIONAL
EVIDENCE: <specific code path, test, or API call that demonstrates the issue>
WHY IT MATTERS: <why this is a problem for a public/institutional launch>
RECOMMENDED CORRECTION: <specific fix>
BLOCKS PUBLIC LAUNCH: YES / NO / CONDITIONAL
```

Severity definitions:
- **BLOCKER**: must be fixed before any controlled institutional exposure
- **HIGH**: serious issue; fix before public launch
- **MEDIUM**: should be fixed; workaround may exist
- **LOW**: improvement; not a launch blocker
- **INFORMATIONAL**: observation only; no required action

If no findings in a dimension: `NO FINDINGS — invariants hold as described.`

---

## Instructions

- Do NOT assign an overall score.
- Do NOT fabricate findings. Verify from code, not from intent.
- Do NOT tell us FINCO is enterprise-ready or expected to pass.
- Do NOT tell us specific gaps are "already solved" unless you have verified them.
- Verify each historical problem area independently.
- Cross-check the Known Limitations in `05_KNOWN_LIMITATIONS.md` — if any is
  understated or overstated, say so as a finding.
- If a LIVE capability in `02_CAPABILITY_MATRIX.md` is not reliably deployable
  given documented limitations, flag it.
- Report your findings ordered by severity (BLOCKER first).

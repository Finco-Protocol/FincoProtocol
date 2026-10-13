# F3.5-B Advanced Financing: release-closed integration

## Provenance and first architecture preflight

Verified origin/main: `cff1a7b19a72429636ec20325aadf5364365b12d`.
Branch: `feat/model-f35b-advanced-financing`. Diagnostics #268 is separate.
Production Junior activation remains OFF. No financial successor is authorized
by this implementation. Exact HEAD, CI and numerical evidence follow in the
Draft PR handoff; a document cannot contain its own commit SHA.

| Capability | Status | Actual authority / remaining boundary |
| --- | --- | --- |
| Versioned facilities, stable IDs, dated draws | EXISTING | F3.1 `financing_instruments.py`; strict serialization |
| Two-Senior execution | EXISTING | `multisenior.py`; fixed contractual commitments, not mixed bank sizing |
| One-Senior + one-Junior execution | EXISTING, RELEASE CLOSED | F3.5-A `junior_debt.py`; isolated candidate fixtures only |
| Two-Senior + Junior | UNSUPPORTED | F3.5-A requires exactly one Senior and one Junior |
| Senior / Junior cash IDC and eligible Senior fees | EXISTING | Separate funded asset and existing contractual primitives; no Junior fees |
| Construction funding and Sources & Uses | EXISTING | Canonical construction allocation and Project Uses; no plugs |
| Senior-first service / full-payment rejection | EXISTING | Final Base CFADS, then contractual Junior service; no refinancing or PIK |
| Tax / book basis / statements / returns | EXISTING | Ordinary TaxPolicy, separate Junior liability/interest, financing-independent Project IRR |
| CAS, scenario ownership, immutable Run and export | EXISTING | F3 workspace snapshot, canonical writer, Last Run evidence and export binding |
| Capital Stack Junior proposal display | PARTIAL | Read-only proposal exists; zero subtotal and pari-passu labels misstate it |
| Customer Junior activation/editor | UNSUPPORTED | `app/workbook/junior_debt_config.py:ACTIVATION_ENABLED=False` |
| F3 form CSRF | MISSING | Existing `/v2/workbook/update` field path lacks CSRF; separate bounded authorization requested |
| Facility-level tax attribution | UNSUPPORTED | F3.8 explicitly exposes aggregate tax only |
| SHL, reserves, VAT facility, ATAD/thin-cap, mezzanine, multiple Junior | UNSUPPORTED | Existing F3.5-A fail-closed boundary; no extension here |

The historical F3 blueprint/spec describe a foundation proposal. The merged
F3.5-A, F3.6, F3.7 and F3.8 code/reports, not the obsolete foundation status,
determine the implemented capability inventory above.

## Implementation boundary

Reuse the accepted 15 financial/core blobs and existing nine application
integration modules. Do not change financial calculations, release pins,
historical authorities, F4, Revenue V2, numerical tooling or Diagnostics.
Complete the existing Capital Stack's truthful release-closed presentation and
extend missing adversarial and numerical acceptance, rather than duplicate the
existing 16-case oracle or introduce a new debt solver.

Policy without a persisted explicit authority is UNAVAILABLE, not defaulted.
Construction draws are scheduled inputs, not actual funded cash. A proposal
never obtains calculated Last Run evidence or a production ACTIVE label.

## Future activation gate

1. Independent review of exact protected content (no new protected content here).
2. Explicit approval of the supported one-Senior/one-Junior ordinary-tax policy.
3. Complete exact-head CI and independent financial/security acceptance.
4. Separately reviewed application activation diff; no customer JSON bypass.
5. Operational/staging acceptance, currently PENDING.

Two-Senior + Junior requires a separate financial-authority proposal; it is not
an activation toggle for the existing one-Senior candidate.

## Acceptance evidence

Pending local focused numerical/lifecycle/browser execution and exact-head CI.
No pass or production readiness is claimed before those gates complete.

# Signed Run Certificate V1

The authenticated `GET /api/v1.1/projects/{project_id}/run-certificate` signs a
committed Last Run. It never runs the model and never signs Working Copy state.
Incomplete run identity fails closed with `LAST_RUN_IDENTITY_INCOMPLETE`.
Legacy runs without a run-bound workbook version must be run again before they
can be signed; the current workbook version is never substituted at issuance.

The service requires `FINCO_RUN_CERT_SIGNING_KEY`, a base64-encoded, 32-byte
Ed25519 seed supplied through deployment configuration. There is no fallback
production key. Keep the seed outside the repository and logs.

The certificate contains an explicit UTC-aware `issued_at`, issuer, run identity,
KPI digest, signing algorithm, kid binding, key identifier, payload digest, and
signature. Canonical JSON uses sorted keys and compact UTF-8 encoding. The same
payload bytes signed with the same key produce the same Ed25519 signature;
separate issuance times create different payloads and signatures.

Signing is not FINCO Verify, economic truth, model correctness, or an executable
market price. The certificate carries no synthetic Verify observation. Verify
remains a separate `app/verified` authority.

## Public trust and verification (M-2)

The pinned-trust problem above is closed by the version-controlled public
signing-key registry manifest, `app/protocol/signing_keys_registry.json`
(schema `finco-signing-keys-v1`). It is the single trust authority for:

- `GET /.well-known/finco/keys.json` — RFC 8615 discovery document;
- `GET /api/v1.1/protocol/signing-keys` — byte-identical API mirror;
- `POST /api/v1.1/run-certificates/verify` — public verifier;
- `python tools/verify_finco_run_certificate.py <cert.json>` — standalone
  offline verifier (bundled manifest is the default trust root; `--keys`
  accepts a freshly downloaded discovery document).

Verification is unauthenticated, needs no token, no wallet, and performs no
engine calls or writes. Verdict states are typed and cryptographic:
`VALID`, `INVALID_SIGNATURE`, `UNKNOWN_KEY_ID`, `KEY_NOT_VERIFY_CAPABLE`,
`KEY_NOT_VALID_FOR_CERTIFICATE_TIME`, `PAYLOAD_DIGEST_MISMATCH`,
`UNSUPPORTED_CERTIFICATE_VERSION`, `UNSUPPORTED_ALGORITHM`,
`MALFORMED_CERTIFICATE`, `VERIFICATION_UNAVAILABLE`. Failure details are
sanitized — no tracebacks, no exception text, no key material.

The certificate's `kid` binding is explicit; a legacy `key_id` fingerprint
alone is never a trust anchor. A key verifies a certificate only if its
`ACTIVE`/`VERIFY_ONLY` status permits verification AND the certificate's
issuance time falls inside the key's `activated_at`/`retired_at` window.

## Operational configuration

Issuance (deployment-side, private material — never committed):

- `FINCO_RUN_CERT_SIGNING_KEY` — base64 of the 32-byte Ed25519 seed.
- `FINCO_RUN_CERT_SIGNING_KID` — kid of the ACTIVE record in the registry
  manifest whose public key must equal the configured key's derived public
  key; otherwise issuance fails closed (`SIGNING_KEY_UNKNOWN_KID`,
  `SIGNING_KEY_REGISTRY_MISMATCH`).

Rotation runbook (see `docs/review/M2_SIGNED_RUN_PUBLIC_TRUST.md` §6):
generate the new key in an HSM/KMS → add its PUBLIC record to the manifest
as `ACTIVE` via reviewed PR → switch issuance env vars → mark the old key
`VERIFY_ONLY` with a `retired_at` timestamp in a second reviewed PR. Never
delete retired keys; never commit private material; the bundled canonical
key is a deterministic test fixture and must be replaced before production.


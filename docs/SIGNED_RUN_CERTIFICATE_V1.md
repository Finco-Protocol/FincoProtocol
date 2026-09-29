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
KPI digest, signing algorithm, key identifier, payload digest, and signature.
Canonical JSON uses sorted keys and compact UTF-8 encoding. The same payload
bytes signed with the same key produce the same Ed25519 signature; separate
issuance times create different payloads and signatures.

Verification requires the expected FINCO public key in DER form. A valid
signature proves cryptographic integrity and provenance **only if that public
key or its fingerprint was independently trusted and pinned**. A self-supplied
key or key identifier alone does not establish the issuer's identity.

Signing is not FINCO Verify, economic truth, model correctness, or an executable
market price. The certificate carries no synthetic Verify observation. Verify
remains a separate `app/verified` authority.

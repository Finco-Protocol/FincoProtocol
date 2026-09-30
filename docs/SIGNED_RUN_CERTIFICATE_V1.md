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
(schema `finco-signing-keys-v1`). The manifest SHIPS WITH `keys: []` — no
key is trusted by default (`PUBLIC_ISSUER_KEY_NOT_CONFIGURED`): no key whose
private counterpart is publicly known or deterministically reconstructable
is ever shipped as a trust anchor. A production issuer public key is
committed only via reviewed PR when a real deployment supplies it; its
private key stays outside git, logs, and PRs. Until then public verification
returns `UNKNOWN_KEY_ID` for every certificate and issuance fails closed.

The manifest is the single trust authority for:

- `GET /.well-known/finco/keys.json` — RFC 8615 discovery document;
- `GET /api/v1.1/protocol/signing-keys` — byte-identical API mirror;
- `POST /api/v1.1/run-certificates/verify` — public verifier;
- `python tools/verify_finco_run_certificate.py <cert.json>` — standalone
  offline verifier (bundled manifest is the default trust root; `--keys`
  accepts a freshly downloaded discovery document).

The public API and the offline CLI share ONE verification core
(`app/protocol/run_certificate_verifier.py`) — the same certificate plus the
same registry returns the same state through both surfaces.

Verification is unauthenticated, needs no token, no wallet, and performs no
engine calls or writes. Verdict states are typed and cryptographic:
`VALID`, `INVALID_SIGNATURE`, `UNKNOWN_KEY_ID`, `KEY_NOT_VERIFY_CAPABLE`,
`KEY_NOT_VALID_FOR_CERTIFICATE_TIME`, `PAYLOAD_DIGEST_MISMATCH`,
`UNSUPPORTED_CERTIFICATE_VERSION`, `UNSUPPORTED_ALGORITHM`,
`MALFORMED_CERTIFICATE`, `KEYS_DOCUMENT_INVALID` (offline, malformed trust
document), `VERIFICATION_UNAVAILABLE`. Failure details are sanitized — no
tracebacks, no exception text, no key material.

The certificate's `kid` binding is explicit; a legacy `key_id` fingerprint
alone is never a trust anchor. `issued_at` is required and must be
timezone-aware — key validity is decided against `issued_at` only (`run_at`
is never consulted; naive timestamps are never silently read as UTC). A key
verifies a certificate only if its status permits verification AND the
certificate's `issued_at` falls inside the key's `activated_at`/`retired_at`
window.

Key states: `ACTIVE` issues and verifies; `VERIFY_ONLY` verifies historical
certificates only (rotation); `REVOKED` neither issues nor verifies
(compromise). Rotation is not compromise — a compromised key must be
removable from trust even if that invalidates certificates relying on it.

## Operational configuration

Issuance (deployment-side, private material — never committed):

- `FINCO_RUN_CERT_SIGNING_KEY` — base64 of the 32-byte Ed25519 seed.
- `FINCO_RUN_CERT_SIGNING_KID` — kid of the ACTIVE record in the registry
  manifest whose public key must equal the configured key's derived public
  key; otherwise issuance fails closed (`SIGNING_KEY_UNKNOWN_KID`,
  `SIGNING_KEY_REGISTRY_MISMATCH`).
- The deployment's public key must be committed to the manifest via
  reviewed PR before any certificate can publicly verify.

Rotation runbook (see `docs/review/M2_SIGNED_RUN_PUBLIC_TRUST.md` §8):
generate the new key in an HSM/KMS → add its PUBLIC record to the manifest
as `ACTIVE` with an explicit timezone-aware `activated_at` via reviewed PR →
switch issuance env vars → mark the old key `VERIFY_ONLY` with a
`retired_at` timestamp in a second reviewed PR. For a compromised key, set
`REVOKED` — it then neither issues nor verifies. Never delete retired keys;
never commit private material; never ship a key whose private counterpart
is publicly known or deterministically reconstructable.



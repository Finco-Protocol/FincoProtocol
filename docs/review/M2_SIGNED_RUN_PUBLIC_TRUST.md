# FINCO M-2 — Signed Run Public Trust — Review Dossier

Correction B cut (trust-root security hardening). Branch:
`protocol/m2-signed-run-public-trust`. Base: main `77f29ae` (post-#146) +
merged sync of `7c4655b` (post-#147).

**Scope discipline:** this dossier covers the M-2 public trust closure ONLY.
It does not modify PR #143 surfaces (README, ROADMAP, OPUS_V1_REVIEW,
trust-pack templates/UI), `financial_engine/**`, `finco_core/**`,
`finco_radar/**`, `app/verified/**`, `app/model_validation/**` (all ZERO
DIFF), and does not change `app.verified` truth semantics or
`PRODUCTION_VERIFIED_ASSET_COUNT`.

---

## 1. What M-2 is (and is not)

Signed Run Public Trust closes the loop opened by Signed Run Certificate V1
(PR #132): a certificate is only as useful as the public ability to verify
it **without** access to the signing process, the database, or any session.

M-2 ships:

- a **version-controlled public signing-key registry manifest** — the single
  trust authority (`app/protocol/signing_keys_registry.json`);
- a **public key discovery** surface (`/.well-known/finco/keys.json`, RFC
  8615) and an **API mirror** (`GET /api/v1.1/protocol/signing-keys`) — both
  rendered from the SAME manifest (one source, byte-identical documents);
- a **public, unauthenticated certificate verifier**
  (`POST /api/v1.1/run-certificates/verify`) with typed, sanitized verdicts;
- a **standalone offline verifier** (`tools/verify_finco_run_certificate.py`)
  whose default trust root is the bundled manifest;
- **ONE shared verification core** (`app/protocol/run_certificate_verifier.py`)
  used by BOTH the public API and the offline CLI — the same certificate plus
  the same registry returns the same state through both surfaces.

M-2 does NOT ship (explicit non-goals, unchanged):

- BLOCKCHAIN_ANCHORING = **NOT_SHIPPED**
- TOKEN_GATING = **NOT_ADDED** — `PUBLIC_VERIFICATION_REQUIRES_TOKEN = NO`,
  `PUBLIC_VERIFICATION_REQUIRES_WALLET = NO`
- FINCO Verify status changes — verification is **never** `FINCO_VERIFIED`;
- economic truth claims — a valid signature proves provenance/integrity of
  the bytes, nothing else.

## 2. Trust root policy (Correction B, P0)

**No publicly forgeable trust root.** Correction A bundled a canonical test
key (`seed = bytes(range(32))`) as the default trusted public key — its
private counterpart was publicly reconstructable, so anyone could forge a
certificate the public verifier accepted as VALID. Correction B removes that
entirely:

- the shipped manifest contains **`keys: []`** — no default trusted key
  (`PUBLIC_ISSUER_KEY_NOT_CONFIGURED`);
- until a real deployment commits its public issuer key (reviewed PR),
  public verification returns `UNKNOWN_KEY_ID` for every certificate and
  issuance fails closed;
- deterministic fixture keys exist ONLY in test code / tmp fixtures; a
  regression test proves a certificate signed with the known test seed is
  **UNKNOWN_KEY_ID against the default registry**
  (`KNOWN_TEST_PRIVATE_KEY_CAN_FORGE_DEFAULT_TRUST_ROOT = NO`);
- no production private key is ever generated or committed in this PR.

When a real issuer key is supplied externally: commit ONLY the public key,
with a truthful production/staging kid; the private key stays outside git,
logs, PR comments, and agent output.

## 3. Trust authority: the version-controlled manifest

- `app/protocol/signing_keys_registry.json` — public material only:
  `kid`, `algorithm`, DER `public_key`, `public_key_encoding`, `jwk`,
  `status`, `activated_at`, `retired_at`, `issuer`, `schema_version`
  (`finco-signing-keys-v1`).
- Loaded at import time by `app/protocol/signing_keys.py`
  (`load_registry_manifest`) — **fail-closed at import**: an invalid bundled
  manifest refuses to boot the process; no partial registry is exposed.
- Runtime `register_key()` remains for tests / deployment bootstrap; every
  registration path runs the same strict validation.

### STRICT ATOMIC validation (Correction B, P1)

Every manifest / keys-document entry is validated in full; any invalid
entry rejects the WHOLE document (`SigningKeyRegistryError`):

- exact `schema_version` and `issuer` (document level and entry level);
- algorithm exactly `Ed25519`; encoding exactly `DER`;
- unique, non-empty `kid`; no duplicates;
- cryptographically valid Ed25519 public key (real `ECC.import_key` +
  curve check — P-256 or garbage DER rejected);
- JWK `kty = "OKP"`, `crv = "Ed25519"`, and `x` EXACTLY equal to the DER
  key's raw 32-byte public point (JWK/DER binding);
- status in `{ACTIVE, VERIFY_ONLY, REVOKED}`;
- explicit **timezone-aware** `activated_at` (required); optional
  timezone-aware `retired_at` with `activated_at < retired_at`;
  naive timestamps are rejected — never silently read as UTC;
- strict field allow-list — unknown fields rejected;
- issuer/schema consistency between entries and document.

Negative tests cover every rule above, plus atomicity (one valid + one
invalid entry → whole document rejected) and file-level failures
(unreadable / non-JSON manifest).

### Key confusion removal (Correction A, preserved)

`tools/_offline_keys.json` (previously committed) carried a **different
public key under the same kid** as the trust manifest, and tests wrote
runtime key documents into `tools/`. Correction A deleted it; runtime
verifier artifacts are gitignored; offline-verifier tests write key
documents to pytest `tmp_path` only.

## 4. ONE shared verification core (Correction B, P2)

`app/protocol/run_certificate_verifier.py` owns the entire verification
state machine: structural validation, explicit kid resolution, key state,
strict time validity, independent payload-digest recompute, `key_id`
crosscheck, canonical bytes, Ed25519 verification, typed sanitized states.

- The public API router is a thin adapter (`verify_certificate_against_registry`
  → `verify_certificate(cert, all_keys())`).
- The offline CLI is a thin adapter (bundled manifest or `--keys` document →
  `verify_certificate(cert, records)`).
- Parity tests prove core == API == offline CLI state for VALID and
  tampered certificates with the same trust list.

## 5. Verification contract (identical in API and offline CLI)

1. **Structural invariants** → `MALFORMED_CERTIFICATE` (missing
   signature / payload digest / oversized certificate — 1 MB canonical
   cap), `UNSUPPORTED_CERTIFICATE_VERSION`, `UNSUPPORTED_ALGORITHM`
   (Ed25519 only).
2. **Explicit kid** → the certificate MUST carry `kid`. No fallback to the
   legacy `key_id` fingerprint or any other field; a `key_id`-only
   certificate is `MALFORMED_CERTIFICATE`. `key_id` remains in V1
   certificates as an integrity crosscheck only — never a trust anchor.
3. **kid resolution** → exact lookup, no fuzzy matching →
   `UNKNOWN_KEY_ID` otherwise.
4. **Rotation / revocation contract (P5)** → `ACTIVE` and `VERIFY_ONLY`
   keys verify historical certificates; **`REVOKED` (compromised) keys
   verify NOTHING** → `KEY_NOT_VERIFY_CAPABLE`. Issuance accepts ONLY
   ACTIVE keys and fails closed on `SIGNING_KEY_UNKNOWN_KID` /
   `SIGNING_KEY_REGISTRY_MISMATCH` / missing kid env binding.
   **Rotation is not compromise:** retiring (VERIFY_ONLY) never breaks
   history; revoking removes trust even for historical certificates.
5. **STRICT certificate time (P4)** → `issued_at` is REQUIRED and MUST be
   timezone-aware; naive timestamps are rejected, never silently read as
   UTC; `run_at` is NEVER consulted (different authority). Key validity is
   decided against `issued_at` only: the key's `activated_at`/`retired_at`
   window must contain it → otherwise
   `KEY_NOT_VALID_FOR_CERTIFICATE_TIME`.
6. **Payload digest recompute** → the stated `payload_digest` must equal an
   independent recompute over the received fields → otherwise
   `PAYLOAD_DIGEST_MISMATCH`. Tampering caught precisely before the
   signature check; a tamperer who also recomputes the digest still fails
   `INVALID_SIGNATURE`.
7. **Ed25519 verification** over the canonical signed bytes → `VALID`
   with `signature_valid: true`, or `INVALID_SIGNATURE`.

Failure details are **sanitized**: no traceback printing, no exception
class names or messages, no key material in any response or stdout.
Unexpected internal errors surface as HTTP 503 `VERIFICATION_UNAVAILABLE`
(API) or a typed JSON verdict (offline), never a stack trace.

### Malformed external keys documents (Correction B, P3)

The offline CLI validates `--keys` documents atomically; malformed
documents (missing public_key, invalid base64, non-Ed25519 DER, malformed
JWK, duplicate kid, malformed timestamps, oversized document) return a
typed `KEYS_DOCUMENT_INVALID` machine-readable failure — never an uncaught
traceback, never raw exception text, never key material. Malformed
certificate signature base64 → sanitized `INVALID_SIGNATURE`.

## 6. Surfaces

| Surface | Route / path | Auth | Source |
| --- | --- | --- | --- |
| Well-known discovery | `GET /.well-known/finco/keys.json` | none | manifest via `public_keys_document()` |
| API mirror | `GET /api/v1.1/protocol/signing-keys` | none | same function — byte-identical output |
| Public verifier | `POST /api/v1.1/run-certificates/verify` | none | shared core + registry |
| Offline verifier | `python tools/verify_finco_run_certificate.py cert.json` | none | shared core + bundled manifest (default) or `--keys` document |

Verifier guarantees (tested): zero engine calls, zero Working Copy access,
zero Last Run / FINCO Verify / Radar mutations, zero DB writes, no token or
wallet requirement.

## 7. Legacy certificate policy (explicit)

Certificates issued under PR #132 before the kid binding existed carry
`key_id` but no `kid`. Policy: such certificates are
**`MALFORMED_CERTIFICATE` for public verification** — they were never
publicly verifiable (no public registry existed before M-2), so nothing
that was previously accepted is now rejected. Re-issue under the current
issuance path if a historical run needs a publicly verifiable certificate.
No silent migration, no fallback trust.

## 8. Operational configuration

Issuance (deployment-side, private):

- `FINCO_RUN_CERT_SIGNING_KEY` — base64 of the 32-byte Ed25519 seed.
  Never committed, never logged; the service fails closed
  (`SIGNING_KEY_UNAVAILABLE`) when absent or malformed.
- `FINCO_RUN_CERT_SIGNING_KID` — the kid of the ACTIVE registry record
  whose public key must equal the configured key's derived public key.
- With the shipped `keys: []` manifest, a deployment must commit its real
  public key to the manifest (reviewed PR) AND register/hold the private
  key in its own configuration (`PUBLIC_ISSUER_KEY_NOT_CONFIGURED` until
  then).

Rotation vs compromise runbook:

- **Rotation (planned):** generate the NEW key in an HSM/KMS → add its
  PUBLIC record to the manifest as `ACTIVE` with `activated_at` = now
  (reviewed PR) → switch issuance env vars → mark the old key
  `VERIFY_ONLY` with `retired_at` = switch time (second reviewed PR).
  Historical certificates stay verifiable.
- **Compromise (REVOKED):** if a private key is compromised, set its
  status to `REVOKED` (reviewed PR). It can no longer issue OR verify —
  certificates relying on it stop verifying. That is the point: a
  compromised key must be removable from trust.

Never delete keys from the manifest (revocation, not deletion, is the
mechanism); never commit private material.

Verification (public, private-key-free): fetch
`/.well-known/finco/keys.json` (or use the bundled manifest) and run the
offline verifier; or POST the certificate to the public verify endpoint.

## 9. Test coverage (M-2 suite — 60 tests, all green)

- P0/P7: bundled manifest ships `keys: []` with no seed documentation;
  certificate signed by the known test seed is UNKNOWN_KEY_ID against the
  default trust root (`KNOWN_TEST_PRIVATE_KEY_CAN_FORGE_DEFAULT_TRUST_ROOT
  = NO`).
- Discovery: well-known document shape, determinism, public-material-only;
  API mirror byte-identical to well-known.
- Issuance kid binding: missing kid / unknown kid / registry mismatch /
  VERIFY_ONLY issuance / REVOKED issuance all fail closed.
- Rotation + revocation: VERIFY_ONLY verifies history; REVOKED verifies
  nothing (API + offline) and cannot issue.
- Public verifier: VALID; tampered field → `PAYLOAD_DIGEST_MISMATCH`;
  tampered + attacker-recomputed digest → `INVALID_SIGNATURE`; tampered
  signature; unknown kid; unsupported algorithm/version; malformed;
  legacy key_id-only → `MALFORMED_CERTIFICATE`; missing issued_at (with
  run_at present) → `MALFORMED_CERTIFICATE` (no fallback); naive
  issued_at → `MALFORMED_CERTIFICATE`; key activated-after /
  retired-before issuance → `KEY_NOT_VALID_FOR_CERTIFICATE_TIME`;
  in-window key → VALID; REVOKED → `KEY_NOT_VERIFY_CAPABLE`; oversized
  certificate → `MALFORMED_CERTIFICATE`; sanitized failure details; no
  engine calls.
- P2 parity: shared core == API == offline CLI for VALID and tampered.
- P3: malformed external keys documents (missing/invalid public_key,
  non-Ed25519 DER, 4 JWK corruptions, duplicate kid, naive/missing
  activated_at, naive retired_at, retired-before-activated, wrong schema
  version/issuer, unknown field) → typed `SigningKeyRegistryError`;
  offline CLI → typed sanitized `KEYS_DOCUMENT_INVALID` (incl. non-JSON
  file); file-level manifest failures fail closed; valid empty manifest
  loads.
- Registry hardening: real Ed25519 validation rejects P-256 and garbage
  DER; `public_keys_document()` contains no private material.

Regression: `tests/test_signed_run_certificate.py` (updated fixture for
the strict registry), EV suites untouched.

## 10. Status

| Item | Status |
| --- | --- |
| Signed Run Certificate V1 issuance (PR #132 lineage) | SHIPPED (config-gated) |
| M-2 public trust closure (this branch) | **OPEN DRAFT PR — not merged; not shipped until merged** |
| DEFAULT_TRUST_ROOT_PRIVATE_KEY_PUBLICLY_KNOWN | NO |
| DEFAULT_REGISTRY_TEST_KEY | NO |
| KNOWN_TEST_PRIVATE_KEY_CAN_FORGE_DEFAULT_TRUST_ROOT | NO |
| BLOCKCHAIN_ANCHORING | NOT_SHIPPED |
| TOKEN_GATING | NOT_ADDED |
| PUBLIC_VERIFICATION_REQUIRES_TOKEN | NO |
| PUBLIC_VERIFICATION_REQUIRES_WALLET | NO |

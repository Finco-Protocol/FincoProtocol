# FINCO M-2 — Signed Run Public Trust — Review Dossier

Correction A cut. Branch: `protocol/m2-signed-run-public-trust`.
Base: main `77f29ae` (post-#146) + merged sync of `7c4655b` (post-#147).

**Scope discipline:** this dossier covers the M-2 public trust closure ONLY.
It does not modify PR #143 surfaces (README, ROADMAP, OPUS_V1_REVIEW,
trust-pack templates/UI), `financial_engine/**`, `finco_core/**`,
`finco_radar/**` (all ZERO DIFF), and does not change `app.verified`
truth semantics or `PRODUCTION_VERIFIED_ASSET_COUNT`.

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
  whose default trust root is the bundled manifest.

M-2 does NOT ship (explicit non-goals, unchanged):

- BLOCKCHAIN_ANCHORING = **NOT_SHIPPED**
- TOKEN_GATING = **NOT_ADDED** — `PUBLIC_VERIFICATION_REQUIRES_TOKEN = NO`,
  `PUBLIC_VERIFICATION_REQUIRES_WALLET = NO`
- FINCO Verify status changes — verification is **never** `FINCO_VERIFIED`;
- economic truth claims — a valid signature proves provenance/integrity of
  the bytes, nothing else.

## 2. Trust authority: the version-controlled manifest

Before Correction A the runtime registry was a process-local dict seeded
only by runtime registration (tests) — production trust had no committed,
auditable source. Correction A replaces that with:

- `app/protocol/signing_keys_registry.json` — public material only:
  `kid`, `algorithm`, DER `public_key`, `public_key_encoding`, `jwk`,
  `status` (ACTIVE / VERIFY_ONLY), `activated_at`, `retired_at`, `issuer`,
  `schema_version` (`finco-signing-keys-v1`).
- Loaded at import time by `app/protocol/signing_keys.py`
  (`_load_bundled_registry`); runtime `register_key()` remains available for
  tests/deployment bootstrap but production trust no longer depends on it.
- Real cryptographic validation on every registration path:
  `Crypto.PublicKey.ECC.import_key` + curve check — a non-Ed25519 or garbage
  DER record raises `ValueError` (fail-closed), it is never stored as opaque
  bytes.
- The bundled canonical key (`finco-prod-2026-01`) is a **deterministic test
  fixture key** (`seed = bytes(range(32))`) and its manifest `notes` field
  says exactly that. It must be replaced with an HSM-generated key before
  production deployment. **No real production private key is committed;
  a deterministic test public key is never labelled prod-usable.**

### Key confusion removal (Correction A)

`tools/_offline_keys.json` (previously committed) carried a **different
public key under the same kid** (`finco-prod-2026-01`) than the trust
manifest, and tests wrote runtime key documents into `tools/`. Correction A:

- deletes `tools/_offline_keys.json` from the repository;
- gitignores `tools/_offline_cert.json` / `tools/_offline_keys.json` so
  runtime verifier artifacts can never be committed again;
- offline-verifier tests write key documents to pytest `tmp_path` only.

## 3. Verification contract (public API and offline verifier — identical)

Both verifiers run the same checks, in the same order, over the same
canonical bytes (`canonical_certificate_signing_bytes`: sorted keys, compact
separators, UTF-8):

1. **Structural invariants** → `MALFORMED_CERTIFICATE` (missing
   signature / payload digest / timestamps), `UNSUPPORTED_CERTIFICATE_VERSION`,
   `UNSUPPORTED_ALGORITHM` (Ed25519 only).
2. **Explicit kid** → the certificate MUST carry `kid`. There is **no
   fallback** to the legacy `key_id` fingerprint or any other field; a
   certificate with only `key_id` is `MALFORMED_CERTIFICATE`. The `key_id`
   fingerprint remains in V1 certificates as an integrity crosscheck only —
   never a trust anchor.
3. **kid resolution** → exact lookup in the registry, no fuzzy matching →
   `UNKNOWN_KEY_ID` otherwise.
4. **Rotation contract** → `ACTIVE` and `VERIFY_ONLY` keys both verify
   historical certificates; anything else → `KEY_NOT_VERIFY_CAPABLE`.
   Issuance (separate path, `run_certificate_service.issue_run_certificate`)
   accepts **only** ACTIVE keys and fails closed on
   `SIGNING_KEY_UNKNOWN_KID` / `SIGNING_KEY_REGISTRY_MISMATCH` (derived
   public key must equal the registry record) / missing kid env binding.
5. **Key time validity** → the key must have been inside its
   `activated_at`/`retired_at` window at the certificate's `issued_at`
   (falling back to `run_at`) → otherwise
   `KEY_NOT_VALID_FOR_CERTIFICATE_TIME`. An open end (`retired_at: null`)
   stays valid. Rotation never invalidates history: a VERIFY_ONLY key whose
   window covered issuance still verifies.
6. **Payload digest recompute** → the stated `payload_digest` must equal an
   independent recompute over the received fields (everything except
   `payload_digest` and `signature`) → otherwise `PAYLOAD_DIGEST_MISMATCH`.
   This catches tampering with a precise typed state BEFORE the signature
   check; a tamperer who also recomputes the digest still fails
   `INVALID_SIGNATURE` because the canonical bytes no longer match the
   signature.
7. **Ed25519 verification** over the canonical signed bytes (certificate
   minus `signature`) → `VALID` with `signature_valid: true`, or
   `INVALID_SIGNATURE`.

Failure details are **sanitized**: no traceback printing, no exception class
names or messages, no key material in any response or stdout. Unexpected
internal errors surface as HTTP 503 `VERIFICATION_UNAVAILABLE` (API) or a
typed JSON verdict (offline), never a stack trace.

## 4. Surfaces

| Surface | Route / path | Auth | Source |
| --- | --- | --- | --- |
| Well-known discovery | `GET /.well-known/finco/keys.json` | none | manifest via `public_keys_document()` |
| API mirror | `GET /api/v1.1/protocol/signing-keys` | none | same function — byte-identical output |
| Public verifier | `POST /api/v1.1/run-certificates/verify` | none | registry + canonical bytes |
| Offline verifier | `python tools/verify_finco_run_certificate.py cert.json` | none | bundled manifest (default) or `--keys` document |

Verifier guarantees (tested): zero engine calls, zero Working Copy access,
zero Last Run / FINCO Verify / Radar mutations, zero DB writes, no token or
wallet requirement.

## 5. Legacy certificate policy (explicit)

Certificates issued under PR #132 before the kid binding existed carry
`key_id` but no `kid`. Policy: such certificates are **`MALFORMED_CERTIFICATE`
for public verification** — they were never publicly verifiable (no public
registry existed before M-2), so nothing that was previously accepted is now
rejected. Re-issue under the current issuance path if a historical run needs
a publicly verifiable certificate. No silent migration, no fallback trust.

## 6. Operational configuration

Issuance (deployment-side, private):

- `FINCO_RUN_CERT_SIGNING_KEY` — base64 of the 32-byte Ed25519 seed.
  Never committed, never logged; the service fails closed
  (`SIGNING_KEY_UNAVAILABLE`) when absent or malformed.
- `FINCO_RUN_CERT_SIGNING_KID` — the kid of the ACTIVE registry record whose
  public key must equal the configured key's derived public key.

Rotation runbook:

1. Generate a NEW key in an HSM/KMS; derive the public DER.
2. Add the new record to `signing_keys_registry.json` with
   `status: ACTIVE`, `activated_at` = now (UTC), `retired_at: null`; open a
   reviewed PR (this file is the trust root — changes must be reviewed like
   code).
3. Deploy the manifest update; switch issuance env vars to the new kid.
4. Retire the old key: set `status: VERIFY_ONLY` and `retired_at` = switch
   time in a second reviewed PR. **Never delete a retired key** — historical
   certificates must stay verifiable.

Verification (public, private-key-free): fetch
`/.well-known/finco/keys.json` (or use the bundled manifest) and run the
offline verifier; or POST the certificate to the public verify endpoint.

## 7. Test coverage (M-2 suite — 32 tests, all green)

- Discovery: well-known document shape, determinism, public-material-only.
- API mirror == well-known (one source).
- Issuance kid binding: missing kid / unknown kid / registry mismatch /
  VERIFY_ONLY issuance all fail closed; kid + fingerprint present in cert.
- Rotation: VERIFY_ONLY verifies history; ACTIVE required for new issuance.
- Public verifier: VALID path; tampered field → `PAYLOAD_DIGEST_MISMATCH`;
  tampered field + attacker-recomputed digest → `INVALID_SIGNATURE`;
  tampered signature → `INVALID_SIGNATURE`; unknown kid; unsupported
  algorithm/version; malformed; legacy key_id-only → `MALFORMED_CERTIFICATE`;
  key activated-after / retired-before issuance →
  `KEY_NOT_VALID_FOR_CERTIFICATE_TIME`; in-window key → VALID; sanitized
  failure details (no exception text, no key material); no engine calls.
- Offline verifier: VALID (explicit keys doc AND bundled manifest trust
  root), tampered → `PAYLOAD_DIGEST_MISMATCH`, unknown kid, expired window.
- Registry hardening: real Ed25519 validation rejects P-256 and garbage DER;
  manifest seeds the process registry; `public_keys_document()` contains no
  private material.

Regression: `tests/test_signed_run_certificate.py` 24/24,
`tests/test_ev_charging_efficiency_authority.py` 13/13,
`tests/test_ev_charging_range_parity.py` 13/13.

## 8. Status

| Item | Status |
| --- | --- |
| Signed Run Certificate V1 issuance (PR #132 lineage) | SHIPPED (config-gated) |
| M-2 public trust closure (this branch) | **OPEN DRAFT PR — not merged; not shipped until merged** |
| BLOCKCHAIN_ANCHORING | NOT_SHIPPED |
| TOKEN_GATING | NOT_ADDED |
| PUBLIC_VERIFICATION_REQUIRES_TOKEN | NO |
| PUBLIC_VERIFICATION_REQUIRES_WALLET | NO |

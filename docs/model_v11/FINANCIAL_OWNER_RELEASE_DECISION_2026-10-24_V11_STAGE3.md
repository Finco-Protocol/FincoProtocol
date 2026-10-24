# Financial Owner exact release decision — V11 Stage 3a+3b with V10 Stage 1+2 (PR #360, Correction A)

**Decision (2026-10-24, conversation): APPROVE EXACT RELEASE**, subject to byte-exact verification of the packet and the record
below. The verification was performed before recording, and every identity matched the reviewed candidate.

- Release packet `docs/model_v11/V11_STAGE3_RELEASE_PACKET.json`: sha256
  `f6059daca9c3fd067af2d6c1385b5d01e54c596310070a90a8e395dd8892cbca`
- Exact release record `docs/model_v11/v11-stage3-release-authority.json`: sha256
  `60b8d508973d3c5ad22ae221c48a9854ae83444cc5be6b47dfe081731f4f2581`. It is pinned in code in
  `tests/v11_stage3_release_authority.py`; owner authority is that reviewed pin, never a JSON field.
- Reference: `conversation:2026-10-24:PR360-CorrectionA:Financial-Owner-Release-Decision:V11-Stage3+V10-Stage1+2-permanent-production`

## Approved scope

- Permanent production activation of V11 Stage 3a+3b together with V10 Stage 1+2. This resolves the outstanding V10
  production release authority for this combined configuration.
- Activation happens during the approved production deployment immediately following an independently approved normal
  merge.
- No pilot, canary, phased rollout or separate staging acceptance.
- Verified native binaries (`deploy/scripts/release_native.sh install`) and a permanent configuration across service restarts
  (`/opt/finco_protocol/.env.native`).
- Canonical fallback, the independent kill switches and the existing financial exactness requirements remain mandatory.
  Unsupported and non-process-isolated Runs remain canonical.

## Verified identities

- Content checkpoint `94fd918e547f818cc0ca256db96f5fe1a165dc45` (tree `7131ab3ba632ac35bd31ea0368cce99ba7e393cc`); content
  record sha256 `f0555f999b10359af9243494e1115387c25a3554689a8cdba9da0dab1dd470c0`, unchanged.
- Release candidate `08d8108e4f4bdbf11b340b98275d9b750f5c4196` (tree `2d2da00db6b346eae2bc579314bd738078166415`).
- Release surface blobs:
  - `app/runtime/native_activation.py` `75eb68bd…`
  - `tools/native_release.py` `2eaf84c7…`
  - `deploy/scripts/release_native.sh` `8421e3e3…`
  - `deploy/systemd/finco-web.service` `eea293b4…`
  - `deploy/env.example` `78bcb2bf…`
- The 8 protected engine blobs are unchanged; the V10 package is unchanged since `9e712e21` (no reseal).
- Runtime identities:
  - V10 Stage 1: build `ced5b63a…`, artifact `da763e0e…`
  - V10 Stage 2: build `1471f6d8…`, artifact `34dc14a9…`
  - V11 Stage 3: build `9b96a831…`, artifact `eda33517…`

## Not authorized

- Merging without independent final review.
- Deployment or activation before the approved merge.
- Changes to the eight protected engine blobs.
- A V10 reseal.
- Relaxation of CI, financial tests or governance.

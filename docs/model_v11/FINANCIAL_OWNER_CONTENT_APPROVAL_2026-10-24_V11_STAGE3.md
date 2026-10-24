# Financial Owner exact-content decision — V11 Stage 3a + 3b (2026-10-24)

**Decision:** APPROVE EXACT CONTENT (one consolidated decision for Stage 3a native tax and Stage 3b native
senior-debt model evaluation).

* Packet: `docs/model_v11/V11_STAGE3_APPROVAL_PACKET.json`, sha256
  `eaa2a05b60eb407b9e3c22a716168245413baca1637542c096be5dc9ec0c8be1`.
* Base: V10 checkpoint `main` `9e712e21b9efd1a57fe702f178a496aaefb427ec` (tree `e8305ab1…`).
* Source candidate: `3bf206d0d4c3b0430916cd05eae552dd3b5fed77` (tree `0d775362e0689f3b0f9a76d82341f2c620ead227`), no
  approval record.
* Exactly 8 protected blobs: `financial_engine/financing/project.py` (`3bc6c097` -> `4d77988d`, default-off hook) and the
  seven new `financial_engine/native_v11/` files (blobs in the packet and in `tests/v11_stage3_successor.py`).
* Stage 3 build: ABI 30001, build ID `9b96a8312bd6cec7c66098370164149f0ef5f9f5265db2b9e91abce5773a7344`, artifact sha256
  `eda33517ec07522e3985ccc02228b30289d4c471bbeb5745b51f8e7373817963`, gcc 13.3.0, x86_64-linux-gnu.
* V10 Stage 1 / Stage 2 sources, artifacts and manifests unchanged (no reseal).

**Not authorised:** Stage 3 activation, staging or production enablement, deployment, V10 reseal, runtime
compilation, merge. Recognition by the governance successor is content recognition only, never a financial release.

Owner authority is the reviewed code pin (`OWNER_APPROVAL_SHA256` in `tests/v11_stage3_successor.py`) of the byte-exact
record `docs/model_v11/v11-stage3-content-approval.json`, never a self-asserting JSON field.

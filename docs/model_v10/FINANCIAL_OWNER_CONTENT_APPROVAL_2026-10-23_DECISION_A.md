# PR #347 Decision A — V10 dormant native shadow: exact-content Financial Owner decision

Reference: `conversation:2026-10-23:PR347:Financial-Owner-Exact-Content-Approval:Decision-A`. Record: `docs/model_v10/v10-native-shadow-content-approval.json` (sha256 `0eaa1d17cbb4201ef6fa94963b45f37e7530efb5925e4b906e4c081e1c79e5a5`, pinned in
`tests/v10_native_shadow_successor.py`).

Basis: explicit user-provided Financial Owner statement in this conversation on 2026-10-23. This is not a signed GitHub review or a
cryptographic owner attestation. Existing exact-content governance requires reviewed code-level content pins; it does not require a signed
GitHub attestation. The statement authorizes this exact content recognition and CI closure only.

Approved packet SHA-256: `81e653c0677ae53ae9ac8c5c9d8c4fab8da434ad58283999654cc4eb26b6059e` (the packet lists Decision A and Decision B separately).
Statement SHA-256: `7daebfe919f1e7844d35f6388aa900363ffba4e7d425e1c0c0485b7551ae85c2`.

## Verbatim decision

> **Financial Owner — Exact-Content Approval / PR #347**
>
> I explicitly approve **Decision A (V10 dormant native shadow)** and **Decision B (R-LIVE Python 3.10 compatibility)** exactly as listed in approval packet SHA-256:
>
> `81e653c0677ae53ae9ac8c5c9d8c4fab8da434ad58283999654cc4eb26b6059e`
>
> Approval is limited to the listed exact source blobs, their stated checkpoints, governance successor recognition and CI closure.
>
> This does not authorize native activation, replace mode, candidate-then-canonical, Stage 3, deployment, hosted pilot or merge.
>
> Write the two separate exact-content approval records, verify their hashes, complete the local acceptance gate and push the consolidated governance correction to the existing PR #347.
>
> Require all mandatory exact-head CI checks green.
>
> Stop for ChatGPT independent final review. No automatic merge.

## Non-circular source chain

Immutable checkpoint (`main`, PR #346 merged): `0b57031ae6949d8e7d187a1932c4451e213238f7` / tree `608b4ae23169d2fbce084c6f63e4fd43925549b5`.
Exact source candidate (all approved blobs, no approval record): `f137aaccff601c2f86126e1215165a7edc81574d` / tree `1bd953ed1967c82a76e8f7c0a84caa7347c027f1`.

## Approved exact blobs

| Path | Checkpoint blob | Approved blob |
|---|---|---|
| `financial_engine/senior_debt/solver.py` | `6cf4a6cd9f149f271d4b61a60bb6b0aa70e4c9e0` | `9d30525b3fc09b422c1deb38784bf49834cbac35` |
| `financial_engine/shl/production.py` | `9bb852c235a988bff994c4327b3b63dd6d77ae20` | `fb563770bc87a0a8403e21e5f571ebec39840f18` |
| `financial_engine/native_v10/__init__.py` | `(new file)` | `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` |
| `financial_engine/native_v10/approved_canonical_blobs.json` | `(new file)` | `c24555f03783d67f6aa9f3af16b497a805710960` |
| `financial_engine/native_v10/approved_canonical_blobs_stage2.json` | `(new file)` | `74c025e6e45660d6143161daa11480b94eec0ce6` |
| `financial_engine/native_v10/build.py` | `(new file)` | `0fce6c25c3d37545012a49fa246a2a6a9d38c615` |
| `financial_engine/native_v10/build_stage2.py` | `(new file)` | `509c18541f07db8acb9fca384069ccc767af4eb9` |
| `financial_engine/native_v10/config.py` | `(new file)` | `5e7f4994583384a0ef5ec88efa798dc9c361e8b1` |
| `financial_engine/native_v10/dispatch.py` | `(new file)` | `31e02b8a6c833d5dc37138cd175dfec2d3d2973a` |
| `financial_engine/native_v10/eligibility.py` | `(new file)` | `9bf5683680c9f0725454bb2760049a159d00cea6` |
| `financial_engine/native_v10/fk_v10_manifest.json` | `(new file)` | `af6b668048d2ba2e74685dd21251fdafe2749ea6` |
| `financial_engine/native_v10/fk_v10_stage2_manifest.json` | `(new file)` | `a656d48153f870bbbe8b03c72ac8b5fb797301fc` |
| `financial_engine/native_v10/isolation.py` | `(new file)` | `9e227d17d975cd09685f20e6495c3645f202b4c0` |
| `financial_engine/native_v10/kernel_v10.c` | `(new file)` | `e0b5372aec22261cc4e82e8348fb6089a5d1ba77` |
| `financial_engine/native_v10/kernel_v10_stage2.c` | `(new file)` | `29cb3e3874ccd3e10cbc482c10c8f83f08158584` |
| `financial_engine/native_v10/loader.py` | `(new file)` | `80993fb46cf3539e9dd8018da1b5da29db9de2ba` |
| `financial_engine/native_v10/provenance.py` | `(new file)` | `769f0e645b4267be05aadefb09a22f7763f3199c` |
| `financial_engine/native_v10/stage2.py` | `(new file)` | `90121690f598a9eaf6944dc038e386c80bfaef9c` |
| `app/services/production_financial_authority.py` | `89083cd41a4de029ae3c57ee0a4f4a871c7863bd` | `98c04020d03711f3683b5340fc2f89387a60553c` |
| `app/runtime/model_execution.py` | `22dd596a826a1fdfe3e7eb0e9fab6b75c75310a3` | `c8c5a0dc184b8901c7cb292b0dbbd248e4cf191a` |
| `app/runtime/native_shadow.py` | `(new file)` | `2351375d62878aa5c7156ee881601260a9de4114` |
| `main_web.py` | `e005ece7002ea8e07edb98f15da3d5c9c2731a8a` | `9b3734417fe6cd931b7814e015ca42d5c9264f8b` |

Wiring: `tests/quarterly_candidate_recognition.py` → `d27dbceb9aa2483a33bc205652dd0e58fc976d8d`.

**Not authorized:** native activation, replace mode, candidate-then-canonical, Stage 3, runtime compilation, deployment, hosted pilot, merge,
or any other blob (including any later edit of these paths). Decision B is a separate record and grants nothing here.

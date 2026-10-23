# PR #347 Decision B — R-LIVE Python 3.10 compatibility (issue #348): exact-content Financial Owner decision

Reference: `conversation:2026-10-23:PR347:Financial-Owner-Exact-Content-Approval:Decision-B`. Record: `docs/ci_v3/final/r-live-lifecycle-py310-content-approval.json` (sha256 `9a3d55ac1866381a67ecd394ed98377ea19c48f01a493f61c661778ccac17f64`, pinned in
`tests/r_live_lifecycle_py310_successor.py`). The PR #346 decision (`conversation:2026-10-22:PR346:Correction-D:section-1`), its record and
its authority module are NOT edited; they remain judged at the checkpoint.

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

| Path | PR #346 approved blob | Approved blob |
|---|---|---|
| `app/radar_rwa/r_live_snapshot_store.py` | `4179c296c803f42040b2811dc70ef55a1cdfa1d0` | `4179c296c803f42040b2811dc70ef55a1cdfa1d0` |
| `app/radar_rwa/r_live_warming.py` | `563c1a256886f7b26af21ac63e121216f908c840` | `c29fe4cdfe4e07df6ecd82a2a714f13f4b78d7e9` |

Guard adapter: `tests/r_live_lifecycle_governance.py` → `3ea649e983b2c634328ef24a312d49e06f408171`.

**Not authorized:** runtime activation, workflow deployment, hosted shadow, image publication, Phase 4 activation, merge, or any other blob.
Decision A is a separate record and grants nothing here.

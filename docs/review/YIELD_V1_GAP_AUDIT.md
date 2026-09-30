# FINCO Yield — PR #148 Gap Audit

Baseline reviewed HEAD: `7a1a308719b4f43eb21f1dbb69767468911d942d`.

This audit is the required pre-change classification for the Yield master stream.

| Area | State | Finding |
|---|---|---|
| Y0 exact yield identity | DONE | Exact chain/protocol/product/contract/underlying/share identity exists. |
| Y0 evidence schema | PARTIAL | Confidence/provenance exists, but final typed V1 evidence and canonicalization are incomplete. |
| Y0 live opportunities | PARTIAL | 14 exact Morpho observations exist on Ethereum/Base; they are frozen `NATIVE_ENRICHED` research observations, not block-bound current state. |
| Y0 underwriting primitives | PARTIAL | APY decomposition/scenarios exist; net APY/exit semantics need completion. |
| Y0 evidence hashes | PARTIAL | Generic canonical JSON/SHA-256 exists; Decimal/time semantics need freezing. |
| Y0 execution plan | PARTIAL | Unsigned plan exists, but caller-supplied destination/underlying/share fields are an authority defect. |
| Y0 Enso / 0x clients | PARTIAL | Spike-level wrappers; raw provider response trust and contract-target validation are incomplete. |
| Y0 feature flags | DONE | Yield and execution are independently OFF by default. |
| Y1 Explore/filter/detail | NOT DONE | Only an isolated prototype exists. |
| Y1 freshness/history | PARTIAL | Generic freshness exists; no immutable history contract. |
| Y2 Underwrite/Compare/Evidence | PARTIAL | No complete Compare surface or typed `YIELD_EVIDENCE_V1`. |
| Y2 exit semantics | NOT DONE | No typed `INSTANT/QUEUED/LOCKED/UNKNOWN` contract. |
| Y3 wallet monitor | NOT DONE | Existing FINCO verified-wallet infrastructure is available but not reused by Yield. |
| Y4 canonical execution binding | NOT DONE | Must resolve economic destination from canonical opportunity registry. |
| Y4 approvals | PARTIAL | Unlimited approvals fail closed; full allowance → exact approval → deposit plan is incomplete. |
| Y4 receiver / quote immutability | PARTIAL | Useful checks exist but do not bind a canonical opportunity snapshot. |
| Y4 wallet signing | DEFERRED BY DESIGN | No custody, private keys, server signing or automatic broadcast. |
| Y4 pre-trade evidence | PARTIAL | Needs typed binding to underwriting + quote + approvals + receiver. |
| Y4 post-trade receipt | NOT DONE | Typed design required; no mainnet transfer required. |

## Priority order

1. Fix canonical execution binding before broader execution UX.
2. Introduce a typed exact-UID registry while preserving the 14 frozen observations as research evidence.
3. Implement block-bound ERC-4626 direct reads without silently upgrading native observations to direct authority.
4. Freeze typed Yield evidence/canonicalization.
5. Build Explore, Detail, Compare, immutable History and read-only Wallet Monitor.
6. Normalize Enso/0x into FINCO-owned typed contracts and fail closed on unknown targets.
7. Keep production signing/broadcast, custody, pooled funds, proprietary vaults and automated allocation out of V1.

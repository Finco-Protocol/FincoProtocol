# FINCO V1 — PR / SHA Ledger

All entries verified from `git log origin/main` at final live main SHA
`8cd58ad8f50108bbe9931751a4ef8d5b3feef797`.

Merge SHAs are the SHA on `main` after merge. Entries are newest-first within
each stream.

---

## Model Trust Pack UX V1 (PR #133)

| PR | Capability | Accepted Feature HEAD | Merge SHA | State |
|---|---|---|---|---|
| #133 | Model Trust Pack UX V1 — 7-section read-only evidence surface; Corrections A1–A4 (CSS, Section G certificate, fail-closed validation, labeling) | `ab8bd68fcde079a2bec685c258b0d593ee08819f` | `8cd58ad8f50108bbe9931751a4ef8d5b3feef797` | MERGED |

Evidence: 31/31 trust pack UX tests pass; 4/4 CI checks SUCCESS.
Changed files (7): `app/ui/trust_pack.py`, templates, router, tests.
Frozen namespaces: ZERO DIFF.

---

## Signed Run Certificate V1 (PR #132)

| PR | Capability | Accepted Feature HEAD | Merge SHA | State |
|---|---|---|---|---|
| #132 | Signed Run Certificate V1 — Ed25519, committed Last Run only, fail-closed identity | `e292442a9ddd0ff4703f8009e8bbabf9554946a8` | `c9abf435b62086c5a19ec7660fc78bc0653196df` | MERGED |

Key properties: Ed25519 (`cryptography` library), FINCO canonical JSON (sorted keys,
compact UTF-8), `FINCO_RUN_CERT_SIGNING_KEY` required, no fallback key,
no Working Copy values, legacy runs without workbook_version fail closed.

---

## V1 Product Truth Freeze (PR #130)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #130 | docs: V1 Product Truth Freeze — align product documentation with canonical implemented behavior | `cf67770504d4e07cda9094a76e4af3af5a48ce24` | MERGED |

---

## B2.3 Usage / Metering (PR #128)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #128 | B2.3 Correction A — subject-scoped idempotency, session identity, wallet canonical resolution, query failure distinction | `5b6abf71c7286db5e8fd172983f4505f7e3b18ce` | MERGED |
| (non-merge) | B2.3 V1 initial — append-only off-chain usage ledger | `1f53b8b` (direct push) | MERGED |

---

## MCP V1 (PR #129)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #129 | MCP V1 + Correction A — read-only institutional agent interface, dependency pin, version responses, exception boundary | `1f273d9` | MERGED |

MCP tools (9): `finco_supported_today`, `finco_projects`, `finco_last_run`,
`finco_run_identity`, `finco_kpis`, `finco_validation`, `finco_verify`,
`finco_r_live`, `finco_export_metadata`.

---

## R-LIVE Ops (PR #127)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #127 | R-LIVE collector timer — external R-LIVE collector operational package | `52aac6e` | MERGED |

---

## API v1.1 Institutional (PR #125)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #125 | API v1.1 Institutional Read-Only Surface — Correction A + B | `a94e77f` | MERGED |

---

## R-LIVE (PR #124, #126)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #126 | R-LIVE operational activation — read-only R-LIVE collection and surface | `13b86c8` | MERGED |
| #124 | R-LIVE token reference authority — exact on-chain AAPL token reference | `9ebb314` | MERGED |

---

## B2.2 Token Entitlement (PR #122)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #122 | B2.2 FINCO token entitlement — fail-closed FINCO token entitlement for Verified dossiers | `dfb8657` | MERGED |

---

## B2.1 Verified Assets / P5 (PR #120)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #120 | B2.1 first real Verified asset — fail-closed Verified provenance gate and dossier entitlement | `4100307` | MERGED |

---

## P1.4 EV Institutional Reconciliation (PR #123)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #123 | P1.4 EV institutional reconciliation closure | `b9c4d1a` | MERGED |

---

## P1.3 Institutional Validation (PR #121)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #121 | P1.3 Institutional Validation & Reconciliation Pack (+ Corrections A and B) | `412324c` | MERGED |

---

## P1.1 Institutional Model Trust Pack (PR #118)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #118 | P1.1 Trust Pack authority hardening (+ Corrections A, B, C) | `678fc8f` | MERGED |

---

## P0.4 Release Integrity / Supported Today (PR #115)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #115 | P0.4 Canonical Supported Today capability contract | `abbc4b0` | MERGED |

---

## P3 Run Certificate V1 — Initial (PR #101)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #101 | P3 Run Certificate V1 (initial hash-based) | `9f67d91` | MERGED |

**Note:** PR #101 established the initial run certificate framework (hash-based).
PR #132 upgraded it to Ed25519 asymmetric signing. The current canonical
implementation is in `app/services/run_certificate_service.py` (PR #132).

---

## Radar B1 (PR #114, #116, #117)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #117 | B1.3 BNB premium, execution gap, exact-identity history | `b6e4001` | MERGED |
| #116 | B1.2 cross-chain canonical identity | `ca8c0cd` | MERGED |
| #114 | B1.1 BNB RWA market intelligence | `93eda9a` | MERGED |

---

## Model Last Run P0.3 (PR #113)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #113 | P0.3 Canonical Reference Model Last Run — EV Charging vertical | `8b24a15` | MERGED |

---

## Notes

- `#119` (Jev / Reflex) is NOT merged. It is experimental/shadow and outside V1 authority.
- No entries are fabricated. SHAs verified from `git log origin/main`.
- PRs merged as direct commits to main appear as regular commit SHAs.
- Inspect with:
  ```bash
  git log 8cd58ad8 --oneline
  git log 8cd58ad8 --oneline --merges
  ```

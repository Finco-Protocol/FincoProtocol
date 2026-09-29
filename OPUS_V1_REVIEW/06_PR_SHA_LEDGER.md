# FINCO V1 — PR / SHA Ledger

All entries verified from `git log origin/main` at handoff SHA
`5b6abf71c7286db5e8fd172983f4505f7e3b18ce`.

Merge SHAs are the SHA on `main` after merge. Entries are newest-first.

---

## B2.3 Usage/Metering

| PR | Description | Merge SHA |
|---|---|---|
| #128 | B2.3 Correction A — subject-scoped idempotency, session identity, wallet canonical resolution, query failure distinction | `5b6abf71` |
| (non-merge) | B2.3 V1 initial — append-only off-chain usage ledger | `1f53b8b` (direct push) |

---

## MCP V1

| PR | Description | Merge SHA |
|---|---|---|
| #129 | MCP V1 + Correction A — read-only institutional agent interface, dependency pin, version responses, exception boundary | `1f273d9` (merge commit) |

---

## R-LIVE Ops

| PR | Description | Merge SHA |
|---|---|---|
| #127 | R-LIVE collector timer — external R-LIVE collector operational | `52aac6e` |

---

## API v1.1 (Institutional)

| PR | Description | Merge SHA |
|---|---|---|
| #125 | API v1.1 Institutional Read-Only Surface — Correction A + B | `a94e77f` (direct merge) |

---

## R-LIVE (Radar Live)

| PR | Description | Merge SHA |
|---|---|---|
| #126 | R-LIVE operational activation — read-only R-LIVE collection and surface | `13b86c8` |
| #124 | R-LIVE token reference authority — exact on-chain AAPL token reference | `9ebb314` |

---

## B2.2 Token Entitlement

| PR | Description | Merge SHA |
|---|---|---|
| #122 | B2.2 FINCO token entitlement — fail-closed FINCO token entitlement for Verified dossiers | `dfb8657` |

---

## B2.1 Verified Assets (P5)

| PR | Description | Merge SHA |
|---|---|---|
| #120 | B2.1 first real Verified asset — fail-closed Verified provenance gate and dossier entitlement | `4100307` |

---

## P1.4 EV Institutional Reconciliation

| PR | Description | Merge SHA |
|---|---|---|
| #123 | P1.4 EV institutional reconciliation closure | `b9c4d1a` |

---

## P1.3 Institutional Validation

| PR | Description | Merge SHA |
|---|---|---|
| #121 | P1.3 Institutional Validation & Reconciliation Pack (+ Corrections A and B) | `412324c` |

---

## P1.1 Institutional Model Trust Pack

| PR | Description | Merge SHA |
|---|---|---|
| #118 | P1.1 Trust Pack authority hardening (+ Corrections A, B, C) | `678fc8f` |

---

## P1.2 XLSX Export / Reconciliation

Delivered as part of P1.1 stream. Test file: `tests/test_p1_2_xlsx_export_reconciliation.py`.
Merge SHA: included in `678fc8f` (P1.1 final sync).

---

## P0 Release Integrity / Supported Today

| PR | Description | Merge SHA |
|---|---|---|
| #115 | P0.4 Canonical Supported Today capability contract | `abbc4b0` |

---

## Signed Run / Run Certificate (P3)

| PR | Description | Merge SHA |
|---|---|---|
| #101 | P3 Run Certificate V1 | `9f67d91` |

---

## Radar B1 (BNB RWA / Cross-Chain Identity / Intelligence)

| PR | Description | Merge SHA |
|---|---|---|
| #117 | B1.3 BNB premium, execution gap, exact-identity history | `b6e4001` |
| #116 | B1.2 cross-chain canonical identity | `ca8c0cd` |
| #114 | B1.1 BNB RWA market intelligence | `93eda9a` |

---

## Model Last Run (P0.3)

| PR | Description | Merge SHA |
|---|---|---|
| #113 | P0.3 Canonical Reference Model Last Run — EV Charging vertical | `8b24a15` |

---

## Notes

- PRs merged as direct commits to main (no merge commit) appear as regular
  commit SHAs in the log.
- The full git log can be inspected with:
  ```bash
  git log 5b6abf71 --oneline --merges
  git log 5b6abf71 --oneline
  ```
- No entries are fabricated. "PENDING FINAL MERGE" entries are not needed —
  all V1 streams listed above are merged as of handoff SHA `5b6abf71`.

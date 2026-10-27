# GAP-R5 / GAP-R6 — Financing studio and Investors: authority map

## What is editable, derived, read-only or not released

| Area | State in React | Authority and writer |
|---|---|---|
| Gearing cap, target DSCR, all-in rate, tenor | editable (existing editor, unchanged) | `POST /v2/workbook/update`; scalar controls lock with their reason when a typed schedule owns them |
| **Bankability**: sizing mode, lender case (Solar/Wind), day count, **period-specific all-in rates and DSCR targets**, scalar target, financing fees, reserve policy | **editable — new typed editor** | `debt.bankability.configuration` through the same per-field writer; `parse_config` validates; fee/reserve/rate authority gates apply |
| Overview, Senior pricing / DSCR authority, Last Run evidence | derived, read-only | Legacy Debt-sheet context |
| **Senior facilities (Two-Senior capital stack)** | **read-only; editing NOT RELEASED in React** | `build_capital_stack` over the saved proposal; the digest-bound activation is edited in the classic workbook (link shown) |
| Junior/mezzanine/PIK/third tranche/floating rate/DSRA facility/SHL beside instruments | **release-closed**, listed with the canonical reasons | `UNSUPPORTED_STRUCTURES` |
| Sources & uses | derived, read-only, **committed Last Run only** with CURRENT/STALE/NOT RUN | `build_sources_uses_projection` (fail-closed) |
| Investors: holders (id, ownership %, commitment) and actual paid-in contributions | **editable — new typed editor** | `save_agreement` via the canonical F4 route: session CSRF, composite-hash CAS, agreement-version CAS, protected-reference gate |
| Run-bound investor evidence (paid-in, uncalled, residual cash, DPI/MOIC, XIRR) | derived, read-only | `validate_evidence` against owner/project/snapshot/hash/scenario |
| Sponsor funding & shareholder loan (rate, repayment, day count, eligibility start, maturity) | **read-only** — no SHL control is editable under the released authority | `build_sponsor_view` |
| Preferences, carry, return-of-capital ordering, NAV, SHL lender allocation | release-closed | not exposed |

## Safety properties

* **No raw JSON textarea.** The bankability document and the agreement are built from typed fields by ports of the Legacy serializers
  (`serializeBankability.ts`, `serializeAgreement.ts`). Chromium tests assert **byte-identical** output against the Legacy forms.
* **Advisory client checks only** (ranges, plain numbers, DSRF covers requirement, period targets need sculpting); the server stays the sole
  validator — 18 malformed configurations and 8 invalid/conflicting agreements are refused by the canonical routes without persisting anything.
* **CAS and recovery:** the editors compare the studio's identity hash with the save-token hash before posting ("Working Copy changed — nothing was saved");
  a stale CAS is refused by the server and never overwrites a newer draft; a lost response locks the editor with "Result unknown" and reconciles by a
  fresh read — never a blind retry; success is claimed only after a read-back equals what was sent.
* **Scenario scope:** the bankability configuration is project-owned across scenarios (said on screen); the F4 agreement belongs to the active scenario
  and a non-Base scenario needs its own deliberate Save (canonical rule, unchanged).
* **Returns semantics preserved:** the panel labels *Project IRR*, *Pure Equity IRR* and *Total Sponsor IRR* as distinct, and states that undistributed
  shareholder-loan proceeds are not share-capital returns.
* **Excel-like grid:** arrow/Enter navigation between period rows and tab-separated paste (target, rate) fill *drafts*; nothing is saved or run by a paste.

## Acceptance evidence

`tests/test_model_react_rcm_financing_v1.py` (28), `tests/model_react_rcm_financing_acceptance.py` (13 nodes, run inside the mandatory consolidation role), `tests/test_model_react_rcm_investors_v1.py` (17),
`tests/model_react_rcm_investors_acceptance.py` (9 nodes, same role). Highlights: studio view equals `build_view`; a typed configuration saved through the canonical route is
read back exactly and the Last Run goes STALE without a Run; a period rate schedule locks the scalar rate (`WORKING_CONFIG`); investor evidence equals the
Legacy investor workspace for the same agreement and 60/40 ownership splits the same canonical receipts exactly 60/40.

## Not proven here

Two-Senior configuration **parity** (not edited in React); a Legacy-twin comparison of a two-Senior Run (the item is release-closed in React).

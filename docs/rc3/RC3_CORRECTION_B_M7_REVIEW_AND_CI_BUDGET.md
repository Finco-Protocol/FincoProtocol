# RC-3 Correction B - M7 exact-content review packet and CI budget successor (PR #284)

Status: **PREPARER'S PACKET. NO INDEPENDENT REVIEW HAS BEEN PERFORMED. NOTHING HERE IS AN APPROVAL.**
M7 manifest `release_approved:false`; `app/workbook/bess_config.py::ACTIVATION_ENABLED = False`; M6, Junior and Revenue V3 closed.

Base `main` `6fc77de98bc0562fb51efdbf96e1803a29b5b148`. Reviewed M7 source head `62424a8b777133631f4253d75848ba8c846f83e6` (PR #283).
Integration HEAD at preparation: `9ee46e3aaf491ca0cefee0b6cb6e1ff3298949c4` plus this correction.

## 1. Root cause of the seven failures (all one cause)

Every one of the seven guards compares the integrated tree with a *released* financial authority and finds the M7 candidate, which is
in no released pin set:

| # | Failing node | What it compares | Why it fails |
| --- | --- | --- | --- |
| 1-3 | `test_finance_integrity_governance::{test_approved_engine_paths_are_allowed, test_this_branch_stays_within_the_governance_contract, test_stream_guard_exemption_covers_only_allow_listed_engine_files}` | `financial_engine/**` changes vs `APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS` and the released engine authorities | `financial_engine/bess.py` is unlisted; `adapters/project_inputs.py` and `orchestrator.py` are listed paths whose released content differs from M7 |
| 4 | `test_wf07_revenue_governance::test_exact_seven_content_pins_only` | exact blob of the seven WF07 pins | `project_inputs.py` is `14bd759a...`, WF07 pins `fe09548f...` |
| 5-6 | `test_wf07_revenue_governance::test_every_further_edit_invalidates_authorization[project_inputs.py / orchestrator.py]` | one further edit invalidates the released authority | the synthetic repo's released blob no longer matches M7's |
| 7 | `test_ci_acceptance::test_frozen_financial_namespaces_unmodified` | protected diff == `_F3_5_REVIEWED_PROTECTED_PATHS` | the diff contains the nine M7 paths and not the F3.5 set |

These are not defects in M7 code or in the integration; they are the correct behaviour of fail-closed owner guards in the absence of an
independent acceptance. No historical pin map, registry or guard was edited, and none will be until the acceptance record exists.

## 2. The eleven protected blobs (identical in manifest, M7 source head and integrated tree - verified)

| Path | Status vs RC-2 | +/- lines | Git blob SHA-1 |
| --- | --- | --- | --- |
| `domain/bess/__init__.py` | A | +1 | `1905167cfb38bebb69f5f8b24f4100adf2b71f3d` |
| `domain/bess/contracts.py` | A | +242 | `1143dced2b27e3b7ed16754ccd3a17f6982d9f98` |
| `domain/bess/dispatch.py` | A | +186 | `ff2a9d2be76c2b1be308c596c42e32fe4276a9bc` |
| `domain/bess/settlement.py` | A | +79 | `e10829563e359f1766c6d8f98542e43107dac0dd` |
| `domain/bess/synthetic.py` | A | +20 | `427ad4589f9726c07e7c3723c2ff7ceed68c38ae` |
| `finco_core/inputs/bess_native.py` | A | +35 | `57ee798dbe4742c1b36acbfbc1412c90b172d3a2` |
| `financial_engine/bess.py` | A | +76 | `a07873816d97240ae02af106cd31b2135ee63316` |
| `financial_engine/adapters/project_inputs.py` | M | +14 -1 | `14bd759a9958515a7796626f93c1bd2233d69150` |
| `financial_engine/orchestrator.py` | M | +31 -8 | `be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03` |
| `app/run_integrity/evidence.py` | M | +5 | `89faa2c9c3d4dfddb7b8a8096888f3aa7cf83610` |
| `app/run_integrity/checks.py` | M | +14 -3 | `25e4c3aeb25893694681b4f819c663d1e24ac3a1` |

Diff vs RC-2 is purely additive for seven files; the four modified files are summarised in section 3. No other `financial_engine/`,
`finco_core/` or `domain/` path changes (asserted by `tests/m7_rc3_candidate_successor.py` and the RC-3 inventory).

## 3. What the code does to calculation paths (from the exact source, not the manifest)

* **Gate in `run_operating_model` (`orchestrator.py`).** Everything is guarded by `bess_native_config_json` being present; with it empty
  (Solar, Wind, Data Center, EV) the previous code path is taken unchanged. A legacy `bess_enabled` input (no native contract) is
  rejected first with `BESS_NATIVE_CONTRACT_REQUIRED`.
* **Native path.** Production is set to zero, revenue is the gross merchant sale revenue of the hourly dispatch, and OPEX is *added* to the existing
  fixed OPEX: charging purchases, auxiliary purchases, import and export charges and DC-throughput variable O&M. No second EBITDA, tax, CFADS,
  debt or return calculator exists; those stay downstream and canonical.
* **Dispatch / settlement (`domain/bess/*`).** One hourly DC inventory equation in `Decimal` (prec 40); period aggregation requires the full
  canonical operating axis with contiguous intervals and no straddling hours, and reconciles import, export, gross sale revenue and lifecycle CAPEX
  to the hourly totals.
* **Bank case.** `derive_debt_sizing_operating_input` rejects non-P50 yields and market-price curves for native BESS (`BESS_BANK_CASE_UNSUPPORTED`).
* **Run Integrity.** `evidence.py`/`checks.py` add `BESS_NATIVE_ADDITIONAL_EQUITY_V1` (balance-sheet equity includes actual additional equity) and
  recompute sponsor XIRR with the existing robust G2B authority; missing authority is `UNAVAILABLE`, not PASS. Check IDs and tolerances unchanged.
* **Not supported (fail closed):** augmentation / post-COD accounting events (`BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED`), non-zero stored-energy
  financial basis (`BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED`), hybrid with renewable yield, duplicate revenue authority.

## 4. Evidence available (all from local runs of the unchanged candidate; Python 3.12)

| Question | Evidence | Result |
| --- | --- | --- |
| Physical energy conservation, merchant settlement, dispatch | `tests/test_m7_bess_physics.py`, `test_m7_bess_boundaries.py` | included in 283 passed (M7 + EV + parity group) |
| Revenue/OPEX classification, signed EBITDA, CFADS, tax, debt, DSCR, returns | `tests/test_m7_bess_canonical_finance.py`, `test_m7_bess_financial_boundary.py` | passed |
| Solar/Wind/DC/EV outputs unchanged | `test_perf_model_runtime_v2` (bit-identical to authoritative kernel), `test_ev_charging_reference`, `test_ev_charging_range_parity`, `test_model_v2_revenue_runtime_parity` | passed; 356 passed in the functional group |
| Legacy Storage compatibility | `test_ev_charging_reference::test_ev_charging_equipment_depreciates_over_10_years`, `test_m7_bess_successor_proposal::test_legacy_storage_*` | passed |
| Run Integrity evidence | `test_m7_bess_workflow`, `test_m7_bess_candidate_workspace` | passed |
| CSRF, ownership, CAS, committed Run | `test_m7_bess_workflow`, Trust controls/registry (M7 routes only via the exact-content proposal) | passed |
| Exact-blob mutations | `tests/test_m7_bess_successor_proposal.py` (77), `tests/test_m7_rc3_candidate_successor.py` (19, every blob changed/omitted/substituted/partial/extra) | passed |
| No unauthorized activation | `ACTIVATION_ENABLED` literal `False` asserted by inventory and successor tests | passed |

Numbers are from the commands recorded in the PR #284 description. **Nothing in this table is an independent review.**

## 5. Residual risks and open financial-policy questions for the reviewer

1. Aggregation reconciles import/export energy, gross sale revenue and lifecycle CAPEX to the hourly totals, but auxiliary purchases, import/export
   charges and net contribution are carried through the period sums without a separate reconciliation line; the reviewer should confirm that is sufficient.
2. Variable O&M is computed in `financial_engine/bess.py` (`throughput x EUR/DC-MWh / 1000`); units and sign should be confirmed against the
   OPEX authority, since it is added to OPEX outside `finco_core/opex`.
3. Charging purchases are classified as OPEX, not cost of sales or inventory; accounting presentation is a policy decision, not a calculation fact.
4. Nonzero stored-energy basis and augmentation are rejected, so BESS projects with those features cannot run; this is a scope limit, not a defect.
5. The legacy-Storage rejection now lives at the operating-model boundary (Correction B on #283) rather than in the adapter; any other direct caller
   of the engine that bypasses `run_operating_model` is not covered by that marker.
6. Native BESS stays blocked at production admission (`BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED`) regardless of this review.

## 6. The approval gate (what is required, nothing is invented)

`tests/m7_rc3_candidate_successor.py` defines `M7_RC3_CANDIDATE_AUTHORITIES` (the eleven blobs above, independent of the manifest) and a fail-closed
validator. It is **inert**: no guard imports it (asserted by a test) and no historical pin map is touched. It reports `APPROVAL_REQUIRED` until a
separate record `docs/rc3/M7_FINANCIAL_ACCEPTANCE.json` exists with: a named independent human reviewer, `reviewed_source_head` =
`62424a8b777133631f4253d75848ba8c846f83e6`, the exact eleven blobs, `scope: CANDIDATE_CONTENT_ONLY`, `activation_approved: false`,
`derived_from_manifest: false` and a decision reference. The reviewer, not this PR, then decides how the owner guards (Finance Integrity, WF07, CI
acceptance) are extended; each must accept the exact eleven blobs individually and must not become a namespace allow-list. Candidate acceptance and
production activation remain separate decisions.

## 7. CI budget successor (owner-authorised; budget only, not financial approval)

`.github/workflows/ci_public_job.yml` differs from the accepted RC-2 workflow (blob `4c6b9136...` -> RC-2 successor on main) in exactly two values:
`FINCO_CI_PYTEST_BUDGET_S` `4200` -> `4800` and `timeout-minutes` `90` -> `100`. Exit grace (180), stall (300), full unsharded execution, selection,
artifacts and mandatory evidence are unchanged. New blob `036a5aef7cf9738b8bf7bf2f6294f24a998a928c`. Fit: `4800 + 180 + 900 = 5880 s <= 6000 s`
(120 s slack), also asserted by the existing `test_ci_pytest_progress` guard. The historical RC-1/RC-2 verification stays anchored to the original
commit; `tests/test_rc3_integration_inventory.py` recognises only this exact successor (pure verifier + 17 rejecting mutations: reduced or raised
timeout/budget, grace/stall, selection, deselect, failure handling, evidence removal, artifact softening, extra step, trailing byte, permissions, runner;
and every other workflow file stays byte-identical to the base).

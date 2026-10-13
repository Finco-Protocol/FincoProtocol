# RC-2 integration manifest (Revenue V3 + 2-driver Sensitivity + Developer Economics + Radar R3)

Status: **DRAFT — exact-content proposal awaiting independent (ChatGPT) review. Nothing here is an approval.**
Verified main: `5058c6b4935168241d6923676cb32955cb903185` (merge of RC-1 #273).

## 1. Source-HEAD ancestry (normal `--no-ff` merges, in this order)

| Order | PR | Feature | Exact source HEAD | Merge parents (first, second) |
|---|---|---|---|---|
| 1 | #275 | M2 Revenue V3 (release-closed candidate) | `73f698705ec5d72af820974873d9be202cd57f7d` | `5058c6b…`, `73f6987…` |
| 2 | #274 | M3 Two-driver Sensitivity (corrected HEAD) | `0fa0ac5e268a37decbae6bc252487aba3e6e31c9` | previous merge, `0fa0ac5…` |
| 3 | #277 | M4 Developer Economics persistence | `1599aa5eb4e82463157fbae430fa227ac71bdead` | previous merge, `1599aa5…` |
| 4 | #276 | Radar R3 Deepstate (read-only) | `6c704f4e799a9dc1a10eb4f10d4e6b9a14f0ea2f` | previous merge, `6c704f4…` |

All four merged with **no textual conflicts**. `tests/test_rc2_integration_manifest.py` re-verifies the chain on every run.

## 2. Corrections made on the integration branch (not in separate PRs)

* **M4** — committed Developer evidence is now validated structurally before rendering (exact keys, `fee_basis`, cashflow rows and dates, finite
  values, status vocabulary, value/status consistency, snapshot + composite + scenario binding); any mismatch is `UNAVAILABLE`, never an
  exception and never a figure.
* **R3** — `_rlive_binding` iterated the string-keyed `APPROVED_BY_CANONICAL_ID` and read `.chain_id` on strings (34 of 38 R3 tests failed on the
  source PR head itself); it now uses the `AssetKey`-keyed `APPROVED_RLIVE_ASSETS`. The 30-day Deepstate read escalates over 1 d / 7 d / 30 d
  and stops once 120 qualifying fills are found (public store API only; no change under `finco_radar/`).
* New tests: `tests/test_rc2_integration_acceptance.py` (combined scenarios) and `tests/test_rc2_integration_manifest.py` (exact manifest).

## 3. Protected financial candidate manifest (Revenue V3, `ACTIVATION_ENABLED = False`)

| Path | Blob (this HEAD) |
|---|---|
| `domain/revenue/advanced_products.py` | `d4ab263422aac5571e52bee4925fe36588e853cc` |
| `domain/revenue/multistream_runtime.py` | `83beda4eb296b02baf2ebd6659fec243ab196206` |
| `finco_core/revenue/generation.py` | `35670dc7b5ab4ce01177f9df817a4776c10569ab` |

No change to `plan.py`, `plan_engine.py`, debt/tax/IRR formulas, goldens or tolerances. Production activation stays closed
(asserted by the manifest and by `test_revenue_v3_is_release_closed_without_the_test_activation`).

## 4. Router delta (`app/v2/router.py`)

* Modified functions (exact sha256 pinned): `_build_revenue_contract_editor` (M2), `v2_workbook_run` (M4 selected-scenario developer input + evidence binding).
* Added/removed functions: none. New module-level statements: exactly the four M3 hook statements (router import, `include_router`, `register_template_globals`).
* Protected Revenue V2 handlers, the Capital Stack CSRF gate and the F4 handlers are byte-identical to main (enforced by the RC-1 post-merge successor).

## 5. CSRF call-site inventory

Main plus `app/v2/developer_decision_router.py` (M4 Developer Economics configuration Save: signed CSRF, owner, project isolation,
Protected Reference denial, scenario + composite CAS). **M3's `POST /v2/workbook/sensitivity/matrix/run` validates no CSRF token** (read-only,
same as the existing one-driver sensitivity and goal-seek routes) — see open question 2.

## 6. Trust governance — what is proposed and what is blocked

* Proposed (needs reviewer authorisation): the M4 additions in `tests/test_trust_readiness_registry.py` (`RC1_SUCCESSOR_BLOBS`, `M4_CALL_SITES`,
  post-merge checkpoint successor with mutation tests), the one registry sentence naming the Developer Economics Save, the controls-test CSRF
  inventory and the regenerated `docs/readiness/03_*`. These were authored by the M4 implementation agent and are **candidate changes, not approval**.
  Historical RC-1/WF05/Revenue V2/F4/F3.5-B pins are unchanged.
* `tests/test_rc2_integration_manifest.py` adds the exact RC-2 manifest with negative mutation tests (replaced head, wrong parent, any blob, any
  unreviewed path or deletion, extra router function/statement, CSRF inventory change, activation flags). No wildcard, no descendant rule.
* **Blocked checks that stay red until authorised** (identical on the pristine #275 head, i.e. not integration-caused):
  `tests/test_wf07_revenue_governance.py` (5 tests: seven-pin set, further-edit invalidation for `multistream_runtime.py` and `generation.py`,
  advanced-revenue successor blob, extra byte / unlisted domain path) and `tests/test_finance_integrity_governance.py::test_this_branch_stays_within_the_governance_contract`;
  plus `tests/test_radar_r3_deepstate_composition.py::test_no_frozen_namespace_delta_on_branch`, which fails only because the M2 financial candidate
  (`finco_core/revenue/generation.py`) is a frozen-namespace delta. Authorising the three blobs of section 3 is the single reviewer decision that clears them.

### Open questions for the reviewer
1. Authorise exactly the section 3 blobs as the Revenue V3 release-closed financial successor?
2. Is "no CSRF on read-only analysis POSTs" acceptable for M3 (and the two existing routes), or should a repo-wide decision add CSRF?
3. Accept the M4 Trust successor entries listed above as the RC-2 governance successor?

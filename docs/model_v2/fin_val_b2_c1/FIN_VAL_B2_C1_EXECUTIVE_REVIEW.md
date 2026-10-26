# FIN-VAL B2/C1 — executive review (PR #383, Correction A status)

**Verdict: BLOCKED — EXACT-PATH FINANCIAL OWNER AUTHORIZATION REQUIRED, and BLOCKED — MATERIAL ATOMICITY FINDING for any claim that the capacity Save is fully atomic.** Not ready for independent final review. No merge, deploy or activation.

## What is delivered and verified
| Item | State |
|---|---|
| WF-1A SC-3 Working Copy recovery (legacy + React) | implemented; 13 dedicated tests; live Chromium check desktop/mobile; **a regression found in Correction A (it pre-empted the typed RC-7B 3/3 refusal) is fixed** |
| WF-1B R-1 finiteness | non-finite derived amounts can no longer be persisted by the capacity Save; refusal leaves every persisted byte unchanged; **the full Save is not atomic** (three commits; failure-injection evidence in the R-1 report) |
| WF-1C CAPEX duplicate `Unused` | fixed by deterministic placeholder names; amounts, depreciation and Run economics unchanged |
| WF-2 OPEX authority | audited for 11 fields × 4 technologies; bounds aligned (`min 0`), shadowed groups read-only; no mapping change; methodology items in the Financial Owner register |
| Economics | Solar/Wind default, tariff-60 and capacity-30 Runs bit-identical to main (all financial fields) |

## Blockers (all reproduced)
1. **CI V3 `plan` fails**: the B1 test node was renamed (`original nodes removed`). Fix needs a protected test path → authorization requested.
2. **SEC-02 successor pins**: six reviewed blobs changed → two successor tests red until an exact-path additive successor is authorised.
3. **Atomicity**: S1 (exception after the capacity CAS) leaves capacity new / lines and totals old; S2 (exception in the final snapshot save) leaves stale totals and seed capacity; S3 (competing committed write between phases) is silently lost. S2/S3 are identical on main (pre-existing); a single-transaction design is proposed, not implemented.

## What changed in Correction A (unprotected only)
`app/workbook/draft_recovery.py` stand-down for `QUARTERLY_*` typed refusals; two additive tests; reports updated (R-1 atomicity scope corrected, CI/acceptance, authorization request). The protected-path edit made in the previous push is disclosed and awaiting ratification.

## Next, once authorized
Apply items 1–3 of the request, fill the six final blobs after the freeze, (optionally) the single-transaction capacity Save with S1–S3 as permanent tests, push, then await fresh exact-head CI for all workflow families.


## Correction B status (single-transaction capacity Save)
* **Implemented and verified locally (unprotected files):** the capacity Save is one `BEGIN EXCLUSIVE` transaction (`v2_atomic_draft_update` + `in_transaction_finalizer`); S1/S2/S4, genuine two-connection races, bit-identity against the legacy oracle, user overrides and guard tests pass (37 tests); Solar/Wind/Data Center/EV committed Runs (default and 30 MW) are bit-identical to main; wider regression 439 passed; the React bundle rebuilds byte-identically twice. A fourth pre-existing defect (capacity Save nulling `active_scenario_id/name`) is fixed by construction. See the R-1 report, section "CORRECTION B".
* **Still blocked — exact-path owner authorization:** (1) `tests/test_fin_val_b1_capex_save_integrity.py` node restore (`PROPOSED_B1_NODE_RESTORE.patch`; trial in a scratch tree: patch applies, two collection passes identical, 20,486 nodes, 0 original nodes missing) plus ratification of the three earlier assertion changes; (2) additive SEC-02 successor (`PROPOSED_SEC02_SUCCESSOR.patch`; trial in a scratch tree: the two red successor tests pass, 4 new negative tests pass, all 112 original pins untouched, the six blobs equal the current application blobs). Neither is applied to this branch.
* **Disposition:** `BLOCKED — OWNER_AUTHORIZATION_REQUIRED`. Public Safety `plan` stays red until item (1) is applied. Fresh exact-head CI after Correction B has not been run.

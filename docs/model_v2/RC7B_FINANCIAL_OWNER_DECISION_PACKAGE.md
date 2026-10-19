# RC-7B Financial Owner decision package (D-01..D-12)

Nothing here is an approval. The "Recommended" columns are the implementer's recommendation; every cell under "Owner decision" is intentionally
blank. Conventions, consequences and refusal rules are those of `RC7B_QUARTERLY_DECISION_MATRIX.md` (do not duplicate; this adds the
release-gating, evidence and successor-scope fields). Quarterly admission stays closed (`ACTIVATION_ENABLED = False`) whatever is decided
here; admitting product Runs is a separate change. Existing 6/6 behaviour is unchanged and verified bit-identical.

Two gates are distinguished because they need different decisions:

- **Gate R - release-closed integration:** merging the candidate code with admission closed. Candidate conventions are carried as the named
  version `rc7b-quarterly-candidate-v1`, no product Run can execute them, and out-of-scope combinations are refused.
- **Gate P - product activation:** letting users Run 3/3. Requires the convention to be accepted as the economic rule.

| ID | Candidate convention (summary) | 6/6 convention | Evidence (existing, reproducible) | Supported / refused | Recommended: required for Gate R? | Gate P? | Exact successor scope if approved | Owner decision |
|---|---|---|---|---|---|---|---|---|
| D-01 COD stub | keep actual COD, half-open quarters; no roll window | rolls to Jun/Dec when COD < 7 days before | axis oracle `tests/rc7b_quarterly_oracle.py`, `test_rc7b_quarterly_axis_production.py` | supported outside the 6/6 roll window; roll window refused (`QUARTERLY_COD_ROLL_WINDOW_PENDING_D01`) | acknowledge as candidate | accept or replace | `finco_core/engine/calendar_policy.py`, `period_engine.py` | ____ |
| D-02 Day counts | operating fraction days/end-year; debt interest keeps ACT/360 or ACT/365 | end-year (generic) or next-year (source-aligned) | oracle; funding/statements suite | source-aligned refused | acknowledge | accept or replace | same two files + `financial_engine/adapters/tax_inputs.py` | ____ |
| D-03 Horizon | 4N rows including stub (v1; **superseded by the RC-7C date-authoritative v2**, see `RC7C_QUARTERLY_FINANCIAL_ACCEPTANCE.md`) | 2N rows | axis oracle | anniversary horizon not implemented | acknowledge | accept or replace | `period_engine.py`, `financial_engine/inputs.py` | ____ |
| D-04 Annual clock | four rows advance the model year | two rows | axis + funding oracles | hierarchical OPEX / external annual series refused | acknowledge | accept or replace | `inputs.py`, `orchestrator.py`, `quarterly_scope.py` | ____ |
| D-05 PPA dates | legacy formula only; expiry on a quarter boundary | legacy + PPA-01 + multistream | quarterly scope tests | multistream, dated indexation, per-period vectors refused | confirm refusal | confirm or fund a revenue-owned integration | `quarterly_scope.py` (refusals only) | ____ |
| D-06 3/6 | none | n/a | refusal tests | refused (`QUARTERLY_MATCHED_3_3_REQUIRED`) | none (deferred) | separate decision | none | DEFERRED |
| D-07 6/3 | none | n/a | refusal tests | refused | none (deferred) | separate decision | none | DEFERRED |
| D-08 Covenants / distributions | released mechanics on quarterly dates | half-year dates | funding/returns oracle; Sponsor returns labelled `PENDING_D08` | computed in the candidate; labelled pending | confirm labelling is acceptable | **must be decided** (Sponsor returns rely on it) | `financial_engine/financing/project.py`, `generic_product_policy.py` | ____ |
| D-09 Reserves | `NONE` only; any DSRA/DSRF refused | forward-target DSRA | refusal tests | refused (`QUARTERLY_RESERVE_POLICY_PENDING_D09`) | confirm refusal | **must be decided** before any reserve | `quarterly_scope.py`, `generic_product_policy.py` | ____ |
| D-10 Maturity | tenor x 4 rows, no balloon | tenor x 2 rows | Senior sizing/sculpting oracles | off-grid contractual date needs its own axis | acknowledge | accept or replace | `senior_debt/project_adapter.py` | ____ |
| D-11 Tax | annual ledger, `periods_per_tax_year = 4`, zero lag | `periods_per_tax_year = 2` | tax oracle (annual 12.6 paid once, not 3.15/quarter) | ATAD / thin-cap / interest limitation refused | acknowledge | accept or replace | `adapters/tax_inputs.py` | ____ |
| D-12 Scope | Solar and Wind, one Senior, equity-only | four verticals, SHL, DSRA, gated facilities | 6/6 four-vertical regression bit-identical | everything else refused before any calculation | **required** (it defines what the refusals protect) | required | `quarterly_scope.py`, `financial_engine/financing/project.py` | ____ |

## Approval record (to be completed by the Financial Owner; nothing is pre-filled)

| Field | Value |
|---|---|
| Owner name and role | |
| Decisions accepted / replaced / deferred (D-01..D-12) | |
| Replacement conventions, if any (then the candidate must be re-implemented and re-reviewed) | |
| Independent reviewer of the twelve blobs | |
| Exact blob identities accepted | listed in `RC7B_QUARTERLY_PRODUCTION_SUCCESSOR_CONTRACT.md` |
| Governance owner authorizing the bounded integration successor | |
| Date and signature | |

PR #320 has since been merged as a release-closed candidate (`bf0167a0`; recognition of bytes only, see `RC7B_POSTMERGE_GOVERNANCE_RECOVERY.md`). That merge
is not the Financial Owner decision recorded here: every decision above stays **OPEN**, quarterly activation stays closed, and the RC-7C update of D-01..D-05,
D-10 and the new D-03-b is in `RC7C_QUARTERLY_FINANCIAL_ACCEPTANCE.md`.

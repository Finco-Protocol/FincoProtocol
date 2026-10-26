# OPEX field-to-engine authority matrix (WF-2)

Base: main `8944aca351ef89c81a8a9bf715ab352629c35624`. All values were measured through the real canonical routes (Save via `/v2/workbook/update`, Run via `/v2/workbook/run`) on disposable databases, one field at a time, on a fresh reference-seeded Working Copy per technology (16 MW). `Δ pre-fold` is the change of total OPEX in the adapter-built `ProjectInputs` *before* the Run-boundary fold; `Δ Run` is the change of the committed Run's `total_opex_keur` over the project life for the same edit.

## Reading the matrix

* **Source key** is the snapshot key written by the registry field; **adapter mapping** is `build_effective_draft_opex` (`app/v2/opex_assembly.py`): replace the base item's Y1 amount, or append a canonical-named item at the default inflation if the base has none.
* **Run precedence**: at the Run boundary `fold_opex_with_provenance` (`app/services/opex_sub_lines_integration.py`) drops every base item whose canonical name is in the seeded `replaced_canonical_keys` and substitutes the seeded OPEX sub-lines. A scalar for such a group therefore reaches `ProjectInputs` but is removed again before the engine (class B).
* **Data Center / EV Charging B.08 (power expenses)** is derived from the persisted technology drivers; the scalar has no effect (class B).
* Engine: `finco_core/opex/projections.py` clamps each item amount with `max(0.0, …)`, so a negative scalar is silently ignored (class E, now refused at Save).

Classes: **A** correctly active · **B** correctly inactive/overridden (authority is elsewhere) · **C** incorrectly unmapped · **D** methodology ambiguity · **E** invalid value accepted.

## Solar PV (baseline total OPEX 3,027.522 kEUR)

| Field ID | Source key | B-code | Scenario precedence | Δ pre-fold (edit 25) | Δ Run (edit 25) | Δ Run total OPEX (edit 60) | Observed | Class |
|---|---|---|---|---:|---:|---:|---|---|
| `opex.lines.technical_management` | `opex_technical_management_y1_keur` | B.01 | Working Copy draft; scenario overrides are not defined for this field | 160.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.om_preventive` | `opex_o_and_m_preventive_and_corrective_y1_keur` | B.02 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |
| `opex.lines.site_maintenance` | `opex_maintain_site_y1_keur` | B.03 | Working Copy draft; scenario overrides are not defined for this field | 230.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.cleaning_materials` | `opex_clean_material_y1_keur` | B.04 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |
| `opex.lines.security` | `opex_security_y1_keur` | B.05 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |
| `opex.lines.insurance` | `opex_insurance_y1_keur` | B.06 | Working Copy draft; scenario overrides are not defined for this field | 210.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.lease_property_tax` | `opex_lease_and_property_tax_y1_keur` | B.07 | Working Copy draft; scenario overrides are not defined for this field | 260.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.power_expenses` | `opex_power_expenses_y1_keur` | B.08 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |
| `opex.lines.audit_accounting_legal` | `opex_audit_and_accounting_and_legal_y1_keur` | B.10 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |
| `opex.lines.bank_fees` | `opex_bank_fees_opex_y1_keur` | B.11 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |
| `opex.lines.environmental_social` | `opex_environmental_and_social_management_y1_keur` | B.12 | Working Copy draft; scenario overrides are not defined for this field | 310.0 | 25.0 | 1,912.119 | Reaches the Run | A |

## Wind (baseline total OPEX 6,448.606 kEUR)

| Field ID | Source key | B-code | Scenario precedence | Δ pre-fold (edit 25) | Δ Run (edit 25) | Δ Run total OPEX (edit 60) | Observed | Class |
|---|---|---|---|---:|---:|---:|---|---|
| `opex.lines.technical_management` | `opex_technical_management_y1_keur` | B.01 | Working Copy draft; scenario overrides are not defined for this field | 191.7 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.om_preventive` | `opex_o_and_m_preventive_and_corrective_y1_keur` | B.02 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |
| `opex.lines.site_maintenance` | `opex_maintain_site_y1_keur` | B.03 | Working Copy draft; scenario overrides are not defined for this field | 271.7 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.cleaning_materials` | `opex_clean_material_y1_keur` | B.04 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |
| `opex.lines.security` | `opex_security_y1_keur` | B.05 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |
| `opex.lines.insurance` | `opex_insurance_y1_keur` | B.06 | Working Copy draft; scenario overrides are not defined for this field | 241.7 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.lease_property_tax` | `opex_lease_and_property_tax_y1_keur` | B.07 | Working Copy draft; scenario overrides are not defined for this field | 311.7 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.power_expenses` | `opex_power_expenses_y1_keur` | B.08 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |
| `opex.lines.audit_accounting_legal` | `opex_audit_and_accounting_and_legal_y1_keur` | B.10 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |
| `opex.lines.bank_fees` | `opex_bank_fees_opex_y1_keur` | B.11 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |
| `opex.lines.environmental_social` | `opex_environmental_and_social_management_y1_keur` | B.12 | Working Copy draft; scenario overrides are not defined for this field | 391.7 | 25.0 | 2,110.453 | Reaches the Run | A |

## Data Center (baseline total OPEX 446,186.696 kEUR)

| Field ID | Source key | B-code | Scenario precedence | Δ pre-fold (edit 25) | Δ Run (edit 25) | Δ Run total OPEX (edit 60) | Observed | Class |
|---|---|---|---|---:|---:|---:|---|---|
| `opex.lines.technical_management` | `opex_technical_management_y1_keur` | B.01 | Working Copy draft; scenario overrides are not defined for this field | 1,010.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.om_preventive` | `opex_o_and_m_preventive_and_corrective_y1_keur` | B.02 | Working Copy draft; scenario overrides are not defined for this field | 1,760.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.site_maintenance` | `opex_maintain_site_y1_keur` | B.03 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |
| `opex.lines.cleaning_materials` | `opex_clean_material_y1_keur` | B.04 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |
| `opex.lines.security` | `opex_security_y1_keur` | B.05 | Working Copy draft; scenario overrides are not defined for this field | 610.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.insurance` | `opex_insurance_y1_keur` | B.06 | Working Copy draft; scenario overrides are not defined for this field | 510.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.lease_property_tax` | `opex_lease_and_property_tax_y1_keur` | B.07 | Working Copy draft; scenario overrides are not defined for this field | 610.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.power_expenses` | `opex_power_expenses_y1_keur` | B.08 | Working Copy draft; scenario overrides are not defined for this field | 0.0 | 0.0 | 0.000 | No effect: derived from technology drivers | B |
| `opex.lines.audit_accounting_legal` | `opex_audit_and_accounting_and_legal_y1_keur` | B.10 | Working Copy draft; scenario overrides are not defined for this field | 410.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.bank_fees` | `opex_bank_fees_opex_y1_keur` | B.11 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |
| `opex.lines.environmental_social` | `opex_environmental_and_social_management_y1_keur` | B.12 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |

## EV Charging (baseline total OPEX 171,431.456 kEUR)

| Field ID | Source key | B-code | Scenario precedence | Δ pre-fold (edit 25) | Δ Run (edit 25) | Δ Run total OPEX (edit 60) | Observed | Class |
|---|---|---|---|---:|---:|---:|---|---|
| `opex.lines.technical_management` | `opex_technical_management_y1_keur` | B.01 | Working Copy draft; scenario overrides are not defined for this field | 330.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.om_preventive` | `opex_o_and_m_preventive_and_corrective_y1_keur` | B.02 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |
| `opex.lines.site_maintenance` | `opex_maintain_site_y1_keur` | B.03 | Working Copy draft; scenario overrides are not defined for this field | 490.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.cleaning_materials` | `opex_clean_material_y1_keur` | B.04 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |
| `opex.lines.security` | `opex_security_y1_keur` | B.05 | Working Copy draft; scenario overrides are not defined for this field | 106.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.insurance` | `opex_insurance_y1_keur` | B.06 | Working Copy draft; scenario overrides are not defined for this field | 138.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.lease_property_tax` | `opex_lease_and_property_tax_y1_keur` | B.07 | Working Copy draft; scenario overrides are not defined for this field | 298.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.power_expenses` | `opex_power_expenses_y1_keur` | B.08 | Working Copy draft; scenario overrides are not defined for this field | 0.0 | 0.0 | 0.000 | No effect: derived from technology drivers | B |
| `opex.lines.audit_accounting_legal` | `opex_audit_and_accounting_and_legal_y1_keur` | B.10 | Working Copy draft; scenario overrides are not defined for this field | 106.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.bank_fees` | `opex_bank_fees_opex_y1_keur` | B.11 | Working Copy draft; scenario overrides are not defined for this field | 138.0 | 0.0 | 0.000 | Applied by adapter, removed by Run fold (sub-lines authoritative) | B |
| `opex.lines.environmental_social` | `opex_environmental_and_social_management_y1_keur` | B.12 | Working Copy draft; scenario overrides are not defined for this field | 25.0 | 25.0 | 1,457.842 | Reaches the Run | A |

## Edge-value behaviour (Solar, `opex.lines.om_preventive` active group; `technical_management` shadowed group)

| Case | Save | Committed Run | Total OPEX kEUR | Project IRR |
|---|---|---|---:|---:|
| `om_preventive=-100` | 200 | yes | 3,027.522 | 0.117680 |
| `om_preventive=0` | 200 | yes | 3,027.522 | 0.117680 |
| `om_preventive=60` | 200 | yes | 4,939.642 | 0.111421 |
| `om_preventive=1e99` | 200 | no (fail-closed) | — | — |
| `technical_management(shadowed)=-100` | 200 | yes | 3,027.522 | 0.117680 |
| `technical_management(shadowed)=60` | 200 | yes | 3,027.522 | 0.117680 |

Baseline total OPEX 3,027.523 kEUR, Project IRR 0.117680. A stored `-100` or `0` is *identical to the baseline*: before this PR the negative value was accepted, stored and silently ignored by the engine (`max(0.0,…)`). `1e99` is accepted by Save and is stopped fail-closed by the Run integrity checks (no committed result).

## Conclusions

* **A (correctly active):** every scalar that reaches the Run is mapped consistently from field to engine item; no field is unmapped (**class C: none found**).
* **B (correctly inactive):** the shadowed groups (Solar/Wind B.01, B.03, B.06, B.07; Data Center and EV Charging several groups; DC/EV B.08) accept a Save that cannot change the Run. This is **existing, documented precedence** — OPEX sub-lines replace the base group — and is *not changed*. What was wrong was the Inputs grid offering an editable cell that does nothing. **Implemented (presentation only):** those groups are shown read-only with the existing authority text; Run, adapter and fold are untouched.
* **E (invalid accepted):** the 11 editable `opex.lines.*` amounts accepted negative values that the engine silently clamps. **Implemented:** `min_value=0` on exactly those 11 registry fields, matching the engine and the CAPEX contract from B1. No maximum is introduced.
* **D (methodology ambiguity):** (1) whether a scalar for a replaced group should *win over*, *add to*, or *stay ignored by* the seeded sub-lines; (2) the *append-at-default-inflation* branch of `build_effective_draft_opex` for groups with no base item; (3) the API still accepts a Save of a shadowed field. None is implemented — see `FINANCIAL_OWNER_DECISION_REGISTER.md`.
* The matrix evidence is reproducible with the scripts listed in `EXACT_HEAD_CI_AND_ACCEPTANCE.md`; the regression module asserts the read-only presentation, the registry bounds and the run-precedence delta (`TestOpexAuthority`).

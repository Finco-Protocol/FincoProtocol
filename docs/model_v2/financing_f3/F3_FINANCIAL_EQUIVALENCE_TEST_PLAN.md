# Financing F3 — Financial Equivalence Test Plan

## A. Evidence delivered in this PR (foundation)

| Test file | Proves |
|---|---|
| `tests/test_financing_f3_contract_candidate.py` | candidate validation: duplicate IDs, negative/non-finite commitments, invalid dates, missing terms, invalid type combinations, percent-style rates, derived-amount rules, preferred equity deferral, ownership ≤ 100%, deterministic serialization/identity independent of insertion order |
| `tests/test_financing_f3_reference_compatibility.py` | read-only legacy mapping on Solar / Wind / Data Center / EV: `ProjectInputs` dict and `hash_inputs_for_cache` unchanged, exactly one Senior marked `CANONICAL_SIZING_DERIVED` (never zero), deterministic mapping, explicit equity equals legacy fields; **no production import of the candidate** (AST scan of `app`, `financial_engine`, `finco_core`, `domain`, `main_web.py`); candidate imports no engine/persistence/web module; no route exposes it; `ProjectInputs` gained no instrument/tranche/facility field |
| existing regression suites (run, unchanged) | `test_h1_generic_financing_policy`, `test_h3_sponsor_return_semantics`, `test_model_financing_bankability`, `test_finance_integrity_governance`, `test_data_center_reference`, `test_ev_charging_reference`, `test_developer_economics_v1` |
| frozen-namespace review | `git diff origin/main -- financial_engine finco_core domain` is empty |

## B. Evidence required before ANY activation (future)

1. **Bit-exact legacy equivalence.** For each reference (Solar, Wind, Data Center, EV) and each active scenario: run the
   existing path and the instrument path with the mapped legacy collection; compare, with tolerance 0 (bit-exact) on
   floats that are deterministic and ≤ 1e-9 only where a documented solver tolerance applies:
   total project uses, Senior commitment, IDC, fees, construction funding schedule (every period), Senior
   opening/interest/principal/closing, DSCR/LLCR vectors, SHL schedule, tax lines, financial statements (incl. balance
   check), waterfall distributions, Project/Pure Equity/Total Sponsor IRR & MOIC, certificates and exports.
2. **Independent recomputation** for synthetic two-facility cases (spreadsheet-style recomputation in the test, not the
   engine's own numbers), including IDC and commitment fee per facility and aggregate vs per-facility DSCR.
3. **Funding identities:** per period Σ sources = uses; underfund/overfund fail closed with typed codes; layer order
   reproduced exactly for legacy; residual audit ≤ tolerance.
4. **Opt-in semantics:** absent collection ⇒ byte-identical `project_inputs_to_dict`, hashes, Run History entries and
   exports; enabling then disabling restores byte-identical payloads; no silent migration; historical Runs untouched.
5. **Persistence:** CAS conflict, owner/protected-reference rejection, scenario isolation, STALE after save, canonical
   Run, export parity, no hidden defaults.
6. **Parity:** statements balance, tax interest map equals Σ facility interest, sponsor ledger reconciles by provider
   and by class.
7. **Browser:** Add Debt / Add Equity journeys in real Chromium; documentary fields disabled; no fake controls.
8. **Cross-vertical:** the four references in legacy-mapped and ≥ 1 multi-facility configuration.

## C. CI gates

Five exact-head workflows (Governance Full History, Dependency Security Audit, Protocol UI Browser Acceptance, PR
Compile and Safety Gate, Public Safety and Model Smoke) plus the equivalence suite and the frozen-namespace diff
review on every F3.x PR. No test weakening; any drift is a stop condition.

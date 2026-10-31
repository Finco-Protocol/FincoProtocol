# FIN-TRUTH-B1 — Legacy sensitivity input provenance and export

Base: main `ebf1f15113ec95d69d29e8aa4e4635686dd1f39a` (merged #405).

A user-created Solar 16 MW code previously selected the Wind 48 MW factory. The CSV/XLSX route also referenced undefined `project_record`/`workspace_state`. Both HTTP surfaces now resolve the exact authorized Working Copy draft and selected scenario before admitting work. They disclose `WORKING_COPY_DRAFT`, never Last Run. Unknown/foreign/archived/protected or stale scenario links fail closed. The previously unadmitted Legacy EV surface retains its no-result refusal (HTML error state, typed export refusal); source repair does not expand that admission. Explicit factory aliases remain a closed, disclosed compatibility path; they never provision project or workspace rows.

Materialisation delegates to existing Run authorities for draft inputs, scenario tariff/contracts, persisted CAPEX/OPEX lines, fee/F3 financing and spending profiles. Non-current scenario links, Q4 and unsupported overrides are refused rather than approximated. The final read-context token is validated after calculation/render/export, so a concurrent Save, archive or scenario change discards the response. Neither GET saves or commits a Run. Existing session precedence and bounded executor admission are preserved.

| Driver | Omitted levels | Explicit levels | Unit |
|---|---|---|---|
| Interest rate | -200, -100, -50, +50, +100, +200 | unchanged numeric bps | bps |
| Non-rate | -15, -10, -5, +5, +10, +15 | unchanged relative percentages | % |

HTML, CSV and XLSX use one resolver and request parser. CSV adds trailing source metadata; XLSX adds a Unit column and Source sheet. Existing six-decimal export precision is retained. The HTTP basis and materialized-input hash match across formats. For example, `/scenarios/sensitivity/export?project=<owned-solar-code>&shocks=interest_rate&levels=-100,100&fmt=csv` evaluates that saved Working Copy, with ±100 bps applied to its actual Senior rate vector.

The source successor is finite: `tests/wf03_lifecycle_scope.py` owns the literal B1 paths and retains the reviewed-main WF03 pin map. D01 follows the final sensitivity blob, WS1 follows that D01 manifest, WF04 follows D01/WS1, then WF03 pins the final state. Existing historical manifests, base commits, policy, financial/native namespaces and CSRF inventory are preserved. No other test is weakened or repinned. The private preflight receipt enumerates every existing path/blob/direct dependent before edits.

Focused tests use signed synthetic local sessions and disposable databases. They compare real engine inputs/outputs across HTML/CSV/XLSX, whole database dumps, units and rate arithmetic; refuse scope/race/invalid requests before delivery; and inject source-governance negatives. Local proof and CI receipts must be assessed at the exact PR head. No merged/release-ready/live parity claim follows from these tests.

SHL indices, balancing-zero semantics, financial formulas, credit ESTIMATE/UNAVAILABLE policy, deployment and historical Runs are outside this change.

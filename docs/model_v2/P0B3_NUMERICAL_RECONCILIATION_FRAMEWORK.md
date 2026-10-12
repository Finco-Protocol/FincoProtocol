# P0-B3 — Generic Numerical Reconciliation Framework V1

**Scope:** Reusable validation tooling only. All fixtures committed with this PR are independently synthetic. It does not alter the production financial engine, workbook, debt, tax, source identity, regression tolerances, CI workflows, or user-data persistence.

## Prior public work reused

- PR #241 — the existing financial precision closure (no new changes here).
- PR #252 — Revenue V2 synthetic numerical validation (no reimplementation here).
- Existing WF07 Revenue, F0, statements, Senior debt, immutable Last Run and four-vertical exact-tree parity tests remain independent gate authorities.
- The new tooling does not execute any FINCO Run. A FINCO evidence export must refer to a known immutable Run, with a scenario/configuration identity and output digest.

## Authority contract

Use only evidence to which the user has rights. Store source files, original workbooks, normalized source outputs, private manifests, and generated reports **outside Git or under ignored \`reports/\` / \`artifacts/\`**. Never commit source-dependent fixtures, company names, project identities, conversion assumptions, confidential attribution bridges or source snapshots. The tools do not fetch, scrape or harvest a service.

CLI:

\`\`\`bash
python -m tools.numerical_validation \
  --authorized-source \
  --manifest /private/comparison-manifest.json \
  --reference /private/reference-normalized.json \
  --finco /private/finco-normalized.json \
  --output /private/reconciliation-result
\`\`\`

The CLI reads the manifest and both snapshot files, validates their **raw byte SHA-256** before decoding rows, creates deterministic \`report.json\`, \`report.csv\` and \`report.md\`, and emits only summary statuses to stdout. Exit code 0 means all mapped observations PASS their specifically declared tolerances; code 2 means at least one FAIL, UNAVAILABLE or NOT_COMPARABLE; code 3 means malformed inputs, invalid hashes, or unsafe output location. This is a validation verdict, **not an automatic financial-engine correctness finding**.

## Typed manifest

Manifest schema \`version=1\` requires:

- \`reference\` and \`finco\`: \`project_key\`, \`scenario_key\`, \`configuration_sha256\`, \`run_key\`, timezone-aware \`calculated_at\`, \`engine_version\`, \`output_sha256\`, \`currency\`, \`calendar\`, \`conventions_sha256\`. The project/scenario/configuration bridge is an **independently prepared normalized common identity**; mismatches are rejected, not reconciled opportunistically.
- \`reference_export_version\` and \`reference_parsed_version\`: must agree with one another and with the reference identity before numerical comparisons can proceed.
- \`periods\`: explicit one-to-one reference and FINCO period IDs, each with ISO \`start\` and exclusive \`end\`. Duplicate IDs rejected. Different date boundaries are NOT_COMPARABLE; no guessed proration or calendar transformation.
- \`metrics\`: a unique mapping \`key\`, an ordered \`stage\`, exact reference and FINCO metric IDs, \`unit\`, and independently justified **decimal** \`abs_tolerance\` and \`rel_tolerance\`. Duplicate mappings, negative tolerance and unapproved stages rejected.
- Both output files are JSON objects containing \`rows\` arrays; each row explicitly carries \`metric\`, \`period\`, decimal-compatible \`value\` (or null for missing), \`unit\`, \`currency\`. Duplicate identities and unknown keys are rejected. Missing/null is UNAVAILABLE, never silently replaced with 0.

Never infer a currency conversion, prices, fiscal calendar, indexation convention, unit scaling, production definition, allocation precision or source-to-FINCO run equivalence. Convert and attest these **privately before** generating an eligible normalized comparison manifest. A shared \`conventions_sha256\` is only an attestation of an external alignment decision; this tool cannot itself verify that economic definitions are correct.

## Reconciliation and earliest divergence

Dependency stages (in order):

\`\`\`
assumptions → generation → revenue → opex_ebitda → capex_funding
→ debt → statements → tax → cfads_waterfall → returns
\`\`\`

For each mapped metric and period:

- **PASS** — available, aligned, within the declared allowance.
- **FAIL** — available, aligned, outside allowance.
- **UNAVAILABLE** — an observation, field, or numerical value is absent.
- **NOT_COMPARABLE** — reference provenance conflict, currency/calendar/conventions conflict, period-axis or unit mismatch.

Signed residual is always \`FINCO − reference\`. The comparison allowance is \`max(abs_tolerance, rel_tolerance × max(abs(reference), abs(FINCO)))\`, expressed in the mapping's unit, and is reported explicitly. No arbitrary or retroactively widened thresholds. A PASS says only **this mapped observation** is within the declared tolerance.

The report enumerates mapped outcomes, unmapped evidence IDs, explicit tolerances, counts and the **earliest observed FAIL in dependency order**. Downstream FAIL statuses are not automatically assigned independent FINCO defects. Root cause remains \`UPSTREAM_DIFFERENCE_REQUIRES_INVESTIGATION\` pending verified inputs, definitions and independent review. No balancing, fitting, substituted reference metric or inferred defect classification.

## Bounded independent oracles

\`tools.numerical_validation.oracles\` uses independently supplied Decimal inputs for:

- Physical generation-share conservation.
- Revenue = quantity × authorized price / 1,000 kEUR.
- Debt principal roll-forward.
- Simple interest accrual with **explicitly supplied** days and day-count basis.
- Sources minus Uses.
- Cash opening + inflows − outflows = closing.
- Balance sheet assets − liabilities − equity.
- Discounted cashflow NPV with independently supplied discount factors.

These are *identity checks*, not a second project-finance calculator. They are independent of FINCO production modules and may not set or alter canonical FINCO assumptions or model outputs.

## Private provenance gate

When an external source header/export version differs from its independently parsed engine version, every numeric comparison is **NOT_COMPARABLE**, even if displayed amounts happen to match. It is not permissible to claim a financial acceptance by selecting a convenient version. Similarly no partial FINCO Run, changed scenario, stale historical snapshot or unreviewed convention mapping may become a comparison. A source dataset that has passed transcription/fidelity checking is not thereby financially or legally verified.

Historical case-specific facts and source hashes belong to the **private** P0-A/P0-B2 handoff report, not this file. The initial nominated external configuration remains blocked for external numerical parity until matching source state and immutable FINCO Run evidence exist; no source-dependent figures are published here.

## Verification

Synthetic test suite: \`python -m pytest -q tests/test_p0b3_numerical_reconciliation.py\`.

Keep the existing genuine financial parity rings in CI; do not generate new goldens, reduce assertions or change tolerance values. Compilation and public repository safety scan must PASS. Exact-head workflows must pass before independent numerical review: Public Safety full unsharded test rc=0, normal Python supervisor exit=0, mandatory evidence, browser six-role, Governance, Dependency Security and Compile.

### Safe inventory

Public: \`tools/numerical_validation/{__init__,reconcile,oracles,__main__}.py\`, \`tests/test_p0b3_numerical_reconciliation.py\` and this report. All data in committed tests is intentionally synthetic.

Private only: source evidence/versions, reference raw exports, scenario/run hashes and attribution decision, manifest prepared from authorized sources, normalized source and FINCO outputs, numerical reports and human root-cause reviews. The private handoff is not a PR artifact.

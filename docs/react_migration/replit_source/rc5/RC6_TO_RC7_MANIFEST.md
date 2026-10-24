# FINCO React transfer — RC6 → RC7 source delta

RC7 is an overlay delta, not a replacement package and not a full application archive.

## Reconstitution order

1. Extract `finco-react-transfer-rc5.zip` as the base.
2. Overlay the unchanged `finco-react-transfer-rc6.zip`.
3. Overlay this RC7 archive, preserving the listed paths.

Base design revision: `b94184d` before I23 edits. RC1/RC5 and RC6 archives are immutable; this iteration did not repack or rename them. Production API/DTO mappings remain `NEEDS_GITHUB_VERIFICATION`.

## RC7 overlay contents

| Path | Purpose |
| --- | --- |
| `scripts/finco-browser-smoke.mjs` | Product-state, native-period, scenario-period disclosure and OPEX source-drawer Chromium checks. |
| `scripts/resultsContract.test.mjs` | Product-state dimension and native-calendar/missing-value contract tests. |
| `src/components/mockups/finco-model/ResultsAnalysisView.tsx` | Display-only Working Copy vs Last Run context and scenario identity. |
| `src/components/mockups/finco-model/_results/resultsContract.ts` | Optional UI-only product context on the existing typed run status. |
| `src/components/mockups/finco-model/_results/runComparisonFixtures.ts` | Fixed synthetic per-Run display calendars and values. |
| `src/components/mockups/finco-model/_workbook/DecisionAnalysisWorkspace.tsx` | Explicitly separate native period evidence and unavailable Scenario Compare period basis. |
| `src/finco-transfer/App.tsx` | Transfer-only state selector and mapping to existing typed display props; retains legacy QA routes. |
| `src/finco-transfer/productStates.ts` | Transfer-only scripted state matrix fixture. |
| `BROWSER_ACCEPTANCE.md` | I23 test steps, results, viewports, limitations and evidence references. |
| `COVERAGE.md` | I23 coverage status and production boundary. |
| `INTEGRATION_READINESS.md` | I23 integration contract caveats and source quarantine. |
| `UI_COMPONENT_HANDOFF.md` | I23 component/fixture ownership and transfer notes. |
| `RC6_TO_RC7_MANIFEST.md` | This overlay map. The manifest is not self-hashed to avoid recursive hashes. |

`FINCO_I23_PRODUCT_STATE_REPORT.md` remains beside the source archive rather than inside it because it records the final archive checksum. Browser screenshots, generated build output, `node_modules`, secrets, and `.generated/mockup-components.ts` are excluded.

## Scope and use

- All introduced product states and run-period samples are fixed synthetic presentation fixtures. `productStates.ts` and `runComparisonFixtures.ts` must not be used as production data providers.
- `ResultsAnalysisView` remains a caller-owned component and does not import either synthetic provider.
- No finance formulas, period alignment, actual Save/Run, auth, persistence, APIs, or production DTOs are included.
- No generated Canvas module registry change is included in the final I23 diff or RC7 overlay.

## File checksums

The archive excludes this manifest’s self-hash to avoid recursive hashes. The following checksums are for the exact source/document bytes included in the archive.

| RC7 entry | SHA-256 |
| --- | --- |
| `scripts/finco-browser-smoke.mjs` | `6d69398d0b8da339c42532d3b84066fc61ede34afe57a0850b8b01e4a35a0c2c` |
| `scripts/resultsContract.test.mjs` | `21343012b4182e041fb1fa86d7989e83d29748aa44ae775da628faf7bb10d5b5` |
| `src/components/mockups/finco-model/ResultsAnalysisView.tsx` | `8933e6e47f7dc0b543f0ae01bd8733a357e45c2bd4b89fe4cd09cd9461f94a8a` |
| `src/components/mockups/finco-model/_results/resultsContract.ts` | `e43faab162313fccc213d074d7c202c4b7c832bb6c67e90016771ee9c2481c73` |
| `src/components/mockups/finco-model/_results/runComparisonFixtures.ts` | `28e54a3248b730bddab06e55f377b22b39b20c63d863083fccac8664e46b38db` |
| `src/components/mockups/finco-model/_workbook/DecisionAnalysisWorkspace.tsx` | `5191a71e24fda59193fda903a926c5a4c7f56279bcd3024f1993797197e5aede` |
| `src/finco-transfer/App.tsx` | `63479a0023d108d9937ac7471e5b9b5ffeda66a485868c19dc96299552cf130d` |
| `src/finco-transfer/productStates.ts` | `5e4b3b9b6a1be1110a0056ba061a03014b6c2669a8455ff80877869845136cac` |
| `BROWSER_ACCEPTANCE.md` | `e0f8072685eea15c51e5a0e8d011d7a8d2290d41165abaaa553fd6d77bc47ec1` |
| `COVERAGE.md` | `7033a07b2b2e8cc7d26d6bf9ad1be408fe810b43fde5842e52e95b2310118001` |
| `INTEGRATION_READINESS.md` | `1813df66c5559b280e41359ff0d708f6c00f28af144775af4c3cd216ee711d36` |
| `UI_COMPONENT_HANDOFF.md` | `ac08a5a2890f719c23cc810b7bde83a90643ad4be4fae4bfe6d42d682566b67d` |

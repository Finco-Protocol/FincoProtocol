# Fixture provenance
Source: `ON07_FIXTURE_REVIEW_PACKAGE.zip` (user upload), sha256 `8b17aae6c5e59a7a788a35f2214733e16100a237baa0c06a0434b935a7b5b7b1`. Authored at main `8a74fcb5`; executed here against main `db504f6408cb456c617c9342a1ffa202ee455283`.
| File | sha256 |
|---|---|
| ON07_PROJECT_FIXTURES.csv | 7b717127ff25dd495a7bc347d4c0e3816e69f6125d0117cc8210be9c071b20c5 |
| ON07_PROJECT_FIXTURES.md | 1dc91b353bc8949d67d014752630d8df9a4900d145dc795f401f4178acd594c0 |
| ON07_FIELD_MAPPING.csv | fa4e9e4ddfca63594d9e68a5b34162a2dc5e67b26f3bc3a5281708b42679c8b3 |
| ON07_OUTPUT_COMPARISON_TEMPLATE.csv | d960b9249d64370b0b1093993f671ebfe158432e5e9aea4e97432fa3763d31ed |
| ON07_REACT_LEGACY_GAP_CHECKLIST.md | 30fed73b393ee8ad67dadd02762e37dac7097f4bcdf411fc1bdbf9cff28e4dd3 |
| ON07_RUNBOOK.md | 3fb548d74f472abb8e31d72cb5c0be498d17a78fba50c565e4a96030f1ccb77c |
| ON07_UNVERIFIED_ASSUMPTIONS.md | c16515df0be0552e6b711307ac91faed7184e90c0575ada7da2a33bd6d5b1673 |
| README.txt | bd1c39b46e21b595676e7d087f17f11aa08c5d4a614c82725ead148ae64bdab3 |
The package files are not redistributed here. 172 ledger rows (43 keys x 4 fixtures): 112 EXPLICIT, 52 ENGINE_DEFAULT, 8 EXCLUDED. No value was altered or substituted: EXPLICIT rows are applied verbatim (the single transformation: the literal `(empty)` merchant-curve cell is applied as an empty string; `false` as boolean False). Legacy keys `tariff_eur_mwh`/`ppa_term_years` are mirrored from `rev_ppa_base_tariff`/`rev_ppa_term_years` because the adapter requires them (canonical `rev_*` keys take precedence); `operating_hours_p90_10y`, `total_capex_keur`, `opex_y1_keur` have no registry-field snapshot target and are written to their snapshot keys directly — all recorded in each capture under `snapshot_applied_keys`. Country XA/XB, project names and capacities are passed to the reference seed exactly as in the CSV.
Known deviation from the browser route: values are written to the snapshot directly (registry `validate_field_update` is run and recorded where a registry field exists), not through the grid/Save All endpoints.

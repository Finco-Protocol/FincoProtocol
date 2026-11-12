# C06 Correction A — cost workspace profile presentation

Accepted base: main `b1c08e2d00fe9933565d253d5cee6e5849b143e1`, tree `5b25c1f245d3d53d9bbe24060c13dc936e06b8d7`.
Existing Draft #444 is retained. Accepted main was merged normally into its existing branch; no rebase or replacement PR.
R04 #442 merged before this correction. The accepted chain is F04 → isolated R04 → C06; R04 is still not production PPA wiring.

## Result and authority

Four presentation files expose monthly profiles on ACTIVE user-added CAPEX lines only when the canonical server item list includes them.
Profile-only Save remains distinct from staged amount Save, with existing CAS, scenario/project ownership and readback checks.
The served JS is generated from these sources; CSS stays byte-identical. No app, domain, financial engine, auth, flag or workflow changes.

OPEX Year 1…N remains the canonical read-only saved-line projection. Annual editing is `OWNER_POLICY_BLOCKED / CANONICAL_WRITER_MISSING`.
`FINCO_SAVE_ALL_PROFILE_ENABLED=OFF` (OD-B2), `FINCO_G10_RUN_OPEX_PANEL=OFF`.
O-G-U2-1 (line code versus persisted `sub_line_id` after manual database hard-delete) and B-09 catalogue expansion remain separate owner decisions.
Retiring a profiled line continues to refuse Run with `CAPEX_PROFILE_LEAF_UNKNOWN`; no profile/history deletion or remapping.

## Build evidence

Clean accepted main was built using lockfile-pinned packages and the exact CI `npm ci --ignore-scripts --no-audit --no-fund` / `npm run build` scripts.
Both assets compare byte-for-byte with committed main:

- JS Git blob `6a27300af4d4f818c3f30800b6b8ae634c50224b`.
- CSS Git blob `e3eec67e9e8556e0e3a0bb3892d1209eccffb670`.

C06 JS output is recorded exactly in `SOURCE_SUCCESSOR.json`; CSS is frozen to the accepted base. The identity guard remains unchanged.

## Finite provenance contract

`tests/c06_cost_workspace_scope.py` binds the accepted base/tree, finite literal path set, source/base blobs and Git modes.
It registers once after R04 and never calls predecessors from its low-level signature. One-occurrence literal transformations give R04 its single forward hook,
append the registry tail and extend historical positive tail assertions by exactly one signed state. Historical manifests remain byte-identical.
Eight current maps change only existing registry and JS keys. R04's immutable production baseline remains intact; only its evaluated JS pin can follow the signed C06 successor.

Additional correction paths have specific purposes: generated JS fixes served-source drift; the C06 scope/manifest/negative suite establish closure;
the browser acceptance tests the added-line journey; historical tail tests recognise the one successor and continue exercising real tamper mutations.
`source_blobs`, `base_blobs`, `source_modes`, `base_modes` provide the exact path ledger without a self-referential final commit hash.
Final commit/tree, full file ledger, local logs, browser images and hosted run IDs are delivered in the private owner evidence bound to the pushed commit.

## Validation contract

Focused checks cover userLineProfile, profileDraft, profileImport, combined Save, three TS configs, real-app C06 replay and generated profile keys.
The replay explicitly asserts zero-amount Run success in its positive category fixture and full document/identity preservation on stale CAS.
The desktop/mobile browser acceptance uses a real added ACTIVE server-listed line, invalid month-count/sum refusal, explicit monthly percentages,
profile-only Save while amount is staged, reload readback, a real synthetic local Run and 1440/390px layout.
Negative controls cover byte/map/manifest drift, forged pins, base/tree/mode mismatch, symlink/deletion, missing/duplicate/reordered registration,
closed foreign paths, partial handoff and committed-ref versus working-tree isolation. Earlier F04/R03/T01-E and R04 controls remain mandatory.
Clean-main/corrected-C06 paired RC-SEC, trust and F01 suites determine whether prior security failures were a transitive provenance cascade.

Final-head hosted acceptance requires all six workflows, including every selected CI V4 shard, F01 child and aggregate gate.
No earlier HEAD's green is substituted for this evidence. Staging acceptance remains pending; no merge/deploy is authorized by this correction.

Independent source review found no financial/security authority expansion; the two replay assertion weaknesses were tightened.
The unrelated `editing.test.mjs` staging old/new assertion is compared on clean main and C06 in the private report; it is not weakened here.

## Correction checkpoint — governance contract blocked

The regenerated served bundle and real added-line browser journey pass locally. The proposed C06 leaf itself is exact,
but the full composite remains invalid. In particular, UX-PR2c cannot supersede `ProfileDraftProvider.tsx` through
UX-PR3b1's own finite superseded set. UX-PR2b's signature-level authority separately requires membership in that same set
for the changed provider/row editor. CI V4 calls this signature-level authority.

Both UX-PR2b and UX-PR2c scope files are frozen byte-for-byte by accepted T01-E/R03/F04/R04. Their historical manifests
cannot be repinned under Correction A. No frozen guard or manifest was edited to conceal this missing handoff.
This local candidate has not been pushed; no final-head hosted rerun or green verdict is claimed.
A reviewed governance contract change is needed before the candidate can become eligible for push.

# RC-7B Correction D: CSRF inventory and financial authority reconciliation

Disposition: **CORRECTION PARTIAL - FINANCIAL / GOVERNANCE APPROVAL BLOCKED**.
No financial approval, merge, deployment, activation or protected-path exemption.

## Provenance and original CI

- Verified main / merge-base: `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`.
- Initial HEAD: `8048a74e7f568a40fbcaecf185621350c8251a85`, OPEN/DRAFT,
  MERGEABLE, 23 ahead / 0 behind, clean at preflight.
- Final commit identity and new exact-head CI observations are recorded in the
  final PR handoff. A document cannot embed its own enclosing commit SHA;
  the final handoff copy includes that resolved SHA without changing the tested tree.
- Original exact-head Public Safety run `39157941164`, tests job `117765077620`:
  13287 passed, 77 failed, 105 skipped; pytest rc=1, child exit=1,
  `normal_exit=false`, zero collection errors/deselection. Complete JUnit
  SHA-256 `1cf7dd825e3a69be326824ea42728a377e2d4757d700163cff92438f8dd72ea4`.
- Mandatory Evidence `117784823535` fails downstream:
  `PUBLIC_SINGLE_GATE_FAILED: Required jobs failed/missing: source=success, control=failure`.
  It is not an independent defect or a missing-upload assumption.

## Complete failure inventory

`RC7B_CORRECTION_C_GOVERNANCE_FAILURES.csv` now contains all **77** original
nodes, independently matched to the original complete JUnit failure set.
Every original assertion, sanitized error, authority checkpoint, guard blob,
pin evidence, purpose, successor process and required approval is retained.
New columns bind the original HEAD and the Correction D disposition.

| Original failure class | Count | D disposition |
|---|---:|---|
| Live integration scope guards, financial namespaces | 50 | BLOCKED |
| Current exact-content / candidate authority | 24 | BLOCKED |
| RC-7A current M7/PPA byte coexistence | 1 | BLOCKED; historical proof separated |
| Live CSRF consumer inventory and its WF-09 caller | 2 | Scoped correction implemented; independent review pending |

The normalized classes total 52 LIVE_INTEGRATION_SCOPE_GUARD and 25
CURRENT_EXACT_CONTENT_OR_CANDIDATE_AUTHORITY. No failure is relabelled as
harmless merely because the underlying source was once reviewed. No actual
financial equation or security bypass defect was established by these nodes.

## Implemented correction

1. New `tests/rc7b_quarterly_csrf_successor.py`: inventory recognition for only
   `app/v2/quarterly_calendar_router.py`, Git blob
   `7e3ea127918bfe9d9988a807a25f65b44bd4731c` at immutable initial HEAD.
   Full module AST SHA-256 is the literal
   `f0a89f03124dcdf672e3cb89f00596e8881191b7ee4d020db465b63cff0d093d`.
   Exact content, full structure, source ancestry and literal closed activation
   must all hold. Missing evidence fails closed. No permission is given to any
   other router, writer, engine or namespace.
2. `tests/test_trust_readiness_controls.py`: adds only the conditional quarterly
   consumer through that successor. Existing exact inventory, protected router
   function checks and all historical M6/M7/WF-09 contracts remain.
3. New `tests/test_rc7b_quarterly_csrf_successor.py`: altered content, removed
   token validation, changed status/auth/owner/reference/CAS/financing checks,
   changed routes/fields, additional writer/Run, missing Git evidence and opened
   activation lose recognition. Real HTTP tests exercise anonymous, cross-owner
   and protected-reference refusal without any calculation or history change.
4. `tests/test_rc7_quarterly_rc7a_compatibility.py`: adds a separate positive
   immutable checkpoint/ancestry proof. The original current-byte assertions
   remain blocking, with an explanatory comment; no original pin is replaced.
5. Existing failure register is reconciled to the complete 77-node evidence.
6. The quarterly successor contract documents the security-only boundary and
   unchanged financial blockers; this report records the distinction.

## Historical proof versus current authority

The original RC-7A base is `78e4c0edcc1bdb5013df79f11b3ba7b9c2151013`.
Research merge checkpoint `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d` is its
descendant and an ancestor of the candidate. Both immutable checkpoints carry
all eleven M7 and three PPA-01 original blobs. The new positive proof verifies
exact bytes at both checkpoints, not a guessed historical state.

The existing test
`test_all_historical_m7_and_ppa_bytes_are_preserved_without_successors` also
checks current working-tree bytes. Its M7 adapter assertion still expects
`14bd759a9958515a7796626f93c1bd2233d69150`, not quarterly candidate
`d97ae939559cbd6e031414192fa23fc40be1110f`. That current requirement cannot
be moved to history solely to pass CI. It remains a separate blocking gate.

All twelve quarterly candidate financial/core paths were checked against the
existing literal candidate/predecessor manifest. Correction D changes none.
No historical M7, F3, WF04, WF07, PPA-01 or RC-3 pin or financial governance
helper is edited. `approved_frozen_path` and `strictly_frozen_changes` gain no
exemption, and no acceptance record is fabricated.

## Numerical and security validation

Focused execution counts/durations and exact final-source observations are in
the final handoff. Tests include the original three new failure nodes, complete
impacted Trust/CSRF modules, new security mutation and real endpoint cases,
quarterly admission, independent financial oracles, monthly construction/IDC,
actual funded Senior at COD, statements/returns and Credit V4 interval identity.
The original RC-7A current-authority node is intentionally recorded as FAIL,
not skipped/xfail or hidden inside a passing selection.

| Local execution | Result | Duration |
|---|---|---:|
| Original three nodes + initial successor negatives + historical proof | 21 passed / 1 expected authority failure | 89.44 s |
| Full impacted Trust/CSRF modules, including original successor tests | 214 passed / 1 existing skip | 702.33 s |
| Final new successor module, including real endpoint security cases | 21 passed / zero skips | 108.67 s |
| Quarterly financial, admission and Credit V4 ring | 379 passed / zero skips | 376.07 s |

All completed processes returned explicitly (rc=0 for the passing rings,
rc=1 for the preserved authority failure). The one existing skip is exactly
`tests/test_trust_readiness_registry.py::test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code`,
reason `trust pack not part of this diff`. No new skip or xfail was added.
The final successor module includes the three additional real endpoint cases
not yet collected by the earlier full impacted-module run.

Four complete cold-cache canonical 6/6 results were recomputed and equal the
immutable main evidence in full, including input identities, tax, financing,
statements and returns. Maximum difference is zero for Solar, Wind, Data Center
and EV. No tolerances or goldens were changed. Local Playwright-specific cases
are reported separately from Public Safety's environment-dependent skips.

## Remaining decisions and CI efficiency

75 original financial/integration authority failures remain blocked. They
need independent acceptance of the exact twelve financial successor blobs,
financial-owner decisions and separately reviewed bounded governance wiring.
Historical proof or CSRF recognition is not a substitute for that process.
D-01 through D-12 remain OPEN, with D-06/D-07 deferred. Sponsor distribution
policy D-08 and quarterly reserve policy D-09 are not ratified by arithmetic.
`ACTIVATION_ENABLED=False`; existing SHL/reserves are not silently converted.

No full local public suite or blind CI rerun is used to rediscover known
blockers. Only a meaningful locally validated correction may be pushed. New
automatic exact-head checks must be reported by their own SHA; prior HEAD's
eight successful workflows cannot establish new-head acceptance. Pending
checks are not green, and expected remaining failures are not bypassed.

**CORRECTION PARTIAL - FINANCIAL / GOVERNANCE APPROVAL BLOCKED**

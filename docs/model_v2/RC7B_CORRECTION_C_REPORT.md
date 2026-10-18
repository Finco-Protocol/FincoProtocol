# PR #320 Correction C: financial structure preservation

**NO MERGE.** Technical correction is separate from independent financial
acceptance, financial-owner decisions and product activation. No approval
record, release pin, tolerance, golden or financial formula is changed here.

## Source and provenance

- Live preflight main: `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`.
- Source parent: `01e81143070f1381bc0ad45bd8f5d61460cb3c66`.
- Merge-base: the main above; pre-correction relationship 20 ahead / 0 behind.
- PR #320 was OPEN / DRAFT / MERGEABLE, with no reviews or review threads.
- Original Public Safety `39153680979`, tests job `117752619584`, was still
  running at preflight; source safety and the other reported checks passed.
  Pending full pytest is not acceptance. Final exact-head CI is reported in
  the PR handoff, not inferred from local tests or prior green jobs.

## P0 reproduction and correction

The unmodified source parent converted the default Solar financing from
`SHARE_CAPITAL_THEN_SHL`, SHL 7750 kEUR, clean SHL principal 7750 kEUR and
DSRA 6 months into `EQUITY_ONLY`, zero SHL and zero DSRA through `apply_config`.
This occurred even though `ACTIVATION_ENABLED` was False: the downstream Run
gate did not make that input conversion legitimate.

The corrected adapter requires the actual inputs to be eligible before
creating quarterly calendar inputs. It returns the **same financing object**,
not a financing replacement. SHL funding/IDC/accrual/cash schedules, reserve
months/requirements/accounts/DSRF commitments and other project funding are
refused. The existing canonical quarterly scope validator also runs before
calculation. The `excluded_structure` wire key remains decode-compatible but
never authorizes removal of financial amounts. Mismatched records still fail.

The frequency endpoint validates actual Working Copy inputs before Save;
generic consent cannot override refusal. Imported or previously saved invalid
selections remain renderable with an explicit warning. Display-only fallback
does not write, execute finance or feed a Run. The real Run still materializes
the original selection and refuses before execution or commit.

No new financing workflow is introduced. Eligible acceptance projects are
explicit synthetic, equity-only/no-reserve fixtures from initial creation,
not existing business projects converted by the frequency selector.

## Functional acceptance

The focused admission/workspace suite covers:

- Actual default Solar SHL + six-month DSRA: frequency Save refused; Working
  Copy, prior 6/6 Last Run and Run History preserved.
- Matching, fabricated and imported exclusion records: no financial permission.
- Batch Save: typed scope refusal inside the canonical atomic transaction,
  with rollback and no Working Copy changes.
- Direct snapshot adapter and direct canonical financing entry refusals.
- All workbook presentation sheets with a saved invalid selection: renderable,
  visible invalid-selection warning, no engine call and unchanged history.
- Genuine eligible Solar/Wind: Save -> STALE -> canonical 3/3 Run -> CURRENT,
  rerun, history/export and 6/6 reset; activation is opened in tests only.
- CSRF and CAS rejection, unsupported technology and strict JSON decoding.

Final local execution: **59 passed**, no skips, rc=0, normal return in
171.18 seconds. Initial fixture failures were corrected in synthetic test
setup (consistent FC/duration/COD and expected atomic typed refusal), not
by changing financial calculations or loosening assertions.

An older Credit V4 test fixture lacked committed period start evidence. It
now supplies an explicit start and typed numeric cells; Credit V4 production
code and its interval safety are unchanged.

## Independent numerical evidence

The quarterly axis, financial funding/statements, candidate negative controls
and all three Credit V4 modules executed: **320 passed**, no skips, rc=0 and
normal process return. Independent expectations use the existing 60-digit
Decimal oracle from declared inputs, not candidate-generated goldens.

| Maximum residual | Solar | Wind |
|---|---:|---:|
| Revenue, kEUR | 6.359e-13 | 8.765e-13 |
| EBITDA, kEUR | 6.288e-13 | 9.254e-13 |
| Annual cash tax, kEUR | 9.996e-9 | 7.576e-12 |
| CFADS, kEUR | 9.996e-9 | 7.149e-12 |
| Senior size, kEUR | 0 | 2.5e-12 |
| Senior opening/interest/principal/service/closing, kEUR | 9.890e-7 | 6.904e-10 |
| Balance Sheet, kEUR | 2.792e-11 | 3.934e-11 |
| Project dated XIRR | 9.358e-16 | 4.544e-17 |

These are conservatively rounded-up observed maxima, not replacement
tolerances. Existing solver, statement and return tolerances are unchanged.
Solar has 100 operating periods; Wind has 108. Terminal Senior and construction
Sources/Uses residuals are zero in both oracle cases. Sponsor arithmetic is
tested but quarterly distribution eligibility remains pending D-08.

Monthly construction tests now execute the original eligible 6/6 Working Copy
**before** selecting 3/3. Financing inputs, construction funding, fees, IDC,
Project Uses, Senior commitment and construction statement rows must agree.
Independent inclusive ACT/360 or ACT/365 IDC and actual COD Senior funding
(including non-construction funding) reconcile within existing 1e-6 kEUR.

Complete cold-cache canonical 6/6 results, including effective inputs, G2C,
tax, statements and returns, were serialized on immutable main and the
corrected source. All four complete objects and input identities are identical:

| Vertical | Result SHA-256 on both sources |
|---|---|
| Solar | `a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481` |
| Wind | `b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333` |
| Data Center | `bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed` |
| EV | `45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545` |

## Governance reconciliation: not a release

The prior Correction B report claims 73 remaining failures but its listed
node specifications enumerate **72** collected nodes in 38 modules. Executing
all 72 reproduced 72 failures, rc=1, normal return (359.96 seconds). The
unidentified extra claimed node is not silently accepted or invented; full
exact-head CI remains the authority for additional failures.

`RC7B_CORRECTION_C_GOVERNANCE_FAILURES.csv` records each exact node, original
assertions, observed failure, immutable authority checkpoint, original guard
Git blob, assertion-introduction commit, relevant original content pins or
predecessor blobs, classification, successor process, required independent
approval and unchanged negative controls. Local user paths in public trace
text are redacted; original private JUnit/logs are retained.

Current exact-content/candidate authority requirements are not interchangeable
with historical provenance. Live integration scope guards are also not
automatically historical tests. Neither class can be waived simply because
the candidate passes numerical tests. Negative tests whose accepted-content
setup already fails remain blocked, not claimed as successful mutation tests.

The #313 historical isolation assertion was already corrected in Correction B.
No further historical assertion was changed in Correction C. The successor
contract is corrected: live finance-integrity guards do **not** contain the
RC-7B recognition clauses removed in Correction A.

All twelve protected RC-7B candidate blobs remain unchanged. Historical
authority modules/pin maps remain unchanged, including M7 and PPA-01 maps;
the candidate recognition module is not a release authorization.

## Outstanding decisions and final gate

**TECHNICALLY FIXED:** frequency selection cannot discard funding; invalid
saved financial selections render and refuse Run; like-for-like funding
acceptance uses the original 6/6 structure.

**INDEPENDENT FINANCIAL REVIEW REQUIRED:** exact twelve-blob quarterly
successor and final integrated application correction; no financial acceptance
record has been created. Current financial governance failures remain BLOCKED.

**FINANCIAL OWNER DECISION REQUIRED:** D-01 COD stub; D-02 day counts; D-03
horizon; D-04 annual clocks; D-05 PPA timing; D-06 3/6 and D-07 6/3 (deferred);
D-08 distribution/covenant observation; D-09 reserves; D-10 maturity; D-11 tax;
D-12 supported financing/technology scope. All remain OPEN.

**PRODUCT ACTIVATION DEFERRED:** `ACTIVATION_ENABLED=False` remains literal.
No quarterly, Junior, Revenue V3 or BESS activation is granted.

**NO MERGE.** Return the exact final branch for independent financial and
governance review. No deployment or merge recommendation is made.

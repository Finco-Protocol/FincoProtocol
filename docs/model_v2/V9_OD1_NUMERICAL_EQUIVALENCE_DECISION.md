# OD-1: V9 numerical equivalence decision package

Status: **PENDING; no Financial Owner decision, signature or approval is asserted.**
Base: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`.
Exact proposed content is listed in `V9_CANDIDATE_BLOB_MANIFEST.json`.

## What was executed, not inherited from the PoC

Fresh actual immutable-main Runs cover 60 typed input/policy snapshots: all 49
historical scenarios, four vertical references, equity-only Solar, four further
DSCR boundary cases and two isolated RC-7C v2 projects. Input/policy fingerprints
are identical between checkouts. Computational FEASIBLE means the engine returned
a result, not a bankability certification or automatic Integrity PASS.

The unchanged default path produces 42 bit-identical feasible results and 18
identical rejections, including complete exception type/code/text. The joint
proposal produces 35 numerically/evidentially different results, seven identical
results on canonical-only paths and 18 identical rejected outcomes. No financial
terminal, binding-constraint or Integrity classification flip was observed in
this finite matrix. That observation is not a universal rejection-equivalence proof.

## Existing authorities, not proposed tolerances

| Quantity / check | Existing authority retained |
| --- | --- |
| Senior solve | absolute `1e-4` kEUR; relative `1e-9` |
| G2A service budget | `1e-6` kEUR refinement trigger |
| Strict G2A refinement and minimum-size handshake | `1e-7` kEUR |
| Construction outer convergence | `1e-7` kEUR |
| Strict final construction idempotence | existing `10 * outer_tolerance`, i.e. `1e-6` kEUR at the canonical default |
| H-1 initial DSRA target | `1e-6` kEUR |
| Project-return terminal classification | existing `1e-7` kEUR scale |
| SHL/tax final recomputation | existing absolute/relative, ratio and gate-consistency checks, unchanged |

These are residuals/decisions in different contracts. They must not be combined
into a new blanket cross-path tolerance. In particular, passing a `1e-4` Senior
check does not authorize changing a `1e-7` terminal decision or evidence field.

## Observed representative differences

The largest observed kEUR difference in the complete proposal matrix is
`6.3059269450604915618896484375e-7`, in
`W25r-dscr2.0: g2c_result.total_shl_cash_interest_received_keur`.
Related Sponsor receipts differ by about `5.56e-7` kEUR. This is a cumulative
cash-flow difference, not merely a displayed decimal and not an approved bound.

Different coupled iterates affect reserve funding, capitalized costs, tax/CFADS,
interest, SHL receipts, equity cash flows and their dated return metrics. Outer
iteration/residual evidence also changes. Every changed leaf is retained in the
complete `proposal-comparison.json` in the private review packet; no financial
field is silently omitted to obtain an equivalence result.

Unlevered Project cash flows and Project XIRR remain unchanged in the observed
matrix. Its excluded-financing-cost/reserve disclosures can change and are
reported separately, not presented as identical Project evidence. Integrity
evidence digests necessarily change; they are listed as provenance differences,
not mislabeled as a PASS/FAIL transition.

Independent 80-digit Decimal arithmetic recomputes Sources minus Uses, Balance
Sheet identities and Senior opening-principal-closing roll-forwards from stored
IEEE output leaves. Missing statement components remain unavailable, not zero.
The observed largest proposal BS residual is approximately `1.02614e-9` kEUR and
Sources/Uses residual approximately `1.02591e-9` kEUR. These are measured residuals,
not financial corrections or new tolerance definitions.

For every feasible case, the packet reports actual Senior/SHL maturity balances,
their existing terminal status and distance to the existing `1e-7` scale. A small
representative difference is not accepted merely because a sampled terminal
margin remained positive.

## Decisions that remain separate

1. **OD-1 numerical representative policy:** bit identity is not met by 35 joint
   proposals. A Financial Owner must decide which exact fields may differ and
   under which existing authoritative residuals. This package does not choose
   or implement that policy.
2. **Intermediate rejection coverage:** precision acceptance alone cannot waive
   canonical intermediate failures. Guarded mode retains a complete canonical
   re-decision even for successful proposals. An equivalent cheaper proof is
   still required before raw proposal latency can become accepted Run latency.
3. **Failure-path cost:** guarded/fallback time includes attempted joint work and
   canonical re-decision. It must be measured, not hidden behind raw speedup.
4. **BW:** excluded. The existing test-only seed is evaluated separately; no new
   production seed argument, orchestrator change or warm-start state is added.
5. **Evidence semantics:** joint iteration counts are separate candidate evidence.
   They are not substituted for historical H-1 iteration counts. Proposed policy
   evidence carries `V9_DISABLED_NON_AUTHORITATIVE_JOINT_PROPOSAL`, never a claim
   of approved H-1 execution. Future released serialization needs its own review.
6. **Exact-content governance:** four financial-file candidates and the shared
   application assembly hook require independent review. The manifest is not a
   release map. Historical authorities and their negative controls remain intact.

No approval here changes quarterly D-01 through D-12, quarterly admission,
Revenue V3, BESS, Junior activation, tax/accounting policy or a historical Run.

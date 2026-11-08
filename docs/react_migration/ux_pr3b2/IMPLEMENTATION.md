# Compact Financing editing — PR3b-2

Base: merged #430, `4e22f330d97eec66befcbb5df6dc4e1529ae6835`, tree `cc12db380b5d3fb51dc46b4113050855864bc360`.

The single Financing home adds server-bound scalar inputs in Structure & Terms,
Repayment & Covenants and Facilities / Funding blocks. Each scalar block uses
the already published atomic `/v2/workbook/save-all` capability: one request
containing only its cells, no contracts, cost lines or profile document. The
client retains human units and uses the canonical validator. Fresh scope/CAS
checks precede the POST; fresh projection read-back proves persistence. Dirty
values use the existing shared store, remain visible on refusals and are
cleared only by verified Save or explicit Reset/discard. An unknown outcome
locks editing and can be reconciled only by the identical idempotent request.

Bankability remains one configuration document saved by its existing canonical
writer. It is available under Advanced with the original supported repayment,
native period grid, fee/reserve gates and serialization. Reload preserves a
dirty document and requires explicit review before replacing changed saved
configuration. No new repayment algorithm or financing instrument is introduced.

## Existing functions retained

| Selector | Read authority | Existing writer / new location |
| --- | --- | --- |
| `terms` | GET fields/debt | POST workbook/update per field remains; scalar block additionally uses published atomic Save All |
| `bankability` | GET financing/studio + fields/debt tokens | POST workbook/update, debt.bankability.configuration; same document editor under Advanced |
| `facilities` | GET financing/studio | Read-only capital stack; no new facility writer or activation |
| `investors` | GET investors/agreement | POST workbook/investor/agreement from server-issued URL, agreement-version/composite CAS; full existing editor retained |
| `debt-metrics` | GET analysis/debt-metrics / credit-decision, selected Run | Read-only native schedule/history; Edit terms retains existing destination |
| `sources-uses` | GET financing/studio, committed Last Run | Read-only; no fabricated Saved Sources & Uses |
| `overview` | GET financing/studio | Read-only detailed evidence |

All selectors and direct Debt Metrics → Debt terms remain available. Scalar
drafts survive internal navigation; local document drafts require the existing
leave confirmation. Run and history remain separate from Save.

## Contract boundaries

Facility collections are not scalar cells and remain excluded by the server's
Save All capability. Sponsor agreement changes remain in their complete-document
editor; independent per-row/block writes require a separately reviewed contract.
Rate base/margin, derived repayment, gated instruments and lock-up information
are not promoted to editable inputs. The server's field binding, protected
status and capability decide eligibility, including roles. Bankability fees
and reserves keep their existing per-policy authority checks.

`FINCO_SAVE_ALL_PROFILE_ENABLED=0`, OD-B2 pending. No profile payload or profile
Save rewiring, backend, engine, rate normalization, sizing, DSCR/Run policy,
Revenue or Tax changes. UI Save never executes Run. Existing snapshot assurance
and Battery release limits remain those of #430. Product acceptance requires
real isolated staging at the integrated revision; local synthetic screenshots
and green PR CI do not establish a deployment.

## Governance

The bounded successor records actual base/current Git blobs, ancestry, base tree,
registration, exact path closure and modes. Historical manifests stay intact;
only genuine base-current source pin moves in seven existing integration maps
are permitted. Its low-level exactness never calls the registry composite or a
predecessor validator. Read-only call memos are discarded before mutations.

# PR #389 — Governance reconciliation / Correction C

Financial Owner scope authorized by the 2026-10-27 assigned prompt, including protected governance tests. No financial source changes, historical pin replacements, release state widening, CI bypass or deployment.

The reviewed F01 acceptance workflow is a CI job with read-only `contents: read`, `persist-credentials: false`, explicit browser/pytest cases and offline/non-root native tests; no production activation or deploy step. Its frozen Git blob is `8b7b49a49583fc33c48d60cc55bd88ea9e88ef8d`, unchanged. `tests/v11_stage3_successor.py` now ignores that *one exact blob on that one path* when classifying activation references, conditioned further on test-only semantics. It does not add F01 to the set of owner-released activation surfaces or change V11 release/approval records. Every byte-level mutation loses the exemption.

Changed authority blobs: `tests/v11_stage3_successor.py` `cf51845fc00a919b332d4814903fe4ad16cf868d` → `09f85eabd103f3eb07d760102c55b9217f16e64c`, `tests/test_v11_stage3_successor.py` `459b8cbb67f661933c648f7eba24d70d15da5260` → `c3ac53df8c8fe58f42a060f8f2587a2136041b03`. Negative controls explicitly cover a byte change, V11 enablement, deploy, elevated permission, OIDC permission, release action and a separate workflow. The previously existing synthetic V11 activation tests remain intact. The broad `.github/workflows/**` glob is **not** exempted; unrecognized content is still rejected.

All original governance historical SHA pins remain. New exact-head comprehensive tests are mandatory before merge.
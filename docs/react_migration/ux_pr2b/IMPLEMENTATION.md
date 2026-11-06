# UX-PR2b — shared CAPEX profile draft

Stacked on unmerged #427 at `4d661e5a6e06e3a41a31b8c1ddd1896dd835e760`, tree `e6453b1828c39a7698c5cddbcfa0f9aab9a631a9`. Draft; no merge or deploy.

The workspace owns one lazy, project/scenario-bound raw profile draft above view remounts. Lines and Monthly schedule bind the same shapes, explicit percentage cells and milestone inputs, undo/redo, canonical preview, dirty registration and profile-only Save. Moving between these two CAPEX views retains the draft without a discard prompt. Other navigation keeps its existing guards. Raw invalid and ambiguous inputs remain reviewable; no missing zero, excess month, rescaling or rounding is silently introduced.

Only API-offered shapes and eligible active positive-amount items are selectable. Added lines remain deferred (D-13). The optional saved timeline remains a separate reader of the saved document and server allocation strings. The draft amount preview uses the existing canonical server endpoint, with request/project/scenario/hash/duration cancellation identity, and is labeled Preview rather than Saved or Last Run.

Save uses the existing CSRF/composite-CAS canonical profile writer. It does not save staged cost amounts/comments or run the engine. Every successful response requires a fresh full shape/explicit/milestone document equality check. Refusal retains the draft; an UNKNOWN or unverified success locks it until read-only reconciliation confirms the full requested document, without speculative resubmission. Changed scope retains the original draft and blocks applying it to the new scope. Rebase after unrelated input changes is explicit and requires the saved profile document to be unchanged.

Governance is a closed literal successor, rooted at the immutable verified PR2a parent and tree. PR2b's low-level proof reads only git objects and its own manifest; PR2a delegates one way to that proof. PR1 follows PR2a's authenticated current pins. Historical PR1 and PR2a manifests remain unchanged. Seven existing integration manifests may move only current PR2b-owned pins; their historical metadata and key sets stay unchanged. Source matching also requires the supplied bytes to equal the evaluated file/ref, so an old historical blob cannot bypass a current-source guard.

Tests are additive in the existing mandatory consolidated Chromium role. Local explicit runner: `pytest tests/ux_pr2b_browser_role.py`. Unit validation: `node frontend/src/app/capex/__tests__/profileDraft.test.mjs`. The successor suite mutates real throwaway worktrees and restores original HEAD and modes after every test. Private evidence records the matrix and actual CI conclusions; this document makes no pre-emptive PASS claim.

Deferred: atomic amount+profile transaction PR2c/D-01, added-line profile lifecycle PR2d/D-13, OPEX recurrence D-09. Backend, engine, schemas, flags and CI workflows/selectors/budgets are unchanged. Production/staging acceptance is not claimed.

# D-029 Legacy and React client contract (implemented)

## Wire contract

Request: the existing Run form plus `run_intent_id` (UUIDv4). Typed outcome transport:

* `Accept: application/json` -> JSON `{ok, outcome, run_intent_id, history_id, runtime_snapshot_id, error_code, message}`
  (React; a followed 303 would lose headers). Status: COMMITTED/REPLAYED 200, IN_PROGRESS/FAILED/CONFLICT/EXPIRED/
  HISTORY_UNAVAILABLE/REFUSED 409, INVALID 422, UNAVAILABLE 503.
* HTMX: `X-Finco-Run-Outcome` (+ `X-Finco-Run-Intent`, `-History-Id`, `-Snapshot-Id`); REPLAYED adds `HX-Refresh: true`.
  Responses produced after the atomic commit are stamped COMMITTED so a rendering failure never reads as FAILED.
* Plain form post: released redirect contract, typed headers added.

## React (`frontend/src/app/runIntent.ts`, `api.ts::runModel`, `workflow/WorkflowBar.tsx`)

* One UUIDv4 (CSPRNG; `randomUUID` or `getRandomValues`, never `Math.random`) per deliberate Run.
* Persisted per project in `localStorage` (fallback memory): `{id, contentHash, workbookVersion, createdAt}` only; 24 h TTL,
  at most 20 records, corrupt/expired records dropped. No CSRF token, cookie or result is ever stored.
* Ambiguous outcome (lost connection, IN_PROGRESS, EXPIRED, UNAVAILABLE, opaque error) keeps the intent. The primary Run
  action stays locked (released behaviour); a separate **Resume last Run** re-sends the SAME id with the ORIGINAL hash and
  version, with a fresh Run CSRF token. It is allowed with unsaved edits because it can only replay or refuse.
* Success needs the typed COMMITTED/REPLAYED outcome AND the exact `history_id` + `runtime_snapshot_id` present in the
  persisted Run History. The old history-count heuristic is removed.
* FAILED / CONFLICT / INVALID / REFUSED / pre-ledger rejections consume the intent; HISTORY_UNAVAILABLE consumes it and
  locks until reload. Synchronous single-flight guard and navigation protection are unchanged.

## Legacy (`static/js/workbook_v2.js`, `_v2_run_controls.html` unchanged)

* The id is minted when the user presses Run (also when the Run is queued behind pending field saves), bound to the hash
  and version actually transmitted at dispatch, and re-sent unchanged by queued `htmx.ajax`, by retries after a lost
  response, after an OOB refresh of the run controls (which re-renders the form with newer hidden values) and after reload.
* The control reads "Resume Run" while a transmitted intent is unresolved. Typed terminal outcome (or any definitive
  answer below 5xx without a typed header) consumes it; 5xx/lost keeps it. A queued Run that never reached the server
  (save failed) is discarded.
* Run CSRF (`run_csrf_token`) is unchanged and fetched fresh from the rendered form; it is not stored.

Missing-key external callers keep the released non-idempotent behaviour. Real Chromium coverage:
`tests/model_d029_run_intent_browser_acceptance.py` (4 React + 3 Legacy checks).

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.

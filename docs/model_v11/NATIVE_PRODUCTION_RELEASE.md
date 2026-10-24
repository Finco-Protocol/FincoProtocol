# Native Run acceleration — permanent production release (V10 Stage 1+2 + V11 Stage 3)

The engine content is unchanged by the release: the 8 approved V11 protected blobs, the V10 Stage 1/Stage 2 kernels,
their manifests and the canonical fallback are exactly the approved content. The release adds only the activation
(`app/runtime/native_activation.py`), the release transaction (`tools/native_release.py`,
`deploy/scripts/release_native.sh`) and the production unit line that loads the activation file.

There is no pilot, canary, staged rollout or separate activation step: the approved deployment of the merged commit
runs the release transaction once, and from the restart onwards every eligible production Model Run is served by the
verified kernels, permanently (restarts included), until a kill switch or `remove` is used.

## What runs where

| Run entry point | Executor | Native |
| --- | --- | --- |
| `POST /v2/workbook/run` (Workbook Run, CAS commit, Run History, statements, Integrity) | worker process | **yes** |
| V2 sensitivity points (`app/v2/router.py` `_run_points`) | worker process | **yes** |
| V2 sensitivity matrix (`app/v2/sensitivity_matrix_router.py`) | worker process | **yes** |
| Goal seek (`app/services/goal_seek.py`) | worker process | **yes** |
| `POST /api/v1/run` (`app/api/router.py`) | worker process | **yes** |
| `POST /api/v1/model/references/{key}/run` (`app/api/v1/model_router.py`) | worker process (sync) | **yes** |
| Save & Run, Compare, legacy `/run` (`app/services/*_service.py`), `main_web` exports, lender case, covenant views, V2 section render | thread in the web server | no — canonical |

Thread-executed Runs stay canonical on purpose: native code never runs inside the web server process. Every Run with
the executor in `thread` mode (development, tests) is canonical. Every call the kernels do not admit is served by the
canonical Python engine in the same Run (a counted decline), so values, exceptions, fingerprints, statements,
provenance and persistence are exactly those of the canonical Run.

Combined behaviour: Stage 3 evaluates each admitted senior-debt model end to end (tax, solve, SHL fixed point). Every
evaluation it declines runs the canonical path exactly as without Stage 3, including the V10 Stage 1/Stage 2
candidate. On the four reference verticals V10 then serves the remaining Stage 2 SHL calls. Identities stay independent:
Stage 1 `ced5b63a…`, Stage 2 `1471f6d8…` and Stage 3 `9b96a831…` are pinned by their own committed manifests. Nothing is resealed.

## Settings

Production does not put these in `.env`. The release transaction writes `/opt/finco_protocol/.env.native`
(git-ignored, no secrets), and `deploy/systemd/finco-web.service` loads it after `.env`:

```
FINCO_NATIVE_V10_RUN=stage1+2
FINCO_NATIVE_V10_RUN_BUILD_ID=<Stage 1 build ID of fk_v10_manifest.json>
FINCO_NATIVE_V11_RUN=on
FINCO_NATIVE_V11_RUN_BUILD_ID=<build ID of fk_v11_stage3_manifest.json>
```

Settings are read once per Run, when it is submitted, and bound to that Run as immutable configurations. Any invalid
value means `off`. The staging unit, CI workflows, tests and development never load `.env.native`.
`deploy/env.example` keeps both settings `off`. `FINCO_APP_MODE=pilot` is unchanged.

## Release procedure (part of the approved deployment, after the approved normal merge)

Merging does **not** update the production host: no workflow deploys. The deployment of the merged commit is:

1. Update the checkout on the host to the merged `main` commit and install the declared dependencies into `.venv`.
2. Install the unit:
   `sudo install -m 0644 deploy/systemd/finco-web.service /etc/systemd/system/ && sudo systemctl daemon-reload`.
3. Run the release transaction as the deploy user: `deploy/scripts/release_native.sh install`. It does all of this,
   in order:
   - builds the three kernels offline with the reviewed build scripts;
   - requires every identity field (artifact SHA-256, build ID, ABI, source SHA-256, sealed approved blobs, compiler,
     flags, target, variant) to equal the committed manifests;
   - installs the shared objects atomically;
   - verifies them in a fresh interpreter through the production loaders, including runtime, ABI, build-ID pins and
     source authentication;
   - runs an exact replay self-test: canonical vs V10 Stage 1+2 vs combined must be byte-identical and served natively;
   - checks that the installed unit loads `.env.native`;
   - only then writes `.env.native` atomically.

   Any failure removes all kernels and the activation file and exits non-zero. A failed or partial deployment is never
   reported as an activation. Re-running the transaction is idempotent.
4. Restart: `sudo systemctl restart finco-web`, then run `deploy/scripts/healthcheck.sh`.
5. Re-check: `deploy/scripts/release_native.sh verify` (kernels, self-test, unit and exact activation file). Native
   service is visible per Run in the journal: `journalctl -u finco-web | grep -E 'native_v1[01] run outcome'` shows
   the models served, the declines by reason and the build ID.

Requirements: Linux x86_64, CPython 3.12/3.13 and the reviewed compiler `gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`.
On any other toolchain the transaction refuses (identity mismatch) and every Run stays canonical.

## Rollback

- **Immediate, no restart:** `touch /var/lib/finco/native_v11_run.disabled` stops Stage 3 for every new Run (V10 stays
  as configured); `touch /var/lib/finco/native_v10_run.disabled` makes every new Run fully canonical (V10 and V11).
  Remove the file to resume.
- **Permanent:** `deploy/scripts/release_native.sh remove`, then restart. This deletes the kernels and the activation
  file.
- **Code rollback:** revert the merge normally. The canonical engine is unchanged, so canonical results are unaffected.

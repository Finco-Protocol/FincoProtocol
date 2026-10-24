# V10 native Run activation — operator runbook

Status: implemented, **default OFF** in code. Production enablement (V10 Stage 1+2 together with V11 Stage 3) is the
release transaction described in `docs/model_v11/NATIVE_PRODUCTION_RELEASE.md`. It is governed by the Financial Owner
release-authority record `docs/model_v11/v11-stage3-release-authority.json` and never by an `.env` edit.

## What is activated

| Scope | Setting | Served natively (exact replay) |
|---|---|---|
| Stage 1 | `FINCO_NATIVE_V10_RUN=stage1` | senior debt DSCR solve, authoritative finalisation, tax evaluations inside them |
| Stage 1 + 2 | `FINCO_NATIVE_V10_RUN=stage1+2` | Stage 1 plus the shareholder-loan (SHL) schedules |

Both use the existing run-local `NativeConfig(mode="candidate")` boundary of `financial_engine.native_v10`: every
admission, loader, ABI, build-ID and canonical-source authentication check is unchanged, and every call the kernels do
not admit is served by canonical Python (counted as a decline with its reason). There is no second engine, no tolerance
and no result comparison at runtime: the kernels replay the canonical computation exactly.

Activated Run paths (all execute in the isolated **model worker process**):

- `POST /v2/workbook/run` (the V2 Model Run) and its V2 sensitivity points;
- `POST /api/v1/run` of the API service (`main_api.py` → `app/api/router.py`);
- goal seek (`app/services/goal_seek.py`) and the V2 sensitivity matrix.

Native code never runs in the web server process: Runs executed in a thread (legacy `/run`, Save & Run and Compare
service paths, `main_web` exports / lender case / covenant views) and every Run while the executor is in its dev/test
`thread` mode stay canonical Python.

Save / Run / History / Compare / Export contracts, CAS, source fingerprints, statements and financial authority are
unchanged: the activated Run returns exactly the canonical Run's value (or raises exactly its exception).

## Deploy (before starting `finco-web`)

1. Host requirements for the reviewed kernels: Linux x86_64, CPython 3.12 or 3.13 in `/opt/finco_protocol/.venv`, and the
   reviewed compiler `gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`. Any other compiler produces a different binary,
   which the release step refuses (and the loader would refuse too); Runs then stay canonical.
2. As the deploy user: `deploy/scripts/build_native_v10.sh install`. It builds both kernels offline, requires every
   identity field of the reviewed manifests (`fk_v10_manifest.json`, `fk_v10_stage2_manifest.json`: artifact SHA-256,
   build ID, ABI, source SHA-256, sealed approved-blob manifest, compiler, flags, target), installs only the two shared
   objects atomically and verifies them through the production loaders. Exit status non-zero = nothing installed.
   Reviewed identities: Stage 1 build `ced5b63a…a8434` (SHA-256 `da763e0e…07`), Stage 2 build `1471f6d8…85e15`
   (SHA-256 `34dc14a9…`).
3. Optional pin: `FINCO_NATIVE_V10_RUN_BUILD_ID=<Stage 1 build_id>` - any other binary declines (`BUILD_ID_PIN_MISMATCH`).

Kernels are never compiled during a Run, and the service tree is read-only at runtime (`ProtectSystem=strict`).

## Enable (after the Financial Owner release decision)

Set `FINCO_NATIVE_V10_RUN=stage1+2` (or `stage1`) in `/opt/finco_protocol/.env` and restart `finco-web`.
Logger `finco.native_v10.run` writes one line per activated Run (`native_calls`, `declined_calls`, `build`, `wall_s`,
`declines`) and warns once if the kernels are unavailable.

## Rollback (immediate, independent of native availability)

- **Immediate, no restart:** `touch /var/lib/finco/native_v10_run.disabled` (path: `FINCO_NATIVE_V10_KILL_SWITCH_FILE`).
  Every new Run is canonical Python while the file exists. Remove it to resume.
- **Persistent:** `FINCO_NATIVE_V10_RUN=off` + restart.
- **Remove binaries:** `deploy/scripts/build_native_v10.sh remove` (every native call then declines to canonical).

A Run already executing finishes with the configuration it started with (a Run's mode is immutable).

# FINCO46 operator checklist (live acceptance after an approved merge)

Scope: what an authorised operator verifies on the production host **after** the owner approves the FINCO45B+C merge
and deployment. Nothing here is run by CI or by an agent; no private key, cookie, `.env` value or tenant data is ever
copied into evidence. Record outputs as redacted text (hashes, counts, statuses).

## 1. Code and process identity
- [ ] `git -C /opt/finco_protocol rev-parse HEAD HEAD^{tree}` equals the merged commit/tree.
- [ ] `systemctl show finco-web -p EnvironmentFiles` lists `.env` and `/opt/finco_protocol/.env.native`.
- [ ] Worker count: `FINCO_WEB_WORKERS` (default 2); `ps` shows that many uvicorn workers.
- [ ] Process environment names only (never values): `tr '\0' '\n' < /proc/<pid>/environ | cut -d= -f1 | sort`.

## 2. Native release profile (FINCO45C: default `stage3`)
- [ ] `deploy/scripts/release_native.sh verify --profile stage3` exits 0 (a bare `install` now writes `stage3`;
      `full` = V10 Stage 1+2 + V11 is only an explicit `--profile full` / `FINCO_NATIVE_RELEASE_PROFILE=full`).
- [ ] `.env.native` is byte-identical to the reviewed `stage3` text (verify does this); `FINCO_NATIVE_V10_RUN=off`.
- [ ] Pinned build ID equals `fk_v11_stage3_manifest.json` (`9b96a831…`); `/proc/<pid>/maps` shows the V11 `.so`
      only after a native Run.
- [ ] Native counters: one synthetic Solar and one Wind Run; the Run log/status reports `native_models > 0` for V11 and
      no V10 calls. OFF/ON digest of the same synthetic Run is identical (`tools/native_status.py`).
- [ ] Rollback drill (no restart): `touch /var/lib/finco/native_v11_run.disabled` → next Run canonical; remove the file.
      Full rollback: `release_native.sh remove` + restart.

## 3. Smoke (FINCO45C: script matches the real route contract)
- [ ] `deploy/scripts/smoke_test.sh https://<host>` → all checks pass (`/public-health` 200, `/readyz` 200, `/health`
      401 anonymous, `/login` 200, `/` 200 with a demo cookie and never an admin cookie, security headers).
- [ ] Optional authenticated health: `FINCO_SMOKE_SESSION_COOKIE=<value> smoke_test.sh …` (value is never printed;
      unset the variable afterwards).

## 4. Shared rate limiter (FINCO45C C1)
- [ ] `ls -l <FINCO_DB_PATH>.ratelimit*` exists, mode 0600, owned by the service user; size stays small.
- [ ] From one client: 5 wrong logins → 6th is 429 with `Retry-After`, across workers (repeat a few times so the
      requests land on different workers). Do this with a throwaway account name; then wait out the lockout.
- [ ] nginx forwards the real client: `X-Forwarded-For` spoofing from the client does not reset the lockout.

## 5. Signed Run certificates (C1-Q-12)
- [ ] Public verification only: fetch a certificate's public key / verify endpoint and confirm `VALID` for a fresh
      synthetic Run; never export or print the private Ed25519 key. Record key fingerprint (public) only.

## 6. Product defaults (FINCO45B)
- [ ] New Solar and Wind project → stored `date_authority_version = OD-TIME-01/v1`; Data Center / EV unchanged.
      Existing projects unchanged (no migration). Rollback for new creations: `FINCO_NEW_PROJECT_DATE_AUTHORITY=legacy`.
- [ ] G10 Last-Run OPEX panel visible (rollback `FINCO_G10_RUN_OPEX_PANEL=0`); Save-All CAPEX profile available
      (rollback `FINCO_SAVE_ALL_PROFILE_ENABLED=0`).
- [ ] Synthetic Run → Statements / History / institutional XLSX (values only, no formulas) consistent.

## 7. Acquisition snapshot binding and demo lifecycle
- [ ] Acquisition source-Run digest binding: a synthetic acquisition case shows its bound source Run calendar
      (`DATED_CONTRACTUAL` for new dated projects) and refuses a mismatched digest.
- [ ] Demo lifecycle: demo projects created by an anonymous session are owner-scoped; no global cleanup is run.

## 8. Not covered here (owner decisions)
OD-TAX-01, OD-INVEST-01, OD-NODEBT-01, R04 settlement policy / tariff hard cap, named admin identities (C1-Q-01),
BESS / acquisition financial activation, quarterly 3/3, FX.

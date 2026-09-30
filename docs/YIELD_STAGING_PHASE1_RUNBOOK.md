# FINCO Yield — Staging Phase 1 Runbook

## Scope

Target: `https://staging.finco.one`

Accepted application baseline:

`cf65370f6fb46fc8a3facae5b9f34077b36651b8`

This baseline contains merged PR #148 (Yield), PR #152 (secure runtime) and PR #151
(institutional trust pack). PR #153 is a separate OPEN/DRAFT Radar stream and MUST NOT be
included in this staging release.

Phase 1 is browser/manual acceptance of the already-merged Yield V1 product. It is NOT a
production deployment and it MUST NOT touch `app.finco.one`.

Required flags:

```text
FINCO_YIELD_ENABLED=1
FINCO_YIELD_EXECUTION_ENABLED=0
```

Execution remains disabled. No funded wallet, signing, broadcast, custody, auto-invest or
real-money transfer is permitted.

## Release provenance

If this staging-configuration PR is used before merge, the deployed Git SHA is the reviewed
staging-config commit whose parent is the accepted application baseline above. The staging
preflight requires `FINCO_DEPLOY_SHA` to equal the checked-out exact Git HEAD.

Before deployment record:

```bash
git -C /opt/finco_staging rev-parse HEAD
```

The result MUST equal `FINCO_DEPLOY_SHA` from `/opt/finco_staging/.env.staging`.

Do not deploy historical PR #44 as-is. Its isolation design is only a reference; this runbook
uses the current PR #152 secure launcher and current runtime variables.

## 1. Host isolation

Use a dedicated service identity and filesystem:

```text
service user/group: finco-staging
repository root:   /opt/finco_staging
env file:          /opt/finco_staging/.env.staging
loopback port:     8100
runtime dir:       /run/finco-staging
nginx logs:        /var/log/nginx/finco-staging.*.log
```

Never point any staging DB or storage variable at `/opt/finco_protocol`, `/var/lib/finco`
production state, or any other production database.

Provision writable staging directories owned by `finco-staging`:

```bash
sudo install -d -o finco-staging -g finco-staging -m 0750 \
  /opt/finco_staging/storage \
  /opt/finco_staging/data \
  /opt/finco_staging/exports
```

## 2. Checkout exact reviewed release

Fetch the repository and check out the exact reviewed staging release SHA. Do not deploy a
floating branch name.

Example:

```bash
cd /opt/finco_staging
git fetch --all --prune
git checkout --detach <REVIEWED_STAGING_CONFIG_SHA>
git rev-parse HEAD
```

The commit must descend directly from the accepted application baseline or be the reviewed
merge of this staging-config PR with no unrelated application changes.

## 3. Python environment

Create/update the staging-only virtual environment from repository-declared dependencies:

```bash
cd /opt/finco_staging
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
```

Do not share the production virtualenv.

## 4. Private staging environment

Copy `deploy/staging.env.example` OUTSIDE version control to:

`/opt/finco_staging/.env.staging`

Populate real staging-only values. Required security rules:

- `FINCO_APP_MODE=pilot`
- unique non-placeholder `FINCO_SECRET_KEY`
- unique non-placeholder `FINCO_CSRF_SECRET`
- unique staging admin user
- exactly one of `FINCO_ADMIN_PASSWORD` or `FINCO_ADMIN_PASSWORD_HASH`
- `FINCO_COOKIE_SECURE=true`
- `FINCO_COOKIE_SAMESITE=lax` or `strict`
- `FINCO_WEB_HOST=127.0.0.1`
- `FINCO_WEB_PORT=8100`
- `FINCO_DEPLOY_SHA=<exact checked-out SHA>`
- staging-only database/storage paths
- `FINCO_YIELD_ENABLED=1`
- `FINCO_YIELD_EXECUTION_ENABLED=0`

Then:

```bash
sudo chown finco-staging:finco-staging /opt/finco_staging/.env.staging
sudo chmod 600 /opt/finco_staging/.env.staging
```

Never print populated secrets in shell history, logs, PR comments or acceptance evidence.

## 5. Preflight

Run the same fail-closed preflight systemd will run:

```bash
sudo -u finco-staging /opt/finco_staging/.venv/bin/python \
  /opt/finco_staging/tools/staging_preflight.py \
  --env-file /opt/finco_staging/.env.staging \
  --repo-root /opt/finco_staging
```

Required result:

`YIELD_STAGING_PREFLIGHT_PASS`

Do not start the service on any blocked result.

## 6. systemd

Install the reviewed staging unit only:

```bash
sudo cp /opt/finco_staging/deploy/systemd/finco-staging.service \
  /etc/systemd/system/finco-staging.service
sudo systemctl daemon-reload
sudo systemctl enable finco-staging.service
sudo systemctl restart finco-staging.service
```

Do not modify or restart the production `finco-web.service` as part of this task.

Inspect status without dumping the private env file:

```bash
sudo systemctl status finco-staging.service --no-pager
sudo journalctl -u finco-staging.service -n 100 --no-pager
```

## 7. Bounded readiness

A fresh staging DB may take roughly 70 seconds while canonical reference Last Runs are seeded.
Treat the process as starting, not crashed, while it remains alive inside the bounded gate.

Use a 180-second readiness window:

```bash
for i in $(seq 1 36); do
  if curl -fsS http://127.0.0.1:8100/public-health >/dev/null; then
    echo PUBLIC_HEALTH_PASS
    break
  fi
  sleep 5
done
```

If the process exits or `/public-health` never becomes healthy within the accepted window,
stop and investigate before exposing the vhost.

## 8. Nginx / TLS

Install only the staging vhost:

```bash
sudo cp /opt/finco_staging/deploy/nginx/staging.conf \
  /etc/nginx/sites-available/finco-staging.conf
sudo ln -sfn /etc/nginx/sites-available/finco-staging.conf \
  /etc/nginx/sites-enabled/finco-staging.conf
sudo nginx -t
sudo systemctl reload nginx
```

The vhost proxies only `staging.finco.one` to loopback `127.0.0.1:8100` and uses separate
staging logs. Obtain/renew the TLS certificate for `staging.finco.one` using the host's normal
certificate-management procedure before enabling HTTPS if it is not already present.

Do not reuse the production hostname or production certificate path.

## 9. Browser/manual acceptance

Verify at least:

- `/public-health` -> 200
- home
- Model
- Radar
- R-LIVE
- Crypto/RWA
- public API docs/schema surfaces that current main intentionally exposes
- Docs
- Roadmap
- Verified/trust surfaces
- login/session behaviour

Yield Phase 1:

- Yield navigation/entry
- `/yield` Explore
- at least one opportunity detail
- `/yield/compare` using real bundled opportunity UIDs
- `/{uid}/evidence.json`
- `/{uid}/history.json` (typed `HISTORY_NOT_CONFIGURED` is acceptable if no reviewed staging
  history source is configured; do not fabricate history)
- `/yield/monitor` read-only wallet context

Verify desktop and, where browser tooling permits, 390 px mobile layout.

Expected safety semantics:

```text
PRIVATE_KEY_ACCESS = ZERO
SERVER_SIDE_SIGNING = NO
AUTOMATIC_TRANSACTION_BROADCAST = NO
CUSTODY = NO
FINCO_OWNED_VAULT = NO
REAL_MONEY_TRANSFER = NO
AUTO_INVEST = NO
AUTO_REBALANCE = NO
```

Execution controls must remain unavailable because
`FINCO_YIELD_EXECUTION_ENABLED=0`. Direct ERC-4626 remains non-signable
`UNPROTECTED_PREVIEW_ONLY` where that contract applies.

## 10. Feature-flag OFF control

After the normal Phase 1 checks, prove isolation on staging only:

1. set `FINCO_YIELD_ENABLED=0` in `/opt/finco_staging/.env.staging`;
2. restart **only** `finco-staging.service`;
3. verify Yield is hidden/disabled according to the current product contract;
4. restore `FINCO_YIELD_ENABLED=1`;
5. verify `FINCO_YIELD_EXECUTION_ENABLED=0` is still unchanged;
6. restart only staging and re-run `/public-health` plus Yield Explore.

Never change code merely to make this toggle test pass.

## 11. Stop conditions

STOP Phase 1 and do not enable execution if any of these occurs:

- staging points to production DB/storage;
- deployed SHA is not the reviewed SHA;
- secure `pilot` mode fails;
- secret/admin credential validation fails;
- `FINCO_YIELD_EXECUTION_ENABLED` is not `0`;
- private-key input/signing/broadcast appears;
- reference data is presented as an executable quote without authority;
- provider failure crashes the page or leaks a stack trace/secret;
- app.finco.one is modified by this workflow.

Phase 2 execution-planning acceptance is a separate user-approved workflow.

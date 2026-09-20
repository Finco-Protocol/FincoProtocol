# P7 — FINCO Model Corporate Staging Runbook

## Scope

P7 creates and proves a **separate FINCO Model staging deployment**. It does not
cut over production, does not change `app.finco.one`, and does not include FINCO
Radar runtime work.

P7 is complete only after all four sections below are closed:

1. **P7.1 — staging isolation/deploy contract** (repository deliverables)
2. **P7.2 — actual staging deployment** (infrastructure)
3. **P7.3 — browser acceptance and isolation evidence**
4. **P7.4 — independent review and merge**

P8 load/security testing starts only after P7 is complete.

---

## P7.1 — Staging isolation/deploy contract

Canonical staging identity:

- hostname: `staging.finco.one`
- application root: `/opt/finco_staging`
- service account: `finco-staging`
- env file: `/opt/finco_staging/.env.staging`
- SQLite DB: `/opt/finco_staging/storage/finco_staging.db`
- staging storage root: `/opt/finco_staging/storage/exports`
- application bind: `127.0.0.1:8100`
- systemd unit: `finco-staging.service`
- Nginx logs: `finco-staging.access.log` / `finco-staging.error.log`

Production remains separate:

- production domain: `app.finco.one`
- production root: `/opt/finco_protocol`
- production bind: `127.0.0.1:8000`
- production service: `finco-web.service`

`tools/staging_preflight.py` is the fail-closed startup authority. It blocks a
staging start if environment identity, paths, secrets, port, or checked-out git
SHA do not satisfy the staging contract.

### P7.1 acceptance

- staging systemd unit is separate from production;
- staging Nginx vhost is separate from production;
- staging DB/storage live below `/opt/finco_staging`;
- real staging secrets are external to git and mode `0600`;
- `FINCO_DEPLOY_SHA` pins the exact deployed commit;
- `FINCO_COOKIE_SECURE=true`;
- production deploy files remain unchanged;
- `tests/test_p7_staging_isolation.py` passes;
- full pytest, public-safety scan and compile pass.

---

## P7.2 — Actual staging deployment

This section is an infrastructure operation and must be executed on the staging
host. Do not run these commands on production.

### Host preparation

Create a dedicated OS user and directories:

```bash
sudo useradd --system --create-home --home-dir /opt/finco_staging --shell /usr/sbin/nologin finco-staging
sudo mkdir -p /opt/finco_staging/storage/exports
sudo chown -R finco-staging:finco-staging /opt/finco_staging
```

Checkout the exact independently approved corporate repository SHA into
`/opt/finco_staging`. Do not deploy a floating `main` reference.

Create the venv and install from the constrained dependency set:

```bash
cd /opt/finco_staging
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -c constraints.txt -e .
```

Create the real env file from `deploy/staging.env.example`:

```bash
cp deploy/staging.env.example /opt/finco_staging/.env.staging
chmod 600 /opt/finco_staging/.env.staging
chown finco-staging:finco-staging /opt/finco_staging/.env.staging
```

Replace every placeholder. In particular:

- generate a new staging-only `FINCO_SECRET_KEY`;
- generate a new staging-only admin password;
- set `FINCO_DEPLOY_SHA` to the exact checked-out 40-char commit SHA;
- never copy production credentials or the production DB.

Create/verify the staging DB and canonical references using the existing P6
bootstrap authority. Use `tools/demo_reset.py --full-bootstrap` only after the
P6 double opt-in (`FINCO_ENV=staging`, `FINCO_DEMO_RESET_ALLOWED=true`) is
present in the staging env.

Run the staging preflight as the staging service account:

```bash
sudo -u finco-staging /opt/finco_staging/.venv/bin/python \
  /opt/finco_staging/tools/staging_preflight.py \
  --env-file /opt/finco_staging/.env.staging \
  --repo-root /opt/finco_staging
```

Required token:

`P7_STAGING_PREFLIGHT_PASS`

Install the staging systemd unit:

```bash
sudo cp deploy/systemd/finco-staging.service /etc/systemd/system/finco-staging.service
sudo systemctl daemon-reload
sudo systemctl enable --now finco-staging
sudo systemctl status finco-staging --no-pager
```

The service must listen only on `127.0.0.1:8100`.

### Nginx / TLS

Provision DNS and a staging-only TLS certificate for `staging.finco.one`, then:

```bash
sudo cp deploy/nginx/staging.conf /etc/nginx/sites-available/finco-staging.conf
sudo ln -s /etc/nginx/sites-available/finco-staging.conf /etc/nginx/sites-enabled/finco-staging.conf
sudo nginx -t
sudo systemctl reload nginx
```

Do not replace, disable, edit, or reload a modified production
`app.finco.one` configuration as part of P7.

### P7.2 evidence to retain

Record without secret values:

- exact deployed git SHA;
- `systemctl status finco-staging` result;
- loopback listener evidence for `127.0.0.1:8100`;
- staging DB path and file owner/mode;
- staging env file owner/mode (not contents);
- Nginx `server_name` and proxy target;
- TLS hostname/certificate subject;
- `/public-health` and `/readyz` HTTP status/body;
- proof production service/domain was not modified.

---

## P7.3 — Browser acceptance

Use a normal browser against `https://staging.finco.one`.

Required acceptance flow:

1. landing/library page loads over HTTPS;
2. unauthenticated demo session receives a unique demo session;
3. all three synthetic canonical references are visible;
4. create a working copy from one canonical reference;
5. edit model inputs;
6. save a scenario;
7. execute a model run;
8. verify runtime results render successfully;
9. verify CSV/XLSX export paths work for the owning session;
10. verify a second isolated browser session cannot access the first session's
    project/scenario/export IDs;
11. verify `/public-health` returns 200 without model execution;
12. verify `/readyz` reports staging readiness;
13. verify admin login works with staging-only credentials;
14. verify staging cookies are Secure/HttpOnly and production cookies are not
    accepted by staging;
15. verify the staging run creates data only in the staging DB.

Capture only sanitized evidence: status codes, route names, synthetic project
identifiers and timestamps. Never capture session cookies or secret values.

### P7.3 production-isolation proof

Before and after browser acceptance record:

- production DB checksum/mtime or other agreed non-secret sentinel;
- production service status;
- staging DB checksum/mtime;
- staging service status.

The expected result is staging mutation with no production mutation.

---

## P7.4 — Independent review / closure

Independent review must verify:

- exact base and P7 HEAD;
- P7.1 repository diff;
- no FINCO financial-engine formula changes;
- no FINCO Radar changes;
- staging/production service, port, DB, storage and secret separation;
- exact deployed SHA provenance;
- P7.2 infrastructure evidence;
- P7.3 browser acceptance evidence;
- full pytest / safety / compile green;
- no production cutover.

P7 closes only with an explicit review token and post-merge verification.

Until then:

`P7_CORPORATE_STAGING_NOT_CLOSED`

P8 must not start.

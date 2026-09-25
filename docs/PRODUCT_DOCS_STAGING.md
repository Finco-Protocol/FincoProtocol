# FINCO Product Docs — Staging Deployment & Acceptance

This runbook applies only to the product-documentation PR built from branch
`docs/product-documentation-staging`.

## Safety boundary

- Staging only. Do **not** restart or modify the production `finco-web.service`.
- Do **not** modify production DB, storage, secrets, nginx vhost, or `app.finco.one`.
- Deploy only to a positively identified isolated FINCO staging runtime.
- Do not infer the staging hostname or systemd unit name from historical documentation. Confirm the active staging runtime before any restart.
- Pin the staging deployment to the exact reviewed PR HEAD SHA.

## Route contract for this PR

The web app currently reserves `/docs` for FastAPI Swagger. To avoid shadowing or breaking that route during staging review:

- Product documentation: `GET /docs/start`
- API overview: `GET /api`
- Stable API docs alias: `GET /api/docs` → `307 /docs`
- Stable OpenAPI alias: `GET /api/openapi.json` → `307 /openapi.json`

A later route-foundation change may move Swagger behind `/api/docs` directly and promote the product landing page from `/docs/start` to `/docs`. That migration is **not** part of this PR.

## Pre-deploy checks

1. Record current staging commit SHA and keep it as the rollback target.
2. Confirm the runtime is staging, not production.
3. Confirm staging root, environment file, port and hostname match the active staging deployment contract.
4. Confirm the target checkout is clean before switching to the reviewed PR SHA.
5. Run the repository's staging preflight against the active staging environment before restart.

## Required code gates

Run at the exact PR HEAD:

```bash
python -m compileall -q app tests
python tools/public_safety_scan.py
pytest -q tests/test_protocol_docs.py tests/test_protocol_docs_aliases.py tests/test_protocol_api_beta.py tests/test_chrome_cleanup.py
```

The normal GitHub PR workflow suite must also be green before staging sign-off.

## Staging browser acceptance

### Desktop

1. Open the staging home page and confirm existing navigation remains intact.
2. Open **Docs** from the protocol navigation.
3. Confirm `/docs/start` returns HTTP 200 and renders:
   - Start here
   - Product map
   - FINCO Model
   - Key outputs
   - FINCO Radar
   - Evidence & verification
   - FINCO API Beta
   - Shared concepts
   - Status & limitations
4. Confirm Roadmap and `$FINCO` remain disabled placeholders.
5. Confirm Verify has not been reintroduced into primary product navigation.
6. Open Model and confirm the brand bar Docs link returns to `/docs/start`.
7. Confirm Model, Radar and API links from the Docs page navigate normally.
8. Confirm `/api/docs` redirects to the current Swagger surface.
9. Confirm `/api/openapi.json` redirects to the current OpenAPI schema.
10. Confirm the existing `/docs` Swagger page still renders during this transitional PR.

### 390 px mobile

At a 390 px viewport:

- no page-level horizontal overflow;
- protocol navigation remains usable;
- task cards stack correctly;
- documentation tables scroll inside their own containers rather than widening the page;
- Docs is a usable live navigation item;
- Roadmap / `$FINCO` placeholder behavior remains consistent with existing responsive chrome.

## Regression smoke

At minimum verify HTTP behavior for:

- `/`
- `/library`
- `/radar`
- `/api`
- `/docs/start`
- `/docs`
- `/openapi.json`

No Model calculation, Radar authority, API v1 behavior, wallet, token, or on-chain capability is changed by this PR.

## Rollback

If Docs rendering, navigation, or route separation fails:

1. restore the previously recorded staging SHA;
2. restart only the verified staging service;
3. verify the staging home page and core routes return to their prior state;
4. preserve logs/screenshots for the PR correction pass.

Production is outside this runbook.

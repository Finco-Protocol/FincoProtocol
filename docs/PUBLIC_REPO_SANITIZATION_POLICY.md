# Public Repository Sanitization Policy

## Objective

No public FINCO Protocol source, history, documentation, fixture, artifact, screenshot, database, or generated output may disclose private project lineage or create an unnecessary link to a historical client, project, employer, workbook, account, person, or development environment.

## Removal scope

Before import, remove or replace:

- historical saved projects and project databases
- scenarios, runs, exports, workspace state, generated workbooks, screenshots, logs, caches and temporary artifacts
- real project, SPV, company, employer, lender, fund, client and counterparty names
- personal names, usernames, email addresses, account identifiers and local machine paths
- proprietary workbook names, source-file names and internal project codes
- country/jurisdiction identifiers where they disclose source-project lineage
- source-specific comments, docstrings, test names, fixture names, constants, functions, classes, routes and filenames
- secrets, tokens, passwords, connection strings, bucket names, internal hosts and infrastructure identifiers
- copied third-party source without a documented compatible licence

## Synthetic reference models

The public application must use only fully synthetic reference models:

1. Generic Solar Reference
2. Generic Wind Reference
3. Generic Storage Reference

Synthetic models must not be simple renames or small numerical perturbations of historical projects. Capacity, dates, CAPEX, OPEX, production, revenue, financing, tax, reserve and return assumptions must form new internally coherent datasets.

Geography must use generic market identifiers unless a jurisdiction is intentionally introduced later as a public product preset from public-source rules.

## Git policy

- Do not fork, mirror or import the historical repository.
- Do not import historical `.git` objects, branches or PR metadata.
- Corporate history starts from sanitized source only.
- Historical branches remain in the private legacy archive.

## Pre-import gates

A source batch may enter the corporate repository only after:

- text identifier scan
- secret scan
- email and absolute-path scan
- binary/artifact inventory
- provenance/licence review
- saved-data and database check
- reference-model synthetic-data review
- regression tests

## Public-readiness rule

A reviewer unfamiliar with the historical codebase should not be able to infer a private source project, client, employer, workbook or individual from the public repository.

Acceptance token:

`FINCO_PUBLIC_SOURCE_SANITIZATION_PROVEN`

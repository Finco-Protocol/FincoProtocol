# Contributing to FINCO Protocol

FINCO Protocol is developed with a fail-closed public-safety and evidence discipline. Contributions should preserve that standard.

## Development flow

1. branch from the current `main` HEAD;
2. keep the change narrowly scoped;
3. add or update focused tests for changed behavior;
4. run the repository-wide public-release verification gate locally where practical;
5. open a pull request with the exact scope, evidence, and known limitations;
6. resolve review findings before merge.

Direct changes to `main` are not part of the intended development workflow.

## Required public-safety boundary

Do not commit:

- client or counterparty names;
- real project identifiers or project-specific workbooks;
- private emails, credentials, API keys, wallet keys, or secrets;
- production databases or saved user workspaces;
- private calibration evidence or source files;
- screenshots or exports that expose non-public data;
- proprietary third-party material without permission.

Use synthetic fixtures and generic identifiers for public tests and examples.

## Product-surface boundaries

FINCO Model, FINCO Radar, and future protocol/on-chain functionality have distinct authority boundaries.

A change to one surface should not silently alter another. Pull requests should explicitly state whether they modify:

- `financial_engine/`;
- `finco_core/`;
- FINCO Model application code;
- `finco_radar/`;
- deployment/runtime infrastructure;
- future token, wallet, custody, signing, or smart-contract functionality.

If a directory is intentionally unchanged, call that out when the distinction is material to review.

## Verification

Before requesting review, install dependencies using the repository constraints and run the applicable focused tests and, where practical:

```bash
pip install -r requirements.txt -c constraints.txt
python -m pip check
python tools/public_safety_scan.py
python -m compileall -q .
pytest -q
```

These commands repeat the verification procedure; they do not guarantee a bit-for-bit identical environment. See `docs/VERIFICATION.md` for the public-release verification contract and evidence limitations.

## Review expectations

Changes affecting financial authority, market-data authority, evidence semantics, sanitization controls, or security boundaries should receive independent review focused on correctness rather than style alone.

Reviewers should check:

- whether the claimed authority matches the code path;
- whether unsupported states fail closed;
- whether regression tests prove the intended semantics;
- whether public-release evidence is repeatable and accurately attributed;
- whether the change crosses a product-surface boundary unexpectedly;
- whether any real/private information entered the sanitized repository.

## Pull-request evidence

A strong pull request description includes:

- canonical base SHA;
- exact head SHA;
- actual tested SHA when CI executes a synthetic merge ref or other derived state;
- files and product surfaces changed;
- tests executed and results;
- generated evidence artifacts, when applicable;
- explicit non-goals;
- independent-review findings and resolutions for material authority changes.

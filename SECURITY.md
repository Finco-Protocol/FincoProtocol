# Security Policy

FINCO Protocol treats security, public-repository hygiene, and evidence integrity as release requirements.

## Supported code

Security fixes target the current `main` branch and active release/deployment candidates. Historical commits and abandoned development branches are not supported as production surfaces.

## Reporting a vulnerability

Do not publish exploit details, secrets, private data, credentials, wallet material, or a working proof of compromise in a public issue.

For a potentially sensitive vulnerability:

1. use GitHub's private vulnerability reporting / Security Advisory flow for this repository when available;
2. otherwise contact the repository maintainers privately before disclosing technical details publicly;
3. include the affected commit, component, reproduction conditions, impact, and the smallest safe proof needed to validate the issue.

Non-sensitive hardening suggestions may be opened as normal GitHub issues.

## High-priority classes

Reports are especially useful when they involve:

- authentication or session isolation;
- secrets, credentials, or private-data exposure;
- path traversal or unsafe file handling;
- command, template, SQL, or other injection;
- unsafe deserialization;
- authorization boundary failures;
- financial state-authority corruption or silent fallback behavior;
- market-data or evidence-provenance spoofing;
- dependency or supply-chain compromise;
- future wallet, signing, custody, token, or smart-contract surfaces when those components exist.

## Public repository boundary

The repository is intentionally sanitized. Client data, project-specific workbooks, production databases, private calibration evidence, credentials, keys, and proprietary source artifacts must not be committed.

The public CI gate includes a repository safety scan. A passing scan is one control, not a guarantee that every security issue has been eliminated.

## Scope note

FINCO Model currently does not require wallet signing, custody, swaps, approvals, or private keys. Planned token/protocol functionality described in roadmap material is not represented as a currently deployed smart-contract system unless separately documented.

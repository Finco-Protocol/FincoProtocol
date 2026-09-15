# Security Policy

FINCO Protocol treats security, public-repository hygiene, and evidence integrity as release requirements.

## Supported code

Security fixes target the current `main` branch and active release/deployment candidates. Historical commits and abandoned development branches are not supported as production surfaces.

## Reporting a vulnerability

Do not publish exploit details, secrets, private data, credentials, wallet material, or a working proof of compromise in a public issue.

The repository is currently private/staged for controlled public release. Before public release, maintainers must enable a canonical private vulnerability-reporting route, with GitHub Private Vulnerability Reporting / Security Advisories as the preferred mechanism. This document must not be interpreted as advertising a private fallback channel that has not been configured and verified.

Once private vulnerability reporting is enabled, a sensitive report should include the affected commit, component, reproduction conditions, impact, and the smallest safe proof needed to validate the issue.

Until a private reporting route is explicitly available, do not place sensitive technical details in a public issue. Non-sensitive hardening suggestions may be opened as normal GitHub issues.

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

## Public-release repository boundary

The repository is intentionally sanitized for controlled public release. Client data, project-specific workbooks, production databases, private calibration evidence, credentials, keys, and proprietary source artifacts must not be committed.

The release CI gate includes a configured repository safety scan. A passing scan is one automated control, not a guarantee that every security, confidentiality, provenance, or sanitization issue has been eliminated.

## Scope note

FINCO Model currently does not require wallet signing, custody, swaps, approvals, or private keys. Planned token/protocol functionality described in roadmap material is not represented as a currently deployed smart-contract system unless separately documented.

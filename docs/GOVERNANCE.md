# Repository Governance and Security Automation

This document defines the intended repository controls for FINCO Protocol and distinguishes controls that are active in-repository from hosting-plan controls that must be enabled in GitHub settings.

## Active repository controls

The repository is designed around pull-request review, exact-SHA evidence, deterministic CI gates, dependency monitoring, and explicit authority boundaries.

Active or staged controls include:

- `Public Safety and Model Smoke` for dependency consistency, configured public-release safety scanning, compilation, regression tests, and retained JUnit evidence;
- `Dependency Security Audit` for a resolved-environment vulnerability audit using a pinned `pip-audit` release;
- Dependabot weekly checks for Python dependencies and GitHub Actions;
- full-SHA pins for GitHub Actions used by security-sensitive workflows;
- `CODEOWNERS` for critical repository surfaces;
- pull-request evidence fields for base SHA, head SHA, and actual tested SHA when GitHub executes a synthetic PR merge commit;
- independent review before merging changes that affect financial authority, market-data authority, evidence semantics, sanitization, or security boundaries.

Automated controls are evidence-producing checks, not substitutes for human security, provenance, financial-model, or release review.

## Target `main` protection

When the hosting plan supports branch protection or repository rulesets for this repository's visibility, `main` should be configured with the following minimum controls:

1. Require a pull request before merging.
2. Require successful status checks before merging:
   - `safety-and-smoke`
   - `dependency-audit`
3. Require branches to be up to date before merging when practical.
4. Require all review conversations to be resolved.
5. Block force pushes.
6. Block branch deletion.
7. Do not permit routine bypass of the ruleset.

For a single-maintainer repository, a mandatory approving GitHub review can create a self-approval deadlock. Until a second authorized human reviewer exists, external independent review should be recorded in the PR evidence and the required GitHub approval count may remain zero. Once a second authorized reviewer is available, the target policy is at least one approving review and, where practical, code-owner review for critical surfaces.

## Private-repository plan boundary

GitHub plan capabilities can differ between private and public repositories. If private-repository branch protection/rulesets are unavailable on the current organization plan, the repository should retain the controls above as the documented target and enable them before or at the transition to public visibility, or after upgrading to a plan that supports them for private repositories.

The absence of hosting-enforced branch protection must never be described as if it were active.

## Dependency update policy

Dependabot is configured to check:

- Python dependencies under the `pip` ecosystem;
- GitHub Actions dependencies.

Minor and patch updates are grouped to reduce PR noise. Dependency PRs remain subject to the same CI and review discipline as other changes.

`requirements.txt` expresses supported lower bounds while `constraints.txt` pins the core CI dependency set. An automated update is a proposal, not authority to broaden or replace the tested dependency set without review.

## Dependency vulnerability audit

`Dependency Security Audit` installs the application dependency set using `requirements.txt` together with `constraints.txt`, captures the resolved environment, and audits that exact resolved set with `pip-audit`.

The audit fails when known vulnerabilities are reported or dependency collection fails. Its JSON result and resolved dependency list are uploaded as retention-limited GitHub Actions artifacts.

A successful audit means that the selected vulnerability service did not report a known vulnerability for the audited resolved dependency set at that run time. It is not proof that the software is vulnerability-free.

## CodeQL / code scanning

CodeQL should be enabled when GitHub Code Security/code-scanning entitlement is available for the repository's current visibility. It is intentionally not represented as active until a successful CodeQL run and result upload can be verified.

If the repository becomes public, CodeQL should be reconsidered immediately because GitHub makes code scanning broadly available for public repositories.

## Pre-public-release governance gate

Before changing repository visibility to public, verify all of the following:

- current `main` passes `Public Safety and Model Smoke`;
- current `main` passes `Dependency Security Audit`;
- Dependabot configuration is active;
- branch/ruleset protection for `main` is enabled if available for the hosting plan;
- a canonical private vulnerability-reporting route is enabled and tested;
- current public-safety/provenance review is complete;
- no documentation claims a hosting control that is not actually enabled.

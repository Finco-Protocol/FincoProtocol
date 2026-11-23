"""V9-P2a / OD-R exact-content governance SUCCESSOR - recognition of the Financial Owner's exact-content decision. Not a release.

Chain: RC-3/M7 -> F3/WF-04/WF-07/PPA-01 -> RC-7B (PR #320) -> RC-7C (main ``5996453b``, integrated unchanged in main ``96e58164``)
-> OD-R V9-P2a (PR #332): exactly SIX protected financial paths. Four blobs are new content the Financial Owner accepted after the
independent financial review of the Correction F final candidate ``2764f21a``; two (orchestrator, shl/production) are the blobs
already accepted for the earlier OD-R candidate and carried unchanged.

``odr_violations`` is ``[]`` only while ALL of these Git facts hold for the evaluated ref (every uncertainty rejects):

1. the immutable checkpoints (RC-7C main, its #333 integration with exactly two parents, the reviewed candidate ``2764f21a``) exist and
   are ancestors; RC-7C is still recognised at both RC-7C checkpoints, so the historical state stays identifiable, never relabelled;
2. each of the six paths is its predecessor blob at both RC-7C checkpoints and EXACTLY the approved blob at the reviewed candidate and
   at the evaluated ref; the other nine of the twelve RC-7C paths are still their exact RC-7C blobs;
3. the protected-namespace diff from the RC-7C integration main is exactly the six paths: no other ``financial_engine/``,
   ``finco_core/`` or ``domain/`` path may differ;
4. the application provenance blob is exact; every pin-carrying historical authority module is byte-identical to RC-7C main; the
   current-authority wiring module ``quarterly_candidate_recognition`` is exactly the reviewed successor blob;
5. release stays closed: M7/Revenue/Junior and quarterly flags are literal ``False`` and the OD-R selector default in the approved
   policy blob is the canonical interpretation (no product path selects OD-R).

Recognition grants the six paths their place in the current-authority wiring ONLY. It never makes a path a released engine authority
or an approved frozen path and never rewrites a historical pin. States stay apart: exact content recognised (computed); Financial
Owner exact-content decision (recorded provenance, conveyed in the Stage 2 session, not authenticated here); merge authorisation,
product activation and financial release (constant ``False`` - nothing in the repository can switch them on).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RC7C_MAIN = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"            # main after PR #325 (RC-7C)
RC7C_INTEGRATION_MAIN = "96e5816478306e240a5872662eae449647921595"  # normal merge of PR #333; financial authority unchanged
RC7C_INTEGRATION_PARENTS = (RC7C_MAIN, "78b2882859b65ee7569d5de5c925c66d4bb2bfee")
REVIEWED_CANDIDATE = "2764f21a552328a7816e7f987ad8bcf36d0c322e"     # Correction F final candidate (independent financial review)
POLICY = "OD_R_FINAL_STATE_SHL_MATURITY_V1"
ODR_SUCCESSOR = "ODR_V9P2A_EXACT_CONTENT_SUCCESSOR"

# Blobs at both RC-7C checkpoints (``None`` = new file).
PREDECESSOR_BLOBS = {
    "financial_engine/financing/generic_product_policy.py": "59a2c1f868b4c12718a22919c3114f3af5af5120",
    "financial_engine/financing/project.py": "2e18a6e7c8ddfd85929d9b1906f91dd8858d0044",
    "financial_engine/orchestrator.py": "b6dc102ea18be4d40adc4a7ad08f187af17c5076",
    "financial_engine/shareholder_waterfall/model.py": "e3473e1a2064c8310e41b434da2b0aff9d5753b8",
    "financial_engine/shl/maturity_authority.py": None,
    "financial_engine/shl/production.py": "744b384cfa1652588817e77b8f1c04f8a36fc75f",
}
# The four blobs accepted by the Financial Owner's exact-content decision (Stage 2) and the two carried, previously accepted blobs.
APPROVED_NEW_BLOBS = {
    "financial_engine/financing/generic_product_policy.py": "b7df63cd5be886d5971213c03f9bfff046913ae1",
    "financial_engine/financing/project.py": "3bc6c097b218d27be216cdd86133f2772a82ad70",
    "financial_engine/shareholder_waterfall/model.py": "9520b09b135c7fe39d3d4fac6a0c2462b7c1c4ca",
    "financial_engine/shl/maturity_authority.py": "b5fc2715cf4fb769878eb0534c95eb150479328f",
}
PRESERVED_BLOBS = {
    "financial_engine/orchestrator.py": "85c8008f2b4a656fd28eea1169689b19131576e4",
    "financial_engine/shl/production.py": "9bb852c235a988bff994c4327b3b63dd6d77ae20",
}
ODR_AUTHORITIES = {**APPROVED_NEW_BLOBS, **PRESERVED_BLOBS}
# Superseded candidate blobs (Correction A / earlier) - never acceptable.
SUPERSEDED_BLOBS = {
    "financial_engine/financing/generic_product_policy.py": "293d896ac474f47ea74a93ac5ac5d7a587f1446b",
    "financial_engine/financing/project.py": "16ab1921b539ec3ed42d55554b1392ce781e6ce5",
    "financial_engine/shareholder_waterfall/model.py": "6ab84043c0267832125a073a3a881e1e86ac0e3d",
    "financial_engine/shl/maturity_authority.py": "8383eb2d735f310a09d9f080134a314efb276ba6",
}
# Non-protected application provenance change (OD-R metadata only): (RC-7C blob, approved blob).
APPLICATION_BLOBS = {
    "app/services/production_financial_authority.py": (
        "173991ca8107169672bbf977fe2fad91af520e9c", "89083cd41a4de029ae3c57ee0a4f4a871c7863bd"),
}
# Pin-carrying historical authority modules: byte-identical to RC-7C main, never rewritten.
HISTORICAL_AUTHORITY_MODULES = (
    "tests/model_v2_governance.py", "tests/m7_rc3_candidate_successor.py", "tests/ppa01_candidate_authority.py",
    "tests/rc7b_quarterly_candidate_authority.py", "tests/rc7b_postmerge_successor.py", "tests/rc7c_candidate_successor.py",
    "tests/radar_authority_governance.py", "tests/finance_integrity_governance.py", "tests/rc3_authority_states.py",
)
# Current-authority wiring changed by this successor: (RC-7C blob, exact reviewed successor blob).
WIRING_BLOBS = {
    "tests/quarterly_candidate_recognition.py": ("634581992b24e0d8149cb42daff9a7942b160fae", "5ebee89a4e38fa671234931e451ea7168f481153"),
}
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")
QUARTERLY_FLAG = ("app/workbook/quarterly_frequency_config.py", "ACTIVATION_ENABLED")
POLICY_PATH = "financial_engine/financing/generic_product_policy.py"
SELECTOR_DEFAULT = "shl_maturity_authority: str = SHL_MATURITY_POLICY_CANONICAL"

_CACHE: dict = {}


def _git(*args: str, repo=None):
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo or ROOT), capture_output=True, text=True, encoding="utf-8", timeout=60)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def blob(path: str, ref: str = "HEAD", *, repo=None):
    return _git("rev-parse", "--verify", "--end-of-options", f"{ref}:{path}", repo=repo)


def _commit(value: str, root):
    return _git("rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}", repo=root)


def odr_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` carries exactly the owner-accepted OD-R successor on the exact historical chain."""
    root = repo or ROOT
    head = _commit(ref, root)
    if head is None:
        return ["ODR_REF_UNAVAILABLE"]
    key = (str(root), head, tuple(sorted(ODR_AUTHORITIES.items())), tuple(sorted(WIRING_BLOBS.items())))
    if key in _CACHE:
        return list(_CACHE[key])
    bad: list[str] = []
    try:
        # 1. authentic chain
        for checkpoint in (RC7C_MAIN, RC7C_INTEGRATION_MAIN, REVIEWED_CANDIDATE):
            if _commit(checkpoint, root) != checkpoint:
                bad.append(f"ODR_CHECKPOINT_MISSING: {checkpoint}")
            elif _git("merge-base", "--is-ancestor", checkpoint, head, repo=root) is None:
                bad.append(f"ODR_ANCESTRY_INVALID: {checkpoint}")
        if bad:
            _CACHE[key] = tuple(bad)
            return bad
        parents = _git("show", "-s", "--format=%P", RC7C_INTEGRATION_MAIN, repo=root)
        if parents is None or tuple(parents.split()) != RC7C_INTEGRATION_PARENTS:
            bad.append("ODR_INTEGRATION_LINEAGE_INVALID")
        # 2. exact blobs
        if set(ODR_AUTHORITIES) != set(PREDECESSOR_BLOBS) or len(ODR_AUTHORITIES) != 6:
            bad.append("ODR_MANIFEST_PATHS_INVALID")
        for path, before in PREDECESSOR_BLOBS.items():
            if blob(path, RC7C_MAIN, repo=root) != before or blob(path, RC7C_INTEGRATION_MAIN, repo=root) != before:
                bad.append(f"ODR_PREDECESSOR_BLOB_MISMATCH: {path}")
            expected = ODR_AUTHORITIES.get(path)
            if not expected or blob(path, REVIEWED_CANDIDATE, repo=root) != expected:
                bad.append(f"ODR_MANIFEST_NOT_REVIEWED_CONTENT: {path}")
            if blob(path, head, repo=root) != expected:
                bad.append(f"ODR_BLOB_MISMATCH: {path}")
        try:
            from tests.rc7c_candidate_successor import RC7C_CANDIDATE_AUTHORITIES
        except ModuleNotFoundError:
            from rc7c_candidate_successor import RC7C_CANDIDATE_AUTHORITIES
        for path, pin in RC7C_CANDIDATE_AUTHORITIES.items():
            if path not in ODR_AUTHORITIES and blob(path, head, repo=root) != pin:
                bad.append(f"ODR_RC7C_BLOB_CHANGED: {path}")
        # 3. protected scope
        unchanged = _git("diff", "--name-only", "--no-renames", RC7C_MAIN, RC7C_INTEGRATION_MAIN, "--", *PROTECTED_PREFIXES, repo=root)
        if unchanged != "":
            bad.append("ODR_INTEGRATION_FINANCIAL_PREDECESSOR_CHANGED")
        changed = _git("diff", "--name-only", "--no-renames", RC7C_INTEGRATION_MAIN, head, "--", *PROTECTED_PREFIXES, repo=root)
        if changed is None or set(changed.splitlines()) != set(ODR_AUTHORITIES):
            bad.append(f"ODR_PROTECTED_SCOPE_INVALID: {sorted((changed or '').splitlines())}")
        # 4. application provenance, historical authorities, wiring
        for path, (before, after) in APPLICATION_BLOBS.items():
            if blob(path, RC7C_INTEGRATION_MAIN, repo=root) != before or blob(path, head, repo=root) != after:
                bad.append(f"ODR_APPLICATION_BLOB_MISMATCH: {path}")
        for path in HISTORICAL_AUTHORITY_MODULES:
            historical = blob(path, RC7C_MAIN, repo=root)
            if historical is None or blob(path, head, repo=root) != historical:
                bad.append(f"ODR_HISTORICAL_GUARD_CHANGED: {path}")
        for path, (before, after) in WIRING_BLOBS.items():
            if blob(path, RC7C_MAIN, repo=root) != before or blob(path, head, repo=root) != after:
                bad.append(f"ODR_WIRING_NOT_EXACT: {path}")
        # 5. release closed
        if SELECTOR_DEFAULT not in (_git("show", f"{head}:{POLICY_PATH}", repo=root) or ""):
            bad.append("ODR_SELECTOR_DEFAULT_NOT_CANONICAL")
        if not bad:
            try:
                from tests.rc7c_candidate_successor import rc7c_violations
                from tests.rc3_authority_states import release_closed_violations
                from tests.test_rc2_integration_manifest import activation_state
            except ModuleNotFoundError:
                from rc7c_candidate_successor import rc7c_violations
                from rc3_authority_states import release_closed_violations
                from test_rc2_integration_manifest import activation_state
            for checkpoint in (RC7C_MAIN, RC7C_INTEGRATION_MAIN):
                if rc7c_violations(repo=root, ref=checkpoint):
                    bad.append(f"ODR_HISTORICAL_RC7C_INVALID: {checkpoint}")
            if release_closed_violations(repo=root, ref=head):
                bad.append("ODR_ACTIVATION_NOT_CLOSED")
            flag_source = _git("show", f"{head}:{QUARTERLY_FLAG[0]}", repo=root)
            if flag_source is None or activation_state(flag_source + "\n", QUARTERLY_FLAG[1]) != "CLOSED":
                bad.append("ODR_QUARTERLY_ACTIVATION_NOT_CLOSED")
    except Exception as exc:                                    # noqa: BLE001 - fail closed
        bad.append(f"ODR_FACTS_UNAVAILABLE: {exc!r}")
    _CACHE[key] = tuple(bad)
    return bad


def odr_recognized(*, repo=None, ref: str = "HEAD") -> bool:
    return odr_violations(repo=repo, ref=ref) == []


def odr_candidate_authorities() -> dict:
    """Effective protected content map of the recognised state: the RC-7C twelve with the OD-R replacements plus the new OD-R paths."""
    try:
        from tests.rc7c_candidate_successor import RC7C_CANDIDATE_AUTHORITIES
    except ModuleNotFoundError:
        from rc7c_candidate_successor import RC7C_CANDIDATE_AUTHORITIES
    return {**RC7C_CANDIDATE_AUTHORITIES, **ODR_AUTHORITIES}


def historical_subject(*, repo=None, ref: str = "HEAD") -> str:
    """The ref the historical RC-7C contract is judged at: ``ref`` itself, or - only while ``ref`` is the recognised OD-R successor - its
    immutable RC-7C integration checkpoint. Never a relabelling: RC-7C stays judged on RC-7C bytes."""
    return RC7C_INTEGRATION_MAIN if odr_recognized(repo=repo, ref=ref) else ref


def states(*, repo=None, ref: str = "HEAD") -> dict:
    recognised = odr_recognized(repo=repo, ref=ref)
    return {
        "exact_odr_content_recognized": recognised,
        "historical_rc7c_checkpoints_verified": recognised,
        # Recorded provenance only: the exact-content decision was conveyed by the Financial Owner in the Stage 2 session.
        "financial_owner_exact_content_decision": "RECORDED_NOT_AUTHENTICATED" if recognised else None,
        "authenticated_owner_attestation": False,
        "merge_authorized": False,
        "product_activation": False,
        "od_r_default_policy": False,
        "financial_release": False,
    }

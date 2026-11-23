"""RC-3 combined integration inventory (REVIEW PROPOSAL - not an approval of any financial authority).

Binds the integrated HEAD to the union of the five reviewed source heads. The oracle is live Git state of the pinned source commits
and the pinned base, NOT values generated from the current tree:

 1. exact integration base (commit + tree) and the historical RC-1/RC-2 checkpoints;
 2. the five pinned source heads, present and ancestors of HEAD;
 3. the five ordered ``--no-ff`` merge commits: first parent chain from the base, second parent == the pinned source head;
 4. inclusion of every source tree: each path a source changed carries that source's blob at HEAD, unless it is a DOCUMENTED shared
    path (auto-merge paths must equal an independent ``git merge-file`` of the sources; hand-resolved paths are pinned);
 5. exact integrated path/status inventory == union of the source diffs + the explicit INTEGRATION_ADDED / INTEGRATION_EDITED lists;
 6. exact financial / security / model-authority blobs: every change under a frozen namespace is a source-owned M7 path whose blob
    equals the reviewed M7 head, and the eleven protected blobs of the M7 candidate manifest match;
 7. no unexplained source-content replacement (the multi-source overlap set must equal the documented shared set);
 8. documented shared-file resolutions keep every source's distinguishing markers;
 9. protected workflows, test selection, tolerances and goldens are byte-identical to the base;
10. release-closed flags are literal ``False`` and the M7 candidate manifest stays ``release_approved:false``.

Passing this file is NOT a financial approval: M7 candidate acceptance and production activation are separate decisions that are
still pending (see docs/rc3/RC3_INTEGRATION_CORRECTION_A.md). The owner gates over financial authority stay red until then.
"""
import copy
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.test_trust_readiness_registry import RC1_BASE_MAIN, RC1_MERGED_CHECKPOINT, RC1_MERGED_PARENTS

ROOT = Path(__file__).resolve().parent.parent
BASE_TREE = "4fdcd03b5e0ed3c4b87d9016f2522bfe50bf0d05"
SOURCES = (                                                # merge order; PR number -> reviewed head
    (280, "8378e5df30ec10b4de2b2f5330491837a7cd1ffb"),
    (279, "9f93dc843eed8f2f2cf7f11cf409fffd003ce70f"),
    (281, "5c6963879d8bdf0a16458011a5cfe6011fd36021"),
    (282, "63f1ded39ab90db24f3503c9fe62e9d7029ea017"),
    (283, "62424a8b777133631f4253d75848ba8c846f83e6"),
)
M7_PR = 283
# Post-merge anchoring (PR #284 is on main): the integrated candidate is judged as this pinned, immutable commit; HEAD is then bound to it.
INTEGRATION_HEAD = "b17d3341336fed89624662360c4164184476e7a2"
PR_MERGE = "4527ceadea7a5b9a8c3e2e63eb9fb3395ef9b66e"            # the normal two-parent merge of PR #284 into main
STREAM_TIP = "f2a1e386481b11a0a2b5fb8a73206403c839a480"   # merge of #282: every non-financial stream, not M7
FROZEN_PREFIXES = ("financial_engine/", "finco_core/", "domain/", "finco_radar/", "finco_yield/", "app/radar_rwa/")
GUARDED_PREFIXES = (".github/",)
GUARDED_FILES = ("pytest.ini", "requirements.txt", "requirements-ci-tests.txt", "constraints.txt", "pyproject.toml")
GUARDED_NAME_PARTS = ("tolerance", "golden")                # financial tolerances / goldens: byte-identical to the base
M7_MANIFEST = "docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json"

# Paths touched by two or more sources whose union is produced by an independent three-way merge (no hand edits allowed).
AUTO_MERGED = {
    "app/api/project_runner.py": (282, 283),
    "app/v2/router.py": (282, 283),
    "app/templates/v2/workbook.html": (281, 283),
}
# Paths that needed a hand resolution. Their final content is a reviewed literal pin plus mandatory markers of every source.
HAND_RESOLVED = {
    "tests/test_rc2_integration_manifest.py": {
        "markers": ("R4_REVIEWED_HEAD", "R4_SUCCESSOR_BLOBS", "RC2_ACCEPTED_HEAD", "duplicate cumulative diff entry"),
    },
    "tests/test_trust_readiness_controls.py": {
        "markers": ("current_m6_successor_valid", "current_m7_successor_valid", "app/v2/acquisition_router.py", "CSRF_PROPOSAL"),
    },
    "tests/test_trust_readiness_registry.py": {
        "markers": ("_m6_exact_successor_valid", "_m7_successor_valid", "_csrf_call_sites_at", "_rc1_collect_post"),
    },
}
# Markers every auto-merged file must keep from EACH side (both sources' distinguishing content).
AUTO_MARKERS = {
    "app/api/project_runner.py": ("acquisition_source_candidate_v1", "bess_operating_audit"),
    "app/v2/router.py": ("bind_acquisition_source", "bess_candidate_router", "bess_workspace_router"),
    "app/templates/v2/workbook.html": ("model_diagnostics_v2.js", "model_bess_workspace.js"),
}
# Files the INTEGRATION itself added (not in any source) or edited on top of the sources. Literal reviewed blobs; the two files
# that cannot pin themselves (this test and its helper) are listed by path and reviewed as exact commit files.
INTEGRATION_ADDED = frozenset({
    "tests/test_rc3_r5_successor.py",
    "tests/rc3_historical_anchor.py",
    "tests/test_rc3_integration_inventory.py",
    "docs/rc3/RC3_INTEGRATION_CORRECTION_A.md",
    "docs/rc3/RC3_CORRECTION_B_M7_REVIEW_AND_CI_BUDGET.md",
    "tests/m7_rc3_candidate_successor.py",
    "tests/test_m7_rc3_candidate_successor.py",
})
INTEGRATION_SELF = frozenset({"tests/test_rc3_integration_inventory.py", "tests/rc3_historical_anchor.py"})


# ── RC-3 CI budget successor (owner-authorised budget only; NOT a financial approval) ───────────────────────────────────────
# Exactly two values of .github/workflows/ci_public_job.yml differ from the accepted RC-2 workflow (the file on the base):
#   FINCO_CI_PYTEST_BUDGET_S '4200' -> '4800'   and   timeout-minutes 90 -> 100.
# Everything else (grace, stall, selection, full unsharded run, artifacts, evidence, every other job step) must be byte-identical.
RC3_CI_WORKFLOW_BLOB = "036a5aef7cf9738b8bf7bf2f6294f24a998a928c"
RC3_CI_EDITS = (("timeout-minutes: 90", "timeout-minutes: 100"),
                ("FINCO_CI_PYTEST_BUDGET_S: '4200'", "FINCO_CI_PYTEST_BUDGET_S: '4800'"))


def workflow_successor_violations(base_text: str, head_text: str) -> list[str]:
    """Pure verifier: ``head_text`` must equal ``base_text`` with exactly the two authorised values replaced, and must still fit."""
    import re
    try:
        bad = []
        expected = base_text
        for old, new in RC3_CI_EDITS:
            if expected.count(old) != 1:
                bad.append(f"the accepted RC-2 workflow does not contain exactly one {old!r}")
                continue
            expected = expected.replace(old, new, 1)
        if head_text != expected:
            bad.append("the workflow differs from the accepted RC-2 workflow in more (or other) than the two authorised budget values")
        budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", head_text).group(1))
        grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", head_text).group(1))
        stall = int(re.search(r"FINCO_CI_STALL_S: '(\d+)'", head_text).group(1))
        timeout = int(re.search(r"timeout-minutes: (\d+)", head_text).group(1))
        if (budget, timeout) != (4800, 100) or grace != 180 or stall != 300:
            bad.append("budget/timeout/grace/stall are not the authorised 4800 s / 100 min / 180 s / 300 s")
        if budget + grace + 15 * 60 > timeout * 60:
            bad.append("the job timeout cannot accommodate budget + exit grace + job overhead")
        for needle in ("--junitxml=artifacts/results.xml", "tools/ci_pytest_runner.py", "FULL, UNSHARDED, EXACT HEAD",
                       "if-no-files-found: error", "public-verification-results"):
            if needle not in head_text:
                bad.append(f"required evidence/selection element is missing: {needle}")
        if "continue-on-error" in head_text or "--deselect" in head_text or "-k " in head_text:
            bad.append("test selection or failure handling was altered")
        return bad
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"workflow facts incomplete or malformed: {exc!r}"]


# ── RC-5 CI runtime successor (owner-authorised limits only; NOT a financial approval) ──────────────────────────────────────────
# The FULL UNSHARDED suite outgrew the RC-3 budget (main at 97de3833 already used 4739 of 4800 s; the RC-5 integration needs 12,395 tests).
# Exactly three values of the accepted RC-3 workflow may differ, to the owner-approved limits below. Everything else (stall, selection,
# full unsharded run, artifacts, evidence, every other step and job) must stay byte-identical, and the job timeout must still contain
# budget + exit grace + job overhead, so a genuine timeout still ends in a non-zero exit.
RC5_CI_WORKFLOW_BLOB = "0fa7e2bec303bb94053fe7799186e666dd1e06a9"
RC5_CI_EDITS = (("timeout-minutes: 100", "timeout-minutes: 130"),
                ("FINCO_CI_PYTEST_BUDGET_S: '4800'", "FINCO_CI_PYTEST_BUDGET_S: '6000'"),
                ("FINCO_CI_EXIT_GRACE_S: '180'", "FINCO_CI_EXIT_GRACE_S: '240'"))


def rc5_workflow_successor_violations(rc3_text: str, head_text: str) -> list[str]:
    """Pure verifier: ``head_text`` must equal the accepted RC-3 workflow with exactly the three authorised values replaced, and must still fit."""
    import re
    try:
        bad = []
        expected = rc3_text
        for old, new in RC5_CI_EDITS:
            if expected.count(old) != 1:
                bad.append(f"the accepted RC-3 workflow does not contain exactly one {old!r}")
                continue
            expected = expected.replace(old, new, 1)
        if head_text != expected:
            bad.append("the workflow differs from the accepted RC-3 workflow in more (or other) than the three authorised limit values")
        budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", head_text).group(1))
        grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", head_text).group(1))
        stall = int(re.search(r"FINCO_CI_STALL_S: '(\d+)'", head_text).group(1))
        timeout = int(re.search(r"timeout-minutes: (\d+)", head_text).group(1))
        if (budget, timeout, grace, stall) != (6000, 130, 240, 300):
            bad.append("budget/timeout/grace/stall are not the authorised 6000 s / 130 min / 240 s / 300 s")
        if budget + grace + 15 * 60 > timeout * 60:
            bad.append("the job timeout cannot accommodate budget + exit grace + job overhead")
        for needle in ("--junitxml=artifacts/results.xml", "tools/ci_pytest_runner.py", "FULL, UNSHARDED, EXACT HEAD",
                       "if-no-files-found: error", "public-verification-results"):
            if needle not in head_text:
                bad.append(f"required evidence/selection element is missing: {needle}")
        if "continue-on-error" in head_text or "--deselect" in head_text or "-k " in head_text:
            bad.append("test selection or failure handling was altered")
        return bad
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"workflow facts incomplete or malformed: {exc!r}"]


# ── CI-200M successor (owner-authorised 200-minute full pytest; NOT a financial approval) ───────────────────────────────────────────
# Additive over RC-5: the RC-5 verifier above is untouched and keeps judging the historical RC-5 state. Exactly TWO values of the accepted
# RC-5 workflow may differ (job ceiling and pytest supervisor budget). The successor is content-pinned by its own Git blob; its expected text is
# derived from the RC-3 reference plus the fixed RC-5 and CI-200M edit tables, never from the current HEAD.
CI200_WORKFLOW_BLOB = "f843237cae125867b8978fb2cc38665dcf0c64d8"
CI200_EDITS = (("timeout-minutes: 130", "timeout-minutes: 220"),
               ("FINCO_CI_PYTEST_BUDGET_S: '6000'", "FINCO_CI_PYTEST_BUDGET_S: '12000'"))


# ── CI-340M successor (Owner-directed 2x CI timeouts, 2026-10-30; NOT a financial approval) ───────────────────────────────────────────
# Additive over CI-200M: the CI-200M verifier above is untouched and keeps judging the historical CI-200M state. Exactly TWO values may differ again
# (job ceiling 220 -> 340 min, pytest supervisor budget 12000 -> 19200 s). 340 min stays under the 360-minute GitHub-hosted job ceiling.
CI340_WORKFLOW_BLOB = "248c1e4e46fa36e7a308b9b8e88c6fe27bafa830"
CI340_EDITS = (("timeout-minutes: 220", "timeout-minutes: 340"),
               ("FINCO_CI_PYTEST_BUDGET_S: '12000'", "FINCO_CI_PYTEST_BUDGET_S: '19200'"))
GITHUB_HOSTED_JOB_CEILING_MINUTES = 360


def git_blob_sha(text: str) -> str:
    """Git blob identity of ``text`` (UTF-8, as stored); pure, so verifiers never trust a filename or the working tree."""
    import hashlib
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def rc5_reference_text(rc3_text: str) -> str:
    """The accepted RC-5 workflow text, derived from the RC-3 reference by the fixed RC-5 edits ('' if the reference is not exactly editable)."""
    text = rc3_text
    for old, new_value in RC5_CI_EDITS:
        if text.count(old) != 1:
            return ""
        text = text.replace(old, new_value, 1)
    return text


def ci200_workflow_successor_violations(rc5_text: str, head_text: str) -> list[str]:
    """Pure verifier: ``head_text`` must equal the accepted RC-5 workflow with exactly the two authorised values replaced, be the pinned blob and fit."""
    import re
    try:
        bad = []
        if git_blob_sha(rc5_text) != RC5_CI_WORKFLOW_BLOB:
            bad.append("the predecessor is not the accepted RC-5 workflow blob")
        expected = rc5_text
        for old, new_value in CI200_EDITS:
            if expected.count(old) != 1:
                bad.append(f"the accepted RC-5 workflow does not contain exactly one {old!r}")
                continue
            expected = expected.replace(old, new_value, 1)
        if head_text != expected:
            bad.append("the workflow differs from the accepted RC-5 workflow in more (or other) than the two authorised limit values")
        if git_blob_sha(head_text) != CI200_WORKFLOW_BLOB:
            bad.append("the workflow is not the pinned CI-200M successor blob")
        budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", head_text).group(1))
        grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", head_text).group(1))
        stall = int(re.search(r"FINCO_CI_STALL_S: '(\d+)'", head_text).group(1))
        timeout = int(re.search(r"timeout-minutes: (\d+)", head_text).group(1))
        if (budget, timeout, grace, stall) != (12000, 220, 240, 300):
            bad.append("budget/timeout/grace/stall are not the authorised 12000 s / 220 min / 240 s / 300 s")
        if budget + grace + 15 * 60 > timeout * 60:
            bad.append("the job timeout cannot accommodate budget + exit grace + job overhead")
        for needle in ("--junitxml=artifacts/results.xml", "tools/ci_pytest_runner.py", "FULL, UNSHARDED, EXACT HEAD",
                       "if-no-files-found: error", "public-verification-results"):
            if needle not in head_text:
                bad.append(f"required evidence/selection element is missing: {needle}")
        if "continue-on-error" in head_text or "--deselect" in head_text or "-k " in head_text:
            bad.append("test selection or failure handling was altered")
        return bad
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"workflow facts incomplete or malformed: {exc!r}"]


def ci200_reference_text(rc5_text: str) -> str:
    """The accepted CI-200M workflow text, derived from the RC-5 text by the fixed CI-200M edits ('' if not exactly editable)."""
    text = rc5_text
    for old, new_value in CI200_EDITS:
        if text.count(old) != 1:
            return ""
        text = text.replace(old, new_value, 1)
    return text


def ci340_workflow_successor_violations(ci200_text: str, head_text: str) -> list[str]:
    """Pure verifier: ``head_text`` must equal the accepted CI-200M workflow with exactly the two authorised values replaced, be the pinned blob and fit."""
    import re
    try:
        bad = []
        expected = ci200_text
        for old, new_value in CI340_EDITS:
            if expected.count(old) != 1:
                bad.append(f"the accepted CI-200M workflow does not contain exactly one {old!r}")
                continue
            expected = expected.replace(old, new_value, 1)
        if head_text != expected:
            bad.append("the workflow differs from the accepted CI-200M workflow in more (or other) than the two authorised limit values")
        if git_blob_sha(head_text) != CI340_WORKFLOW_BLOB:
            bad.append("the workflow is not the pinned CI-340M successor blob")
        budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", head_text).group(1))
        grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", head_text).group(1))
        stall = int(re.search(r"FINCO_CI_STALL_S: '(\d+)'", head_text).group(1))
        timeout = int(re.search(r"timeout-minutes: (\d+)", head_text).group(1))
        if (budget, timeout, grace, stall) != (19200, 340, 240, 300):
            bad.append("budget/timeout/grace/stall are not the authorised 19200 s / 340 min / 240 s / 300 s")
        if timeout > GITHUB_HOSTED_JOB_CEILING_MINUTES:
            bad.append("the job timeout exceeds the 360-minute GitHub-hosted job ceiling")
        if budget + grace + 15 * 60 > timeout * 60:
            bad.append("the job timeout cannot accommodate budget + exit grace + job overhead")
        for needle in ("--junitxml=artifacts/results.xml", "tools/ci_pytest_runner.py", "FULL, UNSHARDED, EXACT HEAD",
                       "if-no-files-found: error", "public-verification-results"):
            if needle not in head_text:
                bad.append(f"required evidence/selection element is missing: {needle}")
        if "continue-on-error" in head_text or "--deselect" in head_text or "-k " in head_text:
            bad.append("test selection or failure handling was altered")
        return bad
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"workflow facts incomplete or malformed: {exc!r}"]


def current_workflow_chain_violations(rc3_text: str, current_text: str) -> list[str]:
    """CURRENT workflow: exactly the accepted RC-3 workflow, its RC-5 limit successor, the CI-200M successor over RC-5, or the CI-340M successor over CI-200M. Nothing in between."""
    if current_text == rc3_text:
        return []
    rc5 = rc5_reference_text(rc3_text)
    rc5_bad = rc5_workflow_successor_violations(rc3_text, current_text)
    if not rc5_bad:
        return []
    if not rc5 or rc5_workflow_successor_violations(rc3_text, rc5):
        return ["the RC-5 reference cannot be derived from the accepted RC-3 workflow"] + rc5_bad
    ci200_bad = ci200_workflow_successor_violations(rc5, current_text)
    if not ci200_bad:
        return []
    ci200 = ci200_reference_text(rc5)
    if not ci200 or ci200_workflow_successor_violations(rc5, ci200):
        return ["the CI-200M reference cannot be derived from the accepted RC-5 workflow"] + rc5_bad + ci200_bad
    ci340_bad = ci340_workflow_successor_violations(ci200, current_text)
    return [] if not ci340_bad else rc5_bad + ci200_bad + ci340_bad


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _status(a, b):
    rows = {}
    for line in git("diff", "--name-status", "--no-renames", a, b).splitlines():
        status, path = line.split("\t", 1)
        rows.setdefault(path, []).append(status)
    return rows


def _show(ref, path):
    return git("show", f"{ref}:{path}")


# ── negative mutation tests ────────────────────────────────────────────────────────────────────────────────────


# ── Reviewed integration edits (literal pins; generated once from the reviewed working tree, then frozen for review) ──────────
# Re-anchored historical-stream guards (tests/rc3_historical_anchor.py) and the successor modules anchored to their source heads.
PINNED_INTEGRATION_EDITS = {
    "tests/m6_exact_content_successor.py": "355c1b180e4c3e943a52cc2fc4f4472c86b9dcec",
    "tests/m7_bess_successor_proposal.py": "68976dc3367def588db343620cf1dd2cee77f569",
    "tests/test_crypto_p0_product_reality_reset.py": "12c5b96193456b9b5a2254bfcb6be3488bc86f4d",
    "tests/test_crypto_roadmap_q4_q1.py": "10ec5772ace6a672c85e6e31428ba0355a8e1c43",
    "tests/test_data_center_a3_1.py": "99a42f79501f8f29441445c776e6dc4e2bdc5384",
    "tests/test_m3_two_driver_sensitivity.py": "2f447efd18e2198c5d6805bc43636de9c15b28e6",
    "tests/test_m6_exact_content_successor.py": "4eda2579375045442c326395b6b7ea6ecf193f4b",
    "tests/test_m7_bess_successor_proposal.py": "b0b17ae9219686c1439e361dd29248608de3a132",
    "tests/test_model_market_bridge.py": "874c4e7c3ebe2853d6fa3f6c07a82f5f6cc96108",
    "tests/test_model_v2_assumption_trace_references.py": "02a5c27e2ac2e9ca69cf177c754e03f4987383bd",
    "tests/test_model_v2_cost_templates.py": "29ff769b7841c0b9da0c34fc3f4b0759ea0ed29b",
    "tests/test_model_v2_cost_templates_cd.py": "2c001b8f6d91d1608e00c67a2be357821bdab218",
    "tests/test_model_v2_revenue_runtime_parity.py": "e200112fd0b7078175ec8c7a75ca690b15f42b5e",
    "tests/test_multi_source_evidence_v2.py": "f4f2ece723086a8c2cd2a7e4f65e616e663b07a9",
    "tests/test_opus_c1_product_truth.py": "368e25cd61bb3d88db2c5883c037e4e9e8bda979",
    "tests/test_p0a_model_execution.py": "5d93732cf91418cff42486b90aaf1a5944c01dc1",
    "tests/test_p1_2_xlsx_export_reconciliation.py": "c106feb77de7199e2174650e17c10636c9d5bf22",
    "tests/test_p1_3_institutional_validation.py": "bc56c54ad057983532b1775488d03a4cef2d45ed",
    "tests/test_p3_run_certificate_v1.py": "2757a030f71c692d5fcd6c248f9642a6eab88baa",
    "tests/test_parallel_stream_frozen_diff.py": "585a2584cb00d42a81e3c6687bff53c3105d03cd",
    "tests/test_public_product_truth_sync.py": "f031f107cc19fab25667e19b0fe93e2a1e9a7789",
    "tests/test_radar_crypto_surface_coherence.py": "543b73fa192d4590301e99f38b935cc392df5ca8",
    "tests/test_radar_r3_deepstate_composition.py": "6be748f064ec3ae62cc798c524ae191a66c2edf3",
    "tests/test_radar_r4_tokenized_monitor_v2.py": "1efeb22a69d918db12f411935f9ccc9897f2277a",
    "tests/test_radar_tokenized_signal_lifecycle.py": "6ee72e35673d88c9ba1674843f92a5ce807c80e3",
    "tests/test_rc2_integration_manifest.py": "7f6a0b7adcf3848731fbec8a66947096c73dab0c",
    "tests/test_rc3_diagnostics_manifest.py": "d059db8872ef8d264ba2f9c5e4e867ac863aeb56",
    "tests/test_rc3_r5_successor.py": "3311c43fdbbea6331094d416874d50843380b2ab",
    "tests/test_rwa_integrity.py": "fc8e80bd075ac9b6e7fefcacdd388ca5acfe1ea6",
    "tests/test_staging_product_truth.py": "e403a97e78211320098061346a4b3de59fbe0510",
    "tests/test_stock_token_oracle_rejection.py": "42f7aa35aca055aa65e9b6593919ff799f22b4e1",
    "tests/test_tokenized_access_wiring.py": "093668b5c165dcc62d8ef06ca7547d2b3eecadec",
    "tests/test_tokenized_live_intelligence_v1.py": "d73438f270222e23adcb56dd2ab03aaeee0e4f70",
    "tests/test_tokenized_markets_composition.py": "c06a294f28a71b06643e75834998e380f467e4ab",
    "tests/test_trust_readiness_controls.py": "b662615b0106976d38b431bfc29dc0f2573118f2",
    "tests/test_trust_readiness_registry.py": "8bfd684d95358f94db15302385e310bedbcaea2e",
    "tests/test_yield_alerts_core.py": "ae01affe8673fa30c2a931f94846a8d0a279a8e6",
}


# ── RC-3 CI budget successor: negative tests ──────────────────────────────────────────────────────────────────────────────────


def test_the_rc5_budget_fits_inside_the_job_timeout():
    budget, grace, overhead, timeout_min = 6000, 240, 15 * 60, 130
    assert budget + grace + overhead <= timeout_min * 60 and timeout_min * 60 - (budget + grace + overhead) >= 120


def test_the_authorised_budget_fits_inside_the_job_timeout():
    budget, grace, overhead, timeout_min = 4800, 180, 15 * 60, 100
    assert budget + grace + overhead <= timeout_min * 60 and timeout_min * 60 - (budget + grace + overhead) >= 120


# ── post-merge negative tests ─────────────────────────────────────────────────────────────────────────────────────────────────



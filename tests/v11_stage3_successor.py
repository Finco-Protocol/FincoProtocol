"""V11 Stage 3 (native tax + native senior-debt model evaluation) exact-content governance SUCCESSOR - recognition of the
Financial Owner's exact-content decision. Not a release, not an activation.

Chain: ... -> OD-R V9-P2a (PR #332) -> V10 Stage 1+2 dormant authoritative shadow (PR #347) -> V11 Stage 3 candidate: exactly the
approved V11 protected paths (the explicit default-off hook in ``financial_engine/financing/project.py`` and the new
``financial_engine/native_v11/`` files) on top of the V10 state as it stands at the immutable checkpoint ``main`` ``9e712e21`` (PR #355
merged, V10 recognised there).

``v11_violations`` is ``[]`` only while ALL of these Git facts hold for the evaluated ref (every uncertainty rejects):

1. the immutable checkpoint and the reviewed source candidate exist with their exact trees and are ancestors in order: V10 checkpoint ->
   reviewed V11 source candidate -> evaluated ref; V10 is still recognised AT its checkpoint (judged on its own bytes, never relabelled);
2. every V11 path is its predecessor blob (``None`` = absent) at the checkpoint and EXACTLY the approved blob at the source candidate and
   at the evaluated ref; the source candidate carries no approval record (non-circular provenance);
3. the protected-namespace diff (``financial_engine/``, ``finco_core/``, ``domain/``) from the checkpoint is exactly the V11 protected
   paths: nothing else may differ, nothing may be missing, deleted or added - in particular every approved V10 Stage 1/Stage 2 source,
   build script and manifest is byte-identical (no reseal);
4. every pin-carrying historical authority module (incl. the V10 successor, its owner record and the R-LIVE 3.10 successor) is
   byte-identical to the checkpoint; the wiring module is exactly the reviewed successor blob;
5. the Financial Owner exact-content record is byte-exact (sha256 pinned here; owner authority is this reviewed code pin, never a
   self-asserting JSON field);
6. release stays closed: ``Stage3Config`` and V10 ``NativeConfig`` default to ``off``; the validated native targets are exactly Linux
   x86_64 CPython 3.12/3.13; no application, deployment or workflow source references the Stage 3 package (there is no activation
   path); no compiled artifact is tracked; the OD-R release / quarterly / selector checks hold.

Recognition grants the V11 paths their place in the current-authority wiring ONLY. It never makes a path a released engine authority or
an approved frozen path, never rewrites a historical pin, never authorizes Stage 3 activation, production enablement, a V10 reseal,
runtime compilation, merge or deployment.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

V10_CHECKPOINT = {"head": "9e712e21b9efd1a57fe702f178a496aaefb427ec", "tree": "e8305ab124e59d62b63dad121c3e333040939f2f"}
SOURCE_CANDIDATE = {"head": "3bf206d0d4c3b0430916cd05eae552dd3b5fed77", "tree": "0d775362e0689f3b0f9a76d82341f2c620ead227"}
SUCCESSOR = "V11_STAGE3_EXACT_CONTENT_SUCCESSOR"

# Protected V11 paths: (blob at the V10 checkpoint or None, exact approved V11 blob).
PROTECTED = {
    "financial_engine/financing/project.py": ("3bc6c097b218d27be216cdd86133f2772a82ad70", "4d77988da20ec9ea767d85cc16448489d9f48bb6"),
    "financial_engine/native_v11/__init__.py": (None, "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"),
    "financial_engine/native_v11/approved_canonical_blobs_stage3.json": (None, "12c3aef94e3c4b440e25ab433fd524c99d6d6823"),
    "financial_engine/native_v11/build_stage3.py": (None, "25ff48402d46a90d6a8cf71453ab7c5df4d977fa"),
    "financial_engine/native_v11/config.py": (None, "751e020a0c06c8dfa2113c9ec82a0123892dc81b"),
    "financial_engine/native_v11/fk_v11_stage3_manifest.json": (None, "6d70d6b84ebba6ac86ba1c7f9727502e6c3aec9f"),
    "financial_engine/native_v11/kernel_v11_stage3.c": (None, "63490c990f9268db7b6dcade5fa344ce0f6fec72"),
    "financial_engine/native_v11/stage3.py": (None, "0d55acf14d685b9f72ed9666d86e8e59f0c3326f"),
}
V11_PROTECTED_BLOBS = {path: after for path, (_before, after) in PROTECTED.items()}
# Pin-carrying historical authority modules: byte-identical to the V10 checkpoint, never rewritten.
HISTORICAL_AUTHORITY_MODULES = (
    "tests/model_v2_governance.py", "tests/m7_rc3_candidate_successor.py", "tests/ppa01_candidate_authority.py",
    "tests/rc7b_quarterly_candidate_authority.py", "tests/rc7b_postmerge_successor.py", "tests/rc7c_candidate_successor.py",
    "tests/radar_authority_governance.py", "tests/finance_integrity_governance.py", "tests/rc3_authority_states.py",
    "tests/v9p2a_odr_successor.py", "tests/r_live_lifecycle_content_authority.py", "tests/r_live_lifecycle_py310_successor.py",
    "tests/v10_native_shadow_successor.py", "docs/model_v10/v10-native-shadow-content-approval.json",
)
# Current-authority wiring changed by this successor: (V10 checkpoint blob, exact reviewed V11 successor blob).
WIRING_BLOBS = {
    "tests/quarterly_candidate_recognition.py": ("d27dbceb9aa2483a33bc205652dd0e58fc976d8d", "af11c329d85ff9667bddd88d83320c045f718819"),
}
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")
APPROVAL_PATH = "docs/model_v11/v11-stage3-content-approval.json"
OWNER_APPROVAL_REFERENCE = "conversation:2026-10-24:V11-B/C:Financial-Owner-Exact-Content-Approval:Stage3a+3b"   # explicit Financial Owner exact-content decision (packet sha256 eaa2a05b)
OWNER_APPROVAL_SHA256 = "f0555f999b10359af9243494e1115387c25a3554689a8cdba9da0dab1dd470c0"
STAGE3_DEFAULT = 'mode: str = "off"'
V10_NATIVE_DEFAULTS = ('mode: str = "off"', "stage2_experimental: bool = False")
VALIDATED_TARGETS_SOURCE = ('("Linux", "x86_64", "cpython", (3, 13))', '("Linux", "x86_64", "cpython", (3, 12))')
# no activation path: these sources must never reference the Stage 3 package
ACTIVATION_SURFACES = ("app/", "main_web.py", "deploy/", ".github/", "tools/", "Dockerfile", "docker-compose.yml")

_CACHE: dict = {}


def _git(*args: str, repo=None):
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo or ROOT), capture_output=True, text=True, encoding="utf-8",
                              timeout=60)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def blob(path: str, ref: str = "HEAD", *, repo=None):
    return _git("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}:{path}", repo=repo)


def _commit(value, root):
    if not value:
        return None
    return _git("rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}", repo=root)


def _module(name: str):
    """The SAME module object the recognition hub and the tests use (plain name first, ``tests.<name>`` as fallback)."""
    import importlib
    import sys
    if name in sys.modules:
        return sys.modules[name]
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return importlib.import_module(f"tests.{name}")


def _show(ref: str, path: str, root):
    return _git("show", f"{ref}:{path}", repo=root)


def _show_bytes(ref: str, path: str, root):
    try:
        proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=str(root), capture_output=True, timeout=60)
        return proc.stdout if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _no_duplicates(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("duplicate approval key")
        out[key] = value
    return out


def expected_approval() -> dict:
    """Pinned record schema; no caller-supplied authorization or environment gate."""
    return {"schema": 1, "kind": "v11-stage3-native-senior-debt-exact-content-approval",
            "repository": "Finco-Protocol/FincoProtocol", "branch": "feat/v11-stage3-native-senior-debt",
            "v10_checkpoint": V10_CHECKPOINT, "source_candidate": SOURCE_CANDIDATE, "protected_blobs": V11_PROTECTED_BLOBS,
            "Financial": {"approved": True, "reference": OWNER_APPROVAL_REFERENCE},
            "scope": "V11-B/C-Stage3a-native-tax-and-Stage3b-native-senior-debt-exact-content-only",
            "stage3_activation_authorized": False, "production_enablement_authorized": False,
            "staging_enablement_authorized": False, "v10_reseal_authorized": False,
            "runtime_compilation_authorized": False, "merge_authorized": False, "deployment_authorized": False}


def v11_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` carries exactly the owner-accepted V11 Stage 3 successor on the exact historical chain."""
    root = repo or ROOT
    head = _commit(ref, root)
    if head is None:
        return ["V11_REF_UNAVAILABLE"]
    if not PROTECTED or SOURCE_CANDIDATE["head"] is None or any(after is None for _p, (_b, after) in WIRING_BLOBS.items()):
        return ["V11_CONTRACT_INCOMPLETE"]
    v10_at_checkpoint = tuple(_module("v10_native_shadow_successor").v10_violations(repo=root, ref=V10_CHECKPOINT["head"]))
    key = (str(root), head, OWNER_APPROVAL_SHA256, OWNER_APPROVAL_REFERENCE, tuple(sorted(WIRING_BLOBS.items())),
           tuple(sorted(PROTECTED.items())), tuple(V10_CHECKPOINT.items()), tuple(SOURCE_CANDIDATE.items()), v10_at_checkpoint)
    if key in _CACHE:
        return list(_CACHE[key])
    bad: list[str] = []
    try:
        # 1. authentic chain
        for name, anchor in (("V10_CHECKPOINT", V10_CHECKPOINT), ("SOURCE_CANDIDATE", SOURCE_CANDIDATE)):
            if _commit(anchor["head"], root) != anchor["head"] or \
                    _git("rev-parse", "--verify", anchor["head"] + "^{tree}", repo=root) != anchor["tree"]:
                bad.append(f"V11_CHECKPOINT_MISSING: {name}")
        if bad:
            _CACHE[key] = tuple(bad)
            return bad
        for older, newer in ((V10_CHECKPOINT["head"], SOURCE_CANDIDATE["head"]), (SOURCE_CANDIDATE["head"], head)):
            if _git("merge-base", "--is-ancestor", older, newer, repo=root) is None:
                bad.append(f"V11_ANCESTRY_INVALID: {older[:12]} -> {newer[:12]}")
        if v10_at_checkpoint:
            bad.append("V11_HISTORICAL_V10_INVALID")
        # 2. exact blobs
        for path, (before, after) in PROTECTED.items():
            if blob(path, V10_CHECKPOINT["head"], repo=root) != before:
                bad.append(f"V11_PREDECESSOR_BLOB_MISMATCH: {path}")
            if blob(path, SOURCE_CANDIDATE["head"], repo=root) != after:
                bad.append(f"V11_SOURCE_CANDIDATE_NOT_APPROVED_CONTENT: {path}")
            if blob(path, head, repo=root) != after:
                bad.append(f"V11_BLOB_MISMATCH: {path}")
        if blob(APPROVAL_PATH, SOURCE_CANDIDATE["head"], repo=root) is not None:
            bad.append("V11_APPROVAL_RECORD_IN_SOURCE_CANDIDATE")
        # 3. protected scope: exactly the V11 paths, nothing else (no V10 reseal)
        changed = _git("diff", "--name-only", "--no-renames", V10_CHECKPOINT["head"], head, "--", *PROTECTED_PREFIXES,
                       repo=root)
        if changed is None or set(changed.splitlines()) != set(PROTECTED):
            bad.append(f"V11_PROTECTED_SCOPE_INVALID: {sorted(set((changed or '').splitlines()) ^ set(PROTECTED))}")
        # 4. historical authorities unchanged, wiring exact
        for path in HISTORICAL_AUTHORITY_MODULES:
            historical = blob(path, V10_CHECKPOINT["head"], repo=root)
            if historical is None or blob(path, head, repo=root) != historical:
                bad.append(f"V11_HISTORICAL_GUARD_CHANGED: {path}")
        for path, (before, after) in WIRING_BLOBS.items():
            if blob(path, V10_CHECKPOINT["head"], repo=root) != before or blob(path, head, repo=root) != after:
                bad.append(f"V11_WIRING_NOT_EXACT: {path}")
        # 5. Financial Owner exact-content record
        raw = _show_bytes(head, APPROVAL_PATH, root)
        if OWNER_APPROVAL_SHA256 is None or OWNER_APPROVAL_REFERENCE is None or raw is None:
            bad.append("V11_OWNER_EXACT_CONTENT_DECISION_ABSENT")
        elif hashlib.sha256(raw).hexdigest() != OWNER_APPROVAL_SHA256:
            bad.append("V11_OWNER_RECORD_NOT_EXACT")
        elif json.loads(raw, object_pairs_hook=_no_duplicates) != expected_approval():
            bad.append("V11_OWNER_RECORD_SCHEMA_MISMATCH")
        # 6. release closed
        if STAGE3_DEFAULT not in (_show(head, "financial_engine/native_v11/config.py", root) or ""):
            bad.append("V11_STAGE3_DEFAULT_NOT_OFF")
        v10_config = _show(head, "financial_engine/native_v10/config.py", root) or ""
        if not all(text in v10_config for text in V10_NATIVE_DEFAULTS):
            bad.append("V11_V10_NATIVE_DEFAULT_NOT_OFF")
        eligibility = _show(head, "financial_engine/native_v10/eligibility.py", root) or ""
        block = eligibility.split("VALIDATED_TARGETS = frozenset({", 1)[-1].split("})", 1)[0]
        if sorted(line.split("#")[0].strip().rstrip(",") for line in block.splitlines() if line.strip()) != \
                sorted(VALIDATED_TARGETS_SOURCE):
            bad.append("V11_VALIDATED_TARGETS_WIDENED")
        surfaces = _git("grep", "-l", "-e", "native_v11", "-e", "Stage3Config", "-e", "stage3_run", head, "--",
                        *ACTIVATION_SURFACES, repo=root)
        if surfaces:
            bad.append(f"V11_STAGE3_ACTIVATION_SURFACE: {sorted(surfaces.splitlines())}")
        tracked = _git("ls-tree", "-r", "--name-only", head, "--", "financial_engine/native_v11/", "financial_engine/native_v10/",
                       repo=root)
        if tracked is None or any(p.endswith(".so") for p in tracked.splitlines()):
            bad.append("V11_COMPILED_ARTIFACT_TRACKED")
        if not bad:
            release_closed_violations = _module("rc3_authority_states").release_closed_violations
            activation_state = _module("test_rc2_integration_manifest").activation_state
            odr = _module("v9p2a_odr_successor")
            if release_closed_violations(repo=root, ref=head):
                bad.append("V11_ACTIVATION_NOT_CLOSED")
            flag_source = _show(head, odr.QUARTERLY_FLAG[0], root)
            if flag_source is None or activation_state(flag_source + "\n", odr.QUARTERLY_FLAG[1]) != "CLOSED":
                bad.append("V11_QUARTERLY_ACTIVATION_NOT_CLOSED")
            if odr.SELECTOR_DEFAULT not in (_show(head, odr.POLICY_PATH, root) or ""):
                bad.append("V11_ODR_SELECTOR_DEFAULT_NOT_CANONICAL")
    except Exception as exc:                                    # noqa: BLE001 - fail closed
        bad.append(f"V11_FACTS_UNAVAILABLE: {exc!r}")
    _CACHE[key] = tuple(bad)
    return bad


def v11_recognized(*, repo=None, ref: str = "HEAD") -> bool:
    return v11_violations(repo=repo, ref=ref) == []


def v11_candidate_authorities() -> dict:
    """Effective protected content map of the recognised V11 state: the V10 map plus the exact V11 protected blobs."""
    return {**_module("v10_native_shadow_successor").v10_candidate_authorities(), **V11_PROTECTED_BLOBS}


def historical_subject(*, repo=None, ref: str = "HEAD") -> str:
    """The ref the historical V10 contract is judged at: ``ref`` itself, or - only while ``ref`` is the recognised V11 successor - its
    immutable V10 checkpoint. Never a relabelling: V10 stays judged on V10 bytes."""
    return V10_CHECKPOINT["head"] if v11_recognized(repo=repo, ref=ref) else ref


def states(*, repo=None, ref: str = "HEAD") -> dict:
    recognised = v11_recognized(repo=repo, ref=ref)
    return {
        "exact_v11_content_recognized": recognised,
        "historical_v10_checkpoint_verified": recognised,
        "financial_owner_exact_content_decision": "RECORDED_NOT_AUTHENTICATED" if recognised else None,
        "authenticated_owner_attestation": False,
        "stage3_activation": False,
        "production_enablement": False,
        "v10_reseal": False,
        "merge_authorized": False,
        "financial_release": False,
    }

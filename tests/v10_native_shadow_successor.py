"""V10 dormant native-shadow exact-content governance SUCCESSOR - recognition of the Financial Owner's exact-content decision.
Not a release, not an activation.

Chain: RC-3/M7 -> F3/WF-04/WF-07/PPA-01 -> RC-7B (PR #320) -> RC-7C -> OD-R V9-P2a (PR #332) -> V10 Stage 1+2 dormant
authoritative shadow (PR #347): exactly the approved V10 protected paths (two changed engine files, sixteen new
``financial_engine/native_v10/`` files) plus four application files, on top of the OD-R state as it stands at the immutable
checkpoint ``main`` ``0b57031a`` (PR #346 merged, OD-R recognised).

``v10_violations`` is ``[]`` only while ALL of these Git facts hold for the evaluated ref (every uncertainty rejects):

1. the immutable checkpoints exist with their exact trees and are ancestors in order: OD-R checkpoint -> reviewed V10 source
   candidate -> evaluated ref; OD-R is still recognised AT its checkpoint (judged on its own bytes, never relabelled);
2. every V10 path is its predecessor blob (``None`` = absent) at the checkpoint and EXACTLY the approved blob at the source
   candidate and at the evaluated ref; the source candidate carries no approval record (non-circular provenance);
3. the protected-namespace diff (``financial_engine/``, ``finco_core/``, ``domain/``) from the checkpoint is exactly the V10
   protected paths: nothing else may differ, nothing may be missing, deleted or added;
4. the application files are exact; every pin-carrying historical authority module (incl. the OD-R successor itself and the
   PR #346 lifecycle authority) is byte-identical to the checkpoint; the wiring module is exactly the reviewed successor blob
   (the R-LIVE guard adapter is pinned by its own separate Python 3.10 successor, ``r_live_lifecycle_py310_successor``);
5. the Financial Owner exact-content record is byte-exact (sha256 pinned here, owner authority is this reviewed code pin,
   never a self-asserting JSON field);
6. release stays closed: the OD-R release / quarterly / selector checks hold at the evaluated ref, ``NativeConfig`` defaults to
   ``off`` with ``stage2_experimental=False``, the validated native targets are exactly Linux x86_64 CPython 3.12/3.13, no
   workflow sets ``FINCO_NATIVE_V10_SHADOW``, and no compiled artifact is tracked.

Recognition grants the V10 paths their place in the current-authority wiring ONLY. It never makes a path a released engine
authority or an approved frozen path, never rewrites a historical pin, never authorizes replace / candidate-then-canonical mode,
native activation, merge or deployment.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ODR_CHECKPOINT = {"head": "0b57031ae6949d8e7d187a1932c4451e213238f7", "tree": "608b4ae23169d2fbce084c6f63e4fd43925549b5"}
SOURCE_CANDIDATE = {"head": "f137aaccff601c2f86126e1215165a7edc81574d", "tree": "1bd953ed1967c82a76e8f7c0a84caa7347c027f1"}
SUCCESSOR = "V10_NATIVE_SHADOW_EXACT_CONTENT_SUCCESSOR"

# Protected V10 paths: (blob at the OD-R checkpoint or None, exact approved V10 blob).
PROTECTED = {
    "financial_engine/senior_debt/solver.py": ("6cf4a6cd9f149f271d4b61a60bb6b0aa70e4c9e0", "9d30525b3fc09b422c1deb38784bf49834cbac35"),
    "financial_engine/shl/production.py": ("9bb852c235a988bff994c4327b3b63dd6d77ae20", "fb563770bc87a0a8403e21e5f571ebec39840f18"),
    "financial_engine/native_v10/__init__.py": (None, "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"),
    "financial_engine/native_v10/approved_canonical_blobs.json": (None, "c24555f03783d67f6aa9f3af16b497a805710960"),
    "financial_engine/native_v10/approved_canonical_blobs_stage2.json": (None, "74c025e6e45660d6143161daa11480b94eec0ce6"),
    "financial_engine/native_v10/build.py": (None, "0fce6c25c3d37545012a49fa246a2a6a9d38c615"),
    "financial_engine/native_v10/build_stage2.py": (None, "509c18541f07db8acb9fca384069ccc767af4eb9"),
    "financial_engine/native_v10/config.py": (None, "5e7f4994583384a0ef5ec88efa798dc9c361e8b1"),
    "financial_engine/native_v10/dispatch.py": (None, "31e02b8a6c833d5dc37138cd175dfec2d3d2973a"),
    "financial_engine/native_v10/eligibility.py": (None, "9bf5683680c9f0725454bb2760049a159d00cea6"),
    "financial_engine/native_v10/fk_v10_manifest.json": (None, "af6b668048d2ba2e74685dd21251fdafe2749ea6"),
    "financial_engine/native_v10/fk_v10_stage2_manifest.json": (None, "a656d48153f870bbbe8b03c72ac8b5fb797301fc"),
    "financial_engine/native_v10/isolation.py": (None, "9e227d17d975cd09685f20e6495c3645f202b4c0"),
    "financial_engine/native_v10/kernel_v10.c": (None, "e0b5372aec22261cc4e82e8348fb6089a5d1ba77"),
    "financial_engine/native_v10/kernel_v10_stage2.c": (None, "29cb3e3874ccd3e10cbc482c10c8f83f08158584"),
    "financial_engine/native_v10/loader.py": (None, "80993fb46cf3539e9dd8018da1b5da29db9de2ba"),
    "financial_engine/native_v10/provenance.py": (None, "769f0e645b4267be05aadefb09a22f7763f3199c"),
    "financial_engine/native_v10/stage2.py": (None, "90121690f598a9eaf6944dc038e386c80bfaef9c"),
}
# Application files of the V10 content (the first is the OD-R application provenance pin).
APPLICATION = {
    "app/services/production_financial_authority.py": ("89083cd41a4de029ae3c57ee0a4f4a871c7863bd", "98c04020d03711f3683b5340fc2f89387a60553c"),
    "app/runtime/model_execution.py": ("22dd596a826a1fdfe3e7eb0e9fab6b75c75310a3", "c8c5a0dc184b8901c7cb292b0dbbd248e4cf191a"),
    "app/runtime/native_shadow.py": (None, "2351375d62878aa5c7156ee881601260a9de4114"),
    "main_web.py": ("e005ece7002ea8e07edb98f15da3d5c9c2731a8a", "9b3734417fe6cd931b7814e015ca42d5c9264f8b"),
}
V10_PROTECTED_BLOBS = {path: after for path, (_before, after) in PROTECTED.items()}
# Pin-carrying historical authority modules: byte-identical to the OD-R checkpoint, never rewritten.
HISTORICAL_AUTHORITY_MODULES = (
    "tests/model_v2_governance.py", "tests/m7_rc3_candidate_successor.py", "tests/ppa01_candidate_authority.py",
    "tests/rc7b_quarterly_candidate_authority.py", "tests/rc7b_postmerge_successor.py", "tests/rc7c_candidate_successor.py",
    "tests/radar_authority_governance.py", "tests/finance_integrity_governance.py", "tests/rc3_authority_states.py",
    "tests/v9p2a_odr_successor.py",
    "tests/r_live_lifecycle_content_authority.py",
)
# Current-authority wiring changed by this successor: (OD-R checkpoint blob, exact reviewed V10 successor blob).
WIRING_BLOBS = {
    "tests/quarterly_candidate_recognition.py": ("5ebee89a4e38fa671234931e451ea7168f481153", "d27dbceb9aa2483a33bc205652dd0e58fc976d8d"),
}
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")
APPROVAL_PATH = "docs/model_v10/v10-native-shadow-content-approval.json"
OWNER_APPROVAL_REFERENCE = "conversation:2026-10-23:PR347:Financial-Owner-Exact-Content-Approval:Decision-A"   # explicit Financial Owner exact-content decision (packet sha256 81e653c0)
OWNER_APPROVAL_SHA256 = "0eaa1d17cbb4201ef6fa94963b45f37e7530efb5925e4b906e4c081e1c79e5a5"
NATIVE_DEFAULTS = ('mode: str = "off"', "stage2_experimental: bool = False")
VALIDATED_TARGETS_SOURCE = ('("Linux", "x86_64", "cpython", (3, 13))', '("Linux", "x86_64", "cpython", (3, 12))')

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


def _commit(value: str, root):
    return _git("rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}", repo=root)


def _module(name: str):
    """The SAME module object the recognition hub and the tests use: the plain name (tests/ on sys.path) first, the package-qualified
    ``tests.<name>`` only as a fallback - mirroring ``quarterly_candidate_recognition``'s import order."""
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
    """Exact committed bytes (no decoding, no stripping)."""
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
    return {"schema": 1, "kind": "v10-native-shadow-exact-content-approval", "repository": "Finco-Protocol/FincoProtocol",
            "pull_request": 347, "odr_checkpoint": ODR_CHECKPOINT, "source_candidate": SOURCE_CANDIDATE,
            "protected_blobs": V10_PROTECTED_BLOBS,
            "application_blobs": {path: after for path, (_b, after) in APPLICATION.items()},
            "Financial": {"approved": True, "reference": OWNER_APPROVAL_REFERENCE},
            "scope": "PR347-V10-dormant-shadow-exact-content-governance-and-CI-closure-only",
            "native_replace_mode_authorized": False, "candidate_then_canonical_authorized": False,
            "native_activation_authorized": False, "runtime_compilation_authorized": False,
            "stage3_authorized": False, "merge_authorized": False, "deployment_authorized": False}


def v10_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` carries exactly the owner-accepted V10 successor on the exact historical chain."""
    root = repo or ROOT
    head = _commit(ref, root)
    if head is None:
        return ["V10_REF_UNAVAILABLE"]
    # the historical OD-R verdict at the checkpoint is part of the key (OD-R keeps its own cache), so a changed OD-R contract can never
    # leave a stale V10 recognition behind
    odr_at_checkpoint = tuple(_module("v9p2a_odr_successor").odr_violations(repo=root, ref=ODR_CHECKPOINT["head"]))
    key = (str(root), head, OWNER_APPROVAL_SHA256, OWNER_APPROVAL_REFERENCE, tuple(sorted(WIRING_BLOBS.items())),
           tuple(sorted(PROTECTED.items())), tuple(sorted(APPLICATION.items())), tuple(ODR_CHECKPOINT.items()),
           tuple(SOURCE_CANDIDATE.items()), odr_at_checkpoint)
    if key in _CACHE:
        return list(_CACHE[key])
    bad: list[str] = []
    try:
        # 1. authentic chain
        for name, anchor in (("ODR_CHECKPOINT", ODR_CHECKPOINT), ("SOURCE_CANDIDATE", SOURCE_CANDIDATE)):
            if _commit(anchor["head"], root) != anchor["head"] or \
                    _git("rev-parse", "--verify", anchor["head"] + "^{tree}", repo=root) != anchor["tree"]:
                bad.append(f"V10_CHECKPOINT_MISSING: {name}")
        if bad:
            _CACHE[key] = tuple(bad)
            return bad
        for older, newer in ((ODR_CHECKPOINT["head"], SOURCE_CANDIDATE["head"]), (SOURCE_CANDIDATE["head"], head)):
            if _git("merge-base", "--is-ancestor", older, newer, repo=root) is None:
                bad.append(f"V10_ANCESTRY_INVALID: {older[:12]} -> {newer[:12]}")
        if odr_at_checkpoint:
            bad.append("V10_HISTORICAL_ODR_INVALID")
        # 2. exact blobs
        for path, (before, after) in {**PROTECTED, **APPLICATION}.items():
            if blob(path, ODR_CHECKPOINT["head"], repo=root) != before:
                bad.append(f"V10_PREDECESSOR_BLOB_MISMATCH: {path}")
            if blob(path, SOURCE_CANDIDATE["head"], repo=root) != after:
                bad.append(f"V10_SOURCE_CANDIDATE_NOT_APPROVED_CONTENT: {path}")
            if blob(path, head, repo=root) != after:
                bad.append(f"V10_BLOB_MISMATCH: {path}")
        if blob(APPROVAL_PATH, SOURCE_CANDIDATE["head"], repo=root) is not None:
            bad.append("V10_APPROVAL_RECORD_IN_SOURCE_CANDIDATE")
        # 3. protected scope: exactly the V10 paths, nothing else
        changed = _git("diff", "--name-only", "--no-renames", ODR_CHECKPOINT["head"], head, "--", *PROTECTED_PREFIXES, repo=root)
        if changed is None or set(changed.splitlines()) != set(PROTECTED):
            bad.append(f"V10_PROTECTED_SCOPE_INVALID: {sorted(set((changed or '').splitlines()) ^ set(PROTECTED))}")
        # 4. historical authorities unchanged, wiring exact
        for path in HISTORICAL_AUTHORITY_MODULES:
            historical = blob(path, ODR_CHECKPOINT["head"], repo=root)
            if historical is None or blob(path, head, repo=root) != historical:
                bad.append(f"V10_HISTORICAL_GUARD_CHANGED: {path}")
        for path, (before, after) in WIRING_BLOBS.items():
            if after is None or blob(path, ODR_CHECKPOINT["head"], repo=root) != before or blob(path, head, repo=root) != after:
                bad.append(f"V10_WIRING_NOT_EXACT: {path}")
        # 5. Financial Owner exact-content record
        raw = _show_bytes(head, APPROVAL_PATH, root)
        if OWNER_APPROVAL_SHA256 is None or OWNER_APPROVAL_REFERENCE is None or raw is None:
            bad.append("V10_OWNER_EXACT_CONTENT_DECISION_ABSENT")
        elif hashlib.sha256(raw).hexdigest() != OWNER_APPROVAL_SHA256:
            bad.append("V10_OWNER_RECORD_NOT_EXACT")
        elif json.loads(raw, object_pairs_hook=_no_duplicates) != expected_approval():
            bad.append("V10_OWNER_RECORD_SCHEMA_MISMATCH")
        # 6. release closed
        config = _show(head, "financial_engine/native_v10/config.py", root) or ""
        if not all(text in config for text in NATIVE_DEFAULTS):
            bad.append("V10_NATIVE_DEFAULT_NOT_OFF")
        eligibility = _show(head, "financial_engine/native_v10/eligibility.py", root) or ""
        block = eligibility.split("VALIDATED_TARGETS = frozenset({", 1)[-1].split("})", 1)[0]
        if sorted(line.split("#")[0].strip().rstrip(",") for line in block.splitlines() if line.strip()) != \
                sorted(VALIDATED_TARGETS_SOURCE):
            bad.append("V10_VALIDATED_TARGETS_WIDENED")
        workflows = _git("grep", "-l", "FINCO_NATIVE_V10_SHADOW", head, "--", ".github/", repo=root)
        if workflows:
            bad.append("V10_SHADOW_ENABLED_IN_WORKFLOW")
        tracked = _git("ls-tree", "-r", "--name-only", head, "--", "financial_engine/native_v10/", repo=root)
        if tracked is None or any(p.endswith(".so") for p in tracked.splitlines()):
            bad.append("V10_COMPILED_ARTIFACT_TRACKED")
        if not bad:
            release_closed_violations = _module("rc3_authority_states").release_closed_violations
            activation_state = _module("test_rc2_integration_manifest").activation_state
            odr = _module("v9p2a_odr_successor")
            if release_closed_violations(repo=root, ref=head):
                bad.append("V10_ACTIVATION_NOT_CLOSED")
            flag_source = _show(head, odr.QUARTERLY_FLAG[0], root)
            if flag_source is None or activation_state(flag_source + "\n", odr.QUARTERLY_FLAG[1]) != "CLOSED":
                bad.append("V10_QUARTERLY_ACTIVATION_NOT_CLOSED")
            if odr.SELECTOR_DEFAULT not in (_show(head, odr.POLICY_PATH, root) or ""):
                bad.append("V10_ODR_SELECTOR_DEFAULT_NOT_CANONICAL")
    except Exception as exc:                                    # noqa: BLE001 - fail closed
        bad.append(f"V10_FACTS_UNAVAILABLE: {exc!r}")
    _CACHE[key] = tuple(bad)
    return bad


def v10_recognized(*, repo=None, ref: str = "HEAD") -> bool:
    return v10_violations(repo=repo, ref=ref) == []


def v10_candidate_authorities() -> dict:
    """Effective protected content map of the recognised V10 state: the OD-R map plus the exact V10 protected blobs."""
    return {**_module("v9p2a_odr_successor").odr_candidate_authorities(), **V10_PROTECTED_BLOBS}


def historical_subject(*, repo=None, ref: str = "HEAD") -> str:
    """The ref the historical OD-R contract is judged at: ``ref`` itself, or - only while ``ref`` is the recognised V10
    successor - its immutable OD-R checkpoint. Never a relabelling: OD-R stays judged on OD-R bytes."""
    return ODR_CHECKPOINT["head"] if v10_recognized(repo=repo, ref=ref) else ref


def states(*, repo=None, ref: str = "HEAD") -> dict:
    recognised = v10_recognized(repo=repo, ref=ref)
    return {
        "exact_v10_content_recognized": recognised,
        "historical_odr_checkpoint_verified": recognised,
        "financial_owner_exact_content_decision": "RECORDED_NOT_AUTHENTICATED" if recognised else None,
        "authenticated_owner_attestation": False,
        "native_replace_mode": False,
        "native_activation": False,
        "stage2_default_enabled": False,
        "merge_authorized": False,
        "financial_release": False,
    }

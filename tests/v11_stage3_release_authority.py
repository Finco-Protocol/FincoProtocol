"""V11 Stage 3 + V10 Stage 1+2 permanent production RELEASE authority - recognition of the Financial Owner's release decision for
the exact release content. Separate from, and on top of, the exact-content successor (``v11_stage3_successor``): the content record
(``docs/model_v11/v11-stage3-content-approval.json``) stays byte-exact and keeps saying what it said - content only, no activation.

Chain: V11 exact-content checkpoint (``94fd918e``: the approved 8 protected blobs + the content record) -> reviewed release candidate
(the activation in ``app/runtime/native_activation.py``, the release transaction ``tools/native_release.py`` +
``deploy/scripts/release_native.sh``, the production unit line and the example configuration) -> evaluated ref.

``release_violations`` is ``[]`` only while ALL of these Git facts hold for the evaluated ref (every uncertainty rejects):

1. the content checkpoint and the reviewed release candidate exist with their exact trees and are ancestors in order: content
   checkpoint -> release candidate -> evaluated ref;
2. every release-surface path is its checkpoint blob (``None`` = absent) at the content checkpoint and EXACTLY the reviewed release
   blob at the release candidate and at the evaluated ref; the release candidate carries no release record (non-circular);
3. the content record is still byte-exact (the content successor's pinned sha256) and the runtime identities named by the release
   record are exactly the committed manifests (V10 Stage 1, V10 Stage 2, V11 Stage 3: build ID + artifact SHA-256) - no reseal;
4. the Financial Owner release record is byte-exact (sha256 pinned here; owner authority is this reviewed code pin, never a
   self-asserting JSON field) and equals the pinned schema.

Recognition makes exactly the release-surface paths admissible activation surfaces for the content successor
(``released_surfaces``). It never changes an engine blob, a manifest or a historical pin, never authorizes a merge (independent
final review), runtime compilation, staging enablement, a phased rollout or a V10 reseal.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONTENT_CHECKPOINT = {"head": "94fd918e547f818cc0ca256db96f5fe1a165dc45", "tree": "7131ab3ba632ac35bd31ea0368cce99ba7e393cc"}
RELEASE_CANDIDATE = {"head": "08d8108e4f4bdbf11b340b98275d9b750f5c4196", "tree": "2d2da00db6b346eae2bc579314bd738078166415"}
SUCCESSOR = "V11_STAGE3_V10_STAGE12_PERMANENT_PRODUCTION_RELEASE"

# Release surface: (blob at the content checkpoint or None, exact reviewed release blob).
RELEASE_SURFACE = {
    "app/runtime/native_activation.py": ("eaa404bff2dfac5b774d2c1ab3e3d082c2de48c0", "75eb68bde98982317abf7501caf80a57b5e6f3cf"),
    "tools/native_release.py": (None, "2eaf84c7d9bb599693caa6f6949e75defca3f90f"),
    "deploy/scripts/release_native.sh": (None, "8421e3e308ad5f9b4a05e691a140d4fe8265e615"),
    "deploy/systemd/finco-web.service": ("23a285529b6f77148ae7efbd8d7023941b81fc92", "eea293b4a98854ad5145b4e68584d999224ba802"),
    "deploy/env.example": ("8d09ccc862d55d8c254cb99d517c1ff84cd7ac55", "78bcb2bfd24866517068b0d6eba09c23d804a4fb"),
}
RELEASE_PATH = "docs/model_v11/v11-stage3-release-authority.json"
OWNER_RELEASE_REFERENCE = None
OWNER_RELEASE_SHA256 = None

MANIFESTS = {"v10_stage1": "financial_engine/native_v10/fk_v10_manifest.json",
             "v10_stage2": "financial_engine/native_v10/fk_v10_stage2_manifest.json",
             "v11_stage3": "financial_engine/native_v11/fk_v11_stage3_manifest.json"}
RUNTIME_IDENTITIES = {
    "v10_stage1": {"build_id": "ced5b63a77b5467ba312181cda5ea158af14aa894ab6ec67f3f00a5144fa8434",
                   "artifact_sha256": "da763e0e8895359b81c6197b7252c349be9201c380aeee051dea60e5077e1307"},
    "v10_stage2": {"build_id": "1471f6d88750b150d364b61b3c80b32e315eca1c5af5a8f298d5430260785e15",
                   "artifact_sha256": "34dc14a975d6ab3020fbcd898feac877621a9b5bae6a3731edc3f00089f1922e"},
    "v11_stage3": {"build_id": "9b96a8312bd6cec7c66098370164149f0ef5f9f5265db2b9e91abce5773a7344",
                   "artifact_sha256": "eda33517ec07522e3985ccc02228b30289d4c471bbeb5745b51f8e7373817963"},
}
ACTIVATION = {"FINCO_NATIVE_V10_RUN": "stage1+2", "FINCO_NATIVE_V10_RUN_BUILD_ID": RUNTIME_IDENTITIES["v10_stage1"]["build_id"],
              "FINCO_NATIVE_V11_RUN": "on", "FINCO_NATIVE_V11_RUN_BUILD_ID": RUNTIME_IDENTITIES["v11_stage3"]["build_id"]}
RUN_SCOPE = {
    "native": ["POST /v2/workbook/run", "V2 sensitivity points", "V2 sensitivity matrix", "goal seek", "POST /api/v1/run",
               "POST /api/v1/model/references/{key}/run"],
    "canonical": ["Save & Run", "Compare", "legacy /run", "main_web exports", "lender case", "covenant views",
                  "V2 section render", "every Run while the model executor is in thread mode"],
}

_CACHE: dict = {}


def _content():
    """The SAME content-successor module object the recognition hub and the tests use (plain name first)."""
    import importlib
    import sys
    for name in ("v11_stage3_successor", "tests.v11_stage3_successor"):
        if name in sys.modules:
            return sys.modules[name]
    try:
        return importlib.import_module("v11_stage3_successor")
    except ModuleNotFoundError:
        return importlib.import_module("tests.v11_stage3_successor")


def expected_release() -> dict:
    """Pinned record schema; no caller-supplied authorization or environment gate."""
    content = _content()
    return {"schema": 1, "kind": "v11-stage3-v10-stage12-permanent-production-release-authority",
            "repository": "Finco-Protocol/FincoProtocol", "branch": "feat/v11-stage3-native-senior-debt",
            "content_approval": {"path": content.APPROVAL_PATH, "sha256": content.OWNER_APPROVAL_SHA256,
                                 "protected_blobs": content.V11_PROTECTED_BLOBS},
            "content_checkpoint": CONTENT_CHECKPOINT, "release_candidate": RELEASE_CANDIDATE, "release_surface":
                {path: after for path, (_before, after) in RELEASE_SURFACE.items()},
            "runtime_identities": RUNTIME_IDENTITIES, "activation": ACTIVATION,
            "activation_file": "/opt/finco_protocol/.env.native", "run_scope": RUN_SCOPE,
            "fallback": "every call the kernels do not admit is served by canonical Python in the same Run",
            "rollback": {"immediate_v11": "/var/lib/finco/native_v11_run.disabled",
                         "immediate_all_native": "/var/lib/finco/native_v10_run.disabled",
                         "permanent": "deploy/scripts/release_native.sh remove + restart"},
            "Financial": {"approved": True, "reference": OWNER_RELEASE_REFERENCE},
            "scope": "V11-Stage3a+3b-with-V10-Stage1+2-permanent-production-release",
            "stage3_activation_authorized": True, "production_enablement_authorized": True,
            "v10_stage12_production_release_authorized": True, "permanent": True,
            "activation_at": "approved deployment of the approved normal merge",
            "phased_rollout": False, "pilot_or_canary": False, "staging_enablement_authorized": False,
            "v10_reseal_authorized": False, "runtime_compilation_authorized": False, "thread_mode_native_authorized": False,
            "merge_authorized": False}


def release_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` carries exactly the owner-released V11 Stage 3 + V10 Stage 1+2 release content."""
    content = _content()
    root = repo or ROOT
    head = content._commit(ref, root)
    if head is None:
        return ["V11R_REF_UNAVAILABLE"]
    if not RELEASE_SURFACE or RELEASE_CANDIDATE["head"] is None:
        return ["V11R_CONTRACT_INCOMPLETE"]
    key = (str(root), head, OWNER_RELEASE_SHA256, OWNER_RELEASE_REFERENCE, tuple(sorted(RELEASE_SURFACE.items())),
           tuple(RELEASE_CANDIDATE.items()), tuple(CONTENT_CHECKPOINT.items()))
    if key in _CACHE:
        return list(_CACHE[key])
    bad: list[str] = []
    git, blob = content._git, content.blob
    try:
        # 1. authentic chain
        for name, anchor in (("CONTENT_CHECKPOINT", CONTENT_CHECKPOINT), ("RELEASE_CANDIDATE", RELEASE_CANDIDATE)):
            if content._commit(anchor["head"], root) != anchor["head"] or \
                    git("rev-parse", "--verify", anchor["head"] + "^{tree}", repo=root) != anchor["tree"]:
                bad.append(f"V11R_CHECKPOINT_MISSING: {name}")
        if bad:
            _CACHE[key] = tuple(bad)
            return bad
        for older, newer in ((CONTENT_CHECKPOINT["head"], RELEASE_CANDIDATE["head"]), (RELEASE_CANDIDATE["head"], head)):
            if git("merge-base", "--is-ancestor", older, newer, repo=root) is None:
                bad.append(f"V11R_ANCESTRY_INVALID: {older[:12]} -> {newer[:12]}")
        # 2. exact release surface
        for path, (before, after) in RELEASE_SURFACE.items():
            if blob(path, CONTENT_CHECKPOINT["head"], repo=root) != before:
                bad.append(f"V11R_PREDECESSOR_BLOB_MISMATCH: {path}")
            if blob(path, RELEASE_CANDIDATE["head"], repo=root) != after:
                bad.append(f"V11R_CANDIDATE_NOT_RELEASE_CONTENT: {path}")
            if blob(path, head, repo=root) != after:
                bad.append(f"V11R_RELEASE_BLOB_MISMATCH: {path}")
        if blob(RELEASE_PATH, RELEASE_CANDIDATE["head"], repo=root) is not None:
            bad.append("V11R_RELEASE_RECORD_IN_CANDIDATE")
        # 3. content record exact, runtime identities = committed manifests
        raw_content = content._show_bytes(head, content.APPROVAL_PATH, root)
        if raw_content is None or hashlib.sha256(raw_content).hexdigest() != content.OWNER_APPROVAL_SHA256:
            bad.append("V11R_CONTENT_RECORD_NOT_EXACT")
        for name, path in MANIFESTS.items():
            raw = content._show_bytes(head, path, root)
            manifest = json.loads(raw) if raw else {}
            if {k: manifest.get(k) for k in RUNTIME_IDENTITIES[name]} != RUNTIME_IDENTITIES[name]:
                bad.append(f"V11R_RUNTIME_IDENTITY_MISMATCH: {name}")
        # 4. Financial Owner release record
        raw = content._show_bytes(head, RELEASE_PATH, root)
        if OWNER_RELEASE_SHA256 is None or OWNER_RELEASE_REFERENCE is None or raw is None:
            bad.append("V11R_OWNER_RELEASE_DECISION_ABSENT")
        elif hashlib.sha256(raw).hexdigest() != OWNER_RELEASE_SHA256:
            bad.append("V11R_OWNER_RELEASE_RECORD_NOT_EXACT")
        elif json.loads(raw, object_pairs_hook=content._no_duplicates) != expected_release():
            bad.append("V11R_OWNER_RELEASE_RECORD_SCHEMA_MISMATCH")
    except Exception as exc:                                    # noqa: BLE001 - fail closed
        bad.append(f"V11R_FACTS_UNAVAILABLE: {exc!r}")
    _CACHE[key] = tuple(bad)
    return bad


def release_recognized(*, repo=None, ref: str = "HEAD") -> bool:
    return release_violations(repo=repo, ref=ref) == []


def released_surfaces(*, repo=None, ref: str = "HEAD") -> frozenset:
    """The activation-surface paths the owner released for ``ref``: exactly ``RELEASE_SURFACE`` while recognised, else nothing."""
    return frozenset(RELEASE_SURFACE) if release_recognized(repo=repo, ref=ref) else frozenset()


def states(*, repo=None, ref: str = "HEAD") -> dict:
    released = release_recognized(repo=repo, ref=ref)
    return {
        "exact_release_content_recognized": released,
        "financial_owner_release_decision": "RECORDED_NOT_AUTHENTICATED" if released else None,
        "authenticated_owner_attestation": False,
        "stage3_activation": released,
        "production_enablement": released,
        "v10_stage12_production_release": released,
        "phased_rollout": False,
        "staging_enablement": False,
        "v10_reseal": False,
        "runtime_compilation": False,
        "merge_authorized": False,
        "financial_release": False,
    }

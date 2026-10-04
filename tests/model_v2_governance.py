"""Model V2 epic scope governance contract.

Historical branch-scope guards assert "financial_engine / finco_core have ZERO
diff vs origin/main" (Finance Integrity, Radar coherence, Market bridge,
Crypto, Opus, Run Certificate, Data Center streams). That blanket assumption
cannot hold during an explicitly authorized Model V2 epic that legitimately
modifies Model financial authority.

This module replaces the false blanket assumption with an explicit, committed,
deterministic scope declaration (docs/model_v2/ACTIVE_EPIC_SCOPE.json) built
on TWO distinct concepts:

A. PERMANENT MODEL-V2 HARD DENY (code-level, immutable here)
   Other product authorities Model V2 must never alter without a completely
   separate governance decision: ``finco_radar/``, ``finco_yield/``,
   ``app/radar_rwa/``, ``app/crypto_access.py``,
   ``app/crypto_resource_access.py``. These live in
   ``PERMANENT_HARD_DENY_PREFIXES`` below and are enforced even against a
   tampered scope file. No future Model V2 workflow can authorize them by
   editing the scope JSON.

B. CURRENT EPIC-PHASE FROZEN PREFIXES (scope-file level, explicit per phase)
   Model namespaces that are frozen FOR THE CURRENT PHASE because no reviewed
   workflow has authorized them yet (for the C0 foundation state:
   ``finco_core/``, ``domain/revenue/``, ``domain/analytics/``,
   ``app/model_validation/``, ``app/verified/``). A future reviewed workflow
   authorizes work by (1) removing the specific relevant prefix from the
   current frozen set, (2) adding exact approved files, and (3) remaining
   fail-closed for every other file. No namespace-wide wildcards exist.

Fail-closed properties enforced here:

  - authority never comes from a Git branch name;
  - approved paths are exact files, never wildcards or directories;
  - the code-level permanent hard deny can never be approved, even by a
    tampered scope; the scope file's mirror of the permanent set must EQUAL
    the code set (drift fails validation);
  - approved paths cannot fall under the current frozen prefixes either —
    a workflow must first move the prefix out of the frozen set explicitly;
  - when the marker is absent or status != ACTIVE, nothing is approved and
    every historical guard behaves exactly as before.

Lifecycle: the ACTIVE scope marker exists ONLY while epic/model-saas-v2 is
under development. Before the final epic-to-main release merge it must be
DELETED or set to status RETIRED — both retirement paths pass the gate;
an ACTIVE marker at the main tip fails it (enforcement gate test).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCOPE_JSON_PATH = REPO / "docs" / "model_v2" / "ACTIVE_EPIC_SCOPE.json"

ENGINE_PREFIX = "financial_engine/"

# ── A. PERMANENT MODEL-V2 HARD DENY (code-level authority boundary) ──────────
# Other product authorities. Model V2 must not alter these without a
# completely separate governance decision. This tuple is the authority; the
# scope JSON only mirrors it (and must mirror it exactly).
PERMANENT_HARD_DENY_PREFIXES = (
    "finco_radar/",
    "finco_yield/",
    "app/radar_rwa/",
    "app/crypto_access.py",
    "app/crypto_resource_access.py",
)

# Backwards-compatible alias for readers predating Correction C.
MODEL_V2_HARD_DENY_PREFIXES = PERMANENT_HARD_DENY_PREFIXES

_SHA40 = re.compile(r"^[0-9a-f]{40}$")

_VALID_STATUSES = ("ACTIVE", "RETIRED")


# ---------------------------------------------------------------------------
# Scope loading
# ---------------------------------------------------------------------------

def load_scope_file() -> dict | None:
    """Parse the scope file, or None when absent (retired / not started)."""
    if not SCOPE_JSON_PATH.is_file():
        return None
    return json.loads(SCOPE_JSON_PATH.read_text(encoding="utf-8"))


def active_scope() -> dict | None:
    """The ACTIVE Model V2 epic scope, or None when absent/inactive.

    When None, every Model V2 scope helper approves nothing and all
    historical governance contracts behave exactly as before.
    """
    data = load_scope_file()
    if data is None or data.get("status") != "ACTIVE":
        return None
    return data


def scope_problem(data: dict) -> str | None:
    """Fail-closed structural validation. Returns the first problem or None."""
    if data.get("program") != "MODEL_V2":
        return f"program must be MODEL_V2, got {data.get('program')!r}"
    if data.get("branch") != "epic/model-saas-v2":
        return f"branch must be epic/model-saas-v2, got {data.get('branch')!r}"
    base = data.get("base_sha")
    if not isinstance(base, str) or not _SHA40.match(base):
        return f"base_sha must be a 40-hex SHA, got {base!r}"
    if data.get("status") not in _VALID_STATUSES:
        return f"status must be one of {_VALID_STATUSES}, got {data.get('status')!r}"

    # The scope file's mirror of the PERMANENT hard deny must equal the
    # code-level set exactly — documentation drift fails validation, and the
    # code-level set is what is actually enforced.
    mirrored = data.get("permanent_hard_deny_prefixes")
    if not isinstance(mirrored, list) or sorted(map(str, mirrored)) != sorted(
        PERMANENT_HARD_DENY_PREFIXES
    ):
        return (
            "permanent_hard_deny_prefixes must exactly mirror the code-level "
            f"PERMANENT_HARD_DENY_PREFIXES {sorted(PERMANENT_HARD_DENY_PREFIXES)}, "
            f"got {mirrored!r}"
        )

    frozen = data.get("current_frozen_prefixes")
    if not isinstance(frozen, list):
        return "current_frozen_prefixes must be a list"
    for entry in frozen:
        problem = _path_problem(entry, must_exist=False, allow_directory=True)
        if problem:
            return f"current_frozen_prefixes entry {entry!r}: {problem}"
        if _under_any_prefix(entry, list(PERMANENT_HARD_DENY_PREFIXES)):
            return (
                f"current_frozen_prefixes entry {entry!r} duplicates a "
                "permanent hard-deny authority"
            )

    for key in ("approved_engine_paths", "approved_support_paths"):
        paths = data.get(key)
        if not isinstance(paths, list):
            return f"{key} must be a list"
        for path in paths:
            problem = _path_problem(path, must_exist=True)
            if problem:
                return f"{key} entry {path!r}: {problem}"
            if path.startswith(ENGINE_PREFIX):
                if key == "approved_support_paths":
                    return (
                        f"{key} entry {path!r} is an engine path: engine "
                        "authorization belongs to approved_engine_paths only"
                    )
            elif key == "approved_engine_paths":
                return (
                    f"{key} entry {path!r} is not under {ENGINE_PREFIX}: only "
                    "engine files may be engine-authorized"
                )
            # A permanently denied authority can never be approved.
            if _under_any_prefix(path, list(PERMANENT_HARD_DENY_PREFIXES)):
                return (
                    f"{key} entry {path!r} falls under a PERMANENT Model V2 "
                    "hard-deny authority"
                )
            # A currently frozen prefix must be explicitly unfrozen (removed
            # from current_frozen_prefixes) before its files can be approved.
            if _under_any_prefix(path, frozen):
                return (
                    f"{key} entry {path!r} falls under a currently frozen "
                    "namespace: remove that prefix from current_frozen_prefixes "
                    "in the same reviewed scope change first"
                )
    return None


def _path_problem(path: object, *, must_exist: bool, allow_directory: bool = False) -> str | None:
    if not isinstance(path, str) or not path.strip():
        return "must be a non-empty string"
    if "*" in path:
        return "wildcards are not allowed: authority must be explicit"
    if path.startswith("/") or ".." in Path(path).parts:
        return "must be a repository-relative normalized path"
    if path.endswith("/"):
        # Approved authority is always an exact file; frozen namespaces may be
        # directory prefixes.
        if not allow_directory:
            return "directory prefixes cannot be approved: name the exact file"
        return None
    if must_exist and not (REPO / path).is_file():
        return "file does not exist in the repository"
    return None


def _under_any_prefix(path: str, prefixes: list) -> bool:
    for prefix in prefixes:
        if not isinstance(prefix, str):
            continue
        if prefix.endswith("/") and path.startswith(prefix):
            return True
        if not prefix.endswith("/") and (path == prefix or path.startswith(prefix + "/")):
            return True
    return False


# ---------------------------------------------------------------------------
# Classification helpers (used by the Model V2 tests and by the historical
# guards for their narrow reconciliation)
# ---------------------------------------------------------------------------

def _approved_paths(scope: dict) -> frozenset[str]:
    return frozenset(
        list(scope.get("approved_engine_paths", []))
        + list(scope.get("approved_support_paths", []))
    )


def approved_by_active_model_v2_scope(path: str) -> bool:
    """True only when an ACTIVE scope explicitly authorizes this exact file.

    Permanently denied product authorities are never approved — the code-level
    PERMANENT_HARD_DENY_PREFIXES check wins even over a tampered scope file
    (scope validation also rejects such a file).
    """
    scope = active_scope()
    if scope is None:
        return False
    if path.startswith(PERMANENT_HARD_DENY_PREFIXES):
        return False
    return path in _approved_paths(scope)


def changed_paths_vs_main() -> list[str]:
    """Paths changed on the Model V2 lineage, excluding main-only advances.

    Use the common ancestor of HEAD and origin/main as the comparison base.
    This keeps cumulative Model V2 changes visible to the ACTIVE scope while
    ignoring unrelated commits that landed only on main after the last
    reviewed main -> epic sync (for example Radar/Crypto/Yield work).
    Empty when git is unavailable, matching the historical guards' skip
    convention.
    """
    try:
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            capture_output=True, text=True, cwd=str(REPO), check=True,
        ).stdout.strip()
        if not base:
            base = "origin/main"
        result = subprocess.run(
            ["git", "diff", base, "--name-only"],
            capture_output=True, text=True, cwd=str(REPO), check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def authorized_engine_files() -> set[str]:
    """The exact engine files the ACTIVE scope authorizes (empty when none)."""
    scope = active_scope()
    if scope is None:
        return set()
    return set(scope.get("approved_engine_paths", []))


def model_v2_unapproved_engine_changes(changed: list[str] | None = None) -> list[str]:
    """Engine files changed vs main that the ACTIVE Model V2 scope does not
    explicitly authorize."""
    changed = changed_paths_vs_main() if changed is None else changed
    scope = active_scope()
    approved = _approved_paths(scope) if scope is not None else frozenset()
    return sorted(
        f for f in changed
        if f.startswith(ENGINE_PREFIX)
        and f not in approved
    )


def model_v2_frozen_violations(changed: list[str] | None = None) -> list[str]:
    """Changed paths under frozen namespaces: the code-level permanent hard
    deny PLUS the scope's current epic-phase frozen prefixes."""
    changed = changed_paths_vs_main() if changed is None else changed
    scope = active_scope()
    declared = list(scope.get("current_frozen_prefixes", [])) if scope else []
    prefixes = list(PERMANENT_HARD_DENY_PREFIXES) + declared
    return sorted(
        f for f in changed
        if _under_any_prefix(f, prefixes)
    )


def unauthorized_model_v2_changes(changed: list[str] | None = None) -> list[str]:
    """Every changed path the ACTIVE scope does not explicitly authorize.

    This is the fail-closed branch-wide contract: a future file added to the
    epic shows up here until the scope declaration is explicitly updated.
    """
    changed = changed_paths_vs_main() if changed is None else changed
    scope = active_scope()
    if scope is None:
        return sorted(changed)
    approved = _approved_paths(scope)
    return sorted(f for f in changed if f not in approved)


# ---------------------------------------------------------------------------
# Retirement gate (pure helper + test-facing check)
# ---------------------------------------------------------------------------

def retirement_gate_pass(*, marker_present: bool, marker_status: str | None,
                         is_main_tip: bool) -> bool:
    """MODEL_V2_EPIC_SCOPE_MARKER_RETIREMENT_GATE semantics.

    During epic development an ACTIVE marker is allowed (and required).
    At the main tip an ACTIVE marker FAILS the release gate; both retirement
    paths pass — marker DELETED, or status RETIRED.
    """
    if not is_main_tip:
        return True
    return not (marker_present and marker_status == "ACTIVE")
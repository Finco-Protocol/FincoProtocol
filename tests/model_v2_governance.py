"""Model V2 epic scope governance contract.

Historical branch-scope guards assert "financial_engine / finco_core have ZERO
diff vs origin/main" (Finance Integrity, Radar coherence, Market bridge,
Crypto, Opus, Run Certificate, Data Center streams). That blanket assumption
cannot hold during an explicitly authorized Model V2 epic that legitimately
modifies Model financial authority.

This module replaces the false blanket assumption with an explicit, committed,
deterministic scope declaration (docs/model_v2/ACTIVE_EPIC_SCOPE.json):

  - the program and its base SHA;
  - the exact engine files the epic is authorized to change (no wildcards);
  - the exact support files (app / domain / docs / tests) already reviewed;
  - the namespaces that stay STRICTLY FROZEN for Model V2.

Fail-closed properties enforced here:

  - authority never comes from a Git branch name;
  - approved paths are explicit files, never wildcards;
  - a frozen namespace can never appear in the approved lists (cross-checked
    AND hard-denied in code even if the JSON were corrupted);
  - when the marker is absent or status != ACTIVE, nothing is approved and
    every historical guard behaves exactly as before.

Lifecycle: the ACTIVE scope marker exists ONLY while epic/model-saas-v2 is
under development. It must be removed or retired before the final
epic-to-main release merge (enforced by the retirement gate test).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCOPE_JSON_PATH = REPO / "docs" / "model_v2" / "ACTIVE_EPIC_SCOPE.json"

ENGINE_PREFIX = "financial_engine/"

# Defense in depth: these namespaces can never be approved for Model V2,
# regardless of what a corrupted scope file claims. Radar/Yield/Crypto
# calculation authorities, the core, and the deferred revenue/analytics
# domains stay frozen for the epic.
MODEL_V2_HARD_DENY_PREFIXES = (
    "finco_core/",
    "domain/revenue/",
    "domain/analytics/",
    "finco_radar/",
    "finco_yield/",
    "app/radar_rwa/",
    "app/model_validation/",
    "app/verified/",
    "app/crypto_access.py",
    "app/crypto_resource_access.py",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


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
    if data.get("status") not in ("ACTIVE", "RETIRED"):
        return f"status must be ACTIVE or RETIRED, got {data.get('status')!r}"

    frozen = data.get("strictly_frozen_prefixes")
    if not isinstance(frozen, list) or not frozen:
        return "strictly_frozen_prefixes must be a non-empty list"
    for entry in frozen:
        problem = _path_problem(entry, must_exist=False, allow_directory=True)
        if problem:
            return f"strictly_frozen_prefixes entry {entry!r}: {problem}"

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
            # A frozen namespace can never be approved.
            if _under_any_prefix(path, frozen):
                return f"{key} entry {path!r} falls under a strictly frozen namespace"
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


def authorized_engine_files() -> set[str]:
    """The exact engine files the ACTIVE scope authorizes (empty when none)."""
    scope = active_scope()
    if scope is None:
        return set()
    return set(scope.get("approved_engine_paths", []))


def approved_by_active_model_v2_scope(path: str) -> bool:
    """True only when an ACTIVE scope explicitly authorizes this exact file.

    Hard-denied namespaces are never approved, even if the scope file claimed
    otherwise (the scope validation test also rejects such a file).
    """
    scope = active_scope()
    if scope is None:
        return False
    if path.startswith(MODEL_V2_HARD_DENY_PREFIXES):
        return False
    return path in _approved_paths(scope)


def changed_paths_vs_main() -> list[str]:
    """Paths changed vs origin/main (working tree included). Empty when git
    is unavailable, matching the historical guards' skip convention."""
    try:
        result = subprocess.run(
            ["git", "diff", "origin/main", "--name-only"],
            capture_output=True, text=True, cwd=str(REPO), check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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
    """Changed paths under namespaces that stay strictly frozen for Model V2.

    Hard-denied prefixes always count as violations; additionally any prefix
    the scope file declares as frozen counts, even beyond the hard list.
    """
    changed = changed_paths_vs_main() if changed is None else changed
    scope = active_scope()
    declared = tuple(scope.get("strictly_frozen_prefixes", [])) if scope else ()
    prefixes = tuple(set(MODEL_V2_HARD_DENY_PREFIXES) | set(declared))
    return sorted(
        f for f in changed
        if _under_any_prefix(f, list(prefixes))
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

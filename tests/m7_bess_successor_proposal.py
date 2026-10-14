"""Exact-content REVIEW proposal, deliberately disconnected from release guards."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "6fc77de98bc0562fb51efdbf96e1803a29b5b148"
CANDIDATE = "2fe0fa6fc4c3e12463feb2ff5c4872a5ced22451"   # Correction B candidate (Correction A candidate was 94d73ee7)
BASE_PARENTS = ("5058c6b4935168241d6923676cb32955cb903185", "2155a76bfff4acc3a4e15f7cf35012933ce1a10c")
MANIFEST_PATH = "docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json"
MANIFEST_BLOB = "b7d7f2e0467824ac96e1c68023c70b913696b42a"
RC2_MANIFEST_BLOB = "997e83e6d12c26649b751a15692f0833874bb55a"
HISTORICAL_GOVERNANCE_BLOB = "bf197d35c79a99656821eb77c441a719415ee0a4"
PROTECTED_PROPOSAL = {
    "domain/bess/__init__.py": "1905167cfb38bebb69f5f8b24f4100adf2b71f3d",
    "domain/bess/contracts.py": "1143dced2b27e3b7ed16754ccd3a17f6982d9f98",
    "domain/bess/dispatch.py": "ff2a9d2be76c2b1be308c596c42e32fe4276a9bc",
    "domain/bess/settlement.py": "e10829563e359f1766c6d8f98542e43107dac0dd",
    "domain/bess/synthetic.py": "427ad4589f9726c07e7c3723c2ff7ceed68c38ae",
    "finco_core/inputs/bess_native.py": "57ee798dbe4742c1b36acbfbc1412c90b172d3a2",
    "financial_engine/bess.py": "a07873816d97240ae02af106cd31b2135ee63316",
    "financial_engine/adapters/project_inputs.py": "14bd759a9958515a7796626f93c1bd2233d69150",
    "financial_engine/orchestrator.py": "be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03",
    "app/run_integrity/evidence.py": "89faa2c9c3d4dfddb7b8a8096888f3aa7cf83610",
    "app/run_integrity/checks.py": "25e4c3aeb25893694681b4f819c663d1e24ac3a1",
}
CSRF_PROPOSAL = {
    "app/v2/bess_candidate_router.py": "7c643d2546f21a2cc8a5c48a253a06dd0af63a9b",
    "app/v2/bess_workspace_router.py": "f1f81c9b36dae254dd2589f226ceb39f12f6f8a9",
}
CONFIG_PATH = "app/workbook/bess_config.py"
CONFIG_BLOB = "aaf21b350004107d365565e06ca6d2d70022e5b8"
# Governance-correction files (Correction B): exact content is pinned in GOVERNANCE_PINS below.
GOVERNANCE_PINS: dict[str, str] = {
    "tests/test_rc2_integration_manifest.py": "8848c9d870a2968ac3aa548d16ad40db8fbd22f6",
    "tests/test_trust_readiness_registry.py": "26253b70b096c6a6e72df242aefa11a2168db73c",
    "tests/test_trust_readiness_controls.py": "47c8e7b37a467aae140741c8d775e59b5d664be5",
}
PROPOSAL_ONLY_PATHS = frozenset({
    "tests/test_rc2_integration_manifest.py",
    "tests/test_trust_readiness_registry.py",
    "tests/test_trust_readiness_controls.py",
    "tests/m7_bess_successor_proposal.py",
    "tests/test_m7_bess_successor_proposal.py",
    "docs/model_v2/M7_BESS_SUCCESSOR_PROPOSAL.md",
})
FLAGS = {
    CONFIG_PATH: "ACTIVATION_ENABLED",
    "app/v2/bess_candidate_router.py": "CANDIDATE_UI_ENABLED",
    "domain/revenue/advanced_products.py": "ACTIVATION_ENABLED",
    "app/workbook/junior_debt_config.py": "ACTIVATION_ENABLED",
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.rstrip("\n")


def source_at(ref: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def source_blob(source: str) -> str:
    data = source.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def csrf_sites(sources: dict[str, str]) -> set[str]:
    return {p for p, s in sources.items() if not p.startswith("app/trust_readiness/")
            and re.search(r"(?<!def )validate_csrf_token\(", s)}


def collect() -> dict:
    """Observe pinned history and real files; never replace a changed observation."""
    historical_paths = git("ls-tree", "-r", "--name-only", BASE).splitlines()
    # Git scans the entire pinned tree once; only matching source files need loading.
    historical_matches = git("grep", "-l", "-F", "validate_csrf_token(", BASE,
                             "--", "app", "main_web.py").splitlines()
    historical_sources = {row.partition(":")[2]: source_at(BASE, row.partition(":")[2])
                          for row in historical_matches if row.endswith(".py")}
    current_sources = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
                       for p in [*(ROOT / "app").rglob("*.py"), ROOT / "main_web.py"]}
    for path in FLAGS:
        current_sources[path] = (ROOT / path).read_text(encoding="utf-8")
    paths = set(git("diff", "--name-only", "--no-renames", BASE, CANDIDATE).splitlines()) - PROPOSAL_ONLY_PATHS
    current_paths = set(git("diff", "--name-only", "--no-renames", BASE).splitlines())
    current_paths.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    candidate_blobs = {p: git("rev-parse", f"{CANDIDATE}:{p}") for p in paths}
    actual_blobs = {p: git("hash-object", f"--path={p}", p) for p in paths if (ROOT / p).is_file()}
    immutable_paths = set(git("ls-tree", "-r", "--name-only", BASE).splitlines()) - paths
    immutable_changed = current_paths & immutable_paths - PROPOSAL_ONLY_PATHS
    ancestry = all(subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=ROOT,
                                 capture_output=True).returncode == 0
                   for a, b in ((BASE, CANDIDATE), (CANDIDATE, "HEAD")))
    extra = {p: git("hash-object", f"--path={p}", p) for p in GOVERNANCE_PINS if (ROOT / p).is_file()}
    return {
        "actual_blobs_extra": extra,
        "base_parents": tuple(git("rev-list", "--parents", "-n", "1", BASE).split()[1:]),
        "ancestry": ancestry, "original_paths": paths, "current_paths": current_paths,
        "candidate_blobs": candidate_blobs, "actual_blobs": actual_blobs,
        "immutable_changed": immutable_changed,
        "manifest": json.loads((ROOT / MANIFEST_PATH).read_text(encoding="utf-8")),
        "historical_sources": historical_sources, "current_sources": current_sources,
        "historical_manifest": source_at(BASE, "tests/test_rc2_integration_manifest.py"),
        "historical_governance": source_at(BASE, "tests/model_v2_governance.py"),
        "current_governance": (ROOT / "tests/model_v2_governance.py").read_text(encoding="utf-8"),
    }


def violations(f: dict) -> list[str]:
    """[] means review snapshot preserved, NOT released/authorized/activated."""
    from tests.test_rc2_integration_manifest import RC2_CSRF_CALL_SITES, activation_state
    try:
        errors = []
        if tuple(f["base_parents"]) != BASE_PARENTS or f["ancestry"] is not True:
            errors.append("missing or invalid exact Git provenance")
        if (source_blob(f["historical_manifest"]) != RC2_MANIFEST_BLOB
                or source_blob(f["historical_governance"]) != HISTORICAL_GOVERNANCE_BLOB):
            errors.append("historical checkpoint source evidence changed")
        original = set(f["original_paths"])
        if len(original) != 44 or not (set(PROTECTED_PROPOSAL) | set(CSRF_PROPOSAL) | {CONFIG_PATH, MANIFEST_PATH}) <= original:
            errors.append("original 44-file candidate scope missing or changed")
        if set(f["current_paths"]) != original | PROPOSAL_ONLY_PATHS or f["immutable_changed"]:
            errors.append("unauthorized missing/additional/modified file")
        if set(f["candidate_blobs"]) != original or f["actual_blobs"] != f["candidate_blobs"]:
            errors.append("original financial/application/test snapshot changed")
        required = {**PROTECTED_PROPOSAL, **CSRF_PROPOSAL, CONFIG_PATH: CONFIG_BLOB, MANIFEST_PATH: MANIFEST_BLOB}
        if any(f["candidate_blobs"].get(p) != b for p, b in required.items()):
            errors.append("source checkpoint does not match exact proposal blobs")
        m = f["manifest"]
        if m.get("release_approved") is not False or m != {"status": "CANDIDATE_REVIEW_ONLY", "release_approved": False, "base": BASE,
                 "protected_blobs": PROTECTED_PROPOSAL}:
            errors.append("financial source evidence changed/missing or release asserted")
        if f["current_governance"] != f["historical_governance"]:
            errors.append("historical financial registry changed")
        if csrf_sites(f["historical_sources"]) != RC2_CSRF_CALL_SITES:
            errors.append("historical RC-2 CSRF inventory changed")
        if csrf_sites(f["current_sources"]) != RC2_CSRF_CALL_SITES | set(CSRF_PROPOSAL):
            errors.append("unapproved CSRF call site added/removed")
        for p, name in FLAGS.items():
            if activation_state(f["current_sources"][p], name) != "CLOSED":
                errors.append(f"{p}: activation is not literal False")
        handlers = {
            "app/v2/bess_candidate_router.py": {"validate_candidate"},
            "app/v2/bess_workspace_router.py": {"working_copy", "save"},
        }
        for p, expected in handlers.items():
            tree = ast.parse(f["current_sources"][p])
            observed = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                                and c.func.id == "validate_csrf_token" for c in ast.walk(n))}
            if observed != expected:
                errors.append(f"{p}: CSRF handler authority changed")
        return errors
    except (KeyError, TypeError, ValueError, AttributeError, SyntaxError):
        return ["source evidence incomplete or malformed"]


def current_proposal_violations() -> list[str]:
    try:
        return violations(collect())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return ["Git/source evidence unavailable; proposal fails closed"]


def current_m7_successor_valid() -> bool:
    """True only while HEAD is exactly the reviewed M7 candidate + pinned governance corrections (fail closed)."""
    try:
        facts = collect()
        for path, blob in GOVERNANCE_PINS.items():
            if facts["actual_blobs_extra"].get(path) != blob:
                return False
        return bool(GOVERNANCE_PINS) and not violations(facts)
    except Exception:  # noqa: BLE001 - any evidence failure is not an authorization
        return False

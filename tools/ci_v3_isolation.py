"""Concrete source risk inventory and fail-closed, exact-blob partition restrictions."""
from __future__ import annotations

import ast
from collections import defaultdict
import hashlib
from pathlib import Path

from tools.ci_v3_partition_plan import plan_partitions
from tools.ci_v3_schema import require, seal, validate_plan


def assess(root):
    root = Path(root)
    result = {}
    patterns = {"database": ("sqlite", "create_engine", "DATABASE_URL", ".db", ".sqlite"),
        "filesystem": ("tempfile", "Path(", "open(", "chdir", "app/data", "storage/"),
        "network-or-ports": ("requests.", "httpx.", "socket", "localhost", "127.0.0.1", "uvicorn"),
        "auth-or-tenant": ("tenant", "auth", "session_cookie", "login"),
        "native-threads": ("numpy", "scipy", "threadpool", "ProcessPool", "ThreadPool", "multiprocessing"),
        "environment": ("os.environ", "getenv", "skipif", "importorskip")}
    paths = sorted((root / "tests").rglob("*.py"))
    for path in paths:
        data = path.read_bytes(); text = data.decode("utf-8-sig")
        findings = []
        for number, line in enumerate(text.splitlines(), 1):
            for label, terms in patterns.items():
                if any(term.lower() in line.lower() for term in terms):
                    findings.append({"risk": label, "line": number, "evidence": line.strip()[:220]})
        try:
            tree = ast.parse(text)
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    findings.append({"risk": "module-global-state", "line": node.lineno,
                                     "evidence": ast.get_source_segment(text, node)[:220]})
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for deco in node.decorator_list:
                        if isinstance(deco, ast.Call) and any(k.arg == "scope" and
                            isinstance(k.value, ast.Constant) and k.value.value == "session" for k in deco.keywords):
                            findings.append({"risk": "session-fixture", "line": node.lineno, "evidence": node.name})
        except SyntaxError as exc:
            findings.append({"risk": "unparseable", "line": exc.lineno, "evidence": "manual review required"})
        result[path.relative_to(root).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest(),
            "reviewed": False, "mode": "blocked", "group": None, "findings": findings,
            "reason": "Static inventory is not isolation approval; imported helpers/fixtures and ordering require review."}
    return {"schema": 3, "kind": "ci-v3-isolation-candidate", "modules": result, "authoritative_acceptance": False}


def validate_allowed_daemon_threads(value):
    """Owner-approved background threads that may remain alive when pytest returns. Default empty = none.
    Every entry needs an exact name, a reason and the reference of the actual owner approval."""
    require(isinstance(value, dict), "allowed_daemon_threads must be an object")
    for name, entry in value.items():
        require(isinstance(name, str) and name and isinstance(entry, dict) and set(entry) == {"reason", "approval_reference"}
                and all(isinstance(entry[k], str) and entry[k].strip() for k in entry), "unapproved daemon thread entry: " + str(name))
    return value


def validate_isolation(root, inventory, isolation):
    require(isolation.get("profile") == "docker-no-network-private-workspace-v1", "unsupported isolation configuration")
    require(isolation.get("source") == inventory["source"], "stale isolation source")
    modules = isolation.get("modules", {})
    validate_allowed_daemon_threads(isolation.get("allowed_daemon_threads", {}))
    require(set(modules) == set(inventory["modules"]), "missing/foreign module isolation decisions")
    require(isolation.get("fixture_tree_reviewed") is True and isolation.get("review_reference"),
            "unreviewed shared fixtures/imports/order")
    groups = defaultdict(list)
    for name, decision in modules.items():
        require(decision.get("reviewed") is True and decision.get("rationale"), "unresolved module isolation: " + name)
        require(decision.get("sha256") == hashlib.sha256((Path(root) / name).read_bytes()).hexdigest(), "stale isolation blob: " + name)
        require(decision.get("mode") in ("runner-private", "co-locate"), "blocked/unsupported module isolation: " + name)
        require(not decision.get("requires_external_network") and not decision.get("requires_host_resource"),
                "unsupported external resource isolation: " + name)
        if decision["mode"] == "co-locate":
            require(isinstance(decision.get("group"), str) and decision["group"], "missing colocation group")
            groups[decision["group"]].append(name)
    return groups


def constrained_plan(root, inventory, policy, weights, isolation):
    require(policy["module_overlaps"] == {}, "hosted overlap execution is not admitted")
    groups = validate_isolation(root, inventory, isolation)
    original = plan_partitions(inventory, policy, weights, workers=3)
    owners = dict(original["module_workers"])
    # Preserve Phase 1 LPT for the baseline, then conservatively co-locate reviewed
    # ordering/session groups. No node is omitted to improve predicted balance.
    for group, modules in sorted(groups.items()):
        owner = owners[min(modules)]
        for module in modules:
            owners[module] = owner
    require(set(owners.values()) == {"worker-0", "worker-1", "worker-2"}, "isolation leaves an empty worker; review sequential bottleneck")
    plan = seal({**{k: v for k, v in original.items() if k != "digest"},
        "module_workers": owners, "algorithm": "phase1-lpt-plus-approved-colocation-v1",
        "isolation_digest": isolation["digest"]})
    validate_plan(plan, inventory, policy)
    return plan


def verify_colocation(plan, groups):
    for modules in groups.values():
        require(len({plan["module_workers"][m] for m in modules}) == 1, "split isolation group")

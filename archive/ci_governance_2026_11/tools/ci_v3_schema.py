"""Versioned offline CI V3 data contracts. No application imports or execution hooks."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA = 1
EVALUATOR = "ci-v3-offline/1"
DOMAINS = ("Model", "Radar", "Shared", "Cross-domain", "Governance", "F")


class ContractError(ValueError):
    """Malformed, inconsistent or untrusted evidence; never an acceptance exemption."""


def require(condition, message):
    if not condition:
        raise ContractError(message)


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def seal(value):
    require(isinstance(value, dict) and "digest" not in value, "seal expects unsigned object")
    return {**value, "digest": digest(value)}


def check_seal(value, kind):
    require(isinstance(value, dict), "document must be an object")
    require(type(value.get("schema")) is int and value["schema"] == SCHEMA, "unsupported schema")
    require(value.get("kind") == kind, "wrong document kind")
    actual = digest({k: v for k, v in value.items() if k != "digest"})
    require(value.get("digest") == actual, "document digest mismatch")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ContractError("non-finite JSON number: " + value)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_pairs,
                          parse_constant=_invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("unreadable or truncated JSON evidence") from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def worker_count(value):
    require(type(value) is int and 2 <= value <= 12, "worker count must be an integer from 2 through 12")
    return value


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, label + " must be an integer")


def hash_value(value, label, length=64):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value),
            label + " must be a hexadecimal digest")


def source(value):
    require(isinstance(value, dict) and set(value) == {"head", "tree"}, "source shape")
    hash_value(value["head"], "HEAD", 40)
    hash_value(value["tree"], "tree", 40)


def module_path(value):
    require(isinstance(value, str) and value.startswith("tests/") and value.endswith(".py")
            and "\\" not in value and "::" not in value, "invalid module path")
    require(all(x not in ("", ".", "..") for x in value.split("/"))
            and not PurePosixPath(value).is_absolute(), "unsafe module path")


def unique_strings(values, label, allow_empty=False):
    require(isinstance(values, list) and (allow_empty or bool(values)), label + " must be a list")
    require(all(isinstance(x, str) and x for x in values), label + " contains invalid strings")
    require(len(set(values)) == len(values), label + " contains duplicates")


def skip_key(record):
    require(isinstance(record, dict) and set(record) == {"nodeid", "reason"}, "collection skip shape")
    require(all(isinstance(record[k], str) and record[k] for k in record), "invalid collection skip")
    return canonical_bytes(record).decode("utf-8")


def skip_counter(records):
    require(isinstance(records, list), "collection skips must be a list")
    return Counter(skip_key(r) for r in records)


def validate_inventory(inventory):
    check_seal(inventory, "ci-v3-inventory")
    require(inventory.get("authority") == "offline-prototype", "inventory has no CI authority")
    source(inventory.get("source"))
    require(isinstance(inventory.get("repository"), str) and inventory["repository"], "repository missing")
    nodes = inventory.get("nodes")
    require(isinstance(nodes, list) and nodes, "empty inventory")
    ids = []
    for item in nodes:
        require(isinstance(item, dict), "invalid node record")
        node, module = item.get("nodeid"), item.get("module")
        module_path(module)
        require(isinstance(node, str) and node.startswith(module + "::")
                and len(node) > len(module) + 2, "node/module mismatch")
        require(item.get("fixture_unit") == module, "module fixture unit changed")
        require(item.get("execution_owner") == "plan.module_workers", "missing execution ownership binding")
        require(item.get("domain") in DOMAINS, "unclassified node")
        require(item.get("confidence") in ("candidate-static", "unresolved", "reviewed"), "confidence missing")
        require(item["domain"] != "F" or item["confidence"] == "unresolved", "F cannot claim reviewed ownership")
        require(item.get("mandatory") is True, "mandatory node disabled")
        require(item.get("optional_overlap_ownership") == "policy.module_overlaps", "overlap ownership missing")
        require(isinstance(item.get("obligations"), list) and "full-regression" in item["obligations"],
                "regression obligation missing")
        require(isinstance(item.get("dependency_evidence"), str) and item["dependency_evidence"],
                "dependency evidence reference missing")
        ids.append(node)
    unique_strings(ids, "inventory nodes")
    require(ids == sorted(ids), "inventory nodes not canonical")
    modules = inventory.get("modules")
    require(isinstance(modules, dict) and set(modules) == {n["module"] for n in nodes}, "module metadata mismatch")
    for name, item in modules.items():
        require(isinstance(item, dict), "invalid module metadata")
        require(item.get("isolation_review") == "unproven", "prototype cannot certify module isolation")
        require(isinstance(item.get("dependency_evidence"), dict), "module dependency evidence missing")
    skip_counter(inventory.get("collection_skips"))
    return {n["nodeid"]: n for n in nodes}


def validate_policy(policy, inventory):
    check_seal(policy, "ci-v3-policy")
    require(policy.get("inventory_digest") == inventory["digest"], "policy inventory mismatch")
    require(policy.get("authority") == "offline-prototype", "policy has no CI authority")
    require(policy.get("new_nodes") == "fail-closed", "unknown test policy must fail closed")
    require(policy.get("selective_execution") is False, "selective execution forbidden")
    nonpass = policy.get("allowed_nonpass")
    require(isinstance(nonpass, dict), "nonpass policy missing")
    known = {n["nodeid"] for n in inventory["nodes"]}
    require(set(nonpass) <= known, "foreign nonpass authorization")
    for rec in nonpass.values():
        require(isinstance(rec, dict) and set(rec) == {"status", "reason"}, "nonpass record shape")
        require(rec["status"] in ("skipped", "xfail") and isinstance(rec["reason"], str)
                and rec["reason"], "invalid nonpass authorization")
    overlaps = policy.get("module_overlaps")
    require(isinstance(overlaps, dict) and set(overlaps) <= set(inventory["modules"]), "unknown overlap module")
    for workers in overlaps.values():
        unique_strings(workers, "overlap workers")


def reconcile_collection(inventory, collection):
    """A separate fresh collection is mandatory; neither counts nor stale plans suffice."""
    require(isinstance(collection, dict), "collection missing")
    require(collection.get("source") == inventory["source"], "collection source mismatch")
    require(collection.get("complete") is True and collection.get("errors") == [], "collection incomplete/error")
    values = collection.get("nodes")
    unique_strings(values, "fresh collection nodes")
    require(Counter(values) == Counter(n["nodeid"] for n in inventory["nodes"]),
            "fresh collection inventory mismatch; new/removed tests require reconciliation")
    require(skip_counter(collection.get("skips")) == skip_counter(inventory["collection_skips"]),
            "collection skip mismatch")


def validate_plan(plan, inventory, policy):
    """Structural checker shared by producer/consumer; never calls the planner algorithm."""
    check_seal(plan, "ci-v3-plan")
    require(plan.get("inventory_digest") == inventory["digest"], "plan inventory mismatch")
    require(plan.get("policy_digest") == policy["digest"], "plan policy mismatch")
    require(plan.get("source") == inventory["source"], "plan source mismatch")
    require(plan.get("authority") == "offline-prototype", "plan has no CI authority")
    worker_count(plan.get("worker_count"))
    ids = ["worker-%d" % i for i in range(plan["worker_count"])]
    assignment = plan.get("module_workers")
    require(isinstance(assignment, dict) and set(assignment) == set(inventory["modules"]),
            "plan module assignment incomplete")
    require(all(w in ids for w in assignment.values()), "unknown execution worker")
    for module, extra in policy["module_overlaps"].items():
        require(all(w in ids and w != assignment[module] for w in extra), "invalid overlap owner")
    return ids

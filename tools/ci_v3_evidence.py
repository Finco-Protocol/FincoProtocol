"""Exact-source evidence contract for Phase 3B.

`pack` stores one probe run in a compact, reproducible form. `build` writes a sealed manifest that binds the exact Git
HEAD/tree of the executed source, the image identity and dependency manifests, the complete collected-node inventory,
every attempt and its JUnit set, the proposals and the controller/verifier file hashes. `verify` recomputes everything
and, by default, also proves the published commit differs from the executed source only by evidence/documentation paths.
`verify --historical` keeps an old manifest independently verifiable against its exact historical source (the commit must
be an ancestor of the published HEAD) but never lets it apply to a different source: it reports every changed path by class
(financial source, application, general tests, ...) and `applies_to_published_head` stays false unless only permitted
evidence paths changed. The allow-lists are never widened for financial or application paths. Historical attempts are
carried but explicitly marked; they can never be presented as executed on the evidence commit."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

from tools.ci_v3_classify import load_attempts
from tools.ci_v3_schema import ContractError, check_seal, read_json, require, seal, write_json

EVIDENCE_DIR = "docs/ci_v3/phase3c/evidence/"
ALLOWED_FOLLOWUP = (EVIDENCE_DIR, "docs/ci_v3/phase3c/README.md", "docs/ci_v3/phase3b/README.md")
ALLOWED_README = ("docs/ci_v3/phase3c/README.md", "docs/ci_v3/phase3b/README.md")
EVIDENCE_DIR_PATTERN = re.compile(r"docs/ci_v3/phase3[a-z]/[a-z0-9-]*evidence[a-z0-9-]*/")
HASHED_TOOLS = "tools/ci_v3_*.py"
# Path classes used to describe a source difference. None of the product classes is ever allowed to inherit evidence.
PRODUCT_CLASSES = {"financial-source": ("financial_engine/", "finco_core/"),
                   "application-source": ("app/", "domain/", "finco_protocol/", "finco_radar/", "finco_yield/", "finco_app/", "utils/", "main_api.py", "main_mcp.py", "main_web.py"),
                   "workflow": (".github/",), "dependencies": ("requirements", "constraints.txt", "pyproject.toml", "pytest.ini")}
# Evidence executed on an EARLIER tree may be carried to a later tree only if the later tree differs by CI-V3-internal
# additions and documentation. Files that run or describe the execution (probe, container, adapter, schema) never qualify.
CARRY_ADD_PREFIXES = ("tools/ci_v3_", "tests/test_ci_v3_", "docs/ci_v3/")
CARRY_MODIFY = ("docs/ci_v3/", "tests/test_ci_v3_")
CARRY_MODIFY_TOOLS = {f"tools/ci_v3_{name}.py" for name in ("classify", "evidence", "proposal", "nonpass", "environment", "calibrate", "container_validate", "real_child", "hosted_controller", "isolation")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def change_class(path):
    """Describe a changed path. Used only for reporting; permission comes from the explicit allow-lists above."""
    if path.startswith(("tools/ci_v3_", "tests/test_ci_v3_")) or path.startswith("docs/ci_v3/"):
        return "ci-v3-internal"
    for name, prefixes in PRODUCT_CLASSES.items():
        if path.startswith(prefixes):
            return name
    if path.startswith("tests/"):
        return "general-tests"
    if path.startswith("tools/"):
        return "other-tools"
    if path.startswith("docs/"):
        return "other-docs"
    return "other"


def allowed_followup(manifest):
    """Evidence directory of this manifest (older manifests used the Phase 3C directory) plus the two README files."""
    directory = manifest.get("evidence_dir", EVIDENCE_DIR)
    require(EVIDENCE_DIR_PATTERN.fullmatch(directory), "unsupported evidence directory: " + str(directory))
    return (directory, *ALLOWED_README)


def applicability(repo, manifest, published="HEAD"):
    """Does evidence executed at manifest.source still describe `published`? Only if nothing but permitted evidence paths differ."""
    head = manifest["source"]["head"]
    allowed = allowed_followup(manifest)
    rows = [l.split("\t") for l in git(repo, "diff", "--name-status", "--no-renames", head, published).splitlines() if l]
    unreviewed = [[status, path, change_class(path)] for status, path in rows if not path.startswith(allowed)]
    by_class = {}
    for _, _, klass in unreviewed:
        by_class[klass] = by_class.get(klass, 0) + 1
    return {"applies_to_published_head": not unreviewed, "changed_paths": len(rows), "unreviewed_changes": unreviewed,
            "unreviewed_change_classes": dict(sorted(by_class.items()))}


def pack_attempt(run_dir, destination):
    """Deterministic packed form: meta.json, merged results.jsonl, junit.tar.xz (sorted, zero mtime)."""
    run_dir, destination = Path(run_dir), Path(destination)
    meta, records = load_attempts(run_dir)
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "meta.json", meta)
    ordered = sorted(records, key=lambda r: (r["module"], r.get("tag") or ""))
    (destination / "results.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in ordered), encoding="utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as tar:
        for xml in sorted(run_dir.glob("lane-*/*.xml"), key=lambda p: p.name):
            data = xml.read_bytes(); info = tarfile.TarInfo(xml.name); info.size = len(data); info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    (destination / "junit.tar.xz").write_bytes(buffer.getvalue())
    return attempt_record(destination)


def attempt_record(directory):
    directory = Path(directory)
    meta = read_json(directory / "meta.json")
    rows = [json.loads(l) for l in (directory / "results.jsonl").read_text().splitlines()]
    with tarfile.open(directory / "junit.tar.xz") as tar:
        members = {m.name: sha(tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()}
    declared = {r["junit_sha256"] for r in rows if r.get("junit_sha256")}
    require(declared <= set(members.values()), "attempt results reference JUnit that is not in the archive: " + str(directory))
    return {"label": meta["label"], "kind": meta["kind"], "concurrency": meta["concurrency"], "image_id": meta["image_id"],
            "tree": meta["tree"], "historical": bool(meta.get("historical")), "results": len(rows),
            "results_sha256": sha((directory / "results.jsonl").read_bytes()), "junit_archive_sha256": sha((directory / "junit.tar.xz").read_bytes()),
            "junit_files": len(members), "junit_set_sha256": sha(json.dumps(sorted(members.items())).encode())}


def carry_forward_changes(repo, from_tree, to_tree):
    """Changed paths between two trees; raises unless every change keeps earlier execution evidence valid."""
    rows = [l.split("\t") for l in git(repo, "diff-tree", "-r", "--name-status", "--no-renames", from_tree, to_tree).splitlines() if l]
    changes = []
    for status, path in rows:
        added_ok = status == "A" and path.startswith(CARRY_ADD_PREFIXES)
        modified_ok = status == "M" and (path.startswith(CARRY_MODIFY) or path in CARRY_MODIFY_TOOLS)
        require(added_ok or modified_ok, f"change {status} {path} invalidates evidence executed on tree {from_tree[:12]}")
        changes.append([status, path])
    return changes


def modules_executed_at_tree(evidence, tree):
    """Modules with a non-historical attempt executed at exactly this tree."""
    found = set()
    for directory in sorted((Path(evidence) / "attempts").iterdir()):
        meta = read_json(directory / "meta.json")
        if meta["tree"] == tree and not meta.get("historical"):
            found |= {json.loads(l)["module"] for l in (directory / "results.jsonl").read_text().splitlines()}
    return found


def ci_v3_modules_required(carried, inventory_modules):
    """CI V3 self-tests exercise the tools. If any CI V3 tool changed after an attempt's tree, every
    tests/test_ci_v3_* module must have been executed at the final tree instead of being carried forward."""
    if not any(path.startswith("tools/ci_v3_") for changes in carried.values() for _, path in changes):
        return []
    return sorted(m for m in inventory_modules if m.startswith("tests/test_ci_v3_"))


def tool_hashes(repo):
    return {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in sorted(Path(repo).glob(HASHED_TOOLS))}


def relative_dir(repo, directory):
    value = Path(directory).resolve().relative_to(Path(repo).resolve()).as_posix().rstrip("/") + "/"
    require(EVIDENCE_DIR_PATTERN.fullmatch(value), "unsupported evidence directory: " + value)
    return value


def build(repo, evidence, image_dir, inventory_path, nodes_archive, extra, historical_manifests=()):
    repo, evidence = Path(repo), Path(evidence)
    evidence_dir = relative_dir(repo, evidence)
    require(not git(repo, "status", "--porcelain", "--untracked-files=all", "--", ".", ":(exclude)" + evidence_dir.rstrip("/")),
            "evidence requires a clean committed source tree (only the evidence directory may hold uncommitted files)")
    source = {"head": git(repo, "rev-parse", "HEAD"), "tree": git(repo, "rev-parse", "HEAD^{tree}")}
    image = read_json(Path(image_dir) / "image.json")
    inventory = read_json(inventory_path)
    ids = sorted(n["nodeid"] for n in inventory["nodes"])
    with tarfile.open(nodes_archive) as tar:
        require(tar.extractfile("node-ids.txt").read().decode().splitlines() == ids, "node-id archive differs from the inventory")
    require(inventory["source"] == source, "inventory was collected from a different source tree")
    attempts = [attempt_record(p) for p in sorted((evidence / "attempts").iterdir())]
    carried = {}
    for item in attempts:
        if not item["historical"]:
            require(item["image_id"] == image["image_id"], "attempt not executed on the evidence image: " + item["label"])
            if item["tree"] != source["tree"]:
                carried[item["tree"]] = carry_forward_changes(repo, item["tree"], source["tree"])
    required = ci_v3_modules_required(carried, {n["nodeid"].split("::", 1)[0] for n in inventory["nodes"]})
    missing = sorted(set(required) - modules_executed_at_tree(evidence, source["tree"]))
    require(not missing, "CI V3 tools changed after earlier evidence; these self-tests must run at the final tree: " + ", ".join(missing[:5]))
    files = {name: sha((evidence / name).read_bytes()) for name in extra}
    historical = []
    for manifest_file in historical_manifests:      # earlier executions stay verifiable but are never assumed to apply to this source
        old = read_json(manifest_file)
        verify(repo, Path(manifest_file).parent, manifest_file, historical=True, published=source["head"])
        info = applicability(repo, old, source["head"])
        historical.append({"evidence_dir": relative_dir(repo, Path(manifest_file).parent), "manifest_digest": old["digest"], "source": old["source"],
                           "applies_to_this_source": info["applies_to_published_head"],
                           "unreviewed_change_classes": info["unreviewed_change_classes"], "unreviewed_changed_paths": len(info["unreviewed_changes"])})
    return seal({"schema": 1, "kind": "ci-v3-evidence-manifest", "evidence_dir": evidence_dir, "historical_evidence": historical,
        "source": source, "image": image,
        "image_files_sha256": {p.name: sha(p.read_bytes()) for p in sorted(Path(image_dir).iterdir()) if p.is_file()},
        "inventory": {"digest": inventory["digest"], "nodes": len(ids), "node_ids_sha256": sha("\n".join(ids).encode()),
                      "node_ids_archive_sha256": sha(Path(nodes_archive).read_bytes()), "collection_skips": len(read_json(extra_path(evidence, extra, "collection-skips.json")))},
        "controller_and_verifier_sha256": tool_hashes(repo), "attempts": attempts, "carried_forward_from": carried,
        "ci_v3_modules_required_at_final_tree": required, "files_sha256": files,
        "follow_up_policy": {"allowed_paths": [evidence_dir, *ALLOWED_README],
                             "meaning": "The published commit may differ from `source` only by these paths; test execution evidence is bound to `source`."}})


def extra_path(evidence, extra, name):
    require(name in extra, "missing " + name)
    return Path(evidence) / name


def verify(repo, evidence, manifest_path=None, historical=False, published="HEAD"):
    """Integrity of the evidence against its exact executed source. Strict mode (default) additionally requires that the
    published commit differs only by permitted evidence paths. Historical mode requires the executed commit to be an
    ancestor of the published commit and reports (never allows) every other difference."""
    repo, evidence = Path(repo), Path(evidence)
    manifest = read_json(manifest_path or evidence / "manifest.json")
    check_seal(manifest, "ci-v3-evidence-manifest")
    head = manifest["source"]["head"]
    require(git(repo, "rev-parse", head + "^{tree}") == manifest["source"]["tree"], "executed source commit/tree mismatch")
    info = applicability(repo, manifest, published)
    changed = [p for p in git(repo, "diff", "--name-only", head, published).splitlines() if p]
    if historical:
        require(subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", head, published], capture_output=True).returncode == 0,
                "historical executed source is not an ancestor of the published commit")
    else:
        stray = [path for _, path, _ in info["unreviewed_changes"]]
        require(not stray, "published commit differs from the executed source outside evidence paths: " + ", ".join(stray[:5]))
    # Controller/verifier code is what produced the evidence: it must still be the executed bytes.
    for name, expected in manifest["controller_and_verifier_sha256"].items():
        blob = subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:{name}"])
        require(sha(blob) == expected, "tool hash differs from executed source: " + name)
    for name, expected in manifest["files_sha256"].items():
        require(sha((evidence / name).read_bytes()) == expected, "evidence file changed: " + name)
    seen = []
    for recorded in manifest["attempts"]:
        actual = attempt_record(evidence / "attempts" / recorded["label"])
        require(actual == recorded, "attempt evidence changed: " + recorded["label"])
        if not recorded["historical"]:
            require(recorded["image_id"] == manifest["image"]["image_id"], "non-historical attempt image")
            if recorded["tree"] != manifest["source"]["tree"]:
                require(carry_forward_changes(repo, recorded["tree"], manifest["source"]["tree"]) == manifest["carried_forward_from"].get(recorded["tree"]),
                        "carried-forward evidence no longer valid: " + recorded["label"])
        seen.append(recorded["label"])
    require(len(seen) == len(set(seen)), "duplicate attempt label")
    missing = sorted(set(manifest["ci_v3_modules_required_at_final_tree"]) - modules_executed_at_tree(evidence, manifest["source"]["tree"]))
    require(not missing, "required CI V3 self-test not executed at the final tree: " + ", ".join(missing[:5]))
    return {"verified": True, "mode": "historical" if historical else "current", "attempts": seen, "published_head_differs_from_source_by": changed,
            "applies_to_published_head": info["applies_to_published_head"], "unreviewed_change_classes": info["unreviewed_change_classes"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack"); pack.add_argument("--run", required=True); pack.add_argument("--output", required=True)
    make = sub.add_parser("build")
    for name in ("repo", "evidence", "image-dir", "inventory", "node-ids"):
        make.add_argument("--" + name, required=True)
    make.add_argument("--file", action="append", default=[]); make.add_argument("--historical-manifest", action="append", default=[])
    check = sub.add_parser("verify"); check.add_argument("--repo", required=True); check.add_argument("--evidence", required=True)
    check.add_argument("--historical", action="store_true", help="verify against the exact historical source without requiring it to apply to HEAD")
    check.add_argument("--require-current", action="store_true", help="with --historical: fail unless the evidence still applies to the published HEAD")
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            print(json.dumps(pack_attempt(args.run, args.output)))
        elif args.command == "build":
            manifest = build(args.repo, args.evidence, args.image_dir, args.inventory, args.node_ids, args.file, args.historical_manifest)
            write_json(Path(args.evidence) / "manifest.json", manifest); print(manifest["digest"])
        else:
            result = verify(args.repo, args.evidence, historical=args.historical)
            print(json.dumps(result))
            if args.require_current and not result["applies_to_published_head"]:
                print("CI_V3_EVIDENCE_REJECTED: historical evidence does not apply to the published HEAD"); return 1
    except (ContractError, OSError, subprocess.CalledProcessError, KeyError) as exc:
        print("CI_V3_EVIDENCE_REJECTED: " + str(exc)); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

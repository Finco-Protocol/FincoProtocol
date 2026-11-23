"""Qualify an exact proposed release snapshot without granting release authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import v11_stage3_release_authority as historical
import v11_stage3_successor as content

ROOT = Path(__file__).resolve().parents[1]
RECORD = "docs/model_v11/v11-stage3-release-successor-candidate.json"
RECORD_SHA256 = "bdd0e579aed5988ecabbc92f3c50aa276e0a7004809d9ac306fcc0b324703536"
HISTORICAL_RELEASE = "93c549e160772acd8258c26556bd46ff9ca29156"
F01 = ".github/workflows/finval_f01_acceptance.yml"
SCOPE = (*content.PROTECTED_PREFIXES, F01)


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _entries(root, ref, paths):
    entries = {}
    for line in _git(root, "ls-tree", "-r", "-z", ref, "--", *paths).split(b"\0"):
        if line:
            entry, path = line.split(b"\t", 1)
            mode, kind, blob = entry.decode().split()
            entries[path.decode()] = (mode, kind, blob)
    return entries


def _entry(entry):
    return (entry["mode"], "blob", entry["blob"]) if entry else None


def _changes(root, old, new, *scope):
    return set(_git(root, "diff", "--name-only", "--no-renames", old, new, "--", *scope).decode().splitlines())


def _activation_paths(root, ref):
    raw = _git(root, "grep", "-l", "-e", "native_v11", "-e", "Stage3Config", "-e", "stage3_run",
               ref, "--", *content.ACTIVATION_SURFACES)
    return {line.split(":", 1)[1] for line in raw.decode().splitlines()}


def candidate_violations(*, repo=None, ref="HEAD"):
    """Verify the proposal's record, provenance and source. The record cannot approve a release."""
    root = Path(repo) if repo is not None else ROOT
    try:
        head = _git(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
        raw = _git(root, "show", f"{head}:{RECORD}")
        if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
            return ["V11_SUCCESSOR_RECORD_NOT_EXACT"]
        record_mode = _entries(root, head, [RECORD]).get(RECORD)
        if record_mode is None or record_mode[:2] != ("100644", "blob"):
            return ["V11_SUCCESSOR_RECORD_MODE"]
        record = json.loads(raw)
        anchors = record["anchors"]
        chain = [anchors[name] for name in (
            "historical_release", "fin_v2_r1", "fin_v2_3", "fin_v2_integration", "f01_workflow", "candidate",
        )]
        for anchor in chain:
            tree = _git(root, "rev-parse", "--verify", anchor["commit"] + "^{tree}").decode().strip()
            if tree != anchor["tree"]:
                return ["V11_SUCCESSOR_TREE_MISMATCH"]
        refs = [anchor["commit"] for anchor in chain] + [head]
        for before, after in zip(refs, refs[1:]):
            _git(root, "merge-base", "--is-ancestor", before, after)
        old = HISTORICAL_RELEASE
        if refs[0] != old:
            return ["V11_SUCCESSOR_HISTORICAL_CHECKPOINT"]
        candidate = refs[-2]
        paths = record["paths"]
        if _changes(root, old, candidate, *SCOPE) != set(paths):
            return ["V11_SUCCESSOR_MAPPING_GAP"]
        if _changes(root, candidate, head, *SCOPE):
            return ["V11_SUCCESSOR_SOURCE_DRIFT"]
        old_entries = _entries(root, old, sorted(paths))
        new_entries = _entries(root, candidate, sorted(paths))
        for label in ("fin_v2_integration", "f01_workflow"):
            source = anchors[label]["commit"]
            source_entries = _entries(root, source, sorted(paths))
            for path, facts in paths.items():
                if (path == F01) != (label == "f01_workflow"):
                    continue
                if (facts["source"] != source or old_entries.get(path) != _entry(facts["historical"])
                        or new_entries.get(path) != _entry(facts["accepted"])
                        or source_entries.get(path) != new_entries.get(path)):
                    return ["V11_SUCCESSOR_PATH_PROVENANCE: " + path]
        authority_paths = [historical.RELEASE_PATH, content.APPROVAL_PATH, *historical.RELEASE_SURFACE, *historical.MANIFESTS.values()]
        if _changes(root, old, head, *authority_paths) or historical.release_violations(repo=root, ref=old):
            return ["V11_SUCCESSOR_HISTORICAL_RELEASE_CHANGED"]
        if _activation_paths(root, head) != _activation_paths(root, old) | {F01}:
            return ["V11_SUCCESSOR_UNREVIEWED_ACTIVATION_SURFACE"]
        return []
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, KeyError, TypeError):
        return ["V11_SUCCESSOR_FACTS_UNAVAILABLE"]
